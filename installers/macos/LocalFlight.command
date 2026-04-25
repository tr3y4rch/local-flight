#!/usr/bin/env bash
# Local Flight — macOS launcher
# Double-click this file in Finder to start Local Flight.

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$ROOT/.venv"

if [ ! -f "$VENV/bin/activate" ]; then
    osascript -e 'display alert "Local Flight" message "Not installed. Run installers/macos/install.sh first." as critical'
    exit 1
fi

source "$VENV/bin/activate"

# Load .env
if [ -f "$ROOT/.env" ]; then
    set -a
    source "$ROOT/.env"
    set +a
fi

cd "$ROOT/src"
python -m localflight
