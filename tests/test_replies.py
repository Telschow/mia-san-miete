from datetime import UTC, datetime, timedelta

from mia_san_miete.db import Database
from mia_san_miete.metrics import compute_metrics, format_metrics
from mia_san_miete.replies import (
    AUTO_REPLY,
    DOCUMENTS,
    OTHER,
    REJECTION,
    VIEWING,
    IncomingMail,
    check_replies,
    classify,
    parse_mail,
    recipient_hash,
    strip_quotes,
)
from mia_san_miete.senders.email import EmailSender

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
SENT_AT = NOW - timedelta(hours=6)


def _sent_action(db: Database, source_id="1", message_id="<a@mia.test>",
                 to="vermieter@example.test", score=88.0, used_llm=False) -> int:
    cid = db.conn.execute(
        "INSERT INTO canonicals (created_at) VALUES (?)", (SENT_AT.isoformat(),)
    ).lastrowid
    aid = db.record_action(
        canonical_id=cid, source="email", source_id=source_id, status="sent", mode="live",
        created_at=SENT_AT.isoformat(timespec="seconds"), score=score, used_llm=used_llm,
    )
    db.record_outbound(aid, message_id, recipient_hash(to))
    return aid


def _mail(uid="<r1@x.test>", subject="Re: Anfrage", body="", frm="vermieter@example.test",
          refs=("<a@mia.test>",), headers=None, at=None) -> IncomingMail:
    return IncomingMail(uid, subject, body, frm, list(refs), at or NOW, headers or {})


class FakeMailbox:
    def __init__(self, mails):
        self.mails = mails

    def fetch_recent(self, since):
        return self.mails


def test_classify_categories():
    assert classify("Re: Anfrage", "Gerne laden wir Sie zur Besichtigung ein") == VIEWING
    assert classify("Re", "Bitte senden Sie Schufa und Gehaltsnachweis") == DOCUMENTS
    assert classify("Re", "Leider ist die Wohnung bereits vergeben") == REJECTION
    assert classify("Re", "Leider können wir keinen Termin anbieten") == REJECTION
    assert classify("Re", "Danke für Ihre Nachricht") == OTHER
    assert classify("Automatische Antwort: Abwesenheit", "Besichtigung") == AUTO_REPLY
    assert classify("Re", "x", {"Auto-Submitted": "auto-replied"}) == AUTO_REPLY


def test_check_replies_matches_by_message_id_and_is_idempotent():
    db = Database()
    aid = _sent_action(db)
    box = FakeMailbox([_mail(body="Besichtigung am Montag"), _mail(uid="<z@x>", refs=("<?>",),
                                                                   frm="other@x.test")])
    stats, new = check_replies(db, box, NOW)
    assert (stats.scanned, stats.matched, stats.unmatched) == (2, 1, 1)
    assert new == [(aid, VIEWING)]
    stats2, new2 = check_replies(db, box, NOW)
    assert stats2.matched == 0 and new2 == []


def test_check_replies_falls_back_to_sender_address():
    db = Database()
    aid = _sent_action(db)
    _, new = check_replies(db, FakeMailbox([_mail(refs=(), body="Absage, vergeben")]), NOW)
    assert new == [(aid, REJECTION)]
    row = db.conn.execute("SELECT matched_by FROM replies").fetchone()
    assert row["matched_by"] == "sender"


def test_no_text_or_address_is_stored():
    db = Database()
    _sent_action(db)
    secret = "GEHEIMER-INHALT"
    check_replies(db, FakeMailbox([_mail(body=f"Besichtigung {secret}")]), NOW)
    dump = "\n".join(
        str(tuple(r)) for t in ("replies", "outbound", "actions")
        for r in db.conn.execute(f"SELECT * FROM {t}")
    )
    assert secret not in dump and "example.test" not in dump


def test_metrics_rates_and_breakdowns():
    db = Database()
    a1 = _sent_action(db, "1", "<1@m>", "a@x.test", 88.0, False)
    _sent_action(db, "2", "<2@m>", "b@x.test", 92.0, True)
    a3 = _sent_action(db, "3", "<3@m>", "c@x.test", 91.0, True)
    db.record_reply(a1, "u1", VIEWING, "message_id", (SENT_AT + timedelta(hours=2)).isoformat())
    db.record_reply(a3, "u3", AUTO_REPLY, "message_id", (SENT_AT + timedelta(hours=1)).isoformat())
    m = compute_metrics(db)
    assert (m.sent, m.replied, m.positive) == (3, 1, 1)
    assert m.median_reply_hours == 2.0
    assert m.by_score_band["85-89"]["positive"] == 1
    assert m.by_origin["template"] == {"sent": 1, "replied": 1, "positive": 1}
    assert m.by_origin["llm"]["replied"] == 0
    assert "Sent: 3" in format_metrics(m)


def test_parse_mail_reads_references_and_body():
    raw = (b"From: V <vermieter@example.test>\r\nSubject: Re: Anfrage\r\n"
           b"In-Reply-To: <a@mia.test>\r\nMessage-ID: <r9@x.test>\r\n"
           b"Date: Tue, 03 Nov 2026 10:00:00 +0100\r\n\r\nTermin morgen?\r\n")
    mail = parse_mail(raw, "7", NOW)
    assert mail.references == ["<a@mia.test>"] and mail.uid == "<r9@x.test>"
    assert "Termin" in mail.body and mail.from_address == "vermieter@example.test"


def test_email_sender_returns_message_id():
    from mia_san_miete.messaging.generator import Draft
    from mia_san_miete.models import Listing

    class SMTP:
        def __init__(self, *a): self.msgs = []
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self): pass
        def login(self, *a): pass
        def send_message(self, msg): self.msgs.append(msg)

    smtp = SMTP()
    sender = EmailSender("h", 587, "u", "p", "mia@mia.test", lambda h, p: smtp)
    lst = Listing(source="email", source_id="1", url="u", title="t",
                  contact_email="v@example.test")
    mid = sender.send(lst, Draft("s", "b", "de", "1", False, None, None))
    assert mid and mid == smtp.msgs[0]["Message-ID"] and mid.endswith("@mia.test>")


def test_quoted_original_does_not_decide_the_category():
    quoted = ("Ja, bitte rufen Sie zurück.\n\nAm 02.11.2026 um 10:12 schrieb Max:\n"
              "> Besichtigungen sind bei uns werktags möglich. Unterlagen auf Anfrage.")
    assert classify("Re: Anfrage", quoted) == OTHER
    assert "Besichtigung" not in strip_quotes(quoted)
    assert classify("Re", "Leider ist die Wohnung bereits vergeben.\n> Termin?") == REJECTION


def test_still_available_is_not_read_as_a_rejection():
    assert classify("Re", "Die Wohnung ist noch nicht vermietet. Wann hätten Sie Zeit?") == VIEWING
    assert classify("Re", "Die Wohnung ist leider bereits vermietet.") == REJECTION
    assert classify("Re", "Der Termin muss leider verschoben werden.") == OTHER
