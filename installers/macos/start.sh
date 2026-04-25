#!/usr/bin/env bash
# Local Flight — macOS dev launcher
# Run from the project root: ./installers/macos/start.sh

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo ""
echo " =========================================="
echo "  LOCAL FLIGHT - starting up"
echo " =========================================="
echo ""

if [ ! -f "$ROOT/.venv/bin/activate" ]; then
    echo " ERROR: No virtual environment found."
    echo " Run ./installers/macos/install.sh first."
    exit 1
fi

source "$ROOT/.venv/bin/activate"
echo " Venv activated"

echo " Checking dependencies..."
cd "$ROOT"
pip install -e . -q
echo " Dependencies OK"

if [ -f "$ROOT/.env" ]; then
    set -a; source "$ROOT/.env"; set +a
    echo " Loaded .env"
fi

cd "$ROOT/src"
echo " Launching Local Flight..."
echo ""
python -m localflight