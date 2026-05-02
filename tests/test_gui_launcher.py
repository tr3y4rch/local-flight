from __future__ import annotations

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
    assert window.stack.count() == 10


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
    assert setup.tabs.count() == 4
    assert setup.relay_url.text() == "https://localflight-community-relay.fly.dev"
    assert setup.finish_btn.isVisible() is False
    assert matrix.canvas is not None
    assert matrix.script_preview.isReadOnly()
    assert logs.file_combo is not None
    assert logs.live_tail.text() == "Live tail"
    assert requests.client_type.currentText() == "all clients"
    assert feedback.sysinfo.isReadOnly()


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
    assert client.payload["relay_url"] == ""
    assert client.payload["aviationstack_key"] == ""


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
            "pilot_name": "Should Not Render",
            "cid": 12345,
        }
    )

    assert app is not None
    assert "SWR123" in tooltip
    assert "LSZH -> KJFK" in tooltip
    assert "10000 ft" in tooltip
    assert "250 kt" in tooltip
    assert "Should Not Render" not in tooltip
    assert "12345" not in tooltip


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

    assert app is not None
    assert "Virtual flight" in text
    assert "Flight plan" in text
    assert "DCT TEST" in text
    assert "Private Person" not in text
    assert "123456" not in text


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
    assert screen.advanced_display_group.isChecked() is False
    assert screen.advanced_display_body.isVisible() is False


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
        "Raw",
    ]


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


def test_native_route_registry_is_labelled_and_owned() -> None:
    from localflight.native.routes import CLIENT_ROUTES, NETWORK_ADMIN_ROUTES

    routes = CLIENT_ROUTES + NETWORK_ADMIN_ROUTES

    assert routes
    assert all(route.action_id and route.label and route.method and route.path and route.owner for route in routes)
    assert all(route.method in {"GET", "POST", "PATCH"} for route in routes)
    assert len({route.action_id for route in routes}) == len(routes)
    assert {route.surface for route in routes} == {"client", "network-admin"}


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
