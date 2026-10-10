"""Draft = fixed template + validated LLM opening, or the deterministic fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..models import Listing
from ..profile import Profile
from .llm import OpeningWriter
from .templates import TEMPLATE_VERSION, fallback_opening, render
from .validator import detect_language, profile_terms, validate_message, validate_opening

log = logging.getLogger(__name__)


class DraftInvalid(Exception):
    """The assembled message failed validation and must not be sent."""


@dataclass(frozen=True)
class Draft:
    subject: str
    body: str
    language: str
    template_version: str
    used_llm: bool
    model: str | None
    fallback_reason: str | None


def generate_draft(
    listing: Listing, profile: Profile, writer: OpeningWriter | None, city: str = ""
) -> Draft:
    text = f"{listing.title}\n{listing.description}"
    lang = detect_language(text)
    opening, model, reason = None, None, "llm disabled"
    if writer is not None:
        try:
            candidate, model = writer.write_opening(text, lang)
            errors = validate_opening(candidate, listing, lang, profile_terms(profile))
            if errors:
                reason = "validation: " + "; ".join(errors)
            else:
                opening, reason = candidate.strip(), None
        except Exception as exc:  # noqa: BLE001 (timeout, network, bad JSON all fall back)
            reason = f"llm error: {type(exc).__name__}"
            log.warning("opening fallback: %s", reason)
    used_llm = opening is not None
    if opening is None:
        opening = fallback_opening(listing, lang, len(profile.applicants) > 1)
        model = None
    subject, body = render(listing, profile, lang, opening, city)
    problems = validate_message(body, lang, profile)
    if problems:
        raise DraftInvalid("; ".join(problems))
    return Draft(subject, body, lang, TEMPLATE_VERSION, used_llm, model, reason)
