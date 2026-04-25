#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Local Flight — macOS Installer
#
# Run from the project root:
#   chmod +x installers/macos/install.sh
#   ./installers/macos/install.sh
# ═══════════════════════════════════════════════════════════════════════════════

set -e

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$ROOT/.venv"

echo ""
echo " =========================================="
echo "   LOCAL FLIGHT — macOS Installer"
echo " =========================================="
echo ""

# ── Check Python ───────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo " ERROR: Python 3 not found."
    echo " Install via Homebrew:  brew install python"
    echo " Or download from:      https://www.python.org/downloads/"
    exit 1
fi

PYVER=$(python3 --version 2>&1)
echo " Python found: $PYVER"

# Check version >= 3.11
PYMINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
PYMAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
if [ "$PYMAJOR" -lt 3 ] || { [ "$PYMAJOR" -eq 3 ] && [ "$PYMINOR" -lt 11 ]; }; then
    echo " ERROR: Python 3.11+ required (found $PYVER)"
    exit 1
fi

# ── Create virtual environment ─────────────────────────────────────────────────
if [ ! -f "$VENV/bin/activate" ]; then
    echo " Creating virtual environment..."
    python3 -m venv "$VENV"
    echo " Done"
else
    echo " Virtual environment exists — skipping"
fi

# ── Activate + install ─────────────────────────────────────────────────────────
source "$VENV/bin/activate"

echo " Installing dependencies..."
cd "$ROOT"
pip install -e . -q
echo " Done"

# ── Create .env if missing ─────────────────────────────────────────────────────
if [ ! -f "$ROOT/.env" ]; then
    echo " Creating .env..."
    if [ -f "$ROOT/.env.example" ]; then
        cp "$ROOT/.env.example" "$ROOT/.env"
    else
        cat > "$ROOT/.env" << 'EOF'
# Local Flight — environment variables
# Fill these in via the setup wizard on first launch.

AVIATIONSTACK_API_KEY=
LOCALFLIGHT_AVIATIONSTACK_ENABLED=1
LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT=90

OPENSKY_CLIENT_ID=
OPENSKY_CLIENT_SECRET=

RAPIDAPI_KEY=

# Linear issue tracker (optional)
LINEAR_API_KEY=
LINEAR_TEAM_ID=
EOF
    fi
    echo " Done"
else
    echo " .env already exists — skipping"
fi

# ── Make launcher executable ───────────────────────────────────────────────────
chmod +x "$ROOT/installers/macos/LocalFlight.command"
echo " Launcher ready"

# ── Create Applications symlink (optional) ────────────────────────────────────
SYMLINK="$HOME/Applications/LocalFlight.command"
if [ ! -e "$SYMLINK" ]; then
    mkdir -p "$HOME/Applications"
    ln -sf "$ROOT/installers/macos/LocalFlight.command" "$SYMLINK"
    echo " Shortcut created in ~/Applications"
fi

echo ""
echo " =========================================="
echo "   Installation complete!"
echo " =========================================="
echo ""
echo " Double-click LocalFlight.command in ~/Applications to start."
echo " The setup wizard will guide you through the first launch."
echo ""