from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_PAGE_SIZE = 100
DEFAULT_DISPLAY_GRACE_MINUTES = 30
DEFAULT_DISPLAY_HORIZON_HOURS = 12
DEFAULT_FETCH_PAST_HOURS = 2
DEFAULT_FETCH_FUTURE_HOURS = 18
DEFAULT_PRODUCTION_PAGES_PER_DATE = 4
DEFAULT_AUDIT_PAGES_PER_DATE = 12


def resolve_timezone(timezone_name: str) -> ZoneInfo:
    name = (timezone_name or "").strip() or "UTC"
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, KeyError):
        return ZoneInfo("UTC")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class AviationstackWindow:
    timezone_name: str
    local_now: datetime
    display_start: datetime
    display_end: datetime
    fetch_start: datetime
    fetch_end: datetime

    @property
    def dates(self) -> list[date]:
        start = self.fetch_start.date()
        end = self.fetch_end.date()
        days = (end - start).days
        return [start + timedelta(days=idx) for idx in range(max(0, days) + 1)]


@dataclass(frozen=True)
class AviationstackFetchRequest:
    airport_iata: str
    mode: Literal["departures", "arrivals"]
    flight_date: Optional[str]
    offset: int
    limit: int
    dep_iata: Optional[str]
    arr_iata: Optional[str]
    date_index: int = 0
    page_index: int = 0

    @property
    def scope_key(self) -> tuple[str, str]:
        return (self.mode, self.flight_date or "")


def build_fetch_window(
    *,
    timezone_name: str,
    now: Optional[datetime] = None,
    display_grace_minutes: int = DEFAULT_DISPLAY_GRACE_MINUTES,
    display_horizon_hours: int = DEFAULT_DISPLAY_HORIZON_HOURS,
    fetch_past_hours: int = DEFAULT_FETCH_PAST_HOURS,
    fetch_future_hours: int = DEFAULT_FETCH_FUTURE_HOURS,
) -> AviationstackWindow:
    tz = resolve_timezone(timezone_name)
    current = (now or utc_now()).astimezone(tz)
    display_start = current - timedelta(minutes=max(0, int(display_grace_minutes)))
    display_end = current + timedelta(hours=max(1, int(display_horizon_hours)))
    fetch_start = min(
        current - timedelta(hours=max(0, int(fetch_past_hours))),
        display_start,
    )
    fetch_end = max(
        current + timedelta(hours=max(1, int(fetch_future_hours))),
        display_end,
    )
    return AviationstackWindow(
        timezone_name=tz.key,
        local_now=current,
        display_start=display_start,
        display_end=display_end,
        fetch_start=fetch_start,
        fetch_end=fetch_end,
    )


def build_fetch_plan(
    *,
    airport_iata: str,
    mode: Literal["departures", "arrivals"],
    timezone_name: str,
    now: Optional[datetime] = None,
    display_grace_minutes: int = DEFAULT_DISPLAY_GRACE_MINUTES,
    display_horizon_hours: int = DEFAULT_DISPLAY_HORIZON_HOURS,
    fetch_past_hours: int = DEFAULT_FETCH_PAST_HOURS,
    fetch_future_hours: int = DEFAULT_FETCH_FUTURE_HOURS,
    page_size: int = DEFAULT_PAGE_SIZE,
    pages_per_date: int = DEFAULT_PRODUCTION_PAGES_PER_DATE,
) -> list[AviationstackFetchRequest]:
    airport = (airport_iata or "").strip().upper()
    if not airport:
        return []

    window = build_fetch_window(
        timezone_name=timezone_name,
        now=now,
        display_grace_minutes=display_grace_minutes,
        display_horizon_hours=display_horizon_hours,
        fetch_past_hours=fetch_past_hours,
        fetch_future_hours=fetch_future_hours,
    )

    requests: list[AviationstackFetchRequest] = []
    dep_iata = airport if mode == "departures" else None
    arr_iata = airport if mode == "arrivals" else None
    limit = max(1, min(DEFAULT_PAGE_SIZE, int(page_size)))
    page_cap = max(1, int(pages_per_date))

    for date_index, flight_day in enumerate(window.dates):
        flight_date = flight_day.isoformat()
        for page_index in range(page_cap):
            requests.append(
                AviationstackFetchRequest(
                    airport_iata=airport,
                    mode=mode,
                    flight_date=flight_date,
                    offset=page_index * limit,
                    limit=limit,
                    dep_iata=dep_iata,
                    arr_iata=arr_iata,
                    date_index=date_index,
                    page_index=page_index,
                )
            )
    return requests


def build_undated_plan(
    *,
    airport_iata: str,
    mode: Literal["departures", "arrivals"],
    page_size: int = DEFAULT_PAGE_SIZE,
    page_cap: int = DEFAULT_PRODUCTION_PAGES_PER_DATE,
) -> list[AviationstackFetchRequest]:
    airport = (airport_iata or "").strip().upper()
    if not airport:
        return []
    dep_iata = airport if mode == "departures" else None
    arr_iata = airport if mode == "arrivals" else None
    limit = max(1, min(DEFAULT_PAGE_SIZE, int(page_size)))
    cap = max(1, int(page_cap))
    return [
        AviationstackFetchRequest(
            airport_iata=airport,
            mode=mode,
            flight_date=None,
            offset=page_index * limit,
            limit=limit,
            dep_iata=dep_iata,
            arr_iata=arr_iata,
            page_index=page_index,
        )
        for page_index in range(cap)
    ]


def window_date_count(
    *,
    timezone_name: str,
    now: Optional[datetime] = None,
    display_grace_minutes: int = DEFAULT_DISPLAY_GRACE_MINUTES,
    display_horizon_hours: int = DEFAULT_DISPLAY_HORIZON_HOURS,
    fetch_past_hours: int = DEFAULT_FETCH_PAST_HOURS,
    fetch_future_hours: int = DEFAULT_FETCH_FUTURE_HOURS,
) -> int:
    window = build_fetch_window(
        timezone_name=timezone_name,
        now=now,
        display_grace_minutes=display_grace_minutes,
        display_horizon_hours=display_horizon_hours,
        fetch_past_hours=fetch_past_hours,
        fetch_future_hours=fetch_future_hours,
    )
    return len(window.dates)
