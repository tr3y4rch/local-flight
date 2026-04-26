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
from typing import List, Optional

from localflight.core.models import Flight
from localflight.decode.dedupe import dedupe_codeshares
from localflight.decode.mappings.aviationstack import aviationstack_to_raw_records
from localflight.decode.normalize import normalize_flights
from localflight.storage.config import AppConfig
from localflight.storage.flights_store import prune_snapshots, save_snapshot

log = logging.getLogger(__name__)


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


# ── AviationStack fetch ────────────────────────────────────────────────────────

def _fetch_aviationstack(cfg: AppConfig) -> List[Flight]:
    from localflight.sources.web.aviationstack_client import fetch_flights_once

    airport_iata = cfg.airport_iata
    airport_icao = cfg.airport_icao

    raw_dep = fetch_flights_once(airport_iata=airport_iata, mode="departures", limit=50)
    raw_arr = fetch_flights_once(airport_iata=airport_iata, mode="arrivals",   limit=50)

    records  = aviationstack_to_raw_records(raw_dep, airport_iata=airport_iata, mode="dep")
    records += aviationstack_to_raw_records(raw_arr, airport_iata=airport_iata, mode="arr")

    return normalize_flights(
        records,
        airport_iata=airport_iata,
        airport_icao=airport_icao,
        source_name="aviationstack",
    )


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
    from localflight.sources.web.vatsim_client import fetch_vatsim_data, vatsim_to_raw_records
    from localflight.core.models import FlightPosition

    payload = fetch_vatsim_data()
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
            origin=f.origin,
            destination=f.destination,
            aircraft_type=f.aircraft_type,
            gate=f.gate,
            terminal=f.terminal,
            stand=f.stand,
            status=f.status,
            times=f.times,
            delay_minutes=f.delay_minutes,
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
    """
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
