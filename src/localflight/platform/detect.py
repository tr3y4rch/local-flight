"""
localflight/platform/detect.py

Detects the current platform so __main__.py can branch accordingly.

Platforms:
  WINDOWS      — Windows 10/11 desktop
  MACOS        — macOS 12+
  RASPBERRY_PI — Raspberry Pi running Linux (any model)
  LINUX        — Generic Linux desktop (not Pi)
"""
from __future__ import annotations

import sys
from enum import Enum
from functools import lru_cache
from pathlib import Path


class Platform(Enum):
    WINDOWS      = "windows"
    MACOS        = "macos"
    RASPBERRY_PI = "pi"
    LINUX        = "linux"


@lru_cache(maxsize=1)
def detect() -> Platform:
    """
    Detect the current platform. Result is cached — safe to call repeatedly.
    """
    if sys.platform == "win32":
        return Platform.WINDOWS

    if sys.platform == "darwin":
        return Platform.MACOS

    # Linux — check for Pi
    try:
        model = Path("/proc/device-tree/model").read_bytes().decode("utf-8", errors="ignore")
        if "Raspberry Pi" in model:
            return Platform.RASPBERRY_PI
    except Exception:
        pass

    return Platform.LINUX


def is_desktop() -> bool:
    """Returns True on platforms that show a GUI kiosk window and tray icon."""
    return detect() in (Platform.WINDOWS, Platform.MACOS)


def is_headless() -> bool:
    """Returns True on platforms that run without a local display (Pi, Linux server)."""
    return detect() in (Platform.RASPBERRY_PI, Platform.LINUX)


def platform_name() -> str:
    """Human-readable platform name for logs and admin UI."""
    return {
        Platform.WINDOWS:      "Windows",
        Platform.MACOS:        "macOS",
        Platform.RASPBERRY_PI: "Raspberry Pi",
        Platform.LINUX:        "Linux",
    }[detect()]