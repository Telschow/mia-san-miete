---
layout: home
title: Mia san Miete
---

*Servus!* Mia is a personal agent for the German rental market. It reads the alert emails your
portals send you, filters and scores every flat with fixed rules, drafts a truthful message, and
sends only under an explicit, capped policy, with you in control. **Shadow mode and a kill switch
are the default: out of the box nothing is ever sent.**

The name is a Bavarian pun on *Mia san mia* ("we are who we are"). The tool is not tied to Munich
or to one person: ten large cities and four household types ship as presets.

<img src="images/dashboard-overview-light.png" alt="The dashboard with fictional demo data" width="100%">

<sub>Fictional demo data. Themes: Paper, Slate, Weiß-Blau, Bayern Nacht and High contrast.</sub>

## What it does, and what it does not

| It does | It does not |
|---|---|
| Read portal alert emails over read-only IMAP | Scrape portals or log in to them |
| Apply hard gates: rent, size, rooms, move-in, commute, area, scam signals | Solve captchas or evade detection |
| Score flats deterministically (0 to 100); no language model touches the score | Send through a portal for you: you send from the portal, or approve the email path in the queue |
| Draft a short message that may state only the facts you listed | Invent anything about you |
| Keep an approval queue, a content-free audit trail and a shadow report | Send anything while `send_policy.enabled` is `false` |

## How a flat travels through it

```
alert email  ->  parse  ->  dedup  ->  hard gates  ->  commute and area  ->  score
                                                                               |
                          skip   <-   decision (policy, caps, quiet hours)   <-+
                          review queue  /  would-send (shadow)  /  send
```

A language model, if you run one, only writes one or two sentences about the listing; a validator
checks the draft against your allow-list of facts and falls back to a fixed template.

## Where it stands

Checked on real data (Munich, October 2026), with the limits that implies:

| Part | Result |
|---|---|
| ImmoScout24 alert mails | parsed fully: title, rent (warm only), size, rooms, district |
| Immowelt alert mails | click-tracking links only; one redirect lookup per flat works for most cards |
| Kleinanzeigen, WG-Gesucht, immobilien.de | formats **not yet verified** (account mails only so far) |
| Public-transport and car routing (MOTIS) | works; times are door to door |
| Scheduled shadow run on a Mac | every 5 minutes, nothing sent |

Plan and open work: [roadmap](roadmap.html). Portals restrict automated access; account bans are
an accepted risk if you ever automate sending. See the [portal automation ADR](adr/0006-portal-automation.html).

## Get started

```bash
git clone https://github.com/Telschow/mia-san-miete.git mia && cd mia
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
mia demo          # dashboard on fictional data, nothing real is read or sent
mia init          # guided setup: writes your private, gitignored files
```

Everything personal lives in gitignored files (`config.yaml`, `profile/profile.yaml`, the env
file, `.private-terms`); a pre-commit hook blocks commits that contain your sensitive terms.

## Documentation

- [How-to guide](how-to.html): from a fresh clone to a supervised shadow run
- [Deployment](deploy.html): Mac (launchd) and Raspberry Pi (systemd)
- Configuration reference: [English](config-reference.en.html), [Deutsch](config-reference.de.html)
- [Roadmap](roadmap.html) and [benchmarks](benchmarks.html)
- Decisions: [auto-send policy](adr/0001-housing-auto-send-policy.html), [sources and Fredy](adr/0002-discovery-sources-and-fredy.html),
  [dashboard](adr/0003-dashboard-gui-stack.html), [auto-reply](adr/0004-opt-in-auto-reply-and-local-llm.html),
  [settings editor](adr/0005-dashboard-settings-editor.html), [portal automation](adr/0006-portal-automation.html),
  [click-link resolution](adr/0007-click-link-resolution.html)
- [Source code and issues on GitHub](https://github.com/Telschow/mia-san-miete)

MIT licensed.
