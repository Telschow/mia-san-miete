"""Fictional demo data: a populated database, config and profile with no private information."""

from __future__ import annotations

import json
import random
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import yaml

from .config import Config
from .db import Database
from .dispatcher import Dispatcher
from .messaging.generator import generate_draft
from .models import Listing
from .profile import Profile
from .replies import recipient_hash

CITY = "Beispielstadt"
DISTRICTS = ["Nordviertel", "Altstadt", "Hafenviertel", "Gartenstadt", "Südpark", "Westend",
             "Lindenhof", "Am Mühlbach"]
SOURCES = ["immoscout", "kleinanzeigen", "wg_gesucht", "immowelt"]
TITLES = [
    "Helle {r}-Zimmer-Wohnung mit Balkon", "Ruhige {r}-Zimmer-Altbauwohnung",
    "Moderne {r}-Zimmer-Wohnung mit Einbauküche", "Gemütliche {r}-Zimmer-Dachgeschosswohnung",
    "Sanierte {r}-Zimmer-Wohnung nahe Park", "Schöne {r}-Zimmer-Wohnung mit Loggia",
]
WEIGHTS = ["commute", "price", "size", "move_in", "balcony", "parking", "private_landlord",
           "freshness", "completeness"]
REPLY_MIX = ["viewing_invite"] * 4 + ["documents_request"] * 2 + ["rejection"] * 3 + [
    "auto_reply", "other"]


def demo_config(directory: Path, with_area: bool = True) -> dict:
    cfg = {
        "city": {"name": CITY},
        "criteria": {
            "max_warm_rent_eur": 1600, "max_cold_rent_eur": 1350, "min_area_m2": 52,
            "min_rooms": 2,
            "move_in": {"ideal_from": "2027-01-01", "latest": "2027-02-01", "early_flex_days": 31},
            "exclude_keywords": ["WBS", "Tausch"], "min_lease_months": 24,
            "nice_to_have": ["balcony"],
            "area": {"center": "Hauptbahnhof, Beispielstadt", "max_km": 12},
            "station": {"max_walk_minutes": 10},
        },
        "commute": {
            "combine": "all", "borderline_margin_minutes": 5, "pt_router": "motis",
            "car_router": "google_routes",
            "targets": [{"name": "work_a", "destination": "Hauptbahnhof, Beispielstadt",
                         "arrival_time": "09:00", "max_pt_minutes": 30}],
        },
        "send_policy": {
            "enabled": True, "mode": "live", "min_score": 85,
            "loosen": {"step_points": 5, "every_days": 3, "floor": 70},
            "daily_cap": 10, "per_platform_daily_cap": 5,
            "platform_allow_list": ["immoscout", "kleinanzeigen", "wg_gesucht", "immowelt"],
            "quiet_hours": None, "kill_switch_file": str(directory / "KILL"),
        },
        "llm": {"base_url": "http://localhost:3001/v1", "api_key_env": "UNUSED",
                "timeout_seconds": 6},
        "notifications": {"channel": "ntfy", "topic_env": "UNUSED", "heartbeat_hours": 24},
        "storage": {"db_path": str(directory / "demo.db")},
        "auto_reply": {"enabled": True, "mode": "live"},
    }
    if not with_area:       # tests and benchmarks run the engine without a geo service
        cfg["criteria"].pop("area")
        cfg["criteria"].pop("station")
    return cfg


def demo_profile() -> dict:
    return {
        "applicants": [{"first_name": "Max", "last_name": "Mustermann", "age": 31},
                       {"first_name": "Erika", "last_name": "Beispiel", "age": 29}],
        "contact": {"phone": "+49 170 0000000", "sender_email": "demo@example.test"},
        "facts": [
            {"id": "household", "de": "ein junges Paar ohne Kinder und ohne Haustiere",
             "en": "a young couple without children or pets", "usage": "always"},
            {"id": "income", "de": "unser Einkommen ist stabil und nachweisbar",
             "en": "our income is stable and documented", "usage": "always"},
            {"id": "character", "de": "Wir sind ruhig, ordentlich und zuverlässig",
             "en": "We are quiet, tidy and reliable", "usage": "always"},
        ],
        "viewing": {"de": "werktags ab 17:30 Uhr und am Wochenende jederzeit",
                    "en": "on weekdays from 5:30 pm and at any time on weekends"},
        "move_in": {"earliest": "2027-01-01", "latest": "2027-02-01", "reason": ""},
        "availability": {
            "windows": [{"days": ["mon", "tue", "wed", "thu", "fri"], "start": "17:30", "end": "20:00"},
                        {"days": ["sat", "sun"], "start": "09:00", "end": "20:00"}],
            "viewing_minutes": 30, "min_notice_hours": 12,
        },
    }


class DemoReplySender:
    def send_reply(self, to, subject, body, in_reply_to):
        return None


class DemoSender:
    """Pretends to send: returns a Message-ID and delivers nothing anywhere."""

    def send(self, listing, draft):
        return f"<demo-{listing.source_id}@demo.invalid>"


def write_demo_files(directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    cfg = directory / "config.yaml"
    prof = directory / "profile.yaml"
    cfg.write_text(yaml.safe_dump(demo_config(directory), allow_unicode=True), encoding="utf-8")
    prof.write_text(yaml.safe_dump(demo_profile(), allow_unicode=True), encoding="utf-8")
    return cfg, prof


def _seed_reply_draft(db: Database, profile: Profile, now: datetime) -> None:
    """One drafted answer to a fictional landlord's viewing offer, for the review queue."""
    from .scheduling import compose_reply, propose_slots
    row = db.conn.execute(
        "SELECT id, canonical_id, source, source_id, score FROM actions WHERE status = 'sent'"
        " ORDER BY id LIMIT 1").fetchone()
    if row is None or profile.availability is None:
        return
    iso = now.astimezone(UTC).isoformat(timespec="seconds")
    new_id = db.record_action(canonical_id=row["canonical_id"], source=row["source"],
                              source_id=row["source_id"], status="reply_queued", mode="live",
                              created_at=iso, score=row["score"], score_version="1")
    names = " und ".join(f"{a.first_name} {a.last_name}" for a in profile.applicants)
    body = compose_reply("propose", "de", names, profile.contact.phone, None,
                         propose_slots(profile.availability, now))
    db.save_draft(new_id, "Re: Anfrage zu Ihrer Wohnung", body, "de", iso, kind="reply",
                  reply_to="vermieter@example.test", in_reply_to="<demo@demo.invalid>")


def seed(db: Database, cfg: Config, profile: Profile, now: datetime, n: int = 60,
         seed_value: int = 7) -> None:
    rng = random.Random(seed_value)
    crng = random.Random(seed_value + 1)      # separate stream: keeps the main data stable
    db.kv_set("demo", "1")
    total_w = sum(getattr(cfg.scoring.weights, k) for k in WEIGHTS)
    queued_left = 5
    for i in range(n):
        seen = now - timedelta(hours=rng.uniform(1, 14 * 24))
        rooms = rng.choice([1, 1.5, 2, 2, 2.5, 3, 3.5, 4])
        area = round(rooms * rng.uniform(22, 32), 1)
        warm = round(rng.uniform(700, 2300) / 10) * 10
        lst = Listing(
            source=rng.choice(SOURCES), source_id=f"DEMO-{i:03d}", url=f"https://example.test/{i}",
            title=rng.choice(TITLES).format(r=f"{rooms:g}"),
            description="Ruhige Lage, Einbauküche vorhanden, Balkon.",
            warm_rent_eur=warm, cold_rent_eur=round(warm / 1.2 / 10) * 10, area_m2=area,
            rooms=rooms, street=f"Beispielweg {i % 40 + 1}", postal_code=f"{10000 + i * 37}",
            district=rng.choice(DISTRICTS), available_from=date(2027, 1, 15),
            landlord_type=rng.choice(["private", "agency"]), seen_at=seen,
            contact_email="vermieter@example.test",
        )
        res = db.ingest(lst)
        vals = {k: rng.uniform(0.3, 1.0) for k in WEIGHTS}
        reasons: list[str] = []
        if warm > cfg.criteria.max_warm_rent_eur:
            vals["price"] = 0.0
            reasons.append(f"warm rent {warm:.0f} over limit")
        if area < cfg.criteria.min_area_m2 or rooms < cfg.criteria.min_rooms:
            vals["size"] = 0.0
            reasons.append("too small")
        score = round(100 * sum(vals[k] * getattr(cfg.scoring.weights, k) for k in WEIGHTS)
                      / total_w, 1)
        breakdown = {k: {"value": round(vals[k], 2), "weight": getattr(cfg.scoring.weights, k)}
                     for k in WEIGHTS}
        pt_minutes = round(crng.uniform(8, 45), 0)
        walk = round(crng.uniform(2, 16), 1)
        commute = json.dumps({
            "times": {"work_a": {"pt": pt_minutes, "car": None}}, "estimated": crng.random() < 0.3,
            "area": {"located": True, "estimated": crng.random() < 0.3,
                     "km": round(crng.uniform(0.8, 13), 1), "walk_minutes": walk,
                     "station": crng.choice(["Lindenplatz", "Hafenmarkt", "Südpark", "Alter Markt"]),
                     "station_kind": crng.choice(["subway", "rail", "tram"]), "stop_found": True}})
        common = dict(  # noqa: C408
            canonical_id=res.canonical_id, source=lst.source, source_id=lst.source_id,
            mode="live", created_at=seen.isoformat(timespec="seconds"), score=score,
            score_version="1", breakdown=json.dumps(breakdown), commute=commute,
            reasons=json.dumps(reasons), template_version="1", used_llm=False)
        if reasons:
            db.record_action(status="skipped", **common)
        elif score >= 62 and queued_left and rng.random() < 0.25:
            queued_left -= 1
            aid = db.record_action(status="queued", **{**common, "reasons": json.dumps(
                ["commute incomplete"])})
            d = generate_draft(lst, profile, None, CITY)
            db.save_draft(aid, d.subject, d.body, d.language, common["created_at"])
        elif score >= 66:
            aid = db.record_action(status="sent", **common)
            db.record_outbound(aid, f"<demo-{lst.source_id}@demo.invalid>",
                               recipient_hash(lst.contact_email))
            if rng.random() < 0.55:
                db.record_reply(aid, f"<reply-{i}@demo.invalid>", rng.choice(REPLY_MIX),
                                "message_id",
                                (seen + timedelta(hours=rng.uniform(1, 40))).isoformat(
                                    timespec="seconds"))
        else:
            db.record_action(status="skipped", **{**common, "reasons": json.dumps(
                ["score below threshold"])})
    _seed_reply_draft(db, profile, now)


def build_demo_responder(cfg: Config, db: Database, profile: Profile):
    from .autoreply import AutoResponder
    return AutoResponder(db, cfg.auto_reply, cfg.send_policy, profile, DemoReplySender())


def build_demo_dispatcher(cfg: Config, db: Database) -> Dispatcher:
    return Dispatcher(cfg.send_policy, db, {"email": DemoSender(), **{
        s: DemoSender() for s in SOURCES}})
