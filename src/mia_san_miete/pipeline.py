"""Discovery pipeline (P1): fetch, ingest with dedup, notify once per physical flat."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from .db import Database, IngestResult
from .models import Listing
from .notify import Notifier, format_listing
from .providers.base import Provider

log = logging.getLogger(__name__)


@dataclass
class RunStats:
    fetched: int = 0
    new_flats: int = 0
    duplicates: int = 0
    failed_providers: list[str] = field(default_factory=list)


def run_once(
    providers: list[Provider],
    db: Database,
    notifier: Notifier | None,
    on_new_flat: Callable[[Listing, IngestResult], object] | None = None,
) -> RunStats:
    stats = RunStats()
    for provider in providers:
        try:
            listings = provider.fetch()
        except Exception:   # one broken source must not stop the others
            log.exception("provider %s failed", provider.name)
            stats.failed_providers.append(provider.name)
            continue
        for listing in listings:
            stats.fetched += 1
            result = db.ingest(listing)
            if not result.is_new_listing:
                continue
            if result.is_new_flat:
                stats.new_flats += 1
                if notifier:
                    title, body = format_listing(listing)
                    notifier.send(title, body, listing.url)
                if on_new_flat:
                    try:
                        on_new_flat(listing, result)
                    except Exception:   # a processing bug must not stop discovery
                        log.exception("processing failed for %s/%s", listing.source,
                                      listing.source_id)
            else:
                stats.duplicates += 1
    return stats
