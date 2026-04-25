from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from localflight.core.airports import lookup_airport
from localflight.core.models import Flight
from localflight.display.fids_from_flights import FidsView, flight_to_fids_row

# How long to keep a departed/arrived flight visible on the board
_GRACE_MINUTES = 30
# How far ahead to show upcoming flights
_HORIZON_HOURS = 12


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


def _filter_for_display(flights: list[Flight], now: datetime) -> list[Flight]:
    """
    Remove flights that don't belong on a live FIDS board.

    Rules:
      - VATSIM flights: always kept — they're live and vanish when the pilot disconnects.
      - No scheduled time: always kept — can't make a time decision.
      - Best time (actual > estimated > scheduled) more than GRACE_MINUTES in the past: hidden.
      - Best time more than HORIZON_HOURS ahead: hidden.
    """
    cutoff_past   = now - timedelta(minutes=_GRACE_MINUTES)
    cutoff_future = now + timedelta(hours=_HORIZON_HOURS)

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


def build_fids_context(
    *,
    cfg: Any,
    view: str,
    refresh_seconds: int,
    flights: list[Flight],
    last_refreshed: datetime | None = None,
    source_status: str = "OK",
) -> dict[str, Any]:
    tz = _resolve_tz(cfg)
    now = datetime.now(tz)

    view_str   = "departures" if str(view).lower() == "departures" else "arrivals"
    view_typed = cast(FidsView, view_str)

    flights = _filter_for_display(flights, now)

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
    }
