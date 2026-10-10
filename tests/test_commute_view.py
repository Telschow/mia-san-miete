# ruff: noqa: RUF059
import json

from mia_san_miete.db import Database
from mia_san_miete.gui.api import commute_view, listing_detail
from mia_san_miete.queue import ApprovalQueue
from tests.test_p2 import CFG
from tests.test_p4 import NOW, Recorder, _engine, _go, _l


def test_engine_stores_commute_minutes_with_the_decision(tmp_path, profile):
    db, rec = Database(), Recorder()
    eng, _ = _engine(tmp_path, profile, db, rec, enabled=False)
    _go(eng, db, _l())
    row = db.conn.execute("SELECT commute FROM actions").fetchone()
    data = json.loads(row["commute"])
    assert data["times"]["work_a"]["pt"] == 20.0 and data["estimated"] is False
    assert "Marienplatz" not in row["commute"]                    # minutes only, no places


def test_commute_view_joins_limits_and_leaves_places_out():
    raw = json.dumps({"times": {"work_a": {"pt": 25.0, "car": None},
                                "work_b": {"pt": 38.0, "car": 30.0}}, "estimated": True})
    view = commute_view(raw, CFG)
    assert view["estimated"] is True and view["combine"] == "all"
    a, b = view["targets"]
    assert (a["name"], a["pt"], a["max_pt"], a["max_car"]) == ("work_a", 25.0, 30, None)
    assert (b["max_pt"], b["max_car"], b["modes"]) == (40, 35, "any")
    text = json.dumps(view)
    assert "Marienplatz" not in text and "Ostbahnhof" not in text
    assert commute_view(None, CFG) is None and commute_view("not json", CFG) is None


def test_detail_includes_commute_and_old_rows_degrade(tmp_path, profile):
    db, rec = Database(), Recorder()
    eng, _ = _engine(tmp_path, profile, db, rec, enabled=False)
    _go(eng, db, _l())
    aid = db.conn.execute("SELECT id FROM actions").fetchone()["id"]
    assert listing_detail(db, aid, CFG)["commute"]["targets"][0]["pt"] == 20.0
    db.conn.execute("UPDATE actions SET commute = NULL")           # a row from before this feature
    assert listing_detail(db, aid, CFG)["commute"] is None
    assert listing_detail(db, aid)["commute"] is None              # no config given


def test_approved_send_keeps_the_original_commute(tmp_path, profile):
    db, rec = Database(), Recorder()
    eng, disp = _engine(tmp_path, profile, db, rec, enabled=False)
    _go(eng, db, _l())
    queue = ApprovalQueue(db, disp, profile)
    assert queue.approve(queue.items()[0]["action_id"], NOW).status == "sent"
    rows = db.conn.execute("SELECT commute FROM actions ORDER BY id").fetchall()
    assert rows[0]["commute"] and rows[0]["commute"] == rows[1]["commute"]
