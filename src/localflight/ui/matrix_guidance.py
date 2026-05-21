"""Shared user-facing guidance for Matrix/i75W setup surfaces."""

from __future__ import annotations

MATRIX_GUIDE_STEPS = (
    {
        "title": "1 Choose panel",
        "body": "Pick the HUB75 panel combo you physically wired, or enter a custom size.",
    },
    {
        "title": "2 Tune preview",
        "body": "Rows, brightness, palette, motion, weather, and gate labels update in the preview.",
    },
    {
        "title": "3 Apply live config",
        "body": "Save the board config. A flashed v2 board picks up live settings over Wi-Fi in about a minute.",
    },
    {
        "title": "4 Generate main.py",
        "body": "Regenerate only when Wi-Fi, server address, panel wiring, or board client code changes.",
    },
)

MATRIX_LIVE_SETTINGS = (
    "Board mode",
    "Palette/style",
    "Brightness",
    "Rows shown",
    "Refresh and page rotation",
    "Weather",
    "Gate/stand labels",
    "Status motion and animation speed",
)

MATRIX_REFLASH_SETTINGS = (
    "Wi-Fi network name/password",
    "Local Flight server host/port",
    "Physical panel size or wiring",
    "New board client features",
)

MATRIX_SAFE_NOTES = (
    "The board and Local Flight must be on the same LAN.",
    "Use localflight.local or the server LAN IP. Do not use localhost, 127.0.0.1, or ::1.",
    "Save the generated file to the MicroPython device as main.py in Thonny.",
    "Wi-Fi password is only placed into the generated main.py file and is not saved by the Matrix settings page.",
    "Panel size and wiring are flash-time settings; regenerate main.py after changing them.",
)

MATRIX_ADVANCED_FLOW = (
    "A flashed board checks in at /api/matrix/v2/devices/checkin.",
    "It reads the assigned config from /api/matrix/v2/devices/{id}/config.",
    "It fetches current board rows from /api/matrix/v2/devices/{id}/feed.",
)


def matrix_guidance_payload() -> dict[str, object]:
    return {
        "steps": MATRIX_GUIDE_STEPS,
        "live_settings": MATRIX_LIVE_SETTINGS,
        "reflash_settings": MATRIX_REFLASH_SETTINGS,
        "safe_notes": MATRIX_SAFE_NOTES,
        "advanced_flow": MATRIX_ADVANCED_FLOW,
    }
