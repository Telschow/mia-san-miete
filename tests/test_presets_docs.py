import json
from pathlib import Path

import pytest
import yaml

from mia_san_miete.cli import main
from mia_san_miete.config import Config, load_config
from mia_san_miete.config_docs import SECTIONS, D, all_paths, render, schema_json
from mia_san_miete.messaging.generator import generate_draft
from mia_san_miete.models import Listing
from mia_san_miete.presets import (
    CITIES,
    HOUSEHOLDS,
    UnknownPreset,
    list_presets,
    preset_answers,
)
from mia_san_miete.profile import Profile, load_profile
from mia_san_miete.wizard import Prompter, WizardError, build, collect
from tests.test_wizard import ANSWERS

DOCS = Path(__file__).resolve().parent.parent / "docs"


def test_every_field_is_documented_in_both_languages_and_nothing_is_stale():
    paths = set(all_paths())
    assert paths - set(D) == set(), "undocumented fields"
    assert set(D) - paths == set(), "descriptions for fields that no longer exist"
    assert all(de.strip() and en.strip() for de, en in D.values())
    top = {p.split(".")[0].split("[")[0] for p in paths}
    assert top <= set(SECTIONS)


def test_committed_reference_files_match_the_generator():
    """Generated files are never hand-edited; run `mia docs-config --write` after a change."""
    assert (DOCS / "config-reference.de.md").read_text(encoding="utf-8") == render("de")
    assert (DOCS / "config-reference.en.md").read_text(encoding="utf-8") == render("en")
    assert (DOCS / "config.schema.json").read_text(encoding="utf-8") == schema_json()


def test_reference_content_is_sane():
    de, en = render("de"), render("en")
    assert "Konfigurationsreferenz" in de and "Configuration reference" in en
    assert "`criteria.station.max_walk_minutes`" in de and "`send_policy.mode`" in en
    assert "shadow | live" in de and "**Pflicht**" in de and "**required**" in en
    assert "Marktdaten" in de and "market data" in en
    assert json.loads(schema_json())["config"]["title"] == "Config"
    with pytest.raises(ValueError):
        render("fr")


def test_cli_docs_config_prints_and_writes(tmp_path, capsys):
    assert main(["docs-config"]) == 0 and "Konfigurationsreferenz" in capsys.readouterr().out
    assert main(["docs-config", "--lang", "en"]) == 0 and "Configuration reference" in capsys.readouterr().out
    assert main(["docs-config", "--write", "--out", str(tmp_path)]) == 0
    assert {p.name for p in tmp_path.iterdir()} == {"config-reference.de.md", "config-reference.en.md",
                                                    "config.schema.json"}


def test_presets_cover_the_ten_largest_cities_and_four_household_types():
    assert [c["key"] for c in CITIES] == ["berlin", "hamburg", "muenchen", "koeln", "frankfurt",
                                          "stuttgart", "duesseldorf", "leipzig", "dortmund", "essen"]
    assert [h["key"] for h in HOUSEHOLDS] == ["single", "couple", "family", "student"]
    de, en = list_presets("de"), list_presets("en")
    assert de["cities"][2]["label"] == "München" and en["cities"][2]["label"] == "Munich"
    assert en["cities"][2]["name"] == "München"          # config always gets the German name
    assert "Person" in de["households"][0]["description"] and "person" in en["households"][0]["description"]
    assert all("Hauptbahnhof" in c["station"] for c in de["cities"])


def test_presets_contain_no_rent_or_market_claims():
    for pair in [("berlin", "single"), ("koeln", "family")]:
        a = preset_answers(*pair)
        assert not {"max_warm_rent", "max_cold_rent"} & set(a)         # only you know your budget
    with pytest.raises(UnknownPreset, match="choose one of"):
        preset_answers("atlantis", None)
    with pytest.raises(UnknownPreset):
        preset_answers(None, "dragon")


@pytest.mark.parametrize("city", [c["key"] for c in CITIES])
@pytest.mark.parametrize("hh", [h["key"] for h in HOUSEHOLDS])
def test_every_preset_builds_valid_files(city, hh):
    preset = preset_answers(city, hh)
    answers = {**preset, "max_warm_rent": 1500,
               "targets": [{"name": "work", "destination": "Beispielplatz 1", "arrival_time": "09:00",
                            "max_pt_minutes": 30}],
               "applicants": [{"first_name": "Max", "last_name": "Mustermann"}] * 1,
               "phone": "+49 17" + "0 0000000", "imap_host": "imap.example.test",
               "sender_domains": ["portal.test"]}
    built = build(answers)
    Config.model_validate(built["config"])
    Profile.model_validate(built["profile"])
    assert built["config"]["send_policy"]["enabled"] is False and built["config"]["send_policy"]["mode"] == "shadow"


def test_single_household_messages_say_ich_not_wir():
    answers = {**preset_answers("hamburg", "single"), "max_warm_rent": 1200,
               "targets": [{"name": "w", "destination": "X", "arrival_time": "09:00", "max_pt_minutes": 30}],
               "applicants": [{"first_name": "Max", "last_name": "Mustermann", "age": 28}],
               "phone": "+49 17" + "0 0000000", "imap_host": "h", "sender_domains": ["p.test"]}
    profile = Profile.model_validate(build(answers)["profile"])
    lst = Listing(source="x", source_id="1", url="u", title="Helle Wohnung mit Balkon", district="Altstadt",
                  rooms=2, area_m2=45, warm_rent_eur=1100)
    de = generate_draft(lst, profile, None, "Hamburg").body
    assert "Ich bin Max (28)" in de and "bei mir" in de and "erreichen mich" in de and "Wir sind" not in de
    assert "spricht mich sehr an" in de and " uns " not in de.replace("Sie erreichen uns", "")
    couple = answers | {"applicants": answers["applicants"] + [{"first_name": "Eva", "last_name": "Muster"}]}
    two = generate_draft(lst, Profile.model_validate(build(couple)["profile"]), None, "Hamburg").body
    assert "Wir sind Max (28) und Eva" in two and "bei uns" in two and "spricht uns sehr an" in two


def test_wizard_uses_preset_defaults_and_asks_the_new_optional_limits():
    asked: list[str] = []
    rules = {"City": "", "Address or station": "Beispielplatz 1", "First name": "Max", "Last name": "Mustermann",
             "Phone number": "+49 17" + "0 0000000", "IMAP host of the inbox that receives": "imap.example.test",
             "Domains the alerts": "portal.test", "Maximum straight-line distance": "6",
             "Center (address": "", "Maximum walk to the nearest": "8", "Reject flats with a longer walk": "y"}

    def ask(prompt):
        asked.append(prompt)
        for key, answer in rules.items():
            if key in prompt:
                return answer
        return ""

    a = collect(Prompter(ask, lambda *_: None), preset_answers("muenchen", "couple"))
    assert a["city"] == "München" and a["min_rooms"] == 2 and a["min_area"] == 45
    assert a["area_center"] == "München Hauptbahnhof" and a["area_max_km"] == 6
    assert a["station_max_walk"] == 8 and a["station_required"] is True
    assert len(a["applicants"]) == 2                      # the couple preset suggests a second one
    built = build(a)["config"]
    assert built["criteria"]["area"] == {"center": "München Hauptbahnhof", "max_km": 6.0}
    assert built["criteria"]["station"] == {"max_walk_minutes": 8, "required": True}
    assert built["scoring"]["weights"] == {"station": 5}
    assert any("Maximum straight-line distance" in x for x in asked)       # the new optional limits


def test_wizard_radius_without_a_center_is_refused():
    with pytest.raises(WizardError, match="not valid"):
        build({**ANSWERS, "area_max_km": 5})


def test_cli_presets_and_init_with_preset(tmp_path, capsys):
    assert main(["presets"]) == 0
    out = capsys.readouterr().out
    assert "muenchen" in out and "München Hauptbahnhof" in out and "couple" in out and "Studium" in out
    assert main(["presets", "--lang", "en"]) == 0 and "Cities" in capsys.readouterr().out
    answers = tmp_path / "a.yaml"
    answers.write_text(yaml.safe_dump({
        "max_warm_rent": 1400, "targets": [{"name": "w", "destination": "Beispielplatz 1",
                                            "arrival_time": "09:00", "max_pt_minutes": 30}],
        "applicants": [{"first_name": "Max", "last_name": "Mustermann"}],
        "phone": "+49 17" + "0 0000000", "imap_host": "imap.example.test", "sender_domains": ["portal.test"]}))
    rc = main(["init", "--dir", str(tmp_path), "--env-file", str(tmp_path / "env"), "--answers", str(answers),
               "--city", "leipzig", "--household", "student", "--no-hook"])
    assert rc == 0
    cfg = load_config(tmp_path / "config.yaml")
    assert cfg.city.name == "Leipzig" and cfg.criteria.min_area_m2 == 14
    assert "Wohngemeinschaft" not in cfg.criteria.exclude_keywords          # shared flats are fine
    assert load_profile(tmp_path / "profile" / "profile.yaml").facts[0].id == "household"
    assert main(["init", "--dir", str(tmp_path / "x"), "--env-file", str(tmp_path / "e2"), "--answers",
                 str(answers), "--city", "atlantis"]) == 1
    assert "unknown city" in capsys.readouterr().err
