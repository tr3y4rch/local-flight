#!/usr/bin/env bash
# Local Flight - macOS source launcher.
# Double-click this file in Finder after running installers/macos/install.sh.

# Resolve symlink so ROOT is correct when launched via ~/Applications shortcut.
_SELF="$(readlink "$0" 2>/dev/null)"
[ -z "$_SELF" ] && _SELF="$0"
ROOT="$(cd "$(dirname "$_SELF")/../.." && pwd)"
VENV="$ROOT/.venv"
REQUESTED_GUI_MODE="${LOCALFLIGHT_GUI_MODE:-}"

if [ ! -x "$VENV/bin/python" ]; then
    osascript -e 'display alert "Local Flight" message "Not installed. Run installers/macos/install.sh first." as critical'
    exit 1
fi

"$VENV/bin/python" -m pip install -e "${ROOT}[native]" -q

if [ -f "$ROOT/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT/.env"
    set +a
fi
if [ -n "$REQUESTED_GUI_MODE" ]; then
    export LOCALFLIGHT_GUI_MODE="$REQUESTED_GUI_MODE"
elif [ -z "${LOCALFLIGHT_GUI_MODE:-}" ]; then
    export LOCALFLIGHT_GUI_MODE="native"
fi

exec "$VENV/bin/python" -m localflight
