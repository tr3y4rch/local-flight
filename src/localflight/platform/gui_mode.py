"""
Read and sanitize the requested local GUI mode.

Runtime startup uses platform.gui_launcher for the final platform/display/Qt
decision. This module stays intentionally small so installers and tests can
share the same LOCALFLIGHT_GUI_MODE parsing rules.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Optional

from localflight.platform.detect import Platform, detect

VALID_GUI_MODES = {"auto", "native", "browser", "headless"}
DEFAULT_GUI_MODE = "native"


def display_available(env: Optional[Mapping[str, str]] = None) -> bool:
    """Return whether this process appears to have a local display."""
    values = env if env is not None else os.environ
    return bool((values.get("DISPLAY") or "").strip() or (values.get("WAYLAND_DISPLAY") or "").strip())


def requested_gui_mode(env: Optional[Mapping[str, str]] = None) -> str:
    """Read and sanitize LOCALFLIGHT_GUI_MODE.

    The product default is native-first. Browser/kiosk mode remains available
    as a fallback path when the native Qt shell is not usable.
    """
    values = env if env is not None else os.environ
    raw = (values.get("LOCALFLIGHT_GUI_MODE") or DEFAULT_GUI_MODE).strip().lower()
    return raw if raw in VALID_GUI_MODES else DEFAULT_GUI_MODE


def resolve_gui_mode(
    platform: Optional[Platform] = None,
    env: Optional[Mapping[str, str]] = None,
) -> str:
    """
    Resolve the environment-requested GUI mode.

    Prefer localflight.platform.gui_launcher.decide_gui_launch() for startup
    decisions because it also checks whether PySide6/Qt is importable.
    """
    plat = platform or detect()
    mode = requested_gui_mode(env)
    if mode == "headless":
        return "headless"
    if mode == "browser":
        return "browser" if plat in {Platform.WINDOWS, Platform.MACOS} or display_available(env) else "headless"
    if mode == "native":
        return "native" if plat in {Platform.WINDOWS, Platform.MACOS} or display_available(env) else "headless"
    if plat in {Platform.WINDOWS, Platform.MACOS}:
        return "native"
    if display_available(env):
        return "native"
    return "headless"
