"""Deterministic, versioned 0-100 score with a stored breakdown. No LLM involvement."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from .config import Commute, Criteria, Scoring, Target
from .gates import WARM_TO_COLD_RATIO
from .geo.area import AreaResult
from .geo.travel import CommuteResult
from .models import Listing

BALCONY_RE = re.compile(r"(?<!\w)(balkon|loggia|terrasse|dachterrasse)", re.IGNORECASE)
PARKING_RE = re.compile(r"(?<!\w)(stellplatz|tiefgarage|garage|parkplatz)", re.IGNORECASE)


@dataclass(frozen=True)
class ScoreResult:
    score: float
    version: str
    breakdown: dict[str, dict[str, float]]   # component -> {"value": 0..1, "weight": w}


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def _target_slack(times: dict[str, float | None], target: Target) -> float | None:
    slacks = []
    for mode, limit in (("pt", target.max_pt_minutes), ("car", target.max_car_minutes)):
        value = times.get(mode)
        if limit is not None and value is not None:
            slacks.append((limit - value) / limit)
    if not slacks:
        return None
    return max(slacks) if target.modes == "any" else min(slacks)


def commute_component(c: CommuteResult | None, cfg: Commute) -> float:
    """Slack to the limits; 50 percent slack or more counts as full marks."""
    if c is None:
        return 0.3
    per_target = [_target_slack(c.times.get(t.name, {}), t) for t in cfg.targets]
    if any(x is None for x in per_target):
        return 0.3
    known = [x for x in per_target if x is not None]
    slack = min(known) if cfg.combine == "all" else max(known)
    return _clip(slack / 0.5)


def price_component(listing: Listing, c: Criteria) -> float:
    warm = listing.warm_rent_eur
    if warm is None and listing.cold_rent_eur is not None:
        warm = listing.cold_rent_eur * WARM_TO_COLD_RATIO
    if warm is None:
        return 0.3
    return _clip((1 - warm / c.max_warm_rent_eur) / 0.3)   # 30 percent under cap is full


def size_component(listing: Listing, c: Criteria) -> float:
    if listing.area_m2 is None:
        return 0.3
    return _clip((listing.area_m2 - c.min_area_m2) / (c.min_area_m2 * 0.4))


def move_in_component(listing: Listing, c: Criteria) -> float:
    if listing.available_immediately:
        return 0.5
    d = listing.available_from
    if d is None:
        return 0.3
    if c.move_in.ideal_from <= d <= c.move_in.latest:
        return 1.0
    early_limit = c.move_in.ideal_from - timedelta(days=c.move_in.early_flex_days)
    return 0.5 if early_limit <= d < c.move_in.ideal_from else 0.0


def _text(listing: Listing) -> str:
    return f"{listing.title}\n{listing.description}"


def balcony_component(listing: Listing) -> float:
    return 1.0 if "balcony" in listing.features or BALCONY_RE.search(_text(listing)) else 0.0


def parking_component(listing: Listing) -> float:
    return 1.0 if "parking" in listing.features or PARKING_RE.search(_text(listing)) else 0.0


def landlord_component(listing: Listing) -> float:
    return {"private": 1.0, "unknown": 0.4, "agency": 0.2}[listing.landlord_type]


def freshness_component(listing: Listing, now: datetime) -> float:
    """Full marks within 10 minutes of publication, zero after 24 hours."""
    published = listing.published_at or listing.seen_at
    age_min = max(0.0, (now - published).total_seconds() / 60)
    if age_min <= 10:
        return 1.0
    return _clip(1 - (age_min - 10) / (24 * 60 - 10))


def completeness_component(listing: Listing) -> float:
    known = [
        listing.street,
        listing.postal_code,
        listing.area_m2,
        listing.rooms,
        listing.warm_rent_eur if listing.warm_rent_eur is not None else listing.cold_rent_eur,
        listing.available_from or listing.available_immediately or None,
    ]
    return sum(1 for k in known if k) / len(known)


def station_component(area: AreaResult | None, c: Criteria) -> float:
    """Full marks within half the limit, zero at twice the limit, 0.3 when unknown."""
    s = c.station
    if not s or not s.max_walk_minutes or area is None or area.walk_minutes is None:
        return 0.3
    m = s.max_walk_minutes
    return _clip((2 * m - area.walk_minutes) / (1.5 * m))


def score_listing(
    listing: Listing,
    criteria: Criteria,
    commute_cfg: Commute,
    commute: CommuteResult | None,
    scoring: Scoring,
    now: datetime,
    area: AreaResult | None = None,
) -> ScoreResult:
    values = {
        "commute": commute_component(commute, commute_cfg),
        "price": price_component(listing, criteria),
        "size": size_component(listing, criteria),
        "move_in": move_in_component(listing, criteria),
        "balcony": balcony_component(listing),
        "parking": parking_component(listing),
        "private_landlord": landlord_component(listing),
        "freshness": freshness_component(listing, now),
        "completeness": completeness_component(listing),
    }
    weights = scoring.weights.model_dump()
    if weights.get("station", 0) > 0 and criteria.station and criteria.station.max_walk_minutes:
        values["station"] = station_component(area, criteria)
    total_w = sum(w for k, w in weights.items() if k in values)
    raw = sum(values[k] * weights[k] for k in values) / total_w
    breakdown = {k: {"value": round(values[k], 3), "weight": weights[k]} for k in values}
    return ScoreResult(round(100 * raw, 1), scoring.version, breakdown)
