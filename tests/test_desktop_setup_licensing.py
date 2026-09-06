from __future__ import annotations

import asyncio
import json
import os
import stat
import types
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient
from starlette.requests import Request

import localflight.storage.config as storage_config
import localflight.storage.install as storage_install
import localflight.storage.provider_keys as provider_keys
import localflight.ui.server as ui_server
from localflight.ui.server import app


@pytest.fixture
def desktop_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    config_file = tmp_path / ".localflight" / "config.json"
    env_file = config_file.parent / ".env"
    config_file.parent.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("LOCALFLIGHT_HOME", str(tmp_path))
    monkeypatch.delenv("LOCALFLIGHT_ACTIVATION_TOKEN", raising=False)
    monkeypatch.setattr(storage_config, "config_path", lambda: config_file)
    monkeypatch.setattr(provider_keys, "env_path", lambda: env_file)
    monkeypatch.setattr(ui_server, "provider_env_path", lambda: env_file)
    # A packaged install keeps its provider file beside config. This makes the
    # legacy migration deterministic instead of consulting the checkout .env.
    monkeypatch.setattr(storage_config.sys, "frozen", True, raising=False)
    monkeypatch.setattr("localflight.ui.events.notify_config_updated", lambda *args, **kwargs: None)
    monkeypatch.setattr("localflight.ui.events.restart_scheduler_and_notify", lambda *args, **kwargs: None)
    monkeypatch.setattr("localflight.sources.web.relay_beat.fire_heartbeat", lambda: None)
    return config_file, env_file


@pytest.mark.parametrize(
    ("source", "env_text", "credential", "expected"),
    [
        ("virtual", "", "", "vatsim"),
        ("real", "AERODATABOX_API_KEY=direct-key\nLOCALFLIGHT_AERODATABOX_ENABLED=1\n", "", "byok"),
        ("real", "", "lfr_existing_device", "relay"),
        ("real", "", "", "relay"),
    ],
)
def test_data_route_migrates_from_legacy_configuration(
    desktop_home: tuple[Path, Path], source: str, env_text: str, credential: str, expected: str
) -> None:
    config_file, env_file = desktop_home
    config_file.write_text(json.dumps({"source": source}), encoding="utf-8")
    if env_text:
        env_file.write_text(env_text, encoding="utf-8")
    if credential:
        (config_file.parent / "activation_token").write_text(credential, encoding="utf-8")

    cfg = storage_config.load_config()

    assert cfg.data_route == expected
    assert cfg.source == ("virtual" if expected == "vatsim" else "real")
    assert json.loads(config_file.read_text(encoding="utf-8"))["data_route"] == expected


def test_legacy_env_credential_migrates_to_one_private_file(
    desktop_home: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file, env_file = desktop_home
    env_file.write_text(
        "LOCALFLIGHT_ACTIVATION_TOKEN=lfr_legacy_device_secret\nLOCALFLIGHT_RELAY_URL=https://relay.beacontools.cc\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCALFLIGHT_ACTIVATION_TOKEN", "lfr_legacy_device_secret")

    assert storage_install.get_stored_activation_token() == "lfr_legacy_device_secret"

    credential_file = config_file.parent / "activation_token"
    assert credential_file.read_text(encoding="utf-8") == "lfr_legacy_device_secret"
    assert stat.S_IMODE(credential_file.stat().st_mode) == 0o600
    assert "LOCALFLIGHT_ACTIVATION_TOKEN" not in provider_keys.read_env(env_file)
    assert "LOCALFLIGHT_ACTIVATION_TOKEN" not in os.environ


def test_release_pending_credential_cannot_power_runtime(desktop_home: tuple[Path, Path]) -> None:
    storage_install.set_activation_token("lfr_pending_device")
    storage_install.update_relay_access_summary(relay_state="release_pending", reason_code="relay_unreachable")

    assert storage_install.get_stored_activation_token() == "lfr_pending_device"
    assert storage_install.get_activation_token() == ""
    assert storage_install.get_relay_access_summary()["relay_state"] == "release_pending"


def test_client_info_is_hydrated_and_contains_only_safe_access_summary(
    desktop_home: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file, _env_file = desktop_home
    storage_config.save_config(
        storage_config.AppConfig(
            airport_iata="HKG",
            airport_icao="VHHH",
            timezone="Asia/Hong_Kong",
            display_name="Hong Kong Board",
            data_route="relay",
        )
    )
    storage_install.set_activation_token("lfr_super_secret_device_credential")
    storage_install.update_relay_access_summary(
        relay_state="active",
        access_state="active",
        license_reference="lic_safe_ref",
        masked_key_reference="LFRA-••••-ABCD",
        purchase_source="stripe",
        current_main_device_description="Hong Kong Board",
    )

    payload = ui_server.setup_client_info()
    dumped = json.dumps(payload, ensure_ascii=False)

    assert payload["config"]["data_route"] == "relay"
    assert payload["config"]["airport_iata"] == "HKG"
    assert payload["relay_state"] == "active"
    assert payload["masked_key_reference"] == "LFRA-••••-ABCD"
    assert payload["current_main_device_description"] == "Hong Kong Board"
    assert "lfr_super_secret_device_credential" not in dumped
    assert "LFRA-••••-ABCD" in dumped
    assert config_file.exists()


def test_activation_exchanges_and_discards_raw_key(
    desktop_home: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file, env_file = desktop_home
    raw_key = "LFRA-AAAA-BBBB-CCCC-DDDD-EEEE-FFFF-G"

    class Response:
        status_code = 200
        headers: dict[str, str] = {}

        def __init__(self, *, committed: bool) -> None:
            self.committed = committed

        def json(self) -> dict[str, object]:
            return {
                "ok": True,
                "activated": self.committed,
                "activation_state": "active" if self.committed else "pending_commit",
                "credential": "lfr_device_credential_secret",
                "credential_prefix": "lfr_device_c",
                "license": {
                    "access_state": "active",
                    "reason_code": "",
                    "license_ref": "lic_123",
                    "key_ref": "LFRA-••••-FFFF-G",
                    "purchase_source": "stripe",
                },
                "receiver": {"device_kind": "desktop", "device_name": "My Desktop"},
            }

    monkeypatch.setattr(
        requests,
        "post",
        lambda url, *_args, **_kwargs: Response(committed=str(url).endswith("/commit")),
    )
    result = asyncio.run(
        ui_server.setup_activate(
            ui_server.ActivationSetupIn(
                relay_url="https://relay.beacontools.cc",
                requested_mode="relay",
                display_name="My Desktop",
                license_key=raw_key,
            )
        )
    )

    assert result["ok"] is True
    assert storage_install.get_activation_token() == "lfr_device_credential_secret"
    assert raw_key not in (config_file.parent / "activation_token").read_text(encoding="utf-8")
    assert raw_key not in env_file.read_text(encoding="utf-8") if env_file.exists() else True
    for path in config_file.parent.rglob("*"):
        if path.is_file():
            assert raw_key not in path.read_text(encoding="utf-8")


def test_lan_setup_rejects_master_key_before_network_call(
    desktop_home: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(requests, "post", lambda *_args, **_kwargs: pytest.fail("must not call relay"))
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/setup/activate",
            "raw_path": b"/api/setup/activate",
            "query_string": b"",
            "headers": [],
            "client": ("192.168.1.20", 43210),
            "server": ("192.168.1.2", 4000),
        }
    )

    result = asyncio.run(
        ui_server.setup_activate(
            ui_server.ActivationSetupIn(
                requested_mode="relay",
                relay_url="https://relay.beacontools.cc",
                license_key="LFRA-AAAA-BBBB-CCCC-DDDD",
            ),
            request,
        )
    )

    assert result["status"] == "license_key_local_only"


def test_structured_relay_error_and_retry_after_are_preserved(
    desktop_home: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    class Response:
        status_code = 429
        headers = {"Retry-After": "17"}

        @staticmethod
        def json() -> dict[str, object]:
            return {"detail": {"code": "access_rate_limited", "message": "opaque", "reason_code": "burst"}}

    monkeypatch.setattr(requests, "post", lambda *_args, **_kwargs: Response())
    result = asyncio.run(
        ui_server.setup_activate(
            ui_server.ActivationSetupIn(
                requested_mode="relay",
                relay_url="https://relay.beacontools.cc",
                license_key="LFRA-AAAA-BBBB-CCCC-DDDD",
            )
        )
    )

    assert result["status"] == "rate_limited"
    assert result["retry_after_s"] == 17
    assert result["reason_code"] == "burst"
    assert "opaque" not in result["error"]


def test_free_routes_never_call_access_api_without_credential(
    desktop_home: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(requests, "post", lambda *_args, **_kwargs: pytest.fail("free route called access API"))

    response = TestClient(app).post(
        "/api/setup/complete",
        json={
            "data_route": "vatsim",
            "source": "virtual",
            "airport_iata": "ZRH",
            "airport_icao": "LSZH",
            "timezone": "Europe/Zurich",
        },
    )

    assert response.status_code == 200
    assert response.json()["data_route"] == "vatsim"
    assert storage_config.load_config().data_route == "vatsim"


def test_switching_to_free_route_retains_credential_as_release_pending_when_offline(
    desktop_home: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    storage_install.set_activation_token("lfr_active_device")
    storage_install.update_relay_access_summary(relay_state="active", access_state="active")
    monkeypatch.setattr(requests, "post", lambda *_args, **_kwargs: (_ for _ in ()).throw(requests.ConnectionError()))

    response = TestClient(app).post(
        "/api/setup/complete",
        json={
            "data_route": "vatsim",
            "source": "virtual",
            "airport_iata": "ZRH",
            "airport_icao": "LSZH",
            "timezone": "Europe/Zurich",
        },
    )

    assert response.status_code == 200
    assert response.json()["release_pending"] is True
    assert storage_config.load_config().data_route == "vatsim"
    assert storage_install.get_stored_activation_token() == "lfr_active_device"
    assert storage_install.get_activation_token() == ""


def test_background_retry_releases_pending_access_only_on_a_free_route(
    desktop_home: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    storage_config.save_config(storage_config.AppConfig(data_route="vatsim"))
    storage_install.set_activation_token("lfr_pending_device")
    storage_install.update_relay_access_summary(relay_state="release_pending")
    monkeypatch.setattr(
        ui_server,
        "_deactivate_local_relay",
        lambda relay_url: calls.append(relay_url) or {"ok": True, "status": "inactive"},
    )

    assert asyncio.run(ui_server._retry_pending_relay_release_once()) is True
    assert calls == [ui_server._relay_url_default()]

    calls.clear()
    storage_config.save_config(storage_config.AppConfig(data_route="relay"))
    assert asyncio.run(ui_server._retry_pending_relay_release_once()) is False
    assert calls == []


def test_native_qt_wizard_preserves_routes_and_named_move_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets

    from localflight.native.pages.setup import SetupScreen
    from localflight.native.qt_compat import import_qt

    QtCore, QtGui, _QtWidgets = import_qt()
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setattr(SetupScreen, "refresh", lambda self: None)
    screen = SetupScreen(
        QtCore,
        QtWidgets,
        object(),
        "http://127.0.0.1:4000",
        QtGui=QtGui,
    )

    assert list(screen.source_buttons) == ["relay", "byok", "vatsim"]
    assert [screen.source_buttons[key].accessibleName() for key in screen.source_buttons] == [
        "Beacon Relay",
        "Bring Your Own Keys",
        "VATSIM",
    ]
    assert screen.buy_relay_access_btn.text() == "Get Relay Access"
    assert screen.move_relay_here_btn.text() == "Move to this desktop"
    assert screen.keep_relay_there_btn.text() == "Keep it there"

    screen.activation_token.setText("LFRA-AAAA-BBBB-CCCC-DDDD")
    screen._apply_activation_result(
        {
            "ok": False,
            "status": "seat_in_use",
            "move_token": "move_once_123",
            "current_receiver": {"device_name": "Kitchen board"},
        }
    )
    assert screen._pending_move_token == "move_once_123"
    assert "Kitchen board" in screen.move_warning_text.text()
    screen.activation_token.setText("LFRA-AAAA-BBBB-CCCC-EEEE")
    assert screen._pending_move_token == ""
    assert screen.move_warning.isHidden()


def test_browser_wizard_keeps_three_routes_and_named_move_confirmation() -> None:
    html = Path("src/localflight/ui/templates/setup.html").read_text(encoding="utf-8")
    guidance = Path("src/localflight/ui/setup_guidance.py").read_text(encoding="utf-8")

    assert '"mode": "relay"' in guidance
    assert '"mode": "byok"' in guidance
    assert '"mode": "vatsim"' in guidance
    assert "Get Relay Access" in html
    assert "Keep it there" in html
    assert "Move to this desktop" in html
    assert 'role="radiogroup"' in html
    assert 'role="radio"' in html
    assert "focus-visible" in html
    assert "Community" not in html
    assert "Managed" not in html


def test_compat_activation_endpoint_keeps_lfra_loopback_boundary(
    desktop_home: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(requests, "post", lambda *_args, **_kwargs: pytest.fail("must not contact relay"))

    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/setup/request-activation",
            "raw_path": b"/api/setup/request-activation",
            "query_string": b"",
            "headers": [],
            "client": ("192.168.1.20", 43210),
            "server": ("192.168.1.2", 4000),
        }
    )
    result = asyncio.run(
        ui_server.setup_request_activation_compat(
            ui_server.ActivationSetupIn(
                requested_mode="relay",
                relay_url="https://relay.beacontools.cc",
                license_key="LFRA-AAAA-BBBB-CCCC-DDDD",
            ),
            request,
        )
    )

    assert result["status"] == "license_key_local_only"


def test_data_route_is_authoritative_over_stale_relay_credential(
    desktop_home: tuple[Path, Path],
) -> None:
    storage_install.set_activation_token("lfr_stale_but_valid_shape")
    storage_install.update_relay_access_summary(relay_state="active", access_state="active")
    storage_config.save_config(storage_config.AppConfig(data_route="byok"))

    assert storage_install.get_stored_activation_token() == "lfr_stale_but_valid_shape"
    assert storage_install.get_activation_token() == ""

    storage_config.save_config(storage_config.AppConfig(data_route="relay"))
    assert storage_install.get_activation_token() == "lfr_stale_but_valid_shape"


def test_lfra_status_failure_never_calls_legacy_activation_or_overwrites_credential(
    desktop_home: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from localflight.sources.web import relay_activation

    storage_config.save_config(storage_config.AppConfig(data_route="relay"))
    storage_install.set_activation_token("lfr_original_device_credential")
    relay_activation.reset_auto_repair_state()
    calls: list[str] = []

    class Response:
        status_code = 403
        headers: dict[str, str] = {}

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "detail": {
                    "code": "license_inactive",
                    "access_state": "revoked",
                    "reason_code": "purchase_revoked",
                }
            }

    monkeypatch.setattr(relay_activation.requests, "get", lambda *_args, **_kwargs: calls.append("status") or Response())
    monkeypatch.setattr(relay_activation.requests, "post", lambda *_args, **_kwargs: pytest.fail("must not repair LFRA"))

    result = relay_activation.ensure_relay_link(requested_mode="relay", force=True)

    assert result["linked"] is False
    assert result["status"] == "license_inactive"
    assert calls == ["status"]
    assert storage_install.get_stored_activation_token() == "lfr_original_device_credential"


def test_access_status_fails_closed_on_malformed_success(
    desktop_home: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    storage_config.save_config(storage_config.AppConfig(data_route="relay"))
    storage_install.set_activation_token("lfr_device_credential")
    storage_install.update_relay_access_summary(relay_state="active", access_state="active")

    class Response:
        status_code = 200
        headers: dict[str, str] = {}

        @staticmethod
        def json() -> dict[str, object]:
            return {"ok": True}

    monkeypatch.setattr(requests, "get", lambda *_args, **_kwargs: Response())
    result = asyncio.run(
        ui_server.setup_client_status(
            ui_server.ClientStatusSetupIn(relay_url="https://relay.beacontools.cc")
        )
    )

    assert result["ok"] is False
    assert result["status"] == "invalid_status_response"
    summary = storage_install.get_relay_access_summary()
    assert summary["relay_state"] == "inactive"
    assert summary["access_state"] == ""


def test_activation_storage_preflight_happens_before_exchange(
    desktop_home: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(storage_install, "activation_storage_ready", lambda: False)
    monkeypatch.setattr(requests, "post", lambda *_args, **_kwargs: pytest.fail("must not consume activation"))

    result = asyncio.run(
        ui_server.setup_activate(
            ui_server.ActivationSetupIn(
                requested_mode="relay",
                relay_url="https://relay.beacontools.cc",
                license_key="LFRA-AAAA-BBBB-CCCC-DDDD",
            )
        )
    )

    assert result["status"] == "credential_storage_unavailable"


def test_activation_compensates_if_credential_cannot_be_committed(
    desktop_home: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    class Response:
        status_code = 200
        headers: dict[str, str] = {}

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "ok": True,
                "activated": False,
                "activation_state": "pending_commit",
                "credential": "lfr_new_device_credential",
                "license": {"access_state": "active"},
            }

    def post(url: str, *_args: object, **_kwargs: object) -> Response:
        calls.append(url)
        return Response()

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(storage_install, "activation_storage_ready", lambda: True)
    monkeypatch.setattr(storage_install, "set_activation_token", lambda _token: (_ for _ in ()).throw(OSError("disk full")))

    result = asyncio.run(
        ui_server.setup_activate(
            ui_server.ActivationSetupIn(
                requested_mode="relay",
                relay_url="https://relay.beacontools.cc",
                license_key="LFRA-AAAA-BBBB-CCCC-DDDD",
            )
        )
    )

    assert result["status"] == "credential_storage_failed"
    assert calls[0].endswith("/v1/access/activate")
    assert calls[1].endswith("/v1/access/deactivate")
    assert storage_install.get_stored_activation_token() == ""


def test_release_pending_honors_retry_after_without_reusing_credential(
    desktop_home: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    storage_config.save_config(storage_config.AppConfig(data_route="vatsim"))
    storage_install.set_activation_token("lfr_pending_device")

    class Response:
        status_code = 429
        headers = {"Retry-After": "17"}

        @staticmethod
        def json() -> dict[str, object]:
            return {"detail": {"code": "access_rate_limited"}}

    monkeypatch.setattr(requests, "post", lambda *_args, **_kwargs: Response())
    result = ui_server._deactivate_local_relay("https://relay.beacontools.cc")
    access = storage_install.get_relay_access_summary()

    assert result["status"] == "release_pending"
    assert access["release_retry_after_s"] == 17
    assert access["release_retry_not_before"]
    assert storage_install.get_activation_token() == ""
    monkeypatch.setattr(ui_server, "_deactivate_local_relay", lambda _url: pytest.fail("retry ran too early"))
    assert asyncio.run(ui_server._retry_pending_relay_release_once()) is False


def test_interrupted_free_route_transition_recovers_fail_closed(
    desktop_home: tuple[Path, Path],
) -> None:
    from localflight.storage.route_transition import (
        begin_route_transition,
        load_route_transition,
        update_route_transition,
    )

    storage_config.save_config(storage_config.AppConfig(data_route="relay"))
    storage_install.set_activation_token("lfr_active_device")
    storage_install.update_relay_access_summary(relay_state="active", access_state="active")
    begin_route_transition("relay", "vatsim")
    update_route_transition("provider_saved")

    ui_server._recover_data_route_transition()

    assert storage_config.load_config().data_route == "vatsim"
    assert storage_install.get_relay_access_summary()["relay_state"] == "release_pending"
    assert storage_install.get_activation_token() == ""
    assert load_route_transition() == {}


def test_browser_requires_fresh_verification_and_reveals_recovery_field() -> None:
    html = Path("src/localflight/ui/templates/setup.html").read_text(encoding="utf-8")

    assert 'mode() === "relay" && !managedVerified)' in html
    assert 'managedVerified ? "Active on this desktop" : "License activation required"' in html
    assert 'el("activationToken").dataset.prefix = ""' in html
    assert 'el("activationTokenField").style.display = "block"' in html
