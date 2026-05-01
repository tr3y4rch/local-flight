from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _pick(*values: Optional[str]) -> Optional[str]:
    """Return the first non-empty string."""
    for v in values:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return None


def _s(v: Any) -> str:
    """Safe string conversion (never returns None)."""
    return "" if v is None else str(v)


def _parse_iso(dt: Optional[str]) -> Optional[datetime]:
    """
    Parse ISO-8601 string into timezone-aware datetime (UTC).
    Returns None if parsing fails.
    Accepts trailing 'Z'.
    """
    if not dt:
        return None
    try:
        d = datetime.fromisoformat(str(dt).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        return None


def _compute_delay_minutes(scheduled: Optional[str], estimated: Optional[str]) -> Optional[int]:
    """
    Compute delay in whole minutes using estimated - scheduled.
    Negative means earlier than scheduled.
    """
    s = _parse_iso(scheduled)
    e = _parse_iso(estimated)
    if not s or not e:
        return None
    delta = e - s
    return int(delta.total_seconds() // 60)


def _normalize_status(flight_status: Optional[str], *, direction: str) -> str:
    """
    Aviationstack commonly uses: scheduled, active, landed, cancelled, diverted, etc.

    Your normalize.py does:
        FlightStatus(status_raw.capitalize())
    So we must output strings that map cleanly to your enum values after capitalize():
        scheduled -> Scheduled
        boarding -> Boarding
        delayed -> Delayed
        departed -> Departed
        arrived -> Arrived
        cancelled -> Cancelled
        diverted -> Diverted
        unknown -> Unknown
    """
    if not flight_status:
        return "unknown"

    s = str(flight_status).strip().lower()

    direct = {
        "scheduled": "scheduled",
        "boarding": "boarding",
        "delayed": "delayed",
        "departed": "departed",
        "arrived": "arrived",
        "landed": "arrived",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "diverted": "diverted",
    }
    if s in direct:
        return direct[s]

    if s == "active":
        # "active" is ambiguous; interpret as "departed" (airborne/enroute).
        return "departed"

    if s in {"incident", "redirected"}:
        return "diverted"

    return "unknown"


def aviationstack_to_raw_records(
    payload: Dict[str, Any],
    *,
    airport_iata: str,
    mode: str = "both",  # "dep" | "arr" | "both"
) -> List[dict]:
    """
    Convert aviationstack /v1/flights payload into the flat record format expected by:
      src/localflight/decode/normalize.py::normalize_flights()

    Returns a list of dict records with keys like:
      callsign, direction, status, scheduled, estimated, actual,
      airline_name/iata/icao, origin_iata/icao, destination_iata/icao, aircraft_type, gate, stand
    Plus additional keys (harmless extras if normalize ignores them):
      terminal, delay_minutes
    """
    airport_iata = airport_iata.upper().strip()
    mode = mode.lower().strip()

    flights = payload.get("data") or payload.get("results") or []
    out: List[dict] = []

    for f in flights:
        dep = f.get("departure") or {}
        arr = f.get("arrival") or {}
        airline = f.get("airline") or {}
        flight = f.get("flight") or {}
        aircraft = f.get("aircraft") or {}

        dep_iata = _s(dep.get("iata")).upper()
        arr_iata = _s(arr.get("iata")).upper()

        # Determine direction relative to the airport we're displaying
        direction: Optional[str] = None
        if dep_iata == airport_iata and arr_iata != airport_iata:
            direction = "DEP"
        elif arr_iata == airport_iata and dep_iata != airport_iata:
            direction = "ARR"
        elif dep_iata == airport_iata and arr_iata == airport_iata:
            direction = "DEP"  # weird edge case
        else:
            continue  # ignore flights unrelated to our airport

        if mode == "dep" and direction != "DEP":
            continue
        if mode == "arr" and direction != "ARR":
            continue

        flight_iata = flight.get("iata")
        flight_icao = flight.get("icao")
        number = flight.get("number")

        airline_iata = airline.get("iata")
        airline_icao = airline.get("icao")

        # Callsign is required by normalize_flights(). Build best-effort.
        callsign = _pick(
            (f.get("identification", {}).get("callsign") if isinstance(f.get("identification"), dict) else None),
            flight_icao,
            flight_iata,
            (f"{airline_icao}{number}" if airline_icao and number else None),
            (f"{airline_iata}{number}" if airline_iata and number else None),
        )
        if not callsign:
            continue

        callsign = callsign.replace(" ", "").upper()

        status_raw = _normalize_status(f.get("flight_status"), direction=direction)

        # Pick the “relevant” time set depending on direction
        time_block = dep if direction == "DEP" else arr

        scheduled = time_block.get("scheduled")
        estimated = time_block.get("estimated")
        actual = time_block.get("actual")

        delay_minutes = _compute_delay_minutes(
            _s(scheduled) or None,
            _s(estimated) or None,
        )

        terminal = time_block.get("terminal")
        gate = time_block.get("gate")

        stand = _pick(
            time_block.get("stand"),
            time_block.get("bay"),
            time_block.get("apron"),
        )

        record = {
            "callsign": callsign,
            "direction": direction,
            "status": status_raw,
            "scheduled": scheduled,
            "estimated": estimated,
            "actual": actual,
            "airline_name": airline.get("name"),
            "airline_iata": airline_iata,
            "airline_icao": airline_icao,
            "flight_number": _pick(flight_iata, flight_icao),
            "origin_iata": dep.get("iata"),
            "origin_icao": dep.get("icao"),
            "destination_iata": arr.get("iata"),
            "destination_icao": arr.get("icao"),
            "aircraft_type": _pick(aircraft.get("icao"), aircraft.get("iata")),
            "aircraft_registration": _pick(aircraft.get("registration"), aircraft.get("reg")),
            "gate": gate,
            "stand": stand,
            "terminal": terminal,
            "delay_minutes": delay_minutes,
        }

        out.append(record)

    return out


def aviationstack_to_decoded(f: dict[str, Any]) -> dict[str, Any]:
    """
    Minimal decoded shape for the FIDS v1 pipeline:
      ui/server.py -> render/layouts/fids.py -> display/fids.py -> template

    Keep this "decoded" representation stable and UI-agnostic.
    """
    flight_date = _s(f.get("flight_date")).strip()
    flight_status = _s(f.get("flight_status")).strip()

    flight = f.get("flight") or {}
    airline = f.get("airline") or {}
    dep = f.get("departure") or {}
    arr = f.get("arrival") or {}
    aircraft = f.get("aircraft") or {}

    airline_iata = _s(airline.get("iata")).strip()
    flight_number = _s(flight.get("number")).strip()
    flight_iata = _s(flight.get("iata")).strip()
    flight_icao = _s(flight.get("icao")).strip()

    if airline_iata and flight_number:
        flight_display = f"{airline_iata} {flight_number}"
        flight_key = f"{airline_iata}{flight_number}"
    else:
        flight_display = flight_iata or flight_icao or "-"
        flight_key = flight_iata or flight_display.replace(" ", "")

    aircraft_type = _s(aircraft.get("iata")).strip() or _s(aircraft.get("icao")).strip() or ""

    return {
        "flight_date": flight_date,
        "flight_status": flight_status,
        "flight_display": flight_display,
        "flight_key": flight_key,
        "aircraft_type": aircraft_type,
        "departure": {
            "airport": dep.get("airport"),
            "iata": dep.get("iata"),
            "icao": dep.get("icao"),
            "gate": dep.get("gate"),
            "scheduled": dep.get("scheduled"),
            "estimated": dep.get("estimated"),
            "actual": dep.get("actual"),
        },
        "arrival": {
            "airport": arr.get("airport"),
            "iata": arr.get("iata"),
            "icao": arr.get("icao"),
            "gate": arr.get("gate"),
            "scheduled": arr.get("scheduled"),
            "estimated": arr.get("estimated"),
            "actual": arr.get("actual"),
        },
    }
