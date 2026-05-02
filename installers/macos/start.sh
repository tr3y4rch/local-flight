#!/usr/bin/env bash
# Local Flight - macOS source launcher.
# Run from the project root: bash installers/macos/start.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$ROOT/.venv"
REQUESTED_GUI_MODE="${LOCALFLIGHT_GUI_MODE:-}"

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
"$VENV/bin/python" -m pip install -e "${ROOT}[native]" -q
"$VENV/bin/python" - <<'PY'
from PySide6 import QtCore
print(f" PySide6/Qt OK: {QtCore.qVersion()}")
PY
echo " Dependencies OK"

if [ -f "$ROOT/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT/.env"
    set +a
    echo " Loaded .env"
fi
if [ -n "$REQUESTED_GUI_MODE" ]; then
    export LOCALFLIGHT_GUI_MODE="$REQUESTED_GUI_MODE"
elif [ -z "${LOCALFLIGHT_GUI_MODE:-}" ]; then
    export LOCALFLIGHT_GUI_MODE="native"
fi

echo " Launching Local Flight..."
echo " GUI mode: ${LOCALFLIGHT_GUI_MODE:-auto}"
echo ""
exec "$VENV/bin/python" -m localflight
