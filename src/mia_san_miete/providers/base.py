"""Provider contract. A provider turns an external source into canonical Listings.

Providers must isolate their own failures: raise, never return partial garbage, so the
caller can mark the provider unhealthy without stopping the others.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from ..models import Listing


class Provider(Protocol):
    name: str

    def fetch(self) -> list[Listing]: ...


class FixtureProvider:
    """Reads listings from a JSON file. Used for offline tests and dry runs."""

    name = "fixture"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def fetch(self) -> list[Listing]:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [Listing.model_validate(item) for item in raw]
