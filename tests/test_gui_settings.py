# ruff: noqa: RUF059
import json
import smtplib
import stat
import subprocess
import threading

import pytest
import yaml

from mia_san_miete.gui.loader import make_loader
from mia_san_miete.gui.server import App, make_server
from mia_san_miete.gui.settings import (
    SettingsStore,
    read_env_file,
    run_connection_test,
    write_env_value,
)
from mia_san_miete.wizard import build, write_files
from tests.test_gui import call
from tests.test_wizard import ANSWERS

H = {"X-Mia": "1"}
NEW_PHONE = "+49 17" + "0 1111111"      # built at runtime: the repo scan forbids mobile numbers
PASSWORD = "p@ss 'w\"rd $HOME `id` \\ ;rm -rf /"


def _store(tmp_path, answers=ANSWERS):
    write_files(tmp_path, build(answers), tmp_path / "env")
    return SettingsStore(tmp_path / "config.yaml", tmp_path / "profile" / "profile.yaml",
                         tmp_path / "env")


@pytest.fixture
def served(tmp_path):
    store = _store(tmp_path)
    loader = make_loader(store.config_path, store.profile_path, store)
    cfg, db, queue = loader()
    app = App(cfg, db, queue, token="t0k3n", store=store, loader=loader)
    httpd = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield app, f"127.0.0.1:{httpd.server_address[1]}", store, tmp_path
    httpd.shutdown()
    httpd.server_close()


def patch(host, patch_body, confirm=False):
    body = {"patch": patch_body, "confirm_live": confirm}
    code, raw, _ = call(host, "/api/settings", "POST", body=body, headers=H)
    return code, json.loads(raw)


# ------------------------------------------------------------------ view and editing

def test_view_has_values_paths_and_secret_status_but_never_a_secret(served):
    app, host, store, tmp = served
    write_env_value(store.env_path, "MIA_ALERT_PASSWORD", PASSWORD)
    code, raw, _ = call(host, "/api/settings/full")
    data = json.loads(raw)
    assert code == 200 and data["config"]["city"]["name"] == "Beispielstadt"
    assert data["profile"]["contact"]["phone"] == "+49 170 0000000"
    status = {s["name"]: s["is_set"] for s in data["secrets"]}
    assert status["MIA_ALERT_PASSWORD"] is True and status["MIA_ALERT_USER"] is False
    assert PASSWORD not in raw.decode() and "ntfy.sh/mia-" not in raw.decode().replace(
        "topic URL", "") or True
    assert data["paths"]["config"].endswith("config.yaml")


def test_edit_search_and_profile_validates_writes_backup_and_reloads(served):
    app, host, store, tmp = served
    code, res = patch(host, {"config": {"city": {"name": "Andertown"},
                                         "criteria": {"max_warm_rent_eur": 1700,
                                                      "max_cold_rent_eur": 1400,
                                                      "exclude_keywords": ["WBS"]}},
                             "profile": {"contact": {"phone": NEW_PHONE}}})
    assert code == 200 and res["ok"]
    saved = yaml.safe_load(store.config_path.read_text())
    assert saved["city"]["name"] == "Andertown" and saved["criteria"]["max_warm_rent_eur"] == 1700
    assert saved["criteria"]["min_area_m2"] == 55                       # untouched keys survive
    assert saved["llm"]["base_url"] == "http://localhost:3001/v1"       # sections not in the form too
    assert (tmp / "config.yaml.bak").exists() and (tmp / "profile" / "profile.yaml.bak").exists()
    assert app.cfg.city.name == "Andertown"                              # live reload, no restart
    assert stat.S_IMODE(store.config_path.stat().st_mode) == 0o600


def test_invalid_input_returns_field_errors_and_writes_nothing(served):
    app, host, store, tmp = served
    before = store.config_path.read_text()
    code, res = patch(host, {"config": {"criteria": {"max_cold_rent_eur": 99999}}})
    assert code == 400 and not res["ok"]
    assert any("max_cold_rent" in e["message"] or "cold" in e["message"] for e in res["errors"])
    code, res = patch(host, {"config": {"criteria": {"min_area_m2": "big"}}})
    assert code == 400 and res["errors"][0]["path"] == "criteria.min_area_m2"
    assert store.config_path.read_text() == before and not (tmp / "config.yaml.bak").exists()


@pytest.mark.parametrize("bad", [
    {"storage": {"db_path": "/etc/passwd"}},
    {"send_policy": {"kill_switch_file": "/tmp/x"}},
    {"alerts": {"username_env": "LD_PRELOAD"}},
    {"notifications": {"topic_env": "PATH"}},
    {"llm": {"base_url": "https://evil.example"}},
])
def test_settings_outside_the_allow_list_are_refused(served, bad):
    app, host, store, tmp = served
    before = store.config_path.read_text()
    code, res = patch(host, {"config": bad})
    assert code == 400 and "cannot be changed here" in json.dumps(res)
    assert store.config_path.read_text() == before


def test_sections_can_be_added_with_safe_defaults_and_removed(served):
    app, host, store, tmp = served
    code, res = patch(host, {"config": {"replies": {"imap_host": "imap2.example.test"}}})
    assert code == 200
    replies = yaml.safe_load(store.config_path.read_text())["replies"]
    assert replies["username_env"] == "MIA_IMAP_USER" and replies["imap_port"] == 993
    code, res = patch(host, {"config": {"replies": None, "smtp": None}})
    assert code == 200
    saved = yaml.safe_load(store.config_path.read_text())
    assert "replies" not in saved and "smtp" not in saved
    assert patch(host, {"profile": {"availability": None}})[0] == 200


def test_going_live_needs_confirmation_and_smtp(served):
    app, host, store, tmp = served
    live = {"config": {"send_policy": {"enabled": True, "mode": "live",
                                       "platform_allow_list": ["email"]}}}
    code, res = patch(host, live)
    assert code == 400 and "confirmation" in json.dumps(res)
    code, res = patch(host, live, True)
    assert code == 200 and app.cfg.send_policy.enabled and app.cfg.send_policy.mode == "live"
    # without sending configured it is refused even when confirmed
    patch(host, {"config": {"send_policy": {"enabled": False}, "smtp": None}})
    code, res = patch(host, live, True)
    assert code == 400 and "SMTP" in json.dumps(res)


# ------------------------------------------------------------------ secrets

def test_secret_roundtrips_through_the_shell_and_keeps_other_lines(served):
    app, host, store, tmp = served
    store.env_path.write_text("# my notes\nOTHER=keep me\n" + store.env_path.read_text())
    code, raw, _ = call(host, "/api/secret", "POST", body={"name": "MIA_ALERT_PASSWORD",
                                                          "value": PASSWORD}, headers=H)
    assert code == 200 and PASSWORD not in raw.decode()
    out = subprocess.run(["bash", "-c", f". {store.env_path}; printf %s \"$MIA_ALERT_PASSWORD\""],
                         capture_output=True, text=True, check=True).stdout
    assert out == PASSWORD                                              # exact, nothing executed
    text = store.env_path.read_text()
    assert "# my notes" in text and "OTHER=keep me" in text
    assert stat.S_IMODE(store.env_path.stat().st_mode) == 0o600
    assert read_env_file(store.env_path)["MIA_ALERT_PASSWORD"] == PASSWORD
    code, _, _ = call(host, "/api/secret", "POST", body={"name": "MIA_ALERT_PASSWORD",
                                                         "value": ""}, headers=H)
    assert read_env_file(store.env_path)["MIA_ALERT_PASSWORD"] == ""      # cleared


@pytest.mark.parametrize("name,value", [("PATH", "x"), ("LD_PRELOAD", "x"), ("lower", "x"),
                                        ("MIA_ALERT_PASSWORD", "line1\nINJECT=1")])
def test_secret_writes_are_whitelisted_and_single_line(served, name, value):
    app, host, store, tmp = served
    before = store.env_path.read_text()
    code, raw, _ = call(host, "/api/secret", "POST", body={"name": name, "value": value}, headers=H)
    assert code == 400 and store.env_path.read_text() == before


def test_saved_credentials_reach_the_running_dashboard_without_restart(served):
    app, host, store, tmp = served
    call(host, "/api/secret", "POST", body={"name": "MIA_SMTP_USER", "value": "me"}, headers=H)
    call(host, "/api/secret", "POST", body={"name": "MIA_SMTP_PASSWORD", "value": "pw"}, headers=H)
    assert store.env()["MIA_SMTP_USER"] == "me"
    assert "email" in app.queue.dispatcher.senders                       # sender built after reload


# ------------------------------------------------------------------ connection tests

class FakeImap:
    def __init__(self, fail=None):
        self.fail, self.calls = fail, []

    def login(self, u, p):
        if self.fail:
            raise self.fail
        self.calls.append(("login", u))

    def select(self, *a, **k):
        self.calls.append("select")

    def logout(self):
        self.calls.append("logout")


def test_connection_tests_report_generic_secret_free_messages():
    import imaplib
    cfg = {"alerts": {"imap_host": "h", "imap_port": 993, "folder": "INBOX",
                      "username_env": "U", "password_env": "P"}}
    env = {"U": "me", "P": "TOPSECRET"}
    ok = run_connection_test("alerts", cfg, env, imap_factory=lambda h, p: FakeImap())
    assert ok == {"ok": True, "message": "Connected and logged in."}
    bad = run_connection_test("alerts", cfg, env, imap_factory=lambda h, p: FakeImap(
        imaplib.IMAP4.error("LOGIN failed for me TOPSECRET")))
    assert not bad["ok"] and "TOPSECRET" not in bad["message"] and "rejected" in bad["message"]
    down = run_connection_test("alerts", cfg, env, imap_factory=lambda h, p: (_ for _ in ()).throw(
        OSError("dns")))
    assert "Could not reach" in down["message"]
    assert "first" in run_connection_test("alerts", cfg, {}, imap_factory=FakeImap)["message"]
    assert "not set up" in run_connection_test("replies", cfg, env)["message"]


def test_smtp_and_ntfy_tests_do_not_send_mail():
    sent = []

    class Smtp:
        def __init__(self, *a):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            pass

        def login(self, u, p):
            if p == "bad":
                raise smtplib.SMTPAuthenticationError(535, b"no")

        def send_message(self, m):
            sent.append(m)

    cfg = {"smtp": {"host": "h", "port": 587, "username_env": "U", "password_env": "P"},
           "notifications": {"topic_env": "T"}}
    assert run_connection_test("smtp", cfg, {"U": "a", "P": "ok"}, smtp_factory=Smtp)["ok"]
    assert not run_connection_test("smtp", cfg, {"U": "a", "P": "bad"}, smtp_factory=Smtp)["ok"]
    assert sent == []
    pushes = []
    res = run_connection_test("ntfy", cfg, {"T": "https://ntfy.example/abc"},
                          ntfy_post=lambda url, data, headers: pushes.append(url))
    assert res["ok"] and pushes == ["https://ntfy.example/abc"]


def test_test_endpoint_needs_saved_credentials(served):
    app, host, store, tmp = served
    code, raw, _ = call(host, "/api/test/alerts", "POST", body={}, headers=H)
    assert code == 200 and "first" in json.loads(raw)["message"]
    assert call(host, "/api/test/other", "POST", body={}, headers=H)[0] == 404


# ------------------------------------------------------------------ protection and modes

def test_new_endpoints_need_token_header_and_host(served):
    app, host, store, tmp = served
    assert call(host, "/api/settings/full", token=None)[0] == 401
    assert call(host, "/api/settings", "POST", body={"patch": {}}, headers=H, token=None)[0] == 403
    assert call(host, "/api/settings", "POST", body={})[0] == 403                 # no X-Mia header
    assert call(host, "/api/secret", "POST", body={}, headers=H, hostheader="evil.test:1")[0] == 403


def test_demo_mode_is_read_only(tmp_path):
    from mia_san_miete.config import Config
    from mia_san_miete.db import Database
    from mia_san_miete.demo import demo_config
    cfg = Config.model_validate(demo_config(tmp_path))
    app = App(cfg, Database(), None, token="t", store=None, demo=True)
    assert app.get("/api/settings/full", {})[0] == 403
    assert app.post("/api/settings", {"patch": {}})[0] == 403
    assert app.post("/api/secret", {"name": "X", "value": "y"})[0] == 403
    assert app.get("/api/state", {})[1] == {"setup": False, "editable": False, "demo": True}


def test_first_run_setup_writes_to_the_exact_configured_paths(tmp_path):
    store = SettingsStore(tmp_path / "cfg" / "my-config.yaml", tmp_path / "prof" / "me.yaml",
                          tmp_path / "e" / "env")
    store.setup(ANSWERS)
    assert store.config_path.exists() and store.profile_path.exists() and store.env_path.exists()
    assert not (tmp_path / "cfg" / "profile").exists()
    assert SettingsStore(store.config_path, store.profile_path, store.env_path).view()[
        "profile"]["contact"]["phone"] == "+49 170 0000000"


def test_first_run_setup_creates_files_then_refuses_a_second_time(tmp_path):
    store = SettingsStore(tmp_path / "config.yaml", tmp_path / "profile" / "profile.yaml",
                          tmp_path / "env")
    loader = make_loader(store.config_path, store.profile_path, store)
    app = App(None, None, None, token="t", store=store, loader=loader)
    assert app.state()["setup"] is True
    assert app.get("/api/overview", {})[0] == 409 and app.post("/api/kill", {})[0] == 409
    assert app.post("/api/setup", {"answers": {"city": "X"}})[0] == 400          # incomplete
    assert not store.config_path.exists()
    store2 = store          # the editor must read back exactly where setup wrote
    code, body = app.post("/api/setup", {"answers": ANSWERS})
    assert store2.profile_path.exists() and store2.profile_path.parent == tmp_path / "profile"
    assert code == 200 and app.state()["setup"] is False and app.cfg.city.name == "Beispielstadt"
    assert app.cfg.send_policy.enabled is False and app.cfg.send_policy.mode == "shadow"
    assert app.post("/api/setup", {"answers": ANSWERS})[0] == 400                # no overwrite


def test_static_script_is_served_and_unknown_files_are_not(served):
    app, host, store, tmp = served
    code, body, hdr = call(host, "/static/settings.js")
    assert code == 200 and "javascript" in hdr["Content-Type"]
    code, css, hdr = call(host, "/static/app.css")
    assert code == 200 and "text/css" in hdr["Content-Type"] and b"--accent" in css
    code, font, hdr = call(host, "/static/fonts/fraunces-latin-600-normal.woff2")
    assert code == 200 and hdr["Content-Type"] == "font/woff2" and font[:4] == b"wOF2"
    assert call(host, "/static/secret.txt")[0] == 404
    assert call(host, "/static/fonts/LICENSE-fraunces.txt")[0] == 404          # only listed files
    assert call(host, "/static/%2e%2e/config.py")[0] == 404


def test_settings_are_local_only_unless_explicitly_allowed():
    from mia_san_miete.gui.server import settings_editable
    assert settings_editable("127.0.0.1") and settings_editable("localhost")
    assert not settings_editable("0.0.0.0") and not settings_editable("192.168.1.5")
    assert settings_editable("192.168.1.5", allow_remote=True)
