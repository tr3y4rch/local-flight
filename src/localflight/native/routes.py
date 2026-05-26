"""Declared native UI routes and action ownership.

The registry keeps native buttons honest: every user/operator action that
touches HTTP is declared with a method, path, label, and surface.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NativeRoute:
    action_id: str
    label: str
    method: str
    path: str
    surface: str
    owner: str


CLIENT_ROUTES: tuple[NativeRoute, ...] = (
    NativeRoute("config.read", "Load settings", "GET", "/api/config", "client", "settings"),
    NativeRoute("config.save", "Save settings", "PATCH", "/api/config", "client", "settings"),
    NativeRoute("airports.search", "Search airports", "GET", "/api/airports/search", "client", "setup"),
    NativeRoute("setup.info", "Load install info", "GET", "/api/setup/client-info", "client", "settings"),
    NativeRoute("setup.complete", "Complete setup", "POST", "/api/setup/complete", "client", "setup"),
    NativeRoute("setup.activate", "Request community activation", "POST", "/api/setup/activate", "client", "setup"),
    NativeRoute("setup.activation_status", "Check activation status", "POST", "/api/setup/client-status", "client", "setup"),
    NativeRoute("setup.test_activation", "Test activation token", "POST", "/api/setup/test-activation", "client", "setup"),
    NativeRoute("setup.test_aerodatabox", "Test AeroDataBox key", "POST", "/api/setup/test-aerodatabox", "client", "setup"),
    NativeRoute("setup.test_aviationstack", "Test AviationStack key", "POST", "/api/setup/test-aviationstack", "client", "setup"),
    NativeRoute("setup.test_rapidapi", "Test RapidAPI key", "POST", "/api/setup/test-rapidapi", "client", "setup"),
    NativeRoute("provider_keys.status", "Read provider key status", "GET", "/api/provider-keys/status", "client", "settings"),
    NativeRoute("provider_keys.save", "Save provider keys", "POST", "/api/provider-keys/save", "client", "settings"),
    NativeRoute("provider_keys.clear", "Clear provider keys", "POST", "/api/provider-keys/clear", "client", "settings"),
    NativeRoute("setup.reset", "Re-run setup wizard", "POST", "/api/setup/reset", "client", "settings"),
    NativeRoute("scheduler.read", "Load scheduler status", "GET", "/api/admin/scheduler", "client", "admin"),
    NativeRoute("scheduler.restart", "Restart scheduler", "POST", "/api/admin/scheduler/restart", "client", "settings"),
    NativeRoute("fids.board", "Load FIDS board", "GET", "/api/fids", "client", "fids"),
    NativeRoute("fids.detail", "Load flight detail", "GET", "/api/fids/detail", "client", "fids"),
    NativeRoute("radar.blips", "Load radar blips", "GET", "/api/radar", "client", "radar"),
    NativeRoute("radar.surface", "Load airport surface", "GET", "/api/radar/surface", "client", "radar"),
    NativeRoute("weather.metar", "Load airport weather", "GET", "/api/metar", "client", "weather"),
    NativeRoute("history.browse", "Load flight history", "GET", "/api/history", "client", "history"),
    NativeRoute("history.flight", "Load callsign history", "GET", "/api/history/flight", "client", "history"),
    NativeRoute("history.summary", "Load history summary", "GET", "/api/history/summary", "client", "history"),
    NativeRoute("history.stats", "Load history stats", "GET", "/api/history/stats", "client", "history"),
    NativeRoute("admin.system", "Load system status", "GET", "/api/admin/system", "client", "admin"),
    NativeRoute("admin.budget", "Load schedule access", "GET", "/api/admin/budget", "client", "admin"),
    NativeRoute("admin.connections", "Load connected screens", "GET", "/api/admin/connections", "client", "admin"),
    NativeRoute("admin.companion_reset", "Reset paired mobile devices", "DELETE", "/api/admin/companion", "client", "settings"),
    NativeRoute("admin.updates", "Load update status", "GET", "/api/admin/updates", "client", "admin"),
    NativeRoute("admin.requests", "Load local request log", "GET", "/api/admin/requests", "client", "requests"),
    NativeRoute("matrix.config_read", "Load matrix config", "GET", "/api/matrix/config", "client", "matrix"),
    NativeRoute("matrix.config_save", "Save matrix config", "POST", "/api/matrix/config", "client", "matrix"),
    NativeRoute("matrix.presets", "Load matrix presets", "GET", "/api/matrix/v2/presets", "client", "matrix"),
    NativeRoute("matrix.configs", "Load matrix configs", "GET", "/api/matrix/v2/configs", "client", "matrix"),
    NativeRoute("matrix.config_update", "Save matrix V2 config", "PATCH", "/api/matrix/v2/configs/{config_id}", "client", "matrix"),
    NativeRoute("matrix.devices", "Load matrix devices", "GET", "/api/matrix/v2/devices", "client", "matrix"),
    NativeRoute("matrix.feed", "Load matrix preview feed", "GET", "/api/matrix/v2/devices/{device_id}/feed", "client", "matrix"),
    NativeRoute("matrix.script", "Generate matrix script", "POST", "/api/matrix/script", "client", "matrix"),
    NativeRoute("logs.list", "Load log files", "GET", "/api/logs", "client", "logs"),
    NativeRoute("logs.tail", "Load log tail", "GET", "/logs/tail", "client", "logs"),
    NativeRoute("feedback.send", "Send report", "POST", "/api/feedback", "client", "feedback"),
    NativeRoute("feedback.crash", "Send native crash report", "POST", "/api/feedback/crash", "client", "feedback"),
    NativeRoute("profile.save", "Save profile", "POST", "/profiles/save", "client", "settings"),
    NativeRoute("profile.load", "Load profile", "POST", "/profiles/load", "client", "settings"),
    NativeRoute("profile.delete", "Delete profile", "POST", "/profiles/delete", "client", "settings"),
    NativeRoute("quit", "Quit Local Flight", "POST", "/api/quit", "client", "shell"),
)


NETWORK_ADMIN_ROUTES: tuple[NativeRoute, ...] = (
    NativeRoute("network.overview", "Load overview", "GET", "/admin/api/overview", "network-admin", "operator"),
    NativeRoute("network.usage", "Load usage", "GET", "/admin/api/usage", "network-admin", "operator"),
    NativeRoute("network.fleet", "Load fleet", "GET", "/admin/api/fleet", "network-admin", "operator"),
    NativeRoute("network.schedules", "Load schedules", "GET", "/admin/api/schedules", "network-admin", "operator"),
    NativeRoute("network.surfaces", "Load surfaces", "GET", "/admin/api/surfaces", "network-admin", "operator"),
    NativeRoute("network.activations", "Load activations", "GET", "/admin/api/activations", "network-admin", "operator"),
    NativeRoute("network.reports", "Load reports", "GET", "/admin/api/reports", "network-admin", "operator"),
    NativeRoute("provider.save", "Save provider keys", "POST", "/admin/api/providers/save", "network-admin", "operator"),
    NativeRoute("provider.clear", "Clear provider key", "POST", "/admin/api/providers/clear", "network-admin", "operator"),
    NativeRoute("activation.create", "Create managed token", "POST", "/admin/api/activation/create", "network-admin", "operator"),
    NativeRoute("activation.token_action", "Run token action", "POST", "/admin/api/activation/token-action", "network-admin", "operator"),
    NativeRoute("activation.request_action", "Run request action", "POST", "/admin/api/activation/request-action", "network-admin", "operator"),
    NativeRoute("counters.reset", "Reset counters", "POST", "/admin/api/counters/reset", "network-admin", "operator"),
    NativeRoute("counters.correct_schedule", "Correct schedule total", "POST", "/admin/api/counters/correct-schedule", "network-admin", "operator"),
    NativeRoute("install.access", "Change install access", "POST", "/admin/api/install/access", "network-admin", "operator"),
    NativeRoute("maintenance.clean_trial", "Clean setup trial state", "POST", "/admin/api/maintenance/clean-trial", "network-admin", "operator"),
)


def client_route_paths() -> set[str]:
    return {route.path for route in CLIENT_ROUTES}


def network_admin_route_paths() -> set[str]:
    return {route.path for route in NETWORK_ADMIN_ROUTES}
