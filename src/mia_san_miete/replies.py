"""Reply monitor: match inbox replies to sent messages and classify them.

Only the category and ids are stored. Reply text and sender addresses never reach the
database or the logs (the sender address is kept as a hash for matching).
"""

from __future__ import annotations

import email
import hashlib
import imaplib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email import policy
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from typing import Protocol

from .db import Database

log = logging.getLogger(__name__)

AUTO_REPLY = "auto_reply"
REJECTION = "rejection"
VIEWING = "viewing_invite"
DOCUMENTS = "documents_request"
OTHER = "other"
CATEGORIES = (VIEWING, DOCUMENTS, REJECTION, AUTO_REPLY, OTHER)
POSITIVE = (VIEWING, DOCUMENTS)

def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


_AUTO_SUBJECT = _rx(
    r"automatische antwort|abwesenheit|out of office|auto-?reply|automatic reply|^auto:"
    r"|undeliverable|delivery status|mailer-daemon|zustellung|zustellbericht")
_AUTO_BODY = _rx(
    r"automatisch(?:e|er|en)?\s+(?:erstellte|generierte|antwort|nachricht|hinweis)"
    r"|dies ist eine? automat|this is an automat|bitte nicht antworten|do not reply|no-?reply"
    r"|nicht erreichbar|im urlaub|(?:wieder|zurück)\s+im büro|nicht im büro|office is closed"
    r"|out of (?:the )?office|(?:will be|am) back on|currently away|away until|on leave"
    r"|could not be delivered|delivery has failed|nicht zugestellt werden|wurde zugestellt")

# "noch nicht vermietet", "still available": good news for the applicant, and they must not
# be read as the rejection keywords they contain.
_AVAILABLE = _rx(
    r"(?:noch\s+)?nicht\s+(?:anderweitig\s+)?(?:vergeben|vermietet)"
    r"|noch\s+(?:frei|verfügbar|zu haben)|still\s+(?:available|free)")
_POSTPONED = _rx(
    r"(?:termin|besichtigung)\w*[^.!?]{0,40}(?:verschoben|abgesagt|entfällt|verlegt)"
    r"|(?:postponed|rescheduled|cancel+ed)")
_REJECTION = _rx(
    r"(?:schon|bereits|wurde|ist|wird|ging|geht)\s+(?:\w+\s+){0,2}?(?:vergeben|vermietet)"
    r"|\b(?:vergeben|vermietet)\b|anderweitig|nachmieter|hat sich erledigt"
    r"|an\s+(?:jemand|einen|eine|einem)\w*\s+(?:anderen|andere|anderes)\w*"
    r"|nicht mehr\s+(?:aktuell|verfügbar|frei|zu haben|vorhanden)"
    r"|(?:ist|sind)\s+(?:leider\s+)?weg\b|nicht in frage|nicht berücksichtigen"
    r"|mietvertrag\s+(?:\w+\s+){0,2}unterschrieben|keine besichtigungen? mehr"
    r"|absage|absagen|ablehnen|abgelehnt|entschieden|bedauern|schade"
    r"|decided to go with|another candidate|already found|has been let|let to someone"
    r"|no longer available|already\s+(?:been\s+)?(?:rented|taken|let)|unfortunately"
    r"|leider\s+(?:nicht|keine|keinen|schon|bereits|müssen wir|haben wir|können wir|hat|wurde)")
_VIEWING = _rx(
    r"besichtig|termin|vorbeikomm|vorbeischau|anschauen|ansehen|ansehen|einladen|einladung"
    r"|kennenler|zeige (?:ich )?(?:ihnen )?die|show (?:it|you|the)|open house|viewing"
    r"|appointment|\bvisit\b|come (?:by|over)|\binvite|wann (?:passt|hätten|könnten|können) "
    r"|kommen sie (?:\w+ )?vorbei")
_SLOT = _rx(
    r"(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|monday|tuesday|wednesday"
    r"|thursday|friday|saturday|sunday)\b.{0,60}?(?:uhr|\d{1,2}[:.]\d{2}|\d\s?(?:am|pm)"
    r"|morgen|vormittag|nachmittag|abend|morning|evening|afternoon)"
    r"|(?:anbieten|zeigen|offer|show).{0,60}?(?:montag|dienstag|mittwoch|donnerstag|freitag"
    r"|samstag|sonntag|monday|tuesday|wednesday|thursday|friday|saturday|sunday)")
_DOCUMENTS = _rx(
    r"schufa|bonität|selbstauskunft|gehaltsnachweis|gehaltsabrechnung|gehaltsbescheinigung"
    r"|verdienstbescheinigung|verdienstnachweis|einkommensnachweis|einkommensbeleg"
    r"|einkommensbescheid|lohnabrechnung|arbeitsvertrag|ausweiskopie|personalausweis"
    r"|mietschuldenfreiheit|bescheinigung|unterlagen|bewerbungsmappe|fragebogen|nachweis"
    r"|proof of|payslip|salary statement|employment contract|credit (?:report|check)"
    r"|questionnaire|documents|id copy|passport")


def recipient_hash(address: str | None) -> str | None:
    """Stable hash of a mail address, so replies can be matched without storing it."""
    if not address:
        return None
    return hashlib.sha256(address.strip().lower().encode("utf-8")).hexdigest()


_QUOTE_START = _rx(
    r"^\s*(?:am .{5,90} schrieb|on .{5,90} wrote|-{2,}\s*(?:original|ursprüngliche|weitergeleitete)"
    r"|von:|from:|gesendet:|sent:)")


def strip_quotes(body: str) -> str:
    """Drop quoted lines and everything below an 'On ... wrote:' marker: the quoted text is
    our own message (which mentions viewings and documents) and must not decide the category."""
    kept: list[str] = []
    for line in body.splitlines():
        if _QUOTE_START.match(line):
            break
        if not line.lstrip().startswith(">"):
            kept.append(line)
    return "\n".join(kept)


def classify(subject: str, body: str, headers: dict[str, str] | None = None) -> str:
    """Rule-based reply category. Order: automatic mail, rejection, viewing, documents,
    availability, else `other` (no recognized signal: show it to a human, do not count it)."""
    body = strip_quotes(body)
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    auto = headers.get("auto-submitted", "no").lower() != "no"
    if (auto or "x-autoreply" in headers or _AUTO_SUBJECT.search(subject)
            or _AUTO_BODY.search(body)):
        return AUTO_REPLY
    text = f"{subject}\n{body}"
    if _POSTPONED.search(text):
        return OTHER
    available = bool(_AVAILABLE.search(text))
    if _REJECTION.search(_AVAILABLE.sub(" ", text)):
        return REJECTION
    if _VIEWING.search(text) or _SLOT.search(text):
        return VIEWING
    if _DOCUMENTS.search(text):
        return DOCUMENTS
    return VIEWING if available else OTHER


@dataclass(frozen=True)
class IncomingMail:
    uid: str                  # stable id for this message (its Message-ID, else folder uid)
    subject: str
    body: str
    from_address: str
    references: list[str]     # In-Reply-To and References message ids
    received_at: datetime
    headers: dict[str, str]


class MailboxClient(Protocol):
    def fetch_recent(self, since: datetime) -> list[IncomingMail]: ...


def parse_mail(raw: bytes, fallback_uid: str, fallback_time: datetime) -> IncomingMail:
    msg = email.message_from_bytes(raw, policy=policy.default)
    assert isinstance(msg, EmailMessage)
    body_part = msg.get_body(preferencelist=("plain", "html"))
    try:
        body = body_part.get_content() if body_part else ""
    except (LookupError, UnicodeError):
        body = ""
    refs = " ".join(filter(None, [str(msg.get("In-Reply-To", "")), str(msg.get("References", ""))]))
    try:
        received = parsedate_to_datetime(str(msg["Date"])) if msg["Date"] else fallback_time
        if received.tzinfo is None:
            received = received.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        received = fallback_time
    return IncomingMail(
        uid=str(msg.get("Message-ID") or f"uid:{fallback_uid}").strip(),
        subject=str(msg.get("Subject", "")),
        body=body,
        from_address=parseaddr(str(msg.get("From", "")))[1],
        references=re.findall(r"<[^>]+>", refs),
        received_at=received.astimezone(UTC),
        headers={k: str(v) for k, v in msg.items()},
    )


class ImapMailbox:
    """Read-only IMAP access (BODY.PEEK, so mail is never marked as read)."""

    def __init__(
        self, host: str, port: int, username: str, password: str, folder: str = "INBOX",
        factory: Callable[[str, int], imaplib.IMAP4] = lambda h, p: imaplib.IMAP4_SSL(h, p, timeout=30),
    ) -> None:
        self.host, self.port, self.folder = host, port, folder
        self.username, self.password = username, password
        self._factory = factory

    def fetch_recent(self, since: datetime) -> list[IncomingMail]:
        out: list[IncomingMail] = []
        conn = self._factory(self.host, self.port)
        try:
            conn.login(self.username, self.password)
            conn.select(self.folder, readonly=True)
            _, data = conn.search(None, "SINCE", since.strftime("%d-%b-%Y"))
            for uid in (data[0] or b"").split():
                _, parts = conn.fetch(uid, "(BODY.PEEK[])")
                raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
                if raw:
                    out.append(parse_mail(raw, uid.decode(), datetime.now(UTC)))
        finally:
            try:
                conn.logout()
            except (imaplib.IMAP4.error, OSError):
                pass
        return out


@dataclass
class ReplyStats:
    scanned: int = 0
    matched: int = 0
    unmatched: int = 0
    by_category: dict[str, int] | None = None


class Responder(Protocol):
    def handle(self, mail: IncomingMail, action_id: int, category: str, now: datetime) -> str: ...


class TextClassifier(Protocol):
    def classify(self, text: str) -> str | None: ...


def check_replies(
    db: Database, mailbox: MailboxClient, now: datetime, lookback_days: int = 30,
    llm: TextClassifier | None = None, responder: Responder | None = None,
) -> tuple[ReplyStats, list[tuple[int, str]]]:
    """Scan recent mail; store new replies. Returns stats and the new (action_id, category)."""
    stats = ReplyStats(by_category={})
    new: list[tuple[int, str]] = []
    for mail in mailbox.fetch_recent(now - timedelta(days=lookback_days)):
        stats.scanned += 1
        if db.reply_uid_seen(mail.uid):
            continue
        hit = db.find_sent_action(mail.references, recipient_hash(mail.from_address))
        if hit is None:
            stats.unmatched += 1
            continue
        action_id, matched_by = hit
        category = classify(mail.subject, mail.body, mail.headers)
        if category == OTHER and llm is not None:      # the rules found no signal; ask the model
            category = llm.classify(mail.body) or OTHER
        if db.record_reply(
            action_id, mail.uid, category, matched_by,
            mail.received_at.isoformat(timespec="seconds"),
        ):
            stats.matched += 1
            stats.by_category[category] = stats.by_category.get(category, 0) + 1
            new.append((action_id, category))
            if responder is not None:
                try:
                    responder.handle(mail, action_id, category, now)
                except Exception:  # noqa: BLE001 - one bad reply must not stop the scan
                    log.exception("auto-reply handling failed")
    return stats, new
