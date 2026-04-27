"""
localflight/sources/web/adsbexchange_client.py

ADS-B Exchange data source via RapidAPI.

Endpoint:
  GET https://adsbexchange-com1.p.rapidapi.com/v2/lat/{lat}/lon/{lon}/dist/{nm}/

Returns all aircraft within `dist` nautical miles of a lat/lon point.
Subscription: 10,000 calls/month (configurable via LOCALFLIGHT_RAPIDAPI_MONTHLY_LIMIT).

Environment variable required:
  RAPIDAPI_KEY=your_key_here

Notable fields vs OpenSky:
  - `t`  aircraft type (e.g. "A321") — not available on AviationStack free tier
  - `r`  registration (e.g. "HB-JBA")
  - `flight` callsign (trimmed)
  - `alt_baro` barometric altitude in feet
  - `alt_geom` geometric altitude in feet
  - `gs` ground speed in knots
  - `track` true heading degrees
  - `baro_rate` vertical rate ft/min
  - `squawk`
  - `hex` ICAO 24-bit address
  - `lat`, `lon` position
"""
from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger(__name__)

ADSBX_BASE_URL            = "https://adsbexchange-com1.p.rapidapi.com/v2"
_TIMEOUT_S                = 15
_DEFAULT_MONTHLY_LIMIT    = 10_000


class ADSBExchangeError(RuntimeError):
    pass


class ADSBExchangeBudgetExceeded(ADSBExchangeError):
    pass


def _get_api_key() -> str:
    key = os.getenv("RAPIDAPI_KEY", "").strip()
    if not key:
        raise ADSBExchangeError("RAPIDAPI_KEY not set in environment")
    return key


def _get_monthly_limit() -> int:
    try:
        return int(os.getenv("LOCALFLIGHT_RAPIDAPI_MONTHLY_LIMIT", str(_DEFAULT_MONTHLY_LIMIT)))
    except (ValueError, TypeError):
        return _DEFAULT_MONTHLY_LIMIT


# ── RapidAPI usage counter ─────────────────────────────────────────────────────

def _usage_path() -> Path:
    from localflight.storage.config import config_path
    return config_path().parent / "api_usage.json"


def _load_usage() -> Dict[str, Any]:
    p = _usage_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_usage(data: Dict[str, Any]) -> None:
    try:
        _usage_path().write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _check_and_increment_budget(n_calls: int = 1) -> None:
    usage      = _load_usage()
    month      = _month_key()
    limit      = _get_monthly_limit()
    month_data = usage.setdefault("rapidapi", {})
    current    = month_data.get(month, 0)

    if current + n_calls > limit:
        raise ADSBExchangeBudgetExceeded(
            f"RapidAPI monthly budget exceeded: {current}/{limit} calls used "
            f"this month ({month}). Set LOCALFLIGHT_RAPIDAPI_MONTHLY_LIMIT=N to increase."
        )

    month_data[month] = current + n_calls
    for old in sorted(month_data.keys(), reverse=True)[3:]:
        del month_data[old]
    _save_usage(usage)


def get_usage_stats() -> Dict[str, Any]:
    """Returns current RapidAPI usage stats. Safe to call anytime."""
    usage  = _load_usage()
    month  = _month_key()
    limit  = _get_monthly_limit()
    calls  = usage.get("rapidapi", {}).get(month, 0)
    return {
        "month":            month,
        "calls_this_month": calls,
        "monthly_limit":    limit,
        "remaining":        max(0, limit - calls),
        "budget_ok":        calls < limit,
        "available":        bool(os.getenv("RAPIDAPI_KEY", "").strip()),
    }


def fetch_aircraft(
    lat:       float,
    lon:       float,
    radius_nm: float = 50.0,
    timeout_s: int   = _TIMEOUT_S,
) -> List[Dict[str, Any]]:
    """
    Fetch all aircraft within radius_nm of (lat, lon) from ADS-B Exchange.
    Returns the raw aircraft list from the API.
    Raises ADSBExchangeError on failure.
    """
    # API takes integer nm — round up to nearest 5 for cleaner requests
    dist_nm = max(5, int(math.ceil(radius_nm / 5) * 5))

    _check_and_increment_budget(n_calls=1)

    url = f"{ADSBX_BASE_URL}/lat/{lat}/lon/{lon}/dist/{dist_nm}/"

    try:
        r = requests.get(
            url,
            headers={
                "X-RapidAPI-Key":  _get_api_key(),
                "X-RapidAPI-Host": "adsbexchange-com1.p.rapidapi.com",
            },
            timeout=timeout_s,
        )
    except requests.RequestException as exc:
        raise ADSBExchangeError(f"ADS-B Exchange request failed: {exc}") from exc

    if r.status_code == 429:
        raise ADSBExchangeError("ADS-B Exchange rate limit hit — check RapidAPI dashboard")
    if r.status_code == 403:
        raise ADSBExchangeError("ADS-B Exchange API key invalid or not subscribed")
    if r.status_code >= 400:
        raise ADSBExchangeError(f"ADS-B Exchange HTTP {r.status_code}")

    try:
        data = r.json()
    except Exception as exc:
        raise ADSBExchangeError(f"ADS-B Exchange response not valid JSON: {exc}") from exc

    aircraft = data.get("ac") or []
    log.info(
        "ADS-B Exchange: %d aircraft within %dnm of (%.4f, %.4f)",
        len(aircraft), dist_nm, lat, lon,
    )
    return aircraft


def aircraft_to_blips(
    aircraft:   List[Dict[str, Any]],
    center_lat: float,
    center_lon: float,
    radius_nm:  float = 50.0,
) -> List[Dict[str, Any]]:
    """
    Convert ADS-B Exchange aircraft list to radar blip dicts.
    Compatible with /api/radar response format.
    """
    blips: List[Dict[str, Any]] = []
    NM_PER_DEG = 60.0

    for ac in aircraft:
        lat = ac.get("lat")
        lon = ac.get("lon")
        if lat is None or lon is None:
            continue

        # Distance check (API already filters but double-check)
        dlat = (lat - center_lat) * NM_PER_DEG
        dlon = (lon - center_lon) * NM_PER_DEG * math.cos(math.radians(center_lat))
        dist = math.sqrt(dlat**2 + dlon**2)
        if dist > radius_nm:
            continue

        callsign = (ac.get("flight") or "").strip().upper() or ac.get("hex", "").upper()
        alt_baro = ac.get("alt_baro")
        gs_kts   = ac.get("gs")
        hdg      = ac.get("track")

        # alt_baro can be "ground" string
        on_ground = (alt_baro == "ground")
        alt_m     = None
        if not on_ground and alt_baro is not None:
            try:
                alt_m = float(alt_baro) * 0.3048
            except (ValueError, TypeError):
                alt_m = None

        blips.append({
            "callsign":      callsign,
            "lat":           float(lat),
            "lon":           float(lon),
            "altitude_m":    alt_m,
            "heading":       float(hdg)    if hdg    is not None else None,
            "speed_ms":      float(gs_kts) * 0.514444 if gs_kts is not None else None,
            "vertical_rate": float(ac["baro_rate"]) * 0.00508 if ac.get("baro_rate") else None,
            "on_ground":     on_ground,
            "icao24":        (ac.get("hex") or "").upper(),
            "squawk":        ac.get("squawk"),
            "aircraft_type": ac.get("t"),        # bonus — not in OpenSky
            "registration":  ac.get("r"),         # bonus — not in OpenSky
            "source":        "adsbexchange",
            "enriched":      True,
            "distance_nm":   round(dist, 1),
        })

    return blips


def enrich_flights_with_adsbexchange(
    flights:   List[Any],
    lat:       float,
    lon:       float,
    radius_nm: float = 50.0,
) -> List[Any]:
    """
    Enrich a list of Flight objects with ADS-B Exchange position data.
    Drop-in replacement for enrich_flights_with_opensky().

    Bonus: also backfills aircraft_type from ADS-B Exchange `t` field
    when AviationStack free tier left it empty.

    Matching priority:
      1. Exact callsign match
      2. Flight number as callsign
      3. ICAO hex address match
    """
    from localflight.core.models import Flight, FlightPosition
    from datetime import datetime, timezone

    try:
        aircraft = fetch_aircraft(lat=lat, lon=lon, radius_nm=radius_nm)
    except ADSBExchangeError as exc:
        log.warning("ADS-B Exchange enrichment skipped: %s", exc)
        return flights

    # Build lookup by callsign and hex
    by_callsign: Dict[str, Dict] = {}
    by_hex:      Dict[str, Dict] = {}

    for ac in aircraft:
        cs  = (ac.get("flight") or "").strip().upper()
        hx  = (ac.get("hex")    or "").strip().upper()
        if cs: by_callsign[cs] = ac
        if hx: by_hex[hx]      = ac

    enriched = []
    matched  = 0

    for flight in flights:
        # Match attempt
        ac = by_callsign.get(flight.callsign)
        if ac is None and flight.flight_number:
            fn = flight.flight_number.replace(" ", "").upper()
            ac = by_callsign.get(fn)
        if ac is None and flight.position and flight.position.icao24:
            ac = by_hex.get(flight.position.icao24.upper())

        if ac is None:
            enriched.append(flight)
            continue

        matched += 1

        alt_baro  = ac.get("alt_baro")
        gs_kts    = ac.get("gs")
        on_ground = (alt_baro == "ground")
        alt_m     = None
        if not on_ground and alt_baro is not None:
            try:
                alt_m = float(alt_baro) * 0.3048
            except (ValueError, TypeError):
                pass

        position = FlightPosition(
            lat=ac.get("lat"),
            lon=ac.get("lon"),
            altitude_baro=alt_m,
            altitude_geo=float(ac["alt_geom"]) * 0.3048 if ac.get("alt_geom") else None,
            heading=float(ac["track"])     if ac.get("track")     is not None else None,
            speed_ms=float(gs_kts) * 0.514444 if gs_kts is not None else None,
            vertical_rate=float(ac["baro_rate"]) * 0.00508 if ac.get("baro_rate") else None,
            on_ground=on_ground,
            icao24=(ac.get("hex") or "").upper(),
            squawk=ac.get("squawk"),
            last_contact=datetime.now(timezone.utc),
        )

        # Backfill aircraft_type if AviationStack left it empty
        aircraft_type = flight.aircraft_type or ac.get("t") or None

        enriched.append(Flight(
            direction=flight.direction,
            airport=flight.airport,
            callsign=flight.callsign,
            airline=flight.airline,
            flight_number=flight.flight_number,
            origin=flight.origin,
            destination=flight.destination,
            aircraft_type=aircraft_type,
            gate=flight.gate,
            terminal=flight.terminal,
            stand=flight.stand,
            status=flight.status,
            times=flight.times,
            delay_minutes=flight.delay_minutes,
            position=position,
            source=flight.source,
            enriched_by="adsbexchange",
            updated_at=flight.updated_at,
        ))

    log.info(
        "ADS-B Exchange enrichment: %d/%d flights matched",
        matched, len(flights),
    )
    return enriched


def is_available() -> bool:
    """Quick check — returns True if API key is set."""
    return bool(os.getenv("RAPIDAPI_KEY", "").strip())