"""Builds the dashboard's live objects from the files on disk, and rebuilds them after a save."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from ..config import Config, load_config
from ..db import Database
from ..profile import load_profile
from ..queue import ApprovalQueue
from ..runner import build_dispatcher, build_reply_tools
from .settings import SettingsStore


def make_loader(config_path: Path, profile_path: Path, store: SettingsStore):
    """Return load() -> (config, database, queue). The database connection is kept across
    reloads; the env file is overlaid on the process environment so saved credentials apply
    without a restart."""
    cell: dict[str, Database] = {}

    def load() -> tuple[Config, Database, ApprovalQueue | None]:
        cfg = load_config(config_path)
        db = cell.get("db") or Database(cfg.storage.db_path)
        cell["db"] = db
        env = store.env()
        try:
            profile = load_profile(profile_path)
        except (OSError, ValidationError, ValueError):
            return cfg, db, None
        _, responder = build_reply_tools(cfg, profile, db, env, None)
        return cfg, db, ApprovalQueue(db, build_dispatcher(cfg, db, env), profile, responder)

    return load
