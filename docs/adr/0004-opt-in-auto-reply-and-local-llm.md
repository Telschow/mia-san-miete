# ADR 0004: Opt-in automatic reply to viewing offers, and a local-only reply LLM

Status: accepted (2026-10-10)

## Decision

Both features are **off by default** and must be switched on in `config.yaml`.

- **Automatic reply** (`auto_reply.enabled`). When a landlord's reply is classified as a
  viewing offer, Mia reads the offered slots with a deterministic parser (German and English
  weekdays, dates, `17 Uhr`, `17:30`, `5 pm`, ranges). If a slot fits your weekly `availability`
  windows from the profile (viewing length, minimum notice, blackout dates) she **confirms the
  earliest fitting slot**. Everything else (no readable slot, a clash, a guard hit, a second
  message in the same thread) becomes a **drafted proposal in the review queue** that lists
  your own free times. Starts in `mode: shadow` (logs "would confirm", sends nothing).
- **Reply LLM** (`reply_llm.enabled`). Optional model that labels replies the rules cannot
  place and suggests slots when the parser finds none. **Only a local or private-network
  endpoint is accepted** (config validation rejects hosted URLs): replies are private
  correspondence. Only the reply text without quoted lines, with email addresses, links and
  phone-like numbers removed, is sent.

## Safety rules

- The outgoing text is a fixed template (names, phone, the slot we chose or our own free
  times). Nothing a landlord wrote, and nothing the model produced, is copied into it.
- A model-suggested slot is used only if its time and its weekday or date literally appear in
  the reply text, it is inside the horizon, and it passes the same availability check.
- Same guards as sending applications: kill switch, quiet hours, daily cap, one automatic
  reply per thread. Shadow mode never sends, including on approval from the queue.
- Never answers automatic mail, mailing lists (`Auto-Submitted`, `Precedence: bulk/list`,
  `List-Id`) or messages from our own address (reply-loop guard).
- Storage stays content-free: `auto_replies` holds ids, status and the agreed slot time. The
  recipient address of a queued reply draft is kept only until the draft is resolved or purged
  (30 days) and is cleared on approve or skip.

## Known limits

Measured on a small fictional held-out set (see `docs/benchmarks.md`): the slot parser finds
most but not all offered slots (misses: "19h", "halb sieben", "Montag oder Dienstag ab 18 Uhr");
every miss is safe because it falls back to the review queue. Slot extraction was never run on
real replies. A confirmed viewing is not added to any calendar yet.

## Alternatives rejected

- A hosted LLM for reading replies: sends private correspondence to a third party.
- Letting a model write the reply: prompt-injection surface and a tone risk toward landlords.
- Live calendar integration: more access and setup; windows in the profile are enough to start.
