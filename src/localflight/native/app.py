"""Public facade for the native Local Flight UI.

The native UI started as one large prototype module. Keep this file stable and
small while implementation moves into focused modules by runtime cost.
"""
from __future__ import annotations

import sys
import traceback as traceback_module
import webbrowser
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from localflight.native.api_client import LocalApiClient
from localflight.native.async_tools import API_EXECUTOR
from localflight.native.live import NativeLiveBus, event_refresh_targets, native_ws_url
from localflight.native.models import FlightBoardModel, HistoryModel, RequestLogModel
from localflight.native.canvas.radar import RadarCanvas
from localflight.native.pages.fids import FidsScreen
from localflight.native.pages.radar import RadarScreen
from localflight.native.pages.setup import NativeSetupWindow, SetupScreen
from localflight.native.pages.settings import SettingsScreen
from localflight.native.qt_compat import import_qt
from localflight.native.registry import PAGE_SPECS, SETUP_PAGE_SPEC, NativePageSpec
from localflight.native.service import NativeApiService
from localflight.native.widgets import AirportSearchBox, DetailDrawer, StatusCard, WeatherStrip

_LEGACY_EXPORTS = {
    "AdminSummaryScreen",
    "COFFEE_URL",
    "DisplayScreen",
    "FeedbackScreen",
    "GITHUB_URL",
    "HistoryScreen",
    "LogsScreen",
    "MatrixCanvas",
    "MatrixScreen",
    "NativeMainWindow",
    "RequestsScreen",
    "_NativeCrashReporter",
    "_active_schedule_budget",
    "_budget_detail",
    "_budget_label",
    "_weather_icon_glyph",
    "_weather_line",
    "webbrowser",
}

__all__ = [
    "LocalApiClient",
    "NativeApiService",
    "NativeLiveBus",
    "NativePageSpec",
    "PAGE_SPECS",
    "SETUP_PAGE_SPEC",
    "FlightBoardModel",
    "FidsScreen",
    "RadarCanvas",
    "RadarScreen",
    "SettingsScreen",
    "NativeSetupWindow",
    "SetupScreen",
    "HistoryModel",
    "RequestLogModel",
    "StatusCard",
    "WeatherStrip",
    "DetailDrawer",
    "AirportSearchBox",
    "event_refresh_targets",
    "native_ws_url",
    "is_native_available",
    "launch_native_app",
    "main",
    "_app_version",
    *_LEGACY_EXPORTS,
]


def is_native_available() -> bool:
    """Return whether Qt can be imported without loading the full native shell."""
    try:
        import_qt()
    except Exception:
        return False
    return True


def launch_native_app(*, base_url: str, first_launch: bool, fullscreen: bool = False) -> int:
    from localflight.native.bootstrap import launch_native_app as _launch_native_app

    return _launch_native_app(base_url=base_url, first_launch=first_launch, fullscreen=fullscreen)


def main() -> None:
    from localflight.native.bootstrap import main as _main

    _main()


def _app_version() -> str:
    try:
        return version("localflight")
    except PackageNotFoundError:
        return "0.2.7"


class _NativeCrashReporter:
    """Route native UI exceptions through the local feedback API.

    This facade copy keeps test and monkeypatch compatibility while the
    compatibility launch path is being split behind ``bootstrap``.
    """

    def __init__(self, base_url: str, *, screen_provider: Any | None = None) -> None:
        self.base_url = base_url
        self.screen_provider = screen_provider
        self._installed = False
        self._reporting = False

    def install(self) -> None:
        if self._installed:
            return
        self._installed = True

        def _native_excepthook(exc_type: type[BaseException], exc_value: BaseException, exc_tb: Any) -> None:
            self.report_exception(exc_type, exc_value, exc_tb, sync=True)
            sys.__excepthook__(exc_type, exc_value, exc_tb)

        sys.excepthook = _native_excepthook

    def report_exception(
        self,
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: Any,
        *,
        sync: bool = False,
    ) -> None:
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)) or self._reporting:
            return
        message = f"{exc_type.__name__}: {exc_value}"[:500]
        traceback_str = "".join(traceback_module.format_exception(exc_type, exc_value, exc_tb))[-5000:]
        if sync:
            self._send(message, traceback_str)
        else:
            API_EXECUTOR.submit(self._send, message, traceback_str)

    def _screen(self) -> str:
        try:
            return (self.screen_provider() if self.screen_provider else "native") or "native"
        except Exception:
            return "native"

    def _client_context(self, client: LocalApiClient) -> str:
        parts = [
            "native/gui",
            f"screen={self._screen()}",
            f"app_version={_app_version()}",
            "route=/api/feedback/crash",
            "owner=client",
        ]
        try:
            cfg = client.get_json("/api/config")
            if cfg.get("source"):
                parts.append(f"source={cfg.get('source')}")
            airport = cfg.get("airport_iata") or cfg.get("airport_icao")
            if airport:
                parts.append(f"airport={airport}")
        except Exception:
            pass
        return "; ".join(parts)

    def _send(self, message: str, traceback_str: str) -> None:
        self._reporting = True
        try:
            client = LocalApiClient(base_url=self.base_url, timeout_s=6.0)
            client.post_json(
                "/api/feedback/crash",
                {
                    "message": message,
                    "traceback": traceback_str,
                    "context": "native/gui",
                    "client_context": self._client_context(client),
                },
            )
        except Exception:
            pass
        finally:
            self._reporting = False


def _compat_module() -> Any:
    return import_module("localflight.native._legacy_app")


def __getattr__(name: str) -> Any:
    if name in _LEGACY_EXPORTS:
        return getattr(_compat_module(), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
