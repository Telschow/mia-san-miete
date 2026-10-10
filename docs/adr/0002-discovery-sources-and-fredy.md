# ADR 0002: Discovery sources and the role of Fredy

Status: accepted (2026-10-10)

## Spike result

Read of the Fredy README (github.com/orangecoding/fredy):

- Interval: not stated; set in the UI ("Administration, Execution"). Minimum unknown.
- Export: an MCP server (`<baseUrl>/api/mcp`), notification adapters (Slack, Telegram,
  Email, ntfy, Gotify, Discord, Mattermost, Pushover, Apprise and others), and a SQLite
  database in the `/db` volume. No documented webhook or export endpoint.
- Deploy: Docker image `ghcr.io/orangecoding/fredy:master`, port 9998, volumes `/conf`
  and `/db`. Node 22.22+ if run directly.
- Not verified: sub-2-minute latency, the SQLite schema, whether Apprise can deliver to a
  generic JSON endpoint. These need a hands-on test on the home server.

## Decision

- The pipeline depends only on the `Provider` contract (`providers/base.py`), never on
  Fredy. Fredy becomes one optional provider, added only after the hands-on test.
- Preferred integration, in order: (1) read Fredy's SQLite read-only, (2) MCP client,
  (3) receive notifications through an adapter. The choice waits for the schema check.
- If Fredy cannot meet the latency target, replace it per portal with own providers and
  alert-email triggers (roadmap D4).
- Cross-portal dedup lives in this project (`dedup.py`), keyed on rooms, area, rent and
  location, so it works regardless of source.

## Open checks (home server)

1. Run Fredy with 3 to 4 Munich searches and measure publish-to-appearance latency.
2. Inspect the SQLite schema in `/db`.
3. Test whether Apprise `json://` can post to a local endpoint.
