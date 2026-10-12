"""Heartbeat and failure alerts so a silent breakage does not go unnoticed."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from .db import Database
from .notify import Notifier
from .pipeline import RunStats

FAILURE_ALERT_COOLDOWN = timedelta(hours=1)


class Health:
    def __init__(
        self, db: Database, notifier: Notifier | None, heartbeat_hours: int,
        silence_hours: int | None, clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.db, self.notifier = db, notifier
        self.heartbeat = timedelta(hours=heartbeat_hours)
        self.silence = timedelta(hours=silence_hours) if silence_hours else None
        self.clock = clock

    def _get(self, key: str) -> datetime | None:
        raw = self.db.kv_get(key)
        return datetime.fromisoformat(raw) if raw else None

    def _set(self, key: str, when: datetime) -> None:
        self.db.kv_set(key, when.isoformat(timespec="seconds"))

    def _send(self, title: str, body: str) -> None:
        if self.notifier:
            try:
                self.notifier.send(title, body)
            except OSError:
                pass   # an unreachable notifier must never break the cycle

    def after_cycle(self, stats: RunStats) -> None:
        now = self.clock()
        if stats.failed_providers:
            self.failure("source failed: " + ", ".join(stats.failed_providers))
        if stats.failed_listings:
            self.failure(f"processing failed for {len(stats.failed_listings)} new flat(s); "
                         "see the log")
        if stats.fetched:
            self._set("last_listing_seen", now)
        elif self._get("last_listing_seen") is None:
            self._set("last_listing_seen", now)   # start the silence clock on first run

        seen = self._get("last_listing_seen")
        last_silence = self._get("last_silence_alert")
        if (self.silence and seen and now - seen >= self.silence
                and (last_silence is None or now - last_silence >= self.silence)):
            hours = int((now - seen).total_seconds() // 3600)
            self._send("Mia: no new listings", f"No listings read for {hours} hours. "
                       "Check the alert inbox and the portal alert settings.")
            self._set("last_silence_alert", now)

        last = self._get("last_heartbeat")
        if last is None:
            self._set("last_heartbeat", now)
        elif now - last >= self.heartbeat:
            counts = self._counts_since(last)
            self._send("Mia: alive", ", ".join(f"{k} {v}" for k, v in counts.items()))
            self._set("last_heartbeat", now)

    def failure(self, reason: str) -> None:
        now = self.clock()
        last = self._get("last_failure_alert")
        if last is not None and now - last < FAILURE_ALERT_COOLDOWN:
            return
        self._send("Mia: cycle problem", reason)
        self._set("last_failure_alert", now)

    def _counts_since(self, since: datetime) -> dict[str, int]:
        iso = since.astimezone(UTC).isoformat(timespec="seconds")
        rows = self.db.conn.execute(
            "SELECT status, COUNT(*) n FROM actions WHERE created_at >= ? GROUP BY status", (iso,)
        )
        counts = {r["status"]: r["n"] for r in rows}
        return {
            "processed": sum(counts.values()),
            "queued": counts.get("queued", 0),
            "would_send": counts.get("shadow_would_send", 0),
            "sent": counts.get("sent", 0),
        }
