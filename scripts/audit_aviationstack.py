#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from localflight.decode.dedupe import dedupe_codeshares
from localflight.decode.mappings.aviationstack import aviationstack_to_raw_records
from localflight.decode.normalize import normalize_flights
from localflight.render.fids import build_fids_context
from localflight.scheduler.jobs import _dedupe_identical_flights
from localflight.sources.web.aviationstack_client import fetch_flights_strategy
from localflight.sources.web.aviationstack_plan import (
    DEFAULT_AUDIT_PAGES_PER_DATE,
    DEFAULT_DISPLAY_GRACE_MINUTES,
    DEFAULT_DISPLAY_HORIZON_HOURS,
    DEFAULT_PAGE_SIZE,
)
from localflight.storage.config import AppConfig


AIRPORTS = [
    {"label": "OMDB", "iata": "DXB", "icao": "OMDB", "timezone": "Asia/Dubai"},
    {"label": "OERK", "iata": "RUH", "icao": "OERK", "timezone": "Asia/Riyadh"},
    {"label": "FACT", "iata": "CPT", "icao": "FACT", "timezone": "Africa/Johannesburg"},
    {"label": "OPKC", "iata": "KHI", "icao": "OPKC", "timezone": "Asia/Karachi"},
    {"label": "WSSS", "iata": "SIN", "icao": "WSSS", "timezone": "Asia/Singapore"},
    {"label": "RJTT/HND", "iata": "HND", "icao": "RJTT", "timezone": "Asia/Tokyo"},
    {"label": "FRA", "iata": "FRA", "icao": "EDDF", "timezone": "Europe/Berlin"},
    {"label": "JFK", "iata": "JFK", "icao": "KJFK", "timezone": "America/New_York"},
]

STRATEGIES = ("baseline", "paginated", "fair")
MODES = ("departures", "arrivals")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark AviationStack baseline, paginated, and fair windowed fetch strategies.",
    )
    parser.add_argument(
        "--out-dir",
        default="",
        help="Optional output directory. Defaults to build/aviationstack-audit/<timestamp>/",
    )
    parser.add_argument(
        "--airports",
        nargs="*",
        default=[],
        help="Optional airport labels/IATA/ICAO to audit. Defaults to the built-in global sample set.",
    )
    parser.add_argument(
        "--strategies",
        nargs="*",
        choices=STRATEGIES,
        default=list(STRATEGIES),
        help="Fetch strategies to run.",
    )
    parser.add_argument(
        "--modes",
        nargs="*",
        choices=MODES,
        default=list(MODES),
        help="Directions to audit.",
    )
    parser.add_argument(
        "--pages-per-date",
        type=int,
        default=DEFAULT_AUDIT_PAGES_PER_DATE,
        help="Audit page cap per queried local date for paginated/fair strategies.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help="Page size to request from AviationStack.",
    )
    parser.add_argument(
        "--display-grace-minutes",
        type=int,
        default=DEFAULT_DISPLAY_GRACE_MINUTES,
        help="Visible board grace window used for the fairness audit.",
    )
    parser.add_argument(
        "--display-horizon-hours",
        type=int,
        default=DEFAULT_DISPLAY_HORIZON_HOURS,
        help="Visible board horizon used for the fairness audit.",
    )
    parser.add_argument(
        "--web-row-limit",
        type=int,
        default=20,
        help="Visible web board row cap used when reporting page counts.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="Per-request HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--now",
        default="",
        help="Optional fixed UTC timestamp (ISO-8601) for reproducible planning.",
    )
    return parser.parse_args()


def _parse_now(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _selected_airports(filters: Iterable[str]) -> list[dict[str, str]]:
    wanted = {item.strip().upper() for item in filters if item.strip()}
    if not wanted:
        return list(AIRPORTS)
    selected = [
        airport
        for airport in AIRPORTS
        if airport["label"].upper() in wanted
        or airport["iata"].upper() in wanted
        or airport["icao"].upper() in wanted
    ]
    if not selected:
        raise SystemExit(f"No matching airports found for filters: {sorted(wanted)}")
    return selected


def _best_time_iso(flights) -> tuple[str, str]:
    stamps: list[str] = []
    for flight in flights:
        best = flight.times.actual or flight.times.estimated or flight.times.scheduled
        if not best:
            continue
        if best.tzinfo is None:
            best = best.replace(tzinfo=timezone.utc)
        stamps.append(best.astimezone(timezone.utc).isoformat())
    if not stamps:
        return ("", "")
    stamps.sort()
    return (stamps[0], stamps[-1])


def _field_completeness(flights) -> dict[str, Any]:
    total = len(flights)
    if total <= 0:
        return {
            "gate_pct": 0.0,
            "terminal_pct": 0.0,
            "aircraft_type_pct": 0.0,
            "scheduled_pct": 0.0,
            "estimated_pct": 0.0,
            "actual_pct": 0.0,
        }

    def _pct(count: int) -> float:
        return round((count / total) * 100.0, 1)

    return {
        "gate_pct": _pct(sum(1 for flight in flights if flight.gate)),
        "terminal_pct": _pct(sum(1 for flight in flights if flight.terminal)),
        "aircraft_type_pct": _pct(sum(1 for flight in flights if flight.aircraft_type)),
        "scheduled_pct": _pct(sum(1 for flight in flights if flight.times.scheduled)),
        "estimated_pct": _pct(sum(1 for flight in flights if flight.times.estimated)),
        "actual_pct": _pct(sum(1 for flight in flights if flight.times.actual)),
    }


def _run_case(
    *,
    airport: dict[str, str],
    mode: str,
    strategy: str,
    pages_per_date: int,
    page_size: int,
    display_grace_minutes: int,
    display_horizon_hours: int,
    web_row_limit: int,
    timeout_s: int,
    now: datetime | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, meta = fetch_flights_strategy(
        airport_iata=airport["iata"],
        timezone_name=airport["timezone"],
        mode=mode,
        strategy=strategy,
        display_grace_minutes=display_grace_minutes,
        display_horizon_hours=display_horizon_hours,
        page_size=page_size,
        pages_per_date=pages_per_date,
        timeout_s=timeout_s,
        now=now,
    )

    raw_records = aviationstack_to_raw_records(
        payload,
        airport_iata=airport["iata"],
        mode="dep" if mode == "departures" else "arr",
    )
    normalized = normalize_flights(
        raw_records,
        airport_iata=airport["iata"],
        airport_icao=airport["icao"],
        source_name="aviationstack",
    )
    identical = _dedupe_identical_flights(normalized)
    final = dedupe_codeshares(
        identical,
        preferred_airline_iata=["LX", "WK", "OS", "LH"],
    )
    cfg = AppConfig(
        airport_iata=airport["iata"],
        airport_icao=airport["icao"],
        timezone=airport["timezone"],
        source="real",
        web_row_limit=web_row_limit,
        display_grace_minutes=display_grace_minutes,
        display_horizon_hours=display_horizon_hours,
    )
    ctx = build_fids_context(
        cfg=cfg,
        view=mode,
        refresh_seconds=cfg.refresh_seconds,
        flights=final,
        last_refreshed=now or datetime.now(timezone.utc),
        source_status=strategy,
    )
    visible_rows = list(ctx["rows"])
    earliest_best_utc, latest_best_utc = _best_time_iso(final)
    completeness = _field_completeness(final)

    summary = {
        "airport_label": airport["label"],
        "airport_iata": airport["iata"],
        "airport_icao": airport["icao"],
        "timezone": airport["timezone"],
        "mode": mode,
        "strategy": strategy,
        "pages_requested": int(meta.get("pages_requested", 0) or 0),
        "pages_fetched": int(meta.get("pages_fetched", 0) or 0),
        "page_size": int(meta.get("page_size", page_size) or page_size),
        "page_cap": int(meta.get("page_cap", pages_per_date) or pages_per_date),
        "planned_dates": list(meta.get("planned_dates") or []),
        "dates_touched": list(meta.get("dates_touched") or []),
        "raw_rows": len(payload.get("data") or []),
        "normalized_rows": len(normalized),
        "identical_rows": len(identical),
        "final_rows": len(final),
        "visible_rows": len(visible_rows),
        "web_pages": max(1, (len(visible_rows) + max(1, web_row_limit) - 1) // max(1, web_row_limit)),
        "duplicate_rows_collapsed": len(normalized) - len(final),
        "identical_rows_collapsed": len(normalized) - len(identical),
        "codeshare_rows_collapsed": len(identical) - len(final),
        "earliest_best_time_utc": earliest_best_utc,
        "latest_best_time_utc": latest_best_utc,
        "pages_by_scope": meta.get("pages_by_scope") or {},
        "rows_by_scope": meta.get("rows_by_scope") or {},
        "field_completeness": completeness,
    }
    return summary, {"payload": payload, "meta": meta}


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    args = _parse_args()
    now = _parse_now(args.now)
    generated_at = datetime.now(timezone.utc)
    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "build" / "aviationstack-audit" / generated_at.strftime("%Y%m%dT%H%M%SZ")
    out_dir.mkdir(parents=True, exist_ok=True)

    airports = _selected_airports(args.airports)
    summary_rows: list[dict[str, Any]] = []

    metadata = {
        "generated_at_utc": generated_at.isoformat(),
        "planned_now_utc": (now or generated_at).isoformat(),
        "airports": airports,
        "strategies": list(args.strategies),
        "modes": list(args.modes),
        "pages_per_date": int(args.pages_per_date),
        "page_size": int(args.page_size),
        "display_grace_minutes": int(args.display_grace_minutes),
        "display_horizon_hours": int(args.display_horizon_hours),
        "web_row_limit": int(args.web_row_limit),
        "timeout_s": int(args.timeout),
    }
    _write_json(out_dir / "metadata.json", metadata)

    for airport in airports:
        for mode in args.modes:
            for strategy in args.strategies:
                try:
                    summary, detail = _run_case(
                        airport=airport,
                        mode=mode,
                        strategy=strategy,
                        pages_per_date=int(args.pages_per_date),
                        page_size=int(args.page_size),
                        display_grace_minutes=int(args.display_grace_minutes),
                        display_horizon_hours=int(args.display_horizon_hours),
                        web_row_limit=int(args.web_row_limit),
                        timeout_s=int(args.timeout),
                        now=now,
                    )
                    summary_rows.append(summary)
                    payload_name = f"{mode}-{strategy}.json"
                    payload_dir = out_dir / "payloads" / airport["iata"]
                    _write_json(
                        payload_dir / payload_name,
                        {
                            "metadata": metadata,
                            "summary": summary,
                            "payload": detail["payload"],
                            "fetch_meta": detail["meta"],
                        },
                    )
                    print(
                        f"[ok] {airport['label']} {mode} {strategy}: "
                        f"raw={summary['raw_rows']} visible={summary['visible_rows']} "
                        f"pages={summary['pages_fetched']}",
                    )
                except Exception as exc:
                    error_summary = {
                        "airport_label": airport["label"],
                        "airport_iata": airport["iata"],
                        "airport_icao": airport["icao"],
                        "timezone": airport["timezone"],
                        "mode": mode,
                        "strategy": strategy,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    summary_rows.append(error_summary)
                    _write_json(
                        out_dir / "payloads" / airport["iata"] / f"{mode}-{strategy}.json",
                        {"metadata": metadata, "summary": error_summary},
                    )
                    print(f"[err] {airport['label']} {mode} {strategy}: {type(exc).__name__}: {exc}")

    _write_json(out_dir / "summary.json", summary_rows)

    csv_fields = [
        "airport_label",
        "airport_iata",
        "airport_icao",
        "timezone",
        "mode",
        "strategy",
        "pages_requested",
        "pages_fetched",
        "page_size",
        "page_cap",
        "raw_rows",
        "normalized_rows",
        "identical_rows",
        "final_rows",
        "visible_rows",
        "web_pages",
        "duplicate_rows_collapsed",
        "identical_rows_collapsed",
        "codeshare_rows_collapsed",
        "earliest_best_time_utc",
        "latest_best_time_utc",
        "error",
    ]
    with (out_dir / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fields)
        writer.writeheader()
        for row in summary_rows:
            writer.writerow({field: row.get(field, "") for field in csv_fields})

    print(f"Audit bundle written to {out_dir}")


if __name__ == "__main__":
    main()
