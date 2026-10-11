"""`mia init`: guided setup that writes your private files and nothing else.

Safe by construction: it only creates the gitignored files (config.yaml, profile/profile.yaml,
.private-terms and the env file), always starts in shadow mode with sending disabled, validates
everything with the real models before writing, and refuses to overwrite without --force.
Secrets are never asked for: the env file is written with empty placeholders (plus a freshly
generated ntfy topic) for you to fill in.
"""

from __future__ import annotations

import re
import secrets
import shutil
import sys
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .config import Config
from .privacy import HOOK
from .profile import Profile

DEFAULT_EXCLUDES = ["WBS", "Tausch", "Wohnungstausch", "Tauschwohnung", "Wohngemeinschaft",
                    "Gewerbe"]
DEFAULT_FACTS: list[dict[str, Any]] = [
    {"id": "household", "de": "ein junges Paar ohne Kinder und ohne Haustiere",
     "en": "a young couple without children or pets", "usage": "always"},
    {"id": "employers", "de": "Wir sind beide fest angestellt",
     "en": "We are both in permanent employment", "usage": "always"},
    {"id": "income", "de": "unser Einkommen ist stabil und nachweisbar",
     "en": "our income is stable and documented", "usage": "always"},
    {"id": "character", "de": "Wir sind ruhig, ordentlich und zuverlässig",
     "en": "We are quiet, tidy and reliable", "usage": "always"},
    {"id": "landlord_reference", "de": "eine Empfehlung unseres bisherigen Vermieters",
     "en": "a reference from our previous landlord", "usage": "on_request"},
]
DEFAULT_VIEWING = {"de": "werktags ab 17:30 Uhr und am Wochenende jederzeit",
                   "en": "on weekdays from 5:30 pm and at any time on weekends"}
REQUIRED = ("city", "max_warm_rent", "targets", "applicants", "phone", "imap_host",
            "sender_domains")


class WizardError(Exception):
    """Bad answers or an unsafe write; the message is safe to show."""


# ---------------------------------------------------------------- prompting

class Prompter:
    def __init__(self, ask: Callable[[str], str] = input,
                 say: Callable[[str], None] = print) -> None:
        self._ask, self.say = ask, say

    def text(self, question: str, default: str | None = None, required: bool = False,
             check: Callable[[str], str | None] | None = None,
             yes_keeps_default: bool = False) -> str:
        suffix = f" [{default}]" if default not in (None, "") else ""
        while True:
            try:
                raw = self._ask(f"{question}{suffix}: ").strip()
            except EOFError as exc:
                raise WizardError("input ended before the questions were answered") from exc
            if yes_keeps_default and raw.lower() in ("y", "yes", "j", "ja"):
                raw = ""                      # 'Y' meant 'keep it', not the new wording
            value = raw or (default or "")
            if required and not value:
                self.say("  This one is required.")
                continue
            problem = check(value) if (check and value) else None
            if problem:
                self.say(f"  {problem}")
                continue
            return value

    def number(self, question: str, default: float | None = None, minimum: float = 0,
               as_int: bool = True, required: bool = True) -> float | None:
        def check(v: str) -> str | None:
            try:
                n = float(v.replace(",", "."))
            except ValueError:
                return "Please enter a number."
            return None if n >= minimum else f"Must be at least {minimum:g}."
        raw = self.text(question, None if default is None else f"{default:g}",
                        required=required, check=check)
        if not raw:
            return None
        n = float(raw.replace(",", "."))
        return int(n) if as_int else n

    def yes(self, question: str, default: bool = True) -> bool:
        hint = "Y/n" if default else "y/N"
        raw = self.text(f"{question} ({hint})", "", check=lambda v: None if v.lower() in
                        ("y", "yes", "j", "ja", "n", "no", "nein") else "Please answer y or n.")
        return default if not raw else raw.lower() in ("y", "yes", "j", "ja")


def _date(value: str) -> str | None:
    try:
        date.fromisoformat(value)
    except ValueError:
        return "Use the format YYYY-MM-DD, for example 2027-01-01."
    return None


def _hhmm(value: str) -> str | None:
    return None if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value) else "Use HH:MM, for example 09:00."


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_") or "target"


def _csv(value: str) -> list[str]:
    return [x.strip() for x in value.split(",") if x.strip()]


# ---------------------------------------------------------------- interactive collection

def collect(p: Prompter, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    d = defaults or {}
    say = p.say
    say("\nMia san Miete setup. Press Enter to accept the value in brackets.")
    say("Everything is written to gitignored files; nothing is sent anywhere. Sending stays "
        "disabled and shadow mode stays on.\n")
    a: dict[str, Any] = {}

    say("1/5  Your search")
    a["city"] = p.text("City", d.get("city"), required=True)
    a["max_warm_rent"] = p.number("Maximum warm rent (EUR per month)", 1600, 1)
    a["max_cold_rent"] = p.number("Maximum cold rent (EUR)", round(a["max_warm_rent"] * 0.85, -1), 1)
    while a["max_cold_rent"] > a["max_warm_rent"]:
        say("  Cold rent cannot exceed warm rent.")
        a["max_cold_rent"] = p.number("Maximum cold rent (EUR)", a["max_warm_rent"], 1)
    a["min_area"] = p.number("Minimum size (m2)", d.get("min_area", 50), 1)
    a["min_rooms"] = p.number("Minimum rooms", d.get("min_rooms", 2), 0.5, as_int=False)
    a["move_in_from"] = p.text("Ideal move-in date", str(date.today() + timedelta(days=90)),
                               check=_date)
    a["move_in_latest"] = p.text("Latest move-in date", str(date.fromisoformat(a["move_in_from"])
                                                             + timedelta(days=30)), check=_date)
    a["exclude_keywords"] = _csv(p.text("Words that exclude a flat, comma separated",
                                        ", ".join(d.get("exclude_keywords", DEFAULT_EXCLUDES))))
    a["min_lease_months"] = p.number("Minimum lease length (months; not enforced yet: only sublets are rejected, unknown is accepted)",
                                     d.get("min_lease_months", 24), 0)

    say("\n2/5  Places you travel to (work, university)")
    if d.get("center_hint"):
        say(f"  Tip: write addresses the way a route planner finds them, for example "
            f'"{d["center_hint"]}".')
    targets = []
    while True:
        name = _slug(p.text("Short name for this place", f"place_{len(targets) + 1}"))
        dest = p.text("Address or station, as a routing service would find it", required=True)
        arrive = p.text("Weekday morning arrival time", "09:00", check=_hhmm)
        pt = p.number("Maximum public-transport minutes (0 for no limit)", 30, 0)
        car = p.number("Maximum car minutes (0 for no limit)", 0, 0)
        if not pt and not car:
            say("  Set at least one limit for this place.")
            continue
        t: dict[str, Any] = {"name": name, "destination": dest, "arrival_time": arrive}
        if pt:
            t["max_pt_minutes"] = pt
        if car:
            t["max_car_minutes"] = car
        if pt and car:
            t["modes"] = "any" if p.yes("Is one of the two within its limit enough?", True) else "all"
        targets.append(t)
        if not p.yes("Add another place?", False):
            break
    a["targets"] = targets
    a["combine"] = "all"
    if len(targets) > 1:
        a["combine"] = "all" if p.yes("Must every place pass (no = one is enough)?", True) else "any"

    say("\n  Optional limits on where the flat is (leave blank for none)")
    km = p.number("Maximum straight-line distance from the center (km)", None, 0.5, as_int=False,
                  required=False)
    if km:
        a["area_max_km"] = km
        a["area_center"] = p.text("Center (address or station)", d.get("area_center"), required=True)
    walk = p.number("Maximum walk to the nearest metro, S-Bahn or tram stop (minutes)", None, 1,
                    required=False)
    if walk:
        a["station_max_walk"] = walk
        a["station_required"] = p.yes("Reject flats with a longer walk (no: it only changes the score)?", False)

    say("\n3/5  About you (a message may state only the facts you keep here)")
    applicants = []
    while True:
        first = p.text("First name", required=True)
        last = p.text("Last name", required=True)
        age = p.number("Age (optional, 0 to leave out)", 0, 0, required=False)
        applicants.append({"first_name": first, "last_name": last, **({"age": age} if age else {})})
        if not p.yes("Add another applicant?", len(applicants) < int(d.get("applicants_hint", 1))):
            break
    a["applicants"] = applicants
    a["phone"] = p.text("Phone number landlords can call", required=True)
    say("  Each fact below can appear in messages. Keep, edit or drop it; German and English "
        "text are both needed.")
    facts = []
    for f in d.get("facts", DEFAULT_FACTS):
        if not p.yes(f"Keep fact '{f['id']}': \"{f['de']}\"?", True):
            continue
        de = p.text("  German wording", f["de"], yes_keeps_default=True)
        en = p.text("  English wording", f["en"], yes_keeps_default=True)
        facts.append({**f, "de": de, "en": en})
    a["facts"] = facts
    a["viewing_de"] = p.text("When can you view flats (German, finishing the sentence "
                             "'Besichtigungen sind bei uns ... moeglich')", DEFAULT_VIEWING["de"],
                             yes_keeps_default=True)
    a["viewing_en"] = p.text("Same in English ('We can attend viewings ...')", DEFAULT_VIEWING["en"],
                             yes_keeps_default=True)
    if p.yes("Set weekly viewing availability for the optional automatic reply later?", False):
        a["availability"] = {
            "weekday_start": p.text("Weekdays from", "17:30", check=_hhmm),
            "weekday_end": p.text("Weekdays until", "20:00", check=_hhmm),
            "weekend_start": p.text("Weekends from", "09:00", check=_hhmm),
            "weekend_end": p.text("Weekends until", "20:00", check=_hhmm),
        }

    say("\n4/5  Mail (no passwords are asked for here)")
    a["imap_host"] = p.text("IMAP host of the inbox that receives your portal alerts", required=True)
    a["imap_folder"] = p.text("Folder", "INBOX")
    a["sender_domains"] = _csv(p.text("Domains the alerts come from, comma separated "
                                      "(only mail from these is read)", required=True))
    a["replies_host"] = p.text("IMAP host of the inbox that gets landlord replies (blank to skip)", "")
    a["smtp_host"] = p.text("SMTP host for sending (blank to skip for now)", "")
    if a["smtp_host"]:
        a["smtp_from"] = p.text("Sender address", required=True)

    say("\n5/5  Notifications")
    a["ntfy_server"] = p.text("ntfy server", "https://ntfy.sh")
    return a


# ---------------------------------------------------------------- building the files

def complete(answers: dict[str, Any]) -> dict[str, Any]:
    """Fill defaults for optional keys; fail with a list of missing required ones."""
    missing = [k for k in REQUIRED if not answers.get(k)]
    if missing:
        raise WizardError("missing answers: " + ", ".join(missing))
    a = dict(answers)
    warm = float(a["max_warm_rent"])
    a.setdefault("max_cold_rent", round(warm * 0.85, -1))
    a.setdefault("min_area", 50)
    a.setdefault("min_rooms", 2)
    a.setdefault("move_in_from", str(date.today() + timedelta(days=90)))
    a.setdefault("move_in_latest", str(date.fromisoformat(str(a["move_in_from"])) + timedelta(days=30)))
    a.setdefault("exclude_keywords", DEFAULT_EXCLUDES)
    a.setdefault("min_lease_months", 24)
    a.setdefault("combine", "all")
    a.setdefault("facts", DEFAULT_FACTS)
    a.setdefault("viewing_de", DEFAULT_VIEWING["de"])
    a.setdefault("viewing_en", DEFAULT_VIEWING["en"])
    a.setdefault("imap_folder", "INBOX")
    a.setdefault("ntfy_server", "https://ntfy.sh")
    return a


def build(answers: dict[str, Any]) -> dict[str, Any]:
    """Pure: answers in, validated config dict, profile dict, env text and private terms out."""
    a = complete(answers)
    config: dict[str, Any] = {
        "city": {"name": a["city"]},
        "criteria": {
            "max_warm_rent_eur": int(a["max_warm_rent"]), "max_cold_rent_eur": int(a["max_cold_rent"]),
            "min_area_m2": int(a["min_area"]), "min_rooms": float(a["min_rooms"]),
            "move_in": {"ideal_from": str(a["move_in_from"]), "latest": str(a["move_in_latest"]),
                        "early_flex_days": 31},
            "exclude_keywords": list(a["exclude_keywords"]),
            "min_lease_months": int(a["min_lease_months"]),
            "nice_to_have": ["balcony", "parking"],
        },
        "commute": {"combine": a["combine"], "borderline_margin_minutes": 5, "pt_router": "motis",
                    "car_router": "google_routes", "targets": a["targets"]},
        "send_policy": {
            "enabled": False, "mode": "shadow", "min_score": 85,
            "loosen": {"step_points": 5, "every_days": 3, "floor": 70},
            "daily_cap": 10, "per_platform_daily_cap": 5, "platform_allow_list": [],
            "quiet_hours": None, "kill_switch_file": "./KILL",
        },
        "llm": {"base_url": "http://localhost:3001/v1", "api_key_env": "FREELLMAPI_KEY",
                "timeout_seconds": 6, "log_answering_model": True},
        "notifications": {"channel": "ntfy", "topic_env": "NTFY_TOPIC", "heartbeat_hours": 24},
        "alerts": {"imap_host": a["imap_host"], "imap_port": 993, "folder": a["imap_folder"],
                   "username_env": "MIA_ALERT_USER", "password_env": "MIA_ALERT_PASSWORD",
                   "lookback_days": 3, "sender_domains": list(a["sender_domains"])},
        "storage": {"db_path": "./data/housing.db"},
    }
    if a.get("area_max_km") or a.get("area_include") or a.get("area_exclude_postal"):
        area: dict[str, Any] = {}
        if a.get("area_center"):
            area["center"] = a["area_center"]
        if a.get("area_max_km"):
            area["max_km"] = float(a["area_max_km"])
        config["criteria"]["area"] = area
    if a.get("station_max_walk"):
        config["criteria"]["station"] = {"max_walk_minutes": int(a["station_max_walk"]),
                                         "required": bool(a.get("station_required", False))}
        config["scoring"] = {"version": "1", "weights": {"station": 5}}
    if a.get("replies_host"):
        config["replies"] = {"imap_host": a["replies_host"], "imap_port": 993, "folder": "INBOX",
                             "username_env": "MIA_IMAP_USER", "password_env": "MIA_IMAP_PASSWORD",
                             "lookback_days": 30}
    if a.get("smtp_host"):
        config["smtp"] = {"host": a["smtp_host"], "port": 587, "username_env": "MIA_SMTP_USER",
                          "password_env": "MIA_SMTP_PASSWORD", "from_address": a["smtp_from"]}

    profile: dict[str, Any] = {
        "applicants": a["applicants"],
        "contact": {"phone": a["phone"], "sender_email": a.get("smtp_from", "")},
        "facts": a["facts"],
        "viewing": {"de": a["viewing_de"], "en": a["viewing_en"]},
        "move_in": {"earliest": str(a["move_in_from"]), "latest": str(a["move_in_latest"]),
                    "reason": ""},
    }
    if a.get("availability"):
        av = a["availability"]
        profile["availability"] = {
            "windows": [
                {"days": ["mon", "tue", "wed", "thu", "fri"], "start": av["weekday_start"],
                 "end": av["weekday_end"]},
                {"days": ["sat", "sun"], "start": av["weekend_start"], "end": av["weekend_end"]}],
            "viewing_minutes": 30, "min_notice_hours": 12}
    try:
        Config.model_validate(config)
        Profile.model_validate(profile)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(x) for x in first["loc"])
        raise WizardError(f"these answers are not valid ({where}): {first['msg']}") from exc

    topic = f"{a['ntfy_server'].rstrip('/')}/mia-{secrets.token_urlsafe(12)}"
    env_lines = ["# Secrets for Mia. Keep this file private (chmod 600); never commit it."]
    env_lines += [f"{k}=" for k in ("MIA_ALERT_USER", "MIA_ALERT_PASSWORD")]
    if "replies" in config:
        env_lines += [f"{k}=" for k in ("MIA_IMAP_USER", "MIA_IMAP_PASSWORD")]
    if "smtp" in config:
        env_lines += [f"{k}=" for k in ("MIA_SMTP_USER", "MIA_SMTP_PASSWORD")]
    env_lines += [f"NTFY_TOPIC={topic}", "FREELLMAPI_KEY=", "GOOGLE_ROUTES_API_KEY="]
    return {"config": config, "profile": profile, "env": "\n".join(env_lines) + "\n",
            "terms": private_terms(a)}


def private_terms(a: dict[str, Any]) -> list[str]:
    """Terms the leak scan should block, derived from the answers (the user can edit them)."""
    terms: list[str] = []
    for ap in a["applicants"]:
        terms += [ap["last_name"], f"{ap['first_name']} {ap['last_name']}"]
    phone = str(a["phone"]).strip()
    terms += [phone, re.sub(r"\D", "", phone)]
    for t in a["targets"]:
        dest = t["destination"].strip()
        terms += [dest, dest.split(",")[0].strip()]
    for f in a["facts"]:
        for text in (f["de"], f["en"]):
            terms += re.findall(r"\d[\d.,]{3,}\d", text)             # income figures and similar
    seen: set[str] = set()
    out = []
    for t in terms:
        key = t.lower()
        if len(t) >= 4 and key not in seen:
            seen.add(key)
            out.append(t)
    return out


# ---------------------------------------------------------------- writing

def _backup_or_refuse(path: Path, force: bool) -> None:
    if not path.exists():
        return
    if not force:
        raise WizardError(f"{path} already exists; nothing was written (use --force to keep a "
                          ".bak copy and overwrite)")
    shutil.copy2(path, path.with_name(path.name + ".bak"))


def write_files(root: Path, built: dict[str, Any], env_file: Path, force: bool = False,
                config_path: Path | None = None, profile_path: Path | None = None
                ) -> list[tuple[Path, str]]:
    """Write the four files. By default under `root`; the dashboard passes the exact paths its
    own settings point at, so what it writes is what it reads back."""
    root = Path(root)
    targets = {
        "config": Path(config_path) if config_path else root / "config.yaml",
        "profile": Path(profile_path) if profile_path else root / "profile" / "profile.yaml",
        "terms": root / ".private-terms", "env": Path(env_file).expanduser(),
    }
    for path in targets.values():
        _backup_or_refuse(path, force)
    written: list[tuple[Path, str]] = []
    for key in ("config", "profile"):
        path = targets[key]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(built[key], allow_unicode=True, sort_keys=False),
                        encoding="utf-8")
        written.append((path, "written"))
    existing = targets["terms"].read_text(encoding="utf-8").split("\n") if (
        targets["terms"].exists() and force) else []
    merged = [t for t in existing if t.strip()]
    merged += [t for t in built["terms"] if t not in merged]
    targets["terms"].write_text("\n".join(merged) + "\n", encoding="utf-8")
    written.append((targets["terms"], "written"))
    env = targets["env"]
    env.parent.mkdir(parents=True, exist_ok=True)
    env.write_text(built["env"], encoding="utf-8")
    env.chmod(0o600)
    written.append((env, "written, mode 600"))
    return written


def install_hook(root: Path) -> Path | None:
    git_dir = Path(root) / ".git"
    if not git_dir.exists():
        return None
    hook = git_dir / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(HOOK.format(python=sys.executable), encoding="utf-8")
    hook.chmod(0o755)
    return hook
