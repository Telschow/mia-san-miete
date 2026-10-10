from datetime import UTC, datetime, timedelta

import pytest

from mia_san_miete.db import Database
from mia_san_miete.geo.motis import MotisRouter, make_pt_router
from mia_san_miete.pipeline import run_once
from mia_san_miete.providers.alert_email import AlertEmailProvider, portal_for
from mia_san_miete.replies import IncomingMail

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)

HTML = """
<html><body>
<div><a href="https://www.immobilienscout24.de/expose/123456789?x=1"><img src="i.png"></a>
<a href="https://www.immobilienscout24.de/expose/123456789?x=1">Helle 2-Zimmer-Wohnung mit Balkon</a><br>
1.450 € Gesamtmiete &middot; 58,4 m² &middot; 2 Zimmer<br>80802 Beispielstadt</div>
<div><a href="https://www.immobilienscout24.de/expose/987654321">Ruhige 3 Zi. Altbau</a><br>
2.100 € · 85 m² · 3 Zimmer</div>
<a href="https://example.test/unsubscribe">Abmelden</a>
</body></html>
"""

PLAIN = """Neue Treffer
Schöne Wohnung am Park
1.200 € kalt, 1.450 € warm, 60 m², 2,5 Zimmer, 80333
https://www.kleinanzeigen.de/s-anzeige/schoene-wohnung/2345678901-203-1234
"""


def _mail(body, frm="alerts@mail.portal.test", uid="<m1>"):
    return IncomingMail(uid, "Neue Treffer", body, frm, [], NOW, {})


class Box:
    def __init__(self, mails):
        self.mails = mails

    def fetch_recent(self, since):
        return self.mails


def test_portal_for_recognises_known_urls():
    assert portal_for("https://www.immobilienscout24.de/expose/42") == ("immoscout", "42")
    assert portal_for("https://www.wg-gesucht.de/wg-zimmer-in-x.123456.html") == (
        "wg_gesucht", "123456")
    assert portal_for("https://example.test/foo") is None


def test_html_alert_yields_one_listing_per_flat():
    prov = AlertEmailProvider(Box([_mail(HTML)]), ["portal.test"])
    listings = prov.fetch()
    assert [x.source_id for x in listings] == ["123456789", "987654321"]
    first = listings[0]
    assert first.title == "Helle 2-Zimmer-Wohnung mit Balkon"
    assert (first.warm_rent_eur, first.area_m2, first.rooms) == (1450.0, 58.4, 2.0)
    assert first.postal_code == "80802"
    assert listings[1].warm_rent_eur == 2100.0 and listings[1].rooms == 3.0


def test_plain_text_alert_with_cold_and_warm_rent():
    prov = AlertEmailProvider(Box([_mail(PLAIN, "no-reply@portal.test")]),
                              ["portal.test"])
    (listing,) = prov.fetch()
    assert listing.source == "kleinanzeigen" and listing.source_id == "2345678901"
    assert (listing.cold_rent_eur, listing.warm_rent_eur) == (1200.0, 1450.0)
    assert (listing.area_m2, listing.rooms, listing.postal_code) == (60.0, 2.5, "80333")
    assert listing.title == "Schöne Wohnung am Park"


def test_other_senders_are_ignored_and_repeats_deduplicate():
    spoof = _mail(HTML, "alerts@evil.test", "<m2>")
    prov = AlertEmailProvider(Box([spoof]), ["portal.test"])
    assert prov.fetch() == []
    db = Database()
    prov = AlertEmailProvider(Box([_mail(HTML), _mail(HTML, uid="<m3>")]),
                              ["portal.test"])
    stats = run_once([prov], db, notifier=None)
    assert stats.fetched == 4 and stats.new_flats == 2


def test_subdomain_allowed_but_lookalike_domain_is_not():
    prov = AlertEmailProvider(Box([]), ["portal.test"])
    assert prov._allowed("a@mail.portal.test")
    assert not prov._allowed("a@evilportal.test")


class FakeGet:
    def __init__(self, plan=None, geocode=None):
        self.calls, self.plan, self.geocode = [], plan, geocode

    def __call__(self, url):
        self.calls.append(url)
        if "/geocode" in url:
            return self.geocode if self.geocode is not None else [{"lat": 48.1, "lon": 11.5}]
        return self.plan


def test_motis_takes_fastest_itinerary_in_minutes():
    get = FakeGet(plan={"itineraries": [{"duration": 1800}, {"duration": 1500}]})
    r = MotisRouter("https://motis.example.test/", get)
    arrive = NOW + timedelta(days=1)
    assert r.minutes("A", "B", arrive) == 25.0
    plan_url = next(u for u in get.calls if "/plan" in u)
    assert "arriveBy=true" in plan_url and "fromPlace=48.1%2C11.5" in plan_url
    r.minutes("A", "B", arrive)
    assert sum("/geocode" in u for u in get.calls) == 2    # A and B geocoded once each


def test_motis_returns_none_when_unroutable():
    assert MotisRouter(get=FakeGet(geocode=[])).minutes("A", "B", NOW) is None
    assert MotisRouter(get=FakeGet(plan={"itineraries": []})).minutes("A", "B", NOW) is None


def test_unknown_pt_router_is_explicit():
    assert make_pt_router("motis").mode == "pt"
    with pytest.raises(NotImplementedError):
        make_pt_router("mvg")
