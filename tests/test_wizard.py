import stat
from pathlib import Path

import pytest
import yaml

from mia_san_miete.cli import main
from mia_san_miete.config import load_config
from mia_san_miete.profile import load_profile
from mia_san_miete.wizard import (
    Prompter,
    WizardError,
    build,
    collect,
    install_hook,
    private_terms,
    write_files,
)

ANSWERS = {
    "city": "Beispielstadt", "max_warm_rent": 1500, "min_area": 55, "min_rooms": 2.5,
    "move_in_from": "2027-02-01", "move_in_latest": "2027-03-01",
    "targets": [{"name": "work", "destination": "Beispielplatz 1, Beispielstadt",
                 "arrival_time": "08:30", "max_pt_minutes": 35}],
    "applicants": [{"first_name": "Max", "last_name": "Mustermann", "age": 31}],
    "phone": "+49 170 0000000",
    "facts": [{"id": "income", "de": "unser Einkommen liegt bei rund 4.800 Euro", "en":
               "our income is about 4,800 EUR", "usage": "always"}],
    "imap_host": "imap.example.test", "sender_domains": ["portal.test"],
    "smtp_host": "smtp.example.test", "smtp_from": "me@example.test",
}


def test_build_is_valid_safe_and_secret_free():
    built = build(ANSWERS)
    pol = built["config"]["send_policy"]
    assert pol["enabled"] is False and pol["mode"] == "shadow" and pol["platform_allow_list"] == []
    assert built["config"]["alerts"]["sender_domains"] == ["portal.test"]
    assert built["config"]["smtp"]["from_address"] == "me@example.test"
    env = dict(line.split("=", 1) for line in built["env"].splitlines() if "=" in line)
    assert env["MIA_ALERT_PASSWORD"] == "" and env["MIA_SMTP_PASSWORD"] == ""      # never asked
    assert env["NTFY_TOPIC"].startswith("https://ntfy.sh/mia-") and len(env["NTFY_TOPIC"]) > 30


def test_private_terms_are_derived_from_the_answers():
    terms = private_terms({**ANSWERS})
    for expected in ("Mustermann", "Max Mustermann", "+49 170 0000000", "491700000000",
                     "Beispielplatz 1, Beispielstadt", "Beispielplatz 1", "4.800"):
        assert expected in terms, terms
    assert all(len(t) >= 4 for t in terms) and len(terms) == len({t.lower() for t in terms})


def test_missing_and_invalid_answers_write_nothing(tmp_path):
    with pytest.raises(WizardError, match="missing answers: .*phone"):
        build({k: v for k, v in ANSWERS.items() if k != "phone"})
    with pytest.raises(WizardError, match="not valid"):
        build({**ANSWERS, "max_cold_rent": 9999})               # cold above warm
    with pytest.raises(WizardError, match="not valid"):
        build({**ANSWERS, "targets": [{"name": "x", "destination": "y", "arrival_time": "09:00"}]})
    assert list(tmp_path.iterdir()) == []


def test_write_refuses_overwrite_then_force_keeps_a_backup(tmp_path):
    env = tmp_path / "cfg" / "env"
    write_files(tmp_path, build(ANSWERS), env)
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    first = (tmp_path / "config.yaml").read_text()
    with pytest.raises(WizardError, match="already exists"):
        write_files(tmp_path, build(ANSWERS), env)
    write_files(tmp_path, build({**ANSWERS, "city": "Andertown"}), env, force=True)
    assert (tmp_path / "config.yaml.bak").read_text() == first
    assert "Andertown" in (tmp_path / "config.yaml").read_text()
    # forcing keeps what was already in .private-terms
    assert "Mustermann" in (tmp_path / ".private-terms").read_text()


def test_generated_files_load_with_the_real_loaders(tmp_path):
    write_files(tmp_path, build(ANSWERS), tmp_path / "env")
    cfg = load_config(tmp_path / "config.yaml")
    assert cfg.city.name == "Beispielstadt" and cfg.send_policy.enabled is False
    assert load_profile(tmp_path / "profile" / "profile.yaml").contact.phone == "+49 170 0000000"


def test_availability_answers_become_profile_windows():
    built = build({**ANSWERS, "availability": {"weekday_start": "18:00", "weekday_end": "20:30",
                                               "weekend_start": "10:00", "weekend_end": "18:00"}})
    windows = built["profile"]["availability"]["windows"]
    assert windows[0]["start"] == "18:00" and windows[1]["days"] == ["sat", "sun"]


class Scripted:
    """Answers prompts by keyword, one answer per asking; then (and for anything not listed)
    the default (Enter). A rule with a list gives its answers in order, so a bad value can be
    followed by a good one."""

    def __init__(self, rules):
        self.rules = [(k, list(a) if isinstance(a, list) else [a]) for k, a in rules]
        self.asked = []

    def __call__(self, prompt):
        self.asked.append(prompt)
        for key, answers in self.rules:
            if key in prompt and answers:
                return answers.pop(0)
        return ""


def test_interactive_run_with_validation_retries():
    ask = Scripted([
        ("City", "Beispielstadt"), ("Maximum warm rent", ["abc"]),      # invalid first, then default
        ("Ideal move-in date", ["soon"]),                             # invalid, then default
        ("Address or station", "Beispielplatz 1, Beispielstadt"),
        ("First name", "Max"), ("Last name", "Mustermann"), ("Phone number", "+49 170 0000000"),
        ("IMAP host of the inbox that receives", "imap.example.test"),
        ("Domains the alerts", "portal.test, mail.portal.test"),
    ])
    answers = collect(Prompter(ask, lambda *_: None))
    assert answers["city"] == "Beispielstadt" and answers["max_warm_rent"] == 1600   # default after retry
    assert answers["sender_domains"] == ["portal.test", "mail.portal.test"]
    assert answers["targets"][0]["max_pt_minutes"] == 30 and "max_car_minutes" not in answers["targets"][0]
    assert len(answers["facts"]) == 5                                   # all defaults kept
    assert sum("warm rent" in q for q in ask.asked) == 2                # asked again after "abc"
    built = build(answers)
    assert built["config"]["send_policy"]["enabled"] is False


def test_eof_aborts_cleanly():
    def eof(_):
        raise EOFError
    with pytest.raises(WizardError, match="input ended"):
        collect(Prompter(eof, lambda *_: None))


def test_install_hook_only_in_a_git_checkout(tmp_path):
    assert install_hook(tmp_path) is None
    (tmp_path / ".git").mkdir()
    hook = install_hook(tmp_path)
    assert hook and hook.exists() and "check-private" in hook.read_text()


def test_cli_init_from_answers_then_check_config(tmp_path, capsys):
    answers_file = tmp_path / "answers.yaml"
    answers_file.write_text(yaml.safe_dump(ANSWERS), encoding="utf-8")
    (tmp_path / "proj").mkdir()
    rc = main(["init", "--dir", str(tmp_path / "proj"), "--env-file", str(tmp_path / "env"),
               "--answers", str(answers_file)])
    out = capsys.readouterr().out
    assert rc == 0 and "Starting state: sending disabled, shadow mode on" in out
    assert main(["check-config", str(tmp_path / "proj" / "config.yaml")]) == 0
    # a second run refuses to overwrite
    rc = main(["init", "--dir", str(tmp_path / "proj"), "--env-file", str(tmp_path / "env"),
               "--answers", str(answers_file)])
    assert rc == 1 and "already exists" in capsys.readouterr().err


def test_cli_init_reports_missing_answers(tmp_path, capsys):
    answers_file = tmp_path / "answers.yaml"
    answers_file.write_text("city: X\n", encoding="utf-8")
    rc = main(["init", "--dir", str(tmp_path), "--env-file", str(tmp_path / "env"),
               "--answers", str(answers_file)])
    assert rc == 1 and "missing answers" in capsys.readouterr().err
    assert not Path(tmp_path / "config.yaml").exists()
