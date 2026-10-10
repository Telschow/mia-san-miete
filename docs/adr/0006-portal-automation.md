# ADR 0006: Portal automation, what exists and what does not

Status: proposed (2026-10-10), decision with the owner

## Where things stand

Mia **does not log in to portals and does not send through them.** Today it:

- reads the alert emails you receive (read-only IMAP), scores each flat and drafts a message;
- sends by email only for listings that carry a landlord's contact address (SMTP);
- answers landlord replies with an opt-in, guarded automatic reply;
- supports the manual route for portal messages: **Copy message**, **Open listing**, send it
  yourself, then **I sent it myself** (recorded in the audit trail and counted by the
  duplicate guard, so the same flat is not sent twice).

Alert emails carry no landlord address, so flats found through alerts cannot be sent
automatically yet. That is issue #23.

## Options

| | What it is | Effort | Risk |
|---|---|---|---|
| A. Assisted (built) | Copy, open, send yourself, mark as sent | none | none beyond your own use of the portal |
| B. Semi-automatic | A local browser (Playwright) opens the listing in your own logged-in session and pre-fills the message; you read it and click send | medium per portal | low to medium: still your session; selectors break when the page changes |
| C. Automatic | A headless sender logs in and submits for you, inside the existing caps, quiet hours and kill switch | high per portal, needs your accounts to build and test | highest: portals restrict automated access, accounts can be banned, anti-bot measures change |

## Constraints that do not change

- No captcha solving and no detection evasion. If a portal blocks automation, the answer is
  option A, not a workaround.
- Read each portal's terms before using B or C. Automating a logged-in account may breach them;
  that risk is the account holder's and is accepted explicitly, per portal.
- Every automatic send keeps all guards: hard gates, score threshold, duplicate guard, daily and
  per-platform caps, quiet hours, kill switch, shadow mode first.
- I cannot build or verify B or C without a real portal account to test against, and a sender
  written blind would be brittle. It needs the owner's accounts and a decision per portal.

## Proposal

Ship A now (done). Build B for one portal the owner names, with a mock page in tests and a
`--dry-run` that fills the form without submitting. Consider C only after B has run
reliably for weeks and the owner has accepted the account risk in writing in the config
(`platform_allow_list` plus an explicit per-portal acknowledgement).

## For the published project

A recruiter-facing demo should not show automation against a named portal: it may breach that
portal's terms and invites the wrong questions. The public description says what is true:
Mia finds, scores and drafts; sending through portals is manual or, later, semi-automatic.
