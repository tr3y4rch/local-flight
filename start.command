#!/usr/bin/env bash
# Local Flight - macOS dev launcher (mirrors start.bat)
# Double-clickable from Finder or runnable from a terminal.

set -u

# -- Resolve script directory (handles spaces, symlinks) -----------------------------
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
    DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
cd "$SCRIPT_DIR"

# Pretty terminal title (best-effort)
printf '\033]0;Local Flight\007' 2>/dev/null || true

echo
echo " ========================================="
echo "  LOCAL FLIGHT - starting up"
echo " ========================================="
echo

pause() {
    # Mirror cmd.exe `pause` so double-click windows don't vanish on error.
    echo
    read -n 1 -s -r -p " Press any key to close..."
    echo
}

LF_FONT_DEVTEST=0
LF_FONT_SMOKE=0
case "${1:-}" in
    --font-test|fonttest|fonts) LF_FONT_DEVTEST=1 ;;
    --font-smoke)               LF_FONT_SMOKE=1 ;;
esac

# -- Pick a stable Python (3.13 > 3.12 > 3.11, skip pre-release 3.14) ---------------
PYTHON=""
for cand in python3.13 python3.12 python3.11 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c 'import sys; sys.exit(0 if sys.version_info[:2] in [(3,11),(3,12),(3,13)] else 1)' >/dev/null 2>&1; then
            PYTHON="$cand"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo " ERROR: Python 3.11, 3.12, or 3.13 not found."
    echo " Install from https://www.python.org/downloads/ or via Homebrew: brew install python@3.13"
    pause
    exit 1
fi
echo " Python found ($PYTHON -> $($PYTHON --version 2>&1))"

LF_REQUESTED_GUI_MODE="${LOCALFLIGHT_GUI_MODE:-}"

# -- Create venv if missing ----------------------------------------------------------
if [ ! -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
    echo " Creating virtual environment..."
    if ! "$PYTHON" -m venv "$SCRIPT_DIR/.venv"; then
        echo " ERROR: Failed to create virtual environment."
        pause
        exit 1
    fi
    echo " Virtual environment created"
fi

# -- Activate venv -------------------------------------------------------------------
# shellcheck disable=SC1091
source "$SCRIPT_DIR/.venv/bin/activate"
echo " Venv activated"

# -- Load .env before dependency choice ---------------------------------------------
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    # Ignore comments and blank lines; tolerate values with '=' signs.
    while IFS='=' read -r key val; do
        [ -z "${key:-}" ] && continue
        case "$key" in \#*) continue ;; esac
        # Trim whitespace around key
        key="${key#"${key%%[![:space:]]*}"}"
        key="${key%"${key##*[![:space:]]}"}"
        [ -z "$key" ] && continue
        export "$key=$val"
    done < "$SCRIPT_DIR/.env"
    set +a
    echo " Loaded .env"
else
    echo " WARNING: No .env file found - API calls may fail."
    echo " Copy .env.example to .env and fill in your keys."
    echo
fi

if [ -n "$LF_REQUESTED_GUI_MODE" ]; then
    export LOCALFLIGHT_GUI_MODE="$LF_REQUESTED_GUI_MODE"
fi
if [ -z "${LOCALFLIGHT_GUI_MODE:-}" ]; then
    export LOCALFLIGHT_GUI_MODE="native"
fi

# -- Install / update dependencies --------------------------------------------------
echo " Checking dependencies..."
echo " GUI mode requested: $LOCALFLIGHT_GUI_MODE"
LF_INSTALL_NATIVE=1
case "$LOCALFLIGHT_GUI_MODE" in
    browser|Browser|BROWSER)   LF_INSTALL_NATIVE=0 ;;
    headless|Headless|HEADLESS) LF_INSTALL_NATIVE=0 ;;
esac

if [ "$LF_INSTALL_NATIVE" = "1" ]; then
    echo " Installing native-capable GUI dependencies..."
    python -m pip install -e ".[native]" -q
else
    python -m pip install -e . -q
fi
if [ $? -ne 0 ]; then
    echo " ERROR: Dependency installation failed."
    echo " Native GUI mode needs PySide6. If you want browser mode for dev only:"
    echo "   export LOCALFLIGHT_GUI_MODE=browser"
    echo "   ./start.command"
    pause
    exit 1
fi
if [ "$LF_INSTALL_NATIVE" = "1" ]; then
    if ! python -c "from PySide6.QtCore import qVersion; print(' PySide6/Qt OK: Qt ' + qVersion())"; then
        echo " ERROR: PySide6/Qt is not importable after dependency installation."
        pause
        exit 1
    fi
fi
echo " Dependencies OK"

if [ "$LF_FONT_SMOKE" = "1" ]; then
    echo " Running bundled font smoke test..."
    python "$SCRIPT_DIR/scripts/font_devtest.py" --smoke
    rc=$?
    if [ $rc -ne 0 ]; then
        echo " ERROR: Bundled font smoke test failed."
        pause
    fi
    exit $rc
fi

if [ "$LF_FONT_DEVTEST" = "1" ]; then
    echo " Opening bundled font devtest window..."
    echo " This does not start the backend."
    python "$SCRIPT_DIR/scripts/font_devtest.py"
    rc=$?
    if [ $rc -ne 0 ]; then
        echo " ERROR: Bundled font devtest failed."
        pause
    fi
    exit $rc
fi

# -- Guard the dev server port only --------------------------------------------------
echo " Checking dev server port..."
python "$SCRIPT_DIR/scripts/dev_preflight.py"
rc=$?
if [ $rc -eq 2 ]; then
    echo
    echo " Start blocked to avoid launching the in-dev server on an occupied port."
    pause
    exit 2
fi

# -- Launch Local Flight -------------------------------------------------------------
echo " Launching Local Flight..."
echo " Public/client app only. Operator relay tools stay in the separate Network Admin launcher."
case "$LOCALFLIGHT_GUI_MODE" in
    browser|Browser|BROWSER)
        echo " Browser/LAN UI mode will open. Right-click tray icon to open UI or quit."
        ;;
    headless|Headless|HEADLESS)
        echo " Headless backend mode requested. Local LAN web UI remains available at http://localhost:8000"
        ;;
esac
if [ "$LF_INSTALL_NATIVE" = "1" ]; then
    echo " Native Qt GUI is prepared. On first run, setup opens before the main Display shell."
    echo " Local LAN web UI remains available at http://localhost:8000"
fi
echo
python -m localflight
rc=$?

# -- If we get here, app exited ------------------------------------------------------
echo
echo " Local Flight stopped."
if [ $rc -ne 0 ]; then
    echo
    echo " NOTE: Local Flight exited with an error (code $rc)."
    pause
fi
exit $rc
