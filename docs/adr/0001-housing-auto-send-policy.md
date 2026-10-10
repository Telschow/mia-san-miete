# ADR 0001: Explicit, auditable auto-send policy

Status: accepted (2026-10-10)

## Context

The roadmap requires a new listing to produce a sent message in under 2 minutes. In a
competitive rental market that is not achievable with a human approval step on every listing. A
sibling job-application project deliberately forbids auto-submit; this project is separate
and does not inherit that rule.

## Decision

Auto-send is allowed only through a dedicated `send_policy` block in the config:

- `enabled` master switch, default `false`.
- `mode: shadow | live`. Shadow runs the full pipeline up to, but not including, the send.
- `min_score` threshold, loosened on a fixed schedule down to a floor. Hard gates are
  never loosened by the schedule.
- `daily_cap` and `per_platform_daily_cap`.
- `platform_allow_list`: only listed channels may auto-send.
- `kill_switch_file`: if the file exists, nothing is sent.
- Every send, skip and shadow "would send" is written to an audit log (ids, score
  breakdown, template version, answering model; no message bodies).

Everything below the threshold goes to the approval queue. Documents (Schufa, payslips,
reference) are never attached automatically; a reply asking for them triggers a push
notification and one-tap approval.

## Consequences

- Shadow mode (3 to 5 days) is a required step before `mode: live`.
- Portals prohibit automated access; account bans are an accepted risk. The project does
  not implement captcha solving or detection evasion.
- A bug can message landlords at scale, which the caps and kill switch bound.
