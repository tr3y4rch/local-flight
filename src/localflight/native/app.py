"""Native Local Flight user UI.

This shell is a Qt Widgets rebuild of the browser/kiosk experience. It keeps
the same local FastAPI contracts as the web UI, but does not embed a webview.
"""
from __future__ import annotations

import math
import json
import sys
import webbrowser
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Callable
from urllib.parse import urlparse

from localflight.native.api_client import LocalApiClient, NativeApiError
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
from localflight.native.qt_compat import import_qt
from localflight.storage.profiles import list_profiles

_API_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="lf-native-api")


def _native_ws_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    host = parsed.netloc or parsed.path
    return f"{scheme}://{host}/ws"


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
        return "0.2.5b4"


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
    pixmap = pixmap_from_media(QtCore, QtGui, "ui", "static", "splash_mark.svg", width=220, height=108)
    if pixmap.isNull():
        pixmap = pixmap_from_media(QtCore, QtGui, "assets", "icon_circle.svg", width=96, height=96)
    if pixmap.isNull():
        mark.setText("Local Flight")
        mark.setObjectName("Title")
    else:
        mark.setPixmap(pixmap)

    title = label(QtWidgets, "Local Flight", "Title")
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


class _AsyncFetchMixin:
    """Run slow local API calls away from the Qt UI thread."""

    def _init_async(self, QtCore: Any, owner: Any) -> None:
        self._pending_fetch: Future[Any] | None = None
        self._pending_apply: Callable[[Any], None] | None = None
        self._pending_error: Callable[[Exception], None] | None = None
        self._poll_timer = QtCore.QTimer(owner)
        self._poll_timer.setInterval(50)
        self._poll_timer.timeout.connect(self._poll_fetch)

    def _run_async(
        self,
        work: Callable[[], Any],
        apply: Callable[[Any], None],
        on_error: Callable[[Exception], None],
    ) -> bool:
        if self._pending_fetch is not None and not self._pending_fetch.done():
            return False
        self._pending_apply = apply
        self._pending_error = on_error
        self._pending_fetch = _API_EXECUTOR.submit(work)
        self._poll_timer.start()
        return True

    def _poll_fetch(self) -> None:
        future = self._pending_fetch
        if future is None or not future.done():
            return
        self._poll_timer.stop()
        self._pending_fetch = None
        apply = self._pending_apply
        on_error = self._pending_error
        self._pending_apply = None
        self._pending_error = None
        try:
            result = future.result()
        except Exception as exc:  # pragma: no cover - exercised by Qt runtime
            if on_error:
                on_error(exc)
            return
        if apply:
            apply(result)


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


def launch_native_app(
    *,
    base_url: str,
    first_launch: bool,
    fullscreen: bool = False,
) -> int:
    QtCore, QtGui, QtWidgets = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    app.setApplicationName("Local Flight")
    app_icon = icon_from_media(QtGui, "assets", "icon_circle.svg")
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
    splash = _build_splash(QtCore, QtGui, QtWidgets)
    splash.show()
    app.processEvents()

    windows: dict[str, Any] = {}

    def show_main_window() -> None:
        window = NativeMainWindow(QtCore, QtGui, QtWidgets, base_url=base_url, first_launch=False)
        if not app_icon.isNull():
            window.setWindowIcon(app_icon)
        if fullscreen:
            window.showFullScreen()
        else:
            window.resize(1280, 820)
            window.show()
        windows["main"] = window

    def setup_complete() -> None:
        show_main_window()
        setup_window = windows.get("setup")
        if setup_window is not None:
            setup_window.close()

    if first_launch:
        setup_window = NativeSetupWindow(
            QtCore,
            QtGui,
            QtWidgets,
            base_url=base_url,
            on_setup_complete=setup_complete,
        )
        if not app_icon.isNull():
            setup_window.setWindowIcon(app_icon)
        setup_window.resize(980, 720)
        setup_window.show()
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
                self.setWindowTitle("Local Flight Setup")
                self.setStyleSheet(native_stylesheet())
                self.setup_screen = SetupScreen(
                    QtCore,
                    QtWidgets,
                    self.client,
                    base_url,
                    on_setup_complete=on_setup_complete,
                )
                self.setCentralWidget(_as_widget(self.setup_screen))

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
                self.setWindowTitle("Local Flight Native")
                self.theme = "dark"
                self.skin = "standard"
                self.colors = colors_for(self.theme, self.skin)
                self.setStyleSheet(native_stylesheet(theme=self.theme, skin=self.skin))
                self._nav_buttons: dict[str, Any] = {}
                self.screens: list[Any] = []
                self.screen_keys: list[str] = []

                root = QtWidgets.QWidget()
                shell = QtWidgets.QVBoxLayout(root)
                shell.setContentsMargins(0, 0, 0, 0)
                shell.setSpacing(0)
                shell.addWidget(self._build_top_nav())

                self.stack = QtWidgets.QStackedWidget()
                shell.addWidget(self.stack, 1)
                self.setCentralWidget(root)

                self.first_launch = first_launch
                self._add_screen("display", "Display", DisplayScreen(QtCore, QtGui, QtWidgets, self.client), nav=True)
                self._add_screen("fids", "FIDS", FidsScreen(QtCore, QtGui, QtWidgets, self.client), nav=True)
                self._add_screen("radar", "Radar", RadarScreen(QtCore, QtGui, QtWidgets, self.client), nav=True)
                self._add_screen("matrix", "Matrix", MatrixScreen(QtWidgets, self.client), nav=True)
                self._add_screen("settings", "Settings", SettingsScreen(QtCore, QtGui, QtWidgets, self.client, base_url), nav=True)
                self._add_screen(
                    "admin",
                    "Admin",
                    AdminSummaryScreen(QtWidgets, self.client, navigate=self._show_page),
                    nav=True,
                )
                self._add_screen("history", "History", HistoryScreen(QtWidgets, self.client), nav=True)
                self._add_screen("logs", "Logs", LogsScreen(QtWidgets, self.client), nav=True)
                self._add_screen("requests", "Requests", RequestsScreen(QtWidgets, self.client), nav=False)
                self._add_screen("feedback", "Report", FeedbackScreen(QtWidgets, self.client), nav=True)

                self._load_design_from_config()
                self._show_page("display")

                self.clock_timer = QtCore.QTimer(self)
                self.clock_timer.timeout.connect(self._update_clocks)
                self.clock_timer.start(1000)
                self._update_clocks()

                self.refresh_timer = QtCore.QTimer(self)
                self.refresh_timer.timeout.connect(self._refresh_active)
                self.refresh_timer.start(30_000)

                self._ws_bridge = None
                try:
                    from PySide6 import QtWebSockets

                    self._ws_bridge = _NativeEventBridge(
                        QtCore,
                        QtWebSockets,
                        self,
                        base_url=base_url,
                        on_event=self._handle_live_event,
                        on_status=self._set_live_status,
                    )
                except Exception:
                    self._set_live_status("live push unavailable", False)
            def _build_top_nav(self) -> Any:
                nav = QtWidgets.QFrame()
                nav.setObjectName("TopNav")
                layout = QtWidgets.QHBoxLayout(nav)
                layout.setContentsMargins(14, 7, 14, 7)
                layout.setSpacing(8)

                brand_mark = QtWidgets.QLabel()
                brand_mark.setObjectName("BrandMark")
                brand_mark.setAlignment(QtCore.Qt.AlignCenter)
                brand_pixmap = pixmap_from_media(QtCore, QtGui, "assets", "icon_circle.svg", width=24, height=24)
                if brand_pixmap.isNull():
                    brand_mark.setText("*")
                else:
                    brand_mark.setPixmap(brand_pixmap)
                brand = QtWidgets.QLabel("Local Flight")
                brand.setObjectName("Brand")
                ver = QtWidgets.QLabel(f"v{_app_version()}")
                ver.setObjectName("Version")
                self.utc_clock = QtWidgets.QLabel("UTC --:--:--")
                self.utc_clock.setObjectName("ClockChip")
                self.local_clock = QtWidgets.QLabel("LT --:--:--")
                self.local_clock.setObjectName("ClockChip")
                self.live_status = QtWidgets.QLabel("LIVE --")
                self.live_status.setObjectName("ClockChip")
                self.nav_group = QtWidgets.QWidget()
                self.nav_layout = QtWidgets.QHBoxLayout(self.nav_group)
                self.nav_layout.setContentsMargins(0, 0, 0, 0)
                self.nav_layout.setSpacing(3)
                self.nav_scroll = QtWidgets.QScrollArea()
                self.nav_scroll.setObjectName("NavScroll")
                self.nav_scroll.setWidgetResizable(False)
                self.nav_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
                self.nav_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
                self.nav_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
                self.nav_scroll.setMinimumHeight(40)
                self.nav_scroll.setWidget(self.nav_group)
                quit_btn = QtWidgets.QPushButton("Power")
                quit_btn.setObjectName("Quiet")
                quit_btn.setToolTip("Shut down Local Flight")
                quit_btn.clicked.connect(self._quit_app)

                layout.addWidget(brand_mark)
                layout.addWidget(brand)
                layout.addWidget(ver)
                layout.addSpacing(8)
                layout.addWidget(self.utc_clock)
                layout.addWidget(self.local_clock)
                layout.addWidget(self.live_status)
                layout.addWidget(self.nav_scroll, 1)
                layout.addWidget(quit_btn)
                return nav

            def _add_screen(self, key: str, label_text: str, screen: Any, *, nav: bool) -> None:
                self.stack.addWidget(_as_widget(screen))
                self.screens.append(screen)
                self.screen_keys.append(key)
                if nav:
                    glyph = NAV_GLYPHS.get(key, "")
                    button = self.QtWidgets.QPushButton(f"{glyph} {label_text}".strip())
                    button.setObjectName("NavButton")
                    button.setCheckable(True)
                    button.setProperty("lf_label", label_text)
                    button.setProperty("lf_key", key)
                    button.setProperty("lf_glyph", glyph)
                    button.clicked.connect(lambda _checked=False, k=key: self._show_page(k))
                    self.nav_layout.addWidget(button)
                    self.nav_group.adjustSize()
                    self._nav_buttons[key] = button

            def _show_page(self, key: str) -> None:
                if key not in self.screen_keys:
                    return
                index = self.screen_keys.index(key)
                self.stack.setCurrentIndex(index)
                for page_key, button in self._nav_buttons.items():
                    button.setChecked(page_key == key)
                self._refresh_active()

            def _load_design_from_config(self) -> None:
                try:
                    cfg = self.client.get_json("/api/config")
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
                for screen in self.screens:
                    if hasattr(screen, "apply_theme"):
                        screen.apply_theme(theme, skin)

            def _update_clocks(self) -> None:
                now_utc = datetime.now(timezone.utc)
                now_local = datetime.now().astimezone()
                self.utc_clock.setText("UTC " + now_utc.strftime("%H:%M:%S"))
                self.local_clock.setText("LT " + now_local.strftime("%H:%M:%S"))

            def _refresh_active(self) -> None:
                index = self.stack.currentIndex()
                screen = self.screens[index] if 0 <= index < len(self.screens) else None
                if hasattr(screen, "refresh"):
                    screen.refresh()

            def _set_live_status(self, text: str, connected: bool) -> None:
                self.live_status.setText(("LIVE" if connected else "SYNC") + " " + text.replace("live push ", ""))
                self.live_status.setProperty("connected", connected)
                self.live_status.style().unpolish(self.live_status)
                self.live_status.style().polish(self.live_status)

            def _handle_live_event(self, payload: dict[str, Any]) -> None:
                event_type = str(payload.get("type") or "").strip()
                if not event_type:
                    return
                if event_type == "config_updated":
                    self._load_design_from_config()
                    for screen in self.screens:
                        if hasattr(screen, "handle_live_event"):
                            screen.handle_live_event(payload)
                    self._refresh_active()
                    return
                screen = self.screens[self.stack.currentIndex()] if 0 <= self.stack.currentIndex() < len(self.screens) else None
                if hasattr(screen, "handle_live_event"):
                    screen.handle_live_event(payload)
                elif event_type in {"snapshot_updated", "scheduler_restarted"}:
                    self._refresh_active()

            def _after_setup_complete(self) -> None:
                self._show_page("display")

            def _quit_app(self) -> None:
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
                        "This closes the native shell and asks the local backend to stop cleanly.",
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
                if dialog.exec() != self.QtWidgets.QDialog.Accepted:
                    return
                try:
                    self.client.post_json("/api/quit", {})
                except NativeApiError:
                    pass
                QtWidgets.QApplication.quit()

            def resizeEvent(self, event: Any) -> None:
                super().resizeEvent(event)
                compact = self.width() < 1160
                tiny = self.width() < 760
                self.utc_clock.setVisible(not tiny)
                self.local_clock.setVisible(not tiny)
                self.live_status.setVisible(self.width() >= 640)
                for button in self._nav_buttons.values():
                    glyph = str(button.property("lf_glyph") or "")
                    text = str(button.property("lf_label") or "")
                    button.setText(glyph if compact and glyph else f"{glyph} {text}".strip())
                    button.setMinimumWidth(42 if compact else 72)

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
    ) -> None:
        self.QtCore = QtCore
        self.QtWidgets = QtWidgets
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.on_setup_complete = on_setup_complete
        self._airport_search_future: Future[Any] | None = None
        self._last_airport_query = ""
        self._stored_activation = False
        self._mode_initialized = False
        self.step_names = ["Airport", "Source", "Keys", "Finish"]
        self.step_buttons: list[Any] = []
        self.source_buttons: dict[str, Any] = {}

        self.widget, layout = scroll_page(QtWidgets)
        layout.setSpacing(14)
        hero = QtWidgets.QFrame()
        hero.setObjectName("Panel")
        hero_layout = QtWidgets.QVBoxLayout(hero)
        hero_layout.setContentsMargins(20, 18, 20, 18)
        hero_layout.setSpacing(8)
        hero_layout.addWidget(label(QtWidgets, "Local Flight Setup", "Title"))
        hero_layout.addWidget(
            label(
                QtWidgets,
                "Pick your airport, choose the data path, and Local Flight opens the native display when this is done.",
                "Muted",
                wrap=True,
            )
        )
        self.status = label(QtWidgets, "Setup is local-first. You can change these choices later in Settings.", "Muted", wrap=True)
        hero_layout.addWidget(self.status)
        layout.addWidget(hero)

        steps = QtWidgets.QHBoxLayout()
        for idx, name in enumerate(self.step_names):
            button = QtWidgets.QPushButton(f"{idx + 1}. {name}")
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, i=idx: self._set_step(i))
            self.step_buttons.append(button)
            steps.addWidget(button)
        steps.addStretch(1)
        layout.addLayout(steps)

        self.tabs = QtWidgets.QStackedWidget()
        self.search_timer = QtCore.QTimer(self.widget)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._start_airport_search)
        self.search_poll_timer = QtCore.QTimer(self.widget)
        self.search_poll_timer.setInterval(50)
        self.search_poll_timer.timeout.connect(self._poll_airport_search)

        self._build_airport_page()
        self._build_source_page()
        self._build_keys_page()
        self._build_finish_page()
        layout.addWidget(self.tabs, 1)

        nav = QtWidgets.QHBoxLayout()
        self.back_btn = QtWidgets.QPushButton("Back")
        self.back_btn.setObjectName("Quiet")
        self.next_btn = QtWidgets.QPushButton("Next")
        self.finish_btn = QtWidgets.QPushButton("Finish setup")
        self.web_fallback_btn = QtWidgets.QPushButton("Open web setup fallback")
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
        layout.addLayout(nav)
        layout.addStretch(1)
        self._set_step(0)
        self.refresh()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def _page(self, title: str, text: str) -> tuple[Any, Any]:
        page = self.QtWidgets.QFrame()
        page.setObjectName("Panel")
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
        self.airport_search.textChanged.connect(lambda _text: self.search_timer.start(250))
        self.airport_results = self.QtWidgets.QListWidget()
        self.airport_results.setMinimumHeight(150)
        self.airport_results.itemClicked.connect(self._select_airport_item)
        self.display_name = self.QtWidgets.QLineEdit("Local Flight")
        self.airport_iata = self.QtWidgets.QLineEdit("ZRH")
        self.airport_icao = self.QtWidgets.QLineEdit("LSZH")
        self.timezone = self.QtWidgets.QLineEdit("Europe/Zurich")
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
        for col, (mode, title, body, glyph) in enumerate(
            (
                ("community", "Community Relay", "Shared airport snapshots through the hosted beta relay.", NAV_GLYPHS.get("radar", "")),
                ("byok", "BYOK AviationStack", "Use your own API key and keep provider calls local.", NAV_GLYPHS.get("settings", "")),
                ("virtual", "Virtual / VATSIM", "No paid schedule key. Uses live VATSIM flight-network data.", NAV_GLYPHS.get("fids", "")),
            )
        ):
            button = self.QtWidgets.QPushButton(f"{glyph} {title}\n{body}".strip())
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setMinimumHeight(88)
            button.clicked.connect(lambda _checked=False, m=mode: self._set_mode(m))
            self.source_buttons[mode] = button
            cards.addWidget(button, 0, col)
        layout.addLayout(cards)
        self.mode_help = label(self.QtWidgets, "", "Muted", wrap=True)
        layout.addWidget(self.mode_help)

        relay_box, relay_layout = panel(self.QtWidgets, "Community Relay")
        self.relay_url = self.QtWidgets.QLineEdit("https://localflight-community-relay.fly.dev")
        self.relay_url.setPlaceholderText("https://localflight-community-relay.fly.dev")
        self.activation_token = self.QtWidgets.QLineEdit()
        self.activation_token.setEchoMode(self.QtWidgets.QLineEdit.Password)
        self.activation_token.setPlaceholderText("Only needed when a token is not already stored")
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

    def _build_finish_page(self) -> None:
        _page, layout = self._page(
            "Ready to Launch",
            "This saves local configuration, writes the selected environment values, starts the scheduler, and opens the native display.",
        )
        self.finish_summary = label(self.QtWidgets, "", "Muted", wrap=True)
        self.diagnostics_note = label(
            self.QtWidgets,
            "Bug reports are not auto-enabled here. Manual reports stay available, and diagnostics can be changed later in Settings.",
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

    def _set_mode(self, mode: str) -> None:
        idx = self.setup_mode.findData(mode)
        self.setup_mode.setCurrentIndex(idx if idx >= 0 else 0)
        for key, button in self.source_buttons.items():
            button.setChecked(key == mode)
        self._sync_mode_ui()
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
        self.finish_summary.setText(
            "\n".join(
                [
                    f"Airport: {self.airport_iata.text().strip().upper() or 'ZRH'} / {self.airport_icao.text().strip().upper() or 'LSZH'}",
                    f"Timezone: {self.timezone.text().strip() or 'Europe/Zurich'}",
                    f"Mode: {self._mode_label(mode)}",
                    f"Source: {source}",
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

    def refresh(self) -> None:
        try:
            info = self.client.get_json("/api/setup/client-info")
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
            lambda: self.client.get_any_json("/api/airports/search", params={"q": query, "limit": 12})
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
            result = self.client.post_json("/api/setup/activate", self._activation_payload())
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
            result = self.client.post_json("/api/setup/client-status", self._activation_payload())
        except NativeApiError as exc:
            self.status.setText(f"Status check failed: {exc}")
            return
        self.status.setText(format_value(result.get("status") or result))

    def test_activation(self) -> None:
        try:
            result = self.client.post_json("/api/setup/test-activation", self._activation_payload())
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
            result = self.client.post_json(path, {"key": key})
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
            "relay_url": self._clean_relay_display(self.relay_url.text()) if mode == "community" else "",
            "activation_token": self.activation_token.text().strip() if mode == "community" else "",
            "aviationstack_key": self.aviationstack_key.text().strip() if mode == "byok" else "",
            "rapidapi_key": self.rapidapi_key.text().strip() if mode == "byok" else "",
            "opensky_id": self.opensky_id.text().strip() if mode == "byok" else "",
            "opensky_secret": self.opensky_secret.text().strip() if mode == "byok" else "",
        }
        try:
            result = self.client.post_json("/api/setup/complete", payload)
        except NativeApiError as exc:
            self.status.setText(f"Setup failed: {exc}")
            return
        self.status.setText("Setup complete. Opening the native display..." if result.get("ok", True) else format_value(result))
        if result.get("ok", True):
            try:
                self.client.clear_cache()
            except Exception:
                pass
            if self.on_setup_complete:
                self.on_setup_complete()


class FidsScreen(_AsyncFetchMixin):  # pragma: no cover - optional Qt runtime
    def __init__(self, QtCore: Any, QtGui: Any, QtWidgets: Any, client: LocalApiClient, *, embedded: bool = False) -> None:
        self.QtCore = QtCore
        self.QtGui = QtGui
        self.QtWidgets = QtWidgets
        self.client = client
        self.embedded = embedded
        self.view = "departures"
        self.rows: list[dict[str, Any]] = []
        self.row_limit = 20
        self.rotation_seconds = 8
        self.page_index = 0
        self.colors = colors_for()

        self.widget = QtWidgets.QSplitter()
        self._init_async(QtCore, self.widget)
        self.escape_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Escape"), self.widget)
        self.escape_shortcut.activated.connect(lambda: self.drawer.hide())
        self.page_timer = QtCore.QTimer(self.widget)
        self.page_timer.timeout.connect(self._advance_page)
        self.widget.setChildrenCollapsible(False)
        board = QtWidgets.QFrame()
        board.setObjectName("Page")
        board_layout = QtWidgets.QVBoxLayout(board)
        board_layout.setContentsMargins(18, 18, 18, 18)
        board_layout.setSpacing(10)

        header = QtWidgets.QHBoxLayout()
        title_box = QtWidgets.QVBoxLayout()
        self.airport = QtWidgets.QLabel("LOCAL")
        self.airport.setObjectName("AirportCode")
        self.title = QtWidgets.QLabel("Departures")
        self.title.setObjectName("Title")
        if embedded:
            self.airport.hide()
            self.title.hide()
        title_box.addWidget(self.airport)
        title_box.addWidget(self.title)
        header.addLayout(title_box)
        if not embedded:
            header.addStretch(1)
        self.arr_btn = self._segment_button("ARR", "arrivals")
        self.dep_btn = self._segment_button("DEP", "departures")
        self.dep_btn.setChecked(True)
        refresh = QtWidgets.QPushButton("Refresh board")
        refresh.clicked.connect(self.refresh)
        self.live_dot = label(QtWidgets, chr(9679), "LiveDot")
        self.last_updated = label(QtWidgets, "LT --:--:--", "Muted")
        header.addWidget(self.live_dot)
        header.addWidget(self.last_updated)
        header.addWidget(self.arr_btn)
        header.addWidget(self.dep_btn)
        header.addWidget(refresh)
        if embedded:
            header.addStretch(1)

        self.weather = _strip(QtWidgets, "Weather loading...")
        self.error_banner = _banner(QtWidgets, "Data fetch error", "ErrorBanner")
        self.info_banner = _banner(
            QtWidgets,
            "Fetching schedule data. If Community Relay is warming this airport, it can take a moment.",
            "InfoBanner",
        )
        self.status = label(QtWidgets, "Waiting for first board refresh...", "Muted")

        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setObjectName("FidsTable")
        self.table.setHorizontalHeaderLabels(["Time (LT)", "Flight", "To", "Status", "Gate", "A/C"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.cellClicked.connect(self._show_detail_for_row)
        self.table.setWordWrap(True)
        self.table.setShowGrid(False)
        self.table.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.table.horizontalHeader().setDefaultAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self.table.horizontalHeader().setMinimumSectionSize(64)

        board_layout.addLayout(header)
        board_layout.addWidget(self.weather)
        board_layout.addWidget(self.error_banner)
        board_layout.addWidget(self.info_banner)
        board_layout.addWidget(self.status)
        board_layout.addWidget(self.table, 1)

        self.drawer = self._build_detail_drawer()
        self.drawer.hide()
        self.widget.addWidget(board)
        self.widget.addWidget(self.drawer)
        self.widget.setSizes([940, 340])

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def apply_theme(self, theme: str, skin: str) -> None:
        self.colors = colors_for(theme, skin)
        self._render_rows()

    def _segment_button(self, text: str, view: str) -> Any:
        button = self.QtWidgets.QPushButton(text)
        button.setObjectName("SegmentButton")
        button.setCheckable(True)
        button.clicked.connect(lambda _checked=False, v=view: self.set_view(v))
        return button

    def _build_detail_drawer(self) -> Any:
        drawer = self.QtWidgets.QFrame()
        drawer.setObjectName("Drawer")
        drawer.setMinimumWidth(330)
        drawer.setMaximumWidth(430)
        layout = self.QtWidgets.QVBoxLayout(drawer)
        layout.setContentsMargins(16, 16, 16, 16)
        head = self.QtWidgets.QHBoxLayout()
        self.detail_title = label(self.QtWidgets, "Flight detail", "Title")
        close = self.QtWidgets.QPushButton("Close")
        close.setObjectName("Quiet")
        close.clicked.connect(drawer.hide)
        head.addWidget(self.detail_title)
        head.addStretch(1)
        head.addWidget(close)
        self.detail_route = label(self.QtWidgets, "", "Muted", wrap=True)
        self.detail_body = self.QtWidgets.QTextEdit()
        self.detail_body.setReadOnly(True)
        layout.addLayout(head)
        layout.addWidget(self.detail_route)
        layout.addWidget(self.detail_body, 1)
        return drawer

    def set_view(self, view: str) -> None:
        self.view = view
        self.arr_btn.setChecked(view == "arrivals")
        self.dep_btn.setChecked(view == "departures")
        self.refresh()

    def handle_live_event(self, payload: dict[str, Any]) -> None:
        event_type = str(payload.get("type") or "")
        if event_type in {"snapshot_updated", "config_updated"}:
            self.refresh()
        elif event_type == "scheduler_restarted":
            self.status.setText("Scheduler restarted. Refreshing board...")
            self.refresh()

    def refresh(self) -> None:
        view = self.view
        started = self._run_async(
            lambda: self._fetch_board(view),
            self._apply_board,
            self._board_error,
        )
        if started:
            self.status.setText(f"Loading {view} without blocking the UI...")

    def _fetch_board(self, view: str) -> dict[str, Any]:
        cfg = self.client.get_json("/api/config")
        payload = self.client.get_any_json("/api/fids", params={"view": view, "limit": 80})
        weather: dict[str, Any] | None = None
        weather_error = ""
        try:
            weather = self.client.get_json("/api/metar")
        except NativeApiError as exc:
            weather_error = str(exc)
        return {"view": view, "cfg": cfg, "payload": payload, "weather": weather, "weather_error": weather_error}

    def _apply_board(self, result: dict[str, Any]) -> None:
        cfg = result["cfg"]
        view = str(result["view"])
        self.error_banner.hide()
        weather = result.get("weather")
        if isinstance(weather, dict):
            self.weather.findChild(self.QtWidgets.QLabel).setText(_weather_line(weather, raw=False))
        else:
            self.weather.findChild(self.QtWidgets.QLabel).setText(f"Weather unavailable: {result.get('weather_error') or 'offline'}")

        airport = str(cfg.get("airport_iata") or cfg.get("airport_icao") or "LOCAL").upper()
        source = str(cfg.get("source") or "real").upper()
        self.airport.setText(airport)
        if not self.embedded:
            self.title.setText("Arrivals" if view == "arrivals" else "Departures")
        self.table.setHorizontalHeaderLabels(["Time (LT)", "Flight", "From" if view == "arrivals" else "To", "Status", "Gate", "A/C"])
        self.rows = list_payload(result.get("payload"))
        self.row_limit = max(5, int(cfg.get("web_row_limit") or 20))
        self.rotation_seconds = max(3, int(cfg.get("web_rotation_seconds") or 8))
        self.page_index = 0
        self.info_banner.setVisible(not self.rows)
        self.last_updated.setText("LT " + datetime.now().astimezone().strftime("%H:%M:%S"))
        page_count = max(1, math.ceil(len(self.rows) / max(1, self.row_limit)))
        self.status.setText(f"{len(self.rows)} {view} loaded | source {source} | page 1/{page_count} | local API /api/fids")
        if len(self.rows) > self.row_limit:
            self.page_timer.start(self.rotation_seconds * 1000)
        else:
            self.page_timer.stop()
        self._render_rows()

    def _board_error(self, exc: Exception) -> None:
        self.error_banner.show()
        self.status.setText(f"Board offline: {exc}")

    def _render_rows(self) -> None:
        self.table.clearContents()
        self.table.clearSpans()
        if not self.rows:
            self.table.setRowCount(1)
            item = self.QtWidgets.QTableWidgetItem("No flights in window - schedule data may still be warming.")
            self.table.setSpan(0, 0, 1, 6)
            self.table.setItem(0, 0, item)
            return
        start = self.page_index * self.row_limit
        visible = self.rows[start : start + self.row_limit] or self.rows[: self.row_limit]
        self.table.setRowCount(len(visible))
        for row_idx, row in enumerate(visible):
            self.table.setItem(row_idx, 0, _item(self.QtWidgets, row.get("display_time") or "-"))
            time_item = self.table.item(row_idx, 0)
            if time_item is not None:
                font = time_item.font()
                font.setBold(True)
                time_item.setFont(font)
            flight_text = str(row.get("flight_display") or row.get("callsign") or "-")
            airline = str(row.get("airline_display") or "")
            codeshares = str(row.get("codeshare_display") or "")
            flight_lines = [flight_text]
            if airline:
                flight_lines.append(airline)
            if codeshares:
                flight_lines.append(codeshares)
            flight_item = _item(self.QtWidgets, "\n".join(flight_lines))
            flight_item.setToolTip("\n".join(flight_lines))
            flight_font = flight_item.font()
            flight_font.setBold(True)
            flight_item.setFont(flight_font)
            self.table.setItem(row_idx, 1, flight_item)
            route_item = _item(self.QtWidgets, row.get("route_display") or "-")
            route_item.setForeground(self.QtGui.QColor(self.colors["text"]))
            self.table.setItem(row_idx, 2, route_item)
            status_item = _item(self.QtWidgets, row.get("status_display") or "-")
            self._style_status_item(status_item, str(row.get("status_class") or row.get("status_display") or ""))
            self.table.setItem(row_idx, 3, status_item)
            gate_item = _item(self.QtWidgets, row.get("gate") or "-")
            gate_item.setForeground(self.QtGui.QColor(self.colors["muted"]))
            self.table.setItem(row_idx, 4, gate_item)
            ac_item = _item(self.QtWidgets, row.get("aircraft_type") or "-")
            ac_item.setForeground(self.QtGui.QColor(self.colors["muted"]))
            self.table.setItem(row_idx, 5, ac_item)
            self.table.setRowHeight(row_idx, 58 if airline or codeshares else 42)
        self.table.setColumnWidth(0, 92)
        self.table.setColumnWidth(1, 170)
        self.table.setColumnWidth(2, 230)
        self.table.setColumnWidth(3, 118)
        self.table.setColumnWidth(4, 74)
        self.table.horizontalHeader().setStretchLastSection(True)

    def _style_status_item(self, item: Any, status: str) -> None:
        status_l = status.lower()
        if any(part in status_l for part in ("delay", "late")):
            color = self.QtGui.QColor(self.colors["amber"])
        elif any(part in status_l for part in ("board", "land", "arriv")):
            color = self.QtGui.QColor(self.colors["green"])
        elif any(part in status_l for part in ("cancel", "divert")):
            color = self.QtGui.QColor(self.colors["red"])
        elif any(part in status_l for part in ("depart", "past")):
            color = self.QtGui.QColor(self.colors["dim"])
        else:
            color = self.QtGui.QColor(self.colors["blue"])
        bg = self.QtGui.QColor(color)
        bg.setAlpha(34)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        item.setForeground(color)
        item.setBackground(bg)

    def _advance_page(self) -> None:
        if len(self.rows) <= self.row_limit:
            return
        page_count = max(1, math.ceil(len(self.rows) / max(1, self.row_limit)))
        self.page_index = (self.page_index + 1) % page_count
        self.status.setText(f"{len(self.rows)} {self.view} loaded | page {self.page_index + 1}/{page_count} | rotating every {self.rotation_seconds}s")
        self._render_rows()

    def _show_detail_for_row(self, row_idx: int, _col: int) -> None:
        actual_idx = self.page_index * self.row_limit + row_idx
        if actual_idx < 0 or actual_idx >= len(self.rows):
            return
        callsign = str(self.rows[actual_idx].get("callsign") or "").strip()
        if not callsign:
            return
        self.drawer.show()
        self.detail_title.setText(self.rows[actual_idx].get("flight_display") or callsign)
        self.detail_route.setText("Loading detail...")
        self.detail_body.setPlainText("")
        started = self._run_async(
            lambda: self.client.get_json("/api/fids/detail", params={"callsign": callsign}),
            self._apply_detail,
            lambda exc: self.detail_route.setText(f"Detail unavailable: {exc}"),
        )
        if not started:
            self.detail_route.setText("Board refresh is still running. Try the row again in a moment.")

    def _apply_detail(self, payload: dict[str, Any]) -> None:
        detail = payload.get("detail") if isinstance(payload.get("detail"), dict) else payload
        history = payload.get("history") if isinstance(payload.get("history"), list) else []
        origin = detail.get("origin_iata") or "-"
        dest = detail.get("dest_iata") or "-"
        airline = detail.get("airline_display") or detail.get("airline_name") or ""
        self.detail_route.setText(f"{origin} -> {dest}" + (f" | {airline}" if airline else ""))
        mode = str(detail.get("detail_mode") or "real").strip().lower()
        lines = self._virtual_detail_lines(detail) if mode == "virtual" else self._real_detail_lines(detail)
        if history:
            lines.append("")
            lines.append("Recent history")
            for item in history[:8]:
                lines.append(
                    f"- {item.get('date', '')}: {item.get('status', '')} "
                    f"{format_value(item.get('delay_minutes'))} min"
                )
        self.detail_body.setPlainText("\n".join(lines))

    def _real_detail_lines(self, detail: dict[str, Any]) -> list[str]:
        return self._section_lines(
            ("Schedule", [
                ("Status", detail.get("status") or detail.get("status_display")),
                ("Scheduled", detail.get("sched_time")),
                ("Estimated", detail.get("est_time")),
                ("Actual", detail.get("actual_time")),
                ("Delay", self._minutes(detail.get("delay_minutes"))),
            ]),
            ("Airport operations", [
                ("Origin", self._airport_line(detail, "origin")),
                ("Destination", self._airport_line(detail, "dest")),
                ("Terminal", detail.get("terminal")),
                ("Gate", detail.get("gate")),
            ]),
            ("Aircraft", [
                ("Type", detail.get("aircraft_type")),
                ("Registration", detail.get("aircraft_registration")),
                ("Flight", detail.get("flight_display") or detail.get("callsign")),
                ("Codeshares", ", ".join(detail.get("codeshares") or [])),
            ]),
            ("Source confidence", [
                ("Schedule source", value_at(detail, "data_sources.schedule") or detail.get("source")),
                ("Live enrichment", detail.get("enriched_by") or value_at(detail, "data_sources.enrichment")),
                ("Confidence", value_at(detail, "data_sources.confidence")),
                ("Snapshot age", self._seconds(value_at(detail, "data_sources.snapshot_age_seconds"))),
            ]),
            ("Live track", [
                ("Latitude", value_at(detail, "position.lat")),
                ("Longitude", value_at(detail, "position.lon")),
                ("Altitude", self._altitude(value_at(detail, "position.altitude_m"))),
                ("Ground speed", self._speed(value_at(detail, "position.speed_ms"))),
                ("Heading", self._heading(value_at(detail, "position.heading"))),
                ("On ground", value_at(detail, "position.on_ground")),
                ("Squawk", value_at(detail, "position.squawk")),
            ]),
        )

    def _virtual_detail_lines(self, detail: dict[str, Any]) -> list[str]:
        return self._section_lines(
            ("Virtual flight", [
                ("Callsign", detail.get("callsign")),
                ("Flight", detail.get("flight_display") or detail.get("flight_number")),
                ("Aircraft", detail.get("aircraft_type")),
                ("Status", detail.get("status") or detail.get("status_display")),
                ("Source", value_at(detail, "data_sources.schedule") or detail.get("source")),
            ]),
            ("Flight plan", [
                ("Origin", self._airport_line(detail, "origin")),
                ("Destination", self._airport_line(detail, "dest")),
                ("Rules", value_at(detail, "flight_plan.flight_rules")),
                ("Route", value_at(detail, "flight_plan.route")),
                ("Cruise altitude", value_at(detail, "flight_plan.cruise_altitude")),
                ("Cruise TAS", value_at(detail, "flight_plan.cruise_tas")),
                ("Planned departure", value_at(detail, "flight_plan.planned_departure")),
                ("Planned arrival", value_at(detail, "flight_plan.planned_arrival")),
                ("Enroute", self._minutes(value_at(detail, "flight_plan.enroute_minutes"))),
                ("Alternate", value_at(detail, "flight_plan.alternate_icao")),
                ("Squawk", value_at(detail, "flight_plan.assigned_transponder") or value_at(detail, "position.squawk")),
            ]),
            ("Network position", [
                ("Latitude", value_at(detail, "position.lat")),
                ("Longitude", value_at(detail, "position.lon")),
                ("Altitude", self._altitude(value_at(detail, "position.altitude_m"))),
                ("Ground speed", self._speed(value_at(detail, "position.speed_ms"))),
                ("Heading", self._heading(value_at(detail, "position.heading"))),
                ("On ground", value_at(detail, "position.on_ground")),
                ("Last contact", value_at(detail, "position.last_contact")),
            ]),
            ("Freshness", [
                ("Snapshot generated", value_at(detail, "data_sources.snapshot_generated_at")),
                ("Snapshot age", self._seconds(value_at(detail, "data_sources.snapshot_age_seconds"))),
                ("Position age", self._seconds(value_at(detail, "data_sources.position_age_seconds"))),
            ]),
        )

    def _section_lines(self, *sections: tuple[str, list[tuple[str, Any]]]) -> list[str]:
        lines: list[str] = []
        for title, fields in sections:
            visible = [(name, value) for name, value in fields if format_value(value)]
            if not visible:
                continue
            if lines:
                lines.append("")
            lines.append(title)
            lines.append("-" * len(title))
            for name, value in visible:
                lines.append(f"{name}: {format_value(value)}")
        return lines or ["No detail fields available for this flight yet."]

    def _airport_line(self, detail: dict[str, Any], prefix: str) -> str:
        iata = detail.get(f"{prefix}_iata")
        icao = detail.get(f"{prefix}_icao")
        name = detail.get(f"{prefix}_name")
        codes = " / ".join(str(v) for v in (iata, icao) if v)
        return (codes + (f" - {name}" if name else "")).strip()

    def _altitude(self, value: Any) -> str:
        try:
            meters = float(value)
        except (TypeError, ValueError):
            return ""
        return f"{int(round(meters * 3.28084))} ft"

    def _speed(self, value: Any) -> str:
        try:
            meters_s = float(value)
        except (TypeError, ValueError):
            return ""
        return f"{int(round(meters_s * 1.94384))} kt"

    def _heading(self, value: Any) -> str:
        try:
            return f"{int(round(float(value))) % 360} deg"
        except (TypeError, ValueError):
            return ""

    def _minutes(self, value: Any) -> str:
        try:
            minutes = int(value)
        except (TypeError, ValueError):
            return ""
        if minutes == 0:
            return "0 min"
        hours, mins = divmod(abs(minutes), 60)
        sign = "-" if minutes < 0 else ""
        if hours:
            return f"{sign}{hours}h {mins}m"
        return f"{sign}{mins} min"

    def _seconds(self, value: Any) -> str:
        try:
            seconds = int(value)
        except (TypeError, ValueError):
            return ""
        if seconds < 90:
            return f"{seconds}s"
        return self._minutes(round(seconds / 60))


class RadarCanvas:  # pragma: no cover - optional Qt runtime
    def __new__(cls, QtCore: Any, QtGui: Any, QtWidgets: Any):
        class _Canvas(QtWidgets.QWidget):
            def __init__(self) -> None:
                super().__init__()
                self.setMouseTracking(True)
                self.setMinimumSize(420, 420)
                self.blips: list[dict[str, Any]] = []
                self.surface: list[dict[str, Any]] = []
                self.center = {"lat": 0.0, "lon": 0.0}
                self.radius_nm = 5.0
                self.status = "No radar data yet"
                self.attribution = ""
                self.sweep_angle = 0.0
                self.colors = colors_for()
                self._sweep_timer = QtCore.QTimer(self)
                self._sweep_interval_ms = 66
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
                self.blips = [b for b in payload.get("blips", []) if isinstance(b, dict)]
                self.radius_nm = float(payload.get("radius_nm") or self.radius_nm)
                center = payload.get("center") if isinstance(payload.get("center"), dict) else {}
                if center:
                    self.center = {
                        "lat": float(center.get("lat") or self.center.get("lat") or 0.0),
                        "lon": float(center.get("lon") or self.center.get("lon") or 0.0),
                    }
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
                for feature in self.surface:
                    points = feature.get("points")
                    if not isinstance(points, list) or len(points) < 2:
                        continue
                    kind = str(feature.get("kind") or "taxiway")
                    poly = []
                    for point in points:
                        if isinstance(point, list) and len(point) >= 2:
                            x_nm, y_nm = self._latlon_to_nm(float(point[0]), float(point[1]))
                            poly.append(QtCore.QPointF(cx + (x_nm / self.radius_nm) * radius, cy - (y_nm / self.radius_nm) * radius))
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
                    if kind == "runway" and feature.get("label") and len(poly) >= 2:
                        mid = poly[len(poly) // 2]
                        painter.setPen(QtGui.QColor(self.colors["text"]))
                        painter.drawText(mid, str(feature.get("label"))[:12])

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
        self.canvas = RadarCanvas(QtCore, QtGui, QtWidgets)
        self.status = label(QtWidgets, "Initialising radar...", "Muted")
        layout.addLayout(top)
        layout.addWidget(self.weather)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.status)
        self.radius_nm = 5
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
        )
        if started:
            self.status.setText(f"Loading {radius}nm radar without blocking the UI...")

    def handle_live_event(self, payload: dict[str, Any]) -> None:
        event_type = str(payload.get("type") or "")
        if event_type in {"snapshot_updated", "scheduler_restarted", "config_updated"}:
            self.refresh()

    def _fetch_radar(self, radius: int) -> dict[str, Any]:
        surface: dict[str, Any] | None = None
        surface_error = ""
        try:
            cfg = self.client.get_json("/api/config")
            if cfg.get("radar_surface_enabled"):
                try:
                    surface = self.client.get_json("/api/radar/surface", params={"radius_nm": min(5, radius)})
                except NativeApiError as exc:
                    surface_error = str(exc)
        except NativeApiError:
            pass
        payload = self.client.get_json("/api/radar", params={"radius_nm": float(radius)})
        weather: dict[str, Any] | None = None
        try:
            weather = self.client.get_json("/api/metar")
        except NativeApiError:
            pass
        return {"payload": payload, "surface": surface, "surface_error": surface_error, "weather": weather}

    def _apply_radar(self, result: dict[str, Any]) -> None:
        payload = result["payload"]
        if isinstance(result.get("surface"), dict):
            self.canvas.set_surface(result["surface"])
        if isinstance(result.get("weather"), dict):
            self.weather.findChild(self.QtWidgets.QLabel).setText(_weather_line(result["weather"], raw=True))
        self.canvas.set_payload(payload)
        hidden_airborne = int(payload.get("hidden_airborne_count") or 0)
        hidden_ground = int(payload.get("hidden_ground_count") or 0)
        hidden = f" | {hidden_airborne} airborne hidden" if hidden_airborne else (f" | {hidden_ground} ground hidden" if hidden_ground else "")
        surface_note = f" | surface unavailable: {result['surface_error']}" if result.get("surface_error") else ""
        self.status.setText(
            f"{payload.get('count', 0)} visible | mode {payload.get('radar_mode', 'airborne')} | "
            f"source {payload.get('source', 'unknown')}{hidden}{surface_note}"
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
        for key, text in (("fids", "FIDS"), ("split", "Split"), ("radar", "Radar")):
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
        self.fids = FidsScreen(QtCore, QtGui, QtWidgets, client, embedded=True)
        self.radar = RadarScreen(QtCore, QtGui, QtWidgets, client, embedded=True)
        self.splitter.addWidget(_as_widget(self.fids))
        self.splitter.addWidget(_as_widget(self.radar))
        saved = self.settings.value("display/splitter_sizes")
        if isinstance(saved, list) and len(saved) == 2:
            self.splitter.setSizes([int(saved[0]), int(saved[1])])
        else:
            self.splitter.setSizes([720, 560])
        self.splitter.splitterMoved.connect(lambda *_args: self._save_splitter())
        layout.addLayout(top)
        layout.addWidget(self.splitter, 1)
        self.mode = "split"
        self.set_mode("split")

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

    def handle_live_event(self, payload: dict[str, Any]) -> None:
        self.live.setText(f"Live push: {payload.get('type', 'event')}")
        if self.mode in {"fids", "split"}:
            self.fids.handle_live_event(payload)
        if self.mode in {"radar", "split"}:
            self.radar.handle_live_event(payload)


class MatrixCanvas:  # pragma: no cover - optional Qt runtime
    def __new__(cls, QtCore: Any, QtGui: Any, QtWidgets: Any):
        class _Canvas(QtWidgets.QWidget):
            def __init__(self) -> None:
                super().__init__()
                self.setMinimumHeight(260)
                self.rows: list[dict[str, Any]] = []
                self.panel_w = 256
                self.panel_h = 64
                self.brightness = 0.8
                self.zoom = 3
                self.animate = True
                self.phase = 0
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
                self.update()

            def set_options(self, *, panel_w: int, panel_h: int, brightness: float, zoom: int, animate: bool) -> None:
                self.panel_w = panel_w
                self.panel_h = panel_h
                self.brightness = brightness
                self.zoom = zoom
                self.animate = animate
                self.update()

            def _tick(self) -> None:
                if self.animate:
                    self.phase = (self.phase + 1) % 12
                    self.update()

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
                font = QtGui.QFont("Consolas", max(7, int(7 * scale)))
                font.setBold(True)
                painter.setFont(font)
                row_h = board_h / max(1, min(4, len(self.rows) or 4))
                text_color = QtGui.QColor(self.colors["cyan"])
                text_color.setAlpha(max(90, int(255 * self.brightness)))
                painter.setPen(text_color)
                visible = self.rows[:4] or [{"display_time": "--:--", "flight_display": "LOCAL FLIGHT", "route_display": "Waiting for schedule", "status_display": "READY"}]
                for idx, row in enumerate(visible):
                    y = top + idx * row_h + row_h * 0.62
                    shift = self.phase if self.animate and idx == 0 else 0
                    text = f"{row.get('display_time') or '--:--'}  {row.get('flight_display') or '-'}  {row.get('route_display') or '-'}  {row.get('status_display') or '-'}"
                    painter.drawText(int(left + 10 - shift), int(y), text[:58])

        return _Canvas()


class MatrixScreen:  # pragma: no cover - optional Qt runtime
    def __init__(self, QtWidgets: Any, client: LocalApiClient) -> None:
        self.QtWidgets = QtWidgets
        self.client = client
        QtCore, QtGui, QtWidgets2 = import_qt()
        self.widget, layout = scroll_page(QtWidgets)
        header = QtWidgets.QHBoxLayout()
        header.addWidget(label(QtWidgets, "Matrix Preview", "Title"))
        header.addStretch(1)
        refresh = QtWidgets.QPushButton("Refresh preview")
        save = QtWidgets.QPushButton("Save matrix config")
        script = QtWidgets.QPushButton("Generate main.py")
        refresh.clicked.connect(self.refresh)
        save.clicked.connect(self.save_config)
        script.clicked.connect(self.generate_script)
        header.addWidget(refresh)
        header.addWidget(save)
        header.addWidget(script)
        self.status = label(QtWidgets, "LED canvas preview, runtime config, and MicroPython export.", "Muted", wrap=True)
        controls, form = panel(QtWidgets, "Matrix Controls")
        self.panel_preset = QtWidgets.QComboBox()
        for text, w, h in (("256 x 64 Interstate 75 W", 256, 64), ("128 x 64", 128, 64), ("512 x 64", 512, 64)):
            self.panel_preset.addItem(text, (w, h))
        self.zoom = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.zoom.setRange(1, 8)
        self.zoom.setValue(3)
        self.brightness = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.brightness.setRange(5, 100)
        self.brightness.setValue(80)
        self.view = QtWidgets.QComboBox()
        self.view.addItems(["departures", "arrivals"])
        self.refresh_seconds = QtWidgets.QSpinBox()
        self.refresh_seconds.setRange(10, 3600)
        self.refresh_seconds.setSuffix("s")
        self.rotation_seconds = QtWidgets.QSpinBox()
        self.rotation_seconds.setRange(3, 120)
        self.rotation_seconds.setSuffix("s")
        self.max_rows = QtWidgets.QSpinBox()
        self.max_rows.setRange(1, 8)
        self.animate = QtWidgets.QCheckBox("Split-flap animation")
        self.animate.setChecked(True)
        self.wifi_ssid = QtWidgets.QLineEdit()
        self.wifi_ssid.setPlaceholderText("WiFi SSID")
        self.wifi_password = QtWidgets.QLineEdit()
        self.wifi_password.setPlaceholderText("WiFi password")
        self.wifi_password.setEchoMode(QtWidgets.QLineEdit.Password)
        self.api_host = QtWidgets.QLineEdit("localflight.local")
        self.api_port = QtWidgets.QSpinBox()
        self.api_port.setRange(1, 65535)
        self.api_port.setValue(8000)
        form_layout = QtWidgets.QFormLayout()
        form_layout.addRow("Panel preset", self.panel_preset)
        form_layout.addRow("Zoom", self.zoom)
        form_layout.addRow("Brightness", self.brightness)
        form_layout.addRow("Default view", self.view)
        form_layout.addRow("Max rows", self.max_rows)
        form_layout.addRow("Refresh", self.refresh_seconds)
        form_layout.addRow("Page rotation", self.rotation_seconds)
        form_layout.addRow("Animation", self.animate)
        form_layout.addRow("WiFi SSID", self.wifi_ssid)
        form_layout.addRow("WiFi password", self.wifi_password)
        form_layout.addRow("Server host", self.api_host)
        form_layout.addRow("Server port", self.api_port)
        form.addLayout(form_layout)
        self.panel_preset.currentIndexChanged.connect(self._sync_canvas_options)
        self.zoom.valueChanged.connect(self._sync_canvas_options)
        self.brightness.valueChanged.connect(self._sync_canvas_options)
        self.animate.stateChanged.connect(self._sync_canvas_options)
        self.view.currentTextChanged.connect(lambda _text: self.refresh())
        self.canvas = MatrixCanvas(QtCore, QtGui, QtWidgets2)
        self.script_preview = QtWidgets.QPlainTextEdit()
        self.script_preview.setReadOnly(True)
        self.script_preview.setPlaceholderText("Generated MicroPython main.py appears here.")
        self.script_preview.setMaximumHeight(180)
        layout.addLayout(header)
        layout.addWidget(self.status)
        layout.addWidget(controls)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(section_label(QtWidgets, "Generated Script Preview"))
        layout.addWidget(self.script_preview)
        self._sync_canvas_options()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def apply_theme(self, theme: str, skin: str) -> None:
        if hasattr(self.canvas, "apply_theme"):
            self.canvas.apply_theme(theme, skin)

    def refresh(self) -> None:
        try:
            cfg = self.client.get_json("/api/matrix/config")
            payload = self.client.get_any_json("/api/fids", params={"view": self.view.currentText(), "limit": 32})
        except NativeApiError as exc:
            self.status.setText(f"Matrix preview offline: {exc}")
            return
        self._populate_config(cfg)
        rows = list_payload(payload)[: max(1, int(self.max_rows.value()))]
        self.status.setText(f"{len(rows)} rows loaded | {self.view.currentText()} | canvas preview.")
        self.canvas.set_rows(rows)
        self._sync_canvas_options()

    def _populate_config(self, cfg: dict[str, Any]) -> None:
        self.brightness.setValue(int(float(cfg.get("brightness", 0.8)) * 100))
        self.max_rows.setValue(int(cfg.get("max_rows") or 4))
        self.refresh_seconds.setValue(int(cfg.get("refresh_seconds") or 60))
        self.rotation_seconds.setValue(int(cfg.get("page_rotation_seconds") or 10))
        self.view.setCurrentText(str(cfg.get("default_view") or "departures"))

    def _panel_size(self) -> tuple[int, int]:
        data = self.panel_preset.currentData()
        return data if isinstance(data, tuple) else (256, 64)

    def _sync_canvas_options(self) -> None:
        w, h = self._panel_size()
        self.canvas.set_options(
            panel_w=w,
            panel_h=h,
            brightness=self.brightness.value() / 100.0,
            zoom=int(self.zoom.value()),
            animate=bool(self.animate.isChecked()),
        )

    def save_config(self) -> None:
        payload = {
            "brightness": self.brightness.value() / 100.0,
            "max_rows": int(self.max_rows.value()),
            "refresh_seconds": int(self.refresh_seconds.value()),
            "default_view": self.view.currentText(),
            "page_rotation_seconds": int(self.rotation_seconds.value()),
        }
        try:
            result = self.client.post_json("/api/matrix/config", payload)
        except NativeApiError as exc:
            self.status.setText(f"Matrix save failed: {exc}")
            return
        self.status.setText("Matrix config saved." if result.get("ok") else format_value(result))

    def generate_script(self) -> None:
        w, h = self._panel_size()
        payload = {
            "wifi_ssid": self.wifi_ssid.text().strip() or "Your WiFi",
            "wifi_password": self.wifi_password.text(),
            "api_host": self.api_host.text().strip() or "localflight.local",
            "api_port": int(self.api_port.value()),
            "panel_w": w,
            "panel_h": h,
            "max_rows": int(self.max_rows.value()),
            "refresh_seconds": int(self.refresh_seconds.value()),
            "brightness": self.brightness.value() / 100.0,
            "default_view": self.view.currentText(),
            "page_rotation_seconds": int(self.rotation_seconds.value()),
        }
        try:
            text = self.client.post_text("/api/matrix/script", payload)
        except NativeApiError as exc:
            self.status.setText(f"Script generation failed: {exc}")
            return
        self.script_preview.setPlainText(text)
        self.status.setText("Generated matrix main.py preview. Copy it to the Pico when ready.")


class SettingsScreen:  # pragma: no cover - optional Qt runtime
    def __init__(self, QtCore: Any, QtGui: Any, QtWidgets: Any, client: LocalApiClient, base_url: str) -> None:
        self.QtWidgets = QtWidgets
        self.QtCore = QtCore
        self.QtGui = QtGui
        self.client = client
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
        for title, slug in (("Project README", "readme"), ("Privacy & diagnostics", "privacy"), ("Release notes", "changelog")):
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
            cfg = self.client.get_json("/api/config")
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
            lambda: self.client.get_any_json("/api/airports/search", params={"q": query, "limit": 10})
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
            info = self.client.get_json("/api/setup/client-info")
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
            self.client.patch_json("/api/config", self._config_payload())
        except NativeApiError as exc:
            self.status.setText(f"Save failed: {exc}")
            return
        self.status.setText("Settings saved. Scheduler restarts automatically when needed.")

    def restart_scheduler(self) -> None:
        try:
            result = self.client.post_json("/api/admin/scheduler/restart", {})
        except NativeApiError as exc:
            self.status.setText(f"Restart failed: {exc}")
            return
        self.status.setText(str(result.get("message") or "Scheduler restart requested."))

    def reset_setup(self) -> None:
        if self.QtWidgets.QMessageBox.question(self.widget, "Re-run setup", "Clear setup marker and restart the setup wizard?") != self.QtWidgets.QMessageBox.Yes:
            return
        try:
            self.client.post_json("/api/setup/reset", {})
        except NativeApiError as exc:
            self.status.setText(f"Setup reset failed: {exc}")
            return
        self.status.setText("Setup marker removed. Open setup on next launch or via browser fallback.")

    def save_profile(self) -> None:
        name = self.profile_name.text().strip()
        if not name:
            self.status.setText("Enter a profile name first.")
            return
        try:
            self.client.post_form("/profiles/save", {"profile_name": name})
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
            self.client.post_form("/profiles/load", {"profile_name": name})
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
            self.client.post_form("/profiles/delete", {"profile_name": name})
        except NativeApiError as exc:
            self.status.setText(f"Profile delete failed: {exc}")
            return
        self.status.setText(f"Profile deleted: {name}")
        self._refresh_profiles()


class AdminSummaryScreen:  # pragma: no cover - optional Qt runtime
    def __init__(self, QtWidgets: Any, client: LocalApiClient, *, navigate: Callable[[str], None]) -> None:
        self.QtWidgets = QtWidgets
        self.client = client
        self.navigate = navigate
        self.widget, self.layout = scroll_page(QtWidgets)
        head = QtWidgets.QHBoxLayout()
        head.addWidget(label(QtWidgets, "System Overview", "Title"))
        head.addStretch(1)
        refresh = QtWidgets.QPushButton("Refresh overview")
        refresh.clicked.connect(self.refresh)
        head.addWidget(refresh)
        self.status = label(QtWidgets, "Status, access, devices, weather, and quick tools.", "Muted", wrap=True)
        self.grid = QtWidgets.QGridLayout()
        self.detail_layout = QtWidgets.QVBoxLayout()
        self.quick = QtWidgets.QHBoxLayout()
        for text, key in (("Open display", "display"), ("Open radar", "radar"), ("Open settings", "settings"), ("Traffic log", "requests"), ("Report a problem", "feedback")):
            button = QtWidgets.QPushButton(text)
            button.clicked.connect(lambda _checked=False, k=key: self.navigate(k))
            self.quick.addWidget(button)
        self.layout.addLayout(head)
        self.layout.addWidget(self.status)
        self.layout.addLayout(self.grid)
        self.layout.addLayout(self.detail_layout)
        self.layout.addWidget(section_label(QtWidgets, "Quick Tools"))
        self.layout.addLayout(self.quick)
        self.layout.addStretch(1)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def refresh(self) -> None:
        try:
            system = self.client.get_json("/api/admin/system")
            budget = self.client.get_json("/api/admin/budget")
            connections = self.client.get_json("/api/admin/connections")
            scheduler = self.client.get_json("/api/admin/scheduler")
            updates = self.client.get_json("/api/admin/updates")
            weather = self.client.get_json("/api/metar")
            history = self.client.get_json("/api/history/stats")
        except NativeApiError as exc:
            self.status.setText(f"Admin offline: {exc}")
            return
        clear_layout(self.grid)
        clear_layout(self.detail_layout)
        aviation = budget.get("aviationstack") if isinstance(budget.get("aviationstack"), dict) else {}
        community = budget.get("community") if isinstance(budget.get("community"), dict) else {}
        cards = [
            card(self.QtWidgets, "Flight Refresh", scheduler.get("state") or scheduler.get("status") or "unknown", scheduler.get("airport") or ""),
            card(self.QtWidgets, "Schedule Access", _budget_label(aviation, community), _budget_detail(aviation, community)),
            card(self.QtWidgets, "Connected Screens", connections.get("count", 0), f"{connections.get('companion_count', 0)} companions"),
            card(self.QtWidgets, "Flight History", history.get("rows") or history.get("row_count") or 0, "Local 90-day database"),
            card(self.QtWidgets, "App & Device", system.get("version") or _app_version(), system.get("platform") or ""),
            card(self.QtWidgets, "Airport Weather", weather.get("weather_label") or weather.get("flight_cat") or "-", weather.get("decoded_summary") or ""),
            card(self.QtWidgets, "Latest Release", updates.get("latest_version") or updates.get("status") or "-", updates.get("message") or ""),
        ]
        for idx, widget in enumerate(cards):
            self.grid.addWidget(widget, idx // 3, idx % 3)
        used = aviation.get("calls_this_month") or community.get("calls_this_month") or 0
        limit = aviation.get("monthly_limit") or community.get("monthly_limit") or 0
        self.detail_layout.addWidget(progress_card(self.QtWidgets, "Schedule Access Budget", used, limit, _budget_detail(aviation, community)))
        device_rows = list_payload(connections, "devices") or list_payload(connections, "recent")
        if device_rows:
            self.detail_layout.addWidget(section_label(self.QtWidgets, "Connected Screens"))
            self.detail_layout.addWidget(
                table(
                    self.QtWidgets,
                    device_rows[:8],
                    [("device", "Device"), ("client_type", "Type"), ("platform", "Platform"), ("last_seen", "Last seen")],
                    min_height=140,
                )
            )
        weather_detail = weather.get("decoded_summary") or weather.get("raw_text") or weather.get("raw") or ""
        if weather_detail:
            self.detail_layout.addWidget(section_label(self.QtWidgets, "Airport Weather"))
            self.detail_layout.addWidget(pill(self.QtWidgets, f"{weather.get('weather_icon') or ''} {weather.get('flight_cat') or '-'} | {weather_detail}"))
        self.status.setText("Overview refreshed from local user-facing admin APIs.")


class RequestsScreen:  # pragma: no cover - optional Qt runtime
    def __init__(self, QtWidgets: Any, client: LocalApiClient) -> None:
        self.QtWidgets = QtWidgets
        self.client = client
        self.widget, self.layout = scroll_page(QtWidgets)
        head = QtWidgets.QHBoxLayout()
        head.addWidget(label(QtWidgets, "Traffic Log", "Title"))
        head.addStretch(1)
        self.hours = QtWidgets.QComboBox()
        for value, text in ((1, "Last hour"), (6, "Last 6h"), (24, "Last 24h"), (168, "Last 7d")):
            self.hours.addItem(text, value)
        self.client_type = QtWidgets.QComboBox()
        for label_text, value in (("all clients", "all"), ("web", "web"), ("native", "native"), ("mobile", "mobile"), ("matrix", "matrix"), ("api", "api")):
            self.client_type.addItem(label_text, value)
        refresh = QtWidgets.QPushButton("Refresh traffic")
        refresh.clicked.connect(self.refresh)
        head.addWidget(self.hours)
        head.addWidget(self.client_type)
        head.addWidget(refresh)
        self.status = label(QtWidgets, "Local anonymized request log. Hidden unless network tools are enabled.", "Muted", wrap=True)
        self.summary_grid = QtWidgets.QGridLayout()
        self.table = QtWidgets.QTableWidget(0, 8)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.layout.addLayout(head)
        self.layout.addWidget(self.status)
        self.layout.addLayout(self.summary_grid)
        self.layout.addWidget(self.table, 1)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def refresh(self) -> None:
        params = {"hours": int(self.hours.currentData()), "limit": 300}
        selected_client_type = str(self.client_type.currentData() or "all")
        if selected_client_type != "all":
            params["client_type"] = selected_client_type
        try:
            payload = self.client.get_json("/api/admin/requests", params=params)
        except NativeApiError as exc:
            self.status.setText(f"Traffic log unavailable: {exc}")
            return
        clear_layout(self.summary_grid)
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        cards = [
            card(self.QtWidgets, "Requests", summary.get("total_requests") or summary.get("total") or len(list_payload(payload, "requests"))),
            card(self.QtWidgets, "Clients", summary.get("clients") or summary.get("client_count") or "-"),
            card(self.QtWidgets, "Errors", summary.get("errors") or summary.get("error_count") or 0),
        ]
        for idx, widget in enumerate(cards):
            self.summary_grid.addWidget(widget, 0, idx)
        rows = list_payload(payload, "requests")
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
        self.status.setText(f"{len(rows)} anonymized local request rows loaded.")


class HistoryScreen:  # pragma: no cover - optional Qt runtime
    def __init__(self, QtWidgets: Any, client: LocalApiClient) -> None:
        self.QtWidgets = QtWidgets
        self.client = client
        self.rows: list[dict[str, Any]] = []
        self.all_rows: list[dict[str, Any]] = []
        self.widget = QtWidgets.QSplitter()
        body, layout = scroll_page(QtWidgets)
        header = QtWidgets.QHBoxLayout()
        header.addWidget(label(QtWidgets, "History", "Title"))
        header.addStretch(1)
        self.callsign = QtWidgets.QLineEdit()
        self.callsign.setPlaceholderText("Callsign")
        self.hours = QtWidgets.QComboBox()
        for value, text in ((6, "Last 6h"), (24, "Last 24h"), (168, "Last 7d"), (720, "Last 30d")):
            self.hours.addItem(text, value)
        self.direction = QtWidgets.QComboBox()
        self.direction.addItems(["both", "dep", "arr"])
        apply = QtWidgets.QPushButton("Apply")
        apply.clicked.connect(self.refresh)
        search = QtWidgets.QPushButton("Search")
        search.clicked.connect(self.search_callsign)
        clear = QtWidgets.QPushButton("Clear")
        clear.setObjectName("Quiet")
        clear.clicked.connect(self.clear_search)
        self.status_filter = QtWidgets.QComboBox()
        self.status_filter.addItems(["all statuses", "scheduled", "boarding", "delayed", "departed", "arrived", "cancelled"])
        self.status_filter.currentTextChanged.connect(lambda _text: self._apply_local_filters())
        header.addWidget(self.callsign)
        header.addWidget(search)
        header.addWidget(clear)
        header.addWidget(self.hours)
        header.addWidget(self.direction)
        header.addWidget(self.status_filter)
        header.addWidget(apply)
        self.status = label(QtWidgets, "90-day local database. Click any row for details.", "Muted", wrap=True)
        self.tabs = QtWidgets.QTabWidget()
        self.table = QtWidgets.QTableWidget(0, 10)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSortingEnabled(True)
        self.table.cellClicked.connect(self._show_row_detail)
        self.stats_body = QtWidgets.QWidget()
        self.stats_outer_layout = QtWidgets.QVBoxLayout(self.stats_body)
        self.stats_period = QtWidgets.QComboBox()
        for value, text in ((6, "6 hours"), (24, "24 hours"), (168, "7 days"), (720, "30 days")):
            self.stats_period.addItem(text, value)
        self.stats_period.currentIndexChanged.connect(lambda _idx: self._render_stats())
        self.stats_outer_layout.addWidget(self.stats_period)
        self.stats_content = QtWidgets.QWidget()
        self.stats_layout = QtWidgets.QVBoxLayout(self.stats_content)
        self.stats_outer_layout.addWidget(self.stats_content, 1)
        self.tabs.addTab(self.table, "Browse")
        self.tabs.addTab(self.stats_body, "Stats")
        layout.addLayout(header)
        layout.addWidget(self.status)
        layout.addWidget(self.tabs, 1)
        self.detail = self._detail_panel()
        self.detail.hide()
        self.widget.addWidget(body)
        self.widget.addWidget(self.detail)
        self.widget.setSizes([930, 350])

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def _detail_panel(self) -> Any:
        detail = self.QtWidgets.QFrame()
        detail.setObjectName("Drawer")
        detail.setMaximumWidth(420)
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

    def refresh(self) -> None:
        try:
            payload = self.client.get_json(
                "/api/history",
                params={"hours": int(self.hours.currentData()), "direction": self.direction.currentText(), "limit": 500},
            )
        except NativeApiError as exc:
            self.status.setText(f"History offline: {exc}")
            return
        self.all_rows = list_payload(payload, "flights")
        self._apply_local_filters(render=False)
        self.status.setText(f"{payload.get('count', len(self.rows))} records | {payload.get('airport_iata', 'airport')}")
        self._render_table()
        self._render_stats()

    def search_callsign(self) -> None:
        callsign = self.callsign.text().strip().upper()
        if not callsign:
            self.refresh()
            return
        try:
            payload = self.client.get_json("/api/history/flight", params={"callsign": callsign, "days": 30})
        except NativeApiError as exc:
            self.status.setText(f"Callsign search failed: {exc}")
            return
        self.all_rows = list_payload(payload, "flights")
        self._apply_local_filters(render=False)
        self.status.setText(f"{len(self.rows)} records for {callsign}")
        self._render_table()

    def clear_search(self) -> None:
        self.callsign.clear()
        self.refresh()

    def _apply_local_filters(self, *, render: bool = True) -> None:
        status = self.status_filter.currentText().replace("all statuses", "").strip().lower()
        if status:
            self.rows = [row for row in self.all_rows if status in str(row.get("status") or "").lower()]
        else:
            self.rows = list(self.all_rows)
        if render:
            self._render_table()

    def _render_table(self) -> None:
        set_table_rows(
            self.table,
            self.QtWidgets,
            self.rows[:300],
            [
                ("sched_time", "Scheduled"),
                ("direction", "Dir"),
                ("flight_number", "Flight"),
                ("callsign", "Callsign"),
                ("origin_iata", "From"),
                ("dest_iata", "To"),
                ("status", "Status"),
                ("gate", "Gate"),
                ("aircraft_type", "A/C"),
                ("source", "Source"),
            ],
        )

    def _render_stats(self) -> None:
        clear_layout(self.stats_layout)
        try:
            summary = self.client.get_json("/api/history/summary", params={"hours": int(self.stats_period.currentData())})
        except NativeApiError as exc:
            self.stats_layout.addWidget(label(self.QtWidgets, f"Stats unavailable: {exc}", "Muted", wrap=True))
            return
        kpis = summary.get("kpis") if isinstance(summary.get("kpis"), dict) else summary
        grid = self.QtWidgets.QGridLayout()
        for idx, (title, key) in enumerate((("Flights tracked", "total"), ("Departures", "departures"), ("Arrivals", "arrivals"), ("On time", "on_time"), ("Avg delay", "avg_delay_minutes"))):
            grid.addWidget(card(self.QtWidgets, title, value_at(kpis, key) or summary.get(key)), idx // 3, idx % 3)
        self.stats_layout.addLayout(grid)
        for section in ("top_airlines", "top_destinations", "top_origins", "top_aircraft"):
            rows = list_payload(summary, section)
            if rows:
                self.stats_layout.addWidget(section_label(self.QtWidgets, section.replace("_", " ").title()))
                self.stats_layout.addWidget(bar_summary(self.QtWidgets, rows))
                self.stats_layout.addWidget(table(self.QtWidgets, rows, [("label", "Name"), ("count", "Count")], min_height=120))
        self.stats_layout.addStretch(1)

    def _show_row_detail(self, row_idx: int, _col: int) -> None:
        if row_idx < 0 or row_idx >= len(self.rows):
            return
        row = self.rows[row_idx]
        self.detail_title.setText(str(row.get("flight_number") or row.get("callsign") or "Flight"))
        lines = [f"{key}: {format_value(value)}" for key, value in row.items() if value not in (None, "")]
        self.detail_text.setPlainText("\n".join(lines))
        self.detail.show()


class LogsScreen:  # pragma: no cover - optional Qt runtime
    def __init__(self, QtWidgets: Any, client: LocalApiClient) -> None:
        self.client = client
        self.QtWidgets = QtWidgets
        QtCore, _QtGui, _QtWidgets = import_qt()
        self._known_files: list[str] = []
        self.widget, layout = scroll_page(QtWidgets)
        head = QtWidgets.QHBoxLayout()
        head.addWidget(label(QtWidgets, "Logs", "Title"))
        head.addStretch(1)
        self.file_combo = QtWidgets.QComboBox()
        self.file_combo.currentTextChanged.connect(lambda _name: self.refresh())
        self.live_tail = QtWidgets.QCheckBox("Live tail")
        self.live_tail.setChecked(False)
        self.live_tail.toggled.connect(self._toggle_live)
        self.auto_scroll = QtWidgets.QCheckBox("Scroll to bottom")
        self.auto_scroll.setChecked(True)
        refresh = QtWidgets.QPushButton("Refresh logs")
        refresh.clicked.connect(self.refresh)
        head.addWidget(self.file_combo)
        head.addWidget(self.live_tail)
        head.addWidget(self.auto_scroll)
        head.addWidget(refresh)
        self.status = label(QtWidgets, "Local log tail for troubleshooting.", "Muted", wrap=True)
        self.meta = label(QtWidgets, "No log metadata loaded yet.", "Muted")
        self.text = QtWidgets.QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMinimumHeight(560)
        self.timer = QtCore.QTimer()
        self.timer.setInterval(2500)
        self.timer.timeout.connect(self.refresh)
        layout.addLayout(head)
        layout.addWidget(self.status)
        layout.addWidget(self.meta)
        layout.addWidget(self.text, 1)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def refresh(self) -> None:
        try:
            selected = self.file_combo.currentText().strip() or None
            meta = self.client.get_json("/api/logs", params={"file": selected} if selected else None)
            self._sync_file_combo(list_payload(meta, "files"), str(meta.get("selected") or ""))
            selected = self.file_combo.currentText().strip() or meta.get("selected") or None
            payload = self.client.get_json("/logs/tail", params={"file": selected, "after": 0} if selected else {"after": 0})
        except NativeApiError as exc:
            self.status.setText(f"Logs unavailable: {exc}")
            return
        lines = payload.get("lines") if isinstance(payload.get("lines"), list) else []
        self.text.setPlainText("\n".join(str(line) for line in lines[-500:]))
        if self.auto_scroll.isChecked():
            self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())
        total = int(payload.get("total") or len(lines))
        shown = min(len(lines), 500)
        self.status.setText(f"{selected or 'default log'} | {total} lines available | showing last {shown}")
        self.meta.setText(f"Updated {datetime.now().strftime('%H:%M:%S')} | files retained locally | live tail {'on' if self.live_tail.isChecked() else 'off'}")

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
        self.widget, layout = scroll_page(QtWidgets)
        layout.addWidget(label(QtWidgets, "Report an Issue", "Title"))
        layout.addWidget(label(QtWidgets, "Your report is sanitized locally, forwarded through the hosted relay reporting gateway, and filed into the developer issue inbox.", "Muted", wrap=True))
        self.summary = QtWidgets.QLineEdit()
        self.summary.setPlaceholderText("Short summary, e.g. Radar not loading")
        self.body = QtWidgets.QPlainTextEdit()
        self.body.setPlaceholderText("Steps to reproduce, what you expected, what happened instead...")
        self.sysinfo = QtWidgets.QPlainTextEdit()
        self.sysinfo.setReadOnly(True)
        self.sysinfo.setMaximumHeight(210)
        self.status = label(QtWidgets, "Manual reports are always available.", "Muted", wrap=True)
        self.send_button = QtWidgets.QPushButton("Send Report")
        self.send_button.clicked.connect(self.send)
        layout.addWidget(section_label(QtWidgets, "What went wrong?"))
        layout.addWidget(self.summary)
        layout.addWidget(section_label(QtWidgets, "Details"))
        layout.addWidget(self.body, 1)
        layout.addWidget(section_label(QtWidgets, "Attached automatically"))
        layout.addWidget(self.sysinfo)
        layout.addWidget(self.send_button)
        layout.addWidget(self.status)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def refresh(self) -> None:
        try:
            cfg = self.client.get_json("/api/config")
            sysinfo = self.client.get_json("/api/admin/system")
            client_info = self.client.get_json("/api/setup/client-info")
        except NativeApiError:
            return
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

    def send(self) -> None:
        title = self.summary.text().strip()
        if not title:
            self.status.setText("Add a short summary first.")
            return
        description = self.body.toPlainText().strip()
        if len(description) < 12:
            self.status.setText("Add a few details so the report is useful.")
            return
        self.send_button.setEnabled(False)
        self.status.setText("Sending sanitized report...")
        try:
            result = self.client.post_json(
                "/api/feedback",
                {
                    "title": title,
                    "description": description,
                    "client_context": "native/gui; screen=feedback",
                },
            )
        except NativeApiError as exc:
            self.status.setText(f"Report failed: {exc}")
            self.send_button.setEnabled(True)
            return
        self.status.setText(str(result.get("message") or "Report sent. Thank you."))
        self.send_button.setEnabled(True)


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


def _banner(QtWidgets: Any, text: str, role: str) -> Any:
    box = QtWidgets.QFrame()
    box.setObjectName(role)
    layout = QtWidgets.QHBoxLayout(box)
    layout.setContentsMargins(10, 7, 10, 7)
    layout.addWidget(label(QtWidgets, text, "Muted", wrap=True))
    box.hide()
    return box


def _weather_line(payload: dict[str, Any], *, raw: bool) -> str:
    icon = payload.get("weather_icon") or ""
    cat = payload.get("flight_cat") or "?"
    temp = payload.get("temperature_c")
    temp_text = f"{temp} C" if temp is not None else "-- C"
    summary = payload.get("decoded_summary") or payload.get("weather_summary") or payload.get("weather_label") or ""
    raw_text = payload.get("raw_text") or payload.get("raw") or ""
    return f"{icon} {cat} | {temp_text} | {summary}" + (f" | {raw_text}" if raw and raw_text else "")


def _budget_label(aviation: dict[str, Any], community: dict[str, Any]) -> str:
    mode = str(aviation.get("active_mode") or aviation.get("mode") or community.get("mode") or "unknown")
    used = aviation.get("calls_this_month") or community.get("calls_this_month") or 0
    limit = aviation.get("monthly_limit") or community.get("monthly_limit") or 0
    return f"{used} / {limit}" if limit else mode


def _budget_detail(aviation: dict[str, Any], community: dict[str, Any]) -> str:
    remaining = aviation.get("remaining") or community.get("remaining")
    reset = community.get("period_end") or aviation.get("period_end") or ""
    parts = []
    if remaining is not None:
        parts.append(f"{remaining} requests left")
    if reset:
        parts.append(f"resets {reset}")
    return " | ".join(parts)


if __name__ == "__main__":  # pragma: no cover - manual Qt entrypoint
    main()
