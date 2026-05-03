from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.request


def _port_8000_open() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=0.6):
            return True
    except OSError:
        return False


def _port_8000_owners() -> list[str]:
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
    except Exception:
        return []
    owners: list[str] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[1].endswith(":8000") and parts[3].upper() == "LISTENING":
            owners.append(parts[4])
    return sorted(set(owners))


def _request_clean_quit() -> None:
    request = urllib.request.Request(
        "http://127.0.0.1:8000/api/quit",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=4).read()
    except Exception:
        pass


def main() -> int:
    if _port_8000_open():
        print(" Existing Local Flight API detected on port 8000; requesting clean quit...")
        _request_clean_quit()
        time.sleep(2.0)

    port_owners = _port_8000_owners()
    if port_owners:
        print(" ERROR: Port 8000 is still occupied, so the in-dev server cannot start cleanly.")
        if port_owners:
            print(" Port 8000 owner PID(s): " + ", ".join(port_owners))
        print(" Close the app using that port, or change LOCALFLIGHT_PORT once we add multi-port dev support.")
        return 2

    print(" Dev server port is free")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
