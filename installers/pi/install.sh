#!/usr/bin/env bash
# Local Flight - Raspberry Pi source installer
#
# Tested on Raspberry Pi OS Bookworm (64-bit), Pi 4 and Pi 5.
#
# What this does:
#   1. Installs system dependencies (Python, Chromium, Avahi/mDNS)
#   2. Creates a Python venv and installs Local Flight from this checkout
#   3. Creates .env from .env.example when missing
#   4. Installs the Python app and Chromium kiosk systemd services
#   5. Enables localflight.local via mDNS
#   6. Starts both services
#
# Run as the normal Pi user, not root:
#   bash installers/pi/install.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$ROOT/.venv"
USER_HOME="$HOME"
SERVICE_USER="$(whoami)"

echo ""
echo " =========================================="
echo "   LOCAL FLIGHT - Pi source install"
echo " =========================================="
echo ""
echo " Project root: $ROOT"
echo " Running as:   $SERVICE_USER"
echo ""

if [ "${EUID:-$(id -u)}" -eq 0 ]; then
    echo " ERROR: Do not run as root. Run as the normal Pi user."
    echo " The installer will use sudo where needed."
    exit 1
fi

echo " Updating package lists..."
sudo apt-get update -qq

echo " Resolving package names..."
CHROMIUM_PKG="chromium-browser"
if ! apt-cache show chromium-browser >/dev/null 2>&1; then
    CHROMIUM_PKG="chromium"
fi

ASOUND_PKG="libasound2t64"
if ! apt-cache show libasound2t64 >/dev/null 2>&1; then
    ASOUND_PKG="libasound2"
fi

echo " Installing system packages..."
sudo apt-get install -y -qq \
    python3 \
    python3-venv \
    python3-pip \
    "$CHROMIUM_PKG" \
    avahi-daemon \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    "$ASOUND_PKG"
echo " System packages installed"

CHROMIUM_BIN="$(command -v chromium-browser || command -v chromium || true)"
if [ -z "$CHROMIUM_BIN" ]; then
    echo " ERROR: Chromium was installed but no chromium binary was found in PATH."
    exit 1
fi
echo " Chromium binary: $CHROMIUM_BIN"

if [ ! -x "$VENV/bin/python" ]; then
    echo " Creating virtual environment..."
    python3 -m venv "$VENV"
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
# Edit this file, then restart with: sudo systemctl restart localflight

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
EOF
    fi
    echo " Done - edit $ROOT/.env to add API keys"
else
    echo " .env already exists - skipping"
fi

echo " Installing localflight.service..."
sudo tee /etc/systemd/system/localflight.service >/dev/null <<EOF
[Unit]
Description=Local Flight - Airport FIDS Display
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
echo " Done"

echo " Installing localflight-kiosk.service..."
DISPLAY_ENV="DISPLAY=:0"
if [ -n "${WAYLAND_DISPLAY:-}" ]; then
    DISPLAY_ENV="WAYLAND_DISPLAY=${WAYLAND_DISPLAY}"
elif command -v loginctl >/dev/null 2>&1; then
    SESSION_ID="$(loginctl 2>/dev/null | awk -v user="$SERVICE_USER" '$3 == user {print $1; exit}')"
    if [ -n "${SESSION_ID:-}" ] && loginctl show-session "$SESSION_ID" -p Type 2>/dev/null | grep -q wayland; then
        DISPLAY_ENV="WAYLAND_DISPLAY=wayland-0"
    fi
fi

sudo tee /etc/systemd/system/localflight-kiosk.service >/dev/null <<EOF
[Unit]
Description=Local Flight - Chromium Kiosk
After=localflight.service graphical.target
Wants=localflight.service

[Service]
Type=simple
User=$SERVICE_USER
Environment=$DISPLAY_ENV
Environment=XAUTHORITY=$USER_HOME/.Xauthority
ExecStartPre=/bin/sleep 5
ExecStart=$CHROMIUM_BIN \\
    --kiosk \\
    --no-sandbox \\
    --disable-infobars \\
    --disable-session-crashed-bubble \\
    --disable-restore-session-state \\
    --noerrdialogs \\
    --disable-translate \\
    --no-first-run \\
    --fast \\
    --fast-start \\
    --disable-features=TranslateUI \\
    --disk-cache-dir=/tmp/chromium-cache \\
    --user-data-dir=$USER_HOME/.localflight/browser-profile \\
    http://localhost:8000/splash?next=%2Fdisplay
Restart=on-failure
RestartSec=10

[Install]
WantedBy=graphical.target
EOF
echo " Done"

echo " Configuring mDNS..."
sudo systemctl enable --now avahi-daemon
CURRENT_HOST="$(hostname)"
if [ "$CURRENT_HOST" != "localflight" ]; then
    echo " Setting hostname to 'localflight'..."
    sudo hostnamectl set-hostname localflight
    if grep -q "127.0.1.1" /etc/hosts; then
        sudo sed -i "s/^127.0.1.1.*/127.0.1.1\tlocalflight/" /etc/hosts
    else
        echo "127.0.1.1 localflight" | sudo tee -a /etc/hosts >/dev/null
    fi
    echo " Pi will be accessible at localflight.local after hostname refresh"
fi
echo " Done"

echo " Enabling services..."
sudo systemctl daemon-reload
sudo systemctl enable localflight.service
sudo systemctl enable localflight-kiosk.service
echo " Done"

echo " Starting Local Flight..."
sudo systemctl restart localflight.service
sleep 3
sudo systemctl restart localflight-kiosk.service

PI_IP="$(hostname -I | awk '{print $1}')"

echo ""
echo " =========================================="
echo "   Installation complete"
echo " =========================================="
echo ""
echo " Local Flight is running."
echo " Access from any device on your network:"
echo "   http://localflight.local:8000"
if [ -n "$PI_IP" ]; then
    echo "   http://$PI_IP:8000"
fi
echo ""
echo " Useful commands:"
echo "   bash installers/pi/lf.sh status"
echo "   bash installers/pi/lf.sh logs"
echo "   bash installers/pi/lf.sh update"
echo ""
echo " Edit API keys:  nano $ROOT/.env"
echo " Then restart:   sudo systemctl restart localflight"
echo ""
