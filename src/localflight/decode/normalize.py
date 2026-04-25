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


def parse_time(value: str | None) -> datetime | None:
    """
    Parse ISO-8601 time strings. Accepts trailing 'Z' as UTC.
    Returns timezone-aware UTC datetime or None.
    """
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


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
        callsign = record["callsign"]
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

        flight = Flight(
            direction=direction,
            airport=airport,
            callsign=callsign,
            airline=AirlineRef(
                name=record.get("airline_name"),
                iata=record.get("airline_iata"),
                icao=record.get("airline_icao"),
            ),
            flight_number=record.get("flight_number"),
            origin=AirportRef(
                iata=record.get("origin_iata"),
                icao=record.get("origin_icao"),
            ) if record.get("origin_iata") or record.get("origin_icao") else None,
            destination=AirportRef(
                iata=record.get("destination_iata"),
                icao=record.get("destination_icao"),
            ) if record.get("destination_iata") or record.get("destination_icao") else None,
            aircraft_type=record.get("aircraft_type"),
            gate=record.get("gate"),
            terminal=record.get("terminal"),
            stand=record.get("stand"),
            status=status,
            times=times,
            delay_minutes=delay_minutes,
            source=source_name,
            updated_at=datetime.now(timezone.utc),
        )

        flights.append(flight)

    return flights
