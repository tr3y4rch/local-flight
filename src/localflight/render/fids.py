from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from localflight.core.airports import lookup_airport
from localflight.core.models import Flight
from localflight.display.fids_from_flights import FidsView, flight_to_fids_row
from localflight.storage.config import (
    DEFAULT_DISPLAY_GRACE_MINUTES,
    DEFAULT_DISPLAY_HORIZON_HOURS,
)


def _resolve_tz(cfg: Any) -> ZoneInfo:
    tz_name = getattr(cfg, "timezone", None) or "Europe/Zurich"
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        return ZoneInfo("Europe/Zurich")


def _fmt_ts(dt: datetime, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime("%H:%M:%S")


def _fmt_mmss(seconds: int) -> str:
    seconds = max(0, int(seconds))
    mm, ss = divmod(seconds, 60)
    return f"{mm:02d}:{ss:02d}"


def _sort_key(display_time: str) -> tuple[int, str]:
    if not display_time or display_time.startswith("--"):
        return (1, "99:99")
    hhmm = display_time[:5]
    if len(hhmm) != 5 or hhmm[2] != ":":
        return (1, "99:99")
    return (0, hhmm)


def _display_window(cfg: Any) -> tuple[int, int]:
    grace_minutes = getattr(cfg, "display_grace_minutes", DEFAULT_DISPLAY_GRACE_MINUTES)
    horizon_hours = getattr(cfg, "display_horizon_hours", DEFAULT_DISPLAY_HORIZON_HOURS)
    try:
        grace_minutes = int(grace_minutes)
    except Exception:
        grace_minutes = DEFAULT_DISPLAY_GRACE_MINUTES
    try:
        horizon_hours = int(horizon_hours)
    except Exception:
        horizon_hours = DEFAULT_DISPLAY_HORIZON_HOURS
    return (
        max(0, grace_minutes),
        max(1, horizon_hours),
    )


def _best_time_for_display(flight: Flight) -> datetime | None:
    value = flight.times.actual or flight.times.estimated or flight.times.scheduled
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def _filter_for_display(flights: list[Flight], now: datetime, *, cfg: Any) -> list[Flight]:
    """
    Remove flights that don't belong on a live FIDS board.

    Rules:
      - VATSIM flights: always kept — they're live and vanish when the pilot disconnects.
      - No scheduled time: always kept — can't make a time decision.
      - Best time (actual > estimated > scheduled) more than GRACE_MINUTES in the past: hidden.
      - Best time more than HORIZON_HOURS ahead: hidden.
    """
    grace_minutes, horizon_hours = _display_window(cfg)
    cutoff_past = now - timedelta(minutes=grace_minutes)
    cutoff_future = now + timedelta(hours=horizon_hours)

    result = []
    for f in flights:
        if f.source == "vatsim":
            result.append(f)
            continue

        t = f.times.actual or f.times.estimated or f.times.scheduled
        if t is None:
            result.append(f)
            continue

        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)

        if cutoff_past <= t <= cutoff_future:
            result.append(f)

    return result


def _fallback_for_sparse_window(flights: list[Flight], now: datetime, *, cfg: Any) -> list[Flight]:
    if not flights:
        return []

    grace_minutes, horizon_hours = _display_window(cfg)
    cutoff_past = now - timedelta(minutes=grace_minutes)
    cutoff_future = now + timedelta(hours=horizon_hours)
    fallback_limit = max(10, int(getattr(cfg, "web_row_limit", 20) or 20) * 2)

    with_times = [(flight, _best_time_for_display(flight)) for flight in flights]
    timed = [(flight, stamp) for flight, stamp in with_times if stamp is not None]
    recent_past = [(flight, stamp) for flight, stamp in timed if stamp < cutoff_past]
    future = [(flight, stamp) for flight, stamp in timed if stamp > cutoff_future]

    if recent_past:
        recent_past.sort(key=lambda item: item[1], reverse=True)
        selected = recent_past[:fallback_limit]
        selected.sort(key=lambda item: item[1])
        return [flight for flight, _stamp in selected]

    if future:
        future.sort(key=lambda item: item[1])
        return [flight for flight, _stamp in future[:fallback_limit]]

    untimed = [flight for flight, stamp in with_times if stamp is None]
    if untimed:
        return untimed[:fallback_limit]

    return []


def build_fids_context(
    *,
    cfg: Any,
    view: str,
    refresh_seconds: int,
    flights: list[Flight],
    last_refreshed: datetime | None = None,
    reference_now: datetime | None = None,
    allow_sparse_fallback: bool = True,
    source_status: str = "OK",
) -> dict[str, Any]:
    tz = _resolve_tz(cfg)
    if reference_now is None:
        now = datetime.now(tz)
    else:
        now = reference_now
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(tz)

    view_str   = "departures" if str(view).lower() == "departures" else "arrivals"
    view_typed = cast(FidsView, view_str)

    visible_flights = _filter_for_display(flights, now, cfg=cfg)
    sparse_window_fallback = False
    if not visible_flights and allow_sparse_fallback:
        fallback_flights = _fallback_for_sparse_window(flights, now, cfg=cfg)
        if fallback_flights:
            visible_flights = fallback_flights
            sparse_window_fallback = True
    flights = visible_flights

    ap = lookup_airport(iata=getattr(cfg, "airport_iata", None), icao=getattr(cfg, "airport_icao", None))
    airport_lat = ap.lat if ap else None
    airport_lon = ap.lon if ap else None

    rows = [flight_to_fids_row(f, view=view_typed, airport_lat=airport_lat, airport_lon=airport_lon) for f in flights]
    rows.sort(key=lambda r: _sort_key(r.display_time))

    last = last_refreshed or now

    return {
        "cfg": cfg,
        "view": view_str,
        "rows": rows,
        "last_refreshed": _fmt_ts(last, tz),
        "next_in": _fmt_mmss(refresh_seconds),
        "source_status": source_status,
        "sparse_window_fallback": sparse_window_fallback,
    }
