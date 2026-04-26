#!/usr/bin/env bash
# Local Flight - Pi management helper.
#
# Usage:
#   bash installers/pi/lf.sh start
#   bash installers/pi/lf.sh stop
#   bash installers/pi/lf.sh restart
#   bash installers/pi/lf.sh status
#   bash installers/pi/lf.sh logs
#   bash installers/pi/lf.sh update

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$ROOT/.venv"
CMD="${1:-status}"

case "$CMD" in
    start)
        sudo systemctl start localflight localflight-kiosk
        echo "Started."
        ;;
    stop)
        sudo systemctl stop localflight localflight-kiosk
        echo "Stopped."
        ;;
    restart)
        sudo systemctl restart localflight
        sleep 2
        sudo systemctl restart localflight-kiosk
        echo "Restarted."
        ;;
    status)
        echo "== localflight =="
        sudo systemctl status localflight --no-pager -l
        echo ""
        echo "== localflight-kiosk =="
        sudo systemctl status localflight-kiosk --no-pager -l
        ;;
    logs)
        sudo journalctl -u localflight -f --no-pager
        ;;
    update)
        if [ ! -x "$VENV/bin/python" ]; then
            echo "ERROR: No virtual environment found at $VENV."
            echo "Run bash installers/pi/install.sh first."
            exit 1
        fi
        echo "Pulling latest code..."
        git -C "$ROOT" pull --ff-only
        echo "Installing updated package..."
        "$VENV/bin/python" -m pip install -e "$ROOT" -q
        sudo systemctl restart localflight
        sleep 2
        sudo systemctl restart localflight-kiosk
        echo "Updated and restarted."
        ;;
    *)
        echo "Usage: bash installers/pi/lf.sh [start|stop|restart|status|logs|update]"
        exit 1
        ;;
esac
