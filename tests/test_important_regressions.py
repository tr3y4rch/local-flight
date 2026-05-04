from __future__ import annotations

import json
import sys
import threading
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import localflight.scheduler.jobs as jobs
import localflight.scheduler.runtime as runtime
import localflight.__main__ as localflight_main
import localflight.sources.web.adsbexchange_client as adsbexchange_client
import localflight.sources.web.aviationstack_client as aviationstack_client
import localflight.sources.web.airport_surface as airport_surface
import localflight.sources.web.bug_reporter as bug_reporter
import localflight.sources.web.metar_client as metar_client
import localflight.sources.web.relay_defaults as relay_defaults
import localflight.storage.config as storage_config
import localflight.storage.flights_store as flights_store
import localflight.storage.install as storage_install
import localflight.ui.api as ui_api
import localflight.ui.server as ui_server
import relay.main as relay_main
from localflight.core.models import AirportRef, Flight, FlightDirection, FlightTime
from localflight.decode.metar import decorate_metar
from localflight.decode.dedupe import dedupe_codeshares
from localflight.decode.normalize import normalize_flights
from localflight.native.api_client import _normalize_relay_base_url
from localflight.platform.detect import Platform
from localflight.platform.gui_mode import resolve_gui_mode
from localflight.render.fids import build_fids_context
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


def test_metar_decorator_turns_cavok_into_clear_weather_mood() -> None:
    decorated = decorate_metar(
        {
            "raw_text": "METAR LSZH 011220Z 28008KT CAVOK 12/04 Q1018",
            "flight_cat": "VFR",
            "wind_dir_deg": 280,
            "wind_speed_kt": 8,
            "visibility_m": 10000,
            "ceiling_ft": None,
            "clouds": [],
        }
    )

    assert decorated["weather_condition"] == "clear"
    assert decorated["weather_icon"] == "sun"
    assert decorated["weather_tone"] == "good"
    assert "Clear" in decorated["weather_summary"]


def test_metar_decorator_prioritizes_thunderstorm_over_sky_cover() -> None:
    decorated = decorate_metar(
        {
            "raw_text": "METAR KDEN 011920Z 16022G34KT 3SM +TSRA BKN018CB 08/07 A2992",
            "flight_cat": "IFR",
            "wind_dir_deg": 160,
            "wind_speed_kt": 22,
            "wind_gust_kt": 34,
            "visibility_m": 4828,
            "ceiling_ft": 1800,
            "clouds": [{"cover": "BKN", "base_ft": 1800}],
            "wx_string": "+TSRA",
        }
    )

    assert decorated["weather_condition"] == "thunderstorm"
    assert decorated["weather_icon"] == "storm"
    assert decorated["weather_tone"] == "bad"
    assert any("Thunderstorm" in item for item in decorated["weather_hazards"])


def test_metar_decorator_detects_low_visibility_fog() -> None:
    decorated = decorate_metar(
        {
            "raw_text": "METAR EGLL 010650Z 00000KT 0300 FG VV002 03/03 Q1004",
            "flight_cat": "LIFR",
            "wind_speed_kt": 0,
            "visibility_m": 300,
            "ceiling_ft": 200,
            "clouds": [{"cover": "VV", "base_ft": 200}],
            "wx_string": "FG",
        }
    )

    assert decorated["weather_condition"] == "fog"
    assert decorated["weather_icon"] == "fog"
    assert decorated["weather_tone"] == "bad"
    assert "Very low visibility" in decorated["weather_hazards"]


def test_metar_client_decode_includes_local_weather_fields() -> None:
    decoded = metar_client._decode(
        {
            "station_id": "RJTT",
            "raw_ob": "METAR RJTT 012100Z 03012KT 9999 -RA SCT020 BKN040 18/14 Q1012",
            "obs_time": "2026-05-01T21:00:00Z",
            "flight_cat": "VFR",
            "temp": 18,
            "dewp": 14,
            "wind_dir": 30,
            "wind_speed": 12,
            "visibility": 6.21,
            "clouds": [{"cover": "SCT", "base": 2000}, {"cover": "BKN", "base": 4000}],
            "wx_string": "-RA",
            "altim_in_hg": 29.88,
        }
    )

    assert decoded["weather_condition"] == "rain"
    assert decoded["weather_icon"] == "rain"
    assert decoded["weather_label"] == "Light rain"
    assert decoded["weather"]["source"] == "metar"


def test_raw_metar_decoder_keeps_temperature_for_vatsim_weather() -> None:
    decoded = metar_client.decode_raw_metar(
        "LSZH",
        "METAR LSZH 012000Z 28008KT CAVOK 12/M01 Q1018",
        source="vatsim",
    )

    assert decoded["source"] == "vatsim"
    assert decoded["temp_c"] == 12
    assert decoded["dewpoint_c"] == -1
    assert decoded["weather_icon"] == "sun"
    assert "12/-1" in decoded["decoded_summary"]


def test_api_metar_uses_vatsim_atis_without_identity_leak(monkeypatch) -> None:
    import localflight.sources.web.vatsim_client as vatsim_client

    monkeypatch.setattr(
        ui_api,
        "load_config",
        lambda: AppConfig(airport_iata="ZRH", airport_icao="LSZH", source="virtual"),
    )
    monkeypatch.setattr(
        vatsim_client,
        "fetch_vatsim_data",
        lambda: {
            "atis": [
                {
                    "callsign": "LSZH_ATIS",
                    "cid": 123456,
                    "name": "Private Controller",
                    "text_atis": [
                        "Controller Private Controller CID 123456",
                        "METAR LSZH 012000Z 28008KT CAVOK 10/04 Q1018",
                    ],
                }
            ]
        },
    )
    monkeypatch.setattr(
        metar_client,
        "fetch_metar",
        lambda icao: (_ for _ in ()).throw(AssertionError("real METAR should be fallback only")),
    )

    decoded = ui_api.api_metar()

    assert decoded["source"] == "vatsim"
    assert decoded["temp_c"] == 10
    assert "Private" not in decoded["raw_text"]
    assert "CID" not in decoded["raw_text"]


def test_fids_orders_by_full_airport_local_datetime_across_midnight() -> None:
    tz = ZoneInfo("America/Denver")
    cfg = AppConfig(
        airport_iata="DEN",
        airport_icao="KDEN",
        timezone="America/Denver",
        display_grace_minutes=30,
        display_horizon_hours=12,
    )
    airport = AirportRef(iata="DEN", icao="KDEN")
    flights = [
        Flight(
            direction=FlightDirection.ARRIVAL,
            airport=airport,
            callsign="DAL0008",
            origin=AirportRef(iata="ATL", icao="KATL"),
            times=FlightTime(scheduled=datetime(2026, 5, 2, 0, 8, tzinfo=tz)),
            source="aviationstack",
        ),
        Flight(
            direction=FlightDirection.ARRIVAL,
            airport=airport,
            callsign="UAL1745",
            origin=AirportRef(iata="ORD", icao="KORD"),
            times=FlightTime(scheduled=datetime(2026, 5, 1, 17, 45, tzinfo=tz)),
            source="aviationstack",
        ),
    ]

    ctx = build_fids_context(
        cfg=cfg,
        view="arrivals",
        refresh_seconds=cfg.refresh_seconds,
        flights=flights,
        reference_now=datetime(2026, 5, 1, 14, 52, tzinfo=tz),
    )

    assert [row.callsign for row in ctx["rows"]] == ["UAL1745", "DAL0008"]
    assert [row.display_time[:5] for row in ctx["rows"]] == ["17:45", "00:08"]


def test_fids_decodes_airline_names_and_links_codeshares() -> None:
    scheduled = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc).isoformat()
    records = [
        {
            "callsign": "SWR100",
            "direction": "DEP",
            "status": "scheduled",
            "scheduled": scheduled,
            "airline_icao": "SWR",
            "flight_number": "SWR100",
            "destination_iata": "JFK",
        },
        {
            "callsign": "UAL100",
            "direction": "DEP",
            "status": "scheduled",
            "scheduled": scheduled,
            "airline_icao": "UAL",
            "flight_number": "UAL100",
            "destination_iata": "JFK",
        },
    ]

    flights = normalize_flights(
        records,
        airport_iata="ZRH",
        airport_icao="LSZH",
        source_name="test",
    )
    deduped = dedupe_codeshares(flights, preferred_airline_iata=["LX"])
    ctx = build_fids_context(
        cfg=AppConfig(airport_iata="ZRH", airport_icao="LSZH", timezone="UTC"),
        view="departures",
        refresh_seconds=60,
        flights=deduped,
        reference_now=datetime(2026, 5, 1, 11, 55, tzinfo=timezone.utc),
    )

    assert len(ctx["rows"]) == 1
    row = ctx["rows"][0]
    assert row.flight_display == "LX 100"
    assert row.airline_display == "SWISS"
    assert row.codeshare_display == "Also UA 100"


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


def test_local_mutation_guard_blocks_cross_origin_browser_posts() -> None:
    cross_origin = types.SimpleNamespace(
        method="POST",
        headers={"host": "127.0.0.1:8000", "origin": "https://evil.example"},
    )
    same_origin = types.SimpleNamespace(
        method="POST",
        headers={"host": "127.0.0.1:8000", "origin": "http://127.0.0.1:8000"},
    )
    native_client = types.SimpleNamespace(method="POST", headers={"host": "192.168.1.20:8000"})
    cross_site_fetch = types.SimpleNamespace(
        method="POST",
        headers={"host": "127.0.0.1:8000", "sec-fetch-site": "cross-site"},
    )

    assert ui_server._is_cross_origin_mutation(cross_origin) is True
    assert ui_server._is_cross_origin_mutation(cross_site_fetch) is True
    assert ui_server._is_cross_origin_mutation(same_origin) is False
    assert ui_server._is_cross_origin_mutation(native_client) is False


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

    monkeypatch.setattr(jobs, "_fetch_is_due", lambda cfg: (True, "forced by test"))
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


def test_windowed_pyinstaller_stdio_fallback_is_writable(tmp_path: Path, monkeypatch) -> None:
    previous_handles = list(localflight_main._stdio_fallback_handles)

    monkeypatch.setattr(localflight_main, "Path", types.SimpleNamespace(home=lambda: tmp_path))
    monkeypatch.setattr(sys, "stdin", None)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    localflight_main._ensure_stdio()

    assert sys.stdin is not None
    assert sys.stdout is not None
    assert sys.stderr is not None
    sys.stderr.write("windowed bootstrap ok\n")
    assert (tmp_path / ".localflight" / "logs").exists()

    for handle in localflight_main._stdio_fallback_handles:
        if handle not in previous_handles:
            try:
                handle.close()
            except Exception:
                pass
    localflight_main._stdio_fallback_handles[:] = previous_handles


def test_threading_crash_hook_uses_python_thread_traceback_field(monkeypatch) -> None:
    previous_sys_hook = sys.excepthook
    previous_threading_hook = threading.excepthook
    submitted: list[tuple[str, str, str]] = []

    monkeypatch.setattr(threading, "excepthook", lambda args: None)
    monkeypatch.setattr(
        bug_reporter,
        "submit_crash",
        lambda message, traceback_str="", context="", **kwargs: submitted.append(
            (message, traceback_str, context)
        )
        or {"ok": True},
    )

    try:
        localflight_main._install_crash_hooks()

        class Args:
            exc_type = RuntimeError
            exc_value = RuntimeError("thread boom")
            exc_traceback = None
            thread = types.SimpleNamespace(name="uvicorn")

        threading.excepthook(Args())
    finally:
        sys.excepthook = previous_sys_hook
        threading.excepthook = previous_threading_hook

    assert submitted
    assert submitted[0][0] == "RuntimeError: thread boom"
    assert submitted[0][2] == "thread/uvicorn"


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
            "relay_snapshot": {
                "generated_at": "2026-04-15T12:00:00+00:00",
                "cache_state": "fresh",
                "provider": "aviationstack",
                "airport_iata": "ZRH",
                "timezone": "Europe/Zurich",
                "display_grace_minutes": 30,
                "display_horizon_hours": 12,
                "meta": {
                    "shared_stats": {
                        "client_accesses": 12,
                        "upstream_pulls": 4,
                        "refresh_count": 1,
                        "cache_hits": 11,
                        "stale_serves": 0,
                        "cache_hit_rate_pct": 91.7,
                        "estimated_savings": 11,
                    }
                },
            },
            "aviationstack": {"2026-04": 34},
        },
    )
    monkeypatch.setattr(aviationstack_client, "_utc_now", lambda: datetime(2026, 4, 15, tzinfo=timezone.utc))
    monkeypatch.setattr(aviationstack_client, "_month_key", lambda: "2026-04")
    monkeypatch.setattr(aviationstack_client, "_get_relay_limit", lambda: 50)
    monkeypatch.setattr(aviationstack_client, "_get_byok_limit", lambda: 90)
    monkeypatch.setattr(aviationstack_client, "_get_relay_url", lambda: "https://localflight-community-relay.fly.dev")
    monkeypatch.setattr(aviationstack_client, "_has_enabled_byok_key", lambda: False)
    monkeypatch.setattr(aviationstack_client, "_has_api_key", lambda: False)
    monkeypatch.setattr(aviationstack_client, "_has_community_api_key", lambda: False)
    monkeypatch.setattr(aviationstack_client, "_get_activation_token", lambda: "")
    monkeypatch.setattr(aviationstack_client, "_is_enabled", lambda: False)
    monkeypatch.setattr(
        storage_config,
        "load_config",
        lambda: AppConfig(
            airport_iata="ZRH",
            airport_icao="LSZH",
            timezone="Europe/Zurich",
            display_grace_minutes=30,
            display_horizon_hours=12,
        ),
    )

    community_stats = aviationstack_client.get_usage_stats("real")
    assert community_stats["active_mode"] == "community"
    assert community_stats["shared_relay"] is True
    assert community_stats["community"]["calls_this_month"] == 12
    assert community_stats["community"]["monthly_limit"] == 50
    assert community_stats["shared_snapshot"]["shared_stats"]["upstream_pulls"] == 4
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
    monkeypatch.setattr(aviationstack_client, "_get_relay_url", lambda: "https://localflight-community-relay.fly.dev")
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
                "transponder": "2201",
                "cid": 123456,
                "name": "Private Pilot",
                "flight_plan": {
                    "departure": "LSZH",
                    "arrival": "EGLL",
                    "aircraft_short": "A320",
                    "route": "DCT TEST",
                    "flight_rules": "I",
                },
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
    assert result["blips"][0]["source"] == "vatsim"
    assert result["blips"][0]["departure_icao"] == "LSZH"
    assert result["blips"][0]["arrival_icao"] == "EGLL"
    assert result["blips"][0]["aircraft_type"] == "A320"
    assert result["blips"][0]["route"] == "DCT TEST"
    assert "name" not in result["blips"][0]
    assert "cid" not in result["blips"][0]


def test_api_radar_virtual_uses_exact_circular_range(monkeypatch) -> None:
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
                "callsign": "INRING",
                "latitude": 47.455,
                "longitude": 8.55,
                "altitude": 0,
                "groundspeed": 8,
                "heading": 140,
                "flight_plan": {"departure": "LSZH", "arrival": "EGLL"},
            },
            {
                "callsign": "CORNER",
                "latitude": 47.465,
                "longitude": 8.565,
                "altitude": 0,
                "groundspeed": 8,
                "heading": 140,
                "flight_plan": {"departure": "LSZH", "arrival": "EGLL"},
            },
        ]
    }
    monkeypatch.setitem(sys.modules, "localflight.sources.web.vatsim_client", vatsim_module)

    opensky_module = types.ModuleType("localflight.sources.web.opensky_radar")
    opensky_module.bounding_box = lambda lat, lon, radius_nm: (47.43, 8.52, 47.48, 8.58)
    monkeypatch.setitem(sys.modules, "localflight.sources.web.opensky_radar", opensky_module)

    result = ui_api.api_radar(1.0)

    assert result["source"] == "vatsim"
    assert result["radar_mode"] == "surface"
    assert [b["callsign"] for b in result["blips"]] == ["INRING"]


def test_api_radar_virtual_filters_ground_blips_on_airborne_ranges(monkeypatch) -> None:
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
                "callsign": "AIRBORNE",
                "latitude": 47.50,
                "longitude": 8.60,
                "altitude": 9000,
                "groundspeed": 240,
                "flight_plan": {"departure": "LSZH", "arrival": "EGLL"},
            },
            {
                "callsign": "GROUND",
                "latitude": 47.451,
                "longitude": 8.551,
                "altitude": 0,
                "groundspeed": 4,
                "flight_plan": {"departure": "LSZH", "arrival": "EGLL"},
            },
        ]
    }
    monkeypatch.setitem(sys.modules, "localflight.sources.web.vatsim_client", vatsim_module)

    opensky_module = types.ModuleType("localflight.sources.web.opensky_radar")
    opensky_module.bounding_box = lambda lat, lon, radius_nm: (47.0, 8.0, 48.0, 9.0)
    monkeypatch.setitem(sys.modules, "localflight.sources.web.opensky_radar", opensky_module)

    result = ui_api.api_radar(20.0)

    assert result["source"] == "vatsim"
    assert result["radar_mode"] == "airborne"
    assert result["ground_filtered"] == 1
    assert result["hidden_ground_count"] == 1
    assert [b["callsign"] for b in result["blips"]] == ["AIRBORNE"]


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


def test_vatsim_records_drop_person_identifying_fields() -> None:
    from localflight.sources.web.vatsim_client import vatsim_to_raw_records

    records = vatsim_to_raw_records(
        {
            "pilots": [
                {
                    "cid": 1234567,
                    "name": "Jane Pilot",
                    "callsign": "BAW123",
                    "altitude": 12000,
                    "groundspeed": 250,
                    "server": "EUROPE-C",
                    "flight_plan": {
                        "aircraft_icao": "B738",
                        "departure": "EGLL",
                        "arrival": "LSZH",
                        "route": "LAM UL9 KONAN",
                    },
                }
            ],
            "controllers": [
                {"cid": 7654321, "name": "John Controller", "callsign": "LSZH_TWR"}
            ],
        },
        airport_icao="EGLL",
    )

    assert len(records) == 1
    serialized = json.dumps(records[0])
    assert "Jane Pilot" not in serialized
    assert "John Controller" not in serialized
    assert "1234567" not in serialized
    assert "7654321" not in serialized
    assert "EUROPE-C" not in serialized
    assert records[0]["callsign"] == "BAW123"
    assert records[0]["planned_route"] == "LAM UL9 KONAN"


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


def test_overpass_surface_normalizer_handles_core_airport_geometry() -> None:
    payload = {
        "elements": [
            {
                "type": "way",
                "id": 10,
                "tags": {"aeroway": "runway", "ref": "16/34"},
                "geometry": [
                    {"lat": 47.451, "lon": 8.548},
                    {"lat": 47.462, "lon": 8.563},
                ],
            },
            {
                "type": "way",
                "id": 11,
                "tags": {"aeroway": "apron"},
                "geometry": [
                    {"lat": 47.45, "lon": 8.55},
                    {"lat": 47.451, "lon": 8.551},
                    {"lat": 47.45, "lon": 8.55},
                ],
            },
            {
                "type": "way",
                "id": 13,
                "tags": {"building": "hangar", "name": "North Hangar"},
                "geometry": [
                    {"lat": 47.453, "lon": 8.552},
                    {"lat": 47.454, "lon": 8.553},
                    {"lat": 47.453, "lon": 8.552},
                ],
            },
            {
                "type": "way",
                "id": 12,
                "tags": {"aeroway": "parking_position"},
                "geometry": [{"lat": 47.45, "lon": 8.55}, {"lat": 47.46, "lon": 8.56}],
            },
        ]
    }

    features = airport_surface.normalize_overpass_surface(payload)

    runway = next(feature for feature in features if feature["kind"] == "runway")
    apron = next(feature for feature in features if feature["kind"] == "apron")
    building = next(feature for feature in features if feature["kind"] == "building")
    assert runway["label"] == "16/34"
    assert runway["closed"] is False
    assert apron["closed"] is True
    assert building["label"] == "North Hangar"
    assert building["closed"] is True
    assert all(feature["kind"] != "parking_position" for feature in features)


def test_api_radar_surface_respects_disabled_config(monkeypatch) -> None:
    monkeypatch.setattr(
        ui_api,
        "load_config",
        lambda: AppConfig(
            airport_iata="ZRH",
            airport_icao="LSZH",
            source="real",
            radar_surface_enabled=False,
        ),
    )
    monkeypatch.setattr(
        ui_api,
        "lookup_airport",
        lambda **kwargs: types.SimpleNamespace(lat=47.45, lon=8.55, icao="LSZH"),
    )

    result = ui_api.api_radar_surface(20.0)

    assert result["cache_state"] == "disabled"
    assert result["features"] == []
    assert result["provider"] == "openstreetmap"


def test_radar_surface_defaults_to_disabled() -> None:
    assert AppConfig().radar_surface_enabled is False


def test_api_radar_surface_falls_back_to_local_stale_cache(monkeypatch) -> None:
    cfg = AppConfig(airport_iata="ZRH", airport_icao="LSZH", radar_surface_enabled=True)
    cached = airport_surface.build_surface_payload(
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
    )

    class _Response:
        status_code = 503

        def json(self) -> dict[str, object]:
            return {"detail": "down"}

    monkeypatch.setattr(ui_api, "load_config", lambda: cfg)
    monkeypatch.setattr(
        ui_api,
        "lookup_airport",
        lambda **kwargs: types.SimpleNamespace(lat=47.45, lon=8.55, icao="LSZH"),
    )
    monkeypatch.setattr(ui_api, "_load_local_surface_cache", lambda cfg: cached)
    monkeypatch.setattr(ui_api, "_save_local_surface_cache", lambda cfg, payload: None)
    monkeypatch.setattr(ui_api._req, "get", lambda *args, **kwargs: _Response())

    result = ui_api.api_radar_surface(20.0)

    assert result["cache_state"] == "stale"
    assert "Relay surface HTTP 503" in result["error"]
    assert result["features"][0]["label"] == "16/34"


def test_api_radar_surface_returns_estimated_first_run_overlay(monkeypatch) -> None:
    cfg = AppConfig(airport_iata="DEN", airport_icao="KDEN", radar_surface_enabled=True)

    class _Response:
        status_code = 503

        def json(self) -> dict[str, object]:
            return {"detail": "surface disabled"}

    monkeypatch.setattr(ui_api, "load_config", lambda: cfg)
    monkeypatch.setattr(
        ui_api,
        "lookup_airport",
        lambda **kwargs: types.SimpleNamespace(lat=39.8617, lon=-104.6731, icao="KDEN"),
    )
    monkeypatch.setattr(ui_api, "_load_local_surface_cache", lambda cfg: None)
    monkeypatch.setattr(ui_api, "_save_local_surface_cache", lambda cfg, payload: (_ for _ in ()).throw(AssertionError("estimated fallback must not be cached")))
    monkeypatch.setattr(ui_api._req, "get", lambda *args, **kwargs: _Response())

    result = ui_api.api_radar_surface(5.0)

    assert result["cache_state"] == "estimated"
    assert result["provider"] == "localflight-estimated"
    assert result["meta"]["estimated_surface"] is True
    assert "Relay surface HTTP 503" in result["error"]
    assert {feature["kind"] for feature in result["features"]} >= {"boundary", "runway", "taxiway", "apron", "building"}


def test_radar_template_loads_surface_layer_and_attribution(monkeypatch) -> None:
    monkeypatch.setattr(ui_server, "_setup_complete", lambda: True)
    monkeypatch.setattr(
        ui_server,
        "load_config",
        lambda: AppConfig(airport_iata="ZRH", airport_icao="LSZH", source="real"),
    )
    monkeypatch.setattr(ui_server, "best_label", lambda **kwargs: "Zurich")

    response = TestClient(app).get("/radar?radius_nm=1")

    assert response.status_code == 200
    assert "/api/radar/surface" in response.text
    assert 'data-nm="1"' in response.text
    assert "SURFACE_BY_SKIN" in response.text
    assert "building" in response.text
    assert "osmAttribution" in response.text
    assert "OpenStreetMap contributors" in response.text
    assert "Estimated airport surface" in response.text
    assert "localflight-estimated" in response.text
    assert "height: 100dvh" in response.text
    assert "ResizeObserver" in response.text
    assert "--lf-chrome" not in response.text


def test_mobile_companion_checkin_is_exposed_in_connections(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ui_server, "_setup_complete", lambda: True)
    monkeypatch.setattr(ui_api, "_companion_presence_path", lambda: tmp_path / "companion_clients.json")

    client = TestClient(app)
    response = client.post(
        "/api/admin/companion/checkin",
        json={
            "companion_id": "lfc_test_mobile_001",
            "client_name": "Local Flight Companion",
            "app_version": "0.2.5b5",
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


def test_matrix_device_checkin_is_exposed_as_hardware_inventory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ui_server, "_setup_complete", lambda: True)
    monkeypatch.setattr(ui_api, "_matrix_config_path", lambda: tmp_path / "matrix_config.json")

    client = TestClient(app)
    response = client.post(
        "/api/matrix/v2/devices/checkin",
        json={
            "device_id": "i75w-test",
            "label": "Desk Matrix",
            "kind": "led_matrix",
            "brand": "Pimoroni",
            "model": "Interstate 75 W",
            "hardware": "Pimoroni Interstate 75 W",
            "hardware_name": "Pimoroni Interstate 75 W",
            "panel_w": 256,
            "panel_h": 64,
            "firmware": "2.0",
            "renderers": ["modern_fids", "vatsim_atc"],
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True

    connections = client.get("/api/admin/connections")
    assert connections.status_code == 200
    payload = connections.json()
    assert payload["matrix_device_count"] == 1
    assert payload["matrix_online_count"] == 1
    assert payload["matrix_hardware_counts"] == {"Pimoroni Interstate 75 W": 1}
    assert payload["matrix_last_seen"]

    device = payload["matrix_devices"][0]
    assert device["device_id"] == "i75w-test"
    assert device["label"] == "Desk Matrix"
    assert device["kind"] == "led_matrix"
    assert device["brand"] == "Pimoroni"
    assert device["model"] == "Interstate 75 W"
    assert device["hardware_name"] == "Pimoroni Interstate 75 W"
    assert device["panel_w"] == 256
    assert device["panel_h"] == 64
    assert device["firmware"] == "2.0"
    assert device["online"] is True


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
                        "aircraft_registration": "HB-JCA",
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
    monkeypatch.setattr(ui_server, "_setup_complete", lambda: True)
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


def test_api_radar_tiny_views_reuse_minimum_adsb_provider_payload(monkeypatch) -> None:
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

    calls: list[float] = []
    radii_seen: list[float] = []
    adsbx_module = types.ModuleType("localflight.sources.web.adsbexchange_client")
    adsbx_module.is_available = lambda: True
    adsbx_module.fetch_aircraft = lambda lat, lon, radius_nm, timeout_s=10: calls.append(radius_nm) or [
        {"hex": "near"},
        {"hex": "far"},
    ]

    def _to_blips(aircraft, center_lat, center_lon, radius_nm=50.0):
        radii_seen.append(radius_nm)
        return [
            {
                "callsign": "AIRBORNE",
                "lat": 47.4501,
                "lon": 8.5501,
                "altitude_m": 1200,
                "speed_ms": 115,
                "on_ground": False,
            },
            {
                "callsign": "SURFACE",
                "lat": 47.4502,
                "lon": 8.5502,
                "altitude_m": 0,
                "speed_ms": 2,
                "on_ground": True,
            }
        ]

    adsbx_module.aircraft_to_blips = _to_blips
    monkeypatch.setitem(sys.modules, "localflight.sources.web.adsbexchange_client", adsbx_module)

    first = ui_api.api_radar(1.0)
    second = ui_api.api_radar(2.0)

    assert calls == [5.0]
    assert radii_seen == [1.0, 2.0]
    assert first["provider_radius_nm"] == 5.0
    assert second["provider_radius_nm"] == 5.0
    assert first["raw_provider_count"] == 2
    assert first["radar_mode"] == "surface"
    assert first["count"] == 1
    assert first["airborne_filtered"] == 1
    assert first["blips"][0]["callsign"] == "SURFACE"
    assert second["source"] == "adsbexchange_cached"


def test_api_radar_filters_ground_blips_for_real_sources(monkeypatch) -> None:
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
        {"callsign": "AIRBORNE", "lat": 47.46, "lon": 8.56, "altitude_m": 1200, "speed_ms": 115, "on_ground": False},
        {"callsign": "SURFACE1", "lat": 47.47, "lon": 8.57, "altitude_m": 0, "speed_ms": 0, "on_ground": True},
        {"callsign": "SURFACE2", "lat": 47.48, "lon": 8.58, "altitude_m": 12, "speed_ms": 4},
    ]
    monkeypatch.setitem(sys.modules, "localflight.sources.web.adsbexchange_client", adsbx_module)

    result = ui_api.api_radar(20.0)

    assert result["source"] == "adsbexchange_live"
    assert result["count"] == 1
    assert result["ground_filtered"] == 2
    assert result["blips"][0]["callsign"] == "AIRBORNE"


def test_matrix_config_endpoint_round_trip(tmp_path: Path, monkeypatch) -> None:
    matrix_config = tmp_path / "matrix_config.json"
    monkeypatch.setattr(ui_api, "_matrix_config_path", lambda: matrix_config)
    monkeypatch.setattr(ui_api, "load_config", lambda: AppConfig(skin="technical"))

    client = TestClient(ui_api.app)

    response = client.get("/api/matrix/config")
    assert response.status_code == 200
    payload = response.json()
    assert {
        key: payload[key]
        for key in (
            "brightness",
            "max_rows",
            "refresh_seconds",
            "default_view",
            "page_rotation_seconds",
            "animation_enabled",
            "palette",
            "skin",
        )
    } == {
        "brightness": 0.8,
        "max_rows": 4,
        "refresh_seconds": 60,
        "default_view": "departures",
        "page_rotation_seconds": 10,
        "animation_enabled": True,
        "palette": "pax_blue",
        "skin": "technical",
    }
    assert isinstance(payload["clock_utc_epoch"], int)
    assert payload["clock_utc"]
    assert payload["clock_local"]
    assert "clock_local_offset_minutes" in payload

    response = client.post(
        "/api/matrix/config",
        json={
            "brightness": 0.55,
            "max_rows": 6,
            "refresh_seconds": 90,
            "page_rotation_seconds": 12,
            "default_view": "arrivals",
            "animation_enabled": False,
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "brightness": 0.55,
        "max_rows": 6,
        "refresh_seconds": 90,
        "page_rotation_seconds": 12,
        "default_view": "arrivals",
        "animation_enabled": False,
        "animation_mode": "static",
        "animation_speed": 3,
        "status_animation_enabled": True,
        "palette": "pax_blue",
        "options": {
            "animation_mode": "static",
            "palette": "pax_blue",
            "show_metar": True,
        },
    }
    saved = json.loads(matrix_config.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 2
    default = saved["configs"][0]
    assert default["brightness"] == 0.55
    assert default["max_rows"] == 6
    assert default["refresh_seconds"] == 90
    assert default["page_rotation_seconds"] == 12
    assert default["default_view"] == "arrivals"
    assert default["animation_enabled"] is False
    assert default["animation_mode"] == "static"
    assert default["palette"] == "pax_blue"


def test_matrix_v2_migrates_flat_config_and_registers_device(tmp_path: Path, monkeypatch) -> None:
    matrix_config = tmp_path / "matrix_config.json"
    matrix_config.write_text(
        json.dumps(
            {
                "brightness": 0.44,
                "max_rows": 3,
                "refresh_seconds": 120,
                "default_view": "arrivals",
                "page_rotation_seconds": 8,
                "animation_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ui_api, "_matrix_config_path", lambda: matrix_config)
    monkeypatch.setattr(ui_api, "load_config", lambda: AppConfig(airport_iata="ZRH", airport_icao="LSZH"))

    client = TestClient(ui_api.app)
    response = client.get("/api/matrix/v2/configs")
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == 2
    assert payload["configs"][0]["brightness"] == 0.44
    assert payload["configs"][0]["animation_enabled"] is False

    preset_payload = client.get("/api/matrix/v2/presets").json()
    presets = preset_payload["presets"]
    preset_ids = {item["id"] for item in presets}
    assert preset_ids == {"real_fids", "vatsim_pilot", "vatsim_atc"}
    palette_ids = {item["id"] for item in preset_payload["palettes"]}
    assert {"pax_blue", "solari_amber", "tower_scope", "vatsim_scope", "night_ops", "ice_white"} <= palette_ids

    response = client.post(
        "/api/matrix/v2/devices/checkin",
        json={
            "device_id": "i75w-test",
            "label": "Desk Board",
            "panel_w": 256,
            "panel_h": 64,
            "firmware": "2.0",
            "renderers": ["split_flap", "modern_fids"],
        },
    )
    assert response.status_code == 200
    device = response.json()["device"]
    assert device["device_id"] == "i75w-test"
    assert device["assigned_config_id"] == payload["default_config_id"]

    response = client.get("/api/matrix/v2/devices/i75w-test/config")
    assert response.status_code == 200
    resolved = response.json()
    assert resolved["renderer"] == "modern_fids"
    assert resolved["device_id"] == "i75w-test"


def test_matrix_v2_legacy_presets_normalize_to_three_public_profiles(tmp_path: Path, monkeypatch) -> None:
    matrix_config = tmp_path / "matrix_config.json"
    matrix_config.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "default_config_id": "old",
                "configs": [
                    {**ui_api._MATRIX_CONFIG_DEFAULTS, "id": "old", "preset": "classic_split_flap"},
                    {**ui_api._MATRIX_CONFIG_DEFAULTS, "id": "ops", "preset": "vatsim_ops"},
                    {**ui_api._MATRIX_CONFIG_DEFAULTS, "id": "radar", "preset": "radar_strip"},
                ],
                "devices": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ui_api, "_matrix_config_path", lambda: matrix_config)
    monkeypatch.setattr(ui_api, "load_config", lambda: AppConfig(airport_iata="ZRH", airport_icao="LSZH"))

    payload = TestClient(ui_api.app).get("/api/matrix/v2/configs").json()

    presets = {cfg["id"]: cfg["preset"] for cfg in payload["configs"]}
    assert presets == {"old": "real_fids", "ops": "vatsim_pilot", "radar": "real_fids"}


def test_matrix_v2_feed_adds_route_safe_fields_and_metar(tmp_path: Path, monkeypatch) -> None:
    matrix_config = tmp_path / "matrix_config.json"
    monkeypatch.setattr(ui_api, "_matrix_config_path", lambda: matrix_config)
    monkeypatch.setattr(
        ui_api,
        "load_config",
        lambda: AppConfig(airport_iata="DFW", airport_icao="KDFW", timezone="America/Chicago"),
    )
    monkeypatch.setattr(
        ui_api,
        "api_fids",
        lambda view, limit: [
            {
                "id": "flight-1",
                "display_time": "10:35",
                "flight_display": "AA 100",
                "route_display": "Dallas-Fort Worth (KDFW)",
                "status_display": "SCHEDULED",
                "status_class": "scheduled",
                "gate": "-",
                "aircraft_type": "A321",
                "callsign": "AAL100",
            }
        ],
    )
    monkeypatch.setattr(
        ui_api,
        "api_metar",
        lambda: {
            "flight_cat": "VFR",
            "flight_cat_color": "#00ff00",
            "weather_icon": "sun",
            "weather_label": "Clear",
            "raw_text": "METAR KDFW TEST",
            "wind_display": "180/08",
            "temperature_c": 29,
            "source": "test",
        },
    )

    client = TestClient(ui_api.app)
    response = client.get("/api/matrix/v2/devices/preview/feed?view=departures")

    assert response.status_code == 200
    payload = response.json()
    row = payload["rows"][0]
    assert row["route_display"] == "Dallas-Fort Worth (KDFW)"
    assert row["route_city"] == "Dallas-Fort Worth"
    assert row["route_code"] == "KDFW"
    assert row["route_matrix_label"] == "DALLAS-FORT WORTH KDFW"
    assert row["gate"] == "-"
    assert row["aircraft_type"] == "A321"
    assert row["callsign"] == "AAL100"
    assert payload["metar"]["weather_icon"] == "sun"
    assert payload["metar"]["temperature_display"] == "29 C"


def test_matrix_vatsim_preset_requires_virtual_source_without_real_fallback(tmp_path: Path, monkeypatch) -> None:
    matrix_config = tmp_path / "matrix_config.json"
    matrix_config.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "default_config_id": "default",
                "configs": [{**ui_api._MATRIX_CONFIG_DEFAULTS, "id": "default", "preset": "vatsim_pilot"}],
                "devices": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ui_api, "_matrix_config_path", lambda: matrix_config)
    monkeypatch.setattr(ui_api, "load_config", lambda: AppConfig(airport_iata="ZRH", airport_icao="LSZH", source="real"))
    monkeypatch.setattr(ui_api, "api_fids", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("real FIDS must not be fetched")))
    monkeypatch.setattr(ui_api, "api_metar", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("real METAR must not be fetched")))

    response = TestClient(ui_api.app).get("/api/matrix/v2/devices/preview/feed?view=departures")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_required"] == "virtual"
    assert payload["message"] == "SET SOURCE TO VATSIM"
    assert payload["rows"] == []
    assert payload["metar"] is None
    assert payload["weather_page"]["source"] == "vatsim"


def test_matrix_vatsim_atc_feed_pages_and_weather_are_vatsim_only(tmp_path: Path, monkeypatch) -> None:
    matrix_config = tmp_path / "matrix_config.json"
    matrix_config.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "default_config_id": "default",
                "configs": [{**ui_api._MATRIX_CONFIG_DEFAULTS, "id": "default", "preset": "vatsim_atc"}],
                "devices": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ui_api, "_matrix_config_path", lambda: matrix_config)
    monkeypatch.setattr(ui_api, "load_config", lambda: AppConfig(airport_iata="ZRH", airport_icao="LSZH", source="virtual"))
    monkeypatch.setattr(ui_api, "api_fids", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("real/snapshot FIDS must not be fetched")))
    monkeypatch.setattr(ui_api, "api_metar", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("real METAR fallback must not be fetched")))

    def vatsim_rows(*, cfg, view, limit):
        route = "London Heathrow (EGLL)" if view == "departures" else "Zurich (LSZH)"
        return [
            {
                "id": f"vatsim-{view}",
                "display_time": "12:00",
                "flight_display": "SWR100",
                "route_display": route,
                "status_display": "SCHEDULED",
                "status_class": "scheduled",
                "gate": "-",
                "aircraft_type": "A320",
                "callsign": "SWR100",
            }
        ]

    monkeypatch.setattr(ui_api, "_matrix_vatsim_rows", vatsim_rows)
    monkeypatch.setattr(
        ui_api,
        "_matrix_vatsim_weather",
        lambda cfg: {
            "flight_cat": "VFR",
            "flight_cat_color": "#00c040",
            "weather_icon": "sun",
            "weather_label": "Clear",
            "raw_text": "METAR LSZH 011200Z 28008KT CAVOK 12/04 Q1018",
            "wind_display": "280/08",
            "temperature_c": 12,
            "dewpoint_c": 4,
            "altimeter_hpa": 1018,
            "visibility_sm": 6.2,
            "clouds": [],
            "source": "vatsim",
        },
    )

    response = TestClient(ui_api.app).get("/api/matrix/v2/devices/preview/feed?view=arrivals")

    assert response.status_code == 200
    payload = response.json()
    assert payload["rows"][0]["route_code"] == "LSZH"
    assert payload["rows"][0]["gate"] == "-"
    assert set(payload["pages"]) == {"departures", "arrivals", "weather"}
    assert payload["pages"]["departures"][0]["route_code"] == "EGLL"
    assert payload["pages"]["arrivals"][0]["gate"] == "-"
    assert payload["metar"]["source"] == "vatsim"
    assert payload["weather_page"]["available"] is True
    assert "LSZH VATSIM WX" in payload["weather_page"]["lines"]


def test_matrix_vatsim_weather_does_not_use_real_metar_fallback(monkeypatch) -> None:
    import localflight.sources.web.metar_client as metar_client_module
    import localflight.sources.web.vatsim_client as vatsim_client_module

    monkeypatch.setattr(
        vatsim_client_module,
        "fetch_vatsim_data_cached",
        lambda: {
            "pilots": [],
            "atis": [
                {
                    "callsign": "LSZH_ATIS",
                    "text_atis": ["Controller Name CID 123456", "METAR LSZH 011200Z 28008KT CAVOK 12/04 Q1018"],
                }
            ],
        },
    )
    monkeypatch.setattr(
        metar_client_module,
        "fetch_metar",
        lambda icao: (_ for _ in ()).throw(AssertionError("real METAR must not be fetched")),
    )

    metar = ui_api._matrix_vatsim_weather(AppConfig(airport_iata="ZRH", airport_icao="LSZH", source="virtual"))

    assert metar["source"] == "vatsim"
    assert metar["temp_c"] == 12
    assert "Controller" not in metar["raw_text"]


def test_matrix_route_fields_preserve_icao_only_codes() -> None:
    fields = ui_api._matrix_route_fields("KJFK")

    assert fields == {
        "route_city": "",
        "route_code": "KJFK",
        "route_matrix_label": "KJFK",
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
                'DEVICE_LABEL = "Interstate 75 W"',
                "PANEL_W       = 256",
                "PANEL_H       = 64",
                "MAX_ROWS      = 4",
                "REFRESH_S     = 60",
                "PAGE_ROTATION_S = 10",
                "BRIGHTNESS    = 0.80",
                'DEFAULT_VIEW  = "departures"',
                "ANIMATION_ENABLED = True",
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
            "page_rotation_seconds": 14,
            "brightness": 0.55,
            "default_view": "arrivals",
            "animation_enabled": False,
        },
    )

    assert response.status_code == 200
    assert 'WIFI_SSID     = "BoardNet"' in response.text
    assert 'WIFI_PASSWORD = "secret123"' in response.text
    assert 'API_HOST      = "localflight.local"' in response.text
    assert "API_PORT      = 8000" in response.text
    assert 'DEVICE_LABEL  = "Interstate 75 W"' in response.text
    assert "PANEL_W       = 256" in response.text
    assert "PANEL_H       = 64" in response.text
    assert "MAX_ROWS      = 6" in response.text
    assert "REFRESH_S     = 120" in response.text
    assert "PAGE_ROTATION_S = 14" in response.text
    assert "BRIGHTNESS    = 0.55" in response.text
    assert 'DEFAULT_VIEW  = "arrivals"' in response.text
    assert "ANIMATION_ENABLED = False" in response.text


def test_matrix_script_endpoint_uses_current_i75w_client_template() -> None:
    client = TestClient(ui_api.app)
    response = client.post(
        "/api/matrix/script",
        json={
            "wifi_ssid": "BoardNet",
            "wifi_password": "",
            "api_host": "localflight.local",
            "api_port": 8000,
            "panel_w": 256,
            "panel_h": 64,
            "max_rows": 4,
            "refresh_seconds": 60,
            "brightness": 0.8,
            "default_view": "departures",
            "animation_enabled": True,
        },
    )

    assert response.status_code == 200
    script = response.text
    compile(script, "generated-main.py", "exec")
    assert 'CLIENT_VER       = "2.0"' in script
    assert "import interstate75 as interstate75_module" in script
    assert "def update_display():" in script
    assert "def fit_text(value, length):" in script
    assert "def _text_field(value, fallback=\"\"):" in script
    assert "def _clock_hhmm(offset_minutes=0):" in script
    assert "clock_utc_epoch" in script
    assert "ACTIVE_BREATH" in script
    assert "AMBER_BREATH" in script
    assert "def cycle_chunks(value, width, code=\"\"):" in script
    assert "def code_preserve(value, code, width):" in script
    assert "def marquee(value, width, step=None):" in script
    assert "def draw_glyph(name, x, y, color):" in script
    assert "route_matrix_label" in script
    assert "def _weather_line(chars=18):" in script
    assert "SHOW_WEATHER" in script
    assert "_airport_label" in script
    assert '"temp": ["00100", "01010", "01010", "10001", "01110"]' in script
    assert '"WX "' not in script
    assert "def draw_vatsim_weather_page():" in script
    assert "def draw_vatsim_atc(flap_rows, fallback_rows, fallback_view):" in script
    assert "\"real_fids\"" in script
    assert "\"vatsim_pilot\"" in script
    assert "\"vatsim_atc\"" in script
    assert ".ljust(" not in script
    assert "DISPLAY, DISPLAY_PANELS = _display_for_size(PANEL_W, PANEL_H)" in script
    assert "Unsupported Interstate 75 display size" in script
    assert "compact = WIDTH < 180" in script
    assert "draw_row(flap_rows[i], row_data, y, row_h)" in script
    assert "text[39:43]" in script
    assert "CODE_SHARE_ROTATION_S = 4" in script
    assert "def _flight_cycle_display(row):" in script
    assert "limit=min(_visible_rows() * 4, 32)" in script
    assert "urequests.get(_api_url(path))" in script
    assert "timeout=timeout" not in script
    assert "/api/matrix/v2/devices/checkin" in script
    assert "/api/matrix/v2/devices/{device_id()}/config" in script
    assert "/api/matrix/v2/devices/{device_id()}/feed?view={view}" in script
    assert 'HARDWARE_BRAND = "Pimoroni"' in script
    assert 'HARDWARE_MODEL = "Interstate 75 W"' in script
    assert 'HARDWARE_NAME  = "Pimoroni Interstate 75 W"' in script
    assert '"hardware_name": HARDWARE_NAME' in script
    assert "CONFIG_REFRESH_S = 60" in script
    assert "old_view = view" in script
    assert "if DEFAULT_VIEW != old_view:" in script
    assert '"pax_blue"' in script
    assert '"solari_amber"' in script
    assert '"tower_scope"' in script
    assert '"vatsim_scope"' in script
    assert '"night_ops"' in script
    assert '"ice_white"' in script


def test_matrix_payloads_use_city_label_and_decoded_weather_display() -> None:
    cfg = AppConfig(airport_iata="SIN", airport_icao="WSSS", timezone="Asia/Singapore")
    airport = ui_api._matrix_airport_payload(cfg)
    assert airport["airport_display_name"] == "Singapore"
    assert airport["airport_label"] == "Singapore"

    metar = ui_api._matrix_metar_payload({
        "flight_cat": "VFR",
        "weather_label": "Clear",
        "weather_icon": "sun",
        "temperature_c": 30,
        "wind_display": "090/08",
    })
    assert metar is not None
    assert metar["condition_display"] == "Clear"
    assert metar["temperature_short"] == "30C"
    assert metar["weather_display"] == "Clear 30C"


def test_matrix_preview_download_payload_uses_defined_animation_state() -> None:
    root = Path(__file__).resolve().parents[1]
    template = (root / "src" / "localflight" / "ui" / "templates" / "matrix_preview.html").read_text(encoding="utf-8")

    assert 'animation_enabled: ANIMATION_MODE !== "static"' in template
    assert "animation_enabled: ANIMATION_ENABLED" not in template
    assert "SHOW_WEATHER" in template
    assert "weatherToggle" in template
    assert 'id="paletteSelect"' in template
    assert 'id="animationSpeedSelect"' in template
    assert 'id="statusMotionToggle"' in template
    assert "Toggle without reflashing" in template
    assert "Reflash when these change" in template
    assert "Apply to board" in template
    assert "about 60 seconds" in template
    assert "function setPreviewPalette(name)" in template
    assert "MATRIX_PALETTE_OPTIONS" in template
    assert "palette: MATRIX_PALETTE" in template
    assert "condition_display" in template
    assert 'WX ${' not in template


def test_matrix_preview_panel_geometry_stays_in_sync() -> None:
    root = Path(__file__).resolve().parents[1]
    template = (root / "src" / "localflight" / "ui" / "templates" / "matrix_preview.html").read_text(encoding="utf-8")

    assert "function syncPanelGeometry(w, h)" in template
    assert 'id="panelWidthInput"' in template
    assert 'id="panelHeightInput"' in template
    assert "window.setCustomPanelSize" in template
    assert 'value="128x128"' in template
    assert 'value="256x128"' in template
    assert "const compact = PANEL_W < 180" in template
    assert "if (compact)" in template
    assert "txt.slice(39,43)" in template
    assert "function flightCycleDisplay(row)" in template
    assert "function codeshareFlightNumbers(row)" in template
    assert "function breathAmount(periodMs = 1800)" in template
    assert "Math.floor(performance.now()/240)" not in template
    assert "function cycleChunks(value, width, code = \"\")" in template
    assert "const code_preserve = codePreserve" in template
    assert "function routeChunk(row, chars)" in template
    assert "function visibleRows()" in template
    assert "function drawGlyph(name, x, y, color)" in template
    assert "Real FIDS" in template
    assert "VATSIM pilot" in template
    assert "VATSIM ATC" in template
    assert "function drawVatsimWeatherPage()" in template
    assert "function vatsimAtcPage()" in template
    assert "lastCodeshareCycle" in template
    assert "const fetchLimit = Math.min(visibleRows() * 4, 32)" in template
    assert "canvas.style.width" in template
    assert "canvas.style.height" in template
    assert "let RENDER_PIXEL_SIZE = PIXEL_SIZE" in template
    assert "PANEL_W * PANEL_H <= 180000" in template
    assert "syncPanelGeometry(w, h);" in template
    assert "syncPanelGeometry(d.panel_w, d.panel_h);" in template
    assert "64px-tall HUB75 chains only" not in template


def test_native_matrix_panel_geometry_matches_web_controls() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "src" / "localflight" / "native" / "_legacy_app.py").read_text(encoding="utf-8")

    assert '("128 x 64 - 1 rectangular module", 128, 64)' in source
    assert '("256 x 64 - 2 across", 256, 64)' in source
    assert '("128 x 128 - 2 stacked", 128, 128)' in source
    assert '("256 x 128 - 2 by 2", 256, 128)' in source
    assert "self.panel_w = self.QtWidgets.QSpinBox()" in source
    assert "self.panel_h = self.QtWidgets.QSpinBox()" in source
    assert 'form_layout.addRow("Panel size", self._panel_size_row())' in source
    assert "def _panel_dimensions_changed" in source
    assert "if self.panel_w < 180:" in source
    assert "text[39:43]" in source
    assert "def _flight_cycle_display" in source
    assert "def _codeshare_flights" in source
    assert "def _breath_color" in source
    assert "math.sin((self.phase / 24.0)" in source
    assert "def cycle_chunks" in source
    assert "def code_preserve" in source
    assert "def _route_chunk" in source
    assert "def _visible_rows" in source
    assert "def _weather_page_lines" in source
    assert "def _vatsim_atc_page" in source
    assert "set_matrix_payload" in source
    assert "/api/matrix/v2/devices/preview/feed" in source
    assert '"pax_blue"' in source
    assert '"tower_scope"' in source
    assert '"night_ops"' in source


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

    monkeypatch.setattr(bug_reporter, "_crash_fingerprint", lambda msg, context="": f"fp-{context}-{msg}")
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


def test_bug_reporter_routes_native_gui_reports_to_desktop(monkeypatch) -> None:
    submitted: list[dict] = []
    monkeypatch.setattr(bug_reporter, "_auto_diagnostics_mode", lambda: "auto")
    monkeypatch.setattr(bug_reporter, "_crash_fingerprint", lambda msg, context="": f"fp-{context}-{msg}")
    monkeypatch.setattr(bug_reporter, "_already_crash_filed", lambda fp: False)
    monkeypatch.setattr(bug_reporter, "_mark_crash_filed", lambda fp: None)
    monkeypatch.setattr(
        bug_reporter,
        "_system_metadata",
        lambda: {
            "install_id": "00000000-0000-0000-0000-000000000223",
            "install_fingerprint": "fp-test",
            "activation_token": "",
            "app_version": "test",
            "platform": "Windows",
            "os": "Windows 11",
            "arch": "amd64",
            "python_version": "3.13",
            "airport": "ZRH",
            "source": "virtual",
            "api_mode": "community relay",
            "diagnostics_mode": "auto",
        },
    )
    monkeypatch.setattr(bug_reporter, "_system_context", lambda client_context="": client_context)
    monkeypatch.setattr(
        bug_reporter,
        "_post_relay_report",
        lambda payload: submitted.append(payload) or {"ok": True, "url": "https://linear.test/native", "team": "desktop"},
    )

    manual = bug_reporter.submit_report("Native button issue", "Native report details", "native/gui; screen=feedback")
    crash = bug_reporter.submit_crash(
        "Native interaction crash",
        traceback_str="stack",
        context="native/gui",
        client_context="native/gui; screen=radar",
    )

    assert manual["ok"] is True
    assert crash["ok"] is True
    assert submitted[0]["origin"] == "desktop"
    assert submitted[0]["report_type"] == "manual"
    assert submitted[1]["origin"] == "desktop"
    assert submitted[1]["report_type"] == "crash"
    assert submitted[1]["context"] == "native/gui"


def test_feedback_api_routes_mobile_reports_with_ios_origin(monkeypatch) -> None:
    submitted: list[dict] = []
    monkeypatch.setattr(
        bug_reporter,
        "_system_metadata",
        lambda: {
            "install_id": "00000000-0000-0000-0000-000000000333",
            "install_fingerprint": "fp-test",
            "activation_token": "",
            "app_version": "test",
            "platform": "Darwin",
            "os": "iOS 18.0",
            "arch": "arm64",
            "python_version": "3.11",
            "airport": "ZRH",
            "source": "real",
            "api_mode": "community relay",
            "diagnostics_mode": "auto",
        },
    )
    monkeypatch.setattr(bug_reporter, "_system_context", lambda client_context="": client_context)
    monkeypatch.setattr(
        bug_reporter,
        "_post_relay_report",
        lambda payload: submitted.append(payload) or {
            "ok": True,
            "url": "https://linear.test/mobile-manual",
            "team": "ios",
            "deduped": False,
        },
    )

    response = TestClient(ui_api.app).post(
        "/api/feedback",
        json={
            "title": "Mobile button issue",
            "description": "The board detail drawer feels stuck",
            "client_context": "Companion OS  iOS 18.0\nCompanion ID  lfc_ios_test",
        },
    )

    assert response.status_code == 200
    assert submitted[0]["report_type"] == "manual"
    assert submitted[0]["origin"] == "ios"
    assert submitted[0]["title"] == "Mobile button issue"
    assert "Companion ID" in submitted[0]["client_context"]
    assert response.json()["team"] == "ios"
    assert response.json()["deduped"] is False
    assert response.json()["url"] == "https://linear.test/mobile-manual"


def test_feedback_crash_api_routes_mobile_crashes_with_context(monkeypatch) -> None:
    submitted: list[dict] = []
    monkeypatch.setattr(bug_reporter, "_auto_diagnostics_mode", lambda: "auto")
    monkeypatch.setattr(bug_reporter, "_crash_fingerprint", lambda msg, context="": f"fp-{context}-{msg}")
    monkeypatch.setattr(bug_reporter, "_already_crash_filed", lambda fp: False)
    monkeypatch.setattr(bug_reporter, "_mark_crash_filed", lambda fp: None)
    monkeypatch.setattr(
        bug_reporter,
        "_system_metadata",
        lambda: {
            "install_id": "00000000-0000-0000-0000-000000000334",
            "install_fingerprint": "fp-test",
            "activation_token": "",
            "app_version": "test",
            "platform": "Darwin",
            "os": "iOS 18.0",
            "arch": "arm64",
            "python_version": "3.11",
            "airport": "ZRH",
            "source": "real",
            "api_mode": "community relay",
            "diagnostics_mode": "auto",
        },
    )
    monkeypatch.setattr(bug_reporter, "_system_context", lambda client_context="": client_context)
    monkeypatch.setattr(
        bug_reporter,
        "_post_relay_report",
        lambda payload: submitted.append(payload) or {
            "ok": True,
            "url": "https://linear.test/mobile-crash",
            "team": "ios",
            "deduped": False,
        },
    )

    response = TestClient(ui_api.app).post(
        "/api/feedback/crash",
        json={
            "message": "Mobile render crash",
            "traceback": "stack",
            "context": "mobile/manual-auto-test",
            "client_context": "Companion OS  iOS 18.0\nCompanion ID  lfc_ios_test",
        },
    )

    assert response.status_code == 200
    assert submitted[0]["report_type"] == "crash"
    assert submitted[0]["origin"] == "ios"
    assert submitted[0]["context"] == "mobile/manual-auto-test"
    assert submitted[0]["traceback"] == "stack"
    assert response.json()["team"] == "ios"
    assert response.json()["deduped"] is False


def test_crash_fingerprint_is_scoped_by_context() -> None:
    assert bug_reporter._crash_fingerprint("Same message", context="desktop") != bug_reporter._crash_fingerprint(
        "Same message",
        context="mobile",
    )


def test_system_context_reports_schedule_mode_and_board_window(monkeypatch) -> None:
    class DummyCfg:
        airport_iata = "OMDB"
        source = "real"
        diagnostics_mode = "auto_logs"
        timezone = "Asia/Dubai"
        display_grace_minutes = 45
        display_horizon_hours = 16
        web_row_limit = 24
        web_rotation_seconds = 12

    monkeypatch.setattr(storage_config, "load_config", lambda: DummyCfg())
    monkeypatch.setattr(
        bug_reporter,
        "_schedule_mode_context",
        lambda source: {
            "mode_label": "managed relay (shared snapshot)",
            "transport": "relay",
            "shared_snapshot": True,
            "relay_url": "https://relay.example.test/v1/flights",
        },
    )
    monkeypatch.setattr(storage_install, "get_install_fingerprint", lambda: "install-test")
    monkeypatch.setattr(
        bug_reporter,
        "_gui_launch_context",
        lambda: {
            "requested": "native",
            "effective": "native",
            "platform": "windows",
            "display": "yes",
            "qt": "yes",
            "fullscreen": "no",
            "reason": "native requested and Qt available",
        },
    )

    context = bug_reporter._system_context("Reporter\tmobile")

    assert "- **Schedule mode:** managed relay (shared snapshot)" in context
    assert "- **Transport:** relay" in context
    assert "- **Shared snapshot path:** yes" in context
    assert "- **Display window:** -45m / +16h" in context
    assert "- **Web board:** 24 rows, rotate 12s" in context
    assert "- **GUI requested:** native" in context
    assert "- **GUI effective shell:** native" in context
    assert "- **GUI Qt available:** yes" in context
    assert "- **Relay URL:** https://relay.example.test/v1/flights" in context
    assert "**Reporter environment**" in context


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

    assert relay_defaults.default_public_relay_url() == "https://localflight-community-relay.fly.dev"


def test_setup_relay_url_validation_blocks_untrusted_roots(monkeypatch) -> None:
    monkeypatch.delenv("LOCALFLIGHT_ALLOW_CUSTOM_RELAY_URL", raising=False)
    monkeypatch.delenv("LOCALFLIGHT_ALLOW_PRIVATE_RELAY_URL", raising=False)
    default_url = "https://localflight-community-relay.fly.dev"

    assert relay_defaults.validate_public_relay_url(default_url, trusted_default=default_url) == default_url
    assert relay_defaults.validate_public_relay_url(
        "https://relay.localflight.app/v1/flights",
        trusted_default=default_url,
    ) == "https://relay.localflight.app/v1/flights"

    with pytest.raises(ValueError, match="Custom relay hosts"):
        relay_defaults.validate_public_relay_url("https://relay.example.test/v1/flights", trusted_default=default_url)
    with pytest.raises(ValueError, match="Private or local"):
        relay_defaults.validate_public_relay_url("http://127.0.0.1:8080/v1/flights", trusted_default=default_url)

    monkeypatch.setenv("LOCALFLIGHT_ALLOW_CUSTOM_RELAY_URL", "1")
    assert relay_defaults.validate_public_relay_url(
        "https://relay.example.test/v1/flights",
        trusted_default=default_url,
    ) == "https://relay.example.test/v1/flights"

    monkeypatch.setenv("LOCALFLIGHT_ALLOW_PRIVATE_RELAY_URL", "1")
    assert relay_defaults.validate_public_relay_url(
        "http://127.0.0.1:8080/v1/flights",
        trusted_default=default_url,
    ) == "http://127.0.0.1:8080/v1/flights"


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
        "/api/radar/surface",
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
        "/api/docs/{slug}",
    }

    assert expected.issubset(paths)


def test_api_docs_serves_bundled_markdown(monkeypatch) -> None:
    monkeypatch.setattr(ui_server, "_setup_complete", lambda: True)

    response = TestClient(ui_server.app).get("/api/docs/readme")

    assert response.status_code == 200
    payload = response.json()
    assert payload["slug"] == "readme"
    assert payload["title"] == "Project README"
    assert payload["filename"] == "README.md"
    assert payload["bundled"] is True
    assert payload["content"].startswith("# Local Flight")
    assert payload["github_url"].startswith("https://github.com/tr3y4rch/local-flight")


def test_api_docs_rejects_unknown_slug(monkeypatch) -> None:
    monkeypatch.setattr(ui_server, "_setup_complete", lambda: True)

    response = TestClient(ui_server.app).get("/api/docs/nope")

    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found"


def test_api_docs_returns_fallback_when_bundled_file_missing(monkeypatch) -> None:
    monkeypatch.setattr(ui_server, "_setup_complete", lambda: True)
    monkeypatch.setitem(
        ui_server._DOC_PAGES,
        "missing",
        {
            "title": "Missing Test Doc",
            "filename": "MISSING_TEST_DOC.md",
            "summary": "Fallback coverage",
            "github_url": "https://github.com/tr3y4rch/local-flight/blob/main/MISSING_TEST_DOC.md",
        },
    )

    response = TestClient(ui_server.app).get("/api/docs/missing")

    assert response.status_code == 200
    payload = response.json()
    assert payload["slug"] == "missing"
    assert payload["bundled"] is False
    assert payload["content"] == "MISSING_TEST_DOC.md is not bundled with this build."


def test_relay_route_contracts_cover_public_and_admin_surfaces() -> None:
    paths = {getattr(route, "path", None) for route in relay_main.app.router.routes}

    expected = {
        "/",
        "/health",
        "/admin",
        "/admin/api/overview",
        "/admin/api/usage",
        "/admin/api/schedules",
        "/admin/api/surfaces",
        "/admin/api/activations",
        "/admin/api/reports",
        "/admin/api/providers/save",
        "/admin/api/providers/clear",
        "/admin/api/activation/create",
        "/admin/api/activation/token-action",
        "/admin/api/activation/request-action",
        "/admin/api/counters/reset",
        "/admin/api/counters/correct-schedule",
        "/admin/api/install/access",
        "/admin/api/maintenance/clean-trial",
        "/v1/flights",
        "/v1/radar",
        "/v1/airport-surface",
        "/v1/reports",
        "/v1/activate",
        "/v1/client/status",
        "/v1/client/checkin",
        "/v1/managed/config",
    }

    assert expected.issubset(paths)


def test_gui_mode_defaults_to_native_only_when_a_local_display_is_expected() -> None:
    assert resolve_gui_mode(Platform.WINDOWS, {}) == "native"
    assert resolve_gui_mode(Platform.MACOS, {}) == "native"
    assert resolve_gui_mode(Platform.RASPBERRY_PI, {}) == "headless"
    assert resolve_gui_mode(Platform.RASPBERRY_PI, {"DISPLAY": ":0"}) == "native"
    assert resolve_gui_mode(Platform.LINUX, {"WAYLAND_DISPLAY": "wayland-0"}) == "native"
    assert resolve_gui_mode(Platform.WINDOWS, {"LOCALFLIGHT_GUI_MODE": "browser"}) == "browser"
    assert resolve_gui_mode(Platform.WINDOWS, {"LOCALFLIGHT_GUI_MODE": "nonsense"}) == "native"


def test_release_installers_keep_pi_headless_default_and_windows_native() -> None:
    pi_install = Path("installers/pi/install.sh").read_text(encoding="utf-8")
    pi_helper = Path("installers/pi/lf.sh").read_text(encoding="utf-8")
    win_install = Path("installers/windows/install.ps1").read_text(encoding="utf-8")

    assert 'PI_GUI_MODE="headless"' in pi_install
    assert "LOCALFLIGHT_GUI_MODE=headless" in pi_install
    assert 'PI_GUI_MODE="native"' in pi_install
    assert "grep -Eq" in pi_helper
    assert "import PySide6" not in pi_helper
    assert "LOCALFLIGHT_GUI_MODE=native" in win_install
    assert ".env.example" not in win_install


def test_network_admin_client_accepts_relay_root_or_admin_url() -> None:
    assert _normalize_relay_base_url("https://localflight-community-relay.fly.dev") == "https://localflight-community-relay.fly.dev"
    assert _normalize_relay_base_url("https://localflight-community-relay.fly.dev/admin") == "https://localflight-community-relay.fly.dev"
    assert _normalize_relay_base_url("https://localflight-community-relay.fly.dev/admin/api") == "https://localflight-community-relay.fly.dev"
