"""Shared first-run setup guidance for native Qt and LAN/browser UI.

Everything a person reads in the setup wizard lives here once: step names,
headings, card copy, button labels, summary labels, and the icon set. The
native Qt wizard and the browser ``/setup`` page both render from this module
so their wording and icons stay identical.
"""
from __future__ import annotations

from typing import Any


STEP_NAMES: tuple[str, ...] = (
    "Welcome",
    "Airport",
    "Flight data",
    "Provider keys",
    "Problem reports",
    "Review and open",
)

STEP_SHORT_LABELS: tuple[str, ...] = (
    "Welcome",
    "Airport",
    "Data",
    "Keys",
    "Reports",
    "Finish",
)

# Heading and one-line lede for each step, shared by both wizards.
STEP_COPY: tuple[dict[str, str], ...] = (
    {
        "heading": "Welcome to Local Flight",
        "lede": "A short first-launch setup: pick your airport, choose where flight data comes from, and decide how problem reports work. You can change everything later in Settings.",
    },
    {
        "heading": "Choose your airport",
        "lede": "Search by city, airport name, or code. Pick a result and the codes and time zone are filled in for you.",
    },
    {
        "heading": "Choose where flight data comes from",
        "lede": "Beacon Relay, your own provider keys, or VATSIM virtual traffic.",
    },
    {
        "heading": "Add your provider keys",
        "lede": "Only needed for Bring Your Own Keys. Keys stay on this device and go only to the provider you chose.",
    },
    {
        "heading": "Choose how problems are reported",
        "lede": "Manual reports are always available. Automatic reports are optional and never include keys or identities.",
    },
    {
        "heading": "Review and open",
        "lede": "Check your choices. Finishing saves them on this device and opens Local Flight.",
    },
)

BUTTON_LABELS: dict[str, str] = {
    "start": "Start setup",
    "back": "Back",
    "next": "Continue",
    "finish": "Open Local Flight",
    "skip_keys": "Skip for now",
    "browser": "Open in browser",
}

# Tagline under the welcome hero.
WELCOME_TAGLINE = "Your airport board, on a screen you own."

WELCOME_CARDS: tuple[dict[str, str], ...] = (
    {
        "icon": "screen",
        "title": "Runs on this device",
        "body": "Local Flight runs on this computer or Pi. Phones, tablets, and extra screens on your network can open the same board.",
    },
    {
        "icon": "antenna",
        "title": "Choose a data source",
        "body": "Use Beacon Relay, bring your own provider keys, or follow VATSIM virtual traffic.",
    },
    {
        "icon": "shield",
        "title": "Private by choice",
        "body": "Keys stay on this device, Relay Access credentials stay local, and problem reports are opt-in.",
    },
)

SOURCE_OPTIONS: tuple[dict[str, str], ...] = (
    {
        "mode": "relay",
        "title": "Beacon Relay",
        "short_title": "Relay",
        "icon": "antenna",
        "body": "Hosted real-flight schedules and Remote Companion from Beacon Tools. One Relay Access subscription covers one main device.",
        "note": "Beacon Relay is selected. Get Relay Access, or enter an existing key or one-time activation code.",
        "finish_label": "Beacon Relay",
    },
    {
        "mode": "byok",
        "title": "Bring Your Own Keys",
        "short_title": "BYOK",
        "icon": "key",
        "body": "Use your own aviation-data accounts. Keys stay on this device and go only to the provider you chose.",
        "note": "Bring Your Own Keys is selected. Add an AeroDataBox or AviationStack key on the next step. Radar keys are optional.",
        "finish_label": "Your own provider keys",
    },
    {
        "mode": "vatsim",
        "title": "VATSIM",
        "short_title": "VATSIM",
        "icon": "plane",
        "body": "Follow virtual VATSIM traffic. No Relay Access or provider keys needed.",
        "note": "VATSIM is selected. Local Flight skips provider keys and shows virtual-network traffic only.",
        "finish_label": "VATSIM",
    },
)

DIAGNOSTICS_OPTIONS: tuple[dict[str, str], ...] = (
    {
        "mode": "manual",
        "title": "Manual reports only",
        "short_title": "Manual",
        "icon": "chat",
        "body": "Nothing is sent unless you submit a report from the Report screen.",
        "note": "Manual reports only. Nothing leaves this device unless you send a report yourself.",
    },
    {
        "mode": "auto",
        "title": "Automatic crash reports",
        "short_title": "Auto crashes",
        "icon": "bolt",
        "body": "Send a cleaned crash summary when something breaks.",
        "note": "Automatic crash reports send a cleaned crash summary only when something breaks.",
    },
    {
        "mode": "auto_logs",
        "title": "Automatic crash reports + local logs",
        "short_title": "Auto + logs",
        "icon": "list",
        "body": "Also attach a short cleaned log excerpt to help with harder problems.",
        "note": "Automatic crash reports with logs attach a short cleaned log excerpt. Keys and identities are never included.",
    },
)

PROVIDER_LINKS: tuple[dict[str, str], ...] = (
    {"label": "AeroDataBox docs", "url": "https://doc.aerodatabox.com/"},
    {"label": "Get AviationStack key", "url": "https://aviationstack.com/signup"},
    {"label": "ADS-B Exchange on RapidAPI", "url": "https://rapidapi.com/adsbx/api/adsbexchange-com1"},
    {"label": "OpenSky account", "url": "https://opensky-network.org/login?view=registration"},
    {"label": "VATSIM status", "url": "https://network-status.vatsim.net/"},
)

# Provider key fields, grouped so both wizards lay them out the same way.
PROVIDER_KEY_GROUPS: tuple[dict[str, Any], ...] = (
    {
        "id": "schedules",
        "title": "Schedules",
        "lede": "One schedule key is enough. Adding both lets one fill gaps in the other.",
        "fields": (
            {"id": "aerodatabox_key", "label": "AeroDataBox key", "help": "Recommended schedule source. Used first when both keys are present.", "secret": True},
            {"id": "aerodatabox_marketplace", "label": "AeroDataBox marketplace", "help": "Where you bought the AeroDataBox plan.", "secret": False},
            {"id": "aerodatabox_monthly_limit", "label": "Monthly request limit", "help": "Local Flight stops calling AeroDataBox for the month once this many units are used, so a plan cannot be overrun.", "secret": False},
            {"id": "aviationstack_key", "label": "AviationStack key", "help": "Works alone or as a fallback for AeroDataBox.", "secret": True},
        ),
    },
    {
        "id": "radar",
        "title": "Radar (optional)",
        "lede": "Live aircraft positions around the airport.",
        "fields": (
            {"id": "rapidapi_key", "label": "ADS-B Exchange key", "help": "RapidAPI key for ADS-B Exchange. Optional.", "secret": True},
            {"id": "opensky_id", "label": "OpenSky client ID", "help": "Optional fallback for positions when ADS-B Exchange is unavailable.", "secret": False},
            {"id": "opensky_secret", "label": "OpenSky client secret", "help": "Pairs with the OpenSky client ID. Stored on this device only.", "secret": True},
        ),
    },
)

SUMMARY_LABELS: dict[str, str] = {
    "airport": "Airport",
    "timezone": "Time zone",
    "source": "Flight data",
    "relay": "Relay Access",
    "keys": "Provider keys",
    "diagnostics": "Problem reports",
}

SUMMARY_VALUES: dict[str, str] = {
    "relay_active": "Active on this desktop",
    "relay_required": "Activation needed",
    "relay_not_used": "Not used",
    "keys_none": "No provider keys saved",
}

# Monochrome line icons shared by both wizards. Each entry is the inner SVG
# markup for a 24x24 viewBox drawn with the current colour.
ICONS: dict[str, str] = {
    "screen": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    "antenna": '<circle cx="12" cy="11" r="2"/><path d="M8.5 14.5a5 5 0 0 1 0-7M15.5 7.5a5 5 0 0 1 0 7M5.6 17.4a9 9 0 0 1 0-12.8M18.4 4.6a9 9 0 0 1 0 12.8M12 13v8"/>',
    "shield": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "key": '<circle cx="7.5" cy="15.5" r="3.5"/><path d="M10 13l9-9M14.5 8.5l3 3M17 6l3 3"/>',
    "plane": '<path d="M21 13l-7-2.2V5a2 2 0 0 0-4 0v5.8L3 13v2l7-1.4V18l-2.5 1.5V21l4.5-1 4.5 1v-1.5L14 18v-4.4l7 1.4z" fill="currentColor" stroke="none"/>',
    "chat": '<path d="M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H9l-5 4z"/>',
    "bolt": '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01"/>',
    "eye": '<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "eye_off": '<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12z"/><circle cx="12" cy="12" r="3"/><path d="M4 4l16 16"/>',
    "arrow_left": '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    "arrow_right": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "takeoff": '<path d="M2.5 20h19"/><path d="M3.2 13.6l4.1 1.1 11.4-3.1a2 2 0 0 0 1.4-2.4 2 2 0 0 0-2.5-1.4l-3.3.9-6.8-3.7-2 .5 4.5 4.6-4.1 1.1-2.4-1.6-1.6.4z" fill="currentColor" stroke="none"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    "external": '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    "flask": '<path d="M9 3h6M10 3v6l-5.5 9a2 2 0 0 0 1.7 3h11.6a2 2 0 0 0 1.7-3L14 9V3"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.3-4.3"/>',
    "tower": '<path d="M9 21h6M12 21v-6M6 8h12l-1.5 7h-9zM12 3v5M8 5h8"/>',
    "pin": '<path d="M12 21s7-6.5 7-11.5a7 7 0 0 0-14 0C5 14.5 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/>',
    "refresh": '<path d="M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "sparkle": '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>',
}

ICON_NAMES: tuple[str, ...] = tuple(ICONS)


def icon_svg(name: str, *, color: str = "currentColor", size: int = 24, stroke_width: float = 1.8) -> str:
    """Return a complete SVG document for one shared icon.

    ``color`` may stay ``currentColor`` for inline HTML, or be a hex value
    when the SVG is rasterized by Qt, which does not resolve ``currentColor``.
    """
    body = ICONS.get(name) or ICONS["info"]
    if color != "currentColor":
        body = body.replace("currentColor", color)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="{size}" height="{size}" '
        f'fill="none" stroke="{color}" stroke-width="{stroke_width}" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true" focusable="false">{body}</svg>'
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
        "step_copy": STEP_COPY,
        "buttons": BUTTON_LABELS,
        "welcome_tagline": WELCOME_TAGLINE,
        "welcome_cards": WELCOME_CARDS,
        "source_options": SOURCE_OPTIONS,
        "diagnostics_options": DIAGNOSTICS_OPTIONS,
        "provider_links": PROVIDER_LINKS,
        "provider_key_groups": PROVIDER_KEY_GROUPS,
        "summary_labels": SUMMARY_LABELS,
        "summary_values": SUMMARY_VALUES,
        "icons": {name: icon_svg(name) for name in ICONS},
    }
