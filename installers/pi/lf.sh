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

case "$CMD" in
    start)
        sudo systemctl start localflight
        has_kiosk && sudo systemctl start localflight-kiosk || true
        echo "Started."
        ;;

    stop)
        has_kiosk && sudo systemctl stop localflight-kiosk 2>/dev/null || true
        sudo systemctl stop localflight
        echo "Stopped."
        ;;

    restart)
        sudo systemctl restart localflight
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
        ;;

    logs)
        sudo journalctl -u localflight -f --no-pager
        ;;

    update)
        [ -x "$VENV/bin/python" ] || {
            echo "ERROR: No virtual environment at $VENV — run the installer first."
            exit 1
        }
        echo "Pulling latest code..."
        git -C "$ROOT" pull --ff-only
        echo "Installing updated package..."
        "$VENV/bin/python" -m pip install -e "$ROOT" -q > /dev/null 2>&1
        sudo systemctl restart localflight
        if has_kiosk; then
            sleep 2
            sudo systemctl restart localflight-kiosk
        fi
        echo "Updated and restarted."
        ;;

    *)
        echo "Usage: lf [start|stop|restart|status|logs|update]"
        exit 1
        ;;
esac
