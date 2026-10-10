from pathlib import Path

from mia_san_miete.cli import main
from mia_san_miete.db import Database
from mia_san_miete.dedup import is_same_flat
from mia_san_miete.models import Listing
from mia_san_miete.notify import NtfyNotifier, format_listing
from mia_san_miete.pipeline import run_once
from mia_san_miete.providers.base import FixtureProvider

FIXTURE = Path(__file__).parent / "fixtures" / "listings.json"


def _l(**kw) -> Listing:
    base = {
        "source": "a", "source_id": "1", "url": "u", "title": "t", "rooms": 2,
        "area_m2": 58.0, "cold_rent_eur": 1200, "warm_rent_eur": 1450,
        "postal_code": "80802",
    }
    base.update(kw)
    return Listing(**base)


def test_same_flat_across_portals_with_street_variants():
    a = _l(street="Leopoldstraße")
    b = _l(source="b", source_id="2", area_m2=58.4, street="Leopold Str.")
    assert is_same_flat(a, b)


def test_different_postal_code_is_not_same():
    assert not is_same_flat(_l(), _l(source="b", postal_code="80939"))


def test_rent_mismatch_is_not_same():
    assert not is_same_flat(_l(), _l(source="b", cold_rent_eur=1400))


def test_sparse_listing_is_not_merged_on_rooms_and_area_alone():
    a = _l(cold_rent_eur=None, warm_rent_eur=None, postal_code=None)
    b = _l(source="b", cold_rent_eur=None, warm_rent_eur=None, postal_code=None)
    assert not is_same_flat(a, b)


def test_missing_area_never_merges():
    assert not is_same_flat(_l(area_m2=None), _l(source="b", area_m2=None))


def test_ingest_is_idempotent_and_groups_duplicates():
    db = Database()
    first = db.ingest(_l())
    again = db.ingest(_l())
    dup = db.ingest(_l(source="b", source_id="2"))
    assert first.is_new_flat and first.is_new_listing
    assert not again.is_new_listing and again.canonical_id == first.canonical_id
    assert dup.is_new_listing and not dup.is_new_flat
    assert len(db.listings_for(first.canonical_id)) == 2


def test_pipeline_notifies_once_per_flat_and_isolates_failures():
    sent = []

    class Spy:
        def send(self, title, body, url=None):
            sent.append((title, body, url))

    class Broken:
        name = "broken"

        def fetch(self):
            raise RuntimeError("site changed")

    db = Database()
    stats = run_once([Broken(), FixtureProvider(FIXTURE)], db, Spy())
    assert stats.fetched == 4
    assert stats.new_flats == 3
    assert stats.duplicates == 1
    assert stats.failed_providers == ["broken"]
    assert len(sent) == 3
    assert run_once([FixtureProvider(FIXTURE)], db, Spy()).new_flats == 0


def test_ntfy_notifier_posts_body_and_click_header():
    calls = []
    n = NtfyNotifier("https://ntfy.test/topic", post=lambda u, d, h: calls.append((u, d, h)))
    title, body = format_listing(_l(district="Schwabing"))
    n.send(title, body, "https://example.test/x")
    url, data, headers = calls[0]
    assert url == "https://ntfy.test/topic"
    assert b"58 m2" in data
    assert headers["Click"] == "https://example.test/x"


def test_cli_ingest_fixture(capsys):
    assert main(["ingest-fixture", str(FIXTURE)]) == 0
    assert "new_flats=3" in capsys.readouterr().out
