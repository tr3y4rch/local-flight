from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import localflight.scheduler.jobs as jobs
import localflight.scheduler.runtime as runtime
import localflight.storage.flights_store as flights_store
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
