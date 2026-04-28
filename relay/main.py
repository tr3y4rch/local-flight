from __future__ import annotations

import hashlib
import html
import hmac
import os
import re
import secrets
import sqlite3
import time
import uuid
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


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _community_schedule_limit() -> int:
    try:
        return int(_env("RELAY_MONTHLY_LIMIT", "50"))
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
    install_id: str,
) -> int:
    conn = _connect()
    now = _utc_now()
    conn.execute(
        """
        INSERT INTO usage (subject_key, service, month, calls, last_seen, plan, install_id)
        VALUES (?, ?, ?, 1, ?, ?, ?)
        ON CONFLICT(subject_key, service, month) DO UPDATE SET
            calls = calls + 1,
            last_seen = excluded.last_seen,
            plan = excluded.plan,
            install_id = excluded.install_id
        """,
        (subject_key, service, month, now, plan, install_id),
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
    airport: str,
    mode: str,
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
            (_utc_now(), install_id, airport, mode, status, latency_ms, service, plan),
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
    airport_iata: Optional[str],
    airport_icao: Optional[str],
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
            airport_iata,
            airport_icao,
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
        "SELECT COUNT(DISTINCT install_id) FROM usage WHERE month=?",
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
                   airport_iata,
                   airport_icao,
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
            WHERE u.month=?
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
            SELECT ts, install_id, airport, mode, status, latency_ms, service, plan
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
            return "<tr><td colspan='10' class='muted'>No activation activity yet</td></tr>"
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
            route = " / ".join(
                [part for part in [str(row["airport_iata"] or "").strip(), str(row["airport_icao"] or "").strip()] if part]
            ) or "-"
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
                f"<td>{html.escape(route)}</td>"
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
            f"<td>{html.escape(str(row['airport'] or '-'))}</td>"
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
    <div class="card"><h2>Schedule calls</h2><div class="big">{int(total_schedule or 0):,} / {_managed_schedule_limit():,}</div></div>
    <div class="card"><h2>Radar calls</h2><div class="big">{int(total_radar or 0)}</div></div>
    <div class="card"><h2>Requests (24h)</h2><div class="big">{int(totals_24h['requests'] or 0)}</div></div>
    <div class="card"><h2>Errors (24h)</h2><div class="big">{int(totals_24h['errors'] or 0)}</div></div>
    <div class="card"><h2>Manual reviews</h2><div class="big">{int(pending_requests or 0)}</div></div>
    <div class="card"><h2>Provider revision</h2><div class="big">{provider_revision}</div></div>
    <div class="card"><h2>Avg latency</h2><div class="big">{int(totals_24h['avg_latency'] or 0)}ms</div></div>
    <div class="card"><h2>Blocked installs</h2><div class="big">{int(blocked_count or 0)}</div></div>
  </div>

  <div class="split">
    <div class="card stack">
      <div>
        <h2>Provider keys</h2>
        <div class="kicker">Managed clients do not receive raw vendor keys. Key changes take effect on the next relay request and advance the provider revision.</div>
        <div class="provider-line"><span>AviationStack</span><span>{html.escape(_mask_secret(aviationstack_key))} <span class="tiny">({html.escape(aviationstack_source)})</span></span></div>
        <div class="provider-line"><span>RapidAPI ADS-B</span><span>{html.escape(_mask_secret(rapidapi_key))} <span class="tiny">({html.escape(rapidapi_source)})</span></span></div>
        <div class="provider-line"><span>Community schedule cap</span><span>{_community_schedule_limit()} calls per install / 30-day window</span></div>
        <div class="provider-line"><span>Radar cache</span><span>{_radar_cache_seconds()}s</span></div>
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
    <thead><tr><th>Install</th><th>Network tag</th><th>Airport</th><th>Request</th><th>Status</th><th>Source</th><th>Token</th><th>Note</th><th>Created</th><th>Actions</th></tr></thead>
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


app = FastAPI(title="Local Flight Network Admin", docs_url=None, redoc_url=None)


@app.on_event("startup")
def _startup() -> None:
    _db_path().parent.mkdir(parents=True, exist_ok=True)
    _ensure_schema()


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/admin", status_code=307)


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "provider_revision": _provider_revision()}


class ActivationRequestIn(BaseModel):
    install_id: str
    install_fingerprint: str
    airport_iata: str = ""
    airport_icao: str = ""
    display_name: str = ""
    requested_mode: str = "managed"
    app_version: str = ""


class ClientStatusIn(BaseModel):
    install_id: str
    activation_token: str = ""
    app_version: str = ""


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
    }


@app.post("/v1/activate")
def relay_activate(body: ActivationRequestIn, request: Request) -> Dict[str, Any]:
    install_id = _validate_install_id(body.install_id)
    install_fingerprint = (body.install_fingerprint or "").strip()
    expected_fingerprint = _install_fingerprint(install_id)
    if install_fingerprint != expected_fingerprint:
        raise HTTPException(status_code=400, detail="install_fingerprint does not match install_id")

    airport_iata = _clean_airport(body.airport_iata) if body.airport_iata else None
    airport_icao = _clean_airport(body.airport_icao) if body.airport_icao else None
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
            airport_iata=airport_iata,
            airport_icao=airport_icao,
            display_name=display_name or f"Local Flight {airport_iata or airport_icao or expected_fingerprint}",
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
        label=display_name or f"Local Flight {airport_iata or airport_icao or expected_fingerprint}",
        created_by="auto-issue",
    )
    request_id = _record_activation_event(
        conn,
        install_id=install_id,
        install_fingerprint=install_fingerprint,
        network_tag=network_tag,
        airport_iata=airport_iata,
        airport_icao=airport_icao,
        display_name=display_name or f"Local Flight {airport_iata or airport_icao or expected_fingerprint}",
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
    return _build_client_status(
        install_id=install_id,
        activation_token=(body.activation_token or "").strip(),
        app_version=body.app_version,
    )


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


@app.get("/v1/flights")
def relay_flights(
    dep_iata: Optional[str] = Query(None),
    arr_iata: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=100),
    install_id: str = Query(...),
    activation_token: str = Query(""),
) -> Response:
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
    if dep_iata:
        params["dep_iata"] = dep_iata
    if arr_iata:
        params["arr_iata"] = arr_iata

    airport = dep_iata or arr_iata or ""
    mode = "dep" if dep_iata else "arr"
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
            airport=airport,
            mode=mode,
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
        airport=airport,
        mode=mode,
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
        airport=f"{round(lat, 2)},{round(lon, 2)}",
        mode=f"{int(radius_nm)}nm",
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
    label = str(row["display_name"] or row["airport_iata"] or row["install_fingerprint"] or "Managed install")
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
        "relay.main:app",
        host=_env("HOST", "0.0.0.0"),
        port=int(_env("PORT", "8080")),
        reload=False,
    )


if __name__ == "__main__":
    main()
