# ADR 0005: Settings editor in the dashboard

Status: accepted (2026-10-10)

## Decision

The dashboard can create and edit everything needed to run Mia: a first-run setup when no
configuration exists, then a Settings tab with cards for the search, places you travel to,
facts about you, viewing availability, the alert inbox, the reply inbox, sending (SMTP),
notifications, the sending policy, automatic replies, score weights and optional API keys.
Each card validates and saves on its own. Saved values apply to the running dashboard at
once (config, dispatcher and queue are rebuilt) and to the next scheduled run.

## Where data lives (per user, local only)

Plain files on the user's own machine, the same ones the command line uses: `config.yaml`,
the profile YAML, the env file (default `~/.config/mia/env`) and the SQLite database. There is
no account system and no shared store: each person runs their own copy with their own files,
and nothing is uploaded. Interface preferences (theme) stay in the browser's local storage.

## Safety rules

- **Allow-list.** Only listed settings can be changed. File paths (database, kill-switch
  file), the names of environment variables and anything unlisted are refused, so a request
  cannot point Mia at other files or make it read other variables.
- **Validate before writing.** The real `Config` and `Profile` models run on the merged result;
  invalid input returns per-field errors and writes nothing.
- **Atomic writes with a backup.** Temp file, `chmod 600`, rename; the previous file is kept
  as `.bak`. Comments in the YAML are not preserved.
- **Credentials are write-only.** They go to the env file only (shell-quoted, because the
  scheduler sources that file), never into `config.yaml`. The API returns only whether a value
  is stored, never the value, and accepts only the variable names the config already uses.
- **Going live is a deliberate act.** Enabling live sending needs an explicit confirmation in
  the request and a configured SMTP account; the kill switch stays one click away.
- **Connection tests are generic.** Login tests for the inboxes and SMTP never send a message
  and report fixed, secret-free messages (no raw server errors). They have timeouts, because
  the server handles one request at a time.
- **Same protections as the rest of the dashboard:** token cookie, `X-Mia` header on writes,
  Host check, localhost by default (use an SSH tunnel or VPN for phone access).
- **Local only by default.** On a non-local address (`--host`) the editor is switched off,
  because it takes passwords over plain HTTP; `--allow-remote-settings` turns it on for use
  behind an SSH tunnel or VPN.
- **Demo mode is read-only.**

## Consequences

- A user who never opens a terminal can set everything up in the browser. The wizard
  (`mia init`) and the editor share the same builder and validation.
- YAML comments are lost on save; users who hand-edit with comments should keep editing the
  file directly (and `.bak` shows the previous version).
