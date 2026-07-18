"""Platform-aware GUI launch decision layer."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import os
from typing import Optional

from localflight.platform.detect import Platform, detect
from localflight.platform.gui_mode import display_available, requested_gui_mode

GuiMode = str
NativeProbe = Callable[[], bool]


@dataclass(frozen=True)
class GuiLaunchDecision:
    """Resolved GUI launch plan for this process."""

    requested_mode: GuiMode
    effective_mode: GuiMode
    platform: Platform
    native_available: bool
    display_available: bool
    fullscreen: bool
    reason: str

    @property
    def is_native(self) -> bool:
        return self.effective_mode == "native"

    @property
    def is_browser(self) -> bool:
        return self.effective_mode == "browser"

    @property
    def is_headless(self) -> bool:
        return self.effective_mode == "headless"


def qt_available() -> bool:
    """Return whether PySide6/Qt can be imported in this environment."""
    try:
        from localflight.native.qt_compat import qt_available as _qt_available

        return bool(_qt_available())
    except Exception:
        return False


def decide_gui_launch(
    platform: Optional[Platform] = None,
    env: Optional[Mapping[str, str]] = None,
    native_probe: Optional[NativeProbe] = None,
) -> GuiLaunchDecision:
    """Resolve the launch shell after platform, display, and Qt availability checks."""
    values = env if env is not None else os.environ
    plat = platform or detect()
    requested = requested_gui_mode(values)
    has_display = _platform_display_available(plat, values)
    native_ok = bool((native_probe or qt_available)())

    if requested == "headless":
        return _decision(requested, "headless", plat, native_ok, has_display, "headless requested", values)

    if requested == "browser":
        if has_display:
            return _decision(requested, "browser", plat, native_ok, has_display, "browser requested", values)
        return _decision(
            requested,
            "headless",
            plat,
            native_ok,
            has_display,
            "browser requested without display",
            values,
        )

    if requested == "native":
        if native_ok and has_display:
            return _decision(
                requested,
                "native",
                plat,
                native_ok,
                has_display,
                "native requested and Qt available",
                values,
            )
        if native_ok and _desktop_without_display_ok(plat):
            return _decision(
                requested,
                "native",
                plat,
                native_ok,
                has_display,
                "native requested on desktop",
                values,
            )
        if has_display:
            return _decision(
                requested,
                "browser",
                plat,
                native_ok,
                has_display,
                "native requested but Qt unavailable",
                values,
            )
        return _decision(
            requested,
            "headless",
            plat,
            native_ok,
            has_display,
            "native requested without display",
            values,
        )

    # auto
    if native_ok and (has_display or _desktop_without_display_ok(plat)):
        return _decision(
            requested,
            "native",
            plat,
            native_ok,
            has_display,
            "auto selected native Qt",
            values,
        )
    if has_display or plat in {Platform.WINDOWS, Platform.MACOS}:
        return _decision(
            requested,
            "browser",
            plat,
            native_ok,
            has_display,
            "auto selected browser UI",
            values,
        )
    return _decision(requested, "headless", plat, native_ok, has_display, "auto selected headless", values)


def _decision(
    requested: GuiMode,
    effective: GuiMode,
    platform: Platform,
    native_available: bool,
    has_display: bool,
    reason: str,
    env: Mapping[str, str] | None = None,
) -> GuiLaunchDecision:
    values = env or {}
    explicit_fullscreen = str(values.get("LOCALFLIGHT_NATIVE_FULLSCREEN", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return GuiLaunchDecision(
        requested_mode=requested,
        effective_mode=effective,
        platform=platform,
        native_available=native_available,
        display_available=has_display,
        fullscreen=effective == "native"
        and (platform is Platform.RASPBERRY_PI or explicit_fullscreen),
        reason=reason,
    )


def _desktop_without_display_ok(platform: Platform) -> bool:
    # Windows/macOS GUI sessions do not normally expose DISPLAY/WAYLAND_DISPLAY.
    return platform in {Platform.WINDOWS, Platform.MACOS}


def _platform_display_available(platform: Platform, env: Mapping[str, str]) -> bool:
    if platform in {Platform.WINDOWS, Platform.MACOS}:
        return True
    return display_available(env)
