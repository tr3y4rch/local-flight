#!/usr/bin/env bash
# Local Flight - macOS source installer
#
# Use this when running Local Flight from a source checkout:
#   bash installers/macos/install.sh
#   bash installers/macos/install.sh --display native
#   bash installers/macos/install.sh --display browser
#   bash installers/macos/install.sh --display headless
#
# Release builds may also provide LocalFlight.app. If you have the app bundle,
# use that instead of this source installer.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$ROOT/.venv"
DISPLAY_MODE="native"

usage() {
    echo "Usage: bash installers/macos/install.sh [--display native|browser|headless]"
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --display)
            [ "$#" -ge 2 ] || { usage; exit 1; }
            DISPLAY_MODE="$2"
            shift 2
            ;;
        --display=*)
            DISPLAY_MODE="${1#--display=}"
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo " ERROR: Unknown argument: $1"
            usage
            exit 1
            ;;
    esac
done

case "$(printf '%s' "$DISPLAY_MODE" | tr '[:upper:]' '[:lower:]')" in
    native) DISPLAY_MODE="native" ;;
    browser) DISPLAY_MODE="browser" ;;
    headless) DISPLAY_MODE="headless" ;;
    *)
        echo " ERROR: Invalid display mode '$DISPLAY_MODE'. Use native, browser, or headless."
        exit 1
        ;;
esac

set_env_value() {
    local key="$1"
    local value="$2"
    local file="$3"
    if grep -q "^${key}=" "$file"; then
        sed -i '' "s|^${key}=.*|${key}=${value}|" "$file"
    else
        printf '\n%s=%s\n' "$key" "$value" >> "$file"
    fi
}

echo ""
echo " =========================================="
echo "   LOCAL FLIGHT - macOS source install"
echo " =========================================="
echo ""
echo " Project root: $ROOT"
echo " Display mode: $DISPLAY_MODE"
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
INSTALL_TARGET="$ROOT"
if [ "$DISPLAY_MODE" = "native" ]; then
    INSTALL_TARGET="${ROOT}[native]"
fi
"$VENV/bin/python" -m pip install -e "$INSTALL_TARGET" -q
echo " Done"

if [ "$DISPLAY_MODE" = "native" ]; then
    echo " Confirming native Qt availability..."
    "$VENV/bin/python" - <<'PY'
from PySide6 import QtCore
print(f" PySide6/Qt OK: {QtCore.qVersion()}")
PY
else
    echo " Native Qt check skipped for $DISPLAY_MODE mode"
fi

if [ ! -f "$ROOT/.env" ]; then
    echo " Creating .env..."
    if [ -f "$ROOT/.env.example" ]; then
        cp "$ROOT/.env.example" "$ROOT/.env"
    else
        cat > "$ROOT/.env" <<'EOF'
# Local Flight environment variables.
# Fill these in via the setup wizard on first launch.

LOCALFLIGHT_ACTIVATION_TOKEN=
LOCALFLIGHT_RELAY_URL=https://localflight-community-relay.fly.dev
LOCALFLIGHT_GUI_MODE=native

AVIATIONSTACK_API_KEY=
LOCALFLIGHT_AVIATIONSTACK_ENABLED=1
LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT=90
LOCALFLIGHT_RELAY_MONTHLY_LIMIT=50

RAPIDAPI_KEY=
LOCALFLIGHT_RAPIDAPI_MONTHLY_LIMIT=10000

OPENSKY_CLIENT_ID=
OPENSKY_CLIENT_SECRET=
EOF
    fi
    echo " Done"
else
    echo " .env already exists - skipping"
fi

echo " Setting LOCALFLIGHT_GUI_MODE=$DISPLAY_MODE..."
set_env_value "LOCALFLIGHT_GUI_MODE" "$DISPLAY_MODE" "$ROOT/.env"
echo " Done"

chmod +x "$ROOT/installers/macos/LocalFlight.command" "$ROOT/installers/macos/start.sh"

echo " Building LocalFlight.app..."
mkdir -p "$HOME/Applications"
"$VENV/bin/python" "$ROOT/scripts/make_app_bundle.py" \
    "$ROOT" "$VENV" "$HOME/Applications"
echo " Done"

echo ""
echo " =========================================="
echo "   Installation complete"
echo " =========================================="
echo ""
echo " Start from Finder:  ~/Applications/LocalFlight.app"
echo " Start from shell:   bash installers/macos/start.sh"
echo " Display mode:       $DISPLAY_MODE"
echo " The setup wizard will guide you through first launch."
echo ""
