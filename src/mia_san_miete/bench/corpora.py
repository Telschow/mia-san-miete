"""Labeled fictional corpora for tests and benchmarks.

Everything here is invented. The reply corpus is written by hand; the alert-mail and
duplicate-pair corpora are generated from a fixed seed with known ground truth. Because the
author of the heuristics also wrote these corpora, scores on them describe behavior on this
test set, not accuracy on real mail: see docs/benchmarks.md for the limits.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

CORPUS_DIR = Path(__file__).parent / "corpora"

# (label, subject, body). Tricky cases are marked with a comment.
REPLIES: list[tuple[str, str, str]] = [
    ("viewing_invite", "Re: Anfrage Wohnung", "Gerne laden wir Sie zur Besichtigung am Montag um 17 Uhr ein."),
    ("viewing_invite", "Besichtigungstermin", "Wir hätten am Samstag einen Termin für Sie frei. Passt Ihnen 11 Uhr?"),
    ("viewing_invite", "Re: Ihre Anfrage", "Sie können die Wohnung gerne diese Woche besichtigen. Bitte rufen Sie mich an."),
    ("viewing_invite", "Re: Wohnung", "Hallo, wir würden uns freuen, wenn Sie vorbeikommen könnten. Donnerstag ab 18 Uhr."),
    ("viewing_invite", "Einladung zur Besichtigung", "Hiermit laden wir Sie zur Gruppenbesichtigung am 12.11. ein."),
    ("viewing_invite", "Re: Anfrage", "Termin ist möglich am Dienstag, 16:30 Uhr. Bitte bestätigen Sie kurz."),
    ("viewing_invite", "Re: Anfrage", "Die Wohnung ist noch frei. Wann können Sie zur Besichtigung kommen?"),
    ("viewing_invite", "Viewing", "Thank you for your interest. We can offer you a viewing on Friday at 5 pm."),
    ("viewing_invite", "Re: Enquiry", "You are welcome to visit the flat this week, please suggest a time."),
    ("viewing_invite", "Re: Anfrage", "Leider erst am Montag möglich, dann aber gern zur Besichtigung um 18 Uhr."),  # tricky: 'leider' but invite
    ("viewing_invite", "Re: Anfrage", "Wir haben mehrere Interessenten, laden Sie aber gern zum Termin am Mittwoch ein."),
    ("documents_request", "Re: Anfrage", "Bitte senden Sie uns eine aktuelle Schufa-Auskunft und Ihre Gehaltsnachweise."),
    ("documents_request", "Unterlagen", "Für die weitere Bearbeitung benötigen wir die Mieterselbstauskunft."),
    ("documents_request", "Re: Wohnung", "Könnten Sie uns bitte die letzten drei Einkommensnachweise zukommen lassen?"),
    ("documents_request", "Re: Anfrage", "Bitte füllen Sie die angehängte Selbstauskunft aus und schicken Sie sie zurück."),
    ("documents_request", "Bewerbungsmappe", "Wir bitten um Ihre vollständige Bewerbungsmappe mit Schufa und Gehaltsnachweis."),
    ("documents_request", "Re: Enquiry", "Please send us proof of income and a credit report."),
    ("documents_request", "Re: Enquiry", "We would need your last three payslips and the completed documents form."),
    ("documents_request", "Re: Anfrage", "Schicken Sie uns zuerst Ihre Unterlagen, dann melden wir uns."),
    ("rejection", "Re: Anfrage", "Leider ist die Wohnung bereits vergeben."),
    ("rejection", "Absage", "Vielen Dank für Ihr Interesse. Die Wohnung wurde anderweitig vermietet."),
    ("rejection", "Re: Wohnung", "Wir müssen Ihnen leider mitteilen, dass die Wohnung nicht mehr verfügbar ist."),
    ("rejection", "Re: Anfrage", "Leider haben wir uns für einen anderen Bewerber entschieden."),
    ("rejection", "Re: Anfrage", "Die Wohnung ist schon vermietet, wir wünschen Ihnen weiterhin viel Erfolg."),
    ("rejection", "Re: Anfrage", "Leider können wir keinen Termin mehr anbieten, die Wohnung ist vergeben."),
    ("rejection", "Re: Enquiry", "Unfortunately the flat is no longer available."),
    ("rejection", "Re: Enquiry", "Thank you, but the apartment has already been rented."),
    ("rejection", "Absage", "Wir bedauern, Ihnen eine Absage erteilen zu müssen."),
    ("rejection", "Re: Anfrage", "Leider nicht, die Wohnung ist bereits vermietet."),
    ("auto_reply", "Automatische Antwort: Abwesenheit", "Ich bin bis zum 15.11. nicht im Büro und kann Besichtigungen erst danach anbieten."),  # tricky: mentions viewings
    ("auto_reply", "Out of office", "I am away until Monday with limited access to email."),
    ("auto_reply", "Automatic reply: Enquiry", "Thank you for your message. We will get back to you."),
    ("auto_reply", "Abwesenheitsnotiz", "Vielen Dank für Ihre Nachricht, ich bin im Urlaub."),
    ("auto_reply", "Undeliverable: Anfrage", "Delivery has failed to these recipients."),
    ("auto_reply", "Re: Anfrage", "Ihre Anfrage ist eingegangen. Termin folgt."),  # tricky: only the header marks it
    ("auto_reply", "Re: Anfrage", "Dies ist eine automatisch erstellte Nachricht, bitte nicht antworten. Termin folgt."),
    ("other", "Re: Anfrage", "Danke für Ihre Nachricht. Wir melden uns bei Bedarf."),
    ("other", "Re: Wohnung", "Wie lange möchten Sie die Wohnung mieten?"),
    ("other", "Re: Wohnung", "Sind Haustiere vorhanden?"),
    ("other", "Re: Anfrage", "Ist die Wohnung für Sie auch ohne Küche interessant?"),
    ("other", "Re: Enquiry", "How many people would be moving in?"),
    ("other", "Re: Anfrage", "Wann genau möchten Sie einziehen?"),
    ("other", "Re: Anfrage", "Vielen Dank, wir prüfen alle Anfragen und melden uns."),
]
# Reply indexes that are only identifiable as automatic through a header.
REPLY_AUTO_HEADER = {34}   # index of the header-only auto-reply above


# Round 1 held-out set. Its misses drove the second classifier rewrite, so it is now part of
# the tuning data (see reply_corpus). Never tune against HOLDOUT_2.
HOLDOUT_1: list[tuple[str, str, str, dict]] = [
    ("viewing_invite", "Re: Anfrage", "Guten Tag, vielen Dank für Ihr Interesse. Die Wohnung kann am Freitag um 15:00 Uhr besichtigt werden.", {}),
    ("viewing_invite", "Re: Anfrage", "Hallo, ich kann Ihnen den kommenden Mittwoch anbieten, sagen wir 18 Uhr? Gruß", {}),
    ("viewing_invite", "Re: Wohnung", "Die Wohnung ist noch nicht vermietet. Wir würden uns freuen, Sie kennenzulernen. Wann hätten Sie Zeit?", {}),
    ("viewing_invite", "Re: Wohnung", "Wir machen am Samstag einen Sammeltermin ab 10 Uhr, kommen Sie gerne dazu.", {}),
    ("viewing_invite", "Re: Enquiry", "Hello, the flat is still available. Would Tuesday at 6 pm work for a visit?", {}),
    ("viewing_invite", "Re: Anfrage", "Besichtigung ist ab nächster Woche möglich, bitte melden Sie sich telefonisch.", {}),
    ("documents_request", "Re: Anfrage", "Falls Sie weiterhin Interesse haben, schicken Sie mir bitte Ihre Bewerbungsunterlagen inklusive Gehaltsabrechnungen.", {}),
    ("documents_request", "Re: Wohnung", "Bitte laden Sie Ihre Unterlagen (Schufa, Einkommensbelege, Ausweiskopie) im Portal hoch.", {}),
    ("documents_request", "Re: Enquiry", "Please fill in the attached tenant questionnaire and send it back with proof of income.", {}),
    ("documents_request", "Re: Anfrage", "Wir benötigen noch eine Mietschuldenfreiheitsbescheinigung und die letzten Verdienstbescheinigungen.", {}),
    ("rejection", "Re: Anfrage", "Vielen Dank für Ihr Interesse, aber wir haben die Wohnung bereits an jemand anderen vergeben.", {}),
    ("rejection", "Re: Anfrage", "Die Anzeige ist leider nicht mehr aktuell.", {}),
    ("rejection", "Re: Wohnung", "Es tut uns leid, die Wohnung ist leider weg.", {}),
    ("rejection", "Re: Enquiry", "Sorry, we have already found a tenant.", {}),
    ("rejection", "Re: Anfrage", "Wir haben uns für einen Mieter entschieden und müssen Ihre Anfrage daher ablehnen.", {}),
    ("rejection", "Re: Anfrage", "Leider kommen Sie für diese Wohnung nicht in Frage.", {}),
    ("auto_reply", "Re: Anfrage", "Vielen Dank für Ihre E-Mail. Ich bin vom 3. bis 17. November nicht erreichbar.", {}),
    ("auto_reply", "Auto: Enquiry", "I am currently out of the office and will respond on my return.", {}),
    ("auto_reply", "Abwesenheitsnotiz", "Ich bin bis Montag im Urlaub.", {}),
    ("other", "Re: Anfrage", "Könnten Sie mir bitte Ihre Telefonnummer schicken?", {}),
    ("other", "Re: Anfrage", "Ist die Wohnung auch für drei Personen geeignet?", {}),
    ("other", "Re: Anfrage", "Vielen Dank, bitte schreiben Sie uns noch, wann Sie einziehen möchten und ob Sie Haustiere haben.", {}),
    ("other", "Re: Anfrage", "Der Termin muss leider verschoben werden, ich melde mich.", {}),
    ("other", "Re: Enquiry", "Thanks for your message, can you tell us more about yourself?", {}),
]


# Round 2 held-out set. I looked at it while designing the second rewrite, so it is
# contaminated and now part of the tuning data. Never tune against HOLDOUT_3.
HOLDOUT_2: list[tuple[str, str, str, dict]] = [
    ("viewing_invite", "Re: Anfrage", "Servus, ich zeige die Wohnung am Donnerstag zwischen 17 und 19 Uhr. Kommen Sie einfach vorbei.", {}),
    ("viewing_invite", "Re: Anfrage", "Sehr geehrte Frau Beispiel, gerne können Sie sich die Wohnung ansehen. Wann passt es Ihnen?", {}),
    ("viewing_invite", "Re: Enquiry", "Hi, the apartment is still free. I could show it to you on Saturday morning.", {}),
    ("viewing_invite", "Re: Anfrage", "Wir haben noch Besichtigungstermine frei, zum Beispiel Montag 16 Uhr oder Dienstag 18 Uhr.", {}),
    ("viewing_invite", "Re: Wohnung", "Hallo, die Wohnung ist noch verfügbar. Rufen Sie mich doch bitte kurz an, dann machen wir etwas aus.", {}),
    ("viewing_invite", "Re: Anfrage", "Danke für Ihre ausführliche Bewerbung! Ich würde Sie gerne persönlich kennenlernen, hätten Sie nächste Woche Zeit?", {}),
    ("viewing_invite", "Open house", "Dear applicant, we would like to invite you to an open house on 14 November, 2 pm.", {}),
    ("documents_request", "Re: Anfrage", "Bitte senden Sie mir noch Ihre Schufa-Bonitätsauskunft und eine Kopie Ihres Arbeitsvertrags.", {}),
    ("documents_request", "Re: Anfrage", "Zur Prüfung benötigen wir eine Verdienstbescheinigung der letzten drei Monate.", {}),
    ("documents_request", "Re: Enquiry", "Please send me your employment contract and the last three salary statements.", {}),
    ("documents_request", "Re: Wohnung", "Könnten Sie mir die ausgefüllte Mieterselbstauskunft per Mail zurückschicken?", {}),
    ("documents_request", "Re: Wohnung", "Für den Mietvertrag brauchen wir Ihre Ausweiskopien und einen Einkommensnachweis.", {}),
    ("documents_request", "Re: Anfrage", "Bevor wir fortfahren: bitte laden Sie Ihre Bonitätsunterlagen hoch.", {}),
    ("rejection", "Re: Anfrage", "Hallo, leider hat sich die Wohnung erledigt, wir haben bereits einen Nachmieter.", {}),
    ("rejection", "Re: Anfrage", "Vielen Dank, die Wohnung ist leider nicht mehr zu haben.", {}),
    ("rejection", "Re: Enquiry", "Thank you for applying. We have decided to go with another candidate.", {}),
    ("rejection", "Re: Anfrage", "Wir haben bereits einen Mietvertrag unterschrieben, daher leider keine Besichtigungen mehr.", {}),
    ("rejection", "Re: Wohnung", "Schade, die Wohnung ging gestern an eine andere Familie.", {}),
    ("rejection", "Re: Anfrage", "Ihre Bewerbung konnten wir leider nicht berücksichtigen.", {}),
    ("rejection", "Re: Enquiry", "Unfortunately, the unit has been let to someone else.", {}),
    ("auto_reply", "Automatische Antwort: Re: Anfrage", "Ich bin ab dem 20.10. wieder im Büro.", {}),
    ("auto_reply", "Re: Anfrage", "Dies ist ein automatischer Hinweis: Ihre Nachricht wurde zugestellt.", {}),
    ("auto_reply", "Out of Office: Enquiry", "I will be back on 3 November.", {}),
    ("auto_reply", "Re: Enquiry", "Thank you for your enquiry. Our office is closed until January.", {}),
    ("auto_reply", "Re: Anfrage", "Wir melden uns.", {"Auto-Submitted": "auto-replied"}),
    ("auto_reply", "Delivery Status Notification (Failure)", "Your message could not be delivered.", {}),
    ("other", "Re: Anfrage", "Wie hoch ist Ihr monatliches Haushaltseinkommen?", {}),
    ("other", "Re: Anfrage", "Sind Sie Raucher?", {}),
    ("other", "Re: Anfrage", "Darf ich fragen, wie Sie auf die Anzeige gekommen sind?", {}),
    ("other", "Re: Anfrage", "Ab wann genau wäre die Wohnung für Sie interessant?", {}),
    ("other", "Re: Anfrage", "Vielen Dank für Ihre Nachricht. Ich schaue mir alle Bewerbungen in Ruhe an.", {}),
    ("other", "Re: Enquiry", "Do you have any pets?", {}),
    ("other", "Re: Anfrage", "Welche Mietdauer stellen Sie sich vor?", {}),
    ("other", "Re: Anfrage", "Hallo, bitte rufen Sie mich zurück.", {}),
    ("other", "Re: Anfrage", "Die Kaution beträgt drei Monatsmieten. Ist das für Sie in Ordnung?", {}),
    ("other", "Re: Anfrage", "Danke, wir melden uns.", {}),
]


# Round 3 held-out set, written after the second rewrite, used for reporting only. Do not
# change the classifier to fix its misses; add a new unseen round instead.
HOLDOUT_3: list[tuple[str, str, str, dict]] = [
    ("viewing_invite", "Re: Anfrage", "Guten Abend,\n\nvielen Dank für Ihre Nachricht. Die Wohnung steht noch zur Verfügung. Ich könnte Ihnen morgen um 19 Uhr die Räume zeigen.\n\nViele Grüße\nK. Hoffmann", {}),
    ("viewing_invite", "Re: Anfrage", "Hallo Herr Mustermann, wir sind am Wochenende vor Ort. Schauen Sie gern am Samstag um 11 vorbei.", {}),
    ("other", "Re: Anfrage", "Ja, gerne, bitte um Rückruf unter der Nummer unten.\n\nAm 02.11.2026 um 10:12 schrieb Max Mustermann:\n> Besichtigungen sind bei uns werktags ab 17:30 Uhr möglich.", {}),
    ("viewing_invite", "Re: Enquiry", "Dear Sir or Madam, the flat can be viewed this Thursday from 6 pm. Please confirm by return.", {}),
    ("viewing_invite", "Re: Anfrage", "Wir würden uns freuen, Sie bei uns begrüßen zu dürfen. Bitte melden Sie sich für einen Slot an.", {}),
    ("viewing_invite", "Besichtigung", "Besichtigung: Samstag 14:00, Treffpunkt vor dem Haus.", {}),
    ("documents_request", "Re: Anfrage", "Schicken Sie uns bitte noch Ihre letzten drei Lohnzettel.", {}),
    ("documents_request", "Re: Anfrage", "Wir bräuchten noch einen aktuellen Auszug der Schufa.", {}),
    ("documents_request", "Re: Enquiry", "Please attach a copy of your ID and proof of employment.", {}),
    ("documents_request", "Re: Wohnung", "Gerne senden wir Ihnen den Bewerberbogen zu. Bitte füllen Sie ihn aus.", {}),
    ("documents_request", "Re: Anfrage", "Bitte reichen Sie Gehaltsnachweise nach, dann prüfen wir weiter.", {}),
    ("rejection", "Re: Anfrage", "Hallo, danke für Ihre Anfrage. Wir haben so viele Anfragen bekommen und uns bereits entschieden. Alles Gute bei der Suche.", {}),
    ("rejection", "Re: Anfrage", "Die Wohnung steht nicht mehr zur Verfügung.", {}),
    ("rejection", "Re: Anfrage", "Leider wurde die Wohnung heute morgen schon zugesagt.", {}),
    ("rejection", "Re: Enquiry", "Sorry, the flat was taken yesterday.", {}),
    ("rejection", "Re: Anfrage", "Hallo, ich muss Ihnen leider absagen.", {}),
    ("rejection", "Re: Anfrage", "Leider ist die Wohnung bereits weg.\n\n> Wir bitten um einen Besichtigungstermin.", {}),
    ("auto_reply", "Re: Ihre Anfrage", "Bin bis 08.11. auf Dienstreise und antworte danach.", {}),
    ("auto_reply", "Abwesenheitsnotiz", "Vielen Dank für Ihre E-Mail.", {}),
    ("auto_reply", "Re: Anfrage", "Ihre E-Mail wurde empfangen. Wir bearbeiten Anfragen in der Reihenfolge des Eingangs.", {}),
    ("auto_reply", "Auto-Reply: Anfrage", "Ich melde mich.", {}),
    ("auto_reply", "Re: Anfrage", "Danke.", {"Precedence": "auto_reply"}),
    ("other", "Re: Anfrage", "Können Sie mir sagen, wie viele Personen einziehen?", {}),
    ("other", "Re: Anfrage", "Ja, die Wohnung hat einen Balkon nach Süden.", {}),
    ("other", "Re: Anfrage", "Der Vormieter lässt die Küche gegen Ablöse da, 1.500 Euro. Hätten Sie daran Interesse?", {}),
    ("other", "Re: Anfrage", "Vielen Dank für Ihr Interesse. Wir melden uns, sobald wir alle Anfragen gesichtet haben.", {}),
    ("other", "Re: Anfrage", "Bitte schreiben Sie uns, wie lange Sie schon in Ihrer aktuellen Wohnung wohnen.", {}),
    ("other", "Re: Anfrage", "Wann wäre denn Ihr Wunsch-Einzugstermin?", {}),
]


def _rows(items) -> list[dict]:
    return [{"label": a, "subject": b, "body": c, "headers": d} for a, b, c, d in items]


def holdout_corpus() -> list[dict]:
    return _rows(HOLDOUT_3)


def reply_corpus() -> list[dict]:
    out = []
    for i, (label, subject, body) in enumerate(REPLIES):
        headers = {"Auto-Submitted": "auto-replied"} if i in REPLY_AUTO_HEADER else {}
        out.append({"label": label, "subject": subject, "body": body, "headers": headers})
    return out + _rows(HOLDOUT_1) + _rows(HOLDOUT_2)


# ---------------------------------------------------------------- alert mails

def _fmt_de(x: float, decimals: int = 0) -> str:
    s = f"{x:,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


STREETS = ["Lindenallee", "Beispielweg", "Mühlbachstraße", "Gartenstr.", "Am Park", "Hafenstraße"]
HIDDEN = {"A": ["cold"], "D": ["cold"], "E": ["cold", "postal"]}   # not shown by that style
TITLE_BITS = ["Helle", "Ruhige", "Sanierte", "Gemütliche", "Moderne", "Schöne"]
TITLE_KINDS = ["{r}-Zimmer-Wohnung mit Balkon", "{r}-Zimmer-Altbauwohnung",
               "{r}-Zimmer-Wohnung nahe Park", "{r}-Zimmer-Dachgeschosswohnung"]


def _truth(rng: random.Random, i: int, source: str, ids: set[str]) -> dict:
    rooms = rng.choice([1, 1.5, 2, 2, 2.5, 3, 3.5, 4])
    area = round(rooms * rng.uniform(22, 32), 1)
    cold = round(rng.uniform(600, 1900) / 10) * 10
    warm = cold + round(rng.uniform(150, 350) / 10) * 10
    sid = str(rng.randint(10_000_000, 99_999_999))
    while sid in ids:
        sid = str(rng.randint(10_000_000, 99_999_999))
    ids.add(sid)
    return {"source": source, "source_id": sid,
            "title": f"{rng.choice(TITLE_BITS)} {rng.choice(TITLE_KINDS).format(r=f'{rooms:g}')}",
            "warm": float(warm), "cold": float(cold), "area": area, "rooms": float(rooms),
            "postal": f"{rng.randint(10000, 99999)}"}


URL = {"immoscout": "https://www.immobilienscout24.de/expose/{id}",
       "kleinanzeigen": "https://www.kleinanzeigen.de/s-anzeige/wohnung-{id}/{id}-203-1234",
       "wg_gesucht": "https://www.wg-gesucht.de/wohnung-in-beispielstadt.{id}.html",
       "immowelt": "https://www.immowelt.de/expose/{id}"}


def _render(t: dict, style: str, rng: random.Random) -> tuple[str, str]:
    """Return (kind, text) where kind is 'html' or 'plain' for one listing block."""
    url = URL[t["source"]].format(id=t["source_id"])
    rooms = f"{t['rooms']:g}".replace(".", ",")
    if style == "A":      # anchor title and a figures line; the area may be missing
        figures = [f'{_fmt_de(t["warm"])} € Gesamtmiete']
        if t["area"] is not None:
            figures.append(f'{_fmt_de(t["area"], 1)} m²')
        figures.append(f"{rooms} Zimmer")
        return "html", (f'<div><a href="{url}">{t["title"]}</a><br>{" · ".join(figures)}<br>'
                        f'{t["postal"]} Beispielstadt</div>')
    area = _fmt_de(t["area"], 1)
    if style == "B":      # labeled rows
        return "html", (f'<table><tr><td><a href="{url}">{t["title"]}</a></td></tr>'
                        f'<tr><td>Kaltmiete: {_fmt_de(t["cold"])} €</td></tr>'
                        f'<tr><td>Warmmiete: {_fmt_de(t["warm"])} €</td></tr>'
                        f'<tr><td>Wohnfläche: {area} m²</td></tr><tr><td>Zimmer: {rooms}</td></tr>'
                        f'<tr><td>{t["postal"]} Beispielstadt</td></tr></table>')
    if style == "C":      # plain text, title above, url below
        return "plain", (f'{t["title"]}\n{_fmt_de(t["cold"])} € kalt, {_fmt_de(t["warm"])} € warm, '
                         f'{area} m², {rooms} Zimmer, {t["postal"]}\n{url}\n')
    if style == "D":      # unusual number formats
        warm = f'{t["warm"]:.2f}'.replace(".", ",")
        return "plain", (f'{t["title"]}\n{warm} EUR, {t["area"]:g} qm, {rooms} Zi., '
                         f'{t["postal"]}\n{url}\n')
    return "plain", (f'{t["title"]}\nab {_fmt_de(t["warm"])} Euro Gesamtmiete | '
                     f'{_fmt_de(t["area"], 1)} m2 | {rooms} Räume\n{url}\n')   # style E


def alert_corpus(n_mails: int = 40, seed: int = 11) -> list[dict]:
    rng = random.Random(seed)
    sources = list(URL)
    ids: set[str] = set()
    mails = []
    for m in range(n_mails):
        source = sources[m % len(sources)]
        style = "ABCDE"[m % 5]
        n_listings = rng.randint(1, 3)
        truths, parts = [], []
        kind = "html" if style in "AB" else "plain"
        for i in range(n_listings):
            t = _truth(rng, i, source, ids)
            if style == "A" and rng.random() < 0.25:     # a listing with no area shown
                t["area"] = None
            truths.append(t)
            parts.append(_render(t, style, rng)[1])
            for hidden in HIDDEN.get(style, []):
                t[hidden] = None            # ground truth only contains what the mail shows
        if style in "AB":
            body = "<html><body><p>Neue Treffer für Ihre Suche</p>" + "".join(parts) + \
                   '<a href="https://example.test/unsubscribe">Abmelden</a></body></html>'
        else:
            body = "Neue Treffer für Ihre Suche\n\n" + "\n".join(parts)
        mails.append({"style": style, "kind": kind, "body": body, "truth": truths})
    return mails


# ---------------------------------------------------------------- duplicate pairs

def _flat(rng: random.Random) -> dict:
    rooms = rng.choice([1.5, 2, 2, 2.5, 3, 3.5])
    return {"rooms": float(rooms), "area": round(rooms * rng.uniform(22, 32), 1),
            "cold": float(round(rng.uniform(700, 1900) / 10) * 10),
            "postal": str(rng.randint(10000, 99999)), "street": rng.choice(STREETS),
            "no": rng.randint(1, 60)}


def _variant(f: dict, rng: random.Random, portal: int) -> dict:
    """The same flat as another portal would list it, with realistic differences."""
    street = f["street"]
    if portal and rng.random() < 0.5:
        street = street.replace("straße", " Str.").replace("str.", " Str.")
    drop_street = portal and rng.random() < 0.2
    return {"rooms": f["rooms"], "area": round(f["area"] + rng.uniform(-0.6, 0.6), 1),
            "cold": round(f["cold"] * (1 + rng.uniform(-0.02, 0.02))),
            "warm": round(f["cold"] * 1.2 * (1 + rng.uniform(-0.02, 0.02))),
            "postal": f["postal"], "street": None if drop_street else f"{street} {f['no']}"}


def dedup_corpus(n_pairs: int = 100, seed: int = 5) -> list[dict]:
    rng = random.Random(seed)
    pairs = []
    for _ in range(n_pairs):                                    # same flat on two portals
        f = _flat(rng)
        a, b = _variant(f, rng, 0), _variant(f, rng, 1)
        pairs.append({"same": True, "a": a, "b": b})
    for k in range(n_pairs):                                    # hard negatives
        f = _flat(rng)
        a = _variant(f, rng, 0)
        g = dict(f)
        mode = k % 4
        if mode == 0:        # same building, other unit: slightly different area and rent
            g["area"] += rng.choice([-1, 1]) * rng.uniform(1.6, 4)
            g["cold"] *= 1 + rng.choice([-1, 1]) * rng.uniform(0.05, 0.15)
        elif mode == 1:      # same size, other street in the same postcode
            g["street"] = rng.choice([s for s in STREETS if s != f["street"]])
            g["no"] = rng.randint(1, 60)
        elif mode == 2:      # same everything but a clearly different rent
            g["cold"] *= 1 + rng.choice([-1, 1]) * rng.uniform(0.08, 0.3)
        else:                # different postcode, same rooms and similar size
            g["postal"] = str(rng.randint(10000, 99999))
            g["area"] += rng.uniform(-0.8, 0.8)
        pairs.append({"same": False, "a": a, "b": _variant(g, rng, 1)})
    rng.shuffle(pairs)
    return pairs


# Offered viewing slots as (month, day, hour, minute), relative to a reply received on Monday
# 2 Nov 2026 10:00. Written after the slot parser and run once; never tuned against.
SLOT_HOLDOUT: list[tuple[str, list[list[int]]]] = [
    ("Die Wohnung kann am Freitag um 17:30 besichtigt werden.", [[11, 6, 17, 30]]),
    ("Termin: Mittwoch, 04.11., 18:00 Uhr.", [[11, 4, 18, 0]]),
    ("Wir haben am Dienstag um 18 Uhr und am Donnerstag um 19 Uhr Zeit.", [[11, 3, 18, 0], [11, 5, 19, 0]]),
    ("Kommen Sie am Samstag, den 7. November gegen 11 Uhr vorbei.", [[11, 7, 11, 0]]),
    ("Besichtigung morgen um 17.45 Uhr?", [[11, 3, 17, 45]]),
    ("Saturday 7th at 2 pm works for us.", [[11, 7, 14, 0]]),
    ("Ich kann Ihnen Montag oder Dienstag anbieten, jeweils ab 18 Uhr.", [[11, 9, 18, 0], [11, 3, 18, 0]]),
    ("Gruppenbesichtigung am 10.11. von 17 bis 18 Uhr.", [[11, 10, 17, 0]]),
    ("Wie wäre es mit nächstem Mittwoch 19h?", [[11, 4, 19, 0]]),
    ("Leider erst nächste Woche möglich, am Montag um 18 Uhr.", [[11, 9, 18, 0]]),
    ("Sa., 07.11. um 10 Uhr oder So., 08.11. um 12 Uhr", [[11, 7, 10, 0], [11, 8, 12, 0]]),
    ("Ich bin am Wochenende da, bitte rufen Sie an.", []),
    ("Besichtigung um 18 Uhr.", []),
    ("Am 5. November um halb sieben.", [[11, 5, 18, 30]]),
    ("Thursday at 6:30 pm.", [[11, 5, 18, 30]]),
]


def slot_corpus() -> list[dict]:
    return [{"text": t, "slots": sl} for t, sl in SLOT_HOLDOUT]


def write_corpora() -> None:
    CORPUS_DIR.mkdir(exist_ok=True)
    for name, data in (("replies", reply_corpus()), ("replies_holdout", holdout_corpus()),
                       ("slots_holdout", slot_corpus()), ("alerts", alert_corpus()),
                       ("dedup", dedup_corpus())):
        (CORPUS_DIR / f"{name}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def load(name: str) -> list[dict]:
    return json.loads((CORPUS_DIR / f"{name}.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    write_corpora()
