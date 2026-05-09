#!/usr/bin/env bash
# Local Flight - Raspberry Pi installer
#
# Usage:
#   bash installers/pi/install.sh                  # guided display choice (Enter = headless)
#   bash installers/pi/install.sh --headless       # backend only - LED panels, LAN clients
#   bash installers/pi/install.sh --kiosk          # headless + legacy Chromium fallback kiosk on HDMI
#   bash installers/pi/install.sh --native-kiosk   # native Qt fullscreen kiosk on HDMI
#
# Run as the normal Pi user (not root). Requires: Pi OS Bookworm/Trixie 64-bit, Python 3.11+.

set -euo pipefail

# Args -----------------------------------------------------------------------
KIOSK=0
NATIVE_KIOSK=0
REQUESTED_DISPLAY_MODE=""
for arg in "$@"; do
    case "$arg" in
        --kiosk)
            REQUESTED_DISPLAY_MODE="chromium-kiosk"
            ;;
        --native-kiosk)
            REQUESTED_DISPLAY_MODE="native-kiosk"
            ;;
        --headless)
            REQUESTED_DISPLAY_MODE="headless"
            ;;
        --help|-h)
            echo "Usage: bash installers/pi/install.sh [--native-kiosk|--kiosk|--headless]"
            echo "  no flag opens a small menu when run interactively; Enter defaults to headless"
            exit 0
            ;;
        *)
            echo "Unknown argument: $arg"
            echo "Usage: bash installers/pi/install.sh [--native-kiosk|--kiosk|--headless]"
            exit 1
            ;;
    esac
done

# Paths ----------------------------------------------------------------------
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$ROOT/.venv"
SERVICE_USER="$(whoami)"
USER_SYSTEMD_DIR="$HOME/.config/systemd/user"
NATIVE_GUI_SERVICE="$USER_SYSTEMD_DIR/localflight-native-kiosk.service"
NATIVE_GUI_WRAPPER="$HOME/.localflight/bin/localflight-native-kiosk.sh"

# Helpers --------------------------------------------------------------------
ok()   { echo "  [OK]  $*"; }
step() { echo ""; echo "  -->  $*"; }
fail() { echo ""; echo "  [ERR] $*"; exit 1; }
warn() { echo "  [WARN] $*"; }

choose_display_mode() {
    if [ -n "$REQUESTED_DISPLAY_MODE" ]; then
        printf '%s\n' "$REQUESTED_DISPLAY_MODE"
        return
    fi
    if [ -t 0 ]; then
        echo "  Choose how this Pi should run Local Flight:" >&2
        echo "    1) Headless server        - recommended over SSH; LAN/mobile/matrix access" >&2
        echo "    2) Native Qt kiosk        - attached HDMI display, Chrome-free fullscreen GUI" >&2
        echo "    3) Chromium kiosk fallback - attached HDMI display when Qt is not usable" >&2
        printf "  Select 1/2/3, or press Enter for Headless: " >&2
        read -r choice
        case "$choice" in
            2) printf '%s\n' "native-kiosk" ;;
            3) printf '%s\n' "chromium-kiosk" ;;
            *) printf '%s\n' "headless" ;;
        esac
        return
    fi
    printf '%s\n' "headless"
}

PI_DISPLAY_MODE="$(choose_display_mode)"
case "$PI_DISPLAY_MODE" in
    headless)
        KIOSK=0
        NATIVE_KIOSK=0
        PI_GUI_MODE="headless"
        ;;
    native-kiosk)
        KIOSK=0
        NATIVE_KIOSK=1
        PI_GUI_MODE="native"
        ;;
    chromium-kiosk)
        KIOSK=1
        NATIVE_KIOSK=0
        PI_GUI_MODE="headless"
        ;;
    *)
        fail "Invalid display mode: $PI_DISPLAY_MODE"
        ;;
esac

user_systemctl() {
    XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" systemctl --user "$@"
}

set_env_value() {
    local key="$1"
    local value="$2"
    local file="$3"
    if grep -q "^${key}=" "$file"; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$file"
    else
        printf '\n%s=%s\n' "$key" "$value" >> "$file"
    fi
}

echo ""
echo "  +--------------------------------------+"
echo "  |   Local Flight - Pi Installer        |"
echo "  +--------------------------------------+"
echo ""
echo "  Root:  $ROOT"
echo "  User:  $SERVICE_USER"
if [ "$NATIVE_KIOSK" -eq 1 ]; then
    echo "  Mode:  native kiosk (Qt on HDMI, split backend + user GUI)"
elif [ "$KIOSK" -eq 1 ]; then
    echo "  Mode:  kiosk (Chromium on HDMI)"
else
    echo "  Mode:  headless (no display)"
fi
echo ""

[ "${EUID:-$(id -u)}" -eq 0 ] && fail "Do not run as root. Run as your normal Pi user - sudo is used internally."

# 1. System packages ---------------------------------------------------------
step "Updating package lists..."
sudo apt-get update -qq > /dev/null 2>&1
ok "Package lists updated"

step "Installing Python, git, and mDNS packages..."
sudo apt-get install -y -qq python3 python3-venv python3-pip git avahi-daemon > /dev/null 2>&1
ok "python3, python3-venv, python3-pip, git, avahi-daemon installed"

if [ "$NATIVE_KIOSK" -eq 1 ]; then
    step "Installing Qt runtime packages for native kiosk..."
    sudo apt-get install -y -qq \
        libegl1 \
        libgl1 \
        libfontconfig1 \
        libdbus-1-3 \
        libxkbcommon0 \
        libxcb-cursor0 \
        libxcb-icccm4 \
        libxcb-image0 \
        libxcb-keysyms1 \
        libxcb-render-util0 \
        libxcb-xinerama0 \
        libxcb-xinput0 \
        libxcb-xfixes0 \
        libxcb-shape0 \
        > /dev/null 2>&1
    ok "Qt runtime packages installed"
fi

# 2. Chromium (legacy kiosk only) -------------------------------------------
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
        echo "  [WARN] Chromium not available - kiosk service will be skipped"
        KIOSK=0
    fi
fi

# 3. Python venv -------------------------------------------------------------
if [ ! -x "$VENV/bin/python" ]; then
    step "Creating Python virtual environment..."
    python3 -m venv "$VENV"
    ok "Virtual environment created"
else
    step "Upgrading existing virtual environment..."
    ok "Already exists - will upgrade package"
fi

step "Installing Local Flight..."
"$VENV/bin/python" -m pip install --upgrade pip -q > /dev/null 2>&1
INSTALL_TARGET="$ROOT"
if [ "$NATIVE_KIOSK" -eq 1 ]; then
    INSTALL_TARGET="${ROOT}[native]"
fi
"$VENV/bin/python" -m pip install -e "$INSTALL_TARGET" -q > /dev/null 2>&1
ok "Local Flight installed"

if [ "$NATIVE_KIOSK" -eq 1 ]; then
    step "Confirming PySide6/Qt availability..."
    QT_INFO="$("$VENV/bin/python" - <<'PY'
from PySide6.QtCore import qVersion
print(qVersion())
PY
)"
    ok "PySide6/Qt available: Qt $QT_INFO"
fi

# 4. Environment file --------------------------------------------------------
if [ ! -f "$ROOT/.env" ]; then
    step "Creating .env..."
    cat > "$ROOT/.env" <<'ENVEOF'
# Local Flight - client environment
# The setup wizard writes these on first launch.
# Restart after any manual changes: sudo systemctl restart localflight

LOCALFLIGHT_ACTIVATION_TOKEN=
LOCALFLIGHT_RELAY_URL=https://localflight-community-relay.fly.dev
LOCALFLIGHT_GUI_MODE=headless

AVIATIONSTACK_API_KEY=
LOCALFLIGHT_AVIATIONSTACK_ENABLED=1
LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT=90
LOCALFLIGHT_RELAY_MONTHLY_LIMIT=50

RAPIDAPI_KEY=
LOCALFLIGHT_RAPIDAPI_MONTHLY_LIMIT=10000

OPENSKY_CLIENT_ID=
OPENSKY_CLIENT_SECRET=
ENVEOF
    ok ".env created"
else
    ok ".env already exists - skipping"
fi

step "Setting Pi GUI mode in .env..."
set_env_value "LOCALFLIGHT_GUI_MODE" "$PI_GUI_MODE" "$ROOT/.env"
ok "LOCALFLIGHT_GUI_MODE=$PI_GUI_MODE"

# 5. systemd: main service ---------------------------------------------------
step "Installing localflight.service..."
SERVICE_AFTER="network-online.target"
SERVICE_WANTS="network-online.target"
SERVICE_INSTALL_TARGET="multi-user.target"
SERVICE_EXTRA_ENV=""

if [ "$NATIVE_KIOSK" -eq 1 ]; then
    # The backend service stays headless. A separate user-session service owns
    # the Qt fullscreen shell so display permissions/session state stay sane.
    SERVICE_EXTRA_ENV="Environment=LOCALFLIGHT_GUI_MODE=headless"
fi

sudo tee /etc/systemd/system/localflight.service > /dev/null <<EOF
[Unit]
Description=Local Flight - Airport FIDS
After=$SERVICE_AFTER
Wants=$SERVICE_WANTS

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$ROOT/src
EnvironmentFile=$ROOT/.env
$SERVICE_EXTRA_ENV
ExecStart=$VENV/bin/python -m localflight
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=localflight

[Install]
WantedBy=$SERVICE_INSTALL_TARGET
EOF
ok "localflight.service installed"

# 6. systemd: browser kiosk service (optional legacy mode) -------------------
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
ExecStart=$CHROMIUM_BIN --kiosk --no-sandbox --disable-infobars --disable-session-crashed-bubble --disable-restore-session-state --noerrdialogs --disable-translate --no-first-run --fast --fast-start --disable-features=TranslateUI --disk-cache-dir=/tmp/chromium-cache --user-data-dir=$HOME/.localflight/browser-profile http://localhost:8000/splash?next=%2Fdisplay
Restart=on-failure
RestartSec=10

[Install]
WantedBy=graphical.target
EOF
    ok "localflight-kiosk.service installed"
fi

# Remove stale Chromium service unless legacy browser kiosk is requested.
if [ "$KIOSK" -eq 0 ] && [ -f /etc/systemd/system/localflight-kiosk.service ]; then
    step "Removing stale Chromium kiosk service..."
    sudo systemctl stop localflight-kiosk 2>/dev/null || true
    sudo systemctl disable localflight-kiosk 2>/dev/null || true
    sudo rm -f /etc/systemd/system/localflight-kiosk.service
    ok "Chromium kiosk service removed"
fi

# 7. Native Qt user-session kiosk service ------------------------------------
if [ "$NATIVE_KIOSK" -eq 1 ]; then
    step "Installing native Qt user-session kiosk service..."
    mkdir -p "$(dirname "$NATIVE_GUI_WRAPPER")" "$USER_SYSTEMD_DIR"
    cat > "$NATIVE_GUI_WRAPPER" <<EOF
#!/usr/bin/env bash
set -euo pipefail

ROOT="$ROOT"
VENV="$VENV"
BASE_URL="\${LOCALFLIGHT_NATIVE_BASE_URL:-http://127.0.0.1:8000}"

cd "\$ROOT/src"

ready=0
for _i in \$(seq 1 60); do
    if "\$VENV/bin/python" - <<'PY'
import os
import urllib.request

url = os.environ.get("LOCALFLIGHT_NATIVE_BASE_URL", "http://127.0.0.1:8000").rstrip("/") + "/health"
with urllib.request.urlopen(url, timeout=1) as response:
    raise SystemExit(0 if response.status < 500 else 1)
PY
    then
        ready=1
        break
    fi
    sleep 1
done

if [ "\$ready" -ne 1 ]; then
    echo "Local Flight backend did not become ready at \$BASE_URL" >&2
    exit 1
fi

exec "\$VENV/bin/python" -m localflight.native.app
EOF
    chmod +x "$NATIVE_GUI_WRAPPER"

    cat > "$NATIVE_GUI_SERVICE" <<EOF
[Unit]
Description=Local Flight - Native Qt Kiosk
After=graphical-session.target

[Service]
Type=simple
WorkingDirectory=$ROOT/src
EnvironmentFile=$ROOT/.env
Environment=LOCALFLIGHT_GUI_MODE=native
Environment=LOCALFLIGHT_NATIVE_FULLSCREEN=1
Environment=LOCALFLIGHT_NATIVE_UI_ONLY=1
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/$SERVICE_USER/.Xauthority
Environment=QT_QPA_PLATFORM=xcb
ExecStart=$NATIVE_GUI_WRAPPER
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
EOF

    sudo loginctl enable-linger "$SERVICE_USER" >/dev/null 2>&1 || warn "Could not enable lingering; native GUI may require a logged-in desktop session"
    if user_systemctl daemon-reload >/dev/null 2>&1 && user_systemctl enable localflight-native-kiosk.service >/dev/null 2>&1; then
        ok "native Qt user service installed"
    else
        warn "Native Qt user service written, but systemctl --user could not enable it from this shell"
        warn "After logging into the Pi desktop, run: systemctl --user enable --now localflight-native-kiosk.service"
    fi
elif [ -f "$NATIVE_GUI_SERVICE" ]; then
    step "Removing stale native Qt user-session kiosk service..."
    user_systemctl stop localflight-native-kiosk.service >/dev/null 2>&1 || true
    user_systemctl disable localflight-native-kiosk.service >/dev/null 2>&1 || true
    rm -f "$NATIVE_GUI_SERVICE" "$NATIVE_GUI_WRAPPER"
    user_systemctl daemon-reload >/dev/null 2>&1 || true
    ok "native Qt user service removed"
fi

# 8. mDNS hostname -----------------------------------------------------------
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
ok "Hostname: localflight - accessible as localflight.local"

# 9. lf command --------------------------------------------------------------
step "Installing 'lf' management command..."
sudo tee /usr/local/bin/lf > /dev/null <<EOF
#!/usr/bin/env bash
exec bash $ROOT/installers/pi/lf.sh "\$@"
EOF
sudo chmod +x /usr/local/bin/lf
ok "'lf' available system-wide"

# 10. Enable and start -------------------------------------------------------
step "Enabling and starting services..."
sudo systemctl daemon-reload
sudo systemctl enable localflight.service > /dev/null 2>&1
sudo systemctl restart localflight.service

if [ "$NATIVE_KIOSK" -eq 1 ] && [ -f "$NATIVE_GUI_SERVICE" ]; then
    sleep 3
    user_systemctl restart localflight-native-kiosk.service >/dev/null 2>&1 || warn "Native Qt user service did not start from this shell; log into the Pi desktop or run: systemctl --user restart localflight-native-kiosk.service"
fi

if [ "$KIOSK" -eq 1 ] && [ -f /etc/systemd/system/localflight-kiosk.service ]; then
    sudo systemctl enable localflight-kiosk.service > /dev/null 2>&1
    sleep 3
    sudo systemctl restart localflight-kiosk.service
fi
ok "Services started"

# Summary --------------------------------------------------------------------
PI_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"

echo ""
echo "  +--------------------------------------+"
echo "  |   Installation complete              |"
echo "  +--------------------------------------+"
echo ""
if [ "$NATIVE_KIOSK" -eq 1 ]; then
    echo "  Native Qt kiosk mode is enabled for the attached display."
    echo "  Backend: localflight.service (headless)"
    echo "  Display: user service localflight-native-kiosk.service"
    echo ""
fi
echo "  Open in any browser on your network:"
[ -n "$PI_IP" ] && echo "    http://$PI_IP:8000"
echo "    http://localflight.local:8000  (mDNS - may take a minute)"
echo ""
echo "  Management:"
echo "    lf status     - check if running"
echo "    lf logs       - live log tail"
echo "    lf restart    - restart after config changes"
echo "    lf update     - pull latest code and restart"
echo ""
echo "  To add API keys later:"
echo "    nano $ROOT/.env"
echo "    lf restart"
echo ""
