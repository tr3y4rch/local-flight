from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _s(value: Any) -> str:
    return "" if value is None else str(value)


def _pick(*values: Any) -> Optional[str]:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _parse_iso(value: Any) -> Optional[datetime]:
    text = _s(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _time_value(block: Dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = block.get(key)
        if isinstance(value, dict):
            picked = _pick(
                value.get("utc"),
                value.get("Utc"),
                value.get("UTC"),
                value.get("local"),
                value.get("Local"),
            )
        else:
            picked = _pick(value)
        if picked:
            return picked
    return None


def _delay_minutes(scheduled: Optional[str], estimated: Optional[str], actual: Optional[str]) -> Optional[int]:
    start = _parse_iso(scheduled)
    end = _parse_iso(estimated) or _parse_iso(actual)
    if not start or not end:
        return None
    return int((end - start).total_seconds() // 60)


def _status(value: Any, *, direction: str) -> str:
    raw = _s(value).strip().lower()
    if not raw:
        return "unknown"
    normalized = raw.replace("_", " ").replace("-", " ")
    direct = {
        "scheduled": "scheduled",
        "expected": "scheduled",
        "boarding": "boarding",
        "check in": "boarding",
        "gate open": "boarding",
        "delayed": "delayed",
        "departed": "departed",
        "departing": "departed",
        "active": "departed" if direction == "DEP" else "scheduled",
        "en route": "departed",
        "arrived": "arrived",
        "landed": "arrived",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "canceled uncertain": "cancelled",
        "cancelled uncertain": "cancelled",
        "diverted": "diverted",
        "redirected": "diverted",
    }
    return direct.get(normalized, "unknown")


def _airport_code(block: Dict[str, Any], kind: str) -> Optional[str]:
    airport = _dict(block.get("airport"))
    return _pick(
        airport.get(kind),
        airport.get(kind.upper()),
        airport.get(kind.lower()),
        block.get(f"airport_{kind}"),
        block.get(f"airport{kind.upper()}"),
        block.get(kind),
        block.get(kind.upper()),
    )


def _codeshare_identifiers(row: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    blocks = row.get("codeshares") or row.get("codeShares") or row.get("codeshared") or []
    if isinstance(blocks, dict):
        blocks = [blocks]
    if not isinstance(blocks, list):
        return values
    for block in blocks:
        if not isinstance(block, dict):
            continue
        candidates = (
            block.get("number"),
            block.get("flightNumber"),
            block.get("iata"),
            block.get("icao"),
            block.get("callSign"),
        )
        for candidate in candidates:
            text = _s(candidate).replace(" ", "").upper()
            if text and text not in values:
                values.append(text)
    return values


def _flight_number(row: Dict[str, Any], airline: Dict[str, Any]) -> Optional[str]:
    number = _pick(row.get("number"), row.get("flightNumber"))
    if not number:
        return None
    compact = number.replace(" ", "").upper()
    if any(ch.isalpha() for ch in compact):
        return compact
    airline_iata = _pick(airline.get("iata"), airline.get("IATA"))
    airline_icao = _pick(airline.get("icao"), airline.get("ICAO"))
    prefix = airline_iata or airline_icao
    return f"{prefix}{compact}".upper() if prefix else compact


def _callsign(row: Dict[str, Any], airline: Dict[str, Any], flight_number: Optional[str]) -> Optional[str]:
    callsign = _pick(row.get("callSign"), row.get("callsign"), row.get("CallSign"))
    if callsign:
        return callsign.replace(" ", "").upper()
    if flight_number:
        airline_icao = _pick(airline.get("icao"), airline.get("ICAO"))
        digits = "".join(ch for ch in flight_number if ch.isdigit())
        if airline_icao and digits:
            return f"{airline_icao}{digits}".upper()
        return flight_number.replace(" ", "").upper()
    return None


def _movement_blocks(row: Dict[str, Any], direction: str) -> tuple[Dict[str, Any], Dict[str, Any]]:
    departure = _dict(row.get("departure") or row.get("Departure"))
    arrival = _dict(row.get("arrival") or row.get("Arrival"))
    movement = _dict(row.get("movement") or row.get("Movement"))
    if departure or arrival:
        return departure, arrival
    if direction == "DEP":
        return movement, {}
    return {}, movement


def aerodatabox_to_raw_records(
    payload: Dict[str, Any],
    *,
    airport_iata: str,
    airport_icao: str = "",
    mode: str = "both",
) -> List[dict]:
    """Convert AeroDataBox FIDS payloads into Local Flight canonical raw records."""

    airport_iata = airport_iata.upper().strip()
    airport_icao = airport_icao.upper().strip()
    requested = mode.lower().strip()
    sections: list[tuple[str, list[Any]]] = []
    if requested in {"both", "dep", "departures", "departure"}:
        departures = payload.get("departures") or payload.get("Departures") or []
        sections.append(("DEP", departures if isinstance(departures, list) else []))
    if requested in {"both", "arr", "arrivals", "arrival"}:
        arrivals = payload.get("arrivals") or payload.get("Arrivals") or []
        sections.append(("ARR", arrivals if isinstance(arrivals, list) else []))

    out: List[dict] = []
    for direction, rows in sections:
        for item in rows:
            row = _dict(item)
            if not row:
                continue
            airline = _dict(row.get("airline") or row.get("Airline"))
            aircraft = _dict(row.get("aircraft") or row.get("Aircraft"))
            dep, arr = _movement_blocks(row, direction)
            time_block = dep if direction == "DEP" else arr

            flight_number = _flight_number(row, airline)
            callsign = _callsign(row, airline, flight_number)
            if not callsign:
                continue

            scheduled = _time_value(time_block, "scheduledTime", "scheduled", "scheduledAt")
            estimated = _time_value(time_block, "revisedTime", "estimatedTime", "estimated", "estimatedAt")
            actual = _time_value(time_block, "actualTime", "actual", "actualAt")

            origin_iata = _airport_code(dep, "iata") or (airport_iata if direction == "DEP" else None)
            origin_icao = _airport_code(dep, "icao") or (airport_icao if direction == "DEP" else None)
            destination_iata = _airport_code(arr, "iata") or (airport_iata if direction == "ARR" else None)
            destination_icao = _airport_code(arr, "icao") or (airport_icao if direction == "ARR" else None)

            out.append(
                {
                    "callsign": callsign,
                    "direction": direction,
                    "status": _status(row.get("status") or row.get("flightStatus"), direction=direction),
                    "scheduled": scheduled,
                    "estimated": estimated,
                    "actual": actual,
                    "airline_name": _pick(airline.get("name"), airline.get("Name")),
                    "airline_iata": _pick(airline.get("iata"), airline.get("IATA")),
                    "airline_icao": _pick(airline.get("icao"), airline.get("ICAO")),
                    "flight_number": flight_number,
                    "codeshares": _codeshare_identifiers(row),
                    "origin_iata": origin_iata,
                    "origin_icao": origin_icao,
                    "destination_iata": destination_iata,
                    "destination_icao": destination_icao,
                    "aircraft_type": _pick(
                        aircraft.get("icaoCode"),
                        aircraft.get("icao"),
                        aircraft.get("model"),
                        aircraft.get("type"),
                    ),
                    "aircraft_registration": _pick(aircraft.get("reg"), aircraft.get("registration")),
                    "gate": _pick(time_block.get("gate"), time_block.get("Gate")),
                    "stand": _pick(time_block.get("stand"), time_block.get("parkingPosition")),
                    "terminal": _pick(time_block.get("terminal"), time_block.get("Terminal")),
                    "delay_minutes": _delay_minutes(scheduled, estimated, actual),
                }
            )
    return out
