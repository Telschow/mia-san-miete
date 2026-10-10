"""Shadow-run report: what the agent decided, and where it may be wrong."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from .db import Database


def _line(row, listing) -> str:
    bits = []
    if listing:
        if listing.warm_rent_eur is not None:
            bits.append(f"{listing.warm_rent_eur:.0f} EUR warm")
        elif listing.cold_rent_eur is not None:
            bits.append(f"{listing.cold_rent_eur:.0f} EUR cold")
        if listing.area_m2 is not None:
            bits.append(f"{listing.area_m2:g} m2")
        if listing.rooms is not None:
            bits.append(f"{listing.rooms:g} rooms")
        where = listing.district or listing.postal_code
        if where:
            bits.append(where)
    reasons = "; ".join(json.loads(row["reasons"] or "[]")) or "no flags"
    score = "n/a" if row["score"] is None else f"{row['score']:.0f}"
    return (f"  [{row['source']}/{row['source_id']}] score {score} | "
            f"{', '.join(bits) or 'details missing'}\n      {reasons}")


def shadow_report(db: Database, days: int, now: datetime, limit: int = 15) -> str:
    since = (now - timedelta(days=days)).isoformat(timespec="seconds")
    rows = db.conn.execute(
        "SELECT a.* FROM actions a WHERE a.created_at >= ? ORDER BY a.id", (since,)
    ).fetchall()
    by_status: dict[str, list] = {}
    for r in rows:
        by_status.setdefault(r["status"], []).append(r)

    out = [f"Shadow report, last {days} days: {len(rows)} flats processed", ""]
    out += [f"  {k}: {len(v)}" for k, v in sorted(by_status.items())] or ["  nothing yet"]

    def section(title: str, status: str, hint: str, ascending: bool = False) -> None:
        group = sorted(by_status.get(status, []), key=lambda r: r["score"] or 0,
                       reverse=not ascending)[:limit]
        if not group:
            return
        out.extend(["", f"{title} ({hint})"])
        for r in group:
            out.append(_line(r, db.listing_for_action(r["id"])))

    section("Would have been sent", "shadow_would_send",
            "check these are flats you really want; false accepts")
    section("Queued for review", "queued", "borderline or incomplete data; what is missing?")
    section("Skipped, highest score first", "skipped",
            "check for false rejects: would you have wanted any of these?")
    return "\n".join(out)
