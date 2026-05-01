from __future__ import annotations

from pathlib import Path
import types

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import relay.main as relay_main


def _use_temp_db(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "relay.db"))
    relay_main._ensure_schema()


def _shared_snapshot_payload(*, pages_fetched: int = 4) -> dict[str, object]:
    return {
        "generated_at": relay_main._utc_now(),
        "provider": "aviationstack",
        "meta": {
            "pages_fetched": pages_fetched,
            "dates_touched": ["2026-05-01"],
            "raw_rows": 1,
            "planner_version": "fair-v1",
        },
        "records": [
            {
                "callsign": "SWR100",
                "direction": "DEP",
                "status": "scheduled",
                "scheduled": "2026-05-01T10:00:00+00:00",
                "estimated": "2026-05-01T10:00:00+00:00",
                "actual": None,
                "airline_name": "Swiss",
                "airline_iata": "LX",
                "airline_icao": "SWR",
                "flight_number": "LX100",
                "origin_iata": "ZRH",
                "origin_icao": "LSZH",
                "destination_iata": "JFK",
                "destination_icao": "KJFK",
                "aircraft_type": "A333",
                "gate": "E45",
                "stand": None,
                "terminal": "1",
                "delay_minutes": 0,
            }
        ],
    }


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
            "app_version": "0.2.5b3",
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
            "app_version": "0.2.5b3",
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
            "app_version": "0.2.5b3",
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


def test_relay_flights_forwards_page_params_and_counts_one_raw_call(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ALLOW_RAW_PROVIDER_DEBUG", "1")
    client = TestClient(relay_main.app)

    captured: dict[str, object] = {}
    increments: list[dict[str, object]] = []
    logs: list[dict[str, object]] = []

    monkeypatch.setattr(
        relay_main,
        "_resolve_access",
        lambda **kwargs: {"subject_key": "install:test", "limit": 50, "plan": "community"},
    )
    monkeypatch.setattr(relay_main, "_get_usage", lambda *args, **kwargs: 0)
    monkeypatch.setattr(relay_main, "_aviationstack_key", lambda: "relay-key-123")

    def fake_get(url, *, params, headers, timeout):
        captured["url"] = url
        captured["params"] = dict(params)
        captured["headers"] = dict(headers)
        captured["timeout"] = timeout
        return types.SimpleNamespace(status_code=200, content=b'{"data":[]}')

    monkeypatch.setattr(relay_main._req, "get", fake_get)
    monkeypatch.setattr(
        relay_main,
        "_increment_usage",
        lambda **kwargs: increments.append(dict(kwargs)) or 1,
    )
    monkeypatch.setattr(
        relay_main,
        "_log_request",
        lambda **kwargs: logs.append(dict(kwargs)),
    )

    response = client.get(
        "/v1/flights",
        params={
            "dep_iata": "zrh",
            "limit": 100,
            "flight_date": "2026-05-01",
            "offset": 200,
            "install_id": "00000000-0000-0000-0000-000000000321",
        },
    )

    assert response.status_code == 200
    assert captured["url"] == relay_main.AVIATIONSTACK_URL
    assert captured["params"] == {
        "access_key": "relay-key-123",
        "limit": 100,
        "flight_date": "2026-05-01",
        "offset": 200,
        "dep_iata": "ZRH",
    }
    assert captured["timeout"] == 25
    assert len(increments) == 1
    assert increments[0]["service"] == "aviationstack"
    assert increments[0]["plan"] == "community"
    assert len(logs) == 1
    assert logs[0]["scope"] == "departures"


def test_raw_provider_debug_route_stays_hidden_on_public_surface(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ALLOW_RAW_PROVIDER_DEBUG", "1")
    client = TestClient(relay_main.app)

    response = client.get(
        "/v1/flights",
        params={
            "dep_iata": "ZRH",
            "install_id": "00000000-0000-0000-0000-000000000321",
        },
        headers={"host": "relay.localflight.app"},
    )

    assert response.status_code == 404


def test_shared_schedule_route_coalesces_repeated_accesses_and_counts_upstream_separately(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)
    upstream_calls: list[dict[str, object]] = []

    def fake_shared_fetch(**kwargs):
        upstream_calls.append(dict(kwargs))
        return _shared_snapshot_payload(pages_fetched=8)

    monkeypatch.setattr(relay_main, "_fetch_shared_schedule_from_upstream", fake_shared_fetch)

    first = client.get(
        "/v1/schedule",
        params={
            "airport_iata": "ZRH",
            "timezone": "Europe/Zurich",
            "display_grace_minutes": 30,
            "display_horizon_hours": 12,
            "refresh_seconds": 3600,
            "install_id": "00000000-0000-0000-0000-000000000401",
        },
    )
    assert first.status_code == 200
    assert first.json()["cache_state"] == "miss"

    for _ in range(19):
        response = client.get(
            "/v1/schedule",
            params={
                "airport_iata": "ZRH",
                "timezone": "Europe/Zurich",
                "display_grace_minutes": 30,
                "display_horizon_hours": 12,
                "refresh_seconds": 3600,
                "install_id": "00000000-0000-0000-0000-000000000401",
            },
        )
        assert response.status_code == 200
        assert response.json()["cache_state"] == "fresh"

    assert len(upstream_calls) == 1

    conn = relay_main._connect()
    access_row = conn.execute(
        "SELECT calls FROM usage WHERE service='aviationstack' ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    upstream_row = conn.execute(
        "SELECT calls FROM usage WHERE service='aviationstack_upstream' ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    snapshot_row = conn.execute(
        "SELECT client_accesses, refresh_count, cache_hits, upstream_pulls FROM schedule_snapshots"
    ).fetchone()
    conn.close()

    assert access_row is not None and int(access_row["calls"] or 0) == 20
    assert upstream_row is not None and int(upstream_row["calls"] or 0) == 8
    assert snapshot_row is not None
    assert int(snapshot_row["client_accesses"] or 0) == 20
    assert int(snapshot_row["refresh_count"] or 0) == 1
    assert int(snapshot_row["cache_hits"] or 0) == 19
    assert int(snapshot_row["upstream_pulls"] or 0) == 8


def test_shared_schedule_cache_key_changes_with_window_settings(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)
    upstream_calls: list[dict[str, object]] = []

    def fake_shared_fetch(**kwargs):
        upstream_calls.append(dict(kwargs))
        return _shared_snapshot_payload(pages_fetched=2)

    monkeypatch.setattr(relay_main, "_fetch_shared_schedule_from_upstream", fake_shared_fetch)

    base_params = {
        "airport_iata": "ZRH",
        "timezone": "Europe/Zurich",
        "display_grace_minutes": 30,
        "refresh_seconds": 3600,
        "install_id": "00000000-0000-0000-0000-000000000402",
    }
    response_a = client.get("/v1/schedule", params={**base_params, "display_horizon_hours": 12})
    response_b = client.get("/v1/schedule", params={**base_params, "display_horizon_hours": 18})

    assert response_a.status_code == 200
    assert response_b.status_code == 200
    assert len(upstream_calls) == 2

    conn = relay_main._connect()
    count = conn.execute("SELECT COUNT(*) AS n FROM schedule_snapshots").fetchone()
    conn.close()
    assert count is not None
    assert int(count["n"] or 0) == 2


def test_shared_schedule_serves_stale_snapshot_when_refresh_fails(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)

    monkeypatch.setattr(relay_main, "_fetch_shared_schedule_from_upstream", lambda **kwargs: _shared_snapshot_payload())
    seed = client.get(
        "/v1/schedule",
        params={
            "airport_iata": "ZRH",
            "timezone": "Europe/Zurich",
            "display_grace_minutes": 30,
            "display_horizon_hours": 12,
            "refresh_seconds": 3600,
            "install_id": "00000000-0000-0000-0000-000000000403",
        },
    )
    assert seed.status_code == 200

    conn = relay_main._connect()
    stale_at = (relay_main.datetime.now(relay_main.timezone.utc) - relay_main.timedelta(minutes=30)).isoformat()
    conn.execute(
        "UPDATE schedule_snapshots SET generated_at=?, updated_at=?",
        (stale_at, relay_main._utc_now()),
    )
    conn.commit()
    conn.close()

    def fail_refresh(**kwargs):
        raise HTTPException(status_code=502, detail="upstream down")

    monkeypatch.setattr(relay_main, "_fetch_shared_schedule_from_upstream", fail_refresh)
    stale = client.get(
        "/v1/schedule",
        params={
            "airport_iata": "ZRH",
            "timezone": "Europe/Zurich",
            "display_grace_minutes": 30,
            "display_horizon_hours": 12,
            "refresh_seconds": 3600,
            "install_id": "00000000-0000-0000-0000-000000000403",
        },
    )

    assert stale.status_code == 200
    payload = stale.json()
    assert payload["cache_state"] == "stale"
    assert payload["meta"]["last_error"] == "upstream down"


def test_shared_schedule_returns_error_when_no_snapshot_exists_and_upstream_fails(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)

    def fail_refresh(**kwargs):
        raise HTTPException(status_code=502, detail="upstream down")

    monkeypatch.setattr(relay_main, "_fetch_shared_schedule_from_upstream", fail_refresh)
    response = client.get(
        "/v1/schedule",
        params={
            "airport_iata": "ZRH",
            "timezone": "Europe/Zurich",
            "display_grace_minutes": 30,
            "display_horizon_hours": 12,
            "refresh_seconds": 3600,
            "install_id": "00000000-0000-0000-0000-000000000404",
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "upstream down"


def test_client_checkin_records_interest_and_exposes_schedule_cache(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)
    install_id = "00000000-0000-0000-0000-000000000405"

    monkeypatch.setattr(relay_main, "_fetch_shared_schedule_from_upstream", lambda **kwargs: _shared_snapshot_payload())
    schedule = client.get(
        "/v1/schedule",
        params={
            "airport_iata": "ZRH",
            "timezone": "Europe/Zurich",
            "display_grace_minutes": 30,
            "display_horizon_hours": 12,
            "refresh_seconds": 3600,
            "install_id": install_id,
        },
    )
    assert schedule.status_code == 200

    checkin = client.post(
        "/v1/client/checkin",
        json={
            "install_id": install_id,
            "airport_iata": "ZRH",
            "timezone": "Europe/Zurich",
            "display_grace_minutes": 30,
            "display_horizon_hours": 12,
            "refresh_seconds": 3600,
        },
    )
    assert checkin.status_code == 200

    status = client.get("/v1/client/status", params={"install_id": install_id})
    assert status.status_code == 200
    payload = status.json()
    assert payload["interest"]["airport_iata"] == "ZRH"
    assert payload["schedule_cache"]["provider"] == "aviationstack"
    assert payload["schedule_cache"]["meta"]["shared_stats"]["client_accesses"] >= 1
