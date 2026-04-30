from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import relay.main as relay_main


def _use_temp_db(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "relay.db"))
    relay_main._ensure_schema()


def test_relay_prefers_relay_stored_provider_key_over_env(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("AVIATIONSTACK_API_KEY", "env-key-123")

    conn = relay_main._connect()
    relay_main._setting_set_conn(conn, relay_main._SETTING_AVIATIONSTACK_KEY, "stored-key-456")
    conn.commit()
    conn.close()

    assert relay_main._aviationstack_key() == "stored-key-456"


def test_resolve_access_rejects_blocked_install(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    install_id = "00000000-0000-0000-0000-000000000123"

    conn = relay_main._connect()
    conn.execute(
        "INSERT INTO blocked_installs (install_id, reason, created_at) VALUES (?, ?, ?)",
        (install_id, "test block", relay_main._utc_now()),
    )
    conn.commit()
    conn.close()

    with pytest.raises(HTTPException) as excinfo:
        relay_main._resolve_access(
            install_id=install_id,
            activation_token="",
            service="aviationstack",
        )

    assert excinfo.value.status_code == 403
    assert "test block" in str(excinfo.value.detail)


def test_activate_auto_issues_and_client_status_verifies(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)

    install_id = "00000000-0000-0000-0000-000000000999"
    activate_resp = client.post(
        "/v1/activate",
        json={
            "install_id": install_id,
            "install_fingerprint": relay_main._install_fingerprint(install_id),
            "airport_iata": "ZRH",
            "airport_icao": "LSZH",
            "display_name": "Test kiosk",
            "requested_mode": "community",
            "app_version": "0.2.5b1",
        },
        headers={"x-forwarded-for": "203.0.113.42"},
    )
    assert activate_resp.status_code == 200
    activate_data = activate_resp.json()
    assert activate_data["status"] == "issued"
    assert activate_data["activation_token"].startswith("lfm_")
    assert activate_data["token_prefix"] == activate_data["activation_token"][:10]
    assert activate_data["plan"] == "managed"

    status_resp = client.get(
        "/v1/client/status",
        params={
            "install_id": install_id,
            "activation_token": activate_data["activation_token"],
            "app_version": "0.2.5b1",
        },
    )
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["plan"] == "managed"
    assert status_data["token_prefix"] == activate_data["token_prefix"]
    assert status_data["providers"]["aviationstack"] is False

    conn = relay_main._connect()
    request_row = conn.execute(
        "SELECT status, network_tag FROM activation_requests WHERE request_id=?",
        (activate_data["request_id"],),
    ).fetchone()
    conn.close()
    assert request_row is not None
    assert request_row["status"] == "issued"
    assert str(request_row["network_tag"]).startswith("net_")
    assert "203.0.113.42" not in str(request_row["network_tag"])


def test_activate_uses_manual_review_after_anonymous_network_burst(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setattr(relay_main, "_AUTO_ACTIVATION_NETWORK_DAILY_LIMIT", 2)
    monkeypatch.setattr(relay_main, "_AUTO_ACTIVATION_NETWORK_INSTALLS_DAILY_LIMIT", 2)
    client = TestClient(relay_main.app)

    def _activate(suffix: int) -> dict[str, object]:
        install_id = f"00000000-0000-0000-0000-0000000001{suffix:02d}"
        resp = client.post(
            "/v1/activate",
            json={
                "install_id": install_id,
                "install_fingerprint": relay_main._install_fingerprint(install_id),
                "airport_iata": "ZRH",
                "airport_icao": "LSZH",
                "display_name": f"Install {suffix}",
                "requested_mode": "community",
            },
            headers={"x-forwarded-for": "198.51.100.44"},
        )
        assert resp.status_code == 200
        return resp.json()

    first = _activate(1)
    second = _activate(2)
    third = _activate(3)

    assert first["status"] == "issued"
    assert second["status"] == "issued"
    assert third["status"] == "manual_review"
    assert "activation_token" not in third


def test_public_host_hides_admin_surface(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)

    response = client.get("/admin", headers={"host": "relay.localflight.app"})

    assert response.status_code == 404


def test_admin_host_hides_public_api_surface(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)

    response = client.get(
        "/v1/client/status",
        params={"install_id": "00000000-0000-0000-0000-000000000111"},
        headers={"host": "network.localflight.app"},
    )

    assert response.status_code == 404


def test_relay_root_switches_by_hostname(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)

    public_response = client.get("/", headers={"host": "relay.localflight.app"})
    assert public_response.status_code == 200
    public_payload = public_response.json()
    assert public_payload["public_host"] == "relay.localflight.app"
    assert public_payload["admin_host"] == "network.localflight.app"

    admin_response = client.get("/", headers={"host": "network.localflight.app"}, follow_redirects=False)
    assert admin_response.status_code == 307
    assert admin_response.headers["location"] == "/admin"


def test_activation_requests_do_not_persist_airport_fields(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)
    install_id = "00000000-0000-0000-0000-000000000777"

    response = client.post(
        "/v1/activate",
        json={
            "install_id": install_id,
            "install_fingerprint": relay_main._install_fingerprint(install_id),
            "airport_iata": "ZRH",
            "airport_icao": "LSZH",
            "display_name": "Privacy test",
            "requested_mode": "community",
            "app_version": "0.2.5b1",
        },
        headers={"host": "relay.localflight.app", "x-forwarded-for": "203.0.113.55"},
    )
    assert response.status_code == 200

    conn = relay_main._connect()
    row = conn.execute(
        "SELECT airport_iata, airport_icao, display_name FROM activation_requests WHERE install_id=?",
        (install_id,),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["airport_iata"] is None
    assert row["airport_icao"] is None
    assert row["display_name"] == "Privacy test"


def test_relay_request_log_uses_scope_without_airport_data(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)

    relay_main._log_request(
        install_id="00000000-0000-0000-0000-000000000555",
        scope="departures",
        status=200,
        latency_ms=123,
        service="aviationstack",
        plan="community",
    )

    conn = relay_main._connect()
    row = conn.execute("SELECT airport, mode, service FROM request_log ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()

    assert row is not None
    assert row["airport"] is None
    assert row["mode"] == "departures"
    assert row["service"] == "aviationstack"
