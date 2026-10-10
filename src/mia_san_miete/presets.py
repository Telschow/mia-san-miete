"""Starting values for a city and a household type.

These are *starting points to adjust*, not market data: they set a city, a sensible shape for
the household (rooms, size, wording of the facts a message may state) and a station that makes
a good radius center. Rent limits are deliberately left out: only you know your budget.
The ten largest German cities by population are covered; every other city works with the plain
wizard.
"""

from __future__ import annotations

from typing import Any

# (key, config city name, German label, English label, central station)
_CITIES = [
    ("berlin", "Berlin", "Berlin", "Berlin", "Berlin Hauptbahnhof"),
    ("hamburg", "Hamburg", "Hamburg", "Hamburg", "Hamburg Hauptbahnhof"),
    ("muenchen", "München", "München", "Munich", "München Hauptbahnhof"),
    ("koeln", "Köln", "Köln", "Cologne", "Köln Hauptbahnhof"),
    ("frankfurt", "Frankfurt am Main", "Frankfurt am Main", "Frankfurt am Main",
     "Frankfurt (Main) Hauptbahnhof"),
    ("stuttgart", "Stuttgart", "Stuttgart", "Stuttgart", "Stuttgart Hauptbahnhof"),
    ("duesseldorf", "Düsseldorf", "Düsseldorf", "Düsseldorf", "Düsseldorf Hauptbahnhof"),
    ("leipzig", "Leipzig", "Leipzig", "Leipzig", "Leipzig Hauptbahnhof"),
    ("dortmund", "Dortmund", "Dortmund", "Dortmund", "Dortmund Hauptbahnhof"),
    ("essen", "Essen", "Essen", "Essen", "Essen Hauptbahnhof"),
]
CITIES: list[dict[str, str]] = [
    {"key": k, "name": n, "label_de": de, "label_en": en, "station": st}
    for k, n, de, en, st in _CITIES
]

_EXCLUDES = ["WBS", "Tausch", "Wohnungstausch", "Tauschwohnung", "Wohngemeinschaft", "Gewerbe"]


def _facts(*rows: tuple[str, str, str, str]) -> list[dict[str, Any]]:
    return [{"id": i, "de": de, "en": en, "usage": u} for i, de, en, u in rows]


# key, labels, short descriptions (filled from the numbers), values, facts
_HOUSEHOLDS: list[dict[str, Any]] = [
    {"key": "single", "label_de": "Single", "label_en": "Single", "applicants": 1,
     "min_rooms": 1, "min_area": 28, "min_lease_months": 24, "exclude_keywords": _EXCLUDES,
     "facts": _facts(
         ("household", "alleinstehend und ohne Haustiere", "single and without pets", "always"),
         ("employers", "Ich bin fest angestellt", "I am in permanent employment", "always"),
         ("income", "mein Einkommen ist stabil und nachweisbar", "my income is stable and documented", "always"),
         ("character", "Ich bin ruhig, ordentlich und zuverlässig", "I am quiet, tidy and reliable", "always"))},
    {"key": "couple", "label_de": "Paar", "label_en": "Couple", "applicants": 2,
     "min_rooms": 2, "min_area": 45, "min_lease_months": 24, "exclude_keywords": _EXCLUDES,
     "facts": _facts(
         ("household", "ein Paar ohne Kinder und ohne Haustiere", "a couple without children or pets", "always"),
         ("employers", "Wir sind beide fest angestellt", "We are both in permanent employment", "always"),
         ("income", "unser Einkommen ist stabil und nachweisbar", "our income is stable and documented", "always"),
         ("character", "Wir sind ruhig, ordentlich und zuverlässig", "We are quiet, tidy and reliable", "always"))},
    {"key": "family", "label_de": "Familie", "label_en": "Family", "applicants": 2,
     "min_rooms": 3, "min_area": 65, "min_lease_months": 24, "exclude_keywords": _EXCLUDES,
     "facts": _facts(
         ("household", "eine Familie", "a family", "always"),
         ("employers", "Wir sind beide fest angestellt", "We are both in permanent employment", "always"),
         ("income", "unser Einkommen ist stabil und nachweisbar", "our income is stable and documented", "always"),
         ("character", "Wir sind ruhig, ordentlich und zuverlässig", "We are quiet, tidy and reliable", "always"))},
    {"key": "student", "label_de": "Studium oder Ausbildung", "label_en": "Student or trainee", "applicants": 1,
     "min_rooms": 1, "min_area": 14, "min_lease_months": 12,
     "exclude_keywords": [k for k in _EXCLUDES if k != "Wohngemeinschaft"],   # shared flats are fine
     "facts": _facts(
         ("household", "in Ausbildung oder Studium und ohne Haustiere", "in training or studies and without pets", "always"),
         ("income", "meine Finanzierung ist gesichert und nachweisbar", "my funding is secured and documented", "always"),
         ("character", "Ich bin ruhig, ordentlich und zuverlässig", "I am quiet, tidy and reliable", "always"))},
]


def _desc(h: dict[str, Any], lang: str) -> str:
    n = h["applicants"]
    if lang == "de":
        return (f"{n} Person{'en' if n > 1 else ''}, ab {h['min_rooms']} Zimmer und {h['min_area']} m², "
                f"Mindestmietdauer {h['min_lease_months']} Monate"
                + (", WG-Angebote erlaubt" if h["key"] == "student" else ""))
    return (f"{n} person{'s' if n > 1 else ''}, from {h['min_rooms']} room(s) and {h['min_area']} m², "
            f"minimum lease {h['min_lease_months']} months"
            + (", shared flats allowed" if h["key"] == "student" else ""))


HOUSEHOLDS: list[dict[str, Any]] = [
    {**h, "desc_de": _desc(h, "de"), "desc_en": _desc(h, "en")} for h in _HOUSEHOLDS
]


class UnknownPreset(ValueError):
    pass


def city(key: str) -> dict[str, str]:
    for c in CITIES:
        if c["key"] == key.lower():
            return c
    raise UnknownPreset(f"unknown city '{key}'; choose one of: " + ", ".join(c["key"] for c in CITIES))


def household(key: str) -> dict[str, Any]:
    for h in HOUSEHOLDS:
        if h["key"] == key.lower():
            return h
    raise UnknownPreset(f"unknown household '{key}'; choose one of: " + ", ".join(h["key"] for h in HOUSEHOLDS))


def preset_answers(city_key: str | None, household_key: str | None) -> dict[str, Any]:
    """Partial wizard answers for the chosen preset (either part may be omitted)."""
    out: dict[str, Any] = {}
    if city_key:
        c = city(city_key)
        out.update(city=c["name"], area_center=c["station"], center_hint=c["station"])
    if household_key:
        h = household(household_key)
        out.update(min_rooms=h["min_rooms"], min_area=h["min_area"],
                   min_lease_months=h["min_lease_months"], exclude_keywords=list(h["exclude_keywords"]),
                   facts=[dict(f) for f in h["facts"]], applicants_hint=h["applicants"])
    return out


def list_presets(lang: str = "de") -> dict[str, list[dict[str, str]]]:
    lang = "en" if lang == "en" else "de"
    return {
        "cities": [{"key": c["key"], "name": c["name"], "label": c[f"label_{lang}"], "station": c["station"]}
                   for c in CITIES],
        "households": [{"key": h["key"], "label": h[f"label_{lang}"], "description": h[f"desc_{lang}"],
                        "min_rooms": h["min_rooms"], "min_area": h["min_area"]} for h in HOUSEHOLDS],
    }
