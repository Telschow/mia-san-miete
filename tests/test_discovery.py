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


def test_immoscout_click_link_and_canonical_url():
    from datetime import UTC, datetime

    from mia_san_miete.providers.alert_email import (
        _blocks_from_plain,
        link_shape,
        listing_from_block,
    )

    body = "3 Zimmer Wohnung\n1.200 € kalt 70 m2\nhttps://push.search.is24.de/email/expose/123456?token=secret"
    block = _blocks_from_plain(body)[0]
    assert (block.source, block.source_id) == ("immoscout", "123456")
    listing = listing_from_block(block, datetime.now(UTC))
    assert listing.url == "https://www.immobilienscout24.de/expose/123456"
    assert "secret" not in link_shape("https://x.de/c?u=https%3A%2F%2Fy.de%2Fexpose%2F1&t=secret")


ALERT_TEXT = """Dein neuer Suchauftrag
----------------------------------------------------------------------
Deine suche Mietwohnung, in München, ab 2 Zimmer, ab 50 m² Wohnfläche, bis 1.600 € Warmmiete
----------------------------------------------------------------------
Angebote, die zu deiner Suche passen:
Titel: Erste Wohnung

Link:
https://push.search.is24.de/email/expose/1?PID=x
Adresse: Frankfurter Ring 1, Milbertshofen, München
Warmmiete: 1.599 €
Wohnfläche: 55 m²
Zimmer: 2,5
Balkon/Terrasse, Einbauküche, Keller

Titel: Zweite Wohnung

Link:
https://push.search.is24.de/email/expose/2?PID=x
"""


def test_labelled_alert_fields():
    from datetime import UTC, datetime

    from mia_san_miete.providers.alert_email import _blocks_from_plain, listing_from_block

    blocks = _blocks_from_plain(ALERT_TEXT)
    first, second = (listing_from_block(b, datetime.now(UTC)) for b in blocks)
    # the search summary above the rule must not leak into the first flat
    assert first.title == "Erste Wohnung" and first.warm_rent_eur is None and first.rooms is None
    assert second.title == "Zweite Wohnung"
    assert (second.warm_rent_eur, second.area_m2, second.rooms) == (1599.0, 55.0, 2.5)
    assert second.district == "Milbertshofen" and second.street == "Frankfurter Ring 1"
    assert second.features == ["balcony"]


def test_click_resolver_follows_caches_and_skips_actions():
    from mia_san_miete.providers.alert_email import ClickResolver, blocks_from_mail
    from mia_san_miete.replies import IncomingMail

    calls = []
    hops = {
        "https://click.by.immowelt.de/?qs=a": "https://t.example/next",
        "https://t.example/next": "https://www.immowelt.de/expose/abc123?utm=1",
    }

    def locate(url):
        calls.append(url)
        return hops.get(url)

    store: dict[str, str] = {}
    r = ClickResolver(locate, store.get, store.__setitem__, pause_seconds=0, sleep=lambda s: None)
    assert r.resolve("https://click.by.immowelt.de/?qs=a") == "https://www.immowelt.de/expose/abc123?utm=1"
    assert r.resolve("https://click.by.immowelt.de/?qs=a")      # second call comes from the cache
    assert len(calls) == 2 and r.requests == 1
    assert r.resolve("https://click.by.immowelt.de/?qs=z", "Abmelden") is None   # never opened
    assert r.resolve("https://other.example/x") is None
    assert len(calls) == 2

    capped = ClickResolver(locate, max_requests=0, sleep=lambda s: None)
    assert capped.resolve("https://click.by.immowelt.de/?qs=a") is None and capped.skipped_over_cap == 1

    body = ('<div>1.100 € Kaltmiete</div><div>2 Zimmer . 50 m2</div>'
            '<a href="https://click.by.immowelt.de/?qs=other">Preis</a>'
            '<a href="https://click.by.immowelt.de/?qs=a">Mehr Informationen</a>')
    mail = IncomingMail(uid="1", from_address="x" + chr(64) + "immowelt.de", subject="s", body=body, references=[],
                        received_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
                        headers={})
    before = len(calls)
    blocks = blocks_from_mail(mail, r)
    assert [(b.source, b.source_id, b.url) for b in blocks] == [
        ("immowelt", "abc123", "https://www.immowelt.de/expose/abc123")]
    assert len(calls) == before          # the button answer was cached; the other link was not asked


def test_click_resolver_survives_login_redirects_and_bad_locations():
    from mia_san_miete.providers.alert_email import ClickResolver

    hops = {
        "https://click.by.immowelt.de/?qs=login": "/u/login?state=abc",
        "https://click.by.immowelt.de/?qs=bad": "not a url",
    }

    def locate(url):
        if url == "not a url":
            raise ValueError("unknown url type")
        return hops.get(url)

    store: dict[str, str] = {}
    r = ClickResolver(locate, store.get, store.__setitem__, pause_seconds=0, sleep=lambda s: None)
    assert r.resolve("https://click.by.immowelt.de/?qs=login") is None
    assert r.resolve("https://click.by.immowelt.de/?qs=bad") is None
    assert r.requests == 2
    assert r.resolve("https://click.by.immowelt.de/?qs=login") is None and r.requests == 2   # remembered


def test_mail_skeleton_hides_addresses_and_greeting():
    from datetime import UTC, datetime

    from mia_san_miete.providers.alert_email import mail_skeleton
    from mia_san_miete.replies import IncomingMail

    body = ('<html><body><p>Hallo Max,</p><p>Kontakt: max' + chr(64) + 'x.de</p><div>2 Zimmer, 1.200 €</div>'
            '<a href="https://click.example.de/?qs=secret">Mehr Informationen</a></body></html>')
    mail = IncomingMail(uid="1", subject="s", body=body, from_address="a" + chr(64) + "b.de",
                        references=[], received_at=datetime.now(UTC), headers={})
    out = mail_skeleton(mail)
    assert "Max" not in out and "secret" not in out and "x.de" not in out
    assert "2 Zimmer, 1.200 €" in out and "[LINK click.example.de/?qs=<v> | Mehr Informationen]" in out


IMMOWELT_MAIL = (
    "<html><body>"
    "<div>Du hast deine Suche gespeichert</div><div>bis 1.350 €</div><div>ab 2 Zi.</div>"
    "<div>Deine ersten Treffer zur Suche</div>"
    '<a href="https://click.by.immowelt.de/?qs=img"></a>'
    '<div><a href="https://click.by.immowelt.de/?qs=p1">900 €</a></div>'
    '<div><a href="https://click.by.immowelt.de/?qs=t1">Wohnung zur Miete</a></div>'
    '<div><a href="https://click.by.immowelt.de/?qs=r1">2 Zimmer . 58 m²</a></div>'
    '<div><a href="https://click.by.immowelt.de/?qs=a1">Schwabing-Freimann,</a></div>'
    "<div>München</div><div>(80939)</div>"
    '<a href="https://click.by.immowelt.de/?qs=b1">Mehr Informationen</a>'
    '<div><a href="https://click.by.immowelt.de/?qs=p2">1.022 € Kaltmiete</a></div>'
    '<div><a href="https://click.by.immowelt.de/?qs=t2">Helle Wohnung mit Südbalkon</a></div>'
    '<div><a href="https://click.by.immowelt.de/?qs=r2">2,5 Zimmer . 62 m²</a></div>'
    "<div>Bogenhausen,</div><div>München</div><div>(81925)</div>"
    '<a href="https://click.by.immowelt.de/?qs=b2">Mehr Informationen</a>'
    '<a href="https://click.by.immowelt.de/?qs=unsub">Abmelden</a>'
    "</body></html>"
)


def test_immowelt_card_mail_costs_one_lookup_per_flat():
    from datetime import UTC, datetime

    from mia_san_miete.providers.alert_email import (
        ClickResolver,
        blocks_from_mail,
        listing_from_block,
    )
    from mia_san_miete.replies import IncomingMail

    looked_up = []
    ids = {"b1": "https://www.immowelt.de/expose/aaa111", "b2": "https://www.immowelt.de/expose/bbb222"}

    def locate(url):
        looked_up.append(url)
        return ids[url.rsplit("=", 1)[1]]

    r = ClickResolver(locate, pause_seconds=0, sleep=lambda s: None)
    mail = IncomingMail(uid="1", subject="s", body=IMMOWELT_MAIL, from_address="x" + chr(64) + "immowelt.de",
                        references=[], received_at=datetime.now(UTC), headers={})
    first, second = (listing_from_block(b, mail.received_at) for b in blocks_from_mail(mail, r))
    assert len(looked_up) == 2                       # the two buttons only, not the other 10 links
    assert (first.source, first.source_id) == ("immowelt", "aaa111")
    assert (first.cold_rent_eur, first.warm_rent_eur) == (900.0, None)    # card prices are cold rents
    assert (first.rooms, first.area_m2) == (2.0, 58.0)
    assert (first.district, first.postal_code) == ("Schwabing-Freimann", "80939")
    assert first.title == "Wohnung zur Miete, 2 Zi., 58 m², Schwabing-Freimann"
    assert second.title == "Helle Wohnung mit Südbalkon"
    assert (second.cold_rent_eur, second.rooms, second.area_m2) == (1022.0, 2.5, 62.0)
    assert second.district == "Bogenhausen"


IMMOWELT_PLAIN = """Neue Nachricht von immowelt
https://click.by.immowelt.de/?qs=top
bis 1.350 €
ab 2 Zi.
Deine ersten Treffer zur Suche
https://click.by.immowelt.de/?qs=img
900 €
https://click.by.immowelt.de/?qs=p1
Wohnung zur Miete
https://click.by.immowelt.de/?qs=t1
2 Zimmer . 58 m²
https://click.by.immowelt.de/?qs=r1
Schwabing-Freimann,
München
(80939)
https://click.by.immowelt.de/?qs=a1
Mehr Informationen
https://click.by.immowelt.de/?qs=b1
1.022 € Kaltmiete
https://click.by.immowelt.de/?qs=p2
TAUSCHWOHNUNG Helle 62qm mit Südbalkon
https://click.by.immowelt.de/?qs=t2
2,5 Zimmer . 62 m²
https://click.by.immowelt.de/?qs=r2
Bogenhausen,
München
(81925)
https://click.by.immowelt.de/?qs=a2
Mehr Informationen
https://click.by.immowelt.de/?qs=b2
Abmelden
https://click.by.immowelt.de/?qs=unsub
"""


def test_immowelt_plain_text_cards():
    from datetime import UTC, datetime

    from mia_san_miete.providers.alert_email import (
        ClickResolver,
        blocks_from_mail,
        listing_from_block,
    )
    from mia_san_miete.replies import IncomingMail

    looked_up = []
    ids = {"b1": "https://www.immowelt.de/expose/aaa111", "b2": "https://www.immowelt.de/expose/bbb222"}

    def locate(url):
        looked_up.append(url)
        return ids[url.rsplit("=", 1)[1]]

    r = ClickResolver(locate, pause_seconds=0, sleep=lambda s: None)
    mail = IncomingMail(uid="1", subject="s", body=IMMOWELT_PLAIN, from_address="x" + chr(64) + "immowelt.de",
                        references=[], received_at=datetime.now(UTC), headers={})
    first, second = (listing_from_block(b, mail.received_at) for b in blocks_from_mail(mail, r))
    assert len(looked_up) == 2
    assert (first.source_id, first.cold_rent_eur, first.warm_rent_eur) == ("aaa111", 900.0, None)
    assert (first.rooms, first.area_m2, first.district, first.postal_code) == (2.0, 58.0, "Schwabing-Freimann", "80939")
    assert first.title == "Wohnung zur Miete, 2 Zi., 58 m², Schwabing-Freimann"
    assert second.title == "TAUSCHWOHNUNG Helle 62qm mit Südbalkon" and second.cold_rent_eur == 1022.0


def test_click_cards_try_other_links_when_the_button_leads_nowhere():
    from datetime import UTC, datetime

    from mia_san_miete.providers.alert_email import (
        ClickResolver,
        blocks_from_mail,
        listing_from_block,
    )
    from mia_san_miete.replies import IncomingMail

    body = (
        "Neues Angebot für dich in München\nhttps://click.by.immowelt.de/?qs=img\n"
        "1.022 € Kaltmiete\nhttps://click.by.immowelt.de/?qs=price\n"
        "2 Zimmer . 62 m²\nhttps://click.by.immowelt.de/?qs=rooms\n"
        "Bogenhausen,\nMünchen\n(81925)\nhttps://click.by.immowelt.de/?qs=place\n"
        "Mehr Informationen\nhttps://click.by.immowelt.de/?qs=button\n"
    )
    asked = []

    def locate(url):
        asked.append(url.rsplit("=", 1)[1])
        return "https://www.immowelt.de/expose/zzz999" if url.endswith("price") else None

    r = ClickResolver(locate, pause_seconds=0, sleep=lambda s: None)
    mail = IncomingMail(uid="1", subject="s", body=body, from_address="x" + chr(64) + "immowelt.de",
                        references=[], received_at=datetime.now(UTC), headers={})
    (block,) = blocks_from_mail(mail, r)
    listing = listing_from_block(block, mail.received_at)
    assert asked == ["button", "img", "price"]          # stops at the first link that leads to a flat
    assert listing.source_id == "zzz999" and listing.cold_rent_eur == 1022.0 and listing.area_m2 == 62.0
    assert "https" not in listing.description
