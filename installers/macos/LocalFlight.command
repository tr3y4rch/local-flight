#!/usr/bin/env bash
# Local Flight - macOS source launcher.
# Double-click this file in Finder after running installers/macos/install.sh.

# Resolve symlink so ROOT is correct when launched via ~/Applications shortcut.
_SELF="$(readlink "$0" 2>/dev/null)"
[ -z "$_SELF" ] && _SELF="$0"
ROOT="$(cd "$(dirname "$_SELF")/../.." && pwd)"
VENV="$ROOT/.venv"

if [ ! -x "$VENV/bin/python" ]; then
    osascript -e 'display alert "Local Flight" message "Not installed. Run installers/macos/install.sh first." as critical'
    exit 1
fi

if [ -f "$ROOT/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT/.env"
    set +a
fi

cd "$ROOT/src"
exec "$VENV/bin/python" -m localflight
