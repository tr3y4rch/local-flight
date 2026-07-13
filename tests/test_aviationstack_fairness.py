from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import localflight.scheduler.jobs as jobs
import localflight.sources.web.aviationstack_client as aviationstack_client
import localflight.ui.api as ui_api
from localflight.core.models import (
    AirlineRef,
    AirportRef,
    Flight,
    FlightDirection,
    FlightStatus,
    FlightTime,
)
from localflight.decode.mappings.aviationstack import aviationstack_to_raw_records
from localflight.decode.normalize import normalize_flights
from localflight.display.fids_from_flights import flight_to_fids_row
from localflight.render.fids import build_fids_context
from localflight.sources.web.aviationstack_plan import build_fetch_plan
from localflight.storage.config import AppConfig


def _flight(
    callsign: str,
    scheduled: datetime,
    *,
    direction: FlightDirection = FlightDirection.DEPARTURE,
    gate: str | None = None,
    terminal: str | None = None,
    aircraft_type: str | None = "A320",
) -> Flight:
    airport = AirportRef(iata="ZRH", icao="LSZH", name="Zurich")
    airline = AirlineRef(name="Swiss", iata="LX", icao="SWR")
    origin = airport if direction == FlightDirection.DEPARTURE else AirportRef(iata="LHR", icao="EGLL", name="London Heathrow")
    destination = AirportRef(iata="LHR", icao="EGLL", name="London Heathrow") if direction == FlightDirection.DEPARTURE else airport
    return Flight(
        direction=direction,
        airport=airport,
        callsign=callsign,
        airline=airline,
        flight_number=f"LX{callsign[-3:]}",
        origin=origin if direction == FlightDirection.ARRIVAL else airport,
        destination=destination if direction == FlightDirection.DEPARTURE else airport,
        aircraft_type=aircraft_type,
        gate=gate,
        terminal=terminal,
        status=FlightStatus.SCHEDULED,
        times=FlightTime(scheduled=scheduled),
        source="test",
        updated_at=scheduled,
    )


def _aviationstack_departure(
    number: str,
    scheduled: datetime,
    *,
    gate: str | None = None,
    terminal: str | None = None,
    destination_iata: str = "LHR",
) -> dict:
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
            "gate": gate,
            "terminal": terminal,
        },
        "arrival": {
            "iata": destination_iata,
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


def _normalized_signatures(payload: dict) -> list[tuple[str, str, str]]:
    raw_records = aviationstack_to_raw_records(payload, airport_iata="ZRH", mode="dep")
    flights = normalize_flights(
        raw_records,
        airport_iata="ZRH",
        airport_icao="LSZH",
        source_name="aviationstack",
    )
    return [
        (
            flight.callsign,
            flight.display_time(),
            flight.destination.code() if flight.destination else "",
        )
        for flight in flights
    ]


def test_build_fetch_plan_same_day_window_uses_single_local_date() -> None:
    now = datetime(2026, 5, 1, 3, 0, tzinfo=timezone.utc)

    plan = build_fetch_plan(
        airport_iata="ZRH",
        mode="departures",
        timezone_name="UTC",
        now=now,
        pages_per_date=4,
    )

    assert len(plan) == 4
    assert {request.flight_date for request in plan} == {"2026-05-01"}
    assert [request.offset for request in plan] == [0, 100, 200, 300]
    assert all(request.dep_iata == "ZRH" and request.arr_iata is None for request in plan)


def test_build_fetch_plan_cross_midnight_spans_two_dates_and_respects_page_cap() -> None:
    now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)

    plan = build_fetch_plan(
        airport_iata="ZRH",
        mode="arrivals",
        timezone_name="UTC",
        now=now,
        pages_per_date=3,
    )

    assert len(plan) == 6
    assert [plan[0].flight_date, plan[-1].flight_date] == ["2026-05-01", "2026-05-02"]
    assert [request.offset for request in plan[:3]] == [0, 100, 200]
    assert [request.offset for request in plan[3:]] == [0, 100, 200]
    assert all(request.arr_iata == "ZRH" and request.dep_iata is None for request in plan)


def test_fetch_flights_strategy_fair_beats_baseline_on_date_scoped_fixture(monkeypatch) -> None:
    now = datetime(2026, 5, 1, 3, 0, tzinfo=timezone.utc)
    rows = [
        _aviationstack_departure("100", now + timedelta(hours=1), gate="A1"),
        _aviationstack_departure("102", now + timedelta(hours=2), gate="A2"),
    ]

    def fake_fetch_flights_once(**kwargs):
        flight_date = kwargs.get("flight_date")
        offset = kwargs.get("offset", 0)
        limit = kwargs.get("limit", 100)
        if flight_date is None:
            return {"pagination": {"limit": limit, "offset": offset}, "data": []}
        if flight_date == "2026-05-01" and offset == 0:
            return {"pagination": {"limit": limit, "offset": 0}, "data": rows}
        return {"pagination": {"limit": limit, "offset": offset}, "data": []}

    monkeypatch.setattr(aviationstack_client, "fetch_flights_once", fake_fetch_flights_once)

    baseline_payload, baseline_meta = aviationstack_client.fetch_flights_strategy(
        airport_iata="ZRH",
        timezone_name="UTC",
        mode="departures",
        strategy="baseline",
        page_size=2,
        pages_per_date=2,
        now=now,
    )
    fair_payload, fair_meta = aviationstack_client.fetch_flights_strategy(
        airport_iata="ZRH",
        timezone_name="UTC",
        mode="departures",
        strategy="fair",
        page_size=2,
        pages_per_date=2,
        now=now,
    )

    assert baseline_meta["pages_fetched"] == 1
    assert len(baseline_payload["data"]) == 0
    assert fair_meta["dates_touched"] == ["2026-05-01"]
    assert len(fair_payload["data"]) == 2


def test_fetch_flights_strategy_fair_adds_adaptive_pages_until_window_is_covered(monkeypatch) -> None:
    now = datetime(2026, 5, 1, 5, 0, tzinfo=timezone.utc)
    start = datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc)
    calls: list[tuple[str | None, int]] = []

    def fake_fetch_flights_once(**kwargs):
        flight_date = kwargs.get("flight_date")
        offset = int(kwargs.get("offset", 0) or 0)
        limit = int(kwargs.get("limit", 100) or 100)
        calls.append((flight_date, offset))
        if flight_date != "2026-05-01" or offset >= 500:
            return {"pagination": {"limit": limit, "offset": offset}, "data": []}
        rows = [
            _aviationstack_departure(
                f"{1000 + offset + idx}",
                start + timedelta(minutes=offset + idx),
                gate="A1",
            )
            for idx in range(limit)
        ]
        return {"pagination": {"limit": limit, "offset": offset}, "data": rows}

    monkeypatch.setattr(aviationstack_client, "fetch_flights_once", fake_fetch_flights_once)

    payload, meta = aviationstack_client.fetch_flights_strategy(
        airport_iata="ZRH",
        timezone_name="UTC",
        mode="departures",
        strategy="fair",
        display_horizon_hours=2,
        page_size=100,
        pages_per_date=4,
        now=now,
    )

    latest = datetime.fromisoformat(payload["data"][-1]["departure"]["scheduled"])

    assert meta["pages_requested"] == 4
    assert meta["pages_fetched"] == 5
    assert meta["adaptive_extra_pages"] == 1
    assert calls[-1] == ("2026-05-01", 400)
    assert latest >= datetime(2026, 5, 1, 7, 0, tzinfo=timezone.utc)


def test_fetch_flights_strategy_fair_falls_back_to_undated_when_date_scope_is_board_empty(monkeypatch) -> None:
    now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    early = _aviationstack_departure("100", datetime(2026, 5, 1, 5, 0, tzinfo=timezone.utc), gate="A1")
    rescue = _aviationstack_departure("200", datetime(2026, 5, 1, 15, 0, tzinfo=timezone.utc), gate="B7")

    def fake_fetch_flights_once(**kwargs):
        flight_date = kwargs.get("flight_date")
        offset = kwargs.get("offset", 0)
        limit = kwargs.get("limit", 100)
        if flight_date == "2026-05-01" and offset == 0:
            return {"pagination": {"limit": limit, "offset": 0}, "data": [early]}
        if flight_date is None and offset == 0:
            return {"pagination": {"limit": limit, "offset": 0}, "data": [early, rescue]}
        return {"pagination": {"limit": limit, "offset": offset}, "data": []}

    monkeypatch.setattr(aviationstack_client, "fetch_flights_once", fake_fetch_flights_once)

    payload, meta = aviationstack_client.fetch_flights_strategy(
        airport_iata="ZRH",
        timezone_name="UTC",
        mode="departures",
        strategy="fair",
        display_horizon_hours=12,
        page_size=100,
        pages_per_date=4,
        now=now,
    )

    scheduled_values = {row["departure"]["scheduled"] for row in payload["data"]}

    assert meta["undated_fallback_used"] is True
    assert any(key.startswith("departures:undated") for key in meta["pages_by_scope"])
    assert rescue["departure"]["scheduled"] in scheduled_values


def test_dedupe_identical_flights_collapses_duplicate_pages_and_keeps_best_details() -> None:
    scheduled = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    plain = _flight("SWR100", scheduled)
    detailed = _flight("SWR100", scheduled, gate="A12", terminal="1", aircraft_type="A321")

    deduped = jobs._dedupe_identical_flights([plain, detailed])

    assert len(deduped) == 1
    assert deduped[0].gate == "A12"
    assert deduped[0].terminal == "1"
    assert deduped[0].aircraft_type == "A321"


def test_dedupe_identical_flights_preserves_distinct_callsigns_same_route_and_time() -> None:
    scheduled = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    flight_a = _flight("SWR100", scheduled)
    flight_b = _flight("UAL100", scheduled)

    deduped = jobs._dedupe_identical_flights([flight_a, flight_b])

    assert len(deduped) == 2
    assert {flight.callsign for flight in deduped} == {"SWR100", "UAL100"}


def test_display_window_config_changes_visible_board_rows() -> None:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    recent_departure = _flight("SWR110", now - timedelta(minutes=45))
    distant_departure = _flight("SWR120", now + timedelta(hours=18))

    tight_cfg = AppConfig(
        airport_iata="ZRH",
        airport_icao="LSZH",
        timezone="UTC",
        display_grace_minutes=30,
        display_horizon_hours=12,
    )
    wide_cfg = AppConfig(
        airport_iata="ZRH",
        airport_icao="LSZH",
        timezone="UTC",
        display_grace_minutes=60,
        display_horizon_hours=24,
    )

    tight_rows = build_fids_context(
        cfg=tight_cfg,
        view="departures",
        refresh_seconds=tight_cfg.refresh_seconds,
        flights=[recent_departure, distant_departure],
        last_refreshed=now,
        allow_sparse_fallback=False,
        source_status="test",
    )["rows"]
    wide_rows = build_fids_context(
        cfg=wide_cfg,
        view="departures",
        refresh_seconds=wide_cfg.refresh_seconds,
        flights=[recent_departure, distant_departure],
        last_refreshed=now,
        allow_sparse_fallback=False,
        source_status="test",
    )["rows"]

    assert len(list(tight_rows)) == 0
    assert len(list(wide_rows)) == 2


def test_build_fids_context_uses_sparse_fallback_when_window_is_empty() -> None:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    older_a = _flight("SWR110", now - timedelta(hours=4))
    older_b = _flight("SWR120", now - timedelta(hours=2))

    cfg = AppConfig(
        airport_iata="ZRH",
        airport_icao="LSZH",
        timezone="UTC",
        web_row_limit=10,
        display_grace_minutes=30,
        display_horizon_hours=12,
    )

    ctx = build_fids_context(
        cfg=cfg,
        view="departures",
        refresh_seconds=cfg.refresh_seconds,
        flights=[older_a, older_b],
        last_refreshed=now,
        source_status="test",
    )

    rows = list(ctx["rows"])

    assert ctx["sparse_window_fallback"] is True
    assert len(rows) == 2
    assert [row.callsign for row in rows] == ["SWR110", "SWR120"]


def test_api_fids_can_serve_overflow_rows_for_rotating_clients(monkeypatch) -> None:
    now = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
    flights = [
        _flight(f"SWR{100 + idx}", now + timedelta(minutes=idx * 10))
        for idx in range(15)
    ]

    monkeypatch.setattr(
        ui_api,
        "load_config",
        lambda: AppConfig(
            airport_iata="ZRH",
            airport_icao="LSZH",
            timezone="UTC",
            web_row_limit=10,
            display_grace_minutes=60,
            display_horizon_hours=24,
        ),
    )
    monkeypatch.setattr(ui_api, "_load_latest_flights", lambda airport_iata: (flights, now))

    rows = ui_api.api_fids(view="departures", limit=40)

    assert len(rows) == 15
    assert rows[0].callsign == "SWR100"
    assert rows[-1].callsign == "SWR114"


def test_api_fids_uses_sparse_departure_fallback_when_window_is_empty(monkeypatch) -> None:
    now = datetime(2026, 5, 1, 14, 0, tzinfo=timezone.utc)
    flights = [
        _flight("SWR100", datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc)),
        _flight("SWR101", datetime(2026, 5, 1, 9, 30, tzinfo=timezone.utc)),
    ]

    monkeypatch.setattr(
        ui_api,
        "load_config",
        lambda: AppConfig(
            airport_iata="ZRH",
            airport_icao="LSZH",
            timezone="UTC",
            web_row_limit=10,
            display_grace_minutes=30,
            display_horizon_hours=12,
        ),
    )
    monkeypatch.setattr(ui_api, "_load_latest_flights", lambda airport_iata: (flights, now))

    rows = ui_api.api_fids(view="departures", limit=20)

    assert len(rows) == 2
    assert [row.callsign for row in rows] == ["SWR100", "SWR101"]


def test_api_fids_compiles_fused_aerodatabox_rows_for_web(monkeypatch) -> None:
    now = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
    flight = replace(
        _flight("SWR100", now + timedelta(hours=1), gate="A42", terminal="1", aircraft_type="A320"),
        source="aerodatabox+aviationstack",
        delay_minutes=7,
        codeshares=("BA7100", "UA9000"),
    )

    monkeypatch.setattr(
        ui_api,
        "load_config",
        lambda: AppConfig(
            airport_iata="ZRH",
            airport_icao="LSZH",
            timezone="UTC",
            web_row_limit=10,
            display_grace_minutes=60,
            display_horizon_hours=24,
        ),
    )
    monkeypatch.setattr(ui_api, "_load_latest_flights", lambda airport_iata: ([flight], now))

    rows = ui_api.api_fids(view="departures", limit=10)

    assert len(rows) == 1
    row = rows[0]
    assert row.callsign == "SWR100"
    assert row.flight_display == "LX 100"
    assert row.airline_display == "Swiss"
    assert row.codeshare_display == "Also BA 7100 / UA 9000"
    assert row.route_display == "London (LHR)"
    assert row.gate_display == "A42"
    assert row.terminal_display == "1"
    assert row.terminal_gate_display == "A42"
    assert row.aircraft_type == "A320"
    assert row.status_display == "DELAYED +7M"
    assert row.source_hint == "aerodatabox+aviationstack"


def test_gate_first_fusion_prefers_confident_fallback_gate_over_terminal_like_primary() -> None:
    scheduled = datetime(2026, 5, 1, 13, 0, tzinfo=timezone.utc).isoformat()
    primary = [
        {
            "callsign": "SWR100",
            "direction": "DEP",
            "status": "scheduled",
            "scheduled": scheduled,
            "airline_iata": "LX",
            "airline_icao": "SWR",
            "flight_number": "LX100",
            "origin_iata": "ZRH",
            "origin_icao": "LSZH",
            "destination_iata": "JFK",
            "destination_icao": "KJFK",
            "gate": "2",
            "terminal": "2",
        }
    ]
    fill = [
        {
            "callsign": "SWR100",
            "direction": "DEP",
            "status": "scheduled",
            "scheduled": scheduled,
            "airline_iata": "LX",
            "airline_icao": "SWR",
            "flight_number": "LX100",
            "origin_iata": "ZRH",
            "origin_icao": "LSZH",
            "destination_iata": "JFK",
            "destination_icao": "KJFK",
            "gate": "E43",
        }
    ]

    from localflight.sources.web.schedule_fusion import merge_schedule_records

    merged, meta = merge_schedule_records(primary, fill)
    flights = normalize_flights(merged, airport_iata="ZRH", airport_icao="LSZH", source_name="aerodatabox+aviationstack")
    row = flight_to_fids_row(flights[0], view="departures", display_tz=ZoneInfo("Europe/Zurich"))

    assert meta["filled_fields"] >= 1
    assert flights[0].gate == "E43"
    assert flights[0].terminal == "2"
    assert flights[0].gate_confidence == "high"
    assert "ops_location.gate_replaced_by_higher_confidence_source" in flights[0].ops_location_notes
    assert row.gate == "E43"
    assert row.gate_display == "E43"
    assert row.terminal_display == "2"
    assert row.terminal_gate_display == "E43"


def test_byok_and_relay_fair_fetch_normalize_equivalently(monkeypatch) -> None:
    now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    payload_map = {
        ("2026-05-01", 0): {
            "pagination": {"limit": 2, "offset": 0},
            "data": [
                _aviationstack_departure("100", now + timedelta(hours=1), gate="A1"),
                _aviationstack_departure("102", now + timedelta(hours=2), gate="A2"),
            ],
        },
        ("2026-05-01", 2): {
            "pagination": {"limit": 2, "offset": 2},
            "data": [],
        },
        ("2026-05-02", 0): {
            "pagination": {"limit": 2, "offset": 0},
            "data": [
                _aviationstack_departure("104", now + timedelta(hours=13), gate="A3"),
            ],
        },
    }
    byok_calls: list[tuple[str | None, int]] = []
    relay_calls: list[tuple[str | None, int]] = []

    def fake_byok(**kwargs):
        key = (kwargs.get("flight_date"), kwargs.get("offset", 0))
        byok_calls.append(key)
        return payload_map.get(
            key,
            {"pagination": {"limit": kwargs.get("limit", 2), "offset": kwargs.get("offset", 0)}, "data": []},
        )

    def fake_relay(**kwargs):
        key = (kwargs.get("flight_date"), kwargs.get("offset", 0))
        relay_calls.append(key)
        return payload_map.get(
            key,
            {"pagination": {"limit": kwargs.get("limit", 2), "offset": kwargs.get("offset", 0)}, "data": []},
        )

    monkeypatch.setattr(aviationstack_client, "_fetch_byok", fake_byok)
    monkeypatch.setattr(aviationstack_client, "_fetch_relay", fake_relay)
    monkeypatch.setattr(aviationstack_client, "_fetch_community_direct", fake_relay)
    monkeypatch.setattr(aviationstack_client, "_has_community_api_key", lambda: False)

    monkeypatch.setattr(aviationstack_client, "_has_enabled_byok_key", lambda: True)
    monkeypatch.setattr(aviationstack_client, "_has_activation_token", lambda: False)
    byok_payload, _ = aviationstack_client.fetch_flights_strategy(
        airport_iata="ZRH",
        timezone_name="UTC",
        mode="departures",
        strategy="fair",
        page_size=2,
        pages_per_date=2,
        now=now,
    )

    monkeypatch.setattr(aviationstack_client, "_has_enabled_byok_key", lambda: False)
    monkeypatch.setattr(aviationstack_client, "_has_activation_token", lambda: True)
    relay_payload, _ = aviationstack_client.fetch_flights_strategy(
        airport_iata="ZRH",
        timezone_name="UTC",
        mode="departures",
        strategy="fair",
        page_size=2,
        pages_per_date=2,
        now=now,
    )

    assert byok_calls == relay_calls
    assert _normalized_signatures(byok_payload) == _normalized_signatures(relay_payload)


def test_shared_relay_schedule_records_feed_normalize_pipeline_without_provider_json(monkeypatch) -> None:
    records = [
        {
            "callsign": "SWR100",
            "direction": "DEP",
            "status": "scheduled",
            "scheduled": "2026-05-01T13:00:00+00:00",
            "estimated": "2026-05-01T13:00:00+00:00",
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
    ]

    monkeypatch.setattr(aviationstack_client, "_relay_uses_shared_schedule", lambda source=None: True)
    monkeypatch.setattr(
        aviationstack_client,
        "fetch_relay_schedule_records",
        lambda **kwargs: (records, {"cache_state": "fresh"}),
    )

    flights = jobs._fetch_aviationstack(
        AppConfig(
            airport_iata="ZRH",
            airport_icao="LSZH",
            timezone="Europe/Zurich",
            source="real",
        )
    )

    assert len(flights) == 1
    assert flights[0].callsign == "SWR100"
    assert flights[0].gate == "E45"
