from __future__ import annotations

import json
from pathlib import Path

from localflight.scheduler.runtime import run_loop
from localflight.decode.dedupe import dedupe_codeshares
from localflight.decode.mappings.aviationstack import aviationstack_to_raw_records
from localflight.decode.normalize import normalize_flights

SAMPLE_PATH = Path("src/localflight/storage/samples/aviationstack_flights_real.json")


def fetch(cfg):
    payload = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    return payload


def process(payload, cfg):
    raw = aviationstack_to_raw_records(payload, airport_iata=cfg.airport_iata, mode="both")
    flights = normalize_flights(
        raw,
        airport_iata=cfg.airport_iata,
        airport_icao=cfg.airport_icao,
        source_name="aviationstack",
    )
    return flights


def render(flights, cfg):
    print(f"Raw mapped flights: {len(flights)}")
    for f in flights:
        print(f"  {f.display_time()}  {f.callsign:<8}  {f.display_route():<11}  {f.airline.code():<3}  {f.status.value}")

    print("\n--- after dedupe (preferred LX/WK) ---")
    deduped = dedupe_codeshares(flights, preferred_airline_iata=["LX", "WK"], time_bucket_minutes=5)
    print(f"Deduped flights: {len(deduped)}")

    for f in deduped:
        print(f"  {f.display_time()}  {f.callsign:<8}  {f.display_route():<11}  {f.airline.code():<3}  {f.status.value}")


def main() -> None:
    print("[codeshares] runtime loop reading frozen payload")
    run_loop(fetch=fetch, process=process, render=render, source_name="codeshares_dedupe")


if __name__ == "__main__":
    main()
