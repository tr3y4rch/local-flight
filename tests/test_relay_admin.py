from __future__ import annotations

import json
import threading
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
    assert status_data["known_install"] is True
    assert status_data["can_reissue"] is True
    assert status_data["providers"]["aviationstack"] is False

    no_token_status = client.get("/v1/client/status", params={"install_id": install_id})
    assert no_token_status.status_code == 200
    assert no_token_status.json()["plan"] == "community"
    assert no_token_status.json()["known_install"] is True
    assert no_token_status.json()["can_reissue"] is True
    assert no_token_status.json()["token_prefix"] == activate_data["token_prefix"]

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


def test_client_status_exposes_safe_shared_schedule_budget(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_SCHEDULE_PROVIDER", "aviationstack")
    monkeypatch.setenv("AVIATIONSTACK_API_KEY", "secret-aviationstack-key")
    monkeypatch.setenv("RELAY_AVIATIONSTACK_UPSTREAM_MONTHLY_LIMIT", "10000")
    client = TestClient(relay_main.app)
    install_id = "00000000-0000-0000-0000-000000000777"
    relay_main._increment_usage(
        subject_key="shared:upstream",
        service="aviationstack_upstream",
        month=relay_main._month_key(),
        plan="upstream",
        install_id=None,
        n_calls=37,
    )
    relay_main._increment_usage(
        subject_key=install_id,
        service="aviationstack",
        month=relay_main._month_key(),
        plan="community",
        install_id=install_id,
        n_calls=2,
    )

    response = client.get("/v1/client/status", params={"install_id": install_id})

    assert response.status_code == 200
    payload = response.json()
    shared = payload["shared_schedule_budget"]
    access = payload["schedule_access_budget"]
    assert shared["provider"] == "aviationstack"
    assert shared["used"] == 37
    assert shared["limit"] == 10000
    assert shared["remaining"] == 9963
    assert shared["reset_at"]
    assert shared["scope_label"] == "Shared by all community relay real-data users"
    assert access["used"] == 2
    assert access["limit"] == relay_main._community_schedule_limit()
    serialized = json.dumps(payload)
    assert "secret-aviationstack-key" not in serialized
    assert "/admin/api" not in serialized


def test_activate_mobile_standalone_uses_standalone_limits(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)
    install_id = "00000000-0000-0000-0000-000000000901"

    response = client.post(
        "/v1/activate",
        json={
            "install_id": install_id,
            "install_fingerprint": relay_main._install_fingerprint(install_id),
            "airport_iata": "ZRH",
            "airport_icao": "LSZH",
            "timezone": "Europe/Zurich",
            "device_type": "phone",
            "display_name": "Mobile standalone",
            "requested_mode": "mobile_standalone",
            "app_version": "0.2.6",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["activation_token"].startswith("lfm_")
    assert payload["limits"]["schedule"] == 600
    assert payload["limits"]["radar"] == 3000

    conn = relay_main._connect()
    token = conn.execute(
        "SELECT schedule_limit, radar_limit FROM activation_tokens WHERE bound_install_id=?",
        (install_id,),
    ).fetchone()
    profile = conn.execute(
        "SELECT client_kind, device_type, airport_iata, airport_icao, timezone FROM install_profiles WHERE install_id=?",
        (install_id,),
    ).fetchone()
    request_row = conn.execute(
        "SELECT airport_iata, airport_icao FROM activation_requests WHERE request_id=?",
        (payload["request_id"],),
    ).fetchone()
    conn.close()
    assert token is not None
    assert int(token["schedule_limit"]) == 600
    assert int(token["radar_limit"]) == 3000
    assert profile["client_kind"] == "mobile_standalone"
    assert profile["device_type"] == "phone"
    assert profile["airport_iata"] == "ZRH"
    assert profile["airport_icao"] == "LSZH"
    assert profile["timezone"] == "Europe/Zurich"
    assert request_row["airport_iata"] == "ZRH"
    assert request_row["airport_icao"] == "LSZH"


def test_mobile_standalone_known_install_reissues_during_network_review(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setattr(relay_main, "_AUTO_ACTIVATION_NETWORK_DAILY_LIMIT", 1)
    monkeypatch.setattr(relay_main, "_AUTO_ACTIVATION_NETWORK_INSTALLS_DAILY_LIMIT", 1)
    client = TestClient(relay_main.app)
    install_id = "00000000-0000-0000-0000-000000000902"
    pending_id = "lfr_existing_pending"
    headers = {"fly-client-ip": "198.51.100.88"}

    first = client.post(
        "/v1/activate",
        json={
            "install_id": install_id,
            "install_fingerprint": relay_main._install_fingerprint(install_id),
            "airport_iata": "ZRH",
            "airport_icao": "LSZH",
            "timezone": "Europe/Zurich",
            "device_type": "phone",
            "display_name": "Mobile standalone",
            "requested_mode": "mobile_standalone",
            "app_version": "0.2.6",
        },
        headers=headers,
    )
    assert first.status_code == 200
    first_payload = first.json()
    first_token = first_payload["activation_token"]

    now = relay_main._utc_now()
    conn = relay_main._connect()
    conn.execute(
        """
        INSERT INTO activation_requests (
            request_id, install_id, install_fingerprint, network_tag, airport_iata, airport_icao,
            display_name, requested_mode, app_version, status, created_at, updated_at, last_seen,
            decision_source, decision_note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            pending_id,
            install_id,
            relay_main._install_fingerprint(install_id),
            "net_pending",
            "ZRH",
            "LSZH",
            "Mobile standalone",
            "mobile_standalone",
            "0.2.6",
            relay_main._REQUEST_STATUS_MANUAL_REVIEW,
            now,
            now,
            now,
            "auto-safety-net",
            "manual review required",
        ),
    )
    conn.commit()
    conn.close()

    reissued = client.post(
        "/v1/activate",
        json={
            "install_id": install_id,
            "install_fingerprint": relay_main._install_fingerprint(install_id),
            "airport_iata": "ZRH",
            "airport_icao": "LSZH",
            "timezone": "Europe/Zurich",
            "device_type": "phone",
            "display_name": "Mobile standalone reset",
            "requested_mode": "mobile_standalone",
            "app_version": "0.2.6",
        },
        headers=headers,
    )

    assert reissued.status_code == 200
    reissued_payload = reissued.json()
    assert reissued_payload["status"] == "issued"
    assert reissued_payload["request_id"] == pending_id
    assert reissued_payload["activation_token"].startswith("lfm_")
    assert reissued_payload["activation_token"] != first_token
    assert reissued_payload["limits"]["schedule"] == 600
    assert reissued_payload["limits"]["radar"] == 3000
    assert "reissued" in reissued_payload["decision_note"]

    old_status = client.get(
        "/v1/client/status",
        params={"install_id": install_id, "activation_token": first_token},
        headers={"host": "relay.beacontools.cc"},
    )
    new_status = client.get(
        "/v1/client/status",
        params={"install_id": install_id, "activation_token": reissued_payload["activation_token"]},
        headers={"host": "relay.beacontools.cc"},
    )
    assert old_status.status_code == 403
    assert new_status.status_code == 200
    assert new_status.json()["limits"]["schedule"] == 600
    assert new_status.json()["limits"]["radar"] == 3000

    unknown_install = "00000000-0000-0000-0000-000000000903"
    unknown = client.post(
        "/v1/activate",
        json={
            "install_id": unknown_install,
            "install_fingerprint": relay_main._install_fingerprint(unknown_install),
            "airport_iata": "ZRH",
            "airport_icao": "LSZH",
            "display_name": "Unknown standalone",
            "requested_mode": "mobile_standalone",
            "app_version": "0.2.6",
        },
        headers=headers,
    )
    assert unknown.status_code == 200
    assert unknown.json()["status"] == "manual_review"
    assert "activation_token" not in unknown.json()

    conn = relay_main._connect()
    row = conn.execute(
        "SELECT status, decision_source, token_prefix, airport_iata, airport_icao FROM activation_requests WHERE request_id=?",
        (pending_id,),
    ).fetchone()
    conn.close()
    assert row["status"] == "issued"
    assert row["decision_source"] == "auto-existing-install"
    assert row["token_prefix"] == reissued_payload["token_prefix"]
    assert row["airport_iata"] == "ZRH"
    assert row["airport_icao"] == "LSZH"


def test_known_install_reissues_do_not_consume_new_install_network_burst(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setattr(relay_main, "_AUTO_ACTIVATION_NETWORK_DAILY_LIMIT", 2)
    monkeypatch.setattr(relay_main, "_AUTO_ACTIVATION_NETWORK_INSTALLS_DAILY_LIMIT", 2)
    client = TestClient(relay_main.app)
    headers = {"x-forwarded-for": "198.51.100.99"}
    known_install = "00000000-0000-0000-0000-000000000904"

    first = client.post(
        "/v1/activate",
        json={
            "install_id": known_install,
            "install_fingerprint": relay_main._install_fingerprint(known_install),
            "display_name": "Known desktop",
            "requested_mode": "community",
        },
        headers=headers,
    )
    assert first.status_code == 200
    assert first.json()["status"] == "issued"
    assert first.json()["known_install"] is False

    for _ in range(3):
        reissued = client.post(
            "/v1/activate",
            json={
                "install_id": known_install,
                "install_fingerprint": relay_main._install_fingerprint(known_install),
                "display_name": "Known desktop reset",
                "requested_mode": "community",
            },
            headers=headers,
        )
        assert reissued.status_code == 200
        assert reissued.json()["status"] == "issued"
        assert reissued.json()["known_install"] is True
        assert "reissued" in reissued.json()["decision_note"]

    unknown_install = "00000000-0000-0000-0000-000000000905"
    unknown = client.post(
        "/v1/activate",
        json={
            "install_id": unknown_install,
            "install_fingerprint": relay_main._install_fingerprint(unknown_install),
            "display_name": "Unknown desktop",
            "requested_mode": "community",
        },
        headers=headers,
    )

    assert unknown.status_code == 200
    assert unknown.json()["status"] == "issued"
    assert unknown.json()["known_install"] is False

    conn = relay_main._connect()
    known_rows = conn.execute(
        "SELECT network_tag FROM activation_requests WHERE install_id=? ORDER BY created_at",
        (known_install,),
    ).fetchall()
    conn.close()
    assert str(known_rows[0]["network_tag"]).startswith("net_")
    assert all((row["network_tag"] or "") == "" for row in known_rows[1:])


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

    admin = client.get("/admin", headers={"host": "network.beacontools.cc"}, auth=("admin", "correct-horse"))
    schedules = client.get("/admin/api/schedules", headers={"host": "network.beacontools.cc"}, auth=("admin", "correct-horse")).json()

    assert admin.status_code == 200
    assert "Presence is coarse" in admin.text
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
        headers={"host": "network.beacontools.cc"},
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

    response = client.get("/admin", headers={"host": "relay.beacontools.cc"})
    api_response = client.get("/admin/api/overview", headers={"host": "relay.beacontools.cc"})

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
        headers={"host": "relay.beacontools.cc", "x-forwarded-for": "198.51.100.88"},
    )
    assert activate.status_code == 200
    raw_token = activate.json()["activation_token"]

    unauth = client.get("/admin/api/overview", headers={"host": "network.beacontools.cc"})
    assert unauth.status_code == 401

    responses = [
        client.get(path, headers={"host": "network.beacontools.cc"}, auth=("admin", "correct-horse"))
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
    headers = {"host": "network.beacontools.cc"}
    auth = ("admin", "correct-horse")

    save = client.post(
        "/admin/api/providers/save",
        headers=headers,
        auth=auth,
        json={
            "aerodatabox_key": "stored-aero-test",
            "aviationstack_key": "stored-avi-test",
            "rapidapi_key": "stored-radar-test",
        },
    )
    assert save.status_code == 200
    overview = client.get("/admin/api/overview", headers=headers, auth=auth).json()
    assert overview["providers"]["aerodatabox"]["configured"] is True
    assert overview["providers"]["aviationstack"]["configured"] is True
    assert "stored-aero-test" not in json.dumps(overview)
    assert "stored-avi-test" not in json.dumps(overview)

    clear_aero = client.post(
        "/admin/api/providers/clear",
        headers=headers,
        auth=auth,
        json={"provider": "aerodatabox"},
    )
    assert clear_aero.status_code == 200

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
    headers = {"host": "network.beacontools.cc"}
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
        headers={"host": "relay.beacontools.cc"},
    )
    assert status.status_code == 200
    assert status.json()["plan"] == "managed"


def test_admin_api_activation_request_action_uses_standalone_limits(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ADMIN_PASSWORD", "correct-horse")
    client = TestClient(relay_main.app)
    headers = {"host": "network.beacontools.cc"}
    auth = ("admin", "correct-horse")
    install_id = "00000000-0000-0000-0000-000000000618"
    request_id = "req_mobile_standalone_manual"
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
            "mobile_standalone",
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
    status = client.get(
        "/v1/client/status",
        params={"install_id": install_id, "activation_token": payload["activation_token"]},
        headers={"host": "relay.beacontools.cc"},
    )
    assert status.status_code == 200
    assert status.json()["limits"]["schedule"] == 600
    assert status.json()["limits"]["radar"] == 3000


def test_admin_api_write_actions_tolerate_blank_optional_text(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ADMIN_PASSWORD", "correct-horse")
    client = TestClient(relay_main.app)
    headers = {"host": "network.beacontools.cc"}
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
        headers={"host": "network.beacontools.cc"},
    )

    assert response.status_code == 404


def test_relay_root_switches_by_hostname(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)

    public_response = client.get("/", headers={"host": "relay.beacontools.cc"})
    assert public_response.status_code == 200
    public_payload = public_response.json()
    assert public_payload["public_host"] == "relay.beacontools.cc"
    assert public_payload["admin_host"] == "network.beacontools.cc"

    admin_response = client.get("/", headers={"host": "network.beacontools.cc"}, follow_redirects=False)
    assert admin_response.status_code == 307
    assert admin_response.headers["location"] == "/admin"


def test_admin_auth_throttles_repeated_bad_passwords(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ADMIN_PASSWORD", "correct-horse")
    monkeypatch.setattr(relay_main, "_ADMIN_AUTH_FAILURE_LIMIT", 2)
    relay_main._admin_auth_failures.clear()
    client = TestClient(relay_main.app)

    first = client.get("/admin", headers={"host": "network.beacontools.cc"}, auth=("admin", "wrong"))
    second = client.get("/admin", headers={"host": "network.beacontools.cc"}, auth=("admin", "wrong"))
    third = client.get("/admin", headers={"host": "network.beacontools.cc"}, auth=("admin", "wrong"))

    assert first.status_code == 401
    assert second.status_code == 401
    assert third.status_code == 429


def test_activation_requests_persist_review_airport_fields(tmp_path: Path, monkeypatch) -> None:
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
        headers={"host": "relay.beacontools.cc", "x-forwarded-for": "203.0.113.55"},
    )
    assert response.status_code == 200

    conn = relay_main._connect()
    row = conn.execute(
        "SELECT airport_iata, airport_icao, display_name FROM activation_requests WHERE install_id=?",
        (install_id,),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["airport_iata"] == "ZRH"
    assert row["airport_icao"] == "LSZH"
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

    assert filed[0]["title"].startswith("[iOS][LAN Companion][Crash]")
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


def test_relay_reports_label_android_standalone_without_ios_title(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    _enable_reporter_env(monkeypatch)
    filed: list[dict[str, str]] = []
    monkeypatch.setattr(
        relay_main,
        "_post_linear_issue",
        lambda **kwargs: filed.append(kwargs) or "https://linear.test/android-standalone",
    )
    client = TestClient(relay_main.app)

    response = client.post(
        "/v1/reports",
        json=_report_payload(
            "00000000-0000-0000-0000-000000000310",
            report_type="manual",
            origin="android",
            context="mobile_standalone/manual",
            title="Standalone report",
            description="Standalone board did not refresh",
            client_context="App mode      Standalone relay\nMobile OS     Android 16 (phone)\nMobile ID     lfc_android_test",
        )
        | {
            "platform": "mobile_standalone",
            "os": "Android 16 (phone)",
            "api_mode": "relay",
        },
    )

    assert response.status_code == 200
    assert response.json()["team"] == "ios"
    assert filed[-1]["team_id"] == "team-ios"
    assert filed[-1]["title"].startswith("[Android][Standalone][Manual]")
    assert "**Origin:** android" in filed[-1]["description"]
    assert "**App mode:** Standalone" in filed[-1]["description"]
    assert "**Platform:** mobile_standalone" in filed[-1]["description"]
    assert "**OS:** Android 16 (phone)" in filed[-1]["description"]


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


def test_site_contact_sends_mailbox_message_and_routes_privacy(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_CONTACT_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("RELAY_CONTACT_SMTP_PORT", "587")
    monkeypatch.setenv("RELAY_CONTACT_SMTP_USERNAME", "smtp-user")
    monkeypatch.setenv("RELAY_CONTACT_SMTP_PASSWORD", "smtp-pass")
    monkeypatch.setenv("RELAY_CONTACT_FROM", "support@example.test")
    monkeypatch.setenv("RELAY_CONTACT_TO_GENERAL", "general@example.test")
    monkeypatch.setenv("RELAY_CONTACT_TO_PRIVACY", "privacy@example.test")
    sent: list[dict[str, object]] = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            self.host = host
            self.port = port
            self.timeout = timeout
            self.started_tls = False
            self.login_args: tuple[str, str] | None = None

        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> None:
            return None

        def starttls(self) -> None:
            self.started_tls = True

        def login(self, username: str, password: str) -> None:
            self.login_args = (username, password)

        def send_message(self, message) -> None:
            sent.append(
                {
                    "host": self.host,
                    "port": self.port,
                    "started_tls": self.started_tls,
                    "login_args": self.login_args,
                    "to": message["To"],
                    "reply_to": message["Reply-To"],
                    "subject": message["Subject"],
                    "body": message.get_content(),
                }
            )

    monkeypatch.setattr(relay_main.smtplib, "SMTP", FakeSMTP)
    client = TestClient(relay_main.app)

    response = client.post(
        "/v1/site/contact",
        json={
            "category": "privacy",
            "name": "Tester",
            "reply_email": "tester@example.test",
            "subject": "Data question",
            "message": "Can you help with privacy choices? RAPIDAPI_KEY=secret",
            "website_context": "/support/",
        },
        headers={"origin": "https://beacontools.cc", "fly-client-ip": "198.51.100.22"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "message": "Message sent. Thank you.", "deduped": False}
    assert sent
    assert sent[0]["to"] == "privacy@example.test"
    assert sent[0]["reply_to"] == "tester@example.test"
    assert sent[0]["started_tls"] is True
    assert sent[0]["login_args"] == ("smtp-user", "smtp-pass")
    assert "RAPIDAPI_KEY=secret" not in str(sent[0]["body"])
    assert "RAPIDAPI_KEY=[redacted]" in str(sent[0]["body"])


def test_site_contact_accepts_legacy_mail_secret_aliases(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SMTP_HOST", "smtp.alias.test")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USER", "alias-user")
    monkeypatch.setenv("SMTP_PASSWORD", "alias-pass")
    monkeypatch.setenv("SMTP_SECURITY", "ssl")
    monkeypatch.setenv("MAIL_FROM", "Beacon Tools <alias@example.test>")
    monkeypatch.setenv("MAIL_TO", "general@example.test")
    monkeypatch.setenv("PRIVACY_TO", "privacy@example.test")
    sent: list[dict[str, object]] = []

    class FakeSMTPSSL:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            self.host = host
            self.port = port
            self.timeout = timeout
            self.login_args: tuple[str, str] | None = None

        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> None:
            return None

        def login(self, username: str, password: str) -> None:
            self.login_args = (username, password)

        def send_message(self, message) -> None:
            sent.append(
                {
                    "host": self.host,
                    "port": self.port,
                    "login_args": self.login_args,
                    "to": message["To"],
                    "from": message["From"],
                }
            )

    monkeypatch.setattr(relay_main.smtplib, "SMTP_SSL", FakeSMTPSSL)
    client = TestClient(relay_main.app)

    response = client.post(
        "/v1/site/contact",
        json={
            "category": "general",
            "subject": "Alias smoke",
            "message": "Does the short SMTP secret set work?",
        },
        headers={"origin": "https://beacontools.cc", "fly-client-ip": "198.51.100.24"},
    )

    assert response.status_code == 200
    assert sent == [
        {
            "host": "smtp.alias.test",
            "port": 465,
            "login_args": ("alias-user", "alias-pass"),
            "to": "general@example.test",
            "from": "Beacon Tools <alias@example.test>",
        }
    ]


def test_site_contact_requires_config_and_blocks_abuse(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)
    payload = {
        "category": "general",
        "subject": "Hello",
        "message": "Support question",
    }

    missing_config = client.post(
        "/v1/site/contact",
        json=payload,
        headers={"origin": "https://beacontools.cc", "fly-client-ip": "198.51.100.33"},
    )
    honeypot = client.post(
        "/v1/site/contact",
        json={**payload, "company": "bot"},
        headers={"origin": "https://beacontools.cc", "fly-client-ip": "198.51.100.33"},
    )
    bad_origin = client.post(
        "/v1/site/contact",
        json=payload,
        headers={"origin": "https://evil.example", "fly-client-ip": "198.51.100.33"},
    )

    assert missing_config.status_code == 503
    assert honeypot.status_code == 400
    assert bad_origin.status_code == 403


def test_site_contact_rate_limits_by_network(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_SITE_CONTACT_NETWORK_DAILY_LIMIT", "1")
    monkeypatch.setenv("RELAY_CONTACT_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("RELAY_CONTACT_FROM", "support@example.test")
    monkeypatch.setenv("RELAY_CONTACT_TO_GENERAL", "general@example.test")
    monkeypatch.setattr(relay_main, "_send_contact_email", lambda *_args, **_kwargs: None)
    client = TestClient(relay_main.app)
    headers = {"origin": "https://beacontools.cc", "fly-client-ip": "198.51.100.44"}

    first = client.post(
        "/v1/site/contact",
        json={"category": "general", "subject": "One", "message": "First"},
        headers=headers,
    )
    second = client.post(
        "/v1/site/contact",
        json={"category": "general", "subject": "Two", "message": "Second"},
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 429


def test_site_bug_report_files_sanitized_linear_issue_without_install(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    _enable_reporter_env(monkeypatch)
    filed: list[dict[str, str]] = []
    monkeypatch.setattr(
        relay_main,
        "_post_linear_issue",
        lambda **kwargs: filed.append(kwargs) or "https://linear.test/public-site",
    )
    client = TestClient(relay_main.app)

    response = client.post(
        "/v1/site/bug-report",
        data={
            "title": "Matrix preview broke",
            "description": "The browser preview went blank.",
            "surface": "matrix",
            "app_version": "0.2.7",
            "platform": "Windows 11",
            "reply_email": "tester@example.test",
            "steps": "Open Matrix page",
            "expected": "Preview renders",
            "actual": "Canvas is empty",
        },
        files={
            "logs": (
                "localflight.log",
                b"RAPIDAPI_KEY=secret\nlin_api_abcdef\n192.168.1.44\nTraceback here",
                "text/plain",
            )
        },
        headers={"origin": "https://beacontools.cc", "fly-client-ip": "198.51.100.55"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "message": "Bug report sent. Thank you.", "deduped": False}
    assert filed
    assert filed[0]["team_id"] == "team-desktop"
    assert filed[0]["title"].startswith("[Web][Manual]")
    description = filed[0]["description"]
    assert "Matrix preview broke" in filed[0]["title"]
    assert "Sanitized uploaded log excerpts" in description
    assert "Traceback here" in description
    assert "secret" not in description
    assert "lin_api_abcdef" not in description
    assert "192.168.1.44" not in description
    assert "tester@example.test" in description
    assert "url" not in response.json()
    assert "team" not in response.json()


def test_site_bug_report_rejects_non_text_upload(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    _enable_reporter_env(monkeypatch)
    client = TestClient(relay_main.app)

    response = client.post(
        "/v1/site/bug-report",
        data={
            "title": "Bad upload",
            "description": "Binary file",
            "surface": "website",
        },
        files={"logs": ("screenshot.png", b"\x89PNG\x00\x00binary", "image/png")},
        headers={"origin": "https://beacontools.cc", "fly-client-ip": "198.51.100.66"},
    )

    assert response.status_code == 415


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
    admin = client.get("/admin", headers={"host": "network.beacontools.cc"}, auth=("admin", "correct-horse"))
    reports = client.get("/admin/api/reports", headers={"host": "network.beacontools.cc"}, auth=("admin", "correct-horse")).json()

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
    admin = client.get("/admin", headers={"host": "network.beacontools.cc"}, auth=("admin", "correct-horse"))
    reports = client.get("/admin/api/reports?sort=ts&dir=desc", headers={"host": "network.beacontools.cc"}, auth=("admin", "correct-horse")).json()

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
        headers={"host": "relay.beacontools.cc"},
    )

    assert response.status_code == 404


def test_raw_provider_debug_route_hidden_before_query_validation(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ALLOW_RAW_PROVIDER_DEBUG", "1")
    client = TestClient(relay_main.app)

    response = client.get("/v1/flights", headers={"host": "relay.beacontools.cc"})

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
        "airport_iata": "LHR",
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
        airport_iata="LHR",
        timezone_name="Europe/London",
        display_grace_minutes=30,
        display_horizon_hours=12,
    )
    relay_main._store_schedule_snapshot(
        cache_key=cache_key,
        airport_iata="LHR",
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
            "airport_iata": "LHR",
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
    assert upstream_calls[0]["timezone_name"] == "Europe/Zurich"

    conn = relay_main._connect()
    row = conn.execute("SELECT COUNT(*) AS n, MIN(timezone) AS timezone FROM schedule_snapshots").fetchone()
    conn.close()
    assert row is not None
    assert int(row["n"] or 0) == 1
    assert row["timezone"] == "Europe/Zurich"


def test_shared_schedule_upstream_fetch_adds_adaptive_pages_for_busy_departures(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
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


def test_shared_schedule_upstream_fetch_falls_back_to_undated_when_date_scope_is_empty_on_board(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _use_temp_db(tmp_path, monkeypatch)
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


def _aerodatabox_departure(scheduled: datetime, *, gate: object = None, aircraft: object = None) -> dict[str, object]:
    stamp = scheduled.astimezone(timezone.utc).replace(second=0, microsecond=0).isoformat()
    return {
        "number": "LX100",
        "callSign": "SWR100",
        "status": "Scheduled",
        "departure": {
            "airport": {"iata": "ZRH", "icao": "LSZH"},
            "scheduledTime": {"utc": stamp},
            "revisedTime": {"utc": stamp},
            "gate": gate,
            "terminal": None,
        },
        "arrival": {
            "airport": {"iata": "LHR", "icao": "EGLL"},
            "scheduledTime": {"utc": stamp},
        },
        "airline": {"name": "Swiss", "iata": "LX", "icao": "SWR"},
        "aircraft": {"icaoCode": aircraft} if aircraft else {},
    }


def test_aerodatabox_units_cap_blocks_before_outbound(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("AERODATABOX_API_KEY", "adb-test")
    monkeypatch.setenv("RELAY_SCHEDULE_PROVIDER", "aerodatabox")
    monkeypatch.setenv("RELAY_AERODATABOX_UPSTREAM_MONTHLY_UNITS_LIMIT", "1")
    client = TestClient(relay_main.app)
    outbound: list[object] = []

    def fake_get(*args, **kwargs):
        outbound.append((args, kwargs))
        raise AssertionError("cap should block before outbound HTTP")

    monkeypatch.setattr(relay_main._req, "get", fake_get)
    response = client.get(
        "/v1/schedule",
        params={
            "airport_iata": "ZRH",
            "timezone": "Europe/Zurich",
            "display_grace_minutes": 30,
            "display_horizon_hours": 12,
            "refresh_seconds": 3600,
            "install_id": "00000000-0000-0000-0000-000000000430",
        },
    )

    assert response.status_code == 503
    assert outbound == []


def test_aerodatabox_daily_units_cap_blocks_before_outbound(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("AERODATABOX_API_KEY", "adb-test")
    monkeypatch.setenv("RELAY_AERODATABOX_UPSTREAM_MONTHLY_UNITS_LIMIT", "24000")
    monkeypatch.setenv("RELAY_AERODATABOX_UPSTREAM_DAILY_UNITS_LIMIT", "1")
    outbound: list[object] = []

    def fake_get(*args, **kwargs):
        outbound.append((args, kwargs))
        raise AssertionError("daily cap should block before outbound HTTP")

    monkeypatch.setattr(relay_main._req, "get", fake_get)

    with pytest.raises(relay_main.UpstreamBudgetExceeded) as excinfo:
        relay_main._aerodatabox_upstream_payload(
            airport_iata="ZRH",
            display_grace_minutes=30,
            display_horizon_hours=12,
        )

    assert excinfo.value.period == "daily"
    assert outbound == []


def test_relay_aerodatabox_uses_apimarket_gateway_by_default(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("AERODATABOX_API_KEY", "adb-test")
    monkeypatch.delenv("RELAY_AERODATABOX_MARKETPLACE", raising=False)
    monkeypatch.delenv("AERODATABOX_MARKETPLACE", raising=False)
    captured: dict[str, object] = {}

    def fake_get(url, *, params, headers, timeout):
        captured.update({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return types.SimpleNamespace(status_code=200, json=lambda: {"departures": [], "arrivals": []})

    monkeypatch.setattr(relay_main._req, "get", fake_get)

    payload = relay_main._aerodatabox_upstream_payload(
        airport_iata="ZRH",
        display_grace_minutes=30,
        display_horizon_hours=12,
    )

    assert payload == {"departures": [], "arrivals": []}
    assert str(captured["url"]).startswith("https://prod.api.market/api/v1/aedbx/aerodatabox/")
    params = captured["params"]
    assert isinstance(params, dict)
    assert params["durationMinutes"] == 720
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["x-magicapi-key"] == "adb-test"
    assert "X-RapidAPI-Key" not in headers


def test_provider_circuit_breaker_blocks_before_budget_and_outbound(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("AERODATABOX_API_KEY", "adb-test")
    monkeypatch.setenv("RELAY_PROVIDER_FAILURE_COOLDOWN_SECONDS", "600")
    outbound: list[object] = []

    def fake_get(*args, **kwargs):
        outbound.append((args, kwargs))
        raise AssertionError("open circuit should block before outbound HTTP")

    monkeypatch.setattr(relay_main._req, "get", fake_get)
    for _ in range(3):
        relay_main._provider_circuit_record_failure("aerodatabox", "boom")

    with pytest.raises(HTTPException) as excinfo:
        relay_main._aerodatabox_upstream_payload(
            airport_iata="ZRH",
            display_grace_minutes=30,
            display_horizon_hours=12,
        )

    assert excinfo.value.status_code == 503
    assert outbound == []
    conn = relay_main._connect()
    units = conn.execute("SELECT calls FROM usage WHERE service='aerodatabox_upstream_units'").fetchone()
    conn.close()
    assert units is None


def test_schedule_unknown_airport_rejects_before_usage_or_upstream(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)
    monkeypatch.setattr(
        relay_main,
        "_fetch_shared_schedule_from_upstream",
        lambda **kwargs: pytest.fail("unknown airport must not reach upstream"),
    )

    response = client.get(
        "/v1/schedule",
        params={
            "airport_iata": "ZZZZ",
            "timezone": "UTC",
            "display_grace_minutes": 30,
            "display_horizon_hours": 12,
            "refresh_seconds": 3600,
            "install_id": "00000000-0000-0000-0000-000000000440",
        },
    )

    assert response.status_code == 400
    conn = relay_main._connect()
    usage_count = conn.execute("SELECT COUNT(*) FROM usage").fetchone()[0]
    snapshot_count = conn.execute("SELECT COUNT(*) FROM schedule_snapshots").fetchone()[0]
    conn.close()
    assert usage_count == 0
    assert snapshot_count == 0


def test_schedule_admission_buckets_windows_into_one_cache_key(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)
    upstream_calls: list[dict[str, object]] = []

    def fake_shared_fetch(**kwargs):
        upstream_calls.append(dict(kwargs))
        return _shared_snapshot_payload(pages_fetched=1)

    monkeypatch.setattr(relay_main, "_fetch_shared_schedule_from_upstream", fake_shared_fetch)
    base = {
        "airport_iata": "ZRH",
        "timezone": "Etc/DefinitelyWrong",
        "refresh_seconds": 3600,
        "install_id": "00000000-0000-0000-0000-000000000441",
    }

    first = client.get("/v1/schedule", params={**base, "display_grace_minutes": 31, "display_horizon_hours": 11})
    second = client.get("/v1/schedule", params={**base, "display_grace_minutes": 60, "display_horizon_hours": 12})

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(upstream_calls) == 1
    assert upstream_calls[0]["timezone_name"] == "Europe/Zurich"
    assert upstream_calls[0]["display_grace_minutes"] == 60
    assert upstream_calls[0]["display_horizon_hours"] == 12
    assert second.json()["cache_state"] == "fresh"


def test_schedule_install_rpm_limit_rejects_before_cache_or_upstream(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_SCHEDULE_INSTALL_RPM_LIMIT", "1")
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
        "install_id": "00000000-0000-0000-0000-000000000442",
    }

    first = client.get("/v1/schedule", params=params)
    second = client.get("/v1/schedule", params=params)

    assert first.status_code == 200
    assert second.status_code == 429
    assert len(upstream_calls) == 1


def test_schedule_new_cache_key_daily_limit_blocks_miss_explosions(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_SCHEDULE_NEW_KEYS_NETWORK_DAILY_LIMIT", "1")
    client = TestClient(relay_main.app)
    upstream_calls: list[dict[str, object]] = []

    def fake_shared_fetch(**kwargs):
        upstream_calls.append(dict(kwargs))
        return _shared_snapshot_payload(pages_fetched=1)

    monkeypatch.setattr(relay_main, "_fetch_shared_schedule_from_upstream", fake_shared_fetch)
    base = {
        "timezone": "UTC",
        "display_grace_minutes": 30,
        "display_horizon_hours": 12,
        "refresh_seconds": 3600,
        "install_id": "00000000-0000-0000-0000-000000000443",
    }

    first = client.get("/v1/schedule", params={**base, "airport_iata": "ZRH"})
    second = client.get("/v1/schedule", params={**base, "airport_iata": "LHR"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert len(upstream_calls) == 1


def test_community_schedule_zero_limit_rejects_before_upstream(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_COMMUNITY_SCHEDULE_LIMIT", "0")
    client = TestClient(relay_main.app)
    upstream_calls: list[dict[str, object]] = []
    monkeypatch.setattr(relay_main, "_fetch_shared_schedule_from_upstream", lambda **kwargs: upstream_calls.append(kwargs))

    response = client.get(
        "/v1/schedule",
        params={
            "airport_iata": "ZRH",
            "timezone": "Europe/Zurich",
            "display_grace_minutes": 30,
            "display_horizon_hours": 12,
            "refresh_seconds": 3600,
            "install_id": "00000000-0000-0000-0000-000000000447",
        },
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "86400"
    assert upstream_calls == []


def test_schedule_new_cache_key_zero_limit_blocks_unknown_lanes_before_upstream(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_SCHEDULE_NEW_KEYS_NETWORK_DAILY_LIMIT", "0")
    client = TestClient(relay_main.app)
    upstream_calls: list[dict[str, object]] = []
    monkeypatch.setattr(relay_main, "_fetch_shared_schedule_from_upstream", lambda **kwargs: upstream_calls.append(kwargs))

    response = client.get(
        "/v1/schedule",
        params={
            "airport_iata": "ZRH",
            "timezone": "Europe/Zurich",
            "display_grace_minutes": 30,
            "display_horizon_hours": 12,
            "refresh_seconds": 3600,
            "install_id": "00000000-0000-0000-0000-000000000448",
        },
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "86400"
    assert upstream_calls == []


def test_schedule_rpm_limit_includes_retry_after(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_SCHEDULE_INSTALL_RPM_LIMIT", "0")
    client = TestClient(relay_main.app)

    response = client.get(
        "/v1/schedule",
        params={
            "airport_iata": "ZRH",
            "timezone": "Europe/Zurich",
            "display_grace_minutes": 30,
            "display_horizon_hours": 12,
            "refresh_seconds": 3600,
            "install_id": "00000000-0000-0000-0000-000000000449",
        },
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"


def test_schedule_new_cache_key_marker_is_idempotent_and_sanitized(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_SCHEDULE_NEW_KEYS_NETWORK_DAILY_LIMIT", "1")
    cache_key = relay_main._schedule_cache_key(
        airport_iata="ZRH",
        timezone_name="Europe/Zurich",
        display_grace_minutes=30,
        display_horizon_hours=12,
    )

    relay_main._check_and_mark_new_schedule_cache_key(network_tag="not a real tag", cache_key=cache_key.upper())
    relay_main._check_and_mark_new_schedule_cache_key(network_tag="also-bad", cache_key=cache_key)

    day = relay_main._day_key()
    conn = relay_main._connect()
    rows = {
        (row["subject_key"], row["service"]): int(row["calls"] or 0)
        for row in conn.execute("SELECT subject_key, service, calls FROM usage WHERE month=?", (day,)).fetchall()
    }
    conn.close()

    assert rows[(f"schedule-new-key:{cache_key}", "schedule:new-cache-key-marker")] == 1
    assert rows[("schedule-new-key-network:unknown", "schedule:new-cache-key-network-day")] == 1
    assert rows[("schedule-new-key-global", "schedule:new-cache-key-global-day")] == 1


def test_schedule_new_cache_key_guard_rejects_malformed_keys_without_counters(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _use_temp_db(tmp_path, monkeypatch)

    with pytest.raises(HTTPException) as excinfo:
        relay_main._check_and_mark_new_schedule_cache_key(
            network_tag="net_1234567890abcd",
            cache_key="../not-a-cache-key",
        )

    assert excinfo.value.status_code == 400
    conn = relay_main._connect()
    count = conn.execute("SELECT COUNT(*) AS n FROM usage").fetchone()
    conn.close()
    assert count is not None
    assert int(count["n"] or 0) == 0


def test_schedule_new_cache_key_marker_survives_concurrent_first_seen(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_SCHEDULE_NEW_KEYS_NETWORK_DAILY_LIMIT", "1")
    cache_key = relay_main._schedule_cache_key(
        airport_iata="LHR",
        timezone_name="Europe/London",
        display_grace_minutes=30,
        display_horizon_hours=12,
    )
    errors: list[BaseException] = []

    def mark() -> None:
        try:
            relay_main._check_and_mark_new_schedule_cache_key(
                network_tag="net_1234567890abcd",
                cache_key=cache_key,
            )
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=mark) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    day = relay_main._day_key()
    conn = relay_main._connect()
    rows = {
        (row["subject_key"], row["service"]): int(row["calls"] or 0)
        for row in conn.execute("SELECT subject_key, service, calls FROM usage WHERE month=?", (day,)).fetchall()
    }
    conn.close()
    assert rows[(f"schedule-new-key:{cache_key}", "schedule:new-cache-key-marker")] == 1
    assert rows[("schedule-new-key-network:net_1234567890abcd", "schedule:new-cache-key-network-day")] == 1
    assert rows[("schedule-new-key-global", "schedule:new-cache-key-global-day")] == 1


def test_relay_schedule_cache_tables_have_expected_working_columns(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    conn = relay_main._connect()
    schedule_columns = relay_main._table_columns(conn, "schedule_snapshots")
    provider_columns = relay_main._table_columns(conn, "provider_schedule_snapshots")
    interest_columns = relay_main._table_columns(conn, "client_interests")
    usage_indexes = [
        str(row["name"])
        for row in conn.execute("PRAGMA index_list(usage)").fetchall()
    ]
    conn.close()

    assert {
        "cache_key",
        "airport_iata",
        "timezone",
        "display_grace_minutes",
        "display_horizon_hours",
        "planner_version",
        "schema_version",
        "provider",
        "generated_at",
        "meta_json",
        "records_json",
        "client_accesses",
        "upstream_pulls",
        "refresh_count",
        "cache_hits",
        "stale_serves",
        "last_cache_state",
        "last_error",
    }.issubset(schedule_columns)
    assert {
        "cache_key",
        "provider",
        "airport_iata",
        "timezone",
        "display_grace_minutes",
        "display_horizon_hours",
        "policy_version",
        "meta_json",
        "records_json",
        "refresh_count",
        "last_error",
    }.issubset(provider_columns)
    assert {"install_id", "plan", "airport_iata", "refresh_seconds", "last_seen"}.issubset(interest_columns)
    assert any("sqlite_autoindex_usage" in name for name in usage_indexes)


def test_aerodatabox_fresh_cache_avoids_upstream(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("AERODATABOX_API_KEY", "adb-test")
    monkeypatch.setenv("RELAY_SCHEDULE_PROVIDER", "aerodatabox")
    client = TestClient(relay_main.app)
    scheduled = datetime(2026, 5, 12, 10, 0, tzinfo=timezone.utc)
    outbound: list[str] = []

    def fake_get(url, *, params, headers, timeout):
        outbound.append(url)
        return types.SimpleNamespace(
            status_code=200,
            json=lambda: {"departures": [_aerodatabox_departure(scheduled, gate="A42", aircraft="A333")], "arrivals": []},
        )

    monkeypatch.setattr(relay_main._req, "get", fake_get)
    params = {
        "airport_iata": "ZRH",
        "timezone": "Europe/Zurich",
        "display_grace_minutes": 30,
        "display_horizon_hours": 12,
        "refresh_seconds": 3600,
        "install_id": "00000000-0000-0000-0000-000000000431",
    }

    first = client.get("/v1/schedule", params=params)
    second = client.get("/v1/schedule", params=params)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["provider"] == "aerodatabox"
    assert second.json()["cache_state"] == "fresh"
    assert len(outbound) == 1


def test_aerodatabox_stale_cache_served_when_capped(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("AERODATABOX_API_KEY", "adb-test")
    monkeypatch.setenv("RELAY_SCHEDULE_PROVIDER", "aerodatabox")
    monkeypatch.setenv("RELAY_AERODATABOX_UPSTREAM_MONTHLY_UNITS_LIMIT", "2")
    monkeypatch.setenv("RELAY_AERODATABOX_UPSTREAM_DAILY_UNITS_LIMIT", "2")
    client = TestClient(relay_main.app)
    scheduled = datetime(2026, 5, 12, 10, 0, tzinfo=timezone.utc)
    outbound: list[str] = []

    def fake_get(url, *, params, headers, timeout):
        outbound.append(url)
        return types.SimpleNamespace(
            status_code=200,
            json=lambda: {"departures": [_aerodatabox_departure(scheduled, gate="A42", aircraft="A333")], "arrivals": []},
        )

    monkeypatch.setattr(relay_main._req, "get", fake_get)
    params = {
        "airport_iata": "ZRH",
        "timezone": "Europe/Zurich",
        "display_grace_minutes": 30,
        "display_horizon_hours": 12,
        "refresh_seconds": 3600,
        "install_id": "00000000-0000-0000-0000-000000000432",
    }
    seed = client.get("/v1/schedule", params=params)
    assert seed.status_code == 200

    stale_at = (relay_main.datetime.now(relay_main.timezone.utc) - relay_main.timedelta(minutes=70)).isoformat()
    conn = relay_main._connect()
    conn.execute("UPDATE schedule_snapshots SET generated_at=?, updated_at=?", (stale_at, relay_main._utc_now()))
    conn.execute("UPDATE provider_schedule_snapshots SET generated_at=?, updated_at=?", (stale_at, relay_main._utc_now()))
    conn.commit()
    conn.close()

    stale = client.get("/v1/schedule", params=params)

    assert stale.status_code == 200
    payload = stale.json()
    assert payload["cache_state"] == "stale"
    assert payload["meta"]["stale_reason"] == "budget_limited"
    assert payload["meta"]["budget_limited_providers"] == ["aerodatabox"]
    assert len(outbound) == 1


def test_sparse_schedule_refresh_does_not_overwrite_healthy_cache(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)
    records = []
    for idx in range(12):
        row = dict(_shared_snapshot_payload(pages_fetched=1)["records"][0])
        row["callsign"] = f"SWR{100 + idx}"
        row["flight_number"] = f"LX{100 + idx}"
        row["scheduled"] = f"2026-05-01T{10 + (idx % 8):02d}:00:00+00:00"
        records.append(row)
    cache_key = relay_main._schedule_cache_key(
        airport_iata="ZRH",
        timezone_name="Europe/Zurich",
        display_grace_minutes=30,
        display_horizon_hours=12,
    )
    healthy = _shared_snapshot_payload(pages_fetched=1)
    healthy["records"] = records
    relay_main._store_schedule_snapshot(
        cache_key=cache_key,
        airport_iata="ZRH",
        timezone_name="Europe/Zurich",
        display_grace_minutes=30,
        display_horizon_hours=12,
        payload=healthy,
        pages_fetched=1,
    )
    stale_at = (relay_main.datetime.now(relay_main.timezone.utc) - relay_main.timedelta(minutes=70)).isoformat()
    conn = relay_main._connect()
    conn.execute("UPDATE schedule_snapshots SET generated_at=?, updated_at=?", (stale_at, relay_main._utc_now()))
    conn.commit()
    conn.close()

    sparse = _shared_snapshot_payload(pages_fetched=1)
    sparse["records"] = [records[0]]
    monkeypatch.setattr(relay_main, "_fetch_shared_schedule_from_upstream", lambda **kwargs: sparse)

    response = client.get(
        "/v1/schedule",
        params={
            "airport_iata": "ZRH",
            "timezone": "Europe/Zurich",
            "display_grace_minutes": 30,
            "display_horizon_hours": 12,
            "refresh_seconds": 3600,
            "install_id": "00000000-0000-0000-0000-000000000444",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["cache_state"] == "stale"
    assert payload["meta"]["stale_reason"] == "suspicious_sparse_refresh"
    assert len(payload["records"]) == 12
    conn = relay_main._connect()
    row = conn.execute("SELECT records_json, last_error FROM schedule_snapshots WHERE cache_key=?", (cache_key,)).fetchone()
    conn.close()
    assert row is not None
    assert len(json.loads(row["records_json"])) == 12
    assert "sparse" in str(row["last_error"])


def test_aerodatabox_auto_fuses_aviationstack_fill(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("AERODATABOX_API_KEY", "adb-test")
    monkeypatch.setenv("AVIATIONSTACK_API_KEY", "avi-test")
    monkeypatch.setenv("RELAY_SCHEDULE_PROVIDER", "auto")
    scheduled = datetime.now(timezone.utc).replace(second=0, microsecond=0)

    def fake_get(url, *, params, headers, timeout):
        if "aerodatabox" in url:
            return types.SimpleNamespace(
                status_code=200,
                json=lambda: {"departures": [_aerodatabox_departure(scheduled)], "arrivals": []},
            )
        rows = []
        if params.get("dep_iata") == "ZRH" and params.get("flight_date") == scheduled.date().isoformat() and int(params.get("offset", 0) or 0) == 0:
            rows = [_aviationstack_departure("100", scheduled)]
        return types.SimpleNamespace(status_code=200, json=lambda: {"data": rows})

    monkeypatch.setattr(relay_main._req, "get", fake_get)
    payload = relay_main._fetch_shared_schedule_from_upstream(
        airport_iata="ZRH",
        timezone_name="UTC",
        display_grace_minutes=30,
        display_horizon_hours=12,
    )

    assert payload["provider"] == "aerodatabox+aviationstack"
    assert payload["meta"]["providers_used"] == ["aerodatabox", "aviationstack"]
    assert payload["meta"]["provider_record_counts"]["aerodatabox"] == 1
    assert payload["meta"]["provider_record_counts"]["aviationstack"] >= 1
    assert payload["records"][0]["gate"] == "A1"
    assert payload["records"][0]["aircraft_type"] == "A320"
    assert payload["records"][0]["status"] == "scheduled"


def test_upstream_budget_guard_is_atomic(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    results: list[str] = []

    def consume() -> None:
        try:
            relay_main._check_and_increment_upstream_budget(
                provider="aerodatabox",
                service="aerodatabox_upstream_units",
                n_calls=1,
                monthly_limit=2,
            )
            results.append("ok")
        except relay_main.UpstreamBudgetExceeded:
            results.append("capped")

    threads = [threading.Thread(target=consume) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    conn = relay_main._connect()
    row = conn.execute("SELECT calls FROM usage WHERE service='aerodatabox_upstream_units'").fetchone()
    conn.close()
    assert results.count("ok") == 2
    assert results.count("capped") == 4
    assert row is not None and int(row["calls"] or 0) == 2


def test_aviationstack_upstream_cap_blocks_adaptive_pages_before_outbound(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_AVIATIONSTACK_UPSTREAM_MONTHLY_LIMIT", "1")
    monkeypatch.setattr(relay_main, "_aviationstack_key", lambda: "relay-key-123")
    captured: list[dict[str, object]] = []
    scheduled = datetime.now(timezone.utc).replace(second=0, microsecond=0)

    def fake_get(url, *, params, headers, timeout):
        captured.append(dict(params))
        return types.SimpleNamespace(
            status_code=200,
            json=lambda: {"data": [_aviationstack_departure("100", scheduled) for _ in range(int(params.get("limit", 100) or 100))]},
        )

    monkeypatch.setattr(relay_main._req, "get", fake_get)
    with pytest.raises(relay_main.UpstreamBudgetExceeded):
        relay_main._fetch_aviationstack_schedule_source_from_upstream(
            airport_iata="ZRH",
            timezone_name="UTC",
            display_grace_minutes=30,
            display_horizon_hours=12,
        )

    assert len(captured) == 1


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
    conn = relay_main._connect()
    row = conn.execute(
        "SELECT last_checkin_at, last_relay_activity_at FROM install_profiles WHERE install_id=?",
        (install_id,),
    ).fetchone()
    conn.close()
    assert row["last_checkin_at"]
    assert row["last_relay_activity_at"]


def test_client_checkin_records_redacted_fleet_profile_and_preserves_first_seen(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ADMIN_PASSWORD", "correct-horse")
    client = TestClient(relay_main.app)
    headers = {"host": "network.beacontools.cc"}
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
    assert row["last_checkin_at"]
    assert row["presence_source"] == "checkin"
    assert row["presence_status"] == "fresh"
    assert row["last_heartbeat_at"] == ""
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
    assert updated["last_checkin_at"] >= row["last_checkin_at"]


def test_relay_airport_search_and_resolve_for_mobile_setup(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)

    search = client.get("/v1/airports/search", params={"q": "Zurich"})
    assert search.status_code == 200
    assert any(row["iata"] == "ZRH" and row["timezone"] for row in search.json())

    resolved = client.get("/v1/airports/resolve", params={"q": "ZRH"})
    assert resolved.status_code == 200
    payload = resolved.json()
    assert payload["iata"] == "ZRH"
    assert payload["icao"] == "LSZH"
    assert payload["lat"] is not None
    assert payload["lon"] is not None


def _activate_mobile_standalone(client: TestClient, install_id: str) -> str:
    response = client.post(
        "/v1/activate",
        json={
            "install_id": install_id,
            "install_fingerprint": relay_main._install_fingerprint(install_id),
            "airport_iata": "ZRH",
            "airport_icao": "LSZH",
            "timezone": "Europe/Zurich",
            "device_type": "phone",
            "display_name": "Mobile standalone",
            "requested_mode": "mobile_standalone",
            "app_version": "0.2.6",
        },
    )
    assert response.status_code == 200
    return str(response.json()["activation_token"])


def test_mobile_standalone_fids_uses_shared_schedule_and_three_hour_policy(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)
    install_id = "00000000-0000-0000-0000-000000000902"
    token = _activate_mobile_standalone(client, install_id)

    def fake_shared_fetch(**kwargs):
        payload = _shared_snapshot_payload()
        stamp = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(microsecond=0).isoformat()
        for row in payload["records"]:
            row["scheduled"] = stamp
            row["estimated"] = stamp
        return payload

    monkeypatch.setattr(relay_main, "_fetch_shared_schedule_from_upstream", fake_shared_fetch)

    response = client.get(
        "/v1/mobile/fids",
        params={
            "install_id": install_id,
            "activation_token": token,
            "app_version": "0.2.6",
            "client_kind": "mobile_standalone",
            "airport_iata": "ZRH",
            "timezone": "Europe/Zurich",
            "view": "departures",
        },
    )

    assert response.status_code == 200
    rows = response.json()
    assert rows and rows[0]["callsign"] == "SWR100"

    conn = relay_main._connect()
    interest = conn.execute(
        "SELECT client_kind, refresh_seconds FROM client_interests WHERE install_id=?",
        (install_id,),
    ).fetchone()
    conn.close()
    assert interest["client_kind"] == "mobile_standalone"
    assert int(interest["refresh_seconds"]) == 10800


def test_mobile_standalone_rejects_non_uuid_install_ids(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)

    response = client.get(
        "/v1/mobile/fids",
        params={
            "install_id": "not-a-uuid",
            "activation_token": "lfm_fake",
            "app_version": "0.2.6",
            "client_kind": "mobile_standalone",
            "airport_iata": "ZRH",
            "timezone": "Europe/Zurich",
            "view": "departures",
        },
    )

    assert response.status_code == 400


def test_mobile_iap_verify_rejects_unknown_products() -> None:
    client = TestClient(relay_main.app)
    response = client.post(
        "/v1/mobile/iap/apple/verify",
        json={
            "install_id": "00000000-0000-0000-0000-000000000904",
            "app_account_token": "00000000-0000-0000-0000-000000000904",
            "app_version": "0.2.7",
            "product_id": "cc.beacontools.localflight.tip.999",
            "transaction_id": "1000000000000001",
            "signed_transaction_info": "signed-jws-placeholder",
            "environment": "sandbox",
        },
    )

    assert response.status_code == 400


def test_mobile_iap_verify_is_scaffolded_until_apple_credentials_exist() -> None:
    client = TestClient(relay_main.app)
    response = client.post(
        "/v1/mobile/iap/apple/verify",
        json={
            "install_id": "00000000-0000-0000-0000-000000000905",
            "app_account_token": "00000000-0000-0000-0000-000000000905",
            "app_version": "0.2.7",
            "product_id": "cc.beacontools.localflight.tip.5",
            "transaction_id": "1000000000000002",
            "original_transaction_id": "1000000000000002",
            "signed_transaction_info": "signed-jws-placeholder",
            "environment": "sandbox",
        },
    )

    assert response.status_code == 503
    assert "scaffolded" in response.json()["detail"]


def test_mobile_standalone_radar_limits_radii_and_serves_cache(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)
    install_id = "00000000-0000-0000-0000-000000000903"
    token = _activate_mobile_standalone(client, install_id)
    upstream_calls: list[tuple[float, float, float]] = []

    def fake_adsbx(lat: float, lon: float, radius_nm: float) -> bytes:
        upstream_calls.append((lat, lon, radius_nm))
        return json.dumps({
            "ac": [
                {
                    "flight": "SWR42",
                    "hex": "4b1800",
                    "lat": 47.46,
                    "lon": 8.56,
                    "alt_baro": 3000,
                    "gs": 140,
                    "track": 90,
                }
            ]
        }).encode("utf-8")

    monkeypatch.setattr(relay_main, "_fetch_adsbx_payload", fake_adsbx)
    params = {
        "install_id": install_id,
        "activation_token": token,
        "app_version": "0.2.6",
        "client_kind": "mobile_standalone",
        "airport_iata": "ZRH",
        "radius_nm": 3,
    }

    rejected = client.get("/v1/mobile/radar", params={**params, "radius_nm": 20})
    assert rejected.status_code == 422

    first = client.get("/v1/mobile/radar", params=params)
    second = client.get("/v1/mobile/radar", params=params)
    unauthenticated_cache_probe = client.get("/v1/mobile/radar", params={**params, "activation_token": ""})

    assert first.status_code == 200
    assert first.json()["radius_nm"] == 3
    assert first.json()["refresh_after_s"] == 300
    assert first.json()["count"] == 1
    assert second.status_code == 200
    assert second.headers["x-lf-mobile-standalone-cache"] == "hit"
    assert unauthenticated_cache_probe.status_code == 403
    assert len(upstream_calls) == 1


def test_admin_fleet_install_refs_support_actions(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ADMIN_PASSWORD", "correct-horse")
    client = TestClient(relay_main.app)
    headers = {"host": "network.beacontools.cc"}
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


def test_admin_overview_exposes_heartbeat_summary_without_private_ids(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ADMIN_PASSWORD", "correct-horse")
    client = TestClient(relay_main.app)
    headers = {"host": "network.beacontools.cc"}
    auth = ("admin", "correct-horse")
    install_id = "00000000-0000-0000-0000-000000000408"

    heartbeat = client.post(
        "/v1/heartbeat",
        json={"install_id": install_id, "app_version": "0.2.7", "os_family": "Windows"},
    )
    assert heartbeat.status_code == 200

    overview = client.get("/admin/api/overview", headers=headers, auth=auth).json()
    combined = json.dumps(overview)

    assert overview["heartbeat"]["fresh"] == 1
    assert overview["heartbeat"]["latest_heartbeat_at"]
    assert overview["heartbeat"]["cadence_seconds"] == 1800
    assert overview["heartbeat"]["cooldown_seconds"] == relay_main._HEARTBEAT_MIN_INTERVAL_S
    assert install_id not in combined


def test_admin_fleet_supports_server_filters_pagination_and_facets(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ADMIN_PASSWORD", "correct-horse")
    client = TestClient(relay_main.app)
    headers = {"host": "network.beacontools.cc"}
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
    assert filtered["facets"]["presence_status"] == {"fresh": 1}
    assert filtered["rows"][0]["presence_source"] == "checkin"
    assert filtered["facets"]["has_companion"]["yes"] == 1
    assert "00000000-0000-0000-0000-000000001003" not in combined

    presence_filtered = client.get(
        "/admin/api/fleet?presence_status=fresh&presence_source=checkin",
        headers=headers,
        auth=auth,
    ).json()
    assert presence_filtered["filtered_estimate"] == 4

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
    response = client.get("/admin", headers={"host": "network.beacontools.cc"}, auth=("admin", "correct-horse"))
    text = response.text

    assert response.status_code == 200
    assert "Presence is coarse" in text
    assert "statusRailEl" in text
    assert "Heartbeat pipeline" in text
    assert "Missing heartbeat" in text
    assert "detail-block" in text
    assert '"/admin/api/fleet"' in text
    assert "quickViewDefs" in text
    assert "data-filter" in text
    assert "Provider State" not in text
