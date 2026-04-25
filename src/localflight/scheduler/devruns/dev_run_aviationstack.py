from __future__ import annotations

from typing import Optional, Union

from localflight.scheduler.runtime import run_loop
from localflight.sources.web.aviationstack_mock import load_sample_payload
from localflight.decode.mappings.aviationstack import aviationstack_to_raw_records
from localflight.decode.normalize import normalize_flights


def _fmt_delay(d: Optional[Union[int, float, str]]) -> str:
    if d is None:
        return "-"
    if isinstance(d, bool):
        return "-"
    try:
        di = int(d)
    except (TypeError, ValueError):
        return "-"
    if di == 0:
        return "0m"
    return f"{di:+d}m"


def fetch(cfg):
    return load_sample_payload()


def process(payload, cfg):
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
    print()

    print(f"{'TIME':<5}  {'CALLSIGN':<8}  {'ROUTE':<11}  {'STATUS':<9}  {'T':<3} {'GATE':<5} {'STAND':<6} {'DLY':<5}")
    print("-" * 60)

    for f in flights[:25]:
        gate = f.gate or "-"
        stand = f.stand or "-"
        terminal = getattr(f, "terminal", None) or "-"
        delay_val = getattr(f, "delay_minutes", None)
        delay = _fmt_delay(delay_val if isinstance(delay_val, (int, float, str)) else None)

        print(
            f"{f.display_time():<5}  "
            f"{f.callsign:<8}  "
            f"{f.display_route():<11}  "
            f"{f.status.value:<9}  "
            f"{terminal:<3} "
            f"{gate:<5} "
            f"{stand:<6} "
            f"{delay:<5}"
        )


def main() -> None:
    run_loop(fetch=fetch, process=process, render=render, once=True, source_name="aviationstack_mock")


if __name__ == "__main__":
    main()
