#!/usr/bin/env bash
# Local Flight - macOS source launcher.
# Run from the project root: bash installers/macos/start.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$ROOT/.venv"

echo ""
echo " =========================================="
echo "   LOCAL FLIGHT - starting up"
echo " =========================================="
echo ""

if [ ! -x "$VENV/bin/python" ]; then
    echo " ERROR: No virtual environment found."
    echo " Run bash installers/macos/install.sh first."
    exit 1
fi

echo " Checking dependencies..."
"$VENV/bin/python" -m pip install -e "$ROOT" -q
echo " Dependencies OK"

if [ -f "$ROOT/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT/.env"
    set +a
    echo " Loaded .env"
fi

cd "$ROOT/src"
echo " Launching Local Flight..."
echo ""
exec "$VENV/bin/python" -m localflight
