from __future__ import annotations

import sys
import importlib

import pytest

from localflight.platform.detect import Platform
from localflight.platform.gui_launcher import decide_gui_launch


def test_auto_desktop_uses_native_when_qt_available() -> None:
    decision = decide_gui_launch(
        Platform.WINDOWS,
        {"LOCALFLIGHT_GUI_MODE": "auto"},
        native_probe=lambda: True,
    )

    assert decision.effective_mode == "native"
    assert decision.native_available is True
    assert decision.display_available is True
    assert decision.fullscreen is False


def test_blank_mode_defaults_to_native() -> None:
    decision = decide_gui_launch(
        Platform.WINDOWS,
        {},
        native_probe=lambda: True,
    )

    assert decision.requested_mode == "native"
    assert decision.effective_mode == "native"


def test_auto_desktop_falls_back_to_browser_when_qt_missing() -> None:
    decision = decide_gui_launch(
        Platform.MACOS,
        {"LOCALFLIGHT_GUI_MODE": "auto"},
        native_probe=lambda: False,
    )

    assert decision.effective_mode == "browser"
    assert decision.native_available is False


def test_auto_pi_without_display_stays_headless_even_when_qt_exists() -> None:
    decision = decide_gui_launch(
        Platform.RASPBERRY_PI,
        {"LOCALFLIGHT_GUI_MODE": "auto"},
        native_probe=lambda: True,
    )

    assert decision.effective_mode == "headless"
    assert decision.display_available is False


def test_native_default_pi_without_display_stays_headless() -> None:
    decision = decide_gui_launch(
        Platform.RASPBERRY_PI,
        {},
        native_probe=lambda: True,
    )

    assert decision.requested_mode == "native"
    assert decision.effective_mode == "headless"
    assert "without display" in decision.reason


def test_auto_pi_with_display_uses_native_fullscreen_when_qt_available() -> None:
    decision = decide_gui_launch(
        Platform.RASPBERRY_PI,
        {"LOCALFLIGHT_GUI_MODE": "auto", "DISPLAY": ":0"},
        native_probe=lambda: True,
    )

    assert decision.effective_mode == "native"
    assert decision.fullscreen is True


def test_explicit_browser_without_display_becomes_headless() -> None:
    decision = decide_gui_launch(
        Platform.LINUX,
        {"LOCALFLIGHT_GUI_MODE": "browser"},
        native_probe=lambda: True,
    )

    assert decision.effective_mode == "headless"
    assert "without display" in decision.reason


def test_invalid_mode_uses_native_first_path() -> None:
    decision = decide_gui_launch(
        Platform.WINDOWS,
        {"LOCALFLIGHT_GUI_MODE": "weird"},
        native_probe=lambda: True,
    )

    assert decision.requested_mode == "native"
    assert decision.effective_mode == "native"


def test_native_first_falls_back_to_browser_when_qt_missing_on_desktop() -> None:
    decision = decide_gui_launch(
        Platform.WINDOWS,
        {},
        native_probe=lambda: False,
    )

    assert decision.requested_mode == "native"
    assert decision.effective_mode == "browser"
    assert "Qt unavailable" in decision.reason


def test_native_app_facade_keeps_legacy_shell_lazy() -> None:
    sys.modules.pop("localflight.native.app", None)
    sys.modules.pop("localflight.native._legacy_app", None)

    native_app = importlib.import_module("localflight.native.app")

    assert "localflight.native._legacy_app" not in sys.modules
    native_app.is_native_available()
    assert "localflight.native._legacy_app" not in sys.modules


def test_display_screen_passes_real_qwidgets_to_splitter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtCore, QtGui, QtWidgets
    from localflight.native.app import DisplayScreen

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = DisplayScreen(QtCore, QtGui, QtWidgets, client=object())

    assert app is not None
    assert screen.splitter.count() == 2
    assert set(screen.mode_buttons) == {"fids", "split", "radar"}


def test_native_client_window_exposes_real_user_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import NativeMainWindow
    from localflight.native.qt_compat import import_qt

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = NativeMainWindow(*import_qt(), base_url="http://127.0.0.1:9", first_launch=False)

    assert app is not None
    assert window.screen_keys == [
        "display",
        "fids",
        "radar",
        "matrix",
        "settings",
        "admin",
        "history",
        "logs",
        "requests",
        "feedback",
    ]
    assert [button.property("lf_label") for button in window._nav_buttons.values()] == [
        "Display",
        "FIDS",
        "Radar",
        "Matrix",
        "Settings",
        "Admin",
        "History",
        "Logs",
        "Report",
    ]
    assert all(button.text() != button.property("lf_label") for button in window._nav_buttons.values())
    assert [window.primary_nav_layout.itemAt(i).widget().property("lf_label") for i in range(window.primary_nav_layout.count())] == [
        "Display",
        "FIDS",
        "Radar",
        "Matrix",
    ]
    assert [window.utility_nav_layout.itemAt(i).widget().property("lf_label") for i in range(window.utility_nav_layout.count())] == [
        "Settings",
        "Admin",
        "History",
        "Logs",
        "Report",
    ]
    assert window.stack.count() == 10
    assert window.screens[0] is not None
    assert all(screen is None for screen in window.screens[1:])
    window._show_page("settings")
    assert window.screens[4] is not None
    assert window.screens[1] is None


def test_native_client_window_footer_links(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    import localflight.native._legacy_app as legacy_app
    from localflight.native.app import NativeMainWindow
    from localflight.native.qt_compat import import_qt

    opened: list[str] = []
    monkeypatch.setattr(legacy_app.webbrowser, "open", lambda url: opened.append(url))

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = NativeMainWindow(*import_qt(), base_url="http://127.0.0.1:9", first_launch=False)
    window.footer_github_button.click()
    window.footer_coffee_button.click()

    assert app is not None
    assert window.footer_github_button.text() == "GitHub"
    assert window.footer_coffee_button.text() == "Buy Me a Coffee"
    assert opened == [legacy_app.GITHUB_URL, legacy_app.COFFEE_URL]


def test_native_history_stats_render_code_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import HistoryScreen
    from localflight.native.qt_compat import import_qt

    class _Client:
        def get_json(self, path: str, *, params: dict[str, object] | None = None) -> dict[str, object]:
            assert path == "/api/history/summary"
            return {
                "total": 12,
                "departures": 7,
                "arrivals": 5,
                "on_time_pct": 91.2,
                "avg_delay_minutes": 3,
                "top_airlines": [{"code": "LX", "count": 8}],
                "top_destinations": [{"code": "BCN", "count": 4}],
                "top_origins": [{"code": "FRA", "count": 3}],
                "top_aircraft": [{"aircraft_type": "A320", "count": 2}],
            }

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = HistoryScreen(*import_qt()[2:], client=_Client())
    screen._render_stats()

    labels = {child.text() for child in screen.stats_content.findChildren(QtWidgets.QLabel)}
    assert app is not None
    assert {"LX", "BCN", "FRA", "A320"}.issubset(labels)


def test_native_admin_uses_active_nested_schedule_budget() -> None:
    from localflight.native.app import _active_schedule_budget, _budget_label

    bucket = _active_schedule_budget(
        {
            "active_mode": "community",
            "calls_this_month": 2,
            "monthly_limit": 10000,
            "community": {"calls_this_month": 2, "monthly_limit": 50, "remaining": 48},
        }
    )

    assert _budget_label(bucket) == "2 / 50"


def test_native_admin_exposes_buy_me_a_coffee_link(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    import localflight.native.app as native_app
    from localflight.native.app import AdminSummaryScreen, COFFEE_URL

    opened: list[str] = []
    monkeypatch.setattr(native_app.webbrowser, "open", lambda url: opened.append(url))

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = AdminSummaryScreen(QtWidgets, client=object(), navigate=lambda _key: None)
    screen._open_quick_tool("coffee")

    assert app is not None
    assert screen.loading_indicator.isVisible() is False
    assert opened == [COFFEE_URL]
    assert COFFEE_URL in screen.status.text()


def test_native_first_launch_main_window_does_not_embed_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import NativeMainWindow, NativeSetupWindow
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    setup_done = {"called": False}
    setup_window = NativeSetupWindow(
        QtCore,
        QtGui,
        QtWidgets2,
        base_url="http://127.0.0.1:9",
        on_setup_complete=lambda: setup_done.update(called=True),
    )
    main_window = NativeMainWindow(QtCore, QtGui, QtWidgets2, base_url="http://127.0.0.1:9", first_launch=True)

    assert app is not None
    assert setup_window.setup_screen is not None
    assert "setup" not in main_window.screen_keys
    assert main_window.screen_keys[0] == "display"


def test_native_custom_splash_can_close_without_qsplash_finish(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    import localflight.native._legacy_app as legacy
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    splash = legacy._build_splash(QtCore, QtGui, QtWidgets2)
    target = QtWidgets.QWidget()

    splash.show()
    assert splash.isVisible()
    legacy._finish_splash(splash, target)

    assert app is not None
    assert not splash.isVisible()


def test_native_initial_window_size_fits_available_screen() -> None:
    import localflight.native._legacy_app as legacy

    class _Point:
        pass

    class _Geometry:
        def __init__(self, width: int, height: int) -> None:
            self._width = width
            self._height = height

        def width(self) -> int:
            return self._width

        def height(self) -> int:
            return self._height

        def center(self) -> _Point:
            return _Point()

    class _Frame:
        def __init__(self) -> None:
            self.centered = False

        def moveCenter(self, _point: _Point) -> None:
            self.centered = True

        def topLeft(self) -> tuple[int, int]:
            return (12, 34)

    class _Screen:
        def __init__(self, geometry: _Geometry) -> None:
            self._geometry = geometry

        def availableGeometry(self) -> _Geometry:
            return self._geometry

    class _Window:
        def __init__(self, geometry: _Geometry) -> None:
            self._screen = _Screen(geometry)
            self.frame = _Frame()
            self.size: tuple[int, int] | None = None
            self.position: tuple[int, int] | None = None

        def screen(self) -> _Screen:
            return self._screen

        def resize(self, width: int, height: int) -> None:
            self.size = (width, height)

        def frameGeometry(self) -> _Frame:
            return self.frame

        def move(self, position: tuple[int, int]) -> None:
            self.position = position

    small_window = _Window(_Geometry(1000, 700))
    large_window = _Window(_Geometry(3000, 2000))

    legacy._fit_window_to_screen(object(), small_window, 1280, 820)
    legacy._fit_window_to_screen(object(), large_window, 1280, 820)

    assert small_window.size == (920, 644)
    assert small_window.frame.centered is True
    assert small_window.position == (12, 34)
    assert large_window.size == (1280, 820)


def test_native_main_window_close_requests_backend_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.qt_compat import import_qt
    import localflight.native._legacy_app as legacy

    class _Client:
        def __init__(self) -> None:
            self.posts: list[tuple[str, dict[str, object]]] = []

        def get_json(self, path: str, *, params: dict[str, object] | None = None) -> dict[str, object]:
            return {}

        def get_any_json(self, path: str, *, params: dict[str, object] | None = None) -> list[object]:
            return []

        def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
            self.posts.append((path, payload))
            return {"ok": True}

    class _CloseEvent:
        accepted = False
        ignored = False

        def accept(self) -> None:
            self.accepted = True

        def ignore(self) -> None:
            self.ignored = True

    client = _Client()
    monkeypatch.setattr(legacy, "LocalApiClient", lambda **_kwargs: client)

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = legacy.NativeMainWindow(*import_qt(), base_url="http://127.0.0.1:9", first_launch=False)
    window._confirm_quit = lambda: True
    event = _CloseEvent()

    window.closeEvent(event)

    assert app is not None
    assert event.accepted is True
    assert event.ignored is False
    assert client.posts == [("/api/quit", {})]


def test_native_setup_internal_close_does_not_shutdown_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.qt_compat import import_qt
    import localflight.native._legacy_app as legacy

    class _Client:
        def __init__(self) -> None:
            self.posts: list[tuple[str, dict[str, object]]] = []

        def get_json(self, path: str, *, params: dict[str, object] | None = None) -> dict[str, object]:
            if path == "/api/setup/client-info":
                return {"relay_url": "https://localflight-community-relay.fly.dev"}
            return {}

        def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
            self.posts.append((path, payload))
            return {"ok": True}

    class _CloseEvent:
        accepted = False

        def accept(self) -> None:
            self.accepted = True

        def ignore(self) -> None:
            pass

    client = _Client()
    monkeypatch.setattr(legacy, "LocalApiClient", lambda **_kwargs: client)

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    setup_window = legacy.NativeSetupWindow(
        QtCore,
        QtGui,
        QtWidgets2,
        base_url="http://127.0.0.1:9",
        on_setup_complete=lambda: None,
    )
    setup_window.allow_close_without_shutdown()
    event = _CloseEvent()

    setup_window.closeEvent(event)

    assert app is not None
    assert event.accepted is True
    assert client.posts == []


def test_native_display_refreshes_only_visible_child_panels(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import DisplayScreen
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = DisplayScreen(QtCore, QtGui, QtWidgets2, client=object())
    calls = {"fids": 0, "radar": 0}
    screen.fids.refresh = lambda: calls.update(fids=calls["fids"] + 1)
    screen.radar.refresh = lambda: calls.update(radar=calls["radar"] + 1)

    screen.set_mode("fids")
    screen.refresh()
    assert calls == {"fids": 1, "radar": 0}

    screen.set_mode("radar")
    screen.refresh()
    assert calls == {"fids": 1, "radar": 1}

    screen.set_mode("split")
    screen.refresh()
    assert calls == {"fids": 2, "radar": 2}
    assert app is not None


def test_native_main_window_constructs_pages_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import NativeMainWindow
    from localflight.native.qt_compat import import_qt

    sys.modules.pop("localflight.native.pages.settings", None)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = NativeMainWindow(*import_qt(), base_url="http://127.0.0.1:9", first_launch=False)

    assert app is not None
    assert window.screens[0] is not None
    assert all(screen is None for screen in window.screens[1:])
    assert "localflight.native.pages.settings" not in sys.modules
    window._show_page("history")
    assert window.screens[6] is not None
    assert window.screens[4] is None
    assert "localflight.native.pages.settings" not in sys.modules
    window._show_page("settings")
    assert window.screens[4] is not None
    assert "localflight.native.pages.settings" in sys.modules


def test_native_parity_screens_construct_core_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import FeedbackScreen, LogsScreen, MatrixScreen, RequestsScreen, SetupScreen
    from localflight.native.qt_compat import import_qt

    class _Client:
        def get_json(self, path: str, *, params: dict[str, object] | None = None) -> dict[str, object]:
            if path == "/api/setup/client-info":
                return {"relay_url": "https://localflight-community-relay.fly.dev", "has_activation_token": False}
            return {}

    QtCore, _QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    client = _Client()

    setup = SetupScreen(QtCore, QtWidgets2, client, base_url="http://127.0.0.1:9")
    matrix = MatrixScreen(QtWidgets2, client)
    logs = LogsScreen(QtWidgets2, client)
    requests = RequestsScreen(QtWidgets2, client)
    feedback = FeedbackScreen(QtWidgets2, client)

    assert app is not None
    assert setup.tabs.count() == 6
    assert setup.step_names[0] == "Welcome"
    assert setup.relay_url.text() == "https://localflight-community-relay.fly.dev"
    assert setup.loading_indicator.isVisible() is False
    assert setup.provider_action_status.text()
    assert setup.setup_mode.currentData() == "community"
    assert setup.diagnostics_mode.currentData() == "manual"
    assert setup.finish_btn.isVisible() is False
    assert matrix.canvas is not None
    assert matrix.loading_indicator.isVisible() is False
    assert matrix.script_preview.isReadOnly()
    assert matrix.zoom_value.text().endswith("px")
    assert matrix.brightness_value.text().endswith("%")
    assert matrix.animation_mode.currentData() == "split_flap"
    assert any(button.text() == "Generate code" for button in matrix.widget.findChildren(QtWidgets.QPushButton))
    assert logs.file_combo is not None
    assert logs.live_tail.text() == "Live tail"
    assert logs.loading_indicator.isVisible() is False
    assert requests.client_type.currentText() == "all clients"
    assert requests.loading_indicator.isVisible() is False
    assert feedback.sysinfo.isReadOnly()
    assert feedback.loading_indicator.isVisible() is False


def test_native_matrix_controls_drive_preview_and_script(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import MatrixScreen
    from localflight.native.qt_compat import import_qt

    class _Client:
        def __init__(self) -> None:
            self.saved: dict[str, object] = {}
            self.script_payload: dict[str, object] = {}

        def get_json(self, path: str, *, params: dict[str, object] | None = None) -> dict[str, object]:
            if path == "/api/matrix/config":
                return {
                    "brightness": 0.55,
                    "max_rows": 3,
                    "refresh_seconds": 90,
                    "page_rotation_seconds": 12,
                    "default_view": "arrivals",
                    "animation_enabled": False,
                }
            if path == "/api/admin/connections":
                return {"matrix_last_seen": "2026-05-02T15:00:00+00:00"}
            return {}

        def get_any_json(self, path: str, *, params: dict[str, object] | None = None) -> dict[str, object]:
            assert path == "/api/fids"
            return {
                "rows": [
                    {"display_time": "09:10", "flight_display": "LX 1", "route_display": "BCN", "status_display": "SCHEDULED"},
                    {"display_time": "09:20", "flight_display": "LX 2", "route_display": "FRA", "status_display": "BOARDING"},
                ]
            }

        def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
            assert path == "/api/matrix/config"
            self.saved = payload
            return {"ok": True, **payload}

        def post_text(self, path: str, payload: dict[str, object]) -> str:
            assert path == "/api/matrix/script"
            self.script_payload = payload
            return "WIFI_SSID = 'BoardNet'\nANIMATION_ENABLED = False\n"

    QtCore, _QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    client = _Client()
    screen = MatrixScreen(QtWidgets2, client)
    screen.refresh()

    assert app is not None
    assert screen.brightness.value() == 55
    assert screen.max_rows.value() == 3
    assert screen.animation_mode.currentData() == "static"
    assert screen.canvas.animation_mode == "static"
    screen.zoom.setValue(7)
    assert screen.zoom_value.text() == "7px"
    screen.save_config()
    assert client.saved["animation_enabled"] is False
    screen.generate_script()
    assert client.script_payload["animation_enabled"] is False
    assert "ANIMATION_ENABLED" in screen.script_preview.toPlainText()


def test_native_matrix_canvas_timer_stops_when_screen_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import MatrixScreen
    from localflight.native.qt_compat import import_qt

    class _Client:
        pass

    _QtCore, _QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = MatrixScreen(QtWidgets2, _Client())

    screen.set_active(True)
    assert screen.canvas.timer.isActive()
    screen.set_active(False)
    assert not screen.canvas.timer.isActive()
    assert app is not None


def test_native_setup_reuses_stored_relay_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import SetupScreen
    from localflight.native.qt_compat import import_qt

    class _Client:
        def get_json(self, path: str, *, params: dict[str, object] | None = None) -> dict[str, object]:
            if path == "/api/setup/client-info":
                return {
                    "relay_url": "https://localflight-community-relay.fly.dev/v1/flights",
                    "activation_token_present": True,
                    "activation_token_prefix": "tok-prefix",
                }
            return {}

    QtCore, _QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    setup = SetupScreen(QtCore, QtWidgets2, _Client(), base_url="http://127.0.0.1:9")

    assert app is not None
    assert setup.setup_mode.currentData() == "community"
    assert setup.relay_url.text() == "https://localflight-community-relay.fly.dev"
    assert "Stored token linked" in setup.activation_token.placeholderText()
    assert setup.diagnostics_mode.currentData() == "manual"


def test_native_setup_is_extracted_from_legacy_module() -> None:
    import localflight.native.pages.setup as setup_page

    assert setup_page.SetupScreen.__module__ == "localflight.native.pages.setup"
    assert setup_page.NativeSetupWindow.__module__ == "localflight.native.pages.setup"


def test_native_setup_defaults_to_community_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import SetupScreen
    from localflight.native.qt_compat import import_qt

    class _Client:
        def get_json(self, path: str, *, params: dict[str, object] | None = None) -> dict[str, object]:
            if path == "/api/setup/client-info":
                return {"relay_url": "https://localflight-community-relay.fly.dev", "activation_token_present": False}
            return {}

    QtCore, _QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    setup = SetupScreen(QtCore, QtWidgets2, _Client(), base_url="http://127.0.0.1:9")

    assert app is not None
    assert setup.tabs.count() == 6
    assert setup.setup_mode.currentData() == "community"
    assert "not linked" in setup.relay_status.text().lower()
    assert setup.logo_label.minimumHeight() >= 120


def test_native_setup_airport_selection_updates_finish_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import SetupScreen
    from localflight.native.qt_compat import import_qt

    class _Client:
        def get_json(self, path: str, *, params: dict[str, object] | None = None) -> dict[str, object]:
            if path == "/api/setup/client-info":
                return {"relay_url": "https://localflight-community-relay.fly.dev"}
            return {}

    QtCore, _QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    setup = SetupScreen(QtCore, QtWidgets2, _Client(), base_url="http://127.0.0.1:9")
    item = QtWidgets2.QListWidgetItem("SIN / WSSS Singapore Changi")
    item.setData(
        QtCore.Qt.UserRole,
        {"iata": "SIN", "icao": "WSSS", "name": "Singapore Changi", "city": "Singapore", "timezone": "Asia/Singapore"},
    )

    setup._select_airport_item(item)

    assert app is not None
    assert setup.airport_iata.text() == "SIN"
    assert setup.airport_icao.text() == "WSSS"
    assert setup.timezone.text() == "Asia/Singapore"
    assert "SIN / WSSS" in setup.finish_summary.text()


def test_native_setup_provider_links_open_public_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import SetupScreen
    from localflight.native.pages.setup import PROVIDER_LINKS
    from localflight.native.qt_compat import import_qt

    class _Client:
        def get_json(self, path: str, *, params: dict[str, object] | None = None) -> dict[str, object]:
            if path == "/api/setup/client-info":
                return {"relay_url": "https://localflight-community-relay.fly.dev"}
            return {}

    opened: list[str] = []
    monkeypatch.setattr("localflight.native.pages.setup.webbrowser.open", lambda url: opened.append(url))
    QtCore, _QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    setup = SetupScreen(QtCore, QtWidgets2, _Client(), base_url="http://127.0.0.1:9")

    for text, _url in PROVIDER_LINKS:
        setup.provider_link_buttons[text].click()
    setup.web_fallback_btn.click()

    assert app is not None
    assert opened[:-1] == [url for _text, url in PROVIDER_LINKS]
    assert opened[-1] == "http://127.0.0.1:9/setup"


def test_native_setup_relay_actions_show_local_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import SetupScreen
    from localflight.native.qt_compat import import_qt

    class _Client:
        def get_json(self, path: str, *, params: dict[str, object] | None = None) -> dict[str, object]:
            if path == "/api/setup/client-info":
                return {"relay_url": "https://localflight-community-relay.fly.dev"}
            return {}

    class _Service:
        def setup_client_info(self) -> dict[str, object]:
            return {"relay_url": "https://localflight-community-relay.fly.dev"}

        def setup_activate(self, payload: dict[str, object]) -> dict[str, object]:
            return {"ok": True, "activation_token_prefix": "tok-prefix"}

        def setup_client_status(self, payload: dict[str, object]) -> dict[str, object]:
            return {"ok": True, "status": "active"}

        def setup_test_activation(self, payload: dict[str, object]) -> dict[str, object]:
            return {"ok": True}

    QtCore, _QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    setup = SetupScreen(QtCore, QtWidgets2, _Client(), base_url="http://127.0.0.1:9")
    setup.service = _Service()

    setup.request_activation()
    assert app is not None
    assert setup.relay_action_status.objectName() == "StatusGood"
    assert "connected" in setup.relay_action_status.text().lower()
    assert setup.request_activation_btn.isEnabled()

    setup.check_activation_status()
    assert setup.relay_action_status.objectName() == "StatusGood"
    assert "active" in setup.relay_action_status.text().lower()
    assert setup.check_relay_status_btn.isEnabled()

    setup.test_activation()
    assert setup.relay_action_status.objectName() == "StatusGood"
    assert "token works" in setup.relay_action_status.text().lower()
    assert setup.test_token_btn.isEnabled()


def test_native_setup_provider_key_actions_show_feedback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import SetupScreen
    from localflight.native.qt_compat import import_qt

    class _Client:
        def get_json(self, path: str, *, params: dict[str, object] | None = None) -> dict[str, object]:
            if path == "/api/setup/client-info":
                return {"relay_url": "https://localflight-community-relay.fly.dev"}
            return {}

    class _Service:
        def setup_client_info(self) -> dict[str, object]:
            return {"relay_url": "https://localflight-community-relay.fly.dev"}

        def setup_test_provider_key(self, path: str, key: str) -> dict[str, object]:
            assert key == "secret-test-key"
            assert path in {"/api/setup/test-aviationstack", "/api/setup/test-rapidapi"}
            return {"ok": True}

    QtCore, _QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    setup = SetupScreen(QtCore, QtWidgets2, _Client(), base_url="http://127.0.0.1:9")
    setup.service = _Service()

    setup.test_aviationstack()
    assert app is not None
    assert setup.provider_action_status.objectName() == "StatusWarn"
    assert "paste" in setup.provider_action_status.text().lower()

    setup.aviationstack_key.setText("secret-test-key")
    setup.test_aviationstack()
    assert setup.provider_action_status.objectName() == "StatusGood"
    assert "works" in setup.provider_action_status.text().lower()
    assert setup.test_as_btn.isEnabled()
    assert setup.loading_indicator.isVisible() is False


def test_native_setup_byok_finish_sends_keys_only_for_byok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import SetupScreen
    from localflight.native.qt_compat import import_qt

    class _Client:
        def __init__(self) -> None:
            self.payload: dict[str, object] = {}

        def get_json(self, path: str, *, params: dict[str, object] | None = None) -> dict[str, object]:
            if path == "/api/setup/client-info":
                return {"relay_url": "https://localflight-community-relay.fly.dev"}
            return {}

        def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
            assert path == "/api/setup/complete"
            self.payload = payload
            return {"ok": True}

        def clear_cache(self) -> None:
            pass

    QtCore, _QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    client = _Client()
    setup = SetupScreen(QtCore, QtWidgets2, client, base_url="http://127.0.0.1:9")
    setup._set_mode("byok")
    setup.aviationstack_key.setText("as-key")
    setup.rapidapi_key.setText("rapid-key")
    setup.opensky_id.setText("opensky-id")
    setup.opensky_secret.setText("opensky-secret")
    setup.finish_setup()

    assert app is not None
    assert client.payload["setup_mode"] == "byok"
    assert client.payload["source"] == "real"
    assert client.payload["relay_url"] == ""
    assert client.payload["aviationstack_key"] == "as-key"
    assert client.payload["rapidapi_key"] == "rapid-key"
    assert client.payload["opensky_id"] == "opensky-id"
    assert client.payload["opensky_secret"] == "opensky-secret"


def test_native_setup_virtual_finish_sends_virtual_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import SetupScreen
    from localflight.native.qt_compat import import_qt

    class _Client:
        def __init__(self) -> None:
            self.payload: dict[str, object] = {}

        def get_json(self, path: str, *, params: dict[str, object] | None = None) -> dict[str, object]:
            if path == "/api/setup/client-info":
                return {"relay_url": "https://localflight-community-relay.fly.dev", "activation_token_present": False}
            return {}

        def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
            self.payload = payload
            return {"ok": True}

        def clear_cache(self) -> None:
            pass

    QtCore, _QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    client = _Client()
    completed = {"value": False}
    setup = SetupScreen(QtCore, QtWidgets2, client, base_url="http://127.0.0.1:9", on_setup_complete=lambda: completed.update(value=True))
    setup._set_mode("virtual")
    setup.finish_setup()

    assert app is not None
    assert completed["value"] is True
    assert client.payload["setup_mode"] == "virtual"
    assert client.payload["source"] == "virtual"
    assert client.payload["diagnostics_mode"] == "manual"
    assert client.payload["relay_url"] == ""
    assert client.payload["aviationstack_key"] == ""


def test_native_setup_saves_selected_diagnostics_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import SetupScreen
    from localflight.native.qt_compat import import_qt

    class _Client:
        def __init__(self) -> None:
            self.payload: dict[str, object] = {}

        def get_json(self, path: str, *, params: dict[str, object] | None = None) -> dict[str, object]:
            if path == "/api/setup/client-info":
                return {"relay_url": "https://localflight-community-relay.fly.dev", "activation_token_present": False}
            return {}

        def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
            assert path == "/api/setup/complete"
            self.payload = payload
            return {"ok": True}

        def clear_cache(self) -> None:
            pass

    QtCore, _QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    client = _Client()
    setup = SetupScreen(QtCore, QtWidgets2, client, base_url="http://127.0.0.1:9")
    setup._set_diagnostics_mode("auto_logs")
    setup.finish_setup()

    assert app is not None
    assert client.payload["diagnostics_mode"] == "auto_logs"
    assert "local logs" in setup.finish_summary.text()


def test_native_radar_projects_lat_lon_blips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import RadarCanvas
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    canvas = RadarCanvas(QtCore, QtGui, QtWidgets2)
    canvas.set_payload(
        {
            "center": {"lat": 47.0, "lon": 8.0},
            "radius_nm": 5,
            "blips": [{"callsign": "TST1", "lat": 47.01, "lon": 8.0}],
        }
    )

    assert app is not None
    assert canvas.center == {"lat": 47.0, "lon": 8.0}
    assert canvas._blip_angle(canvas.blips[0]) == pytest.approx(0.0)


def test_native_radar_projects_surface_points_from_lon_lat_or_lat_lon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import RadarCanvas
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    canvas = RadarCanvas(QtCore, QtGui, QtWidgets2)
    canvas.resize(500, 500)
    canvas.set_payload({"center": {"lat": 47.0, "lon": 8.0}, "radius_nm": 5, "blips": []})
    canvas.set_surface(
        {
            "center": {"lat": 47.0, "lon": 8.0},
            "features": [
                {"kind": "runway", "label": "lat-lon", "points": [[47.0, 8.0], [47.01, 8.0]]},
                {"kind": "runway", "label": "lon-lat", "points": [[8.0, 47.0], [8.0, 47.01]]},
            ],
        }
    )
    viewport = canvas._viewport(canvas.rect())
    projected = canvas._projected_surface(QtCore, viewport)

    assert app is not None
    assert len(projected) == 2
    assert all(len(poly) == 2 for _kind, _label, poly, _closed, _feature in projected)


def test_native_radar_canvas_keeps_light_local_track_history(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import RadarCanvas
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    canvas = RadarCanvas(QtCore, QtGui, QtWidgets2)
    base = {"center": {"lat": 47.0, "lon": 8.0}, "radius_nm": 5}
    canvas.set_payload({**base, "blips": [{"callsign": "TST1", "lat": 47.0, "lon": 8.0, "speed_kt": 120}]})
    canvas.set_payload({**base, "blips": [{"callsign": "TST1", "lat": 47.01, "lon": 8.01, "speed_kt": 120}]})

    assert app is not None
    assert canvas.track_history["TST1"] == [(47.0, 8.0), (47.01, 8.01)]
    assert canvas._direction_heading({"callsign": "TST1", "lat": 47.01, "lon": 8.01}) is not None


def test_native_radar_canvas_reduces_labels_at_wide_range(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import RadarCanvas
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    canvas = RadarCanvas(QtCore, QtGui, QtWidgets2)
    canvas.resize(500, 500)
    canvas.set_payload(
        {
            "center": {"lat": 47.0, "lon": 8.0},
            "radius_nm": 40,
            "blips": [
                {"callsign": f"TST{idx}", "lat": 47.0 + idx * 0.001, "lon": 8.0, "speed_kt": 120}
                for idx in range(20)
            ],
        }
    )
    viewport = canvas._viewport(canvas.rect())

    assert app is not None
    assert canvas._should_draw_callsign(canvas.blips[0], viewport) is False
    canvas._set_hover_blip(canvas.blips[0])
    assert canvas._should_draw_callsign(canvas.blips[0], viewport) is True


def test_native_radar_blips_light_on_sweep_bar_then_fade(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import RadarCanvas
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    canvas = RadarCanvas(QtCore, QtGui, QtWidgets2)
    blip = {"callsign": "TST1", "lat": 47.01, "lon": 8.0}
    canvas.set_payload({"center": {"lat": 47.0, "lon": 8.0}, "radius_nm": 5, "blips": [blip]})

    canvas.sweep_angle = 0
    bright = canvas._blip_alpha(blip)
    canvas.sweep_angle = 45
    fading = canvas._blip_alpha(blip)
    canvas.sweep_angle = 120
    gone = canvas._blip_alpha(blip)

    assert app is not None
    assert bright == 255
    assert 0 < fading < bright
    assert gone == 0


def test_native_radar_embedded_layout_stays_narrow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import RadarScreen
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = RadarScreen(QtCore, QtGui, QtWidgets2, object(), embedded=True)

    assert app is not None
    assert screen.range_combo is not None
    assert not screen.range_buttons
    assert screen.loading_indicator.isVisible() is False
    assert screen.canvas.minimumWidth() <= 320
    assert screen.widget.minimumSizeHint().width() <= 520
    assert screen.advanced_panel.isHidden()


def test_native_radar_ground_filter_only_available_in_surface_ranges(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import RadarScreen
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = RadarScreen(QtCore, QtGui, QtWidgets2, object())
    screen.refresh = lambda: None
    ground_idx = screen.traffic_filter.findData("ground")

    screen.set_radius(5)
    assert app is not None
    assert screen.traffic_filter.model().item(ground_idx).isEnabled() is True
    screen.traffic_filter.setCurrentIndex(ground_idx)
    assert screen.traffic_filter.currentData() == "ground"

    screen.set_radius(10)
    assert screen.traffic_filter.model().item(ground_idx).isEnabled() is False
    assert screen.traffic_filter.currentData() == "all"


def test_native_radar_static_layer_cache_invalidates_for_layers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import RadarCanvas
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    canvas = RadarCanvas(QtCore, QtGui, QtWidgets2)
    canvas.resize(420, 420)
    canvas.set_surface(
        {
            "center": {"lat": 47.0, "lon": 8.0},
            "features": [{"kind": "runway", "label": "16/34", "points": [[47.0, 8.0], [47.01, 8.0]]}],
        }
    )
    viewport = canvas._viewport(canvas.rect())
    pixmap = canvas._static_layer_pixmap(QtCore, QtGui, canvas.rect(), viewport)
    key = canvas._static_cache_key

    assert app is not None
    assert pixmap is canvas._static_cache_pixmap
    assert canvas._static_layer_pixmap(QtCore, QtGui, canvas.rect(), viewport) is pixmap
    canvas.set_layer_enabled("surface", False)
    assert canvas._static_cache_key is None
    canvas._static_layer_pixmap(QtCore, QtGui, canvas.rect(), viewport)
    assert canvas._static_cache_key != key


def test_native_radar_static_layer_order_is_explicit_for_map_terrain_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import RadarCanvas
    from localflight.native.canvas.radar import STATIC_RADAR_LAYER_ORDER
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    canvas = RadarCanvas(QtCore, QtGui, QtWidgets2)
    canvas.resize(420, 420)
    viewport = canvas._viewport(canvas.rect())
    image = QtGui.QImage(420, 420, QtGui.QImage.Format_ARGB32)
    image.fill(QtGui.QColor("black"))
    painter = QtGui.QPainter(image)
    calls: list[str] = []

    canvas._draw_background = lambda *args, **kwargs: calls.append("background")
    canvas._draw_static_layer = lambda layer, *args, **kwargs: calls.append(layer)

    canvas._draw_static_layers(painter, QtCore, QtGui, canvas.rect(), viewport)
    painter.end()

    assert app is not None
    assert calls == list(STATIC_RADAR_LAYER_ORDER)
    assert calls.index("surface") < calls.index("map") < calls.index("terrain") < calls.index("grid") < calls.index("runways")
    assert calls.index("runways") < calls.index("procedures")


def test_native_radar_uses_contrast_safe_palette_in_light_and_dark(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import RadarCanvas
    from localflight.native.qt_compat import import_qt

    _QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    canvas = RadarCanvas(_QtCore, QtGui, QtWidgets2)

    dark_blip = canvas._radar_color(QtGui, "blip").name()
    dark_runway = canvas._radar_color(QtGui, "runway").name()
    dark_road = canvas._radar_color(QtGui, "map_road").name()

    canvas.apply_theme("light", "standard")
    light_blip = canvas._radar_color(QtGui, "blip").name()
    light_runway = canvas._radar_color(QtGui, "runway").name()
    light_road = canvas._radar_color(QtGui, "map_road").name()

    assert app is not None
    assert canvas._is_light_mode() is True
    assert len({dark_blip, dark_runway, dark_road}) == 3
    assert len({light_blip, light_runway, light_road}) == 3
    assert dark_blip != light_blip
    assert dark_runway != light_runway


def test_native_radar_heavy_render_smoke_uses_cached_static_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import RadarCanvas
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    canvas = RadarCanvas(QtCore, QtGui, QtWidgets2)
    canvas.resize(520, 520)
    canvas.set_payload(
        {
            "center": {"lat": 47.0, "lon": 8.0},
            "radius_nm": 40,
            "source": "test",
            "blips": [
                {
                    "callsign": f"T{idx:03d}",
                    "lat": 47.0 + ((idx % 20) - 10) * 0.01,
                    "lon": 8.0 + ((idx // 20) - 3) * 0.015,
                    "speed_kt": 180,
                    "track_deg": (idx * 17) % 360,
                }
                for idx in range(120)
            ],
        }
    )
    canvas.set_surface(
        {
            "center": {"lat": 47.0, "lon": 8.0},
            "features": [
                {"kind": "taxiway", "points": [[47.0 + idx * 0.0002, 8.0], [47.01, 8.01]]}
                for idx in range(80)
            ]
            + [{"kind": "runway", "label": "16/34", "points": [[47.05, 8.0], [46.95, 8.1]]}],
        }
    )
    image = QtGui.QImage(520, 520, QtGui.QImage.Format_ARGB32)
    image.fill(QtGui.QColor("black"))

    started = time.perf_counter()
    for _idx in range(8):
        canvas.render(image)
    elapsed = time.perf_counter() - started

    assert app is not None
    assert canvas._static_cache_pixmap is not None
    assert elapsed < 2.0


def test_native_radar_surface_projection_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import RadarCanvas
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    canvas = RadarCanvas(QtCore, QtGui, QtWidgets2)
    canvas.set_surface(
        {
            "center": {"lat": 47.0, "lon": 8.0},
            "features": [{"kind": "runway", "label": "16/34", "points": [[47.0, 8.0], [47.01, 8.0]]}],
        }
    )

    canvas.resize(400, 400)
    viewport = canvas._viewport(canvas.rect())
    first = canvas._projected_surface(QtCore, viewport)
    second = canvas._projected_surface(QtCore, viewport)

    assert app is not None
    assert first is second
    assert first[0][0] == "runway"


def test_native_radar_canvas_keeps_surface_and_future_layers_separate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import RadarCanvas
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    canvas = RadarCanvas(QtCore, QtGui, QtWidgets2)
    canvas.resize(400, 400)
    canvas.set_map({"features": [{"kind": "road", "label": "service", "points": [[47.01, 8.02], [47.02, 8.03]]}]})
    canvas.set_surface(
        {
            "center": {"lat": 47.0, "lon": 8.0},
            "features": [
                {"kind": "runway", "label": "16/34", "closed": True, "points": [[47.0, 8.0], [47.01, 8.0], [47.01, 8.01]]}
            ],
        }
    )
    canvas.set_procedures({"paths": [{"kind": "approach", "label": "ILS16", "points": [[47.02, 8.0], [47.0, 8.0]]}]})
    canvas.set_terrain({"features": [{"kind": "ridge", "label": "terrain", "points": [[47.02, 8.02], [47.03, 8.03]]}]})

    viewport = canvas._viewport(canvas.rect())
    map_layer = canvas._projected_map(QtCore, viewport)
    surface = canvas._projected_surface(QtCore, viewport)
    procedures = canvas._projected_procedures(QtCore, viewport)
    terrain = canvas._projected_terrain(QtCore, viewport)

    assert app is not None
    assert map_layer[0][0] == "road"
    assert map_layer[0][1] == "service"
    assert surface[0][0] == "runway"
    assert surface[0][1] == "16/34"
    assert surface[0][3] is True
    assert procedures[0][0] == "approach"
    assert procedures[0][1] == "ILS16"
    assert terrain[0][0] == "ridge"
    assert canvas._surface_alpha() == 0.55
    canvas.radius_nm = 3
    assert canvas._surface_alpha() == 1.0


def test_native_radar_canvas_accepts_string_encoded_map_points(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import RadarCanvas
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    canvas = RadarCanvas(QtCore, QtGui, QtWidgets2)
    canvas.resize(400, 400)
    canvas.set_payload({"center": {"lat": 47.0, "lon": 8.0}, "radius_nm": 5, "blips": []})
    canvas.set_map({"features": [{"kind": "road", "points": ["47.0000 8.0000", "47.0100 8.0100"]}]})

    projected = canvas._projected_map(QtCore, canvas._viewport(canvas.rect()))

    assert app is not None
    assert projected[0][0] == "road"
    assert len(projected[0][2]) == 2


def test_native_radar_grid_does_not_paint_over_map_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import RadarCanvas
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    canvas = RadarCanvas(QtCore, QtGui, QtWidgets2)
    canvas.resize(400, 400)
    canvas.set_radius_nm(5)
    canvas.set_payload({"center": {"lat": 47.0, "lon": 8.0}, "radius_nm": 5, "blips": []})
    canvas.set_map({"features": [{"kind": "road", "points": [[46.995, 7.995], [47.005, 8.005]]}]})

    with_map = QtGui.QImage(400, 400, QtGui.QImage.Format_ARGB32)
    with_map.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(with_map)
    canvas.render(painter, QtCore.QPoint(0, 0))
    painter.end()

    canvas.set_map([])
    without_map = QtGui.QImage(400, 400, QtGui.QImage.Format_ARGB32)
    without_map.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(without_map)
    canvas.render(painter, QtCore.QPoint(0, 0))
    painter.end()

    changed_pixels = 0
    for y in range(with_map.height()):
        for x in range(with_map.width()):
            if with_map.pixel(x, y) != without_map.pixel(x, y):
                changed_pixels += 1

    assert app is not None
    assert changed_pixels > 20


def test_native_radar_screen_toggles_optional_intelligence_layers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import RadarScreen
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = RadarScreen(QtCore, QtGui, QtWidgets2, object())
    screen._apply_radar(
        {
            "cfg": {"airport_iata": "ZRH", "airport_icao": "LSZH", "source": "virtual", "radar_surface_enabled": True},
            "payload": {
                "center": {"lat": 47.0, "lon": 8.0},
                "count": 1,
                "source": "vatsim",
                "radar_mode": "airborne",
                "radius_nm": 20,
                "provider_radius_nm": 20,
                "raw_provider_count": 1,
                "blips": [
                    {
                        "callsign": "SWR123",
                        "lat": 47.02,
                        "lon": 8.0,
                        "arrival_icao": "LSZH",
                        "radar_phase": "approach",
                        "radar_status_label": "On approach",
                    }
                ],
            },
            "surface": {
                "provider": "openstreetmap",
                "cache_state": "fresh",
                "center": {"lat": 47.0, "lon": 8.0},
                "features": [{"kind": "runway", "label": "16/34", "points": [[47.0, 8.0], [47.01, 8.0]]}],
                "meta": {"validation": {"runway_count": 1}},
            },
            "radar_map": {
                "center": {"lat": 47.0, "lon": 8.0},
                "runways": [{"kind": "runway", "label": "16/34", "points": [[47.0, 8.0], [47.01, 8.0]]}],
                "surface_features": [],
                "map_features": [{"kind": "road", "label": "", "points": [[47.0, 8.0], [47.02, 8.02]]}],
                "terrain": {"features": [{"kind": "relief", "points": [[47.0, 8.0], [47.02, 8.02]]}]},
                "sources": {"surface": "openstreetmap", "surface_cache_state": "fresh", "map": "openstreetmap", "map_cache_state": "fresh", "terrain_cache_state": "fresh"},
            },
            "surface_error": "",
            "weather": {},
        }
    )

    assert app is not None
    assert screen.advanced_panel.isHidden()
    screen._toggle_options_panel(True)
    assert not screen.advanced_panel.isHidden()
    assert screen.layer_toggles["map"].isChecked() is True
    assert screen.layer_toggles["surface"].isChecked() is True
    assert screen.layer_toggles["traffic_status"].isChecked() is False
    assert "OSM surface checked" in screen.source_info.text()
    assert screen.canvas.map_features[0]["kind"] == "road"
    assert "map" in screen.source_info.text()
    assert "map 1 features" in screen.source_info.text()
    assert "status labels" not in screen.source_info.text()
    screen.layer_toggles["traffic_status"].setChecked(True)
    assert "status labels" in screen.source_info.text()
    screen.layer_toggles["procedures"].setChecked(True)
    screen.layer_toggles["terrain"].setChecked(True)
    assert screen.canvas.layers["procedures"] is True
    assert screen.canvas.layers["terrain"] is True
    assert screen.canvas.procedure_paths[0]["kind"] == "approach"
    assert screen.canvas.terrain_features
    assert "terrain 1 features" in screen.source_info.text()
    assert "labels" in screen.filter_summary.text()


def test_native_radar_defaults_to_airborne_range_and_uses_current_hidden_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import RadarScreen
    from localflight.native.qt_compat import import_qt

    class _Client:
        pass

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = RadarScreen(QtCore, QtGui, QtWidgets2, _Client())
    screen._apply_radar(
        {
            "payload": {
                "count": 2,
                "source": "vatsim",
                "radar_mode": "airborne",
                "radius_nm": 20,
                "provider_radius_nm": 20,
                "raw_provider_count": 2,
                "ground_filtered": 3,
                "blips": [],
            },
            "surface": None,
            "surface_error": "",
            "weather": {},
        }
    )

    assert app is not None
    assert screen.radius_nm == 20
    assert "3 ground targets hidden" in screen.status.text()
    assert "Details: /api/radar 20nm, VATSIM" in screen.status.text()


def test_native_radar_exports_standalone_page_and_canvas() -> None:
    from localflight.native.app import RadarCanvas, RadarScreen

    assert RadarScreen.__module__ == "localflight.native.pages.radar"
    assert RadarCanvas.__module__ == "localflight.native.canvas.radar"


def test_native_radar_tooltip_handles_vatsim_safe_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import RadarCanvas
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    canvas = RadarCanvas(QtCore, QtGui, QtWidgets2)
    tooltip = canvas._tooltip_for_blip(
        {
            "callsign": "SWR123",
            "departure_icao": "LSZH",
            "arrival_icao": "KJFK",
            "aircraft_type": "B77W",
            "altitude_m": 3048,
            "speed_ms": 128.6,
            "source": "vatsim",
            "flight_rules": "I",
            "route": "DCT TEST",
            "planned_altitude": "39000",
            "pilot_name": "Should Not Render",
            "cid": 12345,
        }
    )

    assert app is not None
    assert "SWR123" in tooltip
    assert "LSZH -> KJFK" in tooltip
    assert "10000 ft" in tooltip
    assert "250 kt" in tooltip
    assert "Rules I" in tooltip
    assert "DCT TEST" in tooltip
    assert "Should Not Render" not in tooltip
    assert "12345" not in tooltip


def test_native_radar_canvas_emits_hovered_blip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import RadarCanvas
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    canvas = RadarCanvas(QtCore, QtGui, QtWidgets2)
    seen: list[object] = []
    canvas.hoverChanged.connect(lambda blip: seen.append(blip))
    canvas.set_payload(
        {
            "center": {"lat": 47.0, "lon": 8.0},
            "radius_nm": 5,
            "blips": [{"callsign": "TST1", "lat": 47.0, "lon": 8.0, "source": "vatsim"}],
        }
    )
    canvas._set_hover_blip(canvas.blips[0])
    canvas._set_hover_blip(None)

    assert app is not None
    assert seen[0]["callsign"] == "TST1"
    assert seen[-1] is None


def test_native_radar_callsign_label_is_click_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import RadarCanvas
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    canvas = RadarCanvas(QtCore, QtGui, QtWidgets2)
    canvas.resize(500, 500)
    canvas.set_payload(
        {
            "center": {"lat": 47.0, "lon": 8.0},
            "radius_nm": 5,
            "blips": [{"callsign": "TST123", "lat": 47.01, "lon": 8.0}],
        }
    )
    viewport = canvas._viewport(canvas.rect())
    x, y = canvas._blip_pos(canvas.blips[0], viewport)

    assert app is not None
    assert canvas._hit_blip(x + 34, y - 10, viewport)["callsign"] == "TST123"


def test_native_radar_hover_status_shows_safe_basic_info_without_bottom_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import RadarScreen
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = RadarScreen(QtCore, QtGui, QtWidgets2, object())
    screen._set_status("2 aircraft visible. Details: /api/radar 20nm")
    screen._show_blip_info(
        {
            "callsign": "SWR123",
            "departure_icao": "LSZH",
            "arrival_icao": "EGLL",
            "aircraft_type": "A320",
            "altitude_m": 3000,
            "speed_ms": 120,
            "vertical_rate": -3.0,
            "heading": 270,
            "distance_nm": 4.5,
            "source": "vatsim",
            "flight_rules": "I",
            "radar_status_label": "On final",
            "pilot_name": "Do Not Show",
            "cid": 123456,
        }
    )

    assert app is not None
    assert screen.blip_info.isHidden()
    assert "SWR123 under pointer" in screen.status.text()


def test_native_radar_selected_panel_shows_safe_fids_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import RadarScreen
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = RadarScreen(QtCore, QtGui, QtWidgets2, object())
    summary = {
        "title": "SWR123",
        "route": "LSZH -> EGLL",
        "detail": "On final | A320 | 9843 ft | -591 fpm | 233 kt",
    }
    screen._apply_selected_summary(summary)
    screen._apply_selected_detail(
        summary,
        {
            "detail": {
                "status": "delayed",
                "delay_minutes": 12,
                "gate": "A42",
                "terminal": "1",
                "aircraft_type": "A320",
                "aircraft_registration": "HB-JXX",
                "origin_iata": "ZRH",
                "dest_iata": "LHR",
                "detail_mode": "real",
                "data_sources": {"confidence": "live_position_matched"},
                "pilot_name": "Do Not Show",
                "cid": 123456,
            }
        },
    )

    assert app is not None
    assert not screen.blip_info.isHidden()
    assert screen.blip_title.text() == "SWR123"
    assert screen.blip_route.text() == "ZRH -> LHR"
    assert "DELAYED +12m" in screen.blip_detail.text()
    assert "Terminal 1 Gate A42" in screen.blip_detail.text()
    assert "A320 HB-JXX" in screen.blip_detail.text()
    assert "live position matched" in screen.blip_detail.text()
    assert "Do Not Show" not in screen.blip_detail.text()
    assert "123456" not in screen.blip_detail.text()


def test_native_weather_line_translates_icons_and_keeps_keys_hidden() -> None:
    from localflight.native.app import _weather_icon_glyph, _weather_line

    line = _weather_line(
        {"weather_icon": "rain", "flight_cat": "VFR", "temperature_c": 12, "decoded_summary": "Light rain"},
        raw=False,
    )

    assert _weather_icon_glyph("rain") == chr(0x2614)
    assert line.startswith(chr(0x2614))
    assert "rain VFR" not in line
    assert "Light rain" in line


def test_native_fids_detail_splits_real_and_virtual(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import FidsScreen
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = FidsScreen(QtCore, QtGui, QtWidgets2, client=object())
    screen._apply_detail(
        {
            "detail": {
                "detail_mode": "virtual",
                "callsign": "VIR42",
                "origin_icao": "EGLL",
                "dest_icao": "KJFK",
                "aircraft_type": "A35K",
                "flight_plan": {
                    "flight_rules": "I",
                    "route": "DCT TEST",
                    "cruise_altitude": "39000",
                    "assigned_transponder": "2201",
                },
                "position": {"altitude_m": 3000, "speed_ms": 100, "heading": 270},
                "data_sources": {"schedule": "vatsim", "snapshot_age_seconds": 12},
                "pilot_name": "Private Person",
                "cid": 123456,
            },
            "history": [],
        }
    )

    text = screen.detail_body.toPlainText()
    html = screen._detail_html(
        {
            "detail_mode": "virtual",
            "callsign": "VIR42",
            "origin_icao": "EGLL",
            "dest_icao": "KJFK",
            "aircraft_type": "A35K",
            "flight_plan": {"route": "DCT TEST"},
            "position": {"altitude_m": 3000, "speed_ms": 100, "heading": 270},
            "data_sources": {"schedule": "vatsim", "snapshot_age_seconds": 12},
            "pilot_name": "Private Person",
            "cid": 123456,
        },
        [],
        virtual=True,
    )

    assert app is not None
    assert "Virtual flight" in text
    assert "Flight Plan" in text
    assert "DCT TEST" in text
    assert "detail-hero" in html
    assert "hero-chips" in html
    assert "detail-card wide" in html
    assert "history-card" in html
    assert "Private Person" not in text
    assert "123456" not in text
    assert "Private Person" not in html
    assert "123456" not in html


def test_native_fids_real_detail_uses_passenger_board_cards_and_safe_placeholders(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import FidsScreen
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = FidsScreen(QtCore, QtGui, QtWidgets2, client=object())
    detail = {
        "detail_mode": "real",
        "flight_display": "LX 100",
        "status_display": "DELAYED +18M",
        "delay_minutes": 18,
        "origin_iata": "ZRH",
        "origin_icao": "LSZH",
        "origin_name": "Zurich",
        "dest_iata": "LHR",
        "dest_icao": "EGLL",
        "dest_name": "Heathrow",
        "sched_time": "2026-05-07T10:00:00+00:00",
        "est_time": "2026-05-07T10:18:00+00:00",
        "terminal": "",
        "gate": "",
        "aircraft_type": "",
        "aircraft_registration": "",
        "callsign": "SWR100",
        "airline_display": "Swiss",
        "data_sources": {"schedule": "aviationstack", "confidence": "schedule_only"},
        "pilot_name": "Do Not Render",
        "cid": 999999,
        "raw": {"provider": "hidden"},
    }
    history = [
        {"date": "2026-05-06", "status": "landed", "delay_minutes": -4},
        {"date": "2026-05-05", "status": "delayed", "delay_minutes": 21},
    ]

    html = screen._detail_html(detail, history, virtual=False)
    screen.detail_body.setHtml(html)
    text = screen.detail_body.toPlainText()

    assert app is not None
    assert "LX 100" in text
    assert "ZRH / LSZH - Zurich" in text
    assert "LHR / EGLL - Heathrow" in text
    assert "Gate pending" in text
    assert "Aircraft pending" in text
    assert "Recent History" in text
    assert "detail-hero" in html
    assert "time-strip" in html
    assert "route-card" in html
    assert "status bad" in html
    assert "delay-chip good" in html
    assert "delay-chip bad" in html
    assert "Do Not Render" not in text
    assert "999999" not in text
    assert "hidden" not in text
    assert "Do Not Render" not in html
    assert "999999" not in html
    assert "hidden" not in html


def test_native_fids_empty_board_shows_user_focused_waiting_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import FidsScreen
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = FidsScreen(QtCore, QtGui, QtWidgets2, client=object())
    screen._apply_board(
        {
            "view": "departures",
            "cfg": {"airport_iata": "ZRH", "source": "real", "web_row_limit": 20, "web_rotation_seconds": 8},
            "payload": [],
            "weather": {"weather_icon": "sun", "flight_cat": "VFR", "temperature_c": 12, "decoded_summary": "Clear"},
        }
    )

    label_widget = screen.info_banner.findChild(QtWidgets.QLabel)
    progress = screen.info_banner.findChild(QtWidgets.QProgressBar, "LoadingProgress")

    assert app is not None
    assert not screen.info_banner.isHidden()
    assert label_widget is not None
    assert "local flight will keep checking" in label_widget.text().lower()
    assert "relay" not in label_widget.text().lower()
    assert progress is not None
    assert progress.isHidden()


def test_native_fids_loading_banner_uses_busy_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import FidsScreen
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = FidsScreen(QtCore, QtGui, QtWidgets2, client=object())

    screen._set_info_banner("Updating arrivals. First refreshes can take a moment.", True, busy=True)
    label_widget = screen.info_banner.findChild(QtWidgets.QLabel)
    progress = screen.info_banner.findChild(QtWidgets.QProgressBar, "LoadingProgress")

    assert app is not None
    assert label_widget is not None
    assert "updating arrivals" in label_widget.text().lower()
    assert progress is not None
    assert not progress.isHidden()
    assert progress.minimum() == 0
    assert progress.maximum() == 0


def test_native_fids_model_click_fetches_visible_row_callsign(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import FidsScreen
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = FidsScreen(QtCore, QtGui, QtWidgets2, client=object())
    seen: list[str] = []

    class _Service:
        def fids_detail(self, callsign: str) -> dict[str, object]:
            seen.append(callsign)
            return {
                "detail": {
                    "detail_mode": "virtual",
                    "callsign": callsign,
                    "origin_icao": "LSZH",
                    "dest_icao": "EGLL",
                    "data_sources": {"schedule": "vatsim"},
                },
                "history": [],
            }

    screen.service = _Service()
    screen._run_async = lambda fetch, apply, _error, **_kwargs: (apply(fetch()) or True)
    screen._apply_board(
        {
            "view": "departures",
            "cfg": {"airport_iata": "ZRH", "source": "virtual", "web_row_limit": 1, "web_rotation_seconds": 8},
            "payload": [
                {"callsign": f"PAGE1{i}", "flight_display": f"PAGE1 {i}", "route_display": "London"}
                for i in range(5)
            ]
            + [
                {"callsign": "SECOND2", "flight_display": "SECOND 2", "route_display": "Paris"},
            ],
            "weather": {"weather_icon": "sun", "flight_cat": "VFR", "temperature_c": 12, "decoded_summary": "Clear"},
        }
    )
    screen.page_index = 1
    screen._render_rows()
    screen._show_detail_for_row(0, 1)

    assert app is not None
    assert seen == ["SECOND2"]
    assert "Virtual flight" in screen.detail_body.toPlainText()


def test_native_fids_shapes_codeshare_fallback_and_delay_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import FidsScreen
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = FidsScreen(QtCore, QtGui, QtWidgets2, client=object())
    row = {
        "callsign": "SWR100",
        "flight_display": "LX 100",
        "codeshares": ["UA9000", "AC7000"],
        "display_time": "12:00 (+25)",
        "sched_time": "2026-05-05T10:00:00+00:00",
        "delay_minutes": 25,
        "status_display": "DELAYED +25M",
        "status_class": "delayed",
    }
    screen._set_airport_timezone("Europe/Zurich")
    shaped = screen._model_row(row, 0)

    assert app is not None
    assert shaped["display_time"] == "12:00 (+25)"
    assert shaped["codeshare_display"] == "UA 9000 / AC 7000"
    assert shaped["_codeshare_frames"] == ["UA 9000", "AC 7000"]
    assert shaped["status_class"] == "delayed-bad"
    assert screen.delegate._split_time_delay(shaped["display_time"]) == ("12:00", "+25")
    assert screen.delegate._status_color(shaped, screen.colors) == screen.colors["red"]


def test_native_fids_animates_sold_as_codeshare_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import FidsScreen
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = FidsScreen(QtCore, QtGui, QtWidgets2, client=object())
    screen.rows = [
        {
            "callsign": "SWR100",
            "flight_display": "LX 100",
            "airline_display": "Swiss",
            "sold_as": "UA9000 / AC7000",
            "display_time": "12:00",
        }
    ]
    screen.set_active(True)
    screen._render_rows()
    first = screen.visible_rows[0]
    screen._advance_codeshare_frames()
    second = screen.visible_rows[0]

    assert app is not None
    assert first["_codeshare_frames"] == ["UA 9000", "AC 7000"]
    assert screen.delegate._codeshare_frame(first) == "UA 9000"
    assert screen.delegate._codeshare_frame(second) == "AC 7000"
    assert screen.codeshare_timer.isActive()


def test_native_fids_derives_delay_visuals_from_delay_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import FidsScreen
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = FidsScreen(QtCore, QtGui, QtWidgets2, client=object())
    screen._set_airport_timezone("Europe/Zurich")
    shaped = screen._model_row(
        {
            "callsign": "SWR100",
            "flight_display": "LX 100",
            "display_time": "12:00",
            "sched_time": "2026-05-05T10:00:00+00:00",
            "delay_minutes": 25,
            "status_display": "SCHEDULED",
            "status_class": "scheduled",
        },
        0,
    )

    assert app is not None
    assert shaped["display_time"] == "12:00 (+25)"
    assert shaped["status_class"] == "delayed-bad"
    assert screen.delegate._status_color(shaped, screen.colors) == screen.colors["red"]
    model = screen.model
    model.set_rows([shaped])

    warn = screen._model_row(
        {
            "callsign": "SWR101",
            "flight_display": "LX 101",
            "display_time": "12:10",
            "delay_minutes": 15,
            "status_display": "SCHEDULED",
            "status_class": "scheduled",
        },
        1,
    )
    early = screen._model_row(
        {
            "callsign": "SWR102",
            "flight_display": "LX 102",
            "display_time": "12:20",
            "delay_minutes": -8,
            "status_display": "LANDED",
            "status_class": "landed",
        },
        2,
    )
    assert warn["status_class"] == "delayed-warn"
    assert screen.delegate._status_color(warn, screen.colors) == screen.colors["amber"]
    assert early["status_class"] == "early"
    assert screen.delegate._status_color(early, screen.colors) == screen.colors["green"]
    assert model.data(model.index(0, 3), QtCore.Qt.DisplayRole) == "DELAYED +25M"
    assert model.data(model.index(0, 3), QtCore.Qt.ForegroundRole).color().name() == screen.colors["red"]
    assert model.data(model.index(0, 3), QtCore.Qt.BackgroundRole) is None


def test_native_fids_status_then_gate_column_widths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import FidsScreen
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = FidsScreen(QtCore, QtGui, QtWidgets2, client=object())
    screen.board.resize(1200, 500)
    screen.visible_rows = [
        {
            "display_time": "12:00",
            "flight_display": "LX 100",
            "route_display": "London",
            "status_display": "DELAYED +25M",
            "gate": "A42",
        }
    ]
    screen.model.set_rows(screen.visible_rows)
    screen._fit_columns()
    columns = screen.board._column_rects(screen.board.viewport().rect())

    assert app is not None
    assert screen.model.headerData(3, QtCore.Qt.Horizontal, QtCore.Qt.DisplayRole) == "Status"
    assert screen.model.headerData(4, QtCore.Qt.Horizontal, QtCore.Qt.DisplayRole) == "Gate"
    assert tuple(screen.board.column_keys) == (
        "display_time",
        "flight_cell",
        "route_display",
        "status_display",
        "gate",
        "aircraft_type",
    )
    assert columns["status_display"].left() < columns["gate"].left()
    assert columns["status_display"].width() > columns["gate"].width()
    assert screen.board._row_at_y(screen.board.padding + screen.board.header_h + 4) == 0


def test_native_fids_board_animation_pauses_when_inactive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import FidsScreen
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = FidsScreen(QtCore, QtGui, QtWidgets2, client=object())

    screen.set_active(True)
    screen._set_info_banner("Updating arrivals. First refreshes can take a moment.", True, busy=True)
    assert app is not None
    assert screen.board_animation_timer.isActive()
    screen._advance_board_animation()
    assert "SCAN" in screen.scan_indicator.text()

    screen.set_active(False)
    assert not screen.board_animation_timer.isActive()
    assert screen.scan_indicator.text() == ""


def test_native_fids_plain_model_rotates_one_codeshare_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import FidsScreen
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = FidsScreen(QtCore, QtGui, QtWidgets2, client=object())
    screen.rows = [
        {
            "callsign": "SWR100",
            "flight_display": "LX 100",
            "airline_display": "Swiss",
            "codeshares": ["UA9000", "AC7000"],
            "display_time": "12:00",
        }
    ]
    screen.set_active(True)
    screen._render_rows()
    first = screen.model.data(screen.model.index(0, 1), QtCore.Qt.DisplayRole)
    screen._advance_codeshare_frames()
    second = screen.model.data(screen.model.index(0, 1), QtCore.Qt.DisplayRole)

    assert app is not None
    assert first.splitlines()[-1] == "UA 9000"
    assert second.splitlines()[-1] == "AC 7000"


def test_native_fids_keeps_visible_window_filled_ahead_of_completed_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import FidsScreen
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = FidsScreen(QtCore, QtGui, QtWidgets2, client=object())
    screen.row_limit = 3
    screen.rows = screen._ordered_board_rows(
        [
            {"callsign": "DONE1", "flight_display": "LX 1", "display_time": "10:00", "status_class": "departed"},
            {"callsign": "ACTIVE1", "flight_display": "LX 2", "display_time": "10:05", "status_class": "scheduled"},
            {"callsign": "LANDED1", "flight_display": "LX 3", "display_time": "10:10", "status_class": "landed"},
            {"callsign": "ACTIVE2", "flight_display": "LX 4", "display_time": "10:15", "status_class": "boarding"},
            {"callsign": "ACTIVE3", "flight_display": "LX 5", "display_time": "10:20", "status_class": "delayed"},
        ]
    )
    screen._render_rows()

    assert app is not None
    assert [row["callsign"] for row in screen.visible_rows] == ["ACTIVE1", "ACTIVE2", "ACTIVE3"]
    assert [row["callsign"] for row in screen.rows[-2:]] == ["DONE1", "LANDED1"]


def test_native_fids_completed_rows_still_fill_when_not_enough_active(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import FidsScreen
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = FidsScreen(QtCore, QtGui, QtWidgets2, client=object())
    screen.row_limit = 3
    screen.rows = screen._ordered_board_rows(
        [
            {"callsign": "DONE1", "flight_display": "LX 1", "display_time": "10:00", "status_class": "departed"},
            {"callsign": "ACTIVE1", "flight_display": "LX 2", "display_time": "10:05", "status_class": "scheduled"},
            {"callsign": "LANDED1", "flight_display": "LX 3", "display_time": "10:10", "status_class": "landed"},
        ]
    )
    screen._render_rows()

    assert app is not None
    assert [row["callsign"] for row in screen.visible_rows] == ["ACTIVE1", "DONE1", "LANDED1"]


def test_native_settings_has_airport_search_picker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import SettingsScreen
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = SettingsScreen(QtCore, QtGui, QtWidgets2, client=object(), base_url="http://127.0.0.1:9")

    assert app is not None
    assert screen.airport_search.placeholderText().startswith("Search airport")
    assert screen.airport_iata.isReadOnly()
    assert screen.airport_icao.isReadOnly()
    assert screen.timezone.isReadOnly()
    assert screen.loading_indicator.isVisible() is False
    assert screen.apply_surface_button.text() == "Apply radar overlay"
    assert "Surface overlay" in screen.surface_status.text()
    assert screen.surface_progress.isVisible() is False
    assert screen.help_docs_group.isChecked() is False
    assert screen.help_docs_body.isVisible() is False
    assert screen.maintenance_group.isChecked() is False
    assert screen.maintenance_body.isVisible() is False
    assert screen.advanced_display_group.isChecked() is False
    assert screen.advanced_display_body.isVisible() is False


def test_native_settings_is_extracted_from_legacy_module() -> None:
    import localflight.native.pages.settings as settings_page

    assert settings_page.SettingsScreen.__module__ == "localflight.native.pages.settings"


def test_native_settings_config_payload_preserves_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import SettingsScreen
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = SettingsScreen(QtCore, QtGui, QtWidgets2, client=object(), base_url="http://127.0.0.1:9")
    screen._populate_config(
        {
            "airport_iata": "sin",
            "airport_icao": "wsss",
            "timezone": "Asia/Singapore",
            "display_name": "Terminal Board",
            "source": "virtual",
            "refresh_seconds": 1800,
            "theme": "light",
            "skin": "night_ops",
            "diagnostics_mode": "manual",
            "web_row_limit": 32,
            "web_rotation_seconds": 12,
            "display_grace_minutes": 45,
            "display_horizon_hours": 18,
            "radar_surface_enabled": True,
            "display_outputs": [],
        }
    )
    screen.output_web.setChecked(False)
    screen.output_matrix.setChecked(False)
    screen.output_hdmi.setChecked(False)

    payload = screen._config_payload()

    assert app is not None
    assert set(payload) == {
        "airport_iata",
        "airport_icao",
        "timezone",
        "display_name",
        "source",
        "refresh_seconds",
        "theme",
        "skin",
        "diagnostics_mode",
        "web_row_limit",
        "web_rotation_seconds",
        "display_grace_minutes",
        "display_horizon_hours",
        "radar_surface_enabled",
        "display_outputs",
    }
    assert payload["airport_iata"] == "SIN"
    assert payload["airport_icao"] == "WSSS"
    assert payload["refresh_seconds"] == 1800
    assert payload["display_outputs"] == ["web"]


def test_native_settings_actions_use_native_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import SettingsScreen
    from localflight.native.qt_compat import import_qt

    class _Service:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        def save_config(self, payload: dict[str, object]) -> dict[str, object]:
            self.calls.append(("save_config", payload))
            return {"ok": True}

        def restart_scheduler(self) -> dict[str, object]:
            self.calls.append(("restart_scheduler", None))
            return {"message": "Scheduler restart requested."}

        def setup_reset(self) -> dict[str, object]:
            self.calls.append(("setup_reset", None))
            return {"ok": True}

        def save_profile(self, name: str) -> dict[str, object]:
            self.calls.append(("save_profile", name))
            return {"ok": True}

        def load_profile(self, name: str) -> dict[str, object]:
            self.calls.append(("load_profile", name))
            return {"ok": True}

        def delete_profile(self, name: str) -> dict[str, object]:
            self.calls.append(("delete_profile", name))
            return {"ok": True}

        def config(self) -> dict[str, object]:
            self.calls.append(("config", None))
            return {"airport_iata": "ZRH", "airport_icao": "LSZH", "display_outputs": ["web"]}

        def setup_client_info(self) -> dict[str, object]:
            self.calls.append(("setup_client_info", None))
            return {"relay_url": "https://relay.example", "has_activation_token": False}

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = SettingsScreen(QtCore, QtGui, QtWidgets2, client=object(), base_url="http://127.0.0.1:9")
    service = _Service()
    screen.service = service
    monkeypatch.setattr("localflight.native.pages.settings.list_profiles", lambda: ["home"])
    monkeypatch.setattr(QtWidgets2.QMessageBox, "question", lambda *_args, **_kwargs: QtWidgets2.QMessageBox.Yes)

    screen.profile_name.setText("home")
    screen.save()
    screen.restart_scheduler()
    screen.reset_setup()
    screen.save_profile()
    screen.profile_combo.clear()
    screen.profile_combo.addItem("home")
    screen.load_profile()
    screen.profile_combo.clear()
    screen.profile_combo.addItem("home")
    screen.delete_profile()

    assert app is not None
    assert [call[0] for call in service.calls] == [
        "save_config",
        "restart_scheduler",
        "setup_reset",
        "save_profile",
        "load_profile",
        "config",
        "setup_client_info",
        "delete_profile",
    ]


def test_native_settings_surface_check_feedback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import SettingsScreen
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = SettingsScreen(QtCore, QtGui, QtWidgets2, client=object(), base_url="http://127.0.0.1:9")

    screen._apply_surface_check_result(
        {
            "runways": [{"label": "25L/07R"}],
            "surface_features": [{"kind": "terminal"}],
            "sources": {"surface": "localflight-estimated", "surface_cache_state": "estimated"},
        }
    )

    assert app is not None
    assert "Surface data ready" in screen.surface_status.text()
    assert "1 runway" in screen.surface_status.text()
    assert "online map check timed out" in screen._surface_error_message(RuntimeError("HTTPConnectionPool read timed out"))


def test_native_media_and_docs_are_resolvable() -> None:
    from localflight.native.design import bundled_doc, resolve_media_path

    assert resolve_media_path("ui", "static", "splash_mark.svg") is not None
    assert resolve_media_path("assets", "icon_circle.svg") is not None
    assert resolve_media_path("docs", "previews", "fids-preview.svg") is not None

    readme = bundled_doc("readme")

    assert readme["filename"] == "README.md"
    assert "Local Flight" in readme["text"]


def test_native_theme_and_skin_tokens_cover_web_choices() -> None:
    from localflight.native.design import colors_for, native_stylesheet

    for theme in ("dark", "light"):
        for skin in ("standard", "technical", "neon", "cyan", "crt"):
            colors = colors_for(theme, skin)
            sheet = native_stylesheet(theme=theme, skin=skin)

            assert colors["bg"].startswith("#")
            assert colors["blue"].startswith("#")
            assert colors["cyan"].startswith("#")
            assert colors["blue"] in sheet
            assert "QFrame#TopNav" in sheet
            assert "QTableWidget#FidsTable" in sheet


def test_native_fonts_match_web_kiosk_families(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.design import (
        BOARD_FONT_FAMILY,
        UI_FONT_FAMILY,
        apply_app_font_defaults,
        native_stylesheet,
    )
    from localflight.native.qt_compat import import_qt

    _QtCore, QtGui, _QtWidgets = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    loaded = set(apply_app_font_defaults(QtGui, app))
    sheet = native_stylesheet()

    assert UI_FONT_FAMILY in loaded
    assert BOARD_FONT_FAMILY in loaded
    assert app.font().family() == UI_FONT_FAMILY
    assert f'font-family: "{UI_FONT_FAMILY}"' in sheet
    assert f'font-family: "{BOARD_FONT_FAMILY}"' in sheet


def test_native_light_theme_keeps_nav_and_core_text_readable() -> None:
    from localflight.native.design import colors_for, native_stylesheet

    colors = colors_for("light", "crt")
    sheet = native_stylesheet(theme="light", skin="crt")

    assert f"QLabel#Brand {{\n  color: {colors['text']};" in sheet
    assert f"QLabel#Title {{\n  font-size: 24px;\n  font-weight: 900;\n  color: {colors['text']};" in sheet
    assert f"QLabel#Metric {{\n  color: {colors['text']};" in sheet
    assert "rgba(232,240,254,0.68)" not in sheet
    assert "border-bottom: 1px solid rgba(255,255,255,0.07)" not in sheet
    assert "QPushButton#NavButton:checked" in sheet
    assert f"color: {colors['text']};" in sheet


def test_native_window_applies_config_skin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import NativeMainWindow
    from localflight.native.qt_compat import import_qt

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = NativeMainWindow(*import_qt(), base_url="http://127.0.0.1:9", first_launch=False)

    window._apply_design_from_config({"theme": "light", "skin": "crt"})

    assert app is not None
    assert window.theme == "light"
    assert window.skin == "crt"
    assert "#9aff6b" in window.styleSheet()


def test_native_settings_embeds_public_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import SettingsScreen
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    screen = SettingsScreen(QtCore, QtGui, QtWidgets2, client=object(), base_url="http://127.0.0.1:9")
    screen.open_doc("privacy")

    assert app is not None
    assert screen.current_doc_slug == "privacy"
    assert "Privacy" in screen.doc_title.text()
    assert "diagnostics" in screen.doc_summary.text().lower()


def test_native_network_admin_tabs_match_operator_surfaces(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.delenv("LOCALFLIGHT_NETWORK_ADMIN_RAW", raising=False)
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.network_admin import NetworkAdminWindow
    from localflight.native.qt_compat import import_qt

    QtCore, _QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = NetworkAdminWindow(QtCore, QtWidgets2)

    assert app is not None
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == [
        "Overview",
        "Providers",
        "Usage",
        "Schedules",
        "Surfaces",
        "Activations",
        "Reports",
        "Maintenance",
    ]
    assert "Raw" not in window.pages
    assert set(window.nav_buttons) == set(window.pages)


def test_native_network_admin_raw_tab_is_explicit_debug_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("LOCALFLIGHT_NETWORK_ADMIN_RAW", "1")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.network_admin import NetworkAdminWindow
    from localflight.native.qt_compat import import_qt

    QtCore, _QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = NetworkAdminWindow(QtCore, QtWidgets2)

    assert app is not None
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())][-1] == "Raw"
    assert "raw" in window.pages


def test_native_network_admin_visible_actions_are_route_declared(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.delenv("LOCALFLIGHT_NETWORK_ADMIN_RAW", raising=False)
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.network_admin import NetworkAdminWindow
    from localflight.native.qt_compat import import_qt
    from localflight.native.routes import NETWORK_ADMIN_ROUTES

    QtCore, _QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = NetworkAdminWindow(QtCore, QtWidgets2)
    window.payloads = {
        "overview": {
            "month": "2026-05",
            "counts": {"usage_rows": 1, "schedule_snapshots": 1, "surface_snapshots": 1, "activation_requests_pending": 1, "reports_24h": 1},
            "shared_schedule": {"cache_hits": 4, "upstream_pulls": 2, "client_accesses": 8},
            "surface_cache": {"cache_hits": 3},
            "providers": {
                "aviationstack": {"configured": True, "source": "relay", "masked": "av..."},
                "rapidapi": {"configured": False, "source": "unset", "masked": ""},
            },
        },
        "usage": {"month": "2026-05", "summary": [], "rows": []},
        "schedules": {"snapshots": [], "client_interests": []},
        "surfaces": {"enabled": False, "snapshots": []},
        "activations": {
            "tokens": [{"token_prefix": "tok_1234567890", "action_ref": "tok_action_ref", "revoked": False}],
            "requests": [{"request_id": "req_1234567890", "action_ref": "req_action_ref", "status": "pending"}],
            "blocked_installs": [{"install_fingerprint": "abcdef1234567890", "action_ref": "inst_action_ref"}],
        },
        "reports": {"summary_24h": [], "recent_events": [], "dedupe": []},
    }
    window._render_all()

    declared = {route.path for route in NETWORK_ADMIN_ROUTES}
    action_buttons = [
        button
        for button in window.findChildren(QtWidgets.QPushButton)
        if button.property("lf_action_path")
    ]

    assert app is not None
    assert action_buttons
    assert {str(button.property("lf_action_path")) for button in action_buttons}.issubset(declared)
    assert "/admin/api/providers/save" in {str(button.property("lf_action_path")) for button in action_buttons}
    assert "/admin/api/maintenance/clean-trial" in {str(button.property("lf_action_path")) for button in action_buttons}


def test_native_network_admin_auto_refresh_keeps_credentials_and_active_tab(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.delenv("LOCALFLIGHT_NETWORK_ADMIN_RAW", raising=False)
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    import localflight.native.network_admin as network_admin
    from localflight.native.network_admin import NetworkAdminWindow
    from localflight.native.qt_compat import import_qt

    calls: list[str] = []

    class _Relay:
        def __init__(self, *, base_url: str, username: str, password: str) -> None:
            assert base_url.endswith("/admin")
            assert username == "admin"
            assert password == "secret"

        def get_json(self, path: str) -> dict[str, object]:
            calls.append(path)
            if path == "/admin/api/overview":
                return {"generated_at": "now", "counts": {}, "providers": {}, "shared_schedule": {}, "surface_cache": {}}
            return {}

    monkeypatch.setattr(network_admin, "RelayAdminClient", _Relay)
    QtCore, _QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = NetworkAdminWindow(QtCore, QtWidgets2)
    window.password.setText("secret")
    window.connect_relay()
    window._show_page("reports")
    calls.clear()
    window._auto_refresh_tick()

    assert app is not None
    assert window.password.text() == "secret"
    assert window._current_page_key() == "reports"
    assert calls == ["/admin/api/reports"]


def test_native_declared_routes_exist() -> None:
    import localflight.ui.server as ui_server
    import relay.main as relay_main
    from localflight.native.routes import CLIENT_ROUTES, NETWORK_ADMIN_ROUTES

    local_paths = {getattr(route, "path", "") for route in ui_server.app.routes}
    relay_paths = {getattr(route, "path", "") for route in relay_main.app.routes}

    client_paths = {route.path for route in CLIENT_ROUTES}
    relay_admin_paths = {route.path for route in NETWORK_ADMIN_ROUTES}

    assert client_paths.issubset(local_paths)
    assert relay_admin_paths.issubset(relay_paths)
    assert {"/api/feedback", "/api/feedback/crash"}.issubset(client_paths)


def test_native_page_registry_tracks_browser_parity_templates() -> None:
    from pathlib import Path
    import re

    from localflight.native.registry import (
        PAGE_SPECS,
        SETUP_PAGE_SPEC,
        browser_parity_templates,
        fallback_refresh_page_keys,
        page_spec,
    )

    template_names = {path.name for path in Path("src/localflight/ui/templates").glob("*.html")}
    fids_template = Path("src/localflight/ui/templates/fids.html").read_text(encoding="utf-8")
    fids_fetch_routes = {
        match.group(1)
        for match in re.finditer(r'fetch\((?:`|")([^"`?]+)', fids_template)
        if match.group(1).startswith("/api/")
    }

    assert [spec.key for spec in PAGE_SPECS] == [
        "display",
        "fids",
        "radar",
        "matrix",
        "settings",
        "admin",
        "history",
        "logs",
        "requests",
        "feedback",
    ]
    assert browser_parity_templates().issubset(template_names)
    assert SETUP_PAGE_SPEC.browser_template == "setup.html"
    assert "/api/setup/client-status" in SETUP_PAGE_SPEC.required_routes
    assert fids_fetch_routes.issubset(page_spec("fids").required_routes)
    assert "/ws" in page_spec("fids").required_routes
    assert {
        "/api/config",
        "/api/setup/client-info",
        "/api/airports/search",
        "/profiles/save",
        "/profiles/load",
        "/profiles/delete",
        "/api/setup/reset",
        "/api/admin/scheduler/restart",
    }.issubset(page_spec("settings").required_routes)
    assert {"/api/feedback", "/api/feedback/crash", "/api/setup/client-info"}.issubset(
        page_spec("feedback").required_routes
    )
    assert fallback_refresh_page_keys() == {"display", "fids", "radar"}
    assert all(spec.module.startswith("localflight.native.pages.") for spec in PAGE_SPECS)
    assert all(spec.required_routes for spec in PAGE_SPECS)


def test_native_main_window_uses_page_registry_for_refresh_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import NativeMainWindow
    from localflight.native.qt_compat import import_qt
    from localflight.native.registry import PAGE_SPECS, primary_page_keys

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = NativeMainWindow(*import_qt(), base_url="http://127.0.0.1:9", first_launch=False)

    assert app is not None
    assert window.screen_keys == [spec.key for spec in PAGE_SPECS]
    assert [window.primary_nav_layout.itemAt(i).widget().property("lf_key") for i in range(window.primary_nav_layout.count())] == list(primary_page_keys())
    assert window._fallback_refresh_keys == {"display", "fids", "radar"}


def test_native_service_adapters_normalize_core_payloads() -> None:
    from localflight.native.service import NativeApiService

    class _Client:
        def get_json(self, path: str, *, params: dict[str, object] | None = None) -> dict[str, object]:
            if path == "/api/config":
                return {"airport_iata": "ZRH", "radar_surface_enabled": True}
            if path == "/api/health":
                return {"ok": True}
            if path == "/api/metar":
                return {"flight_cat": "VFR"}
            if path == "/api/radar":
                return {"radius_nm": params["radius_nm"], "blips": [{"callsign": "LX1"}]}
            if path == "/api/radar/surface":
                return {"features": [{"kind": "runway"}]}
            if path == "/api/matrix/v2/presets":
                return {"presets": [{"id": "real_fids"}]}
            if path == "/api/matrix/v2/configs":
                return {"default_config_id": "default", "configs": [{"id": "default"}]}
            if path == "/api/matrix/v2/devices":
                return {"devices": [{"device_id": "board"}]}
            raise AssertionError(path)

        def get_any_json(self, path: str, *, params: dict[str, object] | None = None) -> object:
            assert path == "/api/fids"
            return [{"flight_display": "LX 1"}]

    service = NativeApiService(_Client())

    board = service.fids_board(view="departures")
    radar = service.radar(radius_nm=3)
    matrix = service.matrix_state()

    assert board.config["airport_iata"] == "ZRH"
    assert board.rows == [{"flight_display": "LX 1"}]
    assert board.health == {"ok": True}
    assert radar.config["airport_iata"] == "ZRH"
    assert radar.config["radar_surface_enabled"] is True
    assert radar.blips == [{"callsign": "LX1"}]
    assert radar.surface == {"features": [{"kind": "runway"}]}
    assert matrix.default_config_id == "default"
    assert matrix.presets[0]["id"] == "real_fids"


def test_native_service_prefers_radar_map_over_surface_fallback() -> None:
    from localflight.native.service import NativeApiService

    class _Client:
        def __init__(self) -> None:
            self.paths: list[str] = []

        def get_json(self, path: str, *, params: dict[str, object] | None = None) -> dict[str, object]:
            self.paths.append(path)
            if path == "/api/config":
                return {"airport_iata": "ZRH", "radar_surface_enabled": True}
            if path == "/api/radar/map":
                return {"runways": [{"kind": "runway"}], "surface_features": []}
            if path == "/api/radar":
                return {"radius_nm": params["radius_nm"], "blips": []}
            if path == "/api/metar":
                return {"flight_cat": "VFR"}
            if path == "/api/radar/surface":
                raise AssertionError("surface fallback should not be called when radar map is available")
            raise AssertionError(path)

    client = _Client()
    radar = NativeApiService(client).radar(radius_nm=5)

    assert radar.radar_map == {"runways": [{"kind": "runway"}], "surface_features": []}
    assert "/api/radar/surface" not in client.paths


def test_native_radar_surface_label_distinguishes_runway_truth_from_estimate() -> None:
    from localflight.native.pages.radar import _surface_source_label

    label = _surface_source_label(
        {
            "provider": "localflight-estimated",
            "cache_state": "estimated",
            "features": [
                {"kind": "boundary", "label": "Estimated airport"},
                {"kind": "runway", "label": "7L/25R", "confidence": "ourairports"},
            ],
        }
    )

    assert label == "OurAirports runways with estimated surface"


def test_native_service_adapters_cover_kiosk_parity_reads() -> None:
    from localflight.native.service import NativeApiService

    class _Client:
        def get_json(self, path: str, *, params: dict[str, object] | None = None) -> dict[str, object]:
            if path == "/api/config":
                return {"airport_iata": "ZRH"}
            if path == "/api/admin/system":
                return {"version": "test"}
            if path == "/api/setup/client-info":
                return {"relay_url": "https://relay.test"}
            if path == "/api/history":
                assert params == {"hours": 24, "direction": "both", "limit": 500}
                return {"flights": [{"callsign": "SWR1"}], "count": 1}
            if path == "/api/history/flight":
                assert params == {"callsign": "SWR1", "days": 30}
                return {"flights": [{"callsign": "SWR1"}]}
            if path == "/api/history/summary":
                assert params == {"hours": 24}
                return {"total": 1}
            if path == "/api/admin/requests":
                assert params == {"hours": 6, "limit": 300, "client_type": "native"}
                return {"summary": {"total": 1}, "requests": [{"path": "/api/fids"}]}
            if path == "/api/logs":
                return {"files": ["localflight.log"], "selected": "localflight.log", "total": 12}
            if path == "/logs/tail":
                assert params == {"file": "localflight.log", "after": 0}
                return {"lines": ["one", "two"], "total": 2}
            raise AssertionError(path)

        def get_any_json(self, path: str, *, params: dict[str, object] | None = None) -> object:
            if path == "/api/airports/search":
                assert params == {"q": "zurich", "limit": 10}
                return [{"iata": "ZRH"}]
            raise AssertionError(path)

    service = NativeApiService(_Client())

    assert service.airport_search("zurich") == [{"iata": "ZRH"}]
    assert service.history_payload()["flights"][0]["callsign"] == "SWR1"
    assert service.history_flight("SWR1")["flights"][0]["callsign"] == "SWR1"
    assert service.history_summary(hours=24)["total"] == 1
    assert service.request_log(hours=6, client_type="native").rows == [{"path": "/api/fids"}]
    assert service.log_tail(selected="localflight.log").lines == ["one", "two"]
    cfg, system, client_info = service.feedback_context()
    assert cfg["airport_iata"] == "ZRH"
    assert system["version"] == "test"
    assert client_info["relay_url"] == "https://relay.test"


def test_native_service_adapters_cover_native_actions() -> None:
    from localflight.native.service import NativeApiService

    class _Client:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, object]] = []
            self.cache_cleared = False

        def clear_cache(self) -> None:
            self.cache_cleared = True

        def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
            self.calls.append(("post_json", path, payload))
            return {"ok": True, "path": path}

        def patch_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
            self.calls.append(("patch_json", path, payload))
            return {"ok": True, "path": path}

        def delete_json(self, path: str) -> dict[str, object]:
            self.calls.append(("delete_json", path, {}))
            return {"ok": True, "path": path}

        def post_form(self, path: str, payload: dict[str, object]) -> dict[str, object]:
            self.calls.append(("post_form", path, payload))
            return {"ok": True, "path": path}

        def post_text(self, path: str, payload: dict[str, object]) -> str:
            self.calls.append(("post_text", path, payload))
            return "generated"

    client = _Client()
    service = NativeApiService(client)
    matrix_payload = {
        "brightness": 0.8,
        "max_rows": 4,
        "refresh_seconds": 60,
        "page_rotation_seconds": 10,
        "animation_enabled": True,
    }

    service.clear_cache()
    service.quit_app()
    service.save_config({"theme": "dark"})
    service.setup_complete({"source": "virtual"})
    service.setup_reset()
    service.matrix_save_config(config_id="cfg1", payload=matrix_payload, v2_available=True)
    service.matrix_save_config(config_id=None, payload=matrix_payload, v2_available=False)
    service.matrix_create_config({"name": "Board"})
    service.matrix_delete_config("cfg1")
    service.matrix_set_default_config("cfg1")
    service.matrix_save_device_assignment("board1", {"assigned_config_id": "cfg1"})
    assert service.matrix_generate_script({"wifi_ssid": "x"}) == "generated"
    service.restart_scheduler()
    service.save_profile("Home")
    service.load_profile("Home")
    service.delete_profile("Home")
    service.send_feedback({"title": "T", "description": "Long enough"})

    paths = [path for _method, path, _payload in client.calls]
    assert client.cache_cleared is True
    assert "/api/quit" in paths
    assert "/api/config" in paths
    assert "/api/setup/complete" in paths
    assert "/api/setup/reset" in paths
    assert "/api/matrix/v2/configs/cfg1" in paths
    assert "/api/matrix/config" in paths
    assert "/api/matrix/script" in paths
    assert "/api/admin/scheduler/restart" in paths
    assert "/profiles/save" in paths
    assert "/profiles/load" in paths
    assert "/profiles/delete" in paths
    assert "/api/feedback" in paths


def test_native_table_models_expose_common_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.models import FlightBoardModel, HistoryModel, RequestLogModel
    from localflight.native.qt_compat import import_qt

    QtCore, _QtGui, _QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    model = FlightBoardModel(QtCore, [{"display_time": "09:10", "flight_display": "LX 1"}])
    styled = FlightBoardModel(
        QtCore,
        [
            {
                "display_time": "09:20",
                "flight_display": "LX 2",
                "status_display": "Boarding",
                "status_class": "boarding",
                "codeshares": ["UA9000", "AC7000"],
            }
        ],
    )
    history = HistoryModel(QtCore, [{"callsign": "SWR1"}])
    requests = RequestLogModel(QtCore, [{"method": "GET", "path": "/api/fids"}])

    assert app is not None
    assert model.rowCount() == 1
    assert [label for _key, label in model.columns] == ["Time", "Flight", "Route", "Status", "Gate", "A/C"]
    assert model.headerData(1, QtCore.Qt.Horizontal, QtCore.Qt.DisplayRole) == "Flight"
    assert model.data(model.index(0, 1), QtCore.Qt.DisplayRole) == "LX 1"
    assert styled.headerData(3, QtCore.Qt.Horizontal, QtCore.Qt.DisplayRole) == "Status"
    assert styled.headerData(4, QtCore.Qt.Horizontal, QtCore.Qt.DisplayRole) == "Gate"
    assert styled.data(styled.index(0, 3), QtCore.Qt.DisplayRole) == "BOARDING"
    assert "UA 9000 / AC 7000" in styled.data(styled.index(0, 1), QtCore.Qt.DisplayRole)
    assert history.headerData(3, QtCore.Qt.Horizontal, QtCore.Qt.DisplayRole) == "Callsign"
    assert requests.data(requests.index(0, 1), QtCore.Qt.DisplayRole) == "GET"
    model.set_rows([])
    assert model.rowCount() == 0


def test_native_reusable_widgets_construct_without_legacy_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.qt_compat import import_qt
    from localflight.native.widgets import AirportSearchBox, DetailDrawer, StatusCard, WeatherStrip

    QtCore, _QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    selected: list[dict[str, object]] = []

    status = StatusCard(QtWidgets2, "Airport", "ZRH")
    weather = WeatherStrip(QtWidgets2)
    drawer = DetailDrawer(QtWidgets2, "Flight")
    search = AirportSearchBox(
        QtCore,
        QtWidgets2,
        search=lambda _query: [{"iata": "ZRH", "icao": "LSZH", "name": "Zurich", "city": "Zurich"}],
        on_select=lambda row: selected.append(row),
    )
    weather.set_weather("VFR Clear", "*")

    assert app is not None
    assert status.findChildren(QtWidgets.QLabel)
    assert weather.body_label.text() == "VFR Clear"
    assert drawer.body.isReadOnly()
    assert search.line_edit.placeholderText().startswith("Search airport")


def test_native_live_helpers_map_urls_and_refresh_targets() -> None:
    from localflight.native.live import event_refresh_targets, native_ws_url

    assert native_ws_url("http://127.0.0.1:8000") == "ws://127.0.0.1:8000/ws"
    assert native_ws_url("https://example.test/root") == "wss://example.test/ws"
    assert event_refresh_targets("snapshot_updated", {"display", "fids", "radar"}, "fids") == {"display", "radar"}
    assert event_refresh_targets("config_updated", {"display", "fids", "radar"}, "fids") == {"display", "fids", "radar"}


def test_native_route_registry_is_labelled_and_owned() -> None:
    from localflight.native.routes import CLIENT_ROUTES, NETWORK_ADMIN_ROUTES

    routes = CLIENT_ROUTES + NETWORK_ADMIN_ROUTES

    assert routes
    assert all(route.action_id and route.label and route.method and route.path and route.owner for route in routes)
    assert all(route.method in {"GET", "POST", "PATCH"} for route in routes)
    assert len({route.action_id for route in routes}) == len(routes)
    assert {route.surface for route in routes} == {"client", "network-admin"}


def test_native_crash_reporter_posts_local_crash_route(monkeypatch: pytest.MonkeyPatch) -> None:
    import localflight.native.app as native_app

    posts: list[tuple[str, dict[str, object]]] = []

    class _Client:
        def __init__(self, *, base_url: str, timeout_s: float = 10.0) -> None:
            assert base_url == "http://127.0.0.1:8000"
            assert timeout_s == 6.0

        def get_json(self, path: str) -> dict[str, object]:
            assert path == "/api/config"
            return {"source": "virtual", "airport_iata": "ZRH"}

        def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
            posts.append((path, payload))
            return {"ok": True, "team": "desktop"}

    monkeypatch.setattr(native_app, "LocalApiClient", _Client)
    monkeypatch.setattr(native_app, "_app_version", lambda: "test-version")
    reporter = native_app._NativeCrashReporter(
        "http://127.0.0.1:8000",
        screen_provider=lambda: "radar",
    )

    try:
        raise RuntimeError("native boom")
    except RuntimeError:
        reporter.report_exception(*sys.exc_info(), sync=True)

    assert posts
    path, payload = posts[0]
    assert path == "/api/feedback/crash"
    assert payload["context"] == "native/gui"
    assert "RuntimeError: native boom" in str(payload["message"])
    assert "native/gui" in str(payload["client_context"])
    assert "screen=radar" in str(payload["client_context"])
    assert "source=virtual" in str(payload["client_context"])


def test_local_api_client_accepts_list_fids_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests
    from localflight.native.api_client import LocalApiClient

    class _Response:
        status_code = 200
        text = "[]"

        def json(self) -> list[dict[str, str]]:
            return [{"flight_display": "LX 1"}]

    monkeypatch.setattr(requests.Session, "get", lambda *args, **kwargs: _Response())

    payload = LocalApiClient().get_any_json("/api/fids")

    assert isinstance(payload, list)
    assert payload[0]["flight_display"] == "LX 1"


def test_local_api_client_identifies_native_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests
    import localflight.storage.install as install
    from localflight.native.api_client import LocalApiClient

    class _Response:
        status_code = 200
        text = "{}"

        def json(self) -> dict[str, bool]:
            return {"ok": True}

    seen: dict[str, str] = {}

    def fake_get(self: requests.Session, *args: object, **kwargs: object) -> _Response:
        seen.update(self.headers)
        return _Response()

    monkeypatch.setattr(install, "get_install_id", lambda: "native-install-id")
    monkeypatch.setattr(requests.Session, "get", fake_get)

    LocalApiClient().get_json("/api/health")

    assert seen["X-LocalFlight-Client-Type"] == "native"
    assert seen["X-LocalFlight-Companion-Id"] == "native-install-id"
    assert seen["User-Agent"].startswith("LocalFlight Native/")


def test_local_api_client_reuses_short_get_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests
    from localflight.native.api_client import LocalApiClient

    calls = {"count": 0}

    class _Response:
        status_code = 200
        text = "{}"

        def json(self) -> dict[str, int]:
            calls["count"] += 1
            return {"count": calls["count"]}

    monkeypatch.setattr(requests.Session, "get", lambda *args, **kwargs: _Response())

    client = LocalApiClient()
    first = client.get_json("/api/config")
    second = client.get_json("/api/config")

    assert first == second
    assert calls["count"] == 1


def test_local_api_client_parallel_gets_do_not_serialize_on_cache_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    import time
    from concurrent.futures import ThreadPoolExecutor

    import requests
    from localflight.native.api_client import LocalApiClient

    active = {"current": 0, "max": 0}
    lock = __import__("threading").Lock()

    class _Response:
        status_code = 200
        text = "{}"

        def json(self) -> dict[str, bool]:
            return {"ok": True}

    def fake_get(*args, **kwargs) -> _Response:
        with lock:
            active["current"] += 1
            active["max"] = max(active["max"], active["current"])
        time.sleep(0.08)
        with lock:
            active["current"] -= 1
        return _Response()

    monkeypatch.setattr(requests.Session, "get", fake_get)
    client = LocalApiClient(timeout_s=1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda path: client.get_any_json(path), ["/uncached-a", "/uncached-b"]))

    assert active["max"] == 2
