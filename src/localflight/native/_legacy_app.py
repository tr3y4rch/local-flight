"""Legacy monolithic Native Local Flight user UI.

This shell is a Qt Widgets rebuild of the browser/kiosk experience. It keeps
the same local FastAPI contracts as the web UI, but does not embed a webview.

This module is intentionally private while the native UI is split into smaller
runtime-cost modules. Public imports should go through localflight.native.app.
"""
from __future__ import annotations

import math
import json
import os
import re
import sys
import time
import traceback as traceback_module
import unicodedata
import webbrowser
from concurrent.futures import Future
from datetime import datetime, timezone
from html import escape as html_escape
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Callable
from zoneinfo import ZoneInfo

from localflight.native.api_client import LocalApiClient, NativeApiError
from localflight.native.async_tools import API_EXECUTOR as _API_EXECUTOR
from localflight.native.async_tools import LOG as _LOG
from localflight.native.async_tools import AsyncFetchMixin as _AsyncFetchMixin
from localflight.native.design import (
    COLORS,
    NAV_GLYPHS,
    bar_summary,
    bundled_doc,
    card,
    clear_layout,
    colors_for,
    format_value,
    icon_from_media,
    label,
    list_payload,
    apply_app_font_defaults,
    native_stylesheet,
    panel,
    pill,
    pixmap_from_media,
    preview_card,
    progress_card,
    scroll_page,
    section_label,
    set_table_rows,
    table,
    value_at,
)
from localflight.native.geometry import default_display_mode, fitted_window_size, native_visual_density
from localflight.native.identity import configure_qt_app_identity, localflight_app_icon
from localflight.native.loader import lazy_symbol
from localflight.native.live import LiveStatus, NativeLiveBus, native_ws_url
from localflight.native.qt_compat import import_qt
from localflight.native.registry import PAGE_SPECS, NativePageSpec, fallback_refresh_page_keys
from localflight.native.service import NativeApiService
from localflight.storage.profiles import list_profiles
from localflight.ui.matrix_guidance import (
    MATRIX_ADVANCED_FLOW,
    MATRIX_GUIDE_STEPS,
    MATRIX_LIVE_SETTINGS,
    MATRIX_REFLASH_SETTINGS,
    MATRIX_SAFE_NOTES,
)

COFFEE_URL = "https://buymeacoffee.com/localflight"
GITHUB_URL = "https://github.com/tr3y4rch/local-flight"


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _native_ws_url(base_url: str) -> str:
    return native_ws_url(base_url)


def _css_rgba(hex_color: str, alpha: float) -> str:
    value = str(hex_color or "").lstrip("#")
    if len(value) != 6:
        return f"rgba(74,158,218,{alpha:.2f})"
    try:
        r = int(value[0:2], 16)
        g = int(value[2:4], 16)
        b = int(value[4:6], 16)
    except ValueError:
        return f"rgba(74,158,218,{alpha:.2f})"
    return f"rgba({r},{g},{b},{alpha:.2f})"


def _detail_css(colors: dict[str, str]) -> str:
    """Theme-aware CSS for QTextEdit/QTextBrowser rich detail panels."""
    is_light = str(colors.get("bg", "")).lower() == "#f4f7fb"
    divider = "rgba(0,0,0,.08)" if is_light else "rgba(255,255,255,.045)"
    card_bg = _css_rgba(colors.get("blue", "#4a9eda"), 0.10 if is_light else 0.08)
    card_border = _css_rgba(colors.get("blue", "#4a9eda"), 0.28 if is_light else 0.22)
    return (
        "<style>"
        f"body{{font-family:'DM Sans','Segoe UI','Helvetica Neue',sans-serif;color:{colors['text']};background:{colors['panel_2']};}}"
        f".section{{margin:0 0 16px 0;padding:0 0 12px 0;border-bottom:1px solid {divider};}}"
        f".label{{font:700 10px 'Space Mono','Consolas',monospace;letter-spacing:.12em;text-transform:uppercase;color:{colors['dim']};margin:0 0 9px 0;}}"
        f".row{{display:flex;justify-content:space-between;gap:14px;padding:5px 0;border-bottom:1px solid {divider};}}"
        ".row:last-child{border-bottom:0;}"
        f".key{{color:{colors['muted']};}}"
        f".val{{color:{colors['text']};font-weight:700;text-align:right;}}"
        ".cards{display:grid;grid-template-columns:1fr 1fr;gap:8px;}"
        f".card{{border:1px solid {card_border};background:{card_bg};border-radius:10px;padding:10px;}}"
        ".card .key{font:700 10px 'Space Mono','Consolas',monospace;text-transform:uppercase;letter-spacing:.08em;}"
        ".history{display:flex;justify-content:space-between;gap:12px;padding:6px 0;}"
        f".good{{color:{colors['green']}}}.warn{{color:{colors['amber']}}}.bad{{color:{colors['red']}}}.muted{{color:{colors['muted']}}}"
        "</style>"
    )


def main() -> None:
    try:
        code = launch_native_app(base_url="http://127.0.0.1:8000", first_launch=False)
    except Exception as exc:
        print(f"Local Flight native UI unavailable: {exc}", file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(code)


def is_native_available() -> bool:
    try:
        import_qt()
        return True
    except Exception:
        return False


def _app_version() -> str:
    try:
        return version("localflight")
    except PackageNotFoundError:
        return "0.2.7"


def _as_widget(screen: Any) -> Any:
    return getattr(screen, "widget", screen)


def _build_splash(QtCore: Any, QtGui: Any, QtWidgets: Any) -> Any:
    splash = QtWidgets.QFrame()
    splash.setObjectName("NativeSplash")
    splash.setWindowFlag(QtCore.Qt.FramelessWindowHint, True)
    splash.setWindowFlag(QtCore.Qt.SplashScreen, True)
    splash.setStyleSheet(native_stylesheet())
    layout = QtWidgets.QVBoxLayout(splash)
    layout.setContentsMargins(26, 22, 26, 22)
    layout.setSpacing(10)

    mark = QtWidgets.QLabel()
    mark.setAlignment(QtCore.Qt.AlignCenter)
    pixmap = pixmap_from_media(QtCore, QtGui, "ui", "static", "localflight-logo.svg", width=160, height=160)
    if pixmap.isNull():
        pixmap = pixmap_from_media(QtCore, QtGui, "assets", "localflight-logo.svg", width=96, height=96)
    if pixmap.isNull():
        mark.setText("Local Flight")
        mark.setObjectName("BrandTitle")
    else:
        mark.setPixmap(pixmap)

    title = label(QtWidgets, "Local Flight", "BrandTitle")
    title.setAlignment(QtCore.Qt.AlignCenter)
    version_label = label(QtWidgets, f"v{_app_version()} native shell", "Muted")
    version_label.setAlignment(QtCore.Qt.AlignCenter)
    status = label(QtWidgets, "Starting backend, board, radar, and local docs...", "Muted", wrap=True)
    status.setAlignment(QtCore.Qt.AlignCenter)
    layout.addWidget(mark)
    layout.addWidget(title)
    layout.addWidget(version_label)
    layout.addWidget(status)
    splash.resize(420, 260)
    screen = QtWidgets.QApplication.primaryScreen()
    if screen is not None:
        geometry = screen.availableGeometry()
        splash.move(geometry.center() - splash.rect().center())
    return splash


def _screen_available_geometry(QtWidgets: Any, window: Any | None = None) -> Any | None:
    qapplication = getattr(QtWidgets, "QApplication", None)
    app = qapplication.instance() if qapplication is not None else None
    screen = None
    if window is not None and hasattr(window, "screen"):
        try:
            screen = window.screen()
        except Exception:
            screen = None
    if screen is None and app is not None:
        screen = app.primaryScreen()
    if screen is None:
        return None
    try:
        return screen.availableGeometry()
    except Exception:
        return None


def _fit_window_to_screen(QtWidgets: Any, window: Any, preferred_width: int, preferred_height: int) -> None:
    """Set a comfortable first-launch size without overflowing small displays."""
    geometry = _screen_available_geometry(QtWidgets, window)
    if geometry is None:
        window.resize(preferred_width, preferred_height)
        return

    width, height = fitted_window_size(
        geometry.width(),
        geometry.height(),
        max_width=preferred_width,
        max_height=preferred_height,
    )
    window.resize(width, height)

    frame = getattr(window, "frameGeometry", lambda: None)()
    if frame is not None:
        frame.moveCenter(geometry.center())
        window.move(frame.topLeft())


def _show_fitted_window(QtCore: Any, QtWidgets: Any, window: Any, preferred_width: int, preferred_height: int) -> None:
    _fit_window_to_screen(QtWidgets, window, preferred_width, preferred_height)
    window.show()
    # The final macOS frame and layout minimums settle only after show().
    QtCore.QTimer.singleShot(0, lambda: _fit_window_to_screen(QtWidgets, window, preferred_width, preferred_height))
    QtCore.QTimer.singleShot(120, lambda: _fit_window_to_screen(QtWidgets, window, preferred_width, preferred_height))


def _finish_splash(splash: Any, window: Any) -> None:
    """Close either a real QSplashScreen or our lightweight splash widget."""
    if splash is None:
        return
    try:
        if not splash.isVisible():
            return
    except Exception:
        return
    finish = getattr(splash, "finish", None)
    if callable(finish):
        finish(window)
        return
    try:
        splash.hide()
    except Exception:
        pass
    try:
        splash.close()
    except Exception:
        pass


class _NativeEventBridge:  # pragma: no cover - exercised by Qt runtime
    """Qt WebSocket bridge matching the browser kiosk live-push contract."""

    def __init__(
        self,
        QtCore: Any,
        QtWebSockets: Any,
        owner: Any,
        *,
        base_url: str,
        on_event: Callable[[dict[str, Any]], None],
        on_status: Callable[[str, bool], None],
    ) -> None:
        self.QtCore = QtCore
        self.owner = owner
        self.url = _native_ws_url(base_url)
        self.on_event = on_event
        self.on_status = on_status
        self.retry_ms = 1000
        self.closed = False
        self.socket = QtWebSockets.QWebSocket()
        self.retry_timer = QtCore.QTimer(owner)
        self.retry_timer.setSingleShot(True)
        self.retry_timer.timeout.connect(self.connect)
        self.socket.connected.connect(self._connected)
        self.socket.disconnected.connect(self._disconnected)
        self.socket.textMessageReceived.connect(self._message)
        if hasattr(self.socket, "errorOccurred"):
            self.socket.errorOccurred.connect(lambda _err: self._failed())
        owner.destroyed.connect(self.close)
        self.connect()

    def connect(self) -> None:
        if self.closed:
            return
        self.on_status("live push connecting", False)
        self.socket.open(self.QtCore.QUrl(self.url))

    def close(self) -> None:
        self.closed = True
        self.retry_timer.stop()
        try:
            self.socket.close()
        except RuntimeError:
            # Qt can delete the socket before Python finalizers run in tests/app exit.
            pass

    def _connected(self) -> None:
        self.retry_ms = 1000
        self.on_status("live push connected", True)

    def _failed(self) -> None:
        if not self.closed:
            self.on_status("live push reconnecting", False)

    def _disconnected(self) -> None:
        if self.closed:
            return
        self.on_status("live push offline", False)
        self.retry_timer.start(min(self.retry_ms, 30000))
        self.retry_ms = min(self.retry_ms * 2, 30000)

    def _message(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        if isinstance(payload, dict):
            self.on_event(payload)


class _NativeCrashReporter:
    """Route native UI exceptions through the same local feedback API as users."""

    def __init__(self, base_url: str, *, screen_provider: Callable[[], str] | None = None) -> None:
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
            _API_EXECUTOR.submit(self._send, message, traceback_str)

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
            # Reporting must never make a UI crash worse.
            pass
        finally:
            self._reporting = False


def launch_native_app(
    *,
    base_url: str,
    first_launch: bool,
    fullscreen: bool = False,
) -> int:
    QtCore, QtGui, QtWidgets = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    configure_qt_app_identity(QtCore, QtGui, app)
    apply_app_font_defaults(QtGui, app)
    app_icon = localflight_app_icon(QtGui)
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
    splash = _build_splash(QtCore, QtGui, QtWidgets)
    splash.show()
    app.processEvents()

    windows: dict[str, Any] = {}

    def current_native_screen() -> str:
        main_window = windows.get("main")
        if main_window is not None:
            return str(getattr(main_window, "current_screen_key", "native") or "native")
        if windows.get("setup") is not None:
            return "setup"
        return "native"

    crash_reporter = _NativeCrashReporter(base_url, screen_provider=current_native_screen)
    crash_reporter.install()
    windows["crash_reporter"] = crash_reporter

    def show_main_window() -> None:
        window = NativeMainWindow(QtCore, QtGui, QtWidgets, base_url=base_url, first_launch=False)
        if not app_icon.isNull():
            window.setWindowIcon(app_icon)
        if fullscreen:
            window.showFullScreen()
        else:
            _show_fitted_window(QtCore, QtWidgets, window, 1680, 980)
        _finish_splash(splash, window)
        windows["main"] = window

    def setup_complete() -> None:
        show_main_window()
        setup_window = windows.get("setup")
        if setup_window is not None:
            if hasattr(setup_window, "allow_close_without_shutdown"):
                setup_window.allow_close_without_shutdown()
            setup_window.close()

    if first_launch:
        setup_window_cls = lazy_symbol("localflight.native.pages.setup", "NativeSetupWindow")
        setup_window = setup_window_cls(
            QtCore,
            QtGui,
            QtWidgets,
            base_url=base_url,
            on_setup_complete=setup_complete,
        )
        if not app_icon.isNull():
            setup_window.setWindowIcon(app_icon)
        _show_fitted_window(QtCore, QtWidgets, setup_window, 980, 760)
        _finish_splash(splash, setup_window)
        windows["setup"] = setup_window
    else:
        show_main_window()
    QtCore.QTimer.singleShot(700, splash.close)
    return int(app.exec())


class NativeSetupWindow:  # pragma: no cover - exercised with optional Qt
    def __new__(
        cls,
        QtCore: Any,
        QtGui: Any,
        QtWidgets: Any,
        *,
        base_url: str,
        on_setup_complete: Callable[[], None],
    ):
        class _Window(QtWidgets.QMainWindow):
            def __init__(self) -> None:
                super().__init__()
                self.client = LocalApiClient(base_url=base_url)
                self.service = NativeApiService(self.client)
                self._allow_close_without_backend_shutdown = False
                self._shutdown_started = False
                self._ui_only = _env_truthy("LOCALFLIGHT_NATIVE_UI_ONLY")
                self.setWindowTitle("Local Flight Setup")
                self.setStyleSheet(native_stylesheet())
                setup_cls = lazy_symbol("localflight.native.pages.setup", "SetupScreen")
                self.setup_screen = setup_cls(
                    QtCore,
                    QtWidgets,
                    self.client,
                    base_url,
                    on_setup_complete=on_setup_complete,
                    QtGui=QtGui,
                )
                self.setCentralWidget(_as_widget(self.setup_screen))

            def allow_close_without_shutdown(self) -> None:
                self._allow_close_without_backend_shutdown = True

            def closeEvent(self, event: Any) -> None:
                if self._allow_close_without_backend_shutdown or self._ui_only:
                    event.accept()
                    return
                if not self._shutdown_started:
                    self._shutdown_started = True
                    try:
                        self.service.quit_app()
                    except NativeApiError:
                        pass
                event.accept()

        return _Window()


class NativeMainWindow:  # pragma: no cover - exercised with optional Qt
    def __new__(cls, QtCore: Any, QtGui: Any, QtWidgets: Any, *, base_url: str, first_launch: bool):
        class _Window(QtWidgets.QMainWindow):
            def __init__(self) -> None:
                super().__init__()
                self.QtCore = QtCore
                self.QtGui = QtGui
                self.QtWidgets = QtWidgets
                self.client = LocalApiClient(base_url=base_url)
                self.service = NativeApiService(self.client)
                self._shutdown_started = False
                self._ui_only = _env_truthy("LOCALFLIGHT_NATIVE_UI_ONLY")
                self.setWindowTitle("Local Flight")
                self.theme = "dark"
                self.skin = "standard"
                self.colors = colors_for(self.theme, self.skin)
                self.setStyleSheet(native_stylesheet(theme=self.theme, skin=self.skin))
                self._nav_buttons: dict[str, Any] = {}
                self.screens: list[Any] = []
                self.screen_keys: list[str] = []
                self._screen_factories: dict[str, Callable[[], Any]] = {}
                self._constructed_keys: set[str] = set()
                self._dirty_screens: set[str] = set()
                self._fallback_refresh_keys = fallback_refresh_page_keys()
                self.current_screen_key = "display"

                root = QtWidgets.QWidget()
                shell = QtWidgets.QVBoxLayout(root)
                shell.setContentsMargins(0, 0, 0, 0)
                shell.setSpacing(0)
                shell.addWidget(self._build_top_nav())

                self.stack = QtWidgets.QStackedWidget()
                shell.addWidget(self.stack, 1)
                shell.addWidget(self._build_footer())
                self.setCentralWidget(root)

                self.first_launch = first_launch
                for spec in PAGE_SPECS:
                    self._add_screen(
                        spec.key,
                        spec.title,
                        self._factory_for_spec(spec, base_url),
                        nav=spec.nav_visible,
                        eager=spec.eager,
                    )

                self._load_design_from_config()
                self._show_page("display", force_refresh=True)
                self._log_runtime_diagnostics("startup")

                self.clock_timer = QtCore.QTimer(self)
                self.clock_timer.timeout.connect(self._update_clocks)
                self.clock_timer.start(1000)
                self._update_clocks()

                self.refresh_timer = QtCore.QTimer(self)
                self.refresh_timer.timeout.connect(self._fallback_refresh_active)
                self.refresh_timer.setSingleShot(True)

                self._ws_bridge = None
                try:
                    from PySide6 import QtWebSockets

                    self._ws_bridge = NativeLiveBus(
                        QtCore,
                        QtWebSockets,
                        self,
                        base_url=base_url,
                        on_event=self._handle_live_event,
                        on_status=self._set_live_status,
                    )
                    self._ws_bridge.start()
                except Exception:
                    self._set_live_status("live push unavailable", False)
                self._schedule_fallback_refresh()

            def _factory_for_spec(self, spec: NativePageSpec, base_url: str) -> Callable[[], Any]:
                def _factory() -> Any:
                    page_cls = lazy_symbol(spec.module, spec.symbol)
                    if spec.key == "display":
                        return page_cls(QtCore, QtGui, QtWidgets, self.client)
                    if spec.key in {"fids", "radar"}:
                        return page_cls(QtCore, QtGui, QtWidgets, self.client)
                    if spec.key == "matrix":
                        return page_cls(QtWidgets, self.client)
                    if spec.key == "settings":
                        return page_cls(QtCore, QtGui, QtWidgets, self.client, base_url)
                    if spec.key == "admin":
                        return page_cls(QtWidgets, self.client, navigate=self._show_page)
                    return page_cls(QtWidgets, self.client)

                return _factory

            def _build_top_nav(self) -> Any:
                nav = QtWidgets.QFrame()
                nav.setObjectName("TopNav")
                layout = QtWidgets.QHBoxLayout(nav)
                layout.setContentsMargins(12, 7, 12, 7)
                layout.setSpacing(8)

                brand_mark = QtWidgets.QLabel()
                brand_mark.setObjectName("BrandMark")
                brand_mark.setAlignment(QtCore.Qt.AlignCenter)
                brand_pixmap = pixmap_from_media(QtCore, QtGui, "ui", "static", "localflight-logo.svg", width=26, height=26)
                if brand_pixmap.isNull():
                    brand_pixmap = pixmap_from_media(QtCore, QtGui, "assets", "localflight-logo.svg", width=26, height=26)
                if brand_pixmap.isNull():
                    brand_mark.setText("\U0001F6EB")
                else:
                    brand_mark.setPixmap(brand_pixmap)
                brand = QtWidgets.QLabel("Local Flight")
                brand.setObjectName("Brand")
                ver = QtWidgets.QLabel(f"v{_app_version()}")
                ver.setObjectName("Version")
                self.brand_label = brand
                self.version_label = ver
                self.utc_clock = QtWidgets.QLabel("UTC --:--:--")
                self.utc_clock.setObjectName("ClockChip")
                self.local_clock = QtWidgets.QLabel("LT --:--:--")
                self.local_clock.setObjectName("ClockChip")

                left_group = QtWidgets.QWidget()
                left_layout = QtWidgets.QHBoxLayout(left_group)
                left_layout.setContentsMargins(0, 0, 0, 0)
                left_layout.setSpacing(7)
                left_layout.addWidget(brand_mark)
                left_layout.addWidget(brand)
                left_layout.addWidget(ver)
                left_group.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Preferred)
                self.left_nav_group = left_group

                center_group = QtWidgets.QWidget()
                self.primary_nav_layout = QtWidgets.QHBoxLayout(center_group)
                self.primary_nav_layout.setContentsMargins(0, 0, 0, 0)
                self.primary_nav_layout.setSpacing(4)
                center_group.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Preferred)

                clock_group = QtWidgets.QFrame()
                clock_group.setObjectName("ClockDivider")
                clock_layout = QtWidgets.QHBoxLayout(clock_group)
                clock_layout.setContentsMargins(6, 0, 6, 0)
                clock_layout.setSpacing(6)
                clock_layout.addWidget(self.utc_clock)
                clock_layout.addWidget(self.local_clock)
                clock_group.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Preferred)
                self.clock_nav_group = clock_group

                right_group = QtWidgets.QWidget()
                self.utility_nav_layout = QtWidgets.QHBoxLayout(right_group)
                self.utility_nav_layout.setContentsMargins(0, 0, 0, 0)
                self.utility_nav_layout.setSpacing(4)
                right_group.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Preferred)

                self.nav_more_menu = QtWidgets.QMenu(nav)
                self._nav_more_actions: dict[str, Any] = {}
                self.nav_more_button = QtWidgets.QPushButton("More")
                self.nav_more_button.setObjectName("Quiet")
                self.nav_more_button.setToolTip("More Local Flight pages")
                self.nav_more_button.setMenu(self.nav_more_menu)
                self.nav_more_button.hide()

                sync_chip = QtWidgets.QFrame()
                sync_chip.setObjectName("SyncChip")
                sync_layout = QtWidgets.QHBoxLayout(sync_chip)
                sync_layout.setContentsMargins(7, 4, 7, 4)
                sync_layout.setSpacing(0)
                self.live_dot = QtWidgets.QLabel(chr(9679))
                self.live_dot.setObjectName("SyncDot")
                self.live_status = QtWidgets.QLabel("")
                self.live_status.setObjectName("SyncText")
                self.live_status.setMinimumWidth(0)
                self.live_status.hide()
                sync_layout.addWidget(self.live_dot)
                sync_layout.addWidget(self.live_status)
                sync_chip.setToolTip("Local Flight live updates")
                self.sync_chip = sync_chip

                quit_btn = QtWidgets.QPushButton("Power")
                quit_btn.setObjectName("Quiet")
                quit_btn.setToolTip("Shut down Local Flight")
                quit_btn.clicked.connect(self._quit_app)
                self.quit_button = quit_btn

                layout.addWidget(left_group)
                layout.addWidget(center_group, 0)
                layout.addStretch(1)
                layout.addWidget(clock_group, 0)
                layout.addStretch(1)
                layout.addWidget(right_group, 0)
                layout.addWidget(self.nav_more_button)
                layout.addWidget(sync_chip)
                layout.addWidget(quit_btn)
                self.nav = nav
                self.primary_nav_group = center_group
                self.utility_nav_group = right_group
                return nav

            def _build_footer(self) -> Any:
                footer = QtWidgets.QFrame()
                footer.setObjectName("AppFooter")
                layout = QtWidgets.QHBoxLayout(footer)
                layout.setContentsMargins(14, 4, 14, 5)
                layout.setSpacing(10)
                status = QtWidgets.QLabel(f"v{_app_version()} \u00b7 Local-first \u00b7 private by design")
                status.setObjectName("FooterStatus")
                tagline = QtWidgets.QLabel("")
                tagline.setObjectName("FooterTagline")
                tagline.setMinimumWidth(0)
                tagline.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
                github = QtWidgets.QPushButton("")
                github.setObjectName("FooterLink")
                github.setToolTip("GitHub")
                github.setAccessibleName("GitHub")
                github.setMinimumSize(36, 30)
                github.setMaximumWidth(38)
                # Theme-aware: white invertocat on dark theme, black on light.
                gh_file = (
                    "support-repository-dark.svg"
                    if self.theme == "light"
                    else "support-repository.svg"
                )
                github_icon = icon_from_media(QtGui, "ui", "static", gh_file)
                if github_icon.isNull():
                    github.setText("repo")
                else:
                    github.setIcon(github_icon)
                    github.setIconSize(QtCore.QSize(20, 20))
                github.clicked.connect(lambda: webbrowser.open(GITHUB_URL))
                coffee = QtWidgets.QPushButton("")
                coffee.setObjectName("FooterLink")
                coffee.setToolTip("Buy Me a Coffee")
                coffee.setAccessibleName("Buy Me a Coffee")
                coffee.setMinimumSize(36, 30)
                coffee.setMaximumWidth(38)
                coffee_icon = icon_from_media(QtGui, "ui", "static", "support-coffee.svg")
                if coffee_icon.isNull():
                    coffee.setText(chr(0x2615))
                else:
                    coffee.setIcon(coffee_icon)
                    coffee.setIconSize(QtCore.QSize(19, 19))
                coffee.clicked.connect(lambda: webbrowser.open(COFFEE_URL))
                self.footer_status_label = status
                self.footer_tagline_label = tagline
                self.footer_github_button = github
                self.footer_coffee_button = coffee
                layout.addWidget(status)
                layout.addWidget(tagline, 1)
                layout.addWidget(github)
                layout.addWidget(coffee)
                return footer

            def _placeholder(self, label_text: str) -> Any:
                frame = self.QtWidgets.QFrame()
                frame.setObjectName("Panel")
                layout = self.QtWidgets.QVBoxLayout(frame)
                layout.setContentsMargins(18, 18, 18, 18)
                layout.addWidget(label(self.QtWidgets, f"{label_text} will load when opened.", "Muted", wrap=True))
                layout.addStretch(1)
                return frame

            def _add_screen(
                self,
                key: str,
                label_text: str,
                factory: Callable[[], Any],
                *,
                nav: bool,
                eager: bool = False,
            ) -> None:
                self._screen_factories[key] = factory
                screen = factory() if eager else None
                self.stack.addWidget(_as_widget(screen) if screen is not None else self._placeholder(label_text))
                self.screens.append(screen)
                self.screen_keys.append(key)
                if screen is not None:
                    self._constructed_keys.add(key)
                if nav:
                    glyph = NAV_GLYPHS.get(key, "")
                    button = self.QtWidgets.QPushButton(f"{glyph} {label_text}".strip())
                    button.setObjectName("NavButton")
                    button.setCheckable(True)
                    button.setProperty("lf_label", label_text)
                    button.setProperty("lf_key", key)
                    button.setProperty("lf_glyph", glyph)
                    button.clicked.connect(lambda _checked=False, k=key: self._show_page(k))
                    try:
                        nav_group = next(spec.nav_group for spec in PAGE_SPECS if spec.key == key)
                    except StopIteration:
                        nav_group = "utility"
                    target_layout = self.primary_nav_layout if nav_group == "primary" else self.utility_nav_layout
                    target_layout.addWidget(button)
                    self._nav_buttons[key] = button
                    if nav_group == "utility":
                        action = self.nav_more_menu.addAction(f"{glyph} {label_text}".strip())
                        action.triggered.connect(lambda _checked=False, k=key: self._show_page(k))
                        self._nav_more_actions[key] = action
                    self._apply_nav_density(self.width())

            def _nav_button_text(self, key: str, glyph: str, label_text: str, density: str) -> str:
                if density == "compact":
                    return glyph or label_text[:1]
                if density == "medium" and key not in {"display", "fids", "radar"}:
                    return glyph or label_text[:1]
                return f"{glyph} {label_text}".strip()

            def _apply_nav_density(self, width: int | None = None) -> None:
                density = native_visual_density(width or self.width())
                self._nav_density = density
                compact = density == "compact"
                medium = density == "medium"
                presentation = density == "presentation"

                self.brand_label.setVisible(not compact or (width or self.width()) >= 720)
                self.version_label.setVisible(density in {"wide", "presentation"})
                self.utc_clock.setVisible(True)
                self.local_clock.setVisible(not compact)
                self.sync_chip.setVisible(True)
                self.live_status.setVisible(False)
                self.utility_nav_group.setVisible(not compact)
                self.nav_more_button.setVisible(compact)
                self.nav_more_button.setText("⋯" if compact else "More")
                self.nav_more_button.setMinimumWidth(40 if compact else 72)
                if hasattr(self, "footer_status_label"):
                    self.footer_status_label.setText(f"v{_app_version()} \u00b7 Local-first \u00b7 private by design")

                self.quit_button.setText(chr(0x23FB) if compact else "Power")
                self.quit_button.setMinimumWidth(42 if compact else 68)

                primary_spacing = 3 if compact else 4
                utility_spacing = 3 if medium else 4
                self.primary_nav_layout.setSpacing(primary_spacing)
                self.utility_nav_layout.setSpacing(utility_spacing)

                for key, button in self._nav_buttons.items():
                    glyph = str(button.property("lf_glyph") or "")
                    label_text = str(button.property("lf_label") or "")
                    text = self._nav_button_text(key, glyph, label_text, density)
                    button.setText(text)
                    button.setToolTip(label_text)
                    button.setAccessibleName(label_text)
                    glyph_only = text == glyph or text == label_text[:1]
                    button.setMinimumWidth(36 if glyph_only else (72 if presentation else 58))
                    button.setMaximumWidth(56 if glyph_only else 154)
                    action = self._nav_more_actions.get(key)
                    if action is not None:
                        action.setText(f"{glyph} {label_text}".strip())
                        action.setVisible(compact)

            def _ensure_screen(self, key: str) -> Any:
                if key not in self.screen_keys:
                    return None
                index = self.screen_keys.index(key)
                screen = self.screens[index]
                if screen is not None:
                    return screen
                factory = self._screen_factories.get(key)
                if factory is None:
                    return None
                screen = factory()
                self.screens[index] = screen
                self._constructed_keys.add(key)
                old_widget = self.stack.widget(index)
                self.stack.removeWidget(old_widget)
                old_widget.deleteLater()
                self.stack.insertWidget(index, _as_widget(screen))
                if hasattr(screen, "apply_theme"):
                    screen.apply_theme(self.theme, self.skin)
                return screen

            def _constructed_screens(self) -> list[Any]:
                return [screen for screen in self.screens if screen is not None]

            def _show_page(self, key: str, *, force_refresh: bool = False) -> None:
                if key not in self.screen_keys:
                    return
                old_screen = self._ensure_screen(self.current_screen_key)
                if old_screen is not None and key != self.current_screen_key and hasattr(old_screen, "set_active"):
                    old_screen.set_active(False)
                first_open = key not in self._constructed_keys
                screen = self._ensure_screen(key)
                self.current_screen_key = key
                index = self.screen_keys.index(key)
                try:
                    from localflight.native.shell_widgets import fade_swap

                    fade_swap(QtCore, QtWidgets, self.stack, index, duration_ms=180)
                except Exception:
                    self.stack.setCurrentIndex(index)
                for page_key, button in self._nav_buttons.items():
                    button.setChecked(page_key == key)
                if hasattr(screen, "set_active"):
                    screen.set_active(True)
                should_refresh = force_refresh or first_open or key in self._dirty_screens or key in self._fallback_refresh_keys
                self._dirty_screens.discard(key)
                if should_refresh:
                    self._refresh_active(force=True)
                self._schedule_fallback_refresh()
                self._log_runtime_diagnostics(f"show:{key}")

            def _load_design_from_config(self) -> None:
                try:
                    cfg = self.service.config()
                except NativeApiError:
                    cfg = {}
                self._apply_design_from_config(cfg)

            def _apply_design_from_config(self, cfg: dict[str, Any]) -> None:
                theme = str(cfg.get("theme") or self.theme or "dark").strip().lower()
                skin = str(cfg.get("skin") or self.skin or "standard").strip().lower()
                self.theme = theme
                self.skin = skin
                self.colors = colors_for(theme, skin)
                self.setStyleSheet(native_stylesheet(theme=theme, skin=skin))
                # Theme-aware GitHub mark: white on dark, black on light.
                if hasattr(self, "footer_github_button"):
                    try:
                        gh_file = (
                            "support-repository-dark.svg"
                            if theme == "light"
                            else "support-repository.svg"
                        )
                        gh_icon = icon_from_media(QtGui, "ui", "static", gh_file)
                        if not gh_icon.isNull():
                            self.footer_github_button.setIcon(gh_icon)
                    except Exception:
                        pass
                for screen in self._constructed_screens():
                    if hasattr(screen, "apply_theme"):
                        screen.apply_theme(theme, skin)

            def _update_clocks(self) -> None:
                now_utc = datetime.now(timezone.utc)
                now_local = datetime.now().astimezone()
                density = getattr(self, "_nav_density", native_visual_density(self.width()))
                if density == "compact":
                    self.utc_clock.setText("UTC " + now_utc.strftime("%H:%M"))
                    self.local_clock.setText("LT " + now_local.strftime("%H:%M"))
                else:
                    self.utc_clock.setText("UTC " + now_utc.strftime("%H:%M:%S"))
                    self.local_clock.setText("LT " + now_local.strftime("%H:%M:%S"))

            def _refresh_active(self, *, force: bool = False) -> None:
                index = self.stack.currentIndex()
                if 0 <= index < len(self.screen_keys):
                    self._ensure_screen(self.screen_keys[index])
                screen = self.screens[index] if 0 <= index < len(self.screens) else None
                if hasattr(screen, "refresh"):
                    screen.refresh()
                self._schedule_fallback_refresh()

            def _fallback_refresh_active(self) -> None:
                if self.current_screen_key in self._fallback_refresh_keys:
                    self._refresh_active(force=True)

            def _fallback_interval_ms(self) -> int | None:
                key = self.current_screen_key
                if key not in self._fallback_refresh_keys:
                    return None
                if key in {"display", "fids"}:
                    return 300_000
                if key == "radar":
                    screen = self._ensure_screen(key)
                    payload = getattr(screen, "_last_payload", {}) if screen is not None else {}
                    try:
                        refresh_after = int(float(payload.get("refresh_after_s") or 0))
                    except Exception:
                        refresh_after = 0
                    return max(60_000, refresh_after * 1000)
                return 300_000

            def _schedule_fallback_refresh(self) -> None:
                if not hasattr(self, "refresh_timer"):
                    return
                interval = self._fallback_interval_ms()
                self.refresh_timer.stop()
                if interval is not None:
                    self.refresh_timer.start(interval)

            def _log_runtime_diagnostics(self, reason: str) -> None:
                constructed = [key for key, screen in zip(self.screen_keys, self.screens) if screen is not None]
                active_timers: list[str] = []
                pending_fetches: list[str] = []
                for key, screen in zip(self.screen_keys, self.screens):
                    if screen is None:
                        continue
                    if getattr(screen, "_fetch_active", False):
                        pending_fetches.append(key)
                    for attr in ("page_timer", "refresh_timer", "timer"):
                        timer = getattr(screen, attr, None)
                        if timer is not None and hasattr(timer, "isActive") and timer.isActive():
                            active_timers.append(f"{key}.{attr}")
                    canvas = getattr(screen, "canvas", None)
                    for attr in ("_sweep_timer", "timer"):
                        timer = getattr(canvas, attr, None) if canvas is not None else None
                        if timer is not None and hasattr(timer, "isActive") and timer.isActive():
                            active_timers.append(f"{key}.canvas.{attr}")
                _LOG.debug(
                    "Native runtime | reason=%s active=%s constructed=%s active_timers=%s pending_fetches=%s",
                    reason,
                    self.current_screen_key,
                    ",".join(constructed) or "-",
                    ",".join(active_timers) or "-",
                    ",".join(pending_fetches) or "-",
                )

            def _set_live_status(self, status: LiveStatus | str, connected: bool | None = None) -> None:
                if isinstance(status, LiveStatus):
                    text = status.text
                    connected_value = status.connected
                else:
                    text = status
                    connected_value = bool(connected)
                display_text = self._friendly_live_status(text, connected_value)
                self.live_status.setText(display_text)
                tooltip = f"Live updates: {display_text}"
                self.sync_chip.setToolTip(tooltip)
                self.live_dot.setToolTip(tooltip)
                self.live_status.setToolTip(tooltip)
                self.live_status.setVisible(False)
                self.sync_chip.setProperty("connected", connected_value)
                self.live_dot.setProperty("connected", connected_value)
                self.live_status.setProperty("connected", connected_value)
                for widget in (self.sync_chip, self.live_dot, self.live_status):
                    widget.style().unpolish(widget)
                    widget.style().polish(widget)

            def _friendly_live_status(self, text: str, connected: bool) -> str:
                normalized = str(text or "").replace("live push", "").strip().lower()
                if connected:
                    return "Live updates"
                if "connect" in normalized or "reconnect" in normalized:
                    return "Reconnecting"
                if "offline" in normalized or "unavailable" in normalized:
                    return "Local refresh"
                return "Syncing"

            def _handle_live_event(self, payload: dict[str, Any]) -> None:
                event_type = str(payload.get("type") or "").strip()
                if not event_type:
                    return
                if event_type == "config_updated":
                    self.service.clear_cache()
                    self._load_design_from_config()
                    for key in self.screen_keys:
                        if key != self.current_screen_key:
                            self._dirty_screens.add(key)
                    screen = self._ensure_screen(self.current_screen_key)
                    if hasattr(screen, "handle_live_event"):
                        screen.handle_live_event(payload)
                    else:
                        self._refresh_active(force=True)
                    return
                if event_type in {"snapshot_updated", "scheduler_restarted"}:
                    for key in self._fallback_refresh_keys:
                        if key != self.current_screen_key:
                            self._dirty_screens.add(key)
                screen = self._ensure_screen(self.current_screen_key)
                if hasattr(screen, "handle_live_event"):
                    screen.handle_live_event(payload)
                elif event_type in {"snapshot_updated", "scheduler_restarted"}:
                    self._refresh_active(force=True)

            def _after_setup_complete(self) -> None:
                self._show_page("display")

            def _quit_app(self) -> None:
                if not self._confirm_quit():
                    return
                self._request_backend_shutdown()
                QtWidgets.QApplication.quit()

            def _confirm_quit(self) -> bool:
                dialog = self.QtWidgets.QDialog(self)
                dialog.setWindowTitle("Quit Local Flight?")
                dialog.setObjectName("NativeModal")
                layout = self.QtWidgets.QVBoxLayout(dialog)
                layout.setContentsMargins(18, 18, 18, 18)
                layout.setSpacing(10)
                layout.addWidget(label(self.QtWidgets, "Quit Local Flight?", "Title"))
                layout.addWidget(
                    label(
                        self.QtWidgets,
                        (
                            "This closes the native display shell. The backend service will keep running."
                            if self._ui_only
                            else "This closes the native shell and asks the local backend to stop cleanly."
                        ),
                        "Muted",
                        wrap=True,
                    )
                )
                buttons = self.QtWidgets.QHBoxLayout()
                cancel = self.QtWidgets.QPushButton("Keep running")
                cancel.setObjectName("Quiet")
                quit_now = self.QtWidgets.QPushButton("Quit")
                quit_now.setObjectName("Danger")
                cancel.clicked.connect(dialog.reject)
                quit_now.clicked.connect(dialog.accept)
                buttons.addStretch(1)
                buttons.addWidget(cancel)
                buttons.addWidget(quit_now)
                layout.addLayout(buttons)
                return dialog.exec() == self.QtWidgets.QDialog.Accepted

            def _request_backend_shutdown(self) -> None:
                if self._shutdown_started:
                    return
                self._shutdown_started = True
                if self._ui_only:
                    return
                try:
                    self.service.quit_app()
                except NativeApiError:
                    pass

            def closeEvent(self, event: Any) -> None:
                if self._shutdown_started:
                    event.accept()
                    return
                if not self._confirm_quit():
                    event.ignore()
                    return
                self._request_backend_shutdown()
                event.accept()

            def resizeEvent(self, event: Any) -> None:
                super().resizeEvent(event)
                self._apply_nav_density(self.width())
                self._update_clocks()

        return _Window()


class SetupScreen:  # pragma: no cover - optional Qt runtime
    def __init__(
        self,
        QtCore: Any,
        QtWidgets: Any,
        client: LocalApiClient,
        base_url: str,
        *,
        on_setup_complete: Callable[[], None] | None = None,
        QtGui: Any | None = None,
    ) -> None:
        self.QtCore = QtCore
        self.QtGui = QtGui
        self.QtWidgets = QtWidgets
        self.client = client
        self.service = NativeApiService(client)
        self.base_url = base_url.rstrip("/")
        self.on_setup_complete = on_setup_complete
        self._airport_search_future: Future[Any] | None = None
        self._last_airport_query = ""
        self._stored_activation = False
        self._mode_initialized = False
        self.step_names = ["Airport", "Source", "Keys", "Diagnostics", "Finish"]
        self.step_icons = ["\u2708", "\U0001f4e1", "\U0001f511", "\U0001f6e1", "\u2728"]
        self.setup_max_width = 940
        self.step_buttons: list[Any] = []
        self.source_buttons: dict[str, Any] = {}
        self.diagnostics_buttons: dict[str, Any] = {}

        self.widget, layout = scroll_page(QtWidgets)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        hero = QtWidgets.QFrame()
        hero.setObjectName("Panel")
        hero.setMaximumWidth(self.setup_max_width)
        hero_layout = QtWidgets.QVBoxLayout(hero)
        hero_layout.setContentsMargins(20, 18, 20, 18)
        hero_layout.setSpacing(8)
        brand = QtWidgets.QHBoxLayout()
        if self.QtGui is not None:
            logo = QtWidgets.QLabel()
            pixmap = pixmap_from_media(self.QtCore, self.QtGui, "ui", "static", "localflight-logo.svg", width=48, height=48)
            if pixmap is not None and not pixmap.isNull():
                logo.setPixmap(pixmap)
            else:
                logo.setText("\u2708")
                logo.setObjectName("Metric")
            brand.addWidget(logo)
        else:
            brand.addWidget(label(QtWidgets, "\u2708", "Metric"))
        title_stack = QtWidgets.QVBoxLayout()
        title_stack.addWidget(label(QtWidgets, "Local Flight", "BrandTitle"))
        title_stack.addWidget(label(QtWidgets, "Setup", "Title"))
        title_stack.addWidget(label(QtWidgets, "Native privacy-first display shell", "Muted"))
        brand.addLayout(title_stack, 1)
        brand.addStretch(1)
        hero_layout.addLayout(brand)
        hero_layout.addWidget(
            label(
                QtWidgets,
                "Pick your airport, choose the data path, and Local Flight opens the display when this is done.",
                "Muted",
                wrap=True,
            )
        )
        self.status = label(QtWidgets, "Setup is local-first. You can change these choices later in Settings.", "Muted", wrap=True)
        hero_layout.addWidget(self.status)
        layout.addWidget(hero, 0, QtCore.Qt.AlignHCenter)

        steps_wrap = QtWidgets.QWidget()
        steps_wrap.setMaximumWidth(self.setup_max_width)
        steps = QtWidgets.QHBoxLayout()
        steps.setContentsMargins(0, 0, 0, 0)
        for idx, name in enumerate(self.step_names):
            icon = self.step_icons[idx] if idx < len(self.step_icons) else ""
            button = QtWidgets.QPushButton(f"{idx + 1}. {icon} {name}".strip())
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, i=idx: self._set_step(i))
            self.step_buttons.append(button)
            steps.addWidget(button)
        steps.addStretch(1)
        steps_wrap.setLayout(steps)
        layout.addWidget(steps_wrap, 0, QtCore.Qt.AlignHCenter)

        self.tabs = QtWidgets.QStackedWidget()
        self.tabs.setMaximumWidth(self.setup_max_width)
        self.tabs.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.search_timer = QtCore.QTimer(self.widget)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._start_airport_search)
        self.search_poll_timer = QtCore.QTimer(self.widget)
        self.search_poll_timer.setInterval(50)
        self.search_poll_timer.timeout.connect(self._poll_airport_search)

        self._build_airport_page()
        self._build_source_page()
        self._build_keys_page()
        self._build_diagnostics_page()
        self._build_finish_page()
        layout.addWidget(self.tabs, 1, QtCore.Qt.AlignHCenter)

        nav_wrap = QtWidgets.QWidget()
        nav_wrap.setMaximumWidth(self.setup_max_width)
        nav = QtWidgets.QHBoxLayout()
        nav.setContentsMargins(0, 0, 0, 0)
        self.back_btn = QtWidgets.QPushButton("Back")
        self.back_btn.setObjectName("Quiet")
        self.next_btn = QtWidgets.QPushButton("Next")
        self.finish_btn = QtWidgets.QPushButton("Finish setup")
        self.web_fallback_btn = QtWidgets.QPushButton("Open browser setup")
        self.web_fallback_btn.setObjectName("Quiet")
        self.back_btn.clicked.connect(self._previous_step)
        self.next_btn.clicked.connect(self._next_step)
        self.finish_btn.clicked.connect(self.finish_setup)
        self.web_fallback_btn.clicked.connect(lambda: webbrowser.open(f"{self.base_url}/setup"))
        nav.addWidget(self.web_fallback_btn)
        nav.addStretch(1)
        nav.addWidget(self.back_btn)
        nav.addWidget(self.next_btn)
        nav.addWidget(self.finish_btn)
        nav_wrap.setLayout(nav)
        layout.addWidget(nav_wrap, 0, QtCore.Qt.AlignHCenter)
        layout.addStretch(1)
        self._set_step(0)
        self.refresh()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def _page(self, title: str, text: str) -> tuple[Any, Any]:
        page = self.QtWidgets.QFrame()
        page.setObjectName("Panel")
        page.setMaximumWidth(self.setup_max_width)
        layout = self.QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(label(self.QtWidgets, title, "Section"))
        layout.addWidget(label(self.QtWidgets, text, "Muted", wrap=True))
        self.tabs.addWidget(page)
        return page, layout

    def _build_airport_page(self) -> None:
        _page, layout = self._page(
            "Airport",
            "Search by city, airport name, IATA, or ICAO. Selecting a result fills the technical codes for you.",
        )
        self.airport_search = self.QtWidgets.QLineEdit()
        self.airport_search.setPlaceholderText("Search airport, city, IATA, or ICAO...")
        self.airport_search.setMaximumWidth(620)
        self.airport_search.textChanged.connect(lambda _text: self.search_timer.start(250))
        self.airport_results = self.QtWidgets.QListWidget()
        self.airport_results.setMinimumHeight(150)
        self.airport_results.setMaximumWidth(720)
        self.airport_results.itemClicked.connect(self._select_airport_item)
        self.display_name = self.QtWidgets.QLineEdit("Local Flight")
        self.airport_iata = self.QtWidgets.QLineEdit("ZRH")
        self.airport_icao = self.QtWidgets.QLineEdit("LSZH")
        self.timezone = self.QtWidgets.QLineEdit("Europe/Zurich")
        for field in (self.display_name, self.airport_iata, self.airport_icao, self.timezone):
            field.setMaximumWidth(420)
        for field in (self.airport_iata, self.airport_icao, self.timezone):
            field.setReadOnly(True)
        form = self.QtWidgets.QFormLayout()
        form.addRow("Display name", self.display_name)
        form.addRow("Airport IATA", self.airport_iata)
        form.addRow("Airport ICAO", self.airport_icao)
        form.addRow("Timezone", self.timezone)
        layout.addWidget(self.airport_search)
        layout.addWidget(self.airport_results)
        layout.addLayout(form)

    def _build_source_page(self) -> None:
        _page, layout = self._page(
            "Choose Data Source",
            "Community Relay is easiest for beta testing. BYOK keeps AviationStack direct on this device. VATSIM is the virtual-network mode.",
        )
        self.setup_mode = self.QtWidgets.QComboBox()
        for label_text, mode in (
            ("Community relay", "community"),
            ("Bring your own AviationStack key", "byok"),
            ("Virtual / VATSIM", "virtual"),
        ):
            self.setup_mode.addItem(label_text, mode)
        self.setup_mode.hide()
        cards = self.QtWidgets.QGridLayout()
        cards.setHorizontalSpacing(10)
        cards.setVerticalSpacing(10)
        for col, (mode, title, body, glyph) in enumerate(
            (
                ("community", "Community Relay", "Shared airport snapshots through the hosted community relay.", "\U0001F4E1"),
                ("byok", "BYOK AviationStack", "Use your own API key and keep provider calls local.", "\U0001F511"),
                ("virtual", "Virtual / VATSIM", "No paid schedule key. Uses live VATSIM flight-network data.", "\U0001F6E9"),
            )
        ):
            button = self.QtWidgets.QPushButton(f"{glyph} {title}\n{body}".strip())
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setMinimumHeight(88)
            button.setMaximumWidth(285)
            button.clicked.connect(lambda _checked=False, m=mode: self._set_mode(m))
            self.source_buttons[mode] = button
            cards.addWidget(button, 0, col)
        layout.addLayout(cards)
        self.mode_help = label(self.QtWidgets, "", "Muted", wrap=True)
        layout.addWidget(self.mode_help)

        relay_box, relay_layout = panel(self.QtWidgets, "Community Relay")
        self.relay_url = self.QtWidgets.QLineEdit("https://localflight-community-relay.fly.dev")
        self.relay_url.setPlaceholderText("https://localflight-community-relay.fly.dev")
        self.relay_url.setMaximumWidth(540)
        self.activation_token = self.QtWidgets.QLineEdit()
        self.activation_token.setEchoMode(self.QtWidgets.QLineEdit.Password)
        self.activation_token.setPlaceholderText("Only needed when a token is not already stored")
        self.activation_token.setMaximumWidth(420)
        token_toggle = self.QtWidgets.QPushButton("Show token")
        token_toggle.setObjectName("Quiet")
        token_toggle.clicked.connect(lambda: self._toggle_secret(self.activation_token, token_toggle, "token"))
        token_row = self.QtWidgets.QHBoxLayout()
        token_row.addWidget(self.activation_token)
        token_row.addWidget(token_toggle)
        relay_form = self.QtWidgets.QFormLayout()
        relay_form.addRow("Relay host", self.relay_url)
        relay_form.addRow("Activation token", token_row)
        relay_layout.addLayout(relay_form)
        relay_actions = self.QtWidgets.QHBoxLayout()
        request = self.QtWidgets.QPushButton("Request activation")
        status = self.QtWidgets.QPushButton("Check relay status")
        test = self.QtWidgets.QPushButton("Test token")
        request.clicked.connect(self.request_activation)
        status.clicked.connect(self.check_activation_status)
        test.clicked.connect(self.test_activation)
        relay_actions.addWidget(request)
        relay_actions.addWidget(status)
        relay_actions.addWidget(test)
        relay_actions.addStretch(1)
        self.relay_status = label(self.QtWidgets, "Relay URL is auto-filled. Stored tokens are reused without exposing them.", "Muted", wrap=True)
        relay_layout.addLayout(relay_actions)
        relay_layout.addWidget(self.relay_status)
        layout.addWidget(relay_box)
        self.relay_box = relay_box

    def _build_keys_page(self) -> None:
        _page, layout = self._page(
            "Optional Provider Keys",
            "Only BYOK needs AviationStack. ADS-B Exchange and OpenSky are optional enrichment paths.",
        )
        self.keys_hint = label(self.QtWidgets, "Community and VATSIM can skip this page.", "Muted", wrap=True)
        layout.addWidget(self.keys_hint)
        self.aviationstack_key = self.QtWidgets.QLineEdit()
        self.rapidapi_key = self.QtWidgets.QLineEdit()
        self.opensky_id = self.QtWidgets.QLineEdit()
        self.opensky_secret = self.QtWidgets.QLineEdit()
        for field in (self.aviationstack_key, self.rapidapi_key, self.opensky_secret):
            field.setEchoMode(self.QtWidgets.QLineEdit.Password)
        for field in (self.aviationstack_key, self.rapidapi_key, self.opensky_id, self.opensky_secret):
            field.setMaximumWidth(520)
        self.aviationstack_key.setPlaceholderText("AviationStack API key")
        self.rapidapi_key.setPlaceholderText("RapidAPI key for ADS-B Exchange")
        self.opensky_id.setPlaceholderText("OpenSky client ID")
        self.opensky_secret.setPlaceholderText("OpenSky client secret")
        form = self.QtWidgets.QFormLayout()
        form.addRow("AviationStack", self.aviationstack_key)
        form.addRow("RapidAPI", self.rapidapi_key)
        form.addRow("OpenSky ID", self.opensky_id)
        form.addRow("OpenSky Secret", self.opensky_secret)
        layout.addLayout(form)
        actions = self.QtWidgets.QHBoxLayout()
        for text, url in (
            ("Create AviationStack key", "https://aviationstack.com/product"),
            ("Open ADS-B Exchange on RapidAPI", "https://rapidapi.com/adsbx/api/adsbexchange-com1"),
            ("Create OpenSky account", "https://opensky-network.org/login?view=registration"),
        ):
            actions.addWidget(self._link_button(text, url))
        actions.addStretch(1)
        layout.addLayout(actions)
        tests = self.QtWidgets.QHBoxLayout()
        test_as = self.QtWidgets.QPushButton("Test AviationStack")
        test_rapid = self.QtWidgets.QPushButton("Test RapidAPI")
        test_as.clicked.connect(self.test_aviationstack)
        test_rapid.clicked.connect(self.test_rapidapi)
        tests.addWidget(test_as)
        tests.addWidget(test_rapid)
        tests.addStretch(1)
        layout.addLayout(tests)

    def _build_diagnostics_page(self) -> None:
        _page, layout = self._page(
            "Bug Reporting & Diagnostics",
            "Choose how Local Flight may help report problems. Manual reports are always available; automatic crash reports stay sanitized and local-config gated.",
        )
        self.diagnostics_mode = self.QtWidgets.QComboBox()
        for label_text, mode in (
            ("Manual reports only", "manual"),
            ("Auto crash reports", "auto"),
            ("Auto crash reports + local logs", "auto_logs"),
        ):
            self.diagnostics_mode.addItem(label_text, mode)
        self.diagnostics_mode.hide()
        layout.addWidget(self.diagnostics_mode)

        cards = self.QtWidgets.QGridLayout()
        cards.setHorizontalSpacing(10)
        cards.setVerticalSpacing(10)
        for col, (mode, title, body) in enumerate(
            (
                ("manual", "Manual reports only", "You choose when to send a report from the Report screen. Automatic crash reports stay off."),
                ("auto", "Auto crash reports", "Send sanitized native crash diagnostics automatically when the GUI hits an uncaught error."),
                ("auto_logs", "Auto + recent local logs", "Also attach a short local log tail so hard crashes are easier to diagnose."),
            )
        ):
            button = self.QtWidgets.QPushButton(f"{title}\n{body}")
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setMinimumHeight(96)
            button.setMaximumWidth(285)
            button.clicked.connect(lambda _checked=False, m=mode: self._set_diagnostics_mode(m))
            self.diagnostics_buttons[mode] = button
            cards.addWidget(button, 0, col)
        layout.addLayout(cards)
        self.diagnostics_help = label(
            self.QtWidgets,
            "Privacy rule: no Linear keys, activation tokens, raw provider keys, pilot identities, or personal account data are shown here or sent from the client UI.",
            "Muted",
            wrap=True,
        )
        layout.addWidget(self.diagnostics_help)
        layout.addWidget(
            label(
                self.QtWidgets,
                "You can change this later in Settings. The setup wizard saves the choice now so first launch is explicit instead of silently unset.",
                "Muted",
                wrap=True,
            )
        )
        layout.addStretch(1)
        self._set_diagnostics_mode("manual")

    def _build_finish_page(self) -> None:
        _page, layout = self._page(
            "Ready to Launch",
            "This saves local configuration, writes the selected environment values, starts the scheduler, and opens the native display.",
        )
        self.finish_summary = label(self.QtWidgets, "", "Muted", wrap=True)
        self.diagnostics_note = label(
            self.QtWidgets,
            "Your bug-reporting choice is saved with setup. Manual reporting remains available from Report, and diagnostics can be changed later in Settings.",
            "Muted",
            wrap=True,
        )
        layout.addWidget(self.finish_summary)
        layout.addWidget(self.diagnostics_note)
        layout.addWidget(self._link_button("Open VATSIM status page", "https://status.vatsim.net/"))
        layout.addStretch(1)

    def _link_button(self, text: str, url: str) -> Any:
        button = self.QtWidgets.QPushButton(text)
        button.setObjectName("Quiet")
        button.clicked.connect(lambda _checked=False, u=url: webbrowser.open(u))
        return button

    def _set_step(self, index: int) -> None:
        index = max(0, min(index, self.tabs.count() - 1))
        self.tabs.setCurrentIndex(index)
        for idx, button in enumerate(self.step_buttons):
            button.setChecked(idx == index)
        self.back_btn.setEnabled(index > 0)
        self.next_btn.setVisible(index < self.tabs.count() - 1)
        self.finish_btn.setVisible(index == self.tabs.count() - 1)
        self._update_finish_summary()

    def _next_step(self) -> None:
        index = self.tabs.currentIndex()
        mode = self._current_mode()
        if index == 1 and mode in {"community", "virtual"}:
            self._set_step(3)
        else:
            self._set_step(index + 1)

    def _previous_step(self) -> None:
        index = self.tabs.currentIndex()
        if index == 3 and self._current_mode() in {"community", "virtual"}:
            self._set_step(1)
        else:
            self._set_step(index - 1)

    def _current_mode(self) -> str:
        return str(self.setup_mode.currentData() or "community")

    def _current_diagnostics_mode(self) -> str:
        if hasattr(self, "diagnostics_mode"):
            return str(self.diagnostics_mode.currentData() or "manual")
        return "manual"

    def _set_mode(self, mode: str) -> None:
        idx = self.setup_mode.findData(mode)
        self.setup_mode.setCurrentIndex(idx if idx >= 0 else 0)
        for key, button in self.source_buttons.items():
            button.setChecked(key == mode)
        self._sync_mode_ui()
        self._update_finish_summary()

    def _set_diagnostics_mode(self, mode: str) -> None:
        idx = self.diagnostics_mode.findData(mode)
        self.diagnostics_mode.setCurrentIndex(idx if idx >= 0 else 0)
        active_mode = self._current_diagnostics_mode()
        for key, button in self.diagnostics_buttons.items():
            button.setChecked(key == active_mode)
        if hasattr(self, "diagnostics_help"):
            if active_mode == "auto_logs":
                text = "Auto + logs is most useful during beta testing. Reports stay sanitized, and only a short local log tail is attached."
            elif active_mode == "auto":
                text = "Auto crash reporting sends sanitized exception details only when diagnostics allow it. Manual reports still work any time."
            else:
                text = "Manual mode is privacy-first: Local Flight only sends a report when you press Submit in the Report screen."
            self.diagnostics_help.setText(text)
        self._update_finish_summary()

    def _sync_mode_ui(self) -> None:
        mode = self._current_mode()
        self.relay_box.setVisible(mode == "community")
        if mode == "community":
            self.mode_help.setText("Recommended beta path. One hosted relay setup, shared airport snapshots, no provider key pasted into this client.")
            self.keys_hint.setText("Community relay mode skips provider keys. You can add enrichment keys later in Settings if needed.")
        elif mode == "byok":
            self.mode_help.setText("Direct local AviationStack mode. You own the provider quota and the app talks to AviationStack from this machine.")
            self.keys_hint.setText("Paste an AviationStack key here. RapidAPI/OpenSky are optional enrichment helpers.")
        else:
            self.mode_help.setText("Virtual mode uses VATSIM flight/network information. It is great for testing and never displays pilot identities.")
            self.keys_hint.setText("VATSIM needs no AviationStack key. This setup will save source=virtual and start the virtual fetch path.")

    def _update_finish_summary(self) -> None:
        if not hasattr(self, "finish_summary"):
            return
        mode = self._current_mode() if hasattr(self, "setup_mode") else "community"
        source = "virtual" if mode == "virtual" else "real"
        relay = self._clean_relay_display(self.relay_url.text()) if hasattr(self, "relay_url") else ""
        linked = "yes" if self._stored_activation or (hasattr(self, "activation_token") and self.activation_token.text().strip()) else "no"
        diagnostics = self._current_diagnostics_mode()
        self.finish_summary.setText(
            "\n".join(
                [
                    f"Airport: {self.airport_iata.text().strip().upper() or 'ZRH'} / {self.airport_icao.text().strip().upper() or 'LSZH'}",
                    f"Timezone: {self.timezone.text().strip() or 'Europe/Zurich'}",
                    f"Mode: {self._mode_label(mode)}",
                    f"Source: {source}",
                    f"Bug reporting: {self._diagnostics_label(diagnostics)}",
                    f"Relay linked: {linked}" if mode == "community" else "Relay linked: not used",
                    f"Relay host: {relay}" if mode == "community" else "",
                ]
            ).strip()
        )

    def _mode_label(self, mode: str) -> str:
        return {
            "community": "Community Relay",
            "byok": "BYOK AviationStack",
            "virtual": "Virtual / VATSIM",
        }.get(mode, mode)

    def _diagnostics_label(self, mode: str) -> str:
        return {
            "manual": "Manual reports only",
            "auto": "Auto crash reports",
            "auto_logs": "Auto crash reports + local logs",
            "unset": "Not chosen",
        }.get(mode, mode)

    def refresh(self) -> None:
        try:
            info = self.service.setup_client_info()
        except NativeApiError as exc:
            self.status.setText(f"Setup info unavailable: {exc}")
            self._set_mode("virtual")
            return
        if info.get("relay_url"):
            self.relay_url.setText(self._clean_relay_display(str(info.get("relay_url"))))
        prefix = str(info.get("activation_token_prefix") or "")
        self._stored_activation = bool(info.get("activation_token_present") or info.get("has_activation_token") or prefix)
        if self._stored_activation:
            self.activation_token.setPlaceholderText(f"Stored token linked ({prefix or 'hidden'}...)")
            self.relay_status.setText("Relay token is already stored on this install. You can finish Community setup without pasting it again.")
        if not self._mode_initialized:
            self._set_mode("community" if self._stored_activation else "virtual")
            self._mode_initialized = True
        self._update_finish_summary()

    def _clean_relay_display(self, value: str) -> str:
        clean = (value or "").strip().rstrip("/")
        for suffix in ("/v1/flights", "/v1/schedule", "/flights", "/schedule"):
            if clean.endswith(suffix):
                clean = clean[: -len(suffix)]
        return clean or "https://localflight-community-relay.fly.dev"

    def _toggle_secret(self, field: Any, button: Any, label_text: str) -> None:
        is_password = field.echoMode() == self.QtWidgets.QLineEdit.Password
        field.setEchoMode(self.QtWidgets.QLineEdit.Normal if is_password else self.QtWidgets.QLineEdit.Password)
        button.setText(("Hide " if is_password else "Show ") + label_text)

    def _start_airport_search(self) -> None:
        query = self.airport_search.text().strip()
        if len(query) < 2:
            return
        query_key = query.casefold()
        if query_key == self._last_airport_query:
            return
        self._last_airport_query = query_key
        if self._airport_search_future is not None and not self._airport_search_future.done():
            return
        self.airport_results.clear()
        self.airport_results.addItem("Searching airports...")
        self._airport_search_future = _API_EXECUTOR.submit(
            lambda: self.service.airport_search(query, limit=12)
        )
        self.search_poll_timer.start()

    def _poll_airport_search(self) -> None:
        future = self._airport_search_future
        if future is None or not future.done():
            return
        self.search_poll_timer.stop()
        self._airport_search_future = None
        try:
            payload = future.result()
        except Exception as exc:
            self.airport_results.clear()
            self.airport_results.addItem(f"Search failed: {exc}")
            return
        self.airport_results.clear()
        rows = list_payload(payload)
        if not rows:
            self.airport_results.addItem("No airport matches found.")
            return
        for row in rows:
            item = self.QtWidgets.QListWidgetItem(
                f"{row.get('iata') or '---'} / {row.get('icao') or '----'}  {row.get('name') or ''} - {row.get('city') or ''}"
            )
            item.setData(self.QtCore.Qt.UserRole, row)
            self.airport_results.addItem(item)

    def _select_airport_item(self, item: Any) -> None:
        row = item.data(self.QtCore.Qt.UserRole)
        if not isinstance(row, dict):
            return
        self.airport_iata.setText(str(row.get("iata") or "").upper())
        self.airport_icao.setText(str(row.get("icao") or "").upper())
        self.timezone.setText(str(row.get("timezone") or "UTC"))
        self.airport_search.blockSignals(True)
        self.airport_search.setText(f"{row.get('iata') or '---'} / {row.get('icao') or '----'}")
        self.airport_search.blockSignals(False)
        self._update_finish_summary()

    def _activation_payload(self) -> dict[str, Any]:
        return {
            "relay_url": self._clean_relay_display(self.relay_url.text()),
            "activation_token": self.activation_token.text().strip(),
            "airport_iata": self.airport_iata.text().strip().upper(),
            "airport_icao": self.airport_icao.text().strip().upper(),
            "display_name": self.display_name.text().strip(),
            "requested_mode": self._current_mode(),
        }

    def request_activation(self) -> None:
        try:
            result = self.service.setup_activate(self._activation_payload())
        except NativeApiError as exc:
            self.status.setText(f"Activation request failed: {exc}")
            return
        if result.get("activation_token_prefix"):
            self._stored_activation = True
            self.activation_token.clear()
            self.activation_token.setPlaceholderText(f"Stored token linked ({result.get('activation_token_prefix')}...)")
            self.relay_status.setText("Relay token received and stored locally. You can finish setup now.")
        self.status.setText(format_value(result.get("message") or result.get("status") or result))
        self._update_finish_summary()

    def check_activation_status(self) -> None:
        try:
            result = self.service.setup_client_status(self._activation_payload())
        except NativeApiError as exc:
            self.status.setText(f"Status check failed: {exc}")
            return
        self.status.setText(format_value(result.get("status") or result))

    def test_activation(self) -> None:
        try:
            result = self.service.setup_test_activation(self._activation_payload())
        except NativeApiError as exc:
            self.status.setText(f"Token test failed: {exc}")
            return
        self.status.setText("Activation token OK." if result.get("ok") else format_value(result))

    def test_aviationstack(self) -> None:
        key = self.aviationstack_key.text().strip()
        if not key:
            self.status.setText("Paste an AviationStack key first.")
            return
        self._test_key("/api/setup/test-aviationstack", key, "AviationStack")

    def test_rapidapi(self) -> None:
        key = self.rapidapi_key.text().strip()
        if not key:
            self.status.setText("Paste a RapidAPI key first.")
            return
        self._test_key("/api/setup/test-rapidapi", key, "RapidAPI")

    def _test_key(self, path: str, key: str, label_text: str) -> None:
        try:
            result = self.service.setup_test_provider_key(path, key)
        except NativeApiError as exc:
            self.status.setText(f"{label_text} test failed: {exc}")
            return
        self.status.setText(f"{label_text} key OK." if result.get("ok") else f"{label_text} rejected: {result.get('error') or result}")

    def finish_setup(self) -> None:
        mode = self._current_mode()
        payload = {
            "airport_iata": self.airport_iata.text().strip().upper() or "ZRH",
            "airport_icao": self.airport_icao.text().strip().upper() or "LSZH",
            "timezone": self.timezone.text().strip() or "Europe/Zurich",
            "source": "virtual" if mode == "virtual" else "real",
            "setup_mode": mode,
            "display_name": self.display_name.text().strip() or "Local Flight",
            "diagnostics_mode": self._current_diagnostics_mode(),
            "relay_url": self._clean_relay_display(self.relay_url.text()) if mode == "community" else "",
            "activation_token": self.activation_token.text().strip() if mode == "community" else "",
            "aviationstack_key": self.aviationstack_key.text().strip() if mode == "byok" else "",
            "rapidapi_key": self.rapidapi_key.text().strip() if mode == "byok" else "",
            "opensky_id": self.opensky_id.text().strip() if mode == "byok" else "",
            "opensky_secret": self.opensky_secret.text().strip() if mode == "byok" else "",
        }
        try:
            result = self.service.setup_complete(payload)
        except NativeApiError as exc:
            self.status.setText(f"Setup failed: {exc}")
            return
        self.status.setText("Setup complete. Opening the native display..." if result.get("ok", True) else format_value(result))
        if result.get("ok", True):
            try:
                self.service.clear_cache()
            except Exception:
                pass
            if self.on_setup_complete:
                self.on_setup_complete()


class RadarCanvas:  # pragma: no cover - optional Qt runtime
    def __new__(cls, QtCore: Any, QtGui: Any, QtWidgets: Any):
        class _Canvas(QtWidgets.QWidget):
            def __init__(self) -> None:
                super().__init__()
                self.setMouseTracking(True)
                self.setMinimumSize(260, 260)
                self.blips: list[dict[str, Any]] = []
                self.surface: list[dict[str, Any]] = []
                self.center = {"lat": 0.0, "lon": 0.0}
                self.radius_nm = 5.0
                self.status = "No radar data yet"
                self.attribution = ""
                self.sweep_angle = 0.0
                self.colors = colors_for()
                self._surface_version = 0
                self._surface_projection_key: tuple[Any, ...] | None = None
                self._surface_projection: list[tuple[str, str, list[Any]]] = []
                self._sweep_timer = QtCore.QTimer(self)
                self._sweep_interval_ms = 100
                self._sweep_timer.timeout.connect(self._tick_sweep)

            def showEvent(self, event: Any) -> None:
                super().showEvent(event)
                if not self._sweep_timer.isActive():
                    self._sweep_timer.start(self._sweep_interval_ms)

            def hideEvent(self, event: Any) -> None:
                super().hideEvent(event)
                self._sweep_timer.stop()

            def apply_theme(self, theme: str, skin: str) -> None:
                self.colors = colors_for(theme, skin)
                self.update()

            def set_payload(self, payload: dict[str, Any]) -> None:
                old_key = (self.radius_nm, self.center.get("lat"), self.center.get("lon"))
                self.blips = [b for b in payload.get("blips", []) if isinstance(b, dict)]
                self.radius_nm = float(payload.get("radius_nm") or self.radius_nm)
                center = payload.get("center") if isinstance(payload.get("center"), dict) else {}
                if center:
                    self.center = {
                        "lat": float(center.get("lat") or self.center.get("lat") or 0.0),
                        "lon": float(center.get("lon") or self.center.get("lon") or 0.0),
                    }
                new_key = (self.radius_nm, self.center.get("lat"), self.center.get("lon"))
                if new_key != old_key:
                    self._surface_projection_key = None
                self.status = f"{len(self.blips)} blips | {payload.get('source', 'unknown')}"
                self.update()

            def set_surface(self, payload: dict[str, Any]) -> None:
                self.surface = [f for f in payload.get("features", []) if isinstance(f, dict)]
                center = payload.get("center") if isinstance(payload.get("center"), dict) else {}
                self.center = {
                    "lat": float(center.get("lat") or self.center.get("lat") or 0.0),
                    "lon": float(center.get("lon") or self.center.get("lon") or 0.0),
                }
                attribution = payload.get("attribution") if isinstance(payload.get("attribution"), dict) else {}
                self.attribution = str(attribution.get("text") or ("Estimated airport surface" if self.surface else ""))
                self._surface_version += 1
                self._surface_projection_key = None
                self.update()

            def _tick_sweep(self) -> None:
                self.sweep_angle = (self.sweep_angle + 2.4) % 360.0
                self.update()

            def paintEvent(self, _event: Any) -> None:
                painter = QtGui.QPainter(self)
                painter.setRenderHint(QtGui.QPainter.Antialiasing)
                rect = self.rect()
                painter.fillRect(rect, QtGui.QColor(self.colors["panel_2"]))
                size = min(rect.width(), rect.height()) - 18
                cx = rect.center().x()
                cy = rect.center().y()
                radius = size / 2
                self._draw_surface(painter, QtCore, QtGui, cx, cy, radius)
                grid = QtGui.QColor(self.colors["blue"])
                grid.setAlpha(130)
                painter.setPen(QtGui.QPen(grid, 1))
                for frac in (0.25, 0.5, 0.75, 1.0):
                    r = radius * frac
                    painter.drawEllipse(QtCore.QPointF(cx, cy), r, r)
                    painter.drawText(int(cx + r + 5), int(cy - 4), f"{self.radius_nm * frac:.0f}nm")
                painter.drawLine(cx - radius, cy, cx + radius, cy)
                painter.drawLine(cx, cy - radius, cx, cy + radius)
                painter.setPen(QtGui.QColor(self.colors["muted"]))
                painter.drawText(int(cx - 4), int(cy - radius + 18), "N")
                painter.drawText(int(cx + radius - 18), int(cy + 4), "E")
                painter.drawText(int(cx - 4), int(cy + radius - 8), "S")
                painter.drawText(int(cx - radius + 8), int(cy + 4), "W")
                self._draw_sweep(painter, QtCore, QtGui, cx, cy, radius)
                painter.setPen(QtGui.QPen(QtGui.QColor(self.colors["cyan"]), 2))
                for blip in self.blips:
                    if blip.get("lat") is not None and blip.get("lon") is not None:
                        x_nm, y_nm = self._latlon_to_nm(float(blip["lat"]), float(blip["lon"]))
                        if math.hypot(x_nm, y_nm) > self.radius_nm:
                            continue
                    pos = self._blip_pos(blip, cx, cy, radius)
                    alpha = self._blip_alpha(blip)
                    color = QtGui.QColor(self.colors["cyan"])
                    color.setAlpha(alpha)
                    painter.setPen(QtGui.QPen(color, 2))
                    painter.setBrush(color)
                    painter.drawEllipse(QtCore.QPointF(pos[0], pos[1]), 4.5, 4.5)
                    callsign = str(blip.get("callsign") or "").strip()
                    if callsign and self.radius_nm <= 10:
                        painter.setPen(QtGui.QColor(self.colors["text"]))
                        painter.drawText(int(pos[0] + 8), int(pos[1] - 6), callsign[:10])
                    heading = blip.get("heading")
                    speed = float(blip.get("speed_ms") or 0.0)
                    if heading is not None and speed > 2:
                        hr = math.radians(float(heading) - 90.0)
                        painter.drawLine(pos[0], pos[1], pos[0] + math.cos(hr) * 22, pos[1] + math.sin(hr) * 22)
                    painter.setBrush(QtCore.Qt.NoBrush)
                painter.setPen(QtGui.QColor(self.colors["muted"]))
                painter.drawText(14, rect.height() - 14, self.status)
                if self.attribution:
                    painter.drawText(rect.width() - 320, rect.height() - 14, self.attribution[:48])

            def mouseMoveEvent(self, event: Any) -> None:
                rect = self.rect()
                size = min(rect.width(), rect.height()) - 18
                cx = rect.center().x()
                cy = rect.center().y()
                radius = size / 2
                hit = ""
                for blip in self.blips:
                    x, y = self._blip_pos(blip, cx, cy, radius)
                    if math.hypot(event.position().x() - x, event.position().y() - y) <= 10:
                        hit = self._tooltip_for_blip(blip)
                        break
                self.setToolTip(hit)

            def _tooltip_for_blip(self, blip: dict[str, Any]) -> str:
                callsign = str(blip.get("callsign") or blip.get("hex") or "aircraft").strip()
                route = " -> ".join(str(v) for v in (blip.get("departure_icao"), blip.get("arrival_icao")) if v)
                details = [callsign]
                if route:
                    details.append(route)
                aircraft = blip.get("aircraft_type") or blip.get("type")
                if aircraft:
                    details.append(str(aircraft))
                altitude = self._tooltip_altitude(blip.get("altitude_m"))
                speed = self._tooltip_speed(blip.get("speed_ms"))
                if altitude:
                    details.append(altitude)
                if speed:
                    details.append(speed)
                if blip.get("heading") is not None:
                    try:
                        details.append(f"HDG {int(round(float(blip.get('heading')))) % 360}")
                    except (TypeError, ValueError):
                        pass
                if blip.get("distance_nm") is not None:
                    details.append(f"{format_value(blip.get('distance_nm'))}nm")
                if str(blip.get("source") or "").lower() == "vatsim":
                    if blip.get("flight_rules"):
                        details.append(f"Rules {blip.get('flight_rules')}")
                    if blip.get("planned_altitude"):
                        details.append(f"Planned alt {blip.get('planned_altitude')}")
                    if blip.get("cruise_tas"):
                        details.append(f"TAS {blip.get('cruise_tas')}")
                    if blip.get("route"):
                        details.append(str(blip.get("route"))[:80])
                source = blip.get("source")
                if source:
                    details.append(str(source))
                return " | ".join(details)

            def _tooltip_altitude(self, value: Any) -> str:
                try:
                    meters = float(value)
                except (TypeError, ValueError):
                    return ""
                return f"{int(round(meters * 3.28084))} ft"

            def _tooltip_speed(self, value: Any) -> str:
                try:
                    meters_s = float(value)
                except (TypeError, ValueError):
                    return ""
                return f"{int(round(meters_s * 1.94384))} kt"

            def _blip_pos(self, blip: dict[str, Any], cx: float, cy: float, radius: float) -> tuple[float, float]:
                if blip.get("lat") is not None and blip.get("lon") is not None:
                    x_nm, y_nm = self._latlon_to_nm(float(blip["lat"]), float(blip["lon"]))
                    return cx + (x_nm / max(0.1, self.radius_nm)) * radius, cy - (y_nm / max(0.1, self.radius_nm)) * radius
                dist = float(blip.get("distance_nm") or 0.0)
                bearing = math.radians(float(blip.get("bearing_deg") or 0.0))
                frac = min(1.0, dist / max(0.1, self.radius_nm))
                return cx + math.sin(bearing) * radius * frac, cy - math.cos(bearing) * radius * frac

            def _blip_angle(self, blip: dict[str, Any]) -> float:
                if blip.get("lat") is not None and blip.get("lon") is not None:
                    x_nm, y_nm = self._latlon_to_nm(float(blip["lat"]), float(blip["lon"]))
                    return (math.degrees(math.atan2(x_nm, y_nm)) + 360.0) % 360.0
                return float(blip.get("bearing_deg") or 0.0) % 360.0

            def _blip_alpha(self, blip: dict[str, Any]) -> int:
                if blip.get("on_ground"):
                    return 150
                age = (self.sweep_angle - self._blip_angle(blip) + 360.0) % 360.0
                if age > 350 or age < 30:
                    return 255
                return max(45, int(255 - ((age - 30.0) / 310.0) * 210))

            def _draw_sweep(self, painter: Any, QtCore: Any, QtGui: Any, cx: float, cy: float, radius: float) -> None:
                painter.save()
                painter.translate(cx, cy)
                painter.rotate(self.sweep_angle)
                for idx in range(18):
                    color = QtGui.QColor(self.colors["sweep"])
                    color.setAlpha(max(0, int((1 - idx / 18) * 28)))
                    painter.setBrush(color)
                    painter.setPen(QtCore.Qt.NoPen)
                    path = QtGui.QPainterPath()
                    path.moveTo(0, 0)
                    path.arcTo(-radius, -radius, radius * 2, radius * 2, -idx * 4, -4)
                    path.closeSubpath()
                    painter.drawPath(path)
                line = QtGui.QColor(self.colors["sweep"])
                line.setAlpha(180)
                painter.setBrush(QtCore.Qt.NoBrush)
                painter.setPen(QtGui.QPen(line, 1.5))
                painter.drawLine(0, 0, 0, -radius)
                painter.restore()

            def _draw_surface(self, painter: Any, QtCore: Any, QtGui: Any, cx: float, cy: float, radius: float) -> None:
                if not self.surface:
                    return
                colors = {
                    "boundary": _qcolor_alpha(QtGui, self.colors["blue"], 110),
                    "runway": _qcolor_alpha(QtGui, self.colors["cyan"], 180),
                    "taxiway": _qcolor_alpha(QtGui, self.colors["blue"], 120),
                    "apron": _qcolor_alpha(QtGui, self.colors["blue"], 45),
                    "terminal": _qcolor_alpha(QtGui, self.colors["amber"], 55),
                    "building": _qcolor_alpha(QtGui, self.colors["amber"], 65),
                }
                for kind, runway_label, poly in self._projected_surface(QtCore, cx, cy, radius):
                    if len(poly) < 2:
                        continue
                    pen = QtGui.QPen(colors.get(kind, colors["taxiway"]), 2 if kind == "runway" else 1)
                    painter.setPen(pen)
                    if kind in {"apron", "terminal", "building"} and len(poly) >= 3:
                        painter.setBrush(colors.get(kind, colors["apron"]))
                        painter.drawPolygon(poly)
                        painter.setBrush(QtCore.Qt.NoBrush)
                    else:
                        for idx in range(1, len(poly)):
                            painter.drawLine(poly[idx - 1], poly[idx])
                    if kind == "runway" and runway_label and len(poly) >= 2:
                        mid = poly[len(poly) // 2]
                        painter.setPen(QtGui.QColor(self.colors["text"]))
                        painter.drawText(mid, runway_label[:12])

            def _projected_surface(self, QtCore: Any, cx: float, cy: float, radius: float) -> list[tuple[str, str, list[Any]]]:
                key = (
                    self._surface_version,
                    round(cx, 1),
                    round(cy, 1),
                    round(radius, 1),
                    round(float(self.radius_nm), 3),
                    round(float(self.center.get("lat") or 0.0), 6),
                    round(float(self.center.get("lon") or 0.0), 6),
                )
                if key == self._surface_projection_key:
                    return self._surface_projection
                projected: list[tuple[str, str, list[Any]]] = []
                scale_radius = max(0.1, float(self.radius_nm))
                for feature in self.surface:
                    points = feature.get("points")
                    if not isinstance(points, list) or len(points) < 2:
                        continue
                    kind = str(feature.get("kind") or "taxiway")
                    poly = []
                    for point in points:
                        if not isinstance(point, list) or len(point) < 2:
                            continue
                        try:
                            x_nm, y_nm = self._latlon_to_nm(float(point[0]), float(point[1]))
                        except (TypeError, ValueError):
                            continue
                        poly.append(QtCore.QPointF(cx + (x_nm / scale_radius) * radius, cy - (y_nm / scale_radius) * radius))
                    if len(poly) >= 2:
                        projected.append((kind, str(feature.get("label") or ""), poly))
                self._surface_projection_key = key
                self._surface_projection = projected
                return projected

            def _latlon_to_nm(self, lat: float, lon: float) -> tuple[float, float]:
                lat0 = float(self.center.get("lat") or 0.0)
                lon0 = float(self.center.get("lon") or 0.0)
                y_nm = (lat - lat0) * 60.0
                x_nm = (lon - lon0) * 60.0 * math.cos(math.radians(lat0))
                return x_nm, y_nm

        return _Canvas()


class RadarScreen(_AsyncFetchMixin):  # pragma: no cover - optional Qt runtime
    def __init__(self, QtCore: Any, QtGui: Any, QtWidgets: Any, client: LocalApiClient, *, embedded: bool = False) -> None:
        self.QtWidgets = QtWidgets
        self.embedded = embedded
        self.client = client
        self.service = NativeApiService(client)
        self.widget = QtWidgets.QFrame()
        self._init_async(QtCore, self.widget)
        self.widget.setObjectName("Page")
        layout = QtWidgets.QVBoxLayout(self.widget)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        top = QtWidgets.QHBoxLayout()
        self.title = label(QtWidgets, "Radar range" if embedded else "Radar", "Kicker" if embedded else "Title")
        top.addWidget(self.title)
        top.addStretch(1)
        self.range_buttons: dict[int, Any] = {}
        for radius in (1, 2, 3, 5, 10, 20, 40):
            button = QtWidgets.QPushButton(f"{radius}nm")
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, r=radius: self.set_radius(r))
            self.range_buttons[radius] = button
            top.addWidget(button)
        refresh = QtWidgets.QPushButton("Refresh radar")
        refresh.clicked.connect(self.refresh)
        top.addWidget(refresh)
        self.weather = _strip(QtWidgets, "Loading weather...")
        self.canvas = lazy_symbol("localflight.native.canvas.radar", "RadarCanvas")(QtCore, QtGui, QtWidgets)
        self.status = label(QtWidgets, "Initialising radar...", "Muted")
        layout.addLayout(top)
        layout.addWidget(self.weather)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.status)
        self.radius_nm = 20
        self._sync_range_buttons()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def apply_theme(self, theme: str, skin: str) -> None:
        if hasattr(self.canvas, "apply_theme"):
            self.canvas.apply_theme(theme, skin)

    def set_radius(self, radius: int) -> None:
        self.radius_nm = radius
        self._sync_range_buttons()
        self.refresh()

    def _sync_range_buttons(self) -> None:
        for radius, button in self.range_buttons.items():
            button.setChecked(radius == self.radius_nm)

    def refresh(self) -> None:
        radius = self.radius_nm
        started = self._run_async(
            lambda: self._fetch_radar(radius),
            self._apply_radar,
            lambda exc: self.status.setText(f"Radar fetch failed: {exc}"),
            label=f"radar.{radius}nm",
        )
        if started:
            self.status.setText(f"Loading {radius}nm radar without blocking the UI...")

    def handle_live_event(self, payload: dict[str, Any]) -> None:
        event_type = str(payload.get("type") or "")
        if event_type in {"snapshot_updated", "scheduler_restarted", "config_updated"}:
            self.refresh()

    def set_active(self, active: bool) -> None:
        timer = getattr(self.canvas, "_sweep_timer", None)
        if timer is None:
            return
        if active:
            if not timer.isActive():
                timer.start(getattr(self.canvas, "_sweep_interval_ms", 100))
        else:
            timer.stop()

    def _fetch_radar(self, radius: int) -> dict[str, Any]:
        radar = self.service.radar(radius_nm=float(radius), include_surface=True)
        return {
            "payload": radar.payload,
            "surface": radar.surface,
            "surface_error": radar.surface_error,
            "weather": radar.weather,
        }

    def _apply_radar(self, result: dict[str, Any]) -> None:
        payload = result["payload"]
        if isinstance(result.get("surface"), dict):
            self.canvas.set_surface(result["surface"])
        if isinstance(result.get("weather"), dict):
            self.weather.findChild(self.QtWidgets.QLabel).setText(_weather_line(result["weather"], raw=True))
        self.canvas.set_payload(payload)
        hidden_airborne = int(payload.get("airborne_filtered") or payload.get("hidden_airborne_count") or 0)
        hidden_ground = int(payload.get("ground_filtered") or payload.get("hidden_ground_count") or 0)
        hidden = f" | {hidden_airborne} airborne hidden" if hidden_airborne else (f" | {hidden_ground} ground hidden" if hidden_ground else "")
        raw_provider_count = int(payload.get("raw_provider_count") or payload.get("count") or 0)
        provider_radius = float(payload.get("provider_radius_nm") or payload.get("radius_nm") or self.radius_nm)
        crop_note = f" | cropped from {raw_provider_count} @ {provider_radius:g}nm" if provider_radius > float(payload.get("radius_nm") or self.radius_nm) else ""
        surface_note = f" | surface unavailable: {result['surface_error']}" if result.get("surface_error") else ""
        self.status.setText(
            f"{payload.get('count', 0)} visible | mode {payload.get('radar_mode', 'airborne')} | "
            f"source {payload.get('source', 'unknown')}{hidden}{crop_note}{surface_note}"
        )


class DisplayScreen:  # pragma: no cover - optional Qt runtime
    def __init__(self, QtCore: Any, QtGui: Any, QtWidgets: Any, client: LocalApiClient) -> None:
        self.QtCore = QtCore
        self.QtWidgets = QtWidgets
        self.settings = QtCore.QSettings("LocalFlight", "Native")
        self.widget = QtWidgets.QFrame()
        self.widget.setObjectName("Page")
        layout = QtWidgets.QVBoxLayout(self.widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        top = QtWidgets.QHBoxLayout()
        self.mode_buttons: dict[str, Any] = {}
        for key, text in (("fids", "\U0001F6EB  FIDS"), ("split", "\U0001F4FA  Split"), ("radar", "\U0001F6F0  Radar")):
            button = QtWidgets.QPushButton(text)
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, k=key: self.set_mode(k))
            self.mode_buttons[key] = button
            top.addWidget(button)
        top.addStretch(1)
        self.live_dot = label(QtWidgets, chr(9679), "LiveDot")
        self.live = label(QtWidgets, "Live push: local refresh", "Muted")
        fullscreen = QtWidgets.QPushButton("Fullscreen")
        fullscreen.setObjectName("Quiet")
        fullscreen.clicked.connect(self.toggle_fullscreen)
        top.addWidget(self.live_dot)
        top.addWidget(self.live)
        top.addWidget(fullscreen)
        self.splitter = QtWidgets.QSplitter()
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setMinimumWidth(0)
        self.fids = lazy_symbol("localflight.native.pages.fids", "FidsScreen")(
            QtCore, QtGui, QtWidgets, client, embedded=True
        )
        self.radar = lazy_symbol("localflight.native.pages.radar", "RadarScreen")(
            QtCore, QtGui, QtWidgets, client, embedded=True
        )
        _as_widget(self.fids).setMinimumWidth(0)
        _as_widget(self.radar).setMinimumWidth(0)
        _as_widget(self.fids).setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        _as_widget(self.radar).setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.splitter.addWidget(_as_widget(self.fids))
        self.splitter.addWidget(_as_widget(self.radar))
        saved = self.settings.value("display/splitter_sizes")
        if isinstance(saved, list) and len(saved) == 2:
            self.splitter.setSizes([int(saved[0]), int(saved[1])])
        else:
            self.splitter.setSizes([620, 420])
        self.splitter.splitterMoved.connect(lambda *_args: self._save_splitter())
        layout.addLayout(top)
        layout.addWidget(self.splitter, 1)
        geometry = _screen_available_geometry(QtWidgets, self.widget)
        screen_width = geometry.width() if geometry is not None else None
        saved_mode = str(self.settings.value("display/mode") or "").strip().lower()
        if saved_mode not in {"fids", "split", "radar"} or (saved_mode == "split" and default_display_mode(screen_width) != "split"):
            saved_mode = default_display_mode(screen_width)
        self.mode = saved_mode
        self.set_mode(saved_mode)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def apply_theme(self, theme: str, skin: str) -> None:
        self.fids.apply_theme(theme, skin)
        self.radar.apply_theme(theme, skin)

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        for key, button in self.mode_buttons.items():
            button.setChecked(key == mode)
        _as_widget(self.fids).setVisible(mode in {"fids", "split"})
        _as_widget(self.radar).setVisible(mode in {"radar", "split"})
        self.set_active(_as_widget(self).isVisible())
        self.settings.setValue("display/mode", mode)

    def _save_splitter(self) -> None:
        self.settings.setValue("display/splitter_sizes", self.splitter.sizes())

    def toggle_fullscreen(self) -> None:
        window = self.widget.window()
        if window.isFullScreen():
            window.showNormal()
        else:
            window.showFullScreen()

    def refresh(self) -> None:
        if self.mode in {"fids", "split"}:
            self.fids.refresh()
        if self.mode in {"radar", "split"}:
            self.radar.refresh()

    def set_active(self, active: bool) -> None:
        self.fids.set_active(active and self.mode in {"fids", "split"})
        self.radar.set_active(active and self.mode in {"radar", "split"})

    def handle_live_event(self, payload: dict[str, Any]) -> None:
        self.live.setText(f"Live push: {payload.get('type', 'event')}")
        if self.mode in {"fids", "split"}:
            self.fids.handle_live_event(payload)
        if self.mode in {"radar", "split"}:
            self.radar.handle_live_event(payload)


class MatrixCanvas:  # pragma: no cover - optional Qt runtime
    def __new__(cls, QtCore: Any, QtGui: Any, QtWidgets: Any):
        class _Canvas(QtWidgets.QWidget):
            FLAP_CHARS = " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.:/-+()>"

            def __init__(self) -> None:
                super().__init__()
                self.setMinimumHeight(260)
                self.rows: list[dict[str, Any]] = []
                self.panel_w = 256
                self.panel_h = 64
                self.brightness = 0.8
                self.zoom = 4
                self.animate = True
                self.animation_mode = "split_flap"
                self.animation_speed = 3
                self.status_animation_enabled = True
                self.show_weather = True
                self.show_gate_info = True
                self.preset = "real_fids"
                self.max_rows = 4
                self.phase = 0
                self.target_lines: list[str] = []
                self.display_lines: list[str] = []
                self.slide_source_lines: list[str] = []
                self.slide_frame = 0
                self.slide_frames = 1
                self.row_statuses: list[str] = []
                self.row_details: list[str] = []
                self.codeshare_cycle = -1
                self.metar: dict[str, Any] | None = None
                self.pages: dict[str, Any] | None = None
                self.weather_page: dict[str, Any] | None = None
                self.message = ""
                self.airport_iata = "LOCAL"
                self.airport_label = "LOCAL"
                self.view = "departures"
                self.clock_utc_epoch: int | None = None
                self.clock_sync_monotonic = time.monotonic()
                self.clock_offset_minutes = 0
                self.colors = colors_for()
                self.timer = QtCore.QTimer(self)
                self.timer.timeout.connect(self._tick)

            def showEvent(self, event: Any) -> None:
                super().showEvent(event)
                if not self.timer.isActive():
                    self.timer.start(250)

            def hideEvent(self, event: Any) -> None:
                super().hideEvent(event)
                self.timer.stop()

            def apply_theme(self, theme: str, skin: str) -> None:
                self.colors = colors_for(theme, skin)
                self.update()

            def set_rows(self, rows: list[dict[str, Any]]) -> None:
                self.rows = rows
                self._retarget_lines()
                self.update()

            def set_metar(self, metar: dict[str, Any] | None) -> None:
                self.metar = metar if isinstance(metar, dict) else None
                self.update()

            def set_matrix_payload(self, payload: dict[str, Any] | None) -> None:
                payload = payload if isinstance(payload, dict) else {}
                self.metar = payload.get("metar") if isinstance(payload.get("metar"), dict) else None
                self.pages = payload.get("pages") if isinstance(payload.get("pages"), dict) else None
                self.weather_page = payload.get("weather_page") if isinstance(payload.get("weather_page"), dict) else None
                self.message = str(payload.get("message") or "").upper()
                self.airport_iata = str(payload.get("airport_iata") or self.airport_iata or "LOCAL").upper()
                self.airport_label = str(payload.get("airport_label") or payload.get("airport_iata") or self.airport_label or "LOCAL").upper()
                payload_view = str(payload.get("view") or self.view or "departures").lower()
                self.view = payload_view if payload_view in {"departures", "arrivals"} else "departures"
                try:
                    if payload.get("clock_utc_epoch") is not None:
                        self.clock_utc_epoch = int(payload.get("clock_utc_epoch"))
                        self.clock_sync_monotonic = time.monotonic()
                        self.clock_offset_minutes = int(payload.get("clock_local_offset_minutes") or 0)
                except Exception:
                    pass
                self.update()

            def set_options(
                self,
                *,
                panel_w: int,
                panel_h: int,
                brightness: float,
                zoom: int,
                animate: bool,
                animation_mode: str = "split_flap",
                animation_speed: int = 3,
                status_animation_enabled: bool = True,
                show_weather: bool = True,
                show_gate_info: bool = True,
                preset: str = "real_fids",
                max_rows: int = 4,
            ) -> None:
                old_mode = self.animation_mode
                self.panel_w = panel_w
                self.panel_h = panel_h
                self.brightness = brightness
                self.zoom = zoom
                self.animation_mode = animation_mode if animation_mode in {"split_flap", "slide_left", "slide_right", "static"} else "split_flap"
                self.animation_speed = max(1, min(5, int(animation_speed or 3)))
                self.status_animation_enabled = bool(status_animation_enabled)
                self.show_weather = bool(show_weather)
                self.preset = preset or "real_fids"
                self.show_gate_info = bool(show_gate_info) and not self._is_vatsim_preset()
                self.animate = animate and self.animation_mode != "static"
                self.max_rows = max(1, min(8, int(max_rows or 4)))
                self.setMinimumHeight(max(260, int(self.panel_h * max(2, self.zoom) + 96)))
                if old_mode != self.animation_mode:
                    self.display_lines = []
                    self.slide_source_lines = []
                self.timer.setInterval(max(35, 220 - self.animation_speed * 32))
                self._retarget_lines(force=old_mode != self.animation_mode)
                self.update()

            def _tick(self) -> None:
                self.phase = (self.phase + 1) % 24
                next_codeshare_cycle = int(time.monotonic() // 4)
                if next_codeshare_cycle != self.codeshare_cycle and self._page_has_codeshares():
                    self.codeshare_cycle = next_codeshare_cycle
                    self._retarget_lines(force=True)
                if not self.animate:
                    self.update()
                    return
                changed = False
                if self.animation_mode in {"slide_left", "slide_right"}:
                    if self.slide_frame < self.slide_frames:
                        self.slide_frame += 1
                        self.display_lines = [
                            self._slide_line(old, target)
                            for old, target in zip(self.slide_source_lines, self.target_lines)
                        ]
                        changed = True
                    else:
                        self.display_lines = list(self.target_lines)
                else:
                    next_lines: list[str] = []
                    for current, target in zip(self.display_lines, self.target_lines):
                        next_line, line_changed = self._advance_line(current, target)
                        next_lines.append(next_line)
                        changed = changed or line_changed
                    if changed:
                        self.display_lines = next_lines
                self.update()

            def _retarget_lines(self, *, force: bool = False) -> None:
                source_rows = self.rows[: self._visible_rows()]
                if not source_rows:
                    source_rows = [
                        {
                            "display_time": "--:--",
                            "flight_display": "LOCAL",
                            "route_display": "WAITING",
                            "status_display": "READY",
                            "gate": "-",
                        }
                    ]
                self.target_lines = [self._row_line(row) for row in source_rows]
                self.row_statuses = [str(row.get("status_kind") or row.get("status_class") or row.get("status_display") or row.get("status") or "") for row in source_rows]
                self.row_details = [self._detail_line(row) for row in source_rows]
                if len(self.display_lines) != len(self.target_lines):
                    self.display_lines = [" " * len(line) for line in self.target_lines]
                    force = True
                if self.animation_mode in {"slide_left", "slide_right"} and (force or self.display_lines != self.target_lines):
                    self.slide_source_lines = [line.ljust(len(target))[:len(target)] for line, target in zip(self.display_lines, self.target_lines)]
                    self.slide_frame = 0
                    self.slide_frames = max(4, 16 - self.animation_speed * 2)
                if not self.animate:
                    self.display_lines = list(self.target_lines)

            def _clean_flight_number(self, value: Any) -> str:
                text = (format_value(value) or "")
                text = text.replace("Sold as ", "").replace("SOLD AS ", "")
                text = text.replace("Also ", "").replace("ALSO ", "").replace(",", " ").replace("|", " ").strip()
                if not text or text.startswith("+"):
                    return ""
                parts = text.split()
                if len(parts) >= 2:
                    return f"{parts[0]} {parts[1]}"
                return parts[0] if parts else ""

            def _codeshare_flights(self, row: dict[str, Any]) -> list[str]:
                values: list[str] = []
                for key in ("codeshares", "codeshare_display", "codeshare", "sold_as"):
                    raw = row.get(key)
                    if not raw:
                        continue
                    parts = raw if isinstance(raw, list) else (
                        str(raw)
                        .replace("Sold as ", "")
                        .replace("SOLD AS ", "")
                        .replace("Also ", "")
                        .replace("ALSO ", "")
                        .replace("|", "/")
                        .replace(",", "/")
                        .split("/")
                    )
                    for part in parts:
                        code = self._clean_flight_number(part)
                        if code and code not in values:
                            values.append(code)
                return values

            def _page_has_codeshares(self) -> bool:
                return False

            def _visible_rows(self) -> int:
                if self.panel_w < 180:
                    return max(1, min(self.max_rows, (self.panel_h - self._header_height()) // 27))
                return self.max_rows

            def _flight_cycle_display(self, row: dict[str, Any]) -> str:
                primary = self._clean_flight_number(
                    row.get("matrix_flight_label")
                    or row.get("flight_display")
                    or row.get("flight")
                    or row.get("flight_number")
                )
                if primary:
                    return primary
                return self._clean_flight_number(row.get("operating_callsign") or row.get("callsign")) or "-"

            def fit(self, value: Any, length: int) -> str:
                return self._ascii(value).upper().ljust(length)[:length]

            def marquee(self, value: Any, width: int) -> str:
                text = self._ascii(value).upper()
                if len(text) <= width:
                    return text.ljust(width)
                canvas = text + "   "
                start = int(time.monotonic() * 3) % len(canvas)
                return (canvas + canvas)[start:start + width]

            def code_preserve(self, value: Any, code: Any, width: int) -> str:
                text = self._ascii(value).upper()
                code_text = self._ascii(code).upper()
                if not code_text or code_text in text[:width] or len(text) <= width:
                    return text.ljust(width)[:width]
                if len(code_text) >= width:
                    return code_text[:width]
                return f"{text[: max(0, width - len(code_text) - 1)].strip()} {code_text}".strip().ljust(width)[:width]

            def cycle_chunks(self, value: Any, width: int, code: Any = "") -> str:
                text = self._ascii(value).replace("(", " ").replace(")", " ").upper().strip()
                code_text = self._ascii(code).upper().strip()
                if not text:
                    return (code_text or "-").ljust(width)[:width]
                if len(text) <= width:
                    return self.code_preserve(text, code_text, width)
                chunks: list[str] = []
                current = ""
                for raw in text.split():
                    word = raw[:width] if len(raw) > width else raw
                    if not current:
                        current = word
                    elif len(current) + 1 + len(word) <= width:
                        current += f" {word}"
                    else:
                        chunks.append(current)
                        current = word
                if current:
                    chunks.append(current)
                if code_text and not any(code_text in chunk for chunk in chunks):
                    chunks.append(code_text[:width])
                slot = int(time.monotonic() // 3) % max(1, len(chunks))
                return self.code_preserve(chunks[slot], code_text if slot == len(chunks) - 1 else "", width)

            def _route_fields(self, row: dict[str, Any]) -> tuple[str, str]:
                label = self._ascii(row.get("matrix_route_label") or row.get("route_matrix_label") or row.get("route_display") or row.get("route") or "-")
                code = self._ascii(row.get("route_code") or "")
                if not code:
                    match = re.search(r"\(([A-Z0-9]{3,4})\)\s*$", label.upper())
                    if match:
                        code = match.group(1)
                        label = re.sub(r"\s*\([A-Za-z0-9]{3,4}\)\s*$", "", label).strip() + f" {code}"
                return label.upper(), code.upper()

            def _ascii(self, value: Any) -> str:
                text = format_value(value) or ""
                replacements = {
                    "\u00c4": "AE", "\u00d6": "OE", "\u00dc": "UE", "\u00e4": "AE", "\u00f6": "OE", "\u00fc": "UE",
                    "\u00df": "SS", "\u00c6": "AE", "\u00e6": "AE", "\u0152": "OE", "\u0153": "OE", "\u00d8": "O", "\u00f8": "O",
                }
                text = "".join(replacements.get(ch, ch) for ch in text)
                return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")

            def _clock_text(self, compact: bool = False) -> str:
                if self.clock_utc_epoch is None:
                    now_utc = datetime.now(timezone.utc)
                else:
                    elapsed = max(0, time.monotonic() - self.clock_sync_monotonic)
                    now_utc = datetime.fromtimestamp(self.clock_utc_epoch + elapsed, timezone.utc)
                local = datetime.fromtimestamp(now_utc.timestamp() + self.clock_offset_minutes * 60, timezone.utc)
                if compact:
                    return f"U{now_utc:%H:%M} L{local:%H:%M}"
                return f"UTC{now_utc:%H:%M} LT{local:%H:%M}"

            def _weather_line(self, chars: int = 18) -> str:
                if not self.show_weather or not isinstance(self.metar, dict):
                    return ""
                condition = (
                    self.metar.get("matrix_weather_label")
                    or self.metar.get("condition_display")
                    or self.metar.get("weather_label")
                    or self.metar.get("summary")
                    or self.metar.get("weather_display")
                    or ""
                )
                temp = (
                    self.metar.get("matrix_weather_temp")
                    or self.metar.get("temperature_short")
                    or self.metar.get("temperature_display")
                    or self.metar.get("temp_c")
                    or self.metar.get("temperature_c")
                    or ""
                )
                temp_s = str(temp).replace(" C", "C").replace(" ", "").upper()
                if temp_s and not temp_s.endswith("C") and temp_s.replace("-", "").isdigit():
                    temp_s = f"{temp_s}C"
                text = " ".join(part for part in (self._ascii(condition).upper(), temp_s) if part)
                if not text:
                    return ""
                return self.marquee(text, chars).strip() if len(text) > chars else text[:chars]

            def _weather_glyph_name(self) -> str:
                if not isinstance(self.metar, dict):
                    return "unknown"
                text = str(
                    self.metar.get("matrix_weather_icon")
                    or self.metar.get("weather_icon")
                    or self.metar.get("condition_display")
                    or self.metar.get("weather_label")
                    or self.metar.get("summary")
                    or ""
                ).lower()
                if "storm" in text or "thunder" in text:
                    return "storm"
                if "rain" in text or "shower" in text:
                    return "rain"
                if "snow" in text:
                    return "snow"
                if "mist" in text or "fog" in text or "haze" in text:
                    return "fog"
                if "cloud" in text or "overcast" in text:
                    return "cloud"
                if "sun" in text or "clear" in text or "vfr" in text:
                    return "sun"
                return "unknown"

            def _weather_temp_text(self) -> str:
                if not self.show_weather or not isinstance(self.metar, dict):
                    return ""
                temp = (
                    self.metar.get("matrix_weather_temp")
                    or self.metar.get("temperature_short")
                    or self.metar.get("temperature_display")
                    or self.metar.get("temp_c")
                    or self.metar.get("temperature_c")
                    or ""
                )
                temp_s = str(temp).replace(" C", "C").replace(" ", "").upper()
                if temp_s and not temp_s.endswith("C") and temp_s.replace("-", "").replace(".", "").isdigit():
                    temp_s = f"{temp_s}C"
                return temp_s

            def _weather_compact_token(self, max_chars: int = 8) -> str:
                temp = self._weather_temp_text()
                if temp:
                    icon = {
                        "sun": "SUN",
                        "cloud": "CLD",
                        "rain": "RAIN",
                        "storm": "STRM",
                        "fog": "MIST",
                        "mist": "MIST",
                        "snow": "SNOW",
                    }.get(self._weather_glyph_name(), "WX")
                    return f"{icon} {temp}"[:max_chars]
                return self._weather_line(max_chars)

            def _header_height(self) -> int:
                if self.panel_w < 200:
                    return 20
                return 20 if self.panel_h >= 96 else 11

            def _route_chunk(self, row: dict[str, Any], chars: int) -> str:
                label_text, code_text = self._route_fields(row)
                return self.cycle_chunks(label_text, chars, code_text).strip()

            def _status_chunk(self, row: dict[str, Any], chars: int) -> str:
                return self.cycle_chunks(row.get("matrix_status_label") or row.get("status_display") or row.get("status") or "-", chars).strip()

            def _is_vatsim_preset(self) -> bool:
                return str(self.preset or "").lower().startswith("vatsim_")

            def _gate_label(self, row: dict[str, Any]) -> str:
                if self._is_vatsim_preset() or not self.show_gate_info:
                    return ""
                for key in ("matrix_gate_label", "gate_label", "terminal_gate_display", "gate_display", "gate"):
                    value = (format_value(row.get(key)) or "").strip().upper()
                    if value and value != "-":
                        return value
                return ""

            def _gate_chip(self, row: dict[str, Any], chars: int) -> str:
                gate = self._gate_label(row)
                if not gate:
                    return ""
                return f"G {gate}"[:chars].strip()

            def _status_or_gate_chunk(self, row: dict[str, Any], chars: int) -> str:
                gate = self._gate_chip(row, chars)
                if gate and self.panel_w < 180 and int(time.monotonic() // 4) % 2 == 1:
                    return gate
                return self._status_chunk(row, chars)

            def _weather_page_lines(self, chars: int) -> list[str]:
                if not self.show_weather:
                    return []
                page = self.weather_page if isinstance(self.weather_page, dict) else {}
                lines = page.get("lines") if isinstance(page.get("lines"), list) else []
                if not lines:
                    lines = ["NO VATSIM ATIS"] if self.preset == "vatsim_atc" else []
                clean = [str(line or "").upper().strip() for line in lines if str(line or "").strip()]
                return [
                    self.marquee(line, chars).strip() if len(line) > chars else line[:chars]
                    for line in (clean or ["NO WX"])
                ]

            def _vatsim_atc_page(self) -> str:
                pages = ("departures", "arrivals", "weather") if self.show_weather and self.weather_page else ("departures", "arrivals")
                return pages[int(time.monotonic() // 10) % len(pages)]

            def _row_line(self, row: dict[str, Any]) -> str:
                time_text = (format_value(row.get("matrix_time_label")) or format_value(row.get("display_time")) or format_value(row.get("time")) or "--:--")[:5].ljust(5)
                flight = self._flight_cycle_display(row)[:8].ljust(8)
                route = self.fit(self._route_fields(row)[0], 12)
                status = (format_value(row.get("matrix_status_label")) or format_value(row.get("status_display")) or format_value(row.get("status")) or "-")[:10].ljust(10)
                gate = (self._gate_label(row) or "")[:4].ljust(4)
                return f"{time_text} {flight} {route} {status} {gate}".upper()

            def _detail_line(self, row: dict[str, Any]) -> str:
                operator = format_value(row.get("operating_airline")) or format_value(row.get("operator")) or format_value(row.get("airline_display"))
                sold_as = format_value(row.get("sold_as")) or format_value(row.get("codeshare")) or format_value(row.get("codeshare_display"))
                aircraft = format_value(row.get("aircraft")) or format_value(row.get("aircraft_type"))
                parts = []
                if operator:
                    parts.append(f"OP {operator}")
                if sold_as:
                    parts.append(f"SOLD {sold_as.replace('Also ', '')}")
                if aircraft:
                    parts.append(aircraft)
                return " | ".join(parts).upper()

            def _slide_line(self, old: str, target: str) -> str:
                width = max(len(target), len(old), 1)
                old = old.ljust(width)[:width]
                target = target.ljust(width)[:width]
                gap = "   "
                progress = self.slide_frame / max(1, self.slide_frames)
                span = width + len(gap)
                offset = int(progress * span)
                if self.animation_mode == "slide_right":
                    canvas = target + gap + old
                    return canvas[span - offset:span - offset + width].ljust(width)
                canvas = old + gap + target
                return canvas[offset:offset + width].ljust(width)

            def _advance_line(self, current: str, target: str) -> tuple[str, bool]:
                target = target.ljust(len(current))
                chars = list(current.ljust(len(target)))
                changed = False
                for idx, target_char in enumerate(target):
                    current_char = chars[idx]
                    if current_char == target_char:
                        continue
                    changed = True
                    cur_i = self.FLAP_CHARS.find(current_char)
                    target_i = self.FLAP_CHARS.find(target_char)
                    if cur_i < 0 or target_i < 0:
                        chars[idx] = target_char
                        continue
                    chars[idx] = self.FLAP_CHARS[(cur_i + 1) % len(self.FLAP_CHARS)]
                    if chars[idx] == target_char:
                        chars[idx] = target_char
                return "".join(chars), changed

            def paintEvent(self, _event: Any) -> None:
                painter = QtGui.QPainter(self)
                painter.setRenderHint(QtGui.QPainter.Antialiasing)
                painter.fillRect(self.rect(), QtGui.QColor(self.colors["bg"]))
                margin = 18
                scale = min(
                    (self.width() - margin * 2) / max(1, self.panel_w),
                    (self.height() - margin * 2) / max(1, self.panel_h),
                )
                scale = max(1.0, min(float(self.zoom), scale))
                board_w = self.panel_w * scale
                board_h = self.panel_h * scale
                left = (self.width() - board_w) / 2
                top = (self.height() - board_h) / 2
                painter.setPen(QtGui.QPen(QtGui.QColor(self.colors["line"]), 1))
                painter.setBrush(QtGui.QColor(self.colors["panel_2"]))
                painter.drawRoundedRect(QtCore.QRectF(left, top, board_w, board_h), 10, 10)
                grid_color = QtGui.QColor(self.colors["blue"])
                grid_color.setAlpha(int(28 * self.brightness))
                painter.setPen(QtGui.QPen(grid_color, 1))
                for x in range(0, self.panel_w + 1, 16):
                    painter.drawLine(int(left + x * scale), int(top), int(left + x * scale), int(top + board_h))
                for y in range(0, self.panel_h + 1, 16):
                    painter.drawLine(int(left), int(top + y * scale), int(left + board_w), int(top + y * scale))
                font = QtGui.QFont("Space Mono", max(6, int(6.5 * scale)))
                font.setBold(True)
                painter.setFont(font)
                text_color = QtGui.QColor(self.colors["cyan"])
                text_color.setAlpha(max(90, int(255 * self.brightness)))
                dim_color = QtGui.QColor(self.colors["dim"])
                dim_color.setAlpha(max(80, int(180 * self.brightness)))
                if self.message:
                    painter.setPen(dim_color)
                    painter.drawText(int(left + 10), int(top + 14 * scale), self._clock_text(self.panel_w < 200))
                    painter.setPen(QtGui.QColor(self.colors["amber"]))
                    painter.drawText(int(left + 10), int(top + board_h * 0.48), self.message[:32])
                    painter.setPen(dim_color)
                    painter.drawText(int(left + 10), int(top + board_h * 0.64), "CHECK SETTINGS")
                    return
                if self.preset == "vatsim_atc" and self._vatsim_atc_page() == "weather":
                    chars = max(8, int(self.panel_w / 6) - 1)
                    title = str((self.weather_page or {}).get("title") or "VATSIM WX").upper()
                    painter.setPen(QtGui.QColor(self.colors["green"]))
                    painter.drawText(int(left + 10), int(top + 14 * scale), title[:chars])
                    painter.setPen(dim_color)
                    if self.panel_w < 200:
                        painter.drawText(int(left + 10), int(top + 24 * scale), self._clock_text(True)[:chars])
                    else:
                        painter.drawText(int(left + max(10, board_w - 104 * scale)), int(top + 14 * scale), self._clock_text(False))
                    weather_header_h = 30 if self.panel_w < 200 and self.panel_h >= 96 else self._header_height()
                    y = top + (weather_header_h + 8) * scale
                    for line in self._weather_page_lines(chars)[: max(1, int((self.panel_h - weather_header_h) / 9))]:
                        painter.drawText(int(left + 10), int(y), line)
                        y += 9 * scale
                    return
                header_h = max(float(self._header_height()) * scale, 18.0)
                rows_to_draw = self._visible_rows()
                row_h = (board_h - header_h) / max(1, rows_to_draw)
                painter.setPen(dim_color)
                lane = "ARR" if self.view == "arrivals" else "DEP"
                compact_weather = self._weather_compact_token(8)
                airport = (self.airport_iata if self.panel_w < 200 and compact_weather else self.airport_label or "LOCAL").upper()
                header = f"{airport} {lane}"
                if self.panel_w >= 200:
                    header = f"{header}  {self.panel_w}x{self.panel_h}  {self.animation_mode.replace('_', ' ').upper()}"
                painter.drawText(int(left + 10), int(top + 8 * scale), header[:52])
                clock = self._clock_text(self.panel_w < 200)
                painter.setPen(dim_color)
                if self.panel_w < 200:
                    chars = max(8, int(self.panel_w / 6))
                    second_line = clock[:chars]
                    second_color = dim_color
                    if compact_weather:
                        approx_w = len(compact_weather) * 6 * scale
                        wx_x = left + board_w - approx_w - 10 * scale
                        header_right = left + 10 + len(header[:52]) * 6 * scale + 6 * scale
                        if wx_x > header_right:
                            painter.setPen(QtGui.QColor(self.colors["amber"]))
                            painter.drawText(int(wx_x), int(top + 8 * scale), compact_weather)
                        elif int(time.monotonic() // 8) % 2 == 1:
                            second_line = compact_weather[:chars]
                            second_color = QtGui.QColor(self.colors["amber"])
                    painter.setPen(second_color)
                    painter.drawText(int(left + 10), int(top + 18 * scale), second_line)
                else:
                    painter.drawText(int(left + max(10, board_w - 104 * scale)), int(top + header_h * 0.72), clock)
                    weather_line = self._weather_line(max(10, int(self.panel_w / 8)))
                    if self.panel_h >= 96 and weather_line:
                        painter.setPen(QtGui.QColor(self.colors["amber"]))
                        painter.drawText(int(left + 10), int(top + 18 * scale), weather_line)
                painter.setPen(text_color)
                paint_rows = self.rows
                if self.preset == "vatsim_atc":
                    page_name = self._vatsim_atc_page()
                    if isinstance(self.pages, dict) and isinstance(self.pages.get(page_name), list):
                        paint_rows = list(self.pages.get(page_name) or [])
                visible = [self._row_line(row) for row in paint_rows[: rows_to_draw]] if paint_rows is not self.rows else (self.display_lines or self.target_lines)
                for idx, text in enumerate(visible[: rows_to_draw]):
                    row_data = paint_rows[idx] if idx < len(paint_rows) else {}
                    y = top + header_h + idx * row_h + row_h * 0.64
                    row_top = top + header_h + idx * row_h
                    status = (
                        str(row_data.get("status_kind") or row_data.get("status_class") or row_data.get("status_display") or row_data.get("status") or "")
                        if paint_rows is not self.rows
                        else self.row_statuses[idx] if idx < len(self.row_statuses) else ""
                    )
                    status_color = self._status_color(QtGui, status)
                    cancelled = "cancel" in status.lower()
                    if cancelled:
                        fill = QtGui.QColor(self.colors["red"])
                        fill.setAlpha((90 if self.phase % 2 else 150) if self.status_animation_enabled else 120)
                        painter.fillRect(QtCore.QRectF(left + 4, top + header_h + idx * row_h + 1, board_w - 8, max(8, row_h - 2)), fill)
                    if self.panel_w < 180:
                        chars = max(8, int(self.panel_w / 6))
                        painter.setPen(text_color if cancelled else QtGui.QColor(self.colors["green"]))
                        painter.drawText(int(left + 4 + 8 * scale), int(row_top + 8 * scale), text[:5])
                        painter.setPen(text_color)
                        painter.drawText(int(left + 50 * scale), int(row_top + 8 * scale), text[6:14])
                        painter.setPen(text_color)
                        if row_h >= 18 * scale:
                            painter.drawText(int(left + 4), int(row_top + 16 * scale), self._route_chunk(row_data, chars))
                            status_y = row_top + 24 * scale
                        else:
                            status_y = row_top + 16 * scale
                        if status_y < row_top + row_h:
                            painter.setPen(text_color if cancelled else status_color)
                            status_text = self._status_or_gate_chunk(row_data, chars)
                            gate = self._gate_label(row_data)
                            aircraft = (format_value(row_data.get("aircraft_type")) or format_value(row_data.get("aircraft")) or "").upper()
                            if row_h >= 27 * scale and (aircraft and not gate):
                                extra = aircraft
                                status_text = f"{status_text[: max(1, chars - 5)].strip()} {extra[:4]}".strip()
                            painter.drawText(int(left + 4), int(status_y), status_text)
                        if idx < len(self.row_details) and self.row_details[idx] and row_h >= 34 * scale:
                            detail_font = QtGui.QFont("Space Mono", max(5, int(4.5 * scale)))
                            painter.setFont(detail_font)
                            painter.setPen(dim_color)
                            painter.drawText(int(left + 4), int(row_top + 32 * scale), self.row_details[idx][:20])
                            painter.setFont(font)
                        continue
                    painter.setPen(text_color)
                    painter.drawText(int(left + 10), int(y), text[:28])
                    painter.setPen(status_color)
                    painter.drawText(int(left + min(board_w - 120, 160 * scale)), int(y), text[28:40])
                    painter.setPen(dim_color)
                    painter.drawText(int(left + board_w - 46 * scale), int(y), text[39:43])
                    if idx < len(self.row_details) and self.row_details[idx] and row_h > 22:
                        detail_font = QtGui.QFont("Space Mono", max(5, int(4.5 * scale)))
                        painter.setFont(detail_font)
                        painter.setPen(dim_color)
                        painter.drawText(int(left + 10), int(y + min(row_h * 0.32, 14)), self.row_details[idx][:42])
                        painter.setFont(font)

            def _breath_color(self, QtGui: Any, color: str, floor: float = 0.38) -> Any:
                base = QtGui.QColor(color)
                if not self.status_animation_enabled:
                    return base
                wave = 0.5 + 0.5 * math.sin((self.phase / 24.0) * math.pi * 2)
                amount = floor + wave * (1.0 - floor)
                return QtGui.QColor(
                    int(base.red() * amount),
                    int(base.green() * amount),
                    int(base.blue() * amount),
                )

            def _status_color(self, QtGui: Any, status: str) -> Any:
                lowered = status.lower()
                if "early" in lowered:
                    return QtGui.QColor(self.colors["green"])
                if "delay" in lowered:
                    if "bad" in lowered:
                        return QtGui.QColor(self.colors["red"])
                    return QtGui.QColor(self.colors["amber"])
                if "cancel" in lowered:
                    if self.status_animation_enabled:
                        return QtGui.QColor(self.colors["text"] if self.phase % 2 else self.colors["red"])
                    return QtGui.QColor(self.colors["red"])
                if "boarding" in lowered or "gate" in lowered or "ground" in lowered:
                    return self._breath_color(QtGui, self.colors["amber"])
                if "depart" in lowered or "arriv" in lowered or "approach" in lowered:
                    return self._breath_color(QtGui, self.colors["green"])
                if "land" in lowered:
                    return QtGui.QColor(self.colors["dim"])
                return QtGui.QColor(self.colors["green"])

        return _Canvas()


class MatrixScreen:  # pragma: no cover - optional Qt runtime
    def __init__(self, QtWidgets: Any, client: LocalApiClient) -> None:
        self.QtWidgets = QtWidgets
        self.client = client
        self.service = NativeApiService(client)
        QtCore, QtGui, QtWidgets2 = import_qt()
        self._last_script = ""
        self._v2_available = False
        self.presets: list[dict[str, Any]] = []
        self.panel_presets: list[dict[str, Any]] = []
        self.configs: list[dict[str, Any]] = []
        self.devices: list[dict[str, Any]] = []
        self.default_config_id = "default"
        self.widget, layout = scroll_page(QtWidgets)
        self._busy_buttons: list[Any] = []

        self.status = label(QtWidgets, "Choose a panel, preview the exact board, apply live settings, and generate main.py for the i75W.", "Muted", wrap=True)
        self.loading_indicator = _loading_indicator(QtWidgets)
        self.board_status = label(QtWidgets, "I75W status: not checked yet.", "Muted", wrap=True)
        self.action_status = label(QtWidgets, "Ready.", "Muted", wrap=True)
        self.feed_refresh_timer = QtCore.QTimer(self.widget)
        self.feed_refresh_timer.setSingleShot(True)
        self.feed_refresh_timer.setInterval(250)
        self.feed_refresh_timer.timeout.connect(self.refresh_feed_only)

        self._build_shared_controls(QtCore)
        self._build_dashboard(layout, QtCore, QtGui, QtWidgets2)
        self._connect_shared_controls()
        self._sync_canvas_options()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def set_active(self, active: bool) -> None:
        timer = getattr(self.canvas, "timer", None)
        if timer is None:
            return
        if active:
            if not timer.isActive():
                timer.start(250)
        else:
            timer.stop()

    def _build_dashboard(self, layout: Any, QtCore: Any, QtGui: Any, QtWidgets2: Any) -> None:
        header = self.QtWidgets.QHBoxLayout()
        title_box = self.QtWidgets.QVBoxLayout()
        title_box.addWidget(label(self.QtWidgets, "Matrix Board", "Title"))
        title_box.addWidget(label(self.QtWidgets, "Flash once, then tune the i75W board live from Local Flight.", "Muted", wrap=True))
        header.addLayout(title_box, 1)
        for text, slot, quiet in (
            ("Refresh", self.refresh, False),
            ("Apply live config", self.save_config, False),
            ("Generate main.py", self.generate_script, False),
            ("Demo", self.trigger_demo, True),
        ):
            button = self.QtWidgets.QPushButton(text)
            if quiet:
                button.setObjectName("Quiet")
            button.clicked.connect(slot)
            header.addWidget(button)
            if not quiet:
                self._busy_buttons.append(button)
        layout.addLayout(header)
        layout.addWidget(self.loading_indicator)
        layout.addWidget(self.status)

        summary, summary_layout = panel(self.QtWidgets, "Board status")
        status_row = self.QtWidgets.QHBoxLayout()
        self.summary_labels: dict[str, Any] = {}
        for key, title, value in (
            ("matrix", "Matrix", "Not checked"),
            ("config", "Config", "Default"),
            ("board", "Board", "No i75W seen"),
            ("panel", "Panel", "256 x 64"),
            ("mode", "Mode", "Real FIDS"),
        ):
            item = card(self.QtWidgets, title, value)
            metric = item.findChild(self.QtWidgets.QLabel, "Metric")
            if metric is not None:
                self.summary_labels[key] = metric
            status_row.addWidget(item)
        summary_layout.addLayout(status_row)
        summary_layout.addWidget(self.board_status)
        summary_layout.addWidget(self.action_status)
        layout.addWidget(summary)

        guide, guide_layout = panel(self.QtWidgets, "i75W setup assistant")
        step_row = self.QtWidgets.QHBoxLayout()
        for step in MATRIX_GUIDE_STEPS:
            step_row.addWidget(card(self.QtWidgets, str(step["title"]), str(step["body"])))
        guide_layout.addLayout(step_row)
        note_row = self.QtWidgets.QHBoxLayout()
        note_row.addWidget(card(self.QtWidgets, "Live after Apply", ", ".join(MATRIX_LIVE_SETTINGS[:4]), ", ".join(MATRIX_LIVE_SETTINGS[4:])))
        note_row.addWidget(card(self.QtWidgets, "Regenerate main.py when", ", ".join(MATRIX_REFLASH_SETTINGS[:2]), ", ".join(MATRIX_REFLASH_SETTINGS[2:])))
        guide_layout.addLayout(note_row)
        layout.addWidget(guide)

        main_row = self.QtWidgets.QHBoxLayout()
        controls, controls_layout = panel(self.QtWidgets, "Board setup")
        controls_layout.addWidget(label(self.QtWidgets, "These controls change the saved board config and the preview immediately.", "Muted", wrap=True))
        form_layout = self.QtWidgets.QFormLayout()
        form_layout.addRow("Selected config", self.config_select)
        form_layout.addRow("Config name", self.config_name)
        form_layout.addRow("Board mode", self.preset_select)
        form_layout.addRow("Panel combo", self.panel_preset)
        form_layout.addRow("Custom size", self._panel_size_row())
        form_layout.addRow("Startup lane", self.default_view_select)
        form_layout.addRow("Rows shown", self.max_rows)
        form_layout.addRow("Refresh", self.refresh_seconds)
        form_layout.addRow("Page rotation", self.rotation_seconds)
        form_layout.addRow("Brightness", self._slider_row(self.brightness, self.brightness_value))
        form_layout.addRow("Preview zoom", self._slider_row(self.zoom, self.zoom_value))
        form_layout.addRow("Palette", self.palette)
        form_layout.addRow("Motion", self.animation_mode)
        form_layout.addRow("Motion speed", self.animation_speed)
        form_layout.addRow("Status motion", self.status_animation)
        form_layout.addRow("Weather", self.weather_toggle)
        form_layout.addRow("Gate/stand", self.gate_toggle)
        controls_layout.addLayout(form_layout)
        main_row.addWidget(controls, 1)

        self.canvas = lazy_symbol("localflight.native.canvas.matrix", "MatrixCanvas")(QtCore, QtGui, QtWidgets2)
        preview, preview_layout = panel(self.QtWidgets, "Live preview")
        preview_layout.addWidget(label(self.QtWidgets, "Same feed, compact layout, palette, and gate/weather rules used by generated main.py.", "Muted", wrap=True))
        preview_layout.addWidget(self.canvas, 1)
        main_row.addWidget(preview, 2)
        layout.addLayout(main_row, 1)

        self.flash_group, flash_layout = self._collapsible_panel("One-time board file", checked=False)
        self._build_flash_contents(flash_layout)
        layout.addWidget(self.flash_group)

        self.devices_group, devices_layout = self._collapsible_panel("Connected boards", checked=False)
        self._build_devices_contents(devices_layout)
        layout.addWidget(self.devices_group)

        self.configs_group, configs_layout = self._collapsible_panel("Multiple configs", checked=False)
        self._build_configs_contents(configs_layout)
        layout.addWidget(self.configs_group)

        self.advanced_group, advanced_layout = self._collapsible_panel("Advanced: how the board talks to Local Flight", checked=False)
        advanced_layout.addWidget(label(self.QtWidgets, "The board is a LAN client. No cloud account is involved for Matrix control.", "Muted", wrap=True))
        for item in MATRIX_ADVANCED_FLOW:
            advanced_layout.addWidget(label(self.QtWidgets, f"- {item}", "Muted", wrap=True))
        for item in MATRIX_SAFE_NOTES:
            advanced_layout.addWidget(label(self.QtWidgets, f"- {item}", "Muted", wrap=True))
        layout.addWidget(self.advanced_group)
        layout.addStretch(1)

    def _collapsible_panel(self, title: str, *, checked: bool) -> tuple[Any, Any]:
        group = self.QtWidgets.QGroupBox(title)
        group.setCheckable(True)
        group.setChecked(checked)
        body = self.QtWidgets.QWidget()
        body_layout = self.QtWidgets.QVBoxLayout(body)
        body_layout.setContentsMargins(0, 4, 0, 0)
        outer = self.QtWidgets.QVBoxLayout(group)
        outer.setContentsMargins(14, 18, 14, 12)
        outer.addWidget(body)
        body.setVisible(checked)
        group.toggled.connect(body.setVisible)
        return group, body_layout

    def _build_flash_contents(self, layout: Any) -> None:
        layout.addWidget(label(self.QtWidgets, "Use this once to create the file that joins Wi-Fi and points the i75W at this Local Flight server.", "Muted", wrap=True))
        self.wifi_ssid = self.QtWidgets.QLineEdit()
        self.wifi_ssid.setPlaceholderText("Wi-Fi network name")
        self.wifi_password = self.QtWidgets.QLineEdit()
        self.wifi_password.setPlaceholderText("Wi-Fi password")
        self.wifi_password.setEchoMode(self.QtWidgets.QLineEdit.Password)
        self.api_host = self.QtWidgets.QLineEdit("localflight.local")
        self.api_host.setPlaceholderText("localflight.local or LAN IP")
        self.api_port = self.QtWidgets.QSpinBox()
        self.api_port.setRange(1, 65535)
        self.api_port.setValue(8000)
        flash_form = self.QtWidgets.QFormLayout()
        flash_form.addRow("Wi-Fi name", self.wifi_ssid)
        flash_form.addRow("Wi-Fi password", self.wifi_password)
        flash_form.addRow("Server host", self.api_host)
        flash_form.addRow("Server port", self.api_port)
        layout.addLayout(flash_form)
        flash_actions = self.QtWidgets.QHBoxLayout()
        generate = self.QtWidgets.QPushButton("Generate main.py")
        generate.clicked.connect(self.generate_script)
        save = self.QtWidgets.QPushButton("Save main.py...")
        save.clicked.connect(self.save_script_file)
        self._busy_buttons.extend([generate, save])
        flash_actions.addWidget(generate)
        flash_actions.addWidget(save)
        flash_actions.addStretch(1)
        layout.addLayout(flash_actions)
        self.script_summary = label(self.QtWidgets, "No main.py generated yet.", "Muted", wrap=True)
        layout.addWidget(self.script_summary)
        self.script_preview = self.QtWidgets.QPlainTextEdit()
        self.script_preview.setReadOnly(True)
        self.script_preview.setPlaceholderText("Generated MicroPython main.py appears here.")
        self.script_preview.setMinimumHeight(220)
        layout.addWidget(self.script_preview, 1)

    def _build_devices_contents(self, layout: Any) -> None:
        row = self.QtWidgets.QHBoxLayout()
        self.device_list = self.QtWidgets.QListWidget()
        editor, editor_layout = panel(self.QtWidgets, "Device assignment")
        self.device_label = self.QtWidgets.QLineEdit()
        self.device_config = self.QtWidgets.QComboBox()
        self.device_meta = label(self.QtWidgets, "No matrix device selected.", "Muted", wrap=True)
        form = self.QtWidgets.QFormLayout()
        form.addRow("Board label", self.device_label)
        form.addRow("Assigned config", self.device_config)
        editor_layout.addLayout(form)
        assign = self.QtWidgets.QPushButton("Save board assignment")
        assign.clicked.connect(self.save_device_assignment)
        self._busy_buttons.append(assign)
        editor_layout.addWidget(assign)
        editor_layout.addWidget(self.device_meta)
        row.addWidget(self.device_list, 1)
        row.addWidget(editor, 2)
        layout.addLayout(row)

    def _build_configs_contents(self, layout: Any) -> None:
        row = self.QtWidgets.QHBoxLayout()
        self.config_list = self.QtWidgets.QListWidget()
        editor, editor_layout = panel(self.QtWidgets, "Config tools")
        self.config_preset_hint = label(self.QtWidgets, "Edit the selected config in the main Board setup section above.", "Muted", wrap=True)
        editor_layout.addWidget(self.config_preset_hint)
        actions = self.QtWidgets.QHBoxLayout()
        for text, slot in (
            ("New config", self.create_config),
            ("Duplicate", self.duplicate_config),
            ("Delete", self.delete_config),
            ("Set default", self.set_default_config),
        ):
            button = self.QtWidgets.QPushButton(text)
            button.clicked.connect(slot)
            actions.addWidget(button)
            self._busy_buttons.append(button)
        actions.addStretch(1)
        editor_layout.addLayout(actions)
        row.addWidget(self.config_list, 1)
        row.addWidget(editor, 2)
        layout.addLayout(row)

    def _build_shared_controls(self, QtCore: Any) -> None:
        self.config_select = self.QtWidgets.QComboBox()
        self.config_name = self.QtWidgets.QLineEdit()
        self.preset_select = self.QtWidgets.QComboBox()
        self.panel_preset = self.QtWidgets.QComboBox()
        self._panel_presets = (
            ("128 x 64 - 1 rectangular module", 128, 64),
            ("256 x 64 - 2 across", 256, 64),
            ("128 x 128 - 2 stacked", 128, 128),
            ("256 x 128 - 2 by 2", 256, 128),
            ("384 x 64 - 3 across", 384, 64),
            ("512 x 64 - 4 across", 512, 64),
            ("384 x 128 - 3 by 2", 384, 128),
            ("512 x 128 - 4 by 2", 512, 128),
            ("64 x 32", 64, 32),
            ("128 x 32", 128, 32),
            ("256 x 32", 256, 32),
            ("64 x 64", 64, 64),
        )
        self.panel_preset.addItem("Custom size", "custom")
        for text, w, h in self._panel_presets:
            self.panel_preset.addItem(text, (w, h))
        self.panel_w = self.QtWidgets.QSpinBox()
        self.panel_w.setRange(32, 4096)
        self.panel_w.setSuffix(" px")
        self.panel_w.setValue(256)
        self.panel_h = self.QtWidgets.QSpinBox()
        self.panel_h.setRange(16, 512)
        self.panel_h.setSuffix(" px")
        self.panel_h.setValue(64)
        self.zoom = self.QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.zoom.setRange(2, 12)
        self.zoom.setValue(4)
        self.zoom_value = label(self.QtWidgets, "4px", "Muted")
        self.brightness = self.QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.brightness.setRange(5, 100)
        self.brightness.setValue(80)
        self.brightness_value = label(self.QtWidgets, "80%", "Muted")
        self.feed_view = "departures"
        self.refresh_seconds = self.QtWidgets.QSpinBox()
        self.refresh_seconds.setRange(10, 3600)
        self.refresh_seconds.setSuffix("s")
        self.rotation_seconds = self.QtWidgets.QSpinBox()
        self.rotation_seconds.setRange(3, 120)
        self.rotation_seconds.setSuffix("s")
        self.max_rows = self.QtWidgets.QSpinBox()
        self.max_rows.setRange(1, 8)
        self.default_view_select = self.QtWidgets.QComboBox()
        self.default_view_select.addItem("Departures first", "departures")
        self.default_view_select.addItem("Arrivals first", "arrivals")
        self.animation_speed = self.QtWidgets.QSpinBox()
        self.animation_speed.setRange(1, 5)
        self.palette = self.QtWidgets.QComboBox()
        self.palette.addItems([
            "pax_blue",
            "solari_amber",
            "tower_scope",
            "vatsim_scope",
            "night_ops",
            "sunset_terminal",
            "ice_white",
        ])
        self.animation_mode = self.QtWidgets.QComboBox()
        self.animation_mode.addItem("Split-flap animation", "split_flap")
        self.animation_mode.addItem("Slide letters left", "slide_left")
        self.animation_mode.addItem("Slide letters right", "slide_right")
        self.animation_mode.addItem("Static rows", "static")
        self.status_animation = self.QtWidgets.QCheckBox("Pulse active statuses")
        self.status_animation.setChecked(True)
        self.weather_toggle = self.QtWidgets.QCheckBox("Weather strip/page")
        self.weather_toggle.setChecked(True)
        self.gate_toggle = self.QtWidgets.QCheckBox("Gate/stand info")
        self.gate_toggle.setChecked(True)

    def _build_preview_tab(self, QtCore: Any, QtGui: Any, QtWidgets2: Any) -> None:
        tab = self.QtWidgets.QWidget()
        layout = self.QtWidgets.QVBoxLayout(tab)
        guide, guide_layout = panel(self.QtWidgets, "Board setup in four steps")
        steps = self.QtWidgets.QHBoxLayout()
        for title, body in (
            ("1 Choose panel", "Pick the physical panel combo or enter a custom size."),
            ("2 Preview style", "Mode, palette, rows, weather, and motion update live below."),
            ("3 Apply live config", "Saved boards pull these settings over Wi-Fi about once a minute."),
            ("4 Generate main.py", "Use this only when Wi-Fi, server, or panel wiring changes."),
        ):
            steps.addWidget(card(self.QtWidgets, title, body))
        guide_layout.addLayout(steps)

        setup_row = self.QtWidgets.QHBoxLayout()
        controls, form = panel(self.QtWidgets, "Board setup")
        form_layout = self.QtWidgets.QFormLayout()
        form_layout.addRow("Config", self.config_select)
        form_layout.addRow("Name", self.config_name)
        form_layout.addRow("Board mode", self.preset_select)
        form_layout.addRow("Panel combo", self.panel_preset)
        form_layout.addRow("Custom size", self._panel_size_row())
        form_layout.addRow("Startup lane", self.default_view_select)
        form_layout.addRow("Rows", self.max_rows)
        form_layout.addRow("Refresh", self.refresh_seconds)
        form_layout.addRow("Page rotation", self.rotation_seconds)
        form_layout.addRow("Brightness", self._slider_row(self.brightness, self.brightness_value))
        form_layout.addRow("Preview pixel size", self._slider_row(self.zoom, self.zoom_value))
        form_layout.addRow("Palette", self.palette)
        form_layout.addRow("Animation", self.animation_mode)
        form_layout.addRow("Animation speed", self.animation_speed)
        form_layout.addRow("Status motion", self.status_animation)
        form_layout.addRow("Weather", self.weather_toggle)
        form_layout.addRow("Gate/stand", self.gate_toggle)
        form.addLayout(form_layout)
        self.canvas = lazy_symbol("localflight.native.canvas.matrix", "MatrixCanvas")(QtCore, QtGui, QtWidgets2)
        preview, preview_layout = panel(self.QtWidgets, "Live preview")
        preview_layout.addWidget(label(self.QtWidgets, "This preview uses the same Matrix feed and compact renderer as the MicroPython board.", "Muted", wrap=True))
        preview_layout.addWidget(self.canvas, 1)
        setup_row.addWidget(controls, 1)
        setup_row.addWidget(preview, 2)
        layout.addWidget(guide)
        layout.addLayout(setup_row, 1)
        self.tabs.addTab(tab, "Preview & setup")

    def _build_configs_tab(self) -> None:
        tab = self.QtWidgets.QWidget()
        layout = self.QtWidgets.QVBoxLayout(tab)
        row = self.QtWidgets.QHBoxLayout()
        self.config_list = self.QtWidgets.QListWidget()
        editor, editor_layout = panel(self.QtWidgets, "Config Details")
        self.config_preset_hint = label(self.QtWidgets, "Preset and visual controls live in the Preview tab.", "Muted", wrap=True)
        editor_layout.addWidget(label(self.QtWidgets, "Edit the selected config name and board options in Preview & setup.", "Muted", wrap=True))
        editor_layout.addWidget(self.config_preset_hint)
        actions = self.QtWidgets.QHBoxLayout()
        for text, slot in (
            ("New", self.create_config),
            ("Duplicate", self.duplicate_config),
            ("Delete", self.delete_config),
            ("Set default", self.set_default_config),
        ):
            button = self.QtWidgets.QPushButton(text)
            button.clicked.connect(slot)
            actions.addWidget(button)
        actions.addStretch(1)
        editor_layout.addLayout(actions)
        row.addWidget(self.config_list, 1)
        row.addWidget(editor, 2)
        layout.addLayout(row)
        self.tabs.addTab(tab, "Configs")

    def _build_devices_tab(self) -> None:
        tab = self.QtWidgets.QWidget()
        layout = self.QtWidgets.QVBoxLayout(tab)
        row = self.QtWidgets.QHBoxLayout()
        self.device_list = self.QtWidgets.QListWidget()
        editor, editor_layout = panel(self.QtWidgets, "Device Assignment")
        self.device_label = self.QtWidgets.QLineEdit()
        self.device_config = self.QtWidgets.QComboBox()
        self.device_meta = label(self.QtWidgets, "No matrix device selected.", "Muted", wrap=True)
        form = self.QtWidgets.QFormLayout()
        form.addRow("Label", self.device_label)
        form.addRow("Assigned config", self.device_config)
        editor_layout.addLayout(form)
        assign = self.QtWidgets.QPushButton("Save device assignment")
        assign.clicked.connect(self.save_device_assignment)
        editor_layout.addWidget(assign)
        editor_layout.addWidget(self.device_meta)
        row.addWidget(self.device_list, 1)
        row.addWidget(editor, 2)
        layout.addLayout(row)
        self.tabs.addTab(tab, "Devices")

    def _build_flash_tab(self) -> None:
        tab = self.QtWidgets.QWidget()
        layout = self.QtWidgets.QVBoxLayout(tab)
        setup, setup_layout = panel(self.QtWidgets, "Flash Board Once")
        self.wifi_ssid = self.QtWidgets.QLineEdit()
        self.wifi_ssid.setPlaceholderText("WiFi SSID")
        self.wifi_password = self.QtWidgets.QLineEdit()
        self.wifi_password.setPlaceholderText("WiFi password")
        self.wifi_password.setEchoMode(self.QtWidgets.QLineEdit.Password)
        self.api_host = self.QtWidgets.QLineEdit("localflight.local")
        self.api_port = self.QtWidgets.QSpinBox()
        self.api_port.setRange(1, 65535)
        self.api_port.setValue(8000)
        flash_form = self.QtWidgets.QFormLayout()
        flash_form.addRow("WiFi SSID", self.wifi_ssid)
        flash_form.addRow("WiFi password", self.wifi_password)
        flash_form.addRow("Server host", self.api_host)
        flash_form.addRow("Server port", self.api_port)
        setup_layout.addLayout(flash_form)
        setup_layout.addWidget(label(self.QtWidgets, "The generated client auto-registers the board, then pulls its assigned V2 config and compact feed.", "Muted", wrap=True))
        flash_actions = self.QtWidgets.QHBoxLayout()
        generate = self.QtWidgets.QPushButton("Generate code")
        generate.clicked.connect(self.generate_script)
        save = self.QtWidgets.QPushButton("Save main.py...")
        save.clicked.connect(self.save_script_file)
        flash_actions.addWidget(generate)
        flash_actions.addWidget(save)
        flash_actions.addStretch(1)
        setup_layout.addLayout(flash_actions)
        self.script_preview = self.QtWidgets.QPlainTextEdit()
        self.script_preview.setReadOnly(True)
        self.script_preview.setPlaceholderText("Generated MicroPython main.py appears here.")
        layout.addWidget(setup)
        layout.addWidget(self.script_preview, 1)
        self.tabs.addTab(tab, "Flash")

    def _connect_shared_controls(self) -> None:
        self.config_select.currentIndexChanged.connect(self._select_config_from_combo)
        self.config_list.currentRowChanged.connect(self._select_config_from_list)
        self.device_list.currentRowChanged.connect(self._select_device_from_list)
        self.panel_preset.currentIndexChanged.connect(self._apply_panel_preset_index)
        self.panel_w.valueChanged.connect(self._panel_dimensions_changed)
        self.panel_h.valueChanged.connect(self._panel_dimensions_changed)
        for widget in (self.zoom, self.brightness, self.animation_mode, self.animation_speed, self.max_rows, self.preset_select, self.palette, self.default_view_select):
            widget.currentIndexChanged.connect(self._sync_canvas_options) if hasattr(widget, "currentIndexChanged") else widget.valueChanged.connect(self._sync_canvas_options)
        self.status_animation.toggled.connect(self._sync_canvas_options)
        self.weather_toggle.toggled.connect(self._sync_canvas_options)
        self.gate_toggle.toggled.connect(self._sync_canvas_options)
        self.default_view_select.currentIndexChanged.connect(lambda *_args: self.schedule_feed_refresh())
        self.preset_select.currentIndexChanged.connect(lambda *_args: self.schedule_feed_refresh())
        self.max_rows.valueChanged.connect(lambda *_args: self.schedule_feed_refresh())
        self.weather_toggle.toggled.connect(lambda *_args: self.schedule_feed_refresh())
        self.gate_toggle.toggled.connect(lambda *_args: self.schedule_feed_refresh())

    def apply_theme(self, theme: str, skin: str) -> None:
        if hasattr(self.canvas, "apply_theme"):
            self.canvas.apply_theme(theme, skin)

    def refresh(self) -> None:
        self._set_busy(True)
        _set_native_feedback(self, "Loading matrix configuration and feed...", busy=True)
        try:
            self._load_v2_state()
            self._v2_available = bool(self.configs)
        except NativeApiError:
            self._v2_available = False
        if not self._v2_available:
            self._refresh_v1()
            return
        self._populate_v2_lists()
        self.refresh_feed_only()
        _set_native_feedback(self, f"Matrix V2 loaded: {len(self.configs)} configs, {len(self.devices)} devices.", "StatusGood")
        self._set_busy(False)

    def _load_v2_state(self) -> None:
        state = self.service.matrix_state()
        self.presets = state.presets
        self.panel_presets = state.panel_presets
        self.configs = state.configs
        self.devices = state.devices
        self.default_config_id = state.default_config_id
        if not self.presets or not self.configs:
            raise NativeApiError("Matrix V2 APIs unavailable")

    def _refresh_v1(self) -> None:
        try:
            cfg = self.service.matrix_compat_config()
            self._populate_config(cfg)
            rows = self.service.matrix_compat_rows(view=self.feed_view, limit=32)
        except NativeApiError as exc:
            _set_native_feedback(self, f"Matrix preview offline: {exc}", "StatusBad")
            self._set_busy(False)
            return
        rows = rows[: max(1, int(self.max_rows.value()))]
        self.canvas.set_rows(rows)
        self._sync_canvas_options()
        self.board_status.setText("Matrix V2 unavailable; using compatibility config.")
        _set_native_feedback(self, "Matrix compatibility preview loaded.", "StatusWarn")
        self._set_busy(False)

    def schedule_feed_refresh(self) -> None:
        if self._v2_available:
            self.action_status.setText("Preview update queued...")
            self.feed_refresh_timer.start()

    def _set_busy(self, busy: bool) -> None:
        self.loading_indicator.setVisible(bool(busy))
        for button in getattr(self, "_busy_buttons", []):
            try:
                button.setEnabled(not busy)
            except Exception:
                continue

    def _sync_summary(self) -> None:
        labels = getattr(self, "summary_labels", {})
        if not labels:
            return
        config_name = self.config_name.text().strip() if hasattr(self, "config_name") else ""
        labels.get("matrix", self.status).setText("V2 ready" if self._v2_available else "Compatibility")
        labels.get("config", self.status).setText(config_name or "Default Board")
        width, height = self._panel_size()
        labels.get("panel", self.status).setText(f"{width} x {height}")
        labels.get("mode", self.status).setText(self.preset_select.currentText() or "Real FIDS")
        if self.devices:
            seen = sum(1 for device in self.devices if device.get("last_seen"))
            labels.get("board", self.status).setText(f"{seen}/{len(self.devices)} seen")
        else:
            labels.get("board", self.status).setText("No i75W seen")

    def refresh_feed_only(self) -> None:
        if not self._v2_available:
            return
        params = {
            "view": self.feed_view,
            "config_id": self._current_config_id() or "",
            "preset": str(self.preset_select.currentData() or "real_fids"),
            "max_rows": int(self.max_rows.value()),
            "show_weather": bool(self.weather_toggle.isChecked()),
            "show_gate_info": bool(self.gate_toggle.isChecked()),
        }
        try:
            # Service keeps the browser-parity preview route: /api/matrix/v2/devices/preview/feed
            payload, rows = self.service.matrix_feed(params=params)
        except NativeApiError as exc:
            payload = {}
            rows = []
            self.action_status.setText(f"Preview feed unavailable: {exc}")
        self.canvas.set_rows(rows[: max(1, int(self.max_rows.value()))])
        if hasattr(self.canvas, "set_matrix_payload"):
            self.canvas.set_matrix_payload(payload if isinstance(payload, dict) else {})
        self._sync_canvas_options()
        if payload:
            self.action_status.setText(f"Preview updated from {payload.get('view', self.feed_view) if isinstance(payload, dict) else self.feed_view}.")

    def _populate_v2_lists(self) -> None:
        self._populate_panel_presets()
        for widget in (self.config_select, self.preset_select, self.device_config):
            widget.blockSignals(True)
            widget.clear()
        for cfg in self.configs:
            suffix = " *" if cfg.get("id") == self.default_config_id else ""
            self.config_select.addItem(f"{cfg.get('name') or cfg.get('id')}{suffix}", cfg.get("id"))
            self.device_config.addItem(str(cfg.get("name") or cfg.get("id")), cfg.get("id"))
        for preset in self.presets:
            self.preset_select.addItem(str(preset.get("label") or preset.get("id")), preset.get("id"))
        for widget in (self.config_select, self.preset_select, self.device_config):
            widget.blockSignals(False)
        self.config_list.clear()
        for cfg in self.configs:
            self.config_list.addItem(f"{cfg.get('name') or cfg.get('id')} ({cfg.get('preset')})")
        self.device_list.clear()
        for device in self.devices:
            self.device_list.addItem(f"{device.get('label') or device.get('device_id')} | {device.get('last_seen') or 'not seen'}")
        if self.configs:
            self.config_select.setCurrentIndex(0)
            self.config_list.setCurrentRow(0)
            self._populate_config(self.configs[0])
        self._populate_device(0 if self.devices else -1)
        self._sync_summary()

    def _populate_panel_presets(self) -> None:
        if not self.panel_presets:
            return
        current = self.panel_preset.currentData()
        old = self.panel_preset.blockSignals(True)
        self.panel_preset.clear()
        self.panel_preset.addItem("Custom size", "custom")
        for item in self.panel_presets:
            try:
                width = int(item.get("panel_w") or 0)
                height = int(item.get("panel_h") or 0)
            except Exception:
                continue
            if width <= 0 or height <= 0:
                continue
            text = str(item.get("label") or f"{width} x {height}")
            self.panel_preset.addItem(text, (width, height))
        idx = self.panel_preset.findData(current)
        if idx >= 0:
            self.panel_preset.setCurrentIndex(idx)
        self.panel_preset.blockSignals(old)

    def _select_config_from_combo(self, index: int) -> None:
        if index >= 0 and index < len(self.configs):
            self.config_list.setCurrentRow(index)
            self._populate_config(self.configs[index])

    def _select_config_from_list(self, row: int) -> None:
        if row >= 0 and row < len(self.configs):
            self.config_select.setCurrentIndex(row)
            self._populate_config(self.configs[row])

    def _select_device_from_list(self, row: int) -> None:
        self._populate_device(row)

    def _populate_device(self, row: int) -> None:
        if row < 0 or row >= len(self.devices):
            self.device_label.setText("")
            self.device_meta.setText("No matrix device selected.")
            self._sync_summary()
            return
        device = self.devices[row]
        self.device_label.setText(str(device.get("label") or device.get("device_id")))
        assigned = str(device.get("assigned_config_id") or "")
        idx = self.device_config.findData(assigned)
        if idx >= 0:
            self.device_config.setCurrentIndex(idx)
        renderers = ", ".join(device.get("renderers") or [])
        self.device_meta.setText(
            f"{device.get('device_id')} | {device.get('panel_w')}x{device.get('panel_h')} | "
            f"firmware {device.get('firmware') or '-'} | renderers {renderers or '-'}"
        )
        self.board_status.setText(f"Selected board: {device.get('label')} | last seen {device.get('last_seen') or 'never'}")
        self._sync_summary()

    def _populate_config(self, cfg: dict[str, Any]) -> None:
        for widget in (self.brightness, self.max_rows, self.refresh_seconds, self.rotation_seconds, self.default_view_select, self.animation_mode, self.animation_speed, self.palette, self.preset_select, self.status_animation, self.weather_toggle, self.gate_toggle, self.panel_preset, self.panel_w, self.panel_h):
            widget.blockSignals(True)
        self.config_name.setText(str(cfg.get("name") or "Matrix Config"))
        self.brightness.setValue(int(float(cfg.get("brightness", 0.8)) * 100))
        self.max_rows.setValue(int(cfg.get("max_rows") or 4))
        self.refresh_seconds.setValue(int(cfg.get("refresh_seconds") or 60))
        self.rotation_seconds.setValue(int(cfg.get("page_rotation_seconds") or 10))
        feed_view = str(cfg.get("default_view") or "departures")
        self.feed_view = feed_view if feed_view in {"departures", "arrivals"} else "departures"
        view_idx = self.default_view_select.findData(self.feed_view)
        if view_idx >= 0:
            self.default_view_select.setCurrentIndex(view_idx)
        animation_mode = str(cfg.get("animation_mode") or ("split_flap" if bool(cfg.get("animation_enabled", True)) else "static"))
        mode_idx = self.animation_mode.findData(animation_mode)
        self.animation_mode.setCurrentIndex(mode_idx if mode_idx >= 0 else 0)
        self.animation_speed.setValue(int(cfg.get("animation_speed") or 3))
        self.status_animation.setChecked(bool(cfg.get("status_animation_enabled", True)))
        options = cfg.get("options") if isinstance(cfg.get("options"), dict) else {}
        self.weather_toggle.setChecked(bool(options.get("show_metar", options.get("show_weather", True))))
        preset_name = str(cfg.get("preset") or "real_fids")
        is_vatsim = preset_name.startswith("vatsim_")
        self.gate_toggle.setChecked(bool(options.get("show_gate_info", cfg.get("show_gate_info", not is_vatsim))) and not is_vatsim)
        self.gate_toggle.setEnabled(not is_vatsim)
        self.gate_toggle.setToolTip("VATSIM does not provide reliable gate data." if is_vatsim else "Show gate or stand labels when real FIDS data provides them.")
        preset_idx = self.preset_select.findData(preset_name)
        if preset_idx >= 0:
            self.preset_select.setCurrentIndex(preset_idx)
        palette_idx = self.palette.findText(str(cfg.get("palette") or "pax_blue"))
        if palette_idx < 0:
            palette_idx = self.palette.findText("pax_blue")
        if palette_idx >= 0:
            self.palette.setCurrentIndex(palette_idx)
        panel = (int(cfg.get("panel_w") or 256), int(cfg.get("panel_h") or 64))
        self._set_panel_size(*panel, sync=False)
        for widget in (self.brightness, self.max_rows, self.refresh_seconds, self.rotation_seconds, self.default_view_select, self.animation_mode, self.animation_speed, self.palette, self.preset_select, self.status_animation, self.weather_toggle, self.gate_toggle, self.panel_preset, self.panel_w, self.panel_h):
            widget.blockSignals(False)
        self._sync_value_labels()
        self._sync_canvas_options()
        self._sync_summary()

    def _current_config_id(self) -> str | None:
        data = self.config_select.currentData()
        return str(data) if data else None

    def _selected_device_id(self) -> str | None:
        row = self.device_list.currentRow()
        if row >= 0 and row < len(self.devices):
            return str(self.devices[row].get("device_id"))
        return None

    def _panel_size(self) -> tuple[int, int]:
        return int(self.panel_w.value()), int(self.panel_h.value())

    def _set_panel_size(self, width: int, height: int, *, sync: bool = True) -> None:
        width = max(32, min(4096, int(width or 256)))
        height = max(16, min(512, int(height or 64)))
        widgets = (self.panel_preset, self.panel_w, self.panel_h)
        states = [widget.blockSignals(True) for widget in widgets]
        try:
            self.panel_w.setValue(width)
            self.panel_h.setValue(height)
            preset_idx = self.panel_preset.findData((width, height))
            if preset_idx < 0:
                preset_idx = self.panel_preset.findData("custom")
            if preset_idx >= 0:
                self.panel_preset.setCurrentIndex(preset_idx)
        finally:
            for widget, was_blocked in zip(widgets, states):
                widget.blockSignals(was_blocked)
        if sync:
            self._sync_canvas_options()
            self._sync_summary()

    def _apply_panel_preset_index(self, index: int) -> None:
        data = self.panel_preset.itemData(index)
        if isinstance(data, tuple):
            self._set_panel_size(int(data[0]), int(data[1]))

    def _panel_dimensions_changed(self, *_args: Any) -> None:
        width, height = self._panel_size()
        idx = self.panel_preset.findData((width, height))
        if idx < 0:
            idx = self.panel_preset.findData("custom")
        if idx >= 0 and idx != self.panel_preset.currentIndex():
            old = self.panel_preset.blockSignals(True)
            self.panel_preset.setCurrentIndex(idx)
            self.panel_preset.blockSignals(old)
        self._sync_canvas_options()
        self._sync_summary()

    def _config_payload(self) -> dict[str, Any]:
        w, h = self._panel_size()
        return {
            "name": self.config_name.text().strip() or "Matrix Config",
            "preset": str(self.preset_select.currentData() or "real_fids"),
            "panel_w": w,
            "panel_h": h,
            "brightness": self.brightness.value() / 100.0,
            "max_rows": int(self.max_rows.value()),
            "refresh_seconds": int(self.refresh_seconds.value()),
            "default_view": str(self.default_view_select.currentData() or self.feed_view or "departures"),
            "page_rotation_seconds": int(self.rotation_seconds.value()),
            "animation_enabled": self.animation_mode.currentData() != "static",
            "animation_mode": str(self.animation_mode.currentData() or "split_flap"),
            "animation_speed": int(self.animation_speed.value()),
            "status_animation_enabled": bool(self.status_animation.isChecked()),
            "show_gate_info": bool(self.gate_toggle.isChecked()),
            "palette": self.palette.currentText(),
            "options": {
                "palette": self.palette.currentText(),
                "show_metar": bool(self.weather_toggle.isChecked()),
                "show_weather": bool(self.weather_toggle.isChecked()),
                "show_gate_info": bool(self.gate_toggle.isChecked()),
            },
        }

    def _sync_canvas_options(self, *_args: Any) -> None:
        self._sync_value_labels()
        self.feed_view = str(self.default_view_select.currentData() or self.feed_view or "departures")
        w, h = self._panel_size()
        mode = str(self.animation_mode.currentData() or "split_flap")
        preset = str(self.preset_select.currentData() or "real_fids")
        is_vatsim = preset.startswith("vatsim_")
        if is_vatsim and self.gate_toggle.isChecked():
            old = self.gate_toggle.blockSignals(True)
            self.gate_toggle.setChecked(False)
            self.gate_toggle.blockSignals(old)
        elif not is_vatsim and not self.gate_toggle.isEnabled() and not self.gate_toggle.isChecked():
            old = self.gate_toggle.blockSignals(True)
            self.gate_toggle.setChecked(True)
            self.gate_toggle.blockSignals(old)
        self.gate_toggle.setEnabled(not is_vatsim)
        self.gate_toggle.setToolTip("VATSIM does not provide reliable gate data." if is_vatsim else "Show gate or stand labels when real FIDS data provides them.")
        self.canvas.set_options(
            panel_w=w,
            panel_h=h,
            brightness=self.brightness.value() / 100.0,
            zoom=int(self.zoom.value()),
            animate=mode != "static",
            animation_mode=mode,
            animation_speed=int(self.animation_speed.value()),
            status_animation_enabled=bool(self.status_animation.isChecked()),
            show_weather=bool(self.weather_toggle.isChecked()),
            show_gate_info=bool(self.gate_toggle.isChecked()),
            preset=preset,
            max_rows=int(self.max_rows.value()),
        )
        self.canvas.apply_theme("dark", self.palette.currentText())
        self._sync_summary()

    def _sync_value_labels(self) -> None:
        self.zoom_value.setText(f"{int(self.zoom.value())}px")
        self.brightness_value.setText(f"{int(self.brightness.value())}%")

    def _slider_row(self, slider: Any, value_label: Any) -> Any:
        row = self.QtWidgets.QWidget()
        row_layout = self.QtWidgets.QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(slider, 1)
        row_layout.addWidget(value_label)
        return row

    def _panel_size_row(self) -> Any:
        row = self.QtWidgets.QWidget()
        row_layout = self.QtWidgets.QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(self.panel_w)
        row_layout.addWidget(label(self.QtWidgets, "x", "Muted"))
        row_layout.addWidget(self.panel_h)
        row_layout.addStretch(1)
        return row

    def save_config(self) -> None:
        payload = self._config_payload()
        self._set_busy(True)
        _set_native_feedback(self, "Saving matrix configuration...", busy=True)
        self.action_status.setText("Saving Matrix config to the local server...")
        try:
            result = self.service.matrix_save_config(
                config_id=self._current_config_id(),
                payload=payload,
                v2_available=self._v2_available,
            )
        except NativeApiError as exc:
            self._set_busy(False)
            _set_native_feedback(self, f"Matrix save failed: {exc}", "StatusBad")
            self.action_status.setText(f"Save failed: {exc}")
            return
        _set_native_feedback(self, "Matrix config saved." if result.get("ok") else format_value(result), "StatusGood" if result.get("ok") else "StatusWarn")
        self.action_status.setText("Saved. A connected board will pick this up on its next config refresh.")
        self.refresh()
        self._set_busy(False)

    def create_config(self) -> None:
        payload = {**self._config_payload(), "name": self.config_name.text().strip() or "New Matrix Config"}
        _set_native_feedback(self, "Creating matrix configuration...", busy=True)
        try:
            self.service.matrix_create_config(payload)
        except NativeApiError as exc:
            _set_native_feedback(self, f"Create config failed: {exc}", "StatusBad")
            return
        self.refresh()

    def duplicate_config(self) -> None:
        payload = {**self._config_payload(), "name": f"{self.config_name.text().strip() or 'Matrix Config'} Copy"}
        _set_native_feedback(self, "Duplicating matrix configuration...", busy=True)
        try:
            self.service.matrix_create_config(payload)
        except NativeApiError as exc:
            _set_native_feedback(self, f"Duplicate config failed: {exc}", "StatusBad")
            return
        self.refresh()

    def delete_config(self) -> None:
        config_id = self._current_config_id()
        if not config_id:
            return
        _set_native_feedback(self, "Deleting matrix configuration...", busy=True)
        try:
            self.service.matrix_delete_config(config_id)
        except NativeApiError as exc:
            _set_native_feedback(self, f"Delete config failed: {exc}", "StatusBad")
            return
        self.refresh()

    def set_default_config(self) -> None:
        config_id = self._current_config_id()
        if not config_id:
            return
        _set_native_feedback(self, "Setting default matrix configuration...", busy=True)
        try:
            self.service.matrix_set_default_config(config_id)
        except NativeApiError as exc:
            _set_native_feedback(self, f"Set default failed: {exc}", "StatusBad")
            return
        self.refresh()

    def save_device_assignment(self) -> None:
        device_id = self._selected_device_id()
        if not device_id:
            return
        payload = {"label": self.device_label.text().strip(), "assigned_config_id": self.device_config.currentData()}
        _set_native_feedback(self, "Saving matrix device assignment...", busy=True)
        try:
            self.service.matrix_save_device_assignment(device_id, payload)
        except NativeApiError as exc:
            _set_native_feedback(self, f"Device save failed: {exc}", "StatusBad")
            return
        self.refresh()

    def _script_validation_error(self) -> str:
        ssid = self.wifi_ssid.text().strip()
        host = self.api_host.text().strip()
        loopback_hosts = {"localhost", "127.0.0.1", "::1", "[::1]"}
        if not ssid:
            return "Enter the Wi-Fi network name before generating main.py."
        if not host:
            return "Enter a Local Flight server host such as localflight.local or a LAN IP."
        if host.lower() in loopback_hosts:
            return "Use a LAN host the board can reach, not localhost or 127.0.0.1."
        width, height = self._panel_size()
        if width <= 0 or height <= 0:
            return "Choose the physical panel size before generating main.py."
        return ""

    def generate_script(self) -> None:
        validation_error = self._script_validation_error()
        if validation_error:
            self.flash_group.setChecked(True)
            self.action_status.setText(validation_error)
            self.script_summary.setText(validation_error)
            _set_native_feedback(self, validation_error, "StatusWarn")
            return
        w, h = self._panel_size()
        payload = {
            "wifi_ssid": self.wifi_ssid.text().strip(),
            "wifi_password": self.wifi_password.text(),
            "api_host": self.api_host.text().strip(),
            "api_port": int(self.api_port.value()),
            "device_label": self.device_label.text().strip() or "Interstate 75 W",
            "panel_w": w,
            "panel_h": h,
            "max_rows": int(self.max_rows.value()),
            "refresh_seconds": int(self.refresh_seconds.value()),
            "default_view": str(self.default_view_select.currentData() or "departures"),
            "brightness": self.brightness.value() / 100.0,
            "page_rotation_seconds": int(self.rotation_seconds.value()),
            "animation_enabled": self.animation_mode.currentData() != "static",
            "animation_mode": str(self.animation_mode.currentData() or "split_flap"),
            "animation_speed": int(self.animation_speed.value()),
            "status_animation_enabled": bool(self.status_animation.isChecked()),
            "show_weather": bool(self.weather_toggle.isChecked()),
            "show_gate_info": bool(self.gate_toggle.isChecked()),
            "preset": str(self.preset_select.currentData() or "real_fids"),
            "palette": self.palette.currentText(),
        }
        self._set_busy(True)
        _set_native_feedback(self, "Generating Matrix main.py preview...", busy=True)
        self.action_status.setText("Generating main.py preview...")
        try:
            text = self.service.matrix_generate_script(payload)
        except NativeApiError as exc:
            self._set_busy(False)
            _set_native_feedback(self, f"Script generation failed: {exc}", "StatusBad")
            self.action_status.setText(f"main.py generation failed: {exc}")
            self.script_summary.setText(f"Generation failed: {exc}")
            return
        self._last_script = text
        self.script_preview.setPlainText(text)
        self.flash_group.setChecked(True)
        self.script_summary.setText(
            f"Generated for Wi-Fi '{payload['wifi_ssid']}' | server {payload['api_host']}:{payload['api_port']} | "
            f"{w} x {h} | {payload['preset']} | {payload['palette']} | {payload['default_view']} | {payload['refresh_seconds']}s refresh."
        )
        self.action_status.setText("main.py generated. Save it to the board as main.py.")
        _set_native_feedback(self, "Generated V2 matrix main.py preview.", "StatusGood")
        self._set_busy(False)

    def save_script_file(self) -> None:
        if not self._last_script:
            self.generate_script()
        if not self._last_script:
            return
        path, _filter = self.QtWidgets.QFileDialog.getSaveFileName(self.widget, "Save Matrix main.py", "main.py", "Python files (*.py);;All files (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(self._last_script)
        except OSError as exc:
            _set_native_feedback(self, f"Could not save main.py: {exc}", "StatusBad")
            return
        _set_native_feedback(self, f"Saved matrix client to {path}", "StatusGood")

    def trigger_demo(self) -> None:
        demo_rows = [
            {"display_time": "09:10", "flight_display": "LX 1952", "route_display": "Barcelona", "status_display": "SCHEDULED", "status_kind": "scheduled", "gate": "A64", "airline_display": "Swiss", "codeshare_display": "Also UA 9724"},
            {"display_time": "09:20", "flight_display": "LX 724", "route_display": "Amsterdam", "status_display": "BOARDING", "status_kind": "boarding", "gate": "B12", "airline_display": "Swiss"},
            {"display_time": "09:35", "flight_display": "U2 8465", "route_display": "London", "status_display": "DELAYED", "status_kind": "delayed", "gate": "C03", "airline_display": "easyJet"},
            {"display_time": "09:50", "flight_display": "QR 96", "route_display": "Doha", "status_display": "CANCELLED", "status_kind": "cancelled", "gate": "-", "airline_display": "Qatar Airways", "codeshare_display": "Also BA 7006"},
        ]
        self.canvas.set_rows(demo_rows[: int(self.max_rows.value())])
        self._sync_canvas_options()
        _set_native_feedback(self, "Demo rows loaded locally.", "StatusGood")


class SettingsScreen:  # pragma: no cover - optional Qt runtime
    def __init__(self, QtCore: Any, QtGui: Any, QtWidgets: Any, client: LocalApiClient, base_url: str) -> None:
        self.QtWidgets = QtWidgets
        self.QtCore = QtCore
        self.QtGui = QtGui
        self.client = client
        self.service = NativeApiService(client)
        self.base_url = base_url.rstrip("/")
        self.current_doc_slug = "readme"
        self._airport_search_future: Future[Any] | None = None
        self._last_airport_query = ""
        self.widget, self.layout = scroll_page(QtWidgets)
        self.search_timer = QtCore.QTimer(self.widget)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._start_airport_search)
        self.search_poll_timer = QtCore.QTimer(self.widget)
        self.search_poll_timer.setInterval(50)
        self.search_poll_timer.timeout.connect(self._poll_airport_search)
        self.layout.addWidget(label(QtWidgets, "Settings", "Title"))
        self.layout.addWidget(label(QtWidgets, "User-facing client controls. Operator-only relay controls stay in Network Admin.", "Muted", wrap=True))
        self.status = label(QtWidgets, "Loading current settings...", "Muted", wrap=True)
        self._build_current_section()
        self._build_install_section()
        self._build_profile_section()
        self._build_flight_section()
        self._build_display_section()
        self._build_app_section()
        self._build_docs_section()
        self.layout.addWidget(self.status)
        self.layout.addStretch(1)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def _build_current_section(self) -> None:
        box, self.current_layout = panel(self.QtWidgets, "Current")
        self.layout.addWidget(box)

    def _build_install_section(self) -> None:
        box, self.install_layout = panel(self.QtWidgets, "Install & Relay")
        self.layout.addWidget(box)

    def _build_profile_section(self) -> None:
        box, layout = panel(self.QtWidgets, "Profiles")
        row = self.QtWidgets.QHBoxLayout()
        self.profile_combo = self.QtWidgets.QComboBox()
        self.profile_name = self.QtWidgets.QLineEdit()
        self.profile_name.setPlaceholderText("New profile name")
        load = self.QtWidgets.QPushButton("Load")
        save = self.QtWidgets.QPushButton("Save current")
        delete = self.QtWidgets.QPushButton("Delete")
        delete.setObjectName("Danger")
        load.clicked.connect(self.load_profile)
        save.clicked.connect(self.save_profile)
        delete.clicked.connect(self.delete_profile)
        row.addWidget(self.profile_combo)
        row.addWidget(load)
        row.addWidget(self.profile_name)
        row.addWidget(save)
        row.addWidget(delete)
        layout.addLayout(row)
        self.layout.addWidget(box)

    def _build_flight_section(self) -> None:
        box, layout = panel(self.QtWidgets, "Flight Setup")
        layout.addWidget(label(self.QtWidgets, "Search by airport name, city, IATA, or ICAO. Selecting a result fills IATA/ICAO/timezone like the web setup.", "Muted", wrap=True))
        self.airport_search = self.QtWidgets.QLineEdit()
        self.airport_search.setPlaceholderText("Search airport, e.g. Zurich, HKG, Heathrow...")
        self.airport_search.textChanged.connect(lambda _text: self.search_timer.start(250))
        self.airport_results = self.QtWidgets.QListWidget()
        self.airport_results.setMaximumHeight(150)
        self.airport_results.hide()
        self.airport_results.itemClicked.connect(self._select_airport_item)
        self.airport_selected = label(self.QtWidgets, "No airport search selection yet.", "Muted", wrap=True)
        layout.addWidget(self.airport_search)
        layout.addWidget(self.airport_results)
        layout.addWidget(self.airport_selected)
        form = self.QtWidgets.QFormLayout()
        self.airport_iata = self.QtWidgets.QLineEdit()
        self.airport_icao = self.QtWidgets.QLineEdit()
        self.timezone = self.QtWidgets.QLineEdit()
        self.airport_iata.setReadOnly(True)
        self.airport_icao.setReadOnly(True)
        self.timezone.setReadOnly(True)
        self.source = self.QtWidgets.QComboBox()
        self.source.addItems(["real", "virtual"])
        self.refresh_seconds = self.QtWidgets.QComboBox()
        for value in (900, 1800, 2700, 3600, 7200, 14400, 28800, 43200, 86400):
            self.refresh_seconds.addItem(f"{value // 60} min", value)
        form.addRow("Airport IATA", self.airport_iata)
        form.addRow("Airport ICAO", self.airport_icao)
        form.addRow("Timezone", self.timezone)
        form.addRow("Flight source", self.source)
        form.addRow("Refresh cadence", self.refresh_seconds)
        layout.addLayout(form)
        layout.addWidget(
            label(
                self.QtWidgets,
                "Refresh choices are 15, 30, 45, and 60 minutes, then 2, 4, 8, 12, or 24 hours. Shorter values keep local displays fresh; longer values are kinder to schedule providers.",
                "Muted",
                wrap=True,
            )
        )
        self.layout.addWidget(box)

    def _build_display_section(self) -> None:
        box, layout = panel(self.QtWidgets, "Display & Devices")
        form = self.QtWidgets.QFormLayout()
        self.display_name = self.QtWidgets.QLineEdit()
        self.theme = self.QtWidgets.QComboBox()
        self.theme.addItems(["dark", "light"])
        self.skin = self.QtWidgets.QComboBox()
        self.skin.addItems(["standard", "technical", "neon", "cyan", "crt"])
        self.web_row_limit = self.QtWidgets.QSpinBox()
        self.web_row_limit.setRange(5, 100)
        self.web_rotation = self.QtWidgets.QSpinBox()
        self.web_rotation.setRange(3, 120)
        self.grace = self.QtWidgets.QSpinBox()
        self.grace.setRange(0, 240)
        self.horizon = self.QtWidgets.QSpinBox()
        self.horizon.setRange(1, 48)
        self.surface = self.QtWidgets.QCheckBox("Airport surface overlay")
        self.output_web = self.QtWidgets.QCheckBox("Web")
        self.output_matrix = self.QtWidgets.QCheckBox("Matrix")
        self.output_hdmi = self.QtWidgets.QCheckBox("HDMI")
        outputs = self.QtWidgets.QHBoxLayout()
        outputs.addWidget(self.output_web)
        outputs.addWidget(self.output_matrix)
        outputs.addWidget(self.output_hdmi)
        form.addRow("Display name", self.display_name)
        form.addRow("Theme", self.theme)
        form.addRow("Skin", self.skin)
        form.addRow("Radar", self.surface)
        layout.addLayout(form)
        self.advanced_display_group = self.QtWidgets.QGroupBox("Advanced board/device controls")
        self.advanced_display_group.setCheckable(True)
        self.advanced_display_group.setChecked(False)
        advanced_outer = self.QtWidgets.QVBoxLayout(self.advanced_display_group)
        self.advanced_display_body = self.QtWidgets.QWidget()
        advanced_form = self.QtWidgets.QFormLayout(self.advanced_display_body)
        advanced_form.addRow("Visible web rows", self.web_row_limit)
        advanced_form.addRow("Page rotation seconds", self.web_rotation)
        advanced_form.addRow("Past grace minutes", self.grace)
        advanced_form.addRow("Future horizon hours", self.horizon)
        advanced_form.addRow("Outputs", outputs)
        advanced_outer.addWidget(self.advanced_display_body)
        self.advanced_display_body.setVisible(False)
        self.advanced_display_group.toggled.connect(self.advanced_display_body.setVisible)
        layout.addWidget(self.advanced_display_group)
        self.layout.addWidget(box)

    def _build_app_section(self) -> None:
        box, layout = panel(self.QtWidgets, "App")
        self.diagnostics = self.QtWidgets.QComboBox()
        self.diagnostics.addItems(["unset", "manual", "auto", "auto_logs"])
        buttons = self.QtWidgets.QHBoxLayout()
        save = self.QtWidgets.QPushButton("Save settings")
        restart = self.QtWidgets.QPushButton("Restart scheduler")
        reset = self.QtWidgets.QPushButton("Re-run setup wizard")
        reset.setObjectName("Danger")
        save.clicked.connect(self.save)
        restart.clicked.connect(self.restart_scheduler)
        reset.clicked.connect(self.reset_setup)
        buttons.addWidget(save)
        buttons.addWidget(restart)
        buttons.addWidget(reset)
        buttons.addStretch(1)
        layout.addWidget(label(self.QtWidgets, "Diagnostics", "Kicker"))
        layout.addWidget(self.diagnostics)
        layout.addLayout(buttons)
        self.layout.addWidget(box)

    def _build_docs_section(self) -> None:
        box, layout = panel(self.QtWidgets, "Diagnostics & Documents")
        layout.addWidget(
            label(
                self.QtWidgets,
                "Public docs are embedded here from the local app bundle. Internal operator notes stay out of the client UI.",
                "Muted",
                wrap=True,
            )
        )
        preview_row = self.QtWidgets.QHBoxLayout()
        for title, text, asset in (
            ("FIDS board", "Airport-style rows, detail drawer, and local-time labels.", "fids-preview.svg"),
            ("Radar", "Native canvas parity with surface overlays and range controls.", "radar-preview.svg"),
            ("Settings", "User-facing controls, profiles, docs, and diagnostics.", "settings-preview.svg"),
        ):
            preview_row.addWidget(
                preview_card(
                    self.QtCore,
                    self.QtGui,
                    self.QtWidgets,
                    title,
                    text,
                    ("docs", "previews", asset),
                )
            )
        layout.addLayout(preview_row)

        docs = self.QtWidgets.QHBoxLayout()
        self.doc_buttons: dict[str, Any] = {}
        for title, slug in (
            ("Project README", "readme"),
            ("Install guide", "install"),
            ("Display modes", "display-modes"),
            ("Privacy & diagnostics", "privacy"),
            ("Release notes", "changelog"),
            ("Third-party notices", "third-party"),
        ):
            button = self.QtWidgets.QPushButton(title)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, s=slug: self.open_doc(s))
            docs.addWidget(button)
            self.doc_buttons[slug] = button
        open_web = self.QtWidgets.QPushButton("Open web copy")
        open_web.setObjectName("Quiet")
        open_web.clicked.connect(lambda: webbrowser.open(f"{self.base_url}/docs/{self.current_doc_slug}"))
        docs.addWidget(open_web)
        layout.addLayout(docs)

        self.doc_title = label(self.QtWidgets, "Project README", "Section")
        self.doc_summary = label(self.QtWidgets, "", "Muted", wrap=True)
        self.doc_text = self.QtWidgets.QTextEdit()
        self.doc_text.setReadOnly(True)
        self.doc_text.setMinimumHeight(260)
        layout.addWidget(self.doc_title)
        layout.addWidget(self.doc_summary)
        layout.addWidget(self.doc_text)
        self.layout.addWidget(box)
        self.open_doc("readme")

    def open_doc(self, slug: str) -> None:
        doc = bundled_doc(slug)
        self.current_doc_slug = doc["slug"] or "readme"
        for button_slug, button in self.doc_buttons.items():
            button.setChecked(button_slug == self.current_doc_slug)
        self.doc_title.setText(f"{doc['title']} - {doc['filename']}")
        self.doc_summary.setText(doc["summary"])
        if hasattr(self.doc_text, "setMarkdown"):
            self.doc_text.setMarkdown(doc["text"])
        else:
            self.doc_text.setPlainText(doc["text"])

    def refresh(self) -> None:
        try:
            cfg = self.service.config()
        except NativeApiError as exc:
            self.status.setText(f"Settings offline: {exc}")
            return
        self._populate_config(cfg)
        self._refresh_current(cfg)
        self._refresh_install()
        self._refresh_profiles()
        self.status.setText("Settings loaded from /api/config.")

    def _populate_config(self, cfg: dict[str, Any]) -> None:
        self.airport_iata.setText(str(cfg.get("airport_iata") or ""))
        self.airport_icao.setText(str(cfg.get("airport_icao") or ""))
        self.timezone.setText(str(cfg.get("timezone") or ""))
        self.airport_search.setText(f"{cfg.get('airport_iata') or '---'} / {cfg.get('airport_icao') or '----'}")
        self.airport_selected.setText(
            f"Selected: {cfg.get('airport_iata') or '---'} / {cfg.get('airport_icao') or '----'}"
            + (f" | {cfg.get('timezone')}" if cfg.get("timezone") else "")
        )
        self.display_name.setText(str(cfg.get("display_name") or "Local Flight"))
        self.source.setCurrentText(str(cfg.get("source") or "real"))
        self.theme.setCurrentText(str(cfg.get("theme") or "dark"))
        self.skin.setCurrentText(str(cfg.get("skin") or "standard"))
        self.diagnostics.setCurrentText(str(cfg.get("diagnostics_mode") or "unset"))
        self.surface.setChecked(bool(cfg.get("radar_surface_enabled")))
        self.web_row_limit.setValue(int(cfg.get("web_row_limit") or 20))
        self.web_rotation.setValue(int(cfg.get("web_rotation_seconds") or 8))
        self.grace.setValue(int(cfg.get("display_grace_minutes") or 30))
        self.horizon.setValue(int(cfg.get("display_horizon_hours") or 12))
        outputs = cfg.get("display_outputs") if isinstance(cfg.get("display_outputs"), list) else ["web"]
        self.output_web.setChecked("web" in outputs)
        self.output_matrix.setChecked("matrix" in outputs)
        self.output_hdmi.setChecked("hdmi" in outputs)
        refresh_value = int(cfg.get("refresh_seconds") or 3600)
        idx = self.refresh_seconds.findData(refresh_value)
        self.refresh_seconds.setCurrentIndex(idx if idx >= 0 else self.refresh_seconds.findData(3600))

    def _start_airport_search(self) -> None:
        query = self.airport_search.text().strip()
        if len(query) < 2 or "/" in query:
            self.airport_results.hide()
            return
        query_key = query.casefold()
        if query_key == self._last_airport_query:
            return
        self._last_airport_query = query_key
        if self._airport_search_future is not None and not self._airport_search_future.done():
            return
        self.airport_results.clear()
        self.airport_results.addItem("Searching airports...")
        self.airport_results.show()
        self._airport_search_future = _API_EXECUTOR.submit(
            lambda: self.service.airport_search(query, limit=10)
        )
        self.search_poll_timer.start()

    def _poll_airport_search(self) -> None:
        future = self._airport_search_future
        if future is None or not future.done():
            return
        self.search_poll_timer.stop()
        self._airport_search_future = None
        try:
            payload = future.result()
        except Exception as exc:
            self.airport_results.clear()
            self.airport_results.addItem(f"Search failed: {exc}")
            self.airport_results.show()
            return
        results = list_payload(payload)
        self.airport_results.clear()
        if not results:
            self.airport_results.addItem("No airport matches found.")
            self.airport_results.show()
            return
        for result in results:
            item = self.QtWidgets.QListWidgetItem(
                f"{result.get('iata') or '---'} / {result.get('icao') or '----'}  "
                f"{result.get('name') or ''} - {result.get('city') or ''}, {result.get('country') or ''}"
            )
            item.setData(self.QtCore.Qt.UserRole, result)
            self.airport_results.addItem(item)
        self.airport_results.show()

    def _select_airport_item(self, item: Any) -> None:
        result = item.data(self.QtCore.Qt.UserRole)
        if not isinstance(result, dict):
            return
        self.airport_iata.setText(str(result.get("iata") or "").upper())
        self.airport_icao.setText(str(result.get("icao") or "").upper())
        self.timezone.setText(str(result.get("timezone") or "UTC"))
        self.airport_search.blockSignals(True)
        self.airport_search.setText(f"{result.get('iata') or '---'} / {result.get('icao') or '----'}")
        self.airport_search.blockSignals(False)
        self.airport_selected.setText(
            f"Selected: {result.get('iata') or '---'} / {result.get('icao') or '----'} - "
            f"{result.get('name') or ''} | {result.get('city') or ''}, {result.get('country') or ''} | "
            f"{result.get('timezone') or 'UTC'}"
        )
        self.airport_results.hide()

    def _refresh_current(self, cfg: dict[str, Any]) -> None:
        clear_layout(self.current_layout)
        self.current_layout.addWidget(section_label(self.QtWidgets, "Current"))
        grid = self.QtWidgets.QGridLayout()
        cards = [
            card(self.QtWidgets, "Airport", f"{cfg.get('airport_iata')}/{cfg.get('airport_icao')}", cfg.get("timezone") or ""),
            card(self.QtWidgets, "Source", cfg.get("source") or "real", cfg.get("skin") or "standard"),
            card(self.QtWidgets, "Refresh", f"{int(cfg.get('refresh_seconds') or 0) // 60} min", "Scheduler cadence"),
        ]
        for idx, widget in enumerate(cards):
            grid.addWidget(widget, 0, idx)
        self.current_layout.addLayout(grid)

    def _refresh_install(self) -> None:
        clear_layout(self.install_layout)
        self.install_layout.addWidget(section_label(self.QtWidgets, "Install & Relay"))
        try:
            info = self.service.setup_client_info()
        except NativeApiError as exc:
            self.install_layout.addWidget(label(self.QtWidgets, f"Install info unavailable: {exc}", "Muted", wrap=True))
            return
        rows = [
            {"item": "Machine ID", "value": info.get("install_id") or info.get("install_fingerprint")},
            {"item": "Relay URL", "value": info.get("relay_url")},
            {"item": "Managed token", "value": "present" if (info.get("activation_token_present") or info.get("has_activation_token")) else "not set"},
            {"item": "Access path", "value": info.get("mode") or info.get("status")},
        ]
        self.install_layout.addWidget(table(self.QtWidgets, rows, [("item", "Item"), ("value", "Value")], min_height=120))

    def _refresh_profiles(self) -> None:
        current = self.profile_combo.currentText()
        self.profile_combo.clear()
        self.profile_combo.addItems(list_profiles())
        if current:
            idx = self.profile_combo.findText(current)
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)

    def _config_payload(self) -> dict[str, Any]:
        outputs = []
        if self.output_web.isChecked():
            outputs.append("web")
        if self.output_matrix.isChecked():
            outputs.append("matrix")
        if self.output_hdmi.isChecked():
            outputs.append("hdmi")
        return {
            "airport_iata": self.airport_iata.text().strip().upper(),
            "airport_icao": self.airport_icao.text().strip().upper(),
            "timezone": self.timezone.text().strip(),
            "display_name": self.display_name.text().strip() or "Local Flight",
            "source": self.source.currentText(),
            "refresh_seconds": int(self.refresh_seconds.currentData()),
            "theme": self.theme.currentText(),
            "skin": self.skin.currentText(),
            "diagnostics_mode": self.diagnostics.currentText(),
            "web_row_limit": int(self.web_row_limit.value()),
            "web_rotation_seconds": int(self.web_rotation.value()),
            "display_grace_minutes": int(self.grace.value()),
            "display_horizon_hours": int(self.horizon.value()),
            "radar_surface_enabled": bool(self.surface.isChecked()),
            "display_outputs": outputs or ["web"],
        }

    def save(self) -> None:
        try:
            self.service.save_config(self._config_payload())
        except NativeApiError as exc:
            self.status.setText(f"Save failed: {exc}")
            return
        self.status.setText("Settings saved. Scheduler restarts automatically when needed.")

    def restart_scheduler(self) -> None:
        try:
            result = self.service.restart_scheduler()
        except NativeApiError as exc:
            self.status.setText(f"Restart failed: {exc}")
            return
        self.status.setText(str(result.get("message") or "Scheduler restart requested."))

    def reset_setup(self) -> None:
        if self.QtWidgets.QMessageBox.question(self.widget, "Re-run setup", "Clear setup marker and restart the setup wizard?") != self.QtWidgets.QMessageBox.Yes:
            return
        try:
            self.service.setup_reset()
        except NativeApiError as exc:
            self.status.setText(f"Setup reset failed: {exc}")
            return
        self.status.setText("Setup marker removed. Open setup on next launch or from the browser setup page.")

    def save_profile(self) -> None:
        name = self.profile_name.text().strip()
        if not name:
            self.status.setText("Enter a profile name first.")
            return
        try:
            self.service.save_profile(name)
        except NativeApiError as exc:
            self.status.setText(f"Profile save failed: {exc}")
            return
        self.status.setText(f"Profile saved: {name}")
        self._refresh_profiles()

    def load_profile(self) -> None:
        name = self.profile_combo.currentText().strip()
        if not name:
            self.status.setText("No profile selected.")
            return
        try:
            self.service.load_profile(name)
        except NativeApiError as exc:
            self.status.setText(f"Profile load failed: {exc}")
            return
        self.status.setText(f"Profile loaded: {name}")
        self.refresh()

    def delete_profile(self) -> None:
        name = self.profile_combo.currentText().strip()
        if not name:
            self.status.setText("No profile selected.")
            return
        try:
            self.service.delete_profile(name)
        except NativeApiError as exc:
            self.status.setText(f"Profile delete failed: {exc}")
            return
        self.status.setText(f"Profile deleted: {name}")
        self._refresh_profiles()


class AdminSummaryScreen:  # pragma: no cover - optional Qt runtime
    def __init__(self, QtWidgets: Any, client: LocalApiClient, *, navigate: Callable[[str], None]) -> None:
        self.QtWidgets = QtWidgets
        QtCore, _QtGui, _QtWidgets = import_qt()
        self.QtCore = QtCore
        self.client = client
        self.service = NativeApiService(client)
        self.navigate = navigate
        self.widget, self.layout = scroll_page(QtWidgets)
        self.widget.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        body = self.widget.widget()
        if body is not None:
            body.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self.layout.setContentsMargins(28, 22, 28, 22)
        # PageHero replaces the legacy title/subtitle/refresh row.
        from localflight.native.shell_widgets import make_page_hero
        from localflight.native.qt_compat import import_qt as _import_qt

        _QtCore, _QtGui, _QtWidgets = _import_qt()
        refresh = QtWidgets.QPushButton("\U0001F504  Refresh overview")
        refresh.setObjectName("PrimaryCTA")
        refresh.clicked.connect(self.refresh)
        self.hero = make_page_hero(
            _QtCore,
            _QtGui,
            QtWidgets,
            emoji="\U0001F4CA",
            title="System Overview",
            subtitle="Local user-facing status, access, connected devices, history, and weather.",
            info_text="This page lives entirely on this machine. Numbers come from your own local APIs.",
            actions=(refresh,),
            show_last_refreshed=True,
        )
        # Keep the public attribute name so existing _set_native_feedback hooks work.
        self.header_subtitle = self.hero._subtitle  # type: ignore[attr-defined]
        self.status = label(QtWidgets, "Ready.", "Muted", wrap=True)
        self.loading_indicator = _loading_indicator(QtWidgets)
        self.grid = QtWidgets.QGridLayout()
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(14)
        self.detail_layout = QtWidgets.QVBoxLayout()
        self.footer = label(QtWidgets, "", "Muted", wrap=True)
        self.footer.setAlignment(QtCore.Qt.AlignCenter)
        self.layout.addWidget(self.hero)
        self.layout.addSpacing(4)
        self.layout.addLayout(self.grid)
        self.layout.addLayout(self.detail_layout)
        self.layout.addWidget(self.loading_indicator)
        self.layout.addWidget(self.status)
        self.layout.addWidget(self.footer)
        self.layout.addStretch(1)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def refresh(self) -> None:
        _set_native_feedback(self, "Loading admin overview...", busy=True)
        try:
            summary = self.service.admin_summary()
            cfg = summary.config
            system = summary.system
            budget = summary.budget
            connections = summary.connections
            scheduler = summary.scheduler
            updates = summary.updates
            weather = summary.weather or {}
            history = summary.history_stats
        except NativeApiError as exc:
            _set_native_feedback(self, f"Admin offline: {exc}", "StatusBad")
            return
        clear_layout(self.grid)
        clear_layout(self.detail_layout)
        aviation = budget.get("aviationstack") if isinstance(budget.get("aviationstack"), dict) else {}
        schedule_bucket = _active_schedule_budget(aviation)
        active_mode = str(aviation.get("active_mode") or aviation.get("mode") or "unknown")
        airport = f"{cfg.get('airport_iata') or scheduler.get('airport') or '-'} / {cfg.get('airport_icao') or '-'}"
        display_name = cfg.get("display_name") or "Local Flight"
        self.header_subtitle.setText(f"{display_name} | {airport} | local user-facing panel")
        cards = [
            self._stats_panel(
                "✈️  Flight Refresh",
                [
                    ("Health", scheduler.get("state") or scheduler.get("status") or "unknown"),
                    ("Airport", airport),
                    ("Traffic source", cfg.get("source") or scheduler.get("source") or "-"),
                    ("Last update", scheduler.get("last_success_utc") or scheduler.get("last_fetch") or "-"),
                    ("Next update", scheduler.get("next_fetch_in") or scheduler.get("next_run") or "-"),
                    ("Current issue", scheduler.get("last_error") or "No issues"),
                ],
            ),
            self._budget_panel("\U0001F4E1  Schedule Access", active_mode, schedule_bucket, aviation),
            self._devices_panel(connections),
            self._stats_panel(
                "\U0001F4C5  Flight History",
                [
                    ("Total rows", history.get("rows") or history.get("row_count") or 0),
                    ("Oldest record", history.get("oldest") or history.get("oldest_record") or "-"),
                    ("Newest record", history.get("newest") or history.get("newest_record") or "-"),
                    ("Open history", "History tab"),
                ],
            ),
            self._stats_panel(
                "\U0001F527  App & Device",
                [
                    ("Version", system.get("version") or _app_version()),
                    ("Latest release", updates.get("latest_version") or updates.get("status") or "-"),
                    ("Running since", system.get("uptime_human") or system.get("uptime") or "-"),
                    ("This device", system.get("platform") or "-"),
                    ("Support ID", system.get("install_fingerprint") or system.get("fingerprint") or "-"),
                ],
            ),
            self._weather_panel(weather),
        ]
        columns = self._dashboard_columns()
        for column in range(columns):
            self.grid.setColumnStretch(column, 1)
        for idx, widget in enumerate(cards):
            widget.setMinimumWidth(0)
            widget.setSizePolicy(self.QtWidgets.QSizePolicy.Ignored, self.QtWidgets.QSizePolicy.Preferred)
            self.grid.addWidget(widget, idx // columns, idx % columns)
        self.detail_layout.addWidget(progress_card(self.QtWidgets, "\U0001F4C8  Schedule Access Budget", schedule_bucket.get("calls_this_month"), schedule_bucket.get("monthly_limit"), _budget_detail(schedule_bucket)))
        now = datetime.now().strftime('%H:%M:%S')
        _set_native_feedback(self, f"Last refreshed {now} | local user-facing admin APIs.", "StatusGood")
        if hasattr(self, "hero"):
            try:
                self.hero.set_last_refreshed(f"Updated {now}")
                self.hero.set_status("Live", tone="good")
            except Exception:
                pass
        try:
            from localflight.native.qt_compat import import_qt as _import_qt
            from localflight.native.shell_widgets import show_toast

            _QtCore, _QtGui, _QtWidgets = _import_qt()
            show_toast(_QtCore, _QtGui, _QtWidgets, self.widget, text="Admin overview refreshed", tone="good")
        except Exception:
            pass
        self.footer.setText(f"Local Flight is free. If this little airport gremlin helps, coffee lives here: {COFFEE_URL}")

    def _stats_panel(self, title: str, rows: list[tuple[str, Any]]) -> Any:
        box, layout = panel(self.QtWidgets, title)
        box.setMinimumWidth(0)
        box.setSizePolicy(self.QtWidgets.QSizePolicy.Ignored, self.QtWidgets.QSizePolicy.Preferred)
        for key, value in rows:
            layout.addWidget(self._stat_row(key, value))
        return box

    def _stat_row(self, key: str, value: Any) -> Any:
        row = self.QtWidgets.QWidget()
        row.setMinimumWidth(0)
        row.setSizePolicy(self.QtWidgets.QSizePolicy.Ignored, self.QtWidgets.QSizePolicy.Preferred)
        row_layout = self.QtWidgets.QGridLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setHorizontalSpacing(10)
        row_layout.setVerticalSpacing(2)
        key_label = label(self.QtWidgets, key, "Muted")
        key_label.setMinimumWidth(0)
        key_label.setSizePolicy(self.QtWidgets.QSizePolicy.Preferred, self.QtWidgets.QSizePolicy.Preferred)
        val = label(self.QtWidgets, self._display_value(key, value), "Metric", wrap=True)
        val.setAlignment(self.QtCore.Qt.AlignRight | self.QtCore.Qt.AlignVCenter)
        val.setMinimumWidth(0)
        val.setSizePolicy(self.QtWidgets.QSizePolicy.Ignored, self.QtWidgets.QSizePolicy.Preferred)
        val.setStyleSheet("font-size: 12px;")
        row_layout.addWidget(key_label, 0, 0)
        row_layout.addWidget(val, 0, 1)
        row_layout.setColumnStretch(0, 0)
        row_layout.setColumnStretch(1, 1)
        return row

    def _dashboard_columns(self) -> int:
        try:
            width = int(self.widget.viewport().width())
        except Exception:
            width = 1200
        return 1 if width < 980 else 2

    def _display_value(self, key: str, value: Any) -> str:
        text = format_value(value) or "-"
        if len(text) > 120:
            text = text[:117].rstrip() + "..."
        if "T" in text and ("+00:00" in text or text.endswith("Z")):
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                return parsed.strftime("%Y-%m-%d %H:%MZ")
            except Exception:
                pass
        if key.lower() in {"counter resets", "oldest record", "newest record", "last update"} and len(text) > 22:
            return text.replace("T", " ").replace("+00:00", "Z")[:17] + "Z"
        return text

    def _budget_panel(self, title: str, mode: str, bucket: dict[str, Any], aviation: dict[str, Any]) -> Any:
        box, layout = panel(self.QtWidgets, title)
        source_label = {
            "community": "Hosted relay access",
            "managed": "Managed relay access",
            "byok": "Own AviationStack key",
            "virtual": "Virtual source",
        }.get(mode, mode or "unknown")
        for key, value in [
            ("Access source", source_label),
            ("Used this window", _budget_label(bucket)),
            ("Requests left", bucket.get("remaining")),
            ("Access window", bucket.get("month") or bucket.get("period_days") or "-"),
            ("Counter resets", bucket.get("period_end") or "-"),
            ("Current note", aviation.get("cadence_warning") or value_at(bucket, "cost_estimate.cadence_warning") or "Shared relay separates this install's access counter from upstream pulls."),
        ]:
            layout.addWidget(self._stat_row(key, value))
        layout.addWidget(progress_card(self.QtWidgets, "", bucket.get("calls_this_month"), bucket.get("monthly_limit")))
        return box

    def _devices_panel(self, connections: dict[str, Any]) -> Any:
        box, layout = panel(self.QtWidgets, "\U0001F5A5️  Connected Screens")
        count = connections.get("count", 0)
        companions = connections.get("companion_count", 0)
        matrix_count = int(connections.get("matrix_device_count") or 0)
        matrix_online = int(connections.get("matrix_online_count") or 0)
        layout.addWidget(card(self.QtWidgets, "Live viewers", count, f"{companions} companion clients | {matrix_online}/{matrix_count} LED online"))
        devices = connections.get("matrix_devices") if isinstance(connections.get("matrix_devices"), list) else []
        if devices:
            hardware_counts = connections.get("matrix_hardware_counts") if isinstance(connections.get("matrix_hardware_counts"), dict) else {}
            summary = ", ".join(f"{name} x{value}" for name, value in hardware_counts.items()) or f"{matrix_count} LED display(s)"
            layout.addWidget(self._stat_row("LED hardware", summary))
            for device in devices[:4]:
                if not isinstance(device, dict):
                    continue
                size = f"{device.get('panel_w')}x{device.get('panel_h')}" if device.get("panel_w") and device.get("panel_h") else "size unknown"
                name = device.get("hardware_name") or device.get("model") or device.get("label") or "LED matrix"
                firmware = f" fw {device.get('firmware')}" if device.get("firmware") else ""
                seen = device.get("last_seen") or "not seen yet"
                layout.addWidget(self._stat_row(str(name), f"{size}{firmware} | {seen}"))
        else:
            layout.addWidget(self._stat_row("LED hardware", connections.get("matrix_last_seen") or "no check-in yet"))
        for name, seen in [
            ("Mobile Companion", connections.get("companion_last_seen")),
        ]:
            layout.addWidget(self._stat_row(name, seen or "no check-in yet"))
        return box

    def _weather_panel(self, weather: dict[str, Any]) -> Any:
        box, layout = panel(self.QtWidgets, "\U0001F324️  Airport Weather")
        hero = self.QtWidgets.QFrame()
        hero.setObjectName("WeatherStrip")
        hero_layout = self.QtWidgets.QHBoxLayout(hero)
        hero_layout.setContentsMargins(12, 10, 12, 10)
        hero_layout.addWidget(label(self.QtWidgets, _weather_icon_glyph(weather.get("weather_icon")), "Metric"))
        weather_text = self.QtWidgets.QVBoxLayout()
        weather_text.addWidget(label(self.QtWidgets, weather.get("weather_label") or weather.get("flight_cat") or "-", "Metric"))
        weather_text.addWidget(label(self.QtWidgets, weather.get("decoded_summary") or weather.get("raw_text") or "-", "Muted", wrap=True))
        hero_layout.addLayout(weather_text, 1)
        layout.addWidget(hero)
        for key, value in [
            ("Category", weather.get("flight_cat")),
            ("Wind", weather.get("wind_display") or weather.get("wind")),
            ("Visibility", weather.get("visibility")),
            ("Ceiling / sky", weather.get("sky") or weather.get("ceiling")),
            ("Temperature", weather.get("temperature_display") or weather.get("temperature_c")),
            ("Raw report", weather.get("raw_text") or weather.get("raw")),
        ]:
            layout.addWidget(self._stat_row(key, value))
        return box

    def _quick_tools_panel(self) -> Any:
        box, layout = panel(self.QtWidgets, "\U0001F6E0️  Quick Tools")
        grid = self.QtWidgets.QGridLayout()
        tools = [
            ("Open display", "Show the split board with flights and radar.", "display"),
            ("Open radar", "Watch nearby traffic around the selected airport.", "radar"),
            ("Open settings", "Change airport, data source, skins, and timing.", "settings"),
            ("Traffic log", "Open anonymized local request activity.", "requests"),
            ("Report a problem", "Send a sanitized bug report with context.", "feedback"),
            ("Buy me a coffee", "Support Local Flight and keep the boards glowing.", "coffee"),
        ]
        for idx, (text, hint, key) in enumerate(tools):
            button = self.QtWidgets.QPushButton(f"{text}\n{hint}")
            button.setMinimumHeight(56)
            button.clicked.connect(lambda _checked=False, k=key: self._open_quick_tool(k))
            grid.addWidget(button, idx // 3, idx % 3)
        layout.addLayout(grid)
        return box

    def _open_quick_tool(self, key: str) -> None:
        if key == "coffee":
            webbrowser.open(COFFEE_URL)
            self.status.setText(f"Opened support link: {COFFEE_URL}")
            return
        self.navigate(key)


class RequestsScreen:  # pragma: no cover - optional Qt runtime
    def __init__(self, QtWidgets: Any, client: LocalApiClient) -> None:
        self.QtWidgets = QtWidgets
        self.client = client
        self.service = NativeApiService(client)
        self.widget, self.layout = scroll_page(QtWidgets)
        self.hours = QtWidgets.QComboBox()
        for value, text in ((1, "Last hour"), (6, "Last 6h"), (24, "Last 24h"), (168, "Last 7d")):
            self.hours.addItem(text, value)
        self.client_type = QtWidgets.QComboBox()
        for label_text, value in (("all clients", "all"), ("web", "web"), ("native", "native"), ("mobile", "mobile"), ("matrix", "matrix"), ("api", "api")):
            self.client_type.addItem(label_text, value)
        refresh = QtWidgets.QPushButton("\U0001F504  Refresh traffic")
        refresh.setObjectName("PrimaryCTA")
        refresh.clicked.connect(self.refresh)
        from localflight.native.shell_widgets import make_page_hero as _make_hero_r
        from localflight.native.qt_compat import import_qt as _import_qt_r

        _QtCore_r, _QtGui_r, _QtWidgets_r = _import_qt_r()
        self.hero = _make_hero_r(
            _QtCore_r,
            _QtGui_r,
            QtWidgets,
            emoji="\U0001F310",
            title="Traffic Log",
            subtitle="Anonymized local API requests. Hidden unless network tools are enabled.",
            info_text="Nothing here leaves this device. Useful for spotting noisy clients on your LAN.",
            actions=(self.hours, self.client_type, refresh),
            show_last_refreshed=True,
        )
        self.status = label(QtWidgets, "Local anonymized request log. Hidden unless network tools are enabled.", "Muted", wrap=True)
        self.loading_indicator = _loading_indicator(QtWidgets)
        self.summary_grid = QtWidgets.QGridLayout()
        self.table = QtWidgets.QTableWidget(0, 8)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.layout.addWidget(self.hero)
        self.layout.addWidget(self.loading_indicator)
        self.layout.addWidget(self.status)
        self.layout.addLayout(self.summary_grid)
        self.layout.addWidget(self.table, 1)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def refresh(self) -> None:
        selected_client_type = str(self.client_type.currentData() or "all")
        _set_native_feedback(self, "Loading anonymized local request log...", busy=True)
        try:
            request_log = self.service.request_log(
                hours=int(self.hours.currentData()),
                limit=300,
                client_type=selected_client_type,
            )
        except NativeApiError as exc:
            _set_native_feedback(self, f"Traffic log unavailable: {exc}", "StatusBad")
            return
        clear_layout(self.summary_grid)
        summary = request_log.summary
        cards = [
            card(self.QtWidgets, "\U0001F4E8  Requests", summary.get("total_requests") or summary.get("total") or len(request_log.rows)),
            card(self.QtWidgets, "\U0001F464  Clients", summary.get("clients") or summary.get("client_count") or "-"),
            card(self.QtWidgets, "⚠️  Errors", summary.get("errors") or summary.get("error_count") or 0),
        ]
        for idx, widget in enumerate(cards):
            self.summary_grid.addWidget(widget, 0, idx)
        rows = request_log.rows
        set_table_rows(
            self.table,
            self.QtWidgets,
            rows,
            [
                ("ts", "Time"),
                ("method", "Method"),
                ("path", "Path"),
                ("status_code", "Status"),
                ("latency_ms", "Latency"),
                ("client_type", "Type"),
                ("platform", "Platform"),
                ("client_id", "Client"),
            ],
        )
        _set_native_feedback(self, f"{len(rows)} anonymized local request rows loaded.", "StatusGood")
        if hasattr(self, "hero"):
            try:
                self.hero.set_last_refreshed(f"Updated {datetime.now().strftime('%H:%M:%S')}")
                self.hero.set_status(f"{len(rows)} rows", tone="info")
            except Exception:
                pass


class HistoryScreen:  # pragma: no cover - optional Qt runtime
    def __init__(self, QtWidgets: Any, client: LocalApiClient) -> None:
        self.QtWidgets = QtWidgets
        self.client = client
        self.service = NativeApiService(client)
        self.rows: list[dict[str, Any]] = []
        self.colors = colors_for()
        self.widget = QtWidgets.QSplitter()
        self.widget.setMinimumWidth(0)

        body, layout = scroll_page(QtWidgets)
        layout.setSpacing(12)

        from localflight.native.shell_widgets import make_page_hero as _make_hero
        from localflight.native.qt_compat import import_qt as _import_qt_h

        _QtCore_h, _QtGui_h, _QtWidgets_h = _import_qt_h()
        self.hero = _make_hero(
            _QtCore_h,
            _QtGui_h,
            QtWidgets,
            emoji="\U0001F4C5",
            title="Flight History",
            subtitle="Airport-board analytics: delay quotas, airline performance, routes, aircraft, and recent matching flights.",
            info_text="History is a 90-day local rolling window stored on this machine only.",
            actions=(),
            show_last_refreshed=True,
        )
        # Back-compat shim: code below still references self.last_refresh.setText(...)
        class _LastRefreshShim:
            def __init__(self, hero: Any) -> None:
                self._hero = hero
            def setText(self, value: str) -> None:  # noqa: N802 - matches QLabel API
                try:
                    self._hero.set_last_refreshed(value)
                except Exception:
                    pass
        self.last_refresh = _LastRefreshShim(self.hero)
        layout.addWidget(self.hero)

        filters, filter_layout = panel(QtWidgets, "\U0001F50D  Filters")
        filter_grid = QtWidgets.QGridLayout()
        self.callsign = QtWidgets.QLineEdit()
        self.callsign.setPlaceholderText("Callsign, e.g. LX1952")
        self.callsign.setMaximumWidth(180)
        self.callsign.returnPressed.connect(self.refresh)
        self.airline = QtWidgets.QLineEdit()
        self.airline.setPlaceholderText("Airline, e.g. LX")
        self.airline.setMaxLength(3)
        self.airline.setMaximumWidth(100)
        self.airline.returnPressed.connect(self.refresh)
        self.hours = QtWidgets.QComboBox()
        for value, text in ((6, "Last 6h"), (24, "Last 24h"), (168, "Last 7d"), (720, "Last 30d"), (2160, "Last 90d")):
            self.hours.addItem(text, value)
        self.direction = QtWidgets.QComboBox()
        for value, text in (("both", "Both"), ("dep", "Departures"), ("arr", "Arrivals")):
            self.direction.addItem(text, value)
        self.status_filter = QtWidgets.QComboBox()
        for value, text in (("", "All statuses"), ("scheduled", "Scheduled"), ("boarding", "Boarding"), ("delayed", "Delayed"), ("departed", "Departed"), ("arrived", "Arrived"), ("cancelled", "Cancelled")):
            self.status_filter.addItem(text, value)
        apply = QtWidgets.QPushButton("Apply")
        apply.clicked.connect(self.refresh)
        clear = QtWidgets.QPushButton("Clear")
        clear.setObjectName("Quiet")
        clear.clicked.connect(self.clear_search)
        fields = [
            ("Callsign", self.callsign),
            ("Airline", self.airline),
            ("Period", self.hours),
            ("Direction", self.direction),
            ("Status", self.status_filter),
        ]
        for idx, (name, widget) in enumerate(fields):
            filter_grid.addWidget(label(QtWidgets, name, "Muted"), 0, idx)
            filter_grid.addWidget(widget, 1, idx)
        filter_grid.addWidget(apply, 1, len(fields))
        filter_grid.addWidget(clear, 1, len(fields) + 1)
        filter_layout.addLayout(filter_grid)
        layout.addWidget(filters)

        self.status = label(QtWidgets, "90-day local database. Click a row for details.", "Muted", wrap=True)
        self.loading_indicator = _loading_indicator(QtWidgets)
        layout.addWidget(self.loading_indicator)
        layout.addWidget(self.status)

        self.kpi_grid = QtWidgets.QGridLayout()
        self.kpi_cards: dict[str, tuple[Any, Any]] = {}
        for idx, (key, title, note) in enumerate((
            ("total", "✈️  Flights tracked", "local DB"),
            ("departures", "\U0001F6EB  Departures", "outbound rows"),
            ("arrivals", "\U0001F6EC  Arrivals", "inbound rows"),
            ("on_time_pct", "⏰  On time", "-4m to +4m"),
            ("delayed_pct", "\U0001F40C  Delayed", "5m or more"),
            ("avg_delay_minutes", "⏱️  Avg delay", "when late"),
        )):
            box, value_label = self._metric_card(title, note)
            self.kpi_cards[key] = (box, value_label)
            self.kpi_grid.addWidget(box, idx // 3, idx % 3)
        layout.addLayout(self.kpi_grid)

        self.stats_body = QtWidgets.QWidget()
        self.stats_outer_layout = QtWidgets.QVBoxLayout(self.stats_body)
        self.stats_outer_layout.setContentsMargins(0, 0, 0, 0)
        self.stats_content = QtWidgets.QWidget()
        self.stats_layout = QtWidgets.QGridLayout(self.stats_content)
        self.stats_layout.setContentsMargins(0, 0, 0, 0)
        self.stats_outer_layout.addWidget(self.stats_content)
        layout.addWidget(self.stats_body)

        layout.addWidget(section_label(QtWidgets, "\U0001F4CB  Recent matching flights"))
        self.table = QtWidgets.QTableWidget(0, 12)
        self.table.setObjectName("FidsTable")
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSortingEnabled(True)
        self.table.cellClicked.connect(self._show_row_detail)
        layout.addWidget(self.table, 1)

        self.detail = self._detail_panel()
        self.detail.hide()
        self.widget.addWidget(body)
        self.widget.addWidget(self.detail)
        self.widget.setSizes([900, 340])

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def apply_theme(self, theme: str, skin: str) -> None:
        self.colors = colors_for(theme, skin)

    def _metric_card(self, title: str, note: str) -> tuple[Any, Any]:
        box = self.QtWidgets.QFrame()
        box.setObjectName("Card")
        lay = self.QtWidgets.QVBoxLayout(box)
        lay.addWidget(label(self.QtWidgets, title.upper(), "Kicker"))
        value = label(self.QtWidgets, "-", "Title")
        lay.addWidget(value)
        lay.addWidget(label(self.QtWidgets, note, "Muted"))
        return box, value

    def _detail_panel(self) -> Any:
        detail = self.QtWidgets.QFrame()
        detail.setObjectName("Drawer")
        detail.setMinimumWidth(300)
        detail.setMaximumWidth(460)
        layout = self.QtWidgets.QVBoxLayout(detail)
        head = self.QtWidgets.QHBoxLayout()
        self.detail_title = label(self.QtWidgets, "Flight details", "Title")
        close = self.QtWidgets.QPushButton("Close")
        close.setObjectName("Quiet")
        close.clicked.connect(detail.hide)
        head.addWidget(self.detail_title)
        head.addWidget(close)
        self.detail_text = self.QtWidgets.QTextEdit()
        self.detail_text.setReadOnly(True)
        layout.addLayout(head)
        layout.addWidget(self.detail_text, 1)
        return detail

    def _filters(self, *, include_limit: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "hours": int(self.hours.currentData()),
            "direction": str(self.direction.currentData() or "both"),
        }
        if include_limit:
            payload["limit"] = 500
        callsign = self.callsign.text().strip().upper()
        airline = self.airline.text().strip().upper()
        status = str(self.status_filter.currentData() or "")
        if callsign:
            payload["callsign"] = callsign
        if airline:
            payload["airline_iata"] = airline
        if status:
            payload["status"] = status
        return payload

    def refresh(self) -> None:
        _set_native_feedback(self, "Loading local history analytics...", busy=True)
        try:
            payload = self.service.history_payload(**self._filters(include_limit=True))
            summary = self.service.history_summary(**self._filters(include_limit=False))
        except NativeApiError as exc:
            _set_native_feedback(self, f"History offline: {exc}", "StatusBad")
            self.status.setText(f"History unavailable: {exc}")
            return
        self.rows = list_payload(payload, "flights")
        self._render_summary(summary)
        self._render_table()
        visible = min(len(self.rows), 120)
        airport = payload.get("airport_iata") or summary.get("airport_iata") or "airport"
        self.status.setText(f"{len(self.rows)} records in this filter | {airport} | showing first {visible} to keep the view light")
        self.last_refresh.setText(f"Updated {datetime.now().strftime('%H:%M:%S')}")
        _set_native_feedback(self, f"{len(self.rows)} history records loaded.", "StatusGood")
        try:
            from localflight.native.qt_compat import import_qt as _import_qt_ht
            from localflight.native.shell_widgets import show_toast as _toast_ht

            _QtCore_ht, _QtGui_ht, _QtWidgets_ht = _import_qt_ht()
            _toast_ht(_QtCore_ht, _QtGui_ht, _QtWidgets_ht, self.widget, text=f"{len(self.rows)} flights loaded", tone="good")
        except Exception:
            pass

    def search_callsign(self) -> None:
        self.refresh()

    def clear_search(self) -> None:
        self.callsign.clear()
        self.airline.clear()
        self.status_filter.setCurrentIndex(0)
        self.direction.setCurrentIndex(0)
        self.refresh()

    def _render_table(self) -> None:
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        table_rows = [self._table_row(row) for row in self.rows[:120]]
        set_table_rows(
            self.table,
            self.QtWidgets,
            table_rows,
            [
                ("sched_time", "Scheduled"),
                ("direction", "Dir"),
                ("airline_iata", "Airline"),
                ("flight_number", "Flight"),
                ("callsign", "Callsign"),
                ("origin_iata", "From"),
                ("dest_iata", "To"),
                ("status", "Status"),
                ("delay_label", "Delay"),
                ("gate", "Gate"),
                ("aircraft_type", "A/C"),
                ("source", "Source"),
            ],
            resize=False,
        )
        for idx, width in enumerate((138, 60, 82, 96, 110, 80, 80, 118, 96, 64, 86, 90)):
            self.table.setColumnWidth(idx, width)
        self.table.horizontalHeader().setStretchLastSection(True)
        QtCore, _QtGui, _QtWidgets = import_qt()
        for idx, _row in enumerate(self.rows[:120]):
            item = self.table.item(idx, 0)
            if item is not None:
                item.setData(QtCore.Qt.UserRole, idx)
        self.table.setSortingEnabled(sorting)
        self.table.blockSignals(False)
        self.table.setUpdatesEnabled(True)

    def _table_row(self, row: dict[str, Any]) -> dict[str, Any]:
        copied = dict(row)
        copied["delay_label"] = self._delay_label(row.get("delay_minutes"))
        return copied

    def _render_stats(self) -> None:
        try:
            summary = self.service.history_summary(**self._filters(include_limit=False))
        except NativeApiError as exc:
            clear_layout(self.stats_layout)
            self.stats_layout.addWidget(label(self.QtWidgets, f"Stats unavailable: {exc}", "Muted", wrap=True), 0, 0)
            return
        self._render_summary(summary)

    def _render_summary(self, summary: dict[str, Any]) -> None:
        for key, (_box, value_label) in self.kpi_cards.items():
            value = summary.get(key)
            if key in {"on_time_pct", "delayed_pct"} and value is not None:
                value = f"{value}%"
            elif key == "avg_delay_minutes" and value is not None:
                value = f"+{value}m"
            value_label.setText(format_value(value) or "-")

        clear_layout(self.stats_layout)
        specs = [
            ("⏱️  Delay quota", self._delay_rows(summary), 0, 0),
            ("\U0001F4CA  Daily volume", self._daily_rows(summary), 0, 1),
            ("\U0001F3AF  Status mix", self._status_rows(summary), 0, 2),
            ("\U0001F6EB  Airline delay quota", self._airline_rows(summary), 1, 0),
            ("\U0001F30D  Top routes", self._route_rows(summary), 1, 1),
            ("✈️  Top aircraft", self._normalize_stat_rows(list_payload(summary, "top_aircraft"), ("aircraft_type", "code", "label")), 1, 2),
        ]
        for title, rows, r, c in specs:
            box, box_layout = panel(self.QtWidgets, title)
            if rows:
                box_layout.addWidget(bar_summary(self.QtWidgets, rows))
            else:
                box_layout.addWidget(label(self.QtWidgets, "No matching data yet.", "Muted"))
            self.stats_layout.addWidget(box, r, c)

    def _delay_rows(self, summary: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {"label": row.get("label") or row.get("bucket") or "-", "count": row.get("count") or 0}
            for row in list_payload(summary, "delay_buckets")
        ]

    def _daily_rows(self, summary: dict[str, Any]) -> list[dict[str, Any]]:
        rows = list_payload(summary, "daily_volume")[-10:]
        return [{"label": str(row.get("date") or "")[-5:] or "-", "count": row.get("total") or 0} for row in rows]

    def _status_rows(self, summary: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {"label": f"{row.get('label') or row.get('status') or '-'} {row.get('pct') or 0}%", "count": row.get("count") or 0}
            for row in list_payload(summary, "status_mix")
        ]

    def _airline_rows(self, summary: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in list_payload(summary, "top_airlines"):
            code = format_value(row.get("code")) or "-"
            delay = row.get("delay_rate_pct")
            rows.append({"label": f"{code} {delay or 0}% late", "count": row.get("count") or 0})
        return rows

    def _route_rows(self, summary: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in list_payload(summary, "top_routes"):
            origin = format_value(row.get("origin")) or "-"
            dest = format_value(row.get("destination")) or "-"
            delay = row.get("delay_rate_pct")
            rows.append({"label": f"{origin}->{dest} {delay or 0}% late", "count": row.get("count") or 0})
        return rows

    def _normalize_stat_rows(self, rows: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for row in rows:
            label_value = ""
            for key in keys:
                label_value = format_value(row.get(key))
                if label_value:
                    break
            normalized.append({"label": label_value or "-", "count": row.get("count") or 0})
        return normalized

    def _show_row_detail(self, row_idx: int, _col: int) -> None:
        mapped_idx = row_idx
        try:
            QtCore, _QtGui, _QtWidgets = import_qt()
            item = self.table.item(row_idx, 0)
            if item is not None:
                mapped_idx = int(item.data(QtCore.Qt.UserRole))
        except Exception:
            mapped_idx = row_idx
        if mapped_idx < 0 or mapped_idx >= len(self.rows):
            return
        row = self.rows[mapped_idx]
        self.detail_title.setText(str(row.get("flight_number") or row.get("callsign") or "Flight"))
        intel: dict[str, Any] = {}
        callsign = str(row.get("callsign") or "").strip()
        if callsign:
            try:
                live_detail = self.service.fids_detail(callsign)
                if isinstance(live_detail.get("intel"), dict):
                    intel = live_detail["intel"]
                elif isinstance(live_detail.get("detail"), dict) and isinstance(live_detail["detail"].get("intel"), dict):
                    intel = live_detail["detail"]["intel"]
            except Exception:
                intel = {}
        self.detail_text.setHtml(self._history_detail_html(row, intel=intel))
        self.detail.show()

    def _history_detail_html(self, row: dict[str, Any], *, intel: dict[str, Any] | None = None) -> str:
        intel = intel or {}
        motion = intel.get("motion") if isinstance(intel.get("motion"), dict) else {}
        aircraft = intel.get("aircraft") if isinstance(intel.get("aircraft"), dict) else {}
        evidence = intel.get("source_evidence") if isinstance(intel.get("source_evidence"), dict) else {}
        sections = [
            ("Identity", [
                ("Callsign", row.get("callsign")),
                ("Flight", row.get("flight_number")),
                ("Airline", row.get("airline_iata")),
                ("Source", row.get("source")),
            ]),
            ("Route", [
                ("From", row.get("origin_iata")),
                ("To", row.get("dest_iata")),
                ("Direction", row.get("direction")),
                ("Gate", row.get("gate")),
                ("Terminal", row.get("terminal")),
                ("A/C code", row.get("aircraft_type")),
                ("Aircraft type", aircraft.get("model") or aircraft.get("full_type")),
            ]),
            ("Timing", [
                ("Scheduled", row.get("sched_time")),
                ("Actual", row.get("actual_time")),
                ("Delay bucket", self._delay_label(row.get("delay_minutes"))),
                ("Snapshot", row.get("snapshot_ts")),
            ]),
            ("Operations", [
                ("Status", row.get("status")),
                ("Enriched by", evidence.get("position_source") or row.get("enriched_by")),
                ("Lat / Lon", f"{row.get('lat')}, {row.get('lon')}" if row.get("lat") is not None and row.get("lon") is not None else ""),
                ("Altitude", f"{motion.get('altitude_ft'):,} ft" if isinstance(motion.get("altitude_ft"), int) else self._altitude(row.get("altitude_m"))),
                ("Speed", f"{motion.get('speed_kt')} kt" if motion.get("speed_kt") is not None else ""),
                ("Aircraft reg", aircraft.get("registration")),
                ("Source confidence", evidence.get("confidence")),
            ]),
        ]
        parts = [_detail_css(self.colors)]
        for title, fields in sections:
            detail_rows = [(name, format_value(value)) for name, value in fields if format_value(value)]
            if not detail_rows:
                continue
            parts.append(f"<div class='section'><div class='label'>{html_escape(title)}</div>")
            for name, value in detail_rows:
                parts.append(f"<div class='row'><span class='key'>{html_escape(name)}</span><span class='val'>{html_escape(value)}</span></div>")
            parts.append("</div>")
        return "".join(parts)

    def _delay_label(self, value: Any) -> str:
        if value in (None, ""):
            return "unknown"
        try:
            minutes = int(float(value))
        except (TypeError, ValueError):
            return "unknown"
        if minutes <= -5:
            return f"{abs(minutes)}m early"
        if minutes <= 4:
            return "on time"
        if minutes <= 15:
            return f"+{minutes}m warn"
        return f"+{minutes}m late"

    def _altitude(self, value: Any) -> str:
        try:
            meters = float(value)
        except (TypeError, ValueError):
            return ""
        return f"{int(round(meters * 3.28084))} ft"


class LogsScreen:  # pragma: no cover - optional Qt runtime
    def __init__(self, QtWidgets: Any, client: LocalApiClient) -> None:
        self.client = client
        self.QtWidgets = QtWidgets
        self.service = NativeApiService(client)
        QtCore, _QtGui, _QtWidgets = import_qt()
        self._known_files: list[str] = []
        self.widget, layout = scroll_page(QtWidgets)
        self.file_combo = QtWidgets.QComboBox()
        self.file_combo.setMinimumWidth(180)
        self.file_combo.currentTextChanged.connect(lambda _name: self.refresh())
        self.live_tail = QtWidgets.QCheckBox("\U0001F7E2  Live tail")
        self.live_tail.setChecked(False)
        self.live_tail.toggled.connect(self._toggle_live)
        self.auto_scroll = QtWidgets.QCheckBox("Scroll to bottom")
        self.auto_scroll.setChecked(True)
        refresh = QtWidgets.QPushButton("\U0001F504  Refresh logs")
        refresh.setObjectName("PrimaryCTA")
        refresh.clicked.connect(self.refresh)
        from localflight.native.shell_widgets import make_page_hero as _make_hero_l
        from localflight.native.qt_compat import import_qt as _import_qt_l

        _QtCore_l, _QtGui_l, _QtWidgets_l = _import_qt_l()
        self.hero = _make_hero_l(
            _QtCore_l,
            _QtGui_l,
            QtWidgets,
            emoji="\U0001F4DC",
            title="Logs & Diagnostics",
            subtitle="Browse retained local logs or enable a live tail while reproducing an issue.",
            info_text="Logs never leave this device. Live tail polls the file every 2.5 seconds while enabled.",
            actions=(self.file_combo, self.live_tail, self.auto_scroll, refresh),
            show_last_refreshed=True,
        )
        self.status = label(QtWidgets, "Choose any retained Local Flight log. Nothing leaves this device unless you send a report.", "Muted", wrap=True)
        self.loading_indicator = _loading_indicator(QtWidgets)
        self.meta = label(QtWidgets, "No log metadata loaded yet.", "Muted")
        self.text = QtWidgets.QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMinimumHeight(320)
        self.timer = QtCore.QTimer()
        self.timer.setInterval(2500)
        self.timer.timeout.connect(self.refresh)
        layout.addWidget(self.hero)
        layout.addWidget(self.loading_indicator)
        layout.addWidget(self.status)
        self.summary_grid = QtWidgets.QGridLayout()
        layout.addLayout(self.summary_grid)
        layout.addWidget(self.meta)
        layout.addWidget(self.text, 1)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def refresh(self) -> None:
        _set_native_feedback(self, "Loading retained local logs...", busy=True)
        try:
            selected = self.file_combo.currentText().strip() or None
            tail = self.service.log_tail(selected=selected)
            self._sync_file_combo(tail.files, tail.selected)
            selected = self.file_combo.currentText().strip() or tail.selected or None
        except NativeApiError as exc:
            _set_native_feedback(self, f"Logs unavailable: {exc}", "StatusBad")
            return
        lines = tail.lines
        self.text.setPlainText("\n".join(str(line) for line in lines[-500:]))
        if self.auto_scroll.isChecked():
            self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())
        total = tail.total
        shown = min(len(lines), 500)
        clear_layout(self.summary_grid)
        self.summary_grid.addWidget(card(self.QtWidgets, "\U0001F4C1  Selected file", selected or "default"), 0, 0)
        self.summary_grid.addWidget(card(self.QtWidgets, "\U0001F4DD  Lines shown", shown, f"{total} retained"), 0, 1)
        self.summary_grid.addWidget(card(self.QtWidgets, "\U0001F7E2  Live tail", "on" if self.live_tail.isChecked() else "off"), 0, 2)
        now = datetime.now().strftime('%H:%M:%S')
        _set_native_feedback(self, f"{selected or 'default log'} | {total} lines available | showing last {shown}", "StatusGood")
        self.meta.setText(f"Updated {now} | files retained locally | live tail {'on' if self.live_tail.isChecked() else 'off'}")
        if hasattr(self, "hero"):
            try:
                self.hero.set_last_refreshed(f"Updated {now}")
                self.hero.set_status("Live tail" if self.live_tail.isChecked() else "Idle", tone="good" if self.live_tail.isChecked() else "muted")
            except Exception:
                pass

    def _sync_file_combo(self, files: list[Any], selected: str) -> None:
        names = [str(file) for file in files if file]
        if names == self._known_files and (not selected or self.file_combo.currentText() == selected):
            return
        self._known_files = names
        self.file_combo.blockSignals(True)
        self.file_combo.clear()
        self.file_combo.addItems(names)
        if selected:
            idx = self.file_combo.findText(selected)
            if idx >= 0:
                self.file_combo.setCurrentIndex(idx)
        self.file_combo.blockSignals(False)

    def _toggle_live(self, enabled: bool) -> None:
        if enabled:
            self.timer.start()
            self.refresh()
        else:
            self.timer.stop()


class FeedbackScreen:  # pragma: no cover - optional Qt runtime
    def __init__(self, QtWidgets: Any, client: LocalApiClient) -> None:
        self.client = client
        self.QtWidgets = QtWidgets
        self.service = NativeApiService(client)
        self._last_cfg: dict[str, Any] = {}
        self._last_system: dict[str, Any] = {}
        self._last_client_info: dict[str, Any] = {}
        self.widget, layout = scroll_page(QtWidgets)
        from localflight.native.shell_widgets import make_page_hero as _make_hero_f
        from localflight.native.qt_compat import import_qt as _import_qt_f

        _QtCore_f, _QtGui_f, _QtWidgets_f = _import_qt_f()
        self.hero = _make_hero_f(
            _QtCore_f,
            _QtGui_f,
            QtWidgets,
            emoji="\U0001F4AC",
            title="Report an Issue",
            subtitle="Your report is sanitized locally, forwarded through the hosted relay reporting gateway, and filed into the developer issue inbox.",
            info_text="Provider keys, activation tokens, raw install IDs, and other secrets are never included in reports.",
            actions=(),
            show_last_refreshed=False,
        )
        layout.addWidget(self.hero)
        self.summary = QtWidgets.QLineEdit()
        self.summary.setPlaceholderText("Short summary, e.g. Radar not loading")
        self.body = QtWidgets.QPlainTextEdit()
        self.body.setPlaceholderText("Steps to reproduce, what you expected, what happened instead...")
        self.sysinfo = QtWidgets.QPlainTextEdit()
        self.sysinfo.setReadOnly(True)
        self.sysinfo.setMaximumHeight(210)
        self.status = label(QtWidgets, "Manual reports are always available.", "Muted", wrap=True)
        self.loading_indicator = _loading_indicator(QtWidgets)
        self.send_button = QtWidgets.QPushButton("Send Report")
        self.send_button.clicked.connect(self.send)
        layout.addWidget(section_label(QtWidgets, "⚠️  What went wrong?"))
        layout.addWidget(self.summary)
        layout.addWidget(section_label(QtWidgets, "\U0001F4DD  Details"))
        layout.addWidget(self.body, 1)
        layout.addWidget(section_label(QtWidgets, "\U0001F4CE  Attached automatically"))
        layout.addWidget(self.sysinfo)
        layout.addWidget(self.send_button)
        layout.addWidget(self.loading_indicator)
        layout.addWidget(self.status)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def refresh(self) -> None:
        _set_native_feedback(self, "Loading local report context...", busy=True)
        try:
            cfg, sysinfo, client_info = self.service.feedback_context()
        except NativeApiError:
            _set_native_feedback(self, "Report context is unavailable. You can still type a manual report.", "StatusWarn")
            return
        self._last_cfg = cfg
        self._last_system = sysinfo
        self._last_client_info = client_info
        self.sysinfo.setPlainText(
            f"Airport: {cfg.get('airport_iata')}/{cfg.get('airport_icao')}\n"
            f"Source:  {cfg.get('source')}\n"
            f"Version: {sysinfo.get('version')}\n"
            f"Platform: {sysinfo.get('platform')}\n"
            f"Diagnostics: {cfg.get('diagnostics_mode')}\n"
            f"Install ID: {client_info.get('install_id') or 'local'}\n"
            f"Relay: {client_info.get('relay_url') or 'not configured'}\n"
            f"Activation: {'present' if (client_info.get('activation_token_present') or client_info.get('has_activation_token')) else 'not stored'}"
        )
        _set_native_feedback(self, "Report context loaded. Review it before sending.", "StatusGood")

    def send(self) -> None:
        title = self.summary.text().strip()
        if not title:
            _set_native_feedback(self, "Add a short summary first.", "StatusWarn")
            return
        description = self.body.toPlainText().strip()
        if len(description) < 12:
            _set_native_feedback(self, "Add a few details so the report is useful.", "StatusWarn")
            return
        self.send_button.setEnabled(False)
        _set_native_feedback(self, "Sending sanitized report...", busy=True)
        try:
            result = self.service.send_feedback(
                {
                    "title": title,
                    "description": description,
                    "client_context": self._client_context(),
                }
            )
        except NativeApiError as exc:
            _set_native_feedback(self, f"Report failed: {exc}", "StatusBad")
            self.send_button.setEnabled(True)
            return
        _set_native_feedback(self, self._status_message(result), "StatusGood" if result.get("ok", True) else "StatusWarn")
        self.send_button.setEnabled(True)
        try:
            from localflight.native.qt_compat import import_qt as _import_qt_fb
            from localflight.native.shell_widgets import show_toast as _toast_fb

            _QtCore_fb, _QtGui_fb, _QtWidgets_fb = _import_qt_fb()
            ok = bool(result.get("ok", True))
            _toast_fb(
                _QtCore_fb,
                _QtGui_fb,
                _QtWidgets_fb,
                self.widget,
                text="Report sent. Thank you!" if ok else "Report submission warning",
                tone="good" if ok else "warn",
            )
        except Exception:
            pass

    def _client_context(self) -> str:
        cfg = self._last_cfg or {}
        sysinfo = self._last_system or {}
        client_info = self._last_client_info or {}
        airport = cfg.get("airport_iata") or cfg.get("airport_icao") or "unknown"
        parts = [
            "native/gui",
            "screen=feedback",
            f"route=/api/feedback",
            "owner=client",
            f"app_version={sysinfo.get('version') or _app_version()}",
            f"source={cfg.get('source') or 'unknown'}",
            f"airport={airport}",
            f"platform={sysinfo.get('platform') or 'unknown'}",
        ]
        if client_info.get("relay_url"):
            parts.append("relay=configured")
        if client_info.get("activation_token_present") or client_info.get("has_activation_token"):
            parts.append("activation=present")
        return "; ".join(parts)

    def _status_message(self, result: dict[str, Any]) -> str:
        message = str(result.get("message") or "").strip()
        if not message:
            if result.get("deduped"):
                message = "Report already received recently; no duplicate Linear issue was created."
            else:
                message = "Report sent. Thank you."
        extras: list[str] = []
        if result.get("team"):
            extras.append(f"queue {result.get('team')}")
        if result.get("url"):
            extras.append(str(result.get("url")))
        return message if not extras else f"{message} ({' | '.join(extras)})"


def _item(QtWidgets: Any, value: Any) -> Any:
    text = format_value(value)
    item = QtWidgets.QTableWidgetItem(text)
    item.setToolTip(text)
    return item


def _qcolor_alpha(QtGui: Any, hex_color: str, alpha: int) -> Any:
    color = QtGui.QColor(hex_color)
    color.setAlpha(alpha)
    return color


def _strip(QtWidgets: Any, text: str) -> Any:
    box = QtWidgets.QFrame()
    box.setObjectName("WeatherStrip")
    layout = QtWidgets.QHBoxLayout(box)
    layout.setContentsMargins(10, 7, 10, 7)
    layout.addWidget(label(QtWidgets, text, "Muted", wrap=True))
    return box


def _loading_indicator(QtWidgets: Any) -> Any:
    """Unified rotating-glyph spinner that replaces the old marquee bar.

    Falls back to a thin QProgressBar marquee only if the spinner cannot
    be constructed (headless / very early init).
    """
    try:
        from localflight.native.qt_compat import import_qt
        from localflight.native.shell_widgets import make_spinner

        QtCore, QtGui, _QtWidgets = import_qt()
        return make_spinner(QtCore, QtGui, QtWidgets)
    except Exception:
        progress = QtWidgets.QProgressBar()
        progress.setObjectName("LoadingProgress")
        progress.setRange(0, 0)
        progress.setTextVisible(False)
        progress.setFixedHeight(7)
        progress.hide()
        return progress


def _set_native_feedback(screen: Any, text: str, role: str = "Muted", *, busy: bool = False) -> None:
    status = getattr(screen, "status", None)
    if status is not None:
        status.setText(text)
        status.setObjectName(role)
        try:
            status.style().unpolish(status)
            status.style().polish(status)
        except Exception:
            pass
    loading = getattr(screen, "loading_indicator", None)
    if loading is not None:
        loading.setVisible(bool(busy))
    if busy:
        try:
            screen.QtWidgets.QApplication.processEvents()
        except Exception:
            pass


def _banner(QtWidgets: Any, text: str, role: str) -> Any:
    box = QtWidgets.QFrame()
    box.setObjectName(role)
    layout = QtWidgets.QHBoxLayout(box)
    layout.setContentsMargins(10, 7, 10, 7)
    layout.addWidget(label(QtWidgets, text, "Muted", wrap=True))
    box.hide()
    return box


def _weather_line(payload: dict[str, Any], *, raw: bool) -> str:
    icon = _weather_icon_glyph(payload.get("weather_icon"))
    cat = str(payload.get("flight_cat") or "").strip().upper()
    temp_text = str(payload.get("temperature_short") or payload.get("temperature_display") or "").strip()
    if not temp_text:
        temp = payload.get("temperature_c", payload.get("temp_c"))
        temp_text = f"{temp}°C" if temp is not None else ""
    summary = _passenger_weather_label(
        payload.get("condition_display")
        or payload.get("weather_label")
        or payload.get("weather_display")
        or payload.get("weather_summary")
        or payload.get("decoded_summary")
        or "Weather observed"
    )
    parts = [icon, summary]
    if temp_text:
        parts.append(_clean_temperature_text(temp_text))
    if cat:
        parts.append(_flight_category_hint(cat))
    raw_text = payload.get("raw_text") or payload.get("raw") or ""
    line = " · ".join(part for part in parts if part)
    return line + (f" · METAR {raw_text}" if raw and raw_text else "")


def _passenger_weather_label(value: Any) -> str:
    text = str(value or "").strip()
    normalized = re.sub(r"[_-]+", " ", text).strip().lower()
    mapping = {
        "clear": "Clear skies",
        "sunny": "Sunny",
        "partly": "Partly cloudy",
        "partly cloudy": "Partly cloudy",
        "cloud": "Cloudy",
        "cloudy": "Cloudy",
        "rain": "Rain nearby",
        "light rain": "Light rain",
        "snow": "Snow",
        "fog": "Foggy",
        "fog / haze": "Fog or haze",
        "low visibility": "Low visibility",
        "windy": "Windy",
        "storm": "Storm nearby",
        "thunderstorm": "Thunderstorm nearby",
    }
    if normalized in mapping:
        return mapping[normalized]
    if "clear" in normalized:
        return "Clear skies"
    if "partly" in normalized:
        return "Partly cloudy"
    if "rain" in normalized:
        return "Rain nearby"
    if "fog" in normalized or "haze" in normalized:
        return "Fog or haze"
    if "snow" in normalized:
        return "Snow"
    return text or "Weather observed"


def _flight_category_hint(category: str) -> str:
    return {
        "VFR": "good visibility",
        "MVFR": "reduced visibility",
        "IFR": "low cloud or visibility",
        "LIFR": "very low visibility",
    }.get(category.upper(), "")


def _clean_temperature_text(value: Any) -> str:
    text = str(value or "").strip()
    text = text.replace(" C", "°C").replace("C", "°C")
    text = text.replace("°°C", "°C")
    return text


def _weather_icon_glyph(icon_name: Any) -> str:
    from localflight.native.design import WEATHER_EMOJI

    icon = str(icon_name or "unknown").strip().lower()
    return WEATHER_EMOJI.get(icon, WEATHER_EMOJI["unknown"])


def _active_schedule_budget(aviation: dict[str, Any]) -> dict[str, Any]:
    mode = str(aviation.get("active_mode") or aviation.get("mode") or "").strip().lower()
    nested = aviation.get(mode)
    if isinstance(nested, dict):
        return nested
    if mode == "community" and isinstance(aviation.get("community"), dict):
        return aviation["community"]
    if mode == "managed" and isinstance(aviation.get("managed"), dict):
        return aviation["managed"]
    if mode == "byok" and isinstance(aviation.get("byok"), dict):
        return aviation["byok"]
    return aviation


def _budget_label(bucket: dict[str, Any]) -> str:
    mode = str(bucket.get("active_mode") or bucket.get("mode") or "unknown")
    used = bucket.get("calls_this_month") or 0
    limit = bucket.get("monthly_limit") or 0
    return f"{used} / {limit}" if limit else mode


def _budget_detail(bucket: dict[str, Any]) -> str:
    remaining = bucket.get("remaining")
    reset = bucket.get("period_end") or ""
    parts = []
    if remaining is not None:
        parts.append(f"{remaining} requests left")
    if reset:
        parts.append(f"resets {reset}")
    return " | ".join(parts)


if __name__ == "__main__":  # pragma: no cover - manual Qt entrypoint
    main()
