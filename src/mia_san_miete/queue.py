"""Approval queue: review, edit, approve or skip drafts the policy did not send itself."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta

from .db import Database
from .dispatcher import Dispatcher, Outcome, ScoreFields
from .messaging.generator import Draft
from .messaging.validator import validate_message
from .profile import Profile

DRAFT_RETENTION_DAYS = 30


class QueueError(Exception):
    """The requested queue action is not possible; the message is safe to show."""


class ApprovalQueue:
    def __init__(self, db: Database, dispatcher: Dispatcher, profile: Profile,
                 responder=None) -> None:
        self.db, self.dispatcher, self.profile = db, dispatcher, profile
        self.responder = responder

    def items(self) -> list[dict]:
        out = []
        for d in self.db.pending_drafts():
            listing = self.db.listing_for_action(d["action_id"])
            out.append({
                "action_id": d["action_id"],
                "status": d["status"],
                "kind": d["kind"],
                "source": d["source"],
                "score": d["score"],
                "reasons": json.loads(d["reasons"] or "[]"),
                "breakdown": json.loads(d["breakdown"] or "{}"),
                "subject": d["subject"],
                "body": d["body"],
                "language": d["language"],
                "queued_at": d["created_at"],
                "listing": listing.model_dump(mode="json") if listing else None,
            })
        return out

    def approve(
        self, action_id: int, now: datetime | None = None, body: str | None = None,
        subject: str | None = None,
    ) -> Outcome:
        now = now or datetime.now(UTC)
        d = self.db.get_draft(action_id)
        if d is None or d["resolution"] is not None:
            raise QueueError("no pending draft with that id")
        if d["kind"] == "reply":
            return self._approve_reply(d, now, body, subject)
        if body is not None and body != d["body"]:
            problems = validate_message(body, d["language"], self.profile)
            if problems:
                raise QueueError("edited message rejected: " + "; ".join(problems))
        final_body = body if body is not None else d["body"]
        final_subject = subject if subject is not None else d["subject"]
        action = self.db.action_row(action_id)
        listing = self.db.listing_for_action(action_id)
        if action is None or listing is None:
            raise QueueError("listing for this draft is missing")
        draft = Draft(final_subject, final_body, d["language"], action["template_version"] or "",
                      bool(action["used_llm"]), action["model"], None)
        fields = ScoreFields(action["score"], action["score_version"], action["breakdown"],
                             action["reasons"], action["commute"])
        outcome = self.dispatcher.approve(
            listing=listing, canonical_id=action["canonical_id"], draft=draft, now=now,
            fields=fields,
        )
        if outcome.status == "sent":
            self.db.resolve_draft(action_id, "approved", now.isoformat(timespec="seconds"))
        return outcome

    def _approve_reply(self, d, now: datetime, body: str | None, subject: str | None) -> Outcome:
        if self.responder is None:
            raise QueueError("automatic replies are not configured")
        final = body if body is not None else d["body"]
        if re.search(r"[{}\[\]]|\bNone\b", final) or not final.strip():
            raise QueueError("edited reply rejected: placeholder or empty text")
        out = self.responder.send_approved(d, now, subject if subject is not None else d["subject"],
                                           final)
        if out.status == "sent":
            self.db.resolve_draft(d["action_id"], "approved", now.isoformat(timespec="seconds"))
        return out

    def mark_sent(self, action_id: int, now: datetime | None = None) -> Outcome:
        """The user sent the message themselves: record it and clear the card."""
        now = now or datetime.now(UTC)
        d = self.db.get_draft(action_id)
        if d is None or d["resolution"] is not None:
            raise QueueError("no pending draft with that id")
        iso = now.isoformat(timespec="seconds")
        if d["kind"] == "reply":
            self.db.resolve_draft(action_id, "sent_manually", iso)
            return Outcome("sent_manually", action_id)
        action, listing = self.db.action_row(action_id), self.db.listing_for_action(action_id)
        if action is None or listing is None:
            raise QueueError("listing for this draft is missing")
        draft = Draft(d["subject"], d["body"], d["language"], action["template_version"] or "",
                      bool(action["used_llm"]), action["model"], None)
        fields = ScoreFields(action["score"], action["score_version"], action["breakdown"],
                             action["reasons"], action["commute"])
        out = self.dispatcher.record_manual_send(
            listing=listing, canonical_id=action["canonical_id"], draft=draft, now=now, fields=fields)
        self.db.resolve_draft(action_id, "sent_manually", iso)
        return out

    def skip(self, action_id: int, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        d = self.db.get_draft(action_id)
        if d is None or d["resolution"] is not None:
            raise QueueError("no pending draft with that id")
        self.db.resolve_draft(action_id, "skipped", now.isoformat(timespec="seconds"))

    def purge(self, now: datetime | None = None) -> int:
        cutoff = (now or datetime.now(UTC)) - timedelta(days=DRAFT_RETENTION_DAYS)
        return self.db.purge_drafts(cutoff.isoformat(timespec="seconds"))
