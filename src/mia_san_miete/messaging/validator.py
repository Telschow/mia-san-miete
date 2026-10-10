"""Guards for LLM output. Anything that fails here is replaced by the fixed fallback."""

from __future__ import annotations

import re

from ..models import Listing
from ..profile import Profile

DE_WORDS = {
    "der", "die", "das", "und", "ist", "mit", "wir", "sie", "ihre", "ihr", "zu", "sehr",
    "eine", "ein", "für", "im", "auf", "den", "dem", "uns", "gefällt", "gefallen",
}
EN_WORDS = {
    "the", "and", "is", "with", "we", "you", "your", "a", "for", "in", "of", "to", "very",
    "this", "that", "are", "our", "us", "flat", "love",
}

# Facts about the applicants belong to the fixed template, never to the LLM opening.
FORBIDDEN_STEMS = [
    "einkommen", "gehalt", "verdien", "schufa", "haustier", "kinder", "arbeiten", "arbeitgeber",
    "beruf", "income", "salary", "earn", "credit", "pets", "children", "employ", "job",
    "jahre", "years", "monat", "month", "dringend", "urgent", "verzweifel", "desperate",
    "notfall", "emergency", "kaution", "deposit", "garantie", "guarantee",
]
GENERIC = {
    "wohnung", "wohnungen", "zimmer", "anzeige", "apartment", "listing", "ihre", "ihrer",
    "sicher", "gerne", "flat", "gefällt", "gefallen", "angesprochen", "spricht",
}
MAX_OPENING_WORDS = 45
MAX_SENTENCES = 3
MIN_BODY_WORDS = 60
MAX_BODY_WORDS = 200

_WORD = re.compile(r"[a-zäöüß]+", re.IGNORECASE)


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def detect_language(text: str) -> str:
    words = _words(text)
    de = sum(w in DE_WORDS for w in words)
    en = sum(w in EN_WORDS for w in words)
    return "en" if en > de else "de"


def profile_terms(profile: Profile) -> frozenset[str]:
    """Distinctive words from the applicants' own facts (employer names and the like).

    The opening is about the flat, so it must not repeat these unless the listing itself
    uses the same word. Derived from the profile so no personal term lives in the code.
    """
    words: set[str] = set()
    for fact in profile.facts:
        if fact.usage in ("always", "on_request"):
            words.update(w for text in (fact.de, fact.en) for w in _words(text) if len(w) >= 5)
    return frozenset(words - GENERIC)


def validate_opening(
    opening: str, listing: Listing, lang: str, extra_forbidden: frozenset[str] = frozenset()
) -> list[str]:
    errors: list[str] = []
    text = opening.strip()
    if not text:
        return ["empty"]
    source = f"{listing.title}\n{listing.description}".lower()
    words = _words(text)

    if len(text.split()) > MAX_OPENING_WORDS:
        errors.append("too long")
    if len(re.findall(r"[.!?](?:\s|$)", text)) > MAX_SENTENCES:
        errors.append("too many sentences")
    if re.search(r"[{}\[\]<>]", text) or "http" in text.lower() or "@" in text:
        errors.append("placeholder, url or address")
    for token in re.findall(r"\d[\d.,]*", text):
        if token.strip(".,") not in source:
            errors.append(f"number not in listing: {token}")
    for token in re.findall(r"\b[A-ZÄÖÜ]{2,}\b", text):
        if token.lower() not in source:
            errors.append(f"unknown acronym: {token}")
    low = text.lower()
    for stem in FORBIDDEN_STEMS:
        if re.search(rf"(?<!\w){stem}", low):
            errors.append(f"forbidden topic: {stem}")
    listing_vocab = set(_words(source))
    for w in words:
        if w in extra_forbidden and w not in listing_vocab:
            errors.append("mentions applicant details")
            break
    if len(words) >= 5 and detect_language(text) != lang:
        errors.append("wrong language")
    listing_words = set(_words(source))
    if not any(len(w) >= 6 and w not in GENERIC and w in listing_words for w in words):
        errors.append("no concrete reference to the listing")
    return errors


def validate_message(body: str, lang: str, profile: Profile) -> list[str]:
    errors: list[str] = []
    if re.search(r"[{}\[\]]|\bNone\b", body):
        errors.append("placeholder left in message")
    n = len(body.split())
    if n < MIN_BODY_WORDS or n > MAX_BODY_WORDS:
        errors.append(f"message length {n} words")
    if profile.contact.phone not in body:
        errors.append("phone number missing")
    if detect_language(body) != lang:
        errors.append("wrong language")
    return errors
