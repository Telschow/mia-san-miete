"""Provider that turns portal alert emails (saved-search notifications) into Listings.

No scraping and no portal login: the portals send the mail, we read it over IMAP.

Checked against real mail (October 2026): ImmoScout24 (plain text, labelled fields) and
Immowelt (plain text, click-tracking links only, see `ClickResolver` and ADR 0007). Not yet
checked: Kleinanzeigen, WG-Gesucht, immobilien.de; their patterns in `PORTALS` are still
guesses. Use `mia ingest-alerts --link-shapes` / `--show-mail <domain>` to look at what a
portal really sends, and fix `PORTALS` or the parsers where they miss. Fields that cannot be
read stay None, and the gates and score handle missing data.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlsplit

from ..models import Listing
from ..replies import IncomingMail, MailboxClient

log = logging.getLogger(__name__)

# (source name, regex with one group for the portal's listing id)
PORTALS: list[tuple[str, re.Pattern[str]]] = [
    ("immoscout", re.compile(r"immobilienscout24\.de/expose/(\d+)")),
    ("immoscout", re.compile(r"\.is24\.de/email/expose/(\d+)")),   # alert mail click links
    ("kleinanzeigen", re.compile(r"kleinanzeigen\.de/s-anzeige/[^/\s\"'<>]+/(\d+)")),
    ("wg_gesucht", re.compile(r"wg-gesucht\.de/[^\s\"'<>]*?\.(\d+)\.html")),
    ("immowelt", re.compile(r"immowelt\.de/expose/([A-Za-z0-9]+)")),
]
_URL = re.compile(r"https?://[^\s\"'<>)\]]+")
_NUM = r"(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)"
_RENT = re.compile(_NUM + r"\s*(?:€|EUR|Euro)", re.IGNORECASE)
_AREA = re.compile(_NUM + r"\s*(?:m²|m2|qm)", re.IGNORECASE)
_ROOMS = re.compile(_NUM + r"\s*(?:Zimmer|Zi\.?|Räume|Raum)\b", re.IGNORECASE)
_ROOMS_LABEL = re.compile(r"(?:Zimmer|Zimmeranzahl|Räume)\s*:\s*" + _NUM, re.IGNORECASE)
_PLZ = re.compile(r"\b(\d{5})\b")
_COLD = re.compile(r"kalt", re.IGNORECASE)
_WARM = re.compile(r"warm|gesamtmiete", re.IGNORECASE)
# money figures that are not the rent: deposit, commission, running costs, parking
_NOT_RENT = re.compile(r"kaution|provision|courtage|nebenkosten|heizkosten|stellplatz|garage",
                       re.IGNORECASE)
_PER_M2 = re.compile(r"\s*(?:/|pro|je)\s*(?:m²|m2|qm)", re.IGNORECASE)   # used with .match(pos)


_RENT_LABELS = (("cold", _COLD), ("warm", _WARM), ("other", _NOT_RENT))


def _rent_kind(text: str, start: int, end: int) -> str | None:
    """'cold', 'warm', 'other' (not a rent) or None (unlabelled) for the money figure at
    text[start:end]. A label right after the figure wins ('1.200 € kalt, 1.450 € warm');
    otherwise the nearest label before it ('Warmmiete 1.450 € (kalt 1.200 €)': warm, then
    cold; 'Kaution 3.600 €': other)."""
    if _PER_M2.match(text, end):
        return "other"
    follows = re.match(r"[ \t]*[,;:]?[ \t]*(\w+)", text[end:end + 30])   # same line only
    if follows:
        for kind, rx in _RENT_LABELS:
            if rx.match(follows.group(1)):
                return kind
    before = text[max(0, start - 20):start]
    found = [(m.end(), kind) for kind, rx in _RENT_LABELS for m in rx.finditer(before)]
    return max(found)[1] if found else None


def _num(text: str) -> float:
    """German or plain numbers: '1.450,50', '1.450', '58,4', '58.4' (a lone dot before one or
    two digits is a decimal point, before exactly three digits a thousands separator)."""
    if "," in text:
        return float(text.replace(".", "").replace(",", "."))
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", text):
        return float(text.replace(".", ""))
    return float(text)


def link_shape(url: str) -> str:
    """A link with everything specific masked (query dropped, ids and long tokens replaced),
    safe to paste into an issue: host and path structure only."""
    parts = urlsplit(url)
    segs = []
    for seg in parts.path.split("/"):
        if not seg:
            continue
        segs.append(seg if re.fullmatch(r"[A-Za-z-]{1,12}", seg) else
                    "<n>" if seg.isdigit() else "<x>")
    shape = f"{parts.netloc.lower()}/{'/'.join(segs)}"
    if parts.query:
        keys = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True)[:8]:
            inner = link_shape(value) if value.startswith(("http://", "https://")) else None
            keys.append(f"{key}={inner or '<v>'}")
        shape += "?" + "&".join(keys)
    return shape


PORTAL_DOMAINS: dict[str, tuple[str, ...]] = {
    "immoscout": ("immobilienscout24.de", "is24.de"),
    "kleinanzeigen": ("kleinanzeigen.de",),
    "wg_gesucht": ("wg-gesucht.de",),
    "immowelt": ("immowelt.de",),
}


def portal_for(url: str) -> tuple[str, str] | None:
    """(source, listing id) for a link that really points at a portal: http(s) only, and the
    host must be the portal's domain or a subdomain of it. A portal path inside another
    site's URL ('https://evil.example/www.immowelt.de/expose/1') or a javascript: link is not
    a listing; such a URL would end up as the 'Open listing' link and the push click target."""
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not host:
        return None
    target = host + parts.path
    for source, pattern in PORTALS:
        m = pattern.search(target)
        if m and any(host == d or host.endswith("." + d) for d in PORTAL_DOMAINS[source]):
            return source, m.group(1)
    return None


# links whose anchor or nearby text suggests an action on the account, never opened
_ACTION_WORDS = re.compile(
    r"abmeld|unsubscribe|abbestell|l(?:ö|oe)schen|delete|best(?:ä|ae)tig|confirm|datenschutz|"
    r"impressum|agb|kontakt|hilfe|einstellung|manage", re.IGNORECASE)


# a redirect that lands on a sign-in or account page is not a flat; stop there
_ACCOUNT_PAGE = re.compile(r"/(?:u/)?(?:login|signin|anmelden|logout|account|konto|passwort)\b", re.IGNORECASE)


NEGATIVE_TTL_SECONDS = 3 * 86400   # a lookup that found no flat is not repeated for this long (3 days)


class ClickResolver:
    """Finds the real flat link behind a portal's click-tracking redirect (Immowelt mails
    carry only `click.by.immowelt.de/?qs=<token>`). It asks for the redirect target only, never
    loads the page, skips links that look like unsubscribe or account actions, remembers every
    answer, and stops after `max_requests` fresh lookups per run."""

    hosts = ("click.by.immowelt.de",)

    def __init__(
        self,
        locate: Callable[[str], str | None],
        cache_get: Callable[[str], str | None] = lambda key: None,
        cache_set: Callable[[str, str], None] = lambda key, value: None,
        max_requests: int = 60,
        pause_seconds: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._clock = clock
        self._locate, self._get, self._set = locate, cache_get, cache_set
        self.max_requests, self.pause = max_requests, pause_seconds
        self._sleep = sleep
        self.requests = 0
        self.skipped_over_cap = 0
        self.dead_ends: Counter[str] = Counter()     # where lookups ended without a flat

    def handles(self, url: str) -> bool:
        return urlsplit(url).netloc.lower() in self.hosts

    def resolve(self, url: str, context: str = "") -> str | None:
        if not self.handles(url) or _ACTION_WORDS.search(context):
            return None
        key = "click:" + hashlib.sha1(url.encode()).hexdigest()
        cached = self._get(key)
        if cached:
            if not cached.startswith("-"):
                return cached
            if self._clock() - int(cached[1:] or 0) < NEGATIVE_TTL_SECONDS:
                return None             # recently found not to be a flat; try again later
        if self.requests >= self.max_requests:
            self.skipped_over_cap += 1
            return None
        self.requests += 1
        self._sleep(self.pause)
        target: str | None = url
        for _ in range(5):                     # a few hops at most
            try:
                target = self._locate(target)
            except (OSError, ValueError):
                return None                    # network trouble: not remembered, retried later
            if not target or portal_for(target) or _ACCOUNT_PAGE.search(target):
                break
        found = target if target and portal_for(target) else None
        if not found:
            why = getattr(self._locate, "last_status", "") or "no redirect"
            self.dead_ends[f"{link_shape(target)} ({why})" if target else f"no redirect ({why})"] += 1
        self._set(key, found or f"-{int(self._clock())}")
        return found


def _hit(url: str, resolver: ClickResolver | None, context: str = "") -> tuple[str, str, str] | None:
    """(source, id, url to keep) for a listing link, directly or via the click resolver."""
    direct = portal_for(url)
    if direct:
        return direct[0], direct[1], url
    if resolver:
        real = resolver.resolve(url, context)
        hit = portal_for(real) if real else None
        if hit and real:
            return hit[0], hit[1], real.split("?")[0]   # drop tracking parameters
    return None


_BUTTON_TEXT = re.compile(
    r"^(?:mehr (?:informationen|infos|erfahren)|zum (?:angebot|expos(?:é|e))|(?:jetzt )?ansehen|"
    r"details?|angebot (?:ansehen|anzeigen)|expos(?:é|e) (?:ansehen|öffnen))$", re.IGNORECASE)


@dataclass
class _Block:
    source: str
    source_id: str
    url: str
    anchor_text: str
    text: str = ""
    closed: bool = False        # a card block already holds all its text


class _Collector(HTMLParser):
    """Walks the mail in order, cutting it into one text block per distinct listing link."""

    def __init__(self, resolver: ClickResolver | None = None) -> None:
        super().__init__(convert_charrefs=True)
        self.resolver = resolver
        self.blocks: list[_Block] = []
        self._href: str | None = None
        self._anchor_buf: list[str] = []
        self._card: list[str] = []      # text since the last card button (click-link mails)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._anchor_buf = []
        elif tag in ("br", "p", "div", "tr", "li", "td"):
            self._card.append("\n")
            if self.blocks and not self.blocks[-1].closed:
                self.blocks[-1].text += "\n"

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            anchor = "".join(self._anchor_buf).strip()
            if self.resolver and self.resolver.handles(self._href):
                self._click_link(self._href, anchor)
            else:
                hit = _hit(self._href, self.resolver, anchor)
                if hit:
                    self._open_block(hit, anchor)
            self._href = None

    def handle_data(self, data):
        if self._href is not None:
            self._anchor_buf.append(data)
        self._card.append(data)
        if self.blocks and not self.blocks[-1].closed:
            self.blocks[-1].text += data

    def _click_link(self, href: str, anchor: str) -> None:
        """Mails that only carry click-tracking links show each flat as a card (price, type,
        size, place) that ends with a button. Only the button is looked up, one request per
        flat; the card is the text from its last price line to the button."""
        if not _BUTTON_TEXT.match(anchor):
            return
        lines = [ln.strip() for ln in "".join(self._card).splitlines() if ln.strip()]
        self._card = []
        hit = _hit(href, self.resolver, anchor)
        if not hit or any((b.source, b.source_id) == hit[:2] for b in self.blocks):
            return
        start = next((i for i in range(len(lines) - 1, -1, -1) if _RENT.search(lines[i])), 0)
        card = "\n".join(lines[start:])
        if card.endswith(anchor):
            card = card[: -len(anchor)]
        self.blocks.append(_Block(hit[0], hit[1], hit[2], "", card, closed=True))

    def _open_block(self, hit: tuple[str, str, str], anchor: str) -> None:
        source, sid, url = hit
        last = self.blocks[-1] if self.blocks else None
        if last and (last.source, last.source_id) == (source, sid):
            last.anchor_text = last.anchor_text or anchor   # image link then title link
            return
        self.blocks.append(_Block(source, sid, url, anchor))


_TITLE_START = re.compile(r"^[ \t]*Titel[ \t]*:", re.MULTILINE | re.IGNORECASE)


def _labelled_records(body: str) -> list[tuple[int, int]]:
    """(start, end) of each labelled record ('Titel: ...' then Link, Adresse, Warmmiete, ...).

    ImmoScout24 puts a flat's fields after its link, so a record runs from its 'Titel:' line
    to the next 'Titel:' line or the next rule, whichever comes first."""
    starts = [m.start() for m in _TITLE_START.finditer(body)]
    records = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(body)
        rule = _SEPARATOR.search(body, start, end)
        records.append((start, rule.start() if rule else end))
    return records


def _blocks_from_plain(body: str, resolver: ClickResolver | None = None) -> list[_Block]:
    blocks: list[_Block] = []
    matches = [(m, _hit(m.group(0), resolver, body[max(0, m.start() - 120):m.start()]))
               for m in _URL.finditer(body)]
    matches = [(m, h) for m, h in matches if h]
    records = _labelled_records(body)
    for i, (m, hit) in enumerate(matches):
        if any((b.source, b.source_id) == hit[:2] for b in blocks):
            continue
        record = next(((a, b) for a, b in records if a <= m.start() < b), None)
        if record:
            # labelled mail: the whole record, fields before and after the link
            blocks.append(_Block(hit[0], hit[1], hit[2], "", body[record[0]:record[1]]))
            continue
        # text before the link (titles usually sit above their link) up to the previous link
        start = matches[i - 1][0].end() if i else 0
        blocks.append(_Block(hit[0], hit[1], hit[2], "", body[start:m.start()]))
    return blocks


def _blocks_from_click_cards(body: str, resolver: ClickResolver) -> list[_Block]:
    """Plain-text mails that carry only click-tracking links: each flat is a run of lines (price,
    type, size, place) that ends with a button line ("Mehr Informationen") followed by its link.
    The button link is looked up first; if it leads nowhere, the card's other links are tried
    (at most four lookups per flat)."""
    blocks: list[_Block] = []
    card_start = 0
    card_urls: list[str] = []
    for m in _URL.finditer(body):
        url = m.group(0)
        if not resolver.handles(url):
            continue
        lines = [ln.strip() for ln in _URL.sub("\n", body[card_start:m.start()]).splitlines()
                 if ln.strip()]
        if not lines or not _BUTTON_TEXT.match(lines[-1]):
            card_urls.append(url)
            continue
        candidates = [url] + [u for u in card_urls if u != url]
        card_start, card_urls = m.end(), []
        hit = None
        for candidate in candidates[:4]:
            hit = _hit(candidate, resolver, lines[-1] if candidate == url else "")
            if hit:
                break
        if not hit or any((b.source, b.source_id) == hit[:2] for b in blocks):
            continue
        card = lines[:-1]
        start = next((i for i in range(len(card) - 1, -1, -1) if _RENT.search(card[i])), 0)
        blocks.append(_Block(hit[0], hit[1], hit[2], "", "\n".join(card[start:]), closed=True))
    return blocks


def blocks_from_mail(mail: IncomingMail, resolver: ClickResolver | None = None) -> list[_Block]:
    if "<a " in mail.body.lower() or "<a\n" in mail.body.lower():
        parser = _Collector(resolver)
        parser.feed(mail.body)
        if parser.blocks:
            return parser.blocks
    if resolver:
        cards = _blocks_from_click_cards(mail.body, resolver)
        if cards:
            return cards
        # a click-link mail whose cards did not resolve: do not look up every link of it
        return _blocks_from_plain(mail.body, None)
    return _blocks_from_plain(mail.body, resolver)


def _first_line(text: str) -> str:
    """Nearest line that is not a figures line; titles sit above their price line."""
    for line in reversed(text.splitlines()):
        line = line.strip()
        if (len(line) >= 8 and not _URL.search(line)
                and not (_RENT.search(line) or _AREA.search(line) or _ROOMS.search(line))):
            return line[:160]
    return ""


_SEPARATOR = re.compile(r"^\s*[-=_]{10,}\s*$", re.MULTILINE)
_LABEL = re.compile(r"^\s*(Titel|Adresse)\s*:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_BALCONY = re.compile(r"balkon|terrasse|loggia", re.IGNORECASE)
_PARKING = re.compile(r"stellplatz|garage|tiefgarage|parkplatz", re.IGNORECASE)


def _address_parts(address: str) -> tuple[str | None, str | None, str | None]:
    """(street, postal code, district) from 'Street 1, District, City' style lines. A part with a
    digit is a street; the last part is the city."""
    parts = [x.strip() for x in address.split(",") if x.strip()]
    plz = _PLZ.search(address)
    parts = [re.sub(r"^\d{5}\s*", "", x) for x in parts]
    if len(parts) > 1:
        parts = parts[:-1]                 # drop the city
    street = next((x for x in parts if re.search(r"\d", x) or re.search(r"str\b|straße|platz|weg", x, re.I)), None)
    district = next((x for x in reversed(parts) if x != street and not re.search(r"\d", x)), None)
    return street, plz.group(1) if plz else None, district


_PLACE = re.compile(r"([^\n,()]{2,60}),\s*\n\s*[^\n,()]{2,40}\s*\n\s*\((\d{5})\)")
_TYPE_LABEL = re.compile(r"^(?:wohnung|haus|apartment|wg-zimmer|zimmer)\b.*zur miete$", re.IGNORECASE)
UNLABELED_RENT_IS_COLD = {"immowelt"}     # their cards show the cold rent without saying so


def _figures_only(line: str) -> bool:
    """A line made of rent, size and room figures only ('2 Zimmer . 58 m²'), not a title that
    happens to contain one ('Helle 62qm mit Südbalkon')."""
    rest = line
    for rx in (_RENT, _AREA, _ROOMS, _COLD, _WARM):
        rest = rx.sub(" ", rest)
    rest = re.sub(r"(?:kalt|warm|gesamt)?miete\b", " ", rest, flags=re.IGNORECASE)
    return len(re.sub(r"[\W_]+", "", rest)) < 4


def _card_title(text: str, rooms: float | None, area: float | None, district: str | None) -> str:
    """A title for card-style mails: the first line that is not a figure, place or button; a bare
    type label ('Wohnung zur Miete') is extended with size and place."""
    for line in (ln.strip() for ln in text.splitlines()):
        if (not line or _figures_only(line) or _BUTTON_TEXT.match(line) or re.fullmatch(r"\(\d{5}\)", line)
                or line.endswith(",") or line in ("München",)):
            continue
        if not _TYPE_LABEL.match(line):
            return line[:160]
        extra = [f"{rooms:g} Zi." if rooms else "", f"{area:g} m²" if area else "", district or ""]
        return ", ".join([line] + [x for x in extra if x])
    return ""


def listing_from_block(block: _Block, received_at: datetime) -> Listing:
    raw = _URL.sub(" ", block.text)       # link text (tokens like '907qM') must not read as figures
    seps = list(_SEPARATOR.finditer(raw))
    if seps:
        raw = raw[seps[-1].end():]          # header and search summary above the last rule
    labels = {m.group(1).lower(): m.group(2) for m in _LABEL.finditer(raw)}
    text = re.sub(r"[ \t\xa0]+", " ", raw)
    rents = [(_num(m.group(1)), _rent_kind(text, m.start(), m.end())) for m in _RENT.finditer(text)]
    rents = [(value, kind) for value, kind in rents if kind != "other"]
    cold = warm = None
    for value, kind in rents:
        if kind == "cold" and cold is None:
            cold = value
        elif kind == "warm" and warm is None:
            warm = value
    if cold is None and warm is None and rents:
        if block.closed and block.source in UNLABELED_RENT_IS_COLD:
            cold = rents[0][0]
        else:
            warm = rents[0][0]      # a single unlabeled price in an alert is the headline rent
    area = _AREA.search(text)
    rooms = _ROOMS.search(text) or _ROOMS_LABEL.search(text)
    plz = _PLZ.search(text)
    street, label_plz, district = _address_parts(labels["adresse"]) if "adresse" in labels else (None, None, None)
    place = _PLACE.search(raw)
    if place and not district:
        district, label_plz = place.group(1).strip(), place.group(2)
    features = [name for name, rx in (("balcony", _BALCONY), ("parking", _PARKING)) if rx.search(text)]
    rooms_value = _num(rooms.group(1)) if rooms else None
    area_value = _num(area.group(1)) if area else None
    card_title = _card_title(raw, rooms_value, area_value, district) if block.closed else ""
    return Listing(
        source=block.source,
        source_id=block.source_id,
        url=f"https://www.immobilienscout24.de/expose/{block.source_id}"
        if block.source == "immoscout" else block.url,   # not the per-recipient click link
        title=labels.get("titel") or card_title
        or (block.anchor_text if not _BUTTON_TEXT.match(block.anchor_text.strip()) else "")
        or _first_line(text)
        or f"{block.source} {block.source_id}",
        description=text.strip()[:600],
        warm_rent_eur=warm,
        cold_rent_eur=cold,
        area_m2=_num(area.group(1)) if area else None,
        rooms=_num(rooms.group(1)) if rooms else None,
        postal_code=label_plz or (plz.group(1) if plz else None),
        street=street,
        district=district,
        features=features,
        seen_at=received_at,
    )


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_GREETING = re.compile(r"^\s*(?:hallo|hi|hey|guten|liebe[r]?|sehr geehrte|dear|hello)\b", re.IGNORECASE)


class _Skeleton(HTMLParser):
    """Turns an HTML mail into short lines: text, and [link shape | anchor text]."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._href: str | None = None
        self._buf: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head"):
            self._skip += 1
        elif tag == "a":
            self._flush()
            self._href = dict(attrs).get("href") or ""
        elif tag in ("br", "p", "div", "tr", "li", "td", "h1", "h2", "h3"):
            self._flush()

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head"):
            self._skip = max(0, self._skip - 1)
        elif tag == "a":
            text = " ".join("".join(self._buf).split())
            if self._href is not None:
                self.lines.append(f"[LINK {link_shape(self._href)} | {text[:60]}]")
            self._href, self._buf = None, []

    def handle_data(self, data):
        if not self._skip:
            self._buf.append(data)

    def _flush(self) -> None:
        if self._href is None:
            text = " ".join("".join(self._buf).split())
            if text:
                self.lines.append(text[:100])
            self._buf = []


def mail_skeleton(mail: IncomingMail, max_lines: int = 80) -> str:
    """A shareable outline of a mail: no addresses, no greeting lines, links reduced to their
    shape. Flat details (rent, size, title) stay, because that is what the parser must find."""
    if "<a " in mail.body.lower() or "<html" in mail.body.lower():
        sk = _Skeleton()
        sk.feed(mail.body)
        sk._flush()
        lines = sk.lines
    else:
        body = _URL.sub(lambda m: f"[LINK {link_shape(m.group(0))}]", mail.body)
        lines = [ln.strip()[:100] for ln in body.splitlines() if ln.strip()]
    out = [_EMAIL.sub("<email>", ln) for ln in lines if not _GREETING.match(ln)]
    return "\n".join(out[:max_lines])


class AlertEmailProvider:
    name = "alert_email"

    def __init__(
        self, mailbox: MailboxClient, sender_domains: list[str], lookback_days: int = 3,
        clock=lambda: datetime.now(UTC), resolver: ClickResolver | None = None,
    ) -> None:
        self.resolver = resolver
        self.mailbox = mailbox
        self.sender_domains = [d.lower() for d in sender_domains]
        self.lookback_days = lookback_days
        self.clock = clock
        self.mails_seen = 0
        self.mails_allowed = 0
        self.mails_without_links = 0
        self.skipped_domains: Counter[str] = Counter()
        self.link_shapes: Counter[str] = Counter()
        self.samples: dict[str, list[IncomingMail]] = {}
        self.samples: dict[str, list[IncomingMail]] = {}

    def _allowed(self, address: str) -> bool:
        domain = address.rpartition("@")[2].lower()
        return any(domain == d or domain.endswith("." + d) for d in self.sender_domains)

    def fetch(self) -> list[Listing]:
        since = self.clock() - timedelta(days=self.lookback_days)
        listings: list[Listing] = []
        self.mails_seen = self.mails_allowed = self.mails_without_links = 0
        self.skipped_domains = Counter()
        self.link_shapes = Counter()
        self.samples = {}
        for mail in self.mailbox.fetch_recent(since):
            self.mails_seen += 1
            if not self._allowed(mail.from_address):
                self.skipped_domains[mail.from_address.rpartition("@")[2].lower()] += 1
                continue
            self.mails_allowed += 1
            bucket = self.samples.setdefault(mail.from_address.rpartition("@")[2].lower(), [])
            if len(bucket) < 2:
                bucket.append(mail)
            for url in _URL.findall(mail.body):
                self.link_shapes[link_shape(url)] += 1
            blocks = blocks_from_mail(mail, self.resolver)
            self.mails_without_links += not blocks
            for block in blocks:
                listings.append(listing_from_block(block, mail.received_at))
        return listings
