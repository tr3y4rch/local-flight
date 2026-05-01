"""
localflight/__main__.py

Main entry point for Local Flight.
Platform-aware startup — behaviour differs by OS:

  Desktop (Windows / macOS):
    1. Load .env
    2. Start scheduler (if setup complete)
    3. Start uvicorn
    4. Launch kiosk browser window (/setup or /display)
    5. Setup watcher if first launch
    6. System tray icon (main thread — blocks until quit)

  Headless (Raspberry Pi / Linux):
    1. Load .env
    2. Start scheduler (if setup complete)
    3. Start uvicorn
    4. Block forever — systemd handles lifecycle
       Chromium kiosk is a separate systemd service

Usage:
  python -m localflight         (from src/)
  localflight                   (if installed as package)
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from contextlib import closing
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from localflight.platform.detect import Platform, detect, is_desktop, is_headless
from localflight.platform.browser import launch_app_window

HOST     = "0.0.0.0"
PORT     = 8000
BASE_URL = f"http://localhost:{PORT}"

# ── Module-level browser process reference ─────────────────────────────────────
# Exposed so server.py /api/quit can terminate the kiosk window.
_browser_proc: Optional[subprocess.Popen] = None
_stdio_fallback_handles: list[object] = []


def _ensure_stdio() -> None:
    """
    PyInstaller windowed builds can start with stdio streams set to None.
    Uvicorn/logging expects writable streams, so provide a local bootstrap log.
    """
    if sys.stdout is not None and sys.stderr is not None and sys.stdin is not None:
        return
    try:
        log_dir = Path.home() / ".localflight" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stream = open(log_dir / f"bootstrap_{os.getpid()}.log", "a", encoding="utf-8", buffering=1)
        _stdio_fallback_handles.append(stream)
        if sys.stdout is None:
            sys.stdout = stream
        if sys.stderr is None:
            sys.stderr = stream
        if sys.stdin is None:
            stdin = open(os.devnull, "r", encoding="utf-8")
            _stdio_fallback_handles.append(stdin)
            sys.stdin = stdin
    except Exception:
        # Last-resort fallback: keep startup alive even if the log path is unavailable.
        devnull_out = open(os.devnull, "a", encoding="utf-8")
        devnull_in = open(os.devnull, "r", encoding="utf-8")
        _stdio_fallback_handles.extend([devnull_out, devnull_in])
        sys.stdout = sys.stdout or devnull_out
        sys.stderr = sys.stderr or devnull_out
        sys.stdin = sys.stdin or devnull_in


def _splash_url(next_path: str = "/display") -> str:
    """Build the short launch splash URL for a local app path."""
    if not next_path.startswith("/") or next_path.startswith("//"):
        next_path = "/display"
    return f"{BASE_URL}/splash?next={quote(next_path, safe='')}"


# ── .env loader ────────────────────────────────────────────────────────────────

def _load_dotenv() -> None:
    """
    Load .env from the project root into os.environ.
    Safe to call multiple times — never overwrites existing env vars.
    """
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent.parent / ".env",
        here.parent / ".env",
        Path.home() / ".localflight" / ".env",
    ]
    env_path = None
    for p in candidates:
        if p.exists():
            env_path = p
            break
    if env_path is None:
        return
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip(); value = value.strip()
                if key and key not in os.environ:
                    os.environ[key] = value
        print(f"Loaded .env from {env_path}")
    except Exception as exc:
        print(f"Warning: could not load .env: {exc}")


# ── First launch check ─────────────────────────────────────────────────────────

def _is_first_launch() -> bool:
    try:
        from localflight.storage.config import config_path
        return not (config_path().parent / "setup_complete").exists()
    except Exception:
        return True


def _wait_for_setup_complete(poll_interval: float = 1.5) -> None:
    while _is_first_launch():
        time.sleep(poll_interval)


# ── Server helpers ─────────────────────────────────────────────────────────────

def _wait_for_server(timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with closing(socket.create_connection(("localhost", PORT), timeout=0.5)):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def _start_scheduler() -> threading.Thread:
    from localflight.scheduler.control import start_scheduler_thread
    return start_scheduler_thread()


def _start_uvicorn() -> threading.Thread:
    def _run():
        import uvicorn
        uvicorn.run(
            "localflight.ui.server:app",
            host=HOST, port=PORT, log_level="warning",
        )
    t = threading.Thread(target=_run, name="uvicorn", daemon=True)
    t.start()
    return t


# ── Setup watcher (desktop only) ──────────────────────────────────────────────

def _start_setup_watcher(
    scheduler_ref: list,
    browser_proc_ref: list,
) -> threading.Thread:
    """
    Watches for setup_complete marker on first launch.
    When detected: re-loads .env, starts scheduler, opens /display.
    """
    def _watch():
        print("Setup watcher: waiting for setup to complete...")
        _wait_for_setup_complete()
        _load_dotenv()
        print("Setup watcher: setup complete — starting scheduler")
        scheduler_ref[0] = _start_scheduler()
        time.sleep(1.0)
        proc = launch_app_window(_splash_url("/display"))
        if proc:
            browser_proc_ref[0] = proc
            import localflight.__main__ as _self
            _self._browser_proc = proc
        else:
            webbrowser.open(_splash_url("/display"))
        print("Setup watcher: done — display opened")

    t = threading.Thread(target=_watch, name="setup-watcher", daemon=True)
    t.start()
    return t


# ── Headless runtime (Pi / Linux) ─────────────────────────────────────────────

def _run_headless() -> None:
    """
    Pi/Linux runtime:
    - Start scheduler
    - Start uvicorn
    - Block forever (systemd handles lifecycle)
    - No tray, no kiosk window (Chromium is a separate systemd service)
    """
    from localflight.platform.detect import platform_name
    print(f"Local Flight starting in headless mode ({platform_name()})")

    _start_scheduler()
    print("Scheduler started")

    _start_uvicorn()
    print("Web server starting...")

    if not _wait_for_server(timeout=15.0):
        print("ERROR: Web server did not start in time.")
        sys.exit(1)

    print(f"Server ready at {BASE_URL}")
    print("Running headless — manage via web UI or systemctl")
    print("Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nLocal Flight stopping.")
        sys.exit(0)


# ── Desktop runtime (Windows / macOS) ─────────────────────────────────────────

def _run_desktop() -> None:
    """
    Windows/macOS runtime:
    - Start scheduler (if setup complete)
    - Start uvicorn
    - Launch kiosk browser window
    - Setup watcher on first launch
    - System tray icon (blocks main thread)
    """
    from localflight.platform.tray import build_tray

    print("Local Flight starting...")

    first_launch = _is_first_launch()
    launch_url   = _splash_url("/setup" if first_launch else "/display")

    if first_launch:
        print("First launch — setup wizard will open")

    scheduler_ref    = [None]
    browser_proc_ref = [None]

    if not first_launch:
        scheduler_ref[0] = _start_scheduler()
        print("Scheduler started")

    _start_uvicorn()
    print("Web server starting...")

    if not _wait_for_server(timeout=15.0):
        print("ERROR: Web server did not start in time.")
        sys.exit(1)
    print(f"Server ready at {BASE_URL}")

    # Launch kiosk window
    global _browser_proc
    browser_proc = launch_app_window(launch_url)
    if not browser_proc:
        webbrowser.open(launch_url)
        print("No browser found — opened in default browser")
    browser_proc_ref[0] = browser_proc
    _browser_proc       = browser_proc

    if first_launch:
        _start_setup_watcher(scheduler_ref, browser_proc_ref)

    # Tray icon (blocks until quit)
    def on_quit():
        print("\nLocal Flight shutting down...")
        proc = browser_proc_ref[0]
        if proc:
            try: proc.terminate()
            except Exception: pass
        os._exit(0)

    def on_open_display():
        proc = launch_app_window(_splash_url("/display"))
        if proc:
            browser_proc_ref[0] = proc
            global _browser_proc
            _browser_proc = proc

    icon = build_tray(on_quit=on_quit, on_open_display=on_open_display)
    print("Local Flight running — right-click taskbar icon for menu")
    icon.run()


# ── Entry point ────────────────────────────────────────────────────────────────

def _install_crash_hooks() -> None:
    """
    Wire sys.excepthook + threading.excepthook so unhandled exceptions
    anywhere in the process auto-file a crash report to developer's Linear.
    KeyboardInterrupt and SystemExit are intentionally excluded.
    """
    import traceback as _tb

    def _report(error_msg: str, tb_str: str, context: str) -> None:
        try:
            from localflight.sources.web.bug_reporter import submit_crash
            submit_crash(error_msg, traceback_str=tb_str, context=context)
        except Exception:
            pass

    _orig_excepthook = sys.excepthook

    def _excepthook(exc_type, exc_value, exc_tb):
        if not issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            tb_str = "".join(_tb.format_exception(exc_type, exc_value, exc_tb))
            _report(f"{exc_type.__name__}: {exc_value}", tb_str, "main-thread")
        _orig_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook

    import threading
    _orig_threading_hook = threading.excepthook

    def _threading_excepthook(args):
        if args.exc_type and not issubclass(args.exc_type, (KeyboardInterrupt, SystemExit)):
            tb_str = "".join(_tb.format_exception(args.exc_type, args.exc_value, args.exc_tb))
            name = getattr(args.thread, "name", "unknown") if args.thread else "unknown"
            _report(f"{args.exc_type.__name__}: {args.exc_value}", tb_str, f"thread/{name}")
        _orig_threading_hook(args)

    threading.excepthook = _threading_excepthook


def main() -> None:
    _ensure_stdio()
    _load_dotenv()
    _install_crash_hooks()

    if is_headless():
        _run_headless()
    else:
        _run_desktop()


if __name__ == "__main__":
    main()
