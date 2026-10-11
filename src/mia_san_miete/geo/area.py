"""Where a flat is: straight-line distance from a center and walking time to the nearest stop.

Everything here is optional and degrades to "unknown", which the gates send to review. The walk
time is an estimate (straight line times a detour factor over a walking speed), not a routed
path, and is flagged as such. The stop lookup was checked against a live MOTIS server for one
address (right stops, distances and kinds); check yours with `mia check-area`.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass
from typing import Protocol

from ..config import Criteria
from ..db import Database
from ..models import Listing
from .travel import origin_for

log = logging.getLogger(__name__)

# MOTIS mode names, grouped into the kinds a user thinks in.
KIND_MODES: dict[str, set[str]] = {
    "subway": {"SUBWAY", "METRO"},
    "rail": {"RAIL", "SUBURBAN", "REGIONAL_RAIL", "REGIONAL_FAST_RAIL", "HIGHSPEED_RAIL",
             "LONG_DISTANCE", "NIGHT_RAIL"},
    "tram": {"TRAM"},
    "bus": {"BUS", "COACH"},
}


@dataclass(frozen=True)
class Stop:
    name: str
    lat: float
    lon: float
    modes: tuple[str, ...] = ()       # empty: the service did not say


@dataclass(frozen=True)
class AreaResult:
    located: bool = False             # the flat could be placed on the map
    estimated: bool = False           # placed from a postcode or district, not a street address
    km: float | None = None           # from the center, if one is set
    walk_minutes: float | None = None
    station: str | None = None
    station_kind: str | None = None
    stop_found: bool | None = None    # None: stops were not looked up


class Geo(Protocol):
    def geocode(self, text: str) -> tuple[float, float] | None: ...

    def nearest_stops(self, lat: float, lon: float, radius_m: int) -> list[Stop]: ...


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    (la1, lo1), (la2, lo2) = a, b
    p1, p2 = math.radians(la1), math.radians(la2)
    dphi, dlmb = p2 - p1, math.radians(lo2 - lo1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def walking_minutes(km: float, speed_kmh: float, detour: float) -> float:
    return km * detour / speed_kmh * 60


def stop_kinds(modes: tuple[str, ...]) -> set[str]:
    return {k for k, names in KIND_MODES.items() if names & {m.upper() for m in modes}}


def needs_geo(c: Criteria) -> bool:
    return bool((c.area and c.area.center and c.area.max_km)
                or (c.station and c.station.max_walk_minutes))


def compute_area(listing: Listing, c: Criteria, geo: Geo | None, city: str) -> AreaResult | None:
    if geo is None or not needs_geo(c):
        return None
    origin, estimated = origin_for(listing, city)
    point = geo.geocode(origin) if origin else None
    if point is None:
        return AreaResult(located=False, estimated=estimated)
    km = None
    if c.area and c.area.center and c.area.max_km:
        center = geo.geocode(c.area.center)
        km = None if center is None else haversine_km(point, center)
    walk = name = kind = None
    found: bool | None = None
    if c.station and c.station.max_walk_minutes:
        s = c.station
        # search a bit wider than the limit so a stop just beyond it is reported, not "none"
        radius = int(s.max_walk_minutes / 60 * s.walking_speed_kmh * 1000 / s.detour_factor * 1.6)
        best: tuple[float, Stop, str | None] | None = None
        for stop in geo.nearest_stops(point[0], point[1], radius):
            kinds = stop_kinds(stop.modes)
            match = next((k for k in s.kinds if k in kinds), None) if kinds else None
            if stop.modes and match is None:
                continue                 # the stop is known and is not a kind the user counts
            d = haversine_km(point, (stop.lat, stop.lon))
            if best is None or d < best[0]:
                best = (d, stop, match)
        found = best is not None
        if best:
            walk = walking_minutes(best[0], s.walking_speed_kmh, s.detour_factor)
            name, kind = best[1].name, best[2]
    return AreaResult(True, estimated, km, walk, name, kind, found)


def area_json(a: AreaResult | None) -> dict | None:
    return None if a is None else asdict(a)


class CachedGeo:
    """Remembers lookups in the database; failures (None or empty) are never cached."""

    def __init__(self, inner: Geo, db: Database) -> None:
        self.inner, self.db = inner, db

    def geocode(self, text: str) -> tuple[float, float] | None:
        key = f"geocode|{text.strip().lower()}"
        hit = self.db.geo_get(key)
        if hit:
            lat, lon = json.loads(hit)
            return lat, lon
        point = self.inner.geocode(text)
        if point is not None:
            self.db.geo_set(key, json.dumps(list(point)))
        return point

    def nearest_stops(self, lat: float, lon: float, radius_m: int) -> list[Stop]:
        key = f"stops|{lat:.4f},{lon:.4f}|{radius_m}"
        hit = self.db.geo_get(key)
        if hit:
            return [Stop(s["name"], s["lat"], s["lon"], tuple(s["modes"])) for s in json.loads(hit)]
        stops = self.inner.nearest_stops(lat, lon, radius_m)
        if stops:
            self.db.geo_set(key, json.dumps([{**asdict(s), "modes": list(s.modes)} for s in stops]))
        return stops


class SafeGeo:
    """An outage must not lose a flat: lookups that fail become 'unknown'."""

    def __init__(self, inner: Geo) -> None:
        self.inner = inner

    def geocode(self, text: str) -> tuple[float, float] | None:
        try:
            return self.inner.geocode(text)
        except Exception as exc:  # noqa: BLE001 - any failure degrades to unknown
            log.warning("geocoding failed: %s", type(exc).__name__)
            return None

    def nearest_stops(self, lat: float, lon: float, radius_m: int) -> list[Stop]:
        try:
            return self.inner.nearest_stops(lat, lon, radius_m)
        except Exception as exc:  # noqa: BLE001
            log.warning("stop lookup failed: %s", type(exc).__name__)
            return []
