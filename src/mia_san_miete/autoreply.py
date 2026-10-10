"""Opt-in automatic answer to a landlord's viewing offer.

Default off, shadow before live. A slot that fits your weekly availability windows is
confirmed; anything else (no readable slot, clash, guard hit) becomes a drafted proposal in the
review queue instead. The reply text is a fixed template that states only your own availability
and contact details; nothing a landlord wrote is ever copied into it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Protocol

from .config import AutoReply, SendPolicy
from .db import Database
from .dispatcher import Outcome, in_quiet_hours, start_of_day_utc_iso
from .llm_reply import LocalReplyLlm
from .messaging.validator import detect_language
from .notify import Notifier
from .profile import Profile
from .replies import IncomingMail, strip_quotes
from .scheduling import best_slot, compose_reply, fmt_slot, parse_slots, propose_slots
from .senders.base import SendError

log = logging.getLogger(__name__)
BULK = {"bulk", "list", "junk", "auto_reply"}


class ReplySender(Protocol):
    def send_reply(self, to: str, subject: str, body: str, in_reply_to: str) -> None: ...


def _subject(original: str) -> str:
    return original if original.lower().startswith(("re:", "aw:")) else f"Re: {original}"


class AutoResponder:
    def __init__(
        self, db: Database, cfg: AutoReply, policy: SendPolicy, profile: Profile,
        sender: ReplySender | None, llm: LocalReplyLlm | None = None,
        notifier: Notifier | None = None, own_address: str | None = None,
    ) -> None:
        self.db, self.cfg, self.policy, self.profile = db, cfg, policy, profile
        self.sender, self.llm, self.notifier = sender, llm, notifier
        self.own = (own_address or "").lower()

    # ---------------------------------------------------------------- helpers
    def _notify(self, title: str, body: str) -> None:
        if self.notifier:
            try:
                self.notifier.send(title, body)
            except OSError:
                pass

    def _guard(self, action_id: int | None, now: datetime) -> str | None:
        if self.policy.kill_switch_file.exists():
            return "blocked_kill_switch"
        if in_quiet_hours(self.policy.quiet_hours, now):
            return "blocked_quiet_hours"
        if (action_id is not None and self.db.thread_auto_replies(action_id, "sent")
                >= self.cfg.max_replies_per_thread):
            return "blocked_thread_cap"
        if self.db.count_auto_replies("sent", start_of_day_utc_iso(now)) >= self.cfg.daily_cap:
            return "blocked_daily_cap"
        return None

    def _risky(self, mail: IncomingMail) -> bool:
        """Never answer machines, mailing lists or ourselves (reply loops)."""
        h = {k.lower(): v.lower() for k, v in mail.headers.items()}
        return (h.get("auto-submitted", "no") != "no" or h.get("precedence", "") in BULK
                or "list-id" in h or "x-autoreply" in h
                or (bool(self.own) and mail.from_address.lower() == self.own))

    def _names(self) -> str:
        return " und ".join(f"{a.first_name} {a.last_name}" for a in self.profile.applicants)

    def _record(self, action_id: int, uid: str, status: str, slot: datetime | None,
                now: datetime) -> None:
        self.db.record_auto_reply(action_id, uid, status, slot.isoformat(timespec="minutes")
                                  if slot else None, now.astimezone(UTC).isoformat(timespec="seconds"))

    # ---------------------------------------------------------------- main entry
    def handle(self, mail: IncomingMail, action_id: int, category: str, now: datetime) -> str:
        if not self.cfg.enabled or category != "viewing_invite":
            return "ignored"
        if self._risky(mail):
            self._record(action_id, mail.uid, "skipped_automated", None, now)
            return "skipped_automated"
        avail = self.profile.availability
        if avail is None:
            self._notify("Mia: viewing offered", "Add `availability` to your profile to enable "
                         "automatic replies. Reply yourself for now.")
            self._record(action_id, mail.uid, "no_availability_configured", None, now)
            return "no_availability_configured"

        text = strip_quotes(mail.body)
        slots = parse_slots(text, mail.received_at, self.cfg.horizon_days)
        if not slots and self.llm is not None:
            slots = self.llm.extract_slots(text, mail.received_at, self.cfg.horizon_days)
        chosen = best_slot(slots, avail, now)
        lang = detect_language(text)
        subject = _subject(mail.subject or "Anfrage")
        phone = self.profile.contact.phone

        if chosen is not None:
            blocked = self._guard(action_id, now)
            if blocked is None:
                body = compose_reply("confirm", lang, self._names(), phone, chosen)
                if self.cfg.mode == "shadow":
                    self._record(action_id, mail.uid, "shadow_would_confirm", chosen, now)
                    return "shadow_would_confirm"
                if self.sender is None:
                    blocked = "blocked_no_sender"
                else:
                    try:
                        self.sender.send_reply(mail.from_address, subject, body, mail.uid)
                    except SendError:
                        self._record(action_id, mail.uid, "failed", chosen, now)
                        self._notify("Mia: reply failed", "Could not send the viewing confirmation.")
                        return "failed"
                    self._record(action_id, mail.uid, "sent", chosen, now)
                    self._notify("Mia: viewing confirmed", fmt_slot(chosen, lang))
                    return "sent"
            self._record(action_id, mail.uid, blocked or "blocked", chosen, now)

        return self._queue_proposal(mail, action_id, lang, subject, now)

    def _queue_proposal(self, mail: IncomingMail, action_id: int, lang: str, subject: str,
                        now: datetime) -> str:
        avail = self.profile.availability
        assert avail is not None
        proposals = propose_slots(avail, now)
        if not proposals:
            self._notify("Mia: viewing offered", "No free time in your availability; reply yourself.")
            self._record(action_id, mail.uid, "no_free_time", None, now)
            return "no_free_time"
        body = compose_reply("propose", lang, self._names(), self.profile.contact.phone, None,
                             proposals)
        original = self.db.action_row(action_id)
        listing = self.db.listing_for_action(action_id)
        if original is None or listing is None:
            return "ignored"
        iso = now.astimezone(UTC).isoformat(timespec="seconds")
        new_id = self.db.record_action(
            canonical_id=original["canonical_id"], source=listing.source,
            source_id=listing.source_id, status="reply_queued", mode=self.cfg.mode,
            created_at=iso, score=original["score"], score_version=original["score_version"])
        self.db.save_draft(new_id, subject, body, lang, iso, kind="reply",
                           reply_to=mail.from_address, in_reply_to=mail.uid)
        self._record(action_id, mail.uid, "queued", None, now)
        self._notify("Mia: viewing offered", "A reply with your free times is waiting in the "
                     "review queue.")
        return "queued"

    # ---------------------------------------------------------------- queue approval
    def send_approved(self, draft, now: datetime, subject: str, body: str) -> Outcome:
        """A human approved a drafted reply. Guards apply; shadow mode never sends."""
        action = self.db.action_row(draft["action_id"])
        guard = self._guard(None, now)
        if guard:
            return Outcome(guard)
        if self.cfg.mode == "shadow":
            return Outcome("not_sent_shadow_mode")
        if self.sender is None or not draft["reply_to"]:
            return Outcome("blocked_no_sender")
        try:
            self.sender.send_reply(draft["reply_to"], subject, body, draft["in_reply_to"] or "")
        except SendError:
            return Outcome("failed")
        if action is not None:
            self._record(action["id"], draft["in_reply_to"] or "", "sent", None, now)
        return Outcome("sent", draft["action_id"])
