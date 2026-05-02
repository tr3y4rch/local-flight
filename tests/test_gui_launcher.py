from __future__ import annotations

from localflight.platform.detect import Platform
from localflight.platform.gui_launcher import decide_gui_launch


def test_auto_desktop_uses_native_when_qt_available() -> None:
    decision = decide_gui_launch(
        Platform.WINDOWS,
        {"LOCALFLIGHT_GUI_MODE": "auto"},
        native_probe=lambda: True,
    )

    assert decision.effective_mode == "native"
    assert decision.native_available is True
    assert decision.display_available is True
    assert decision.fullscreen is False


def test_blank_mode_defaults_to_native() -> None:
    decision = decide_gui_launch(
        Platform.WINDOWS,
        {},
        native_probe=lambda: True,
    )

    assert decision.requested_mode == "native"
    assert decision.effective_mode == "native"


def test_auto_desktop_falls_back_to_browser_when_qt_missing() -> None:
    decision = decide_gui_launch(
        Platform.MACOS,
        {"LOCALFLIGHT_GUI_MODE": "auto"},
        native_probe=lambda: False,
    )

    assert decision.effective_mode == "browser"
    assert decision.native_available is False


def test_auto_pi_without_display_stays_headless_even_when_qt_exists() -> None:
    decision = decide_gui_launch(
        Platform.RASPBERRY_PI,
        {"LOCALFLIGHT_GUI_MODE": "auto"},
        native_probe=lambda: True,
    )

    assert decision.effective_mode == "headless"
    assert decision.display_available is False


def test_native_default_pi_without_display_stays_headless() -> None:
    decision = decide_gui_launch(
        Platform.RASPBERRY_PI,
        {},
        native_probe=lambda: True,
    )

    assert decision.requested_mode == "native"
    assert decision.effective_mode == "headless"
    assert "without display" in decision.reason


def test_auto_pi_with_display_uses_native_fullscreen_when_qt_available() -> None:
    decision = decide_gui_launch(
        Platform.RASPBERRY_PI,
        {"LOCALFLIGHT_GUI_MODE": "auto", "DISPLAY": ":0"},
        native_probe=lambda: True,
    )

    assert decision.effective_mode == "native"
    assert decision.fullscreen is True


def test_explicit_browser_without_display_becomes_headless() -> None:
    decision = decide_gui_launch(
        Platform.LINUX,
        {"LOCALFLIGHT_GUI_MODE": "browser"},
        native_probe=lambda: True,
    )

    assert decision.effective_mode == "headless"
    assert "without display" in decision.reason


def test_invalid_mode_uses_native_first_path() -> None:
    decision = decide_gui_launch(
        Platform.WINDOWS,
        {"LOCALFLIGHT_GUI_MODE": "weird"},
        native_probe=lambda: True,
    )

    assert decision.requested_mode == "native"
    assert decision.effective_mode == "native"


def test_native_first_falls_back_to_browser_when_qt_missing_on_desktop() -> None:
    decision = decide_gui_launch(
        Platform.WINDOWS,
        {},
        native_probe=lambda: False,
    )

    assert decision.requested_mode == "native"
    assert decision.effective_mode == "browser"
    assert "Qt unavailable" in decision.reason
