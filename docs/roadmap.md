# Roadmap

**Update:** presets and the generated config reference (#15), area limits and walking distance to a stop, the MIT license and a manual-send flow are in; platform automation is an open decision (`docs/adr/0006-portal-automation.md`).

**Earlier:** `mia init` (#14) and the per-flat commute view (#13) are built. The how-to guide (`docs/how-to.md`, #19) is written. M2 is mostly built too (CI workflow, labeled fictional corpora, `mia bench`, randomized safety-invariant tests). Its first finding: the reply classifier generalizes poorly (see `docs/benchmarks.md`). M1 and M3 are mostly built (approval queue, heartbeat and alerts, shadow report, router probe, dashboard, `mia demo`). Still open there: #2 and #3 need real alert mails and your network (`mia check-router`), and #13 still lacks the commute map.

Phases P0 to P4 are done; the reply monitor, metrics, alert-email source, MOTIS router,
`mia run` and the Mac/Pi deployment are built but **not yet verified on real data**. The
remaining work is tracked as GitHub milestones. Order matters: verify before you build more.

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
