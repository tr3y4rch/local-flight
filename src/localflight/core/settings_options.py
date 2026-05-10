"""Shared user-facing settings choices for native Qt and browser UI.

Keep labels, saved values, and preview colors in one place so the native shell
and LAN browser settings page do not drift from each other.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Option:
    value: str
    label: str
    description: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class NumberOption:
    value: int
    label: str
    description: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SkinOption:
    value: str
    label: str
    fg: str
    bg: str
    accent: str
    description: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


THEME_OPTIONS: tuple[Option, ...] = (
    Option("dark", "Dark board", "Low-glare airport-board styling."),
    Option("light", "Light room", "Higher ambient-light contrast."),
)

SOURCE_OPTIONS: tuple[Option, ...] = (
    Option("real", "Real traffic", "AviationStack schedule data plus available enrichment."),
    Option("virtual", "Virtual / VATSIM", "No-key virtual traffic with privacy-safe details."),
)

REFRESH_OPTIONS: tuple[NumberOption, ...] = (
    NumberOption(900, "Every 15 minutes"),
    NumberOption(1800, "Every 30 minutes"),
    NumberOption(2700, "Every 45 minutes"),
    NumberOption(3600, "Every 60 minutes"),
    NumberOption(7200, "Every 2 hours"),
    NumberOption(14400, "Every 4 hours"),
    NumberOption(28800, "Every 8 hours"),
    NumberOption(43200, "Every 12 hours"),
    NumberOption(86400, "Every 24 hours"),
)

SKIN_OPTIONS: tuple[SkinOption, ...] = (
    SkinOption("standard", "Standard", "#e8f0fe", "#0d1520", "#4a9eda", "Balanced Local Flight blue."),
    SkinOption("pax_blue", "PAX blue", "#d9f4ff", "#071829", "#1d8cff", "Bright terminal display blue."),
    SkinOption("solari_amber", "Solari amber", "#fff0bf", "#201000", "#ffad2f", "Split-flap amber board."),
    SkinOption("tower_scope", "Tower scope", "#dfffe8", "#06170d", "#38ff75", "Radar-room green."),
    SkinOption("vatsim_scope", "VATSIM scope", "#e4ffe0", "#07130b", "#74ff5f", "Virtual-network scope green."),
    SkinOption("night_ops", "Night ops", "#d8f3ff", "#07111f", "#4bb8ff", "Dim blue night operations."),
    SkinOption("sunset_terminal", "Sunset terminal", "#ffe8d8", "#20100b", "#ff7a3d", "Warm evening display."),
    SkinOption("ice_white", "Ice white", "#0c2433", "#f5fbff", "#1688bf", "Clean high-contrast light skin."),
    SkinOption("technical", "Technical", "#c8d8e8", "#0a0e14", "#7ab0d8", "Dense technical cockpit feel."),
    SkinOption("cyan", "Cyan", "#d8fbff", "#00080f", "#3ddcff", "Cool ops-center cyan."),
    SkinOption("crt", "CRT", "#fff2bc", "#0a0600", "#ffae2e", "Old amber monitor glow."),
    SkinOption("neon", "Neon", "#d8ffd8", "#000d00", "#00f5ff", "Loud beta-lab neon."),
)

OUTPUT_OPTIONS: tuple[Option, ...] = (
    Option("web", "LAN browser UI", "Serve the fallback browser UI on this network."),
    Option("matrix", "Matrix panel", "Interstate 75 W LED panel over WiFi."),
    Option("hdmi", "HDMI display", "Dedicated attached display output."),
)

DIAGNOSTICS_OPTIONS: tuple[Option, ...] = (
    Option("unset", "Ask on setup", "No automatic diagnostics choice has been saved yet."),
    Option("manual", "Manual reports only", "Nothing is sent unless you submit a report."),
    Option("auto", "Auto crash reports", "Send sanitized exception details for crashes."),
    Option("auto_logs", "Auto crash reports + logs", "Also attach a short sanitized local log tail."),
)

WEB_ROW_OPTIONS: tuple[NumberOption, ...] = (
    NumberOption(10, "10 visible rows"),
    NumberOption(12, "12 visible rows"),
    NumberOption(16, "16 visible rows"),
    NumberOption(20, "20 visible rows"),
    NumberOption(24, "24 visible rows"),
    NumberOption(28, "28 visible rows"),
    NumberOption(32, "32 visible rows"),
)

WEB_ROTATION_OPTIONS: tuple[NumberOption, ...] = (
    NumberOption(4, "Every 4 seconds"),
    NumberOption(6, "Every 6 seconds"),
    NumberOption(8, "Every 8 seconds"),
    NumberOption(10, "Every 10 seconds"),
    NumberOption(12, "Every 12 seconds"),
    NumberOption(15, "Every 15 seconds"),
)

GRACE_OPTIONS: tuple[NumberOption, ...] = (
    NumberOption(0, "Hide immediately"),
    NumberOption(15, "15 minutes"),
    NumberOption(30, "30 minutes"),
    NumberOption(60, "60 minutes"),
    NumberOption(90, "90 minutes"),
)

HORIZON_OPTIONS: tuple[NumberOption, ...] = (
    NumberOption(6, "6 hours"),
    NumberOption(12, "12 hours"),
    NumberOption(18, "18 hours"),
    NumberOption(24, "24 hours"),
)

SKIN_IDS = tuple(option.value for option in SKIN_OPTIONS)
THEME_IDS = tuple(option.value for option in THEME_OPTIONS)
SOURCE_IDS = tuple(option.value for option in SOURCE_OPTIONS)
OUTPUT_IDS = tuple(option.value for option in OUTPUT_OPTIONS)
DIAGNOSTICS_IDS = tuple(option.value for option in DIAGNOSTICS_OPTIONS)
REFRESH_SECONDS = tuple(option.value for option in REFRESH_OPTIONS)


def option_label(options: tuple[Option, ...] | tuple[NumberOption, ...] | tuple[SkinOption, ...], value: Any) -> str:
    clean = str(value)
    for option in options:
        if str(option.value) == clean:
            return option.label
    return clean


def settings_options_context() -> dict[str, list[dict[str, Any]]]:
    """Return template-friendly option data."""
    return {
        "themes": [option.as_dict() for option in THEME_OPTIONS],
        "sources": [option.as_dict() for option in SOURCE_OPTIONS],
        "refresh": [option.as_dict() for option in REFRESH_OPTIONS],
        "skins": [option.as_dict() for option in SKIN_OPTIONS],
        "outputs": [option.as_dict() for option in OUTPUT_OPTIONS],
        "diagnostics": [option.as_dict() for option in DIAGNOSTICS_OPTIONS],
        "web_rows": [option.as_dict() for option in WEB_ROW_OPTIONS],
        "web_rotation": [option.as_dict() for option in WEB_ROTATION_OPTIONS],
        "grace": [option.as_dict() for option in GRACE_OPTIONS],
        "horizon": [option.as_dict() for option in HORIZON_OPTIONS],
    }

