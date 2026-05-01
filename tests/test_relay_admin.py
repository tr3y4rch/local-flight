from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
        "app_version": "0.2.5b1",
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

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["deduped"] is True
    assert admin.status_code == 200
    assert "Report gateway (24h)" in admin.text
    assert "Recent report events" in admin.text
    assert "Report dedupe groups" in admin.text
    assert "filed" in admin.text
    assert "deduped" in admin.text
    assert "web/feedback" in admin.text


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

    assert old_report.status_code == 200
    assert new_report.status_code == 200
    assert admin.status_code == 200
    assert admin.text.index("web/feedback-new") < admin.text.index("web/feedback-old")


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
    start = datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc)
    captured: list[dict[str, object]] = []

    def fake_get(url, *, params, headers, timeout):
        captured.append(dict(params))
        limit = int(params.get("limit", 100) or 100)
        offset = int(params.get("offset", 0) or 0)
        if params.get("dep_iata") == "ZRH" and params.get("flight_date") == "2026-05-01" and offset < 500:
            rows = [
                _aviationstack_departure(
                    str(1000 + offset + idx),
                    start + timedelta(minutes=offset + idx),
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
    assert meta["pages_by_scope"]["departures:2026-05-01"] >= 5
    assert meta["pages_by_scope"]["arrivals:2026-05-01"] == 1
    assert len(payload["records"]) == 500
    assert any(
        params.get("dep_iata") == "ZRH" and int(params.get("offset", 0) or 0) == 400
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
