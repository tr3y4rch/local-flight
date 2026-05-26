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
        "body": "Start with the Local Flight relay, use your own provider keys, or choose VATSIM-only virtual traffic.",
    },
    {
        "icon": "\U0001F510",  # 🔐
        "title": "Private by choice",
        "body": "Keys stay masked, relay tokens stay local, and diagnostics stay opt-in before first launch.",
    },
)

SOURCE_OPTIONS: tuple[dict[str, str], ...] = (
    {
        "mode": "community",
        "title": "Local Flight Relay",
        "short_title": "Community",
        "icon": "\U0001F4E1",  # 📡
        "body": "Recommended first run. Uses the hosted Local Flight relay for real-flight boards without asking you to paste personal schedule keys into this setup.",
        "note": "The Local Flight relay is selected. This device stays key-free during setup and uses the shared relay allowance for board refreshes.",
        "finish_label": "Local Flight relay",
    },
    {
        "mode": "byok",
        "title": "Use Your Own Keys",
        "short_title": "BYOK",
        "icon": "\U0001F511",  # 🔑
        "body": "Use your own provider accounts when you want your own quotas and direct real-data keys on this device.",
        "note": "Use your own keys is selected. The next step collects AeroDataBox or AviationStack for schedules, plus optional ADS-B Exchange radar.",
        "finish_label": "Your own provider keys",
    },
    {
        "mode": "virtual",
        "title": "VATSIM Only",
        "short_title": "VATSIM",
        "icon": "\U0001F6E9",  # 🛩
        "body": "No real-flight provider keys. Good for simulator traffic, testing, or a privacy-first first launch.",
        "note": "VATSIM only is selected. Local Flight skips real-flight provider keys and uses virtual-network traffic only.",
        "finish_label": "VATSIM only",
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
        "note": "Automatic crash reports + local logs is helpful during beta testing. Reports stay sanitized and include only a short local log tail.",
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
