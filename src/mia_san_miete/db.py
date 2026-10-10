"""SQLite store with forward-only migrations and canonical (cross-portal) grouping."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .dedup import is_same_flat
from .models import Listing

MIGRATIONS: list[str] = [
    """
    CREATE TABLE canonicals (
        id INTEGER PRIMARY KEY,
        created_at TEXT NOT NULL
    );
    CREATE TABLE listings (
        id INTEGER PRIMARY KEY,
        canonical_id INTEGER NOT NULL REFERENCES canonicals(id),
        source TEXT NOT NULL,
        source_id TEXT NOT NULL,
        data TEXT NOT NULL,
        seen_at TEXT NOT NULL,
        UNIQUE (source, source_id)
    );
    CREATE INDEX idx_listings_canonical ON listings(canonical_id);
    CREATE INDEX idx_listings_seen ON listings(seen_at);
    """,
    """
    CREATE TABLE travel_cache (
        key TEXT PRIMARY KEY,
        minutes REAL NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE actions (
        id INTEGER PRIMARY KEY,
        canonical_id INTEGER NOT NULL REFERENCES canonicals(id),
        source TEXT NOT NULL,
        source_id TEXT NOT NULL,
        status TEXT NOT NULL,
        mode TEXT NOT NULL,
        score REAL,
        score_version TEXT,
        breakdown TEXT,
        reasons TEXT,
        template_version TEXT,
        used_llm INTEGER,
        model TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX idx_actions_status_time ON actions(status, created_at);
    CREATE INDEX idx_actions_canonical ON actions(canonical_id);
    """,
    """
    CREATE TABLE outbound (
        action_id INTEGER PRIMARY KEY REFERENCES actions(id),
        message_id TEXT,
        recipient_hash TEXT
    );
    CREATE INDEX idx_outbound_message ON outbound(message_id);
    CREATE INDEX idx_outbound_recipient ON outbound(recipient_hash);
    CREATE TABLE replies (
        id INTEGER PRIMARY KEY,
        action_id INTEGER NOT NULL REFERENCES actions(id),
        imap_uid TEXT NOT NULL UNIQUE,
        category TEXT NOT NULL,
        matched_by TEXT NOT NULL,
        received_at TEXT NOT NULL
    );
    CREATE INDEX idx_replies_action ON replies(action_id);
    """,
    """
    CREATE TABLE drafts (
        action_id INTEGER PRIMARY KEY REFERENCES actions(id),
        subject TEXT NOT NULL,
        body TEXT NOT NULL,
        language TEXT NOT NULL,
        created_at TEXT NOT NULL,
        resolution TEXT,
        resolved_at TEXT
    );
    CREATE TABLE kv (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
    """
    ALTER TABLE drafts ADD COLUMN kind TEXT NOT NULL DEFAULT 'application';
    ALTER TABLE drafts ADD COLUMN reply_to TEXT;
    ALTER TABLE drafts ADD COLUMN in_reply_to TEXT;
    CREATE TABLE auto_replies (
        id INTEGER PRIMARY KEY,
        action_id INTEGER NOT NULL REFERENCES actions(id),
        reply_uid TEXT NOT NULL,
        status TEXT NOT NULL,
        slot_start TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX idx_auto_replies_action ON auto_replies(action_id);
    """,
    """
    ALTER TABLE actions ADD COLUMN commute TEXT;
    """,
    """
    CREATE TABLE geo_cache (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
]


@dataclass(frozen=True)
class IngestResult:
    listing_id: int
    canonical_id: int
    is_new_flat: bool        # first time this physical flat was seen on any portal
    is_new_listing: bool     # first time this (source, source_id) was seen


class Database:
    def __init__(self, path: str | Path = ":memory:", check_same_thread: bool = True) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=check_same_thread)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def _migrate(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        for i in range(version, len(MIGRATIONS)):
            with self.conn:
                self.conn.executescript(MIGRATIONS[i])
                self.conn.execute(f"PRAGMA user_version = {i + 1}")

    def close(self) -> None:
        self.conn.close()

    def ingest(self, listing: Listing, lookback: int = 500) -> IngestResult:
        row = self.conn.execute(
            "SELECT id, canonical_id FROM listings WHERE source = ? AND source_id = ?",
            (listing.source, listing.source_id),
        ).fetchone()
        if row:
            return IngestResult(row["id"], row["canonical_id"], False, False)

        canonical_id = self._find_canonical(listing, lookback)
        is_new_flat = canonical_id is None
        with self.conn:
            if canonical_id is None:
                cur = self.conn.execute(
                    "INSERT INTO canonicals (created_at) VALUES (?)",
                    (listing.seen_at.isoformat(),),
                )
                canonical_id = int(cur.lastrowid)
            cur = self.conn.execute(
                "INSERT INTO listings (canonical_id, source, source_id, data, seen_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    canonical_id,
                    listing.source,
                    listing.source_id,
                    listing.model_dump_json(),
                    listing.seen_at.isoformat(),
                ),
            )
        return IngestResult(int(cur.lastrowid), canonical_id, is_new_flat, True)

    def _find_canonical(self, listing: Listing, lookback: int) -> int | None:
        rows = self.conn.execute(
            "SELECT canonical_id, data FROM listings ORDER BY id DESC LIMIT ?", (lookback,)
        ).fetchall()
        for r in rows:
            if is_same_flat(listing, Listing.model_validate_json(r["data"])):
                return int(r["canonical_id"])
        return None

    def cache_get(self, key: str) -> float | None:
        row = self.conn.execute(
            "SELECT minutes FROM travel_cache WHERE key = ?", (key,)
        ).fetchone()
        return None if row is None else float(row["minutes"])

    def cache_set(self, key: str, minutes: float) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO travel_cache (key, minutes, created_at)"
                " VALUES (?, ?, datetime('now'))",
                (key, minutes),
            )

    def geo_get(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM geo_cache WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def geo_set(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO geo_cache (key, value, created_at)"
                " VALUES (?, ?, datetime('now'))", (key, value))

    def record_action(
        self,
        *,
        canonical_id: int,
        source: str,
        source_id: str,
        status: str,
        mode: str,
        created_at: str,
        score: float | None = None,
        score_version: str | None = None,
        breakdown: str | None = None,
        reasons: str | None = None,
        template_version: str | None = None,
        used_llm: bool | None = None,
        model: str | None = None,
        commute: str | None = None,
    ) -> int:
        """Content-free audit row: ids, score, reasons and metadata; never message bodies."""
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO actions (canonical_id, source, source_id, status, mode, score,"
                " score_version, breakdown, reasons, template_version, used_llm, model,"
                " created_at, commute) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (canonical_id, source, source_id, status, mode, score, score_version,
                 breakdown, reasons, template_version,
                 None if used_llm is None else int(used_llm), model, created_at, commute),
            )
        return int(cur.lastrowid)

    def record_outbound(
        self, action_id: int, message_id: str | None, recipient_hash: str | None
    ) -> None:
        """Link a sent action to its Message-ID and a hash of the recipient (no address)."""
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO outbound (action_id, message_id, recipient_hash)"
                " VALUES (?, ?, ?)",
                (action_id, message_id, recipient_hash),
            )

    def find_sent_action(
        self, message_ids: list[str], recipient_hash: str | None
    ) -> tuple[int, str] | None:
        """Match a reply to a sent action: by Message-ID first, then by recipient hash."""
        for mid in message_ids:
            row = self.conn.execute(
                "SELECT action_id FROM outbound WHERE message_id = ?", (mid,)
            ).fetchone()
            if row:
                return int(row["action_id"]), "message_id"
        if recipient_hash:
            row = self.conn.execute(
                "SELECT o.action_id FROM outbound o JOIN actions a ON a.id = o.action_id"
                " WHERE o.recipient_hash = ? AND a.status = 'sent'"
                " ORDER BY a.id DESC LIMIT 1",
                (recipient_hash,),
            ).fetchone()
            if row:
                return int(row["action_id"]), "sender"
        return None

    def record_reply(
        self, action_id: int, imap_uid: str, category: str, matched_by: str, received_at: str
    ) -> bool:
        """Store one reply (category only, never text). False if this uid was already seen."""
        with self.conn:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO replies (action_id, imap_uid, category, matched_by,"
                " received_at) VALUES (?, ?, ?, ?, ?)",
                (action_id, imap_uid, category, matched_by, received_at),
            )
        return cur.rowcount == 1

    def reply_uid_seen(self, imap_uid: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM replies WHERE imap_uid = ?", (imap_uid,)
        ).fetchone() is not None

    def count_actions(self, status: str, since_iso: str, source: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM actions WHERE status = ? AND created_at >= ?"
        args: list[str] = [status, since_iso]
        if source:
            sql += " AND source = ?"
            args.append(source)
        return int(self.conn.execute(sql, args).fetchone()[0])

    def first_action_date(self) -> str | None:
        """Date (YYYY-MM-DD, UTC) of the oldest audit row; anchors the threshold schedule."""
        row = self.conn.execute("SELECT MIN(created_at) FROM actions").fetchone()
        return row[0][:10] if row and row[0] else None

    def has_action(self, canonical_id: int, status: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM actions WHERE canonical_id = ? AND status = ? LIMIT 1",
            (canonical_id, status),
        ).fetchone()
        return row is not None

    def consecutive_failures(self, source: str) -> int:
        rows = self.conn.execute(
            "SELECT status FROM actions WHERE source = ? AND status IN ('sent', 'failed')"
            " ORDER BY id DESC LIMIT 10",
            (source,),
        ).fetchall()
        n = 0
        for r in rows:
            if r["status"] != "failed":
                break
            n += 1
        return n

    def listings_for(self, canonical_id: int) -> list[Listing]:
        rows = self.conn.execute(
            "SELECT data FROM listings WHERE canonical_id = ? ORDER BY id", (canonical_id,)
        ).fetchall()
        return [Listing.model_validate_json(r["data"]) for r in rows]

    # --- approval queue: drafts live apart from the content-free audit table ---

    def save_draft(
        self, action_id: int, subject: str, body: str, language: str, created_at: str,
        kind: str = "application", reply_to: str | None = None,
        in_reply_to: str | None = None,
    ) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO drafts (action_id, subject, body, language, created_at,"
                " kind, reply_to, in_reply_to) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (action_id, subject, body, language, created_at, kind, reply_to, in_reply_to),
            )

    def get_draft(self, action_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM drafts WHERE action_id = ?", (action_id,)
        ).fetchone()

    def pending_drafts(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT d.*, a.canonical_id, a.source, a.source_id, a.score, a.breakdown,"
            " a.reasons, a.status FROM drafts d JOIN actions a ON a.id = d.action_id"
            " WHERE d.resolution IS NULL ORDER BY a.score DESC, d.created_at"
        ).fetchall()

    def resolve_draft(self, action_id: int, resolution: str, now_iso: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE drafts SET resolution = ?, resolved_at = ?, reply_to = NULL,"
                " in_reply_to = NULL WHERE action_id = ? AND resolution IS NULL",
                (resolution, now_iso, action_id),
            )

    def purge_drafts(self, before_iso: str) -> int:
        """Delete message text once it is old or resolved long ago (retention)."""
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM drafts WHERE created_at < ?", (before_iso,)
            )
        return cur.rowcount

    def action_row(self, action_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()

    def listing_for_action(self, action_id: int) -> Listing | None:
        row = self.conn.execute(
            "SELECT l.data FROM listings l JOIN actions a ON a.source = l.source"
            " AND a.source_id = l.source_id WHERE a.id = ?", (action_id,)
        ).fetchone()
        return Listing.model_validate_json(row["data"]) if row else None

    # --- automatic replies (content-free audit: ids, status and the agreed slot only)

    def record_auto_reply(
        self, action_id: int, reply_uid: str, status: str, slot_start: str | None, now_iso: str
    ) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO auto_replies (action_id, reply_uid, status, slot_start, created_at)"
                " VALUES (?, ?, ?, ?, ?)", (action_id, reply_uid, status, slot_start, now_iso))

    def count_auto_replies(self, status: str, since_iso: str) -> int:
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM auto_replies WHERE status = ? AND created_at >= ?",
            (status, since_iso)).fetchone()[0])

    def thread_auto_replies(self, action_id: int, status: str) -> int:
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM auto_replies WHERE action_id = ? AND status = ?",
            (action_id, status)).fetchone()[0])

    def kv_get(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def kv_set(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, value)
            )
