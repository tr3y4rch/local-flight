#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Local Flight — Raspberry Pi Installer
#
# Tested on: Raspberry Pi OS Bookworm (64-bit), Pi 4 and Pi 5
#
# What this does:
#   1. Installs system dependencies (Python, Chromium, avahi-daemon)
#   2. Creates a Python venv and installs Local Flight
#   3. Creates .env from template
#   4. Installs two systemd services:
#        localflight.service         — the Python app
#        localflight-kiosk.service   — Chromium in kiosk mode
#   5. Enables mDNS so the Pi is accessible at localflight.local
#   6. Starts both services
#
# Run as the pi user (not root):
#   chmod +x installers/pi/install.sh
#   ./installers/pi/install.sh
# ═══════════════════════════════════════════════════════════════════════════════

set -e

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$ROOT/.venv"
USER_HOME="$HOME"
SERVICE_USER="$(whoami)"

echo ""
echo " =========================================="
echo "   LOCAL FLIGHT — Pi Installer"
echo " =========================================="
echo ""
echo " Project root: $ROOT"
echo " Running as:   $SERVICE_USER"
echo ""

# ── Must not run as root ───────────────────────────────────────────────────────
if [ "$EUID" -eq 0 ]; then
    echo " ERROR: Do not run as root. Run as the pi user."
    echo " The installer will use sudo where needed."
    exit 1
fi

# ── System dependencies ────────────────────────────────────────────────────────
echo " Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3 \
    python3-venv \
    python3-pip \
    chromium-browser \
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
    libasound2t64
echo " System packages installed"

# ── Python venv ────────────────────────────────────────────────────────────────
if [ ! -f "$VENV/bin/activate" ]; then
    echo " Creating virtual environment..."
    python3 -m venv "$VENV"
    echo " Done"
else
    echo " Virtual environment exists — skipping"
fi

source "$VENV/bin/activate"

echo " Installing Python dependencies..."
cd "$ROOT"
pip install -e . -q
echo " Done"

# ── .env ──────────────────────────────────────────────────────────────────────
if [ ! -f "$ROOT/.env" ]; then
    echo " Creating .env..."
    if [ -f "$ROOT/.env.example" ]; then
        cp "$ROOT/.env.example" "$ROOT/.env"
    else
        cat > "$ROOT/.env" << 'EOF'
# Local Flight — environment variables
# Edit this file then restart: sudo systemctl restart localflight

AVIATIONSTACK_API_KEY=
LOCALFLIGHT_AVIATIONSTACK_ENABLED=1
LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT=90

OPENSKY_CLIENT_ID=
OPENSKY_CLIENT_SECRET=

RAPIDAPI_KEY=
EOF
    fi
    echo " Done — edit $ROOT/.env to add your API keys"
else
    echo " .env already exists — skipping"
fi

# ── localflight.service ────────────────────────────────────────────────────────
echo " Installing localflight.service..."
sudo tee /etc/systemd/system/localflight.service > /dev/null << EOF
[Unit]
Description=Local Flight — Airport FIDS Display
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

# ── localflight-kiosk.service ──────────────────────────────────────────────────
echo " Installing localflight-kiosk.service..."

# Detect display server
DISPLAY_ENV="DISPLAY=:0"
if [ -n "$WAYLAND_DISPLAY" ] || loginctl show-session "$(loginctl | grep "$SERVICE_USER" | awk '{print $1}')" -p Type 2>/dev/null | grep -q wayland; then
    DISPLAY_ENV="WAYLAND_DISPLAY=wayland-0"
fi

sudo tee /etc/systemd/system/localflight-kiosk.service > /dev/null << EOF
[Unit]
Description=Local Flight — Chromium Kiosk
After=localflight.service graphical.target
Wants=localflight.service

[Service]
Type=simple
User=$SERVICE_USER
Environment=$DISPLAY_ENV
Environment=XAUTHORITY=$USER_HOME/.Xauthority
ExecStartPre=/bin/sleep 5
ExecStart=/usr/bin/chromium-browser \
    --kiosk \
    --no-sandbox \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-restore-session-state \
    --noerrdialogs \
    --disable-translate \
    --no-first-run \
    --fast \
    --fast-start \
    --disable-features=TranslateUI \
    --disk-cache-dir=/tmp/chromium-cache \
    --user-data-dir=$USER_HOME/.localflight/browser-profile \
    http://localhost:8000/display
Restart=on-failure
RestartSec=10

[Install]
WantedBy=graphical.target
EOF
echo " Done"

# ── Enable mDNS (localflight.local) ──────────────────────────────────────────
echo " Configuring mDNS..."
sudo systemctl enable avahi-daemon
sudo systemctl start avahi-daemon
# Set hostname to localflight so it's reachable at localflight.local
CURRENT_HOST=$(hostname)
if [ "$CURRENT_HOST" != "localflight" ]; then
    echo " Setting hostname to 'localflight'..."
    sudo hostnamectl set-hostname localflight
    sudo sed -i "s/$CURRENT_HOST/localflight/g" /etc/hosts
    echo " Pi will be accessible at localflight.local on your network"
fi
echo " Done"

# ── Enable + start services ────────────────────────────────────────────────────
echo " Enabling services..."
sudo systemctl daemon-reload
sudo systemctl enable localflight.service
sudo systemctl enable localflight-kiosk.service
echo " Done"

echo " Starting Local Flight..."
sudo systemctl start localflight.service
sleep 3
sudo systemctl start localflight-kiosk.service

# ── Done ───────────────────────────────────────────────────────────────────────
echo ""
echo " =========================================="
echo "   Installation complete!"
echo " =========================================="
echo ""
echo " Local Flight is running."
echo " Access from any device on your network:"
echo "   http://localflight.local:8000"
echo "   http://$(hostname -I | awk '{print $1}'):8000"
echo ""
echo " Useful commands:"
echo "   sudo systemctl status localflight"
echo "   sudo systemctl restart localflight"
echo "   sudo journalctl -u localflight -f"
echo ""
echo " Edit API keys:  nano $ROOT/.env"
echo " Then restart:   sudo systemctl restart localflight"
echo ""