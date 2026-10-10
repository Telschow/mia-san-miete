"""Turn gates and score into an action. This module never sends anything."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from .config import SendPolicy
from .gates import GateResult, Verdict


class Decision(StrEnum):
    AUTO_SEND = "auto_send"
    NEEDS_APPROVAL = "needs_approval"
    SKIP = "skip"


def current_threshold(policy: SendPolicy, live_since: date, today: date) -> int:
    """Auto-send threshold after the loosening schedule, never below the floor."""
    steps = max(0, (today - live_since).days) // policy.loosen.every_days
    loosened = max(policy.loosen.floor, policy.min_score - steps * policy.loosen.step_points)
    return min(policy.min_score, loosened)   # the schedule only ever lowers the bar


def decide(
    gates: GateResult, score: float, policy: SendPolicy, threshold: int, platform: str
) -> Decision:
    """Hard gates always win; the threshold schedule can never override them.

    AUTO_SEND is returned only for a clean pass. A REVIEW verdict (missing or borderline
    data) always goes to the approval queue, whatever the score. In shadow mode the caller
    logs AUTO_SEND as "would send" instead of sending.
    """
    if gates.verdict is Verdict.REJECT:
        return Decision.SKIP
    if gates.verdict is Verdict.REVIEW:
        return Decision.NEEDS_APPROVAL
    if (
        policy.enabled
        and platform in policy.platform_allow_list
        and score >= threshold
    ):
        return Decision.AUTO_SEND
    return Decision.NEEDS_APPROVAL
