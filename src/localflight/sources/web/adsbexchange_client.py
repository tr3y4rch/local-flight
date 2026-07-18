from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import requests
from localflight.core.aircraft import short_aircraft_type
from localflight.sources.web.relay_defaults import default_public_relay_url, relay_radar_url
from localflight.version import user_agent

log = logging.getLogger(__name__)

ADSBX_BASE_URL = "https://adsbexchange-com1.p.rapidapi.com/v2"
_TIMEOUT_S = 15
_DEFAULT_MONTHLY_LIMIT = 10_000
_DEFAULT_RELAY_LIMIT = 600


class ADSBExchangeError(RuntimeError):
    pass


class ADSBExchangeBudgetExceeded(ADSBExchangeError):
    pass


def _get_api_key() -> str:
    key = os.getenv("RAPIDAPI_KEY", "").strip()
    if not key:
        raise ADSBExchangeError("RAPIDAPI_KEY not set in environment")
    return key


def _get_relay_url() -> str:
    base = os.getenv("LOCALFLIGHT_ADSBX_RELAY_URL", "").strip()
    if base:
        return base.rstrip("/")
    return relay_radar_url(default_public_relay_url())


def _get_activation_token() -> str:
    try:
        from localflight.storage.install import get_activation_token

        return get_activation_token()
    except Exception:
        return ""


def _get_monthly_limit() -> int:
    try:
        return int(os.getenv("LOCALFLIGHT_RAPIDAPI_MONTHLY_LIMIT", str(_DEFAULT_MONTHLY_LIMIT)))
    except (ValueError, TypeError):
        return _DEFAULT_MONTHLY_LIMIT


def _get_relay_limit() -> int:
    try:
        return int(os.getenv("LOCALFLIGHT_RELAY_RADAR_MONTHLY_LIMIT", str(_DEFAULT_RELAY_LIMIT)))
    except (ValueError, TypeError):
        return _DEFAULT_RELAY_LIMIT


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


def _check_and_increment_budget(bucket: str, limit: int, n_calls: int = 1) -> None:
    usage = _load_usage()
    month = _month_key()
    month_data = usage.setdefault(bucket, {})
    current = int(month_data.get(month, 0) or 0)

    if current + n_calls > limit:
        raise ADSBExchangeBudgetExceeded(
            f"ADS-B monthly budget exceeded: {current}/{limit} calls used "
            f"this month ({month})."
        )

    month_data[month] = current + n_calls
    for old in sorted(month_data.keys(), reverse=True)[3:]:
        del month_data[old]
    _save_usage(usage)


def _sync_relay_quota_from_headers(headers: Any) -> None:
    used_str = headers.get("X-LF-Radar-Quota-Used") if headers else None
    limit_str = headers.get("X-LF-Radar-Quota-Limit") if headers else None
    if used_str is None:
        return
    try:
        used = int(used_str)
        usage = _load_usage()
        month = _month_key()
        usage.setdefault("rapidapi_relay", {})[month] = used
        if limit_str:
            usage.setdefault("rapidapi_relay_limits", {})[month] = int(limit_str)
        _save_usage(usage)
    except Exception:
        pass


def get_usage_stats() -> Dict[str, Any]:
    usage = _load_usage()
    month = _month_key()
    direct_available = bool(os.getenv("RAPIDAPI_KEY", "").strip())
    managed_available = bool(_get_activation_token())
    mode = "byok" if direct_available else ("managed_relay" if managed_available else "none")
    bucket = "rapidapi" if direct_available else "rapidapi_relay"
    limit_map_key = "rapidapi_relay_limits" if bucket == "rapidapi_relay" else ""

    limit = _get_monthly_limit() if bucket == "rapidapi" else int(usage.get(limit_map_key, {}).get(month, _get_relay_limit()) or _get_relay_limit())
    calls = int(usage.get(bucket, {}).get(month, 0) or 0)
    return {
        "month": month,
        "calls_this_month": calls,
        "monthly_limit": limit,
        "remaining": max(0, limit - calls),
        "budget_ok": calls < limit,
        "available": direct_available or managed_available,
        "mode": mode,
    }


def _fetch_direct(lat: float, lon: float, dist_nm: int, timeout_s: int) -> List[Dict[str, Any]]:
    _check_and_increment_budget("rapidapi", _get_monthly_limit(), n_calls=1)
    url = f"{ADSBX_BASE_URL}/lat/{lat}/lon/{lon}/dist/{dist_nm}/"
    try:
        r = requests.get(
            url,
            headers={
                "X-RapidAPI-Key": _get_api_key(),
                "X-RapidAPI-Host": "adsbexchange-com1.p.rapidapi.com",
            },
            timeout=timeout_s,
        )
    except requests.RequestException as exc:
        raise ADSBExchangeError(f"ADS-B Exchange request failed: {exc}") from exc

    if r.status_code == 429:
        raise ADSBExchangeError("ADS-B Exchange rate limit hit - check RapidAPI dashboard")
    if r.status_code == 403:
        raise ADSBExchangeError("ADS-B Exchange API key invalid or not subscribed")
    if r.status_code >= 400:
        raise ADSBExchangeError(f"ADS-B Exchange HTTP {r.status_code}")

    try:
        data = r.json()
    except Exception as exc:
        raise ADSBExchangeError(f"ADS-B Exchange response not valid JSON: {exc}") from exc
    return data.get("ac") or []


def _fetch_managed_relay(lat: float, lon: float, dist_nm: int, timeout_s: int) -> List[Dict[str, Any]]:
    from localflight.storage.install import get_install_id
    from localflight.sources.web.relay_heartbeat import relay_client_metadata

    params = {
        "install_id": get_install_id(),
        "lat": lat,
        "lon": lon,
        "radius_nm": dist_nm,
        "activation_token": _get_activation_token(),
    }
    params.update(relay_client_metadata())
    try:
        r = requests.get(
            _get_relay_url(),
            params=params,
            headers={"Accept": "application/json", "User-Agent": user_agent()},
            timeout=timeout_s,
        )
    except requests.RequestException as exc:
        raise ADSBExchangeError(f"Managed ADS-B relay request failed: {exc}") from exc

    if r.status_code == 429:
        raise ADSBExchangeBudgetExceeded("Managed ADS-B relay quota exceeded")
    if r.status_code >= 400:
        detail = f"Managed ADS-B relay HTTP {r.status_code}"
        try:
            payload = r.json()
            error = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(error, dict):
                detail += f" ({error.get('code')}): {error.get('info')}"
        except Exception:
            pass
        raise ADSBExchangeError(detail)

    _sync_relay_quota_from_headers(r.headers)
    try:
        data = r.json()
    except Exception as exc:
        raise ADSBExchangeError(f"Managed ADS-B relay response not valid JSON: {exc}") from exc
    return data.get("ac") or []


def fetch_aircraft(
    lat: float,
    lon: float,
    radius_nm: float = 50.0,
    timeout_s: int = _TIMEOUT_S,
) -> List[Dict[str, Any]]:
    dist_nm = max(5, int(math.ceil(radius_nm / 5) * 5))

    if os.getenv("RAPIDAPI_KEY", "").strip():
        aircraft = _fetch_direct(lat, lon, dist_nm, timeout_s)
    elif _get_activation_token():
        aircraft = _fetch_managed_relay(lat, lon, dist_nm, timeout_s)
    else:
        raise ADSBExchangeError("No ADS-B relay or RAPIDAPI_KEY configured")

    log.info(
        "ADS-B Exchange: %d aircraft within %dnm of (%.4f, %.4f)",
        len(aircraft),
        dist_nm,
        lat,
        lon,
    )
    return aircraft


def aircraft_to_blips(
    aircraft: List[Dict[str, Any]],
    center_lat: float,
    center_lon: float,
    radius_nm: float = 50.0,
) -> List[Dict[str, Any]]:
    from localflight.radar.normalize import adsbx_aircraft_to_blips

    return adsbx_aircraft_to_blips(
        aircraft=aircraft,
        center_lat=center_lat,
        center_lon=center_lon,
        radius_nm=radius_nm,
    )


def enrich_flights_with_adsbexchange(
    flights: List[Any],
    lat: float,
    lon: float,
    radius_nm: float = 50.0,
) -> List[Any]:
    from datetime import datetime as _dt

    from localflight.core.models import Flight, FlightPosition

    try:
        aircraft = fetch_aircraft(lat=lat, lon=lon, radius_nm=radius_nm)
    except ADSBExchangeError as exc:
        log.warning("ADS-B Exchange enrichment skipped: %s", exc)
        return flights

    by_callsign: Dict[str, Dict[str, Any]] = {}
    by_hex: Dict[str, Dict[str, Any]] = {}
    for ac in aircraft:
        cs = (ac.get("flight") or "").strip().upper()
        hx = (ac.get("hex") or "").strip().upper()
        if cs:
            by_callsign[cs] = ac
        if hx:
            by_hex[hx] = ac

    enriched = []
    matched = 0

    for flight in flights:
        ac = by_callsign.get(flight.callsign)
        if ac is None and flight.flight_number:
            ac = by_callsign.get(flight.flight_number.replace(" ", "").upper())
        if ac is None and flight.position and flight.position.icao24:
            ac = by_hex.get(flight.position.icao24.upper())
        if ac is None:
            enriched.append(flight)
            continue

        matched += 1

        alt_baro = ac.get("alt_baro")
        gs_kts = ac.get("gs")
        on_ground = alt_baro == "ground"
        alt_m = None
        if not on_ground and alt_baro is not None:
            try:
                alt_m = float(alt_baro) * 0.3048
            except (ValueError, TypeError):
                alt_m = None

        position = FlightPosition(
            lat=ac.get("lat"),
            lon=ac.get("lon"),
            altitude_baro=alt_m,
            altitude_geo=float(ac["alt_geom"]) * 0.3048 if ac.get("alt_geom") else None,
            heading=float(ac["track"]) if ac.get("track") is not None else None,
            speed_ms=float(gs_kts) * 0.514444 if gs_kts is not None else None,
            vertical_rate=float(ac["baro_rate"]) * 0.00508 if ac.get("baro_rate") else None,
            on_ground=on_ground,
            icao24=(ac.get("hex") or "").upper(),
            squawk=ac.get("squawk"),
            last_contact=_dt.now(timezone.utc),
        )

        aircraft_type = flight.aircraft_type or short_aircraft_type(ac.get("t")) or None
        aircraft_type_full = flight.aircraft_type_full
        registration = flight.aircraft_registration or ac.get("r") or None
        enriched.append(
            Flight(
                direction=flight.direction,
                airport=flight.airport,
                callsign=flight.callsign,
                airline=flight.airline,
                flight_number=flight.flight_number,
                codeshares=flight.codeshares,
                sold_as=flight.sold_as,
                marketing_airline_name=flight.marketing_airline_name,
                marketing_airline_iata=flight.marketing_airline_iata,
                marketing_airline_icao=flight.marketing_airline_icao,
                marketing_flight_number=flight.marketing_flight_number,
                operating_callsign=flight.operating_callsign,
                identity_source=flight.identity_source,
                provider_codeshare_status=flight.provider_codeshare_status,
                provider_movement_key=flight.provider_movement_key,
                identity_evidence=flight.identity_evidence,
                origin=flight.origin,
                destination=flight.destination,
                aircraft_type=aircraft_type,
                aircraft_type_full=aircraft_type_full,
                aircraft_registration=registration,
                gate=flight.gate,
                terminal=flight.terminal,
                stand=flight.stand,
                gate_source=flight.gate_source,
                terminal_source=flight.terminal_source,
                gate_confidence=flight.gate_confidence,
                terminal_confidence=flight.terminal_confidence,
                ops_location_notes=flight.ops_location_notes,
                status=flight.status,
                times=flight.times,
                delay_minutes=flight.delay_minutes,
                flight_rules=flight.flight_rules,
                planned_route=flight.planned_route,
                planned_altitude=flight.planned_altitude,
                planned_departure=flight.planned_departure,
                planned_arrival=flight.planned_arrival,
                planned_enroute_minutes=flight.planned_enroute_minutes,
                cruise_tas=flight.cruise_tas,
                alternate_icao=flight.alternate_icao,
                assigned_transponder=flight.assigned_transponder,
                position=position,
                source=flight.source,
                enriched_by="adsbexchange",
                updated_at=flight.updated_at,
            )
        )

    log.info("ADS-B Exchange enrichment: %d/%d flights matched", matched, len(flights))
    return enriched


def is_available() -> bool:
    return bool(os.getenv("RAPIDAPI_KEY", "").strip() or _get_activation_token())
