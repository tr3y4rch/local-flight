#!/usr/bin/env bash
# Local Flight — Pi management helper
#
# Usage:
#   ./installers/pi/lf.sh start
#   ./installers/pi/lf.sh stop
#   ./installers/pi/lf.sh restart
#   ./installers/pi/lf.sh status
#   ./installers/pi/lf.sh logs
#   ./installers/pi/lf.sh update

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
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
        echo "── localflight ──────────────────────────────"
        sudo systemctl status localflight --no-pager -l
        echo ""
        echo "── localflight-kiosk ────────────────────────"
        sudo systemctl status localflight-kiosk --no-pager -l
        ;;
    logs)
        sudo journalctl -u localflight -f --no-pager
        ;;
    update)
        echo "Pulling latest code..."
        cd "$ROOT"
        git pull
        source "$ROOT/.venv/bin/activate"
        pip install -e . -q
        sudo systemctl restart localflight
        echo "Updated and restarted."
        ;;
    *)
        echo "Usage: lf.sh [start|stop|restart|status|logs|update]"
        exit 1
        ;;
esac