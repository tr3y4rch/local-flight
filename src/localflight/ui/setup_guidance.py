"""Shared first-run setup guidance for native Qt and LAN/browser UI."""
from __future__ import annotations

from typing import Any


STEP_NAMES: tuple[str, ...] = (
    "Welcome",
    "Airport",
    "Flight Data",
    "Optional Keys",
    "Diagnostics",
    "Review & Launch",
)

STEP_SHORT_LABELS: tuple[str, ...] = (
    "Welcome",
    "Airport",
    "Data",
    "Keys",
    "Reports",
    "Launch",
)

WELCOME_CARDS: tuple[dict[str, str], ...] = (
    {
        "icon": "\U0001F4FA",  # 📺
        "title": "Runs on this device",
        "body": "Local Flight starts on this computer or Pi. The LAN browser view stays available for phones, tablets, and extra screens.",
    },
    {
        "icon": "\U0001F4E1",  # 📡
        "title": "Choose a data source",
        "body": "Use Beacon Relay with Relay Access, bring your own provider keys, or choose VATSIM virtual traffic.",
    },
    {
        "icon": "\U0001F510",  # 🔐
        "title": "Private by choice",
        "body": "Keys stay masked, Relay Access device credentials stay local, and diagnostics stay opt-in before first launch.",
    },
)

SOURCE_OPTIONS: tuple[dict[str, str], ...] = (
    {
        "mode": "relay",
        "title": "Beacon Relay",
        "short_title": "Relay",
        "icon": "\U0001F4E1",  # 📡
        "body": "Hosted real-flight data from Beacon Tools. Relay Access is a one-time purchase with no subscription. It can be active on one desktop or one phone in Standalone mode.",
        "note": "Beacon Relay is selected. Get Relay Access or enter an existing key or one-time activation code.",
        "finish_label": "Beacon Relay",
    },
    {
        "mode": "byok",
        "title": "Bring Your Own Keys",
        "short_title": "BYOK",
        "icon": "\U0001F511",  # 🔑
        "body": "Use your own supported provider keys on this device. Your provider account and usage limits apply.",
        "note": "Use your own keys is selected. The next step collects AeroDataBox or AviationStack for schedules, plus optional ADS-B Exchange radar.",
        "finish_label": "Your own provider keys",
    },
    {
        "mode": "vatsim",
        "title": "VATSIM",
        "short_title": "VATSIM",
        "icon": "\U0001F6E9",  # 🛩
        "body": "Use virtual VATSIM traffic. No Relay Access or real-flight provider keys are needed.",
        "note": "VATSIM only is selected. Local Flight skips real-flight provider keys and uses virtual-network traffic only.",
        "finish_label": "VATSIM",
    },
)

DIAGNOSTICS_OPTIONS: tuple[dict[str, str], ...] = (
    {
        "mode": "manual",
        "title": "Manual reports only",
        "short_title": "Manual",
        "icon": "✋",  # ✋
        "body": "Nothing is sent unless you submit a report from the Report screen.",
        "note": "Manual only is the privacy-first option. Nothing is sent unless you submit a report yourself.",
    },
    {
        "mode": "auto",
        "title": "Automatic crash reports",
        "short_title": "Auto crashes",
        "icon": "\U0001F4A5",  # 💥
        "body": "Send sanitized crash details only when something breaks.",
        "note": "Automatic crash reports send sanitized exception details only when diagnostics allow it.",
    },
    {
        "mode": "auto_logs",
        "title": "Automatic crash reports + local logs",
        "short_title": "Auto + logs",
        "icon": "\U0001F4DC",  # 📜
        "body": "Also attach a short local log tail to help with harder issues.",
        "note": "Automatic crash reports + local logs can make troubleshooting easier. Reports stay sanitized and include only a short local log tail.",
    },
)

PROVIDER_LINKS: tuple[dict[str, str], ...] = (
    {"label": "AeroDataBox docs", "url": "https://doc.aerodatabox.com/"},
    {"label": "Get AviationStack key", "url": "https://aviationstack.com/signup"},
    {"label": "ADS-B Exchange on RapidAPI", "url": "https://rapidapi.com/adsbx/api/adsbexchange-com1"},
    {"label": "OpenSky account", "url": "https://opensky-network.org/login?view=registration"},
    {"label": "VATSIM status", "url": "https://network-status.vatsim.net/"},
)


def source_option(mode: str) -> dict[str, str]:
    for option in SOURCE_OPTIONS:
        if option["mode"] == mode:
            return option
    return SOURCE_OPTIONS[0]


def diagnostics_option(mode: str) -> dict[str, str]:
    for option in DIAGNOSTICS_OPTIONS:
        if option["mode"] == mode:
            return option
    return DIAGNOSTICS_OPTIONS[0]


def guidance_context() -> dict[str, Any]:
    """Return template-friendly setup guidance."""
    return {
        "step_names": STEP_NAMES,
        "step_short_labels": STEP_SHORT_LABELS,
        "welcome_cards": WELCOME_CARDS,
        "source_options": SOURCE_OPTIONS,
        "diagnostics_options": DIAGNOSTICS_OPTIONS,
        "provider_links": PROVIDER_LINKS,
    }
