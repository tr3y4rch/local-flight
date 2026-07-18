#!/usr/bin/env bash
# Local Flight — Pi management helper
#
# Installed to /usr/local/bin/lf by the installer.
# Also callable directly: bash installers/pi/lf.sh <command>
#
# Commands:
#   lf status    — show service status
#   lf logs      — live log tail (Ctrl+C to exit)
#   lf start     — start the app
#   lf stop      — stop the app
#   lf restart   — restart after config changes
#   lf update    — pull latest code and restart

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$ROOT/.venv"
CMD="${1:-status}"

has_kiosk() {
    [ -f /etc/systemd/system/localflight-kiosk.service ]
}

has_native_kiosk() {
    [ -f "$HOME/.config/systemd/user/localflight-native-kiosk.service" ]
}

uses_native_gui() {
    [ -f "$ROOT/.env" ] && grep -Eq '^LOCALFLIGHT_GUI_MODE="?native"?$' "$ROOT/.env"
}

user_systemctl() {
    XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" systemctl --user "$@"
}

user_journalctl() {
    XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" journalctl --user "$@"
}

install_localflight_package() {
    RELEASE_LOCK="$ROOT/requirements/release-core.txt"
    if uses_native_gui; then
        echo "Installing updated package with native Qt support..."
        OS_CODENAME=""
        if [ -r /etc/os-release ]; then
            OS_CODENAME="$(. /etc/os-release && printf '%s' "${VERSION_CODENAME:-}")"
        fi
        case "$OS_CODENAME" in
            bookworm) RELEASE_LOCK="$ROOT/requirements/release-pi-bookworm.txt" ;;
            trixie) RELEASE_LOCK="$ROOT/requirements/release-pi-trixie.txt" ;;
            *)
                echo "ERROR: Native kiosk updates need Raspberry Pi OS Bookworm or Trixie 64-bit."
                exit 1
                ;;
        esac
    else
        echo "Installing updated package..."
    fi
    [ -f "$RELEASE_LOCK" ] || {
        echo "ERROR: Missing release dependency lock: $RELEASE_LOCK"
        exit 1
    }
    "$VENV/bin/python" -m pip install --require-hashes -r "$RELEASE_LOCK" -q > /dev/null 2>&1
    "$VENV/bin/python" -m pip install --no-deps -e "$ROOT" -q > /dev/null 2>&1
}

case "$CMD" in
    start)
        sudo systemctl start localflight
        if has_native_kiosk; then
            user_systemctl start localflight-native-kiosk 2>/dev/null || echo "WARN: native kiosk user service could not be started from this shell."
        fi
        has_kiosk && sudo systemctl start localflight-kiosk || true
        echo "Started."
        ;;

    stop)
        has_kiosk && sudo systemctl stop localflight-kiosk 2>/dev/null || true
        has_native_kiosk && user_systemctl stop localflight-native-kiosk 2>/dev/null || true
        sudo systemctl stop localflight
        echo "Stopped."
        ;;

    restart)
        sudo systemctl restart localflight
        if has_native_kiosk; then
            sleep 2
            user_systemctl restart localflight-native-kiosk 2>/dev/null || echo "WARN: native kiosk user service could not be restarted from this shell."
        fi
        if has_kiosk; then
            sleep 2
            sudo systemctl restart localflight-kiosk
        fi
        echo "Restarted."
        ;;

    status)
        echo "=== localflight ==="
        sudo systemctl status localflight --no-pager -l
        if has_kiosk; then
            echo ""
            echo "=== localflight-kiosk ==="
            sudo systemctl status localflight-kiosk --no-pager -l
        fi
        if has_native_kiosk; then
            echo ""
            echo "=== localflight-native-kiosk (user service) ==="
            user_systemctl status localflight-native-kiosk --no-pager -l || true
        fi
        ;;

    logs)
        if has_native_kiosk && [ "${2:-}" = "gui" ]; then
            user_journalctl -u localflight-native-kiosk -f --no-pager
        else
            sudo journalctl -u localflight -f --no-pager
        fi
        ;;

    update)
        [ -x "$VENV/bin/python" ] || {
            echo "ERROR: No virtual environment at $VENV — run the installer first."
            exit 1
        }
        [ -d "$ROOT/.git" ] || {
            echo "ERROR: This folder is not a git checkout."
            echo "If you installed from a Pi source zip, download/unzip the newer bundle and rerun:"
            echo "  bash installers/pi/install.sh --headless"
            exit 1
        }
        echo "Pulling latest code..."
        git -C "$ROOT" pull --ff-only
        install_localflight_package
        sudo systemctl restart localflight
        if has_native_kiosk; then
            sleep 2
            user_systemctl restart localflight-native-kiosk 2>/dev/null || echo "WARN: native kiosk user service could not be restarted from this shell."
        fi
        if has_kiosk; then
            sleep 2
            sudo systemctl restart localflight-kiosk
        fi
        echo "Updated and restarted."
        ;;

    *)
        echo "Usage: lf [start|stop|restart|status|logs [gui]|update]"
        exit 1
        ;;
esac
