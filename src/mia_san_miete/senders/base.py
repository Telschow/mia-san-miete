"""Sender contract. A sender delivers one validated draft; it never decides whether to."""

from __future__ import annotations

from typing import Protocol

from ..messaging.generator import Draft
from ..models import Listing


class SendError(Exception):
    """Delivery failed; the dispatcher records it and may pause the platform."""


class Sender(Protocol):
    def send(self, listing: Listing, draft: Draft) -> str | None:
        """Deliver the draft; return the Message-ID if the channel has one."""
        ...
