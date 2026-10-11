"""One discovery-to-dispatch cycle: read the source, process each new flat, audit it."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime

from .autoreply import AutoResponder
from .config import Config
from .db import Database
from .dispatcher import Dispatcher
from .engine import Engine
from .geo.area import CachedGeo, SafeGeo, needs_geo
from .geo.motis import DEFAULT_BASE_URL, MotisCarRouter, make_pt_router
from .geo.travel import CachedRouter, GoogleRoutesRouter, Router, ScaledRouter
from .llm_reply import LocalReplyLlm
from .messaging.llm import LlmClient, OpeningWriter
from .notify import Notifier, NtfyNotifier
from .pipeline import RunStats, run_once
from .profile import Profile
from .providers.base import Provider
from .senders.base import Sender
from .senders.email import EmailSender

log = logging.getLogger(__name__)


def _why(exc: Exception) -> str:
    """The error type, and for an HTTP error its status and the service's own short message
    (never the request, so no API key can appear)."""
    code = getattr(exc, "code", None)
    if code is None:
        return type(exc).__name__
    detail = ""
    try:
        body = json.loads(exc.read(2000))            # type: ignore[attr-defined]
        err = body.get("error", {}) if isinstance(body, dict) else {}
        detail = f" {err.get('status', '')}: {str(err.get('message', ''))[:160]}".rstrip(": ")
    except Exception:  # noqa: BLE001 - the body is only a courtesy
        pass
    return f"{type(exc).__name__} {code}{detail}"


class SafeRouter:
    """A routing outage must not lose a flat: unknown commute sends it to the approval queue."""

    def __init__(self, inner: Router) -> None:
        self.inner, self.mode = inner, inner.mode

    def minutes(self, origin, destination, arrive_by):
        try:
            return self.inner.minutes(origin, destination, arrive_by)
        except Exception as exc:  # noqa: BLE001 - any routing failure degrades to unknown
            log.warning("%s routing failed: %s", self.mode, _why(exc))
            return None


class NoRouter:
    mode = "car"

    def minutes(self, origin, destination, arrive_by):
        return None


def build_dispatcher(cfg: Config, db: Database, env: Mapping[str, str]) -> Dispatcher:
    senders: dict[str, Sender] = {}
    if cfg.smtp and env.get(cfg.smtp.username_env) and env.get(cfg.smtp.password_env):
        senders["email"] = EmailSender(
            cfg.smtp.host, cfg.smtp.port, env[cfg.smtp.username_env],
            env[cfg.smtp.password_env], cfg.smtp.from_address,
        )
    return Dispatcher(cfg.send_policy, db, senders)


def build_engine(
    cfg: Config, profile: Profile, db: Database, env: Mapping[str, str],
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    pt: Router | None = None, car: Router | None = None, geo=None,
) -> Engine:
    c = cfg.commute
    wants_geo = geo is None and needs_geo(cfg.criteria)
    motis = make_pt_router(c.pt_router, c.motis_base_url) if (pt is None or wants_geo) else None
    if pt is None:
        pt = SafeRouter(CachedRouter(motis, db))
    if wants_geo:
        geo = SafeGeo(CachedGeo(motis, db))
    if car is None and c.car_router == "motis":
        car = SafeRouter(ScaledRouter(
            CachedRouter(MotisCarRouter(c.motis_base_url or DEFAULT_BASE_URL), db),
            c.car_rush_hour_factor))
    if car is None:
        key = env.get(c.car_api_key_env)
        needs_car = any(t.max_car_minutes for t in c.targets)
        if needs_car and not key:
            log.warning("%s not set: car commute stays unknown (flats go to review)",
                        c.car_api_key_env)
        car = SafeRouter(CachedRouter(GoogleRoutesRouter(key), db)) if key else NoRouter()

    writer: OpeningWriter | None = None
    if env.get(cfg.llm.api_key_env):
        writer = LlmClient(cfg.llm.base_url, env[cfg.llm.api_key_env], cfg.llm.timeout_seconds)

    first = db.first_action_date()
    live_since = date.fromisoformat(first) if first else clock().date()
    dispatcher = build_dispatcher(cfg, db, env)
    return Engine(cfg, profile, dispatcher, pt, car, writer, live_since, clock, geo)


def build_notifier(cfg: Config, env: Mapping[str, str]) -> Notifier | None:
    topic = env.get(cfg.notifications.topic_env)
    if cfg.notifications.channel == "ntfy" and topic:
        return NtfyNotifier(topic)
    log.warning("no notifier configured (%s unset or channel unsupported)",
                cfg.notifications.topic_env)
    return None


def run_cycle(
    engine: Engine, db: Database, providers: list[Provider], notifier: Notifier | None
) -> RunStats:
    return run_once(providers, db, notifier, on_new_flat=engine.process)


def environ() -> Mapping[str, str]:
    return os.environ


def build_reply_tools(
    cfg: Config, profile: Profile | None, db: Database, env: Mapping[str, str],
    notifier: Notifier | None,
) -> tuple[LocalReplyLlm | None, AutoResponder | None]:
    """Optional local reply LLM and the automatic responder; both None unless enabled."""
    llm = None
    if cfg.reply_llm and cfg.reply_llm.enabled:
        key = env.get(cfg.reply_llm.api_key_env) if cfg.reply_llm.api_key_env else None
        llm = LocalReplyLlm(cfg.reply_llm, key)
    responder = None
    if cfg.auto_reply and cfg.auto_reply.enabled:
        if profile is None:
            log.warning("auto_reply enabled but the profile could not be loaded: disabled")
        else:
            sender = None
            if cfg.smtp and env.get(cfg.smtp.username_env) and env.get(cfg.smtp.password_env):
                sender = EmailSender(cfg.smtp.host, cfg.smtp.port, env[cfg.smtp.username_env],
                                     env[cfg.smtp.password_env], cfg.smtp.from_address)
            responder = AutoResponder(
                db, cfg.auto_reply, cfg.send_policy, profile, sender, llm, notifier,
                cfg.smtp.from_address if cfg.smtp else None)
    return llm, responder
