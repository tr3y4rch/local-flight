from __future__ import annotations

import json
import math
import os
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Literal, Optional

import requests
from localflight.sources.web.aviationstack_plan import (
    DEFAULT_AUDIT_PAGES_PER_DATE,
    DEFAULT_DISPLAY_GRACE_MINUTES,
    DEFAULT_DISPLAY_HORIZON_HOURS,
    DEFAULT_FETCH_FUTURE_HOURS,
    DEFAULT_FETCH_PAST_HOURS,
    DEFAULT_PAGE_SIZE,
    DEFAULT_PRODUCTION_PAGES_PER_DATE,
    AviationstackFetchRequest,
    build_fetch_plan,
    build_fetch_window,
    build_undated_plan,
    window_date_count,
)
from localflight.sources.web.relay_defaults import (
    default_public_relay_url,
    relay_endpoint_url,
    relay_root_url,
    relay_schedule_url,
)

AVIATIONSTACK_BASE_URL = "https://api.aviationstack.com/v1/flights"

_DEFAULT_BYOK_LIMIT = 90
_BYOK_PLAN_MAX = 100
_DEFAULT_RELAY_LIMIT = 50
_MANAGED_STATUS_CACHE_TTL_S = 60
_COMMUNITY_WINDOW_DAYS = 30
_FETCH_STATS_MAX_SAMPLES = 24
_MAX_FAIR_PAGES_PER_DATE = DEFAULT_AUDIT_PAGES_PER_DATE

_managed_status_cache: dict[str, Any] = {"ts": 0.0, "token": "", "data": None}


class AviationstackError(RuntimeError):
    pass


class AviationstackBudgetExceeded(AviationstackError):
    pass


def _has_api_key() -> bool:
    return bool(os.getenv("AVIATIONSTACK_API_KEY", "").strip())


def _get_api_key() -> str:
    key = os.getenv("AVIATIONSTACK_API_KEY", "").strip()
    if not key:
        raise AviationstackError("AVIATIONSTACK_API_KEY not set")
    return key


def _get_community_api_key() -> str:
    env_key = os.getenv("LOCALFLIGHT_COMMUNITY_AVIATIONSTACK_KEY", "").strip()
    if env_key:
        return env_key
    try:
        from localflight.sources.web.private_keys import get_private_key

        return get_private_key("community_aviationstack_key") or ""
    except Exception:
        return ""


def _has_community_api_key() -> bool:
    return bool(_get_community_api_key())


def _is_enabled() -> bool:
    raw = os.getenv("LOCALFLIGHT_AVIATIONSTACK_ENABLED", "").strip().lower()
    if not raw:
        return _has_api_key()
    return raw in {"1", "true", "yes", "on"}


def _has_enabled_byok_key() -> bool:
    return _has_api_key() and _is_enabled()


def _is_relay_mode() -> bool:
    return not _has_enabled_byok_key()


def _get_byok_limit() -> int:
    try:
        return int(os.getenv("LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT", str(_DEFAULT_BYOK_LIMIT)))
    except (ValueError, TypeError):
        return _DEFAULT_BYOK_LIMIT


def _get_relay_url() -> str:
    return default_public_relay_url().rstrip("/")


def _get_relay_limit() -> int:
    try:
        return int(os.getenv("LOCALFLIGHT_RELAY_MONTHLY_LIMIT", str(_DEFAULT_RELAY_LIMIT)))
    except (ValueError, TypeError):
        return _DEFAULT_RELAY_LIMIT


def _get_activation_token() -> str:
    try:
        from localflight.storage.install import get_activation_token

        return get_activation_token()
    except Exception:
        return ""


def _has_activation_token() -> bool:
    return bool(_get_activation_token())


def _usage_path() -> Path:
    from localflight.storage.config import config_path

    return config_path().parent / "api_usage.json"


def _load_usage() -> Dict[str, Any]:
    p = _usage_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_usage(data: Dict[str, Any]) -> None:
    try:
        _usage_path().write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _window_bucket_start(now: Optional[datetime] = None) -> str:
    dt = now or _utc_now()
    return dt.isoformat()


def _load_community_window(limit: int) -> tuple[Dict[str, Any], Dict[str, Any]]:
    usage = _load_usage()
    now = _utc_now()
    bucket = usage.get("relay")

    if isinstance(bucket, dict) and "period_start" in bucket:
        start = _parse_utc(bucket.get("period_start")) or now
        calls = int(bucket.get("calls", 0) or 0)
        stored_limit = int(bucket.get("limit", limit) or limit)
    elif isinstance(bucket, dict) and bucket:
        latest_month = sorted(bucket.keys(), reverse=True)[0]
        try:
            start = datetime.fromisoformat(f"{latest_month}-01T00:00:00+00:00")
        except Exception:
            start = now
        calls = int(bucket.get(latest_month, 0) or 0)
        stored_limit = limit
    else:
        start = now
        calls = 0
        stored_limit = limit

    if (now - start) >= timedelta(days=_COMMUNITY_WINDOW_DAYS):
        start = now
        calls = 0

    window = {
        "period_start": _window_bucket_start(start),
        "period_end": _window_bucket_start(start + timedelta(days=_COMMUNITY_WINDOW_DAYS)),
        "calls": max(0, calls),
        "limit": max(1, stored_limit),
        "period_days": _COMMUNITY_WINDOW_DAYS,
    }
    usage["relay"] = window
    return usage, window


def _save_community_window(usage: Dict[str, Any], window: Dict[str, Any]) -> None:
    usage["relay"] = window
    _save_usage(usage)


def _increment_community_budget(limit: int, n_calls: int = 1) -> None:
    usage, window = _load_community_window(limit)
    current = int(window.get("calls", 0) or 0)
    effective_limit = max(1, int(window.get("limit", limit) or limit))

    if current + n_calls > effective_limit:
        raise AviationstackBudgetExceeded(
            f"Community relay quota exceeded: {current}/{effective_limit} calls used "
            f"in the current {_COMMUNITY_WINDOW_DAYS}-day window. Add AVIATIONSTACK_API_KEY "
            f"to your .env for your own subscription."
        )

    window["calls"] = current + n_calls
    window["limit"] = effective_limit
    _save_community_window(usage, window)


def _increment_budget(bucket: str, limit: int, n_calls: int = 1) -> None:
    usage = _load_usage()
    month = _month_key()
    month_data = usage.setdefault(bucket, {})
    current = int(month_data.get(month, 0) or 0)

    if current + n_calls > limit:
        if bucket == "relay":
            raise AviationstackBudgetExceeded(
                f"Community relay quota exceeded: {current}/{limit} calls used "
                f"this month ({month}). Add AVIATIONSTACK_API_KEY to your .env "
                f"for your own subscription."
            )
        raise AviationstackBudgetExceeded(
            f"AviationStack monthly budget exceeded: {current}/{limit} calls used "
            f"this month ({month}). Set LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT=N "
            f"to increase, or wait until next month."
        )

    month_data[month] = current + n_calls
    for old in sorted(month_data.keys(), reverse=True)[3:]:
        del month_data[old]
    _save_usage(usage)


def _sync_relay_quota_from_headers(headers: Any) -> None:
    used_str = headers.get("X-LF-Quota-Used") if headers else None
    limit_str = headers.get("X-LF-Quota-Limit") if headers else None
    plan = (headers.get("X-LF-Quota-Plan") or "").strip().lower() if headers else ""
    if used_str is None:
        return
    try:
        used = int(used_str)
        usage = _load_usage()
        if plan == "managed":
            month = _month_key()
            bucket = "relay_managed"
            limit_bucket = "relay_managed_limits"
            md = usage.setdefault(bucket, {})
            md[month] = used
            if limit_str:
                limits = usage.setdefault(limit_bucket, {})
                limits[month] = int(limit_str)
        else:
            limit = int(limit_str) if limit_str else _get_relay_limit()
            usage, window = _load_community_window(limit)
            window["calls"] = max(0, used)
            window["limit"] = max(1, limit)
            usage["relay"] = window
        _save_usage(usage)
    except Exception:
        pass


def _load_fetch_stats() -> Dict[str, Any]:
    usage = _load_usage()
    stats = usage.get("fetch_stats")
    return stats if isinstance(stats, dict) else {}


def _save_fetch_stats(stats: Dict[str, Any]) -> None:
    usage = _load_usage()
    usage["fetch_stats"] = stats
    _save_usage(usage)


def record_fetch_cycle_stats(*metas: Dict[str, Any]) -> None:
    valid = [meta for meta in metas if isinstance(meta, dict)]
    if not valid:
        return

    total_pages = sum(int(meta.get("pages_fetched", 0) or 0) for meta in valid)
    directions = max(1, len(valid))
    dates_touched = 0
    for meta in valid:
        touched = meta.get("dates_touched") or []
        if isinstance(touched, list):
            dates_touched = max(dates_touched, len(touched))

    entry = {
        "ts": _utc_now().isoformat(),
        "pages_total": total_pages,
        "directions": directions,
        "pages_per_direction": round(total_pages / directions, 3),
        "dates_touched": max(1, dates_touched),
        "page_size": DEFAULT_PAGE_SIZE,
    }
    stats = _load_fetch_stats()
    history = stats.get("history")
    if not isinstance(history, list):
        history = []
    history.append(entry)
    stats["history"] = history[-_FETCH_STATS_MAX_SAMPLES:]
    stats["last"] = entry
    _save_fetch_stats(stats)


def _recent_fetch_metrics(default_dates_touched: int) -> Dict[str, Any]:
    stats = _load_fetch_stats()
    history = stats.get("history")
    default_pages_per_direction = float(
        max(1, default_dates_touched * DEFAULT_PRODUCTION_PAGES_PER_DATE)
    )
    if not isinstance(history, list) or not history:
        return {
            "samples": 0,
            "avg_pages_per_direction": default_pages_per_direction,
            "avg_dates_touched": max(1, default_dates_touched),
        }

    entries = [entry for entry in history if isinstance(entry, dict)]
    if not entries:
        return {
            "samples": 0,
            "avg_pages_per_direction": default_pages_per_direction,
            "avg_dates_touched": max(1, default_dates_touched),
        }

    avg_pages_per_direction = sum(float(entry.get("pages_per_direction", 0.0) or 0.0) for entry in entries) / len(entries)
    avg_dates_touched = sum(int(entry.get("dates_touched", default_dates_touched) or default_dates_touched) for entry in entries) / len(entries)
    return {
        "samples": len(entries),
        "avg_pages_per_direction": max(float(default_dates_touched), avg_pages_per_direction),
        "avg_dates_touched": max(1, round(avg_dates_touched)),
    }


def _client_status_url() -> str:
    return relay_root_url(_get_relay_url()) + "/v1/client/status"


def _relay_schedule_url() -> str:
    return relay_schedule_url(_get_relay_url())


def _relay_uses_shared_schedule(source: Optional[str] = None) -> bool:
    source_name = (source or "real").strip().lower() or "real"
    if source_name == "virtual":
        return False
    if _has_enabled_byok_key():
        return False
    if _has_activation_token():
        return True
    return not _has_community_api_key()


def _load_relay_snapshot_info() -> Dict[str, Any]:
    usage = _load_usage()
    snapshot = usage.get("relay_snapshot")
    return snapshot if isinstance(snapshot, dict) else {}


def _save_relay_snapshot_info(snapshot: Dict[str, Any]) -> None:
    usage = _load_usage()
    usage["relay_snapshot"] = snapshot
    _save_usage(usage)


def _sync_relay_schedule_snapshot(
    payload: Dict[str, Any],
    *,
    airport_iata: str,
    timezone_name: str,
    display_grace_minutes: int,
    display_horizon_hours: int,
) -> None:
    if not isinstance(payload, dict):
        return
    meta = payload.get("meta")
    snapshot = {
        "generated_at": str(payload.get("generated_at") or ""),
        "cache_state": str(payload.get("cache_state") or ""),
        "provider": str(payload.get("provider") or "aviationstack"),
        "meta": meta if isinstance(meta, dict) else {},
        "airport_iata": airport_iata.upper().strip(),
        "timezone": timezone_name,
        "display_grace_minutes": int(display_grace_minutes),
        "display_horizon_hours": int(display_horizon_hours),
    }
    _save_relay_snapshot_info(snapshot)


def _fetch_managed_status(timeout_s: int = 8) -> Dict[str, Any]:
    from localflight.storage.install import get_install_id
    from localflight.sources.web.relay_heartbeat import relay_client_metadata

    token = _get_activation_token()
    if not token:
        return {"ok": False, "error": "No activation token configured"}

    now_ts = datetime.now(timezone.utc).timestamp()
    cached = _managed_status_cache
    if (
        cached.get("data") is not None
        and cached.get("token") == token
        and (now_ts - float(cached.get("ts") or 0.0)) < _MANAGED_STATUS_CACHE_TTL_S
    ):
        data = cached.get("data")
        if isinstance(data, dict):
            return data

    try:
        response = requests.get(
            _client_status_url(),
            params={"install_id": get_install_id(), "activation_token": token, **relay_client_metadata()},
            headers={"Accept": "application/json", "User-Agent": "local-flight/1.0 (+https://localflight.invalid)"},
            timeout=timeout_s,
        )
    except requests.RequestException as exc:
        data = {"ok": False, "error": f"Managed relay status failed: {exc}"}
        _managed_status_cache.update({"ts": now_ts, "token": token, "data": data})
        return data

    try:
        payload = response.json()
    except Exception as exc:
        data = {"ok": False, "error": f"Managed relay status was not valid JSON: {exc}"}
        _managed_status_cache.update({"ts": now_ts, "token": token, "data": data})
        return data

    if response.status_code >= 400:
        detail = payload.get("detail") if isinstance(payload, dict) else None
        data = {"ok": False, "error": str(detail or f"Managed relay HTTP {response.status_code}")}
        _managed_status_cache.update({"ts": now_ts, "token": token, "data": data})
        return data

    data = payload if isinstance(payload, dict) else {"ok": False, "error": "Managed relay status shape invalid"}
    if "ok" not in data:
        data["ok"] = True
    _managed_status_cache.update({"ts": now_ts, "token": token, "data": data})
    return data


def _active_mode(source: Optional[str]) -> str:
    source_name = (source or "real").strip().lower() or "real"
    if source_name == "virtual":
        return "virtual"
    if _has_enabled_byok_key():
        return "byok"
    if _has_activation_token():
        return "managed"
    return "community"


def _request_json(
    url: str,
    *,
    params: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
    timeout_s: int,
) -> Dict[str, Any]:
    try:
        response = requests.get(
            url,
            params=params,
            headers=headers
            or {
                "User-Agent": "local-flight/1.0 (+https://localflight.invalid)",
                "Accept": "application/json",
            },
            timeout=timeout_s,
        )
    except requests.RequestException as exc:
        raise AviationstackError(f"Request failed: {exc}") from exc

    if response.status_code == 429:
        raise AviationstackBudgetExceeded("Community relay quota exceeded.")
    if response.status_code >= 400:
        msg = f"HTTP {response.status_code}"
        try:
            payload = response.json()
            error = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(error, dict):
                msg += f" ({error.get('code')}): {error.get('info')}"
        except Exception:
            pass
        raise AviationstackError(msg)

    try:
        data = response.json()
    except Exception as exc:
        raise AviationstackError(f"Response was not valid JSON: {exc}") from exc
    return {"data": data, "headers": response.headers}


def _route_params(
    *,
    airport_iata: str,
    limit: int,
    mode: str,
    dep_iata: Optional[str],
    arr_iata: Optional[str],
    flight_date: Optional[str] = None,
    offset: int = 0,
) -> Dict[str, Any]:
    airport = airport_iata.upper().strip()
    if not airport:
        raise AviationstackError("airport_iata is empty")

    dep = dep_iata.upper().strip() if dep_iata else None
    arr = arr_iata.upper().strip() if arr_iata else None
    if dep is None and arr is None:
        if mode == "departures":
            dep = airport
        else:
            arr = airport

    params: Dict[str, Any] = {"limit": int(limit)}
    if int(offset) > 0:
        params["offset"] = int(offset)
    if flight_date:
        params["flight_date"] = str(flight_date).strip()
    if dep:
        params["dep_iata"] = dep
    if arr:
        params["arr_iata"] = arr
    return params


def _fetch_byok(
    *,
    airport_iata: str,
    limit: int,
    mode: str,
    dep_iata: Optional[str],
    arr_iata: Optional[str],
    flight_date: Optional[str],
    offset: int,
    timeout_s: int,
) -> Dict[str, Any]:
    if not _is_enabled():
        raise AviationstackError(
            "AviationStack client is disabled. Set LOCALFLIGHT_AVIATIONSTACK_ENABLED=1 to enable."
        )

    _increment_budget("aviationstack", _get_byok_limit())
    params = _route_params(
        airport_iata=airport_iata,
        limit=limit,
        mode=mode,
        dep_iata=dep_iata,
        arr_iata=arr_iata,
        flight_date=flight_date,
        offset=offset,
    )
    params["access_key"] = _get_api_key()
    result = _request_json(AVIATIONSTACK_BASE_URL, params=params, timeout_s=timeout_s)
    data = result["data"]
    if not isinstance(data, dict) or "data" not in data:
        raise AviationstackError("AviationStack response missing 'data' field")
    return data


def _fetch_community_direct(
    *,
    airport_iata: str,
    limit: int,
    mode: str,
    dep_iata: Optional[str],
    arr_iata: Optional[str],
    flight_date: Optional[str],
    offset: int,
    timeout_s: int,
) -> Dict[str, Any]:
    _increment_community_budget(_get_relay_limit())
    params = _route_params(
        airport_iata=airport_iata,
        limit=limit,
        mode=mode,
        dep_iata=dep_iata,
        arr_iata=arr_iata,
        flight_date=flight_date,
        offset=offset,
    )
    params["access_key"] = _get_community_api_key()
    result = _request_json(AVIATIONSTACK_BASE_URL, params=params, timeout_s=timeout_s)
    data = result["data"]
    if not isinstance(data, dict) or "data" not in data:
        raise AviationstackError("Community schedule response missing 'data' field")
    return data


def _fetch_relay(
    *,
    airport_iata: str,
    limit: int,
    mode: str,
    dep_iata: Optional[str],
    arr_iata: Optional[str],
    flight_date: Optional[str],
    offset: int,
    timeout_s: int,
) -> Dict[str, Any]:
    from localflight.storage.install import get_install_id
    from localflight.sources.web.relay_heartbeat import relay_client_metadata

    params = _route_params(
        airport_iata=airport_iata,
        limit=limit,
        mode=mode,
        dep_iata=dep_iata,
        arr_iata=arr_iata,
        flight_date=flight_date,
        offset=offset,
    )
    params["install_id"] = get_install_id()
    params.update(relay_client_metadata())
    activation_token = _get_activation_token()
    if activation_token:
        params["activation_token"] = activation_token
    else:
        _increment_community_budget(_get_relay_limit())

    result = _request_json(_get_relay_url(), params=params, timeout_s=timeout_s)
    _sync_relay_quota_from_headers(result["headers"])
    data = result["data"]
    if not isinstance(data, dict) or "data" not in data:
        raise AviationstackError("Community relay response missing 'data' field")
    return data


def fetch_relay_schedule_records(
    *,
    airport_iata: str,
    timezone_name: str,
    display_grace_minutes: int = DEFAULT_DISPLAY_GRACE_MINUTES,
    display_horizon_hours: int = DEFAULT_DISPLAY_HORIZON_HOURS,
    refresh_seconds: int = 3600,
    timeout_s: int = 60,
    return_meta: bool = False,
) -> Any:
    from localflight.storage.install import get_install_id
    from localflight.sources.web.relay_heartbeat import relay_client_metadata

    params: Dict[str, Any] = {
        "airport_iata": airport_iata.upper().strip(),
        "timezone": timezone_name,
        "display_grace_minutes": int(display_grace_minutes),
        "display_horizon_hours": int(display_horizon_hours),
        "refresh_seconds": int(refresh_seconds),
        "install_id": get_install_id(),
    }
    params.update(relay_client_metadata())
    activation_token = _get_activation_token()
    if activation_token:
        params["activation_token"] = activation_token
    else:
        _increment_community_budget(_get_relay_limit())

    result = _request_json(_relay_schedule_url(), params=params, timeout_s=timeout_s)
    _sync_relay_quota_from_headers(result["headers"])
    data = result["data"]
    if not isinstance(data, dict):
        raise AviationstackError("Community relay schedule response was invalid")
    records = data.get("records")
    if not isinstance(records, list):
        raise AviationstackError("Community relay schedule response missing canonical records")
    _sync_relay_schedule_snapshot(
        data,
        airport_iata=airport_iata,
        timezone_name=timezone_name,
        display_grace_minutes=display_grace_minutes,
        display_horizon_hours=display_horizon_hours,
    )
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    meta = dict(meta)
    meta["cache_state"] = str(data.get("cache_state") or "")
    meta["generated_at"] = str(data.get("generated_at") or "")
    meta["provider"] = str(data.get("provider") or "aviationstack")
    if return_meta:
        return records, meta
    return records


def fetch_flights_once(
    *,
    airport_iata: str,
    limit: int = 10,
    mode: Literal["departures", "arrivals"] = "departures",
    dep_iata: Optional[str] = None,
    arr_iata: Optional[str] = None,
    flight_date: Optional[str] = None,
    offset: int = 0,
    timeout_s: int = 20,
) -> Dict[str, Any]:
    """
    Fetch one page of flight data.

    Routing:
      - Enabled AVIATIONSTACK_API_KEY -> direct BYOK
      - Activation token present      -> managed relay
      - Local community key present   -> local community direct
      - Otherwise                     -> community relay
    """
    if _has_enabled_byok_key():
        return _fetch_byok(
            airport_iata=airport_iata,
            limit=limit,
            mode=mode,
            dep_iata=dep_iata,
            arr_iata=arr_iata,
            flight_date=flight_date,
            offset=offset,
            timeout_s=timeout_s,
        )
    if _has_activation_token():
        return _fetch_relay(
            airport_iata=airport_iata,
            limit=limit,
            mode=mode,
            dep_iata=dep_iata,
            arr_iata=arr_iata,
            flight_date=flight_date,
            offset=offset,
            timeout_s=timeout_s,
        )
    if _has_community_api_key():
        return _fetch_community_direct(
            airport_iata=airport_iata,
            limit=limit,
            mode=mode,
            dep_iata=dep_iata,
            arr_iata=arr_iata,
            flight_date=flight_date,
            offset=offset,
            timeout_s=timeout_s,
        )
    return _fetch_relay(
        airport_iata=airport_iata,
        limit=limit,
        mode=mode,
        dep_iata=dep_iata,
        arr_iata=arr_iata,
        flight_date=flight_date,
        offset=offset,
        timeout_s=timeout_s,
    )


def _page_rows(payload: Dict[str, Any]) -> list[Dict[str, Any]]:
    rows = payload.get("data") if isinstance(payload, dict) else None
    return list(rows) if isinstance(rows, list) else []


def _combine_payloads(payloads: list[Dict[str, Any]]) -> Dict[str, Any]:
    rows: list[Dict[str, Any]] = []
    last_pagination: Dict[str, Any] = {}
    for payload in payloads:
        rows.extend(_page_rows(payload))
        pagination = payload.get("pagination") if isinstance(payload, dict) else None
        if isinstance(pagination, dict):
            last_pagination = pagination
    pagination = dict(last_pagination)
    pagination["count"] = len(rows)
    pagination["limit"] = len(rows)
    pagination["offset"] = 0
    if not pagination.get("total"):
        pagination["total"] = len(rows)
    return {"pagination": pagination, "data": rows}


def _row_best_time_for_mode(row: Dict[str, Any], mode: str) -> Optional[datetime]:
    block_name = "departure" if mode == "departures" else "arrival"
    block = row.get(block_name) if isinstance(row, dict) else None
    if not isinstance(block, dict):
        return None
    for key in ("actual", "estimated", "scheduled"):
        value = _parse_utc(block.get(key))
        if value is not None:
            return value
    return None


def _scope_latest_time(payloads: list[Dict[str, Any]], mode: str) -> Optional[datetime]:
    latest: Optional[datetime] = None
    for payload in payloads:
        for row in _page_rows(payload):
            candidate = _row_best_time_for_mode(row, mode)
            if candidate is not None and (latest is None or candidate > latest):
                latest = candidate
    return latest


def _scope_display_target_end(
    *,
    window: Any,
    flight_date: Optional[str],
) -> Optional[datetime]:
    if not flight_date:
        return None
    try:
        scope_date = date.fromisoformat(str(flight_date))
    except Exception:
        return None

    display_start_date = window.display_start.date()
    display_end_date = window.display_end.date()
    if scope_date < display_start_date or scope_date > display_end_date:
        return None

    tz = window.local_now.tzinfo
    if scope_date == display_end_date:
        return window.display_end.astimezone(timezone.utc)

    target_local = datetime.combine(scope_date, dt_time.max, tzinfo=tz)
    return target_local.astimezone(timezone.utc)


def _rows_within_window(
    rows: list[Dict[str, Any]],
    mode: str,
    *,
    window_start_utc: datetime,
    window_end_utc: datetime,
) -> int:
    count = 0
    for row in rows:
        candidate = _row_best_time_for_mode(row, mode)
        if candidate is not None and window_start_utc <= candidate <= window_end_utc:
            count += 1
    return count


def _merge_scope_counts(
    first: Dict[str, Any],
    second: Dict[str, Any],
) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for source in (first, second):
        for key, value in (source or {}).items():
            merged[key] = int(merged.get(key, 0) or 0) + int(value or 0)
    return merged


def _merge_fetch_meta(primary: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(primary)
    merged["pages_requested"] = int(primary.get("pages_requested", 0) or 0) + int(
        extra.get("pages_requested", 0) or 0
    )
    merged["pages_fetched"] = int(primary.get("pages_fetched", 0) or 0) + int(
        extra.get("pages_fetched", 0) or 0
    )
    merged["raw_rows"] = int(primary.get("raw_rows", 0) or 0) + int(extra.get("raw_rows", 0) or 0)
    merged["adaptive_extra_pages"] = int(primary.get("adaptive_extra_pages", 0) or 0) + int(
        extra.get("adaptive_extra_pages", 0) or 0
    )
    merged["planned_dates"] = sorted(
        {
            *list(primary.get("planned_dates") or []),
            *list(extra.get("planned_dates") or []),
        }
    )
    merged["dates_touched"] = sorted(
        {
            *list(primary.get("dates_touched") or []),
            *list(extra.get("dates_touched") or []),
        }
    )
    merged["pages_by_scope"] = _merge_scope_counts(
        primary.get("pages_by_scope") or {},
        extra.get("pages_by_scope") or {},
    )
    merged["rows_by_scope"] = _merge_scope_counts(
        primary.get("rows_by_scope") or {},
        extra.get("rows_by_scope") or {},
    )
    return merged


def _fetch_request_plan(
    requests_plan: list[AviationstackFetchRequest],
    *,
    timeout_s: int,
    adaptive_scope_targets: Optional[dict[tuple[str, str], datetime]] = None,
    max_pages_per_scope: Optional[int] = None,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    payloads: list[Dict[str, Any]] = []
    payloads_by_scope: dict[tuple[str, str], list[Dict[str, Any]]] = {}
    pages_by_scope: dict[tuple[str, str], int] = {}
    rows_by_scope: dict[tuple[str, str], int] = {}
    skip_scopes: set[tuple[str, str]] = set()
    executed: list[AviationstackFetchRequest] = []
    scope_templates: dict[tuple[str, str], AviationstackFetchRequest] = {}
    adaptive_extra_pages = 0

    for req in requests_plan:
        scope_key = req.scope_key
        scope_templates.setdefault(scope_key, req)
        if scope_key in skip_scopes:
            continue

        payload = fetch_flights_once(
            airport_iata=req.airport_iata,
            limit=req.limit,
            mode=req.mode,
            dep_iata=req.dep_iata,
            arr_iata=req.arr_iata,
            flight_date=req.flight_date,
            offset=req.offset,
            timeout_s=timeout_s,
        )
        payloads.append(payload)
        payloads_by_scope.setdefault(scope_key, []).append(payload)
        executed.append(req)

        page_rows = _page_rows(payload)
        pages_by_scope[scope_key] = pages_by_scope.get(scope_key, 0) + 1
        rows_by_scope[scope_key] = rows_by_scope.get(scope_key, 0) + len(page_rows)
        if len(page_rows) < req.limit:
            skip_scopes.add(scope_key)

    if adaptive_scope_targets:
        for scope_key, target_end in adaptive_scope_targets.items():
            if scope_key in skip_scopes:
                continue
            template = scope_templates.get(scope_key)
            if template is None:
                continue
            fetched_pages = pages_by_scope.get(scope_key, 0)
            if fetched_pages <= 0:
                continue
            cap = max_pages_per_scope if max_pages_per_scope is not None else fetched_pages
            while fetched_pages < cap:
                scope_payloads = payloads_by_scope.get(scope_key, [])
                latest = _scope_latest_time(scope_payloads, template.mode)
                if latest is not None and latest >= target_end:
                    break
                last_payload = scope_payloads[-1] if scope_payloads else {}
                last_page_rows = _page_rows(last_payload)
                if len(last_page_rows) < template.limit:
                    skip_scopes.add(scope_key)
                    break

                req = AviationstackFetchRequest(
                    airport_iata=template.airport_iata,
                    mode=template.mode,
                    flight_date=template.flight_date,
                    offset=fetched_pages * template.limit,
                    limit=template.limit,
                    dep_iata=template.dep_iata,
                    arr_iata=template.arr_iata,
                    date_index=template.date_index,
                    page_index=fetched_pages,
                )
                payload = fetch_flights_once(
                    airport_iata=req.airport_iata,
                    limit=req.limit,
                    mode=req.mode,
                    dep_iata=req.dep_iata,
                    arr_iata=req.arr_iata,
                    flight_date=req.flight_date,
                    offset=req.offset,
                    timeout_s=timeout_s,
                )
                payloads.append(payload)
                payloads_by_scope.setdefault(scope_key, []).append(payload)
                executed.append(req)
                adaptive_extra_pages += 1

                page_rows = _page_rows(payload)
                fetched_pages += 1
                pages_by_scope[scope_key] = fetched_pages
                rows_by_scope[scope_key] = rows_by_scope.get(scope_key, 0) + len(page_rows)
                if len(page_rows) < req.limit:
                    skip_scopes.add(scope_key)
                    break

    touched_dates = sorted({req.flight_date for req in executed if req.flight_date})
    planned_dates = sorted({req.flight_date for req in requests_plan if req.flight_date})
    combined = _combine_payloads(payloads)
    meta = {
        "pages_requested": len(requests_plan),
        "pages_fetched": len(executed),
        "pages_by_scope": {
            f"{mode}:{flight_date or 'undated'}": count
            for (mode, flight_date), count in pages_by_scope.items()
        },
        "raw_rows": len(combined.get("data") or []),
        "planned_dates": planned_dates,
        "dates_touched": touched_dates,
        "rows_by_scope": {
            f"{mode}:{flight_date or 'undated'}": count
            for (mode, flight_date), count in rows_by_scope.items()
        },
        "adaptive_extra_pages": adaptive_extra_pages,
    }
    return combined, meta


def fetch_flights_strategy(
    *,
    airport_iata: str,
    timezone_name: str,
    mode: Literal["departures", "arrivals"] = "departures",
    strategy: Literal["baseline", "paginated", "fair"] = "fair",
    display_grace_minutes: int = DEFAULT_DISPLAY_GRACE_MINUTES,
    display_horizon_hours: int = DEFAULT_DISPLAY_HORIZON_HOURS,
    page_size: int = DEFAULT_PAGE_SIZE,
    pages_per_date: Optional[int] = None,
    timeout_s: int = 20,
    now: Optional[datetime] = None,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    page_cap = int(
        pages_per_date
        if pages_per_date is not None
        else (1 if strategy == "baseline" else DEFAULT_PRODUCTION_PAGES_PER_DATE)
    )
    if strategy == "fair":
        effective_page_cap = page_cap
        window = build_fetch_window(
            timezone_name=timezone_name,
            now=now,
            display_grace_minutes=display_grace_minutes,
            display_horizon_hours=display_horizon_hours,
            fetch_past_hours=DEFAULT_FETCH_PAST_HOURS,
            fetch_future_hours=DEFAULT_FETCH_FUTURE_HOURS,
        )
        requests_plan = build_fetch_plan(
            airport_iata=airport_iata,
            mode=mode,
            timezone_name=timezone_name,
            now=now,
            display_grace_minutes=display_grace_minutes,
            display_horizon_hours=display_horizon_hours,
            fetch_past_hours=DEFAULT_FETCH_PAST_HOURS,
            fetch_future_hours=DEFAULT_FETCH_FUTURE_HOURS,
            page_size=page_size,
            pages_per_date=page_cap,
        )
        adaptive_scope_targets = {
            req.scope_key: target
            for req in requests_plan
            if (target := _scope_display_target_end(window=window, flight_date=req.flight_date)) is not None
        }
    else:
        effective_page_cap = 1 if strategy == "baseline" else page_cap
        requests_plan = build_undated_plan(
            airport_iata=airport_iata,
            mode=mode,
            page_size=page_size,
            page_cap=effective_page_cap,
        )
        adaptive_scope_targets = None

    combined, meta = _fetch_request_plan(
        requests_plan,
        timeout_s=timeout_s,
        adaptive_scope_targets=adaptive_scope_targets,
        max_pages_per_scope=_MAX_FAIR_PAGES_PER_DATE if strategy == "fair" else None,
    )
    if strategy == "fair":
        display_start_utc = window.display_start.astimezone(timezone.utc)
        display_end_utc = window.display_end.astimezone(timezone.utc)
        if _rows_within_window(
            _page_rows(combined),
            mode,
            window_start_utc=display_start_utc,
            window_end_utc=display_end_utc,
        ) == 0:
            fallback_payload, fallback_meta = _fetch_request_plan(
                build_undated_plan(
                    airport_iata=airport_iata,
                    mode=mode,
                    page_size=page_size,
                    page_cap=effective_page_cap,
                ),
                timeout_s=timeout_s,
                adaptive_scope_targets={(mode, ""): display_end_utc},
                max_pages_per_scope=_MAX_FAIR_PAGES_PER_DATE,
            )
            if _page_rows(fallback_payload):
                combined = _combine_payloads([combined, fallback_payload])
                meta = _merge_fetch_meta(meta, fallback_meta)
                meta["undated_fallback_used"] = True
                meta["undated_fallback_pages_fetched"] = int(
                    fallback_meta.get("pages_fetched", 0) or 0
                )
                meta["undated_fallback_adaptive_extra_pages"] = int(
                    fallback_meta.get("adaptive_extra_pages", 0) or 0
                )
            else:
                meta["undated_fallback_used"] = False
    meta.update(
        {
            "strategy": strategy,
            "page_size": min(DEFAULT_PAGE_SIZE, max(1, int(page_size))),
            "page_cap": max(1, effective_page_cap),
            "mode": mode,
            "airport_iata": airport_iata.upper().strip(),
        }
    )
    return combined, meta


def fetch_flights_windowed(
    *,
    airport_iata: str,
    timezone_name: str,
    mode: Literal["departures", "arrivals"] = "departures",
    display_grace_minutes: int = DEFAULT_DISPLAY_GRACE_MINUTES,
    display_horizon_hours: int = DEFAULT_DISPLAY_HORIZON_HOURS,
    page_size: int = DEFAULT_PAGE_SIZE,
    pages_per_date: int = DEFAULT_PRODUCTION_PAGES_PER_DATE,
    timeout_s: int = 20,
    now: Optional[datetime] = None,
    return_meta: bool = False,
) -> Any:
    payload, meta = fetch_flights_strategy(
        airport_iata=airport_iata,
        timezone_name=timezone_name,
        mode=mode,
        strategy="fair",
        display_grace_minutes=display_grace_minutes,
        display_horizon_hours=display_horizon_hours,
        page_size=page_size,
        pages_per_date=pages_per_date,
        timeout_s=timeout_s,
        now=now,
    )
    if return_meta:
        return payload, meta
    return payload


def estimate_schedule_cost(source: Optional[str] = None) -> Dict[str, Any]:
    source_name = (source or "real").strip().lower() or "real"
    if source_name == "virtual":
        return {
            "enabled": False,
            "usage_model": "virtual",
            "dates_touched": 0,
            "page_size": DEFAULT_PAGE_SIZE,
            "recent_avg_pages_per_direction": 0.0,
            "estimated_calls_per_refresh": 0,
            "estimated_calls_per_month": 0,
            "refreshes_per_30_days": 0,
            "cadence_warning": "",
        }

    try:
        from localflight.storage.config import load_config

        cfg = load_config()
    except Exception:
        cfg = None

    timezone_name = getattr(cfg, "timezone", "UTC")
    display_grace_minutes = getattr(cfg, "display_grace_minutes", DEFAULT_DISPLAY_GRACE_MINUTES)
    display_horizon_hours = getattr(cfg, "display_horizon_hours", DEFAULT_DISPLAY_HORIZON_HOURS)
    refresh_seconds = getattr(cfg, "refresh_seconds", 3600)

    dates_touched = max(
        1,
        window_date_count(
            timezone_name=timezone_name,
            display_grace_minutes=display_grace_minutes,
            display_horizon_hours=display_horizon_hours,
            fetch_past_hours=DEFAULT_FETCH_PAST_HOURS,
            fetch_future_hours=DEFAULT_FETCH_FUTURE_HOURS,
        ),
    )
    recent = _recent_fetch_metrics(dates_touched)
    avg_pages_per_direction = min(
        float(dates_touched * _MAX_FAIR_PAGES_PER_DATE),
        max(
            float(dates_touched * DEFAULT_PRODUCTION_PAGES_PER_DATE),
            float(
                recent.get(
                    "avg_pages_per_direction",
                    dates_touched * DEFAULT_PRODUCTION_PAGES_PER_DATE,
                )
                or (dates_touched * DEFAULT_PRODUCTION_PAGES_PER_DATE)
            ),
        ),
    )
    estimated_calls_per_refresh = max(2 * dates_touched, int(math.ceil(avg_pages_per_direction * 2)))
    refreshes_per_30_days = max(1, math.ceil((30 * 24 * 3600) / max(1, int(refresh_seconds))))
    estimated_calls_per_month = estimated_calls_per_refresh * refreshes_per_30_days

    usage_model = "shared_relay" if _relay_uses_shared_schedule(source_name) else "direct"
    limit = 0
    active_mode = _active_mode(source_name)
    if active_mode == "community":
        limit = _get_relay_limit()
    elif active_mode == "byok":
        limit = _get_byok_limit()
    elif active_mode == "managed":
        limit = _managed_schedule_limit_fallback()

    cadence_warning = ""
    if usage_model == "shared_relay":
        cadence_warning = (
            "Relay-backed mode shares upstream fetches by airport/window. "
            "This install budget counts relay accesses, not raw AviationStack pulls."
        )
    elif limit > 0 and estimated_calls_per_month > limit:
        cadence_warning = (
            f"At the current refresh cadence, fair-fetch may use about "
            f"{estimated_calls_per_month} schedule calls in 30 days against a limit of {limit}."
        )

    return {
        "enabled": True,
        "usage_model": usage_model,
        "dates_touched": dates_touched,
        "page_size": DEFAULT_PAGE_SIZE,
        "pages_per_date_cap": DEFAULT_PRODUCTION_PAGES_PER_DATE,
        "recent_avg_pages_per_direction": round(avg_pages_per_direction, 2),
        "recent_samples": int(recent.get("samples", 0) or 0),
        "estimated_calls_per_refresh": estimated_calls_per_refresh,
        "estimated_calls_per_month": estimated_calls_per_month,
        "refreshes_per_30_days": refreshes_per_30_days,
        "cadence_warning": cadence_warning,
    }


def get_usage_stats(source: Optional[str] = None) -> Dict[str, Any]:
    month = _month_key()
    source_name = (source or "real").strip().lower() or "real"
    activation_token = _get_activation_token()
    active_mode = _active_mode(source_name)
    community_transport = "local_key" if _has_community_api_key() else "relay"
    shared_relay = _relay_uses_shared_schedule(source_name)
    cfg = None
    try:
        from localflight.storage.config import load_config

        cfg = load_config()
    except Exception:
        cfg = None

    usage = _load_usage()
    _, community_window = _load_community_window(_get_relay_limit())
    relay_managed_limits = usage.get("relay_managed_limits", {})
    community_limit = int(community_window.get("limit", _get_relay_limit()) or _get_relay_limit())
    community_calls = int(community_window.get("calls", 0) or 0)
    managed_limit = int(relay_managed_limits.get(month, _managed_schedule_limit_fallback()) or _managed_schedule_limit_fallback())
    managed_calls = int(usage.get("relay_managed", {}).get(month, 0) or 0)
    byok_limit = _get_byok_limit()
    byok_calls = int(usage.get("aviationstack", {}).get(month, 0) or 0)
    cost_estimate = estimate_schedule_cost(source_name)
    cached_snapshot = _load_relay_snapshot_info()

    managed_status = _fetch_managed_status() if activation_token else {"ok": False}
    if managed_status.get("ok"):
        limits = managed_status.get("limits") or {}
        try:
            managed_limit = int(limits.get("schedule") or managed_limit)
        except Exception:
            pass

    managed_status_snapshot = managed_status.get("schedule_cache")
    if not cached_snapshot and isinstance(managed_status_snapshot, dict) and managed_status_snapshot:
        cached_snapshot = {
            "generated_at": str(managed_status_snapshot.get("generated_at") or ""),
            "cache_state": str(managed_status_snapshot.get("cache_state") or ""),
            "provider": str(managed_status_snapshot.get("provider") or "aviationstack"),
            "meta": managed_status_snapshot.get("meta") if isinstance(managed_status_snapshot.get("meta"), dict) else {},
        }

    shared_snapshot = cached_snapshot if (shared_relay and isinstance(cached_snapshot, dict) and cached_snapshot) else {}
    if shared_snapshot and cfg is not None:
        if (
            str(shared_snapshot.get("airport_iata") or "").upper().strip() != str(getattr(cfg, "airport_iata", "")).upper().strip()
            or str(shared_snapshot.get("timezone") or "").strip() != str(getattr(cfg, "timezone", "")).strip()
            or int(shared_snapshot.get("display_grace_minutes", -1) or -1) != int(getattr(cfg, "display_grace_minutes", -2))
            or int(shared_snapshot.get("display_horizon_hours", -1) or -1) != int(getattr(cfg, "display_horizon_hours", -2))
        ):
            shared_snapshot = {}
    if shared_snapshot:
        meta = shared_snapshot.get("meta") if isinstance(shared_snapshot.get("meta"), dict) else {}
        shared_snapshot = {
            "generated_at": str(shared_snapshot.get("generated_at") or ""),
            "cache_state": str(shared_snapshot.get("cache_state") or ""),
            "provider": str(shared_snapshot.get("provider") or "aviationstack"),
            "meta": meta,
            "shared_stats": meta.get("shared_stats") if isinstance(meta.get("shared_stats"), dict) else {},
        }

    community = {
        "configured": True,
        "transport": community_transport,
        "relay_url": _get_relay_url(),
        "key_present": _has_community_api_key(),
        "month": f"{_COMMUNITY_WINDOW_DAYS}-day window",
        "calls_this_month": community_calls,
        "monthly_limit": community_limit,
        "remaining": max(0, community_limit - community_calls),
        "budget_ok": community_calls < community_limit,
        "period_days": int(community_window.get("period_days", _COMMUNITY_WINDOW_DAYS) or _COMMUNITY_WINDOW_DAYS),
        "period_start": community_window.get("period_start"),
        "period_end": community_window.get("period_end"),
        "cost_estimate": cost_estimate,
        "shared_snapshot": shared_snapshot if community_transport == "relay" else {},
    }
    managed = {
        "configured": bool(activation_token),
        "relay_url": _get_relay_url(),
        "token_present": bool(activation_token),
        "token_prefix": managed_status.get("token_prefix"),
        "providers": managed_status.get("providers") or {},
        "status_ok": bool(managed_status.get("ok")),
        "status_error": managed_status.get("error"),
        "month": month,
        "calls_this_month": managed_calls,
        "monthly_limit": managed_limit,
        "remaining": max(0, managed_limit - managed_calls),
        "budget_ok": managed_calls < managed_limit,
        "cost_estimate": cost_estimate,
        "shared_snapshot": shared_snapshot,
    }
    byok = {
        "configured": _has_api_key(),
        "enabled": _is_enabled(),
        "month": month,
        "calls_this_month": byok_calls,
        "monthly_limit": byok_limit,
        "ui_monthly_max": _BYOK_PLAN_MAX,
        "remaining": max(0, byok_limit - byok_calls),
        "plan_remaining": max(0, _BYOK_PLAN_MAX - byok_calls),
        "budget_ok": byok_calls < byok_limit,
        "safety_reserve": max(0, _BYOK_PLAN_MAX - byok_limit),
        "cost_estimate": cost_estimate,
    }

    if active_mode == "community":
        active_bucket = community
    elif active_mode == "managed":
        active_bucket = managed
    elif active_mode == "byok":
        active_bucket = byok
    else:
        active_bucket = {
            "calls_this_month": 0,
            "monthly_limit": 0,
            "remaining": 0,
            "budget_ok": True,
        }

    return {
        "mode": active_mode,
        "active_mode": active_mode,
        "source": source_name,
        "month": month,
        "calls_this_month": active_bucket["calls_this_month"],
        "monthly_limit": active_bucket["monthly_limit"],
        "remaining": active_bucket["remaining"],
        "budget_ok": active_bucket["budget_ok"],
        "enabled": active_mode != "virtual",
        "cost_estimate": cost_estimate,
        "shared_relay": shared_relay,
        "shared_snapshot": shared_snapshot,
        "community": community,
        "managed": managed,
        "byok": byok,
    }


def _managed_schedule_limit_fallback() -> int:
    try:
        return int(os.getenv("RELAY_MANAGED_SCHEDULE_LIMIT", "10000"))
    except (ValueError, TypeError):
        return 10000
