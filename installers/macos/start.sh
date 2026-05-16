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

if [ ! -x "$VENV/bin/python" ]; then
    echo " ERROR: No virtual environment found."
    echo " Run bash installers/macos/install.sh first."
    exit 1
fi

echo " Checking dependencies..."
INSTALL_TARGET="$ROOT"
if [ "${LOCALFLIGHT_GUI_MODE:-native}" != "browser" ] && [ "${LOCALFLIGHT_GUI_MODE:-native}" != "headless" ]; then
    INSTALL_TARGET="${ROOT}[native]"
fi
"$VENV/bin/python" -m pip install -e "$INSTALL_TARGET" -q
if [ "$INSTALL_TARGET" = "${ROOT}[native]" ]; then
    "$VENV/bin/python" - <<'PY'
from PySide6 import QtCore
print(f" PySide6/Qt OK: {QtCore.qVersion()}")
PY
else
    echo " PySide6/Qt check skipped for ${LOCALFLIGHT_GUI_MODE:-browser} mode"
fi
echo " Dependencies OK"

echo " Launching Local Flight..."
echo " GUI mode: ${LOCALFLIGHT_GUI_MODE:-auto}"
echo ""
exec -a "Local Flight" "$VENV/bin/python" -m localflight
