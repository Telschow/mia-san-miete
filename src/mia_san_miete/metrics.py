"""Funnel and reply metrics computed from the audit tables. Content-free by construction."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from statistics import median

from .db import Database
from .replies import CATEGORIES, POSITIVE


@dataclass
class Metrics:
    statuses: dict[str, int] = field(default_factory=dict)
    sent: int = 0
    replied: int = 0                   # sent messages with at least one non-auto reply
    positive: int = 0                  # viewing invite or documents request
    by_category: dict[str, int] = field(default_factory=dict)
    by_source: dict[str, dict[str, int]] = field(default_factory=dict)
    by_score_band: dict[str, dict[str, int]] = field(default_factory=dict)
    by_origin: dict[str, dict[str, int]] = field(default_factory=dict)   # llm vs template
    median_reply_hours: float | None = None

    @property
    def reply_rate(self) -> float | None:
        return self.replied / self.sent if self.sent else None

    @property
    def positive_rate(self) -> float | None:
        return self.positive / self.sent if self.sent else None


def _band(score: float | None) -> str:
    if score is None:
        return "unknown"
    low = int(score // 5) * 5
    return f"{low}-{low + 4}"


def _bump(table: dict[str, dict[str, int]], key: str, sent: int, replied: int, positive: int):
    row = table.setdefault(key, {"sent": 0, "replied": 0, "positive": 0})
    row["sent"] += sent
    row["replied"] += replied
    row["positive"] += positive


def compute_metrics(db: Database, since_iso: str | None = None) -> Metrics:
    m = Metrics()
    since = since_iso or ""
    for r in db.conn.execute(
        "SELECT status, COUNT(*) n FROM actions WHERE created_at >= ? GROUP BY status", (since,)
    ):
        m.statuses[r["status"]] = r["n"]
    m.by_category = dict.fromkeys(CATEGORIES, 0)

    sent_rows = db.conn.execute(
        "SELECT id, source, score, used_llm, created_at FROM actions"
        " WHERE status = 'sent' AND created_at >= ?", (since,)
    ).fetchall()
    m.sent = len(sent_rows)
    delays: list[float] = []
    for a in sent_rows:
        replies = db.conn.execute(
            "SELECT category, received_at FROM replies WHERE action_id = ? ORDER BY received_at",
            (a["id"],),
        ).fetchall()
        real = [r for r in replies if r["category"] != "auto_reply"]
        for r in replies:
            m.by_category[r["category"]] += 1
        replied = 1 if real else 0
        positive = 1 if any(r["category"] in POSITIVE for r in real) else 0
        m.replied += replied
        m.positive += positive
        if real:
            sent_at = datetime.fromisoformat(a["created_at"])
            first = datetime.fromisoformat(real[0]["received_at"])
            delays.append((first - sent_at).total_seconds() / 3600)
        _bump(m.by_source, a["source"], 1, replied, positive)
        _bump(m.by_score_band, _band(a["score"]), 1, replied, positive)
        origin = "unknown" if a["used_llm"] is None else ("llm" if a["used_llm"] else "template")
        _bump(m.by_origin, origin, 1, replied, positive)
    m.median_reply_hours = round(median(delays), 1) if delays else None
    return m


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def format_metrics(m: Metrics) -> str:
    lines = ["Funnel (actions by status):"]
    lines += [f"  {k}: {v}" for k, v in sorted(m.statuses.items())] or ["  none"]
    lines += [
        "",
        (f"Sent: {m.sent}   replied: {m.replied} ({_pct(m.reply_rate)})   "
         f"positive: {m.positive} ({_pct(m.positive_rate)})"),
        ("Median hours to first reply: "
         + ("n/a" if m.median_reply_hours is None else str(m.median_reply_hours))),
        ("Replies by category: "
         + ", ".join(f"{k}={v}" for k, v in m.by_category.items())),
    ]
    for title, table in (("source", m.by_source), ("score band", m.by_score_band),
                         ("message origin", m.by_origin)):
        lines += ["", f"By {title} (sent / replied / positive):"]
        lines += [f"  {k}: {v['sent']} / {v['replied']} / {v['positive']}"
                  for k, v in sorted(table.items())] or ["  none"]
    if m.sent < 30:
        lines += ["", "Note: fewer than 30 sent messages, so rates are noisy."]
    return "\n".join(lines)
