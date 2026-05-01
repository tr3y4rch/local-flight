from __future__ import annotations

import hashlib
import html
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import requests as _req
import uvicorn
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

AVIATIONSTACK_URL = "https://api.aviationstack.com/v1/flights"
ADSBX_URL = "https://adsbexchange-com1.p.rapidapi.com/v2"

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_AIRPORT_RE = re.compile(r"^[A-Z0-9]{2,4}$")

_SETTING_AVIATIONSTACK_KEY = "provider_aviationstack_key"
_SETTING_RAPIDAPI_KEY = "provider_rapidapi_key"
_SETTING_PROVIDER_REVISION = "provider_revision"
_SETTING_NETWORK_SECRET = "network_secret"
_REQUEST_STATUS_PENDING = "pending"
_REQUEST_STATUS_APPROVED = "approved"
_REQUEST_STATUS_REJECTED = "rejected"
_REQUEST_STATUS_ISSUED = "issued"
_REQUEST_STATUS_MANUAL_REVIEW = "manual_review"
_REQUEST_STATUS_DISMISSED = "dismissed"

_AUTO_ACTIVATION_NETWORK_DAILY_LIMIT = 6
_AUTO_ACTIVATION_NETWORK_INSTALLS_DAILY_LIMIT = 4
_SHARED_SCHEDULE_PROVIDER = "aviationstack"
_SHARED_SCHEDULE_PLANNER_VERSION = "fair-v1"
_SHARED_SCHEDULE_SCHEMA_VERSION = "canonical-raw-v1"
_SHARED_SCHEDULE_LOCK_WAIT_S = 4.0

_schedule_refresh_locks: Dict[str, threading.Lock] = {}
_schedule_refresh_locks_guard = threading.Lock()


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _public_host() -> str:
    return _normalized_host(_env("RELAY_PUBLIC_HOST", "relay.localflight.app"))


def _admin_host() -> str:
    return _normalized_host(_env("RELAY_ADMIN_HOST", "network.localflight.app"))


def _normalized_host(value: str) -> str:
    clean = (value or "").strip().lower()
    if not clean:
        return ""
    clean = clean.split(",", 1)[0].strip()
    if clean.startswith("[") and "]" in clean:
        return clean[1 : clean.index("]")]
    if clean.count(":") == 1:
        return clean.split(":", 1)[0]
    return clean


def _request_host(request: Request) -> str:
    return _normalized_host(request.headers.get("x-forwarded-host") or request.headers.get("host") or "")


def _is_local_host(host: str) -> bool:
    return host in {"", "127.0.0.1", "localhost", "::1", "0.0.0.0", "testserver"}


def _request_surface(request: Request) -> str:
    host = _request_host(request)
    if _is_local_host(host):
        return "local"
    if host == _admin_host():
        return "admin"
    return "public"


def _admin_on_public() -> bool:
    return _env("RELAY_ADMIN_ON_PUBLIC", "").lower() in {"1", "true", "yes"}


def _raw_provider_debug_enabled() -> bool:
    return _env("RELAY_ALLOW_RAW_PROVIDER_DEBUG", "").lower() in {"1", "true", "yes"}


def _surface_allows_path(surface: str, path: str) -> bool:
    if surface == "admin":
        if _raw_provider_debug_enabled() and path == "/v1/flights":
            return True
        return path in {"/", "/health", "/admin"} or path.startswith("/admin/")
    if surface == "public":
        if _admin_on_public() and (path == "/admin" or path.startswith("/admin/")):
            return True
        return path in {"/", "/health"} or path.startswith("/v1/")
    return True


def _community_schedule_limit() -> int:
    try:
        return int(_env("RELAY_COMMUNITY_SCHEDULE_LIMIT", _env("RELAY_MONTHLY_LIMIT", "50")))
    except ValueError:
        return 50


def _community_radar_limit() -> int:
    try:
        return int(_env("RELAY_RADAR_MONTHLY_LIMIT", "600"))
    except ValueError:
        return 600


def _managed_schedule_limit() -> int:
    try:
        return int(_env("RELAY_MANAGED_SCHEDULE_LIMIT", "10000"))
    except ValueError:
        return 10000


def _managed_radar_limit() -> int:
    try:
        return int(_env("RELAY_MANAGED_RADAR_LIMIT", "10000"))
    except ValueError:
        return 10000


def _radar_cache_seconds() -> int:
    try:
        return max(30, int(_env("RELAY_RADAR_CACHE_SECONDS", "300")))
    except ValueError:
        return 300


def _admin_password() -> str:
    return _env("RELAY_ADMIN_PASSWORD", "changeme")


def _db_path() -> Path:
    return Path(_env("DB_PATH", "./relay.db"))


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row["name"]) for row in rows}


def _ensure_column(conn: sqlite3.Connection, table: str, column_def: str) -> None:
    name = column_def.split()[0]
    if name not in _table_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")


def _ensure_schema() -> None:
    conn = _connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS usage (
            subject_key TEXT NOT NULL,
            service     TEXT NOT NULL,
            month       TEXT NOT NULL,
            calls       INTEGER DEFAULT 0,
            last_seen   TEXT,
            plan        TEXT NOT NULL,
            install_id  TEXT,
            PRIMARY KEY (subject_key, service, month)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS activation_tokens (
            token_hash       TEXT PRIMARY KEY,
            token_prefix     TEXT NOT NULL,
            label            TEXT,
            schedule_limit   INTEGER NOT NULL,
            radar_limit      INTEGER NOT NULL,
            created_at       TEXT NOT NULL,
            created_by       TEXT,
            bound_install_id TEXT,
            last_seen        TEXT,
            revoked_at       TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS request_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL,
            install_id  TEXT,
            airport     TEXT,
            mode        TEXT,
            status      INTEGER,
            latency_ms  INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS activation_requests (
            request_id           TEXT PRIMARY KEY,
            install_id           TEXT NOT NULL,
            install_fingerprint  TEXT NOT NULL,
            network_tag          TEXT,
            airport_iata         TEXT,
            airport_icao         TEXT,
            display_name         TEXT,
            requested_mode       TEXT,
            app_version          TEXT,
            status               TEXT NOT NULL,
            created_at           TEXT NOT NULL,
            updated_at           TEXT NOT NULL,
            last_seen            TEXT,
            decision_source      TEXT,
            decision_note        TEXT,
            token_hash           TEXT,
            token_prefix         TEXT,
            issued_token         TEXT,
            approved_at          TEXT,
            delivered_at         TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key         TEXT PRIMARY KEY,
            value       TEXT,
            updated_at  TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS blocked_installs (
            install_id   TEXT PRIMARY KEY,
            reason       TEXT,
            created_at   TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schedule_snapshots (
            cache_key               TEXT PRIMARY KEY,
            airport_iata            TEXT NOT NULL,
            timezone                TEXT NOT NULL,
            display_grace_minutes   INTEGER NOT NULL,
            display_horizon_hours   INTEGER NOT NULL,
            planner_version         TEXT NOT NULL,
            schema_version          TEXT NOT NULL,
            provider                TEXT NOT NULL,
            generated_at            TEXT NOT NULL,
            updated_at              TEXT NOT NULL,
            meta_json               TEXT NOT NULL,
            records_json            TEXT NOT NULL,
            client_accesses         INTEGER DEFAULT 0,
            upstream_pulls          INTEGER DEFAULT 0,
            refresh_count           INTEGER DEFAULT 0,
            cache_hits              INTEGER DEFAULT 0,
            stale_serves            INTEGER DEFAULT 0,
            last_cache_state        TEXT,
            last_error              TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS client_interests (
            install_id               TEXT PRIMARY KEY,
            plan                     TEXT NOT NULL,
            airport_iata             TEXT,
            timezone                 TEXT,
            display_grace_minutes    INTEGER,
            display_horizon_hours    INTEGER,
            refresh_seconds          INTEGER,
            last_seen                TEXT NOT NULL
        )
        """
    )
    _ensure_column(conn, "request_log", "service TEXT")
    _ensure_column(conn, "request_log", "plan TEXT")
    _ensure_column(conn, "activation_requests", "display_name TEXT")
    _ensure_column(conn, "activation_requests", "requested_mode TEXT")
    _ensure_column(conn, "activation_requests", "network_tag TEXT")
    _ensure_column(conn, "activation_requests", "app_version TEXT")
    _ensure_column(conn, "activation_requests", "last_seen TEXT")
    _ensure_column(conn, "activation_requests", "decision_source TEXT")
    _ensure_column(conn, "activation_requests", "decision_note TEXT")
    _ensure_column(conn, "activation_requests", "token_hash TEXT")
    _ensure_column(conn, "activation_requests", "token_prefix TEXT")
    _ensure_column(conn, "activation_requests", "issued_token TEXT")
    _ensure_column(conn, "activation_requests", "approved_at TEXT")
    _ensure_column(conn, "activation_requests", "delivered_at TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_month_service ON usage (month, service, calls DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_activation_revoked ON activation_tokens (revoked_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_activation_requests_status ON activation_requests (status, created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_log_ts ON request_log (ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_schedule_snapshots_airport ON schedule_snapshots (airport_iata, updated_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_client_interests_last_seen ON client_interests (last_seen DESC)")
    conn.commit()
    conn.close()


def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hours_ago(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _install_fingerprint(install_id: str) -> str:
    return hashlib.sha256((install_id or "").encode("utf-8")).hexdigest()[:12]


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_activation_token() -> str:
    return "lfm_" + secrets.token_urlsafe(18)


def _new_request_id() -> str:
    return "lfr_" + uuid.uuid4().hex


def _clean_airport(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    clean = value.strip().upper()
    if not _AIRPORT_RE.match(clean):
        raise HTTPException(status_code=400, detail="airport code must be 2-4 letters/numbers")
    return clean


def _validate_install_id(install_id: str) -> str:
    if not _UUID_RE.match(install_id):
        raise HTTPException(status_code=400, detail="install_id must be a UUID")
    return install_id


def _setting_get_conn(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    return str(row["value"] or default)


def _setting_set_conn(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (key, value, _utc_now()),
    )


def _network_secret(conn: Optional[sqlite3.Connection] = None) -> str:
    own_conn = conn is None
    if own_conn:
        conn = _connect()
    assert conn is not None
    value = _setting_get_conn(conn, _SETTING_NETWORK_SECRET, "")
    if not value:
        value = secrets.token_hex(32)
        _setting_set_conn(conn, _SETTING_NETWORK_SECRET, value)
        if own_conn:
            conn.commit()
    if own_conn:
        conn.close()
    return value


def _setting_delete_conn(conn: sqlite3.Connection, key: str) -> None:
    conn.execute("DELETE FROM settings WHERE key=?", (key,))


def _provider_status(
    setting_key: str,
    env_key: str,
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> tuple[str, str]:
    own_conn = False
    if conn is None:
        conn = _connect()
        own_conn = True
    try:
        stored = _setting_get_conn(conn, setting_key, "")
        if stored:
            return stored, "relay-store"
        env_value = _env(env_key)
        if env_value:
            return env_value, "env"
        return "", "missing"
    finally:
        if own_conn:
            conn.close()


def _provider_revision(conn: Optional[sqlite3.Connection] = None) -> int:
    own_conn = False
    if conn is None:
        conn = _connect()
        own_conn = True
    try:
        raw = _setting_get_conn(conn, _SETTING_PROVIDER_REVISION, "1")
        try:
            return max(1, int(raw))
        except ValueError:
            return 1
    finally:
        if own_conn:
            conn.close()


def _bump_provider_revision(conn: sqlite3.Connection) -> int:
    new_value = _provider_revision(conn) + 1
    _setting_set_conn(conn, _SETTING_PROVIDER_REVISION, str(new_value))
    return new_value


def _hmac_short(secret: str, payload: str, *, length: int = 12) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:length]


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client and request.client.host:
        return str(request.client.host)
    return ""


def _network_tag(ip: str, *, conn: Optional[sqlite3.Connection] = None) -> str:
    raw = (ip or "").strip()
    if not raw:
        return "unknown"
    secret = _network_secret(conn)
    return "net_" + _hmac_short(secret, f"net:{raw}", length=14)


def _aviationstack_key() -> str:
    key, _source = _provider_status(_SETTING_AVIATIONSTACK_KEY, "AVIATIONSTACK_API_KEY")
    if not key:
        raise RuntimeError("AviationStack provider key is not configured in relay admin or environment")
    return key


def _rapidapi_key() -> str:
    key, _source = _provider_status(_SETTING_RAPIDAPI_KEY, "RAPIDAPI_KEY")
    if not key:
        raise RuntimeError("RapidAPI ADS-B provider key is not configured in relay admin or environment")
    return key


def _mask_secret(value: str) -> str:
    if not value:
        return "missing"
    if len(value) <= 8:
        return value[:2] + ("*" * max(0, len(value) - 4)) + value[-2:]
    return value[:4] + ("*" * (len(value) - 8)) + value[-4:]


def _blocked_reason(install_id: str) -> str:
    conn = _connect()
    row = conn.execute("SELECT reason FROM blocked_installs WHERE install_id=?", (install_id,)).fetchone()
    conn.close()
    return str(row["reason"] or "").strip() if row else ""


def _ensure_install_allowed(install_id: str) -> None:
    reason = _blocked_reason(install_id)
    if reason:
        raise HTTPException(status_code=403, detail=f"Install access revoked: {reason}")


def _usage_subject(install_id: str, activation_row: Optional[sqlite3.Row]) -> str:
    if activation_row is None:
        return install_id
    return f"managed:{activation_row['token_hash']}"


def _get_usage(subject_key: str, service: str, month: str) -> int:
    conn = _connect()
    row = conn.execute(
        "SELECT calls FROM usage WHERE subject_key=? AND service=? AND month=?",
        (subject_key, service, month),
    ).fetchone()
    conn.close()
    return int(row["calls"] or 0) if row else 0


def _increment_usage(
    *,
    subject_key: str,
    service: str,
    month: str,
    plan: str,
    install_id: Optional[str],
    n_calls: int = 1,
) -> int:
    conn = _connect()
    now = _utc_now()
    conn.execute(
        """
        INSERT INTO usage (subject_key, service, month, calls, last_seen, plan, install_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(subject_key, service, month) DO UPDATE SET
            calls = calls + excluded.calls,
            last_seen = excluded.last_seen,
            plan = excluded.plan,
            install_id = excluded.install_id
        """,
        (subject_key, service, month, max(1, int(n_calls)), now, plan, install_id),
    )
    row = conn.execute(
        "SELECT calls FROM usage WHERE subject_key=? AND service=? AND month=?",
        (subject_key, service, month),
    ).fetchone()
    conn.commit()
    conn.close()
    return int(row["calls"] or 0) if row else 1


def _log_request(
    *,
    install_id: str,
    scope: str,
    status: int,
    latency_ms: int,
    service: str,
    plan: str,
) -> None:
    try:
        conn = _connect()
        conn.execute(
            """
            INSERT INTO request_log (ts, install_id, airport, mode, status, latency_ms, service, plan)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_utc_now(), install_id, None, scope, status, latency_ms, service, plan),
        )
        conn.execute("DELETE FROM request_log WHERE ts < ?", (_hours_ago(24 * 30),))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _load_activation(token: str) -> Optional[sqlite3.Row]:
    token = (token or "").strip()
    if not token:
        return None
    conn = _connect()
    row = conn.execute(
        """
        SELECT * FROM activation_tokens
        WHERE token_hash=? AND revoked_at IS NULL
        """,
        (_token_hash(token),),
    ).fetchone()
    conn.close()
    return row


def _activation_row_for_install(conn: sqlite3.Connection, install_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        """
        SELECT *
        FROM activation_tokens
        WHERE bound_install_id=? AND revoked_at IS NULL
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (install_id,),
    ).fetchone()


def _bind_activation_install(token_hash: str, install_id: str) -> None:
    conn = _connect()
    conn.execute(
        """
        UPDATE activation_tokens
        SET bound_install_id = COALESCE(bound_install_id, ?),
            last_seen = ?
        WHERE token_hash=?
        """,
        (install_id, _utc_now(), token_hash),
    )
    conn.commit()
    conn.close()


def _issue_token_for_install(
    conn: sqlite3.Connection,
    *,
    install_id: str,
    label: str,
    created_by: str,
) -> tuple[str, str, str]:
    existing = _activation_row_for_install(conn, install_id)
    token = _new_activation_token()
    if existing:
        old_hash = str(existing["token_hash"] or "")
        new_hash = _token_hash(token)
        conn.execute(
            """
            UPDATE activation_tokens
            SET token_hash=?,
                token_prefix=?,
                label=?,
                last_seen=?,
                revoked_at=NULL,
                created_by=?
            WHERE token_hash=?
            """,
            (
                new_hash,
                token[:10],
                label.strip() or str(existing["label"] or "") or None,
                _utc_now(),
                created_by,
                old_hash,
            ),
        )
        conn.execute(
            "UPDATE usage SET subject_key=? WHERE subject_key=?",
            (f"managed:{new_hash}", f"managed:{old_hash}"),
        )
        return token, token[:10], "refreshed"

    _store_activation_token(
        conn,
        token=token,
        label=label,
        schedule_limit=_managed_schedule_limit(),
        radar_limit=_managed_radar_limit(),
        created_by=created_by,
        bound_install_id=install_id,
    )
    return token, token[:10], "issued"


def _recent_activation_counts(
    conn: sqlite3.Connection,
    *,
    install_id: str,
    network_tag: str,
    hours: int = 24,
) -> Dict[str, int]:
    cutoff = _hours_ago(hours)
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS network_requests,
            COUNT(DISTINCT install_id) AS network_installs
        FROM activation_requests
        WHERE network_tag=? AND created_at>=?
        """,
        (network_tag, cutoff),
    ).fetchone()
    install_row = conn.execute(
        """
        SELECT COUNT(*) AS install_requests
        FROM activation_requests
        WHERE install_id=? AND created_at>=?
        """,
        (install_id, cutoff),
    ).fetchone()
    return {
        "network_requests": int(row["network_requests"] or 0) if row else 0,
        "network_installs": int(row["network_installs"] or 0) if row else 0,
        "install_requests": int(install_row["install_requests"] or 0) if install_row else 0,
    }


def _record_activation_event(
    conn: sqlite3.Connection,
    *,
    install_id: str,
    install_fingerprint: str,
    network_tag: str,
    display_name: str,
    requested_mode: str,
    app_version: str,
    status: str,
    decision_source: str,
    decision_note: str,
    token_hash: str = "",
    token_prefix: str = "",
) -> str:
    request_id = _new_request_id()
    now = _utc_now()
    conn.execute(
        """
        INSERT INTO activation_requests (
            request_id, install_id, install_fingerprint, network_tag, airport_iata, airport_icao,
            display_name, requested_mode, app_version, status, created_at, updated_at, last_seen,
            decision_source, decision_note, token_hash, token_prefix, issued_token
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            request_id,
            install_id,
            install_fingerprint,
            network_tag,
            None,
            None,
            display_name or None,
            requested_mode,
            app_version,
            status,
            now,
            now,
            now,
            decision_source,
            decision_note,
            token_hash or None,
            token_prefix or None,
        ),
    )
    return request_id


def _resolve_access(
    *,
    install_id: str,
    activation_token: str,
    service: str,
) -> Dict[str, Any]:
    _ensure_install_allowed(install_id)

    activation_row = _load_activation(activation_token)
    if activation_token and activation_row is None:
        raise HTTPException(status_code=403, detail="Activation token invalid or revoked")

    if activation_row is not None:
        bound_install_id = (activation_row["bound_install_id"] or "").strip()
        if bound_install_id and bound_install_id != install_id:
            raise HTTPException(status_code=403, detail="Activation token already bound to another install")
        _bind_activation_install(str(activation_row["token_hash"]), install_id)
        if service == "aviationstack":
            limit = int(activation_row["schedule_limit"] or _managed_schedule_limit())
        else:
            limit = int(activation_row["radar_limit"] or _managed_radar_limit())
        plan = "managed"
    else:
        limit = _community_schedule_limit() if service == "aviationstack" else _community_radar_limit()
        plan = "community"

    subject_key = _usage_subject(install_id, activation_row)
    return {
        "plan": plan,
        "limit": limit,
        "subject_key": subject_key,
        "activation_row": activation_row,
    }


def _quota_headers(service: str, used: int, limit: int, plan: str) -> Dict[str, str]:
    headers = {
        "X-LF-Relay-Config-Rev": str(_provider_revision()),
    }
    if service == "radar":
        headers.update(
            {
                "X-LF-Radar-Quota-Used": str(used),
                "X-LF-Radar-Quota-Limit": str(limit),
                "X-LF-Radar-Quota-Plan": plan,
            }
        )
    else:
        headers.update(
            {
                "X-LF-Quota-Used": str(used),
                "X-LF-Quota-Limit": str(limit),
                "X-LF-Quota-Plan": plan,
            }
        )
    return headers


def _schedule_cache_key(
    *,
    airport_iata: str,
    timezone_name: str,
    display_grace_minutes: int,
    display_horizon_hours: int,
) -> str:
    payload = "|".join(
        [
            airport_iata.upper().strip(),
            timezone_name.strip(),
            str(int(display_grace_minutes)),
            str(int(display_horizon_hours)),
            _SHARED_SCHEDULE_PLANNER_VERSION,
            _SHARED_SCHEDULE_SCHEMA_VERSION,
        ]
    )
    return "sch_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _parse_utc_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _schedule_ttls(refresh_seconds: int) -> tuple[int, int]:
    try:
        refresh = max(60, int(refresh_seconds))
    except Exception:
        refresh = 3600
    fresh_ttl_s = max(180, min(900, refresh // 4))
    stale_ttl_s = max(fresh_ttl_s * 4, 1800)
    return fresh_ttl_s, stale_ttl_s


def _load_json_blob(raw: Any, default: Any) -> Any:
    try:
        data = json.loads(str(raw or ""))
    except Exception:
        return default
    return data if isinstance(data, type(default)) else default


def _snapshot_age_seconds(generated_at: str) -> Optional[int]:
    dt = _parse_utc_dt(generated_at)
    if not dt:
        return None
    return max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))


def _snapshot_shared_stats(row: sqlite3.Row) -> Dict[str, Any]:
    client_accesses = int(row["client_accesses"] or 0)
    upstream_pulls = int(row["upstream_pulls"] or 0)
    refresh_count = int(row["refresh_count"] or 0)
    cache_hits = int(row["cache_hits"] or 0)
    stale_serves = int(row["stale_serves"] or 0)
    return {
        "client_accesses": client_accesses,
        "upstream_pulls": upstream_pulls,
        "refresh_count": refresh_count,
        "cache_hits": cache_hits,
        "stale_serves": stale_serves,
        "cache_hit_rate_pct": round((cache_hits / client_accesses) * 100.0, 1) if client_accesses > 0 else 0.0,
        "estimated_savings": max(0, client_accesses - refresh_count),
    }


def _snapshot_payload_from_row(row: sqlite3.Row, *, cache_state: Optional[str] = None) -> Dict[str, Any]:
    meta = _load_json_blob(row["meta_json"], {})
    records = _load_json_blob(row["records_json"], [])
    meta = dict(meta) if isinstance(meta, dict) else {}
    records = list(records) if isinstance(records, list) else []
    meta["planner_version"] = str(row["planner_version"] or _SHARED_SCHEDULE_PLANNER_VERSION)
    meta["schema_version"] = str(row["schema_version"] or _SHARED_SCHEDULE_SCHEMA_VERSION)
    meta["shared_stats"] = _snapshot_shared_stats(row)
    if row["last_error"]:
        meta["last_error"] = str(row["last_error"])
    return {
        "generated_at": str(row["generated_at"] or ""),
        "cache_state": cache_state or str(row["last_cache_state"] or "fresh"),
        "provider": str(row["provider"] or _SHARED_SCHEDULE_PROVIDER),
        "meta": meta,
        "records": records,
    }


def _snapshot_lifecycle_state(row: Optional[sqlite3.Row], *, refresh_seconds: int) -> str:
    if row is None:
        return "miss"
    age_s = _snapshot_age_seconds(str(row["generated_at"] or ""))
    if age_s is None:
        return "miss"
    fresh_ttl_s, stale_ttl_s = _schedule_ttls(refresh_seconds)
    if age_s <= fresh_ttl_s:
        return "fresh"
    if age_s <= stale_ttl_s:
        return "stale"
    return "expired"


def _get_schedule_lock(cache_key: str) -> threading.Lock:
    with _schedule_refresh_locks_guard:
        lock = _schedule_refresh_locks.get(cache_key)
        if lock is None:
            lock = threading.Lock()
            _schedule_refresh_locks[cache_key] = lock
        return lock


def _load_schedule_snapshot_conn(conn: sqlite3.Connection, cache_key: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM schedule_snapshots WHERE cache_key=?",
        (cache_key,),
    ).fetchone()


def _store_schedule_snapshot(
    *,
    cache_key: str,
    airport_iata: str,
    timezone_name: str,
    display_grace_minutes: int,
    display_horizon_hours: int,
    payload: Dict[str, Any],
    pages_fetched: int,
    last_error: str = "",
) -> None:
    conn = _connect()
    existing = _load_schedule_snapshot_conn(conn, cache_key)
    shared_stats = _snapshot_shared_stats(existing) if existing is not None else {
        "client_accesses": 0,
        "upstream_pulls": 0,
        "refresh_count": 0,
        "cache_hits": 0,
        "stale_serves": 0,
        "cache_hit_rate_pct": 0.0,
        "estimated_savings": 0,
    }
    meta = dict(payload.get("meta") or {})
    meta.pop("shared_stats", None)
    generated_at = str(payload.get("generated_at") or _utc_now())
    now_iso = _utc_now()
    conn.execute(
        """
        INSERT INTO schedule_snapshots (
            cache_key, airport_iata, timezone, display_grace_minutes, display_horizon_hours,
            planner_version, schema_version, provider, generated_at, updated_at,
            meta_json, records_json, client_accesses, upstream_pulls, refresh_count,
            cache_hits, stale_serves, last_cache_state, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(cache_key) DO UPDATE SET
            airport_iata = excluded.airport_iata,
            timezone = excluded.timezone,
            display_grace_minutes = excluded.display_grace_minutes,
            display_horizon_hours = excluded.display_horizon_hours,
            planner_version = excluded.planner_version,
            schema_version = excluded.schema_version,
            provider = excluded.provider,
            generated_at = excluded.generated_at,
            updated_at = excluded.updated_at,
            meta_json = excluded.meta_json,
            records_json = excluded.records_json,
            client_accesses = excluded.client_accesses,
            upstream_pulls = excluded.upstream_pulls,
            refresh_count = excluded.refresh_count,
            cache_hits = excluded.cache_hits,
            stale_serves = excluded.stale_serves,
            last_cache_state = excluded.last_cache_state,
            last_error = excluded.last_error
        """,
        (
            cache_key,
            airport_iata,
            timezone_name,
            int(display_grace_minutes),
            int(display_horizon_hours),
            _SHARED_SCHEDULE_PLANNER_VERSION,
            _SHARED_SCHEDULE_SCHEMA_VERSION,
            str(payload.get("provider") or _SHARED_SCHEDULE_PROVIDER),
            generated_at,
            now_iso,
            json.dumps(meta, ensure_ascii=False),
            json.dumps(list(payload.get("records") or []), ensure_ascii=False),
            int(shared_stats["client_accesses"]),
            int(shared_stats["upstream_pulls"]) + max(0, int(pages_fetched)),
            int(shared_stats["refresh_count"]) + 1,
            int(shared_stats["cache_hits"]),
            int(shared_stats["stale_serves"]),
            "fresh",
            last_error.strip(),
        ),
    )
    conn.commit()
    conn.close()


def _record_schedule_access(
    *,
    cache_key: str,
    cache_state: str,
    count_cache_hit: bool = False,
    count_stale: bool = False,
) -> None:
    conn = _connect()
    now_iso = _utc_now()
    conn.execute(
        """
        UPDATE schedule_snapshots
        SET client_accesses = client_accesses + 1,
            cache_hits = cache_hits + ?,
            stale_serves = stale_serves + ?,
            last_cache_state = ?,
            updated_at = ?
        WHERE cache_key=?
        """,
        (
            1 if count_cache_hit else 0,
            1 if count_stale else 0,
            cache_state,
            now_iso,
            cache_key,
        ),
    )
    conn.commit()
    conn.close()


def _record_client_interest(
    *,
    install_id: str,
    plan: str,
    airport_iata: str,
    timezone_name: str,
    display_grace_minutes: int,
    display_horizon_hours: int,
    refresh_seconds: int,
) -> None:
    conn = _connect()
    conn.execute(
        """
        INSERT INTO client_interests (
            install_id, plan, airport_iata, timezone, display_grace_minutes,
            display_horizon_hours, refresh_seconds, last_seen
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(install_id) DO UPDATE SET
            plan = excluded.plan,
            airport_iata = excluded.airport_iata,
            timezone = excluded.timezone,
            display_grace_minutes = excluded.display_grace_minutes,
            display_horizon_hours = excluded.display_horizon_hours,
            refresh_seconds = excluded.refresh_seconds,
            last_seen = excluded.last_seen
        """,
        (
            install_id,
            plan,
            airport_iata.upper().strip() or None,
            timezone_name.strip() or None,
            int(display_grace_minutes),
            int(display_horizon_hours),
            int(refresh_seconds),
            _utc_now(),
        ),
    )
    conn.execute("DELETE FROM client_interests WHERE last_seen < ?", (_hours_ago(24 * 30),))
    conn.commit()
    conn.close()


def _client_interest_snapshot(conn: sqlite3.Connection, install_id: str) -> Optional[Dict[str, Any]]:
    interest = conn.execute(
        """
        SELECT install_id, plan, airport_iata, timezone, display_grace_minutes,
               display_horizon_hours, refresh_seconds, last_seen
        FROM client_interests
        WHERE install_id=?
        """,
        (install_id,),
    ).fetchone()
    if not interest:
        return None
    airport_iata = str(interest["airport_iata"] or "").strip()
    timezone_name = str(interest["timezone"] or "").strip()
    if not airport_iata or not timezone_name:
        return {
            "airport_iata": airport_iata,
            "timezone": timezone_name,
            "display_grace_minutes": int(interest["display_grace_minutes"] or 0),
            "display_horizon_hours": int(interest["display_horizon_hours"] or 0),
            "refresh_seconds": int(interest["refresh_seconds"] or 0),
            "last_seen": str(interest["last_seen"] or ""),
        }
    cache_key = _schedule_cache_key(
        airport_iata=airport_iata,
        timezone_name=timezone_name,
        display_grace_minutes=int(interest["display_grace_minutes"] or 0),
        display_horizon_hours=int(interest["display_horizon_hours"] or 0),
    )
    snapshot_row = _load_schedule_snapshot_conn(conn, cache_key)
    data = {
        "airport_iata": airport_iata,
        "timezone": timezone_name,
        "display_grace_minutes": int(interest["display_grace_minutes"] or 0),
        "display_horizon_hours": int(interest["display_horizon_hours"] or 0),
        "refresh_seconds": int(interest["refresh_seconds"] or 0),
        "last_seen": str(interest["last_seen"] or ""),
    }
    if snapshot_row is not None:
        snapshot = _snapshot_payload_from_row(snapshot_row)
        data["schedule_cache"] = {
            "generated_at": snapshot["generated_at"],
            "cache_state": snapshot["cache_state"],
            "provider": snapshot["provider"],
            "meta": snapshot["meta"],
        }
    return data


def _fetch_shared_schedule_from_upstream(
    *,
    airport_iata: str,
    timezone_name: str,
    display_grace_minutes: int,
    display_horizon_hours: int,
) -> Dict[str, Any]:
    from localflight.decode.mappings.aviationstack import aviationstack_to_raw_records
    from localflight.sources.web.aviationstack_plan import (
        DEFAULT_FETCH_FUTURE_HOURS,
        DEFAULT_FETCH_PAST_HOURS,
        DEFAULT_PAGE_SIZE,
        DEFAULT_PRODUCTION_PAGES_PER_DATE,
        build_fetch_plan,
    )

    aviationstack_key = _aviationstack_key()
    generated_at = _utc_now()
    planner_inputs = {
        "airport_iata": airport_iata,
        "timezone_name": timezone_name,
        "display_grace_minutes": display_grace_minutes,
        "display_horizon_hours": display_horizon_hours,
        "fetch_past_hours": DEFAULT_FETCH_PAST_HOURS,
        "fetch_future_hours": DEFAULT_FETCH_FUTURE_HOURS,
        "page_size": DEFAULT_PAGE_SIZE,
        "pages_per_date": DEFAULT_PRODUCTION_PAGES_PER_DATE,
    }
    requests_plan = build_fetch_plan(mode="departures", **planner_inputs) + build_fetch_plan(
        mode="arrivals",
        **planner_inputs,
    )

    records: list[Dict[str, Any]] = []
    pages_by_scope: dict[tuple[str, str], int] = {}
    rows_by_scope: dict[tuple[str, str], int] = {}
    skip_scopes: set[tuple[str, str]] = set()
    touched_dates: set[str] = set()
    pages_fetched = 0
    raw_rows = 0

    for req in requests_plan:
        if req.scope_key in skip_scopes:
            continue

        params: Dict[str, Any] = {"access_key": aviationstack_key, "limit": req.limit}
        if req.flight_date:
            params["flight_date"] = req.flight_date
            touched_dates.add(req.flight_date)
        if req.offset > 0:
            params["offset"] = req.offset
        if req.dep_iata:
            params["dep_iata"] = req.dep_iata
        if req.arr_iata:
            params["arr_iata"] = req.arr_iata

        try:
            response = _req.get(
                AVIATIONSTACK_URL,
                params=params,
                headers={"User-Agent": "localflight-relay/1.0"},
                timeout=25,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"AviationStack unreachable: {exc}")

        if response.status_code >= 400:
            try:
                payload = response.json()
                detail = payload.get("error") if isinstance(payload, dict) else None
                info = detail.get("info") if isinstance(detail, dict) else ""
            except Exception:
                info = ""
            suffix = f": {info}" if info else ""
            raise HTTPException(status_code=502, detail=f"AviationStack upstream HTTP {response.status_code}{suffix}")

        try:
            payload = response.json()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"AviationStack returned invalid JSON: {exc}")

        if not isinstance(payload, dict):
            raise HTTPException(status_code=502, detail="AviationStack response shape invalid")
        page_rows = payload.get("data")
        if not isinstance(page_rows, list):
            raise HTTPException(status_code=502, detail="AviationStack response missing data rows")

        pages_fetched += 1
        raw_rows += len(page_rows)
        pages_by_scope[req.scope_key] = pages_by_scope.get(req.scope_key, 0) + 1
        rows_by_scope[req.scope_key] = rows_by_scope.get(req.scope_key, 0) + len(page_rows)
        records.extend(
            aviationstack_to_raw_records(
                {"data": page_rows},
                airport_iata=airport_iata,
                mode="dep" if req.mode == "departures" else "arr",
            )
        )
        if len(page_rows) < req.limit:
            skip_scopes.add(req.scope_key)

    meta = {
        "pages_requested": len(requests_plan),
        "pages_fetched": pages_fetched,
        "page_size": DEFAULT_PAGE_SIZE,
        "pages_per_date_cap": DEFAULT_PRODUCTION_PAGES_PER_DATE,
        "dates_touched": sorted(touched_dates),
        "raw_rows": raw_rows,
        "record_count": len(records),
        "planner_version": _SHARED_SCHEDULE_PLANNER_VERSION,
        "schema_version": _SHARED_SCHEDULE_SCHEMA_VERSION,
        "pages_by_scope": {
            f"{mode}:{flight_date or 'undated'}": count
            for (mode, flight_date), count in pages_by_scope.items()
        },
        "rows_by_scope": {
            f"{mode}:{flight_date or 'undated'}": count
            for (mode, flight_date), count in rows_by_scope.items()
        },
    }
    return {
        "generated_at": generated_at,
        "provider": _SHARED_SCHEDULE_PROVIDER,
        "meta": meta,
        "records": records,
    }


_radar_cache: Dict[str, tuple[float, bytes]] = {}


def _fetch_adsbx_payload(lat: float, lon: float, radius_nm: float) -> bytes:
    dist_nm = max(5, int(radius_nm))
    cache_key = f"{round(lat, 4)}:{round(lon, 4)}:{dist_nm}"
    cached = _radar_cache.get(cache_key)
    now = time.monotonic()
    if cached and (now - cached[0]) < _radar_cache_seconds():
        return cached[1]

    try:
        rapidapi_key = _rapidapi_key()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    response = _req.get(
        f"{ADSBX_URL}/lat/{lat}/lon/{lon}/dist/{dist_nm}/",
        headers={
            "X-RapidAPI-Key": rapidapi_key,
            "X-RapidAPI-Host": "adsbexchange-com1.p.rapidapi.com",
        },
        timeout=20,
    )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"ADS-B upstream HTTP {response.status_code}")
    _radar_cache[cache_key] = (now, response.content)
    return response.content


def _require_admin(creds: HTTPBasicCredentials = Depends(HTTPBasic())) -> str:
    admin_pw = _admin_password()
    if not admin_pw or admin_pw == "changeme":
        raise HTTPException(status_code=503, detail="RELAY_ADMIN_PASSWORD is not configured")
    if not secrets.compare_digest(creds.password.encode(), admin_pw.encode()):
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"})
    return creds.username or "admin"


def _post_form(action: str, fields: Dict[str, str], label: str, css: str = "") -> str:
    inputs = "".join(
        f"<input type='hidden' name='{html.escape(name, quote=True)}' value='{html.escape(value, quote=True)}'>"
        for name, value in fields.items()
    )
    return (
        f"<form method='post' action='{html.escape(action, quote=True)}' class='inline'>"
        f"{inputs}<button type='submit' class='{html.escape(css, quote=True)}'>{html.escape(label)}</button></form>"
    )


def _store_activation_token(
    conn: sqlite3.Connection,
    *,
    token: str,
    label: str,
    schedule_limit: int,
    radar_limit: int,
    created_by: str,
    bound_install_id: Optional[str] = None,
) -> None:
    conn.execute(
        """
        INSERT INTO activation_tokens (
            token_hash, token_prefix, label, schedule_limit, radar_limit,
            created_at, created_by, bound_install_id, last_seen, revoked_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
        """,
        (
            _token_hash(token),
            token[:10],
            label.strip() or None,
            max(1, int(schedule_limit)),
            max(1, int(radar_limit)),
            _utc_now(),
            created_by,
            bound_install_id,
        ),
    )


def _render_admin(username: str, *, created_token: str = "", message: str = "") -> str:
    conn = _connect()
    month = _month_key()
    day_cutoff = _hours_ago(24)

    total_installs = conn.execute(
        "SELECT COUNT(DISTINCT install_id) FROM usage WHERE month=? AND service IN ('aviationstack', 'radar')",
        (month,),
    ).fetchone()[0]
    total_schedule = conn.execute(
        "SELECT COALESCE(SUM(calls), 0) FROM usage WHERE month=? AND service='aviationstack'",
        (month,),
    ).fetchone()[0]
    total_schedule = (total_schedule or 0) + int(
        _setting_get_conn(conn, f"schedule_counter_offset:{month}", "0") or 0
    )
    total_radar = conn.execute(
        "SELECT COALESCE(SUM(calls), 0) FROM usage WHERE month=? AND service='radar'",
        (month,),
    ).fetchone()[0]
    total_schedule_upstream = conn.execute(
        "SELECT COALESCE(SUM(calls), 0) FROM usage WHERE month=? AND service='aviationstack_upstream'",
        (month,),
    ).fetchone()[0]
    snapshot_totals = conn.execute(
        """
        SELECT
            COALESCE(SUM(client_accesses), 0) AS client_accesses,
            COALESCE(SUM(upstream_pulls), 0) AS upstream_pulls,
            COALESCE(SUM(refresh_count), 0) AS refresh_count,
            COALESCE(SUM(cache_hits), 0) AS cache_hits,
            COALESCE(SUM(stale_serves), 0) AS stale_serves
        FROM schedule_snapshots
        """
    ).fetchone()
    totals_24h = conn.execute(
        """
        SELECT COUNT(*) AS requests,
               COALESCE(AVG(latency_ms), 0) AS avg_latency,
               COALESCE(SUM(CASE WHEN status >= 400 OR status = 0 THEN 1 ELSE 0 END), 0) AS errors
        FROM request_log
        WHERE ts >= ?
        """,
        (day_cutoff,),
    ).fetchone()
    provider_revision = _provider_revision(conn)
    blocked_count = conn.execute("SELECT COUNT(*) FROM blocked_installs").fetchone()[0]
    snapshot_accesses = int(snapshot_totals["client_accesses"] or 0) if snapshot_totals else 0
    snapshot_refreshes = int(snapshot_totals["refresh_count"] or 0) if snapshot_totals else 0
    snapshot_hits = int(snapshot_totals["cache_hits"] or 0) if snapshot_totals else 0
    snapshot_stale = int(snapshot_totals["stale_serves"] or 0) if snapshot_totals else 0
    snapshot_hit_rate = round((snapshot_hits / snapshot_accesses) * 100.0, 1) if snapshot_accesses > 0 else 0.0
    snapshot_savings = max(0, snapshot_accesses - snapshot_refreshes)

    service_breakdown = [
        dict(r)
        for r in conn.execute(
            """
            SELECT service,
                   plan,
                   COUNT(DISTINCT install_id) AS installs,
                   COALESCE(SUM(calls), 0) AS calls,
                   MAX(last_seen) AS last_seen
            FROM usage
            WHERE month=?
            GROUP BY service, plan
            ORDER BY service, plan
            """,
            (month,),
        ).fetchall()
    ]
    network_breakdown = [
        dict(r)
        for r in conn.execute(
            """
            SELECT service,
                   plan,
                   COUNT(*) AS requests,
                   COALESCE(AVG(latency_ms), 0) AS avg_latency,
                   COALESCE(SUM(CASE WHEN status >= 400 OR status = 0 THEN 1 ELSE 0 END), 0) AS errors
            FROM request_log
            WHERE ts >= ?
            GROUP BY service, plan
            ORDER BY service, plan
            """,
            (day_cutoff,),
        ).fetchall()
    ]
    tokens = [
        dict(r)
        for r in conn.execute(
            """
            SELECT t.token_hash,
                   t.token_prefix,
                   t.label,
                   t.schedule_limit,
                   t.radar_limit,
                   t.created_at,
                   t.bound_install_id,
                   t.last_seen,
                   t.revoked_at,
                   COALESCE(us.calls, 0) AS schedule_used,
                   COALESCE(ur.calls, 0) AS radar_used
            FROM activation_tokens t
            LEFT JOIN usage us
                ON us.subject_key = ('managed:' || t.token_hash)
               AND us.service = 'aviationstack'
               AND us.month = ?
            LEFT JOIN usage ur
                ON ur.subject_key = ('managed:' || t.token_hash)
               AND ur.service = 'radar'
               AND ur.month = ?
            ORDER BY t.created_at DESC
            LIMIT 200
            """,
            (month, month),
        ).fetchall()
    ]
    activation_requests = [
        dict(r)
        for r in conn.execute(
            """
            SELECT request_id,
                   install_id,
                   install_fingerprint,
                   network_tag,
                   display_name,
                   requested_mode,
                   app_version,
                   status,
                   created_at,
                   updated_at,
                   last_seen,
                   decision_source,
                   decision_note,
                   token_prefix,
                   approved_at,
                   delivered_at
            FROM activation_requests
            ORDER BY
                CASE status
                    WHEN 'manual_review' THEN 0
                    WHEN 'issued' THEN 1
                    ELSE 2
                END,
                created_at DESC
            LIMIT 200
            """
        ).fetchall()
    ]
    pending_requests = sum(1 for row in activation_requests if row.get("status") == _REQUEST_STATUS_MANUAL_REVIEW)
    installs = [
        dict(r)
        for r in conn.execute(
            """
            SELECT u.install_id,
                   MAX(u.last_seen) AS last_seen,
                   COALESCE(SUM(CASE WHEN u.service = 'aviationstack' THEN u.calls ELSE 0 END), 0) AS schedule_calls,
                   COALESCE(SUM(CASE WHEN u.service = 'radar' THEN u.calls ELSE 0 END), 0) AS radar_calls,
                   GROUP_CONCAT(DISTINCT u.plan) AS plans,
                   CASE WHEN b.install_id IS NULL THEN 0 ELSE 1 END AS blocked
            FROM usage u
            LEFT JOIN blocked_installs b ON b.install_id = u.install_id
            WHERE u.month=? AND u.service IN ('aviationstack', 'radar')
            GROUP BY u.install_id
            ORDER BY (schedule_calls + radar_calls) DESC, last_seen DESC
            LIMIT 300
            """,
            (month,),
        ).fetchall()
    ]
    recent = [
        dict(r)
        for r in conn.execute(
            """
            SELECT ts, install_id, mode, status, latency_ms, service, plan
            FROM request_log
            ORDER BY ts DESC
            LIMIT 100
            """
        ).fetchall()
    ]

    aviationstack_key, aviationstack_source = _provider_status(
        _SETTING_AVIATIONSTACK_KEY,
        "AVIATIONSTACK_API_KEY",
        conn=conn,
    )
    rapidapi_key, rapidapi_source = _provider_status(
        _SETTING_RAPIDAPI_KEY,
        "RAPIDAPI_KEY",
        conn=conn,
    )
    conn.close()

    def rows_for_service_breakdown() -> str:
        if not service_breakdown:
            return "<tr><td colspan='5' class='muted'>No monthly usage yet</td></tr>"
        return "".join(
            "<tr>"
            f"<td>{html.escape(str(row['service'] or '-'))}</td>"
            f"<td>{html.escape(str(row['plan'] or '-'))}</td>"
            f"<td>{int(row['installs'] or 0)}</td>"
            f"<td>{int(row['calls'] or 0)}</td>"
            f"<td class='soft'>{html.escape(str(row['last_seen'] or '')[:16].replace('T', ' '))}</td>"
            "</tr>"
            for row in service_breakdown
        )

    def rows_for_network_breakdown() -> str:
        if not network_breakdown:
            return "<tr><td colspan='5' class='muted'>No request logs yet</td></tr>"
        return "".join(
            "<tr>"
            f"<td>{html.escape(str(row['service'] or '-'))}</td>"
            f"<td>{html.escape(str(row['plan'] or '-'))}</td>"
            f"<td>{int(row['requests'] or 0)}</td>"
            f"<td>{int(row['avg_latency'] or 0)}ms</td>"
            f"<td>{int(row['errors'] or 0)}</td>"
            "</tr>"
            for row in network_breakdown
        )

    def rows_for_tokens() -> str:
        if not tokens:
            return "<tr><td colspan='8' class='muted'>No activation tokens yet</td></tr>"
        out = []
        for row in tokens:
            status = "revoked" if row["revoked_at"] else "active"
            action_bits = [
                _post_form(
                    "/admin/activation/rotate",
                    {"token_hash": str(row["token_hash"] or "")},
                    "Reshuffle",
                    "amber",
                ),
                _post_form(
                    "/admin/counters/reset",
                    {"scope": "token", "token_hash": str(row["token_hash"] or "")},
                    "Reset counters",
                    "slate",
                ),
                _post_form(
                    "/admin/activation/unbind",
                    {"token_hash": str(row["token_hash"] or "")},
                    "Unbind install",
                    "slate",
                ),
            ]
            if row["revoked_at"]:
                action_bits.append(
                    _post_form(
                        "/admin/activation/reactivate",
                        {"token_hash": str(row["token_hash"] or "")},
                        "Restore",
                        "green",
                    )
                )
            else:
                action_bits.append(
                    _post_form(
                        "/admin/activation/revoke",
                        {"token_hash": str(row["token_hash"] or "")},
                        "Revoke",
                        "red",
                    )
                )
            action_bits.append(
                _post_form(
                    "/admin/activation/delete",
                    {"token_hash": str(row["token_hash"] or "")},
                    "Delete",
                    "red",
                )
            )
            out.append(
                "<tr>"
                f"<td class='mono'>{html.escape(str(row['token_prefix'] or '-'))}...</td>"
                f"<td>{html.escape(str(row['label'] or '-'))}</td>"
                f"<td>{int(row['schedule_used'] or 0)} / {int(row['schedule_limit'] or 0)}</td>"
                f"<td>{int(row['radar_used'] or 0)} / {int(row['radar_limit'] or 0)}</td>"
                f"<td class='mono'>{html.escape(_install_fingerprint(str(row['bound_install_id'] or ''))) if row['bound_install_id'] else '-'}</td>"
                f"<td class='soft'>{html.escape(str(row['last_seen'] or '')[:16].replace('T', ' ')) if row['last_seen'] else '-'}</td>"
                f"<td>{status}</td>"
                f"<td class='actions'>{''.join(action_bits)}</td>"
                "</tr>"
            )
        return "".join(out)

    def rows_for_activation_requests() -> str:
        if not activation_requests:
            return "<tr><td colspan='9' class='muted'>No activation activity yet</td></tr>"
        out = []
        for row in activation_requests:
            request_id = str(row["request_id"] or "")
            status = str(row["status"] or _REQUEST_STATUS_PENDING)
            action_bits = []
            if status == _REQUEST_STATUS_MANUAL_REVIEW:
                action_bits.extend(
                    [
                        _post_form(
                            "/admin/activation-request/approve",
                            {"request_id": request_id},
                            "Issue now",
                            "green",
                        ),
                        _post_form(
                            "/admin/activation-request/reject",
                            {"request_id": request_id, "decision_note": "dismissed"},
                            "Dismiss",
                            "slate",
                        ),
                    ]
                )
            else:
                action_bits.append(
                    _post_form(
                        "/admin/activation-request/delete",
                        {"request_id": request_id},
                        "Clear row",
                        "slate",
                    )
                )
            label_bits = [
                str(row["display_name"] or "").strip(),
                str(row["requested_mode"] or "").strip(),
                str(row["app_version"] or "").strip(),
            ]
            label = " | ".join([bit for bit in label_bits if bit]) or "-"
            source = str(row["decision_source"] or "-")
            out.append(
                "<tr>"
                f"<td class='mono'>{html.escape(str(row['install_fingerprint'] or '-'))}</td>"
                f"<td class='mono'>{html.escape(str(row['network_tag'] or '-'))}</td>"
                f"<td>{html.escape(label)}</td>"
                f"<td>{html.escape(status)}</td>"
                f"<td>{html.escape(source)}</td>"
                f"<td>{html.escape(str(row['token_prefix'] or '-') + ('...' if row['token_prefix'] else ''))}</td>"
                f"<td>{html.escape(str(row['decision_note'] or '-')[:42])}</td>"
                f"<td class='soft'>{html.escape(str(row['created_at'] or '')[:16].replace('T', ' '))}</td>"
                f"<td class='actions'>{''.join(action_bits)}</td>"
                "</tr>"
            )
        return "".join(out)

    def rows_for_installs() -> str:
        if not installs:
            return "<tr><td colspan='6' class='muted'>No install usage yet</td></tr>"
        out = []
        for row in installs:
            install_id = str(row["install_id"] or "")
            blocked = bool(row["blocked"])
            action_bits = [
                _post_form(
                    "/admin/counters/reset",
                    {"scope": "install", "install_id": install_id},
                    "Reset counters",
                    "slate",
                )
            ]
            if blocked:
                action_bits.append(
                    _post_form(
                        "/admin/install/unblock",
                        {"install_id": install_id},
                        "Restore access",
                        "green",
                    )
                )
            else:
                action_bits.append(
                    _post_form(
                        "/admin/install/block",
                        {"install_id": install_id, "reason": "revoked by admin"},
                        "Revoke access",
                        "red",
                    )
                )
            out.append(
                "<tr>"
                f"<td class='mono'>{html.escape(_install_fingerprint(install_id))}</td>"
                f"<td>{int(row['schedule_calls'] or 0)}</td>"
                f"<td>{int(row['radar_calls'] or 0)}</td>"
                f"<td>{html.escape(str(row['plans'] or '-'))}</td>"
                f"<td class='soft'>{html.escape(str(row['last_seen'] or '')[:16].replace('T', ' '))}</td>"
                f"<td class='actions'>{''.join(action_bits)}</td>"
                "</tr>"
            )
        return "".join(out)

    def rows_for_recent() -> str:
        if not recent:
            return "<tr><td colspan='7' class='muted'>No requests yet</td></tr>"
        return "".join(
            "<tr>"
            f"<td class='soft'>{html.escape(str(row['ts'] or '')[:16].replace('T', ' '))}</td>"
            f"<td class='mono'>{html.escape(_install_fingerprint(str(row['install_id'] or '')))}</td>"
            f"<td>{html.escape(str(row['service'] or '-'))}</td>"
            f"<td>{html.escape(str(row['plan'] or '-'))}</td>"
            f"<td>{html.escape(str(row['mode'] or '-'))}</td>"
            f"<td>{int(row['status'] or 0)}</td>"
            f"<td>{int(row['latency_ms'] or 0)}ms</td>"
            "</tr>"
            for row in recent
        )

    token_notice = (
        f"<div class='notice ok'><strong>Fresh token:</strong> <span class='mono'>{html.escape(created_token)}</span></div>"
        if created_token
        else ""
    )
    message_notice = f"<div class='notice'>{html.escape(message)}</div>" if message else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Local Flight Network Admin</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: system-ui, sans-serif; background: #0c1117; color: #e7edf3; line-height: 1.45; }}
  .wrap {{ max-width: 1480px; margin: 0 auto; padding: 28px; }}
  h1 {{ margin: 0 0 4px; font-size: 1.45rem; }}
  .sub {{ opacity: .6; margin-bottom: 18px; }}
  .notice {{ margin: 0 0 14px; padding: 10px 12px; border-radius: 8px; background: #18212b; border: 1px solid #2a3441; }}
  .notice.ok {{ border-color: #1f6f45; background: #12271c; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-bottom: 18px; }}
  .split {{ display: grid; grid-template-columns: 1.2fr 1fr; gap: 14px; margin-bottom: 18px; }}
  .card {{ background: #171d25; border: 1px solid #283241; border-radius: 8px; padding: 14px 16px; }}
  .card h2 {{ margin: 0 0 10px; font-size: .75rem; text-transform: uppercase; letter-spacing: .06em; opacity: .58; }}
  .big {{ font-size: 1.85rem; font-weight: 800; line-height: 1; }}
  .stack {{ display: grid; gap: 14px; }}
  .soft {{ opacity: .62; }}
  .muted {{ opacity: .45; padding: 18px 10px; }}
  .mono {{ font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }}
  form {{ display: grid; gap: 10px; }}
  .inline {{ display: inline-block; margin: 0 6px 6px 0; }}
  .inline input {{ display: none; }}
  label {{ font-size: .83rem; opacity: .78; }}
  input {{ width: 100%; border: 1px solid #2f3948; border-radius: 8px; padding: 9px 11px; background: #0f141b; color: #e7edf3; }}
  button {{ border: 0; border-radius: 8px; padding: 9px 12px; font-weight: 700; cursor: pointer; background: #00d46a; color: #041108; }}
  button.red {{ background: #f25f5c; color: #220605; }}
  button.amber {{ background: #f3b744; color: #231600; }}
  button.slate {{ background: #2a3441; color: #e7edf3; }}
  button.green {{ background: #00d46a; color: #041108; }}
  h3 {{ margin: 18px 0 10px; font-size: .88rem; opacity: .72; text-transform: uppercase; letter-spacing: .05em; }}
  table {{ width: 100%; border-collapse: collapse; font-size: .84rem; background: #11161d; border: 1px solid #202936; border-radius: 8px; overflow: hidden; }}
  th {{ text-align: left; padding: 9px 10px; opacity: .58; border-bottom: 1px solid #26303d; }}
  td {{ padding: 8px 10px; border-bottom: 1px solid #1a222d; vertical-align: top; }}
  tr:last-child td {{ border-bottom: 0; }}
  .actions {{ min-width: 240px; }}
  .kicker {{ font-size: .88rem; opacity: .78; margin-bottom: 8px; }}
  .provider-line {{ display: flex; justify-content: space-between; gap: 12px; font-size: .9rem; padding: 6px 0; border-bottom: 1px solid #1d2530; }}
  .provider-line:last-child {{ border-bottom: 0; }}
  .tiny {{ font-size: .82rem; opacity: .7; }}
  @media (max-width: 1080px) {{
    .split {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Local Flight Network Admin</h1>
  <div class="sub">Relay console only · {html.escape(month)} · logged in as {html.escape(username)} · no raw IP addresses are stored here</div>
  {token_notice}
  {message_notice}

  <div class="grid">
    <div class="card"><h2>Known installs</h2><div class="big">{int(total_installs or 0)}</div></div>
    <div class="card"><h2>Relay accesses</h2><div class="big">{int(total_schedule or 0):,}</div></div>
    <div class="card"><h2>Upstream pulls</h2><div class="big">{int(total_schedule_upstream or 0):,}</div></div>
    <div class="card"><h2>Radar calls</h2><div class="big">{int(total_radar or 0)}</div></div>
    <div class="card"><h2>Requests (24h)</h2><div class="big">{int(totals_24h['requests'] or 0)}</div></div>
    <div class="card"><h2>Errors (24h)</h2><div class="big">{int(totals_24h['errors'] or 0)}</div></div>
    <div class="card"><h2>Manual reviews</h2><div class="big">{int(pending_requests or 0)}</div></div>
    <div class="card"><h2>Provider revision</h2><div class="big">{provider_revision}</div></div>
    <div class="card"><h2>Avg latency</h2><div class="big">{int(totals_24h['avg_latency'] or 0)}ms</div></div>
    <div class="card"><h2>Cache hit rate</h2><div class="big">{snapshot_hit_rate:.1f}%</div></div>
    <div class="card"><h2>Shared savings</h2><div class="big">{snapshot_savings:,}</div></div>
    <div class="card"><h2>Blocked installs</h2><div class="big">{int(blocked_count or 0)}</div></div>
  </div>

  <div class="split">
    <div class="card stack">
      <div>
        <h2>Provider keys</h2>
        <div class="kicker">Managed clients do not receive raw vendor keys. Key changes take effect on the next relay request and advance the provider revision.</div>
        <div class="provider-line"><span>AviationStack</span><span>{html.escape(_mask_secret(aviationstack_key))} <span class="tiny">({html.escape(aviationstack_source)})</span></span></div>
        <div class="provider-line"><span>RapidAPI ADS-B</span><span>{html.escape(_mask_secret(rapidapi_key))} <span class="tiny">({html.escape(rapidapi_source)})</span></span></div>
        <div class="provider-line"><span>Community schedule cap</span><span>{_community_schedule_limit()} relay accesses per install / 30-day window</span></div>
        <div class="provider-line"><span>Shared snapshot pool</span><span>{snapshot_refreshes:,} refreshes · {snapshot_stale:,} stale serves</span></div>
        <div class="provider-line"><span>Radar cache</span><span>{_radar_cache_seconds()}s</span></div>
        <div class="provider-line"><span>Raw provider debug</span><span>{'enabled' if _raw_provider_debug_enabled() else 'disabled'}</span></div>
        <div class="provider-line"><span>Activation privacy</span><span>Anonymous network tags only</span></div>
      </div>
      <form method="post" action="/admin/providers/save">
        <label>AviationStack key
          <input name="aviationstack_key" placeholder="Paste a replacement key to store in the relay" />
        </label>
        <label>RapidAPI ADS-B key
          <input name="rapidapi_key" placeholder="Paste a replacement key to store in the relay" />
        </label>
        <button type="submit">Save provider keys</button>
      </form>
      <div>
        {_post_form('/admin/providers/clear', {'provider': 'aviationstack'}, 'Clear AviationStack override', 'slate')}
        {_post_form('/admin/providers/clear', {'provider': 'rapidapi'}, 'Clear RapidAPI override', 'slate')}
      </div>
    </div>

    <div class="card stack">
      <div>
        <h2>Token and counter tools</h2>
        <div class="kicker">Normal installs auto-issue through the setup flow. Use this area for managed exceptions, reshuffles, revokes, and counter resets.</div>
      </div>
      <form method="post" action="/admin/activation/create">
        <label>Label
          <input name="label" placeholder="Client name or deployment note" />
        </label>
        <label>Schedule limit
          <input name="schedule_limit" type="number" min="1" value="{_managed_schedule_limit()}" />
        </label>
        <label>Radar limit
          <input name="radar_limit" type="number" min="1" value="{_managed_radar_limit()}" />
        </label>
        <button type="submit">Create activation token</button>
      </form>
      <div>
        {_post_form('/admin/counters/reset', {'scope': 'all'}, 'Reset all monthly counters', 'amber')}
        {_post_form('/admin/counters/reset', {'scope': 'service', 'service': 'aviationstack'}, 'Reset schedule counters', 'slate')}
        {_post_form('/admin/counters/reset', {'scope': 'service', 'service': 'radar'}, 'Reset radar counters', 'slate')}
        {_post_form('/admin/counters/reset', {'scope': 'logs'}, 'Clear network log', 'slate')}
        <form method="post" action="/admin/counters/correct-schedule" style="margin-top:0.5rem;display:flex;gap:0.4rem;align-items:center">
          <input name="total" type="number" min="0" value="{int(total_schedule or 0)}" style="width:9rem" title="Set known schedule total for this month (includes prior usage outside this relay)" />
          <button type="submit">Correct schedule total</button>
        </form>
      </div>
    </div>
  </div>

  <div class="split">
    <div>
      <h3>API Totals</h3>
      <table>
        <thead><tr><th>Service</th><th>Plan</th><th>Installs</th><th>Calls</th><th>Last seen</th></tr></thead>
        <tbody>{rows_for_service_breakdown()}</tbody>
      </table>
    </div>
    <div>
      <h3>Network Stats (24h)</h3>
      <table>
        <thead><tr><th>Service</th><th>Plan</th><th>Requests</th><th>Avg latency</th><th>Errors</th></tr></thead>
        <tbody>{rows_for_network_breakdown()}</tbody>
      </table>
    </div>
  </div>

  <h3>Activation Lane</h3>
  <table>
    <thead><tr><th>Install</th><th>Network tag</th><th>Request</th><th>Status</th><th>Source</th><th>Token</th><th>Note</th><th>Created</th><th>Actions</th></tr></thead>
    <tbody>{rows_for_activation_requests()}</tbody>
  </table>

  <h3>Managed Tokens</h3>
  <table>
    <thead><tr><th>Token</th><th>Label</th><th>Schedule</th><th>Radar</th><th>Bound install</th><th>Last seen</th><th>Status</th><th>Actions</th></tr></thead>
    <tbody>{rows_for_tokens()}</tbody>
  </table>

  <h3>Install Registry</h3>
  <table>
    <thead><tr><th>Install</th><th>Schedule calls</th><th>Radar calls</th><th>Plans</th><th>Last seen</th><th>Actions</th></tr></thead>
    <tbody>{rows_for_installs()}</tbody>
  </table>

  <h3>Recent Network Log</h3>
  <table>
    <thead><tr><th>Time</th><th>Install</th><th>Service</th><th>Plan</th><th>Scope</th><th>Status</th><th>Latency</th></tr></thead>
    <tbody>{rows_for_recent()}</tbody>
  </table>
</div>
</body>
</html>"""


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _db_path().parent.mkdir(parents=True, exist_ok=True)
    _ensure_schema()
    yield


app = FastAPI(title="Local Flight Network Admin", lifespan=_lifespan, docs_url=None, redoc_url=None)


@app.middleware("http")
async def _surface_gate(request: Request, call_next):
    surface = _request_surface(request)
    if not _surface_allows_path(surface, request.url.path or "/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return await call_next(request)

@app.get("/")
def root(request: Request):
    if _request_surface(request) == "public":
        return {
            "ok": True,
            "service": "Local Flight Community Relay",
            "public_host": _public_host(),
            "admin_host": _admin_host(),
            "health": "/health",
            "provider_revision": _provider_revision(),
        }
    return RedirectResponse(url="/admin", status_code=307)


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "provider_revision": _provider_revision(),
        "public_host": _public_host(),
        "admin_host": _admin_host(),
    }


class ActivationRequestIn(BaseModel):
    install_id: str
    install_fingerprint: str
    airport_iata: str = ""
    airport_icao: str = ""
    display_name: str = ""
    requested_mode: str = "community"
    app_version: str = ""


class ClientStatusIn(BaseModel):
    install_id: str
    activation_token: str = ""
    app_version: str = ""
    airport_iata: str = ""
    timezone: str = ""
    display_grace_minutes: int = 30
    display_horizon_hours: int = 12
    refresh_seconds: int = 3600


def _build_client_status(
    *,
    install_id: str,
    activation_token: str,
    app_version: str = "",
) -> Dict[str, Any]:
    _ensure_install_allowed(install_id)
    activation_row = _load_activation(activation_token)
    if activation_token and activation_row is None:
        raise HTTPException(status_code=403, detail="Activation token invalid or revoked")
    if activation_row is not None:
        bound_install_id = (activation_row["bound_install_id"] or "").strip()
        if bound_install_id and bound_install_id != install_id:
            raise HTTPException(status_code=403, detail="Activation token already bound to another install")
        _bind_activation_install(str(activation_row["token_hash"]), install_id)
        plan = "managed"
        schedule_limit = int(activation_row["schedule_limit"] or _managed_schedule_limit())
        radar_limit = int(activation_row["radar_limit"] or _managed_radar_limit())
        token_prefix = str(activation_row["token_prefix"] or "")
        label = str(activation_row["label"] or "")
    else:
        plan = "community"
        schedule_limit = _community_schedule_limit()
        radar_limit = _community_radar_limit()
        token_prefix = ""
        label = ""

    conn = _connect()
    aviationstack_key, _ = _provider_status(_SETTING_AVIATIONSTACK_KEY, "AVIATIONSTACK_API_KEY", conn=conn)
    rapidapi_key, _ = _provider_status(_SETTING_RAPIDAPI_KEY, "RAPIDAPI_KEY", conn=conn)
    revision = _provider_revision(conn)
    interest = _client_interest_snapshot(conn, install_id)
    conn.close()

    return {
        "ok": True,
        "plan": plan,
        "relay_ok": True,
        "provider_revision": revision,
        "install_fingerprint": _install_fingerprint(install_id),
        "token_prefix": token_prefix,
        "label": label,
        "app_version": (app_version or "").strip(),
        "providers": {
            "aviationstack": bool(aviationstack_key),
            "adsbexchange": bool(rapidapi_key),
        },
        "limits": {
            "schedule": schedule_limit,
            "radar": radar_limit,
        },
        "interest": interest or {},
        "schedule_cache": (interest or {}).get("schedule_cache") or {},
    }


@app.post("/v1/activate")
def relay_activate(body: ActivationRequestIn, request: Request) -> Dict[str, Any]:
    install_id = _validate_install_id(body.install_id)
    install_fingerprint = (body.install_fingerprint or "").strip()
    expected_fingerprint = _install_fingerprint(install_id)
    if install_fingerprint != expected_fingerprint:
        raise HTTPException(status_code=400, detail="install_fingerprint does not match install_id")

    display_name = (body.display_name or "").strip()[:80]
    requested_mode = (body.requested_mode or "managed").strip().lower()[:20]
    app_version = (body.app_version or "").strip()[:32]
    network_tag = _network_tag(_client_ip(request))

    blocked_reason = _blocked_reason(install_id)
    if blocked_reason:
        raise HTTPException(status_code=403, detail=f"Install access revoked: {blocked_reason}")

    conn = _connect()
    counts = _recent_activation_counts(conn, install_id=install_id, network_tag=network_tag)
    manual_review = counts["network_requests"] >= _AUTO_ACTIVATION_NETWORK_DAILY_LIMIT or counts[
        "network_installs"
    ] >= _AUTO_ACTIVATION_NETWORK_INSTALLS_DAILY_LIMIT

    if manual_review:
        existing = conn.execute(
            """
            SELECT request_id, install_fingerprint, decision_note
            FROM activation_requests
            WHERE install_id=? AND status=?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (install_id, _REQUEST_STATUS_MANUAL_REVIEW),
        ).fetchone()
        if existing:
            conn.close()
            return {
                "ok": True,
                "request_id": str(existing["request_id"] or ""),
                "status": _REQUEST_STATUS_MANUAL_REVIEW,
                "install_fingerprint": str(existing["install_fingerprint"] or expected_fingerprint),
                "decision_note": str(existing["decision_note"] or "manual review required"),
            }
        request_id = _record_activation_event(
            conn,
            install_id=install_id,
            install_fingerprint=install_fingerprint,
            network_tag=network_tag,
            display_name=display_name or f"Local Flight {expected_fingerprint}",
            requested_mode=requested_mode,
            app_version=app_version,
            status=_REQUEST_STATUS_MANUAL_REVIEW,
            decision_source="auto-safety-net",
            decision_note="manual review required",
        )
        conn.commit()
        conn.close()
        return {
            "ok": True,
            "request_id": request_id,
            "status": _REQUEST_STATUS_MANUAL_REVIEW,
            "install_fingerprint": expected_fingerprint,
            "decision_note": "Relay paused automatic activation for this install and queued a manual review.",
        }

    token, token_prefix, issuance = _issue_token_for_install(
        conn,
        install_id=install_id,
        label=display_name or f"Local Flight {expected_fingerprint}",
        created_by="auto-issue",
    )
    request_id = _record_activation_event(
        conn,
        install_id=install_id,
        install_fingerprint=install_fingerprint,
        network_tag=network_tag,
        display_name=display_name or f"Local Flight {expected_fingerprint}",
        requested_mode=requested_mode,
        app_version=app_version,
        status=_REQUEST_STATUS_ISSUED,
        decision_source="auto",
        decision_note=issuance,
        token_hash=_token_hash(token),
        token_prefix=token_prefix,
    )
    conn.commit()
    conn.close()
    status = _build_client_status(install_id=install_id, activation_token=token, app_version=app_version)
    status.update(
        {
            "request_id": request_id,
            "status": _REQUEST_STATUS_ISSUED,
            "activation_token": token,
            "decision_note": "Relay access issued instantly for this installation.",
        }
    )
    return status


@app.get("/v1/client/status")
def relay_client_status(
    install_id: str = Query(...),
    activation_token: str = Query(""),
    app_version: str = Query(""),
) -> Dict[str, Any]:
    install_id = _validate_install_id(install_id)
    return _build_client_status(
        install_id=install_id,
        activation_token=(activation_token or "").strip(),
        app_version=app_version,
    )


@app.post("/v1/client/checkin")
def relay_client_checkin(body: ClientStatusIn) -> Dict[str, Any]:
    install_id = _validate_install_id(body.install_id)
    status = _build_client_status(
        install_id=install_id,
        activation_token=(body.activation_token or "").strip(),
        app_version=body.app_version,
    )
    airport_iata = _clean_airport(body.airport_iata) if (body.airport_iata or "").strip() else None
    timezone_name = (body.timezone or "").strip()
    if airport_iata and timezone_name:
        _record_client_interest(
            install_id=install_id,
            plan=str(status.get("plan") or "community"),
            airport_iata=airport_iata,
            timezone_name=timezone_name,
            display_grace_minutes=max(0, int(body.display_grace_minutes or 0)),
            display_horizon_hours=max(1, int(body.display_horizon_hours or 1)),
            refresh_seconds=max(60, int(body.refresh_seconds or 3600)),
        )
        status = _build_client_status(
            install_id=install_id,
            activation_token=(body.activation_token or "").strip(),
            app_version=body.app_version,
        )
    return status


@app.post("/v1/activation-request")
def relay_activation_request_compat(body: ActivationRequestIn, request: Request) -> Dict[str, Any]:
    return relay_activate(body, request)


@app.get("/v1/activation-request/status")
def relay_activation_request_status_compat(
    request_id: str = Query(...),
    install_id: str = Query(...),
) -> Dict[str, Any]:
    install_id = _validate_install_id(install_id)
    conn = _connect()
    row = conn.execute(
        """
        SELECT status, decision_note, token_prefix, install_fingerprint
        FROM activation_requests
        WHERE request_id=? AND install_id=?
        """,
        (request_id.strip(), install_id),
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Activation request not found")
    return {
        "ok": True,
        "request_id": request_id.strip(),
        "status": str(row["status"] or _REQUEST_STATUS_MANUAL_REVIEW),
        "install_fingerprint": str(row["install_fingerprint"] or _install_fingerprint(install_id)),
        "decision_note": str(row["decision_note"] or ""),
        "token_prefix": str(row["token_prefix"] or ""),
        "delivered": str(row["status"] or "") == _REQUEST_STATUS_ISSUED,
    }


@app.get("/v1/schedule")
def relay_schedule(
    airport_iata: str = Query(...),
    timezone: str = Query(...),
    display_grace_minutes: int = Query(30, ge=0, le=180),
    display_horizon_hours: int = Query(12, ge=1, le=24),
    refresh_seconds: int = Query(3600, ge=60, le=86400),
    install_id: str = Query(...),
    activation_token: str = Query(""),
) -> JSONResponse:
    install_id = _validate_install_id(install_id)
    airport_iata = _clean_airport(airport_iata)
    timezone_name = (timezone or "").strip()
    if not timezone_name:
        raise HTTPException(status_code=400, detail="timezone is required")

    access = _resolve_access(install_id=install_id, activation_token=activation_token, service="aviationstack")
    _record_client_interest(
        install_id=install_id,
        plan=str(access["plan"] or "community"),
        airport_iata=airport_iata,
        timezone_name=timezone_name,
        display_grace_minutes=display_grace_minutes,
        display_horizon_hours=display_horizon_hours,
        refresh_seconds=refresh_seconds,
    )

    month = _month_key()
    current = _get_usage(access["subject_key"], "aviationstack", month)
    if current >= access["limit"]:
        return JSONResponse(
            {
                "error": {
                    "code": "quota_exceeded",
                    "info": (
                        f"{access['plan'].title()} relay schedule access quota exceeded: "
                        f"{current}/{access['limit']} accesses used in the current window."
                    ),
                }
            },
            status_code=429,
            headers=_quota_headers("aviationstack", current, access["limit"], access["plan"]),
        )

    cache_key = _schedule_cache_key(
        airport_iata=airport_iata,
        timezone_name=timezone_name,
        display_grace_minutes=display_grace_minutes,
        display_horizon_hours=display_horizon_hours,
    )
    lock = _get_schedule_lock(cache_key)

    def _quota_headers_for_access(used_count: int) -> Dict[str, str]:
        return _quota_headers("aviationstack", used_count, access["limit"], access["plan"])

    def _serve_snapshot(
        row: sqlite3.Row,
        *,
        cache_state: str,
        served_via: str,
        count_cache_hit: bool = False,
        count_stale: bool = False,
        used_count: int,
    ) -> JSONResponse:
        payload = _snapshot_payload_from_row(row, cache_state=cache_state)
        payload["meta"]["served_via"] = served_via
        _record_schedule_access(
            cache_key=cache_key,
            cache_state=cache_state,
            count_cache_hit=count_cache_hit,
            count_stale=count_stale,
        )
        return JSONResponse(payload, headers=_quota_headers_for_access(used_count))

    used = _increment_usage(
        subject_key=access["subject_key"],
        service="aviationstack",
        month=month,
        plan=access["plan"],
        install_id=install_id,
    )

    conn = _connect()
    snapshot_row = _load_schedule_snapshot_conn(conn, cache_key)
    state = _snapshot_lifecycle_state(snapshot_row, refresh_seconds=refresh_seconds)
    conn.close()

    if snapshot_row is not None and state == "fresh":
        _log_request(
            install_id=install_id,
            scope="shared_schedule",
            status=200,
            latency_ms=0,
            service="aviationstack",
            plan=access["plan"],
        )
        return _serve_snapshot(
            snapshot_row,
            cache_state="fresh",
            served_via="cache-hit",
            count_cache_hit=True,
            used_count=used,
        )

    acquired = lock.acquire(blocking=False)
    if not acquired:
        if snapshot_row is not None and state == "stale":
            _log_request(
                install_id=install_id,
                scope="shared_schedule",
                status=200,
                latency_ms=0,
                service="aviationstack",
                plan=access["plan"],
            )
            return _serve_snapshot(
                snapshot_row,
                cache_state="stale",
                served_via="stale-fallback",
                count_stale=True,
                used_count=used,
            )

        waited = lock.acquire(timeout=_SHARED_SCHEDULE_LOCK_WAIT_S)
        if waited:
            lock.release()
        conn = _connect()
        latest = _load_schedule_snapshot_conn(conn, cache_key)
        latest_state = _snapshot_lifecycle_state(latest, refresh_seconds=refresh_seconds)
        conn.close()
        if latest is not None and latest_state in {"fresh", "stale"}:
            _log_request(
                install_id=install_id,
                scope="shared_schedule",
                status=200,
                latency_ms=0,
                service="aviationstack",
                plan=access["plan"],
            )
            return _serve_snapshot(
                latest,
                cache_state="fresh" if latest_state == "fresh" else "stale",
                served_via="awaited-refresh" if latest_state == "fresh" else "stale-fallback",
                count_cache_hit=latest_state == "fresh",
                count_stale=latest_state == "stale",
                used_count=used,
            )
        raise HTTPException(status_code=503, detail="Relay schedule refresh is already in progress")

    t0 = time.monotonic()
    try:
        snapshot = _fetch_shared_schedule_from_upstream(
            airport_iata=airport_iata,
            timezone_name=timezone_name,
            display_grace_minutes=display_grace_minutes,
            display_horizon_hours=display_horizon_hours,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        pages_fetched = int(((snapshot.get("meta") or {}).get("pages_fetched", 0) or 0))
        _store_schedule_snapshot(
            cache_key=cache_key,
            airport_iata=airport_iata,
            timezone_name=timezone_name,
            display_grace_minutes=display_grace_minutes,
            display_horizon_hours=display_horizon_hours,
            payload=snapshot,
            pages_fetched=pages_fetched,
        )
        if pages_fetched > 0:
            _increment_usage(
                subject_key=f"shared:{cache_key}",
                service="aviationstack_upstream",
                month=month,
                plan="shared",
                install_id=None,
                n_calls=pages_fetched,
            )
        _log_request(
            install_id=install_id,
            scope="shared_schedule",
            status=200,
            latency_ms=latency_ms,
            service="aviationstack",
            plan=access["plan"],
        )
        conn = _connect()
        fresh_row = _load_schedule_snapshot_conn(conn, cache_key)
        conn.close()
        if fresh_row is None:
            raise HTTPException(status_code=500, detail="Relay snapshot storage failed")
        public_state = "miss" if snapshot_row is None else "fresh"
        return _serve_snapshot(
            fresh_row,
            cache_state=public_state,
            served_via="cold-fill" if public_state == "miss" else "refresh",
            used_count=used,
        )
    except HTTPException as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        if snapshot_row is not None and state == "stale":
            conn = _connect()
            conn.execute(
                "UPDATE schedule_snapshots SET last_error=?, updated_at=? WHERE cache_key=?",
                (str(exc.detail), _utc_now(), cache_key),
            )
            conn.commit()
            stale_row = _load_schedule_snapshot_conn(conn, cache_key)
            conn.close()
            _log_request(
                install_id=install_id,
                scope="shared_schedule",
                status=200,
                latency_ms=latency_ms,
                service="aviationstack",
                plan=access["plan"],
            )
            if stale_row is not None:
                return _serve_snapshot(
                    stale_row,
                    cache_state="stale",
                    served_via="stale-on-error",
                    count_stale=True,
                    used_count=used,
                )
        _log_request(
            install_id=install_id,
            scope="shared_schedule",
            status=getattr(exc, "status_code", 502),
            latency_ms=latency_ms,
            service="aviationstack",
            plan=access["plan"],
        )
        raise
    finally:
        lock.release()


@app.get("/v1/flights")
def relay_flights(
    request: Request,
    dep_iata: Optional[str] = Query(None),
    arr_iata: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=100),
    flight_date: Optional[str] = Query(None),
    offset: int = Query(0, ge=0, le=10000),
    install_id: str = Query(...),
    activation_token: str = Query(""),
) -> Response:
    if not _raw_provider_debug_enabled() or _request_surface(request) not in {"admin", "local"}:
        raise HTTPException(status_code=404, detail="Not found")
    install_id = _validate_install_id(install_id)
    dep_iata = _clean_airport(dep_iata)
    arr_iata = _clean_airport(arr_iata)
    if not dep_iata and not arr_iata:
        raise HTTPException(status_code=400, detail="dep_iata or arr_iata is required")

    access = _resolve_access(install_id=install_id, activation_token=activation_token, service="aviationstack")
    month = _month_key()
    current = _get_usage(access["subject_key"], "aviationstack", month)
    if current >= access["limit"]:
        return JSONResponse(
            {
                "error": {
                    "code": "quota_exceeded",
                    "info": f"{access['plan'].title()} schedule quota exceeded: {current}/{access['limit']} calls used this month.",
                }
            },
            status_code=429,
            headers=_quota_headers("aviationstack", current, access["limit"], access["plan"]),
        )

    try:
        aviationstack_key = _aviationstack_key()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    params: Dict[str, Any] = {"access_key": aviationstack_key, "limit": limit}
    if flight_date:
        params["flight_date"] = str(flight_date).strip()
    if offset > 0:
        params["offset"] = int(offset)
    if dep_iata:
        params["dep_iata"] = dep_iata
    if arr_iata:
        params["arr_iata"] = arr_iata

    scope = "departures" if dep_iata else "arrivals"
    t0 = time.monotonic()
    try:
        upstream = _req.get(
            AVIATIONSTACK_URL,
            params=params,
            headers={"User-Agent": "localflight-relay/1.0"},
            timeout=25,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
    except Exception as exc:
        _log_request(
            install_id=install_id,
            scope=scope,
            status=0,
            latency_ms=0,
            service="aviationstack",
            plan=access["plan"],
        )
        raise HTTPException(status_code=502, detail=f"AviationStack unreachable: {exc}")

    used = _increment_usage(
        subject_key=access["subject_key"],
        service="aviationstack",
        month=month,
        plan=access["plan"],
        install_id=install_id,
    )
    _log_request(
        install_id=install_id,
        scope=scope,
        status=upstream.status_code,
        latency_ms=latency_ms,
        service="aviationstack",
        plan=access["plan"],
    )

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type="application/json",
        headers=_quota_headers("aviationstack", used, access["limit"], access["plan"]),
    )


@app.get("/v1/radar")
def relay_radar(
    lat: float = Query(...),
    lon: float = Query(...),
    radius_nm: float = Query(20.0, ge=5.0, le=200.0),
    install_id: str = Query(...),
    activation_token: str = Query(""),
) -> Response:
    install_id = _validate_install_id(install_id)
    access = _resolve_access(install_id=install_id, activation_token=activation_token, service="radar")
    month = _month_key()
    current = _get_usage(access["subject_key"], "radar", month)
    if current >= access["limit"]:
        return JSONResponse(
            {
                "error": {
                    "code": "quota_exceeded",
                    "info": f"{access['plan'].title()} radar quota exceeded: {current}/{access['limit']} calls used this month.",
                }
            },
            status_code=429,
            headers=_quota_headers("radar", current, access["limit"], access["plan"]),
        )

    t0 = time.monotonic()
    payload = _fetch_adsbx_payload(lat, lon, radius_nm)
    latency_ms = int((time.monotonic() - t0) * 1000)
    used = _increment_usage(
        subject_key=access["subject_key"],
        service="radar",
        month=month,
        plan=access["plan"],
        install_id=install_id,
    )
    _log_request(
        install_id=install_id,
        scope=f"{int(radius_nm)}nm",
        status=200,
        latency_ms=latency_ms,
        service="radar",
        plan=access["plan"],
    )
    return Response(
        content=payload,
        status_code=200,
        media_type="application/json",
        headers=_quota_headers("radar", used, access["limit"], access["plan"]),
    )


@app.get("/v1/managed/config")
def relay_managed_config(
    install_id: str = Query(...),
    activation_token: str = Query(...),
) -> Dict[str, Any]:
    status = _build_client_status(install_id=_validate_install_id(install_id), activation_token=activation_token)
    if status.get("plan") != "managed":
        raise HTTPException(status_code=403, detail="Managed activation token required")
    return status


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(username: str = Depends(_require_admin)) -> str:
    return _render_admin(username)


@app.post("/admin/providers/save")
def admin_save_provider_keys(
    aviationstack_key: str = Form(""),
    rapidapi_key: str = Form(""),
    username: str = Depends(_require_admin),
) -> HTMLResponse:
    conn = _connect()
    changes: list[str] = []
    if aviationstack_key.strip():
        _setting_set_conn(conn, _SETTING_AVIATIONSTACK_KEY, aviationstack_key.strip())
        changes.append("AviationStack")
    if rapidapi_key.strip():
        _setting_set_conn(conn, _SETTING_RAPIDAPI_KEY, rapidapi_key.strip())
        changes.append("RapidAPI ADS-B")
    if changes:
        revision = _bump_provider_revision(conn)
        conn.commit()
        conn.close()
        message = f"Updated relay-side provider key storage for {', '.join(changes)}. Provider revision is now {revision}."
    else:
        conn.close()
        message = "No provider key changes submitted."
    return HTMLResponse(_render_admin(username, message=message))


@app.post("/admin/providers/clear")
def admin_clear_provider_key(
    provider: str = Form(...),
    username: str = Depends(_require_admin),
) -> HTMLResponse:
    mapping = {
        "aviationstack": (_SETTING_AVIATIONSTACK_KEY, "AviationStack"),
        "rapidapi": (_SETTING_RAPIDAPI_KEY, "RapidAPI ADS-B"),
    }
    if provider not in mapping:
        raise HTTPException(status_code=400, detail="Unknown provider")
    setting_key, label = mapping[provider]
    conn = _connect()
    _setting_delete_conn(conn, setting_key)
    revision = _bump_provider_revision(conn)
    conn.commit()
    conn.close()
    return HTMLResponse(
        _render_admin(
            username,
            message=f"Cleared relay-stored {label} override. Provider revision is now {revision}.",
        )
    )


@app.post("/admin/activation/create")
def admin_activation_create(
    label: str = Form(""),
    schedule_limit: int = Form(...),
    radar_limit: int = Form(...),
    username: str = Depends(_require_admin),
) -> HTMLResponse:
    token = _new_activation_token()
    conn = _connect()
    _store_activation_token(
        conn,
        token=token,
        label=label,
        schedule_limit=schedule_limit,
        radar_limit=radar_limit,
        created_by=username,
    )
    conn.commit()
    conn.close()
    return HTMLResponse(_render_admin(username, created_token=token))


@app.post("/admin/activation-request/approve")
def admin_activation_request_approve(
    request_id: str = Form(...),
    username: str = Depends(_require_admin),
) -> HTMLResponse:
    conn = _connect()
    row = conn.execute(
        """
        SELECT *
        FROM activation_requests
        WHERE request_id=?
        """,
        (request_id.strip(),),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Activation request not found")
    if str(row["status"] or "") != _REQUEST_STATUS_MANUAL_REVIEW:
        conn.close()
        return HTMLResponse(_render_admin(username, message="Activation row is no longer waiting for manual review."))

    install_id = str(row["install_id"] or "").strip()
    label = str(row["display_name"] or row["install_fingerprint"] or "Managed install")
    token, token_prefix, _issuance = _issue_token_for_install(
        conn,
        install_id=install_id,
        label=label,
        created_by=username,
    )
    now = _utc_now()
    conn.execute(
        """
        UPDATE activation_requests
        SET status=?,
            updated_at=?,
            approved_at=?,
            last_seen=?,
            decision_source=?,
            decision_note=?,
            token_hash=?,
            token_prefix=?,
            issued_token=NULL
        WHERE request_id=?
        """,
        (
            _REQUEST_STATUS_ISSUED,
            now,
            now,
            now,
            username,
            "manual issue completed",
            _token_hash(token),
            token_prefix,
            request_id.strip(),
        ),
    )
    conn.commit()
    conn.close()
    return HTMLResponse(_render_admin(username, created_token=token, message="Managed access issued for that install."))


@app.post("/admin/activation-request/reject")
def admin_activation_request_reject(
    request_id: str = Form(...),
    decision_note: str = Form("dismissed"),
    username: str = Depends(_require_admin),
) -> HTMLResponse:
    conn = _connect()
    conn.execute(
        """
        UPDATE activation_requests
        SET status=?,
            updated_at=?,
            last_seen=?,
            decision_source=?,
            decision_note=?,
            issued_token=NULL
        WHERE request_id=?
        """,
        (
            _REQUEST_STATUS_DISMISSED,
            _utc_now(),
            _utc_now(),
            username,
            decision_note.strip() or "dismissed",
            request_id.strip(),
        ),
    )
    conn.commit()
    conn.close()
    return HTMLResponse(_render_admin(username, message="Activation row dismissed."))


@app.post("/admin/activation-request/delete")
def admin_activation_request_delete(
    request_id: str = Form(...),
    username: str = Depends(_require_admin),
) -> HTMLResponse:
    conn = _connect()
    conn.execute("DELETE FROM activation_requests WHERE request_id=?", (request_id.strip(),))
    conn.commit()
    conn.close()
    return HTMLResponse(_render_admin(username, message="Activation request deleted."))


@app.post("/admin/activation/revoke")
def admin_activation_revoke(
    token_hash: str = Form(...),
    username: str = Depends(_require_admin),
) -> HTMLResponse:
    conn = _connect()
    conn.execute(
        "UPDATE activation_tokens SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
        (_utc_now(), token_hash.strip()),
    )
    conn.commit()
    conn.close()
    return HTMLResponse(_render_admin(username, message="Activation token revoked."))


@app.post("/admin/activation/reactivate")
def admin_activation_reactivate(
    token_hash: str = Form(...),
    username: str = Depends(_require_admin),
) -> HTMLResponse:
    conn = _connect()
    conn.execute(
        "UPDATE activation_tokens SET revoked_at=NULL WHERE token_hash=?",
        (token_hash.strip(),),
    )
    conn.commit()
    conn.close()
    return HTMLResponse(_render_admin(username, message="Activation token restored."))


@app.post("/admin/activation/unbind")
def admin_activation_unbind(
    token_hash: str = Form(...),
    username: str = Depends(_require_admin),
) -> HTMLResponse:
    conn = _connect()
    conn.execute(
        "UPDATE activation_tokens SET bound_install_id=NULL, last_seen=NULL WHERE token_hash=?",
        (token_hash.strip(),),
    )
    conn.commit()
    conn.close()
    return HTMLResponse(_render_admin(username, message="Token binding cleared."))


@app.post("/admin/activation/rotate")
def admin_activation_rotate(
    token_hash: str = Form(...),
    username: str = Depends(_require_admin),
) -> HTMLResponse:
    conn = _connect()
    row = conn.execute(
        """
        SELECT label, schedule_limit, radar_limit
        FROM activation_tokens
        WHERE token_hash=?
        """,
        (token_hash.strip(),),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Activation token not found")

    token = _new_activation_token()
    new_hash = _token_hash(token)
    conn.execute(
        """
        UPDATE activation_tokens
        SET token_hash=?,
            token_prefix=?,
            bound_install_id=NULL,
            last_seen=NULL,
            revoked_at=NULL,
            created_by=?
        WHERE token_hash=?
        """,
        (new_hash, token[:10], username, token_hash.strip()),
    )
    conn.execute(
        "UPDATE usage SET subject_key=? WHERE subject_key=?",
        (f"managed:{new_hash}", f"managed:{token_hash.strip()}"),
    )
    conn.commit()
    conn.close()
    return HTMLResponse(_render_admin(username, created_token=token, message="Activation token reshuffled."))


@app.post("/admin/activation/delete")
def admin_activation_delete(
    token_hash: str = Form(...),
    username: str = Depends(_require_admin),
) -> HTMLResponse:
    conn = _connect()
    conn.execute("DELETE FROM activation_tokens WHERE token_hash=?", (token_hash.strip(),))
    conn.commit()
    conn.close()
    return HTMLResponse(_render_admin(username, message="Activation token deleted."))


@app.post("/admin/install/block")
def admin_install_block(
    install_id: str = Form(...),
    reason: str = Form("revoked by admin"),
    username: str = Depends(_require_admin),
) -> HTMLResponse:
    install_id = _validate_install_id(install_id)
    conn = _connect()
    conn.execute(
        """
        INSERT INTO blocked_installs (install_id, reason, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT(install_id) DO UPDATE SET
            reason = excluded.reason,
            created_at = excluded.created_at
        """,
        (install_id, reason.strip() or "revoked by admin", _utc_now()),
    )
    conn.commit()
    conn.close()
    return HTMLResponse(_render_admin(username, message="Install access revoked."))


@app.post("/admin/install/unblock")
def admin_install_unblock(
    install_id: str = Form(...),
    username: str = Depends(_require_admin),
) -> HTMLResponse:
    install_id = _validate_install_id(install_id)
    conn = _connect()
    conn.execute("DELETE FROM blocked_installs WHERE install_id=?", (install_id,))
    conn.commit()
    conn.close()
    return HTMLResponse(_render_admin(username, message="Install access restored."))


@app.post("/admin/counters/reset")
def admin_reset_counters(
    scope: str = Form(...),
    service: str = Form(""),
    token_hash: str = Form(""),
    install_id: str = Form(""),
    username: str = Depends(_require_admin),
) -> HTMLResponse:
    conn = _connect()
    month = _month_key()

    if scope == "all":
        conn.execute("DELETE FROM usage WHERE month=?", (month,))
        message = "Reset all monthly relay counters."
    elif scope == "service":
        if service not in {"aviationstack", "radar"}:
            conn.close()
            raise HTTPException(status_code=400, detail="Unknown service")
        conn.execute("DELETE FROM usage WHERE month=? AND service=?", (month, service))
        message = f"Reset monthly counters for {service}."
    elif scope == "token":
        if not token_hash.strip():
            conn.close()
            raise HTTPException(status_code=400, detail="token_hash required")
        conn.execute(
            "DELETE FROM usage WHERE month=? AND subject_key=?",
            (month, f"managed:{token_hash.strip()}"),
        )
        message = "Reset counters for the selected activation token."
    elif scope == "install":
        install_id = _validate_install_id(install_id)
        conn.execute("DELETE FROM usage WHERE month=? AND install_id=?", (month, install_id))
        message = "Reset counters for the selected install."
    elif scope == "logs":
        conn.execute("DELETE FROM request_log")
        message = "Cleared the network request log."
    else:
        conn.close()
        raise HTTPException(status_code=400, detail="Unknown reset scope")

    conn.commit()
    conn.close()
    return HTMLResponse(_render_admin(username, message=message))


@app.post("/admin/counters/correct-schedule")
def admin_correct_schedule(
    total: int = Form(...),
    username: str = Depends(_require_admin),
) -> HTMLResponse:
    conn = _connect()
    month = _month_key()
    db_count = conn.execute(
        "SELECT COALESCE(SUM(calls), 0) FROM usage WHERE month=? AND service='aviationstack'",
        (month,),
    ).fetchone()[0] or 0
    offset = max(0, total - db_count)
    _setting_set_conn(conn, f"schedule_counter_offset:{month}", str(offset))
    conn.commit()
    conn.close()
    return HTMLResponse(_render_admin(username, message=f"Schedule total corrected to {total:,} ({offset:,} offset stored for {month})."))


def main() -> None:
    uvicorn.run(
        app,
        host=_env("HOST", "0.0.0.0"),
        port=int(_env("PORT", "8080")),
        reload=False,
    )


if __name__ == "__main__":
    main()
