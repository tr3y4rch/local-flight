#!/usr/bin/env bash
# Local Flight — Raspberry Pi installer
#
# Usage:
#   bash installers/pi/install.sh            # headless (default) — LED panels, LAN clients
#   bash installers/pi/install.sh --kiosk    # headless + Chromium kiosk on HDMI
#
# Run as the normal Pi user (not root). Requires: Pi OS Bookworm 64-bit, Python 3.11+.

set -euo pipefail

# ── Args ───────────────────────────────────────────────────────────────────────
KIOSK=0
for arg in "$@"; do
    case "$arg" in
        --kiosk)    KIOSK=1 ;;
        --headless) KIOSK=0 ;;
        --help|-h)
            echo "Usage: bash installers/pi/install.sh [--kiosk|--headless]"
            echo "  (default is headless)"
            exit 0 ;;
    esac
done

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$ROOT/.venv"
SERVICE_USER="$(whoami)"

# ── Helpers ────────────────────────────────────────────────────────────────────
ok()   { echo "  [OK]  $*"; }
step() { echo ""; echo "  -->  $*"; }
fail() { echo ""; echo "  [ERR] $*"; exit 1; }

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║   Local Flight — Pi Installer        ║"
echo "  ╚══════════════════════════════════════╝"
echo ""
echo "  Root:  $ROOT"
echo "  User:  $SERVICE_USER"
[ "$KIOSK" -eq 1 ] && echo "  Mode:  kiosk (Chromium on HDMI)" || echo "  Mode:  headless (no display)"
echo ""

[ "${EUID:-$(id -u)}" -eq 0 ] && fail "Do not run as root. Run as your normal Pi user — sudo is used internally."

# ── 1. System packages ─────────────────────────────────────────────────────────
step "Updating package lists..."
sudo apt-get update -qq > /dev/null 2>&1
ok "Package lists updated"

step "Installing Python and mDNS packages..."
sudo apt-get install -y -qq python3 python3-venv python3-pip avahi-daemon > /dev/null 2>&1
ok "python3, python3-venv, python3-pip, avahi-daemon installed"

# ── 2. Chromium (kiosk only) ───────────────────────────────────────────────────
CHROMIUM_BIN=""
if [ "$KIOSK" -eq 1 ]; then
    step "Installing Chromium for kiosk display..."
    INSTALLED=0
    for PKG in chromium chromium-browser; do
        if apt-cache show "$PKG" > /dev/null 2>&1; then
            if sudo apt-get install -y -qq "$PKG" > /dev/null 2>&1; then
                CHROMIUM_BIN="$(command -v chromium || command -v chromium-browser || true)"
                INSTALLED=1
                break
            fi
        fi
    done
    if [ "$INSTALLED" -eq 1 ] && [ -n "$CHROMIUM_BIN" ]; then
        ok "Chromium installed: $CHROMIUM_BIN"
    else
        echo "  [WARN] Chromium not available — kiosk service will be skipped"
        KIOSK=0
    fi
fi

# ── 3. Python venv ─────────────────────────────────────────────────────────────
if [ ! -x "$VENV/bin/python" ]; then
    step "Creating Python virtual environment..."
    python3 -m venv "$VENV"
    ok "Virtual environment created"
else
    step "Upgrading existing virtual environment..."
    ok "Already exists — will upgrade package"
fi

step "Installing Local Flight..."
"$VENV/bin/python" -m pip install --upgrade pip -q > /dev/null 2>&1
"$VENV/bin/python" -m pip install -e "$ROOT" -q > /dev/null 2>&1
ok "Local Flight installed"

# ── 4. Environment file ────────────────────────────────────────────────────────
if [ ! -f "$ROOT/.env" ]; then
    step "Creating .env..."
    if [ -f "$ROOT/.env.example" ]; then
        cp "$ROOT/.env.example" "$ROOT/.env"
    else
        cat > "$ROOT/.env" <<'ENVEOF'
# Local Flight — environment config
# The setup wizard writes these on first launch.
# Restart after any manual changes: sudo systemctl restart localflight

LOCALFLIGHT_ACTIVATION_TOKEN=
LOCALFLIGHT_RELAY_URL=https://localflight-community-relay.fly.dev/v1/flights

AVIATIONSTACK_API_KEY=
LOCALFLIGHT_AVIATIONSTACK_ENABLED=1
LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT=90
LOCALFLIGHT_RELAY_MONTHLY_LIMIT=50

RAPIDAPI_KEY=
LOCALFLIGHT_RAPIDAPI_MONTHLY_LIMIT=10000

OPENSKY_CLIENT_ID=
OPENSKY_CLIENT_SECRET=
ENVEOF
    fi
    ok ".env created"
else
    ok ".env already exists — skipping"
fi

# ── 5. systemd: main service ───────────────────────────────────────────────────
step "Installing localflight.service..."
sudo tee /etc/systemd/system/localflight.service > /dev/null <<EOF
[Unit]
Description=Local Flight - Airport FIDS
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$ROOT/src
EnvironmentFile=$ROOT/.env
ExecStart=$VENV/bin/python -m localflight
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=localflight

[Install]
WantedBy=multi-user.target
EOF
ok "localflight.service installed"

# ── 6. systemd: kiosk service (optional) ──────────────────────────────────────
if [ "$KIOSK" -eq 1 ] && [ -n "$CHROMIUM_BIN" ]; then
    step "Installing localflight-kiosk.service..."

    DISPLAY_ENV="DISPLAY=:0"
    if [ -n "${WAYLAND_DISPLAY:-}" ]; then
        DISPLAY_ENV="WAYLAND_DISPLAY=${WAYLAND_DISPLAY}"
    elif command -v loginctl > /dev/null 2>&1; then
        SESSION_ID="$(loginctl 2>/dev/null | awk -v u="$SERVICE_USER" '$3==u{print $1;exit}')"
        if [ -n "${SESSION_ID:-}" ] && loginctl show-session "$SESSION_ID" -p Type 2>/dev/null | grep -q wayland; then
            DISPLAY_ENV="WAYLAND_DISPLAY=wayland-0"
        fi
    fi

    # Note: %% in the heredoc produces a literal % in the unit file,
    # which is required because systemd treats % as a unit specifier prefix.
    sudo tee /etc/systemd/system/localflight-kiosk.service > /dev/null <<EOF
[Unit]
Description=Local Flight - Chromium Kiosk
After=localflight.service graphical.target
Wants=localflight.service

[Service]
Type=simple
User=$SERVICE_USER
Environment="$DISPLAY_ENV"
Environment="XAUTHORITY=$HOME/.Xauthority"
ExecStartPre=/bin/sleep 5
ExecStart=$CHROMIUM_BIN --kiosk --no-sandbox --disable-infobars --disable-session-crashed-bubble --disable-restore-session-state --noerrdialogs --disable-translate --no-first-run --fast --fast-start --disable-features=TranslateUI --disk-cache-dir=/tmp/chromium-cache --user-data-dir=$HOME/.localflight/browser-profile http://localhost:8000/display
Restart=on-failure
RestartSec=10

[Install]
WantedBy=graphical.target
EOF
    ok "localflight-kiosk.service installed"
fi

# Remove stale kiosk service if we're in headless mode
if [ "$KIOSK" -eq 0 ] && [ -f /etc/systemd/system/localflight-kiosk.service ]; then
    step "Removing stale kiosk service (headless mode)..."
    sudo systemctl stop localflight-kiosk 2>/dev/null || true
    sudo systemctl disable localflight-kiosk 2>/dev/null || true
    sudo rm -f /etc/systemd/system/localflight-kiosk.service
    ok "Kiosk service removed"
fi

# ── 7. mDNS hostname ──────────────────────────────────────────────────────────
step "Configuring mDNS (localflight.local)..."
sudo systemctl enable --now avahi-daemon > /dev/null 2>&1
if [ "$(hostname)" != "localflight" ]; then
    sudo hostnamectl set-hostname localflight
    if grep -q "127.0.1.1" /etc/hosts; then
        sudo sed -i "s/^127.0.1.1.*/127.0.1.1\tlocalflight/" /etc/hosts
    else
        echo "127.0.1.1 localflight" | sudo tee -a /etc/hosts > /dev/null
    fi
fi
ok "Hostname: localflight — accessible as localflight.local"

# ── 8. lf command ─────────────────────────────────────────────────────────────
step "Installing 'lf' management command..."
sudo tee /usr/local/bin/lf > /dev/null <<EOF
#!/usr/bin/env bash
exec bash $ROOT/installers/pi/lf.sh "\$@"
EOF
sudo chmod +x /usr/local/bin/lf
ok "'lf' available system-wide"

# ── 9. Enable and start ────────────────────────────────────────────────────────
step "Enabling and starting services..."
sudo systemctl daemon-reload
sudo systemctl enable localflight.service > /dev/null 2>&1
sudo systemctl restart localflight.service

if [ "$KIOSK" -eq 1 ] && [ -f /etc/systemd/system/localflight-kiosk.service ]; then
    sudo systemctl enable localflight-kiosk.service > /dev/null 2>&1
    sleep 3
    sudo systemctl restart localflight-kiosk.service
fi
ok "Services started"

# ── Summary ────────────────────────────────────────────────────────────────────
PI_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║   Installation complete              ║"
echo "  ╚══════════════════════════════════════╝"
echo ""
echo "  Open in any browser on your network:"
[ -n "$PI_IP" ] && echo "    http://$PI_IP:8000"
echo "    http://localflight.local:8000  (mDNS — may take a minute)"
echo ""
echo "  Management:"
echo "    lf status     — check if running"
echo "    lf logs       — live log tail"
echo "    lf restart    — restart after config changes"
echo "    lf update     — pull latest code and restart"
echo ""
echo "  To add API keys later:"
echo "    nano $ROOT/.env"
echo "    lf restart"
echo ""
