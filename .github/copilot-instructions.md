# Copilot instructions for Local-Flight

Purpose
- Help AI contributors be immediately productive: explain architecture, core data flows, and project-specific conventions.

Big picture
- Canonical domain object: `Flight` defined in `src/localflight/core/models.py`.
- External data ingestion: each provider should emit simple dicts that are converted to `Flight` objects by normalization code under `src/localflight/decode/`.
- UI / rendering and sources are separated: data normalization lives in `decode/`, presentation in `render/` and `display/` (mostly scaffolding currently).

Key files and patterns to inspect
- `src/localflight/core/models.py` — dataclass-based immutable domain models: `Flight`, `AirportRef`, `AirlineRef`, `FlightTime`, `FlightDirection`, `FlightStatus`.
- `src/localflight/decode/normalize.py` — canonicalization helpers. See `normalize_flights(raw_flights, *, airport_iata, airport_icao, source_name)` for how sources must be adapted.
- `scripts/dev_model_test.py` — quick smoke example constructing a `Flight` and printing `display_route()` and `display_time()`.

Project-specific conventions
- Timezones: All datetimes are timezone-aware UTC. Use `datetime(..., timezone.utc)` and the provided `parse_time()` in `decode/normalize.py` which accepts ISO strings and trailing `Z`.
- Codes: `AirportRef.code()` prefers IATA then ICAO; use `iata` when available for display.
- Immutability: Domain dataclasses are `frozen=True`; construct new objects rather than mutating.
- Status enums: `FlightStatus` values are canonical; normalization should map provider statuses to these enums, falling back to `UNKNOWN`.

How to add a new source
1. Add an adapter under `src/localflight/sources/` (follow existing folder layout: `web/` or `adsb/`).
2. Produce a list/iterable of raw dicts with keys used in `normalize_flights` (e.g. `callsign`, `direction`, `scheduled`, `estimated`, `actual`, `origin_iata`/`origin_icao`, `destination_iata`/`destination_icao`, `airline_name`, `airline_iata`, `airline_icao`, `flight_number`, `aircraft_type`, `gate`, `stand`, `status`).
3. Call `normalize_flights(raw, airport_iata="ZRH", airport_icao="LSZH", source_name="your_provider")` to get `List[Flight]`.

Quick developer workflows (discoverable here)
- Fast smoke run: `python scripts/dev_model_test.py` (shows model usage).
- There are no test harnesses or packaging files in the repo snapshot; prefer simple local python runs and small scripts for verification.

Examples
- Normalizer call:

  ```py
  from localflight.decode.normalize import normalize_flights
  flights = normalize_flights(raw_records, airport_iata="ZRH", airport_icao="LSZH", source_name="flights_api")
  ```

- Time parsing: `parse_time("2024-01-01T12:00:00Z")` returns a timezone-aware UTC `datetime`.

Notes for AI edits
- Preserve `frozen` dataclasses and timezone-aware handling when changing model fields.
- When adding fields to `Flight`, update any normalization adapters and `scripts/dev_model_test.py` to demonstrate the new field.
- Many folders are scaffolding; check for empty directories before assuming behavior exists.

If anything above is unclear or you'd like me to expand examples (e.g., create a sample source adapter), tell me which area to extend.
