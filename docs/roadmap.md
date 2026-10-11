# Roadmap

**Status (2026-10-11):** the first real-data checks are done and a scheduled shadow run is live on a Mac. Verified: the ImmoScout24 alert parser (#2, partly), the MOTIS router (#3), `mia run` and the launchd deployment. Immowelt works partly through redirect lookups (`docs/adr/0007-click-link-resolution.md`). Not yet verified: Kleinanzeigen, WG-Gesucht and immobilien.de alert formats (only account mails have arrived), the reply monitor and metrics, the Pi deployment. Added from the real run: price-per-m² market check and stronger scam signals, `criteria.move_in.unknown`, a free MOTIS car router, `mia market-rent`, parser diagnostics (`--link-shapes`, `--show-mail`), TLS via certifi, `MIA_VENV` for the scheduler.

**Next:** run the shadow run for one to two weeks and review `mia shadow-report` for false rejects; verify the other portals once real alerts arrive; make setup portal-guided ("add a portal" with a mailbox check); limit push notifications to flats that are not skipped.

**Earlier:** presets and the generated config reference (#15), area limits and walking distance to a stop, `mia init` (#14), the per-flat commute view (#13), the how-to guide (`docs/how-to.md`, #19), CI, labeled fictional corpora, benchmarks, the MIT license and a manual-send flow. Platform automation is an open decision (`docs/adr/0006-portal-automation.md`).

Phases P0 to P4 are done. Order matters: verify before you build more.

Issue links: https://github.com/Telschow/mia-san-miete/issues

| Milestone | Goal | Issues |
|---|---|---|
| M1: Verify and shadow run | Prove discovery, scoring and drafting on real data, sending nothing | #2 parser check, #3 MOTIS check, #4 approval queue CLI, #5 heartbeat and alerts, #6 shadow report |
| M2: Quality, CI and benchmarks | Automated checks and measured, reproducible numbers | #7 CI, #8 benchmark suite, #9 labeled corpora, #10 safety invariants |
| M3: Dashboard GUI | Local web dashboard: metrics, approval queue, controls | #11 foundation, #12 approval queue, #13 controls and polish |
| M4: Customization and onboarding | Fit any city and life situation without code changes | #14 `mia init`, #15 config reference and presets, #16 extension points, #17 editable templates |
| M5: Docs, how-to and demo | Guide, refreshed docs, demo data, demo video | #18 `mia demo`, #19 how-to guide, #20 docs refresh, #21 demo video and post |
| M6: Go-live and more sources | Live sending, platform senders, more sources | #22 go-live checklist, #23 platform senders ADR, #24 MVG, Fredy, pollers, #25 feedback loop |

## Dependencies

- #4 (approval queue) is the backend for #12 (GUI queue).
- #9 (corpora) feeds #8 (benchmarks); #8, #11 and #18 feed #21 (video).
- #6 (reviewed shadow run) gates #22 (going live).
- Nothing in M3 to M5 changes the safety defaults: shadow mode and the kill switch stay on
  by default.

## Principles

- No published number without a reproducible benchmark behind it.
- All screenshots, demos and fixtures use fictional data only; `mia check-private` runs in CI.
- Portal automation stays a user-accepted risk; no captcha solving or detection evasion.
