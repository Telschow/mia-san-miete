"""Email sender for landlords and agencies that publish a contact address (SMTP)."""

from __future__ import annotations

import smtplib
from collections.abc import Callable
from email.message import EmailMessage
from email.utils import make_msgid

from ..messaging.generator import Draft
from ..models import Listing
from .base import SendError


class EmailSender:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        from_address: str,
        smtp_factory: Callable[[str, int], smtplib.SMTP] = lambda h, p: smtplib.SMTP(h, p, timeout=30),
    ) -> None:
        self.host, self.port = host, port
        self.username, self.password = username, password
        self.from_address = from_address
        self._smtp = smtp_factory

    def send(self, listing: Listing, draft: Draft) -> str | None:
        if not listing.contact_email:
            raise SendError("listing has no contact email")
        msg = EmailMessage()
        msg["From"] = self.from_address
        msg["To"] = listing.contact_email
        msg["Subject"] = draft.subject
        message_id = make_msgid(domain=self.from_address.rpartition("@")[2] or None)
        msg["Message-ID"] = message_id
        msg.set_content(draft.body)
        try:
            with self._smtp(self.host, self.port) as smtp:
                smtp.starttls()
                smtp.login(self.username, self.password)
                smtp.send_message(msg)
        except (OSError, smtplib.SMTPException) as exc:
            raise SendError(f"smtp failure: {type(exc).__name__}") from exc
        return message_id

    def send_reply(self, to: str, subject: str, body: str, in_reply_to: str) -> None:
        """Answer a landlord's mail in the same thread."""
        msg = EmailMessage()
        msg["From"] = self.from_address
        msg["To"] = to
        msg["Subject"] = subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        msg["Message-ID"] = make_msgid(domain=self.from_address.rpartition("@")[2] or None)
        msg["Auto-Submitted"] = "no"
        msg.set_content(body)
        try:
            with self._smtp(self.host, self.port) as smtp:
                smtp.starttls()
                smtp.login(self.username, self.password)
                smtp.send_message(msg)
        except (OSError, smtplib.SMTPException) as exc:
            raise SendError(f"smtp failure: {type(exc).__name__}") from exc
