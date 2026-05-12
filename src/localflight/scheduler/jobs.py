"""
localflight/scheduler/jobs.py

End-to-end snapshot job.

Source modes:
  "real"    -> AviationStack (schedule) + position enrichment
  "virtual" -> VATSIM live feed (schedule + position in one)

Enrichment priority for "real":
  1. ADS-B Exchange (RapidAPI) — best quality, aircraft type, registration
  2. OpenSky Network — fallback if ADS-B Exchange unavailable/rate limited
  3. No enrichment — schedule data only

Pipeline for "real":
  1. Fetch AviationStack departures + arrivals
  2. Normalise -> List[Flight]
  3. Try ADS-B Exchange enrichment
  4. Fall back to OpenSky if needed
  5. Deduplicate codeshares
  6. Save snapshot + write to history DB
  7. Broadcast WebSocket event to all connected clients
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import List, Optional

from localflight.core.models import Flight
from localflight.decode.dedupe import dedupe_codeshares
from localflight.decode.mappings.aviationstack import aviationstack_to_raw_records
from localflight.decode.normalize import normalize_flights
from localflight.storage.config import AppConfig
from localflight.storage.flights_store import prune_snapshots, save_snapshot, snapshot_age_seconds

log = logging.getLogger(__name__)

# Grace window before the scheduled interval during which a fetch is still allowed.
# Prevents spurious skips when the scheduler wakes up a few seconds early.
_REAL_GRACE_S  = 300   # 5 min before interval → allow fetch
_VIRTUAL_MIN_S = 60    # VATSIM: allow at most once per minute


def _fetch_is_due(cfg: AppConfig) -> tuple[bool, str]:
    """
    Returns (should_fetch, reason).

    Rules:
    - No snapshot for this airport            → always fetch (new airport or first run)
    - source=real, age < interval - 5min      → skip (still fresh)
    - source=virtual, age < 60s              → skip (spam guard)
    - Otherwise                               → fetch
    """
    age = snapshot_age_seconds(cfg.airport_iata)
    if age is None:
        return True, "no snapshot for this airport"

    source = (cfg.source or "real").strip().lower()
    if source == "real":
        threshold = max(60, cfg.refresh_seconds - _REAL_GRACE_S)
        if age < threshold:
            return False, f"snapshot is {int(age)}s old — due after {int(threshold)}s"
    else:
        if age < _VIRTUAL_MIN_S:
            return False, f"snapshot is {int(age)}s old — virtual minimum is {_VIRTUAL_MIN_S}s"

    return True, f"snapshot is {int(age)}s old — fetch due"


# ── History write (non-fatal) ──────────────────────────────────────────────────

def _write_history(flights: List[Flight], cfg: AppConfig) -> None:
    try:
        from localflight.storage.history import write_snapshot_to_history
        write_snapshot_to_history(flights, cfg)
    except Exception as exc:
        log.warning("History write failed (non-fatal): %s", exc)


def _prune_old_snapshots(cfg: AppConfig, *, keep_hours: int = 24) -> None:
    try:
        deleted = prune_snapshots(cfg.airport_iata, keep_hours=keep_hours)
        if deleted:
            log.info("Snapshot prune: deleted %d files for %s", deleted, cfg.airport_iata)
    except Exception as exc:
        log.warning("Snapshot prune failed (non-fatal): %s", exc)


# ── WebSocket broadcast (non-fatal) ───────────────────────────────────────────

def _broadcast_update(flights: List[Flight], cfg: AppConfig) -> None:
    """
    Notify all connected WebSocket clients that new data is available.
    Clients receive a push and re-fetch /api/fids and /api/radar themselves.
    Non-fatal — broadcast failure never stops the scheduler.
    """
    try:
        from localflight.ui.events import _utc_now, notify_clients

        notify_clients("snapshot_updated", {
            "airport_iata": cfg.airport_iata,
            "flight_count": len(flights),
            "source":       cfg.source,
            "updated_at":   _utc_now(),
        })
        log.debug("WS broadcast: snapshot_updated for %s (%d flights)", cfg.airport_iata, len(flights))
    except Exception as exc:
        log.debug("WS broadcast failed (non-fatal): %s", exc)


# ── Real schedule fetch ────────────────────────────────────────────────────────

def _local_schedule_provider() -> str:
    raw = os.getenv("LOCALFLIGHT_REAL_SCHEDULE_PROVIDER", "auto").strip().lower()
    if raw in {"auto", "aerodatabox", "aviationstack"}:
        return raw
    return "auto"


def _fetch_aviationstack_records_windowed(cfg: AppConfig, *, now: datetime) -> tuple[list[dict], dict]:
    from localflight.sources.web.aviationstack_client import (
        fetch_flights_windowed,
        record_fetch_cycle_stats,
    )

    raw_dep, dep_meta = fetch_flights_windowed(
        airport_iata=cfg.airport_iata,
        timezone_name=cfg.timezone,
        mode="departures",
        display_grace_minutes=cfg.display_grace_minutes,
        display_horizon_hours=cfg.display_horizon_hours,
        return_meta=True,
        now=now,
    )
    raw_arr, arr_meta = fetch_flights_windowed(
        airport_iata=cfg.airport_iata,
        timezone_name=cfg.timezone,
        mode="arrivals",
        display_grace_minutes=cfg.display_grace_minutes,
        display_horizon_hours=cfg.display_horizon_hours,
        return_meta=True,
        now=now,
    )
    record_fetch_cycle_stats(dep_meta, arr_meta)

    records = aviationstack_to_raw_records(raw_dep, airport_iata=cfg.airport_iata, mode="dep")
    records += aviationstack_to_raw_records(raw_arr, airport_iata=cfg.airport_iata, mode="arr")
    meta = {
        "provider": "aviationstack",
        "dep_raw": len(raw_dep.get("data") or []),
        "arr_raw": len(raw_arr.get("data") or []),
        "dep_pages": dep_meta.get("pages_fetched"),
        "arr_pages": arr_meta.get("pages_fetched"),
        "dep_extra": dep_meta.get("adaptive_extra_pages", 0),
        "arr_extra": arr_meta.get("adaptive_extra_pages", 0),
    }
    return records, meta


def _fetch_aviationstack(cfg: AppConfig) -> List[Flight]:
    from localflight.sources.web.aviationstack_client import (
        fetch_relay_schedule_records,
        _has_enabled_byok_key,
        _relay_uses_shared_schedule,
    )

    airport_iata = cfg.airport_iata
    airport_icao = cfg.airport_icao
    if _relay_uses_shared_schedule(cfg.source):
        records, _relay_meta = fetch_relay_schedule_records(
            airport_iata=airport_iata,
            timezone_name=cfg.timezone,
            display_grace_minutes=cfg.display_grace_minutes,
            display_horizon_hours=cfg.display_horizon_hours,
            refresh_seconds=cfg.refresh_seconds,
            timeout_s=60,
            return_meta=True,
        )
        flights = normalize_flights(
            records,
            airport_iata=airport_iata,
            airport_icao=airport_icao,
            source_name=str(_relay_meta.get("provider") or "aviationstack"),
        )
        log.info(
            "AviationStack relay snapshot: %s canonical records -> %d flights (%s, provider=%s, pages=%s, adaptive_extra=%s)",
            len(records),
            len(flights),
            _relay_meta.get("cache_state") or "unknown",
            _relay_meta.get("provider") or "aviationstack",
            _relay_meta.get("pages_fetched"),
            _relay_meta.get("adaptive_extra_pages", 0),
        )
        return _dedupe_identical_flights(flights)

    now = datetime.now(timezone.utc)
    provider_choice = _local_schedule_provider()

    if provider_choice in {"auto", "aerodatabox"}:
        from localflight.sources.web.aerodatabox_client import (
            AeroDataBoxBudgetExceeded,
            AeroDataBoxError,
            fetch_schedule_records,
            has_enabled_key as aerodatabox_has_enabled_key,
        )
        from localflight.sources.web.schedule_fusion import (
            merge_schedule_records,
            schedule_records_need_fill,
        )

        if aerodatabox_has_enabled_key():
            try:
                primary_records, aero_meta = fetch_schedule_records(
                    airport_iata=airport_iata,
                    airport_icao=airport_icao,
                    timezone_name=cfg.timezone,
                    display_grace_minutes=cfg.display_grace_minutes,
                    display_horizon_hours=cfg.display_horizon_hours,
                    timeout_s=25,
                    now=now,
                    return_meta=True,
                )
            except (AeroDataBoxBudgetExceeded, AeroDataBoxError) as exc:
                if provider_choice == "aerodatabox" or not _has_enabled_byok_key():
                    raise
                log.warning("AeroDataBox primary unavailable; falling back to AviationStack: %s", exc)
            else:
                records = primary_records
                source_name = "aerodatabox"
                fill_meta: dict = {}
                if (
                    provider_choice == "auto"
                    and _has_enabled_byok_key()
                    and schedule_records_need_fill(primary_records)
                ):
                    try:
                        fill_records, fill_fetch_meta = _fetch_aviationstack_records_windowed(cfg, now=now)
                        records, fill_meta = merge_schedule_records(
                            primary_records,
                            fill_records,
                            primary_provider="aerodatabox",
                            fill_provider="aviationstack",
                        )
                        source_name = "aerodatabox+aviationstack"
                        fill_meta["aviationstack_fetch"] = fill_fetch_meta
                    except Exception as exc:
                        log.warning("AviationStack fill unavailable after AeroDataBox primary: %s", exc)

                flights = normalize_flights(
                    records,
                    airport_iata=airport_iata,
                    airport_icao=airport_icao,
                    source_name=source_name,
                )
                log.info(
                    "Real schedule %s: aero_records=%d normalized=%d units=%s fill=%s",
                    source_name,
                    len(primary_records),
                    len(flights),
                    aero_meta.get("units_spent"),
                    fill_meta.get("provider_record_counts", {}),
                )
                return _dedupe_identical_flights(flights)
        elif provider_choice == "aerodatabox":
            raise RuntimeError("LOCALFLIGHT_REAL_SCHEDULE_PROVIDER=aerodatabox but AERODATABOX_API_KEY is not enabled")

    records, fetch_meta = _fetch_aviationstack_records_windowed(cfg, now=now)

    flights = normalize_flights(
        records,
        airport_iata=airport_iata,
        airport_icao=airport_icao,
        source_name="aviationstack",
    )
    log.info(
        "AviationStack fair-fetch: dep raw=%d arr raw=%d normalized=%d dep_pages=%s arr_pages=%s dep_extra=%s arr_extra=%s",
        fetch_meta.get("dep_raw"),
        fetch_meta.get("arr_raw"),
        len(flights),
        fetch_meta.get("dep_pages"),
        fetch_meta.get("arr_pages"),
        fetch_meta.get("dep_extra", 0),
        fetch_meta.get("arr_extra", 0),
    )
    return _dedupe_identical_flights(flights)


def _flight_identity_signature(flight: Flight) -> tuple[str, str, str, str, str, str, str]:
    def _code(ref) -> str:
        if not ref:
            return ""
        return (ref.iata or ref.icao or "").upper()

    def _stamp(value: Optional[datetime]) -> str:
        if not value:
            return ""
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    return (
        flight.direction.value,
        (flight.callsign or "").upper(),
        _code(flight.origin),
        _code(flight.destination),
        _stamp(flight.times.scheduled),
        _stamp(flight.times.estimated),
        _stamp(flight.times.actual),
    )


def _flight_detail_score(flight: Flight) -> tuple[int, int, int, int, int, str]:
    return (
        1 if flight.times.actual else 0,
        1 if flight.times.estimated else 0,
        1 if flight.gate else 0,
        1 if flight.terminal else 0,
        1 if flight.aircraft_type else 0,
        flight.callsign,
    )


def _dedupe_identical_flights(flights: List[Flight]) -> List[Flight]:
    grouped: dict[tuple[str, str, str, str, str, str, str], List[Flight]] = {}
    for flight in flights:
        grouped.setdefault(_flight_identity_signature(flight), []).append(flight)

    deduped: List[Flight] = []
    for items in grouped.values():
        if len(items) == 1:
            deduped.append(items[0])
            continue
        deduped.append(sorted(items, key=_flight_detail_score, reverse=True)[0])

    deduped.sort(
        key=lambda item: (
            item.times.actual
            or item.times.estimated
            or item.times.scheduled
            or datetime.min.replace(tzinfo=timezone.utc)
        )
    )
    return deduped


# ── Position enrichment ────────────────────────────────────────────────────────

def _enrich_with_adsbexchange(
    flights: List[Flight],
    cfg: AppConfig,
) -> Optional[List[Flight]]:
    try:
        from localflight.sources.web.adsbexchange_client import (
            enrich_flights_with_adsbexchange,
            is_available,
        )
        from localflight.core.airports import lookup_airport

        if not is_available():
            log.debug("ADS-B Exchange: RAPIDAPI_KEY not set — skipping")
            return None

        airport = lookup_airport(iata=cfg.airport_iata, icao=cfg.airport_icao)
        if not airport or airport.lat is None or airport.lon is None:
            log.warning("ADS-B Exchange: no coordinates for %s", cfg.airport_iata)
            return None

        return enrich_flights_with_adsbexchange(
            flights,
            lat=airport.lat,
            lon=airport.lon,
            radius_nm=50.0,
        )
    except Exception as exc:
        log.warning("ADS-B Exchange enrichment failed (non-fatal): %s", exc)
        return None


def _enrich_with_opensky(
    flights: List[Flight],
    cfg: AppConfig,
) -> Optional[List[Flight]]:
    try:
        from localflight.decode.opensky import enrich_flights_with_opensky
        from localflight.core.airports import lookup_airport
        from localflight.sources.web.opensky_radar import (
            bounding_box, _get_auth, OPENSKY_BASE_URL,
        )
        import requests

        airport = lookup_airport(iata=cfg.airport_iata, icao=cfg.airport_icao)
        if not airport or airport.lat is None or airport.lon is None:
            return None

        lamin, lomin, lamax, lomax = bounding_box(airport.lat, airport.lon, radius_nm=50.0)

        r = requests.get(
            OPENSKY_BASE_URL,
            params={
                "lamin": round(lamin, 6),
                "lomin": round(lomin, 6),
                "lamax": round(lamax, 6),
                "lomax": round(lomax, 6),
            },
            auth=_get_auth(),
            timeout=20,
            headers={"User-Agent": "local-flight/1.0 (+https://localflight.invalid)"},
        )

        if r.status_code == 429:
            log.warning("OpenSky: rate limit hit")
            return None
        if r.status_code >= 400:
            log.warning("OpenSky: HTTP %s", r.status_code)
            return None

        vectors = r.json().get("states") or []
        log.info("OpenSky fallback: %d state vectors", len(vectors))
        return enrich_flights_with_opensky(flights, vectors)

    except Exception as exc:
        log.warning("OpenSky enrichment failed (non-fatal): %s", exc)
        return None


def _fetch_real(cfg: AppConfig) -> List[Flight]:
    flights = _fetch_aviationstack(cfg)

    enriched = _enrich_with_adsbexchange(flights, cfg)
    if enriched is not None:
        log.info("Position enrichment: ADS-B Exchange")
        flights = enriched
    else:
        log.info("Position enrichment: falling back to OpenSky")
        opensky_enriched = _enrich_with_opensky(flights, cfg)
        if opensky_enriched is not None:
            flights = opensky_enriched
        else:
            log.info("Position enrichment: no source available — schedule data only")

    return dedupe_codeshares(
        flights,
        preferred_airline_iata=["LX", "WK", "OS", "LH"],
    )


# ── VATSIM (virtual) ───────────────────────────────────────────────────────────

def _fetch_vatsim(cfg: AppConfig) -> List[Flight]:
    from localflight.sources.web.vatsim_client import fetch_vatsim_data_cached, vatsim_to_raw_records
    from localflight.core.models import FlightPosition

    payload = fetch_vatsim_data_cached()
    pilots  = payload.get("pilots") or []

    records = vatsim_to_raw_records(payload, airport_icao=cfg.airport_icao, mode="both")
    flights = normalize_flights(
        records,
        airport_iata=cfg.airport_iata,
        airport_icao=cfg.airport_icao,
        source_name="vatsim",
    )

    pilot_lookup = {
        (p.get("callsign") or "").strip().upper(): p
        for p in pilots if p.get("callsign")
    }

    enriched: List[Flight] = []
    for f in flights:
        pilot = pilot_lookup.get(f.callsign)
        if not pilot:
            enriched.append(f)
            continue

        alt_ft = float(pilot.get("altitude")    or 0)
        gs_kts = float(pilot.get("groundspeed") or 0)
        hdg    = pilot.get("heading")

        position = FlightPosition(
            lat=pilot.get("latitude"),
            lon=pilot.get("longitude"),
            altitude_baro=alt_ft * 0.3048 if alt_ft else None,
            altitude_geo=None,
            heading=float(hdg) if hdg is not None else None,
            speed_ms=gs_kts * 0.514444 if gs_kts else None,
            vertical_rate=None,
            on_ground=(alt_ft < 100 and gs_kts < 50),
            icao24=None,
            squawk=None,
            last_contact=None,
        )

        enriched.append(Flight(
            direction=f.direction,
            airport=f.airport,
            callsign=f.callsign,
            airline=f.airline,
            flight_number=f.flight_number,
            codeshares=f.codeshares,
            origin=f.origin,
            destination=f.destination,
            aircraft_type=f.aircraft_type,
            aircraft_registration=f.aircraft_registration,
            gate=f.gate,
            terminal=f.terminal,
            stand=f.stand,
            status=f.status,
            times=f.times,
            delay_minutes=f.delay_minutes,
            flight_rules=f.flight_rules,
            planned_route=f.planned_route,
            planned_altitude=f.planned_altitude,
            planned_departure=f.planned_departure,
            planned_arrival=f.planned_arrival,
            planned_enroute_minutes=f.planned_enroute_minutes,
            cruise_tas=f.cruise_tas,
            alternate_icao=f.alternate_icao,
            assigned_transponder=f.assigned_transponder,
            position=position,
            source=f.source,
            enriched_by="vatsim_position",
            updated_at=f.updated_at,
        ))

    return dedupe_codeshares(enriched)


# ── Mock / offline (dev only) ──────────────────────────────────────────────────

def _fetch_mock(cfg: AppConfig) -> List[Flight]:
    from localflight.sources.web.aviationstack_mock import load_sample_payload

    payload = load_sample_payload()
    records = aviationstack_to_raw_records(payload, airport_iata=cfg.airport_iata, mode="both")
    flights = normalize_flights(
        records,
        airport_iata=cfg.airport_iata,
        airport_icao=cfg.airport_icao,
        source_name="mock",
    )
    return dedupe_codeshares(flights, preferred_airline_iata=["LX", "WK", "OS", "LH"])


# ── Public job functions ───────────────────────────────────────────────────────

def run_snapshot_job(cfg: AppConfig) -> List[Flight]:
    """
    Main job — fetch, enrich, save, broadcast.
    Skips the fetch if the existing snapshot is still fresh (see _fetch_is_due).
    This means any restart triggered by a config save, profile load, or manual
    button press will not burn an API call if the data is already current.
    """
    due, reason = _fetch_is_due(cfg)
    if not due:
        log.info("Fetch skipped — %s", reason)
        return []

    log.info("Fetch due — %s", reason)
    source = (cfg.source or "real").strip().lower()

    if source == "virtual":
        flights = _fetch_vatsim(cfg)
    else:
        flights = _fetch_real(cfg)

    # Save JSON snapshot
    save_snapshot(cfg.airport_iata, flights, at=datetime.now(timezone.utc))

    # Prune old snapshot files (non-fatal)
    _prune_old_snapshots(cfg)

    # Write to SQLite history DB (non-fatal)
    _write_history(flights, cfg)

    # Broadcast to WebSocket clients (non-fatal)
    _broadcast_update(flights, cfg)

    log.info(
        "Snapshot complete: %d flights | %s | source=%s",
        len(flights), cfg.airport_iata, source,
    )

    return flights


def run_mock_snapshot_job(
    *,
    airport_iata: str,
    airport_icao: str,
    mode: str = "both",
) -> List[Flight]:
    cfg     = AppConfig(airport_iata=airport_iata, airport_icao=airport_icao)
    flights = _fetch_mock(cfg)
    save_snapshot(airport_iata, flights, at=datetime.now(timezone.utc))
    _prune_old_snapshots(cfg)
    _write_history(flights, cfg)
    return flights


# Backwards-compat alias
run_aviationstack_snapshot_job = run_mock_snapshot_job
