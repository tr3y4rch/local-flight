"""
localflight/platform/browser.py

Cross-platform browser detection and kiosk window launcher.

Supports:
  Windows — Edge (preferred), Chrome
  macOS   — Chrome (preferred), Edge, Chromium via Homebrew
  Pi/Linux — No kiosk window managed here.
             Chromium is launched by systemd as a separate service.
             find_browser() returns None on these platforms.

The --app= flag and all other Chromium args work identically
on Windows and macOS so the launch logic is shared.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from localflight.platform.detect import Platform, detect

# Kiosk window size — override per-platform if needed
WINDOW_W = 1280
WINDOW_H = 800


def find_browser() -> Optional[tuple[str, str]]:
    """
    Returns (executable_path, browser_name) or None if no browser found
    or if the platform manages its own kiosk (Pi/Linux).
    """
    plat = detect()

    if plat == Platform.WINDOWS:
        candidates = [
            (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", "Edge"),
            (r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",       "Edge"),
            (r"C:\Program Files\Google\Chrome\Application\chrome.exe",        "Chrome"),
            (r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",  "Chrome"),
        ]
        for path, name in candidates:
            if Path(path).exists():
                return path, name
        # PATH fallback
        for cmd, name in [("msedge", "Edge"), ("chrome", "Chrome")]:
            if shutil.which(cmd):
                return cmd, name

    elif plat == Platform.MACOS:
        candidates = [
            ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "Chrome"),
            ("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge", "Edge"),
            ("/Applications/Chromium.app/Contents/MacOS/Chromium", "Chromium"),
        ]
        for path, name in candidates:
            if Path(path).exists():
                return path, name
        # Homebrew chromium fallback
        for cmd, name in [("google-chrome", "Chrome"), ("chromium", "Chromium")]:
            if shutil.which(cmd):
                return cmd, name

    # Pi / Linux — kiosk managed by systemd, not by us
    return None


def launch_app_window(url: str) -> Optional[subprocess.Popen]:
    """
    Launch a borderless kiosk browser window pointing at `url`.
    Returns the Popen object or None if no browser is available.

    On Pi/Linux always returns None — kiosk is systemd's responsibility.
    """
    browser = find_browser()
    if not browser:
        return None

    exe, name = browser
    print(f"Opening {name} app window: {url}")

    user_data = Path.home() / ".localflight" / "browser-profile"
    user_data.mkdir(parents=True, exist_ok=True)

    args = [
        exe,
        f"--app={url}",
        f"--window-size={WINDOW_W},{WINDOW_H}",
        f"--user-data-dir={user_data}",
        "--disable-infobars",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
    ]

    try:
        return subprocess.Popen(args)
    except Exception as exc:
        print(f"Failed to launch {name}: {exc}")
        return None