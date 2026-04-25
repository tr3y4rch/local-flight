"""
localflight/platform/tray.py

Cross-platform system tray icon for Local Flight.

Windows / macOS — uses pystray (works on both)
Pi / Linux      — no tray, returns a no-op stub

Tray menu:
  Open Display      → kiosk window or default browser
  Open FIDS         → default browser
  Open Radar        → default browser
  Open Settings     → default browser
  Open Admin        → default browser
  Open History      → default browser
  ──────────────────
  Restart Scheduler
  ──────────────────
  Quit

Icon color:
  Green  = scheduler OK
  Amber  = degraded (had errors but previously succeeded)
  Red    = never succeeded
  Gray   = unknown
"""
from __future__ import annotations

import threading
import webbrowser
from typing import Callable, Optional

from localflight.platform.detect import is_desktop

BASE_URL = "http://localhost:8000"


# ── Icon drawing ───────────────────────────────────────────────────────────────

def _draw_icon(color: str = "#1D9E75"):
    from PIL import Image, ImageDraw
    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, size - 2, size - 2], fill=color)
    cx, cy = size // 2, size // 2
    draw.polygon([(cx-18,cy+4),(cx+20,cy),(cx-18,cy-4)], fill="white")
    draw.polygon([(cx-4,cy-2),(cx+4,cy-2),(cx-2,cy-14),(cx-10,cy-14)], fill="white")
    draw.polygon([(cx-18,cy-2),(cx-12,cy-2),(cx-16,cy-8)], fill="white")
    return img


def _status_color() -> str:
    try:
        from localflight.storage.state import load_state
        state = load_state()
        if state.ok:                return "#1D9E75"
        elif state.last_success_utc: return "#BA7517"
        else:                        return "#A32D2D"
    except Exception:
        return "#888780"


def _update_icon_loop(icon, stop_event: threading.Event) -> None:
    while not stop_event.wait(30):
        try:
            icon.icon = _draw_icon(_status_color())
        except Exception:
            pass


# ── No-op stub for headless platforms ─────────────────────────────────────────

class _HeadlessTray:
    """
    Stub returned on Pi/Linux — no tray icon.
    run() just blocks forever (or until KeyboardInterrupt).
    The web UI + /api/quit handle lifecycle on headless platforms.
    """
    def run(self) -> None:
        import time
        print("Running headless — no tray icon (Pi/Linux mode)")
        print("Access the UI at http://localhost:8000")
        print("Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


# ── Desktop tray (Windows / macOS) ────────────────────────────────────────────

def build_tray(
    on_quit: Callable,
    on_restart_scheduler: Optional[Callable] = None,
    on_open_display: Optional[Callable] = None,
):
    """
    Build and return the system tray icon.
    On Pi/Linux returns a _HeadlessTray stub instead.
    Call .run() to start (blocks until quit).
    """
    if not is_desktop():
        return _HeadlessTray()

    import pystray

    color = _status_color()
    img   = _draw_icon(color)

    stop_event = threading.Event()

    def _open_display(icon, item):
        if on_open_display:
            on_open_display()
        else:
            webbrowser.open(f"{BASE_URL}/display")

    def _open(path: str):
        def _handler(icon, item):
            webbrowser.open(f"{BASE_URL}{path}")
        return _handler

    def _quit(icon, item):
        stop_event.set()
        icon.stop()
        on_quit()

    def _restart(icon, item):
        if on_restart_scheduler:
            on_restart_scheduler()

    menu_items = [
        pystray.MenuItem("Local Flight", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open Display",      _open_display),
        pystray.MenuItem("Open FIDS",         _open("/fids")),
        pystray.MenuItem("Open Radar",        _open("/radar")),
        pystray.MenuItem("Open Settings",     _open("/")),
        pystray.MenuItem("Open Admin",        _open("/admin")),
        pystray.MenuItem("Open History",      _open("/history")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Restart Scheduler", _restart),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit",              _quit),
    ]

    icon = pystray.Icon(
        name="localflight",
        icon=img,
        title="Local Flight",
        menu=pystray.Menu(*menu_items),
    )

    threading.Thread(
        target=_update_icon_loop,
        args=(icon, stop_event),
        daemon=True,
    ).start()

    return icon