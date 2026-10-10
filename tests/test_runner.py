from datetime import UTC, datetime

import yaml

from mia_san_miete.config import load_config
from mia_san_miete.db import Database
from mia_san_miete.providers.alert_email import AlertEmailProvider
from mia_san_miete.replies import IncomingMail
from mia_san_miete.runner import SafeRouter, build_engine, run_cycle
from tests.conftest import ROOT
from tests.test_p2 import FakeRouter

NOW = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
BODY = """Gute Wohnung am Park
1.450 € warm, 60 m², 2 Zimmer, 80802
https://www.immobilienscout24.de/expose/111
Zu teuer
2.900 € warm, 60 m², 2 Zimmer, 80802
https://www.immobilienscout24.de/expose/222
"""


class Box:
    def fetch_recent(self, since):
        return [IncomingMail("<m>", "Treffer", BODY, "a@portal.test", [], NOW, {})]


class Raising:
    mode = "pt"

    def minutes(self, *a):
        raise OSError("down")


def _cfg(tmp_path):
    raw = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    raw["send_policy"]["kill_switch_file"] = str(tmp_path / "KILL")
    raw["send_policy"]["enabled"] = True            # shadow mode: logs would-be sends only
    raw["send_policy"]["platform_allow_list"] = ["immoscout"]
    raw["send_policy"]["min_score"] = 10
    raw["send_policy"]["loosen"]["floor"] = 10
    raw["storage"]["db_path"] = str(tmp_path / "db.sqlite")
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return load_config(p)


def test_shadow_cycle_audits_everything_and_sends_nothing(tmp_path, profile):
    cfg, db = _cfg(tmp_path), Database()
    engine = build_engine(cfg, profile, db, {}, lambda: NOW,
                          pt=FakeRouter("pt", 15.0), car=FakeRouter("car", 15.0))
    prov = AlertEmailProvider(Box(), ["portal.test"], clock=lambda: NOW)
    stats = run_cycle(engine, db, [prov], None)
    assert stats.new_flats == 2
    statuses = {r["source_id"]: r["status"] for r in
                db.conn.execute("SELECT source_id, status FROM actions")}
    assert statuses["222"] == "skipped"                    # rent far over the limit
    assert statuses["111"] in ("shadow_would_send", "queued")
    assert db.count_actions("sent", "") == 0
    run_cycle(engine, db, [prov], None)                    # second cycle: nothing new
    assert db.conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0] == 2


def test_routing_outage_degrades_to_unknown_not_lost(tmp_path, profile):
    cfg, db = _cfg(tmp_path), Database()
    engine = build_engine(cfg, profile, db, {}, lambda: NOW,
                          pt=SafeRouter(Raising()), car=FakeRouter("car", 15.0))
    prov = AlertEmailProvider(Box(), ["portal.test"], clock=lambda: NOW)
    run_cycle(engine, db, [prov], None)
    row = db.conn.execute("SELECT status FROM actions WHERE source_id = '111'").fetchone()
    assert row["status"] == "queued"                       # commute unknown -> review


def test_first_action_date_anchors_threshold_schedule():
    db = Database()
    assert db.first_action_date() is None
