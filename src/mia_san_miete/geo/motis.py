"""Public-transport routing via a MOTIS 2 server (works for all of Germany).

Checked against the community Transitous instance (October 2026): `/api/v1/geocode`,
`/api/v1/plan` (public transport and `directModes=CAR`) and `/api/v1/reverse-geocode` answer
as read here. Times are door to door. Check its usage policy, or run your own MOTIS, before
relying on it, and check one real route by hand against a journey planner.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime

from ..net import urlopen
from .area import Stop, haversine_km

DEFAULT_BASE_URL = "https://api.transitous.org"
USER_AGENT = "mia-san-miete/0.1 (personal flat search; contact via repository)"


def _get_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


class MotisRouter:
    mode = "pt"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        get: Callable[[str], object] = _get_json,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._get = get
        self._geo: dict[str, str | None] = {}

    def _place(self, text: str) -> str | None:
        if text not in self._geo:
            url = f"{self.base_url}/api/v1/geocode?" + urllib.parse.urlencode({"text": text})
            data = self._get(url)
            hit = data[0] if isinstance(data, list) and data else None
            self._geo[text] = (
                f"{hit['lat']},{hit['lon']}" if hit and "lat" in hit and "lon" in hit else None
            )
        return self._geo[text]

    def geocode(self, text: str) -> tuple[float, float] | None:
        place = self._place(text)
        if not place:
            return None
        lat, lon = place.split(",")
        return float(lat), float(lon)

    def nearest_stops(self, lat: float, lon: float, radius_m: int = 1500) -> list[Stop]:
        """Stops around a point. UNVERIFIED: `/api/v1/reverse-geocode` with `type=STOP` as
        remembered; the fields read are name, lat, lon and optionally modes. Parsing is
        defensive and anything unreadable is skipped."""
        query = urllib.parse.urlencode({"place": f"{lat},{lon}", "type": "STOP"})
        data = self._get(f"{self.base_url}/api/v1/reverse-geocode?{query}")
        out: list[Stop] = []
        for item in data if isinstance(data, list) else []:
            try:
                s_lat, s_lon = float(item["lat"]), float(item["lon"])
                modes = tuple(str(m) for m in (item.get("modes") or []))
                name = str(item.get("name") or "stop")
            except (KeyError, TypeError, ValueError):
                continue
            if haversine_km((lat, lon), (s_lat, s_lon)) * 1000 <= radius_m:
                out.append(Stop(name, s_lat, s_lon, modes))
        return out

    def minutes(self, origin: str, destination: str, arrive_by: datetime) -> float | None:
        src, dst = self._place(origin), self._place(destination)
        if not src or not dst:
            return None
        query = urllib.parse.urlencode({
            "fromPlace": src,
            "toPlace": dst,
            "time": arrive_by.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "arriveBy": "true",
            "numItineraries": 3,
        })
        data = self._get(f"{self.base_url}/api/v1/plan?{query}")
        itineraries = data.get("itineraries") if isinstance(data, dict) else None
        durations = [i["duration"] for i in itineraries or [] if "duration" in i]
        return min(durations) / 60.0 if durations else None


class MotisCarRouter(MotisRouter):
    """Car times from the same MOTIS server (street routing, no live traffic). Free, no key.
    Check one route by hand: `mia check-router` style, against a map for the same hour."""

    mode = "car"

    def minutes(self, origin: str, destination: str, arrive_by: datetime) -> float | None:
        src, dst = self._place(origin), self._place(destination)
        if not src or not dst:
            return None
        query = urllib.parse.urlencode({
            "fromPlace": src,
            "toPlace": dst,
            "time": arrive_by.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "arriveBy": "true",
            "directModes": "CAR",
            "transitModes": "",
            "numItineraries": 1,
        })
        data = self._get(f"{self.base_url}/api/v1/plan?{query}")
        direct = data.get("direct") if isinstance(data, dict) else None
        durations = [i["duration"] for i in direct or [] if "duration" in i]
        return min(durations) / 60.0 if durations else None


def make_pt_router(kind: str, base_url: str | None = None) -> MotisRouter:
    if kind == "motis":
        return MotisRouter(base_url or DEFAULT_BASE_URL)
    raise NotImplementedError(f"pt_router '{kind}' has no implementation yet; use motis")
