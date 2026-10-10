# Deployment

Both targets run the same thing: `deploy/run.sh` every 5 minutes. It reads secrets from an
env file outside the repository, skips a tick if the previous cycle is still running, runs
`mia run`, and `mia check-replies` if your config has a `replies` section.

Your private files (`config.yaml`, `profile/profile.yaml`, `.private-terms`, the env file,
`data/`) live only on that machine and are never committed.

## Common setup (both machines)

```bash
git clone https://github.com/Telschow/mia-san-miete-clean.git mia && cd mia
python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
cp config.example.yaml config.yaml                     # edit: your values
cp profile/profile.example.yaml profile/profile.yaml   # edit: your values
touch .private-terms                                   # one sensitive term per line
mkdir -p ~/.config/mia && cp deploy/env.example ~/.config/mia/env
chmod 600 ~/.config/mia/env                            # edit: your secrets
mia check-config config.yaml && mia install-hook && mia check-private
```

Keep `send_policy.enabled: false` (or `mode: shadow`) for the first one to two weeks.

Before scheduling anything, run once by hand and read the output:

```bash
set -a; . ~/.config/mia/env; set +a
mia ingest-alerts --config config.yaml     # check titles, rents, postcodes of stored flats
mia run --config config.yaml --profile profile/profile.yaml
mia metrics --config config.yaml
```

## Option A: Mac (preferred)

```bash
deploy/macos/install.sh            # installs a launchd agent, every 5 minutes
tail -f ~/Library/Logs/mia/run.log
deploy/macos/install.sh uninstall
```

Limits of a Mac:

- launchd does not run while the Mac sleeps. After wake it runs the missed job once, so
  alert mail waits (the default lookback is 3 days) but you lose speed.
- To keep it running: System Settings > Battery (or Energy) > prevent automatic sleeping
  when the display is off, and stay on power. A closed MacBook lid sleeps the machine
  unless it is on power with an external display.
- `caffeinate -s` in a terminal also holds it awake while it is running.
- Closing the Terminal is fine; the agent runs in the background after login. It does not
  run before you log in.

## Option B: Raspberry Pi (second, future option)

```bash
sudo deploy/pi/install.sh <your-linux-user>    # systemd timer, every 5 minutes
journalctl -u mia.service -f
sudo systemctl disable --now mia.timer         # to stop
```

The timer also starts after boot (`OnBootSec`) and catches up a missed run
(`Persistent=true`). Use an SSD or a good SD card, and enable automatic OS updates.
Unverified: whether `pydantic` installs from a prebuilt wheel on your Pi's OS and CPU; use
a 64-bit OS to make that likely. Moving from the Mac later means copying `config.yaml`,
`profile/profile.yaml`, `.private-terms`, the env file and `data/housing.db`.

## Moving or stopping

- Never run two machines against the same mailbox with sending enabled: stop the old one
  first (`mia kill` also stops all sending).
- The database keeps dedup state and the audit trail. Back up `data/housing.db`.
