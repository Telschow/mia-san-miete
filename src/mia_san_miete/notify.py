"""Push notifications and heartbeat. ntfy over plain HTTP, sender injectable for tests."""

from __future__ import annotations

import urllib.request
from collections.abc import Callable
from typing import Protocol

from .models import Listing


class Notifier(Protocol):
    def send(self, title: str, body: str, url: str | None = None) -> None: ...


def format_listing(listing: Listing) -> tuple[str, str]:
    bits = []
    if listing.warm_rent_eur is not None:
        bits.append(f"{listing.warm_rent_eur:.0f} EUR warm")
    elif listing.cold_rent_eur is not None:
        bits.append(f"{listing.cold_rent_eur:.0f} EUR cold")
    if listing.area_m2 is not None:
        bits.append(f"{listing.area_m2:g} m2")
    if listing.rooms is not None:
        bits.append(f"{listing.rooms:g} rooms")
    where = listing.district or listing.postal_code or "location unknown"
    title = f"New flat: {where}"
    body = f"{', '.join(bits) or 'details missing'} ({listing.source})\n{listing.title}"
    return title, body


def _http_post(url: str, data: bytes, headers: dict[str, str]) -> None:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=10):
        pass


class NtfyNotifier:
    def __init__(
        self,
        topic_url: str,
        post: Callable[[str, bytes, dict[str, str]], None] = _http_post,
    ) -> None:
        self.topic_url = topic_url
        self._post = post

    def send(self, title: str, body: str, url: str | None = None) -> None:
        headers = {"Title": title.encode("utf-8").decode("latin-1", "ignore")}
        if url:
            headers["Click"] = url
        self._post(self.topic_url, body.encode("utf-8"), headers)
