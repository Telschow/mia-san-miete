from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from mia_san_miete.cli import main
from mia_san_miete.config import Config, load_config

EXAMPLE = Path(__file__).resolve().parent.parent / "config.example.yaml"


def _raw() -> dict:
    return yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))


def test_example_config_is_valid():
    cfg = load_config(EXAMPLE)
    assert cfg.send_policy.enabled is False
    assert cfg.send_policy.mode == "shadow"
    assert cfg.criteria.max_warm_rent_eur == 1600


def test_live_requires_allow_list():
    raw = _raw()
    raw["send_policy"].update(enabled=True, mode="live", platform_allow_list=[])
    with pytest.raises(ValidationError):
        Config.model_validate(raw)


def test_floor_cannot_exceed_threshold():
    raw = _raw()
    raw["send_policy"]["loosen"]["floor"] = 95
    with pytest.raises(ValidationError):
        Config.model_validate(raw)


def test_cold_rent_cannot_exceed_warm():
    raw = _raw()
    raw["criteria"]["max_cold_rent_eur"] = 2000
    with pytest.raises(ValidationError):
        Config.model_validate(raw)


def test_unknown_keys_rejected():
    raw = _raw()
    raw["send_policy"]["autosend_everything"] = True
    with pytest.raises(ValidationError):
        Config.model_validate(raw)


def test_cli_check_config(capsys):
    assert main(["check-config", str(EXAMPLE)]) == 0
    assert "config ok" in capsys.readouterr().out
    assert main(["check-config", "does-not-exist.yaml"]) == 1


def test_target_needs_a_limit_and_names_are_unique():
    raw = _raw()
    raw["commute"]["targets"][0].pop("max_pt_minutes")
    with pytest.raises(ValidationError):
        Config.model_validate(raw)
    raw = _raw()
    raw["commute"]["targets"][1]["name"] = raw["commute"]["targets"][0]["name"]
    with pytest.raises(ValidationError):
        Config.model_validate(raw)
