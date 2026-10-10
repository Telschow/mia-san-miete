# How-to guide: from zero to a safe shadow run

This guide takes you from a fresh clone to a running, supervised flat search, without sending
a single message you did not approve. Follow it in order. Each part says what you should see
when it worked.

Mia is a personal agent for the German rental market. It reads portal alert emails, scores
each flat against your criteria, drafts a truthful message, and (only if you allow it) sends.
Nothing personal is ever committed to the repository.

## 0. What to expect, honestly

- **Shadow first.** Out of the box nothing is sent. The agent decides, logs what it would
  have done, and puts borderline flats in a review queue.
- **Alert-sourced flats cannot be sent automatically yet.** Portal alert emails carry no
  landlord contact address, and platform (browser) senders are not built (issue #23). Today
  the realistic workflow is: Mia finds, scores and drafts; you open the listing and send the
  drafted message yourself (see part 7). Direct sending works only for listings that carry a
  contact email.
- **Several parts are unverified on real data:** the alert-mail parser, the transit router,
  the reply classifier and the slot parser were all tested on fictional data only. Parts 4 and
  5 tell you how to check them on your own mail.
- **Portals restrict automation.** Reading alert emails that you receive yourself is the
  low-risk path. Account bans are a risk you accept if you automate sending. Mia does not
  solve captchas or evade detection.

## 1. What you need

- Python 3.11 or newer and git.
- An email inbox with IMAP access that receives your portal alerts (a dedicated address or
  folder is best).
- Accounts on the portals you use, with saved searches and email alerts.
- A machine that stays on for the scheduled run: a Mac that does not sleep, a Raspberry Pi or
  a small server (see `docs/deploy.md`). Your laptop works while it is awake.
- Optional: the ntfy app on your phone for push notifications.
- Optional: an API key for car routing (Google Routes) if you set a car time limit, and a
  local LLM server (for example Ollama) for the opt-in reply features.

## 2. Try it first on fictional data (5 minutes)

```bash
git clone https://github.com/Telschow/mia-san-miete.git mia && cd mia
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
mia demo
```

Open the link `mia demo` prints. You should see a dashboard with fictional flats, a review
queue with six drafts, and charts. Nothing real is read and nothing is sent. Press Ctrl+C to
stop. Click around: approve a draft, open a flat, toggle dark mode.

## 3. Set up your own private files

Everything about you lives in gitignored files. Nothing below is ever committed.

**Easiest, in the browser:** run `mia gui`. With no configuration yet it opens a short
first-run setup; afterwards the **Settings** tab edits everything (search, places, your facts,
mail inboxes, sending, notifications, policy, automatic replies, scores). Mail passwords are
entered there, stored only in your local env file and never shown again; each inbox has a
"Test connection" button that logs in without sending anything. Changes are validated before
they are saved and apply at once. Everything stays in files on your own computer, so every
person who runs Mia has their own setup.

**Or in the terminal: let the wizard do it.**

```bash
mia init
```

It asks about your search, the places you travel to, your household facts and your mail
settings, validates every answer, and writes `config.yaml`, `profile/profile.yaml`,
`.private-terms` (suggested from your answers: names, phone, addresses, income figures) and the
env file (empty placeholders for the passwords plus a freshly generated ntfy topic). It never
asks for a password, always starts with sending disabled and shadow mode on, refuses to
overwrite existing files unless you pass `--force` (which keeps `.bak` copies), and offers to
install the privacy hook. For scripting, `mia init --answers answers.yaml` asks nothing.
Then continue at part 4. The manual route, which shows what each file contains, follows.

```bash
cp config.example.yaml config.yaml
cp profile/profile.example.yaml profile/profile.yaml
touch .private-terms
mkdir -p ~/.config/mia && cp deploy/env.example ~/.config/mia/env
chmod 600 ~/.config/mia/env
```

### 3.1 `config.yaml`: your search (manual route)

| Section | What to set |
|---|---|
| `city.name` | Your city, for example `Hamburg` (added to partial addresses when routing). |
| `criteria` | Maximum warm and cold rent, minimum size and rooms, move-in window, words that exclude a flat (`exclude_keywords`), minimum lease length. |
| `commute.targets` | Places you travel to (work, university): destination, weekday arrival time and a limit in minutes for public transport and/or car. `combine: all` means every target must pass. |
| `commute.pt_router` | Use `motis` (works for all of Germany). |
| `send_policy` | Leave `enabled: false` and `mode: shadow` for now. |
| `alerts` | The inbox that receives portal alerts (part 4). |
| `notifications` | ntfy settings; the topic URL itself goes in the env file. |
| `storage.db_path` | Where the SQLite database lives (default `./data/housing.db`). |

Then check it:

```bash
mia check-config config.yaml
# config ok (send_policy: enabled=False, mode=shadow)
```

### 3.2 `profile/profile.yaml`: who you are

Names, phone number, the facts a message may state (household, employment, income wording),
viewing availability text and move-in dates. **A message can only state facts listed here**, in
German and English. Leave out anything you do not want a landlord to read. Preview what a
message looks like with fictional listings:

```bash
mia draft-preview tests/fixtures/listings.json --profile profile/profile.yaml
```

You should see German drafts that mention your names and phone and nothing else about you.

### 3.3 The env file: secrets

`~/.config/mia/env` holds passwords and tokens as `NAME=value` lines. The names must match the
`*_env` keys in your config (for example `MIA_ALERT_USER`, `MIA_ALERT_PASSWORD`, `NTFY_TOPIC`).
Use a long random ntfy topic, since anyone who knows the topic can read your notifications.

### 3.4 Keep private data out of git

1. Put every sensitive term, one per line, in `.private-terms`: employers, street names,
   your phone number, full names, income figures.
2. `mia install-hook` installs a pre-commit hook that blocks a commit containing any of them,
   or any email address, mobile number or IBAN.
3. `mia check-private` runs the same scan on demand. It prints file and line, never the match.

## 4. Get alerts into an inbox

1. On each portal, save your search and turn on **instant email alerts**.
2. Send them to a dedicated inbox (or a folder with its own login) so nothing else is read.
3. In `config.yaml`, fill the `alerts` section: IMAP host, the env var names for user and
   password, `folder`, and `sender_domains` (only mail from these domains is read; use the
   domains the alerts really come from).
4. Put the IMAP user and password in the env file.

Supported alert formats are guessed from how the portals' links usually look
(ImmoScout, Kleinanzeigen, WG-Gesucht, Immowelt). **This has not been checked against real
mail.** Part 5 is how you check it.

## 5. Verify on real data (do this before trusting anything)

Load your env file for the commands below:

```bash
set -a; . ~/.config/mia/env; set +a
```

### 5.1 Alert parser

```bash
mia ingest-alerts --config config.yaml
# example output: fetched=12 new_flats=9 duplicates=3 failed=[]
mia gui --config config.yaml --profile profile/profile.yaml
```

Open the **Flats** tab and compare a few rows with the real alert mails: title, rent, size,
rooms, postcode. Empty fields mean the parser did not find them; such flats go to review.
If a portal's mails are not recognised at all, that portal's format needs adding (issue #2).
Reading mail is read-only: your inbox is never changed.

### 5.2 Public-transport router

```bash
mia check-router --config config.yaml --origin "Marienplatz, München"
# example output: work_a: 18 min (arrive Mon 09:00); compare by hand with a journey planner
```

Compare each number with a journey planner (DB Navigator, Google Maps) for the same arrival
time. A big difference or `no route found` means the router needs fixing before the commute
rule can be trusted (issue #3). Without working routing, every flat's commute is unknown and
lands in review (`commute incomplete`), which is safe but noisy.

### 5.3 A full cycle

```bash
mia run --config config.yaml --profile profile/profile.yaml
# example output: fetched=12 new_flats=9 duplicates=3 failed=[] (send_policy enabled=False mode=shadow)
```

This reads alerts, scores, drafts and records every decision. It sends nothing.

## 6. Run in shadow mode for one to two weeks

Schedule the run (part 9), then look at what the agent decided.

```bash
mia shadow-report --config config.yaml --days 14
```

The report lists:

- **Would have been sent**: flats the policy would have sent. Are these flats you really want?
  (false accepts)
- **Queued for review**: borderline or incomplete data. What is missing?
- **Skipped, highest score first**: flats it rejected. Would you have wanted any of these?
  (false rejects)

### Tuning

| Symptom | What to change |
|---|---|
| Good flats are skipped for rent or size | `criteria.max_warm_rent_eur`, `min_area_m2`, `min_rooms` |
| Unwanted flats get through | `criteria.exclude_keywords` (whole words), `min_lease_months` |
| Many flats say `commute incomplete` | Router or API key problem (part 5.2) |
| Commute rejects flats you would take | Raise a target's `max_pt_minutes` or switch `modes` to `any` |
| Scores feel off | `scoring.weights` (relative weights; the score is always 0 to 100) |
| Too few or too many auto-send candidates | `send_policy.min_score` and the `loosen` schedule |

Hard gates (rent, size, move-in date, commute, scam patterns, exclusion words) always win over
the score. The score is deterministic and never touched by an LLM.

## 7. Day to day

### The dashboard

```bash
mia gui --config config.yaml --profile profile/profile.yaml
```

Open the printed link (it contains an access token). **Overview** shows the funnel, flats per
day and reply metrics. **Review queue** holds drafts waiting for you. **Flats** lists every flat
with its score breakdown. **Settings** shows your effective limits (never addresses or
credentials). The kill switch is in the top bar. To use it from your phone, tunnel to your
machine over SSH or a VPN; do not expose the port to the internet (the server speaks plain HTTP).

### Working the review queue

For each card: read the flat's facts and reasons, edit the draft if you like, then either:

- **Approve & send** (works for listings with a contact email, and never in shadow mode), or
- **Send it yourself**: click **Copy message**, then **Open listing**, send it through the portal,
  and click **I sent it myself**. It is recorded as sent by you, the card is cleared and the
  duplicate guard will not send the same flat again.

Keyboard: arrow keys select, `A` approves, `S` skips. The same actions exist on the command
line: `mia queue list`, `mia queue show <id>`, `mia queue approve <id>`, `mia queue skip <id>`.

### Replies and metrics

If your config has a `replies` section, `mia check-replies` matches landlord replies to your
sent messages and sorts them: viewing invite, documents request, rejection, automatic reply,
or **Needs a look**. The keyword classifier misses more than it mislabels (57% on a fresh
fictional test set), so read the "Needs a look" ones yourself. `mia metrics` shows reply rate,
positive rate and median time to reply; with fewer than about 30 sent messages the rates are
noise.

### Notifications

ntfy sends a push per new flat, a heartbeat (default every 24 hours), a warning if no listings
arrived for 48 hours, and an alert when a cycle fails. If you stop receiving heartbeats, the
agent is not running.

### Where the flat may be (optional)

Besides the commute, you can limit the search area: postcodes to include or exclude, districts
to avoid, a straight-line radius around a center (for example the main station), and a limit or a
score bonus for the walk to the nearest metro, S-Bahn or tram stop. Postcode and district lists
need no lookup; the radius and the walk need the flat placed on a map. A flat whose location
cannot be found goes to review, never to reject. Distance and walking time are estimates (straight
line, with a detour factor) and are shown that way in the dashboard. The stop lookup is not verified
against a live server: run `mia check-area --origin "<an address>"` and compare with a map.

### Presets

`mia presets` lists starting values for the ten largest German cities and four household types
(single, couple, family, student or trainee); `mia init --city muenchen --household couple` uses
them, and the browser setup has the same two menus. They are example values to adjust, not market
data, and they never set your rent limit. The full list of settings, in German (default) and
English, is in `docs/config-reference.de.md` and `docs/config-reference.en.md`.

## 8. Opt-in: answering viewing offers

Off by default. Add your weekly availability to the profile, then enable `auto_reply` in shadow
mode first. A slot that fits your windows is confirmed; anything else is drafted for you in the
queue. Full description, guards and limits: the README section "Automatic reply to viewing
offers" and `docs/adr/0004-opt-in-auto-reply-and-local-llm.md`. The optional `reply_llm` only
accepts a model on your own machine or network.

## 9. Run it on a schedule

`deploy/run.sh` runs one cycle every five minutes. Install it as a launchd agent on a Mac or a
systemd timer on a Raspberry Pi; commands and the sleep caveat are in `docs/deploy.md`. Check
that it works:

```bash
tail -f ~/Library/Logs/mia/run.log      # macOS
journalctl -u mia.service -f            # Raspberry Pi
```

A Mac does not run it while asleep. Alert mail waits in the inbox (default lookback: 3 days), so
you lose speed, not flats.

## 10. Going live: the checklist

Do not skip items. Live sending only matters for listings with a contact email today.

- [ ] Shadow mode ran for at least a week and you read `mia shadow-report`.
- [ ] You checked the parser (5.1) and the router (5.2) on your own data.
- [ ] `mia kill` stops sending and `mia resume` lifts it (try both).
- [ ] ntfy notifications reach your phone and the heartbeat arrives.
- [ ] `smtp` is configured and the credentials are in the env file (there is no test-send command yet, so check the sender address twice).
- [ ] `send_policy.daily_cap` is low (for example 3) and `per_platform_daily_cap` lower (2).
- [ ] `platform_allow_list` names exactly one platform you trust.
- [ ] `quiet_hours` are set (for example `"22:00-07:00"`).
- [ ] You backed up `data/housing.db`.

Then set `enabled: true` and `mode: live`. Watch the first sends, check `mia metrics` after a
few days, and raise caps gradually. Messages go out only when all hard gates pass, the score
meets the (loosening) threshold, the duplicate guard, caps, quiet hours and kill switch allow
it, and no document is ever attached.

## 11. Backups, moving machines, stopping

- **Back up** `data/housing.db` (dedup state and audit trail), `config.yaml`,
  `profile/profile.yaml`, `.private-terms` and the env file. Never commit them.
- **Move to another machine**: copy those files, run the common setup there, stop the old
  scheduler first (never run two machines against the same inbox with sending enabled).
- **Stop everything**: `mia kill` (stops sending), then remove the scheduler entry.
- **Retention**: message drafts are deleted after 30 days; the audit table never contains
  message text.

## 12. What the statuses mean

| Status | Meaning |
|---|---|
| `skipped` | A hard gate rejected the flat (reason shown), or it is below the threshold. |
| `queued` | Needs your review: missing or borderline data, or sending is disabled. |
| `shadow_would_send` | Shadow mode: this would have been sent. |
| `sent` | A message was sent. |
| `failed` | Sending failed; three failures in a row pause that platform. |
| `blocked_kill_switch` | The kill switch is on. |
| `blocked_duplicate` | The same physical flat was already sent on another portal. |
| `blocked_quiet_hours` / `blocked_daily_cap` / `blocked_platform_cap` | A send limit applies; the draft stays in the queue. |
| `blocked_platform_failures` | Three failed sends in a row on that platform. |
| `blocked_no_sender` | No way to send this flat (no contact email, or SMTP not configured). |
| `reply_queued` | A drafted answer to a landlord's viewing offer is waiting for you. |

## 13. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `config invalid: ...` | The message names the key. Strict config: unknown keys are errors. Compare with `config.example.yaml`. |
| `profile invalid: applicant names must be filled in` | `profile/profile.yaml` still has the example blanks. |
| `IMAP credentials missing in the environment` | You did not load the env file (`set -a; . ~/.config/mia/env; set +a`) or the variable names differ from the config. |
| `fetched=0` | Wrong `sender_domains`, alerts in another folder, nothing newer than `lookback_days`, or an unrecognised alert format. |
| Flats have empty rent or size | The parser did not understand that portal's mail; see part 5.1. |
| Everything is `queued` with `commute incomplete` | Router unreachable or no API key for car routing: run `mia check-router`. |
| Nothing is ever sent | Expected in shadow mode, with `enabled: false`, or for flats without a contact email. |
| Dashboard says 401 | Open the exact link `mia gui` printed (it sets the token cookie). |
| Dashboard says 403 | You used another address than the one served; add it with `--allow-host`. |
| Silent for 48 hours | You get an ntfy alert; check the scheduler logs and the alert settings on the portals. |
| Replies show "Needs a look" | The keyword classifier could not place them; read them yourself. |
| Pre-commit hook blocks a commit | It found a private term, address, number or IBAN in a tracked file; remove it. |
| `check-private` flags a test file | Build fake numbers at runtime in tests; the repo scan forbids real-looking ones. |

## 14. Privacy at a glance

- Your search, profile, secrets and database stay on your machine and are gitignored.
- The audit table stores ids, scores, reasons and statuses, never message text, reply text or
  email addresses. Drafts for review are kept apart and deleted after 30 days.
- Only the opening sentence of a message can come from an LLM, only from public listing text,
  and a validator checks it against your profile. Landlord replies go to a model only if you
  enable a local one.
- The demo and all test data are fictional.

## 15. What is verified and what is not

| Part | Status |
|---|---|
| Scoring, gates, send policy, dedup, queue, dashboard | Unit and randomized tests; CI on Python 3.11 to 3.13 |
| Alert-mail parser | Fictional mails only; unverified on real portal mail (issue #2) |
| MOTIS transit router | Not verified against a live server (issue #3) |
| Reply classifier | 57% on a small fictional held-out set; misses land in "Needs a look" (issue #26) |
| Slot parser and auto-reply | Fictional tests; not run on real replies (issue #27) |
| Platform (browser) senders | Not built (issue #23) |

Benchmarks and their limits: `docs/benchmarks.md`. Roadmap: `docs/roadmap.md`.
