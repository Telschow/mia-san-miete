"""Provider that turns portal alert emails (saved-search notifications) into Listings.

No scraping and no portal login: the portals send the mail, we read it over IMAP.

UNVERIFIED against real mails: the URL shapes below follow how the portals' public links
look as remembered, and the field extraction is a text heuristic. Test with a few real
alert mails (see `mia ingest-alerts`) and fix `PORTALS` or the regexes where they miss.
Fields that cannot be read stay None, and the gates and score handle missing data.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser

from ..models import Listing
from ..replies import IncomingMail, MailboxClient

log = logging.getLogger(__name__)

# (source name, regex with one group for the portal's listing id)
PORTALS: list[tuple[str, re.Pattern[str]]] = [
    ("immoscout", re.compile(r"immobilienscout24\.de/expose/(\d+)")),
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


def _num(text: str) -> float:
    """German or plain numbers: '1.450,50', '1.450', '58,4', '58.4' (a lone dot before one or
    two digits is a decimal point, before exactly three digits a thousands separator)."""
    if "," in text:
        return float(text.replace(".", "").replace(",", "."))
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", text):
        return float(text.replace(".", ""))
    return float(text)


def portal_for(url: str) -> tuple[str, str] | None:
    for source, pattern in PORTALS:
        m = pattern.search(url)
        if m:
            return source, m.group(1)
    return None


@dataclass
class _Block:
    source: str
    source_id: str
    url: str
    anchor_text: str
    text: str = ""


class _Collector(HTMLParser):
    """Walks the mail in order, cutting it into one text block per distinct listing link."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[_Block] = []
        self._href: str | None = None
        self._anchor_buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._anchor_buf = []
        elif tag in ("br", "p", "div", "tr", "li") and self.blocks:
            self.blocks[-1].text += "\n"

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            hit = portal_for(self._href)
            if hit:
                self._open_block(hit, "".join(self._anchor_buf).strip())
            self._href = None

    def handle_data(self, data):
        if self._href is not None:
            self._anchor_buf.append(data)
        if self.blocks:
            self.blocks[-1].text += data

    def _open_block(self, hit: tuple[str, str], anchor: str) -> None:
        source, sid = hit
        last = self.blocks[-1] if self.blocks else None
        if last and (last.source, last.source_id) == (source, sid):
            last.anchor_text = last.anchor_text or anchor   # image link then title link
            return
        self.blocks.append(_Block(source, sid, self._href or "", anchor))


def _blocks_from_plain(body: str) -> list[_Block]:
    blocks: list[_Block] = []
    matches = [(m, portal_for(m.group(0))) for m in _URL.finditer(body)]
    matches = [(m, h) for m, h in matches if h]
    for i, (m, hit) in enumerate(matches):
        if any((b.source, b.source_id) == hit for b in blocks):
            continue
        # text before the link (titles usually sit above their link) up to the previous link
        start = matches[i - 1][0].end() if i else 0
        blocks.append(_Block(hit[0], hit[1], m.group(0), "", body[start:m.start()]))
    return blocks


def blocks_from_mail(mail: IncomingMail) -> list[_Block]:
    if "<a " in mail.body.lower() or "<a\n" in mail.body.lower():
        parser = _Collector()
        parser.feed(mail.body)
        if parser.blocks:
            return parser.blocks
    return _blocks_from_plain(mail.body)


def _first_line(text: str) -> str:
    """Nearest line that is not a figures line; titles sit above their price line."""
    for line in reversed(text.splitlines()):
        line = line.strip()
        if (len(line) >= 8 and not _URL.search(line)
                and not (_RENT.search(line) or _AREA.search(line) or _ROOMS.search(line))):
            return line[:160]
    return ""


def listing_from_block(block: _Block, received_at: datetime) -> Listing:
    text = re.sub(r"[ \t\xa0]+", " ", block.text)
    rents = [(_num(m.group(1)), text[max(0, m.start() - 20):m.end() + 20]) for m in _RENT.finditer(text)]
    cold = warm = None
    for value, ctx in rents:
        if _COLD.search(ctx) and cold is None:
            cold = value
        elif _WARM.search(ctx) and warm is None:
            warm = value
    if cold is None and warm is None and rents:
        warm = rents[0][0]      # a single unlabeled price in an alert is the headline rent
    area = _AREA.search(text)
    rooms = _ROOMS.search(text) or _ROOMS_LABEL.search(text)
    plz = _PLZ.search(text)
    return Listing(
        source=block.source,
        source_id=block.source_id,
        url=block.url,
        title=block.anchor_text or _first_line(text) or f"{block.source} {block.source_id}",
        description=text.strip()[:600],
        warm_rent_eur=warm,
        cold_rent_eur=cold,
        area_m2=_num(area.group(1)) if area else None,
        rooms=_num(rooms.group(1)) if rooms else None,
        postal_code=plz.group(1) if plz else None,
        seen_at=received_at,
    )


class AlertEmailProvider:
    name = "alert_email"

    def __init__(
        self, mailbox: MailboxClient, sender_domains: list[str], lookback_days: int = 3,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self.mailbox = mailbox
        self.sender_domains = [d.lower() for d in sender_domains]
        self.lookback_days = lookback_days
        self.clock = clock

    def _allowed(self, address: str) -> bool:
        domain = address.rpartition("@")[2].lower()
        return any(domain == d or domain.endswith("." + d) for d in self.sender_domains)

    def fetch(self) -> list[Listing]:
        since = self.clock() - timedelta(days=self.lookback_days)
        listings: list[Listing] = []
        for mail in self.mailbox.fetch_recent(since):
            if not self._allowed(mail.from_address):
                continue
            for block in blocks_from_mail(mail):
                listings.append(listing_from_block(block, mail.received_at))
        return listings
