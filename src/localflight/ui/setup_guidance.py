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
        "icon": "Board",
        "title": "Local first",
        "body": "Your airport board runs from this machine. The LAN browser interface stays available for phones, tablets, and other screens.",
    },
    {
        "icon": "Data",
        "title": "Pick your data path",
        "body": "Start with hosted community access, use your own provider keys, or run VATSIM-only virtual traffic.",
    },
    {
        "icon": "Privacy",
        "title": "Private by design",
        "body": "Keys stay masked, tokens stay local, and diagnostics are an explicit choice before first launch.",
    },
)

SOURCE_OPTIONS: tuple[dict[str, str], ...] = (
    {
        "mode": "community",
        "title": "Community Relay",
        "short_title": "Community",
        "icon": "Relay",
        "body": "Recommended first run. Uses shared real-flight snapshots through the hosted relay without personal schedule keys.",
        "note": "Community Relay is selected. Local Flight keeps this client keyless and uses the shared schedule allowance for this install.",
        "finish_label": "Community real-flight path",
    },
    {
        "mode": "byok",
        "title": "Bring Your Own Keys",
        "short_title": "BYOK",
        "icon": "Keys",
        "body": "Use direct provider accounts when you want quota ownership and your own real-data keys on this machine.",
        "note": "Bring Your Own Keys is selected. The next step collects AviationStack and optional radar/enrichment keys.",
        "finish_label": "Direct provider keys",
    },
    {
        "mode": "virtual",
        "title": "Virtual / VATSIM",
        "short_title": "VATSIM",
        "icon": "VATSIM",
        "body": "No real-data keys. Good for simulator traffic, testing, or a quick privacy-first first launch.",
        "note": "VATSIM is selected. Local Flight skips real-data keys and uses privacy-safe virtual network data.",
        "finish_label": "VATSIM virtual traffic",
    },
)

DIAGNOSTICS_OPTIONS: tuple[dict[str, str], ...] = (
    {
        "mode": "manual",
        "title": "Manual reports only",
        "short_title": "Manual",
        "icon": "Manual",
        "body": "Nothing is sent unless you submit a report from the Report screen.",
        "note": "Manual mode is privacy-first: reports are sent only when you press Submit in the Report screen.",
    },
    {
        "mode": "auto",
        "title": "Auto crash reports",
        "short_title": "Auto crashes",
        "icon": "Crash",
        "body": "Send sanitized native/server crash details when something breaks.",
        "note": "Auto crash reports send sanitized exception details only when diagnostics allow it.",
    },
    {
        "mode": "auto_logs",
        "title": "Auto + local logs",
        "short_title": "Auto + logs",
        "icon": "Logs",
        "body": "Also attach a short local log tail for harder beta issues.",
        "note": "Auto + logs is helpful during beta testing. Reports stay sanitized and include only a short local log tail.",
    },
)

PROVIDER_LINKS: tuple[dict[str, str], ...] = (
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
