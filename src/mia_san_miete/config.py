"""Typed config loading. Fails loudly on unsafe or inconsistent send policy."""

from __future__ import annotations

import ipaddress
from datetime import date
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MoveIn(_Strict):
    ideal_from: date
    latest: date
    early_flex_days: int = Field(default=0, ge=0)   # days before ideal_from that still pass
    unknown: Literal["review", "flag"] = "review"   # a flat without a move-in date

    @model_validator(mode="after")
    def _ordered(self) -> MoveIn:
        if self.latest < self.ideal_from:
            raise ValueError("move_in.latest must not be before ideal_from")
        return self


class Area(_Strict):
    """Where a flat may be. Every part is optional. Postcode and district lists need no network;
    the radius needs the flat and the center placed on a map. An unknown location goes to
    review, never to reject."""

    center: str | None = None          # address or station counted as the middle, e.g. a Hbf
    max_km: float | None = Field(default=None, gt=0)    # straight-line distance from the center
    include_postal_codes: list[str] = Field(default_factory=list)   # prefixes; empty means any
    exclude_postal_codes: list[str] = Field(default_factory=list)
    exclude_districts: list[str] = Field(default_factory=list)      # matched as text, any case

    @model_validator(mode="after")
    def _radius_needs_center(self) -> Area:
        if self.max_km is not None and not self.center:
            raise ValueError("area.max_km needs area.center")
        return self


class Station(_Strict):
    """Walking distance to the closest metro, S-Bahn or tram stop (an estimate)."""

    max_walk_minutes: int | None = Field(default=None, gt=0)
    kinds: list[Literal["subway", "rail", "tram", "bus"]] = Field(
        default_factory=lambda: ["subway", "rail", "tram"])
    required: bool = False             # True: a farther stop rejects; False: only the score uses it
    walking_speed_kmh: float = Field(default=4.8, gt=0)
    detour_factor: float = Field(default=1.3, ge=1)   # streets are longer than straight lines


class Criteria(_Strict):
    max_warm_rent_eur: int = Field(gt=0)
    max_cold_rent_eur: int = Field(gt=0)
    min_area_m2: int = Field(gt=0)
    min_rooms: float = Field(gt=0)
    move_in: MoveIn
    exclude_keywords: list[str] = []
    min_lease_months: int = Field(ge=0)
    max_warm_rent_per_m2: float | None = Field(default=None, gt=0)    # hard limit, euro per m2
    market_warm_rent_per_m2: float | None = Field(default=None, gt=0)  # reference for the checks
    nice_to_have: list[str] = []
    area: Area | None = None
    station: Station | None = None

    @model_validator(mode="after")
    def _rents(self) -> Criteria:
        if self.max_cold_rent_eur > self.max_warm_rent_eur:
            raise ValueError("max_cold_rent_eur must not exceed max_warm_rent_eur")
        return self


class City(_Strict):
    name: str     # appended to partial addresses when routing, e.g. "Hamburg"


class Target(_Strict):
    """A place you travel to regularly (workplace, university, family)."""

    name: str
    destination: str
    arrival_time: str = Field(pattern=r"^\d{2}:\d{2}$")   # weekday morning arrival, HH:MM
    max_pt_minutes: int | None = Field(default=None, gt=0)
    max_car_minutes: int | None = Field(default=None, gt=0)
    modes: Literal["any", "all"] = "any"   # any: one listed mode within its limit is enough

    @model_validator(mode="after")
    def _has_limit(self) -> Target:
        if self.max_pt_minutes is None and self.max_car_minutes is None:
            raise ValueError(f"target {self.name}: set max_pt_minutes and/or max_car_minutes")
        return self


class Commute(_Strict):
    targets: list[Target] = Field(min_length=1)
    combine: Literal["all", "any"] = "all"   # all: every target must pass
    borderline_margin_minutes: int = Field(ge=0)
    pt_router: Literal["mvg", "motis"]
    car_router: Literal["google_routes", "motis"]
    motis_base_url: str | None = None   # default: community Transitous instance
    car_api_key_env: str = "GOOGLE_ROUTES_API_KEY"   # only read if a target has a car limit
    car_rush_hour_factor: float = Field(default=1.3, ge=1)   # motis car times ignore traffic

    @model_validator(mode="after")
    def _unique_names(self) -> Commute:
        names = [t.name for t in self.targets]
        if len(names) != len(set(names)):
            raise ValueError("commute target names must be unique")
        return self


class Loosen(_Strict):
    step_points: int = Field(gt=0)
    every_days: int = Field(gt=0)
    floor: int = Field(ge=0, le=100)


class SendPolicy(_Strict):
    enabled: bool = False
    mode: Literal["shadow", "live"] = "shadow"
    min_score: int = Field(ge=0, le=100)
    loosen: Loosen
    daily_cap: int = Field(ge=0)
    per_platform_daily_cap: int = Field(ge=0)
    platform_allow_list: list[str] = []
    quiet_hours: str | None = None
    kill_switch_file: Path

    @model_validator(mode="after")
    def _consistent(self) -> SendPolicy:
        if self.loosen.floor > self.min_score:
            raise ValueError("send_policy.loosen.floor must not exceed min_score")
        if self.per_platform_daily_cap > self.daily_cap:
            raise ValueError("per_platform_daily_cap must not exceed daily_cap")
        if self.enabled and self.mode == "live" and not self.platform_allow_list:
            raise ValueError("live auto-send requires a non-empty platform_allow_list")
        return self


class Llm(_Strict):
    base_url: str
    api_key_env: str
    timeout_seconds: float = Field(gt=0)
    log_answering_model: bool = True


class Notifications(_Strict):
    channel: Literal["ntfy", "telegram"]
    topic_env: str
    heartbeat_hours: int = Field(gt=0)
    silence_alert_hours: int | None = Field(default=48, gt=0)   # no listings for this long


class Imap(_Strict):
    """An IMAP inbox. Credentials come from environment variables, never from the file."""

    imap_host: str
    imap_port: int = 993
    folder: str = "INBOX"
    username_env: str
    password_env: str
    lookback_days: int = Field(default=30, gt=0)


class Replies(Imap):
    """Inbox that receives landlord replies."""


class Alerts(Imap):
    """Inbox that receives portal alert emails (saved-search notifications)."""

    lookback_days: int = Field(default=3, gt=0)
    sender_domains: list[str] = Field(min_length=1)   # only mail from these domains is read


class Smtp(_Strict):
    """Outgoing mail for the email sender. Credentials come from environment variables."""

    host: str
    port: int = 587
    username_env: str
    password_env: str
    from_address: str


def _is_local_host(host: str) -> bool:
    if host in ("localhost", "") or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


class ReplyLlm(_Strict):
    """Optional local LLM that reads landlord replies (classification, date extraction).

    Off by default. Replies are private correspondence, so only a model on this machine or
    the local network is accepted; a hosted endpoint is rejected on purpose.
    """

    enabled: bool = False
    base_url: str = "http://localhost:11434/v1"
    model: str = "llama3.1"
    timeout_seconds: float = Field(default=20, gt=0)
    api_key_env: str | None = None

    @model_validator(mode="after")
    def _local_only(self) -> ReplyLlm:
        host = urlparse(self.base_url).hostname or ""
        if not _is_local_host(host):
            raise ValueError(
                "reply_llm.base_url must point to this machine or a private network address "
                "(replies are private correspondence); hosted endpoints are not allowed")
        return self


class AutoReply(_Strict):
    """Automatic answer to a landlord's viewing offer. Off by default; shadow first."""

    enabled: bool = False
    mode: Literal["shadow", "live"] = "shadow"
    daily_cap: int = Field(default=5, ge=0)
    max_replies_per_thread: int = Field(default=1, ge=1)
    horizon_days: int = Field(default=21, gt=0)       # ignore slots further away than this


class Storage(_Strict):
    db_path: Path


class Weights(_Strict):
    commute: float = Field(default=25, ge=0)
    price: float = Field(default=20, ge=0)
    size: float = Field(default=10, ge=0)
    move_in: float = Field(default=15, ge=0)
    balcony: float = Field(default=5, ge=0)
    parking: float = Field(default=3, ge=0)
    private_landlord: float = Field(default=7, ge=0)
    freshness: float = Field(default=10, ge=0)
    completeness: float = Field(default=5, ge=0)
    station: float = Field(default=0, ge=0)   # only counts when criteria.station is set

    @model_validator(mode="after")
    def _positive_total(self) -> Weights:
        if sum(self.model_dump().values()) <= 0:
            raise ValueError("at least one scoring weight must be positive")
        return self


class Scoring(_Strict):
    version: str = "1"
    weights: Weights = Field(default_factory=Weights)


class Config(_Strict):
    city: City
    criteria: Criteria
    commute: Commute
    send_policy: SendPolicy
    llm: Llm
    notifications: Notifications
    storage: Storage
    replies: Replies | None = None
    alerts: Alerts | None = None
    smtp: Smtp | None = None
    reply_llm: ReplyLlm | None = None
    auto_reply: AutoReply | None = None
    scoring: Scoring = Field(default_factory=Scoring)


def load_config(path: str | Path) -> Config:
    try:
        fh = open(path, encoding="utf-8")  # noqa: SIM115 - closed right below
    except FileNotFoundError:
        raise FileNotFoundError(
            f"{path} not found. Create it with 'cp config.example.yaml config.yaml' "
            "(or run the guided setup) and edit it; see docs/how-to.md."
        ) from None
    with fh:
        raw = yaml.safe_load(fh)
    return Config.model_validate(raw)
