from pathlib import Path

import pytest
import yaml

from mia_san_miete.profile import Profile

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def profile() -> Profile:
    raw = yaml.safe_load((ROOT / "profile" / "profile.example.yaml").read_text(encoding="utf-8"))
    raw["applicants"] = [
        {"first_name": "Max", "last_name": "Mustermann", "age": 31},
        {"first_name": "Erika", "last_name": "Beispiel", "age": 29},
    ]
    raw["contact"]["phone"] = "+49 170 0000000"
    # Fictional details, only to test that applicant details never leak into LLM openings.
    for fact in raw["facts"]:
        if fact["id"] == "employers":
            fact.update(de="Wir arbeiten bei der Beispiel AG", en="We work at Beispiel AG")
        if fact["id"] == "income":
            fact.update(
                de="unser Nettoeinkommen liegt bei rund 5.000 € pro Monat",
                en="our net income is about 5,000 EUR per month",
            )
    return Profile.model_validate(raw)
