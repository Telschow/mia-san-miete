# ADR 0007: Click-link resolution for alert mails

Status: accepted (2026-10-11)

## Context

Immowelt alert mails contain only click-tracking links (`click.by.<portal>/?qs=<token>`),
never the flat's own address. Each flat is a card (price, type or title, size, place) that
ends with a "Mehr Informationen" button. Without the real address a flat has no stable id,
so duplicates cannot be detected and the owner cannot open it from the dashboard.

## Decision

- mia asks the tracker for the redirect target of **one button per flat** (up to four links of
  a card if the button leads nowhere), using a request that does not follow the redirect, send
  cookies or read the page. The result is stored as the flat's clean address and id.
- Links whose anchor or nearby text suggests an account action (unsubscribe, delete, confirm,
  settings, login) are never opened, and a redirect that lands on a sign-in page ends the lookup.
- Every answer is remembered in the local database. A lookup that found no flat is not repeated
  for three days (the default mail lookback). At most 60 new lookups run per cycle, with a short
  pause between requests.
- A button that answers with a web page (HTTP 200, no redirect) is left out. An experiment that
  read up to 200 KB of such pages for a flat link found none and was removed: it amounted to
  scraping the portal.
- Prices on these cards are read as cold rent (the card says "Kaltmiete" where it says anything).

## Consequences

- Each lookup is a request to the portal's tracker made with your alert token. It may be
  counted as a click, and a portal that dislikes it can stop sending alerts. That is accepted
  for this source and stays opt-in by configuration (`alerts.sender_domains`).
- Coverage of Immowelt is partial: roughly the cards whose button redirects. For full coverage
  use another source (see ADR 0002).
- No captcha solving, no cookies, no page parsing: the same limits as ADR 0006.
