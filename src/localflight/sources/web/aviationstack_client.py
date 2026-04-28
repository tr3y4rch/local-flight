from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Literal, Optional

import requests
from localflight.sources.web.relay_defaults import default_public_relay_url, relay_root_url

AVIATIONSTACK_BASE_URL = "https://api.aviationstack.com/v1/flights"

_DEFAULT_BYOK_LIMIT = 90
_BYOK_PLAN_MAX = 100
_DEFAULT_RELAY_LIMIT = 50
_MANAGED_STATUS_CACHE_TTL_S = 60
_COMMUNITY_WINDOW_DAYS = 30

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


def _client_status_url() -> str:
    return relay_root_url(_get_relay_url()) + "/v1/client/status"


def _fetch_managed_status(timeout_s: int = 8) -> Dict[str, Any]:
    from localflight.storage.install import get_install_id

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
            params={"install_id": get_install_id(), "activation_token": token},
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
    timeout_s: int,
) -> Dict[str, Any]:
    _increment_community_budget(_get_relay_limit())
    params = _route_params(
        airport_iata=airport_iata,
        limit=limit,
        mode=mode,
        dep_iata=dep_iata,
        arr_iata=arr_iata,
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
    timeout_s: int,
) -> Dict[str, Any]:
    from localflight.storage.install import get_install_id

    params = _route_params(
        airport_iata=airport_iata,
        limit=limit,
        mode=mode,
        dep_iata=dep_iata,
        arr_iata=arr_iata,
    )
    params["install_id"] = get_install_id()
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


def fetch_flights_once(
    *,
    airport_iata: str,
    limit: int = 10,
    mode: Literal["departures", "arrivals"] = "departures",
    dep_iata: Optional[str] = None,
    arr_iata: Optional[str] = None,
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
            timeout_s=timeout_s,
        )
    if _has_activation_token():
        return _fetch_relay(
            airport_iata=airport_iata,
            limit=limit,
            mode=mode,
            dep_iata=dep_iata,
            arr_iata=arr_iata,
            timeout_s=timeout_s,
        )
    if _has_community_api_key():
        return _fetch_community_direct(
            airport_iata=airport_iata,
            limit=limit,
            mode=mode,
            dep_iata=dep_iata,
            arr_iata=arr_iata,
            timeout_s=timeout_s,
        )
    return _fetch_relay(
        airport_iata=airport_iata,
        limit=limit,
        mode=mode,
        dep_iata=dep_iata,
        arr_iata=arr_iata,
        timeout_s=timeout_s,
    )


def get_usage_stats(source: Optional[str] = None) -> Dict[str, Any]:
    month = _month_key()
    source_name = (source or "real").strip().lower() or "real"
    activation_token = _get_activation_token()
    active_mode = _active_mode(source_name)
    community_transport = "local_key" if _has_community_api_key() else "relay"

    usage = _load_usage()
    _, community_window = _load_community_window(_get_relay_limit())
    relay_limits = usage.get("relay_limits", {})
    relay_managed_limits = usage.get("relay_managed_limits", {})
    community_limit = int(community_window.get("limit", _get_relay_limit()) or _get_relay_limit())
    community_calls = int(community_window.get("calls", 0) or 0)
    managed_limit = int(relay_managed_limits.get(month, _managed_schedule_limit_fallback()) or _managed_schedule_limit_fallback())
    managed_calls = int(usage.get("relay_managed", {}).get(month, 0) or 0)
    byok_limit = _get_byok_limit()
    byok_calls = int(usage.get("aviationstack", {}).get(month, 0) or 0)

    managed_status = _fetch_managed_status() if activation_token else {"ok": False}
    if managed_status.get("ok"):
        limits = managed_status.get("limits") or {}
        try:
            managed_limit = int(limits.get("schedule") or managed_limit)
        except Exception:
            pass

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
        "community": community,
        "managed": managed,
        "byok": byok,
    }


def _managed_schedule_limit_fallback() -> int:
    try:
        return int(os.getenv("RELAY_MANAGED_SCHEDULE_LIMIT", "10000"))
    except (ValueError, TypeError):
        return 10000
