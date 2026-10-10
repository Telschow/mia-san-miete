import smtplib
from datetime import UTC, date, datetime, timedelta

import pytest

from mia_san_miete.config import load_config
from mia_san_miete.db import Database
from mia_san_miete.dispatcher import Dispatcher, in_quiet_hours, start_of_day_utc_iso
from mia_san_miete.engine import Engine
from mia_san_miete.models import Listing
from mia_san_miete.pipeline import run_once
from mia_san_miete.providers.base import FixtureProvider
from mia_san_miete.senders.base import SendError
from mia_san_miete.senders.email import EmailSender
from tests.test_p2 import CFG, NOW, FakeRouter

# NOW is Monday 2026-11-02 09:00 UTC = 10:00 Berlin.


def _l(**kw) -> Listing:
    base = {
        "source": "immoscout", "source_id": "1", "url": "u",
        "title": "Helle 2-Zimmer-Wohnung mit Südbalkon in Schwabing",
        "description": "Ruhige Lage, Einbauküche vorhanden.",
        "warm_rent_eur": 1450, "cold_rent_eur": 1200, "area_m2": 60, "rooms": 2,
        "street": "Leopoldstraße", "postal_code": "80802", "district": "Schwabing",
        "available_from": date(2027, 1, 15), "landlord_type": "private", "seen_at": NOW,
        "contact_email": "vermieter@example.test",
    }
    base.update(kw)
    return Listing(**base)


class Recorder:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, listing, draft):
        if self.fail:
            raise SendError("boom")
        self.sent.append((listing.source_id, draft.subject))


def _policy(tmp_path, **kw):
    update = {
        "enabled": True, "mode": "live", "platform_allow_list": ["immoscout"],
        "kill_switch_file": tmp_path / "KILL", "min_score": 50,
        "loosen": CFG.send_policy.loosen.model_copy(update={"floor": 40}),
    }
    update.update(kw)
    return CFG.send_policy.model_copy(update=update)


def _engine(tmp_path, profile, db, recorder, clock=lambda: NOW, **policy_kw):
    policy = _policy(tmp_path, **policy_kw)
    cfg = CFG.model_copy(update={"send_policy": policy})
    disp = Dispatcher(policy, db, {"immoscout": recorder})
    eng = Engine(
        cfg, profile, disp, FakeRouter("pt", 20.0), FakeRouter("car", 20.0), None,
        live_since=date(2026, 11, 1), clock=clock,
    )
    return eng, disp


def _go(eng, db, listing):
    return eng.process(listing, db.ingest(listing))


def _statuses(db):
    return [r["status"] for r in db.conn.execute("SELECT status FROM actions ORDER BY id")]


def test_live_auto_send_happy_path_and_audit_is_content_free(tmp_path, profile):
    db, rec = Database(), Recorder()
    eng, _ = _engine(tmp_path, profile, db, rec)
    assert _go(eng, db, _l()).status == "sent"
    assert rec.sent == [("1", "Anfrage zu Ihrer Wohnung in Schwabing, 2 Zimmer, ab 15.01.2027")]
    row = db.conn.execute("SELECT * FROM actions").fetchone()
    assert row["score"] > 50 and row["template_version"] == "1" and row["used_llm"] == 0
    assert "Guten Tag" not in " ".join(str(v) for v in tuple(row))   # no message body stored


def test_shadow_mode_never_sends(tmp_path, profile):
    db, rec = Database(), Recorder()
    eng, _ = _engine(tmp_path, profile, db, rec, mode="shadow")
    assert _go(eng, db, _l()).status == "shadow_would_send"
    assert rec.sent == []


def test_disabled_policy_queues_for_approval(tmp_path, profile):
    db, rec = Database(), Recorder()
    eng, _ = _engine(tmp_path, profile, db, rec, enabled=False)
    assert _go(eng, db, _l()).status == "queued" and rec.sent == []


def test_hard_gate_rejects_are_skipped_and_review_is_queued(tmp_path, profile):
    db, rec = Database(), Recorder()
    eng, _ = _engine(tmp_path, profile, db, rec)
    assert _go(eng, db, _l(source_id="2", warm_rent_eur=2500)).status == "skipped"
    assert _go(eng, db, _l(source_id="3", street="Andere Str 1", available_from=None,
                           area_m2=70, postal_code="80939")).status == "queued"
    assert rec.sent == []


def test_kill_switch_blocks_sending(tmp_path, profile):
    db, rec = Database(), Recorder()
    eng, _ = _engine(tmp_path, profile, db, rec)
    (tmp_path / "KILL").write_text("")
    assert _go(eng, db, _l()).status == "blocked_kill_switch" and rec.sent == []


def test_daily_and_platform_caps(tmp_path, profile):
    db, rec = Database(), Recorder()
    eng, _ = _engine(tmp_path, profile, db, rec, daily_cap=2, per_platform_daily_cap=2)
    flats = [_l(source_id=str(i), area_m2=60 + 5 * i, street=f"Weg {i}") for i in range(3)]
    out = [_go(eng, db, f).status for f in flats]
    assert out == ["sent", "sent", "blocked_daily_cap"]
    eng2, _ = _engine(tmp_path, profile, Database(), Recorder(), daily_cap=5,
                      per_platform_daily_cap=1)
    db2 = eng2.dispatcher.db
    assert [_go(eng2, db2, f).status for f in flats[:2]] == ["sent", "blocked_platform_cap"]


def test_cap_resets_next_day(tmp_path, profile):
    db, rec = Database(), Recorder()
    t = {"now": NOW}
    eng, _ = _engine(tmp_path, profile, db, rec, clock=lambda: t["now"],
                     daily_cap=1, per_platform_daily_cap=1)
    a = _l(source_id="a")
    b = _l(source_id="b", area_m2=75, street="Weg 2")
    assert _go(eng, db, a).status == "sent"
    assert _go(eng, db, b).status == "blocked_daily_cap"
    t["now"] = NOW + timedelta(days=1)
    c = _l(source_id="c", area_m2=90, street="Weg 3")
    assert _go(eng, db, c).status == "sent"


def test_same_flat_is_sent_only_once_across_portals(tmp_path, profile):
    db, rec = Database(), Recorder()
    eng, _ = _engine(tmp_path, profile, db, rec)
    first = _l()
    assert _go(eng, db, first).status == "sent"
    dup = _l(source="immoscout", source_id="9")        # same flat, new id, same canonical
    res = db.ingest(dup)
    assert not res.is_new_flat
    out = eng.process(dup, res)
    assert out.status == "blocked_duplicate" and len(rec.sent) == 1


def test_quiet_hours(tmp_path, profile):
    assert in_quiet_hours("22:00-07:00", datetime(2026, 11, 2, 22, 30, tzinfo=UTC))   # 23:30
    assert in_quiet_hours("22:00-07:00", datetime(2026, 11, 2, 4, 0, tzinfo=UTC))     # 05:00
    assert not in_quiet_hours("22:00-07:00", NOW)
    assert not in_quiet_hours(None, NOW)
    db, rec = Database(), Recorder()
    night = datetime(2026, 11, 2, 22, 30, tzinfo=UTC)
    eng, _ = _engine(tmp_path, profile, db, rec, clock=lambda: night, quiet_hours="22:00-07:00")
    assert _go(eng, db, _l()).status == "blocked_quiet_hours"


def test_repeated_failures_pause_the_platform(tmp_path, profile):
    db, rec = Database(), Recorder(fail=True)
    eng, _ = _engine(tmp_path, profile, db, rec, daily_cap=50, per_platform_daily_cap=50)
    flats = [_l(source_id=str(i), area_m2=60 + 5 * i, street=f"Weg {i}") for i in range(5)]
    assert [_go(eng, db, f).status for f in flats] == [
        "failed", "failed", "failed", "blocked_platform_failures", "blocked_platform_failures"
    ]


def test_no_sender_for_platform_is_blocked(tmp_path, profile):
    db = Database()
    policy = _policy(tmp_path, platform_allow_list=["kleinanzeigen"])
    cfg = CFG.model_copy(update={"send_policy": policy})
    eng = Engine(cfg, profile, Dispatcher(policy, db, {}), FakeRouter("pt", 20.0),
                 FakeRouter("car", 20.0), None, date(2026, 11, 1), lambda: NOW)
    listing = _l(source="kleinanzeigen")
    assert _go(eng, db, listing).status == "blocked_no_sender"


def test_pipeline_runs_engine_per_new_flat_and_survives_engine_errors(tmp_path, profile):
    db, rec = Database(), Recorder()
    eng, _ = _engine(tmp_path, profile, db, rec, mode="shadow")
    fixture = "tests/fixtures/listings.json"
    stats = run_once([FixtureProvider(fixture)], db, None, on_new_flat=eng.process)
    assert stats.new_flats == 3 and len(_statuses(db)) == 3

    def boom(listing, result):
        raise RuntimeError("bug")

    stats2 = run_once([FixtureProvider(fixture)], Database(), None, on_new_flat=boom)
    assert stats2.new_flats == 3     # discovery continued despite the failing callback


def test_email_sender_uses_smtp_and_wraps_errors(profile):
    log = []

    class FakeSmtp:
        def __init__(self, host, port):
            log.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            log.append("tls")

        def login(self, u, p):
            log.append(("login", u))

        def send_message(self, msg):
            log.append(("msg", msg["To"], msg["Subject"]))

    from mia_san_miete.messaging.generator import generate_draft

    draft = generate_draft(_l(), profile, None)
    s = EmailSender("smtp.test", 587, "user", "pw", "me@test", smtp_factory=FakeSmtp)
    s.send(_l(), draft)
    assert log[0] == ("connect", "smtp.test", 587) and "tls" in log
    assert log[-1][1] == "vermieter@example.test"
    with pytest.raises(SendError):
        s.send(_l(contact_email=None), draft)

    class Down(FakeSmtp):
        def login(self, u, p):
            raise smtplib.SMTPAuthenticationError(535, b"no")

    with pytest.raises(SendError):
        EmailSender("h", 1, "u", "p", "f", smtp_factory=Down).send(_l(), draft)


def test_start_of_day_is_berlin_midnight_in_utc():
    assert start_of_day_utc_iso(NOW) == "2026-11-01T23:00:00+00:00"   # CET = UTC+1


def test_load_config_still_valid():
    assert load_config("config.example.yaml").send_policy.enabled is False
