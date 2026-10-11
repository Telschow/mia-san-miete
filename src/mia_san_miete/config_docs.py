"""Generated configuration reference (German by default, English as an option).

The reference is built from the real pydantic models, so it cannot drift from the code: a test
fails when a field has no description, when a description names a field that no longer exists,
or when the committed files differ from what this module generates. Regenerate with
`mia docs-config --write`.
"""

from __future__ import annotations

import json
import typing
from datetime import date
from pathlib import Path

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from .config import Config
from .presets import CITIES, HOUSEHOLDS
from .profile import Profile

# path -> (German, English). `[]` marks list items. Keep one line each.
D: dict[str, tuple[str, str]] = {
    "city.name": ("Stadt; wird an unvollständige Adressen angehängt, damit sie gefunden werden.",
                  "City; appended to partial addresses so they can be found."),
    "criteria.max_warm_rent_eur": ("Höchste Warmmiete pro Monat in Euro; teurere Wohnungen werden aussortiert.",
                                   "Highest warm rent per month in euro; dearer flats are rejected."),
    "criteria.max_cold_rent_eur": ("Höchste Kaltmiete pro Monat in Euro; darf die Warmmiete nicht übersteigen.",
                                   "Highest cold rent per month in euro; must not exceed the warm rent."),
    "criteria.min_area_m2": ("Mindestwohnfläche in Quadratmetern.", "Minimum living area in square metres."),
    "criteria.min_rooms": ("Mindestzahl der Zimmer (Halbe erlaubt, z. B. 2.5).",
                           "Minimum number of rooms (halves allowed, e.g. 2.5)."),
    "criteria.move_in.ideal_from": ("Wunschtermin für den Einzug.", "Preferred move-in date."),
    "criteria.move_in.latest": ("Spätester akzeptabler Einzug; danach wird aussortiert.",
                                "Latest acceptable move-in; later flats are rejected."),
    "criteria.move_in.early_flex_days": ("Tage vor dem Wunschtermin, die noch durchgehen (mit Hinweis, niedrigerer Score).",
                                         "Days before the preferred date that still pass (flagged, lower score)."),
    "criteria.move_in.unknown": ("Wohnung ohne Einzugstermin: `review` schickt sie zur Prüfung (Standard), `flag` lässt sie mit Hinweis durch. Portal-Alarme nennen den Termin meist nicht.",
                                 "A flat without a move-in date: `review` sends it to review (default), `flag` lets it through with a note. Portal alerts usually do not state the date."),
    "criteria.exclude_keywords": ("Ganze Wörter, die eine Wohnung ausschließen (z. B. WBS, Tausch). Verneinungen wie „kein WBS“ werden erkannt.",
                                  "Whole words that exclude a flat (e.g. WBS, Tausch). Negations such as \"kein WBS\" are recognised."),
    "criteria.min_lease_months": ("Mindestmietdauer in Monaten (noch ohne Wirkung): ausgeschlossen werden bisher nur Zwischenmiete und Untermiete auf Zeit; eine unbekannte Dauer gilt als unbefristet und geht durch, „befristet“ ohne Dauer geht in die Prüfung.",
                                  "Minimum lease length in months (no effect yet): so far only sublets (Zwischenmiete, Untermiete auf Zeit) are rejected; an unknown length counts as open-ended and passes, and \"befristet\" without a duration goes to review."),
    "criteria.max_warm_rent_per_m2": ("Optional: höchste Warmmiete pro Quadratmeter in Euro; teurere Wohnungen werden aussortiert.",
                                      "Optional: highest warm rent per square metre in euro; dearer flats are rejected."),
    "criteria.market_warm_rent_per_m2": ("Optional: übliche Warmmiete pro Quadratmeter in deiner Gegend (Euro, siehe `mia market-rent`). Weit darunter geht in die Prüfung (Betrugsverdacht), weit darüber gibt einen Hinweis.",
                                         "Optional: usual warm rent per square metre where you search (euro, see `mia market-rent`). Far below goes to review (possible scam), far above only gets a flag."),
    "criteria.nice_to_have": ("Wünschenswertes (balcony, parking); fließt in den Score ein, schließt nichts aus.",
                              "Nice-to-haves (balcony, parking); they raise the score and never exclude."),
    "criteria.area.center": ("Optional: Adresse oder Bahnhof, der als Mitte der Stadt gilt (Bezugspunkt für den Radius).",
                             "Optional: address or station counted as the middle (reference point for the radius)."),
    "criteria.area.max_km": ("Optional: größte Luftlinie zur Mitte in Kilometern; braucht `center`. Unbekannter Ort geht in die Prüfung, nie in die Ablehnung.",
                             "Optional: largest straight-line distance to the centre in km; needs `center`. An unknown location goes to review, never to reject."),
    "criteria.area.include_postal_codes": ("Nur diese Postleitzahlen (Anfänge genügen, z. B. 803). Leer heißt: überall.",
                                           "Only these postcodes (prefixes are enough, e.g. 803). Empty means anywhere."),
    "criteria.area.exclude_postal_codes": ("Diese Postleitzahlen nie (Anfänge genügen).", "Never these postcodes (prefixes are enough)."),
    "criteria.area.exclude_districts": ("Diese Stadtteile nie (Textvergleich, Groß-/Kleinschreibung egal).",
                                        "Never these districts (text match, case does not matter)."),
    "criteria.station.max_walk_minutes": ("Optional: größter Fußweg zur nächsten Haltestelle in Minuten (Schätzung aus der Luftlinie).",
                                          "Optional: longest walk to the nearest stop in minutes (an estimate from the straight line)."),
    "criteria.station.kinds": ("Welche Haltestellen zählen: subway (U-Bahn), rail (S-Bahn/Bahn), tram, bus.",
                               "Which stops count: subway, rail (S-Bahn/rail), tram, bus."),
    "criteria.station.required": ("Ja: ein weiterer Fußweg lehnt die Wohnung ab. Nein: nur der Score nutzt den Weg (Gewicht `scoring.weights.station`).",
                                  "Yes: a longer walk rejects the flat. No: only the score uses it (weight `scoring.weights.station`)."),
    "criteria.station.walking_speed_kmh": ("Gehgeschwindigkeit für die Schätzung in km/h.", "Walking speed for the estimate in km/h."),
    "criteria.station.detour_factor": ("Umwegfaktor: Straßen sind länger als die Luftlinie (mindestens 1).",
                                       "Detour factor: streets are longer than the straight line (at least 1)."),
    "commute.targets[].name": ("Kurzname des Ziels (eindeutig), z. B. arbeit.", "Short unique name of the place, e.g. work."),
    "commute.targets[].destination": ("Adresse oder Bahnhof, so wie ein Routenplaner ihn findet.",
                                      "Address or station as a route planner would find it."),
    "commute.targets[].arrival_time": ("Ankunftszeit am Werktagmorgen (HH:MM).", "Arrival time on a weekday morning (HH:MM)."),
    "commute.targets[].max_pt_minutes": ("Höchstdauer mit öffentlichen Verkehrsmitteln in Minuten (optional, mindestens ein Limit nötig).",
                                         "Longest trip by public transport in minutes (optional; at least one limit is required)."),
    "commute.targets[].max_car_minutes": ("Höchstdauer mit dem Auto in Minuten (optional).", "Longest trip by car in minutes (optional)."),
    "commute.targets[].modes": ("`any`: ein Verkehrsmittel im Limit genügt; `all`: alle genannten müssen passen.",
                                "`any`: one mode within its limit is enough; `all`: every listed mode must pass."),
    "commute.combine": ("`all`: jedes Ziel muss passen; `any`: ein Ziel genügt.", "`all`: every place must pass; `any`: one is enough."),
    "commute.borderline_margin_minutes": ("Minuten Toleranz: Grenzfälle bei geschätzter Adresse gehen in die Prüfung statt in die Ablehnung.",
                                          "Minutes of tolerance: borderline cases with an estimated address go to review instead of reject."),
    "commute.pt_router": ("Routing für den ÖPNV: `motis` (ganz Deutschland) oder `mvg` (nur München, noch nicht gebaut).",
                          "Public-transport router: `motis` (all of Germany) or `mvg` (Munich only, not built yet)."),
    "commute.car_router": ("Routing fürs Auto: `motis` (kostenlos, ohne Verkehrslage) oder `google_routes` (braucht Schlüssel und Abrechnung bei Google).",
                           "Car router: `motis` (free, no live traffic) or `google_routes` (needs a key and a Google billing account)."),
    "commute.car_rush_hour_factor": ("Nur für `motis`: Faktor auf die Fahrzeit ohne Verkehr, damit der Berufsverkehr berücksichtigt wird (Annahme, nicht gemessen).",
                                     "Only for `motis`: multiplier on the free-flow drive time to allow for rush hour (an assumption, not measured)."),
    "commute.motis_base_url": ("Optional: eigener MOTIS-Server; Standard ist die Transitous-Gemeinschaftsinstanz.",
                               "Optional: your own MOTIS server; the default is the community Transitous instance."),
    "commute.car_api_key_env": ("Name der Umgebungsvariable mit dem Google-Routes-Schlüssel (nur nötig bei Auto-Limit).",
                                "Name of the environment variable holding the Google Routes key (only needed for a car limit)."),
    "send_policy.enabled": ("Hauptschalter für das automatische Senden. Aus: nichts geht von allein raus.",
                            "Master switch for automatic sending. Off: nothing goes out on its own."),
    "send_policy.mode": ("`shadow`: nur protokollieren, was gesendet würde; `live`: wirklich senden.",
                         "`shadow`: only log what would be sent; `live`: really send."),
    "send_policy.min_score": ("Mindestscore (0–100) für automatisches Senden.", "Minimum score (0 to 100) for automatic sending."),
    "send_policy.loosen.step_points": ("Um so viele Punkte sinkt die Schwelle je Stufe.", "Points the threshold drops per step."),
    "send_policy.loosen.every_days": ("Alle so viele Tage sinkt die Schwelle um eine Stufe.", "Every this many days the threshold drops one step."),
    "send_policy.loosen.floor": ("Untergrenze der Schwelle; darf `min_score` nicht übersteigen.", "Floor of the threshold; must not exceed `min_score`."),
    "send_policy.daily_cap": ("Höchstzahl automatischer Sendungen pro Tag.", "Maximum automatic sends per day."),
    "send_policy.per_platform_daily_cap": ("Höchstzahl pro Plattform und Tag; nicht größer als `daily_cap`.",
                                           "Maximum per platform per day; not above `daily_cap`."),
    "send_policy.platform_allow_list": ("Plattformen, die automatisch senden dürfen. Für `live` nötig.",
                                        "Platforms allowed to send automatically. Required for `live`."),
    "send_policy.quiet_hours": ("Optional: Ruhezeit `HH:MM-HH:MM` (Berliner Zeit), in der nichts gesendet wird.",
                                "Optional: quiet period `HH:MM-HH:MM` (Berlin time) in which nothing is sent."),
    "send_policy.kill_switch_file": ("Existiert diese Datei, wird nichts gesendet (`mia kill` legt sie an). Nicht in der Oberfläche änderbar.",
                                     "If this file exists nothing is sent (`mia kill` creates it). Not editable in the dashboard."),
    "llm.base_url": ("OpenAI-kompatibler Endpunkt für den kurzen, wohnungsbezogenen Einstiegssatz.",
                     "OpenAI-compatible endpoint for the short, listing-specific opening sentence."),
    "llm.api_key_env": ("Name der Umgebungsvariable mit dem Schlüssel.", "Name of the environment variable holding the key."),
    "llm.timeout_seconds": ("Bei Zeitüberschreitung gilt der feste Textbaustein.", "On timeout the fixed template text is used."),
    "llm.log_answering_model": ("Ja: das antwortende Modell wird im Protokoll vermerkt.", "Yes: the answering model is noted in the audit trail."),
    "notifications.channel": ("Benachrichtigungskanal: `ntfy` oder `telegram` (Telegram noch nicht gebaut).",
                              "Notification channel: `ntfy` or `telegram` (Telegram not built yet)."),
    "notifications.topic_env": ("Name der Umgebungsvariable mit der ntfy-Themen-URL (wirkt wie ein Passwort).",
                                "Name of the environment variable with the ntfy topic URL (acts like a password)."),
    "notifications.heartbeat_hours": ("Alle so viele Stunden kommt ein Lebenszeichen.", "A heartbeat arrives every this many hours."),
    "notifications.silence_alert_hours": ("Optional: Warnung, wenn so lange keine Wohnung gelesen wurde (Standard 48).",
                                          "Optional: warning when no listing was read for this long (default 48)."),
    "storage.db_path": ("Pfad der SQLite-Datenbank. Nicht in der Oberfläche änderbar.", "Path of the SQLite database. Not editable in the dashboard."),
    "replies.imap_host": ("IMAP-Server des Postfachs, in dem Vermieter-Antworten eingehen.", "IMAP server of the inbox that receives landlord replies."),
    "replies.imap_port": ("IMAP-Port (Standard 993).", "IMAP port (default 993)."),
    "replies.folder": ("Ordner (Standard INBOX).", "Folder (default INBOX)."),
    "replies.username_env": ("Name der Umgebungsvariable mit dem Benutzernamen.", "Name of the environment variable with the username."),
    "replies.password_env": ("Name der Umgebungsvariable mit dem Passwort.", "Name of the environment variable with the password."),
    "replies.lookback_days": ("Wie viele Tage zurück nach Antworten gesucht wird.", "How many days back replies are searched."),
    "alerts.imap_host": ("IMAP-Server des Postfachs mit den Portal-Suchaufträgen.", "IMAP server of the inbox with the portal saved-search alerts."),
    "alerts.imap_port": ("IMAP-Port (Standard 993).", "IMAP port (default 993)."),
    "alerts.folder": ("Ordner (Standard INBOX).", "Folder (default INBOX)."),
    "alerts.username_env": ("Name der Umgebungsvariable mit dem Benutzernamen.", "Name of the environment variable with the username."),
    "alerts.password_env": ("Name der Umgebungsvariable mit dem Passwort.", "Name of the environment variable with the password."),
    "alerts.lookback_days": ("Wie viele Tage zurück gelesen wird (Standard 3).", "How many days back are read (default 3)."),
    "alerts.sender_domains": ("Nur Mails von diesen Absender-Domains werden gelesen; Pflichtangabe.", "Only mail from these sender domains is read; required."),
    "smtp.host": ("SMTP-Server zum Senden.", "SMTP server for sending."),
    "smtp.port": ("SMTP-Port (Standard 587, STARTTLS).", "SMTP port (default 587, STARTTLS)."),
    "smtp.username_env": ("Name der Umgebungsvariable mit dem Benutzernamen.", "Name of the environment variable with the username."),
    "smtp.password_env": ("Name der Umgebungsvariable mit dem Passwort.", "Name of the environment variable with the password."),
    "smtp.from_address": ("Absenderadresse der Nachrichten.", "Sender address of the messages."),
    "reply_llm.enabled": ("Ja: ein lokales Modell liest Antworten, die die Regeln nicht einordnen können.",
                          "Yes: a local model reads replies the rules cannot place."),
    "reply_llm.base_url": ("Nur dieser Rechner oder ein privates Netz ist erlaubt (Antworten sind private Post).",
                           "Only this machine or a private network is allowed (replies are private correspondence)."),
    "reply_llm.model": ("Modellname beim lokalen Server.", "Model name on the local server."),
    "reply_llm.timeout_seconds": ("Zeitlimit pro Anfrage in Sekunden.", "Time limit per request in seconds."),
    "reply_llm.api_key_env": ("Optional: Name der Umgebungsvariable mit einem Schlüssel für den lokalen Server.",
                              "Optional: name of the environment variable with a key for the local server."),
    "auto_reply.enabled": ("Ja: Besichtigungsangebote werden automatisch beantwortet. Standard aus.",
                           "Yes: viewing offers are answered automatically. Off by default."),
    "auto_reply.mode": ("`shadow`: nur protokollieren; `live`: wirklich antworten.", "`shadow`: only log; `live`: really answer."),
    "auto_reply.daily_cap": ("Höchstzahl automatischer Antworten pro Tag.", "Maximum automatic replies per day."),
    "auto_reply.max_replies_per_thread": ("Höchstzahl pro Gespräch (Standard 1).", "Maximum per conversation (default 1)."),
    "auto_reply.horizon_days": ("Termine, die weiter entfernt liegen, werden ignoriert (Standard 21).", "Slots further away are ignored (default 21)."),
    "scoring.version": ("Versionskennung der Bewertung; wird im Protokoll gespeichert.", "Version label of the scoring; stored in the audit trail."),
    "scoring.weights.commute": ("Gewicht des Pendelwegs im Score.", "Weight of the commute in the score."),
    "scoring.weights.price": ("Gewicht des Preises.", "Weight of the price."),
    "scoring.weights.size": ("Gewicht der Größe.", "Weight of the size."),
    "scoring.weights.move_in": ("Gewicht des Einzugstermins.", "Weight of the move-in date."),
    "scoring.weights.balcony": ("Gewicht eines Balkons.", "Weight of a balcony."),
    "scoring.weights.parking": ("Gewicht eines Stellplatzes.", "Weight of parking."),
    "scoring.weights.private_landlord": ("Gewicht eines privaten Vermieters.", "Weight of a private landlord."),
    "scoring.weights.freshness": ("Gewicht der Aktualität (Anzeigen wenige Minuten nach Veröffentlichung).", "Weight of freshness (listings minutes after publication)."),
    "scoring.weights.completeness": ("Gewicht der Vollständigkeit der Angaben.", "Weight of how complete the details are."),
    "scoring.weights.station": ("Gewicht des Fußwegs zur Haltestelle; 0 heißt: kein Einfluss (Standard).",
                                "Weight of the walk to a stop; 0 means no effect (default)."),
    # ---- profile.yaml
    "applicants[].first_name": ("Vorname.", "First name."),
    "applicants[].last_name": ("Nachname.", "Last name."),
    "applicants[].age": ("Optional: Alter; wird in der Nachricht genannt.", "Optional: age; stated in the message."),
    "contact.phone": ("Telefonnummer, unter der Vermieter anrufen können (Pflicht).", "Phone number landlords can call (required)."),
    "contact.sender_email": ("Optional: Absenderadresse.", "Optional: sender address."),
    "facts[].id": ("Kurzname der Angabe (eindeutig).", "Short unique name of the fact."),
    "facts[].de": ("Deutscher Wortlaut; nur hier genannte Angaben dürfen in einer Nachricht stehen.",
                   "German wording; only facts listed here may appear in a message."),
    "facts[].en": ("Englischer Wortlaut.", "English wording."),
    "facts[].usage": ("`always`: immer nennen; `if_relevant`: nur wenn die Anzeige ein Stichwort enthält; `on_request`: nur auf Nachfrage anbieten.",
                      "`always`: always state; `if_relevant`: only when the listing has a keyword; `on_request`: only offered on request."),
    "facts[].relevant_if": ("Stichwörter für `if_relevant`.", "Keywords for `if_relevant`."),
    "viewing.de": ("Besichtigungszeiten, ergänzt den Satz „Besichtigungen sind bei uns … möglich“.", "Viewing times in German, completing \"Besichtigungen sind bei uns … möglich\"."),
    "viewing.en": ("Besichtigungszeiten auf Englisch.", "Viewing times in English."),
    "move_in.earliest": ("Frühester Einzug, wie in der Nachricht genannt.", "Earliest move-in as stated in the message."),
    "move_in.latest": ("Spätester Einzug, wie in der Nachricht genannt.", "Latest move-in as stated in the message."),
    "move_in.reason": ("Optional: Grund für den Umzug.", "Optional: reason for the move."),
    "availability.windows[].days": ("Wochentage: mon, tue, wed, thu, fri, sat, sun.", "Weekdays: mon, tue, wed, thu, fri, sat, sun."),
    "availability.windows[].start": ("Beginn des Fensters (HH:MM).", "Start of the window (HH:MM)."),
    "availability.windows[].end": ("Ende des Fensters (HH:MM).", "End of the window (HH:MM)."),
    "availability.viewing_minutes": ("Dauer einer Besichtigung in Minuten.", "Length of a viewing in minutes."),
    "availability.min_notice_hours": ("Mindestvorlauf in Stunden.", "Minimum notice in hours."),
    "availability.blackout_dates": ("Tage, an denen keine Besichtigung möglich ist.", "Days on which no viewing is possible."),
}
SECTIONS: dict[str, tuple[str, str]] = {
    "city": ("Stadt", "City"), "criteria": ("Suchkriterien", "Search criteria"),
    "commute": ("Pendelwege", "Commute"), "send_policy": ("Sendepolitik", "Sending policy"),
    "llm": ("Einstiegssatz (LLM)", "Opening sentence (LLM)"), "notifications": ("Benachrichtigungen", "Notifications"),
    "storage": ("Speicher", "Storage"), "replies": ("Antwort-Postfach", "Reply inbox"),
    "alerts": ("Alert-Postfach", "Alert inbox"), "smtp": ("Senden (SMTP)", "Sending (SMTP)"),
    "reply_llm": ("Lokales Antwort-Modell", "Local reply model"), "auto_reply": ("Automatische Antwort", "Automatic reply"),
    "scoring": ("Bewertung", "Scoring"), "applicants": ("Bewerber", "Applicants"), "contact": ("Kontakt", "Contact"),
    "facts": ("Angaben für Nachrichten", "Facts for messages"), "viewing": ("Besichtigung", "Viewing"),
    "move_in": ("Einzug", "Move-in"), "availability": ("Verfügbarkeit", "Availability"),
}
WORDS = {
    "de": {"title": "Konfigurationsreferenz", "key": "Schlüssel", "type": "Typ", "default": "Standard",
           "desc": "Beschreibung", "required": "Pflicht", "none": "nicht gesetzt", "optional": "optional",
           "text": "Text", "int": "Ganzzahl", "float": "Zahl", "bool": "Ja/Nein", "date": "Datum (JJJJ-MM-TT)",
           "list": "Liste", "path": "Pfad", "yes": "ja", "no": "nein", "cfg": "config.yaml", "prof": "profile.yaml",
           "intro": ("Diese Seite wird aus dem Code erzeugt (`mia docs-config --write`) und ist deshalb nie veraltet. "
                     "Geheimnisse (Passwörter, Schlüssel) stehen nie in diesen Dateien, sondern in der Umgebungsdatei; "
                     "die Konfiguration nennt nur die Variablennamen. Unbekannte Schlüssel sind Fehler."),
           "presets": "Voreinstellungen", "preset_intro": ("Startwerte für `mia init --city <Stadt> --household <Haushalt>` und die "
                      "Einrichtung im Browser. Es sind Beispielwerte zum Anpassen, keine Marktdaten."),
           "city_col": "Stadt", "hh_col": "Haushalt", "hh_desc": "Startwerte", "lang_note": "Englische Version: config-reference.en.md"},
    "en": {"title": "Configuration reference", "key": "Key", "type": "Type", "default": "Default",
           "desc": "Description", "required": "required", "none": "unset", "optional": "optional",
           "text": "text", "int": "integer", "float": "number", "bool": "yes/no", "date": "date (YYYY-MM-DD)",
           "list": "list", "path": "path", "yes": "yes", "no": "no", "cfg": "config.yaml", "prof": "profile.yaml",
           "intro": ("This page is generated from the code (`mia docs-config --write`), so it cannot go stale. "
                     "Secrets (passwords, keys) never live in these files, only in the env file; the configuration "
                     "names the variables. Unknown keys are errors."),
           "presets": "Presets", "preset_intro": ("Starting values for `mia init --city <city> --household <household>` and the "
                      "browser setup. They are example values to adjust, not market data."),
           "city_col": "City", "hh_col": "Household", "hh_desc": "Starting values", "lang_note": "German version: config-reference.de.md"},
}


def _unwrap(ann: typing.Any) -> tuple[typing.Any, bool, bool]:
    """(core type, is_list, is_optional)"""
    optional = False
    origin, args = typing.get_origin(ann), typing.get_args(ann)
    if args and type(None) in args:
        non = [a for a in args if a is not type(None)]
        if len(non) == 1:
            ann, optional = non[0], True
            origin, args = typing.get_origin(ann), typing.get_args(ann)
    if origin is list:
        core, _, _ = _unwrap(args[0])
        return core, True, optional
    return ann, False, optional


def fields(model: type[BaseModel], prefix: str = "") -> typing.Iterator[tuple[str, FieldInfo, typing.Any, bool]]:
    """Leaf fields as (path, field, core type, is_list)."""
    for name, f in model.model_fields.items():
        core, is_list, _ = _unwrap(f.annotation)
        if isinstance(core, type) and issubclass(core, BaseModel):
            yield from fields(core, f"{prefix}{name}{'[]' if is_list else ''}.")
        else:
            yield f"{prefix}{name}", f, core, is_list


def all_paths() -> list[str]:
    return [p for m in (Config, Profile) for p, *_ in fields(m)]


def _type_text(core: typing.Any, is_list: bool, f: FieldInfo, w: dict[str, str]) -> str:
    if typing.get_origin(core) is typing.Literal:
        text = " | ".join(str(a) for a in typing.get_args(core))
    elif core is date:
        text = w["date"]
    elif core is bool:
        text = w["bool"]
    elif core is int:
        text = w["int"]
    elif core is float:
        text = w["float"]
    elif isinstance(core, type) and issubclass(core, Path):
        text = w["path"]
    else:
        text = w["text"]
    if is_list:
        text = f"{w['list']} ({text})"
    for m in f.metadata:
        for attr, sym in (("gt", ">"), ("ge", "≥"), ("le", "≤"), ("lt", "<")):
            if hasattr(m, attr) and getattr(m, attr) is not None:
                text += f", {sym} {getattr(m, attr)}"
    return text


def _default_text(f: FieldInfo, w: dict[str, str]) -> str:
    if f.is_required():
        return f"**{w['required']}**"
    value = f.default_factory() if f.default_factory else f.default
    if value is None:
        return w["none"]
    if isinstance(value, bool):
        return w["yes"] if value else w["no"]
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) or "[]"
    return f"`{value}`"


def render(lang: str = "de") -> str:
    if lang not in WORDS:
        raise ValueError("lang must be 'de' or 'en'")
    w, i = WORDS[lang], 0 if lang == "de" else 1
    out = [f"# {w['title']}", "", w["intro"], "", w["lang_note"], ""]
    for model, file in ((Config, w["cfg"]), (Profile, w["prof"])):
        out += [f"## {file}", ""]
        current = None
        for path, f, core, is_list in fields(model):
            top = path.split(".")[0].split("[")[0]
            if top != current:
                current = top
                out += ["", f"### {SECTIONS[top][i]} (`{top}`)", "", f"| {w['key']} | {w['type']} | {w['default']} | {w['desc']} |",
                        "|---|---|---|---|"]
            out.append(f"| `{path}` | {_type_text(core, is_list, f, w)} | {_default_text(f, w)} | {D[path][i]} |")
        out.append("")
    out += [f"## {w['presets']}", "", w["preset_intro"], "", f"| {w['city_col']} | key |", "|---|---|"]
    out += [f"| {c['label_' + lang]} | `{c['key']}` |" for c in CITIES]
    out += ["", f"| {w['hh_col']} | key | {w['hh_desc']} |", "|---|---|---|"]
    out += [f"| {h['label_' + lang]} | `{h['key']}` | {h['desc_' + lang]} |" for h in HOUSEHOLDS]
    return "\n".join(out) + "\n"


def schema_json() -> str:
    return json.dumps({"config": Config.model_json_schema(), "profile": Profile.model_json_schema()},
                      indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def write_all(out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    files = {"config-reference.de.md": render("de"), "config-reference.en.md": render("en"),
             "config.schema.json": schema_json()}
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8")
    return [out / n for n in files]
