# ADR 0003: Local dashboard stack and safety model

Status: accepted (2026-10-10)

## Decision

- **Backend:** Python standard library only (`http.server`), JSON API under `/api/`, read
  models in `gui/api.py` (pure functions over the SQLite tables), actions delegated to the
  same `ApprovalQueue` and `Dispatcher` the CLI uses. No new runtime dependency.
- **Frontend:** one static HTML file with vanilla JavaScript and inline SVG charts. No build
  step, no CDN, no external requests (the CSP is `default-src 'self'`). The DOM is built with
  `textContent`, never `innerHTML`, because listing text comes from portals and is untrusted.
- **Single-threaded server:** requests are handled one at a time, which keeps SQLite access
  simple and is enough for one user.

## Safety model

- Binds to `127.0.0.1` by default. A random token is required: opening the printed link sets
  an `HttpOnly`, `SameSite=Strict` cookie.
- State-changing requests need the custom header `X-Mia: 1`, which a cross-site page cannot
  send without a preflight the server never grants.
- The `Host` header must match what we serve (DNS-rebinding guard); extra hosts need
  `--allow-host`.
- Serving beyond localhost is plain HTTP: use an SSH tunnel or a private network (for example
  Tailscale) for phone access.
- Approving a draft goes through the dispatcher: kill switch, duplicate guard, quiet hours,
  caps and platform pauses all still apply, and shadow mode never sends.
- The API never returns contact emails or workplace addresses; the settings page shows
  limits and weights only.

## Alternatives considered

- FastAPI plus a JS framework: nicer ergonomics, but a heavier install on a Raspberry Pi and a
  build step for a single-user tool.
- A hosted dashboard: would put private data on a third party; rejected.

## Consequences

- Charts are hand-built, so new chart types cost some code; the set is deliberately small.
- Live updating is polling (15 s), not push.
