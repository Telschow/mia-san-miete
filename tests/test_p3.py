from datetime import date
from pathlib import Path

import pytest
import yaml

from mia_san_miete.messaging.generator import DraftInvalid, generate_draft
from mia_san_miete.messaging.llm import LlmClient
from mia_san_miete.messaging.validator import detect_language, validate_opening
from mia_san_miete.models import Listing
from mia_san_miete.profile import Profile, load_profile


def _l(**kw) -> Listing:
    base = {
        "source": "immoscout", "source_id": "1", "url": "u",
        "title": "Helle 2-Zimmer-Wohnung mit Südbalkon in Schwabing",
        "description": "Ruhige Lage, 58 m², Einbauküche vorhanden, Parkett.",
        "rooms": 2, "area_m2": 58, "district": "Schwabing", "postal_code": "80802",
        "available_from": date(2027, 1, 15), "contact_name": "Frau Müller",
    }
    base.update(kw)
    return Listing(**base)


class Writer:
    def __init__(self, text=None, exc=None):
        self.text, self.exc = text, exc

    def write_opening(self, listing_text, lang):
        if self.exc:
            raise self.exc
        return self.text, "test-model"


def test_example_profile_must_be_filled_in():
    path = Path(__file__).resolve().parent.parent / "profile" / "profile.example.yaml"
    with pytest.raises(ValueError):
        load_profile(path)


def test_language_detection():
    assert detect_language("Helle Wohnung mit Balkon und Parkett") == "de"
    assert detect_language("Bright flat with a balcony and the parquet floor") == "en"


def test_good_llm_opening_is_used(profile):
    w = Writer("Der Südbalkon und die ruhige Lage in Schwabing gefallen uns sehr.")
    d = generate_draft(_l(), profile, w)
    assert d.used_llm and d.model == "test-model" and d.fallback_reason is None
    assert "Südbalkon" in d.body
    assert d.body.startswith("Guten Tag Frau Müller,")
    assert "Max (31) und Erika (29)" in d.body
    assert "+49 170 0000000" in d.body
    assert "ab 15.01.2027" in d.subject


@pytest.mark.parametrize(
    "bad",
    [
        "Wir verdienen zusammen 20.000 € und haben tolle Schufa.",   # forbidden + number
        "Der Südbalkon gefällt uns, die Miete von 999 Euro auch.",   # number not in listing
        "Der Südbalkon ist toll. Wirklich. Sehr. Ja.",               # too many sentences
        "Wir arbeiten bei SAP und lieben den Südbalkon.",            # forbidden + acronym
        "Als Mitarbeiter der Beispiel in Schwabing mögen wir den Südbalkon.",   # profile term
        "The south balcony in Schwabing is lovely and the quiet location too.",  # language
        "Das ist schön.",                                            # no listing reference
        "Der Südbalkon in {district} ist schön.",                    # placeholder
    ],
)
def test_bad_openings_fall_back_to_template(profile, bad):
    d = generate_draft(_l(), profile, Writer(bad))
    assert not d.used_llm and d.fallback_reason.startswith("validation")
    assert "Ihre Wohnung in Schwabing spricht uns sehr an." in d.body


def test_llm_failure_and_timeout_fall_back(profile):
    for exc in (TimeoutError("slow"), RuntimeError("down"), KeyError("bad json")):
        d = generate_draft(_l(), profile, Writer(exc=exc))
        assert not d.used_llm and d.fallback_reason.startswith("llm error")
    assert generate_draft(_l(), profile, None).fallback_reason == "llm disabled"


def test_english_listing_gets_english_message(profile):
    listing = _l(
        title="Bright flat with a south balcony in Schwabing",
        description="This is a quiet flat with the kitchen included.",
        contact_name=None,
    )
    d = generate_draft(listing, profile, None)
    assert d.language == "en"
    assert d.body.startswith("Hello,")
    assert "We are Max (31) and Erika (29)" in d.body
    assert "Kind regards" in d.body


def test_conditional_and_on_request_facts(profile):
    with_kitchen = generate_draft(_l(), profile, None).body
    assert "Küche würden wir gern übernehmen" in with_kitchen
    no_kitchen = generate_draft(
        _l(description="Ruhige Lage, Parkett.", title="Helle Wohnung in Schwabing"),
        profile, None,
    ).body
    assert "Küche" not in no_kitchen
    assert "auf Anfrage" in with_kitchen and "schufa" in with_kitchen.lower()
    assert "Beispiel AG" in with_kitchen and "5.000" in with_kitchen


def test_move_in_date_is_never_before_profile_earliest(profile):
    d = generate_draft(_l(available_from=date(2026, 12, 10)), profile, None)
    assert "ab 01.01.2027" in d.subject
    d = generate_draft(_l(available_from=None), profile, None)
    assert "ab 01.01.2027" in d.subject


def test_generated_message_has_reasonable_length(profile):
    n = len(generate_draft(_l(), profile, None).body.split())
    assert 60 <= n <= 200


def test_unfilled_profile_cannot_produce_placeholder_message(profile):
    raw = profile.model_dump(mode="json")
    raw["facts"] = []
    thin = Profile.model_validate(raw)
    with pytest.raises(DraftInvalid):
        generate_draft(_l(), thin, None)   # too short and no household facts


def test_validate_opening_requires_listing_numbers():
    assert validate_opening("Die 58 m² in Schwabing gefallen uns sehr.", _l(), "de") == []
    assert validate_opening("Die 99 m² in Schwabing gefallen uns sehr.", _l(), "de")


def test_llm_client_parses_json_and_enforces_timeout(tmp_path):
    seen = {}

    def post(url, headers, body, timeout):
        seen.update(url=url, auth=headers["Authorization"], body=body, timeout=timeout)
        return {"model": "m1", "choices": [{"message": {"content":
                'Sure: {"opening": "Der Südbalkon ist schön."}'}}]}

    c = LlmClient("http://x/v1/", "KEY", 6, post=post)
    assert c.write_opening("text", "de") == ("Der Südbalkon ist schön.", "m1")
    assert seen["url"] == "http://x/v1/chat/completions" and seen["auth"] == "Bearer KEY"
    assert "Ignoriere" not in seen["body"]["messages"][0]["content"]

    import time

    slow = LlmClient("http://x/v1", "K", 0.05, post=lambda *a: time.sleep(0.5))
    with pytest.raises(TimeoutError):
        slow.write_opening("text", "de")


def test_profile_yaml_roundtrip(tmp_path, profile):
    p = tmp_path / "profile.yaml"
    p.write_text(yaml.safe_dump(profile.model_dump(mode="json")), encoding="utf-8")
    assert load_profile(p).contact.phone == profile.contact.phone
