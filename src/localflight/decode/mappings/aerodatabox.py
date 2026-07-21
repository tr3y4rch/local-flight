from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional

from localflight.core.aircraft import aircraft_full_label, short_aircraft_type
from localflight.core.ops_location import gate_confidence, terminal_confidence


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


def _minute_stamp(value: Optional[str]) -> str:
    parsed = _parse_iso(value)
    if parsed:
        return parsed.replace(second=0, microsecond=0).isoformat()
    return _s(value)[:16]


def _codeshare_status(row: Dict[str, Any]) -> str:
    raw = _pick(
        row.get("codeshareStatus"),
        row.get("codeShareStatus"),
        row.get("codeshare_status"),
        row.get("CodeshareStatus"),
    )
    if not raw:
        return "Unknown"
    compact = str(raw).strip().replace(" ", "").lower()
    if compact in {"isoperator", "operator", "operating"}:
        return "IsOperator"
    if compact in {"iscodeshared", "codeshared", "marketing", "codeshare"}:
        return "IsCodeshared"
    return "Unknown"


def _provider_movement_key(
    *,
    direction: str,
    origin_iata: Optional[str],
    origin_icao: Optional[str],
    destination_iata: Optional[str],
    destination_icao: Optional[str],
    scheduled: Optional[str],
    estimated: Optional[str],
    actual: Optional[str],
) -> str:
    stamp = _minute_stamp(scheduled or estimated or actual)
    parts = (
        "aerodatabox",
        direction.upper(),
        (origin_iata or origin_icao or "").upper(),
        (destination_iata or destination_icao or "").upper(),
        stamp,
    )
    return "|".join(part for part in parts if part)


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
        airline = _dict(block.get("airline") or block.get("Airline"))
        number = _pick(block.get("number"), block.get("flightNumber"))
        airline_iata = _pick(block.get("airlineIata"), block.get("airline_iata"), airline.get("iata"), airline.get("IATA"))
        airline_icao = _pick(block.get("airlineIcao"), block.get("airline_icao"), airline.get("icao"), airline.get("ICAO"))
        candidates = (
            block.get("number"),
            block.get("flightNumber"),
            block.get("iata"),
            block.get("icao"),
            block.get("callSign"),
            f"{airline_iata}{number}" if airline_iata and number else None,
            f"{airline_icao}{number}" if airline_icao and number else None,
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
    airline_iata = _pick(airline.get("iata"), airline.get("IATA"))
    airline_icao = _pick(airline.get("icao"), airline.get("ICAO"))
    # AeroDataBox can place an operational callsign suffix (for example 9GD)
    # in `number`. It is useful as a callsign, but it is not evidence for a
    # published passenger flight number. Preserve only complete identifiers or
    # the normal digits-plus-optional-one-letter public form.
    for prefix in (airline_iata, airline_icao):
        if prefix and compact.startswith(prefix.upper()):
            suffix = compact[len(prefix):]
            if re.fullmatch(r"0*[0-9]{1,5}[A-Z]?", suffix):
                return compact
    if not re.fullmatch(r"0*[0-9]{1,5}", compact):
        return None
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
            operating_airline = _dict(
                row.get("operatingAirline")
                or row.get("OperatingAirline")
                or row.get("operating_airline")
                or row.get("operator")
                or row.get("operatedBy")
            )
            aircraft = _dict(row.get("aircraft") or row.get("Aircraft"))
            dep, arr = _movement_blocks(row, direction)
            time_block = dep if direction == "DEP" else arr
            location_prefix = "aerodatabox.departure" if direction == "DEP" else "aerodatabox.arrival"
            aircraft_short = short_aircraft_type(
                aircraft.get("icaoCode"),
                aircraft.get("icao"),
                aircraft.get("iataCode"),
                aircraft.get("iata"),
                aircraft.get("model"),
                aircraft.get("type"),
                aircraft.get("name"),
            )
            aircraft_full = aircraft_full_label(
                aircraft.get("model"),
                aircraft.get("type"),
                aircraft.get("name"),
                aircraft.get("icaoCode"),
                aircraft.get("icao"),
                short_code=aircraft_short,
            )

            flight_number = _flight_number(row, airline)
            callsign = _callsign(row, airline, flight_number)
            if not callsign:
                continue
            provider_codeshare_status = _codeshare_status(row)

            scheduled = _time_value(time_block, "scheduledTime", "scheduled", "scheduledAt")
            estimated = _time_value(time_block, "revisedTime", "estimatedTime", "estimated", "estimatedAt")
            actual = _time_value(time_block, "actualTime", "actual", "actualAt")

            origin_iata = _airport_code(dep, "iata") or (airport_iata if direction == "DEP" else None)
            origin_icao = _airport_code(dep, "icao") or (airport_icao if direction == "DEP" else None)
            destination_iata = _airport_code(arr, "iata") or (airport_iata if direction == "ARR" else None)
            destination_icao = _airport_code(arr, "icao") or (airport_icao if direction == "ARR" else None)
            provider_movement_key = _provider_movement_key(
                direction=direction,
                origin_iata=origin_iata,
                origin_icao=origin_icao,
                destination_iata=destination_iata,
                destination_icao=destination_icao,
                scheduled=scheduled,
                estimated=estimated,
                actual=actual,
            )
            identity_evidence = [f"aerodatabox.codeshareStatus:{provider_codeshare_status}"]

            gate = _pick(time_block.get("gate"), time_block.get("Gate"))
            terminal = _pick(time_block.get("terminal"), time_block.get("Terminal"))

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
                    "marketing_airline_name": _pick(airline.get("name"), airline.get("Name")),
                    "marketing_airline_iata": _pick(airline.get("iata"), airline.get("IATA")),
                    "marketing_airline_icao": _pick(airline.get("icao"), airline.get("ICAO")),
                    "marketing_flight_number": flight_number,
                    "operating_airline_name": _pick(operating_airline.get("name"), operating_airline.get("Name")),
                    "operating_airline_iata": _pick(operating_airline.get("iata"), operating_airline.get("IATA")),
                    "operating_airline_icao": _pick(operating_airline.get("icao"), operating_airline.get("ICAO")),
                    "operating_callsign": callsign if provider_codeshare_status == "IsOperator" else None,
                    "flight_number": flight_number,
                    "codeshares": _codeshare_identifiers(row),
                    "provider_codeshare_status": provider_codeshare_status,
                    "provider_movement_key": provider_movement_key,
                    "identity_evidence": identity_evidence,
                    "origin_iata": origin_iata,
                    "origin_icao": origin_icao,
                    "destination_iata": destination_iata,
                    "destination_icao": destination_icao,
                    "aircraft_type": aircraft_short or None,
                    "aircraft_type_full": aircraft_full or None,
                    "aircraft_registration": _pick(aircraft.get("reg"), aircraft.get("registration")),
                    "gate": gate,
                    "stand": _pick(time_block.get("stand"), time_block.get("parkingPosition")),
                    "terminal": terminal,
                    "gate_source": f"{location_prefix}.gate" if gate else "",
                    "terminal_source": f"{location_prefix}.terminal" if terminal else "",
                    "gate_confidence": gate_confidence(gate),
                    "terminal_confidence": terminal_confidence(terminal),
                    "ops_location_notes": (),
                    "delay_minutes": _delay_minutes(scheduled, estimated, actual),
                }
            )
    return out
