from datetime import datetime, timezone
from localflight.core.models import (
    Flight, FlightDirection, FlightStatus,
    AirportRef, AirlineRef, FlightTime
)

zrh = AirportRef(iata="ZRH", icao="LSZH", name="Zurich")
lhr = AirportRef(iata="LHR", icao="EGLL", name="London Heathrow")

f = Flight(
    direction=FlightDirection.DEPARTURE,
    airport=zrh,
    callsign="SWR184",
    airline=AirlineRef(name="SWISS", iata="LX", icao="SWR"),
    flight_number="LX184",
    destination=lhr,
    aircraft_type="A320",
    status=FlightStatus.BOARDING,
    times=FlightTime(scheduled=datetime.now(timezone.utc)),
    source="fake",
    updated_at=datetime.now(timezone.utc),
)

print(f.callsign, f.display_route(), f.display_time(), f.status.value)
