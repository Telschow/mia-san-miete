"""Settings editor behind the dashboard: change your own config, profile and credentials.

Everything stays on this machine, in the same files the command line uses (config.yaml,
profile.yaml and the env file). Rules:

* Only an allow-list of settings can be changed. Paths (database, kill-switch file), the
  names of environment variables and anything not listed are refused, so a request cannot
  point Mia at other files.
* Every change is validated with the real Config and Profile models before it is written, so
  an invalid form can never leave you with a config that will not load.
* Writes are atomic and keep a `.bak` of the previous file. Comments in the YAML are not kept.
* Credentials go to the env file only (mode 600, shell-quoted because the scheduler sources
  it), are write-only (the API never returns a value, only whether one is stored) and only the
  variable names your config already uses are accepted.
* Switching on live sending needs an explicit confirmation and a configured SMTP account.
"""

from __future__ import annotations

import copy
import imaplib
import os
import re
import secrets as _secrets
import shlex
import smtplib
import socket
import ssl
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ..config import Config
from ..net import ssl_context
from ..notify import NtfyNotifier
from ..presets import preset_answers
from ..profile import Profile
from ..wizard import WizardError, build, write_files

ALLOWED_CONFIG = [
    "city.name", "criteria",
    "commute.targets", "commute.combine", "commute.borderline_margin_minutes",
    "commute.pt_router", "commute.motis_base_url",
    "send_policy.enabled", "send_policy.mode", "send_policy.min_score", "send_policy.loosen",
    "send_policy.daily_cap", "send_policy.per_platform_daily_cap",
    "send_policy.platform_allow_list", "send_policy.quiet_hours",
    "notifications.channel", "notifications.heartbeat_hours", "notifications.silence_alert_hours",
    "alerts.imap_host", "alerts.imap_port", "alerts.folder", "alerts.lookback_days",
    "alerts.sender_domains",
    "replies.imap_host", "replies.imap_port", "replies.folder", "replies.lookback_days",
    "smtp.host", "smtp.port", "smtp.from_address",
    "reply_llm.enabled", "reply_llm.base_url", "reply_llm.model", "reply_llm.timeout_seconds",
    "auto_reply.enabled", "auto_reply.mode", "auto_reply.daily_cap",
    "auto_reply.max_replies_per_thread", "auto_reply.horizon_days",
    "scoring.weights",
]
ALLOWED_PROFILE = ["applicants", "contact.phone", "contact.sender_email", "facts", "viewing",
                   "move_in", "availability"]
REMOVABLE_CONFIG = {"alerts", "replies", "smtp", "auto_reply", "reply_llm"}
REMOVABLE_PROFILE = {"availability"}
SECTION_DEFAULTS: dict[str, dict[str, Any]] = {
    "alerts": {"username_env": "MIA_ALERT_USER", "password_env": "MIA_ALERT_PASSWORD",
               "imap_port": 993, "folder": "INBOX"},
    "replies": {"username_env": "MIA_IMAP_USER", "password_env": "MIA_IMAP_PASSWORD",
                "imap_port": 993, "folder": "INBOX"},
    "smtp": {"username_env": "MIA_SMTP_USER", "password_env": "MIA_SMTP_PASSWORD", "port": 587},
}
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
MAX_SECRET_LENGTH = 4096


class SettingsError(Exception):
    """A refused or invalid change; the message is safe to show to the user."""


def _allowed(path: str, allowed: list[str]) -> bool:
    return any(path == a or path.startswith(a + ".") for a in allowed)


def _write_atomic(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _backup(path: Path, new_text: str) -> None:
    if path.exists() and path.read_text(encoding="utf-8") != new_text:
        _write_atomic(path.with_name(path.name + ".bak"), path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ env file

def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not Path(path).exists():
        return values
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Z][A-Z0-9_]*)=(.*)$", line)
        if not m:
            continue
        try:
            parts = shlex.split(m.group(2))
        except ValueError:
            parts = [m.group(2)]
        values[m.group(1)] = parts[0] if parts else ""
    return values


def write_env_value(path: Path, name: str, value: str) -> None:
    """Set NAME in the env file (shell-quoted), keeping every other line as it is."""
    lines = Path(path).read_text(encoding="utf-8").splitlines() if Path(path).exists() else []
    new = f"{name}={shlex.quote(value) if value else ''}"
    for i, line in enumerate(lines):
        if re.match(rf"^\s*{re.escape(name)}=", line):
            lines[i] = new
            break
    else:
        lines.append(new)
    _write_atomic(Path(path), "\n".join(lines) + "\n", 0o600)


# ------------------------------------------------------------------ store

class SettingsStore:
    def __init__(self, config_path: Path, profile_path: Path, env_path: Path) -> None:
        self.config_path, self.profile_path = Path(config_path), Path(profile_path)
        self.env_path = Path(env_path).expanduser()

    # ---------------------------------------------------------------- reading
    def _load(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}

    def exists(self) -> bool:
        return self.config_path.exists()

    def secret_specs(self, config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        cfg = config if config is not None else self._load(self.config_path)
        specs: list[dict[str, Any]] = []
        for section, label in (("alerts", "Alert inbox"), ("replies", "Reply inbox"),
                               ("smtp", "Sending (SMTP)")):
            sec = cfg.get(section) if isinstance(cfg.get(section), dict) else {}
            d = SECTION_DEFAULTS[section]
            specs.append({"name": sec.get("username_env", d["username_env"]),
                          "label": f"{label}: username", "section": section, "secret": False})
            specs.append({"name": sec.get("password_env", d["password_env"]),
                          "label": f"{label}: password", "section": section, "secret": True})
        n = cfg.get("notifications", {}) or {}
        specs.append({"name": n.get("topic_env", "NTFY_TOPIC"), "section": "notifications",
                      "label": "ntfy topic URL (anyone who knows it can read your notifications)",
                      "secret": True})
        specs.append({"name": (cfg.get("commute", {}) or {}).get("car_api_key_env",
                                                                 "GOOGLE_ROUTES_API_KEY"),
                      "label": "Google Routes API key (only for car commute limits)",
                      "section": "commute", "secret": True})
        rl = cfg.get("reply_llm")
        if isinstance(rl, dict) and rl.get("api_key_env"):
            specs.append({"name": rl["api_key_env"], "label": "Local reply model: API key",
                          "section": "reply_llm", "secret": True})
        return specs

    def view(self) -> dict[str, Any]:
        config = self._load(self.config_path)
        env = read_env_file(self.env_path)
        secrets_view = [{**s, "is_set": bool(env.get(s["name"]))} for s in self.secret_specs(config)]
        return {"config": config, "profile": self._load(self.profile_path),
                "secrets": secrets_view,
                "paths": {"config": str(self.config_path), "profile": str(self.profile_path),
                          "env": str(self.env_path),
                          "database": (config.get("storage") or {}).get("db_path", "")}}

    # ---------------------------------------------------------------- patching
    def _apply(self, raw: dict[str, Any], patch: dict[str, Any], prefix: str,
               allowed: list[str], removable: set[str], defaults: dict[str, Any],
               errors: list[dict[str, str]], label: str) -> None:
        for key, value in patch.items():
            path = f"{prefix}.{key}" if prefix else key
            if prefix == "" and value is None and key in removable:
                raw.pop(key, None)
                continue
            if isinstance(value, dict) and value:
                if not isinstance(raw.get(key), dict):
                    raw[key] = copy.deepcopy(defaults.get(key, {})) if prefix == "" else {}
                self._apply(raw[key], value, path, allowed, removable, defaults, errors, label)
                continue
            if not _allowed(path, allowed):
                errors.append({"path": f"{label}{path}", "message": "cannot be changed here"})
                continue
            if value is None:
                raw.pop(key, None)
            else:
                raw[key] = value

    def patch(self, patch: dict[str, Any], confirm_live: bool = False) -> dict[str, Any]:
        cfg_before, prof_before = self._load(self.config_path), self._load(self.profile_path)
        cfg, prof = copy.deepcopy(cfg_before), copy.deepcopy(prof_before)
        errors: list[dict[str, str]] = []
        self._apply(cfg, patch.get("config") or {}, "", ALLOWED_CONFIG, REMOVABLE_CONFIG,
                    SECTION_DEFAULTS, errors, "")
        self._apply(prof, patch.get("profile") or {}, "", ALLOWED_PROFILE, REMOVABLE_PROFILE,
                    {}, errors, "profile.")
        if errors:
            return {"ok": False, "errors": errors}

        def live(c: dict[str, Any]) -> bool:
            sp = c.get("send_policy") or {}
            return bool(sp.get("enabled")) and sp.get("mode") == "live"

        if live(cfg) and not live(cfg_before):
            if not confirm_live:
                errors.append({"path": "send_policy.enabled",
                               "message": "switching to live sending needs your explicit confirmation"})
            if "smtp" not in cfg:
                errors.append({"path": "send_policy.enabled",
                               "message": "configure sending (SMTP) before enabling live sending"})
        errors += self._validate(cfg, prof)
        if errors:
            return {"ok": False, "errors": errors}
        cfg_text = yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False)
        _backup(self.config_path, cfg_text)
        _write_atomic(self.config_path, cfg_text)
        if prof != prof_before or not self.profile_path.exists():
            prof_text = yaml.safe_dump(prof, allow_unicode=True, sort_keys=False)
            _backup(self.profile_path, prof_text)
            _write_atomic(self.profile_path, prof_text)
        return {"ok": True}

    @staticmethod
    def _validate(cfg: dict[str, Any], prof: dict[str, Any]) -> list[dict[str, str]]:
        errors: list[dict[str, str]] = []
        for model, data, prefix in ((Config, cfg, ""), (Profile, prof, "profile.")):
            if model is Profile and not data:
                continue
            try:
                model.model_validate(data)
            except ValidationError as exc:
                for e in exc.errors():
                    loc = ".".join(str(x) for x in e["loc"])
                    msg = e["msg"].removeprefix("Value error, ")
                    errors.append({"path": f"{prefix}{loc}", "message": msg})
        return errors

    # ---------------------------------------------------------------- secrets
    def set_secret(self, name: str, value: str) -> None:
        names = {s["name"] for s in self.secret_specs()}
        if not ENV_NAME.match(name) or name not in names:
            raise SettingsError("unknown setting")
        if "\n" in value or "\r" in value or "\x00" in value or len(value) > MAX_SECRET_LENGTH:
            raise SettingsError("that value cannot be stored")
        write_env_value(self.env_path, name, value)

    def new_ntfy_topic(self, server: str = "https://ntfy.sh") -> str:
        return f"{server.rstrip('/')}/mia-{_secrets.token_urlsafe(12)}"

    def env(self) -> dict[str, str]:
        """Process environment overlaid with the env file (what a scheduled run would see)."""
        return {**os.environ, **{k: v for k, v in read_env_file(self.env_path).items() if v}}

    # ---------------------------------------------------------------- first run
    def setup(self, answers: dict[str, Any], preset: dict[str, str] | None = None) -> None:
        if self.exists():
            raise SettingsError("a configuration already exists; edit it in Settings instead")
        if preset:      # your answers win; the preset fills in the facts and defaults you left out
            answers = {**preset_answers(preset.get("city"), preset.get("household")), **answers}
        try:
            built = build(answers)
            write_files(self.config_path.parent, built, self.env_path, force=False,
                        config_path=self.config_path, profile_path=self.profile_path)
        except (WizardError, OSError) as exc:
            raise SettingsError(str(exc)) from exc


# ------------------------------------------------------------------ connection tests

def _generic(exc: BaseException) -> str:
    if isinstance(exc, (imaplib.IMAP4.error, smtplib.SMTPAuthenticationError)):
        return "The server rejected the login. Check username and password."
    if isinstance(exc, ssl.SSLError):
        return "Secure connection failed. Check host and port."
    if isinstance(exc, (socket.gaierror, TimeoutError, ConnectionError, OSError)):
        return "Could not reach the server. Check host, port and your network."
    return "The connection test failed."


def run_connection_test(
    kind: str, cfg: dict[str, Any], env: dict[str, str],
    imap_factory: Callable[[str, int], Any] = lambda h, p: imaplib.IMAP4_SSL(
        h, p, timeout=10, ssl_context=ssl_context()),
    smtp_factory: Callable[[str, int], Any] = lambda h, p: smtplib.SMTP(h, p, timeout=10),
    ntfy_post: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Try a login or a test push with the stored settings. Never returns secrets or raw errors."""
    try:
        if kind in ("alerts", "replies"):
            sec = cfg.get(kind)
            if not isinstance(sec, dict):
                return {"ok": False, "message": "This inbox is not set up yet."}
            user, pw = env.get(sec["username_env"]), env.get(sec["password_env"])
            if not user or not pw:
                return {"ok": False, "message": "Enter and save the username and password first."}
            conn = imap_factory(sec["imap_host"], int(sec.get("imap_port", 993)))
            try:
                conn.login(user, pw)
                conn.select(sec.get("folder", "INBOX"), readonly=True)
            finally:
                try:
                    conn.logout()
                except (imaplib.IMAP4.error, OSError):
                    pass
            return {"ok": True, "message": "Connected and logged in."}
        if kind == "smtp":
            sec = cfg.get("smtp")
            if not isinstance(sec, dict):
                return {"ok": False, "message": "Sending is not set up yet."}
            user, pw = env.get(sec["username_env"]), env.get(sec["password_env"])
            if not user or not pw:
                return {"ok": False, "message": "Enter and save the username and password first."}
            with smtp_factory(sec["host"], int(sec.get("port", 587))) as smtp:
                smtp.starttls()
                smtp.login(user, pw)
            return {"ok": True, "message": "Connected and logged in. No message was sent."}
        if kind == "ntfy":
            topic = env.get((cfg.get("notifications") or {}).get("topic_env", "NTFY_TOPIC"))
            if not topic:
                return {"ok": False, "message": "Save a topic URL first."}
            notifier = NtfyNotifier(topic, ntfy_post) if ntfy_post else NtfyNotifier(topic)
            notifier.send("Mia test", "Your notifications work.")
            return {"ok": True, "message": "Test notification sent. Check your phone."}
    except Exception as exc:  # noqa: BLE001 - map every failure to a generic, secret-free message
        return {"ok": False, "message": _generic(exc)}
    return {"ok": False, "message": "Unknown test."}
