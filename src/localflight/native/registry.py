"""Native page registry for the PySide6-first shell.

The browser kiosk remains the feature-spec source during the native redesign.
This registry records the native page inventory, the browser page it must cover,
and the local routes each page depends on.  The current shell can use the same
metadata while page implementations continue to move out of the legacy module.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


NavGroup = Literal["primary", "utility", "hidden"]
RefreshPolicy = Literal["live", "manual", "fallback"]


@dataclass(frozen=True)
class NativePageSpec:
    key: str
    title: str
    module: str
    symbol: str
    browser_template: str
    nav_group: NavGroup
    refresh_policy: RefreshPolicy
    required_routes: tuple[str, ...] = ()
    eager: bool = False

    @property
    def nav_visible(self) -> bool:
        return self.nav_group != "hidden"


PAGE_SPECS: tuple[NativePageSpec, ...] = (
    NativePageSpec(
        "display",
        "Display",
        "localflight.native.pages.display",
        "DisplayScreen",
        "display.html",
        "primary",
        "fallback",
        ("/api/fids", "/api/radar", "/api/metar"),
        eager=True,
    ),
    NativePageSpec(
        "fids",
        "FIDS",
        "localflight.native.pages.fids",
        "FidsScreen",
        "fids.html",
        "primary",
        "fallback",
        ("/api/config", "/api/fids", "/api/fids/detail", "/api/metar", "/api/health", "/ws"),
    ),
    NativePageSpec(
        "radar",
        "Radar",
        "localflight.native.pages.radar",
        "RadarScreen",
        "radar.html",
        "primary",
        "fallback",
        ("/api/config", "/api/radar", "/api/radar/surface", "/api/metar"),
    ),
    NativePageSpec(
        "matrix",
        "Matrix",
        "localflight.native.pages.matrix",
        "MatrixScreen",
        "matrix_preview.html",
        "primary",
        "manual",
        (
            "/api/matrix/config",
            "/api/matrix/script",
            "/api/matrix/v2/presets",
            "/api/matrix/v2/configs",
            "/api/matrix/v2/devices",
        ),
    ),
    NativePageSpec(
        "settings",
        "Settings",
        "localflight.native.pages.settings",
        "SettingsScreen",
        "settings.html",
        "utility",
        "manual",
        ("/api/config", "/api/setup/client-info", "/api/airports/search", "/profiles/save"),
    ),
    NativePageSpec(
        "admin",
        "Admin",
        "localflight.native.pages.admin",
        "AdminSummaryScreen",
        "admin.html",
        "utility",
        "manual",
        ("/api/admin/system", "/api/admin/budget", "/api/admin/connections", "/api/admin/scheduler"),
    ),
    NativePageSpec(
        "history",
        "History",
        "localflight.native.pages.history",
        "HistoryScreen",
        "history.html",
        "utility",
        "manual",
        ("/api/history", "/api/history/flight", "/api/history/summary"),
    ),
    NativePageSpec(
        "logs",
        "Logs",
        "localflight.native.pages.logs",
        "LogsScreen",
        "logs.html",
        "utility",
        "manual",
        ("/api/logs", "/logs/tail"),
    ),
    NativePageSpec(
        "requests",
        "Requests",
        "localflight.native.pages.requests",
        "RequestsScreen",
        "requests.html",
        "hidden",
        "manual",
        ("/api/admin/requests",),
    ),
    NativePageSpec(
        "feedback",
        "Report",
        "localflight.native.pages.feedback",
        "FeedbackScreen",
        "feedback.html",
        "utility",
        "manual",
        ("/api/feedback", "/api/feedback/crash", "/api/admin/system", "/api/setup/client-info"),
    ),
)


SETUP_PAGE_SPEC = NativePageSpec(
    "setup",
    "Setup",
    "localflight.native.pages.setup",
    "SetupScreen",
    "setup.html",
    "hidden",
    "manual",
    (
        "/api/setup/client-info",
        "/api/setup/complete",
        "/api/setup/activate",
        "/api/setup/test-activation",
        "/api/setup/test-aviationstack",
        "/api/setup/test-rapidapi",
    ),
)


def page_specs(*, include_hidden: bool = True) -> tuple[NativePageSpec, ...]:
    if include_hidden:
        return PAGE_SPECS
    return tuple(spec for spec in PAGE_SPECS if spec.nav_visible)


def page_spec(key: str) -> NativePageSpec:
    for spec in (*PAGE_SPECS, SETUP_PAGE_SPEC):
        if spec.key == key:
            return spec
    raise KeyError(key)


def browser_parity_templates() -> set[str]:
    return {spec.browser_template for spec in (*PAGE_SPECS, SETUP_PAGE_SPEC)}


def primary_page_keys() -> tuple[str, ...]:
    return tuple(spec.key for spec in PAGE_SPECS if spec.nav_group == "primary")


def fallback_refresh_page_keys() -> set[str]:
    return {spec.key for spec in PAGE_SPECS if spec.refresh_policy == "fallback"}
