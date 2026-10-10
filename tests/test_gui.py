# ruff: noqa: RUF059  (tuple unpacking of test fixtures)
import json
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime

import pytest

from mia_san_miete.config import load_config
from mia_san_miete.db import Database
from mia_san_miete.demo import (
    build_demo_dispatcher,
    build_demo_responder,
    seed,
    write_demo_files,
)
from mia_san_miete.gui.server import App, make_server
from mia_san_miete.profile import load_profile
from mia_san_miete.queue import ApprovalQueue

NOW = datetime.now(UTC)


@pytest.fixture
def served(tmp_path):
    cfg_path, prof_path = write_demo_files(tmp_path)
    cfg, profile = load_config(cfg_path), load_profile(prof_path)
    db = Database(cfg.storage.db_path, check_same_thread=False)
    seed(db, cfg, profile, NOW)
    queue = ApprovalQueue(db, build_demo_dispatcher(cfg, db), profile,
                          build_demo_responder(cfg, db, profile))
    app = App(cfg, db, queue, token="t0k3n")
    httpd = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield app, f"127.0.0.1:{httpd.server_address[1]}", cfg
    httpd.shutdown()
    httpd.server_close()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def call(host, path, method="GET", token="t0k3n", body=None, headers=None, hostheader=None):
    req = urllib.request.Request(f"http://{host}{path}", method=method,
                                 data=None if body is None else json.dumps(body).encode())
    req.add_header("Host", hostheader or host)
    if token:
        req.add_header("Cookie", f"mia_token={token}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def test_requires_token_and_valid_host(served):
    _, host, _ = served
    assert call(host, "/api/overview", token=None)[0] == 401
    assert call(host, "/api/overview", token="wrong")[0] == 401
    assert call(host, "/api/overview", hostheader="evil.example:80")[0] == 403
    code, _, hdr = call(host, "/?token=t0k3n", token=None)
    assert code == 302 and "HttpOnly" in hdr["Set-Cookie"] and "SameSite=Strict" in hdr["Set-Cookie"]
    assert call(host, "/?token=bad", token=None)[0] == 401


def test_pages_and_read_api(served):
    app, host, _ = served
    code, body, hdr = call(host, "/")
    assert code == 200 and b"Mia san Miete" in body and "default-src 'self'" in hdr["Content-Security-Policy"]
    ov = json.loads(call(host, "/api/overview")[1])
    assert ov["demo"] is True and ov["queue_size"] == 6 and ov["metrics"]["sent"] > 0
    rows = json.loads(call(host, "/api/listings?status=queued")[1])
    assert len(rows) == 5 and all(r["status"] == "queued" for r in rows)
    detail = json.loads(call(host, f"/api/listing/{rows[0]['id']}")[1])
    assert detail["breakdown"] and "contact_email" not in detail["listing"]
    assert call(host, "/api/listing/99999")[0] == 404
    settings = call(host, "/api/settings")[1].decode()
    assert "Hauptbahnhof" not in settings and "example.test" not in settings


def test_post_needs_custom_header_and_works(served):
    app, host, cfg = served
    first = json.loads(call(host, "/api/queue")[1])[0]["action_id"]
    assert call(host, f"/api/queue/{first}/skip", "POST", body={})[0] == 403   # no X-Mia header
    code, body, _ = call(host, f"/api/queue/{first}/skip", "POST", body={}, headers={"X-Mia": "1"})
    assert code == 200 and json.loads(body)["status"] == "skipped"
    nxt = json.loads(call(host, "/api/queue")[1])[0]
    code, body, _ = call(host, f"/api/queue/{nxt['action_id']}/approve", "POST",
                         body={"body": "zu kurz"}, headers={"X-Mia": "1"})
    assert code == 400 and "rejected" in json.loads(body)["error"]
    code, body, _ = call(host, f"/api/queue/{nxt['action_id']}/approve", "POST", body={},
                         headers={"X-Mia": "1"})
    assert code == 200 and json.loads(body)["status"] == "sent"


def test_kill_and_resume(served):
    app, host, cfg = served
    flag = cfg.send_policy.kill_switch_file
    h = {"X-Mia": "1"}
    assert json.loads(call(host, "/api/kill", "POST", body={}, headers=h)[1])["kill_switch"] is True
    assert flag.exists()
    aid = json.loads(call(host, "/api/queue")[1])[0]["action_id"]
    out = json.loads(call(host, f"/api/queue/{aid}/approve", "POST", body={}, headers=h)[1])
    assert out["status"] == "blocked_kill_switch"
    assert json.loads(call(host, "/api/resume", "POST", body={}, headers=h)[1])["kill_switch"] is False


def test_demo_is_deterministic_and_fictional(tmp_path):
    cfg_path, prof_path = write_demo_files(tmp_path)
    cfg, profile = load_config(cfg_path), load_profile(prof_path)
    db = Database()
    seed(db, cfg, profile, NOW, seed_value=3)
    texts = " ".join(str(tuple(r)) for t in ("listings", "drafts", "actions")
                     for r in db.conn.execute(f"SELECT * FROM {t}"))
    assert "Beispielstadt" in texts or "Beispielweg" in texts
    assert db.count_actions("queued", "") == 5


def test_sent_manually_through_the_dashboard(served):
    app, host, cfg = served
    items = json.loads(call(host, "/api/queue")[1])
    first = next(i for i in items if i["kind"] == "application")["action_id"]
    assert call(host, f"/api/queue/{first}/sent-manually", "POST", body={})[0] == 403     # needs X-Mia
    code, body, _ = call(host, f"/api/queue/{first}/sent-manually", "POST", body={}, headers={"X-Mia": "1"})
    assert code == 200 and json.loads(body)["status"] == "sent_manually"
    assert first not in [i["action_id"] for i in json.loads(call(host, "/api/queue")[1])]
    code, body, _ = call(host, f"/api/queue/{first}/sent-manually", "POST", body={}, headers={"X-Mia": "1"})
    assert code == 400                                                                    # already resolved
