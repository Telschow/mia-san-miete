# Konfigurationsreferenz

Diese Seite wird aus dem Code erzeugt (`mia docs-config --write`) und ist deshalb nie veraltet. Geheimnisse (Passwörter, Schlüssel) stehen nie in diesen Dateien, sondern in der Umgebungsdatei; die Konfiguration nennt nur die Variablennamen. Unbekannte Schlüssel sind Fehler.

Englische Version: config-reference.en.md

## config.yaml


### Stadt (`city`)

| Schlüssel | Typ | Standard | Beschreibung |
|---|---|---|---|
| `city.name` | Text | **Pflicht** | Stadt; wird an unvollständige Adressen angehängt, damit sie gefunden werden. |

### Suchkriterien (`criteria`)

| Schlüssel | Typ | Standard | Beschreibung |
|---|---|---|---|
| `criteria.max_warm_rent_eur` | Ganzzahl, > 0 | **Pflicht** | Höchste Warmmiete pro Monat in Euro; teurere Wohnungen werden aussortiert. |
| `criteria.max_cold_rent_eur` | Ganzzahl, > 0 | **Pflicht** | Höchste Kaltmiete pro Monat in Euro; darf die Warmmiete nicht übersteigen. |
| `criteria.min_area_m2` | Ganzzahl, > 0 | **Pflicht** | Mindestwohnfläche in Quadratmetern. |
| `criteria.min_rooms` | Zahl, > 0 | **Pflicht** | Mindestzahl der Zimmer (Halbe erlaubt, z. B. 2.5). |
| `criteria.move_in.ideal_from` | Datum (JJJJ-MM-TT) | **Pflicht** | Wunschtermin für den Einzug. |
| `criteria.move_in.latest` | Datum (JJJJ-MM-TT) | **Pflicht** | Spätester akzeptabler Einzug; danach wird aussortiert. |
| `criteria.move_in.early_flex_days` | Ganzzahl, ≥ 0 | `0` | Tage vor dem Wunschtermin, die noch durchgehen (mit Hinweis, niedrigerer Score). |
| `criteria.exclude_keywords` | Liste (Text) | [] | Ganze Wörter, die eine Wohnung ausschließen (z. B. WBS, Tausch). Verneinungen wie „kein WBS“ werden erkannt. |
| `criteria.min_lease_months` | Ganzzahl, ≥ 0 | **Pflicht** | Mindestmietdauer in Monaten; kürzere oder unbekannte Befristung (Zwischenmiete) wird aussortiert. |
| `criteria.nice_to_have` | Liste (Text) | [] | Wünschenswertes (balcony, parking); fließt in den Score ein, schließt nichts aus. |
| `criteria.area.center` | Text | nicht gesetzt | Optional: Adresse oder Bahnhof, der als Mitte der Stadt gilt (Bezugspunkt für den Radius). |
| `criteria.area.max_km` | Zahl, > 0 | nicht gesetzt | Optional: größte Luftlinie zur Mitte in Kilometern; braucht `center`. Unbekannter Ort geht in die Prüfung, nie in die Ablehnung. |
| `criteria.area.include_postal_codes` | Liste (Text) | [] | Nur diese Postleitzahlen (Anfänge genügen, z. B. 803). Leer heißt: überall. |
| `criteria.area.exclude_postal_codes` | Liste (Text) | [] | Diese Postleitzahlen nie (Anfänge genügen). |
| `criteria.area.exclude_districts` | Liste (Text) | [] | Diese Stadtteile nie (Textvergleich, Groß-/Kleinschreibung egal). |
| `criteria.station.max_walk_minutes` | Ganzzahl, > 0 | nicht gesetzt | Optional: größter Fußweg zur nächsten Haltestelle in Minuten (Schätzung aus der Luftlinie). |
| `criteria.station.kinds` | Liste (subway | rail | tram | bus) | subway, rail, tram | Welche Haltestellen zählen: subway (U-Bahn), rail (S-Bahn/Bahn), tram, bus. |
| `criteria.station.required` | Ja/Nein | nein | Ja: ein weiterer Fußweg lehnt die Wohnung ab. Nein: nur der Score nutzt den Weg (Gewicht `scoring.weights.station`). |
| `criteria.station.walking_speed_kmh` | Zahl, > 0 | `4.8` | Gehgeschwindigkeit für die Schätzung in km/h. |
| `criteria.station.detour_factor` | Zahl, ≥ 1 | `1.3` | Umwegfaktor: Straßen sind länger als die Luftlinie (mindestens 1). |

### Pendelwege (`commute`)

| Schlüssel | Typ | Standard | Beschreibung |
|---|---|---|---|
| `commute.targets[].name` | Text | **Pflicht** | Kurzname des Ziels (eindeutig), z. B. arbeit. |
| `commute.targets[].destination` | Text | **Pflicht** | Adresse oder Bahnhof, so wie ein Routenplaner ihn findet. |
| `commute.targets[].arrival_time` | Text | **Pflicht** | Ankunftszeit am Werktagmorgen (HH:MM). |
| `commute.targets[].max_pt_minutes` | Ganzzahl, > 0 | nicht gesetzt | Höchstdauer mit öffentlichen Verkehrsmitteln in Minuten (optional, mindestens ein Limit nötig). |
| `commute.targets[].max_car_minutes` | Ganzzahl, > 0 | nicht gesetzt | Höchstdauer mit dem Auto in Minuten (optional). |
| `commute.targets[].modes` | any | all | `any` | `any`: ein Verkehrsmittel im Limit genügt; `all`: alle genannten müssen passen. |
| `commute.combine` | all | any | `all` | `all`: jedes Ziel muss passen; `any`: ein Ziel genügt. |
| `commute.borderline_margin_minutes` | Ganzzahl, ≥ 0 | **Pflicht** | Minuten Toleranz: Grenzfälle bei geschätzter Adresse gehen in die Prüfung statt in die Ablehnung. |
| `commute.pt_router` | mvg | motis | **Pflicht** | Routing für den ÖPNV: `motis` (ganz Deutschland) oder `mvg` (nur München, noch nicht gebaut). |
| `commute.car_router` | google_routes | **Pflicht** | Routing fürs Auto; derzeit nur `google_routes`. |
| `commute.motis_base_url` | Text | nicht gesetzt | Optional: eigener MOTIS-Server; Standard ist die Transitous-Gemeinschaftsinstanz. |
| `commute.car_api_key_env` | Text | `GOOGLE_ROUTES_API_KEY` | Name der Umgebungsvariable mit dem Google-Routes-Schlüssel (nur nötig bei Auto-Limit). |

### Sendepolitik (`send_policy`)

| Schlüssel | Typ | Standard | Beschreibung |
|---|---|---|---|
| `send_policy.enabled` | Ja/Nein | nein | Hauptschalter für das automatische Senden. Aus: nichts geht von allein raus. |
| `send_policy.mode` | shadow | live | `shadow` | `shadow`: nur protokollieren, was gesendet würde; `live`: wirklich senden. |
| `send_policy.min_score` | Ganzzahl, ≥ 0, ≤ 100 | **Pflicht** | Mindestscore (0–100) für automatisches Senden. |
| `send_policy.loosen.step_points` | Ganzzahl, > 0 | **Pflicht** | Um so viele Punkte sinkt die Schwelle je Stufe. |
| `send_policy.loosen.every_days` | Ganzzahl, > 0 | **Pflicht** | Alle so viele Tage sinkt die Schwelle um eine Stufe. |
| `send_policy.loosen.floor` | Ganzzahl, ≥ 0, ≤ 100 | **Pflicht** | Untergrenze der Schwelle; darf `min_score` nicht übersteigen. |
| `send_policy.daily_cap` | Ganzzahl, ≥ 0 | **Pflicht** | Höchstzahl automatischer Sendungen pro Tag. |
| `send_policy.per_platform_daily_cap` | Ganzzahl, ≥ 0 | **Pflicht** | Höchstzahl pro Plattform und Tag; nicht größer als `daily_cap`. |
| `send_policy.platform_allow_list` | Liste (Text) | [] | Plattformen, die automatisch senden dürfen. Für `live` nötig. |
| `send_policy.quiet_hours` | Text | nicht gesetzt | Optional: Ruhezeit `HH:MM-HH:MM` (Berliner Zeit), in der nichts gesendet wird. |
| `send_policy.kill_switch_file` | Pfad | **Pflicht** | Existiert diese Datei, wird nichts gesendet (`mia kill` legt sie an). Nicht in der Oberfläche änderbar. |

### Einstiegssatz (LLM) (`llm`)

| Schlüssel | Typ | Standard | Beschreibung |
|---|---|---|---|
| `llm.base_url` | Text | **Pflicht** | OpenAI-kompatibler Endpunkt für den kurzen, wohnungsbezogenen Einstiegssatz. |
| `llm.api_key_env` | Text | **Pflicht** | Name der Umgebungsvariable mit dem Schlüssel. |
| `llm.timeout_seconds` | Zahl, > 0 | **Pflicht** | Bei Zeitüberschreitung gilt der feste Textbaustein. |
| `llm.log_answering_model` | Ja/Nein | ja | Ja: das antwortende Modell wird im Protokoll vermerkt. |

### Benachrichtigungen (`notifications`)

| Schlüssel | Typ | Standard | Beschreibung |
|---|---|---|---|
| `notifications.channel` | ntfy | telegram | **Pflicht** | Benachrichtigungskanal: `ntfy` oder `telegram` (Telegram noch nicht gebaut). |
| `notifications.topic_env` | Text | **Pflicht** | Name der Umgebungsvariable mit der ntfy-Themen-URL (wirkt wie ein Passwort). |
| `notifications.heartbeat_hours` | Ganzzahl, > 0 | **Pflicht** | Alle so viele Stunden kommt ein Lebenszeichen. |
| `notifications.silence_alert_hours` | Ganzzahl, > 0 | `48` | Optional: Warnung, wenn so lange keine Wohnung gelesen wurde (Standard 48). |

### Speicher (`storage`)

| Schlüssel | Typ | Standard | Beschreibung |
|---|---|---|---|
| `storage.db_path` | Pfad | **Pflicht** | Pfad der SQLite-Datenbank. Nicht in der Oberfläche änderbar. |

### Antwort-Postfach (`replies`)

| Schlüssel | Typ | Standard | Beschreibung |
|---|---|---|---|
| `replies.imap_host` | Text | **Pflicht** | IMAP-Server des Postfachs, in dem Vermieter-Antworten eingehen. |
| `replies.imap_port` | Ganzzahl | `993` | IMAP-Port (Standard 993). |
| `replies.folder` | Text | `INBOX` | Ordner (Standard INBOX). |
| `replies.username_env` | Text | **Pflicht** | Name der Umgebungsvariable mit dem Benutzernamen. |
| `replies.password_env` | Text | **Pflicht** | Name der Umgebungsvariable mit dem Passwort. |
| `replies.lookback_days` | Ganzzahl, > 0 | `30` | Wie viele Tage zurück nach Antworten gesucht wird. |

### Alert-Postfach (`alerts`)

| Schlüssel | Typ | Standard | Beschreibung |
|---|---|---|---|
| `alerts.imap_host` | Text | **Pflicht** | IMAP-Server des Postfachs mit den Portal-Suchaufträgen. |
| `alerts.imap_port` | Ganzzahl | `993` | IMAP-Port (Standard 993). |
| `alerts.folder` | Text | `INBOX` | Ordner (Standard INBOX). |
| `alerts.username_env` | Text | **Pflicht** | Name der Umgebungsvariable mit dem Benutzernamen. |
| `alerts.password_env` | Text | **Pflicht** | Name der Umgebungsvariable mit dem Passwort. |
| `alerts.lookback_days` | Ganzzahl, > 0 | `3` | Wie viele Tage zurück gelesen wird (Standard 3). |
| `alerts.sender_domains` | Liste (Text) | **Pflicht** | Nur Mails von diesen Absender-Domains werden gelesen; Pflichtangabe. |

### Senden (SMTP) (`smtp`)

| Schlüssel | Typ | Standard | Beschreibung |
|---|---|---|---|
| `smtp.host` | Text | **Pflicht** | SMTP-Server zum Senden. |
| `smtp.port` | Ganzzahl | `587` | SMTP-Port (Standard 587, STARTTLS). |
| `smtp.username_env` | Text | **Pflicht** | Name der Umgebungsvariable mit dem Benutzernamen. |
| `smtp.password_env` | Text | **Pflicht** | Name der Umgebungsvariable mit dem Passwort. |
| `smtp.from_address` | Text | **Pflicht** | Absenderadresse der Nachrichten. |

### Lokales Antwort-Modell (`reply_llm`)

| Schlüssel | Typ | Standard | Beschreibung |
|---|---|---|---|
| `reply_llm.enabled` | Ja/Nein | nein | Ja: ein lokales Modell liest Antworten, die die Regeln nicht einordnen können. |
| `reply_llm.base_url` | Text | `http://localhost:11434/v1` | Nur dieser Rechner oder ein privates Netz ist erlaubt (Antworten sind private Post). |
| `reply_llm.model` | Text | `llama3.1` | Modellname beim lokalen Server. |
| `reply_llm.timeout_seconds` | Zahl, > 0 | `20` | Zeitlimit pro Anfrage in Sekunden. |
| `reply_llm.api_key_env` | Text | nicht gesetzt | Optional: Name der Umgebungsvariable mit einem Schlüssel für den lokalen Server. |

### Automatische Antwort (`auto_reply`)

| Schlüssel | Typ | Standard | Beschreibung |
|---|---|---|---|
| `auto_reply.enabled` | Ja/Nein | nein | Ja: Besichtigungsangebote werden automatisch beantwortet. Standard aus. |
| `auto_reply.mode` | shadow | live | `shadow` | `shadow`: nur protokollieren; `live`: wirklich antworten. |
| `auto_reply.daily_cap` | Ganzzahl, ≥ 0 | `5` | Höchstzahl automatischer Antworten pro Tag. |
| `auto_reply.max_replies_per_thread` | Ganzzahl, ≥ 1 | `1` | Höchstzahl pro Gespräch (Standard 1). |
| `auto_reply.horizon_days` | Ganzzahl, > 0 | `21` | Termine, die weiter entfernt liegen, werden ignoriert (Standard 21). |

### Bewertung (`scoring`)

| Schlüssel | Typ | Standard | Beschreibung |
|---|---|---|---|
| `scoring.version` | Text | `1` | Versionskennung der Bewertung; wird im Protokoll gespeichert. |
| `scoring.weights.commute` | Zahl, ≥ 0 | `25` | Gewicht des Pendelwegs im Score. |
| `scoring.weights.price` | Zahl, ≥ 0 | `20` | Gewicht des Preises. |
| `scoring.weights.size` | Zahl, ≥ 0 | `10` | Gewicht der Größe. |
| `scoring.weights.move_in` | Zahl, ≥ 0 | `15` | Gewicht des Einzugstermins. |
| `scoring.weights.balcony` | Zahl, ≥ 0 | `5` | Gewicht eines Balkons. |
| `scoring.weights.parking` | Zahl, ≥ 0 | `3` | Gewicht eines Stellplatzes. |
| `scoring.weights.private_landlord` | Zahl, ≥ 0 | `7` | Gewicht eines privaten Vermieters. |
| `scoring.weights.freshness` | Zahl, ≥ 0 | `10` | Gewicht der Aktualität (Anzeigen wenige Minuten nach Veröffentlichung). |
| `scoring.weights.completeness` | Zahl, ≥ 0 | `5` | Gewicht der Vollständigkeit der Angaben. |
| `scoring.weights.station` | Zahl, ≥ 0 | `0` | Gewicht des Fußwegs zur Haltestelle; 0 heißt: kein Einfluss (Standard). |

## profile.yaml


### Bewerber (`applicants`)

| Schlüssel | Typ | Standard | Beschreibung |
|---|---|---|---|
| `applicants[].first_name` | Text | **Pflicht** | Vorname. |
| `applicants[].last_name` | Text | **Pflicht** | Nachname. |
| `applicants[].age` | Ganzzahl | nicht gesetzt | Optional: Alter; wird in der Nachricht genannt. |

### Kontakt (`contact`)

| Schlüssel | Typ | Standard | Beschreibung |
|---|---|---|---|
| `contact.phone` | Text | **Pflicht** | Telefonnummer, unter der Vermieter anrufen können (Pflicht). |
| `contact.sender_email` | Text | `` | Optional: Absenderadresse. |

### Angaben für Nachrichten (`facts`)

| Schlüssel | Typ | Standard | Beschreibung |
|---|---|---|---|
| `facts[].id` | Text | **Pflicht** | Kurzname der Angabe (eindeutig). |
| `facts[].de` | Text | **Pflicht** | Deutscher Wortlaut; nur hier genannte Angaben dürfen in einer Nachricht stehen. |
| `facts[].en` | Text | **Pflicht** | Englischer Wortlaut. |
| `facts[].usage` | always | if_relevant | on_request | **Pflicht** | `always`: immer nennen; `if_relevant`: nur wenn die Anzeige ein Stichwort enthält; `on_request`: nur auf Nachfrage anbieten. |
| `facts[].relevant_if` | Liste (Text) | [] | Stichwörter für `if_relevant`. |

### Besichtigung (`viewing`)

| Schlüssel | Typ | Standard | Beschreibung |
|---|---|---|---|
| `viewing.de` | Text | **Pflicht** | Besichtigungszeiten, ergänzt den Satz „Besichtigungen sind bei uns … möglich“. |
| `viewing.en` | Text | **Pflicht** | Besichtigungszeiten auf Englisch. |

### Einzug (`move_in`)

| Schlüssel | Typ | Standard | Beschreibung |
|---|---|---|---|
| `move_in.earliest` | Datum (JJJJ-MM-TT) | **Pflicht** | Frühester Einzug, wie in der Nachricht genannt. |
| `move_in.latest` | Datum (JJJJ-MM-TT) | **Pflicht** | Spätester Einzug, wie in der Nachricht genannt. |
| `move_in.reason` | Text | `` | Optional: Grund für den Umzug. |

### Verfügbarkeit (`availability`)

| Schlüssel | Typ | Standard | Beschreibung |
|---|---|---|---|
| `availability.windows[].days` | Liste (mon | tue | wed | thu | fri | sat | sun) | **Pflicht** | Wochentage: mon, tue, wed, thu, fri, sat, sun. |
| `availability.windows[].start` | Text | **Pflicht** | Beginn des Fensters (HH:MM). |
| `availability.windows[].end` | Text | **Pflicht** | Ende des Fensters (HH:MM). |
| `availability.viewing_minutes` | Ganzzahl, > 0 | `30` | Dauer einer Besichtigung in Minuten. |
| `availability.min_notice_hours` | Ganzzahl, ≥ 0 | `12` | Mindestvorlauf in Stunden. |
| `availability.blackout_dates` | Liste (Datum (JJJJ-MM-TT)) | [] | Tage, an denen keine Besichtigung möglich ist. |

## Voreinstellungen

Startwerte für `mia init --city <Stadt> --household <Haushalt>` und die Einrichtung im Browser. Es sind Beispielwerte zum Anpassen, keine Marktdaten.

| Stadt | key |
|---|---|
| Berlin | `berlin` |
| Hamburg | `hamburg` |
| München | `muenchen` |
| Köln | `koeln` |
| Frankfurt am Main | `frankfurt` |
| Stuttgart | `stuttgart` |
| Düsseldorf | `duesseldorf` |
| Leipzig | `leipzig` |
| Dortmund | `dortmund` |
| Essen | `essen` |

| Haushalt | key | Startwerte |
|---|---|---|
| Single | `single` | 1 Person, ab 1 Zimmer und 28 m², Mindestmietdauer 24 Monate |
| Paar | `couple` | 2 Personen, ab 2 Zimmer und 45 m², Mindestmietdauer 24 Monate |
| Familie | `family` | 2 Personen, ab 3 Zimmer und 65 m², Mindestmietdauer 24 Monate |
| Studium oder Ausbildung | `student` | 1 Person, ab 1 Zimmer und 14 m², Mindestmietdauer 12 Monate, WG-Angebote erlaubt |
