from pathlib import Path

import yaml

from mia_san_miete.cli import main

ROOT = Path(__file__).resolve().parent.parent


def _profile(tmp_path):
    raw = yaml.safe_load((ROOT / "profile" / "profile.example.yaml").read_text(encoding="utf-8"))
    raw["applicants"] = [{"first_name": "Max", "last_name": "Mustermann", "age": 31}]
    raw["contact"]["phone"] = "+49 170 0000000"
    p = tmp_path / "profile.yaml"
    p.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return p


def test_draft_preview_prints_drafts(tmp_path, capsys):
    rc = main(["draft-preview", str(ROOT / "tests/fixtures/listings.json"),
               "--profile", str(_profile(tmp_path))])
    out = capsys.readouterr().out
    assert rc == 0 and "Anfrage zu Ihrer Wohnung" in out and "Max Mustermann" in out


def test_draft_preview_rejects_unfilled_profile(capsys):
    rc = main(["draft-preview", str(ROOT / "tests/fixtures/listings.json"),
               "--profile", str(ROOT / "profile/profile.example.yaml")])
    assert rc == 1 and "profile invalid" in capsys.readouterr().err


def test_kill_and_resume(tmp_path, capsys):
    raw = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    flag = tmp_path / "KILL"
    raw["send_policy"]["kill_switch_file"] = str(flag)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    assert main(["kill", "--config", str(cfg)]) == 0 and flag.exists()
    assert main(["resume", "--config", str(cfg)]) == 0 and not flag.exists()
