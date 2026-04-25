from __future__ import annotations

import json
from pathlib import Path

from localflight.scheduler.runtime import run_loop
from localflight.sources.web.aviationstack_client import fetch_flights_once
from localflight.decode.mappings.aviationstack import aviationstack_to_raw_records
from localflight.decode.normalize import normalize_flights


SAMPLE_PATH = Path("src/localflight/storage/samples/aviationstack_flights_real.json")


def fetch(cfg):
    return fetch_flights_once(airport_iata=cfg.airport_iata, limit=10)


def process(payload, cfg):
    # freeze/overwrite latest snapshot every cycle (simple + useful)
    SAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SAMPLE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Saved raw response to:", SAMPLE_PATH)

    raw = aviationstack_to_raw_records(payload, airport_iata=cfg.airport_iata, mode="both")
    flights = normalize_flights(
        raw,
        airport_iata=cfg.airport_iata,
        airport_icao=cfg.airport_icao,
        source_name="aviationstack",
    )
    return payload, raw, flights


def render(result, cfg):
    payload, raw, flights = result

    print("Top-level keys:", list(payload.keys()))
    print("Flights in payload:", len(payload.get("data", [])))
    print("Raw records after mapping:", len(raw))
    print("Flights after normalization:", len(flights))

    for f in flights[:10]:
        print(f"{f.display_time()}  {f.callsign:<8}  {f.display_route():<11}  {f.status.value}")


def main() -> None:
    print("[real] aviationstack runtime loop (config-driven)")
    run_loop(fetch=fetch, process=process, render=render, source_name="aviationstack_api")


if __name__ == "__main__":
    main()
