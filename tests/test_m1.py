# ruff: noqa: RUF059  (tuple unpacking of test fixtures)
from datetime import UTC, datetime, timedelta

import pytest

from mia_san_miete.db import Database
from mia_san_miete.health import Health
from mia_san_miete.pipeline import RunStats
from mia_san_miete.queue import ApprovalQueue, QueueError
from mia_san_miete.report import shadow_report
from tests.test_p4 import NOW, Recorder, _engine, _go, _l, _statuses


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body, url=None):
        self.sent.append((title, body))


def _queued(tmp_path, profile, **policy_kw):
    db, rec = Database(), Recorder()
    eng, disp = _engine(tmp_path, profile, db, rec, enabled=False, **policy_kw)
    assert _go(eng, db, _l()).status == "queued"
    return db, rec, disp, ApprovalQueue(db, disp, profile)


def test_queued_draft_is_stored_apart_from_audit(tmp_path, profile):
    db, rec, disp, queue = _queued(tmp_path, profile)
    (item,) = queue.items()
    assert "Guten Tag" in item["body"] and item["listing"]["source_id"] == "1"
    audit = " ".join(str(tuple(r)) for r in db.conn.execute("SELECT * FROM actions"))
    assert "Guten Tag" not in audit


def test_approve_sends_and_resolves(tmp_path, profile):
    db, rec, disp, queue = _queued(tmp_path, profile)
    out = queue.approve(queue.items()[0]["action_id"], NOW)
    assert out.status == "sent" and len(rec.sent) == 1
    assert queue.items() == [] and _statuses(db) == ["queued", "sent"]
    with pytest.raises(QueueError):
        queue.approve(1, NOW)                      # already resolved


def test_approve_respects_guards_and_shadow_mode(tmp_path, profile):
    db, rec, disp, queue = _queued(tmp_path, profile)
    (tmp_path / "KILL").write_text("")
    aid = queue.items()[0]["action_id"]
    assert queue.approve(aid, NOW).status == "blocked_kill_switch" and rec.sent == []
    assert len(queue.items()) == 1                 # still pending, nothing duplicated
    (tmp_path / "KILL").unlink()

    db2, rec2, _, queue2 = _queued(tmp_path, profile, mode="shadow")
    assert queue2.approve(queue2.items()[0]["action_id"], NOW).status == "not_sent_shadow_mode"
    assert rec2.sent == [] and len(queue2.items()) == 1


def test_edited_message_is_validated(tmp_path, profile):
    db, rec, disp, queue = _queued(tmp_path, profile)
    aid = queue.items()[0]["action_id"]
    with pytest.raises(QueueError):
        queue.approve(aid, NOW, body="Zu kurz")
    edited = queue.items()[0]["body"] + " Wir freuen uns auf Ihre Antwort."
    assert queue.approve(aid, NOW, body=edited).status == "sent"


def test_skip_and_purge(tmp_path, profile):
    db, rec, disp, queue = _queued(tmp_path, profile)
    queue.skip(queue.items()[0]["action_id"], NOW)
    assert queue.items() == [] and rec.sent == []
    assert queue.purge(NOW + timedelta(days=31)) == 1
    assert db.conn.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 0


def test_heartbeat_silence_and_failure_alerts():
    db, notes = Database(), Notes()
    t = [datetime(2026, 11, 2, 9, 0, tzinfo=UTC)]
    h = Health(db, notes, heartbeat_hours=24, silence_hours=48, clock=lambda: t[0])
    h.after_cycle(RunStats(fetched=3))                 # first run only starts the clocks
    assert notes.sent == []
    t[0] += timedelta(hours=25)
    h.after_cycle(RunStats(fetched=0))
    assert [n[0] for n in notes.sent] == ["Mia: alive"]
    t[0] += timedelta(hours=30)                        # 55 h without listings
    h.after_cycle(RunStats(fetched=0))
    assert "Mia: no new listings" in [n[0] for n in notes.sent]
    n = len(notes.sent)
    h.after_cycle(RunStats(failed_providers=["alert_email"]))
    h.after_cycle(RunStats(failed_providers=["alert_email"]))   # cooldown: only one alert
    assert [x[0] for x in notes.sent[n:]] == ["Mia: cycle problem"]


def test_notifier_outage_never_breaks_the_cycle():
    class Down:
        def send(self, *a, **k):
            raise OSError("down")
    h = Health(Database(), Down(), 1, 1)
    h.failure("x")                                      # must not raise


def test_shadow_report_sections(tmp_path, profile):
    db, rec = Database(), Recorder()
    eng, _ = _engine(tmp_path, profile, db, rec, mode="shadow")
    _go(eng, db, _l())
    _go(eng, db, _l(source_id="2", warm_rent_eur=2500))
    text = shadow_report(db, 14, NOW)
    assert "2 flats processed" in text and "Would have been sent" in text
    assert "Skipped, highest score first" in text and "immoscout/2" in text
    assert "@" not in text                              # no addresses in the report


def test_sent_manually_is_recorded_clears_the_card_and_blocks_a_second_send(tmp_path, profile):
    db, rec, disp, queue = _queued(tmp_path, profile)
    aid = queue.items()[0]["action_id"]
    out = queue.mark_sent(aid, NOW)
    assert out.status == "sent_manually" and rec.sent == []               # nothing is sent by Mia
    assert queue.items() == [] and _statuses(db) == ["queued", "sent_manually"]
    row = db.conn.execute("SELECT * FROM actions WHERE status = 'sent_manually'").fetchone()
    assert "Guten Tag" not in " ".join(str(v) for v in tuple(row))        # still content-free
    with pytest.raises(QueueError):
        queue.mark_sent(aid, NOW)                                         # already resolved
    twin = _l(source_id="2")                                              # the same physical flat again
    eng, _ = _engine(tmp_path, profile, db, rec, enabled=True)
    assert _go(eng, db, twin).status == "blocked_duplicate"
