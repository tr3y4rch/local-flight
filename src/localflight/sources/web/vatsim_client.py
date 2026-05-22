"""
localflight/sources/web/vatsim_client.py

Fetches live VATSIM traffic from the public Data API v3 and normalises
it into the flat record format consumed by decode/normalize.py.

Privacy rule:
  Local Flight intentionally keeps VATSIM flight/network information only.
  Do not persist or expose pilot/controller names, CIDs, account IDs, or other
  person-identifying fields from the VATSIM feed.

VATSIM Data v3 endpoint (no auth required, ~15s update cycle):
  https://data.vatsim.net/v3/vatsim-data.json

Pilot record shape (relevant fields):
  {
    "callsign": "SWR105",
    "flight_plan": {
      "aircraft_icao": "A320",       # may include equipment suffix: "A320/G"
      "aircraft_faa":  "A320/G",     # FAA format, may have heavy prefix: "H/B748/L"
      "departure": "LSZH",
      "arrival": "EGLL",
      "deptime": "1030",             # planned dep time HHMM UTC
      "enroute_time": "0135",        # planned flight time HHMM
    },
    "latitude": 47.45,
    "longitude": 8.55,
    "altitude": 35000,               # feet
    "groundspeed": 460,              # knots
  }

Aircraft type field notes:
  VATSIM pilots file aircraft type in several formats:
    - Clean:       "A320", "B738", "C172"
    - With suffix: "A320/G", "B738/L", "C172/A"  (equipment codes)
    - With prefix: "H/B748/L"  (H=Heavy, then type, then equipment)
    - FAA format:  "B737/G"
  We extract the ICAO type code by stripping prefixes (single char before /)
  and suffixes (equipment codes after /).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger(__name__)

VATSIM_DATA_URL = "https://data.vatsim.net/v3/vatsim-data.json"
_TIMEOUT_S = 15
_CACHE_TTL_S = 60
_CACHE: Dict[str, Any] = {"fetched_at": None, "payload": None, "fetch_func_id": None}

_GS_AIRBORNE  = 80    # knots above which we consider aircraft airborne
_ALT_AIRBORNE = 3000  # feet above which we consider aircraft airborne

# Known wake turbulence / equipment prefix codes to strip
_SINGLE_CHAR_PREFIXES = {"H", "S", "L", "M", "J"}  # Heavy, Super, Light, Medium, Jumbo

# Valid ICAO aircraft type pattern: 2-4 alphanumeric chars
_ICAO_TYPE_RE = re.compile(r'^[A-Z0-9]{2,4}$')


class VatsimError(RuntimeError):
    """Raised for VATSIM client errors (network, unexpected payload)."""


def fetch_vatsim_data(*, timeout_s: int = _TIMEOUT_S) -> Dict[str, Any]:
    """
    Fetch the raw VATSIM v3 JSON payload.
    Returns the full dict (keys: general, pilots, controllers, atis, …).
    Raises VatsimError on any failure.
    """
    try:
        r = requests.get(
            VATSIM_DATA_URL,
            timeout=timeout_s,
            headers={"User-Agent": "local-flight/1.0 (+https://beacontools.cc/local-flight)"},
        )
    except requests.RequestException as exc:
        raise VatsimError(f"VATSIM request failed: {exc}") from exc

    if r.status_code >= 400:
        raise VatsimError(f"VATSIM HTTP {r.status_code}")

    try:
        data = r.json()
    except Exception as exc:
        raise VatsimError(f"VATSIM response not valid JSON: {exc}") from exc

    if not isinstance(data, dict) or "pilots" not in data:
        raise VatsimError("Unexpected VATSIM payload (missing 'pilots')")

    log.debug("VATSIM: fetched %d pilots", len(data.get("pilots") or []))
    return data


def fetch_vatsim_data_cached(
    *,
    timeout_s: int = _TIMEOUT_S,
    ttl_s: int = _CACHE_TTL_S,
) -> Dict[str, Any]:
    """
    Fetch VATSIM data with a short process-local cache.

    Matrix previews, physical boards, radar, and VATSIM weather can all poll at
    human UI rates. The public VATSIM data feed already updates on its own
    cadence, so sharing one payload per minute keeps Local Flight lively without
    turning every panel/page into its own upstream request.
    """
    now = datetime.now(timezone.utc)
    fetched_at = _CACHE.get("fetched_at")
    payload = _CACHE.get("payload")
    fetch_func_id = id(fetch_vatsim_data)
    if isinstance(payload, dict) and isinstance(fetched_at, datetime):
        age = (now - fetched_at).total_seconds()
        if age < max(1, int(ttl_s)) and _CACHE.get("fetch_func_id") == fetch_func_id:
            return payload

    try:
        payload = fetch_vatsim_data(timeout_s=timeout_s)
    except TypeError:
        payload = fetch_vatsim_data()
    _CACHE["payload"] = payload
    _CACHE["fetched_at"] = now
    _CACHE["fetch_func_id"] = fetch_func_id
    return payload


def vatsim_metar_for_airport(payload: Dict[str, Any], *, airport_icao: str) -> Optional[str]:
    """
    Return only the raw METAR text embedded in VATSIM ATIS for an airport.

    This intentionally drops ATC names, CIDs, frequencies, and free-text remarks
    that are not part of the METAR line.
    """
    airport = (airport_icao or "").strip().upper()
    if not airport:
        return None

    for atis in payload.get("atis") or []:
        if not isinstance(atis, dict):
            continue
        callsign = str(atis.get("callsign") or "").strip().upper()
        if callsign and not callsign.startswith(airport):
            continue
        raw = _extract_metar_from_atis_text(atis.get("text_atis"), airport)
        if raw:
            return raw
    return None


def _extract_metar_from_atis_text(value: Any, airport_icao: str) -> Optional[str]:
    if value is None:
        return None
    lines = value if isinstance(value, list) else str(value).splitlines()
    airport = airport_icao.upper()

    for item in lines:
        text = re.sub(r"\s+", " ", str(item or "").strip())
        if not text:
            continue
        upper = text.upper()
        if "METAR " in upper:
            idx = upper.find("METAR ")
            candidate = text[idx:].strip()
        elif upper.startswith(f"{airport} "):
            candidate = text.strip()
        else:
            continue

        candidate = candidate.replace("=", "").strip()
        if airport in candidate.upper() and re.search(r"\b\d{6}Z\b", candidate.upper()):
            return candidate
    return None


def _extract_aircraft_type(raw: Optional[str]) -> Optional[str]:
    """
    Extract a clean ICAO aircraft type code from a VATSIM aircraft string.

    Handles all common VATSIM filing formats:
      "A320"       -> "A320"
      "A320/G"     -> "A320"   (strip equipment suffix)
      "H/B748/L"   -> "B748"   (strip heavy prefix + equipment suffix)
      "B737/G"     -> "B737"
      "C172/A"     -> "C172"
      "ZZZZ"       -> None     (placeholder)
      "VFR"        -> None     (VFR flight, no type)
      ""           -> None
    """
    if not raw:
        return None

    raw = raw.strip().upper()
    if not raw:
        return None

    # Split on "/" — handles "H/B748/L", "A320/G", "A320"
    parts = [p.strip() for p in raw.split("/") if p.strip()]

    # Filter out single-char prefix codes (H, S, L, M, J)
    # and equipment suffix codes (single char like G, L, A, B, W, Z)
    type_candidates = [p for p in parts if len(p) > 1]

    if not type_candidates:
        return None

    # Take the first multi-char part — that's the type code
    candidate = type_candidates[0]

    # Validate against ICAO type pattern
    if not _ICAO_TYPE_RE.match(candidate):
        return None

    # Filter out known placeholder values
    if candidate in {"ZZZZ", "UNKN", "NONE", "NULL", "VFR", "IFR"}:
        return None

    return candidate


def _parse_deptime(deptime: Optional[str], *, base: datetime) -> Optional[str]:
    """
    VATSIM deptime is "HHMM" UTC.
    Returns ISO-8601 string so normalize.py can parse it like any other time.
    """
    if not deptime:
        return None
    t = deptime.strip().zfill(4)
    try:
        hh, mm = int(t[:2]), int(t[2:4])
        dt = base.replace(hour=hh, minute=mm, second=0, microsecond=0, tzinfo=timezone.utc)
        return dt.isoformat()
    except (ValueError, IndexError):
        return None


def _parse_enroute(enroute: Optional[str]) -> Optional[timedelta]:
    """VATSIM enroute_time is "HHMM". Returns timedelta or None."""
    if not enroute:
        return None
    t = enroute.strip().zfill(4)
    try:
        hh, mm = int(t[:2]), int(t[2:4])
        return timedelta(hours=hh, minutes=mm)
    except (ValueError, IndexError):
        return None


def _enroute_minutes(value: Optional[timedelta]) -> Optional[int]:
    if value is None:
        return None
    return int(value.total_seconds() // 60)


def _clean_fp_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _infer_status(*, direction: str, groundspeed: int, altitude: int) -> str:
    """Crude status from position data. VATSIM has no flight_status field."""
    airborne = groundspeed > _GS_AIRBORNE or altitude > _ALT_AIRBORNE
    if airborne:
        return "departed" if direction == "DEP" else "scheduled"
    return "scheduled"


def _airline_icao_from_callsign(callsign: str) -> Optional[str]:
    """First 3 alpha chars = airline ICAO. e.g. SWR105 -> SWR."""
    prefix = callsign[:3]
    return prefix if len(prefix) == 3 and prefix.isalpha() else None


def vatsim_to_raw_records(
    payload: Dict[str, Any],
    *,
    airport_icao: str,
    mode: str = "both",  # "dep" | "arr" | "both"
) -> List[dict]:
    """
    Convert a VATSIM v3 payload into the flat record format expected by
    decode/normalize.py::normalize_flights().

    Only pilots with a filed flight plan departing or arriving at
    airport_icao are included.

    Differences vs AviationStack:
      - ICAO codes only for dep/arr airports (no IATA)
      - Times are planned only — no estimated or actual splits
      - Status is inferred from groundspeed + altitude
      - No gate / terminal / stand data
      - Airline name not available (ICAO prefix inferred from callsign)
    """
    airport = airport_icao.upper().strip()
    mode    = mode.lower().strip()

    pilots: List[Dict[str, Any]] = payload.get("pilots") or []
    now = datetime.now(timezone.utc)
    out: List[dict] = []

    type_found = 0
    type_missing = 0

    for pilot in pilots:
        fp = pilot.get("flight_plan") or {}
        if not fp:
            continue  # no flight plan filed

        dep_icao = (fp.get("departure") or "").strip().upper()
        arr_icao = (fp.get("arrival")   or "").strip().upper()

        is_dep = dep_icao == airport
        is_arr = arr_icao == airport

        if not is_dep and not is_arr:
            continue
        if mode == "dep" and not is_dep:
            continue
        if mode == "arr" and not is_arr:
            continue

        direction = "DEP" if is_dep else "ARR"

        callsign = (pilot.get("callsign") or "").strip().upper()
        if not callsign:
            continue

        gs  = int(pilot.get("groundspeed") or 0)
        alt = int(pilot.get("altitude")    or 0)

        # ── Aircraft type extraction ───────────────────────────────────────────
        # Try aircraft_icao first (cleaner), fall back to aircraft_faa
        aircraft_type = (
            _extract_aircraft_type(fp.get("aircraft_icao")) or
            _extract_aircraft_type(fp.get("aircraft_faa"))
        )

        if aircraft_type:
            type_found += 1
        else:
            type_missing += 1
            log.debug(
                "VATSIM: no aircraft type for %s (icao=%r faa=%r)",
                callsign,
                fp.get("aircraft_icao"),
                fp.get("aircraft_faa"),
            )

        airline_icao = _airline_icao_from_callsign(callsign)
        dep_time_iso = _parse_deptime(fp.get("deptime"), base=now)

        arr_time_iso: Optional[str] = None
        enroute_td = _parse_enroute(fp.get("enroute_time"))
        if dep_time_iso and enroute_td:
            try:
                arr_dt = datetime.fromisoformat(dep_time_iso) + enroute_td
                arr_time_iso = arr_dt.isoformat()
            except Exception:
                pass

        scheduled = dep_time_iso if direction == "DEP" else arr_time_iso

        out.append({
            "callsign":         callsign,
            "direction":        direction,
            "status":           _infer_status(direction=direction, groundspeed=gs, altitude=alt),
            "scheduled":        scheduled,
            "estimated":        None,
            "actual":           None,
            "airline_name":     None,
            "airline_iata":     None,
            "airline_icao":     airline_icao,
            "flight_number":    callsign,
            "origin_iata":      None,
            "origin_icao":      dep_icao or None,
            "destination_iata": None,
            "destination_icao": arr_icao or None,
            "aircraft_type":    aircraft_type,
            "gate":             None,
            "stand":            None,
            "terminal":         None,
            "delay_minutes":    None,
            "flight_rules":     _clean_fp_text(fp.get("flight_rules")),
            "planned_route":    _clean_fp_text(fp.get("route")),
            "planned_altitude": _clean_fp_text(fp.get("altitude")),
            "planned_departure": dep_time_iso,
            "planned_arrival":   arr_time_iso,
            "planned_enroute_minutes": _enroute_minutes(enroute_td),
            "cruise_tas":       _clean_fp_text(fp.get("cruise_tas")),
            "alternate_icao":    _clean_fp_text(fp.get("alternate")),
            "assigned_transponder": _clean_fp_text(fp.get("assigned_transponder")) or _clean_fp_text(pilot.get("transponder")),
        })

    log.info(
        "vatsim_to_raw_records: %d pilots -> %d records for %s (mode=%s) "
        "aircraft_type: %d found / %d missing",
        len(pilots), len(out), airport, mode, type_found, type_missing,
    )
    return out
