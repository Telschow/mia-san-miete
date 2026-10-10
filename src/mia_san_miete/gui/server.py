"""Local dashboard server (standard library only).

Safety model: binds to loopback by default, every request needs the access token (cookie),
state-changing requests need a custom header (cross-site pages cannot send it) and the Host
header must be one we serve (DNS-rebinding guard). Serve it beyond localhost only through an
SSH tunnel or a private network such as Tailscale: it speaks plain HTTP.
"""

from __future__ import annotations

import hmac
import json
import re
import secrets
from datetime import UTC, datetime
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib import resources
from urllib.parse import parse_qs, urlparse

from ..config import Config
from ..db import Database
from ..presets import UnknownPreset, list_presets
from ..queue import ApprovalQueue, QueueError
from . import api
from .settings import SettingsError, SettingsStore, run_connection_test

COOKIE = "mia_token"
STATIC_FILES = {
    "settings.js": "text/javascript; charset=utf-8",
    "app.css": "text/css; charset=utf-8",
    **{f"fonts/{name}.woff2": "font/woff2" for name in (
        "fraunces-latin-500-normal", "fraunces-latin-600-normal", "ibm-plex-sans-latin-400-normal",
        "ibm-plex-sans-latin-500-normal", "ibm-plex-sans-latin-600-normal",
        "ibm-plex-mono-latin-400-normal", "ibm-plex-mono-latin-500-normal")},
}


class App:
    """The dashboard's state. `store` and `loader` are None in demo mode (settings read-only);
    `cfg` is None until the first-run setup has written a configuration."""

    def __init__(self, cfg: Config | None, db: Database | None, queue: ApprovalQueue | None,
                 token: str | None = None, store: SettingsStore | None = None,
                 loader=None, demo: bool = False) -> None:
        self.cfg, self.db, self.queue = cfg, db, queue
        self.store, self.loader, self.demo = store, loader, demo
        self.token = token or secrets.token_urlsafe(24)
        self.hosts: set[str] = set()

    def reload(self) -> None:
        """Pick up saved settings: new config, dispatcher and queue (no restart needed)."""
        if self.loader is not None:
            self.cfg, self.db, self.queue = self.loader()

    def state(self) -> dict:
        return {"setup": self.cfg is None, "editable": self.store is not None, "demo": self.demo}

    def _flag(self):
        return self.cfg.send_policy.kill_switch_file

    def get(self, path: str, query: dict) -> tuple[int, object]:
        now = datetime.now(UTC)
        if path == "/api/state":
            return 200, self.state()
        if path == "/api/presets":
            return 200, list_presets((query.get("lang") or ["en"])[0])
        if path == "/api/settings/full":
            if self.store is None:
                return 403, {"error": "settings are read-only here"}
            return 200, {**self.store.view(), "state": self.state()}
        if self.cfg is None or self.db is None:
            return 409, {"error": "setup required"}
        if path == "/api/overview":
            size = len(self.queue.items()) if self.queue else 0
            return 200, api.overview(self.cfg, self.db, now, size)
        if path == "/api/queue":
            items = self.queue.items() if self.queue else []
            for it in items:
                it["commute"] = api.queue_commute(self.db, it["action_id"], self.cfg)
            return 200, items
        if path == "/api/listings":
            return 200, api.listings(self.db, (query.get("status") or [None])[0])
        if path == "/api/activity":
            return 200, api.activity(self.db)
        if path == "/api/settings":
            return 200, api.settings_view(self.cfg)
        m = re.fullmatch(r"/api/listing/(\d+)", path)
        if m:
            detail = api.listing_detail(self.db, int(m.group(1)), self.cfg)
            return (200, detail) if detail else (404, {"error": "not found"})
        return 404, {"error": "not found"}

    def post_settings(self, path: str, body: dict) -> tuple[int, object]:
        if self.store is None:
            return 403, {"error": "settings are read-only here"}
        if path == "/api/setup":
            try:
                self.store.setup(body.get("answers") or {}, body.get("preset") or None)
            except (SettingsError, UnknownPreset) as exc:
                return 400, {"error": str(exc)}
            self.reload()
            return 200, {"ok": True}
        if self.cfg is None:
            return 409, {"error": "setup required"}
        if path == "/api/settings":
            result = self.store.patch(body.get("patch") or {}, bool(body.get("confirm_live")))
            if result["ok"]:
                self.reload()
            return (200 if result["ok"] else 400), result
        if path == "/api/secret":
            try:
                self.store.set_secret(str(body.get("name", "")), str(body.get("value", "")))
            except SettingsError as exc:
                return 400, {"error": str(exc)}
            self.reload()
            return 200, {"ok": True}
        if path == "/api/ntfy-topic":
            return 200, {"topic": self.store.new_ntfy_topic()}
        m = re.fullmatch(r"/api/test/(alerts|replies|smtp|ntfy)", path)
        if m:
            return 200, run_connection_test(m.group(1), self.store.view()["config"], self.store.env())
        return 404, {"error": "not found"}

    def post(self, path: str, body: dict) -> tuple[int, object]:
        if path in ("/api/setup", "/api/settings", "/api/secret", "/api/ntfy-topic") or \
                path.startswith("/api/test/"):
            return self.post_settings(path, body)
        if self.cfg is None or self.db is None:
            return 409, {"error": "setup required"}
        if path in ("/api/kill", "/api/resume"):
            if path == "/api/kill":
                self._flag().touch()
            else:
                self._flag().unlink(missing_ok=True)
            return 200, api.policy_status(self.cfg, self.db, datetime.now(UTC))
        m = re.fullmatch(r"/api/queue/(\d+)/(approve|skip|sent-manually)", path)
        if m:
            if self.queue is None:
                return 400, {"error": "profile not loaded; queue actions are unavailable"}
            aid, action = int(m.group(1)), m.group(2)
            try:
                if action == "skip":
                    self.queue.skip(aid)
                    return 200, {"status": "skipped"}
                if action == "sent-manually":
                    return 200, {"status": self.queue.mark_sent(aid).status}
                out = self.queue.approve(aid, body=body.get("body"), subject=body.get("subject"))
            except QueueError as exc:
                return 400, {"error": str(exc)}
            return 200, {"status": out.status}
        return 404, {"error": "not found"}


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "mia-gui"

        def log_message(self, *args):   # request lines can contain ids; keep the console quiet
            pass

        def _send(self, code: int, payload: object, ctype: str = "application/json",
                  headers: dict[str, str] | None = None) -> None:
            raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                             "script-src 'self' 'unsafe-inline'; img-src 'self' data:")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(raw)

        def _host_ok(self) -> bool:
            return self.headers.get("Host", "") in app.hosts

        def _authed(self) -> bool:
            jar = SimpleCookie(self.headers.get("Cookie", ""))
            got = jar[COOKIE].value if COOKIE in jar else ""
            return hmac.compare_digest(got, app.token)

        def do_GET(self):
            if not self._host_ok():
                return self._send(HTTPStatus.FORBIDDEN, {"error": "bad host"})
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if url.path == "/" and query.get("token") and hmac.compare_digest(
                    query["token"][0], app.token):
                return self._send(HTTPStatus.FOUND, b"", "text/plain", {
                    "Location": "/",
                    "Set-Cookie": f"{COOKIE}={app.token}; HttpOnly; SameSite=Strict; Path=/",
                })
            if not self._authed():
                return self._send(HTTPStatus.UNAUTHORIZED, {
                    "error": "open the link printed by `mia gui` (it contains the token)"})
            if url.path.startswith("/static/") and url.path[8:] in STATIC_FILES:
                data = resources.files("mia_san_miete.gui").joinpath(
                    "static/" + url.path[8:]).read_bytes()
                return self._send(200, data, STATIC_FILES[url.path[8:]])
            if url.path == "/":
                page = resources.files("mia_san_miete.gui").joinpath("static/index.html")
                return self._send(200, page.read_bytes(), "text/html; charset=utf-8")
            code, payload = app.get(url.path, query)
            self._send(code, payload)

        def do_POST(self):
            if not (self._host_ok() and self._authed()):
                return self._send(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
            if self.headers.get("X-Mia") != "1":
                return self._send(HTTPStatus.FORBIDDEN, {"error": "missing header"})
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(min(length, 100_000)) or b"{}")
                if not isinstance(body, dict):
                    raise TypeError
            except (ValueError, TypeError):
                return self._send(400, {"error": "bad json"})
            code, payload = app.post(urlparse(self.path).path, body)
            self._send(code, payload)

    return Handler


def settings_editable(host: str, allow_remote: bool = False) -> bool:
    """The settings editor takes passwords, so it is off on non-local addresses (plain HTTP)
    unless the user explicitly allows it."""
    return allow_remote or host in ("127.0.0.1", "localhost", "::1")


def make_server(app: App, host: str = "127.0.0.1", port: int = 8765,
                allow_hosts: list[str] | None = None) -> HTTPServer:
    httpd = HTTPServer((host, port), make_handler(app))
    real = httpd.server_address[1]
    app.hosts = {f"{h}:{real}" for h in ("127.0.0.1", "localhost", host, *(allow_hosts or []))}
    return httpd


def serve(app: App, host: str = "127.0.0.1", port: int = 8765,
          allow_hosts: list[str] | None = None) -> None:
    httpd = make_server(app, host, port, allow_hosts)
    print(f"Mia dashboard: http://{host}:{port}/?token={app.token}")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("WARNING: plain HTTP on a non-local address; use an SSH tunnel or a VPN.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
