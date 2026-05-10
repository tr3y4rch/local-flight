from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import types

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import relay.main as relay_main
from localflight.sources.web.airport_surface import build_surface_payload


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
            "planner_version": relay_main._SHARED_SCHEDULE_PLANNER_VERSION,
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


def _surface_snapshot_payload() -> dict[str, object]:
    return build_surface_payload(
        airport_iata="ZRH",
        airport_icao="LSZH",
        center_lat=47.45,
        center_lon=8.55,
        radius_nm=20,
        cache_state="fresh",
        features=[
            {
                "kind": "runway",
                "id": "way:1",
                "label": "16/34",
                "closed": False,
                "points": [[47.45, 8.55], [47.46, 8.56]],
            }
        ],
        meta={"test": True},
    )


def _aviationstack_departure(number: str, scheduled: datetime) -> dict[str, object]:
    stamp = scheduled.astimezone(timezone.utc).isoformat()
    return {
        "flight_date": stamp[:10],
        "flight_status": "scheduled",
        "departure": {
            "iata": "ZRH",
            "icao": "LSZH",
            "scheduled": stamp,
            "estimated": stamp,
            "actual": None,
            "gate": "A1",
            "terminal": "1",
        },
        "arrival": {
            "iata": "LHR",
            "icao": "EGLL",
            "scheduled": stamp,
            "estimated": stamp,
            "actual": None,
            "gate": None,
            "terminal": None,
        },
        "airline": {"name": "Swiss", "iata": "LX", "icao": "SWR"},
        "flight": {"number": number, "iata": f"LX{number}", "icao": f"SWR{number}"},
        "aircraft": {"icao": "A320", "iata": "320"},
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
            "app_version": "0.2.5",
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
            "app_version": "0.2.5",
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


def test_auto_activation_network_burst_limits_can_be_overridden_by_env(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_AUTO_ACTIVATION_NETWORK_DAILY_LIMIT", "1")
    monkeypatch.setenv("RELAY_AUTO_ACTIVATION_NETWORK_INSTALLS_DAILY_LIMIT", "99")
    client = TestClient(relay_main.app)

    def _activate(suffix: int) -> dict[str, object]:
        install_id = f"00000000-0000-0000-0000-0000000002{suffix:02d}"
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
            headers={"x-forwarded-for": "198.51.100.45"},
        )
        assert resp.status_code == 200
        return resp.json()

    first = _activate(1)
    second = _activate(2)

    assert first["status"] == "issued"
    assert second["status"] == "manual_review"


def test_admin_dashboard_handles_live_lane_without_snapshot(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ADMIN_PASSWORD", "correct-horse")
    conn = relay_main._connect()
    conn.execute(
        """
        INSERT INTO client_interests (
            install_id, plan, airport_iata, timezone,
            display_grace_minutes, display_horizon_hours, refresh_seconds, last_seen
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "00000000-0000-0000-0000-000000000404",
            "community",
            "ZRH",
            "Europe/Zurich",
            30,
            12,
            3600,
            relay_main._utc_now(),
        ),
    )
    conn.commit()
    conn.close()
    client = TestClient(relay_main.app)

    admin = client.get("/admin", headers={"host": "network.localflight.app"}, auth=("admin", "correct-horse"))
    schedules = client.get("/admin/api/schedules", headers={"host": "network.localflight.app"}, auth=("admin", "correct-horse")).json()

    assert admin.status_code == 200
    assert "Lazy, query-driven admin console" in admin.text
    assert any(row["airport_iata"] == "ZRH" for row in schedules["client_interests"])
    assert schedules["filtered_estimate"] == 0


def test_admin_clean_trial_state_keeps_tokens_and_usage_counters(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ADMIN_PASSWORD", "correct-horse")
    install_id = "00000000-0000-0000-0000-000000000405"
    fingerprint = relay_main._install_fingerprint(install_id)
    now = relay_main._utc_now()
    cache_key = relay_main._schedule_cache_key(
        airport_iata="ZRH",
        timezone_name="Europe/Zurich",
        display_grace_minutes=30,
        display_horizon_hours=12,
    )
    conn = relay_main._connect()
    relay_main._store_activation_token(
        conn,
        token="lfm_test-cleanup-token",
        label="Keep this token",
        schedule_limit=50,
        radar_limit=600,
        created_by="test",
    )
    conn.execute(
        """
        INSERT INTO usage (subject_key, service, month, calls, last_seen, plan, install_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("install:test", "aviationstack", relay_main._month_key(), 7, now, "community", install_id),
    )
    conn.execute(
        """
        INSERT INTO request_log (ts, install_id, airport, mode, status, latency_ms, service, plan)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (now, install_id, "", "schedule", 200, 42, "aviationstack", "community"),
    )
    conn.execute(
        """
        INSERT INTO client_interests (
            install_id, plan, airport_iata, timezone,
            display_grace_minutes, display_horizon_hours, refresh_seconds, last_seen
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (install_id, "community", "ZRH", "Europe/Zurich", 30, 12, 3600, now),
    )
    conn.execute(
        """
        INSERT INTO schedule_snapshots (
            cache_key, airport_iata, timezone, display_grace_minutes, display_horizon_hours,
            planner_version, schema_version, provider, generated_at, updated_at,
            meta_json, records_json, client_accesses, upstream_pulls, refresh_count,
            cache_hits, stale_serves, last_cache_state, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cache_key,
            "ZRH",
            "Europe/Zurich",
            30,
            12,
            relay_main._SHARED_SCHEDULE_PLANNER_VERSION,
            relay_main._SHARED_SCHEDULE_SCHEMA_VERSION,
            "aviationstack",
            now,
            now,
            "{}",
            "[]",
            1,
            1,
            1,
            0,
            0,
            "fresh",
            "",
        ),
    )
    conn.execute(
        """
        INSERT INTO activation_requests (
            request_id, install_id, install_fingerprint, network_tag,
            display_name, requested_mode, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("lfr_cleanup", install_id, fingerprint, "net_cleanup", "Cleanup test", "community", "manual_review", now, now),
    )
    conn.execute(
        """
        INSERT INTO report_events (
            ts, install_fingerprint, network_tag, report_type, origin, context, team, status, dedupe_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (now, fingerprint, "net_cleanup", "manual", "web", "cleanup", "default", "filed", "dedupe-cleanup"),
    )
    conn.execute(
        """
        INSERT INTO report_dedupe (
            dedupe_key, team, report_type, origin, install_fingerprint, first_seen, last_seen, count, url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("dedupe-cleanup", "default", "manual", "web", fingerprint, now, now, 1, "https://linear.test/cleanup"),
    )
    conn.commit()
    conn.close()
    client = TestClient(relay_main.app)

    response = client.post(
        "/admin/maintenance/clean-trial",
        headers={"host": "network.localflight.app"},
        auth=("admin", "correct-horse"),
    )

    assert response.status_code == 200
    assert "Clean setup trial state" in response.text
    assert "monthly usage counters were kept" in response.text
    conn = relay_main._connect()
    cleared_counts = {
        table: int(conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"] or 0)
        for table in (
            "request_log",
            "client_interests",
            "schedule_snapshots",
            "airport_surface_snapshots",
            "activation_requests",
            "report_events",
            "report_dedupe",
        )
    }
    usage_count = conn.execute("SELECT COUNT(*) AS n FROM usage").fetchone()
    token_count = conn.execute("SELECT COUNT(*) AS n FROM activation_tokens").fetchone()
    conn.close()
    assert cleared_counts == {table: 0 for table in cleared_counts}
    assert usage_count is not None and int(usage_count["n"] or 0) == 1
    assert token_count is not None and int(token_count["n"] or 0) == 1


def test_airport_surface_endpoint_fetches_once_then_serves_cache(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_AIRPORT_SURFACE_ENABLED", "1")
    client = TestClient(relay_main.app)
    calls: list[dict[str, object]] = []

    def _fake_fetch(**kwargs) -> dict[str, object]:
        calls.append(kwargs)
        return _surface_snapshot_payload()

    monkeypatch.setattr(relay_main, "_fetch_airport_surface_from_osm", _fake_fetch)
    params = {
        "airport_iata": "ZRH",
        "airport_icao": "LSZH",
        "lat": 47.45,
        "lon": 8.55,
        "radius_nm": 5,
    }

    first = client.get("/v1/airport-surface", params=params)
    second = client.get("/v1/airport-surface", params=params)

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(calls) == 1
    assert first.json()["features"][0]["label"] == "16/34"
    assert second.json()["cache_state"] == "fresh"
    conn = relay_main._connect()
    row = conn.execute("SELECT request_count, cache_hits, refresh_count FROM airport_surface_snapshots").fetchone()
    conn.close()
    assert row is not None
    assert int(row["request_count"] or 0) == 2
    assert int(row["cache_hits"] or 0) == 1
    assert int(row["refresh_count"] or 0) == 1


def test_airport_surface_endpoint_serves_stale_on_upstream_failure(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_AIRPORT_SURFACE_ENABLED", "1")
    client = TestClient(relay_main.app)
    monkeypatch.setattr(relay_main, "_fetch_airport_surface_from_osm", lambda **kwargs: _surface_snapshot_payload())
    params = {
        "airport_iata": "ZRH",
        "airport_icao": "LSZH",
        "lat": 47.45,
        "lon": 8.55,
        "radius_nm": 5,
    }

    seeded = client.get("/v1/airport-surface", params=params)
    assert seeded.status_code == 200

    old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    conn = relay_main._connect()
    conn.execute("UPDATE airport_surface_snapshots SET updated_at=?", (old,))
    conn.commit()
    conn.close()

    def _boom(**kwargs) -> dict[str, object]:
        raise HTTPException(status_code=502, detail="overpass down")

    monkeypatch.setattr(relay_main, "_fetch_airport_surface_from_osm", _boom)
    response = client.get("/v1/airport-surface", params=params)

    assert response.status_code == 200
    payload = response.json()
    assert payload["cache_state"] == "stale"
    assert "overpass down" in payload["error"]
    assert payload["features"][0]["kind"] == "runway"


def test_airport_surface_endpoint_is_disabled_unless_operator_enables_it(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)

    response = client.get(
        "/v1/airport-surface",
        params={
            "airport_iata": "ZRH",
            "airport_icao": "LSZH",
            "lat": 47.45,
            "lon": 8.55,
            "radius_nm": 5,
        },
    )

    assert response.status_code == 503
    assert "disabled" in response.json()["detail"]


def test_relay_client_ip_ignores_spoofable_forwarded_for() -> None:
    request = types.SimpleNamespace(
        headers={"fly-client-ip": "203.0.113.42", "x-forwarded-for": "10.0.0.1"},
        client=types.SimpleNamespace(host="198.51.100.10"),
    )
    assert relay_main._client_ip(request) == "203.0.113.42"

    request_without_fly = types.SimpleNamespace(
        headers={"x-forwarded-for": "10.0.0.1"},
        client=types.SimpleNamespace(host="198.51.100.10"),
    )
    assert relay_main._client_ip(request_without_fly) == "198.51.100.10"


def test_public_host_hides_admin_surface(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)

    response = client.get("/admin", headers={"host": "relay.localflight.app"})
    api_response = client.get("/admin/api/overview", headers={"host": "relay.localflight.app"})

    assert response.status_code == 404
    assert api_response.status_code == 404


def test_admin_api_requires_auth_and_redacts_private_values(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ADMIN_PASSWORD", "correct-horse")
    client = TestClient(relay_main.app)

    aviationstack_key = "aviationstack-raw-secret-12345"
    rapidapi_key = "rapidapi-raw-secret-67890"
    install_id = "00000000-0000-0000-0000-000000000515"
    conn = relay_main._connect()
    relay_main._setting_set_conn(conn, relay_main._SETTING_AVIATIONSTACK_KEY, aviationstack_key)
    relay_main._setting_set_conn(conn, relay_main._SETTING_RAPIDAPI_KEY, rapidapi_key)
    conn.execute(
        """
        INSERT INTO report_events (
            ts, install_fingerprint, network_tag, report_type, origin, context, team, status, dedupe_key
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            relay_main._utc_now(),
            relay_main._install_fingerprint(install_id),
            "net_private_test",
            "manual",
            "web",
            "contains LINEAR_API_KEY=secret and private log tail",
            "Desktop",
            "filed",
            "dedupe-private-value",
        ),
    )
    conn.commit()
    conn.close()

    activate = client.post(
        "/v1/activate",
        json={
            "install_id": install_id,
            "install_fingerprint": relay_main._install_fingerprint(install_id),
            "airport_iata": "ZRH",
            "airport_icao": "LSZH",
            "display_name": "Admin API privacy test",
            "requested_mode": "community",
            "app_version": "0.2.5",
        },
        headers={"host": "relay.localflight.app", "x-forwarded-for": "198.51.100.88"},
    )
    assert activate.status_code == 200
    raw_token = activate.json()["activation_token"]

    unauth = client.get("/admin/api/overview", headers={"host": "network.localflight.app"})
    assert unauth.status_code == 401

    responses = [
        client.get(path, headers={"host": "network.localflight.app"}, auth=("admin", "correct-horse"))
        for path in (
            "/admin/api/overview",
            "/admin/api/usage",
            "/admin/api/fleet",
            "/admin/api/schedules",
            "/admin/api/surfaces",
            "/admin/api/activations",
            "/admin/api/reports",
        )
    ]

    assert all(response.status_code == 200 for response in responses)
    combined = json.dumps([response.json() for response in responses], sort_keys=True)
    assert aviationstack_key not in combined
    assert rapidapi_key not in combined
    assert raw_token not in combined
    assert install_id not in combined
    assert "LINEAR_API_KEY=secret" not in combined
    assert "private log tail" not in combined
    assert "token_hash" not in combined
    assert "issued_token" not in combined
    assert "context" not in combined
    assert responses[0].json()["providers"]["aviationstack"]["configured"] is True
    assert responses[5].json()["tokens"][0]["token_prefix"] == raw_token[:10]
    assert responses[5].json()["tokens"][0]["action_ref"].startswith("tok_")


def test_admin_api_provider_and_token_actions(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ADMIN_PASSWORD", "correct-horse")
    client = TestClient(relay_main.app)
    headers = {"host": "network.localflight.app"}
    auth = ("admin", "correct-horse")

    save = client.post(
        "/admin/api/providers/save",
        headers=headers,
        auth=auth,
        json={"aviationstack_key": "stored-avi-test", "rapidapi_key": "stored-radar-test"},
    )
    assert save.status_code == 200
    overview = client.get("/admin/api/overview", headers=headers, auth=auth).json()
    assert overview["providers"]["aviationstack"]["configured"] is True
    assert "stored-avi-test" not in json.dumps(overview)

    clear = client.post(
        "/admin/api/providers/clear",
        headers=headers,
        auth=auth,
        json={"provider": "aviationstack"},
    )
    assert clear.status_code == 200

    created = client.post(
        "/admin/api/activation/create",
        headers=headers,
        auth=auth,
        json={"label": "Qt operator test", "schedule_limit": 7, "radar_limit": 8},
    )
    assert created.status_code == 200
    created_payload = created.json()
    raw_token = created_payload["activation_token"]
    prefix = created_payload["token_prefix"]
    token_ref = created_payload["action_ref"]
    assert raw_token.startswith("lfm_")
    assert token_ref.startswith("tok_")

    revoked = client.post(
        "/admin/api/activation/token-action",
        headers=headers,
        auth=auth,
        json={"token_ref": token_ref, "token_prefix": prefix, "action": "revoke"},
    )
    restored = client.post(
        "/admin/api/activation/token-action",
        headers=headers,
        auth=auth,
        json={"token_ref": token_ref, "token_prefix": prefix, "action": "reactivate"},
    )
    rotated = client.post(
        "/admin/api/activation/token-action",
        headers=headers,
        auth=auth,
        json={"token_ref": token_ref, "token_prefix": prefix, "action": "rotate"},
    )

    assert revoked.status_code == 200
    assert restored.status_code == 200
    assert rotated.status_code == 200
    assert rotated.json()["activation_token"].startswith("lfm_")
    assert rotated.json()["activation_token"] != raw_token
    assert rotated.json()["action_ref"].startswith("tok_")


def test_admin_api_activation_request_action_issues_token(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ADMIN_PASSWORD", "correct-horse")
    client = TestClient(relay_main.app)
    headers = {"host": "network.localflight.app"}
    auth = ("admin", "correct-horse")
    install_id = "00000000-0000-0000-0000-000000000616"
    request_id = "req_manual_test"
    now = relay_main._utc_now()
    conn = relay_main._connect()
    conn.execute(
        """
        INSERT INTO activation_requests (
            request_id, install_id, install_fingerprint, network_tag, status, requested_mode,
            created_at, updated_at, last_seen, app_version
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            request_id,
            install_id,
            relay_main._install_fingerprint(install_id),
            "net_admin_api",
            relay_main._REQUEST_STATUS_MANUAL_REVIEW,
            "community",
            now,
            now,
            now,
            "test",
        ),
    )
    conn.commit()
    conn.close()

    issued = client.post(
        "/admin/api/activation/request-action",
        headers=headers,
        auth=auth,
        json={"request_id": request_id, "action": "approve"},
    )

    assert issued.status_code == 200
    payload = issued.json()
    assert payload["activation_token"].startswith("lfm_")
    assert payload["action_ref"].startswith("tok_")
    status = client.get(
        "/v1/client/status",
        params={"install_id": install_id, "activation_token": payload["activation_token"]},
        headers={"host": "relay.localflight.app"},
    )
    assert status.status_code == 200
    assert status.json()["plan"] == "managed"


def test_admin_api_write_actions_tolerate_blank_optional_text(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ADMIN_PASSWORD", "correct-horse")
    client = TestClient(relay_main.app)
    headers = {"host": "network.localflight.app"}
    auth = ("admin", "correct-horse")

    provider_save = client.post(
        "/admin/api/providers/save",
        headers=headers,
        auth=auth,
        json={"aviationstack_key": None, "rapidapi_key": None},
    )
    assert provider_save.status_code == 200

    created = client.post(
        "/admin/api/activation/create",
        headers=headers,
        auth=auth,
        json={"label": None, "schedule_limit": 7, "radar_limit": 8},
    )
    assert created.status_code == 200
    token_ref = created.json()["action_ref"]
    assert token_ref.startswith("tok_")

    reset_token = client.post(
        "/admin/api/counters/reset",
        headers=headers,
        auth=auth,
        json={"scope": "token", "service": None, "token_ref": token_ref, "install_fingerprint": None},
    )
    assert reset_token.status_code == 200

    install_id = "00000000-0000-0000-0000-000000000617"
    fingerprint = relay_main._install_fingerprint(install_id)
    block = client.post(
        "/admin/api/install/access",
        headers=headers,
        auth=auth,
        json={"install_id": install_id, "install_fingerprint": None, "action": "block", "reason": None},
    )
    assert block.status_code == 200
    blocked_payload = client.get("/admin/api/activations", headers=headers, auth=auth).json()
    blocked_ref = blocked_payload["blocked_installs"][0]["action_ref"]
    assert blocked_ref.startswith("inst_")
    unblock_by_ref = client.post(
        "/admin/api/install/access",
        headers=headers,
        auth=auth,
        json={"install_ref": blocked_ref, "install_fingerprint": None, "action": "unblock", "reason": None},
    )
    assert unblock_by_ref.status_code == 200
    block_again = client.post(
        "/admin/api/install/access",
        headers=headers,
        auth=auth,
        json={"install_id": install_id, "install_fingerprint": None, "action": "block", "reason": None},
    )
    legacy_unblock = client.post(
        "/admin/api/install/access",
        headers=headers,
        auth=auth,
        json={"install_id": None, "install_fingerprint": fingerprint, "action": "unblock", "reason": None},
    )
    assert block_again.status_code == 200
    assert legacy_unblock.status_code == 200

    request_id = "req_optional_text"
    now = relay_main._utc_now()
    conn = relay_main._connect()
    conn.execute(
        """
        INSERT INTO activation_requests (
            request_id, install_id, install_fingerprint, network_tag, status, requested_mode,
            created_at, updated_at, last_seen, app_version
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            request_id,
            install_id,
            fingerprint,
            "net_admin_api",
            relay_main._REQUEST_STATUS_MANUAL_REVIEW,
            "community",
            now,
            now,
            now,
            "test",
        ),
    )
    conn.commit()
    conn.close()

    reject = client.post(
        "/admin/api/activation/request-action",
        headers=headers,
        auth=auth,
        json={"request_id": request_id, "action": "reject", "decision_note": None},
    )
    assert reject.status_code == 200

    clean = client.post(
        "/admin/api/maintenance/clean-trial",
        headers=headers,
        auth=auth,
        json={},
    )
    assert clean.status_code == 200


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


def test_admin_auth_throttles_repeated_bad_passwords(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ADMIN_PASSWORD", "correct-horse")
    monkeypatch.setattr(relay_main, "_ADMIN_AUTH_FAILURE_LIMIT", 2)
    relay_main._admin_auth_failures.clear()
    client = TestClient(relay_main.app)

    first = client.get("/admin", headers={"host": "network.localflight.app"}, auth=("admin", "wrong"))
    second = client.get("/admin", headers={"host": "network.localflight.app"}, auth=("admin", "wrong"))
    third = client.get("/admin", headers={"host": "network.localflight.app"}, auth=("admin", "wrong"))

    assert first.status_code == 401
    assert second.status_code == 401
    assert third.status_code == 429


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
            "app_version": "0.2.5",
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


def _report_payload(
    install_id: str,
    *,
    report_type: str = "crash",
    origin: str = "ios",
    context: str = "mobile/react-boundary",
    title: str = "Companion report",
    message: str = "Example crash",
    description: str = "",
    client_context: str = "Companion OS  iOS 18.0\nCompanion ID  lfc_test",
) -> dict[str, str]:
    return {
        "report_type": report_type,
        "origin": origin,
        "install_id": install_id,
        "install_fingerprint": relay_main._install_fingerprint(install_id),
        "title": title,
        "description": description,
        "message": message,
        "traceback": "stack",
        "context": context,
        "client_context": client_context,
        "app_version": "0.2.5",
        "platform": "Darwin",
        "os": "iOS 18.0",
        "arch": "arm64",
        "python_version": "3.11",
        "airport": "ZRH",
        "source": "real",
        "api_mode": "community relay",
        "diagnostics_mode": "auto",
    }


def _enable_reporter_env(monkeypatch) -> None:
    monkeypatch.setenv("LINEAR_REPORTER_API_KEY", "lin_api_test")
    monkeypatch.setenv("LINEAR_TEAM_IOS_ID", "team-ios")
    monkeypatch.setenv("LINEAR_TEAM_DESKTOP_ID", "team-desktop")
    monkeypatch.setenv("LINEAR_TEAM_SERVER_ID", "team-server")
    monkeypatch.setenv("LINEAR_TEAM_RELAY_ID", "team-relay")
    monkeypatch.setenv("LINEAR_TEAM_DEFAULT_ID", "team-default")


def test_relay_reports_route_to_platform_teams(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    _enable_reporter_env(monkeypatch)
    filed: list[dict[str, str]] = []
    monkeypatch.setattr(
        relay_main,
        "_post_linear_issue",
        lambda **kwargs: filed.append(kwargs) or f"https://linear.test/{len(filed)}",
    )
    client = TestClient(relay_main.app)

    cases = [
        ("00000000-0000-0000-0000-000000000301", "ios", "mobile/react-boundary", "team-ios", "ios"),
        ("00000000-0000-0000-0000-000000000302", "web", "web/js-error", "team-desktop", "desktop"),
        ("00000000-0000-0000-0000-000000000303", "scheduler", "scheduler/real", "team-server", "server"),
        ("00000000-0000-0000-0000-000000000304", "relay", "relay/report", "team-relay", "relay"),
    ]
    for install_id, origin, context, team_id, team in cases:
        client_context = "Companion OS  iOS 18.0" if origin == "ios" else "Reporter Web/Desktop"
        response = client.post(
            "/v1/reports",
            json=_report_payload(
                install_id,
                origin=origin,
                context=context,
                message=f"Crash {origin}",
                client_context=client_context,
            ),
        )
        assert response.status_code == 200
        assert response.json()["team"] == team
        assert response.json()["deduped"] is False
        assert filed[-1]["team_id"] == team_id
        assert f"**Origin:** {origin}" in filed[-1]["description"]
        assert f"**Linear team bucket:** {team}" in filed[-1]["description"]
        assert f"**Context:** `{context}`" in filed[-1]["description"]

    assert filed[0]["title"].startswith("[iOS][Crash]")
    assert filed[1]["title"].startswith("[Web][Crash]")
    assert filed[2]["title"].startswith("[Server][Crash]")
    assert filed[3]["title"].startswith("[Relay][Crash]")

    response = client.post(
        "/v1/reports",
        json=_report_payload(
            "00000000-0000-0000-0000-000000000309",
            origin="native",
            context="native/gui",
            message="Native Qt smoke",
            client_context="native/gui; screen=fids; owner=client",
        ),
    )
    assert response.status_code == 200
    assert response.json()["team"] == "desktop"
    assert filed[-1]["team_id"] == "team-desktop"
    assert filed[-1]["title"].startswith("[Desktop][Crash]")
    assert "**Origin:** desktop" in filed[-1]["description"]
    assert "**Context:** `native/gui`" in filed[-1]["description"]


def test_relay_reports_fall_back_to_default_team_when_specific_team_missing(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("LINEAR_REPORTER_API_KEY", "lin_api_test")
    monkeypatch.setenv("LINEAR_TEAM_DEFAULT_ID", "team-default")
    filed: list[dict[str, str]] = []
    monkeypatch.setattr(
        relay_main,
        "_post_linear_issue",
        lambda **kwargs: filed.append(kwargs) or "https://linear.test/fallback",
    )
    client = TestClient(relay_main.app)
    install_id = "00000000-0000-0000-0000-000000000305"

    response = client.post("/v1/reports", json=_report_payload(install_id))

    assert response.status_code == 200
    assert response.json()["team"] == "ios"
    assert filed[0]["team_id"] == "team-default"


def test_relay_reports_dedupe_repeated_crashes_before_linear(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    _enable_reporter_env(monkeypatch)
    filed: list[dict[str, str]] = []
    monkeypatch.setattr(
        relay_main,
        "_post_linear_issue",
        lambda **kwargs: filed.append(kwargs) or "https://linear.test/one",
    )
    client = TestClient(relay_main.app)
    install_id = "00000000-0000-0000-0000-000000000306"
    payload = _report_payload(install_id, message="Same crash")

    first = client.post("/v1/reports", json=payload)
    second = client.post("/v1/reports", json=payload)

    assert first.status_code == 200
    assert first.json()["deduped"] is False
    assert second.status_code == 200
    assert second.json() == {"ok": True, "url": None, "team": "ios", "deduped": True}
    assert len(filed) == 1


def test_relay_reports_dedupe_repeated_manual_reports_for_short_window(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    _enable_reporter_env(monkeypatch)
    filed: list[dict[str, str]] = []
    monkeypatch.setattr(
        relay_main,
        "_post_linear_issue",
        lambda **kwargs: filed.append(kwargs) or f"https://linear.test/{len(filed)}",
    )
    client = TestClient(relay_main.app)
    install_id = "00000000-0000-0000-0000-000000000307"
    payload = _report_payload(
        install_id,
        report_type="manual",
        origin="web",
        context="",
        title="Same manual report",
        message="",
        description="Same body",
        client_context="Reporter Web UI",
    )
    distinct = {**payload, "title": "Different manual report"}

    first = client.post("/v1/reports", json=payload)
    second = client.post("/v1/reports", json=payload)
    third = client.post("/v1/reports", json=distinct)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["deduped"] is True
    assert third.status_code == 200
    assert third.json()["deduped"] is False
    assert len(filed) == 2


def test_relay_reports_rate_limit_by_install(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    _enable_reporter_env(monkeypatch)
    monkeypatch.setenv("RELAY_REPORT_MANUAL_DAILY_LIMIT", "1")
    monkeypatch.setattr(relay_main, "_post_linear_issue", lambda **kwargs: "https://linear.test/rate")
    client = TestClient(relay_main.app)
    install_id = "00000000-0000-0000-0000-000000000308"
    payload = _report_payload(
        install_id,
        report_type="manual",
        origin="web",
        title="First manual report",
        message="",
        description="First",
    )
    second_payload = {**payload, "title": "Second manual report", "description": "Second"}

    assert client.post("/v1/reports", json=payload).status_code == 200
    second = client.post("/v1/reports", json=second_payload)

    assert second.status_code == 429


def test_relay_reports_redact_secrets_before_linear(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    _enable_reporter_env(monkeypatch)
    filed: list[dict[str, str]] = []
    monkeypatch.setattr(
        relay_main,
        "_post_linear_issue",
        lambda **kwargs: filed.append(kwargs) or "https://linear.test/redacted",
    )
    client = TestClient(relay_main.app)
    install_id = "00000000-0000-0000-0000-000000000309"
    payload = _report_payload(
        install_id,
        report_type="manual",
        origin="web",
        title="Secret report",
        description="RAPIDAPI_KEY=supersecret lin_api_abcdef access_key=abc 192.168.1.44",
        message="",
    )

    response = client.post("/v1/reports", json=payload)

    assert response.status_code == 200
    description = filed[0]["description"]
    assert "supersecret" not in description
    assert "lin_api_abcdef" not in description
    assert "access_key=abc" not in description
    assert "192.168.1.44" not in description


def test_relay_reports_require_linear_configuration(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.delenv("LINEAR_REPORTER_API_KEY", raising=False)
    monkeypatch.delenv("LINEAR_TEAM_DEFAULT_ID", raising=False)
    client = TestClient(relay_main.app)
    install_id = "00000000-0000-0000-0000-000000000310"

    response = client.post("/v1/reports", json=_report_payload(install_id))

    assert response.status_code == 503


def test_admin_dashboard_surfaces_report_gateway_events(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    _enable_reporter_env(monkeypatch)
    monkeypatch.setenv("RELAY_ADMIN_PASSWORD", "correct-horse")
    monkeypatch.setattr(relay_main, "_post_linear_issue", lambda **kwargs: "https://linear.test/admin")
    client = TestClient(relay_main.app)
    install_id = "00000000-0000-0000-0000-000000000311"
    payload = _report_payload(
        install_id,
        report_type="manual",
        origin="web",
        context="web/feedback",
        title="Admin dashboard report",
        message="",
        description="Dashboard visibility",
        client_context="Reporter Web UI",
    )

    first = client.post("/v1/reports", json=payload)
    second = client.post("/v1/reports", json=payload)
    admin = client.get("/admin", headers={"host": "network.localflight.app"}, auth=("admin", "correct-horse"))
    reports = client.get("/admin/api/reports", headers={"host": "network.localflight.app"}, auth=("admin", "correct-horse")).json()

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["deduped"] is True
    assert admin.status_code == 200
    assert "Sanitized report gateway events" in admin.text
    statuses = {row["status"] for row in reports["rows"]}
    assert {"filed", "deduped"}.issubset(statuses)
    assert reports["facets"]["status"]["filed"] == 1
    assert reports["facets"]["status"]["deduped"] == 1
    assert "context" not in json.dumps(reports)
    assert "web/feedback" not in json.dumps(reports)


def test_admin_dashboard_sorts_recent_report_events_newest_first(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    _enable_reporter_env(monkeypatch)
    monkeypatch.setenv("RELAY_ADMIN_PASSWORD", "correct-horse")
    monkeypatch.setattr(relay_main, "_post_linear_issue", lambda **kwargs: "https://linear.test/admin-sort")
    client = TestClient(relay_main.app)

    old_report = client.post(
        "/v1/reports",
        json=_report_payload(
            "00000000-0000-0000-0000-000000000312",
            report_type="manual",
            origin="web",
            context="web/feedback-old",
            title="Old admin sorting report",
            message="",
            description="Old body",
            client_context="Reporter Web UI",
        ),
    )
    new_report = client.post(
        "/v1/reports",
        json=_report_payload(
            "00000000-0000-0000-0000-000000000313",
            report_type="manual",
            origin="web",
            context="web/feedback-new",
            title="New admin sorting report",
            message="",
            description="New body",
            client_context="Reporter Web UI",
        ),
    )
    admin = client.get("/admin", headers={"host": "network.localflight.app"}, auth=("admin", "correct-horse"))
    reports = client.get("/admin/api/reports?sort=ts&dir=desc", headers={"host": "network.localflight.app"}, auth=("admin", "correct-horse")).json()

    assert old_report.status_code == 200
    assert new_report.status_code == 200
    assert admin.status_code == 200
    assert reports["rows"][0]["install_fingerprint"] == relay_main._install_fingerprint("00000000-0000-0000-0000-000000000313")
    assert reports["rows"][1]["install_fingerprint"] == relay_main._install_fingerprint("00000000-0000-0000-0000-000000000312")


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


def test_raw_provider_debug_route_hidden_before_query_validation(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ALLOW_RAW_PROVIDER_DEBUG", "1")
    client = TestClient(relay_main.app)

    response = client.get("/v1/flights", headers={"host": "relay.localflight.app"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


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


def test_shared_schedule_ttls_have_public_relay_floor(monkeypatch) -> None:
    monkeypatch.delenv("RELAY_SHARED_SCHEDULE_MIN_FRESH_TTL_SECONDS", raising=False)
    assert relay_main._schedule_ttls(60)[0] == 900
    assert relay_main._schedule_ttls(3600)[0] == 900
    assert relay_main._schedule_ttls(900, min_fresh_ttl_s=3600)[0] == 3600

    monkeypatch.setenv("RELAY_SHARED_SCHEDULE_MIN_FRESH_TTL_SECONDS", "180")
    assert relay_main._schedule_ttls(60)[0] == 180

    monkeypatch.setenv("RELAY_SHARED_SCHEDULE_MIN_FRESH_TTL_SECONDS", "not-a-number")
    assert relay_main._schedule_ttls(60)[0] == 900


def test_community_shared_schedule_enforces_hourly_upstream_cadence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)
    upstream_calls: list[dict[str, object]] = []

    def fake_shared_fetch(**kwargs):
        upstream_calls.append(dict(kwargs))
        return _shared_snapshot_payload(pages_fetched=2)

    monkeypatch.setattr(relay_main, "_fetch_shared_schedule_from_upstream", fake_shared_fetch)
    params = {
        "airport_iata": "EGLL",
        "timezone": "Europe/London",
        "display_grace_minutes": 30,
        "display_horizon_hours": 12,
        "refresh_seconds": 900,
        "install_id": "00000000-0000-0000-0000-000000000427",
    }

    seed = client.get("/v1/schedule", params=params)
    assert seed.status_code == 200
    assert seed.json()["cache_state"] == "miss"

    conn = relay_main._connect()
    thirty_minutes_ago = (relay_main.datetime.now(relay_main.timezone.utc) - relay_main.timedelta(minutes=30)).isoformat()
    conn.execute(
        "UPDATE schedule_snapshots SET generated_at=?, updated_at=?",
        (thirty_minutes_ago, relay_main._utc_now()),
    )
    conn.commit()
    conn.close()

    response = client.get("/v1/schedule", params=params)

    assert response.status_code == 200
    payload = response.json()
    assert payload["cache_state"] == "fresh"
    assert payload["meta"]["served_via"] == "cache-hit"
    assert payload["meta"]["requested_refresh_seconds"] == 900
    assert payload["meta"]["effective_min_fresh_ttl_seconds"] == 3600
    assert "once per hour" in payload["meta"]["relay_policy"]
    assert len(upstream_calls) == 1

    conn = relay_main._connect()
    row = conn.execute("SELECT refresh_seconds FROM client_interests WHERE install_id=?", (params["install_id"],)).fetchone()
    conn.close()
    assert row is not None
    assert int(row["refresh_seconds"] or 0) == 3600


def test_shared_schedule_rechecks_cache_after_winning_refresh_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)
    cache_key = relay_main._schedule_cache_key(
        airport_iata="EGLL",
        timezone_name="Europe/London",
        display_grace_minutes=30,
        display_horizon_hours=12,
    )
    relay_main._store_schedule_snapshot(
        cache_key=cache_key,
        airport_iata="EGLL",
        timezone_name="Europe/London",
        display_grace_minutes=30,
        display_horizon_hours=12,
        payload=_shared_snapshot_payload(pages_fetched=1),
        pages_fetched=1,
    )
    lifecycle_calls: list[str] = []

    def fake_lifecycle(row, *, refresh_seconds, min_fresh_ttl_s=None):
        lifecycle_calls.append("called")
        return "stale" if len(lifecycle_calls) == 1 else "fresh"

    def fail_fetch(**kwargs):
        raise AssertionError("shared schedule should use the refreshed cache row")

    monkeypatch.setattr(relay_main, "_snapshot_lifecycle_state", fake_lifecycle)
    monkeypatch.setattr(relay_main, "_fetch_shared_schedule_from_upstream", fail_fetch)

    response = client.get(
        "/v1/schedule",
        params={
            "airport_iata": "EGLL",
            "timezone": "Europe/London",
            "display_grace_minutes": 30,
            "display_horizon_hours": 12,
            "refresh_seconds": 3600,
            "install_id": "00000000-0000-0000-0000-000000000426",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["cache_state"] == "fresh"
    assert payload["meta"]["served_via"] == "coalesced-refresh"
    assert len(lifecycle_calls) == 2


def test_shared_schedule_network_daily_limit_blocks_rotating_install_ids(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_COMMUNITY_SCHEDULE_NETWORK_DAILY_LIMIT", "1")
    monkeypatch.setenv("RELAY_COMMUNITY_SCHEDULE_GLOBAL_DAILY_LIMIT", "100")
    client = TestClient(relay_main.app)
    upstream_calls: list[dict[str, object]] = []

    def fake_shared_fetch(**kwargs):
        upstream_calls.append(dict(kwargs))
        return _shared_snapshot_payload(pages_fetched=1)

    monkeypatch.setattr(relay_main, "_fetch_shared_schedule_from_upstream", fake_shared_fetch)
    params = {
        "airport_iata": "ZRH",
        "timezone": "Europe/Zurich",
        "display_grace_minutes": 30,
        "display_horizon_hours": 12,
        "refresh_seconds": 3600,
    }

    first = client.get(
        "/v1/schedule",
        params={**params, "install_id": "00000000-0000-0000-0000-000000000421"},
    )
    second = client.get(
        "/v1/schedule",
        params={**params, "install_id": "00000000-0000-0000-0000-000000000422"},
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert "network daily limit" in second.json()["detail"]
    assert len(upstream_calls) == 1


def test_shared_schedule_global_daily_limit_blocks_rotating_networks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_COMMUNITY_SCHEDULE_NETWORK_DAILY_LIMIT", "100")
    monkeypatch.setenv("RELAY_COMMUNITY_SCHEDULE_GLOBAL_DAILY_LIMIT", "1")
    client = TestClient(relay_main.app)
    upstream_calls: list[dict[str, object]] = []

    def fake_shared_fetch(**kwargs):
        upstream_calls.append(dict(kwargs))
        return _shared_snapshot_payload(pages_fetched=1)

    monkeypatch.setattr(relay_main, "_fetch_shared_schedule_from_upstream", fake_shared_fetch)
    params = {
        "airport_iata": "ZRH",
        "timezone": "Europe/Zurich",
        "display_grace_minutes": 30,
        "display_horizon_hours": 12,
        "refresh_seconds": 3600,
    }

    first = client.get(
        "/v1/schedule",
        params={**params, "install_id": "00000000-0000-0000-0000-000000000423"},
        headers={"fly-client-ip": "203.0.113.1"},
    )
    second = client.get(
        "/v1/schedule",
        params={**params, "install_id": "00000000-0000-0000-0000-000000000424"},
        headers={"fly-client-ip": "203.0.113.2"},
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert "daily safety limit" in second.json()["detail"]
    assert len(upstream_calls) == 1


def test_shared_schedule_invalid_timezones_share_normalized_cache_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)
    upstream_calls: list[dict[str, object]] = []

    def fake_shared_fetch(**kwargs):
        upstream_calls.append(dict(kwargs))
        return _shared_snapshot_payload(pages_fetched=1)

    monkeypatch.setattr(relay_main, "_fetch_shared_schedule_from_upstream", fake_shared_fetch)
    base_params = {
        "airport_iata": "ZRH",
        "display_grace_minutes": 30,
        "display_horizon_hours": 12,
        "refresh_seconds": 3600,
        "install_id": "00000000-0000-0000-0000-000000000425",
    }

    first = client.get("/v1/schedule", params={**base_params, "timezone": "Bad/One"})
    second = client.get("/v1/schedule", params={**base_params, "timezone": "Bad/Two"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(upstream_calls) == 1
    assert upstream_calls[0]["timezone_name"] == "UTC"

    conn = relay_main._connect()
    row = conn.execute("SELECT COUNT(*) AS n, MIN(timezone) AS timezone FROM schedule_snapshots").fetchone()
    conn.close()
    assert row is not None
    assert int(row["n"] or 0) == 1
    assert row["timezone"] == "UTC"


def test_shared_schedule_upstream_fetch_adds_adaptive_pages_for_busy_departures(monkeypatch) -> None:
    monkeypatch.setattr(relay_main, "_aviationstack_key", lambda: "relay-key-123")
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    flight_date = start.date().isoformat()
    captured: list[dict[str, object]] = []

    def fake_get(url, *, params, headers, timeout):
        captured.append(dict(params))
        limit = int(params.get("limit", 100) or 100)
        offset = int(params.get("offset", 0) or 0)
        if params.get("dep_iata") == "ZRH" and params.get("flight_date") == flight_date and offset < 500:
            rows = [
                _aviationstack_departure(
                    str(1000 + offset + idx),
                    start + timedelta(seconds=offset + idx),
                )
                for idx in range(limit)
            ]
        else:
            rows = []
        return types.SimpleNamespace(status_code=200, json=lambda: {"data": rows})

    monkeypatch.setattr(relay_main._req, "get", fake_get)

    payload = relay_main._fetch_shared_schedule_from_upstream(
        airport_iata="ZRH",
        timezone_name="UTC",
        display_grace_minutes=30,
        display_horizon_hours=2,
    )

    meta = payload["meta"]

    assert meta["adaptive_extra_pages"] >= 1
    assert meta["pages_by_scope"][f"departures:{flight_date}"] >= 5
    assert meta["pages_by_scope"][f"arrivals:{flight_date}"] == 1
    assert len(payload["records"]) == 500
    assert any(
        params.get("dep_iata") == "ZRH"
        and params.get("flight_date") == flight_date
        and int(params.get("offset", 0) or 0) == 400
        for params in captured
    )


def test_shared_schedule_upstream_fetch_falls_back_to_undated_when_date_scope_is_empty_on_board(monkeypatch) -> None:
    monkeypatch.setattr(relay_main, "_aviationstack_key", lambda: "relay-key-123")
    early = _aviationstack_departure("100", datetime(2026, 5, 1, 5, 0, tzinfo=timezone.utc))
    rescue = _aviationstack_departure("200", datetime(2026, 5, 1, 15, 0, tzinfo=timezone.utc))

    def fake_get(url, *, params, headers, timeout):
        flight_date = params.get("flight_date")
        offset = int(params.get("offset", 0) or 0)
        if params.get("dep_iata") == "ZRH" and flight_date == "2026-05-01" and offset == 0:
            rows = [early]
        elif params.get("dep_iata") == "ZRH" and flight_date is None and offset == 0:
            rows = [early, rescue]
        else:
            rows = []
        return types.SimpleNamespace(status_code=200, json=lambda: {"data": rows})

    monkeypatch.setattr(relay_main._req, "get", fake_get)

    payload = relay_main._fetch_shared_schedule_from_upstream(
        airport_iata="ZRH",
        timezone_name="UTC",
        display_grace_minutes=30,
        display_horizon_hours=12,
    )

    meta = payload["meta"]
    scheduled_values = {record["scheduled"] for record in payload["records"] if record.get("direction") == "DEP"}

    assert meta["undated_fallback_used"] is True
    assert "departures:undated" in meta["pages_by_scope"]
    assert rescue["departure"]["scheduled"] in scheduled_values


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
    stale_at = (relay_main.datetime.now(relay_main.timezone.utc) - relay_main.timedelta(minutes=70)).isoformat()
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


def test_client_checkin_records_redacted_fleet_profile_and_preserves_first_seen(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ADMIN_PASSWORD", "correct-horse")
    client = TestClient(relay_main.app)
    headers = {"host": "network.localflight.app"}
    auth = ("admin", "correct-horse")
    install_id = "00000000-0000-0000-0000-000000000406"

    first = client.post(
        "/v1/client/checkin",
        json={
            "install_id": install_id,
            "app_version": "0.2.5",
            "os_family": "Windows",
            "os_version": "11",
            "arch": "AMD64",
            "requested_gui": "native",
            "effective_gui": "native",
            "source_mode": "real",
            "diagnostics_mode": "manual",
            "companion_count": 1,
            "matrix_count": 2,
            "matrix_online_count": 1,
            "airport_iata": "ZRH",
            "timezone": "Europe/Zurich",
            "refresh_seconds": 3600,
        },
    )
    assert first.status_code == 200
    fleet_first = client.get("/admin/api/fleet", headers=headers, auth=auth).json()
    row = fleet_first["installs"][0]

    assert row["install_fingerprint"] == relay_main._install_fingerprint(install_id)
    assert row["action_ref"].startswith("inst_")
    assert row["os_family"] == "Windows"
    assert row["effective_gui"] == "native"
    assert row["companion_count"] == 1
    assert row["matrix_online_count"] == 1
    assert row["current_lane"]["airport_iata"] == "ZRH"
    assert install_id not in json.dumps(fleet_first)

    second = client.post(
        "/v1/client/checkin",
        json={"install_id": install_id, "app_version": "0.2.6", "os_family": "Windows"},
    )
    assert second.status_code == 200
    fleet_second = client.get("/admin/api/fleet", headers=headers, auth=auth).json()
    updated = fleet_second["installs"][0]

    assert updated["first_seen"] == row["first_seen"]
    assert updated["last_seen"] >= row["last_seen"]
    assert updated["app_version"] == "0.2.6"


def test_admin_fleet_install_refs_support_actions(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ADMIN_PASSWORD", "correct-horse")
    client = TestClient(relay_main.app)
    headers = {"host": "network.localflight.app"}
    auth = ("admin", "correct-horse")
    install_id = "00000000-0000-0000-0000-000000000407"

    checkin = client.post("/v1/client/checkin", json={"install_id": install_id, "os_family": "macOS"})
    assert checkin.status_code == 200
    fleet = client.get("/admin/api/fleet", headers=headers, auth=auth).json()
    install_ref = fleet["installs"][0]["action_ref"]

    blocked = client.post(
        "/admin/api/install/access",
        headers=headers,
        auth=auth,
        json={"install_ref": install_ref, "action": "block", "reason": "test"},
    )
    assert blocked.status_code == 200
    reset = client.post(
        "/admin/api/counters/reset",
        headers=headers,
        auth=auth,
        json={"scope": "install", "install_ref": install_ref},
    )
    assert reset.status_code == 200
    after = client.get("/admin/api/fleet", headers=headers, auth=auth).json()
    assert after["installs"][0]["blocked"] is True


def test_admin_fleet_supports_server_filters_pagination_and_facets(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ADMIN_PASSWORD", "correct-horse")
    client = TestClient(relay_main.app)
    headers = {"host": "network.localflight.app"}
    auth = ("admin", "correct-horse")
    installs = [
        ("00000000-0000-0000-0000-000000001001", "Windows", "native", "0.2.5", "ZRH", 1, 0),
        ("00000000-0000-0000-0000-000000001002", "Windows", "browser", "0.2.5", "JFK", 0, 1),
        ("00000000-0000-0000-0000-000000001003", "macOS", "native", "0.2.6", "ZRH", 1, 1),
        ("00000000-0000-0000-0000-000000001004", "Linux", "headless", "0.2.6", "LHR", 0, 0),
    ]
    for install_id, os_family, gui, version, airport, companions, matrices in installs:
        response = client.post(
            "/v1/client/checkin",
            json={
                "install_id": install_id,
                "os_family": os_family,
                "effective_gui": gui,
                "requested_gui": gui,
                "app_version": version,
                "airport_iata": airport,
                "timezone": "UTC",
                "companion_count": companions,
                "matrix_count": matrices,
                "matrix_online_count": matrices,
            },
        )
        assert response.status_code == 200

    first_page = client.get(
        "/admin/api/fleet?limit=2&sort=install_fingerprint&dir=asc",
        headers=headers,
        auth=auth,
    ).json()
    second_page = client.get(
        f"/admin/api/fleet?limit=2&sort=install_fingerprint&dir=asc&cursor={first_page['next_cursor']}",
        headers=headers,
        auth=auth,
    ).json()
    first_ids = {row["install_fingerprint"] for row in first_page["rows"]}
    second_ids = {row["install_fingerprint"] for row in second_page["rows"]}

    assert first_page["total_estimate"] == 4
    assert first_page["filtered_estimate"] == 4
    assert first_page["next_cursor"]
    assert len(first_ids) == 2
    assert len(second_ids) == 2
    assert not first_ids & second_ids

    filtered = client.get(
        "/admin/api/fleet?os_family=macOS&effective_gui=native&has_companion=true&airport_iata=ZRH",
        headers=headers,
        auth=auth,
    ).json()
    combined = json.dumps(filtered)

    assert filtered["filtered_estimate"] == 1
    assert filtered["rows"][0]["os_family"] == "macOS"
    assert filtered["rows"][0]["effective_gui"] == "native"
    assert filtered["rows"][0]["current_lane"]["airport_iata"] == "ZRH"
    assert filtered["facets"]["os_family"] == {"macos": 1}
    assert filtered["facets"]["has_companion"]["yes"] == 1
    assert "00000000-0000-0000-0000-000000001003" not in combined

    block_ref = filtered["rows"][0]["action_ref"]
    blocked = client.post(
        "/admin/api/install/access",
        headers=headers,
        auth=auth,
        json={"install_ref": block_ref, "action": "block", "reason": "test"},
    )
    assert blocked.status_code == 200
    blocked_rows = client.get("/admin/api/fleet?blocked=true", headers=headers, auth=auth).json()
    assert blocked_rows["filtered_estimate"] == 1
    assert blocked_rows["rows"][0]["blocked"] is True


def test_admin_html_is_lazy_query_driven_shell(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ADMIN_PASSWORD", "correct-horse")
    client = TestClient(relay_main.app)
    response = client.get("/admin", headers={"host": "network.localflight.app"}, auth=("admin", "correct-horse"))
    text = response.text

    assert response.status_code == 200
    assert "Lazy, query-driven admin console" in text
    assert '"/admin/api/fleet"' in text
    assert "quickViewDefs" in text
    assert "data-filter" in text
    assert "Provider State" not in text
