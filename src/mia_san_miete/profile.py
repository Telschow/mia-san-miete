"""Applicant profile: the only source of personal facts a message may contain."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Applicant(_Strict):
    first_name: str
    last_name: str
    age: int | None = None


class Contact(_Strict):
    phone: str
    sender_email: str = ""


class Fact(_Strict):
    id: str
    de: str
    en: str
    usage: Literal["always", "if_relevant", "on_request"]
    relevant_if: list[str] = Field(default_factory=list)


class Viewing(_Strict):
    de: str
    en: str


class MoveIn(_Strict):
    earliest: date
    latest: date
    reason: str = ""


Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class Window(_Strict):
    days: list[Weekday] = Field(min_length=1)
    start: str = Field(pattern=r"^\d{2}:\d{2}$")
    end: str = Field(pattern=r"^\d{2}:\d{2}$")

    @model_validator(mode="after")
    def _ordered(self) -> Window:
        if self.end <= self.start:
            raise ValueError("availability window end must be after start")
        return self


class Availability(_Strict):
    """When you can attend a viewing. The only source of times an automatic reply may state."""

    windows: list[Window] = Field(min_length=1)
    viewing_minutes: int = Field(default=30, gt=0)
    min_notice_hours: int = Field(default=12, ge=0)
    blackout_dates: list[date] = Field(default_factory=list)


class Profile(_Strict):
    applicants: list[Applicant] = Field(min_length=1)
    contact: Contact
    facts: list[Fact]
    viewing: Viewing
    move_in: MoveIn
    availability: Availability | None = None

    @model_validator(mode="after")
    def _complete(self) -> Profile:
        if any(not a.first_name.strip() or not a.last_name.strip() for a in self.applicants):
            raise ValueError("applicant names must be filled in")
        if not self.contact.phone.strip():
            raise ValueError("contact.phone must be filled in")
        ids = [f.id for f in self.facts]
        if len(ids) != len(set(ids)):
            raise ValueError("fact ids must be unique")
        for f in self.facts:
            if f.usage == "if_relevant" and not f.relevant_if:
                raise ValueError(f"fact {f.id}: if_relevant needs relevant_if keywords")
        return self


def load_profile(path: str | Path) -> Profile:
    with open(path, encoding="utf-8") as fh:
        return Profile.model_validate(yaml.safe_load(fh))
