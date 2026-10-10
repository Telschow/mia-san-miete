"""Enforces the send policy and writes the audit trail. The only place that calls senders."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from .config import SendPolicy
from .db import Database
from .decision import Decision
from .geo.area import AreaResult
from .geo.travel import CommuteResult
from .messaging.generator import Draft
from .models import Listing
from .replies import recipient_hash
from .scoring import ScoreResult
from .senders.base import Sender, SendError

log = logging.getLogger(__name__)
BERLIN = ZoneInfo("Europe/Berlin")
MAX_CONSECUTIVE_FAILURES = 3
# Guards that leave the flat reviewable later; a duplicate is not worth reviewing.
QUEUEABLE_BLOCKS = ("blocked_kill_switch", "blocked_quiet_hours", "blocked_daily_cap",
                    "blocked_platform_cap", "blocked_platform_failures", "blocked_no_sender")


@dataclass(frozen=True)
class Outcome:
    status: str     # sent | shadow_would_send | failed | blocked_* | queued | skipped
    action_id: int | None = None


@dataclass(frozen=True)
class ScoreFields:
    score: float | None
    version: str | None
    breakdown: str | None
    reasons: str | None
    commute: str | None = None      # JSON of the commute times used for this decision


def commute_json(c: CommuteResult | None, area: AreaResult | None = None) -> str | None:
    """Commute and location figures as stored with a decision: numbers and a public stop name,
    never addresses."""
    if c is None and area is None:
        return None
    data: dict = {"times": c.times if c else {}, "estimated": c.estimated if c else False}
    if area is not None:
        data["area"] = asdict(area)
    return json.dumps(data)


def in_quiet_hours(spec: str | None, now: datetime) -> bool:
    if not spec:
        return False
    start_s, end_s = spec.split("-")
    start = time(*(int(x) for x in start_s.split(":")))
    end = time(*(int(x) for x in end_s.split(":")))
    t = now.astimezone(BERLIN).time()
    return (start <= t < end) if start <= end else (t >= start or t < end)


def start_of_day_utc_iso(now: datetime) -> str:
    """Berlin midnight of `now`'s day, as a UTC ISO string comparable with stored rows."""
    local = now.astimezone(BERLIN)
    midnight = datetime.combine(local.date(), time(0, 0), tzinfo=BERLIN)
    return midnight.astimezone(UTC).isoformat(timespec="seconds")


class Dispatcher:
    def __init__(
        self, policy: SendPolicy, db: Database, senders: dict[str, Sender]
    ) -> None:
        self.policy, self.db, self.senders = policy, db, senders

    def kill_switch_active(self) -> bool:
        return self.policy.kill_switch_file.exists()

    def _record(
        self, listing: Listing, canonical_id: int, status: str, now: datetime,
        fields: ScoreFields, draft: Draft | None, message_id: str | None = None,
        keep_draft: bool = True,
    ) -> Outcome:
        iso = now.astimezone(UTC).isoformat(timespec="seconds")
        action_id = self.db.record_action(
            canonical_id=canonical_id,
            source=listing.source,
            source_id=listing.source_id,
            status=status,
            mode=self.policy.mode,
            created_at=iso,
            score=fields.score,
            score_version=fields.version,
            breakdown=fields.breakdown,
            reasons=fields.reasons,
            commute=fields.commute,
            template_version=draft.template_version if draft else None,
            used_llm=draft.used_llm if draft else None,
            model=draft.model if draft else None,
        )
        if status == "sent":
            self.db.record_outbound(action_id, message_id, recipient_hash(listing.contact_email))
        elif draft and keep_draft and (status == "queued" or status in QUEUEABLE_BLOCKS):
            # message text for review lives in `drafts`, never in the audit row
            self.db.save_draft(action_id, draft.subject, draft.body, draft.language, iso)
        return Outcome(status, action_id)

    def _guard(self, listing: Listing, canonical_id: int, now: datetime) -> str | None:
        """First guard that blocks an automatic or approved send, else None."""
        if self.kill_switch_active():
            return "blocked_kill_switch"
        if self.db.has_action(canonical_id, "sent") or self.db.has_action(
                canonical_id, "sent_manually"):
            return "blocked_duplicate"
        if in_quiet_hours(self.policy.quiet_hours, now):
            return "blocked_quiet_hours"
        since = start_of_day_utc_iso(now)
        if self.db.count_actions("sent", since) >= self.policy.daily_cap:
            return "blocked_daily_cap"
        if self.db.count_actions("sent", since, listing.source) >= self.policy.per_platform_daily_cap:
            return "blocked_platform_cap"
        if self.db.consecutive_failures(listing.source) >= MAX_CONSECUTIVE_FAILURES:
            return "blocked_platform_failures"
        return None

    def _deliver(self, listing: Listing, draft: Draft) -> tuple[str, str | None]:
        sender = self.senders.get(listing.source) or self.senders.get("email")
        if sender is None:
            return "blocked_no_sender", None
        try:
            return "sent", sender.send(listing, draft)
        except SendError as exc:
            log.warning("send failed for %s: %s", listing.source, exc)
            return "failed", None

    def handle(
        self,
        *,
        listing: Listing,
        canonical_id: int,
        decision: Decision,
        score: ScoreResult,
        reasons: list[str],
        draft: Draft | None,
        now: datetime,
        commute: CommuteResult | None = None,
        area: AreaResult | None = None,
    ) -> Outcome:
        fields = ScoreFields(score.score, score.version, json.dumps(score.breakdown),
                             json.dumps(reasons), commute_json(commute, area))

        def record(status: str, message_id: str | None = None) -> Outcome:
            return self._record(listing, canonical_id, status, now, fields, draft, message_id)

        if decision is Decision.SKIP:
            return record("skipped")
        if decision is Decision.NEEDS_APPROVAL or draft is None:
            return record("queued")

        # AUTO_SEND from here on: every guard below downgrades to the approval queue.
        blocked = self._guard(listing, canonical_id, now)
        if blocked:
            return record(blocked)
        if self.policy.mode == "shadow":
            return record("shadow_would_send")
        status, message_id = self._deliver(listing, draft)
        return record(status, message_id)

    def record_manual_send(
        self, *, listing: Listing, canonical_id: int, draft: Draft, now: datetime, fields: ScoreFields
    ) -> Outcome:
        """The user sent this message themselves (for example through the portal). Nothing is
        sent here; the audit trail and the duplicate guard learn about it."""
        return self._record(listing, canonical_id, "sent_manually", now, fields, draft,
                            keep_draft=False)

    def approve(
        self, *, listing: Listing, canonical_id: int, draft: Draft, now: datetime,
        fields: ScoreFields,
    ) -> Outcome:
        """A human approved this draft. Every guard still applies; shadow mode never sends."""
        blocked = self._guard(listing, canonical_id, now)
        if blocked:
            return self._record(listing, canonical_id, blocked, now, fields, draft,
                                keep_draft=False)
        if self.policy.mode == "shadow":
            return Outcome("not_sent_shadow_mode")
        status, message_id = self._deliver(listing, draft)
        return self._record(listing, canonical_id, status, now, fields, draft, message_id,
                            keep_draft=False)
