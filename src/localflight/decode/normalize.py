from datetime import datetime, timezone
from typing import Iterable, List

from localflight.core.models import (
    Flight,
    FlightDirection,
    FlightStatus,
    AirportRef,
    AirlineRef,
    FlightTime,
)
from localflight.core.aircraft import aircraft_full_label, short_aircraft_type
from localflight.core.ops_location import normalize_ops_location_record
from localflight.decode.identity import resolve_flight_identity


def parse_time(value: str | None) -> datetime | None:
    """
    Parse ISO-8601 time strings. Accepts trailing 'Z' as UTC.
    Returns timezone-aware UTC datetime or None.
    """
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _parse_optional_int(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _parse_codeshares(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        return ()

    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip().upper()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return tuple(out)


def _parse_text_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return tuple(out)


def normalize_flights(
    raw_flights: Iterable[dict],
    *,
    airport_iata: str,
    airport_icao: str,
    source_name: str,
) -> List[Flight]:
    """
    Convert raw flight records from a web source into canonical Flight objects.
    """
    airport = AirportRef(iata=airport_iata, icao=airport_icao)
    flights: List[Flight] = []

    for record in raw_flights:
        record = normalize_ops_location_record(record, provider=source_name)
        identity = resolve_flight_identity(
            record,
            airport_iata=airport_iata,
            airport_icao=airport_icao,
        )
        callsign = identity.callsign or str(record["callsign"]).strip().upper()
        direction_raw = record["direction"]
        status_raw = record.get("status", "unknown")
        delay_raw = record.get("delay_minutes")
        delay_minutes = int(delay_raw) if isinstance(delay_raw, (int, float, str)) and str(delay_raw).strip() != "" else None


        if direction_raw.upper() == "DEP":
            direction = FlightDirection.DEPARTURE
        elif direction_raw.upper() == "ARR":
            direction = FlightDirection.ARRIVAL
        else:
            raise ValueError(f"Invalid direction: {direction_raw}")

        try:
            status = FlightStatus(status_raw.capitalize())
        except ValueError:
            status = FlightStatus.UNKNOWN

        times = FlightTime(
            scheduled=parse_time(record.get("scheduled")),
            estimated=parse_time(record.get("estimated")),
            actual=parse_time(record.get("actual")),
        )
        aircraft_short = short_aircraft_type(record.get("aircraft_type"))
        aircraft_full = record.get("aircraft_type_full") or aircraft_full_label(
            record.get("aircraft_type"),
            short_code=aircraft_short,
        )

        flight = Flight(
            direction=direction,
            airport=airport,
            callsign=callsign,
            airline=AirlineRef(
                name=identity.airline_name,
                iata=identity.airline_iata,
                icao=identity.airline_icao,
            ),
            flight_number=identity.flight_number,
            codeshares=identity.codeshares,
            sold_as=identity.sold_as,
            marketing_airline_name=identity.marketing_airline_name,
            marketing_airline_iata=identity.marketing_airline_iata,
            marketing_airline_icao=identity.marketing_airline_icao,
            marketing_flight_number=identity.marketing_flight_number,
            operating_callsign=identity.operating_callsign,
            identity_source=identity.identity_source,
            provider_codeshare_status=record.get("provider_codeshare_status"),
            provider_movement_key=record.get("provider_movement_key"),
            identity_evidence=_parse_text_tuple(record.get("identity_evidence")),
            origin=AirportRef(
                iata=record.get("origin_iata"),
                icao=record.get("origin_icao"),
                name=record.get("origin_name"),
            ) if record.get("origin_iata") or record.get("origin_icao") else None,
            destination=AirportRef(
                iata=record.get("destination_iata"),
                icao=record.get("destination_icao"),
                name=record.get("destination_name"),
            ) if record.get("destination_iata") or record.get("destination_icao") else None,
            aircraft_type=aircraft_short or None,
            aircraft_type_full=aircraft_full or None,
            aircraft_registration=record.get("aircraft_registration"),
            gate=record.get("gate"),
            terminal=record.get("terminal"),
            stand=record.get("stand"),
            gate_source=record.get("gate_source"),
            terminal_source=record.get("terminal_source"),
            gate_confidence=record.get("gate_confidence"),
            terminal_confidence=record.get("terminal_confidence"),
            ops_location_notes=_parse_text_tuple(record.get("ops_location_notes")),
            status=status,
            times=times,
            delay_minutes=delay_minutes,
            flight_rules=record.get("flight_rules"),
            planned_route=record.get("planned_route"),
            planned_altitude=record.get("planned_altitude"),
            planned_departure=parse_time(record.get("planned_departure")),
            planned_arrival=parse_time(record.get("planned_arrival")),
            planned_enroute_minutes=_parse_optional_int(record.get("planned_enroute_minutes")),
            cruise_tas=_parse_optional_int(record.get("cruise_tas")),
            alternate_icao=record.get("alternate_icao"),
            assigned_transponder=record.get("assigned_transponder"),
            source=source_name,
            updated_at=datetime.now(timezone.utc),
        )

        flights.append(flight)

    return flights
