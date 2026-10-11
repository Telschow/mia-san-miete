# Roadmap

**Status (2026-10-11):** the first real-data checks are done and a scheduled shadow run is live on a Mac. Verified: the ImmoScout24 alert parser (#2, partly), the MOTIS router (#3, closed), `mia run` and the launchd deployment. Immowelt works partly through redirect lookups (`docs/adr/0007-click-link-resolution.md`). Not yet verified: Kleinanzeigen, WG-Gesucht and immobilien.de alert formats (only account mails have arrived), the reply monitor and metrics, the Pi deployment. Added from the real run: price-per-m² market check and stronger scam signals, `criteria.move_in.unknown`, a free MOTIS car router, `mia market-rent`, parser diagnostics (`--link-shapes`, `--show-mail`), TLS via certifi, `MIA_VENV` for the scheduler.

**Next:** run the shadow run for one to two weeks and review `mia shadow-report` for false rejects; verify the other portals once real alerts arrive; make setup portal-guided ("add a portal" with a mailbox check, #33); limit push notifications to flats that are not skipped (#34).

**Earlier:** presets and the generated config reference (#31), area limits and walking distance to a stop (#20), `mia init` (#30), the per-flat commute view, the how-to guide (`docs/how-to.md`, #9), CI, labeled fictional corpora, benchmarks, the MIT license and a manual-send flow. Platform automation is an open decision (`docs/adr/0006-portal-automation.md`).

Phases P0 to P4 are done. Order matters: verify before you build more.

Issue links: https://github.com/Telschow/mia-san-miete/issues

| Milestone | Goal | Issues |
|---|---|---|
| M1: Verify and shadow run | Prove discovery, scoring and drafting on real data, sending nothing | #2 parser check, #3 MOTIS check (closed), #22 approval queue CLI, #23 heartbeat and alerts, #24 shadow report, #32 verify the other portals, #34 quieter notifications |
| M2: Quality, CI and benchmarks | Automated checks and measured, reproducible numbers | #25 CI, #4 benchmark suite, #26 labeled corpora, #27 safety invariants, #16 reply classifier |
| M3: Dashboard GUI | Local web dashboard: metrics, approval queue, settings | #28 foundation, #29 approval queue, #18 settings editor, #5 controls and polish, #19 redesign and themes |
| M4: Customization and onboarding | Fit any city and life situation without code changes | #30 `mia init`, #31 config reference and presets, #20 area and walking distance, #6 extension points, #7 editable templates, #33 portal-guided setup, #36 lease length |
| M5: Docs, how-to and demo | Guide, refreshed docs, demo data | #8 `mia demo`, #9 how-to guide, #10 docs refresh |
| M6: Go-live and more sources | Live sending, platform senders, more sources | #12 go-live checklist, #13 platform senders, #14 MVG, Fredy, pollers, #15 feedback loop, #17 automatic replies, #35 Immowelt coverage |
| M7: Make it public | Publication checklist, demo video and post | #21 pre-publication checklist, #11 demo video and post |

## Dependencies

- #22 (approval queue CLI) is the backend for #29 (GUI queue).
- #26 (corpora) feeds #4 (benchmarks); #4, #28 and #8 feed #11 (video).
- #24 (reviewed shadow run) gates #12 (going live).
- Nothing in M3 to M5 changes the safety defaults: shadow mode and the kill switch stay on
  by default.

## Principles

- No published number without a reproducible benchmark behind it.
- All screenshots, demos and fixtures use fictional data only; `mia check-private` runs in CI.
- Portal automation stays a user-accepted risk; no captcha solving or detection evasion.
