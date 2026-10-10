"""Read models for the dashboard. Pure functions over the database; no HTTP in here."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from ..config import Config
from ..db import Database
from ..dispatcher import start_of_day_utc_iso
from ..metrics import compute_metrics


def _json(raw: str | None, default):
    try:
        return json.loads(raw) if raw else default
    except ValueError:
        return default


def policy_status(cfg: Config, db: Database, now: datetime) -> dict:
    p = cfg.send_policy
    since = start_of_day_utc_iso(now)
    return {
        "enabled": p.enabled,
        "mode": p.mode,
        "kill_switch": p.kill_switch_file.exists(),
        "sent_today": db.count_actions("sent", since),
        "daily_cap": p.daily_cap,
        "per_platform_daily_cap": p.per_platform_daily_cap,
        "platform_allow_list": list(p.platform_allow_list),
        "quiet_hours": p.quiet_hours,
        "min_score": p.min_score,
    }


def daily_activity(db: Database, now: datetime, days: int = 14) -> list[dict]:
    since = (now - timedelta(days=days)).isoformat(timespec="seconds")
    rows = db.conn.execute(
        "SELECT substr(created_at, 1, 10) AS day, status, COUNT(*) n FROM actions"
        " WHERE created_at >= ? GROUP BY day, status", (since,)
    ).fetchall()
    by_day: dict[str, dict[str, int]] = {}
    for r in rows:
        by_day.setdefault(r["day"], {})[r["status"]] = r["n"]
    out = []
    for i in range(days, -1, -1):
        day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        counts = by_day.get(day, {})
        out.append({"day": day, "total": sum(counts.values()), "by_status": counts})
    return out


def overview(cfg: Config, db: Database, now: datetime, queue_size: int) -> dict:
    m = compute_metrics(db)
    d = asdict(m)
    d["reply_rate"], d["positive_rate"] = m.reply_rate, m.positive_rate
    return {
        "metrics": d,
        "policy": policy_status(cfg, db, now),
        "queue_size": queue_size,
        "daily": daily_activity(db, now),
        "demo": db.kv_get("demo") == "1",
    }


def queue_commute(db: Database, action_id: int, cfg: Config) -> dict | None:
    a = db.action_row(action_id)
    return commute_view(a["commute"], cfg) if a else None


def listings(db: Database, status: str | None = None, limit: int = 200) -> list[dict]:
    sql = (
        "SELECT a.id, a.canonical_id, a.source, a.source_id, a.status, a.score, a.created_at,"
        " l.data FROM actions a LEFT JOIN listings l ON l.source = a.source"
        " AND l.source_id = a.source_id WHERE a.id IN"
        " (SELECT MAX(id) FROM actions GROUP BY canonical_id)"
    )
    args: list = []
    if status:
        sql += " AND a.status = ?"
        args.append(status)
    sql += " ORDER BY a.id DESC LIMIT ?"
    args.append(limit)
    out = []
    for r in db.conn.execute(sql, args):
        data = _json(r["data"], {})
        out.append({
            "id": r["id"], "source": r["source"], "status": r["status"], "score": r["score"],
            "at": r["created_at"], "title": data.get("title", ""),
            "warm_rent_eur": data.get("warm_rent_eur"), "cold_rent_eur": data.get("cold_rent_eur"),
            "area_m2": data.get("area_m2"), "rooms": data.get("rooms"),
            "district": data.get("district") or data.get("postal_code"),
        })
    return out


def commute_view(raw: str | None, cfg: Config) -> dict | None:
    """Stored commute times joined with your limits. Place names and addresses stay out."""
    data = _json(raw, None)
    if not data:
        return None
    times = data.get("times", {})
    targets = []
    for t in cfg.commute.targets:
        got = times.get(t.name, {})
        targets.append({"name": t.name, "pt": got.get("pt"), "car": got.get("car"),
                        "max_pt": t.max_pt_minutes, "max_car": t.max_car_minutes,
                        "modes": t.modes})
    crit = cfg.criteria
    area = data.get("area")
    area_view = None
    if area:
        area_view = {**area,
                     "max_km": crit.area.max_km if crit.area else None,
                     "max_walk": crit.station.max_walk_minutes if crit.station else None,
                     "walk_required": bool(crit.station and crit.station.required)}
    return {"targets": targets, "combine": cfg.commute.combine,
            "margin": cfg.commute.borderline_margin_minutes,
            "estimated": bool(data.get("estimated")), "area": area_view}


def listing_detail(db: Database, action_id: int, cfg: Config | None = None) -> dict | None:
    a = db.action_row(action_id)
    if a is None:
        return None
    lst = db.listing_for_action(action_id)
    history = [
        {"status": r["status"], "at": r["created_at"]}
        for r in db.conn.execute(
            "SELECT status, created_at FROM actions WHERE canonical_id = ? ORDER BY id",
            (a["canonical_id"],))
    ]
    listing = lst.model_dump(mode="json") if lst else {}
    listing.pop("contact_email", None)       # never needed in the UI
    return {
        "id": a["id"], "status": a["status"], "mode": a["mode"], "score": a["score"],
        "score_version": a["score_version"],
        "breakdown": _json(a["breakdown"], {}), "reasons": _json(a["reasons"], []),
        "used_llm": None if a["used_llm"] is None else bool(a["used_llm"]),
        "listing": listing, "history": history,
        "commute": commute_view(a["commute"], cfg) if cfg else None,
    }


def activity(db: Database, limit: int = 30) -> list[dict]:
    rows = db.conn.execute(
        "SELECT a.id, a.source, a.status, a.score, a.created_at, l.data FROM actions a"
        " LEFT JOIN listings l ON l.source = a.source AND l.source_id = a.source_id"
        " ORDER BY a.id DESC LIMIT ?", (limit,))
    return [{"id": r["id"], "source": r["source"], "status": r["status"], "score": r["score"],
             "at": r["created_at"], "title": _json(r["data"], {}).get("title", "")}
            for r in rows]


def settings_view(cfg: Config) -> dict:
    """Effective settings with places, credentials and env var names left out."""
    c, p, w = cfg.criteria, cfg.send_policy, cfg.scoring.weights
    return {
        "criteria": {
            "max_warm_rent_eur": c.max_warm_rent_eur, "max_cold_rent_eur": c.max_cold_rent_eur,
            "min_area_m2": c.min_area_m2, "min_rooms": c.min_rooms,
            "move_in": [str(c.move_in.ideal_from), str(c.move_in.latest)],
            "exclude_keywords": c.exclude_keywords, "min_lease_months": c.min_lease_months,
        },
        "commute": {"targets": len(cfg.commute.targets), "combine": cfg.commute.combine,
                    "router": cfg.commute.pt_router},
        "send_policy": {
            "enabled": p.enabled, "mode": p.mode, "min_score": p.min_score,
            "loosen": {"step_points": p.loosen.step_points, "every_days": p.loosen.every_days,
                       "floor": p.loosen.floor},
            "daily_cap": p.daily_cap, "per_platform_daily_cap": p.per_platform_daily_cap,
            "platform_allow_list": p.platform_allow_list, "quiet_hours": p.quiet_hours,
        },
        "scoring_weights": w.model_dump(),
        "now": datetime.now(UTC).isoformat(timespec="seconds"),
    }
