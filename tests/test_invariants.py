# ruff: noqa: RUF059
"""Randomized safety invariants for the send path (seeded, so failures are reproducible)."""

import logging
import random
from datetime import UTC, date, datetime, timedelta

import pytest

from mia_san_miete.config import Config
from mia_san_miete.db import Database
from mia_san_miete.demo import demo_config, demo_profile
from mia_san_miete.dispatcher import Dispatcher, start_of_day_utc_iso
from mia_san_miete.engine import Engine
from mia_san_miete.models import Listing
from mia_san_miete.profile import Profile

SECRET_EMAIL = "vermieter.geheim@example.test"
SCENARIOS = 300


class Counting:
    def __init__(self):
        self.calls = []

    def send(self, listing, draft):
        self.calls.append((listing.source_id, draft.body))
        return "<id@demo.invalid>"


class Fake:
    def __init__(self, mode, v=15.0):
        self.mode, self.v = mode, v

    def minutes(self, *a):
        return self.v


def _scenario(i, tmp_path):
    rng = random.Random(9000 + i)
    cfg0 = Config.model_validate(demo_config(tmp_path, with_area=False))
    profile = Profile.model_validate(demo_profile())
    now = datetime(2026, 11, 2, 0, 0, tzinfo=UTC) + timedelta(minutes=rng.randint(0, 1439))
    kill = tmp_path / f"KILL{i}"
    if rng.random() < 0.25:
        kill.write_text("")
    daily = rng.randint(1, 4)
    policy = cfg0.send_policy.model_copy(update={
        "enabled": rng.random() < 0.85, "mode": rng.choice(["shadow", "live", "live"]),
        "kill_switch_file": kill, "min_score": 20,
        "loosen": cfg0.send_policy.loosen.model_copy(update={"floor": 10}),
        "daily_cap": daily, "per_platform_daily_cap": rng.randint(1, daily),
        "quiet_hours": rng.choice([None, "22:00-07:00", "08:00-12:00"]),
    })
    cfg = cfg0.model_copy(update={"send_policy": policy})
    db, rec = Database(), Counting()
    for k in range(rng.randint(0, 3)):                      # earlier sends today
        cid = db.conn.execute("INSERT INTO canonicals (created_at) VALUES ('x')").lastrowid
        db.record_action(canonical_id=cid, source="immoscout", source_id=f"old{k}", status="sent",
                         mode="live", created_at=start_of_day_utc_iso(now))
    sender = {s: rec for s in ("immoscout", "email")}
    eng = Engine(cfg, profile, Dispatcher(policy, db, sender), Fake("pt"), Fake("car"), None,
                 date(2026, 11, 1), lambda: now)
    return rng, cfg, db, rec, eng, now


def _listing(rng, i):
    """Mostly clean listings (so sends really happen), with one random hostile mutation."""
    fields = {
        "title": "Helle 2-Zimmer-Wohnung mit Balkon", "description": "Ruhige Lage.",
        "warm_rent_eur": 1400.0, "cold_rent_eur": 1150.0, "area_m2": 60.0, "rooms": 2.0,
        "available_from": date(2027, 1, 15),
    }
    if rng.random() < 0.5:
        k = rng.choice(["scam", "rent_high", "rent_none", "small", "area_none", "date_none",
                        "date_early", "exclude"])
        if k == "scam":
            fields["description"] = "Bitte per Western Union zahlen."
        elif k == "rent_high":
            fields.update(warm_rent_eur=2600.0, cold_rent_eur=2300.0)
        elif k == "rent_none":
            fields.update(warm_rent_eur=None, cold_rent_eur=None)
        elif k == "small":
            fields["area_m2"] = 30.0
        elif k == "area_none":
            fields["area_m2"] = None
        elif k == "date_none":
            fields["available_from"] = None
        elif k == "date_early":
            fields["available_from"] = date(2026, 11, 20)
        else:
            fields["title"] = "Tauschwohnung, WBS nötig"
    return Listing(
        source="immoscout", source_id=f"S{i}", url="https://example.test/x", **fields,
        street="Beispielweg 1", postal_code="12345", district="Nordviertel",
        seen_at=datetime(2026, 11, 2, tzinfo=UTC), contact_email=SECRET_EMAIL)


@pytest.mark.parametrize("i", range(SCENARIOS))
def test_send_path_invariants(i, tmp_path, caplog):
    rng, cfg, db, rec, eng, now = _scenario(i, tmp_path)
    p = cfg.send_policy
    caplog.set_level(logging.DEBUG)
    sent_before = db.count_actions("sent", start_of_day_utc_iso(now))
    lst = _listing(rng, i)
    outcome = eng.process(lst, db.ingest(lst))

    if rec.calls:                                              # something was sent
        assert outcome.status == "sent"
        assert p.mode == "live", "sent in shadow mode"
        assert not p.kill_switch_file.exists(), "sent with kill switch on"
        assert sent_before < p.daily_cap, "daily cap exceeded"
        assert lst.warm_rent_eur is not None and lst.warm_rent_eur <= cfg.criteria.max_warm_rent_eur
        assert lst.area_m2 is not None and lst.area_m2 >= cfg.criteria.min_area_m2, "gate bypassed"
        assert "western union" not in f"{lst.title} {lst.description}".lower(), "scam text sent"
        assert lst.available_from is not None, "review verdict (missing data) was auto-sent"
    if p.mode == "shadow":
        assert rec.calls == []
    assert outcome.status != "sent" or len(rec.calls) == 1

    audit = " ".join(str(tuple(r)) for r in db.conn.execute("SELECT * FROM actions"))
    audit += " ".join(str(tuple(r)) for r in db.conn.execute("SELECT * FROM outbound"))
    assert SECRET_EMAIL not in audit and "Guten Tag" not in audit and "+49 170" not in audit
    logs = caplog.text
    assert SECRET_EMAIL not in logs and "Guten Tag" not in logs


def test_second_send_for_same_flat_is_blocked(tmp_path):
    rng, cfg, db, rec, eng, now = _scenario(1, tmp_path)
    pol = cfg.send_policy.model_copy(update={"mode": "live", "enabled": True, "quiet_hours": None,
                                             "daily_cap": 9, "per_platform_daily_cap": 9,
                                             "kill_switch_file": tmp_path / "none"})
    eng.dispatcher.policy = pol
    eng.config = cfg.model_copy(update={"send_policy": pol})
    lst = Listing(source="immoscout", source_id="D1", url="u", title="Helle Wohnung mit Balkon",
                  warm_rent_eur=1400, cold_rent_eur=1150, area_m2=60, rooms=2, street="Beispielweg 1",
                  postal_code="12345", available_from=date(2027, 1, 15), seen_at=now,
                  contact_email=SECRET_EMAIL)
    first = eng.process(lst, db.ingest(lst))
    twin = lst.model_copy(update={"source": "immowelt", "source_id": "D2"})
    second = eng.process(twin, db.ingest(twin))
    assert first.status == "sent" and second.status == "blocked_duplicate"


def test_scenarios_actually_exercise_sending_and_blocking(tmp_path):
    """Guards against a vacuous invariant test: sends and every kind of block must occur."""
    seen: dict[str, int] = {}
    for i in range(SCENARIOS):
        d = tmp_path / str(i)
        d.mkdir()
        rng, cfg, db, rec, eng, now = _scenario(i, d)
        lst = _listing(rng, i)
        status = eng.process(lst, db.ingest(lst)).status
        seen[status] = seen.get(status, 0) + 1
    assert seen.get("sent", 0) >= 10, seen
    for status in ("skipped", "queued", "shadow_would_send", "blocked_kill_switch",
                   "blocked_quiet_hours", "blocked_daily_cap"):
        assert seen.get(status, 0) >= 1, (status, seen)
