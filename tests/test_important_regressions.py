from __future__ import annotations

import json
import sys
import threading
import types
import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient

import localflight.scheduler.control as scheduler_control
import localflight.scheduler.jobs as jobs
import localflight.scheduler.runtime as runtime
import localflight.__main__ as localflight_main
import localflight.sources.web.adsbexchange_client as adsbexchange_client
import localflight.sources.web.aerodatabox_client as aerodatabox_client
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
from localflight.core.models import AirportRef, Flight, FlightDirection, FlightPosition, FlightTime
from localflight.companion_pairing import build_pairing_deep_link, pairing_gateway_payload
from localflight.decode.metar import decorate_metar
from localflight.decode.dedupe import dedupe_codeshares
from localflight.decode.mappings.aerodatabox import aerodatabox_to_raw_records
from localflight.decode.normalize import normalize_flights
from localflight.display.fids_from_flights import flight_to_fids_row
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


def test_install_identity_migrates_legacy_id_and_restores_from_anchor(tmp_path: Path, monkeypatch) -> None:
    import shutil

    install_id = "00000000-0000-4000-8000-000000000321"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("LOCALFLIGHT_ACTIVATION_TOKEN", raising=False)
    config_dir = tmp_path / ".localflight"
    config_dir.mkdir()
    (config_dir / "install_id").write_text(install_id, encoding="utf-8")

    assert storage_install.get_install_id() == install_id
    assert json.loads((config_dir / "install_identity.json").read_text(encoding="utf-8"))["install_id"] == install_id
    assert json.loads((tmp_path / ".localflight_identity.json").read_text(encoding="utf-8"))["install_id"] == install_id

    shutil.rmtree(config_dir)

    assert storage_install.get_install_id() == install_id
    assert (config_dir / "install_id").read_text(encoding="utf-8") == install_id


def test_setup_reset_preserves_identity_and_token_but_new_identity_clears_token(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("LOCALFLIGHT_ACTIVATION_TOKEN", raising=False)
    install_id = storage_install.get_install_id()
    storage_install.set_activation_token("lfm_old_token")
    marker = tmp_path / ".localflight" / "setup_complete"
    marker.write_text("ok", encoding="utf-8")

    result = ui_server.api_setup_reset()

    assert result["ok"] is True
    assert not marker.exists()
    assert storage_install.get_install_id() == install_id
    assert storage_install.get_activation_token() == "lfm_old_token"

    new_id = storage_install.new_install_identity()

    assert new_id != install_id
    assert storage_install.get_install_id() == new_id
    assert storage_install.get_activation_token() == ""


def test_setup_activate_reuses_valid_stored_token_without_reissuing(tmp_path: Path, monkeypatch) -> None:
    import asyncio
    import requests

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("LOCALFLIGHT_ACTIVATION_TOKEN", raising=False)
    storage_install.set_activation_token("lfm_existing_token")
    calls: list[str] = []

    class _Response:
        status_code = 200
        headers: dict[str, str] = {}

        def json(self) -> dict[str, object]:
            return {
                "ok": True,
                "plan": "managed",
                "token_prefix": "lfm_existi",
                "known_install": True,
                "can_reissue": True,
            }

    def _get(*args, **kwargs):
        calls.append("status")
        return _Response()

    def _post(*args, **kwargs):
        calls.append("activate")
        raise AssertionError("valid stored token should be verified, not reissued")

    monkeypatch.setattr(requests, "get", _get)
    monkeypatch.setattr(requests, "post", _post)

    result = asyncio.run(ui_server.setup_activate(ui_server.ActivationSetupIn(relay_url="https://localflight-community-relay.fly.dev")))

    assert result["ok"] is True
    assert result["activation_token_present"] is True
    assert result["activation_token_prefix"] == "lfm_existi"
    assert calls == ["status"]


def test_setup_activate_repairs_invalid_stored_token_with_reissue(tmp_path: Path, monkeypatch) -> None:
    import asyncio
    import requests

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("LOCALFLIGHT_ACTIVATION_TOKEN", raising=False)
    storage_install.set_activation_token("lfm_stale_token")
    calls: list[str] = []

    class _StatusResponse:
        status_code = 403
        headers: dict[str, str] = {}

        def json(self) -> dict[str, object]:
            return {"detail": "Activation token invalid or revoked"}

    class _ActivateResponse:
        status_code = 200
        headers: dict[str, str] = {}

        def json(self) -> dict[str, object]:
            return {
                "ok": True,
                "status": "issued",
                "activation_token": "lfm_fresh_token",
                "token_prefix": "lfm_fresh",
                "known_install": True,
                "can_reissue": True,
            }

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: calls.append("status") or _StatusResponse())
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: calls.append("activate") or _ActivateResponse())

    result = asyncio.run(ui_server.setup_activate(ui_server.ActivationSetupIn(relay_url="https://localflight-community-relay.fly.dev")))

    assert calls == ["status", "activate"]
    assert result["ok"] is True
    assert result["activation_token_present"] is True
    assert result["activation_token_prefix"] == "lfm_fresh"
    assert storage_install.get_activation_token() == "lfm_fresh_token"


def test_setup_relay_errors_are_typed_and_friendly(tmp_path: Path, monkeypatch) -> None:
    import asyncio
    import requests

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("LOCALFLIGHT_ACTIVATION_TOKEN", raising=False)
    storage_install.set_activation_token("lfm_wrong_token")

    class _Response:
        status_code = 403
        headers: dict[str, str] = {}

        def json(self) -> dict[str, object]:
            return {"detail": "Activation token already bound to another install"}

    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: _Response())

    result = asyncio.run(ui_server.setup_client_status(ui_server.ClientStatusSetupIn(relay_url="https://localflight-community-relay.fly.dev")))

    assert result["ok"] is False
    assert result["status"] == "token_bound_elsewhere"
    assert "another Local Flight install" in result["error"]
    assert "HTTP 403" not in result["error"]


def test_managed_relay_auth_failure_sets_local_cooldown(tmp_path: Path, monkeypatch) -> None:
    import requests

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("LOCALFLIGHT_ACTIVATION_TOKEN", raising=False)
    storage_install.set_activation_token("lfm_stale_token")
    calls = {"count": 0}

    class _Response:
        status_code = 403
        headers: dict[str, str] = {}

        def json(self) -> dict[str, object]:
            return {"detail": "Activation token invalid or revoked"}

    def _get(*args, **kwargs):
        calls["count"] += 1
        return _Response()

    monkeypatch.setattr(requests, "get", _get)

    with pytest.raises(aviationstack_client.AviationstackBudgetExceeded) as first:
        aviationstack_client.fetch_relay_schedule_records(
            airport_iata="ZRH",
            timezone_name="Europe/Zurich",
            display_grace_minutes=30,
            display_horizon_hours=12,
            refresh_seconds=3600,
        )

    assert first.value.status_code == 403
    assert calls["count"] == 1

    with pytest.raises(aviationstack_client.AviationstackRelayCooldown):
        aviationstack_client.fetch_relay_schedule_records(
            airport_iata="ZRH",
            timezone_name="Europe/Zurich",
            display_grace_minutes=30,
            display_horizon_hours=12,
            refresh_seconds=3600,
        )

    assert calls["count"] == 1


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
            "codeshares": ["SWR100"],
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
    assert row.codeshare_display == "Sold as UA 100"


def test_omdb_operating_callsign_becomes_primary_and_marketed_is_sold_as() -> None:
    scheduled = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc).isoformat()
    records = [
        {
            "callsign": "FDB2MY",
            "direction": "DEP",
            "status": "scheduled",
            "scheduled": scheduled,
            "airline_iata": "EK",
            "airline_name": "Emirates",
            "flight_number": "EK2131",
            "destination_iata": "KHI",
        }
    ]

    flights = normalize_flights(records, airport_iata="DXB", airport_icao="OMDB", source_name="test")

    assert len(flights) == 1
    flight = flights[0]
    assert flight.airline.iata == "FZ"
    assert flight.airline.name == "flydubai"
    assert flight.flight_number == "FZ2MY"
    assert flight.operating_callsign == "FDB2MY"
    assert flight.marketing_flight_number == "EK2131"
    assert "EK2131" in flight.sold_as
    row = flight_to_fids_row(flight, view="departures", display_tz=ZoneInfo("UTC"))
    assert row.flight_display == "FZ 2MY"
    assert row.airline_display == "flydubai"
    assert row.codeshare_display == "Sold as EK 2131"


def test_omdb_flydubai_codeshare_becomes_primary_when_provider_markets_ek() -> None:
    scheduled = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc).isoformat()
    records = [
        {
            "callsign": "UAE2426",
            "direction": "DEP",
            "status": "scheduled",
            "scheduled": scheduled,
            "airline_iata": "EK",
            "airline_name": "Emirates",
            "flight_number": "EK2426",
            "codeshares": ["FZ315"],
            "destination_iata": "KHI",
        }
    ]

    flight = normalize_flights(records, airport_iata="DXB", airport_icao="OMDB", source_name="test")[0]

    assert flight.airline.iata == "FZ"
    assert flight.flight_number == "FZ315"
    assert flight.identity_source == "airport_codeshare_hint"
    assert "EK2426" in flight.sold_as
    row = flight_to_fids_row(flight, view="departures", display_tz=ZoneInfo("UTC"))
    assert row.flight_display == "FZ 315"
    assert row.codeshare_display == "Sold as EK 2426"


def test_vatsim_fids_row_uses_pilot_contract_and_suppresses_passenger_fields() -> None:
    from localflight.core.models import AirlineRef, FlightStatus

    flight = Flight(
        direction=FlightDirection.DEPARTURE,
        airport=AirportRef(iata="ZRH", icao="LSZH"),
        callsign="BAW123",
        airline=AirlineRef(name="British Airways", iata="BA", icao="BAW"),
        flight_number="BA123",
        codeshares=("AA9000",),
        sold_as=("BA123",),
        marketing_airline_name="British Airways",
        marketing_airline_iata="BA",
        marketing_airline_icao="BAW",
        marketing_flight_number="BA123",
        operating_callsign="BAW123",
        destination=AirportRef(icao="EGLL", name="Heathrow"),
        aircraft_type="A320",
        aircraft_registration="G-TEST",
        gate="A42",
        terminal="1",
        status=FlightStatus.SCHEDULED,
        times=FlightTime(scheduled=datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)),
        delay_minutes=18,
        flight_rules="I",
        planned_route="DCT TEST",
        planned_altitude="FL350",
        assigned_transponder="2201",
        position=FlightPosition(lat=47.3, lon=8.4, altitude_baro=3048, speed_ms=120, squawk="7000"),
        source="vatsim",
    )

    row = flight_to_fids_row(flight, view="departures", display_tz=ZoneInfo("UTC"))

    assert row.detail_mode == "virtual"
    assert row.flight_display == "BAW123"
    assert row.airline_display == ""
    assert row.airline_iata == ""
    assert row.airline_icao == ""
    assert row.codeshare_display == ""
    assert row.codeshares == ()
    assert row.sold_as == ()
    assert row.marketing_flight_number == ""
    assert row.gate == "-"
    assert row.gate_display == ""
    assert row.terminal_display == ""
    assert row.delay_minutes is None
    assert row.delay_kind == "none"
    assert row.flight_rules == "I"
    assert row.planned_altitude == "FL350"
    assert row.planned_route == "DCT TEST"
    assert row.altitude_ft == 10000
    assert row.ground_speed_kt == 233
    assert row.squawk == "2201"


def test_fids_api_rows_expose_structured_operating_identity() -> None:
    scheduled = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc).isoformat()
    flight = normalize_flights(
        [
            {
                "callsign": "UAE2426",
                "direction": "DEP",
                "status": "scheduled",
                "scheduled": scheduled,
                "airline_iata": "EK",
                "airline_name": "Emirates",
                "flight_number": "EK2426",
                "codeshares": ["FZ315"],
                "destination_iata": "KHI",
            }
        ],
        airport_iata="DXB",
        airport_icao="OMDB",
        source_name="test",
    )[0]

    rows = ui_api._fids_rows_from_flights(
        cfg=AppConfig(airport_iata="DXB", airport_icao="OMDB", timezone="UTC"),
        flights=[flight],
        view="departures",
        limit=10,
        last_refreshed=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
    )

    payload = rows[0].model_dump()
    assert payload["flight_display"] == "FZ 315"
    assert payload["flight_number"] == "FZ315"
    assert payload["airline_iata"] == "FZ"
    assert payload["sold_as"] == ["EK2426"]
    assert payload["marketing_flight_number"] == "EK2426"
    assert payload["identity_source"] == "airport_codeshare_hint"


def test_fids_api_rows_return_virtual_pilot_fields_without_passenger_metadata() -> None:
    from localflight.core.models import AirlineRef

    now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    flight = Flight(
        direction=FlightDirection.DEPARTURE,
        airport=AirportRef(iata="ZRH", icao="LSZH"),
        callsign="DLH42",
        airline=AirlineRef(name="Lufthansa", iata="LH", icao="DLH"),
        flight_number="LH42",
        codeshares=("UA9042",),
        sold_as=("LH42",),
        marketing_flight_number="LH42",
        destination=AirportRef(icao="EDDF", name="Frankfurt"),
        aircraft_type="A320",
        gate="B4",
        terminal="2",
        times=FlightTime(scheduled=now),
        delay_minutes=22,
        flight_rules="I",
        planned_route="DCT TEST",
        planned_altitude="FL330",
        assigned_transponder="2202",
        position=FlightPosition(lat=47.3, lon=8.4, altitude_baro=3048, speed_ms=120),
        source="vatsim",
    )

    rows = ui_api._fids_rows_from_flights(
        cfg=AppConfig(airport_iata="ZRH", airport_icao="LSZH", timezone="UTC", source="virtual"),
        flights=[flight],
        view="departures",
        limit=10,
        last_refreshed=now,
    )

    payload = rows[0].model_dump()
    assert payload["detail_mode"] == "virtual"
    assert payload["flight_display"] == "DLH42"
    assert payload["airline_display"] == ""
    assert payload["airline_iata"] == ""
    assert payload["airline_icao"] == ""
    assert payload["codeshare_display"] == ""
    assert payload["codeshares"] == []
    assert payload["sold_as"] == []
    assert payload["marketing_flight_number"] == ""
    assert payload["gate"] == "-"
    assert payload["gate_display"] == ""
    assert payload["delay_minutes"] is None
    assert payload["flight_rules"] == "I"
    assert payload["planned_altitude"] == "FL330"
    assert payload["planned_route"] == "DCT TEST"
    assert payload["altitude_ft"] == 10000
    assert payload["ground_speed_kt"] == 233
    assert payload["squawk"] == "2202"


def test_matrix_payload_preserves_operating_identity_from_fids_row() -> None:
    scheduled = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc).isoformat()
    flight = normalize_flights(
        [
            {
                "callsign": "FDB2MY",
                "direction": "DEP",
                "status": "scheduled",
                "scheduled": scheduled,
                "airline_iata": "EK",
                "airline_name": "Emirates",
                "flight_number": "EK2131",
                "destination_iata": "KHI",
            }
        ],
        airport_iata="DXB",
        airport_icao="OMDB",
        source_name="test",
    )[0]
    row = flight_to_fids_row(flight, view="departures", display_tz=ZoneInfo("UTC"))

    payload = ui_api._matrix_row_payload(row, preset="real_fids", show_gate_info=True)

    assert payload["flight_display"] == "FZ 2MY"
    assert payload["flight_number"] == "FZ2MY"
    assert payload["airline_iata"] == "FZ"
    assert payload["sold_as"] == ["EK2131"]
    assert payload["codeshare_display"] == "Sold as EK 2131"
    assert payload["marketing_flight_number"] == "EK2131"
    assert payload["operating_callsign"] == "FDB2MY"
    assert payload["identity_source"] == "callsign"
    assert payload["matrix_flight_label"] == "FZ 2MY"


def test_matrix_payload_exposes_stable_display_contract_for_compact_boards() -> None:
    payload = ui_api._matrix_row_payload(
        {
            "id": "ams-arr-ua841",
            "display_time": "16:31 (+8)",
            "time_primary": "+8",
            "flight_display": "UA 841",
            "flight_number": "UA841",
            "callsign": "UAL841",
            "codeshares": ["LH 9876", "AC 1234"],
            "route_display": "Paris (CDG)",
            "status_display": "Arrived",
            "gate": "F4",
            "aircraft_type": "B738",
        },
        preset="real_fids",
        show_gate_info=True,
    )

    assert payload["matrix_time_label"] == "16:31"
    assert payload["matrix_flight_label"] == "UA 841"
    assert payload["matrix_route_label"] == "PARIS CDG"
    assert payload["matrix_status_label"] == "ARRIVED +8"
    assert payload["matrix_gate_label"] == "F4"
    assert payload["matrix_aircraft_label"] == "B738"
    assert payload["codeshares"] == ["LH 9876", "AC 1234"]


def test_matrix_payload_uses_callsign_only_when_no_flight_number_exists() -> None:
    payload = ui_api._matrix_row_payload(
        {
            "display_time": "09:05",
            "callsign": "BGA4726A",
            "route_display": "Toulouse (TLS)",
            "status_display": "scheduled",
        },
        preset="real_fids",
        show_gate_info=True,
    )

    assert payload["matrix_flight_label"] == "BGA4726A"
    assert payload["matrix_time_label"] == "09:05"


def test_identity_aware_dedupe_collapses_marketed_rows_for_same_operating_flight() -> None:
    scheduled = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc).isoformat()
    records = [
        {
            "callsign": "UAE2426",
            "direction": "DEP",
            "status": "scheduled",
            "scheduled": scheduled,
            "airline_iata": "EK",
            "airline_name": "Emirates",
            "flight_number": "EK2426",
            "codeshares": ["FZ315"],
            "destination_iata": "KHI",
        },
        {
            "callsign": "UAL6506",
            "direction": "DEP",
            "status": "scheduled",
            "scheduled": scheduled,
            "airline_iata": "UA",
            "airline_name": "United Airlines",
            "flight_number": "UA6506",
            "codeshares": ["FZ315", "EK2426"],
            "destination_iata": "KHI",
        },
    ]

    flights = normalize_flights(records, airport_iata="DXB", airport_icao="OMDB", source_name="test")
    deduped = dedupe_codeshares(flights)

    assert len(deduped) == 1
    primary = deduped[0]
    assert primary.airline.iata == "FZ"
    assert primary.flight_number == "FZ315"
    assert set(primary.sold_as) >= {"EK 2426", "UA 6506"}
    assert set(primary.codeshares) >= {"EK 2426", "UA 6506"}


def test_identity_aware_dedupe_prefers_explicit_operating_provider_row() -> None:
    scheduled = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc).isoformat()
    records = [
        {
            "callsign": "FDB315",
            "direction": "DEP",
            "status": "scheduled",
            "scheduled": scheduled,
            "airline_iata": "FZ",
            "airline_name": "flydubai",
            "flight_number": "FZ315",
            "codeshares": ["EK2426"],
            "destination_iata": "KHI",
            "gate": "A5",
        },
        {
            "callsign": "UAE2426",
            "direction": "DEP",
            "status": "scheduled",
            "scheduled": scheduled,
            "airline_iata": "EK",
            "airline_name": "Emirates",
            "flight_number": "EK2426",
            "codeshares": ["FZ315"],
            "destination_iata": "KHI",
            "gate": "B9",
        },
    ]

    flights = normalize_flights(records, airport_iata="DXB", airport_icao="OMDB", source_name="test")
    deduped = dedupe_codeshares(flights)

    assert len(deduped) == 1
    primary = deduped[0]
    assert primary.callsign == "FDB315"
    assert primary.flight_number == "FZ315"
    assert primary.gate == "A5"
    assert "EK 2426" in primary.sold_as


def test_identity_aware_dedupe_keeps_unlinked_same_route_and_time_flights_separate() -> None:
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

    flights = normalize_flights(records, airport_iata="ZRH", airport_icao="LSZH", source_name="test")
    deduped = dedupe_codeshares(flights, preferred_airline_iata=["LX"])

    assert len(deduped) == 2
    assert {flight.flight_number for flight in deduped} == {"LX100", "UA100"}


def test_fids_delay_visual_thresholds_and_early_arrivals() -> None:
    tz = ZoneInfo("Europe/Zurich")
    airport = AirportRef(iata="ZRH", icao="LSZH")
    flights = [
        Flight(
            direction=FlightDirection.ARRIVAL,
            airport=airport,
            callsign="WARN15",
            origin=AirportRef(iata="FRA", icao="EDDF"),
            times=FlightTime(scheduled=datetime(2026, 5, 1, 12, 0, tzinfo=tz)),
            delay_minutes=15,
            source="test",
        ),
        Flight(
            direction=FlightDirection.ARRIVAL,
            airport=airport,
            callsign="BAD16",
            origin=AirportRef(iata="LHR", icao="EGLL"),
            times=FlightTime(scheduled=datetime(2026, 5, 1, 12, 5, tzinfo=tz)),
            delay_minutes=16,
            source="test",
        ),
        Flight(
            direction=FlightDirection.ARRIVAL,
            airport=airport,
            callsign="EARLY8",
            origin=AirportRef(iata="AMS", icao="EHAM"),
            times=FlightTime(scheduled=datetime(2026, 5, 1, 12, 10, tzinfo=tz)),
            delay_minutes=-8,
            position=FlightPosition(on_ground=True),
            source="test",
        ),
    ]

    ctx = build_fids_context(
        cfg=AppConfig(airport_iata="ZRH", airport_icao="LSZH", timezone="Europe/Zurich"),
        view="arrivals",
        refresh_seconds=60,
        flights=flights,
        reference_now=datetime(2026, 5, 1, 11, 55, tzinfo=tz),
    )
    by_callsign = {row.callsign: row for row in ctx["rows"]}

    assert by_callsign["WARN15"].status_class == "delayed-warn"
    assert by_callsign["WARN15"].delay_class == "warn"
    assert by_callsign["WARN15"].delay_kind == "warn"
    assert by_callsign["WARN15"].tone == "amber"
    assert by_callsign["WARN15"].time_delta_label == "+15"
    assert by_callsign["BAD16"].status_class == "delayed-bad"
    assert by_callsign["BAD16"].delay_class == "bad"
    assert by_callsign["BAD16"].status_kind == "delayed_bad"
    assert by_callsign["BAD16"].tone == "red"
    assert by_callsign["EARLY8"].status_class == "early"
    assert by_callsign["EARLY8"].delay_class == "early"
    assert by_callsign["EARLY8"].delay_kind == "early"
    assert by_callsign["EARLY8"].tone == "green"


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


def test_api_config_coerces_community_relay_refresh_to_hourly(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage_config, "config_path", lambda: tmp_path / "config.json")
    storage_config.save_config(AppConfig(source="real", refresh_seconds=3600))
    monkeypatch.setattr(aviationstack_client, "_has_enabled_byok_key", lambda: False)
    monkeypatch.setattr(aviationstack_client, "_has_enabled_aerodatabox_byok_key", lambda: False)
    monkeypatch.setattr(aviationstack_client, "_has_activation_token", lambda: False)
    monkeypatch.setattr(aviationstack_client, "_has_community_api_key", lambda: False)

    result = ui_api.api_patch_config(
        ui_api.ConfigPatch(refresh_seconds=900),
        BackgroundTasks(),
    )

    assert result["refresh_seconds"] == 3600
    assert storage_config.load_config().refresh_seconds == 3600


def test_api_config_keeps_byok_and_virtual_fast_refresh(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage_config, "config_path", lambda: tmp_path / "config.json")
    storage_config.save_config(AppConfig(source="real", refresh_seconds=3600))
    monkeypatch.setattr(aviationstack_client, "_has_enabled_byok_key", lambda: True)
    monkeypatch.setattr(aviationstack_client, "_has_enabled_aerodatabox_byok_key", lambda: False)
    monkeypatch.setattr(aviationstack_client, "_has_activation_token", lambda: False)
    monkeypatch.setattr(aviationstack_client, "_has_community_api_key", lambda: False)

    byok = ui_api.api_patch_config(ui_api.ConfigPatch(refresh_seconds=900), BackgroundTasks())
    virtual = ui_api.api_patch_config(
        ui_api.ConfigPatch(source="virtual", refresh_seconds=900),
        BackgroundTasks(),
    )

    assert byok["refresh_seconds"] == 900
    assert virtual["source"] == "virtual"
    assert virtual["refresh_seconds"] == 900


def test_admin_budget_exposes_schedule_policy(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage_config, "config_path", lambda: tmp_path / "config.json")
    storage_config.save_config(AppConfig(source="real", refresh_seconds=3600))
    monkeypatch.setattr(aviationstack_client, "_has_enabled_byok_key", lambda: False)
    monkeypatch.setattr(aviationstack_client, "_has_enabled_aerodatabox_byok_key", lambda: False)
    monkeypatch.setattr(aviationstack_client, "_has_activation_token", lambda: False)
    monkeypatch.setattr(aviationstack_client, "_has_community_api_key", lambda: False)
    monkeypatch.setattr(
        aviationstack_client,
        "_fetch_relay_status",
        lambda timeout_s=8, require_token=False: {
            "ok": True,
            "shared_schedule_budget": {
                "provider": "aviationstack",
                "provider_label": "AviationStack shared schedule",
                "unit_label": "calls",
                "used": 8,
                "limit": 10000,
                "remaining": 9992,
                "reset_at": "2026-06-01T00:00:00+00:00",
                "scope_label": "Shared by all community relay real-data users",
            },
            "schedule_access_budget": {"used": 2, "limit": 50, "remaining": 48},
        },
    )

    payload = ui_api.api_admin_budget()

    assert payload["schedule_policy"]["community_shared"] is True
    assert payload["schedule_policy"]["min_refresh_seconds"] == 3600
    assert payload["schedule_policy"]["allowed_refresh_seconds"][0] == 3600
    assert payload["aviationstack"]["schedule_policy"]["community_shared"] is True
    assert payload["shared_schedule_budget"]["remaining"] == 9992
    assert payload["schedule_access_budget"]["remaining"] == 48
    assert payload["client_polling_policy"]["mode"] == "event_first"
    assert payload["client_polling_policy"]["fids_fallback_seconds"] == 300
    assert payload["client_polling_policy"]["mobile_min_fallback_seconds"] == 300


def test_community_relay_cooldown_suppresses_repeated_schedule_requests(monkeypatch) -> None:
    usage: dict[str, object] = {}
    calls: list[str] = []

    monkeypatch.setattr(aviationstack_client, "_load_usage", lambda: dict(usage))
    monkeypatch.setattr(aviationstack_client, "_save_usage", lambda data: usage.clear() or usage.update(data))
    monkeypatch.setattr(aviationstack_client, "_increment_community_budget", lambda limit, n_calls=1: None)
    monkeypatch.setattr(aviationstack_client, "_get_activation_token", lambda: "")
    monkeypatch.setattr(aviationstack_client, "_get_relay_limit", lambda: 50)
    monkeypatch.setattr(storage_install, "get_install_id", lambda: "00000000-0000-0000-0000-000000000555")

    def fake_get(url, *, params, headers, timeout):
        calls.append(url)
        return types.SimpleNamespace(
            status_code=429,
            headers={"Retry-After": "120"},
            json=lambda: {"error": {"code": "quota_exceeded", "info": "slow down"}},
        )

    monkeypatch.setattr(aviationstack_client.requests, "get", fake_get)

    with pytest.raises(aviationstack_client.AviationstackBudgetExceeded) as first:
        aviationstack_client.fetch_relay_schedule_records(
            airport_iata="ZRH",
            timezone_name="Europe/Zurich",
            return_meta=True,
        )
    with pytest.raises(aviationstack_client.AviationstackRelayCooldown) as second:
        aviationstack_client.fetch_relay_schedule_records(
            airport_iata="ZRH",
            timezone_name="Europe/Zurich",
            return_meta=True,
        )

    assert first.value.retry_after_s == 120
    assert second.value.retry_after_s is not None and second.value.retry_after_s > 0
    assert len(calls) == 1
    assert "relay_cooldown" in usage


def test_scheduler_restart_coalesces_repeated_background_requests(monkeypatch) -> None:
    calls: list[str] = []

    class _Thread:
        name = "scheduler-test"

        def is_alive(self) -> bool:
            return True

    monkeypatch.setattr(scheduler_control, "_thread", None)
    monkeypatch.setattr(scheduler_control, "_stop_event", None)
    monkeypatch.setattr(scheduler_control, "_last_restart_request_monotonic", None)

    def _start() -> _Thread:
        calls.append("start")
        return _Thread()

    monkeypatch.setattr(scheduler_control, "start_scheduler_thread", _start)

    first = scheduler_control.restart_scheduler(coalesce_seconds=60)
    second = scheduler_control.restart_scheduler(coalesce_seconds=60)

    assert first["ok"] is True
    assert second["ok"] is False
    assert second["status"] == "rate_limited"
    assert second["retry_after_s"] > 0
    assert calls == ["start"]


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
        "_fetch_relay_status",
        lambda timeout_s=8, require_token=False: {
            "ok": True,
            "limits": {"schedule": 10000},
            "providers": {"aviationstack": True, "adsbexchange": True},
            "token_prefix": "lfm_test",
            "shared_schedule_budget": {
                "provider": "aviationstack",
                "provider_label": "AviationStack shared schedule",
                "unit_label": "calls",
                "used": 37,
                "limit": 10000,
                "remaining": 9963,
                "reset_at": "2026-05-01T00:00:00+00:00",
                "scope_label": "Shared by all community relay real-data users",
            },
            "schedule_access_budget": {"used": 3, "limit": 10000, "remaining": 9997},
        },
    )

    stats = aviationstack_client.get_usage_stats("real")

    assert stats["active_mode"] == "managed"
    assert stats["calls_this_month"] == 3
    assert stats["monthly_limit"] == 10000
    assert stats["managed"]["token_prefix"] == "lfm_test"
    assert stats["managed"]["providers"]["aviationstack"] is True
    assert stats["shared_schedule_budget"]["remaining"] == 9963
    assert stats["schedule_access_budget"]["used"] == 3


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


def test_aviationstack_byok_daily_cap_uses_atomic_sqlite_counter(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage_config, "config_path", lambda: tmp_path / "config.json")
    monkeypatch.setenv("LOCALFLIGHT_AVIATIONSTACK_DAILY_LIMIT", "1")

    with pytest.raises(aviationstack_client.AviationstackBudgetExceeded):
        aviationstack_client._increment_budget("aviationstack", 100, n_calls=2)

    from localflight.sources.web import local_usage

    assert local_usage.get_counter("aviationstack") == 0


def test_aerodatabox_byok_daily_cap_uses_atomic_sqlite_counter(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage_config, "config_path", lambda: tmp_path / "config.json")
    monkeypatch.setenv("LOCALFLIGHT_AERODATABOX_MONTHLY_UNITS_LIMIT", "100")
    monkeypatch.setenv("LOCALFLIGHT_AERODATABOX_DAILY_UNITS_LIMIT", "1")

    with pytest.raises(aerodatabox_client.AeroDataBoxBudgetExceeded):
        aerodatabox_client._increment_units(2)

    from localflight.sources.web import local_usage

    assert local_usage.get_counter("aerodatabox_units") == 0
    assert local_usage.get_counter("aerodatabox_requests") == 0


def test_aerodatabox_byok_uses_apimarket_gateway_by_default(monkeypatch) -> None:
    monkeypatch.setenv("AERODATABOX_API_KEY", "adb-test")
    monkeypatch.setenv("LOCALFLIGHT_AERODATABOX_ENABLED", "1")
    monkeypatch.delenv("LOCALFLIGHT_AERODATABOX_MARKETPLACE", raising=False)
    monkeypatch.delenv("AERODATABOX_MARKETPLACE", raising=False)
    monkeypatch.setattr(aerodatabox_client, "_increment_units", lambda units: None)
    captured: dict[str, object] = {}

    def fake_get(url, *, params, headers, timeout):
        captured.update({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return types.SimpleNamespace(status_code=200, json=lambda: {"departures": [], "arrivals": []})

    monkeypatch.setattr(aerodatabox_client.requests, "get", fake_get)

    payload = aerodatabox_client._request_payload(
        airport_iata="ZRH",
        display_grace_minutes=30,
        display_horizon_hours=12,
        timeout_s=7,
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


def test_aerodatabox_aircraft_model_keeps_fids_code_short() -> None:
    scheduled = datetime(2026, 5, 12, 10, 0, tzinfo=timezone.utc)
    payload = {
        "departures": [
            {
                "number": "100",
                "callSign": "SWR100",
                "status": "Scheduled",
                "departure": {
                    "airport": {"iata": "ZRH", "icao": "LSZH"},
                    "scheduledTime": {"utc": scheduled.isoformat()},
                },
                "arrival": {
                    "airport": {"iata": "JFK", "icao": "KJFK"},
                    "scheduledTime": {"utc": scheduled.isoformat()},
                },
                "airline": {"name": "Swiss", "iata": "LX", "icao": "SWR"},
                "aircraft": {"icaoCode": "A359", "model": "Airbus A350-900", "reg": "HB-JHA"},
            }
        ],
        "arrivals": [],
    }

    records = aerodatabox_to_raw_records(payload, airport_iata="ZRH", airport_icao="LSZH")
    flights = normalize_flights(records, airport_iata="ZRH", airport_icao="LSZH", source_name="aerodatabox")
    row = flight_to_fids_row(flights[0], view="departures", display_tz=ZoneInfo("Europe/Zurich"))

    assert records[0]["aircraft_type"] == "A359"
    assert records[0]["aircraft_type_full"] == "Airbus A350-900"
    assert flights[0].aircraft_type == "A359"
    assert flights[0].aircraft_type_full == "Airbus A350-900"
    assert row.aircraft_type == "A359"


def test_aerodatabox_verbose_aircraft_model_is_mapped_for_board_display() -> None:
    scheduled = datetime(2026, 5, 12, 10, 0, tzinfo=timezone.utc)
    payload = {
        "departures": [
            {
                "number": "200",
                "callSign": "SWR200",
                "status": "Scheduled",
                "departure": {
                    "airport": {"iata": "ZRH", "icao": "LSZH"},
                    "scheduledTime": {"utc": scheduled.isoformat()},
                },
                "arrival": {
                    "airport": {"iata": "SIN", "icao": "WSSS"},
                    "scheduledTime": {"utc": scheduled.isoformat()},
                },
                "airline": {"name": "Swiss", "iata": "LX", "icao": "SWR"},
                "aircraft": {"model": "Airbus A350-941"},
            }
        ],
        "arrivals": [],
    }

    records = aerodatabox_to_raw_records(payload, airport_iata="ZRH", airport_icao="LSZH")
    flights = normalize_flights(records, airport_iata="ZRH", airport_icao="LSZH", source_name="aerodatabox")
    row = flight_to_fids_row(flights[0], view="departures", display_tz=ZoneInfo("Europe/Zurich"))

    assert records[0]["aircraft_type"] == "A359"
    assert records[0]["aircraft_type_full"] == "Airbus A350-941"
    assert flights[0].aircraft_type == "A359"
    assert flights[0].aircraft_type_full == "Airbus A350-941"
    assert row.aircraft_type == "A359"


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
    assert result["blips"][0]["detail_mode"] == "virtual"
    assert result["blips"][0]["display_title"] == "SWR100"
    assert result["blips"][0]["route_display"] == "LSZH -> EGLL"
    assert result["blips"][0]["altitude_ft"] == 12000
    assert result["blips"][0]["speed_kt"] == 250
    assert result["blips"][0]["motion_display"]
    assert result["blips"][0]["radar_phase"] == "departure"
    assert result["blips"][0]["radar_status_label"] == "Departing"
    assert "name" not in result["blips"][0]
    assert "cid" not in result["blips"][0]


def test_api_radar_snapshot_blips_preserve_operating_identity(monkeypatch) -> None:
    scheduled = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc).isoformat()
    flight = normalize_flights(
        [
            {
                "callsign": "UAE2426",
                "direction": "DEP",
                "status": "scheduled",
                "scheduled": scheduled,
                "airline_iata": "EK",
                "airline_name": "Emirates",
                "flight_number": "EK2426",
                "codeshares": ["FZ315"],
                "destination_iata": "KHI",
            }
        ],
        airport_iata="DXB",
        airport_icao="OMDB",
        source_name="test",
    )[0]
    flight = replace(
        flight,
        position=FlightPosition(
            lat=25.2528,
            lon=55.3644,
            altitude_baro=0,
            heading=270,
            speed_ms=4,
            on_ground=True,
            icao24="8960ab",
        ),
    )

    monkeypatch.setattr(
        ui_api,
        "load_config",
        lambda: AppConfig(airport_iata="DXB", airport_icao="OMDB", source="real"),
    )
    monkeypatch.setattr(
        ui_api,
        "lookup_airport",
        lambda **kwargs: types.SimpleNamespace(lat=25.2532, lon=55.3657, icao="OMDB"),
    )
    monkeypatch.setattr(ui_api, "_load_latest_flights", lambda airport_iata: ([flight], datetime.now(timezone.utc)))
    monkeypatch.setattr(adsbexchange_client, "is_available", lambda: False)

    result = ui_api.api_radar(5.0)
    blip = result["blips"][0]

    assert result["source"] == "snapshot_positions"
    assert blip["flight_number"] == "FZ315"
    assert blip["airline_iata"] == "FZ"
    assert blip["sold_as"] == ["EK2426"]
    assert blip["codeshares"] == ["EK2426"]
    assert blip["marketing_flight_number"] == "EK2426"
    assert blip["identity_source"] == "airport_codeshare_hint"


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
        generated_at=(datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
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
    assert result["features"][0]["validation"]["validated_by"] == ["openstreetmap", "ourairports-center"]
    assert result["features"][0]["validation"]["heading_deg"] is not None
    assert result["meta"]["validation"]["runway_count"] == 1


def test_api_radar_surface_serves_fresh_local_cache_without_relay(monkeypatch) -> None:
    cfg = AppConfig(airport_iata="ZRH", airport_icao="LSZH", radar_surface_enabled=True)
    cached = airport_surface.build_surface_payload(
        airport_iata="ZRH",
        airport_icao="LSZH",
        center_lat=47.45,
        center_lon=8.55,
        radius_nm=5,
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

    monkeypatch.setattr(ui_api, "load_config", lambda: cfg)
    monkeypatch.setattr(
        ui_api,
        "lookup_airport",
        lambda **kwargs: types.SimpleNamespace(lat=47.45, lon=8.55, icao="LSZH"),
    )
    monkeypatch.setattr(ui_api, "_load_local_surface_cache", lambda cfg: cached)
    monkeypatch.setattr(
        ui_api._req,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("fresh local surface cache should avoid relay")),
    )

    result = ui_api.api_radar_surface(5.0)

    assert result["cache_state"] == "fresh"
    assert result["meta"]["served_via"] == "local-surface-cache"
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
    assert result["meta"]["validation"]["validated_by"] == ["localflight-estimated", "ourairports-center"]
    assert result["meta"]["validation"]["runway_count"] >= 1
    assert "Relay surface HTTP 503" in result["error"]
    assert {feature["kind"] for feature in result["features"]} >= {"boundary", "runway", "taxiway", "apron", "building"}


def test_api_radar_surface_timeout_returns_estimate_before_native_timeout(monkeypatch) -> None:
    cfg = AppConfig(airport_iata="DEN", airport_icao="KDEN", radar_surface_enabled=True)
    captured: dict[str, object] = {}

    def _timeout(*args, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        raise ui_api._req.Timeout("surface relay timed out")

    monkeypatch.setattr(ui_api, "load_config", lambda: cfg)
    monkeypatch.setattr(
        ui_api,
        "lookup_airport",
        lambda **kwargs: types.SimpleNamespace(lat=39.8617, lon=-104.6731, icao="KDEN"),
    )
    monkeypatch.setattr(ui_api, "_load_local_surface_cache", lambda cfg: None)
    monkeypatch.setattr(ui_api, "_save_local_surface_cache", lambda cfg, payload: None)
    monkeypatch.setattr(ui_api._req, "get", _timeout)

    result = ui_api.api_radar_surface(5.0)

    assert captured["timeout"] < 10
    assert result["cache_state"] == "estimated"
    assert result["provider"] == "localflight-estimated"
    assert "timed out" in result["error"]
    assert {feature["kind"] for feature in result["features"]} >= {"boundary", "runway"}


def test_api_radar_map_returns_runways_and_simplified_surface(monkeypatch) -> None:
    monkeypatch.setattr(ui_server, "_setup_complete", lambda: True)
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
    monkeypatch.setattr(
        ui_api,
        "_radar_surface_payload_for_map",
        lambda cfg, airport, radius_nm: {
            "provider": "openstreetmap",
            "cache_state": "fresh",
            "attribution": {"text": "OSM", "url": "https://www.openstreetmap.org/copyright"},
            "features": [
                {"kind": "runway", "label": "16/34", "points": [[47.47, 8.53], [47.43, 8.57]]},
                {"kind": "taxiway", "label": "A", "points": [[47.46, 8.54], [47.44, 8.56]]},
                {"kind": "terminal", "label": "Terminal", "closed": True, "points": [[47.45, 8.55], [47.451, 8.55], [47.451, 8.551], [47.45, 8.55]]},
            ],
        },
    )
    monkeypatch.setattr(
        ui_api,
        "_radar_map_context_payload_for_map",
        lambda cfg, airport, radius_nm: {
            "provider": "openstreetmap",
            "cache_state": "fresh",
            "attribution": {"text": "OSM", "url": "https://www.openstreetmap.org/copyright"},
            "features": [
                {"kind": "water", "label": "water", "closed": True, "points": [[47.44, 8.54], [47.45, 8.54], [47.45, 8.55], [47.44, 8.54]]},
                {"kind": "road", "label": "road", "points": [[47.44, 8.53], [47.46, 8.56]]},
            ],
        },
    )

    response = TestClient(app).get("/api/radar/map?radius_nm=40")
    payload = response.json()

    assert response.status_code == 200
    assert payload["schema_version"] == "radar-map-v1"
    assert payload["runways"][0]["label"] == "16/34"
    assert [feature["kind"] for feature in payload["surface_features"]] == ["terminal"]
    assert [feature["kind"] for feature in payload["map_features"]] == ["water"]
    assert payload["map_features"][0]["label"] == ""
    assert payload["attribution"][0]["text"] == "OSM"


def test_api_radar_map_reuses_internal_surface_cache(monkeypatch) -> None:
    cfg = AppConfig(airport_iata="ZRH", airport_icao="LSZH", source="real")
    airport = types.SimpleNamespace(lat=47.45, lon=8.55, icao="LSZH")
    calls = {"surface": 0}

    ui_api._radar_map_cache.clear()
    monkeypatch.setattr(ui_api, "load_config", lambda: cfg)
    monkeypatch.setattr(ui_api, "lookup_airport", lambda **kwargs: airport)

    def surface_payload(_cfg, _airport, *, radius_nm):
        calls["surface"] += 1
        return {
            "provider": "openstreetmap",
            "cache_state": "fresh",
            "attribution": {"text": "OSM", "url": "https://www.openstreetmap.org/copyright"},
            "features": [{"kind": "runway", "label": "16/34", "points": [[47.47, 8.53], [47.43, 8.57]]}],
        }

    monkeypatch.setattr(ui_api, "_radar_surface_payload_for_map", surface_payload)
    monkeypatch.setattr(
        ui_api,
        "_radar_map_context_payload_for_map",
        lambda cfg, airport, radius_nm: {"provider": "openstreetmap", "cache_state": "fresh", "features": []},
    )

    first = ui_api.api_radar_map(radius_nm=20.0, terrain=False)
    second = ui_api.api_radar_map(radius_nm=20.0, terrain=False)

    assert first["runways"][0]["label"] == "16/34"
    assert second["runways"][0]["label"] == "16/34"
    assert calls["surface"] == 1


def test_radar_map_context_miss_is_cached_briefly(tmp_path: Path, monkeypatch) -> None:
    cfg = AppConfig(airport_iata="ZRH", airport_icao="LSZH", source="real")
    airport = types.SimpleNamespace(lat=47.45, lon=8.55, icao="LSZH")
    calls = {"refresh": 0}

    monkeypatch.setattr(ui_api, "_radar_map_context_cache_path", lambda _cfg: tmp_path / "LSZH.json")
    monkeypatch.setattr(ui_api, "_schedule_map_context_refresh", lambda *_args, **_kwargs: calls.__setitem__("refresh", calls["refresh"] + 1))

    first = ui_api._radar_map_context_payload_for_map(cfg, airport, radius_nm=5.0)
    second = ui_api._radar_map_context_payload_for_map(cfg, airport, radius_nm=5.0)

    assert first["cache_state"] == "miss"
    assert second["cache_state"] == "miss"
    assert calls["refresh"] == 1


def test_radar_map_payload_does_not_memory_cache_loading_map_context(monkeypatch) -> None:
    cfg = AppConfig(airport_iata="ZRH", airport_icao="LSZH", source="real")
    airport = types.SimpleNamespace(lat=47.45, lon=8.55, icao="LSZH")
    calls = {"map": 0}

    ui_api._radar_map_cache.clear()
    monkeypatch.setattr(
        ui_api,
        "_radar_surface_payload_for_map",
        lambda cfg, airport, radius_nm: {"provider": "openstreetmap", "cache_state": "fresh", "features": []},
    )

    def map_context(_cfg, _airport, *, radius_nm):
        calls["map"] += 1
        return {"provider": "openstreetmap", "cache_state": "miss", "features": []}

    monkeypatch.setattr(ui_api, "_radar_map_context_payload_for_map", map_context)

    first = ui_api._radar_map_payload_for_request(cfg, airport, radius_nm=5.0)
    second = ui_api._radar_map_payload_for_request(cfg, airport, radius_nm=5.0)

    assert first["map_features"] == []
    assert second["map_features"] == []
    assert calls["map"] == 2


def test_radar_map_context_returns_stale_cache_while_refreshing(tmp_path: Path, monkeypatch) -> None:
    cfg = AppConfig(airport_iata="ZRH", airport_icao="LSZH", source="real")
    airport = types.SimpleNamespace(lat=47.45, lon=8.55, icao="LSZH")
    old = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
    path = tmp_path / "LSZH.json"
    path.write_text(
        json.dumps(
            {
                "generated_at": old,
                "cache_state": "fresh",
                "provider": "openstreetmap",
                "schema_version": "osm-map-context-v1",
                "attribution": {"text": "OSM", "url": ""},
                "center": {"lat": 47.45, "lon": 8.55, "airport_iata": "ZRH", "airport_icao": "LSZH"},
                "radius_nm": 5,
                "features": [{"kind": "water", "points": [[47.4, 8.5], [47.5, 8.6]]}],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(ui_api, "_radar_map_context_cache_path", lambda _cfg: path)
    monkeypatch.setattr(ui_api, "_schedule_map_context_refresh", lambda *_args, **_kwargs: None)

    payload = ui_api._radar_map_context_payload_for_map(cfg, airport, radius_nm=5.0)

    assert payload["cache_state"] == "stale"
    assert payload["features"][0]["kind"] == "water"
    assert "refreshing" in payload["error"]


def test_radar_map_context_refresh_failure_preserves_existing_cache(tmp_path: Path, monkeypatch) -> None:
    cfg = AppConfig(airport_iata="ZRH", airport_icao="LSZH", source="real")
    airport = types.SimpleNamespace(lat=47.45, lon=8.55, icao="LSZH")
    path = tmp_path / "LSZH.json"
    existing = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cache_state": "fresh",
        "provider": "openstreetmap",
        "schema_version": "osm-map-context-v1",
        "attribution": {"text": "OSM", "url": ""},
        "center": {"lat": 47.45, "lon": 8.55, "airport_iata": "ZRH", "airport_icao": "LSZH"},
        "radius_nm": 5,
        "features": [{"kind": "road", "points": [[47.4, 8.5], [47.5, 8.6]]}],
    }
    path.write_text(json.dumps(existing), encoding="utf-8")

    class ImmediateExecutor:
        def submit(self, fn):
            fn()

    monkeypatch.setattr(ui_api, "_radar_map_context_cache_path", lambda _cfg: path)
    monkeypatch.setattr(ui_api, "_map_context_executor", ImmediateExecutor())
    monkeypatch.setattr(ui_api, "_fetch_and_save_map_context", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")))

    ui_api._schedule_map_context_refresh(cfg, airport, radius_nm=5.0)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["cache_state"] == "fresh"
    assert saved["features"][0]["kind"] == "road"


def test_radar_terrain_miss_is_cached_and_refreshed_in_background(tmp_path: Path, monkeypatch) -> None:
    cfg = AppConfig(airport_iata="ZRH", airport_icao="LSZH", source="real")
    airport = types.SimpleNamespace(lat=47.45, lon=8.55, icao="LSZH")
    calls = {"refresh": 0}

    monkeypatch.setattr(ui_api, "_radar_terrain_cache_path", lambda _cfg: tmp_path / "LSZH.json")
    monkeypatch.setattr(ui_api, "_schedule_terrain_refresh", lambda *_args, **_kwargs: calls.__setitem__("refresh", calls["refresh"] + 1))

    first = ui_api._radar_terrain_payload_for_map(cfg, airport, radius_nm=5.0)
    second = ui_api._radar_terrain_payload_for_map(cfg, airport, radius_nm=5.0)

    assert first["cache_state"] == "miss"
    assert second["cache_state"] == "miss"
    assert first["features"] == []
    assert calls["refresh"] == 1


def test_radar_map_requests_terrain_only_when_enabled(monkeypatch) -> None:
    cfg = AppConfig(airport_iata="ZRH", airport_icao="LSZH", source="real")
    airport = types.SimpleNamespace(lat=47.45, lon=8.55, icao="LSZH")
    calls = {"terrain": 0}

    ui_api._radar_map_cache.clear()
    monkeypatch.setattr(ui_api, "load_config", lambda: cfg)
    monkeypatch.setattr(ui_api, "lookup_airport", lambda **kwargs: airport)
    monkeypatch.setattr(ui_api, "_radar_surface_payload_for_map", lambda cfg, airport, radius_nm: {"provider": "openstreetmap", "cache_state": "fresh", "features": []})
    monkeypatch.setattr(ui_api, "_radar_map_context_payload_for_map", lambda cfg, airport, radius_nm: {"provider": "openstreetmap", "cache_state": "fresh", "features": []})

    def _terrain(_cfg, _airport, *, radius_nm):
        calls["terrain"] += 1
        return {
            "provider": "aws-terrain-tiles",
            "cache_state": "fresh",
            "features": [{"kind": "relief", "points": [[47.44, 8.54], [47.45, 8.55]]}],
        }

    monkeypatch.setattr(ui_api, "_radar_terrain_payload_for_map", _terrain)

    off = ui_api._radar_map_payload_for_request(cfg, airport, radius_nm=5.0, terrain=False)
    on = ui_api._radar_map_payload_for_request(cfg, airport, radius_nm=5.0, terrain=True)

    assert calls["terrain"] == 1
    assert off["terrain"]["features"] == []
    assert on["terrain"]["features"][0]["kind"] == "relief"


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
    assert "trackHistory" in response.text
    assert "shouldDrawLabel" in response.text
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
            "app_version": "0.2.5",
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


def test_multi_companion_checkins_remain_distinct_and_update_by_id(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ui_server, "_setup_complete", lambda: True)
    monkeypatch.setattr(ui_api, "_companion_presence_path", lambda: tmp_path / "companion_clients.json")

    client = TestClient(app)
    first = {
        "companion_id": "lfc_test_mobile_phone",
        "client_name": "Local Flight Companion",
        "app_version": "0.2.6",
        "mobile_os": "iOS 18.5 (phone)",
        "device_type": "phone",
    }
    second = {
        "companion_id": "lfc_test_mobile_ipad",
        "client_name": "Local Flight Companion",
        "app_version": "0.2.6",
        "mobile_os": "iPadOS 18.5 (tablet)",
        "device_type": "tablet",
    }

    assert client.post("/api/admin/companion/checkin", json=first).status_code == 200
    assert client.post("/api/admin/companion/checkin", json=second).status_code == 200
    assert client.post(
        "/api/admin/companion/checkin",
        json={**first, "app_version": "0.2.7", "mobile_os": "iOS 19.0 (phone)"},
    ).status_code == 200

    payload = client.get("/api/admin/connections").json()
    assert payload["companion_count"] == 2
    by_id = {item["companion_id"]: item for item in payload["companions"]}
    assert set(by_id) == {"lfc_test_mobile_phone", "lfc_test_mobile_ipad"}
    assert by_id["lfc_test_mobile_phone"]["app_version"] == "0.2.7"
    assert by_id["lfc_test_mobile_phone"]["mobile_os"] == "iOS 19.0 (phone)"
    assert by_id["lfc_test_mobile_ipad"]["device_type"] == "tablet"


def test_companion_reset_clears_remembered_mobile_checkins(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ui_server, "_setup_complete", lambda: True)
    monkeypatch.setattr(ui_api, "_companion_presence_path", lambda: tmp_path / "companion_clients.json")

    client = TestClient(app)
    assert client.post(
        "/api/admin/companion/checkin",
        json={
            "companion_id": "lfc_test_reset_phone",
            "client_name": "Local Flight Companion",
            "app_version": "0.2.7",
            "mobile_os": "iOS 19.0 (phone)",
            "device_type": "phone",
        },
    ).status_code == 200
    assert client.get("/api/admin/connections").json()["companion_count"] == 1

    reset = client.delete("/api/admin/companion")

    assert reset.status_code == 200
    assert reset.json()["ok"] is True
    assert reset.json()["removed"] == 1
    assert client.get("/api/admin/connections").json()["companion_count"] == 0


def test_companion_pairing_gateway_uses_reusable_deep_link(monkeypatch) -> None:
    monkeypatch.setattr("localflight.companion_pairing._local_ipv4_addresses", lambda: ["192.168.1.77"])

    payload = pairing_gateway_payload(
        base_url="http://127.0.0.1:8000",
        server_fingerprint="server-test-fp",
    )

    assert payload["preferred_url"] == "http://192.168.1.77:8000"
    assert payload["manual_urls"][:2] == ["http://192.168.1.77:8000", "http://localflight.local:8000"]
    assert payload["server_fingerprint"] == "server-test-fp"
    assert payload["deep_link"] == build_pairing_deep_link(
        "http://192.168.1.77:8000",
        source="qt",
        server_fingerprint="server-test-fp",
    )
    assert "server=http%3A%2F%2F192.168.1.77%3A8000" in str(payload["deep_link"])
    assert "server_fingerprint=server-test-fp" in str(payload["deep_link"])
    assert "00000000-0000-0000-0000" not in str(payload["deep_link"])


def test_companion_pairing_gateway_prefers_explicit_lan_base_url(monkeypatch) -> None:
    monkeypatch.setattr("localflight.companion_pairing._local_ipv4_addresses", lambda: ["192.168.1.77"])

    payload = pairing_gateway_payload(
        base_url="http://192.168.1.42:9000",
        port=8000,
        server_fingerprint="server-test-fp",
    )

    assert payload["preferred_url"] == "http://192.168.1.42:9000"
    assert payload["manual_urls"][:3] == [
        "http://192.168.1.42:9000",
        "http://192.168.1.77:8000",
        "http://localflight.local:8000",
    ]


def test_mobile_summary_rolls_up_companion_host_status(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ui_server, "_setup_complete", lambda: True)
    monkeypatch.setattr(ui_api, "_companion_presence_path", lambda: tmp_path / "companion_clients.json")

    client = TestClient(app)
    checkin = client.post(
        "/api/admin/companion/checkin",
        json={
            "companion_id": "lfc_test_mobile_002",
            "client_name": "Local Flight Companion",
            "app_version": "0.2.7",
            "mobile_os": "iOS 19.0 (phone)",
            "device_type": "phone",
        },
    )
    assert checkin.status_code == 200

    response = client.get("/api/mobile/summary")
    assert response.status_code == 200
    payload = response.json()

    assert "config" in payload
    assert "state" in payload
    assert "system" in payload
    assert "connections" in payload
    assert "updates" in payload
    assert "budget" in payload
    assert "scheduler" in payload
    assert "metar" in payload
    assert "requests" not in payload
    assert set(payload["scheduler"]).issuperset({"running"})
    assert payload["connections"]["companion_count"] == 1
    assert payload["connections"]["companions"][0]["companion_id"] == "lfc_test_mobile_002"
    assert "running" in payload["scheduler"]


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
    assert response.json()["intel"]["schema_version"] == "flight-intel-v1"
    assert detail["intel"]["schema_version"] == "flight-intel-v1"
    assert response.json()["intel"]["identity"]["callsign"] == "SWR10"
    assert response.json()["intel"]["route"]["route_display"] == "ZRH → LHR"
    assert detail["intel"]["aircraft"]["registration"] == "HB-JCA"
    assert detail["intel"]["motion"]["altitude_ft"] == 10000
    assert detail["intel"]["source_evidence"]["confidence"] == "live_position_matched"


def test_fids_detail_virtual_mode_uses_vatsim_contract_without_passenger_fields(monkeypatch, tmp_path: Path) -> None:
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
                        "callsign": "DLH42",
                        "airline": {"name": "Lufthansa", "iata": "LH", "icao": "DLH"},
                        "flight_number": "LH42",
                        "codeshares": ["UA9042"],
                        "sold_as": ["LH42"],
                        "marketing_airline_name": "Lufthansa",
                        "marketing_airline_iata": "LH",
                        "marketing_airline_icao": "DLH",
                        "marketing_flight_number": "LH42",
                        "origin": {"iata": "ZRH", "icao": "LSZH", "name": "Zurich"},
                        "destination": {"iata": None, "icao": "EDDF", "name": "Frankfurt"},
                        "aircraft_type": "A320",
                        "aircraft_registration": "D-TEST",
                        "gate": "A1",
                        "terminal": "1",
                        "stand": "101",
                        "status": "Scheduled",
                        "times": {
                            "scheduled": now.isoformat(),
                            "estimated": None,
                            "actual": None,
                        },
                        "delay_minutes": 20,
                        "flight_rules": "I",
                        "planned_route": "DCT TEST",
                        "planned_altitude": "FL350",
                        "planned_departure": now.isoformat(),
                        "planned_arrival": (now + timedelta(minutes=80)).isoformat(),
                        "planned_enroute_minutes": 80,
                        "cruise_tas": 430,
                        "alternate_icao": "EDDK",
                        "assigned_transponder": "2201",
                        "position": {
                            "lat": 47.45,
                            "lon": 8.56,
                            "altitude_baro": 3048,
                            "heading": 270,
                            "speed_ms": 120,
                            "on_ground": False,
                            "icao24": "4B1800",
                            "squawk": "7000",
                            "last_contact": now.isoformat(),
                        },
                        "source": "vatsim",
                        "enriched_by": None,
                        "updated_at": now.isoformat(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(ui_api, "load_config", lambda: AppConfig(airport_iata="ZRH", airport_icao="LSZH", source="virtual"))
    monkeypatch.setattr(ui_server, "_setup_complete", lambda: True)
    monkeypatch.setattr(ui_api, "load_latest_snapshot_path", lambda airport_iata: snapshot)
    import localflight.storage.history as history

    monkeypatch.setattr(
        history,
        "query_flight_history",
        lambda callsign, days=7: [
            {"event_time": now.isoformat(), "status": "Scheduled", "delay_minutes": 15, "gate": "A1", "source": "vatsim", "observation_count": 3}
        ],
    )

    response = TestClient(app).get("/api/fids/detail?callsign=DLH42")

    assert response.status_code == 200
    payload = response.json()
    detail = payload["detail"]
    assert detail["detail_mode"] == "virtual"
    assert detail["flight_display"] == "DLH42"
    assert detail["airline"] is None
    assert detail["airline_iata"] is None
    assert detail["airline_icao"] is None
    assert detail["codeshares"] == []
    assert detail["sold_as"] == []
    assert detail["marketing_flight_number"] is None
    assert detail["gate"] is None
    assert detail["terminal"] is None
    assert detail["stand"] is None
    assert detail["delay_minutes"] is None
    assert detail["aircraft_registration"] is None
    assert detail["position"]["icao24"] is None
    assert detail["position"]["squawk"] == "2201"
    assert detail["flight_plan"]["route"] == "DCT TEST"
    assert detail["flight_plan"]["assigned_transponder"] == "2201"
    assert payload["history"][0]["source"] == "vatsim"
    assert "gate" not in payload["history"][0]
    assert "delay_minutes" not in payload["history"][0]
    assert payload["intel"]["detail_mode"] == "virtual"
    assert payload["intel"]["identity"]["codeshares"] == []
    assert payload["intel"]["identity"]["sold_as"] == []
    assert payload["intel"]["aircraft"]["registration"] is None
    assert payload["intel"]["aircraft"]["icao24"] is None


def test_flight_intel_builder_handles_schedule_adsb_and_vatsim_privately() -> None:
    from localflight.core.flight_intel import build_flight_intel
    from localflight.core.models import AirlineRef, FlightStatus

    now = datetime.now(timezone.utc)
    real = Flight(
        direction=FlightDirection.DEPARTURE,
        airport=AirportRef(iata="ZRH", icao="LSZH", name="Zurich"),
        callsign="SWR10",
        airline=AirlineRef(name="Swiss", iata="LX", icao="SWR"),
        flight_number="LX10",
        origin=AirportRef(iata="ZRH", icao="LSZH", name="Zurich"),
        destination=AirportRef(iata="JFK", icao="KJFK", name="New York"),
        aircraft_type="A333",
        aircraft_registration="HB-JHA",
        gate="A42",
        terminal="1",
        status=FlightStatus.SCHEDULED,
        times=FlightTime(scheduled=now),
        position=FlightPosition(
            lat=47.45,
            lon=8.55,
            altitude_baro=3048,
            speed_ms=120,
            vertical_rate=-2.5,
            heading=280,
            on_ground=False,
            icao24="4B1800",
            squawk="7000",
            last_contact=now,
        ),
        source="aviationstack",
        enriched_by="adsbexchange",
    )

    real_intel = build_flight_intel(real, [{"date": "2026-05-10", "status": "Scheduled", "delay_minutes": 8, "gate": "A42"}], generated_at=now)

    assert real_intel["detail_mode"] == "real"
    assert "ZRH" in real_intel["route"]["route_display"]
    assert "JFK" in real_intel["route"]["route_display"]
    assert real_intel["motion"]["altitude_ft"] == 10000
    assert real_intel["motion"]["speed_kt"] == 233
    assert real_intel["aircraft"]["registration"] == "HB-JHA"
    assert real_intel["history_summary"]["late_count"] == 1

    virtual = Flight(
        direction=FlightDirection.ARRIVAL,
        airport=AirportRef(iata="ZRH", icao="LSZH", name="Zurich"),
        callsign="BAW123",
        airline=AirlineRef(name="British Airways", iata="BA", icao="BAW"),
        flight_number="BA123",
        codeshares=("AA9000",),
        sold_as=("BA123",),
        marketing_flight_number="BA123",
        origin=AirportRef(icao="EGLL", name="Heathrow"),
        destination=AirportRef(icao="LSZH", name="Zurich"),
        aircraft_type="A320",
        aircraft_registration="G-TEST",
        gate="A42",
        terminal="1",
        delay_minutes=14,
        flight_rules="I",
        planned_route="DCT TEST",
        planned_altitude="FL350",
        assigned_transponder="2201",
        position=FlightPosition(lat=47.1, lon=8.1, altitude_baro=2500, speed_ms=95, heading=90, icao24="400000"),
        source="vatsim",
    )

    virtual_intel = build_flight_intel(virtual, generated_at=now)
    dumped = json.dumps(virtual_intel).lower()

    assert virtual_intel["detail_mode"] == "virtual"
    assert virtual_intel["identity"]["flight_display"] == "BAW123"
    assert virtual_intel["identity"]["airline_name"] is None
    assert virtual_intel["identity"]["codeshares"] == []
    assert virtual_intel["identity"]["sold_as"] == []
    assert virtual_intel["identity"]["marketing_flight_number"] is None
    assert virtual_intel["operations"]["gate"] is None
    assert virtual_intel["operations"]["terminal"] is None
    assert virtual_intel["timing"]["delay_minutes"] is None
    assert virtual_intel["aircraft"]["registration"] is None
    assert virtual_intel["aircraft"]["icao24"] is None
    assert virtual_intel["flight_plan"]["route"] == "DCT TEST"
    assert "airport_ops" not in virtual_intel["source_evidence"]["fields_available"]
    assert virtual_intel["privacy"]["vatsim_personal_identifiers"] is False
    assert "pilot_name" not in dumped
    assert "cid" not in dumped


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
    assert first["count"] == 2
    assert first["airborne_filtered"] == 0
    assert first["ground_filtered"] == 0
    assert {blip["callsign"] for blip in first["blips"]} == {"AIRBORNE", "SURFACE"}
    assert second["source"] == "adsbexchange_cached"


def test_api_radar_coalesces_concurrent_adsb_cache_misses(monkeypatch) -> None:
    ui_api._adsbx_radar_cache.clear()
    ui_api._opensky_radar_cache.clear()
    ui_api._radar_fetch_locks.clear()
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
    monkeypatch.setattr(ui_api, "_radar_map_payload_for_request", lambda *args, **kwargs: {"runways": []})

    calls: list[float] = []
    start = threading.Barrier(2)
    adsbx_module = types.ModuleType("localflight.sources.web.adsbexchange_client")
    adsbx_module.is_available = lambda: True

    def _fetch_aircraft(lat, lon, radius_nm, timeout_s=10):
        calls.append(radius_nm)
        return [{"hex": "abc123"}]

    adsbx_module.fetch_aircraft = _fetch_aircraft
    adsbx_module.aircraft_to_blips = lambda aircraft, center_lat, center_lon, radius_nm=50.0: [
        {
            "callsign": "SWR100",
            "lat": 47.46,
            "lon": 8.56,
            "altitude_m": 1200,
            "speed_ms": 115,
            "on_ground": False,
        }
    ]
    monkeypatch.setitem(sys.modules, "localflight.sources.web.adsbexchange_client", adsbx_module)

    results: list[dict[str, object]] = []

    def _worker() -> None:
        start.wait()
        results.append(ui_api.api_radar(20.0))

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert calls == [20.0]
    assert sorted(result["source"] for result in results) == ["adsbexchange_cached", "adsbexchange_live"]


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


def test_history_summary_adds_delay_buckets_and_filtered_analytics(tmp_path: Path, monkeypatch) -> None:
    import localflight.storage.history as history

    config_file = tmp_path / ".localflight" / "config.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(history, "config_path", lambda: config_file)

    now = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
    rows = []
    delays = [-5, -4, 4, 5, 15, 16, None]
    for idx, delay in enumerate(delays):
        rows.append((
            "ZRH",
            f"LX{100 + idx}",
            f"LX {100 + idx}",
            "ZRH" if idx % 2 == 0 else "FRA",
            "BCN" if idx % 2 == 0 else "ZRH",
            "DEP" if idx % 2 == 0 else "ARR",
            "Delayed" if delay and delay >= 5 else "Scheduled",
            "A1",
            "1",
            "A320",
            (now + timedelta(minutes=idx * 10)).isoformat(),
            None,
            None,
            None,
            None,
            "aviationstack",
            "schedule",
            now.isoformat(),
            delay,
            "LX",
        ))
    for duplicate_idx in (0, 3):
        duplicate = list(rows[duplicate_idx])
        duplicate[17] = (now + timedelta(minutes=90 + duplicate_idx)).isoformat()
        rows.append(tuple(duplicate))

    conn = history._connect()
    history._ensure_schema(conn)
    history._migrate_schema(conn)
    conn.executemany(
        """
        INSERT INTO flights (
            airport_iata, callsign, flight_number, origin_iata, dest_iata,
            direction, status, gate, terminal, aircraft_type, sched_time,
            actual_time, lat, lon, altitude_m, source, enriched_by, snapshot_ts,
            delay_minutes, airline_iata
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    conn.commit()
    conn.close()

    summary = history.query_summary("ZRH", hours=24)
    buckets = {row["bucket"]: row["count"] for row in summary["delay_buckets"]}

    assert summary["sample_rows"] == 9
    assert summary["total"] == 7
    assert buckets == {
        "early": 1,
        "on_time": 2,
        "delayed_warn": 2,
        "delayed_bad": 1,
        "unknown": 1,
    }
    assert summary["delayed"] == 3
    assert summary["top_airlines"][0]["code"] == "LX"
    assert summary["top_airlines"][0]["delay_rate_pct"] == 42.9
    assert summary["top_routes"][0]["origin"] in {"ZRH", "FRA"}
    assert summary["status_mix"][0]["count"] >= 3
    assert sum(row["total"] for row in summary["daily_volume"]) == 7
    assert history.query_recent("ZRH", direction="DEP", callsign="LX10", status="scheduled", airline_iata="LX", hours=24, limit=10)


def test_history_persists_resolved_operating_identity(tmp_path: Path, monkeypatch) -> None:
    import localflight.storage.history as history

    config_file = tmp_path / ".localflight" / "config.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(history, "config_path", lambda: config_file)

    flight = normalize_flights(
        [
            {
                "callsign": "UAE2426",
                "direction": "DEP",
                "status": "scheduled",
                "scheduled": datetime.now(timezone.utc).isoformat(),
                "airline_iata": "EK",
                "airline_name": "Emirates",
                "flight_number": "EK2426",
                "codeshares": ["FZ315"],
                "destination_iata": "KHI",
            }
        ],
        airport_iata="DXB",
        airport_icao="OMDB",
        source_name="test",
    )[0]

    history.write_snapshot_to_history([flight], AppConfig(airport_iata="DXB", airport_icao="OMDB"))
    rows = history.query_recent("DXB", hours=1, direction="DEP", limit=10, airline_iata="FZ")

    assert len(rows) == 1
    assert rows[0]["flight_number"] == "FZ315"
    assert rows[0]["airline_iata"] == "FZ"
    assert rows[0]["callsign"] == "UAE2426"


def _history_db_for_test(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import localflight.storage.history as history

    config_file = tmp_path / ".localflight" / "config.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(history, "config_path", lambda: config_file)
    conn = history._connect()
    history._ensure_schema(conn)
    history._migrate_schema(conn)
    return history, conn


def _insert_raw_history_rows(conn, rows: list[tuple[object, ...]]) -> None:
    conn.executemany(
        """
        INSERT INTO flights (
            airport_iata, callsign, flight_number, origin_iata, dest_iata,
            direction, status, gate, terminal, aircraft_type, sched_time,
            actual_time, lat, lon, altitude_m, source, enriched_by, snapshot_ts,
            delay_minutes, airline_iata, codeshares_json, sold_as_json,
            operating_callsign, identity_source
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    conn.commit()
    conn.close()


def test_history_movements_collapse_repeated_snapshot_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    history, conn = _history_db_for_test(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    sched = (now - timedelta(minutes=20)).isoformat()
    rows = [
        (
            "EWR", "UAL42", "UA42", "EWR", "LHR", "DEP", "Departed", "C8", "C", "B772",
            sched, None, None, None, None, "aerodatabox", "schedule", (now - timedelta(minutes=15)).isoformat(),
            4, "UA", '["AC5842"]', '["UA42"]', "UAL42", "dedupe",
        ),
        (
            "EWR", "UAL42", "UA 42", "EWR", "LHR", "DEP", "Departed", "C8", "C", "B772",
            sched, None, None, None, None, "aerodatabox", "schedule", (now - timedelta(minutes=5)).isoformat(),
            4, "UA", '["AC5842"]', '["UA42"]', "UAL42", "dedupe",
        ),
    ]
    _insert_raw_history_rows(conn, rows)

    recent = history.query_recent("EWR", hours=24, direction="DEP", limit=20)
    summary = history.query_summary("EWR", hours=24)

    assert len(recent) == 1
    assert recent[0]["observation_count"] == 2
    assert summary["total"] == 1
    assert summary["raw_observation_rows"] == 2


def test_history_movements_collapse_linked_codeshare_aliases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    history, conn = _history_db_for_test(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    sched = (now - timedelta(minutes=30)).isoformat()
    rows = [
        (
            "AMS", "KLM100", "KL100", "AMS", "CDG", "DEP", "Scheduled", "D4", "1", "E190",
            sched, None, None, None, None, "aerodatabox", "schedule", (now - timedelta(minutes=20)).isoformat(),
            None, "KL", '["AF8100"]', '["KL100"]', None, "codeshare",
        ),
        (
            "AMS", "AF8100", "AF8100", "AMS", "CDG", "DEP", "Scheduled", "D4", "1", "E190",
            sched, None, None, None, None, "aviationstack", "schedule", (now - timedelta(minutes=10)).isoformat(),
            None, "AF", '["KL100"]', '["AF8100"]', None, "codeshare",
        ),
    ]
    _insert_raw_history_rows(conn, rows)

    recent = history.query_recent("AMS", hours=24, direction="DEP", limit=20)
    by_alias = history.query_flight_history("AF8100", days=1)

    assert len(recent) == 1
    assert recent[0]["observation_count"] == 2
    assert by_alias and by_alias[0]["movement_key"] == recent[0]["movement_key"]


def test_history_movements_keep_unrelated_same_route_time_flights_separate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    history, conn = _history_db_for_test(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    sched = (now - timedelta(minutes=25)).isoformat()
    rows = [
        (
            "EWR", "UAL42", "UA42", "EWR", "LHR", "DEP", "Scheduled", "C8", "C", "B772",
            sched, None, None, None, None, "aerodatabox", "schedule", now.isoformat(),
            None, "UA", "[]", "[]", None, "direct",
        ),
        (
            "EWR", "BAW188", "BA188", "EWR", "LHR", "DEP", "Scheduled", "B3", "B", "B789",
            sched, None, None, None, None, "aerodatabox", "schedule", now.isoformat(),
            None, "BA", "[]", "[]", None, "direct",
        ),
    ]
    _insert_raw_history_rows(conn, rows)

    recent = history.query_recent("EWR", hours=24, direction="DEP", limit=20)

    assert len(recent) == 2
    assert {row["callsign"] for row in recent} == {"UAL42", "BAW188"}


def test_history_excludes_future_board_rows_until_event_time_is_current(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    history, conn = _history_db_for_test(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    rows = [
        (
            "NRT", "ANA1", "NH1", "NRT", "LAX", "DEP", "Scheduled", "51", "1", "B789",
            (now + timedelta(hours=4)).isoformat(), None, None, None, None, "aerodatabox", "schedule", now.isoformat(),
            None, "NH", "[]", "[]", None, "direct",
        )
    ]
    _insert_raw_history_rows(conn, rows)

    assert history.query_recent("NRT", hours=24, direction="DEP", limit=20) == []
    assert history.query_summary("NRT", hours=24)["total"] == 0


def test_history_backfill_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    history, conn = _history_db_for_test(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    sched = (now - timedelta(minutes=45)).isoformat()
    rows = [
        (
            "ZRH", "SWR2", "LX2", "ZRH", "JFK", "DEP", "Departed", "A2", "A", "A333",
            sched, None, None, None, None, "aerodatabox", "schedule", now.isoformat(),
            8, "LX", "[]", "[]", None, "direct",
        )
    ]
    _insert_raw_history_rows(conn, rows)

    first = history.query_summary("ZRH", hours=24)
    second = history.query_summary("ZRH", hours=24)

    assert first["total"] == 1
    assert second["total"] == 1
    assert second["raw_observation_rows"] == 1


def test_api_history_forwards_dashboard_filters(monkeypatch) -> None:
    import localflight.storage.history as history

    captured_recent: dict[str, object] = {}
    captured_summary: dict[str, object] = {}

    def fake_recent(**kwargs: object) -> list[dict[str, object]]:
        captured_recent.update(kwargs)
        return [{"callsign": "LX1952"}]

    def fake_summary(**kwargs: object) -> dict[str, object]:
        captured_summary.update(kwargs)
        return {"total": 1, "delay_buckets": [], "status_mix": []}

    monkeypatch.setattr(ui_server, "_setup_complete", lambda: True)
    monkeypatch.setattr(ui_api, "load_config", lambda: AppConfig(airport_iata="ZRH", airport_icao="LSZH"))
    monkeypatch.setattr(history, "query_recent", fake_recent)
    monkeypatch.setattr(history, "query_summary", fake_summary)

    client = TestClient(app)
    recent = client.get("/api/history?hours=48&direction=dep&limit=25&status=delayed&callsign=lx1952&airline_iata=lx")
    summary = client.get("/api/history/summary?hours=48&direction=dep&status=delayed&callsign=lx1952&airline_iata=lx")

    assert recent.status_code == 200
    assert summary.status_code == 200
    assert recent.json()["count"] == 1
    assert recent.json()["movement_count"] == 1
    assert recent.json()["raw_observation_rows"] == 1
    assert captured_recent == {
        "airport_iata": "ZRH",
        "hours": 48,
        "direction": "DEP",
        "limit": 25,
        "status": "delayed",
        "callsign": "lx1952",
        "airline_iata": "lx",
    }
    assert captured_summary == {
        "airport_iata": "ZRH",
        "hours": 48,
        "direction": "DEP",
        "status": "delayed",
        "callsign": "lx1952",
        "airline_iata": "lx",
    }


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
        "preset": "real_fids",
        "brightness": 0.55,
        "max_rows": 6,
        "refresh_seconds": 90,
        "page_rotation_seconds": 12,
        "default_view": "arrivals",
        "animation_enabled": False,
        "animation_mode": "static",
        "animation_speed": 3,
        "status_animation_enabled": True,
        "show_gate_info": True,
        "palette": "pax_blue",
        "options": {
            "animation_mode": "static",
            "palette": "pax_blue",
            "show_gate_info": True,
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
    preset_options = {item["id"]: item["options"] for item in presets}
    assert preset_options["real_fids"]["show_gate_info"] is True
    assert preset_options["vatsim_pilot"]["show_gate_info"] is False
    assert preset_options["vatsim_atc"]["show_gate_info"] is False
    palette_ids = {item["id"] for item in preset_payload["palettes"]}
    assert palette_ids == {"pax_blue", "solari_amber", "tower_scope", "vatsim_scope", "night_ops", "sunset_terminal", "ice_white"}
    assert not ({"standard", "technical", "cyan", "crt", "neon", "amber", "green", "white"} & palette_ids)
    panel_ids = {item["id"] for item in preset_payload["panel_presets"]}
    assert {"64x32", "128x64", "128x128", "256x128", "512x128"} <= panel_ids

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
    assert resolved["show_gate_info"] is True


def test_matrix_device_feed_uses_assigned_config_and_exposes_board_contract(tmp_path: Path, monkeypatch) -> None:
    matrix_config = tmp_path / "matrix_config.json"
    monkeypatch.setattr(ui_api, "_matrix_config_path", lambda: matrix_config)
    monkeypatch.setattr(
        ui_api,
        "load_config",
        lambda: AppConfig(airport_iata="ZRH", airport_icao="LSZH", timezone="Europe/Zurich"),
    )
    client = TestClient(ui_api.app)

    default_id = client.get("/api/matrix/v2/configs").json()["default_config_id"]
    created = client.post(
        "/api/matrix/v2/configs",
        json={
            "id": "tiny-arr",
            "name": "Tiny arrivals",
            "preset": "real_fids",
            "panel_w": 128,
            "panel_h": 128,
            "max_rows": 2,
            "default_view": "arrivals",
            "show_gate_info": True,
            "palette": "tower_scope",
        },
    ).json()["config"]
    checkin = client.post(
        "/api/matrix/v2/devices/checkin",
        json={"device_id": "board-a", "label": "Gate Board", "panel_w": 128, "panel_h": 128, "firmware": "2.0"},
    )
    assert checkin.status_code == 200
    assert checkin.json()["assigned_config_id"] == default_id
    assigned = client.patch("/api/matrix/v2/devices/board-a", json={"assigned_config_id": created["id"]})
    assert assigned.status_code == 200

    captured: dict[str, object] = {}

    def fake_fids(view: str, limit: int) -> list[dict[str, str]]:
        captured.update({"view": view, "limit": limit})
        return [
            {
                "id": "arrival-1",
                "display_time": "13:20",
                "flight_display": "LX 42",
                "flight_number": "LX42",
                "airline_iata": "LX",
                "route_display": "Zurich (LSZH)",
                "status_display": "ARRIVED",
                "status_class": "landed",
                "gate": "A42",
                "gate_display": "A42",
                "terminal_gate_display": "T1 / A42",
            }
        ]

    monkeypatch.setattr(ui_api, "api_fids", fake_fids)
    monkeypatch.setattr(ui_api, "api_metar", lambda: {})

    config = client.get("/api/matrix/v2/devices/board-a/config")
    feed = client.get("/api/matrix/v2/devices/board-a/feed")

    assert config.status_code == 200
    assert config.json()["id"] == "tiny-arr"
    assert config.json()["panel_w"] == 128
    assert config.json()["palette"] == "tower_scope"
    assert feed.status_code == 200
    assert captured == {"view": "arrivals", "limit": 8}
    payload = feed.json()
    assert payload["view"] == "arrivals"
    assert payload["show_gate_info"] is True
    assert payload["rows"][0]["gate_label"] == "T1 / A42"
    assert payload["rows"][0]["flight_number"] == "LX42"


def test_matrix_v2_legacy_presets_are_removed_from_public_profiles(tmp_path: Path, monkeypatch) -> None:
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
    assert presets == {"old": "real_fids", "ops": "real_fids", "radar": "real_fids"}


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
    assert row["gate"] == ""
    assert row["gate_display"] == ""
    assert row["gate_label"] == ""
    assert row["aircraft_type"] == "A321"
    assert row["callsign"] == "AAL100"
    assert row["status_kind"] == "scheduled"
    assert row["tone"] == "neutral"
    assert payload["metar"]["weather_icon"] == "sun"
    assert payload["metar"]["temperature_display"] == "29 C"


def test_matrix_v2_real_feed_exposes_gate_label_and_preview_toggle(tmp_path: Path, monkeypatch) -> None:
    matrix_config = tmp_path / "matrix_config.json"
    monkeypatch.setattr(ui_api, "_matrix_config_path", lambda: matrix_config)
    monkeypatch.setattr(
        ui_api,
        "load_config",
        lambda: AppConfig(airport_iata="ZRH", airport_icao="LSZH", timezone="Europe/Zurich"),
    )
    monkeypatch.setattr(
        ui_api,
        "api_fids",
        lambda view, limit: [
            {
                "id": "flight-gate",
                "display_time": "12:10",
                "flight_display": "LX 42",
                "route_display": "New York (JFK)",
                "status_display": "BOARDING",
                "status_class": "boarding",
                "gate": "A64",
                "gate_display": "A64",
                "terminal_display": "1",
                "terminal_gate_display": "T1 / A64",
                "aircraft_type": "A333",
            }
        ],
    )
    monkeypatch.setattr(ui_api, "api_metar", lambda: {})

    client = TestClient(ui_api.app)
    enabled = client.get("/api/matrix/v2/devices/preview/feed?view=departures&show_gate_info=true")
    disabled = client.get("/api/matrix/v2/devices/preview/feed?view=departures&show_gate_info=false")

    assert enabled.status_code == 200
    assert enabled.json()["show_gate_info"] is True
    assert enabled.json()["rows"][0]["gate_label"] == "T1 / A64"
    assert disabled.status_code == 200
    assert disabled.json()["show_gate_info"] is False
    assert disabled.json()["rows"][0]["gate_label"] == ""


def test_matrix_preview_feed_accepts_unsaved_overrides(tmp_path: Path, monkeypatch) -> None:
    matrix_config = tmp_path / "matrix_config.json"
    monkeypatch.setattr(ui_api, "_matrix_config_path", lambda: matrix_config)
    monkeypatch.setattr(ui_api, "load_config", lambda: AppConfig(airport_iata="ZRH", airport_icao="LSZH", source="real"))
    monkeypatch.setattr(ui_api, "api_fids", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("real FIDS must not be fetched for VATSIM preview")))
    monkeypatch.setattr(ui_api, "api_metar", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("real METAR must not be fetched for VATSIM preview")))

    response = TestClient(ui_api.app).get(
        "/api/matrix/v2/devices/preview/feed?view=arrivals&preset=vatsim_pilot&max_rows=2&show_weather=false&show_gate_info=true"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_required"] == "virtual"
    assert payload["message"] == "SET SOURCE TO VATSIM"
    assert payload["show_gate_info"] is False
    assert payload["rows"] == []


def test_matrix_v2_feed_falls_back_to_lane_with_rows(tmp_path: Path, monkeypatch) -> None:
    matrix_config = tmp_path / "matrix_config.json"
    monkeypatch.setattr(ui_api, "_matrix_config_path", lambda: matrix_config)
    monkeypatch.setattr(
        ui_api,
        "load_config",
        lambda: AppConfig(airport_iata="SIN", airport_icao="WSSS", timezone="Asia/Singapore"),
    )

    def fake_fids(view: str, limit: int) -> list[dict[str, str]]:
        if view == "departures":
            return []
        return [
            {
                "id": "arrival-1",
                "display_time": "13:20",
                "flight_display": "SQ 12",
                "route_display": "Tokyo Haneda (RJTT)",
                "status_display": "ARRIVING",
                "status_class": "active",
                "gate": "-",
            }
        ]

    monkeypatch.setattr(ui_api, "api_fids", fake_fids)
    monkeypatch.setattr(ui_api, "api_metar", lambda: {})

    response = TestClient(ui_api.app).get("/api/matrix/v2/devices/preview/feed?view=departures")

    assert response.status_code == 200
    payload = response.json()
    assert payload["requested_view"] == "departures"
    assert payload["view"] == "arrivals"
    assert payload["fallback_view"] is True
    assert payload["rows"][0]["flight_display"] == "SQ 12"


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
                "gate": "A12",
                "gate_display": "A12",
                "terminal_gate_display": "T1 / A12",
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
    assert payload["show_gate_info"] is False
    assert payload["rows"][0]["route_code"] == "LSZH"
    assert payload["rows"][0]["gate"] == ""
    assert payload["rows"][0]["gate_label"] == ""
    assert set(payload["pages"]) == {"departures", "arrivals", "weather"}
    assert payload["pages"]["departures"][0]["route_code"] == "EGLL"
    assert payload["pages"]["arrivals"][0]["gate"] == ""
    assert payload["pages"]["arrivals"][0]["gate_label"] == ""
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


def test_matrix_route_fields_fold_accents_for_led_clients() -> None:
    fields = ui_api._matrix_route_fields("D\u00fcsseldorf (EDDL)")

    assert fields["route_city"] == "Duesseldorf"
    assert fields["route_code"] == "EDDL"
    assert fields["route_matrix_label"] == "DUESSELDORF EDDL"


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
                'ANIMATION_MODE = "split_flap"',
                "ANIMATION_SPEED = 3",
                "STATUS_ANIMATION_ENABLED = True",
                "SHOW_WEATHER = True",
                "SHOW_GATE_INFO = True",
                'PRESET = "real_fids"',
                'PALETTE = "pax_blue"',
                'RENDERER = "modern_fids"',
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
            "animation_mode": "slide_left",
            "animation_speed": 4,
            "status_animation_enabled": False,
            "show_weather": False,
            "show_gate_info": True,
            "preset": "vatsim_pilot",
            "palette": "tower_scope",
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
    assert 'ANIMATION_MODE = "static"' in response.text
    assert "ANIMATION_SPEED = 4" in response.text
    assert "STATUS_ANIMATION_ENABLED = False" in response.text
    assert "SHOW_WEATHER  = False" in response.text
    assert "SHOW_GATE_INFO = False" in response.text
    assert 'PRESET        = "vatsim_pilot"' in response.text
    assert 'PALETTE       = "tower_scope"' in response.text
    assert 'RENDERER      = "vatsim_pilot"' in response.text


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
    assert 'CLIENT_RENDERER_REV = "matrix-display-contract-v2"' in script
    assert "import interstate75 as interstate75_module" in script
    assert "def update_display():" in script
    assert "def fit_text(value, length):" in script
    assert "def _ascii_text(value):" in script
    assert "def _text_field(value, fallback=\"\"):" in script
    assert "def _clock_hhmm(offset_minutes=0):" in script
    assert "def _clock_label(compact=False):" in script
    assert '"U{} L{}"' in script
    assert "clock_utc_epoch" in script
    assert "ACTIVE_BREATH" in script
    assert "AMBER_BREATH" in script
    assert "def cycle_chunks(value, width, code=\"\"):" in script
    assert "def code_preserve(value, code, width):" in script
    assert "def marquee(value, width, step=None):" in script
    assert "def draw_glyph(name, x, y, color):" in script
    assert "route_matrix_label" in script
    assert "matrix_flight_label" in script
    assert "matrix_weather_icon" in script
    assert "def _weather_line(chars=18):" in script
    assert "SHOW_WEATHER" in script
    assert "SHOW_GATE_INFO" in script
    assert "def _gate_label(row):" in script
    assert "def _status_or_gate_chunk(row, chars):" in script
    assert "_airport_label" in script
    assert '"temp": ["00100", "01010", "01010", "10001", "01110"]' in script
    assert '"snow": ["10101", "01010", "10101", "01010", "10101"]' in script
    assert '"WX "' not in script
    assert "def _weather_temp_text():" in script
    assert "def draw_weather_mini(x, y, max_width):" in script
    assert "return 30 if HEIGHT >= 96 and _weather_line(8) else 20" not in script
    assert "def draw_vatsim_weather_page():" in script
    assert "def draw_vatsim_atc(flap_rows, fallback_rows, fallback_view):" in script
    assert "time_label = fit_text(text[0:5].strip()" in script
    assert "flight_label = fit_text(text[6:14].strip()" in script
    assert "status = text[28:38].strip()" in script
    assert "\"real_fids\"" in script
    assert "\"vatsim_pilot\"" in script
    assert "\"vatsim_atc\"" in script
    assert 'PALETTE       = "pax_blue"' in script
    assert 'RENDERER      = "modern_fids"' in script
    assert ".ljust(" not in script
    assert "DISPLAY, DISPLAY_PANELS = _display_for_size(PANEL_W, PANEL_H)" in script
    assert "Unsupported Interstate 75 display size" in script
    assert "compact = WIDTH < 180" in script
    assert "compact = WIDTH < 190" in script
    assert "if WIDTH < 200:" in script
    assert "draw_row(flap_rows[i], row_data, y, row_h)" in script
    assert "text[39:43]" in script
    assert "CODE_SHARE_ROTATION_S = 4" in script
    assert "def _flight_cycle_display(row):" in script
    assert "limit=min(_visible_rows() * 4, 32)" in script
    assert "urequests.get(_api_url(path))" in script
    assert "timeout=timeout" not in script
    assert "/api/matrix/v2/devices/checkin" in script
    assert "/api/matrix/v2/devices/{device_id()}/config" in script
    assert "/api/matrix/v2/devices/{device_id()}/feed" in script
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
    assert '"sunset_terminal"' in script
    assert '"ice_white"' in script
    for legacy in ('"standard"', '"technical"', '"cyan"', '"crt"', '"neon"', '"green"', '"white"', '"classic_split_flap"', '"vatsim_ops"', '"radar_strip"'):
        assert legacy not in script


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
    assert metar["matrix_weather_icon"] == "sun"
    assert metar["matrix_weather_temp"] == "30C"
    assert metar["matrix_weather_label"] == "Clear"


def test_matrix_preview_download_payload_uses_defined_animation_state() -> None:
    root = Path(__file__).resolve().parents[1]
    template = (root / "src" / "localflight" / "ui" / "templates" / "matrix_preview.html").read_text(encoding="utf-8")

    assert 'animation_enabled: ANIMATION_MODE !== "static"' in template
    assert "animation_enabled: ANIMATION_ENABLED" not in template
    assert "SHOW_WEATHER" in template
    assert "SHOW_GATE_INFO" in template
    assert "weatherToggle" in template
    assert "gateToggle" in template
    assert 'id="paletteSelect"' in template
    assert 'id="animationSpeedSelect"' in template
    assert 'id="statusMotionToggle"' in template
    assert "Live after Apply" in template
    assert "Regenerate main.py when" in template
    assert "matrix-status-grid" in template
    assert "Setup guide" in template
    assert "One-time main.py creator" in template
    assert '<details class="matrix-section" open>' not in template
    assert "Connected boards" in template
    assert "Multiple configs" in template
    assert "Advanced: how the board talks to Local Flight" in template
    assert "matrix_guidance.steps" in template
    assert "MATRIX_DEVICES" in template
    assert "scheduleRowsFetch" in template
    assert "/api/matrix/v2/devices" in template
    assert "Apply live config" in template
    assert "Preview animation" in template
    assert "Apply to board" not in template
    assert "about 60 seconds" in template
    assert "function setPreviewPalette(name)" in template
    assert "MATRIX_PALETTE_OPTIONS" in template
    assert "MATRIX_PANEL_PRESETS" in template
    assert "row.matrix_flight_label" in template
    assert "txt.slice(0,5).trim()" in template
    assert "txt.slice(6,14).trim()" in template
    assert "txt.slice(28,38).trim()" in template
    assert "MATRIX_METAR?.matrix_weather_icon" in template
    assert "const choices = [primary" not in template
    assert "palette: MATRIX_PALETTE" in template
    assert "default_view: VIEW" in template
    assert "status_animation_enabled: STATUS_ANIMATION_ENABLED" in template
    assert "show_gate_info: SHOW_GATE_INFO" in template
    assert "preset: MATRIX_PRESET" in template
    assert "condition_display" in template
    assert 'WX ${' not in template
    assert "function weatherTempText()" in template
    assert "function drawWeatherMini" in template
    assert "return PANEL_H >= 96 && weatherLine(8) ? 30 : 20" not in template
    assert "function asciiText" in template
    assert "function clockLabel" in template
    assert "PANEL_W < 200" in template
    assert 'id="btnDep"' not in template
    assert 'id="btnArr"' not in template
    assert "setView" not in template
    for legacy in ('value="standard"', 'value="technical"', 'value="cyan"', 'value="crt"', 'value="neon"', 'value="green"', 'value="white"'):
        assert legacy not in template


def test_history_template_uses_dashboard_summary_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    template = (root / "src" / "localflight" / "ui" / "templates" / "history.html").read_text(encoding="utf-8")

    assert "loadDashboard" in template
    assert "/api/history/summary" in template
    assert "delay_buckets" in template
    assert "status_mix" in template
    assert "top_airlines" in template
    assert "top_routes" in template
    assert 'id="airlineInput"' in template
    assert "movements from" in template
    assert "No matching movements yet" in template


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
    assert "function gateLabel(row)" in template
    assert "function statusOrGateChunk(row, chars)" in template
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
    assert 'form_layout.addRow("Panel combo", self.panel_preset)' in source
    assert 'form_layout.addRow("Custom size", self._panel_size_row())' in source
    assert 'form_layout.addRow("Startup lane", self.default_view_select)' in source
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
    assert "def _weather_temp_text" in source
    assert "def _weather_compact_token" in source
    assert "return 30 if self.panel_h >= 96 and self._weather_line(8) else 20" not in source
    assert "def _vatsim_atc_page" in source
    assert "set_matrix_payload" in source
    assert "/api/matrix/v2/devices/preview/feed" in source
    assert '"pax_blue"' in source
    assert '"tower_scope"' in source
    assert '"night_ops"' in source
    assert '"sunset_terminal"' in source
    assert '"ice_white"' in source
    for legacy in ('            "standard",', '            "technical",', '            "cyan",', '            "crt",', '            "neon",', '            "green",', '            "white",'):
        assert legacy not in source


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


def test_client_settings_explain_refresh_cadence_and_relay_policy() -> None:
    root = Path(__file__).resolve().parents[1]
    web_settings = (root / "src" / "localflight" / "ui" / "templates" / "settings.html").read_text(encoding="utf-8")
    native_settings = "\n".join(
        [
            (root / "src" / "localflight" / "native" / "_legacy_app.py").read_text(encoding="utf-8"),
            (root / "src" / "localflight" / "native" / "pages" / "settings.py").read_text(encoding="utf-8"),
        ]
    )
    mobile_settings = (root / "mobile" / "src" / "screens" / "AppScreens.tsx").read_text(encoding="utf-8")

    assert "settings_options.refresh" in web_settings
    assert "schedule_policy.reason" in web_settings
    for text in (native_settings, mobile_settings):
        assert "15, 30, 45, and 60 minutes" in text
    assert "schedule_policy" in web_settings
    for text in (native_settings, mobile_settings):
        assert "Community Relay" in text
        assert "hourly" in text or "hourly-or-slower" in text or "schedule_policy" in text


def test_fids_template_has_vatsim_display_contract_guards() -> None:
    root = Path(__file__).resolve().parents[1]
    template = (root / "src" / "localflight" / "ui" / "templates" / "fids.html").read_text(encoding="utf-8")

    assert "function isVirtualRow" in template
    assert "function isVirtualDetail" in template
    assert "XPDR ${esc(xpdr)}" in template
    assert "Recent Sessions (7 days)" in template
    assert "Virtual Summary" in template
    assert "Filed Plan" in template
    assert "Pilot Track" in template


def test_event_first_client_polling_static_contracts() -> None:
    root = Path(__file__).resolve().parents[1]
    fids = (root / "src" / "localflight" / "ui" / "templates" / "fids.html").read_text(encoding="utf-8")
    radar = (root / "src" / "localflight" / "ui" / "templates" / "radar.html").read_text(encoding="utf-8")
    admin = (root / "src" / "localflight" / "ui" / "templates" / "admin.html").read_text(encoding="utf-8")
    matrix = (root / "src" / "localflight" / "ui" / "templates" / "matrix_preview.html").read_text(encoding="utf-8")
    mobile_shell = (root / "mobile" / "src" / "app" / "AppShell.tsx").read_text(encoding="utf-8")
    mobile_formatting = (root / "mobile" / "src" / "domain" / "formatting.ts").read_text(encoding="utf-8")

    assert "setInterval(refreshFIDS, 60000)" not in fids
    assert "scheduleFidsFallback" in fids
    assert "FIDS_FALLBACK_MS = 300 * 1000" in fids
    assert "setInterval(refreshAll, 10000)" not in admin
    assert "scheduleAdminFallback" in admin
    assert "ADMIN_FALLBACK_MS = 60 * 1000" in admin
    assert "RADAR_VISIBLE_MIN_MS = 60 * 1000" in radar
    assert "RADAR_HIDDEN_MIN_MS = 300 * 1000" in radar
    assert "radarFetching" in radar
    assert "setInterval(fetchRows, POLL_MS)" not in matrix
    assert "MATRIX_PREVIEW_MIN_POLL_MS = 60 * 1000" in matrix
    assert "refreshInFlightRef" in mobile_shell
    assert "lastRadarRefreshAfterRef" in mobile_shell
    assert "includeDashboard: false" in mobile_shell
    assert "Math.max(300, seconds || 300)" in mobile_formatting


def test_mobile_companion_routes_are_trimmed_to_supported_shells() -> None:
    root = Path(__file__).resolve().parents[1]
    mobile_types = (root / "mobile" / "src" / "domain" / "types.ts").read_text(encoding="utf-8")
    mobile_shell = (root / "mobile" / "src" / "app" / "AppShell.tsx").read_text(encoding="utf-8")
    mobile_screens = (root / "mobile" / "src" / "screens" / "AppScreens.tsx").read_text(encoding="utf-8")

    assert 'export type Screen = "fids" | "radar" | "history" | "control" | "help" | "settings";' in mobile_types
    assert 'screen === "matrix"' not in mobile_shell
    assert 'screen === "admin"' not in mobile_shell
    assert 'screen === "docs"' not in mobile_shell
    assert 'target === "matrix"' not in mobile_shell
    assert 'target === "admin"' not in mobile_shell
    assert 'target === "docs"' not in mobile_shell
    assert "export function MatrixScreen" not in mobile_screens
    assert "export function AdminScreen" not in mobile_screens
    assert "export function SettingsScreen" not in mobile_screens
    assert "export function DocsScreen" not in mobile_screens


def test_mobile_help_screen_refreshes_from_dashboard_summary() -> None:
    root = Path(__file__).resolve().parents[1]
    mobile_shell = (root / "mobile" / "src" / "app" / "AppShell.tsx").read_text(encoding="utf-8")
    mobile_screens = (root / "mobile" / "src" / "screens" / "AppScreens.tsx").read_text(encoding="utf-8")

    assert "function screenNeedsDashboard" in mobile_shell
    assert 'target === "control" || target === "help"' in mobile_shell
    assert 'includeDashboard: screenNeedsDashboard(screen, isStandalone)' in mobile_shell
    assert 'onOpenHelp={() => setScreen("help")}' in mobile_shell
    assert '<HelpScreen' in mobile_shell
    assert "Open mobile help" in mobile_screens


def test_mobile_setup_copy_matches_companion_and_standalone_product() -> None:
    root = Path(__file__).resolve().parents[1]
    mobile_screens = (root / "mobile" / "src" / "screens" / "AppScreens.tsx").read_text(encoding="utf-8")

    assert "LAN Mobile" not in mobile_screens
    assert "full local-server experience" not in mobile_screens
    assert "Checking /api/health on the Local Flight server" not in mobile_screens
    assert "Local Flight Mobile will save this pairing locally" not in mobile_screens
    assert "Companion keeps this phone as a remote and glance screen" in mobile_screens
    assert "Connect your Local Flight host" in mobile_screens
    assert "Host status" in mobile_screens


def test_setup_copy_uses_friendlier_relay_and_launch_terms() -> None:
    root = Path(__file__).resolve().parents[1]
    guidance = (root / "src" / "localflight" / "ui" / "setup_guidance.py").read_text(encoding="utf-8")
    template = (root / "src" / "localflight" / "ui" / "templates" / "setup.html").read_text(encoding="utf-8")

    assert "client keyless" not in template
    assert "shared schedule allowance" not in template
    assert "Support ID" not in template
    assert "Relay host" not in template
    assert "advanced token field" not in template
    assert "Connect this install" not in template
    assert "Verify relay path" not in template
    assert "Launch Local Flight" not in template
    assert "Local Flight Relay" in guidance
    assert "Review & Open" in guidance
    assert "Device code" in template
    assert "Test relay access" in template
    assert "Open Local Flight" in template


def test_public_preview_gallery_includes_matrix_artwork() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    gallery = (root / "docs" / "previews" / "index.html").read_text(encoding="utf-8")
    matrix_preview = root / "docs" / "previews" / "matrix-preview.svg"

    assert "docs/previews/matrix-preview.svg" in readme
    assert "matrix-preview.svg" in gallery
    assert readme.count("<img src=\"docs/previews/") == 9
    assert gallery.count("<article class=\"card\">") == 9
    assert matrix_preview.exists()
    ET.parse(matrix_preview)


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
        "/api/radar/map",
        "/api/radar/surface",
        "/api/metar",
        "/api/history",
        "/api/history/flight",
        "/api/history/summary",
        "/api/mobile/summary",
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


def test_lan_radar_template_uses_native_layer_controls_and_filtered_routes() -> None:
    template = Path("src/localflight/ui/templates/radar.html").read_text(encoding="utf-8")

    for control_id in [
        "mapToggle",
        "surfaceToggle",
        "runwaysToggle",
        "terrainToggle",
        "routesToggle",
        "statusToggle",
        "trafficFilter",
        "altitudeFilter",
    ]:
        assert control_id in template

    for js_hook in [
        "fetchRadarMap",
        "/api/radar/map",
        "radarQueryParams",
        "traffic",
        "min_alt_ft",
        "max_alt_ft",
        "drawMapInlay",
        "drawTerrain",
        "drawProcedures",
        "blipStatusLabel",
        "selectBlip",
        "/api/fids/detail",
    ]:
        assert js_hook in template


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

    install_response = TestClient(ui_server.app).get("/api/docs/install")
    display_response = TestClient(ui_server.app).get("/api/docs/display-modes")

    assert install_response.status_code == 200
    assert install_response.json()["filename"] == "install.md"
    assert install_response.json()["bundled"] is True
    assert "Install Guide" in install_response.json()["title"]

    assert display_response.status_code == 200
    assert display_response.json()["filename"] == "display-modes.md"
    assert display_response.json()["bundled"] is True
    assert "Display Modes" in display_response.json()["title"]


def test_docs_html_pages_expose_bundled_documents(monkeypatch) -> None:
    monkeypatch.setattr(ui_server, "_setup_complete", lambda: True)
    client = TestClient(ui_server.app)

    for slug in ("readme", "install", "display-modes", "privacy", "changelog", "third-party"):
        response = client.get(f"/docs/{slug}")
        assert response.status_code == 200
        assert "Local Flight" in response.text or "Third-Party" in response.text
        assert f"/docs/{slug}" in response.text

    response = client.get("/docs/nope")
    assert response.status_code == 404


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
        "/admin/api/fleet",
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


def test_operator_power_stays_out_of_public_docs_and_examples() -> None:
    root = Path(__file__).resolve().parents[1]
    gitignore = (root / ".gitignore").read_text(encoding="utf-8")
    env_example = (root / ".env.example").read_text(encoding="utf-8")

    for private_name in (
        "start_network.bat",
        "start_network.local.bat",
        "operator/",
        "AGENTS.md",
        "DEV_README.md",
        "docs/native-first-redesign.md",
    ):
        assert private_name in gitignore

    for secret_name in (
        "RELAY_ADMIN_PASSWORD",
        "LINEAR_REPORTER_API_KEY",
        "LINEAR_TEAM_IOS_ID",
        "LINEAR_TEAM_DESKTOP_ID",
        "LINEAR_TEAM_SERVER_ID",
        "LINEAR_TEAM_RELAY_ID",
        "LINEAR_TEAM_DEFAULT_ID",
    ):
        assert secret_name not in env_example

    public_docs = [
        root / "README.md",
        root / "PRIVACY.md",
        root / "docs" / "install.md",
        root / "docs" / "display-modes.md",
    ]
    forbidden_public_terms = (
        "start_network.bat",
        "/admin/api",
        "network.localflight.app",
        "RELAY_ADMIN_PASSWORD",
        "LINEAR_REPORTER_API_KEY",
        "DEV_README.md",
        "AGENTS.md",
    )
    for path in public_docs:
        text = path.read_text(encoding="utf-8")
        for term in forbidden_public_terms:
            assert term not in text, f"{term} leaked into {path}"


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
    mac_install = Path("installers/macos/install.sh").read_text(encoding="utf-8")

    assert 'PI_GUI_MODE="headless"' in pi_install
    assert "LOCALFLIGHT_GUI_MODE=headless" in pi_install
    assert 'PI_GUI_MODE="native"' in pi_install
    assert "localflight-native-kiosk.service" in pi_install
    assert "LOCALFLIGHT_NATIVE_UI_ONLY=1" in pi_install
    assert "LOCALFLIGHT_NATIVE_FULLSCREEN=1" in pi_install
    assert "grep -Eq" in pi_helper
    assert "has_native_kiosk" in pi_helper
    assert "import PySide6" not in pi_helper
    assert "-DisplayMode Native" in win_install
    assert "Resolve-DisplayMode" in win_install
    assert "LOCALFLIGHT_GUI_MODE=$GuiMode" in win_install
    assert 'set "PYTHON=%ROOT%\\.venv\\Scripts\\python.exe"' in win_install
    assert '$venvPythonw = Join-Path $venvPath "Scripts\\pythonw.exe"' in win_install
    assert '$silentArguments = "-m localflight"' in win_install
    assert "$lnk.TargetPath = $silentTarget" in win_install
    assert "$lnk.Arguments = $silentArguments" in win_install
    assert "Start-Process -FilePath $silentTarget -ArgumentList $silentArguments" in win_install
    assert ".env.example" not in win_install
    assert "--display native" in mac_install
    assert "DISPLAY_MODE=\"native\"" in mac_install
    assert "LOCALFLIGHT_GUI_MODE=native" in mac_install


def test_network_admin_client_accepts_relay_root_or_admin_url() -> None:
    assert _normalize_relay_base_url("https://localflight-community-relay.fly.dev") == "https://localflight-community-relay.fly.dev"
    assert _normalize_relay_base_url("https://localflight-community-relay.fly.dev/admin") == "https://localflight-community-relay.fly.dev"
    assert _normalize_relay_base_url("https://localflight-community-relay.fly.dev/admin/api") == "https://localflight-community-relay.fly.dev"
