"""Canonical listing model shared by all providers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def _now() -> datetime:
    return datetime.now(UTC)


class Listing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str                       # e.g. "immoscout", "wg_gesucht", "fredy"
    source_id: str                    # id on that source
    url: str
    title: str
    description: str = ""
    warm_rent_eur: float | None = None
    cold_rent_eur: float | None = None
    area_m2: float | None = None
    rooms: float | None = None
    street: str | None = None         # often hidden before contact
    postal_code: str | None = None
    district: str | None = None
    available_from: date | None = None
    available_immediately: bool = False   # "ab sofort"
    deposit_eur: float | None = None
    contact_name: str | None = None     # e.g. "Frau Müller"
    contact_email: str | None = None
    landlord_type: Literal["private", "agency", "unknown"] = "unknown"
    features: list[str] = Field(default_factory=list)   # e.g. ["balcony", "parking"]
    published_at: datetime | None = None
    seen_at: datetime = Field(default_factory=_now)
