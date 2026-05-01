from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

import localflight.scheduler.jobs as jobs
import localflight.scheduler.runtime as runtime
import localflight.sources.web.adsbexchange_client as adsbexchange_client
import localflight.sources.web.aviationstack_client as aviationstack_client
import localflight.sources.web.bug_reporter as bug_reporter
import localflight.sources.web.relay_defaults as relay_defaults
import localflight.storage.config as storage_config
import localflight.storage.flights_store as flights_store
import localflight.ui.api as ui_api
import localflight.ui.server as ui_server
import relay.main as relay_main
from localflight.core.models import AirportRef, Flight, FlightDirection, FlightTime
from localflight.storage.config import AppConfig
from localflight.storage.state import AppState
from localflight.ui.server import app


def _flight(callsign: str = "SWR184") -> Flight:
    return Flight(
        direction=FlightDirection.DEPARTURE,
        airport=AirportRef(iata="ZRH", icao="LSZH"),
        callsign=callsign,
        destination=AirportRef(iata="LHR", icao="EGLL"),
        times=FlightTime(scheduled=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)),
        source="test",
    )


def test_save_snapshot_uses_canonical_user_storage(tmp_path: Path, monkeypatch) -> None:
    config_file = tmp_path / ".localflight" / "config.json"
    legacy_root = tmp_path / "legacy-storage"

    monkeypatch.setattr(flights_store, "config_path", lambda: config_file)
    monkeypatch.setattr(flights_store, "_legacy_store_root", lambda: legacy_root)

    written = flights_store.save_snapshot(
        "ZRH",
        [_flight()],
        at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
    )

    assert written == (
        tmp_path
        / ".localflight"
        / "storage"
        / "data"
        / "ZRH"
        / "snapshots"
        / "20260102T030405Z.json"
    )
    assert written.exists()


def test_load_latest_snapshot_path_reads_legacy_snapshots_during_migration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_file = tmp_path / ".localflight" / "config.json"
    legacy_root = tmp_path / "legacy-storage"

    monkeypatch.setattr(flights_store, "config_path", lambda: config_file)
    monkeypatch.setattr(flights_store, "_legacy_store_root", lambda: legacy_root)

    canonical = (
        tmp_path
        / ".localflight"
        / "storage"
        / "data"
        / "ZRH"
        / "snapshots"
        / "20260102T030405Z.json"
    )
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text(json.dumps({"flights": []}), encoding="utf-8")

    legacy = legacy_root / "ZRH" / "snapshots" / "20260102T040405Z.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps({"flights": []}), encoding="utf-8")

    assert flights_store.load_latest_snapshot_path("ZRH") == legacy


def test_run_snapshot_job_prunes_snapshots_in_all_entrypoints(monkeypatch) -> None:
    prune_calls: list[tuple[str, int]] = []

    monkeypatch.setattr(jobs, "_fetch_real", lambda cfg: [_flight()])
    monkeypatch.setattr(jobs, "save_snapshot", lambda *args, **kwargs: Path("snapshot.json"))
    monkeypatch.setattr(jobs, "prune_snapshots", lambda airport_iata, keep_hours=24: prune_calls.append((airport_iata, keep_hours)) or 0)
    monkeypatch.setattr(jobs, "_write_history", lambda flights, cfg: None)
    monkeypatch.setattr(jobs, "_broadcast_update", lambda flights, cfg: None)

    jobs.run_snapshot_job(AppConfig(airport_iata="ZRH", airport_icao="LSZH", source="real"))

    assert prune_calls == [("ZRH", 24)]


def test_run_loop_preserves_last_success_when_a_cycle_fails(monkeypatch) -> None:
    saved_states: list[AppState] = []

    class _Logger:
        def info(self, *args, **kwargs) -> None:
            pass

        def exception(self, *args, **kwargs) -> None:
            pass

    monkeypatch.setattr(runtime, "setup_logging", lambda: _Logger())
    monkeypatch.setattr(runtime, "load_config", lambda: AppConfig())
    monkeypatch.setattr(
        runtime,
        "load_state",
        lambda: AppState(
            ok=True,
            last_success_utc="2026-01-01T00:00:00Z",
        ),
    )
    monkeypatch.setattr(runtime, "save_state", saved_states.append)

    def _boom(cfg: AppConfig) -> None:
        raise RuntimeError("boom")

    runtime.run_loop(fetch=_boom, once=True, source_name="real")

    assert saved_states
    assert saved_states[0].ok is False
    assert saved_states[0].last_success_utc == "2026-01-01T00:00:00Z"


def test_api_config_get_route_is_registered_once() -> None:
    routes = [
        route
        for route in app.router.routes
        if getattr(route, "path", None) == "/api/config"
        and "GET" in (getattr(route, "methods", set()) or set())
    ]

    assert len(routes) == 1
    assert routes[0].endpoint.__name__ == "api_get_config"


def test_aviationstack_usage_stats_report_separate_buckets(monkeypatch) -> None:
    monkeypatch.setattr(
        aviationstack_client,
        "_load_usage",
        lambda: {
            "relay": {
                "period_start": "2026-04-01T00:00:00+00:00",
                "period_end": "2026-05-01T00:00:00+00:00",
                "calls": 12,
                "limit": 50,
                "period_days": 30,
            },
            "aviationstack": {"2026-04": 34},
        },
    )
    monkeypatch.setattr(aviationstack_client, "_utc_now", lambda: datetime(2026, 4, 15, tzinfo=timezone.utc))
    monkeypatch.setattr(aviationstack_client, "_month_key", lambda: "2026-04")
    monkeypatch.setattr(aviationstack_client, "_get_relay_limit", lambda: 50)
    monkeypatch.setattr(aviationstack_client, "_get_byok_limit", lambda: 90)
    monkeypatch.setattr(aviationstack_client, "_get_relay_url", lambda: "https://localflight-community-relay.fly.dev/v1/flights")
    monkeypatch.setattr(aviationstack_client, "_has_enabled_byok_key", lambda: False)
    monkeypatch.setattr(aviationstack_client, "_has_api_key", lambda: False)
    monkeypatch.setattr(aviationstack_client, "_has_community_api_key", lambda: False)
    monkeypatch.setattr(aviationstack_client, "_get_activation_token", lambda: "")
    monkeypatch.setattr(aviationstack_client, "_is_enabled", lambda: False)

    community_stats = aviationstack_client.get_usage_stats("real")
    assert community_stats["active_mode"] == "community"
    assert community_stats["community"]["calls_this_month"] == 12
    assert community_stats["community"]["monthly_limit"] == 50
    assert community_stats["byok"]["calls_this_month"] == 34
    assert community_stats["byok"]["monthly_limit"] == 90
    assert community_stats["byok"]["ui_monthly_max"] == 100

    virtual_stats = aviationstack_client.get_usage_stats("virtual")
    assert virtual_stats["active_mode"] == "virtual"
    assert virtual_stats["calls_this_month"] == 0
    assert virtual_stats["monthly_limit"] == 0


def test_fetch_flights_once_prefers_managed_relay_before_local_community_key(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(aviationstack_client, "_has_enabled_byok_key", lambda: False)
    monkeypatch.setattr(aviationstack_client, "_has_activation_token", lambda: True)
    monkeypatch.setattr(aviationstack_client, "_has_community_api_key", lambda: True)
    monkeypatch.setattr(
        aviationstack_client,
        "_fetch_community_direct",
        lambda **kwargs: calls.append("community") or {"data": []},
    )
    monkeypatch.setattr(
        aviationstack_client,
        "_fetch_relay",
        lambda **kwargs: calls.append("relay") or {"data": []},
    )

    result = aviationstack_client.fetch_flights_once(airport_iata="ZRH")

    assert result == {"data": []}
    assert calls == ["relay"]


def test_aviationstack_usage_stats_use_managed_bucket_when_token_present(monkeypatch) -> None:
    monkeypatch.setattr(
        aviationstack_client,
        "_load_usage",
        lambda: {
            "relay": {
                "period_start": "2026-04-01T00:00:00+00:00",
                "period_end": "2026-05-01T00:00:00+00:00",
                "calls": 112,
                "limit": 50,
                "period_days": 30,
            },
            "relay_managed": {"2026-04": 3},
            "relay_managed_limits": {"2026-04": 10000},
            "aviationstack": {"2026-04": 8},
        },
    )
    monkeypatch.setattr(aviationstack_client, "_utc_now", lambda: datetime(2026, 4, 15, tzinfo=timezone.utc))
    monkeypatch.setattr(aviationstack_client, "_month_key", lambda: "2026-04")
    monkeypatch.setattr(aviationstack_client, "_get_relay_limit", lambda: 50)
    monkeypatch.setattr(aviationstack_client, "_get_byok_limit", lambda: 90)
    monkeypatch.setattr(aviationstack_client, "_has_enabled_byok_key", lambda: False)
    monkeypatch.setattr(aviationstack_client, "_has_api_key", lambda: False)
    monkeypatch.setattr(aviationstack_client, "_has_community_api_key", lambda: True)
    monkeypatch.setattr(aviationstack_client, "_get_activation_token", lambda: "lfm_test_token")
    monkeypatch.setattr(
        aviationstack_client,
        "_fetch_managed_status",
        lambda timeout_s=8: {
            "ok": True,
            "limits": {"schedule": 10000},
            "providers": {"aviationstack": True, "adsbexchange": True},
            "token_prefix": "lfm_test",
        },
    )

    stats = aviationstack_client.get_usage_stats("real")

    assert stats["active_mode"] == "managed"
    assert stats["calls_this_month"] == 3
    assert stats["monthly_limit"] == 10000
    assert stats["managed"]["token_prefix"] == "lfm_test"
    assert stats["managed"]["providers"]["aviationstack"] is True


def test_community_budget_uses_rolling_30_day_window(monkeypatch) -> None:
    saved: dict[str, object] = {}

    monkeypatch.setattr(
        aviationstack_client,
        "_load_usage",
        lambda: {
            "relay": {
                "period_start": "2026-03-01T00:00:00+00:00",
                "period_end": "2026-03-31T00:00:00+00:00",
                "calls": 49,
                "limit": 50,
                "period_days": 30,
            }
        },
    )
    monkeypatch.setattr(aviationstack_client, "_save_usage", lambda data: saved.update(data))
    monkeypatch.setattr(aviationstack_client, "_utc_now", lambda: datetime(2026, 4, 5, tzinfo=timezone.utc))

    aviationstack_client._increment_community_budget(50)

    relay = saved["relay"]
    assert isinstance(relay, dict)
    assert relay["calls"] == 1
    assert relay["limit"] == 50
    assert relay["period_days"] == 30


def test_virtual_mode_does_not_clear_community_budget_memory(monkeypatch) -> None:
    monkeypatch.setattr(
        aviationstack_client,
        "_load_usage",
        lambda: {
            "relay": {
                "period_start": "2026-04-10T00:00:00+00:00",
                "period_end": "2026-05-10T00:00:00+00:00",
                "calls": 17,
                "limit": 50,
                "period_days": 30,
            }
        },
    )
    monkeypatch.setattr(aviationstack_client, "_utc_now", lambda: datetime(2026, 4, 20, tzinfo=timezone.utc))
    monkeypatch.setattr(aviationstack_client, "_get_relay_limit", lambda: 50)
    monkeypatch.setattr(aviationstack_client, "_get_byok_limit", lambda: 90)
    monkeypatch.setattr(aviationstack_client, "_get_relay_url", lambda: "https://localflight-community-relay.fly.dev/v1/flights")
    monkeypatch.setattr(aviationstack_client, "_has_enabled_byok_key", lambda: False)
    monkeypatch.setattr(aviationstack_client, "_has_api_key", lambda: False)
    monkeypatch.setattr(aviationstack_client, "_has_community_api_key", lambda: False)
    monkeypatch.setattr(aviationstack_client, "_get_activation_token", lambda: "")
    monkeypatch.setattr(aviationstack_client, "_is_enabled", lambda: False)

    virtual_stats = aviationstack_client.get_usage_stats("virtual")
    community_stats = aviationstack_client.get_usage_stats("real")

    assert virtual_stats["active_mode"] == "virtual"
    assert virtual_stats["calls_this_month"] == 0
    assert community_stats["active_mode"] == "community"
    assert community_stats["calls_this_month"] == 17
    assert community_stats["remaining"] == 33


def test_api_radar_virtual_uses_vatsim_only(monkeypatch) -> None:
    monkeypatch.setattr(
        ui_api,
        "load_config",
        lambda: AppConfig(airport_iata="ZRH", airport_icao="LSZH", source="virtual"),
    )
    monkeypatch.setattr(
        ui_api,
        "lookup_airport",
        lambda **kwargs: types.SimpleNamespace(lat=47.45, lon=8.55, icao="LSZH"),
    )

    vatsim_module = types.ModuleType("localflight.sources.web.vatsim_client")
    vatsim_module.fetch_vatsim_data = lambda: {
        "pilots": [
            {
                "callsign": "SWR100",
                "latitude": 47.5,
                "longitude": 8.6,
                "altitude": 12000,
                "groundspeed": 250,
                "heading": 140,
                "flight_plan": {"departure": "LSZH", "arrival": "EGLL"},
            }
        ]
    }
    monkeypatch.setitem(sys.modules, "localflight.sources.web.vatsim_client", vatsim_module)

    opensky_module = types.ModuleType("localflight.sources.web.opensky_radar")
    opensky_module.bounding_box = lambda lat, lon, radius_nm: (47.0, 8.0, 48.0, 9.0)
    opensky_module.fetch_radar_blips = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("OpenSky should not be used"))
    monkeypatch.setitem(sys.modules, "localflight.sources.web.opensky_radar", opensky_module)

    adsbx_module = types.ModuleType("localflight.sources.web.adsbexchange_client")
    adsbx_module.fetch_aircraft = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ADS-B Exchange should not be used"))
    adsbx_module.aircraft_to_blips = lambda *args, **kwargs: []
    adsbx_module.is_available = lambda: True
    monkeypatch.setitem(sys.modules, "localflight.sources.web.adsbexchange_client", adsbx_module)

    result = ui_api.api_radar(20.0)

    assert result["source"] == "vatsim"
    assert result["count"] == 1
    assert result["blips"][0]["callsign"] == "SWR100"


def test_vatsim_records_keep_dau_flight_plan_fields() -> None:
    from localflight.sources.web.vatsim_client import vatsim_to_raw_records

    records = vatsim_to_raw_records(
        {
            "pilots": [
                {
                    "callsign": "SWR100",
                    "altitude": 12000,
                    "groundspeed": 250,
                    "heading": 140,
                    "flight_plan": {
                        "flight_rules": "I",
                        "aircraft_icao": "A320/M",
                        "departure": "LSZH",
                        "arrival": "EGLL",
                        "alternate": "EGKK",
                        "deptime": "1030",
                        "enroute_time": "0135",
                        "altitude": "FL350",
                        "cruise_tas": "450",
                        "assigned_transponder": "2200",
                        "route": "DEGES Z1 BLM UL613 MID",
                    },
                }
            ]
        },
        airport_icao="LSZH",
    )

    assert len(records) == 1
    record = records[0]
    assert record["aircraft_type"] == "A320"
    assert record["flight_rules"] == "I"
    assert record["planned_altitude"] == "FL350"
    assert record["planned_enroute_minutes"] == 95
    assert record["cruise_tas"] == "450"
    assert record["alternate_icao"] == "EGKK"
    assert record["assigned_transponder"] == "2200"
    assert record["planned_route"] == "DEGES Z1 BLM UL613 MID"


def test_api_admin_budget_hides_provider_side_totals(monkeypatch) -> None:
    monkeypatch.setattr(ui_api, "load_config", lambda: AppConfig(source="real"))

    fake_module = types.ModuleType("localflight.sources.web.aviationstack_client")
    fake_module.get_usage_stats = lambda source=None: {"active_mode": "community", "calls_this_month": 7, "monthly_limit": 50}
    monkeypatch.setitem(sys.modules, "localflight.sources.web.aviationstack_client", fake_module)

    result = ui_api.api_admin_budget()

    assert "aviationstack" in result
    assert "adsbexchange" not in result
    assert "opensky_available" not in result


def test_adsbexchange_fetch_aircraft_uses_managed_relay_when_token_present(monkeypatch) -> None:
    calls: list[tuple[float, float, int, int]] = []

    monkeypatch.setenv("RAPIDAPI_KEY", "")
    monkeypatch.setattr(adsbexchange_client, "_get_activation_token", lambda: "lfm_test_token")
    monkeypatch.setattr(
        adsbexchange_client,
        "_fetch_managed_relay",
        lambda lat, lon, dist_nm, timeout_s: calls.append((lat, lon, dist_nm, timeout_s)) or [{"hex": "abc123"}],
    )

    result = adsbexchange_client.fetch_aircraft(lat=47.45, lon=8.55, radius_nm=21.0, timeout_s=9)

    assert result == [{"hex": "abc123"}]
    assert calls == [(47.45, 8.55, 25, 9)]


def test_mobile_companion_checkin_is_exposed_in_connections(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ui_server, "_setup_complete", lambda: True)
    monkeypatch.setattr(ui_api, "_companion_presence_path", lambda: tmp_path / "companion_clients.json")

    client = TestClient(app)
    response = client.post(
        "/api/admin/companion/checkin",
        json={
            "companion_id": "lfc_test_mobile_001",
            "client_name": "Local Flight Companion",
            "app_version": "0.2.5b1",
            "mobile_os": "iOS 18.5 (phone)",
            "device_type": "phone",
        },
    )

    assert response.status_code == 200
    checkin = response.json()
    assert checkin["ok"] is True
    assert " / iOS 18.5 (phone)" in checkin["platform_pair"]

    connections = client.get("/api/admin/connections")
    assert connections.status_code == 200
    payload = connections.json()
    assert payload["companion_count"] == 1
    assert payload["companions"][0]["companion_id"] == "lfc_test_mobile_001"
    assert payload["companions"][0]["platform_pair"].endswith("/ iOS 18.5 (phone)")


def test_fids_page_keeps_recent_departures_inside_grace_window(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ui_server, "_setup_complete", lambda: True)
    monkeypatch.setattr(
        ui_server,
        "load_config",
        lambda: AppConfig(airport_iata="ZRH", airport_icao="LSZH", timezone="UTC", source="real"),
    )
    monkeypatch.setattr(ui_server, "best_label", lambda **kwargs: "Zurich")
    monkeypatch.setattr(ui_server, "load_state", lambda: AppState(ok=True))

    now = datetime.now(timezone.utc)
    snapshot = tmp_path / "latest.json"
    snapshot.write_text(
        json.dumps(
            {
                "generated_at": now.isoformat(),
                "flights": [
                    {
                        "direction": "DEP",
                        "airport": {"iata": "ZRH", "icao": "LSZH"},
                        "callsign": "SWR10",
                        "airline": {"name": "Swiss", "iata": "LX", "icao": "SWR"},
                        "flight_number": "LX10",
                        "origin": {"iata": "ZRH", "icao": "LSZH", "name": "Zurich"},
                        "destination": {"iata": "LHR", "icao": "EGLL", "name": "London Heathrow"},
                        "aircraft_type": "A320",
                        "aircraft_registration": "HB-JCA",
                        "gate": "A1",
                        "terminal": "1",
                        "stand": None,
                        "status": "Scheduled",
                        "times": {
                            "scheduled": (now - timedelta(minutes=10)).isoformat(),
                            "estimated": None,
                            "actual": None,
                        },
                        "delay_minutes": None,
                        "position": None,
                        "source": "aviationstack",
                        "enriched_by": None,
                        "updated_at": now.isoformat(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "localflight.storage.flights_store.load_latest_snapshot_path",
        lambda airport_iata: snapshot,
    )

    client = TestClient(app)
    response = client.get("/fids?view=departures")

    assert response.status_code == 200
    assert "LX 10" in response.text
    assert "London Heathrow" in response.text or "LHR" in response.text


def test_fids_detail_exposes_live_track_metadata(monkeypatch, tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    snapshot = tmp_path / "latest.json"
    snapshot.write_text(
        json.dumps(
            {
                "generated_at": now.isoformat(),
                "flights": [
                    {
                        "direction": "DEP",
                        "airport": {"iata": "ZRH", "icao": "LSZH"},
                        "callsign": "SWR10",
                        "airline": {"name": "Swiss", "iata": "LX", "icao": "SWR"},
                        "flight_number": "LX10",
                        "origin": {"iata": "ZRH", "icao": "LSZH", "name": "Zurich"},
                        "destination": {"iata": "LHR", "icao": "EGLL", "name": "London Heathrow"},
                        "aircraft_type": "A320",
                        "gate": "A1",
                        "terminal": "1",
                        "stand": None,
                        "status": "Scheduled",
                        "times": {
                            "scheduled": now.isoformat(),
                            "estimated": None,
                            "actual": None,
                        },
                        "delay_minutes": None,
                        "flight_rules": "IFR",
                        "planned_route": "DEGES Z1 BLM UL613 MID",
                        "planned_altitude": "FL350",
                        "planned_departure": now.isoformat(),
                        "planned_arrival": (now + timedelta(minutes=95)).isoformat(),
                        "planned_enroute_minutes": 95,
                        "cruise_tas": 450,
                        "alternate_icao": "EGKK",
                        "assigned_transponder": "2200",
                        "position": {
                            "lat": 47.45,
                            "lon": 8.56,
                            "altitude_baro": 3048,
                            "altitude_geo": 3200,
                            "heading": 270,
                            "speed_ms": 120,
                            "vertical_rate": 5,
                            "on_ground": False,
                            "icao24": "4B1800",
                            "squawk": "7000",
                            "last_contact": now.isoformat(),
                        },
                        "source": "aviationstack",
                        "enriched_by": "adsbexchange",
                        "updated_at": now.isoformat(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(ui_api, "load_config", lambda: AppConfig(airport_iata="ZRH", airport_icao="LSZH"))
    monkeypatch.setattr(ui_api, "load_latest_snapshot_path", lambda airport_iata: snapshot)
    import localflight.storage.history as history

    monkeypatch.setattr(history, "query_flight_history", lambda callsign, days=7: [])

    response = TestClient(app).get("/api/fids/detail?callsign=SWR10")

    assert response.status_code == 200
    detail = response.json()["detail"]
    assert detail["detail_mode"] == "real"
    assert detail["aircraft_registration"] == "HB-JCA"
    assert detail["flight_plan"]["route"] == "DEGES Z1 BLM UL613 MID"
    assert detail["flight_plan"]["enroute_minutes"] == 95
    assert detail["flight_plan"]["assigned_transponder"] == "2200"
    assert detail["position"]["altitude_geo_m"] == 3200
    assert detail["position"]["icao24"] == "4B1800"
    assert detail["position"]["squawk"] == "7000"
    assert detail["data_sources"]["enrichment"] == "adsbexchange"
    assert detail["data_sources"]["confidence"] == "live_position_matched"
    assert isinstance(detail["data_sources"]["snapshot_age_seconds"], int)


def test_api_radar_reports_refresh_hint_for_adsb_cache(monkeypatch) -> None:
    ui_api._adsbx_radar_cache.clear()
    ui_api._opensky_radar_cache.clear()
    monkeypatch.setattr(
        ui_api,
        "load_config",
        lambda: AppConfig(airport_iata="ZRH", airport_icao="LSZH", source="real"),
    )
    monkeypatch.setattr(
        ui_api,
        "lookup_airport",
        lambda **kwargs: types.SimpleNamespace(lat=47.45, lon=8.55, icao="LSZH"),
    )

    adsbx_module = types.ModuleType("localflight.sources.web.adsbexchange_client")
    adsbx_module.is_available = lambda: True
    adsbx_module.fetch_aircraft = lambda lat, lon, radius_nm, timeout_s=10: [{"hex": "abc123"}]
    adsbx_module.aircraft_to_blips = lambda aircraft, center_lat, center_lon, radius_nm=50.0: [
        {"callsign": "SWR100", "lat": 47.46, "lon": 8.56}
    ]
    monkeypatch.setitem(sys.modules, "localflight.sources.web.adsbexchange_client", adsbx_module)

    result = ui_api.api_radar(20.0)

    assert result["source"] == "adsbexchange_live"
    assert result["refresh_after_s"] >= 60
    assert result["count"] == 1


def test_matrix_config_endpoint_round_trip(tmp_path: Path, monkeypatch) -> None:
    matrix_config = tmp_path / "matrix_config.json"
    monkeypatch.setattr(ui_api, "_matrix_config_path", lambda: matrix_config)
    monkeypatch.setattr(ui_api, "load_config", lambda: AppConfig(skin="technical"))

    client = TestClient(ui_api.app)

    response = client.get("/api/matrix/config")
    assert response.status_code == 200
    assert response.json() == {
        "brightness": 0.8,
        "max_rows": 4,
        "refresh_seconds": 60,
        "default_view": "departures",
        "skin": "technical",
    }

    response = client.post(
        "/api/matrix/config",
        json={
            "brightness": 0.55,
            "max_rows": 6,
            "refresh_seconds": 90,
            "default_view": "arrivals",
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "brightness": 0.55,
        "max_rows": 6,
        "refresh_seconds": 90,
        "default_view": "arrivals",
    }
    assert json.loads(matrix_config.read_text(encoding="utf-8")) == {
        "brightness": 0.55,
        "max_rows": 6,
        "refresh_seconds": 90,
        "default_view": "arrivals",
    }


def test_matrix_script_endpoint_renders_from_canonical_template(tmp_path: Path, monkeypatch) -> None:
    template = tmp_path / "client.py"
    template.write_text(
        "\n".join(
            [
                'WIFI_SSID     = "your_wifi_name"',
                'WIFI_PASSWORD = "your_wifi_password"',
                'API_HOST      = "localflight.local"',
                "API_PORT      = 8000",
                "PANEL_W       = 256",
                "PANEL_H       = 64",
                "MAX_ROWS      = 4",
                "REFRESH_S     = 60",
                "BRIGHTNESS    = 0.80",
                'DEFAULT_VIEW  = "departures"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ui_api, "_matrix_client_template_path", lambda: template)

    client = TestClient(ui_api.app)
    response = client.post(
        "/api/matrix/script",
        json={
            "wifi_ssid": "BoardNet",
            "wifi_password": "secret123",
            "api_host": "localflight.local",
            "api_port": 8000,
            "panel_w": 256,
            "panel_h": 64,
            "max_rows": 6,
            "refresh_seconds": 120,
            "brightness": 0.55,
            "default_view": "arrivals",
        },
    )

    assert response.status_code == 200
    assert 'WIFI_SSID     = "BoardNet"' in response.text
    assert 'WIFI_PASSWORD = "secret123"' in response.text
    assert 'API_HOST      = "localflight.local"' in response.text
    assert "API_PORT      = 8000" in response.text
    assert "PANEL_W       = 256" in response.text
    assert "PANEL_H       = 64" in response.text
    assert "MAX_ROWS      = 6" in response.text
    assert "REFRESH_S     = 120" in response.text
    assert "BRIGHTNESS    = 0.55" in response.text
    assert 'DEFAULT_VIEW  = "arrivals"' in response.text


def test_matrix_script_endpoint_rejects_loopback_host(tmp_path: Path, monkeypatch) -> None:
    template = tmp_path / "client.py"
    template.write_text('API_HOST      = "localflight.local"', encoding="utf-8")
    monkeypatch.setattr(ui_api, "_matrix_client_template_path", lambda: template)

    client = TestClient(ui_api.app)
    response = client.post(
        "/api/matrix/script",
        json={
            "wifi_ssid": "BoardNet",
            "wifi_password": "",
            "api_host": "localhost",
            "api_port": 8000,
            "panel_w": 256,
            "panel_h": 64,
            "max_rows": 4,
            "refresh_seconds": 60,
            "brightness": 0.8,
            "default_view": "departures",
        },
    )

    assert response.status_code == 422
    assert "not localhost" in response.json()["detail"]


def test_submit_crash_respects_diagnostics_mode_gate(monkeypatch) -> None:
    calls: list[tuple] = []

    monkeypatch.setattr(bug_reporter, "_auto_diagnostics_mode", lambda: "manual")
    monkeypatch.setattr(bug_reporter, "_post_relay_report", lambda payload: calls.append((payload,)) or {"ok": True})

    result = bug_reporter.submit_crash("Boom")

    assert result == {"ok": False, "error": "automatic diagnostics disabled"}
    assert calls == []

    monkeypatch.setattr(bug_reporter, "_auto_diagnostics_mode", lambda: "unset")
    result = bug_reporter.submit_crash("Boom again")

    assert result == {"ok": False, "error": "automatic diagnostics disabled"}
    assert calls == []


def test_submit_crash_only_attaches_log_tail_in_auto_logs(monkeypatch) -> None:
    submitted: list[dict] = []

    monkeypatch.setattr(bug_reporter, "_crash_fingerprint", lambda msg: f"fp-{msg}")
    monkeypatch.setattr(bug_reporter, "_already_crash_filed", lambda fp: False)
    monkeypatch.setattr(bug_reporter, "_mark_crash_filed", lambda fp: None)
    monkeypatch.setattr(
        bug_reporter,
        "_system_metadata",
        lambda: {
            "install_id": "00000000-0000-0000-0000-000000000111",
            "install_fingerprint": "fp-test",
            "activation_token": "",
            "app_version": "test",
            "platform": "Darwin",
            "os": "macOS",
            "arch": "arm64",
            "python_version": "3.11",
            "airport": "ZRH",
            "source": "real",
            "api_mode": "community relay",
            "diagnostics_mode": "auto",
        },
    )
    monkeypatch.setattr(bug_reporter, "_read_log_tail", lambda n_lines=50: "line-1\nline-2")
    monkeypatch.setattr(
        bug_reporter,
        "_post_relay_report",
        lambda payload: submitted.append(payload) or {"ok": True, "url": "https://example.test"},
    )

    monkeypatch.setattr(bug_reporter, "_auto_diagnostics_mode", lambda: "auto")
    result = bug_reporter.submit_crash("Auto only", traceback_str="tb", context="desktop")
    assert result["ok"] is True
    assert submitted
    assert submitted[-1]["description"] == ""
    assert submitted[-1]["traceback"] == "tb"

    monkeypatch.setattr(bug_reporter, "_auto_diagnostics_mode", lambda: "auto_logs")
    result = bug_reporter.submit_crash("Auto plus logs", traceback_str="tb", context="desktop")
    assert result["ok"] is True
    assert "line-1" in submitted[-1]["description"]


def test_bug_reporter_forwards_to_relay_without_direct_linear(monkeypatch) -> None:
    submitted: list[dict] = []
    monkeypatch.setattr(
        bug_reporter,
        "_system_metadata",
        lambda: {
            "install_id": "00000000-0000-0000-0000-000000000222",
            "install_fingerprint": "fp-test",
            "activation_token": "lfm_secret",
            "app_version": "test",
            "platform": "Darwin",
            "os": "macOS",
            "arch": "arm64",
            "python_version": "3.11",
            "airport": "ZRH",
            "source": "real",
            "api_mode": "community relay",
            "diagnostics_mode": "manual",
        },
    )
    monkeypatch.setattr(
        bug_reporter,
        "_post_relay_report",
        lambda payload: submitted.append(payload) or {"ok": True, "url": "https://linear.test/report"},
    )

    result = bug_reporter.submit_report("Broken thing", "AVIATIONSTACK_API_KEY=secret")

    assert result["ok"] is True
    assert submitted[0]["report_type"] == "manual"
    assert submitted[0]["origin"] == "desktop"
    assert submitted[0]["activation_token"] == "lfm_secret"
    assert "secret" not in submitted[0]["description"]
    assert "api.linear.app/graphql" not in Path(bug_reporter.__file__).read_text(encoding="utf-8")


def test_api_config_patch_accepts_diagnostics_mode(tmp_path: Path, monkeypatch) -> None:
    config_file = tmp_path / ".localflight" / "config.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(storage_config, "config_path", lambda: config_file)

    client = TestClient(ui_api.app)
    response = client.patch("/api/config", json={"diagnostics_mode": "auto_logs"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["diagnostics_mode"] == "auto_logs"
    assert json.loads(config_file.read_text(encoding="utf-8"))["diagnostics_mode"] == "auto_logs"


def test_default_public_relay_url_matches_live_installer_default(monkeypatch) -> None:
    monkeypatch.delenv("LOCALFLIGHT_RELAY_URL", raising=False)

    assert relay_defaults.default_public_relay_url() == "https://localflight-community-relay.fly.dev/v1/flights"


def test_ui_route_contracts_cover_core_pages_and_api_surfaces() -> None:
    paths = {getattr(route, "path", None) for route in ui_server.app.router.routes}

    expected = {
        "/",
        "/setup",
        "/display",
        "/fids",
        "/radar",
        "/admin",
        "/history",
        "/feedback",
        "/matrix-preview",
        "/ws",
        "/api/config",
        "/api/fids",
        "/api/radar",
        "/api/metar",
        "/api/history",
        "/api/admin/system",
        "/api/admin/budget",
        "/api/admin/connections",
        "/api/admin/updates",
        "/api/admin/scheduler",
        "/api/setup/client-info",
        "/api/setup/complete",
        "/api/matrix/config",
        "/api/matrix/script",
        "/api/feedback",
        "/api/feedback/crash",
    }

    assert expected.issubset(paths)


def test_relay_route_contracts_cover_public_and_admin_surfaces() -> None:
    paths = {getattr(route, "path", None) for route in relay_main.app.router.routes}

    expected = {
        "/",
        "/health",
        "/admin",
        "/v1/flights",
        "/v1/radar",
        "/v1/reports",
        "/v1/activate",
        "/v1/client/status",
        "/v1/client/checkin",
        "/v1/managed/config",
    }

    assert expected.issubset(paths)
