"""Hard gates. Deterministic; any REJECT means the listing is never sent."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum

from .config import Commute, Criteria, Target
from .geo.area import AreaResult
from .geo.travel import CommuteResult
from .models import Listing

# Assumption (not measured): warm rent is typically about 1.2 times cold rent. Used only to
# estimate the missing figure, and the result is always flagged.
WARM_TO_COLD_RATIO = 1.2

NEGATION = r"(?:kein|keine|keinen|ohne|nicht)\s+(?:\w+\s+){0,2}"

SCAM_PATTERNS = [
    "western union",
    "vorkasse",
    "kaution vor besichtigung",
    "schlüssel per post",
    "schluessel per post",
    "keine besichtigung",
    "besichtigung nicht möglich",
    "besichtigung nicht moeglich",
]

SHORT_LEASE_TERMS = ["zwischenmiete", "untermiete auf zeit"]


class Verdict(StrEnum):
    PASS = "pass"
    REVIEW = "review"
    REJECT = "reject"


@dataclass
class GateResult:
    rejects: list[str] = field(default_factory=list)
    reviews: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> Verdict:
        if self.rejects:
            return Verdict.REJECT
        if self.reviews:
            return Verdict.REVIEW
        return Verdict.PASS


def _unnegated(low: str, pattern: str) -> bool:
    for m in re.finditer(pattern, low):
        before = low[max(0, m.start() - 40) : m.start()]
        if not re.search(NEGATION + r"$", before):
            return True
    return False


def mentions(text: str, keyword: str) -> bool:
    """Whole-word match that ignores negated mentions ("kein WBS erforderlich")."""
    return _unnegated(text.lower(), rf"(?<!\w){re.escape(keyword.lower())}(?!\w)")


def is_furnished(text: str) -> bool:
    """"möbliert", "vollmöbliert", "fully furnished"; not "teilmöbliert" or "unmöbliert"."""
    pattern = (
        r"(?<!teil)(?<!un)(?<!halb)(?<!\bnicht )m(?:ö|oe)bliert(?!\w)"
        r"|(?<!un)(?<!partly )(?<!part )(?<!semi-)(?<!\w)furnished(?!\w)"
    )
    return _unnegated(text.lower(), pattern)


def _text(listing: Listing) -> str:
    return f"{listing.title}\n{listing.description}"


def check_price(listing: Listing, c: Criteria, out: GateResult) -> None:
    warm, cold = listing.warm_rent_eur, listing.cold_rent_eur
    if warm is None and cold is None:
        out.reviews.append("rent unknown")
        return
    if warm is None:
        warm = cold * WARM_TO_COLD_RATIO
        out.flags.append("warm rent estimated")
    if cold is None:
        cold = warm / WARM_TO_COLD_RATIO
        out.flags.append("cold rent estimated")
    if warm > c.max_warm_rent_eur:
        out.rejects.append(f"warm rent {warm:.0f} above {c.max_warm_rent_eur}")
    if cold > c.max_cold_rent_eur:
        out.rejects.append(f"cold rent {cold:.0f} above {c.max_cold_rent_eur}")


def check_size(listing: Listing, c: Criteria, out: GateResult) -> None:
    if listing.area_m2 is None:
        out.reviews.append("area unknown")
    elif listing.area_m2 < c.min_area_m2:
        out.rejects.append(f"area {listing.area_m2:g} below {c.min_area_m2}")
    if listing.rooms is None:
        out.reviews.append("rooms unknown")
    elif listing.rooms < c.min_rooms:
        out.rejects.append(f"rooms {listing.rooms:g} below {c.min_rooms:g}")


def check_exclusions(listing: Listing, c: Criteria, out: GateResult) -> None:
    text = _text(listing)
    for kw in c.exclude_keywords:
        if mentions(text, kw):
            out.rejects.append(f"excluded term: {kw}")
    for term in SHORT_LEASE_TERMS:
        if mentions(text, term):
            out.rejects.append(f"short lease: {term}")
    if mentions(text, "befristet") and not any("short lease" in r for r in out.rejects):
        out.reviews.append("fixed-term lease, check duration")
    if is_furnished(text):
        out.rejects.append("furnished")


def check_scam(listing: Listing, out: GateResult) -> None:
    text = _text(listing).lower()
    for pattern in SCAM_PATTERNS:
        if pattern in text:
            out.rejects.append(f"scam red flag: {pattern}")
    if (
        listing.deposit_eur
        and listing.cold_rent_eur
        and listing.deposit_eur > 3 * listing.cold_rent_eur
    ):
        out.rejects.append("scam red flag: deposit above 3 cold rents")


def check_move_in(listing: Listing, c: Criteria, out: GateResult) -> None:
    mi = c.move_in
    if listing.available_immediately:
        out.flags.append("available immediately, move-in negotiable?")
        return
    d = listing.available_from
    if d is None:
        out.reviews.append("move-in date unknown")
        return
    if d > mi.latest:
        out.rejects.append(f"available {d} after {mi.latest}")
    elif d >= mi.ideal_from:
        return
    elif d >= mi.ideal_from - timedelta(days=mi.early_flex_days):
        out.flags.append("earlier than ideal move-in, negotiable?")
    else:
        out.rejects.append(f"available {d} too early")


def target_status(times: dict[str, float | None], target: Target, margin: float) -> str:
    """pass | fail | unknown for one target, allowing `margin` extra minutes."""
    checks: list[bool | None] = []
    for mode, limit in (("pt", target.max_pt_minutes), ("car", target.max_car_minutes)):
        if limit is None:
            continue
        value = times.get(mode)
        checks.append(None if value is None else value <= limit + margin)
    if target.modes == "any":
        if any(c is True for c in checks):
            return "pass"
        return "unknown" if any(c is None for c in checks) else "fail"
    if any(c is False for c in checks):
        return "fail"
    return "unknown" if any(c is None for c in checks) else "pass"


def commute_status(result: CommuteResult, cfg: Commute, margin: float) -> str:
    statuses = [
        target_status(result.times.get(t.name, {}), t, margin) for t in cfg.targets
    ]
    if cfg.combine == "all":
        if "fail" in statuses:
            return "fail"
        return "unknown" if "unknown" in statuses else "pass"
    if "pass" in statuses:
        return "pass"
    return "unknown" if "unknown" in statuses else "fail"


def check_commute(result: CommuteResult | None, c: Commute, out: GateResult) -> None:
    if result is None:
        out.reviews.append("commute not computed")
        return
    exact = commute_status(result, c, 0)
    if exact == "unknown":
        out.reviews.append("commute incomplete")
    elif exact == "pass":
        if result.estimated:
            out.flags.append("commute estimated from postal code or district")
    elif result.estimated and commute_status(result, c, c.borderline_margin_minutes) == "pass":
        out.reviews.append("commute borderline and estimated")
    else:
        out.rejects.append("commute too long")


def check_area(listing: Listing, criteria: Criteria, area: AreaResult | None, out: GateResult) -> None:
    """Postcode and district lists (no network), the radius, and the optional stop limit.
    An unknown location is a review, never a reject."""
    a = criteria.area
    if a:
        pc = (listing.postal_code or "").strip()
        if a.exclude_postal_codes and pc and any(pc.startswith(x) for x in a.exclude_postal_codes):
            out.rejects.append(f"postal code {pc} is excluded")
        if a.include_postal_codes:
            if not pc:
                out.reviews.append("postal code unknown (you limited the search to some postcodes)")
            elif not any(pc.startswith(x) for x in a.include_postal_codes):
                out.rejects.append(f"postal code {pc} is outside your list")
        district = (listing.district or "").lower()
        if district and any(d.lower() in district for d in a.exclude_districts):
            out.rejects.append(f"district {listing.district} is excluded")
        if a.center and a.max_km:
            if area is None or area.km is None:
                out.reviews.append("distance to the center unknown")
            elif area.km > a.max_km:
                if area.estimated and area.km <= a.max_km * 1.1:
                    out.reviews.append(f"{area.km:.1f} km from the center, borderline and estimated")
                else:
                    out.rejects.append(f"{area.km:.1f} km from the center (limit {a.max_km:g})")
            elif area.estimated:
                out.flags.append("distance estimated from postcode or district")
    s = criteria.station
    if s and s.max_walk_minutes and s.required:
        if area is None or not area.located:
            out.reviews.append("walking distance to a stop unknown")
        elif area.walk_minutes is None:
            out.reviews.append("no stop found nearby, check by hand")
        elif area.walk_minutes > s.max_walk_minutes:
            if area.estimated and area.walk_minutes <= s.max_walk_minutes + 3:
                out.reviews.append(f"{area.walk_minutes:.0f} min walk to a stop, borderline and estimated")
            else:
                out.rejects.append(
                    f"{area.walk_minutes:.0f} min walk to {area.station or 'a stop'} "
                    f"(limit {s.max_walk_minutes})")


def evaluate_gates(
    listing: Listing, criteria: Criteria, commute_cfg: Commute, commute: CommuteResult | None,
    area: AreaResult | None = None,
) -> GateResult:
    out = GateResult()
    check_price(listing, criteria, out)
    check_size(listing, criteria, out)
    check_exclusions(listing, criteria, out)
    check_scam(listing, out)
    check_move_in(listing, criteria, out)
    check_commute(commute, commute_cfg, out)
    check_area(listing, criteria, area, out)
    return out
