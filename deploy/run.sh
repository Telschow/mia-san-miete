#!/usr/bin/env bash
# One scheduled cycle. Called by launchd (macOS) or a systemd timer / cron (Raspberry Pi).
# Secrets are read from an env file OUTSIDE the repository (default ~/.config/mia/env).
set -euo pipefail

ROOT="${MIA_HOME:-$(cd "$(dirname "$0")/.." && pwd)}"
ENV_FILE="${MIA_ENV_FILE:-$HOME/.config/mia/env}"
LOCK="${TMPDIR:-/tmp}/mia-run.lock"

[ -r "$ENV_FILE" ] || { echo "env file not readable: $ENV_FILE" >&2; exit 1; }

# Skip this tick if the previous cycle is still running (stale locks older than 15 min expire).
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +15 2>/dev/null)" ]; then
    rmdir "$LOCK" && mkdir "$LOCK"
  else
    echo "previous cycle still running, skipping" >&2
    exit 0
  fi
fi
trap 'rmdir "$LOCK"' EXIT

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

cd "$ROOT"
# The virtual environment is .venv in the project unless MIA_VENV (set in the env file) says otherwise.
VENV="${MIA_VENV:-$ROOT/.venv}"
[ -r "$VENV/bin/activate" ] || { echo "no virtual environment at $VENV (set MIA_VENV in $ENV_FILE)" >&2; exit 1; }
# shellcheck disable=SC1091
. "$VENV/bin/activate"

echo "--- $(date -u +%FT%TZ) run"
mia run --config config.yaml --profile profile/profile.yaml
if grep -q '^replies:' config.yaml; then
  mia check-replies --config config.yaml
fi
