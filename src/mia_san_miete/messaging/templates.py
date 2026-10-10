"""Fixed message core. Only the opening sentences may come from an LLM."""

from __future__ import annotations

from datetime import date

from ..models import Listing
from ..profile import Fact, Profile

TEMPLATE_VERSION = "1"

EN_MONTHS = [
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
]

_INTRO_IDS = ("household", "employers", "income", "character", "city_tenure")
_TITLES = ("frau", "herr", "mr", "ms", "mrs")


def _join(items: list[str], lang: str) -> str:
    word = "und" if lang == "de" else "and"
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} {word} {items[-1]}"


def _fmt_date(d: date, lang: str) -> str:
    if lang == "de":
        return d.strftime("%d.%m.%Y")
    return f"{d.day} {EN_MONTHS[d.month - 1]} {d.year}"


def _fmt_rooms(rooms: float, lang: str) -> str:
    text = f"{rooms:g}"
    return text.replace(".", ",") if lang == "de" else text


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def pick_facts(profile: Profile, listing_text: str) -> tuple[dict[str, Fact], list[Fact], list[Fact]]:
    """Return (always facts by id, relevant optional facts, on-request facts)."""
    low = listing_text.lower()
    always = {f.id: f for f in profile.facts if f.usage == "always"}
    relevant = [
        f for f in profile.facts
        if f.usage == "if_relevant" and any(k.lower() in low for k in f.relevant_if)
    ]
    on_request = [f for f in profile.facts if f.usage == "on_request"]
    return always, relevant, on_request


def move_in_date(listing: Listing, profile: Profile) -> date:
    wanted = listing.available_from or profile.move_in.earliest
    return max(wanted, profile.move_in.earliest)


def fallback_opening(listing: Listing, lang: str, plural: bool = True) -> str:
    where = listing.district
    if lang == "de":
        us = "uns" if plural else "mich"
        return (
            f"Ihre Wohnung in {where} spricht {us} sehr an."
            if where else f"Ihre Anzeige hat {us} sehr angesprochen."
        )
    us = "us" if plural else "me"
    return (
        f"Your flat in {where} appeals to {us} very much."
        if where else f"Your listing appeals to {us} very much."
    )


def render(
    listing: Listing, profile: Profile, lang: str, opening: str, city: str = ""
) -> tuple[str, str]:
    """Return (subject, body)."""
    text = f"{listing.title}\n{listing.description}"
    always, relevant, on_request = pick_facts(profile, text)
    d = _fmt_date(move_in_date(listing, profile), lang)
    where = listing.district or listing.postal_code or city
    rooms = _fmt_rooms(listing.rooms, lang) if listing.rooms else None

    names = _join(
        [f"{a.first_name} ({a.age})" if a.age else a.first_name for a in profile.applicants],
        lang,
    )
    signature = _join([f"{a.first_name} {a.last_name}" for a in profile.applicants], lang)

    def get(fact_id: str) -> str | None:
        return getattr(always[fact_id], lang) if fact_id in always else None

    household, employers, income = get("household"), get("employers"), get("income")
    plural = len(profile.applicants) > 1       # one applicant writes "ich", more than one "wir"
    sentences = []
    if lang == "de":
        sentences.append(f"{'Wir sind' if plural else 'Ich bin'} {names}"
                         + (f", {household}." if household else "."))
    else:
        sentences.append(f"{'We are' if plural else 'I am'} {names}"
                         + (f", {household}." if household else "."))
    if employers and income:
        sentences.append(f"{employers}, {income}.")
    elif employers:
        sentences.append(f"{employers}.")
    elif income:
        sentences.append(f"{_cap(income)}.")
    for i in ("character", "city_tenure"):
        if get(i):
            sentences.append(f"{get(i)}.")
    for f in always.values():
        if f.id not in _INTRO_IDS:
            sentences.append(f"{getattr(f, lang)}.")
    if on_request:
        items = _join([getattr(f, lang) for f in on_request], lang)
        sentences.append(
            f"Gern {'legen wir' if plural else 'lege ich'} Ihnen auf Anfrage {items} vor."
            if lang == "de"
            else f"On request {'we are' if plural else 'I am'} happy to provide {items}."
        )
    intro = " ".join(sentences)

    move = (
        f"Einzug wäre ab {d} möglich." if lang == "de"
        else f"{'We' if plural else 'I'} could move in from {d}."
    )
    if relevant:
        move += " " + " ".join(f"{getattr(f, lang)}." for f in relevant)

    viewing = getattr(profile.viewing, lang)
    phone = profile.contact.phone
    if lang == "de":
        name = listing.contact_name
        greeting = (
            f"Guten Tag {name}," if name and name.lower().split()[0] in _TITLES
            else "Guten Tag,"
        )
        contact = (f"Besichtigungen sind bei uns {viewing} möglich. Sie erreichen uns unter {phone}."
                   if plural else
                   f"Besichtigungen sind bei mir {viewing} möglich. Sie erreichen mich unter {phone}.")
        closing = "Herzliche Grüße"
        subject = "Anfrage zu Ihrer Wohnung" + (f" in {where}" if where else "")
        subject += f", {rooms} Zimmer" if rooms else ""
        subject += f", ab {d}"
    else:
        name = listing.contact_name
        greeting = (
            f"Hello {name}," if name and name.lower().split()[0] in _TITLES else "Hello,"
        )
        contact = (f"We can attend viewings {viewing}. You can reach us at {phone}." if plural else
                   f"I can attend viewings {viewing}. You can reach me at {phone}.")
        closing = "Kind regards"
        subject = "Enquiry about your flat" + (f" in {where}" if where else "")
        subject += f", {rooms} rooms" if rooms else ""
        subject += f", from {d}"

    body = f"{greeting}\n\n{opening}\n\n{intro}\n\n{move}\n\n{contact}\n\n{closing}\n{signature}"
    return subject, body
