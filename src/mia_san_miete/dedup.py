"""Cross-portal duplicate detection on physical attributes, not on titles.

Two listings are the same flat if rooms match, areas are close, rents are close when both
are known, and location does not contradict. Missing data never contradicts, but at least
two independent signals must agree so a sparse listing is not merged by accident.
"""

from __future__ import annotations

import re

from .models import Listing

AREA_TOLERANCE_M2 = 1.0
RENT_TOLERANCE = 0.03


def _norm_street(street: str | None) -> str | None:
    if not street:
        return None
    s = street.lower().strip()
    s = s.replace("ß", "ss").replace("straße", "str").replace("strasse", "str")
    s = re.sub(r"[^a-z0-9]", "", s)   # drops spaces and dots: "Leopold Str." == "Leopoldstr"
    return s or None


def _close(a: float, b: float, rel: float) -> bool:
    return abs(a - b) <= rel * max(a, b)


def is_same_flat(a: Listing, b: Listing) -> bool:
    if a.rooms is None or b.rooms is None or a.area_m2 is None or b.area_m2 is None:
        return False   # rooms and area are the minimum identity; without them never merge
    if a.rooms != b.rooms:
        return False
    if abs(a.area_m2 - b.area_m2) > AREA_TOLERANCE_M2:
        return False

    signals = 2        # rooms and area already agree
    for x, y in ((a.cold_rent_eur, b.cold_rent_eur), (a.warm_rent_eur, b.warm_rent_eur)):
        if x is not None and y is not None:
            if not _close(x, y, RENT_TOLERANCE):
                return False
            signals += 1

    if a.postal_code and b.postal_code:
        if a.postal_code != b.postal_code:
            return False
        signals += 1

    sa, sb = _norm_street(a.street), _norm_street(b.street)
    if sa and sb:
        if sa != sb:
            return False
        signals += 1

    return signals >= 4
