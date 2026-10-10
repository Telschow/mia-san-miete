# Benchmarks

Generated 2026-10-10 on top of commit `55788e2` on Linux x86_64, x86_64, Python 3.13.16.
Reproduce with `mia bench --out docs/benchmarks.md`.

## How to read these numbers

- **Accuracy numbers (parser, classifier, dedup) are measured on fictional corpora that the
  same author wrote as the heuristics.** They show that the code does what it was designed
  to do and where it breaks on the cases we thought of. They are **not** estimates of
  accuracy on real portal mail or real landlord replies. Real-data checks are tracked in
  the repository issues.
- Small samples: the reply corpus is a few dozen messages. One message is worth
  several percentage points.
- Throughput numbers are real measurements on the machine above, with fake routers (no
  network) and no LLM. Real runs are dominated by routing and network latency, which is
  not measured here.

## Alert-mail parser (40 mails, 84 listings)

Listings found: 84/84; spurious listings: 0.

| Field | Recall | Precision | n (truth) |
|---|---|---|---|
| title | 100% | 100% | 84 |
| warm | 100% | 100% | 84 |
| cold | 100% | 100% | 38 |
| area | 100% | 100% | 80 |
| rooms | 100% | 100% | 84 |
| postal | 100% | 100% | 74 |

All fields correct, by mail style:

| Style | Listings | All correct |
|---|---|---|
| A | 19 | 100% |
| B | 19 | 100% |
| C | 19 | 100% |
| D | 17 | 100% |
| E | 10 | 100% |

## Reply classifier, tuning set (103 messages)

The keyword lists were adjusted after a first run on this set, so a high score here mostly shows the fitting worked. Use it as a regression test, not as an accuracy estimate.

Overall accuracy: 100%.

| Category | Precision | Recall | n |
|---|---|---|---|
| viewing_invite | 100% | 100% | 24 |
| documents_request | 100% | 100% | 18 |
| rejection | 100% | 100% | 23 |
| auto_reply | 100% | 100% | 16 |
| other | 100% | 100% | 22 |

## Reply classifier, held-out set (28 messages)

Written after the latest rewrite (the two earlier held-out sets became tuning data once their misses were used) and never tuned against: the more honest number, though still small, fictional and written by the same author.

Overall accuracy: 57%. When the classifier commits to a category other than `other`, it was right 10 of 11 times: it misses more than it mislabels, and unrecognized replies land in `other` (shown as "Needs a look" in the dashboard).

| Category | Precision | Recall | n |
|---|---|---|---|
| viewing_invite | 67% | 40% | 5 |
| documents_request | 100% | 60% | 5 |
| rejection | 100% | 50% | 6 |
| auto_reply | 100% | 40% | 5 |
| other | 35% | 86% | 7 |

Misclassified (known gaps, not fixed on purpose):

- expected `viewing_invite`, got `other`: "Guten Abend,

vielen Dank für Ihre Nachricht. Die Wohnung steht noch z"
- expected `viewing_invite`, got `other`: "Hallo Herr Mustermann, wir sind am Wochenende vor Ort. Schauen Sie ger"
- expected `viewing_invite`, got `other`: "Wir würden uns freuen, Sie bei uns begrüßen zu dürfen. Bitte melden Si"
- expected `documents_request`, got `other`: "Schicken Sie uns bitte noch Ihre letzten drei Lohnzettel."
- expected `documents_request`, got `other`: "Gerne senden wir Ihnen den Bewerberbogen zu. Bitte füllen Sie ihn aus."
- expected `rejection`, got `other`: "Die Wohnung steht nicht mehr zur Verfügung."
- expected `rejection`, got `other`: "Sorry, the flat was taken yesterday."
- expected `rejection`, got `other`: "Leider ist die Wohnung bereits weg.

> Wir bitten um einen Besichtigun"
- expected `auto_reply`, got `other`: "Bin bis 08.11. auf Dienstreise und antworte danach."
- expected `auto_reply`, got `other`: "Ihre E-Mail wurde empfangen. Wir bearbeiten Anfragen in der Reihenfolg"
- expected `auto_reply`, got `other`: "Danke."
- expected `other`, got `viewing_invite`: "Wann wäre denn Ihr Wunsch-Einzugstermin?"

## Viewing-slot extraction (15 messages, deterministic parser)

Written after the parser and never tuned against. What matters for automatic replies is the safety line: a slot that was *not* offered must never be accepted.

- Exactly right: 12/15 messages.
- Slots offered but not found: 3/16 (safe: the reply goes to the review queue).
- Slots found that were not offered: 0 (the number that must stay 0).

- Miss: "Ich kann Ihnen Montag oder Dienstag anbieten, jeweils ab 18 ": got [(11, 3, 18, 0)], expected [(11, 3, 18, 0), (11, 9, 18, 0)]
- Miss: "Wie wäre es mit nächstem Mittwoch 19h?": got [], expected [(11, 4, 19, 0)]
- Miss: "Am 5. November um halb sieben.": got [], expected [(11, 5, 18, 30)]

## Duplicate detection (200 pairs, half same flat, half hard negatives)

Precision 97%, recall 89% (TP 89, FP 3, FN 11, TN 97).
False negatives are expected by design: sparse listings are never merged on weak evidence, which prefers a duplicate notification over silently hiding a flat.

## Pipeline throughput (2000 listings, median of 3 runs)

Ingest, dedup, gates, score, template draft and audit write, fake routers, in-memory database, shadow mode.

- 283 listings/s; per-listing p50 3.87 ms, p95 6.12 ms.

## Template drafts (2000 listings)

- Invalid drafts: 0/2000; 0.06 ms per draft.
- LLM opening acceptance rate: not measured (needs an LLM endpoint).

## Not measured here

- Router latency and cache hit rate (needs a network and a real router).
- Anything on real portal mail, real replies or real listings.
