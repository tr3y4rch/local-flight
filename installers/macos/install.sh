#!/usr/bin/env bash
# Local Flight - macOS source installer
#
# Use this when running Local Flight from a source checkout:
#   bash installers/macos/install.sh
#
# Release builds may also provide LocalFlight.app. If you have the app bundle,
# use that instead of this source installer.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$ROOT/.venv"

echo ""
echo " =========================================="
echo "   LOCAL FLIGHT - macOS source install"
echo " =========================================="
echo ""
echo " Project root: $ROOT"
echo ""

if ! command -v python3 >/dev/null 2>&1; then
    echo " ERROR: Python 3 not found."
    echo " Install via Homebrew:  brew install python"
    echo " Or download from:      https://www.python.org/downloads/"
    exit 1
fi

PYTHON_BIN="$(command -v python3)"
PYVER="$("$PYTHON_BIN" --version 2>&1)"
echo " Python found: $PYVER"

if ! "$PYTHON_BIN" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
then
    echo " ERROR: Python 3.11+ is required (found $PYVER)."
    exit 1
fi

if [ ! -x "$VENV/bin/python" ]; then
    echo " Creating virtual environment..."
    "$PYTHON_BIN" -m venv "$VENV"
    echo " Done"
else
    echo " Virtual environment exists - skipping"
fi

echo " Installing Local Flight dependencies..."
"$VENV/bin/python" -m pip install --upgrade pip -q
"$VENV/bin/python" -m pip install -e "$ROOT" -q
echo " Done"

if [ ! -f "$ROOT/.env" ]; then
    echo " Creating .env..."
    if [ -f "$ROOT/.env.example" ]; then
        cp "$ROOT/.env.example" "$ROOT/.env"
    else
        cat > "$ROOT/.env" <<'EOF'
# Local Flight environment variables.
# Fill these in via the setup wizard on first launch.

AVIATIONSTACK_API_KEY=
LOCALFLIGHT_AVIATIONSTACK_ENABLED=1
LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT=90

RAPIDAPI_KEY=

OPENSKY_CLIENT_ID=
OPENSKY_CLIENT_SECRET=
EOF
    fi
    echo " Done"
else
    echo " .env already exists - skipping"
fi

chmod +x "$ROOT/installers/macos/LocalFlight.command" "$ROOT/installers/macos/start.sh"
echo " Launchers ready"

SYMLINK="$HOME/Applications/LocalFlight.command"
if [ ! -e "$SYMLINK" ]; then
    mkdir -p "$HOME/Applications"
    ln -sf "$ROOT/installers/macos/LocalFlight.command" "$SYMLINK"
    echo " Shortcut created in ~/Applications"
fi

echo ""
echo " =========================================="
echo "   Installation complete"
echo " =========================================="
echo ""
echo " Start from Finder:  ~/Applications/LocalFlight.command"
echo " Start from shell:   bash installers/macos/start.sh"
echo " The setup wizard will guide you through first launch."
echo ""
