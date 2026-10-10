"""Commute computation behind small router interfaces, with a SQLite-backed cache.

Real routers (MVG, MOTIS, Google Routes) implement `Router`. Results are cached by
origin, destination, mode and time of day so each address is routed once.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from ..config import Commute
from ..db import Database
from ..models import Listing

BERLIN = ZoneInfo("Europe/Berlin")


@dataclass(frozen=True)
class CommuteResult:
    times: dict[str, dict[str, float | None]]   # target name -> {"pt": min, "car": min}
    estimated: bool          # origin was only a postal code or district, not a full address


class Router(Protocol):
    mode: str

    def minutes(self, origin: str, destination: str, arrive_by: datetime) -> float | None: ...


class CachedRouter:
    def __init__(self, inner: Router, db: Database) -> None:
        self.inner = inner
        self.db = db
        self.mode = inner.mode

    def minutes(self, origin: str, destination: str, arrive_by: datetime) -> float | None:
        key = f"{self.mode}|{origin}|{destination}|{arrive_by:%H:%M}"
        hit = self.db.cache_get(key)
        if hit is not None:
            return hit
        value = self.inner.minutes(origin, destination, arrive_by)
        if value is not None:       # never cache failures
            self.db.cache_set(key, value)
        return value


def next_weekday_arrival(now: datetime, hhmm: str) -> datetime:
    """Next Monday to Friday at hhmm Berlin time, strictly after `now`."""
    hour, minute = (int(x) for x in hhmm.split(":"))
    day = now.astimezone(BERLIN)
    while True:
        candidate = datetime.combine(day.date(), time(hour, minute), tzinfo=BERLIN)
        if candidate > now and candidate.weekday() < 5:
            return candidate
        day = day + timedelta(days=1)


def origin_for(listing: Listing, city: str) -> tuple[str | None, bool]:
    """Return (origin string, estimated). Estimated means no street address."""
    if listing.street and listing.postal_code:
        return f"{listing.street}, {listing.postal_code} {city}", False
    if listing.postal_code:
        return f"{listing.postal_code} {city}", True
    if listing.district:
        return f"{listing.district}, {city}", True
    return None, True


def compute_commute(
    listing: Listing, cfg: Commute, pt: Router, car: Router, now: datetime, city: str
) -> CommuteResult:
    origin, estimated = origin_for(listing, city)
    if origin is None:
        return CommuteResult({}, True)
    times: dict[str, dict[str, float | None]] = {}
    for target in cfg.targets:
        arrive = next_weekday_arrival(now, target.arrival_time)
        times[target.name] = {
            # only call a router when the target actually limits that mode (saves quota)
            "pt": pt.minutes(origin, target.destination, arrive) if target.max_pt_minutes else None,
            "car": (
                car.minutes(origin, target.destination, arrive) if target.max_car_minutes else None
            ),
        }
    return CommuteResult(times, estimated)


def _post_json(url: str, headers: dict[str, str], body: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


class GoogleRoutesRouter:
    """Car routing via the Google Routes API (computeRoutes).

    UNVERIFIED against the live API: request shape follows the public docs as remembered.
    Check the field mask, traffic-aware pricing tier and quota before relying on it.
    The API takes a departure time for driving, so we depart `assumed_trip_minutes`
    before the wanted arrival.
    """

    mode = "car"
    URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

    def __init__(
        self,
        api_key: str,
        assumed_trip_minutes: int = 35,
        post: Callable[[str, dict[str, str], dict], dict] = _post_json,
    ) -> None:
        self.api_key = api_key
        self.assumed_trip_minutes = assumed_trip_minutes
        self._post = post

    def minutes(self, origin: str, destination: str, arrive_by: datetime) -> float | None:
        departure = arrive_by - timedelta(minutes=self.assumed_trip_minutes)
        body = {
            "origin": {"address": origin},
            "destination": {"address": destination},
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
            "departureTime": departure.isoformat(),
        }
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "routes.duration",
        }
        data = self._post(self.URL, headers, body)
        routes = data.get("routes") or []
        if not routes:
            return None
        duration = routes[0].get("duration", "")
        if not duration.endswith("s"):
            return None
        return float(duration[:-1]) / 60.0
