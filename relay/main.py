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
from dataclasses import asdict
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests as _req
import uvicorn
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field, field_validator

AVIATIONSTACK_URL = "https://api.aviationstack.com/v1/flights"
AERODATABOX_RAPIDAPI_URL = "https://aerodatabox.p.rapidapi.com"
AERODATABOX_APIMARKET_URL = "https://prod.api.market/api/v1/aedbx/aerodatabox"
ADSBX_URL = "https://adsbexchange-com1.p.rapidapi.com/v2"

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_AIRPORT_RE = re.compile(r"^[A-Z0-9]{2,4}$")
_SCHEDULE_CACHE_KEY_RE = re.compile(r"^sch_[0-9a-f]{24}$")
_NETWORK_TAG_RE = re.compile(r"^net_[0-9a-f]{14}$")

_SETTING_AVIATIONSTACK_KEY = "provider_aviationstack_key"
_SETTING_AERODATABOX_KEY = "provider_aerodatabox_key"
_SETTING_RAPIDAPI_KEY = "provider_rapidapi_key"
_SETTING_PROVIDER_REVISION = "provider_revision"
_SETTING_NETWORK_SECRET = "network_secret"
_CLIENT_KINDS = {"desktop", "mobile_companion", "mobile_standalone", "matrix", "unknown"}
_DEVICE_TYPES = {"phone", "tablet", "desktop", "unknown"}
_REQUEST_STATUS_PENDING = "pending"
_REQUEST_STATUS_APPROVED = "approved"
_REQUEST_STATUS_REJECTED = "rejected"
_REQUEST_STATUS_ISSUED = "issued"
_REQUEST_STATUS_MANUAL_REVIEW = "manual_review"
_REQUEST_STATUS_DISMISSED = "dismissed"

_AUTO_ACTIVATION_NETWORK_DAILY_LIMIT = 6
_AUTO_ACTIVATION_NETWORK_INSTALLS_DAILY_LIMIT = 4
_SHARED_SCHEDULE_PROVIDER = "aviationstack"
_SHARED_SCHEDULE_PLANNER_VERSION = "fair-v5"
_SHARED_SCHEDULE_SCHEMA_VERSION = "canonical-raw-v1"
_SHARED_SCHEDULE_LOCK_WAIT_S = 4.0
_SHARED_SCHEDULE_MIN_FRESH_TTL_S = 900
_COMMUNITY_SCHEDULE_MIN_FRESH_TTL_S = 3600
_SCHEDULE_GRACE_BUCKETS = (0, 30, 60, 120, 180)
_SCHEDULE_HORIZON_BUCKETS = (6, 12, 18, 24)
_AERODATABOX_MAX_FIDS_DURATION_MINUTES = 720
_AIRPORT_SURFACE_SCHEMA_VERSION = "osm-surface-v1"
_AIRPORT_SURFACE_LOCK_WAIT_S = 4.0

_schedule_refresh_locks: Dict[str, threading.Lock] = {}
_schedule_refresh_locks_guard = threading.Lock()
_airport_surface_locks: Dict[str, threading.Lock] = {}
_airport_surface_locks_guard = threading.Lock()
_admin_auth_failures: Dict[str, list[float]] = {}
_admin_auth_failures_guard = threading.Lock()
_heartbeat_last_seen: Dict[str, float] = {}
_heartbeat_guard = threading.Lock()
_HEARTBEAT_MIN_INTERVAL_S = 300  # 5 minutes per install

_REPORT_CRASH_DEDUPE_HOURS = 6
_REPORT_MANUAL_DEDUPE_MINUTES = 30
_REPORT_MANUAL_INSTALL_DAILY_LIMIT = 5
_REPORT_CRASH_INSTALL_DAILY_LIMIT = 20
_REPORT_NETWORK_DAILY_LIMIT = 60
_COMMUNITY_SCHEDULE_NETWORK_DAILY_LIMIT = 240
_COMMUNITY_SCHEDULE_GLOBAL_DAILY_LIMIT = 1000
_COMMUNITY_RADAR_NETWORK_DAILY_LIMIT = 600
_COMMUNITY_RADAR_GLOBAL_DAILY_LIMIT = 3000
_STANDALONE_SCHEDULE_LIMIT = 600
_STANDALONE_RADAR_LIMIT = 3000
_STANDALONE_SCHEDULE_MIN_REFRESH_SECONDS = 3 * 60 * 60
_STANDALONE_RADAR_MIN_REFRESH_SECONDS = 5 * 60
_STANDALONE_RADAR_RADII_NM = (1, 3, 5, 10)
_ADMIN_AUTH_FAILURE_LIMIT = 8
_ADMIN_AUTH_WINDOW_SECONDS = 5 * 60
_LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"

_REPORT_ALLOWED_TYPES = {"manual", "crash"}
_REPORT_ALLOWED_ORIGINS = {"desktop", "web", "server", "scheduler", "mobile", "ios", "relay"}
_REPORT_TEAM_ENV = {
    "ios": "LINEAR_TEAM_IOS_ID",
    "desktop": "LINEAR_TEAM_DESKTOP_ID",
    "server": "LINEAR_TEAM_SERVER_ID",
    "relay": "LINEAR_TEAM_RELAY_ID",
    "default": "LINEAR_TEAM_DEFAULT_ID",
}
_APPLE_IAP_SUPPORT_PRODUCT_IDS = {
    "com.localflight.companion.tip.2",
    "com.localflight.companion.tip.5",
    "com.localflight.companion.tip.10",
    "com.localflight.companion.tip.20",
}

_SECRET_PATTERNS = (
    (re.compile(r"(AVIATIONSTACK_API_KEY|AERODATABOX_API_KEY|RAPIDAPI_KEY|OPENSKY_CLIENT_SECRET|LINEAR_API_KEY|LINEAR_REPORTER_API_KEY)=\S+", re.I), r"\1=[redacted]"),
    (re.compile(r"(access_key=)[^&\s]+", re.I), r"\1[redacted]"),
    (re.compile(r"(X-RapidAPI-Key['\":\s]+)[A-Za-z0-9._-]+", re.I), r"\1[redacted]"),
    (re.compile(r"(x-magicapi-key['\":\s]+)[A-Za-z0-9._-]+", re.I), r"\1[redacted]"),
    (re.compile(r"lin_api_[A-Za-z0-9_]+", re.I), "[redacted-linear-token]"),
    (re.compile(r"lfm_[A-Za-z0-9._-]+", re.I), "[redacted-activation-token]"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "[redacted-uuid]"),
    (re.compile(r"\b10\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b"), r"10.\1.\2.x"),
    (re.compile(r"\b192\.168\.(\d{1,3})\.(\d{1,3})\b"), r"192.168.\1.x"),
    (re.compile(r"\b172\.(1[6-9]|2\d|3[01])\.(\d{1,3})\.(\d{1,3})\b"), r"172.\1.\2.x"),
)


class UpstreamBudgetExceeded(HTTPException):
    def __init__(
        self,
        *,
        provider: str,
        service: str,
        current: int,
        limit: int,
        requested: int,
        period: str = "monthly",
    ) -> None:
        self.provider = provider
        self.service = service
        self.current = int(current)
        self.limit = int(limit)
        self.requested = int(requested)
        self.period = period
        super().__init__(
            status_code=429,
            detail=(
                f"{provider} upstream {period} budget capped: "
                f"{current}/{limit} used, {requested} requested."
            ),
        )


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _int_env(key: str, default: int, *, minimum: int = 0) -> int:
    try:
        return max(minimum, int(_env(key, str(default))))
    except (TypeError, ValueError):
        return max(minimum, int(default))


def _public_host() -> str:
    return _normalized_host(_env("RELAY_PUBLIC_HOST", "relay.beacontools.cc"))


def _admin_host() -> str:
    return _normalized_host(_env("RELAY_ADMIN_HOST", "network.beacontools.cc"))


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
    return _normalized_host(request.headers.get("host") or request.headers.get("x-forwarded-host") or "")


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
        if path == "/v1/flights":
            return False
        return path in {"/", "/health"} or path.startswith("/v1/")
    return True


def _community_schedule_limit() -> int:
    try:
        return max(0, int(_env("RELAY_COMMUNITY_SCHEDULE_LIMIT", _env("RELAY_MONTHLY_LIMIT", "50"))))
    except ValueError:
        return 50


def _community_radar_limit() -> int:
    try:
        return max(0, int(_env("RELAY_RADAR_MONTHLY_LIMIT", "600")))
    except ValueError:
        return 600


def _community_daily_limit(service: str, scope: str) -> int:
    service_key = "SCHEDULE" if service == "aviationstack" else "RADAR"
    scope_key = "NETWORK" if scope == "network" else "GLOBAL"
    defaults = {
        ("SCHEDULE", "NETWORK"): _COMMUNITY_SCHEDULE_NETWORK_DAILY_LIMIT,
        ("SCHEDULE", "GLOBAL"): _COMMUNITY_SCHEDULE_GLOBAL_DAILY_LIMIT,
        ("RADAR", "NETWORK"): _COMMUNITY_RADAR_NETWORK_DAILY_LIMIT,
        ("RADAR", "GLOBAL"): _COMMUNITY_RADAR_GLOBAL_DAILY_LIMIT,
    }
    default = defaults[(service_key, scope_key)]
    try:
        return max(0, int(_env(f"RELAY_COMMUNITY_{service_key}_{scope_key}_DAILY_LIMIT", str(default))))
    except ValueError:
        return default


def _auto_activation_network_daily_limit() -> int:
    try:
        return max(
            1,
            int(
                _env(
                    "RELAY_AUTO_ACTIVATION_NETWORK_DAILY_LIMIT",
                    str(_AUTO_ACTIVATION_NETWORK_DAILY_LIMIT),
                )
            ),
        )
    except ValueError:
        return _AUTO_ACTIVATION_NETWORK_DAILY_LIMIT


def _auto_activation_network_installs_daily_limit() -> int:
    try:
        return max(
            1,
            int(
                _env(
                    "RELAY_AUTO_ACTIVATION_NETWORK_INSTALLS_DAILY_LIMIT",
                    str(_AUTO_ACTIVATION_NETWORK_INSTALLS_DAILY_LIMIT),
                )
            ),
        )
    except ValueError:
        return _AUTO_ACTIVATION_NETWORK_INSTALLS_DAILY_LIMIT


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


def _standalone_schedule_limit() -> int:
    try:
        return max(1, int(_env("RELAY_STANDALONE_SCHEDULE_LIMIT", str(_STANDALONE_SCHEDULE_LIMIT))))
    except ValueError:
        return _STANDALONE_SCHEDULE_LIMIT


def _standalone_radar_limit() -> int:
    try:
        return max(1, int(_env("RELAY_STANDALONE_RADAR_LIMIT", str(_STANDALONE_RADAR_LIMIT))))
    except ValueError:
        return _STANDALONE_RADAR_LIMIT


def _standalone_schedule_min_refresh_seconds() -> int:
    try:
        return max(
            _shared_schedule_min_fresh_ttl_seconds(),
            int(
                _env(
                    "RELAY_STANDALONE_SCHEDULE_MIN_REFRESH_SECONDS",
                    str(_STANDALONE_SCHEDULE_MIN_REFRESH_SECONDS),
                )
            ),
        )
    except ValueError:
        return max(_shared_schedule_min_fresh_ttl_seconds(), _STANDALONE_SCHEDULE_MIN_REFRESH_SECONDS)


def _standalone_radar_min_refresh_seconds() -> int:
    try:
        return max(
            _radar_cache_seconds(),
            int(_env("RELAY_STANDALONE_RADAR_MIN_REFRESH_SECONDS", str(_STANDALONE_RADAR_MIN_REFRESH_SECONDS))),
        )
    except ValueError:
        return max(_radar_cache_seconds(), _STANDALONE_RADAR_MIN_REFRESH_SECONDS)


def _radar_cache_seconds() -> int:
    try:
        return max(30, int(_env("RELAY_RADAR_CACHE_SECONDS", "300")))
    except ValueError:
        return 300


def _shared_schedule_min_fresh_ttl_seconds() -> int:
    try:
        return max(
            180,
            int(
                _env(
                    "RELAY_SHARED_SCHEDULE_MIN_FRESH_TTL_SECONDS",
                    str(_SHARED_SCHEDULE_MIN_FRESH_TTL_S),
                )
            ),
        )
    except ValueError:
        return _SHARED_SCHEDULE_MIN_FRESH_TTL_S


def _community_schedule_min_fresh_ttl_seconds() -> int:
    try:
        return max(
            _shared_schedule_min_fresh_ttl_seconds(),
            int(
                _env(
                    "RELAY_COMMUNITY_SCHEDULE_MIN_FRESH_TTL_SECONDS",
                    str(_COMMUNITY_SCHEDULE_MIN_FRESH_TTL_S),
                )
            ),
        )
    except ValueError:
        return max(_shared_schedule_min_fresh_ttl_seconds(), _COMMUNITY_SCHEDULE_MIN_FRESH_TTL_S)


def _schedule_min_fresh_ttl_seconds_for_plan(plan: Any) -> int:
    return (
        _community_schedule_min_fresh_ttl_seconds()
        if str(plan or "community").lower() == "community"
        else _shared_schedule_min_fresh_ttl_seconds()
    )


def _clean_client_kind(value: Any) -> str:
    kind = re.sub(r"[^a-z0-9_]", "", str(value or "").strip().lower())
    return kind if kind in _CLIENT_KINDS else "unknown"


def _clean_device_type(value: Any) -> str:
    device = re.sub(r"[^a-z0-9_]", "", str(value or "").strip().lower())
    return device if device in _DEVICE_TYPES else "unknown"


def _is_mobile_standalone(value: Any) -> bool:
    return _clean_client_kind(value) == "mobile_standalone"


def _airport_surface_enabled() -> bool:
    return _env("RELAY_AIRPORT_SURFACE_ENABLED", "").lower() in {"1", "true", "yes", "on"}


def _admin_password() -> str:
    return _env("RELAY_ADMIN_PASSWORD", "changeme")


def _db_path() -> Path:
    return Path(_env("DB_PATH", "./relay.db"))


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
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
        CREATE TABLE IF NOT EXISTS report_dedupe (
            dedupe_key          TEXT PRIMARY KEY,
            team                TEXT NOT NULL,
            report_type         TEXT NOT NULL,
            origin              TEXT NOT NULL,
            install_fingerprint TEXT NOT NULL,
            first_seen          TEXT NOT NULL,
            last_seen           TEXT NOT NULL,
            count               INTEGER DEFAULT 1,
            url                 TEXT
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
        CREATE TABLE IF NOT EXISTS provider_schedule_snapshots (
            cache_key               TEXT PRIMARY KEY,
            provider                TEXT NOT NULL,
            airport_iata            TEXT NOT NULL,
            timezone                TEXT NOT NULL,
            display_grace_minutes   INTEGER NOT NULL,
            display_horizon_hours   INTEGER NOT NULL,
            policy_version          TEXT NOT NULL,
            generated_at            TEXT NOT NULL,
            updated_at              TEXT NOT NULL,
            meta_json               TEXT NOT NULL,
            records_json            TEXT NOT NULL,
            refresh_count           INTEGER DEFAULT 0,
            last_error              TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS provider_circuit_breakers (
            provider       TEXT PRIMARY KEY,
            failure_count  INTEGER DEFAULT 0,
            opened_until   TEXT,
            last_error     TEXT,
            updated_at     TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS airport_surface_snapshots (
            cache_key        TEXT PRIMARY KEY,
            airport_iata     TEXT NOT NULL,
            airport_icao     TEXT,
            schema_version   TEXT NOT NULL,
            provider         TEXT NOT NULL,
            center_lat       REAL NOT NULL,
            center_lon       REAL NOT NULL,
            radius_nm        REAL NOT NULL,
            generated_at     TEXT NOT NULL,
            updated_at       TEXT NOT NULL,
            features_json    TEXT NOT NULL,
            meta_json        TEXT,
            request_count    INTEGER DEFAULT 0,
            cache_hits       INTEGER DEFAULT 0,
            refresh_count    INTEGER DEFAULT 0,
            stale_serves     INTEGER DEFAULT 0,
            last_cache_state TEXT,
            last_error       TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS report_events (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            ts                  TEXT NOT NULL,
            install_fingerprint TEXT NOT NULL,
            network_tag         TEXT NOT NULL,
            report_type         TEXT NOT NULL,
            origin              TEXT NOT NULL,
            context             TEXT,
            team                TEXT NOT NULL,
            status              TEXT NOT NULL,
            dedupe_key          TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS client_interests (
            install_id               TEXT PRIMARY KEY,
            plan                     TEXT NOT NULL,
            client_kind              TEXT,
            airport_iata             TEXT,
            airport_icao             TEXT,
            timezone                 TEXT,
            display_grace_minutes    INTEGER,
            display_horizon_hours    INTEGER,
            refresh_seconds          INTEGER,
            last_seen                TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS install_profiles (
            install_id           TEXT PRIMARY KEY,
            first_seen           TEXT NOT NULL,
            last_seen            TEXT NOT NULL,
            last_heartbeat_at    TEXT,
            last_checkin_at      TEXT,
            last_relay_activity_at TEXT,
            client_kind          TEXT,
            device_type          TEXT,
            airport_iata         TEXT,
            airport_icao         TEXT,
            timezone             TEXT,
            app_version          TEXT,
            os_family            TEXT,
            os_version           TEXT,
            arch                 TEXT,
            requested_gui        TEXT,
            effective_gui        TEXT,
            source_mode          TEXT,
            diagnostics_mode     TEXT,
            companion_count      INTEGER DEFAULT 0,
            matrix_count         INTEGER DEFAULT 0,
            matrix_online_count  INTEGER DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mobile_standalone_cache (
            install_id   TEXT NOT NULL,
            service      TEXT NOT NULL,
            cache_key    TEXT NOT NULL,
            last_seen    TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (install_id, service, cache_key)
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
    _ensure_column(conn, "schedule_snapshots", "client_accesses INTEGER DEFAULT 0")
    _ensure_column(conn, "schedule_snapshots", "upstream_pulls INTEGER DEFAULT 0")
    _ensure_column(conn, "schedule_snapshots", "refresh_count INTEGER DEFAULT 0")
    _ensure_column(conn, "schedule_snapshots", "cache_hits INTEGER DEFAULT 0")
    _ensure_column(conn, "schedule_snapshots", "stale_serves INTEGER DEFAULT 0")
    _ensure_column(conn, "schedule_snapshots", "last_cache_state TEXT")
    _ensure_column(conn, "schedule_snapshots", "last_error TEXT")
    _ensure_column(conn, "airport_surface_snapshots", "request_count INTEGER DEFAULT 0")
    _ensure_column(conn, "airport_surface_snapshots", "cache_hits INTEGER DEFAULT 0")
    _ensure_column(conn, "airport_surface_snapshots", "refresh_count INTEGER DEFAULT 0")
    _ensure_column(conn, "airport_surface_snapshots", "stale_serves INTEGER DEFAULT 0")
    _ensure_column(conn, "airport_surface_snapshots", "last_cache_state TEXT")
    _ensure_column(conn, "airport_surface_snapshots", "last_error TEXT")
    _ensure_column(conn, "install_profiles", "app_version TEXT")
    _ensure_column(conn, "install_profiles", "last_heartbeat_at TEXT")
    _ensure_column(conn, "install_profiles", "last_checkin_at TEXT")
    _ensure_column(conn, "install_profiles", "last_relay_activity_at TEXT")
    _ensure_column(conn, "install_profiles", "client_kind TEXT")
    _ensure_column(conn, "install_profiles", "device_type TEXT")
    _ensure_column(conn, "install_profiles", "airport_iata TEXT")
    _ensure_column(conn, "install_profiles", "airport_icao TEXT")
    _ensure_column(conn, "install_profiles", "timezone TEXT")
    _ensure_column(conn, "install_profiles", "os_family TEXT")
    _ensure_column(conn, "install_profiles", "os_version TEXT")
    _ensure_column(conn, "install_profiles", "arch TEXT")
    _ensure_column(conn, "install_profiles", "requested_gui TEXT")
    _ensure_column(conn, "install_profiles", "effective_gui TEXT")
    _ensure_column(conn, "install_profiles", "source_mode TEXT")
    _ensure_column(conn, "install_profiles", "diagnostics_mode TEXT")
    _ensure_column(conn, "install_profiles", "companion_count INTEGER DEFAULT 0")
    _ensure_column(conn, "install_profiles", "matrix_count INTEGER DEFAULT 0")
    _ensure_column(conn, "install_profiles", "matrix_online_count INTEGER DEFAULT 0")
    _ensure_column(conn, "client_interests", "client_kind TEXT")
    _ensure_column(conn, "client_interests", "airport_icao TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_month_service ON usage (month, service, calls DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_activation_revoked ON activation_tokens (revoked_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_activation_requests_status ON activation_requests (status, created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_log_ts ON request_log (ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_report_events_install ON report_events (install_fingerprint, report_type, ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_report_events_network ON report_events (network_tag, ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_report_dedupe_seen ON report_dedupe (last_seen)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_schedule_snapshots_airport ON schedule_snapshots (airport_iata, updated_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_provider_schedule_snapshots_airport ON provider_schedule_snapshots (provider, airport_iata, updated_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_provider_circuit_breakers_open ON provider_circuit_breakers (opened_until)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_airport_surface_updated ON airport_surface_snapshots (airport_iata, updated_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_client_interests_last_seen ON client_interests (last_seen DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_install_profiles_last_seen ON install_profiles (last_seen DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mobile_standalone_cache_seen ON mobile_standalone_cache (service, last_seen DESC)")
    _backfill_install_profiles(conn)
    conn.commit()
    conn.close()


def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _day_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _minute_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


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


def _normalize_timezone_name(value: str) -> str:
    clean = (value or "").strip()
    if not clean:
        raise HTTPException(status_code=400, detail="timezone is required")
    if len(clean) > 64:
        raise HTTPException(status_code=400, detail="timezone is too long")
    try:
        return ZoneInfo(clean).key
    except (ZoneInfoNotFoundError, ValueError):
        return "UTC"


def _bucket_at_least(value: int, buckets: tuple[int, ...]) -> int:
    number = int(value)
    for bucket in buckets:
        if number <= int(bucket):
            return int(bucket)
    return int(buckets[-1])


def _bucket_schedule_window(display_grace_minutes: int, display_horizon_hours: int) -> tuple[int, int]:
    return (
        _bucket_at_least(max(0, int(display_grace_minutes)), _SCHEDULE_GRACE_BUCKETS),
        _bucket_at_least(max(1, int(display_horizon_hours)), _SCHEDULE_HORIZON_BUCKETS),
    )


def _canonical_schedule_airport(value: str) -> Dict[str, str]:
    airport_iata = _clean_airport(value)
    try:
        from localflight.core.airports import get_airport_timezone, lookup_airport
    except Exception:
        lookup_airport = None
        get_airport_timezone = None

    rec = lookup_airport(iata=airport_iata) if lookup_airport is not None else None
    if rec is None and lookup_airport is not None:
        rec = lookup_airport(icao=airport_iata)
    if rec is None:
        raise HTTPException(status_code=400, detail="unknown airport_iata")
    canonical_iata = str(rec.iata or airport_iata).upper().strip()
    if not canonical_iata:
        raise HTTPException(status_code=400, detail="unknown airport_iata")
    airport_timezone = "UTC"
    if get_airport_timezone is not None:
        airport_timezone = get_airport_timezone(str(rec.country or ""), str(rec.region or ""))
    timezone_name = _normalize_timezone_name(airport_timezone)
    return {
        "iata": canonical_iata,
        "icao": str(rec.icao or "").upper().strip(),
        "timezone": timezone_name,
    }


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


def _header_ip(value: str) -> str:
    candidate = (value or "").split(",", 1)[0].strip()
    if not candidate or len(candidate) > 64:
        return ""
    return candidate


def _client_ip(request: Request) -> str:
    # Fly sets this at the edge. Do not trust generic X-Forwarded-For here:
    # clients can spoof it and bypass network-level abuse counters.
    fly_ip = _header_ip(request.headers.get("fly-client-ip", ""))
    if fly_ip:
        return fly_ip
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


def _aerodatabox_key() -> str:
    key, _source = _provider_status(_SETTING_AERODATABOX_KEY, "AERODATABOX_API_KEY")
    if not key:
        raise RuntimeError("AeroDataBox provider key is not configured in relay admin or environment")
    return key


def _aerodatabox_marketplace() -> str:
    raw = _env("RELAY_AERODATABOX_MARKETPLACE", _env("AERODATABOX_MARKETPLACE", "apimarket"))
    value = raw.lower().replace("_", "-")
    if value in {"rapid", "rapid-api", "rapidapi"}:
        return "rapidapi"
    return "apimarket"


def _aerodatabox_request_url(airport_iata: str) -> str:
    base = AERODATABOX_RAPIDAPI_URL if _aerodatabox_marketplace() == "rapidapi" else AERODATABOX_APIMARKET_URL
    return f"{base}/flights/airports/iata/{airport_iata.upper().strip()}"


def _aerodatabox_request_headers() -> Dict[str, str]:
    if _aerodatabox_marketplace() == "rapidapi":
        return {
            "X-RapidAPI-Key": _aerodatabox_key(),
            "X-RapidAPI-Host": "aerodatabox.p.rapidapi.com",
            "Accept": "application/json",
            "User-Agent": "localflight-relay/0.2.7",
        }
    return {
        "x-magicapi-key": _aerodatabox_key(),
        "Accept": "application/json",
        "User-Agent": "localflight-relay/0.2.7",
    }


def _has_aerodatabox_key() -> bool:
    key, _source = _provider_status(_SETTING_AERODATABOX_KEY, "AERODATABOX_API_KEY")
    return bool(key)


def _has_aviationstack_key() -> bool:
    try:
        return bool(_aviationstack_key())
    except RuntimeError:
        return False


def _rapidapi_key() -> str:
    key, _source = _provider_status(_SETTING_RAPIDAPI_KEY, "RAPIDAPI_KEY")
    if not key:
        raise RuntimeError("RapidAPI ADS-B provider key is not configured in relay admin or environment")
    return key


def _schedule_provider_mode() -> str:
    value = _env("RELAY_SCHEDULE_PROVIDER", "auto").lower()
    return value if value in {"auto", "aerodatabox", "aviationstack"} else "auto"


def _aerodatabox_upstream_units_limit() -> int:
    return _int_env("RELAY_AERODATABOX_UPSTREAM_MONTHLY_UNITS_LIMIT", 24_000, minimum=0)


def _aerodatabox_fids_units() -> int:
    return _int_env("RELAY_AERODATABOX_FIDS_TIER2_UNITS", 2, minimum=1)


def _aviationstack_upstream_monthly_limit() -> int:
    return _int_env("RELAY_AVIATIONSTACK_UPSTREAM_MONTHLY_LIMIT", 10_000, minimum=0)


def _ceil_monthly_daily(monthly: int) -> int:
    return max(0, (max(0, int(monthly)) + 29) // 30)


def _aerodatabox_upstream_daily_units_limit() -> int:
    monthly = _aerodatabox_upstream_units_limit()
    return _int_env("RELAY_AERODATABOX_UPSTREAM_DAILY_UNITS_LIMIT", _ceil_monthly_daily(monthly), minimum=0)


def _aviationstack_upstream_daily_limit() -> int:
    monthly = _aviationstack_upstream_monthly_limit()
    return _int_env("RELAY_AVIATIONSTACK_UPSTREAM_DAILY_LIMIT", _ceil_monthly_daily(monthly), minimum=0)


def _provider_failure_cooldown_seconds() -> int:
    return _int_env("RELAY_PROVIDER_FAILURE_COOLDOWN_SECONDS", 600, minimum=0)


def _schedule_network_rpm_limit() -> int:
    return _int_env("RELAY_SCHEDULE_NETWORK_RPM_LIMIT", 120, minimum=0)


def _schedule_install_rpm_limit() -> int:
    return _int_env("RELAY_SCHEDULE_INSTALL_RPM_LIMIT", 30, minimum=0)


def _schedule_global_rpm_limit() -> int:
    return _int_env("RELAY_SCHEDULE_GLOBAL_RPM_LIMIT", 600, minimum=0)


def _schedule_new_keys_network_daily_limit() -> int:
    return _int_env("RELAY_SCHEDULE_NEW_KEYS_NETWORK_DAILY_LIMIT", 20, minimum=0)


def _schedule_new_keys_global_daily_limit() -> int:
    return _int_env("RELAY_SCHEDULE_NEW_KEYS_GLOBAL_DAILY_LIMIT", 200, minimum=0)


def _schedule_stale_if_error_seconds() -> int:
    return _int_env("RELAY_SCHEDULE_STALE_IF_ERROR_HOURS", 24, minimum=1) * 3600


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


def _monthly_reset_at(month: Optional[str] = None) -> str:
    key = month or _month_key()
    try:
        year_s, month_s = key.split("-", 1)
        year = int(year_s)
        month_num = int(month_s)
        if month_num >= 12:
            year += 1
            month_num = 1
        else:
            month_num += 1
        return datetime(year, month_num, 1, tzinfo=timezone.utc).isoformat()
    except Exception:
        now = datetime.now(timezone.utc)
        year = now.year + (1 if now.month >= 12 else 0)
        month_num = 1 if now.month >= 12 else now.month + 1
        return datetime(year, month_num, 1, tzinfo=timezone.utc).isoformat()


def _shared_schedule_budget_payload(conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    month = _month_key()
    close_conn = False
    if conn is None:
        conn = _connect()
        close_conn = True
    try:
        aerodatabox_key, _ = _provider_status(_SETTING_AERODATABOX_KEY, "AERODATABOX_API_KEY", conn=conn)
        aviationstack_key, _ = _provider_status(_SETTING_AVIATIONSTACK_KEY, "AVIATIONSTACK_API_KEY", conn=conn)
    finally:
        if close_conn:
            conn.close()

    provider_mode = _schedule_provider_mode()
    use_aerodatabox = bool(aerodatabox_key) and provider_mode in {"auto", "aerodatabox"}
    use_aviationstack = bool(aviationstack_key) and (provider_mode == "aviationstack" or not use_aerodatabox)
    if use_aerodatabox:
        provider = "aerodatabox"
        provider_label = "AeroDataBox shared schedule"
        service = "aerodatabox_upstream_units"
        unit_label = "units"
        limit = _aerodatabox_upstream_units_limit()
    elif use_aviationstack:
        provider = "aviationstack"
        provider_label = "AviationStack shared schedule"
        service = "aviationstack_upstream"
        unit_label = "calls"
        limit = _aviationstack_upstream_monthly_limit()
    else:
        provider = provider_mode if provider_mode in {"aerodatabox", "aviationstack"} else "schedule"
        provider_label = "Shared relay schedule"
        service = "aerodatabox_upstream_units" if provider_mode != "aviationstack" else "aviationstack_upstream"
        unit_label = "units" if service == "aerodatabox_upstream_units" else "calls"
        limit = 0

    used = _get_usage("shared:upstream", service, month) if limit > 0 else 0
    budget = {
        "available": limit > 0,
        "provider": provider,
        "provider_label": provider_label,
        "service": service,
        "unit_label": unit_label,
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
        "reset_at": _monthly_reset_at(month),
        "period_label": "Monthly shared provider window",
        "scope_label": "Shared by all community relay real-data users",
    }
    if limit <= 0:
        budget["error"] = "Shared provider budget unavailable"
        budget["used"] = None
        budget["limit"] = None
        budget["remaining"] = None
    if use_aerodatabox and aviationstack_key and provider_mode == "auto":
        aviation_used = _get_usage("shared:upstream", "aviationstack_upstream", month)
        budget["secondary"] = {
            "provider": "aviationstack",
            "provider_label": "AviationStack sparse fill",
            "service": "aviationstack_upstream",
            "unit_label": "calls",
            "used": aviation_used,
            "limit": _aviationstack_upstream_monthly_limit(),
            "remaining": max(0, _aviationstack_upstream_monthly_limit() - aviation_used),
            "reset_at": _monthly_reset_at(month),
        }
    return budget


def _schedule_access_budget_payload(*, install_id: str, activation_row: Optional[sqlite3.Row], limit: int, plan: str) -> Dict[str, Any]:
    month = _month_key()
    subject_key = _usage_subject(install_id, activation_row)
    used = _get_usage(subject_key, "aviationstack", month)
    return {
        "plan": plan,
        "used": used,
        "limit": max(0, int(limit or 0)),
        "remaining": max(0, int(limit or 0) - used),
        "reset_at": _monthly_reset_at(month),
        "period_label": "Monthly install access window",
        "scope_label": "This Local Flight install only",
        "unit_label": "accesses",
    }


def _usage_calls(row: Optional[sqlite3.Row]) -> int:
    if row is None:
        return 0
    try:
        return max(0, int(row["calls"] or 0))
    except (KeyError, TypeError, ValueError):
        return 0


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


def _check_and_increment_usage_counters(
    *,
    provider: str,
    counters: list[Dict[str, Any]],
) -> Dict[str, int]:
    normalized: list[Dict[str, Any]] = []
    for counter in counters:
        requested = max(1, int(counter.get("n_calls", counter.get("calls", 1)) or 1))
        limit_raw = counter.get("limit")
        limit = None if limit_raw is None else max(0, int(limit_raw))
        normalized.append(
            {
                "subject_key": str(counter.get("subject_key") or "shared:upstream"),
                "service": str(counter.get("service") or ""),
                "period": str(counter.get("period") or _month_key()),
                "plan": str(counter.get("plan") or "shared"),
                "install_id": counter.get("install_id"),
                "n_calls": requested,
                "limit": limit,
                "budget_service": str(counter.get("budget_service") or counter.get("service") or ""),
                "budget_period_label": str(counter.get("budget_period_label") or "monthly"),
            }
        )
    if not normalized:
        return {}

    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        current_by_key: dict[tuple[str, str, str], int] = {}
        for counter in normalized:
            key = (counter["subject_key"], counter["service"], counter["period"])
            if key not in current_by_key:
                row = conn.execute(
                    "SELECT calls FROM usage WHERE subject_key=? AND service=? AND month=?",
                    key,
                ).fetchone()
                current_by_key[key] = int(row["calls"] or 0) if row else 0
            current = current_by_key[key]
            limit = counter["limit"]
            if limit is not None and current + counter["n_calls"] > limit:
                conn.rollback()
                raise UpstreamBudgetExceeded(
                    provider=provider,
                    service=counter["budget_service"],
                    current=current,
                    limit=limit,
                    requested=counter["n_calls"],
                    period=counter["budget_period_label"],
                )
        now = _utc_now()
        new_counts: Dict[str, int] = {}
        for counter in normalized:
            key = (counter["subject_key"], counter["service"], counter["period"])
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
                (
                    counter["subject_key"],
                    counter["service"],
                    counter["period"],
                    counter["n_calls"],
                    now,
                    counter["plan"],
                    counter["install_id"],
                ),
            )
            current_by_key[key] = current_by_key[key] + counter["n_calls"]
            new_counts[counter["service"]] = current_by_key[key]
        conn.commit()
        return new_counts
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


def _check_and_increment_upstream_budget(
    *,
    provider: str,
    service: str,
    n_calls: int,
    monthly_limit: int,
    daily_limit: Optional[int] = None,
) -> int:
    requested = max(1, int(n_calls))
    limit = max(0, int(monthly_limit))
    subject_key = "shared:upstream"
    counters = [
        {
            "subject_key": subject_key,
            "service": service,
            "period": _month_key(),
            "n_calls": requested,
            "limit": limit,
            "budget_service": service,
            "budget_period_label": "monthly",
        }
    ]
    if daily_limit is not None:
        counters.append(
            {
                "subject_key": subject_key,
                "service": f"{service}:day",
                "period": _day_key(),
                "n_calls": requested,
                "limit": max(0, int(daily_limit)),
                "budget_service": service,
                "budget_period_label": "daily",
            }
        )
    return _check_and_increment_usage_counters(provider=provider, counters=counters).get(service, requested)


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
    schedule_limit: Optional[int] = None,
    radar_limit: Optional[int] = None,
) -> tuple[str, str, str]:
    existing = _activation_row_for_install(conn, install_id)
    token = _new_activation_token()
    resolved_schedule_limit = schedule_limit if schedule_limit is not None else _managed_schedule_limit()
    resolved_radar_limit = radar_limit if radar_limit is not None else _managed_radar_limit()
    if existing:
        old_hash = str(existing["token_hash"] or "")
        new_hash = _token_hash(token)
        conn.execute(
            """
            UPDATE activation_tokens
            SET token_hash=?,
                token_prefix=?,
                label=?,
                schedule_limit=?,
                radar_limit=?,
                last_seen=?,
                revoked_at=NULL,
                created_by=?
            WHERE token_hash=?
            """,
            (
                new_hash,
                token[:10],
                label.strip() or str(existing["label"] or "") or None,
                resolved_schedule_limit,
                resolved_radar_limit,
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
        schedule_limit=resolved_schedule_limit,
        radar_limit=resolved_radar_limit,
        created_by=created_by,
        bound_install_id=install_id,
    )
    return token, token[:10], "issued"


def _activation_limits_for_requested_mode(requested_mode: str) -> tuple[Optional[int], Optional[int]]:
    if _is_mobile_standalone(requested_mode):
        return _standalone_schedule_limit(), _standalone_radar_limit()
    return None, None


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
    airport_iata: str = "",
    airport_icao: str = "",
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
            airport_iata or None,
            airport_icao or None,
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


def _check_and_increment_community_daily_limit(*, service: str, network_tag: str) -> None:
    service_label = "schedule" if service == "aviationstack" else "radar"
    day = _day_key()
    network_limit = _community_daily_limit(service, "network")
    global_limit = _community_daily_limit(service, "global")
    network_bucket = network_tag if _NETWORK_TAG_RE.fullmatch(network_tag or "") else "unknown"
    network_subject = f"community-network:{network_bucket}"
    global_subject = "community-global"
    network_service = f"{service}:network-day"
    global_service = f"{service}:global-day"

    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        network_row = conn.execute(
            "SELECT calls FROM usage WHERE subject_key=? AND service=? AND month=?",
            (network_subject, network_service, day),
        ).fetchone()
        global_row = conn.execute(
            "SELECT calls FROM usage WHERE subject_key=? AND service=? AND month=?",
            (global_subject, global_service, day),
        ).fetchone()
        network_current = _usage_calls(network_row)
        global_current = _usage_calls(global_row)
        if network_current >= network_limit:
            conn.rollback()
            raise HTTPException(
                status_code=429,
                detail=f"Community relay {service_label} network daily limit reached; try again tomorrow.",
                headers={"Retry-After": "86400"},
            )
        if global_current >= global_limit:
            conn.rollback()
            raise HTTPException(
                status_code=429,
                detail=f"Community relay {service_label} daily safety limit reached; try again tomorrow.",
                headers={"Retry-After": "86400"},
            )

        now = _utc_now()
        for subject_key, scoped_service, plan_name in (
            (network_subject, network_service, "community-network"),
            (global_subject, global_service, "community-global"),
        ):
            conn.execute(
                """
                INSERT INTO usage (subject_key, service, month, calls, last_seen, plan, install_id)
                VALUES (?, ?, ?, 1, ?, ?, NULL)
                ON CONFLICT(subject_key, service, month) DO UPDATE SET
                    calls = calls + 1,
                    last_seen = excluded.last_seen,
                    plan = excluded.plan
                """,
                (subject_key, scoped_service, day, now, plan_name),
            )
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


def _check_and_increment_schedule_rpm_limits(*, install_id: str, network_tag: str) -> None:
    minute = _minute_key()
    checks = [
        (
            f"schedule-network:{network_tag or 'unknown'}",
            "schedule:network-minute",
            _schedule_network_rpm_limit(),
            "Network schedule rate limit reached; try again shortly.",
            "network-minute",
        ),
        (
            f"schedule-install:{install_id}",
            "schedule:install-minute",
            _schedule_install_rpm_limit(),
            "Install schedule rate limit reached; try again shortly.",
            "install-minute",
        ),
        (
            "schedule-global",
            "schedule:global-minute",
            _schedule_global_rpm_limit(),
            "Relay schedule safety rate limit reached; try again shortly.",
            "global-minute",
        ),
    ]
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for subject, service, limit, message, _plan in checks:
            row = conn.execute(
                "SELECT calls FROM usage WHERE subject_key=? AND service=? AND month=?",
                (subject, service, minute),
            ).fetchone()
            current = int(row["calls"] or 0) if row else 0
            if current >= int(limit):
                conn.rollback()
                raise HTTPException(status_code=429, detail=message, headers={"Retry-After": "60"})
        now = _utc_now()
        for subject, service, _limit, _message, plan in checks:
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
                (subject, service, minute, now, plan, install_id),
            )
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


def _check_and_mark_new_schedule_cache_key(*, network_tag: str, cache_key: str) -> None:
    cache_key = (cache_key or "").strip().lower()
    if not _SCHEDULE_CACHE_KEY_RE.fullmatch(cache_key):
        raise HTTPException(status_code=400, detail="Invalid schedule cache key")

    day = _day_key()
    network_bucket = network_tag if _NETWORK_TAG_RE.fullmatch(network_tag or "") else "unknown"
    network_subject = f"schedule-new-key-network:{network_bucket}"
    global_subject = "schedule-new-key-global"
    marker_subject = f"schedule-new-key:{cache_key}"
    marker_service = "schedule:new-cache-key-marker"
    network_service = "schedule:new-cache-key-network-day"
    global_service = "schedule:new-cache-key-global-day"
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        marker = conn.execute(
            "SELECT calls FROM usage WHERE subject_key=? AND service=? AND month=?",
            (marker_subject, marker_service, day),
        ).fetchone()
        if marker:
            conn.commit()
            return
        checks = [
            (
                network_subject,
                network_service,
                _schedule_new_keys_network_daily_limit(),
                "Network schedule cache-key daily limit reached; try again tomorrow.",
                "new-key-network",
            ),
            (
                global_subject,
                global_service,
                _schedule_new_keys_global_daily_limit(),
                "Relay schedule cache-key safety limit reached; try again tomorrow.",
                "new-key-global",
            ),
        ]
        for subject, service, limit, message, _plan in checks:
            row = conn.execute(
                "SELECT calls FROM usage WHERE subject_key=? AND service=? AND month=?",
                (subject, service, day),
            ).fetchone()
            current = _usage_calls(row)
            if current >= int(limit):
                conn.rollback()
                raise HTTPException(status_code=429, detail=message, headers={"Retry-After": "86400"})
        now = _utc_now()
        marker_insert = conn.execute(
            """
            INSERT INTO usage (subject_key, service, month, calls, last_seen, plan, install_id)
            VALUES (?, ?, ?, 1, ?, 'new-key-marker', NULL)
            ON CONFLICT(subject_key, service, month) DO NOTHING
            """,
            (marker_subject, marker_service, day, now),
        )
        if marker_insert.rowcount == 0:
            conn.commit()
            return
        for subject, service, _limit, _message, plan in checks:
            conn.execute(
                """
                INSERT INTO usage (subject_key, service, month, calls, last_seen, plan, install_id)
                VALUES (?, ?, ?, 1, ?, ?, NULL)
                ON CONFLICT(subject_key, service, month) DO UPDATE SET
                    calls = calls + 1,
                    last_seen = excluded.last_seen,
                    plan = excluded.plan
                """,
                (subject, service, day, now, plan),
            )
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


def _report_limit(report_type: str) -> int:
    if report_type == "manual":
        try:
            return int(_env("RELAY_REPORT_MANUAL_DAILY_LIMIT", str(_REPORT_MANUAL_INSTALL_DAILY_LIMIT)))
        except ValueError:
            return _REPORT_MANUAL_INSTALL_DAILY_LIMIT
    try:
        return int(_env("RELAY_REPORT_CRASH_DAILY_LIMIT", str(_REPORT_CRASH_INSTALL_DAILY_LIMIT)))
    except ValueError:
        return _REPORT_CRASH_INSTALL_DAILY_LIMIT


def _report_network_limit() -> int:
    try:
        return int(_env("RELAY_REPORT_NETWORK_DAILY_LIMIT", str(_REPORT_NETWORK_DAILY_LIMIT)))
    except ValueError:
        return _REPORT_NETWORK_DAILY_LIMIT


def _linear_reporter_key() -> str:
    return _env("LINEAR_REPORTER_API_KEY")


def _redact_sensitive(text: str) -> str:
    redacted = text or ""
    for pattern, repl in _SECRET_PATTERNS:
        redacted = pattern.sub(repl, redacted)
    return redacted


def _collapse(value: str, *, limit: int) -> str:
    clean = re.sub(r"\s+", " ", _redact_sensitive(value or "")).strip()
    return clean[:limit]


def _report_origin(body: "ReportIn") -> str:
    hint = f"{body.origin} {body.context} {body.client_context} {body.platform} {body.os}".lower()
    origin = (body.origin or "").strip().lower()
    if origin == "native" or body.context.startswith("native/") or "native/gui" in hint:
        return "desktop"
    if origin in _REPORT_ALLOWED_ORIGINS:
        if origin == "mobile" and "ios" in hint:
            return "ios"
        return origin
    if "ios" in hint:
        return "ios"
    if body.context.startswith("web/"):
        return "web"
    if body.context.startswith("mobile/"):
        return "mobile"
    if body.context.startswith("scheduler/"):
        return "scheduler"
    if body.context.startswith("thread/") or body.context == "main-thread":
        return "server"
    return "desktop" if body.report_type == "manual" else "server"


def _report_team(origin: str, context: str) -> str:
    origin = (origin or "").strip().lower()
    context = (context or "").strip().lower()
    if origin in {"ios", "mobile"} or context.startswith("mobile/"):
        return "ios"
    if origin in {"desktop", "web", "native"} or context.startswith("web/") or context.startswith("native/"):
        return "desktop"
    if origin in {"server", "scheduler"} or context.startswith("scheduler/") or context.startswith("thread/") or context == "main-thread":
        return "server"
    if origin == "relay":
        return "relay"
    return "default"


def _report_team_id(team: str) -> str:
    env_key = _REPORT_TEAM_ENV.get(team) or _REPORT_TEAM_ENV["default"]
    return _env(env_key) or _env(_REPORT_TEAM_ENV["default"])


def _report_team_label(team: str, origin: str) -> str:
    if team == "ios":
        return "iOS"
    if origin == "web":
        return "Web"
    if team == "desktop":
        return "Desktop"
    if team == "server":
        return "Server"
    if team == "relay":
        return "Relay"
    return "Default"


def _report_type_label(report_type: str) -> str:
    return "Manual" if report_type == "manual" else "Crash"


def _report_window_start(report_type: str) -> str:
    if report_type == "manual":
        minutes = _REPORT_MANUAL_DEDUPE_MINUTES
    else:
        minutes = _REPORT_CRASH_DEDUPE_HOURS * 60
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _normalize_message_hash(body: "ReportIn") -> str:
    if body.report_type == "manual":
        source = f"{body.title}\n{body.description}"
    else:
        source = body.message or body.title or body.description
    normalized = re.sub(r"\s+", " ", _redact_sensitive(source).lower()).strip()
    return hashlib.sha256(normalized[:1000].encode("utf-8")).hexdigest()[:16]


def _report_dedupe_key(
    *,
    team: str,
    report_type: str,
    origin: str,
    context: str,
    message_hash: str,
    install_fingerprint: str,
) -> str:
    parts = [team, report_type, origin, context or "-", message_hash, install_fingerprint]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _check_report_rate_limit(
    conn: sqlite3.Connection,
    *,
    report_type: str,
    install_fingerprint: str,
    network_tag: str,
) -> None:
    cutoff = _hours_ago(24)
    install_count = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM report_events
        WHERE install_fingerprint=? AND report_type=? AND ts>=?
        """,
        (install_fingerprint, report_type, cutoff),
    ).fetchone()
    network_count = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM report_events
        WHERE network_tag=? AND ts>=?
        """,
        (network_tag, cutoff),
    ).fetchone()
    if int(install_count["count"] or 0) >= _report_limit(report_type):
        raise HTTPException(status_code=429, detail="Report rate limit reached for this install")
    if int(network_count["count"] or 0) >= _report_network_limit():
        raise HTTPException(status_code=429, detail="Report rate limit reached for this network")


def _check_heartbeat_rate_limit(install_id: str) -> bool:
    """True = allowed. False = cooldown not elapsed (5 min minimum between beats)."""
    now = time.time()
    with _heartbeat_guard:
        last = _heartbeat_last_seen.get(install_id)
        if last is not None and (now - last) < _HEARTBEAT_MIN_INTERVAL_S:
            return False
        _heartbeat_last_seen[install_id] = now
    return True


def _record_report_event(
    conn: sqlite3.Connection,
    *,
    install_fingerprint: str,
    network_tag: str,
    report_type: str,
    origin: str,
    context: str,
    team: str,
    status: str,
    dedupe_key: str,
) -> None:
    conn.execute(
        """
        INSERT INTO report_events (
            ts, install_fingerprint, network_tag, report_type, origin, context, team, status, dedupe_key
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (_utc_now(), install_fingerprint, network_tag, report_type, origin, context[:120], team, status, dedupe_key),
    )


def _dedupe_report(
    conn: sqlite3.Connection,
    *,
    dedupe_key: str,
    team: str,
    report_type: str,
    origin: str,
    install_fingerprint: str,
) -> Optional[str]:
    row = conn.execute(
        "SELECT url, last_seen FROM report_dedupe WHERE dedupe_key=?",
        (dedupe_key,),
    ).fetchone()
    if row:
        last_seen = str(row["last_seen"] or "")
        try:
            in_window = last_seen >= _report_window_start(report_type)
        except Exception:
            in_window = True
        if in_window:
            conn.execute(
                """
                UPDATE report_dedupe
                SET last_seen=?, count=count+1
                WHERE dedupe_key=?
                """,
                (_utc_now(), dedupe_key),
            )
            return str(row["url"] or "")
    conn.execute(
        """
        INSERT INTO report_dedupe (
            dedupe_key, team, report_type, origin, install_fingerprint, first_seen, last_seen, count, url
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL)
        ON CONFLICT(dedupe_key) DO UPDATE SET
            team=excluded.team,
            report_type=excluded.report_type,
            origin=excluded.origin,
            install_fingerprint=excluded.install_fingerprint,
            first_seen=excluded.first_seen,
            last_seen=excluded.last_seen,
            count=0,
            url=NULL
        """,
        (dedupe_key, team, report_type, origin, install_fingerprint, _utc_now(), _utc_now()),
    )
    return None


def _mark_report_filed(conn: sqlite3.Connection, *, dedupe_key: str, url: str) -> None:
    conn.execute(
        """
        UPDATE report_dedupe
        SET last_seen=?, count=count+1, url=?
        WHERE dedupe_key=?
        """,
        (_utc_now(), url, dedupe_key),
    )


def _linear_issue_title(body: "ReportIn", *, team: str, origin: str) -> str:
    platform_label = _report_team_label(team, origin)
    type_label = _report_type_label(body.report_type)
    if body.report_type == "manual":
        summary = body.title or "Manual report"
    else:
        summary = body.message or body.title or "Crash report"
    context = _collapse(body.context, limit=40)
    summary = _collapse(summary, limit=96)
    prefix = f"[{platform_label}][{type_label}]"
    if body.report_type == "crash" and context:
        return f"{prefix} {context} - {summary}"[:200]
    return f"{prefix} {summary}"[:200]


def _linear_issue_body(body: "ReportIn", *, team: str, origin: str, install_fingerprint: str) -> str:
    type_label = _report_type_label(body.report_type)
    sections = [
        f"**Report type:** {type_label}",
        f"**Origin:** {origin}",
        f"**Linear team bucket:** {team}",
        f"**Version/package:** {body.app_version or 'unknown'}",
        f"**Install fingerprint:** `{install_fingerprint}`",
        f"**Platform:** {body.platform or body.os or 'unknown'}",
        f"**OS:** {body.os or 'unknown'}",
        f"**Arch:** {body.arch or 'unknown'}",
        f"**Python:** {body.python_version or 'unknown'}",
        f"**Airport:** {body.airport or '—'}",
        f"**Source:** {body.source or 'unknown'}",
        f"**API mode:** {body.api_mode or 'unknown'}",
        f"**Diagnostics mode:** {body.diagnostics_mode or 'unset'}",
        f"**Context:** `{body.context or 'n/a'}`",
    ]
    body_text = "\n".join(sections)
    if body.report_type == "manual" and body.description.strip():
        body_text += f"\n\n---\n**User description**\n{_redact_sensitive(body.description.strip())[:3000]}"
    if body.report_type == "crash":
        error = body.message or body.title or "Unknown crash"
        body_text += f"\n\n---\n**Error**\n```\n{_redact_sensitive(error)[:500]}\n```"
        if body.traceback.strip():
            body_text += f"\n\n**Traceback**\n```\n{_redact_sensitive(body.traceback)[-1800:]}\n```"
        if body.description.strip():
            body_text += f"\n\n**Sanitized log excerpt**\n```\n{_redact_sensitive(body.description)[-1500:]}\n```"
    if body.client_context.strip():
        body_text += f"\n\n---\n**Client / reporter context**\n{_redact_sensitive(body.client_context.strip())[:1800]}"
    return body_text[:4000]


def _post_linear_issue(*, team_id: str, title: str, description: str) -> str:
    api_key = _linear_reporter_key()
    if not api_key or not team_id:
        raise HTTPException(status_code=503, detail="Linear reporting is not configured on the relay")
    response = _req.post(
        _LINEAR_GRAPHQL_URL,
        json={
            "query": """
mutation CreateIssue($title: String!, $description: String!, $teamId: String!) {
  issueCreate(input: { title: $title, description: $description, teamId: $teamId }) {
    success
    issue { url }
  }
}
""",
            "variables": {"title": title, "description": description, "teamId": team_id},
        },
        headers={"Authorization": api_key, "Content-Type": "application/json"},
        timeout=10,
    )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Linear returned HTTP {response.status_code}")
    data = response.json()
    result = (data.get("data") or {}).get("issueCreate") or {}
    if result.get("success"):
        return str((result.get("issue") or {}).get("url") or "")
    errors = data.get("errors")
    detail = errors[0].get("message") if errors and isinstance(errors[0], dict) else "Linear rejected report"
    raise HTTPException(status_code=502, detail=str(detail))
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


def _provider_schedule_cache_key(
    *,
    provider: str,
    airport_iata: str,
    timezone_name: str,
    display_grace_minutes: int,
    display_horizon_hours: int,
) -> str:
    payload = "|".join(
        [
            provider.lower().strip(),
            airport_iata.upper().strip(),
            timezone_name.strip(),
            str(int(display_grace_minutes)),
            str(int(display_horizon_hours)),
            _SHARED_SCHEDULE_PLANNER_VERSION,
            _SHARED_SCHEDULE_SCHEMA_VERSION,
        ]
    )
    return "psch_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


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


def _latest_presence(
    *,
    heartbeat_at: str = "",
    checkin_at: str = "",
    relay_activity_at: str = "",
) -> tuple[str, str]:
    candidates = [
        ("heartbeat", heartbeat_at),
        ("checkin", checkin_at),
        ("relay_activity", relay_activity_at),
    ]
    dated = [(source, stamp) for source, stamp in candidates if _parse_utc_dt(stamp)]
    if not dated:
        return "unknown", ""
    source, stamp = max(dated, key=lambda item: _parse_utc_dt(item[1]) or datetime.min.replace(tzinfo=timezone.utc))
    return source, stamp


def _presence_status(stamp: str, *, now: Optional[datetime] = None) -> str:
    dt = _parse_utc_dt(stamp)
    if not dt:
        return "unknown"
    current = now or datetime.now(timezone.utc)
    age = current - dt
    if age <= timedelta(minutes=45):
        return "fresh"
    if age <= timedelta(hours=24):
        return "recent"
    return "stale"


def _schedule_ttls(refresh_seconds: int, *, min_fresh_ttl_s: Optional[int] = None) -> tuple[int, int]:
    try:
        refresh = max(60, int(refresh_seconds))
    except Exception:
        refresh = 3600
    if min_fresh_ttl_s is None:
        min_fresh_ttl_s = _shared_schedule_min_fresh_ttl_seconds()
    fresh_ttl_s = max(int(min_fresh_ttl_s), min(900, refresh // 4))
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


def _snapshot_int(row: Any, key: str) -> int:
    if not row:
        return 0
    try:
        value = row.get(key, 0) if isinstance(row, dict) else row[key]
    except (IndexError, KeyError, TypeError):
        return 0
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _snapshot_shared_stats(row: Any) -> Dict[str, Any]:
    client_accesses = _snapshot_int(row, "client_accesses")
    upstream_pulls = _snapshot_int(row, "upstream_pulls")
    refresh_count = _snapshot_int(row, "refresh_count")
    cache_hits = _snapshot_int(row, "cache_hits")
    stale_serves = _snapshot_int(row, "stale_serves")
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


def _snapshot_lifecycle_state(
    row: Optional[sqlite3.Row],
    *,
    refresh_seconds: int,
    min_fresh_ttl_s: Optional[int] = None,
) -> str:
    if row is None:
        return "miss"
    age_s = _snapshot_age_seconds(str(row["generated_at"] or ""))
    if age_s is None:
        return "miss"
    fresh_ttl_s, stale_ttl_s = _schedule_ttls(refresh_seconds, min_fresh_ttl_s=min_fresh_ttl_s)
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


def _snapshot_stale_if_error_state(row: Optional[sqlite3.Row]) -> bool:
    if row is None:
        return False
    age_s = _snapshot_age_seconds(str(row["generated_at"] or ""))
    return age_s is not None and age_s <= _schedule_stale_if_error_seconds()


def _schedule_snapshot_is_suspiciously_sparse(payload: Dict[str, Any], previous: Optional[sqlite3.Row]) -> bool:
    if previous is None:
        return False
    previous_records = _load_json_blob(previous["records_json"], [])
    new_records = list(payload.get("records") or [])
    previous_count = len(previous_records) if isinstance(previous_records, list) else 0
    new_count = len(new_records)
    if previous_count < 8:
        return False
    if new_count == 0:
        return True
    sparse_floor = max(3, int(previous_count * 0.25))
    if new_count < sparse_floor:
        return True
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    provider_errors = meta.get("provider_errors") if isinstance(meta, dict) else {}
    budget_limited = meta.get("budget_limited_providers") if isinstance(meta, dict) else []
    return bool((provider_errors or budget_limited) and new_count < max(5, int(previous_count * 0.5)))


def _store_provider_schedule_snapshot(
    *,
    provider: str,
    airport_iata: str,
    timezone_name: str,
    display_grace_minutes: int,
    display_horizon_hours: int,
    records: list[Dict[str, Any]],
    meta: Dict[str, Any],
    generated_at: str,
    last_error: str = "",
) -> None:
    cache_key = _provider_schedule_cache_key(
        provider=provider,
        airport_iata=airport_iata,
        timezone_name=timezone_name,
        display_grace_minutes=display_grace_minutes,
        display_horizon_hours=display_horizon_hours,
    )
    conn = _connect()
    now_iso = _utc_now()
    conn.execute(
        """
        INSERT INTO provider_schedule_snapshots (
            cache_key, provider, airport_iata, timezone, display_grace_minutes,
            display_horizon_hours, policy_version, generated_at, updated_at,
            meta_json, records_json, refresh_count, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT(cache_key) DO UPDATE SET
            provider = excluded.provider,
            airport_iata = excluded.airport_iata,
            timezone = excluded.timezone,
            display_grace_minutes = excluded.display_grace_minutes,
            display_horizon_hours = excluded.display_horizon_hours,
            policy_version = excluded.policy_version,
            generated_at = excluded.generated_at,
            updated_at = excluded.updated_at,
            meta_json = excluded.meta_json,
            records_json = excluded.records_json,
            refresh_count = provider_schedule_snapshots.refresh_count + 1,
            last_error = excluded.last_error
        """,
        (
            cache_key,
            provider,
            airport_iata,
            timezone_name,
            int(display_grace_minutes),
            int(display_horizon_hours),
            _SHARED_SCHEDULE_PLANNER_VERSION,
            generated_at,
            now_iso,
            json.dumps(meta, ensure_ascii=False),
            json.dumps(records, ensure_ascii=False),
            last_error.strip(),
        ),
    )
    conn.commit()
    conn.close()


def _load_provider_schedule_snapshot_conn(
    conn: sqlite3.Connection,
    *,
    provider: str,
    airport_iata: str,
    timezone_name: str,
    display_grace_minutes: int,
    display_horizon_hours: int,
) -> Optional[sqlite3.Row]:
    cache_key = _provider_schedule_cache_key(
        provider=provider,
        airport_iata=airport_iata,
        timezone_name=timezone_name,
        display_grace_minutes=display_grace_minutes,
        display_horizon_hours=display_horizon_hours,
    )
    return conn.execute(
        "SELECT * FROM provider_schedule_snapshots WHERE cache_key=?",
        (cache_key,),
    ).fetchone()


def _provider_source_payload_from_row(row: sqlite3.Row, *, stale_reason: str = "") -> Dict[str, Any]:
    meta = _load_json_blob(row["meta_json"], {})
    records = _load_json_blob(row["records_json"], [])
    meta = dict(meta) if isinstance(meta, dict) else {}
    records = list(records) if isinstance(records, list) else []
    if "pages_fetched" in meta:
        meta["source_cache_pages_fetched"] = int(meta.get("pages_fetched", 0) or 0)
        meta["pages_fetched"] = 0
    if "units_spent" in meta:
        meta["source_cache_units_spent"] = int(meta.get("units_spent", 0) or 0)
        meta["units_spent"] = 0
    if "request_count" in meta:
        meta["source_cache_request_count"] = int(meta.get("request_count", 0) or 0)
        meta["request_count"] = 0
    meta["source_cache_state"] = "stale"
    meta["source_cache_generated_at"] = str(row["generated_at"] or "")
    if stale_reason:
        meta["source_cache_reason"] = stale_reason
    if row["last_error"]:
        meta["source_cache_last_error"] = str(row["last_error"])
    return {
        "generated_at": str(row["generated_at"] or _utc_now()),
        "provider": str(row["provider"] or ""),
        "meta": meta,
        "records": records,
    }


def _load_provider_source_payload(
    *,
    provider: str,
    airport_iata: str,
    timezone_name: str,
    display_grace_minutes: int,
    display_horizon_hours: int,
    stale_reason: str,
) -> Optional[Dict[str, Any]]:
    conn = _connect()
    try:
        row = _load_provider_schedule_snapshot_conn(
            conn,
            provider=provider,
            airport_iata=airport_iata,
            timezone_name=timezone_name,
            display_grace_minutes=display_grace_minutes,
            display_horizon_hours=display_horizon_hours,
        )
        if row is None:
            return None
        age_s = _snapshot_age_seconds(str(row["generated_at"] or ""))
        if age_s is None or age_s > _schedule_stale_if_error_seconds():
            return None
        return _provider_source_payload_from_row(row, stale_reason=stale_reason)
    finally:
        conn.close()


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
    client_kind: str = "",
    airport_iata: str,
    airport_icao: str = "",
    timezone_name: str,
    display_grace_minutes: int,
    display_horizon_hours: int,
    refresh_seconds: int,
) -> None:
    timezone_name = _normalize_timezone_name(timezone_name)
    conn = _connect()
    conn.execute(
        """
        INSERT INTO client_interests (
            install_id, plan, client_kind, airport_iata, airport_icao, timezone, display_grace_minutes,
            display_horizon_hours, refresh_seconds, last_seen
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(install_id) DO UPDATE SET
            plan = excluded.plan,
            client_kind = COALESCE(NULLIF(excluded.client_kind, ''), client_interests.client_kind),
            airport_iata = excluded.airport_iata,
            airport_icao = COALESCE(NULLIF(excluded.airport_icao, ''), client_interests.airport_icao),
            timezone = excluded.timezone,
            display_grace_minutes = excluded.display_grace_minutes,
            display_horizon_hours = excluded.display_horizon_hours,
            refresh_seconds = excluded.refresh_seconds,
            last_seen = excluded.last_seen
        """,
        (
            install_id,
            plan,
            _clean_client_kind(client_kind) if str(client_kind or "").strip() else "",
            airport_iata.upper().strip() or None,
            airport_icao.upper().strip() or None,
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


def _coarse_admin_text(value: Any, *, limit: int = 80) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.:/+() -]", "", str(value or "").strip())
    return clean[:limit]


def _coarse_admin_int(value: Any, *, minimum: int = 0, maximum: int = 100_000) -> int:
    try:
        number = int(value or 0)
    except Exception:
        number = 0
    return max(minimum, min(maximum, number))


def _record_install_profile(
    *,
    install_id: str,
    presence_event: str = "",
    client_kind: str = "",
    device_type: str = "",
    airport_iata: str = "",
    airport_icao: str = "",
    timezone_name: str = "",
    app_version: str = "",
    os_family: str = "",
    os_version: str = "",
    arch: str = "",
    requested_gui: str = "",
    effective_gui: str = "",
    source_mode: str = "",
    diagnostics_mode: str = "",
    companion_count: int = 0,
    matrix_count: int = 0,
    matrix_online_count: int = 0,
) -> None:
    install_id = _validate_install_id(install_id)
    now = _utc_now()
    event = (presence_event or "").strip().lower()
    heartbeat_at = now if event == "heartbeat" else ""
    checkin_at = now if event == "checkin" else ""
    relay_activity_at = now if event == "relay_activity" else ""
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO install_profiles (
                install_id, first_seen, last_seen, last_heartbeat_at, last_checkin_at, last_relay_activity_at,
                client_kind, device_type, airport_iata, airport_icao, timezone,
                app_version, os_family, os_version, arch,
                requested_gui, effective_gui, source_mode, diagnostics_mode,
                companion_count, matrix_count, matrix_online_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(install_id) DO UPDATE SET
                last_seen = excluded.last_seen,
                last_heartbeat_at = COALESCE(NULLIF(excluded.last_heartbeat_at, ''), install_profiles.last_heartbeat_at),
                last_checkin_at = COALESCE(NULLIF(excluded.last_checkin_at, ''), install_profiles.last_checkin_at),
                last_relay_activity_at = COALESCE(NULLIF(excluded.last_relay_activity_at, ''), install_profiles.last_relay_activity_at),
                client_kind = COALESCE(NULLIF(excluded.client_kind, ''), install_profiles.client_kind),
                device_type = COALESCE(NULLIF(excluded.device_type, ''), install_profiles.device_type),
                airport_iata = COALESCE(NULLIF(excluded.airport_iata, ''), install_profiles.airport_iata),
                airport_icao = COALESCE(NULLIF(excluded.airport_icao, ''), install_profiles.airport_icao),
                timezone = COALESCE(NULLIF(excluded.timezone, ''), install_profiles.timezone),
                app_version = COALESCE(NULLIF(excluded.app_version, ''), install_profiles.app_version),
                os_family = COALESCE(NULLIF(excluded.os_family, ''), install_profiles.os_family),
                os_version = COALESCE(NULLIF(excluded.os_version, ''), install_profiles.os_version),
                arch = COALESCE(NULLIF(excluded.arch, ''), install_profiles.arch),
                requested_gui = COALESCE(NULLIF(excluded.requested_gui, ''), install_profiles.requested_gui),
                effective_gui = COALESCE(NULLIF(excluded.effective_gui, ''), install_profiles.effective_gui),
                source_mode = COALESCE(NULLIF(excluded.source_mode, ''), install_profiles.source_mode),
                diagnostics_mode = COALESCE(NULLIF(excluded.diagnostics_mode, ''), install_profiles.diagnostics_mode),
                companion_count = excluded.companion_count,
                matrix_count = excluded.matrix_count,
                matrix_online_count = excluded.matrix_online_count
            """,
            (
                install_id,
                now,
                now,
                heartbeat_at,
                checkin_at,
                relay_activity_at,
                _clean_client_kind(client_kind) if str(client_kind or "").strip() else "",
                _clean_device_type(device_type) if str(device_type or "").strip() else "",
                _coarse_admin_text(airport_iata, limit=4).upper(),
                _coarse_admin_text(airport_icao, limit=4).upper(),
                _coarse_admin_text(timezone_name, limit=64),
                _coarse_admin_text(app_version, limit=40),
                _coarse_admin_text(os_family, limit=40),
                _coarse_admin_text(os_version, limit=80),
                _coarse_admin_text(arch, limit=40),
                _coarse_admin_text(requested_gui, limit=24),
                _coarse_admin_text(effective_gui, limit=24),
                _coarse_admin_text(source_mode, limit=32),
                _coarse_admin_text(diagnostics_mode, limit=32),
                _coarse_admin_int(companion_count),
                _coarse_admin_int(matrix_count),
                _coarse_admin_int(matrix_online_count),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _backfill_install_profiles(conn: sqlite3.Connection) -> None:
    """Seed first/last seen from existing relay tables without inventing metadata."""
    candidates = conn.execute(
        """
        SELECT install_id, MIN(ts) AS first_seen, MAX(ts) AS last_seen
        FROM (
            SELECT install_id, last_seen AS ts FROM usage WHERE COALESCE(install_id, '') <> ''
            UNION ALL
            SELECT install_id, created_at AS ts FROM activation_requests WHERE COALESCE(install_id, '') <> ''
            UNION ALL
            SELECT install_id, last_seen AS ts FROM activation_requests WHERE COALESCE(install_id, '') <> ''
            UNION ALL
            SELECT install_id, last_seen AS ts FROM client_interests WHERE COALESCE(install_id, '') <> ''
            UNION ALL
            SELECT bound_install_id AS install_id, last_seen AS ts FROM activation_tokens WHERE COALESCE(bound_install_id, '') <> ''
        )
        WHERE COALESCE(ts, '') <> ''
        GROUP BY install_id
        """
    ).fetchall()
    for row in candidates:
        install_id = str(row["install_id"] or "").strip()
        if not install_id:
            continue
        first_seen = str(row["first_seen"] or row["last_seen"] or _utc_now())
        last_seen = str(row["last_seen"] or first_seen)
        conn.execute(
            """
            INSERT INTO install_profiles (install_id, first_seen, last_seen, last_relay_activity_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(install_id) DO UPDATE SET
                first_seen = COALESCE(install_profiles.first_seen, excluded.first_seen),
                last_seen = MAX(install_profiles.last_seen, excluded.last_seen),
                last_relay_activity_at = COALESCE(install_profiles.last_relay_activity_at, excluded.last_relay_activity_at)
            """,
            (install_id, first_seen, last_seen, last_seen),
        )


def _client_interest_snapshot(conn: sqlite3.Connection, install_id: str) -> Optional[Dict[str, Any]]:
    interest = conn.execute(
        """
        SELECT install_id, plan, client_kind, airport_iata, airport_icao, timezone, display_grace_minutes,
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
            "airport_icao": str(interest["airport_icao"] or "").strip(),
            "client_kind": _clean_client_kind(interest["client_kind"]),
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
        "airport_icao": str(interest["airport_icao"] or "").strip(),
        "client_kind": _clean_client_kind(interest["client_kind"]),
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


def _parse_provider_utc(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _provider_row_best_time(row: Dict[str, Any], mode: str) -> Optional[datetime]:
    block_name = "departure" if mode == "departures" else "arrival"
    block = row.get(block_name) if isinstance(row, dict) else None
    if not isinstance(block, dict):
        return None
    for key in ("actual", "estimated", "scheduled"):
        value = _parse_provider_utc(block.get(key))
        if value is not None:
            return value
    return None


def _provider_scope_latest_time(rows: list[Dict[str, Any]], mode: str) -> Optional[datetime]:
    latest: Optional[datetime] = None
    for row in rows:
        candidate = _provider_row_best_time(row, mode)
        if candidate is not None and (latest is None or candidate > latest):
            latest = candidate
    return latest


def _shared_schedule_target_end(window: Any, flight_date: Optional[str]) -> Optional[datetime]:
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


def _provider_rows_within_window(
    rows: list[Dict[str, Any]],
    mode: str,
    *,
    window_start_utc: datetime,
    window_end_utc: datetime,
) -> int:
    count = 0
    for row in rows:
        candidate = _provider_row_best_time(row, mode)
        if candidate is not None and window_start_utc <= candidate <= window_end_utc:
            count += 1
    return count


def _merge_scope_counts(first: Dict[str, Any], second: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for source in (first, second):
        for key, value in (source or {}).items():
            merged[key] = int(merged.get(key, 0) or 0) + int(value or 0)
    return merged


def _merge_schedule_meta(primary: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(primary)
    merged["pages_requested"] = int(primary.get("pages_requested", 0) or 0) + int(
        extra.get("pages_requested", 0) or 0
    )
    merged["pages_fetched"] = int(primary.get("pages_fetched", 0) or 0) + int(
        extra.get("pages_fetched", 0) or 0
    )
    merged["raw_rows"] = int(primary.get("raw_rows", 0) or 0) + int(extra.get("raw_rows", 0) or 0)
    merged["record_count"] = int(primary.get("record_count", 0) or 0) + int(
        extra.get("record_count", 0) or 0
    )
    merged["adaptive_extra_pages"] = int(primary.get("adaptive_extra_pages", 0) or 0) + int(
        extra.get("adaptive_extra_pages", 0) or 0
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


def _provider_circuit_open_exc(provider: str, opened_until: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=f"{provider} upstream is cooling down after repeated failures until {opened_until}",
    )


def _provider_circuit_raise_if_open(provider: str) -> None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT opened_until FROM provider_circuit_breakers WHERE provider=?",
            (provider,),
        ).fetchone()
    finally:
        conn.close()
    opened_until = str(row["opened_until"] or "") if row else ""
    opened_dt = _parse_utc_dt(opened_until)
    if opened_dt is not None and opened_dt > datetime.now(timezone.utc):
        raise _provider_circuit_open_exc(provider, opened_until)


def _provider_circuit_record_success(provider: str) -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO provider_circuit_breakers (provider, failure_count, opened_until, last_error, updated_at)
            VALUES (?, 0, NULL, NULL, ?)
            ON CONFLICT(provider) DO UPDATE SET
                failure_count = 0,
                opened_until = NULL,
                last_error = NULL,
                updated_at = excluded.updated_at
            """,
            (provider, _utc_now()),
        )
        conn.commit()
    finally:
        conn.close()


def _provider_circuit_record_failure(provider: str, error: Any) -> None:
    cooldown = _provider_failure_cooldown_seconds()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT failure_count FROM provider_circuit_breakers WHERE provider=?",
            (provider,),
        ).fetchone()
        failure_count = (int(row["failure_count"] or 0) if row else 0) + 1
        opened_until = None
        if cooldown > 0 and failure_count >= 3:
            opened_until = (datetime.now(timezone.utc) + timedelta(seconds=cooldown)).isoformat()
        conn.execute(
            """
            INSERT INTO provider_circuit_breakers (provider, failure_count, opened_until, last_error, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(provider) DO UPDATE SET
                failure_count = excluded.failure_count,
                opened_until = excluded.opened_until,
                last_error = excluded.last_error,
                updated_at = excluded.updated_at
            """,
            (provider, failure_count, opened_until, _collapse(str(error), limit=240), _utc_now()),
        )
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
    finally:
        conn.close()


def _aviationstack_upstream_payload(params: Dict[str, Any]) -> Dict[str, Any]:
    _provider_circuit_raise_if_open("aviationstack")
    _check_and_increment_upstream_budget(
        provider="aviationstack",
        service="aviationstack_upstream",
        n_calls=1,
        monthly_limit=_aviationstack_upstream_monthly_limit(),
        daily_limit=_aviationstack_upstream_daily_limit(),
    )
    try:
        response = _req.get(
            AVIATIONSTACK_URL,
            params=params,
            headers={"User-Agent": "localflight-relay/1.0"},
            timeout=25,
        )
    except Exception as exc:
        _provider_circuit_record_failure("aviationstack", exc)
        raise HTTPException(status_code=502, detail=f"AviationStack unreachable: {exc}")

    if response.status_code >= 400:
        try:
            payload = response.json()
            detail = payload.get("error") if isinstance(payload, dict) else None
            info = (detail.get("info") or detail.get("message") or "") if isinstance(detail, dict) else ""
            context = detail.get("context") if isinstance(detail, dict) else None
            if isinstance(context, dict) and context:
                context_text = ", ".join(f"{key}: {value}" for key, value in sorted(context.items()))
                info = f"{info} ({context_text})" if info else context_text
        except Exception:
            info = ""
        suffix = f": {info}" if info else ""
        _provider_circuit_record_failure("aviationstack", f"HTTP {response.status_code}{suffix}")
        raise HTTPException(status_code=502, detail=f"AviationStack upstream HTTP {response.status_code}{suffix}")

    try:
        payload = response.json()
    except Exception as exc:
        _provider_circuit_record_failure("aviationstack", exc)
        raise HTTPException(status_code=502, detail=f"AviationStack returned invalid JSON: {exc}")
    if not isinstance(payload, dict):
        _provider_circuit_record_failure("aviationstack", "response shape invalid")
        raise HTTPException(status_code=502, detail="AviationStack response shape invalid")
    if not isinstance(payload.get("data"), list):
        _provider_circuit_record_failure("aviationstack", "missing data rows")
        raise HTTPException(status_code=502, detail="AviationStack response missing data rows")
    _provider_circuit_record_success("aviationstack")
    return payload


def _fetch_aviationstack_schedule_source_from_upstream(
    *,
    airport_iata: str,
    timezone_name: str,
    display_grace_minutes: int,
    display_horizon_hours: int,
) -> Dict[str, Any]:
    from localflight.decode.mappings.aviationstack import aviationstack_to_raw_records
    from localflight.sources.web.aviationstack_plan import (
        DEFAULT_AUDIT_PAGES_PER_DATE,
        DEFAULT_FETCH_FUTURE_HOURS,
        DEFAULT_FETCH_PAST_HOURS,
        DEFAULT_PAGE_SIZE,
        DEFAULT_PRODUCTION_PAGES_PER_DATE,
        build_fetch_plan,
        build_fetch_window,
        build_undated_plan,
    )

    aviationstack_key = _aviationstack_key()
    generated_at_dt = datetime.now(timezone.utc)
    generated_at = generated_at_dt.isoformat()
    window = build_fetch_window(
        timezone_name=timezone_name,
        now=generated_at_dt,
        display_grace_minutes=display_grace_minutes,
        display_horizon_hours=display_horizon_hours,
        fetch_past_hours=DEFAULT_FETCH_PAST_HOURS,
        fetch_future_hours=DEFAULT_FETCH_FUTURE_HOURS,
    )
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
    adaptive_targets = {
        req.scope_key: target
        for req in requests_plan
        if (target := _shared_schedule_target_end(window, req.flight_date)) is not None
    }

    records: list[Dict[str, Any]] = []
    raw_rows_by_scope: dict[tuple[str, str], list[Dict[str, Any]]] = {}
    pages_by_scope: dict[tuple[str, str], int] = {}
    rows_by_scope: dict[tuple[str, str], int] = {}
    last_page_sizes: dict[tuple[str, str], int] = {}
    skip_scopes: set[tuple[str, str]] = set()
    scope_templates: dict[tuple[str, str], Any] = {}
    touched_dates: set[str] = set()
    pages_fetched = 0
    raw_rows = 0
    adaptive_extra_pages = 0

    for req in requests_plan:
        scope_templates.setdefault(req.scope_key, req)
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

        payload = _aviationstack_upstream_payload(params)
        page_rows = payload.get("data")

        pages_fetched += 1
        raw_rows += len(page_rows)
        raw_rows_by_scope.setdefault(req.scope_key, []).extend(page_rows)
        pages_by_scope[req.scope_key] = pages_by_scope.get(req.scope_key, 0) + 1
        rows_by_scope[req.scope_key] = rows_by_scope.get(req.scope_key, 0) + len(page_rows)
        last_page_sizes[req.scope_key] = len(page_rows)
        records.extend(
            aviationstack_to_raw_records(
                {"data": page_rows},
                airport_iata=airport_iata,
                mode="dep" if req.mode == "departures" else "arr",
            )
        )
        if len(page_rows) < req.limit:
            skip_scopes.add(req.scope_key)

    for scope_key, target_end in adaptive_targets.items():
        if scope_key in skip_scopes:
            continue
        template = scope_templates.get(scope_key)
        if template is None:
            continue
        fetched_pages = pages_by_scope.get(scope_key, 0)
        if fetched_pages <= 0:
            continue

        while fetched_pages < DEFAULT_AUDIT_PAGES_PER_DATE:
            latest = _provider_scope_latest_time(raw_rows_by_scope.get(scope_key, []), template.mode)
            if latest is not None and latest >= target_end:
                break
            if last_page_sizes.get(scope_key, 0) < template.limit:
                skip_scopes.add(scope_key)
                break

            params: Dict[str, Any] = {"access_key": aviationstack_key, "limit": template.limit}
            if template.flight_date:
                params["flight_date"] = template.flight_date
                touched_dates.add(template.flight_date)
            next_offset = fetched_pages * template.limit
            if next_offset > 0:
                params["offset"] = next_offset
            if template.dep_iata:
                params["dep_iata"] = template.dep_iata
            if template.arr_iata:
                params["arr_iata"] = template.arr_iata

            payload = _aviationstack_upstream_payload(params)
            page_rows = payload.get("data")

            pages_fetched += 1
            adaptive_extra_pages += 1
            raw_rows += len(page_rows)
            raw_rows_by_scope.setdefault(scope_key, []).extend(page_rows)
            fetched_pages += 1
            pages_by_scope[scope_key] = fetched_pages
            rows_by_scope[scope_key] = rows_by_scope.get(scope_key, 0) + len(page_rows)
            last_page_sizes[scope_key] = len(page_rows)
            records.extend(
                aviationstack_to_raw_records(
                    {"data": page_rows},
                    airport_iata=airport_iata,
                    mode="dep" if template.mode == "departures" else "arr",
                )
            )
            if len(page_rows) < template.limit:
                skip_scopes.add(scope_key)
                break

    meta = {
        "pages_requested": len(requests_plan),
        "pages_fetched": pages_fetched,
        "page_size": DEFAULT_PAGE_SIZE,
        "pages_per_date_cap": DEFAULT_PRODUCTION_PAGES_PER_DATE,
        "max_pages_per_scope": DEFAULT_AUDIT_PAGES_PER_DATE,
        "adaptive_extra_pages": adaptive_extra_pages,
        "dates_touched": sorted(touched_dates),
        "raw_rows": raw_rows,
        "record_count": len(records),
        "planner_version": _SHARED_SCHEDULE_PLANNER_VERSION,
        "schema_version": _SHARED_SCHEDULE_SCHEMA_VERSION,
        "upstream_usage_precounted": True,
        "pages_by_scope": {
            f"{mode}:{flight_date or 'undated'}": count
            for (mode, flight_date), count in pages_by_scope.items()
        },
        "rows_by_scope": {
            f"{mode}:{flight_date or 'undated'}": count
            for (mode, flight_date), count in rows_by_scope.items()
        },
    }
    display_start_utc = window.display_start.astimezone(timezone.utc)
    display_end_utc = window.display_end.astimezone(timezone.utc)
    undated_fallback_used = False
    for mode in ("departures", "arrivals"):
        if _provider_rows_within_window(
            raw_rows_by_scope.get((mode, ""), [])
            + raw_rows_by_scope.get((mode, window.display_start.date().isoformat()), [])
            + raw_rows_by_scope.get((mode, window.display_end.date().isoformat()), []),
            mode,
            window_start_utc=display_start_utc,
            window_end_utc=display_end_utc,
        ) > 0:
            continue

        fallback_plan = build_undated_plan(
            airport_iata=airport_iata,
            mode=mode,
            page_size=DEFAULT_PAGE_SIZE,
            page_cap=DEFAULT_PRODUCTION_PAGES_PER_DATE,
        )
        fallback_rows: list[Dict[str, Any]] = []
        fallback_pages = 0
        fallback_adaptive_pages = 0
        last_page_size = DEFAULT_PAGE_SIZE
        for req in fallback_plan:
            params: Dict[str, Any] = {"access_key": aviationstack_key, "limit": req.limit}
            if req.offset > 0:
                params["offset"] = req.offset
            if req.dep_iata:
                params["dep_iata"] = req.dep_iata
            if req.arr_iata:
                params["arr_iata"] = req.arr_iata
            payload = _aviationstack_upstream_payload(params)
            page_rows = payload.get("data")

            fallback_rows.extend(page_rows)
            fallback_pages += 1
            last_page_size = len(page_rows)
            if len(page_rows) < req.limit:
                break

        while fallback_pages < DEFAULT_AUDIT_PAGES_PER_DATE:
            latest = _provider_scope_latest_time(fallback_rows, mode)
            if latest is not None and latest >= display_end_utc:
                break
            if last_page_size < DEFAULT_PAGE_SIZE:
                break
            params = {"access_key": aviationstack_key, "limit": DEFAULT_PAGE_SIZE, "offset": fallback_pages * DEFAULT_PAGE_SIZE}
            if mode == "departures":
                params["dep_iata"] = airport_iata
            else:
                params["arr_iata"] = airport_iata
            payload = _aviationstack_upstream_payload(params)
            page_rows = payload.get("data")

            fallback_rows.extend(page_rows)
            fallback_pages += 1
            fallback_adaptive_pages += 1
            last_page_size = len(page_rows)
            if len(page_rows) < DEFAULT_PAGE_SIZE:
                break

        if fallback_rows:
            undated_fallback_used = True
            raw_rows += len(fallback_rows)
            pages_fetched += fallback_pages
            adaptive_extra_pages += fallback_adaptive_pages
            raw_rows_by_scope.setdefault((mode, ""), []).extend(fallback_rows)
            pages_by_scope[(mode, "")] = pages_by_scope.get((mode, ""), 0) + fallback_pages
            rows_by_scope[(mode, "")] = rows_by_scope.get((mode, ""), 0) + len(fallback_rows)
            records.extend(
                aviationstack_to_raw_records(
                    {"data": fallback_rows},
                    airport_iata=airport_iata,
                    mode="dep" if mode == "departures" else "arr",
                )
            )

    meta["pages_fetched"] = pages_fetched
    meta["raw_rows"] = raw_rows
    meta["record_count"] = len(records)
    meta["adaptive_extra_pages"] = adaptive_extra_pages
    meta["pages_by_scope"] = {
        f"{mode}:{flight_date or 'undated'}": count
        for (mode, flight_date), count in pages_by_scope.items()
    }
    meta["rows_by_scope"] = {
        f"{mode}:{flight_date or 'undated'}": count
        for (mode, flight_date), count in rows_by_scope.items()
    }
    meta["undated_fallback_used"] = undated_fallback_used
    return {
        "generated_at": generated_at,
        "provider": "aviationstack",
        "meta": meta,
        "records": records,
    }


def _aerodatabox_upstream_payload(
    *,
    airport_iata: str,
    display_grace_minutes: int,
    display_horizon_hours: int,
) -> Dict[str, Any]:
    units = _aerodatabox_fids_units()
    _provider_circuit_raise_if_open("aerodatabox")
    _check_and_increment_usage_counters(
        provider="aerodatabox",
        counters=[
            {
                "subject_key": "shared:upstream",
                "service": "aerodatabox_upstream_units",
                "period": _month_key(),
                "n_calls": units,
                "limit": _aerodatabox_upstream_units_limit(),
                "budget_service": "aerodatabox_upstream_units",
                "budget_period_label": "monthly",
            },
            {
                "subject_key": "shared:upstream",
                "service": "aerodatabox_upstream_units:day",
                "period": _day_key(),
                "n_calls": units,
                "limit": _aerodatabox_upstream_daily_units_limit(),
                "budget_service": "aerodatabox_upstream_units",
                "budget_period_label": "daily",
            },
            {
                "subject_key": "shared:upstream",
                "service": "aerodatabox_upstream_requests",
                "period": _month_key(),
                "n_calls": 1,
                "limit": None,
            },
            {
                "subject_key": "shared:upstream",
                "service": "aerodatabox_upstream_requests:day",
                "period": _day_key(),
                "n_calls": 1,
                "limit": None,
            },
        ],
    )
    offset_minutes = -max(0, int(display_grace_minutes))
    duration_minutes = min(
        _AERODATABOX_MAX_FIDS_DURATION_MINUTES,
        max(60, max(0, int(display_grace_minutes)) + max(1, int(display_horizon_hours)) * 60),
    )
    try:
        response = _req.get(
            _aerodatabox_request_url(airport_iata),
            params={
                "offsetMinutes": offset_minutes,
                "durationMinutes": duration_minutes,
                "direction": "Both",
                "withLeg": "true",
                "withCancelled": "true",
                "withCodeshared": "true",
                "withCargo": "false",
                "withPrivate": "false",
                "withLocation": "false",
            },
            headers=_aerodatabox_request_headers(),
            timeout=25,
        )
    except Exception as exc:
        _provider_circuit_record_failure("aerodatabox", exc)
        raise HTTPException(status_code=502, detail=f"AeroDataBox unreachable: {exc}")

    if response.status_code == 204:
        _provider_circuit_record_success("aerodatabox")
        return {"departures": [], "arrivals": []}
    if response.status_code == 429:
        _provider_circuit_record_failure("aerodatabox", "HTTP 429")
        raise HTTPException(status_code=502, detail="AeroDataBox upstream quota rejected the request")
    if response.status_code >= 400:
        _provider_circuit_record_failure("aerodatabox", f"HTTP {response.status_code}")
        raise HTTPException(status_code=502, detail=f"AeroDataBox upstream HTTP {response.status_code}")
    try:
        payload = response.json()
    except Exception as exc:
        _provider_circuit_record_failure("aerodatabox", exc)
        raise HTTPException(status_code=502, detail=f"AeroDataBox returned invalid JSON: {exc}")
    if not isinstance(payload, dict):
        _provider_circuit_record_failure("aerodatabox", "response shape invalid")
        raise HTTPException(status_code=502, detail="AeroDataBox response shape invalid")
    _provider_circuit_record_success("aerodatabox")
    return payload


def _fetch_aerodatabox_schedule_source_from_upstream(
    *,
    airport_iata: str,
    timezone_name: str,
    display_grace_minutes: int,
    display_horizon_hours: int,
) -> Dict[str, Any]:
    from localflight.decode.mappings.aerodatabox import aerodatabox_to_raw_records

    generated_at = datetime.now(timezone.utc).isoformat()
    payload = _aerodatabox_upstream_payload(
        airport_iata=airport_iata,
        display_grace_minutes=display_grace_minutes,
        display_horizon_hours=display_horizon_hours,
    )
    records = aerodatabox_to_raw_records(
        payload,
        airport_iata=airport_iata,
        mode="both",
    )
    meta = {
        "request_count": 1,
        "units_spent": _aerodatabox_fids_units(),
        "raw_rows": len(payload.get("departures") or []) + len(payload.get("arrivals") or []),
        "record_count": len(records),
        "marketplace": _aerodatabox_marketplace(),
        "planner_version": _SHARED_SCHEDULE_PLANNER_VERSION,
        "schema_version": _SHARED_SCHEDULE_SCHEMA_VERSION,
        "upstream_usage_precounted": True,
    }
    return {
        "generated_at": generated_at,
        "provider": "aerodatabox",
        "meta": meta,
        "records": records,
    }


def _store_provider_source_payload(
    payload: Dict[str, Any],
    *,
    airport_iata: str,
    timezone_name: str,
    display_grace_minutes: int,
    display_horizon_hours: int,
) -> None:
    provider = str(payload.get("provider") or "")
    if provider not in {"aerodatabox", "aviationstack"}:
        return
    _store_provider_schedule_snapshot(
        provider=provider,
        airport_iata=airport_iata,
        timezone_name=timezone_name,
        display_grace_minutes=display_grace_minutes,
        display_horizon_hours=display_horizon_hours,
        records=list(payload.get("records") or []),
        meta=dict(payload.get("meta") or {}),
        generated_at=str(payload.get("generated_at") or _utc_now()),
    )


def _provider_error_text(exc: BaseException) -> str:
    detail = getattr(exc, "detail", None)
    return str(detail or exc)


def _fetch_shared_schedule_from_upstream(
    *,
    airport_iata: str,
    timezone_name: str,
    display_grace_minutes: int,
    display_horizon_hours: int,
) -> Dict[str, Any]:
    from localflight.sources.web.schedule_fusion import (
        merge_schedule_records,
        schedule_records_need_fill,
    )

    mode = _schedule_provider_mode()
    provider_errors: Dict[str, str] = {}
    budget_limited: list[str] = []
    source_cache_providers: list[str] = []

    def _source_cache(provider: str, reason: str) -> Optional[Dict[str, Any]]:
        cached = _load_provider_source_payload(
            provider=provider,
            airport_iata=airport_iata,
            timezone_name=timezone_name,
            display_grace_minutes=display_grace_minutes,
            display_horizon_hours=display_horizon_hours,
            stale_reason=reason,
        )
        if cached is not None:
            source_cache_providers.append(provider)
        return cached

    def _finish(payload: Dict[str, Any], *, provider: str, extra_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        records = list(payload.get("records") or [])
        meta = dict(payload.get("meta") or {})
        if extra_meta:
            meta.update(extra_meta)
        if not meta.get("stale_reason") and meta.get("source_cache_reason"):
            meta["stale_reason"] = str(meta.get("source_cache_reason") or "")
        meta.setdefault("providers_used", [provider])
        meta.setdefault("provider_record_counts", {provider: len(records), "merged": len(records)})
        meta["provider_errors"] = provider_errors
        meta["budget_limited_providers"] = sorted(set(budget_limited))
        meta["source_cache_providers"] = sorted(set(source_cache_providers))
        meta["schedule_provider_mode"] = mode
        meta["planner_version"] = _SHARED_SCHEDULE_PLANNER_VERSION
        meta["schema_version"] = _SHARED_SCHEDULE_SCHEMA_VERSION
        return {
            "generated_at": str(payload.get("generated_at") or _utc_now()),
            "provider": provider,
            "meta": meta,
            "records": records,
        }

    if mode == "aviationstack":
        if not _has_aviationstack_key():
            cached = _source_cache("aviationstack", "provider_not_configured")
            if cached is not None:
                return _finish(cached, provider="aviationstack", extra_meta={"stale_reason": "provider_not_configured"})
            raise HTTPException(status_code=503, detail="AviationStack schedule provider is selected but not configured")
        try:
            payload = _fetch_aviationstack_schedule_source_from_upstream(
                airport_iata=airport_iata,
                timezone_name=timezone_name,
                display_grace_minutes=display_grace_minutes,
                display_horizon_hours=display_horizon_hours,
            )
            _store_provider_source_payload(
                payload,
                airport_iata=airport_iata,
                timezone_name=timezone_name,
                display_grace_minutes=display_grace_minutes,
                display_horizon_hours=display_horizon_hours,
            )
            return _finish(payload, provider="aviationstack", extra_meta={"fill_reason": "provider_selected"})
        except UpstreamBudgetExceeded as exc:
            budget_limited.append("aviationstack")
            provider_errors["aviationstack"] = _provider_error_text(exc)
            cached = _source_cache("aviationstack", "budget_limited")
            if cached is not None:
                return _finish(cached, provider="aviationstack", extra_meta={"stale_reason": "budget_limited"})
            raise
        except (HTTPException, RuntimeError) as exc:
            provider_errors["aviationstack"] = _provider_error_text(exc)
            cached = _source_cache("aviationstack", "upstream_error")
            if cached is not None:
                return _finish(cached, provider="aviationstack", extra_meta={"stale_reason": "upstream_error"})
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(status_code=503, detail="AviationStack schedule provider is unavailable") from exc

    primary: Optional[Dict[str, Any]] = None
    if _has_aerodatabox_key():
        try:
            primary = _fetch_aerodatabox_schedule_source_from_upstream(
                airport_iata=airport_iata,
                timezone_name=timezone_name,
                display_grace_minutes=display_grace_minutes,
                display_horizon_hours=display_horizon_hours,
            )
            _store_provider_source_payload(
                primary,
                airport_iata=airport_iata,
                timezone_name=timezone_name,
                display_grace_minutes=display_grace_minutes,
                display_horizon_hours=display_horizon_hours,
            )
        except UpstreamBudgetExceeded as exc:
            budget_limited.append("aerodatabox")
            provider_errors["aerodatabox"] = _provider_error_text(exc)
            primary = _source_cache("aerodatabox", "budget_limited")
            if primary is None and mode == "aerodatabox":
                raise
        except HTTPException as exc:
            provider_errors["aerodatabox"] = _provider_error_text(exc)
            primary = _source_cache("aerodatabox", "upstream_error")
            if primary is None and mode == "aerodatabox":
                raise
    elif mode == "aerodatabox":
        primary = _source_cache("aerodatabox", "provider_not_configured")
        if primary is None:
            raise HTTPException(status_code=503, detail="AeroDataBox schedule provider is selected but not configured")

    if primary is not None:
        primary_records = list(primary.get("records") or [])
        fill_reason = "primary_sparse" if schedule_records_need_fill(primary_records) else "not_needed"
        if mode == "auto" and fill_reason == "primary_sparse" and _has_aviationstack_key():
            try:
                fill = _fetch_aviationstack_schedule_source_from_upstream(
                    airport_iata=airport_iata,
                    timezone_name=timezone_name,
                    display_grace_minutes=display_grace_minutes,
                    display_horizon_hours=display_horizon_hours,
                )
                _store_provider_source_payload(
                    fill,
                    airport_iata=airport_iata,
                    timezone_name=timezone_name,
                    display_grace_minutes=display_grace_minutes,
                    display_horizon_hours=display_horizon_hours,
                )
                merged_records, fusion_meta = merge_schedule_records(
                    primary_records,
                    list(fill.get("records") or []),
                    primary_provider="aerodatabox",
                    fill_provider="aviationstack",
                )
                fill_meta = dict(fill.get("meta") or {})
                fusion_meta["pages_fetched"] = int(fill_meta.get("pages_fetched", 0) or 0)
                fusion_meta["aviationstack_meta"] = fill_meta
                fusion_meta["aerodatabox_meta"] = dict(primary.get("meta") or {})
                fusion_meta["upstream_usage_precounted"] = True
                fusion_meta["fill_reason"] = fill_reason
                return _finish(
                    {
                        "generated_at": primary.get("generated_at") or _utc_now(),
                        "provider": "aerodatabox+aviationstack",
                        "meta": fusion_meta,
                        "records": merged_records,
                    },
                    provider="aerodatabox+aviationstack",
                )
            except UpstreamBudgetExceeded as exc:
                budget_limited.append("aviationstack")
                provider_errors["aviationstack"] = _provider_error_text(exc)
                fill = _source_cache("aviationstack", "budget_limited")
            except (HTTPException, RuntimeError) as exc:
                provider_errors["aviationstack"] = _provider_error_text(exc)
                fill = _source_cache("aviationstack", "upstream_error")
            if fill is not None:
                merged_records, fusion_meta = merge_schedule_records(
                    primary_records,
                    list(fill.get("records") or []),
                    primary_provider="aerodatabox",
                    fill_provider="aviationstack",
                )
                fill_meta = dict(fill.get("meta") or {})
                fusion_meta["pages_fetched"] = int(fill_meta.get("pages_fetched", 0) or 0)
                fusion_meta["aviationstack_meta"] = fill_meta
                fusion_meta["aerodatabox_meta"] = dict(primary.get("meta") or {})
                fusion_meta["upstream_usage_precounted"] = True
                fusion_meta["fill_reason"] = f"{fill_reason}_source_cache"
                return _finish(
                    {
                        "generated_at": primary.get("generated_at") or _utc_now(),
                        "provider": "aerodatabox+aviationstack",
                        "meta": fusion_meta,
                        "records": merged_records,
                    },
                    provider="aerodatabox+aviationstack",
                )
        return _finish(primary, provider="aerodatabox", extra_meta={"fill_reason": fill_reason})

    try:
        if not _has_aviationstack_key():
            cached = _source_cache("aviationstack", "provider_not_configured")
            if cached is not None:
                return _finish(cached, provider="aviationstack", extra_meta={"stale_reason": "provider_not_configured"})
            raise HTTPException(status_code=503, detail="No configured real schedule provider is available")
        fallback = _fetch_aviationstack_schedule_source_from_upstream(
            airport_iata=airport_iata,
            timezone_name=timezone_name,
            display_grace_minutes=display_grace_minutes,
            display_horizon_hours=display_horizon_hours,
        )
        _store_provider_source_payload(
            fallback,
            airport_iata=airport_iata,
            timezone_name=timezone_name,
            display_grace_minutes=display_grace_minutes,
            display_horizon_hours=display_horizon_hours,
        )
        return _finish(fallback, provider="aviationstack", extra_meta={"fill_reason": "primary_unavailable"})
    except UpstreamBudgetExceeded as exc:
        budget_limited.append("aviationstack")
        provider_errors["aviationstack"] = _provider_error_text(exc)
        cached = _source_cache("aviationstack", "budget_limited")
        if cached is not None:
            return _finish(cached, provider="aviationstack", extra_meta={"stale_reason": "budget_limited"})
        raise
    except (RuntimeError, HTTPException) as exc:
        provider_errors["aviationstack"] = _provider_error_text(exc)
        cached = _source_cache("aviationstack", "upstream_error")
        if cached is not None:
            return _finish(cached, provider="aviationstack", extra_meta={"stale_reason": "upstream_error"})
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=503, detail="No configured real schedule provider is available") from exc


def _airport_surface_fresh_ttl_s() -> int:
    try:
        return max(3600, int(float(_env("RELAY_AIRPORT_SURFACE_CACHE_HOURS", "168")) * 3600))
    except ValueError:
        return 168 * 3600


def _airport_surface_stale_ttl_s() -> int:
    try:
        return max(7 * 86400, int(float(_env("RELAY_AIRPORT_SURFACE_STALE_DAYS", "90")) * 86400))
    except ValueError:
        return 90 * 86400


def _airport_surface_cache_key(airport_iata: str, airport_icao: str) -> str:
    from localflight.sources.web.airport_surface import surface_cache_key

    return surface_cache_key(airport_iata, airport_icao)


def _get_airport_surface_lock(cache_key: str) -> threading.Lock:
    with _airport_surface_locks_guard:
        lock = _airport_surface_locks.get(cache_key)
        if lock is None:
            lock = threading.Lock()
            _airport_surface_locks[cache_key] = lock
        return lock


def _load_airport_surface_snapshot_conn(conn: sqlite3.Connection, cache_key: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM airport_surface_snapshots WHERE cache_key=?",
        (cache_key,),
    ).fetchone()


def _airport_surface_lifecycle_state(row: Optional[sqlite3.Row]) -> str:
    if row is None:
        return "miss"
    updated_at = _parse_utc_dt(row["updated_at"])
    if updated_at is None:
        return "miss"
    age_s = (datetime.now(timezone.utc) - updated_at).total_seconds()
    if age_s <= _airport_surface_fresh_ttl_s():
        return "fresh"
    if age_s <= _airport_surface_stale_ttl_s():
        return "stale"
    return "miss"


def _airport_surface_payload_from_row(
    row: sqlite3.Row,
    *,
    cache_state: str,
    requested_radius_nm: float,
    error: str = "",
) -> Dict[str, Any]:
    from localflight.sources.web.airport_surface import build_surface_payload, clamp_surface_radius_nm

    try:
        features = json.loads(row["features_json"] or "[]")
    except Exception:
        features = []
    if not isinstance(features, list):
        features = []
    try:
        meta = json.loads(row["meta_json"] or "{}")
    except Exception:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    meta.update(
        {
            "request_count": int(row["request_count"] or 0),
            "cache_hits": int(row["cache_hits"] or 0),
            "refresh_count": int(row["refresh_count"] or 0),
            "stale_serves": int(row["stale_serves"] or 0),
        }
    )
    return build_surface_payload(
        airport_iata=str(row["airport_iata"] or ""),
        airport_icao=str(row["airport_icao"] or ""),
        center_lat=float(row["center_lat"]),
        center_lon=float(row["center_lon"]),
        radius_nm=clamp_surface_radius_nm(requested_radius_nm),
        features=features,
        cache_state=cache_state,
        generated_at=str(row["generated_at"] or row["updated_at"] or _utc_now()),
        error=error or str(row["last_error"] or ""),
        meta=meta,
    )


def _store_airport_surface_snapshot(cache_key: str, payload: Dict[str, Any]) -> None:
    center = payload.get("center") if isinstance(payload.get("center"), dict) else {}
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    now = _utc_now()
    conn = _connect()
    conn.execute(
        """
        INSERT INTO airport_surface_snapshots (
            cache_key, airport_iata, airport_icao, schema_version, provider,
            center_lat, center_lon, radius_nm, generated_at, updated_at,
            features_json, meta_json, request_count, cache_hits, refresh_count,
            stale_serves, last_cache_state, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 1, 0, ?, ?)
        ON CONFLICT(cache_key) DO UPDATE SET
            airport_iata=excluded.airport_iata,
            airport_icao=excluded.airport_icao,
            schema_version=excluded.schema_version,
            provider=excluded.provider,
            center_lat=excluded.center_lat,
            center_lon=excluded.center_lon,
            radius_nm=excluded.radius_nm,
            generated_at=excluded.generated_at,
            updated_at=excluded.updated_at,
            features_json=excluded.features_json,
            meta_json=excluded.meta_json,
            refresh_count=airport_surface_snapshots.refresh_count + 1,
            last_cache_state=excluded.last_cache_state,
            last_error=excluded.last_error
        """,
        (
            cache_key,
            str(center.get("airport_iata") or "").upper(),
            str(center.get("airport_icao") or "").upper(),
            str(payload.get("schema_version") or _AIRPORT_SURFACE_SCHEMA_VERSION),
            str(payload.get("provider") or "openstreetmap"),
            float(center.get("lat") or 0.0),
            float(center.get("lon") or 0.0),
            float(payload.get("radius_nm") or 20.0),
            str(payload.get("generated_at") or now),
            now,
            json.dumps(payload.get("features") or [], ensure_ascii=False),
            json.dumps(meta, ensure_ascii=False),
            str(payload.get("cache_state") or "fresh"),
            str(payload.get("error") or ""),
        ),
    )
    conn.commit()
    conn.close()


def _record_airport_surface_access(
    *,
    cache_key: str,
    cache_state: str,
    count_cache_hit: bool = False,
    count_stale: bool = False,
    error: str = "",
) -> None:
    conn = _connect()
    conn.execute(
        """
        UPDATE airport_surface_snapshots
        SET request_count = COALESCE(request_count, 0) + 1,
            cache_hits = COALESCE(cache_hits, 0) + ?,
            stale_serves = COALESCE(stale_serves, 0) + ?,
            last_cache_state = ?,
            last_error = ?
        WHERE cache_key = ?
        """,
        (
            1 if count_cache_hit else 0,
            1 if count_stale else 0,
            cache_state,
            error[:300],
            cache_key,
        ),
    )
    conn.commit()
    conn.close()


def _fetch_airport_surface_from_osm(
    *,
    airport_iata: str,
    airport_icao: str,
    lat: float,
    lon: float,
    radius_nm: float,
) -> Dict[str, Any]:
    from localflight.sources.web.airport_surface import (
        build_surface_payload,
        clamp_surface_radius_m,
        clamp_surface_radius_nm,
        fetch_overpass_surface,
        normalize_overpass_surface,
    )

    clamped_radius_nm = clamp_surface_radius_nm(radius_nm)
    lookup_radius_m = clamp_surface_radius_m(clamped_radius_nm)
    try:
        raw = fetch_overpass_surface(
            lat=lat,
            lon=lon,
            radius_m=lookup_radius_m,
            overpass_url=_env("RELAY_OVERPASS_URL", "") or None,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Overpass surface fetch failed: {exc}")
    features = normalize_overpass_surface(raw)
    return build_surface_payload(
        airport_iata=airport_iata,
        airport_icao=airport_icao,
        center_lat=lat,
        center_lon=lon,
        radius_nm=clamped_radius_nm,
        features=features,
        cache_state="fresh",
        meta={
            "lookup_radius_m": lookup_radius_m,
            "feature_count": len(features),
            "raw_elements": len(raw.get("elements") or []) if isinstance(raw, dict) else 0,
        },
    )


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


def _admin_auth_key(request: Request) -> str:
    return _network_tag(_client_ip(request))


def _check_admin_auth_throttle(key: str) -> None:
    now = time.monotonic()
    with _admin_auth_failures_guard:
        attempts = [
            ts
            for ts in _admin_auth_failures.get(key, [])
            if now - ts < _ADMIN_AUTH_WINDOW_SECONDS
        ]
        _admin_auth_failures[key] = attempts
        if len(attempts) >= _ADMIN_AUTH_FAILURE_LIMIT:
            raise HTTPException(status_code=429, detail="Too many admin login attempts; try again shortly")


def _record_admin_auth_failure(key: str) -> None:
    now = time.monotonic()
    with _admin_auth_failures_guard:
        attempts = [
            ts
            for ts in _admin_auth_failures.get(key, [])
            if now - ts < _ADMIN_AUTH_WINDOW_SECONDS
        ]
        attempts.append(now)
        _admin_auth_failures[key] = attempts


def _clear_admin_auth_failures(key: str) -> None:
    with _admin_auth_failures_guard:
        _admin_auth_failures.pop(key, None)


def _require_admin(request: Request, creds: HTTPBasicCredentials = Depends(HTTPBasic())) -> str:
    admin_pw = _admin_password()
    if not admin_pw or admin_pw == "changeme":
        raise HTTPException(status_code=503, detail="RELAY_ADMIN_PASSWORD is not configured")
    auth_key = _admin_auth_key(request)
    _check_admin_auth_throttle(auth_key)
    if not secrets.compare_digest(creds.password.encode(), admin_pw.encode()):
        _record_admin_auth_failure(auth_key)
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"})
    _clear_admin_auth_failures(auth_key)
    return creds.username or "admin"


def _admin_json_value(raw: str, fallback: Any) -> Any:
    try:
        return json.loads(raw or "")
    except Exception:
        return fallback


def _admin_count(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(query, params).fetchone()
    return int((row[0] if row else 0) or 0)


def _public_install_id(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if re.fullmatch(r"[a-f0-9]{12}", raw, flags=re.IGNORECASE):
        return raw.lower()
    return _install_fingerprint(raw)


def _public_subject(subject_key: str, install_id: str = "") -> Dict[str, str]:
    install_fp = _public_install_id(install_id)
    if install_fp:
        return {"kind": "install", "fingerprint": install_fp}
    raw = (subject_key or "").strip()
    if not raw:
        return {"kind": "unknown", "fingerprint": ""}
    if raw.startswith("managed:"):
        return {"kind": "managed-token", "fingerprint": hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]}
    if raw.startswith("net_"):
        return {"kind": "network", "tag": raw[:24]}
    return {"kind": "install", "fingerprint": _public_install_id(raw)}


def _admin_action_ref(conn: sqlite3.Connection, kind: str, value: str) -> str:
    """Opaque operator-only reference for write actions without exposing raw IDs."""
    clean_kind = re.sub(r"[^a-z0-9_-]", "", (kind or "").lower())[:16] or "ref"
    secret = _setting_get_conn(conn, _SETTING_NETWORK_SECRET, "")
    if not secret:
        # Admin refs must survive across read->write requests, so persist the
        # relay secret immediately when the first operator payload is rendered.
        secret = secrets.token_hex(32)
        _setting_set_conn(conn, _SETTING_NETWORK_SECRET, secret)
        conn.commit()
    digest = hmac.new(
        secret.encode("utf-8"),
        f"admin-action:{clean_kind}:{value or ''}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:24]
    return f"{clean_kind}_{digest}"


def _provider_admin_state(conn: sqlite3.Connection, setting_key: str, env_key: str) -> Dict[str, Any]:
    value, source = _provider_status(setting_key, env_key, conn=conn)
    return {
        "configured": bool(value),
        "source": source,
        "masked": _mask_secret(value) if value else "missing",
    }


def _admin_usage_rows(conn: sqlite3.Connection, month: str) -> list[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT subject_key, service, month, calls, last_seen, plan, install_id
        FROM usage
        WHERE month=?
        ORDER BY service ASC, calls DESC, last_seen DESC
        LIMIT 20000
        """,
        (month,),
    ).fetchall()
    return [
        {
            "subject": _public_subject(str(row["subject_key"] or ""), str(row["install_id"] or "")),
            "service": str(row["service"] or ""),
            "month": str(row["month"] or ""),
            "calls": int(row["calls"] or 0),
            "last_seen": str(row["last_seen"] or ""),
            "plan": str(row["plan"] or ""),
        }
        for row in rows
    ]


def _admin_request_rows(conn: sqlite3.Connection) -> list[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT ts, install_id, mode, status, latency_ms, service, plan
        FROM request_log
        ORDER BY ts DESC
        LIMIT 20000
        """
    ).fetchall()
    return [
        {
            "ts": str(row["ts"] or ""),
            "install_fingerprint": _public_install_id(str(row["install_id"] or "")),
            "scope": str(row["mode"] or ""),
            "status": int(row["status"] or 0),
            "latency_ms": int(row["latency_ms"] or 0),
            "service": str(row["service"] or ""),
            "plan": str(row["plan"] or ""),
            "error": int(row["status"] or 0) == 0 or int(row["status"] or 0) >= 400,
        }
        for row in rows
    ]


def _admin_fleet_rows(conn: sqlite3.Connection, month: str) -> list[Dict[str, Any]]:
    install_ids = _admin_install_candidates(conn)
    try:
        rows = conn.execute(
            "SELECT install_id FROM install_profiles WHERE COALESCE(install_id, '') <> '' LIMIT 1000"
        ).fetchall()
        install_ids.update(str(row["install_id"] or "") for row in rows if str(row["install_id"] or "").strip())
    except sqlite3.Error:
        pass

    fleet: list[Dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for install_id in sorted(install_ids):
        profile = conn.execute("SELECT * FROM install_profiles WHERE install_id=?", (install_id,)).fetchone()
        interest = conn.execute(
            """
            SELECT plan, client_kind, airport_iata, airport_icao, timezone, display_grace_minutes, display_horizon_hours,
                   refresh_seconds, last_seen
            FROM client_interests
            WHERE install_id=?
            """,
            (install_id,),
        ).fetchone()
        usage = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN service='aviationstack' THEN calls ELSE 0 END), 0) AS schedule_calls,
                COALESCE(SUM(CASE WHEN service='radar' THEN calls ELSE 0 END), 0) AS radar_calls,
                MAX(last_seen) AS usage_last_seen,
                GROUP_CONCAT(DISTINCT plan) AS usage_plans
            FROM usage
            WHERE install_id=? AND month=?
            """,
            (install_id, month),
        ).fetchone()
        token = conn.execute(
            """
            SELECT token_prefix, label, schedule_limit, radar_limit, last_seen, revoked_at
            FROM activation_tokens
            WHERE bound_install_id=?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (install_id,),
        ).fetchone()
        latest_request = conn.execute(
            """
            SELECT requested_mode, app_version, display_name, status, created_at, updated_at, last_seen
            FROM activation_requests
            WHERE install_id=?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (install_id,),
        ).fetchone()
        block = conn.execute("SELECT reason, created_at FROM blocked_installs WHERE install_id=?", (install_id,)).fetchone()

        profile_heartbeat = str(profile["last_heartbeat_at"] or "") if profile else ""
        profile_checkin = str(profile["last_checkin_at"] or "") if profile else ""
        legacy_relay_values = [
            str(profile["last_relay_activity_at"] or "") if profile else "",
            str(usage["usage_last_seen"] or "") if usage else "",
            str(token["last_seen"] or "") if token else "",
            str(latest_request["last_seen"] or latest_request["updated_at"] or "") if latest_request else "",
        ]
        last_relay_activity_at = max([value for value in legacy_relay_values if value] or [""])
        presence_source, presence_seen_at = _latest_presence(
            heartbeat_at=profile_heartbeat,
            checkin_at=profile_checkin,
            relay_activity_at=last_relay_activity_at,
        )
        presence_status = _presence_status(presence_seen_at, now=now)
        seen_values = [
            str((profile or {}).get("last_seen") or "") if isinstance(profile, dict) else (str(profile["last_seen"] or "") if profile else ""),
            str(interest["last_seen"] or "") if interest else "",
            str(usage["usage_last_seen"] or "") if usage else "",
            str(token["last_seen"] or "") if token else "",
            str(latest_request["last_seen"] or latest_request["updated_at"] or "") if latest_request else "",
        ]
        first_values = [
            str(profile["first_seen"] or "") if profile else "",
            str(latest_request["created_at"] or "") if latest_request else "",
            str(usage["usage_last_seen"] or "") if usage else "",
            str(interest["last_seen"] or "") if interest else "",
        ]
        last_seen = max([value for value in seen_values if value] or [""])
        first_seen = min([value for value in first_values if value] or [last_seen])
        last_seen_dt = _parse_utc_dt(last_seen)
        if block:
            status = "blocked"
        elif token and token["revoked_at"]:
            status = "token_revoked"
        elif last_seen_dt and (now - last_seen_dt) <= timedelta(hours=24):
            status = "active"
        elif last_seen:
            status = "dormant"
        else:
            status = "unknown"
        plan = str((interest or {}).get("plan") or "") if isinstance(interest, dict) else (str(interest["plan"] or "") if interest else "")
        if not plan and token and not token["revoked_at"]:
            plan = "managed"
        if not plan:
            usage_plans = str(usage["usage_plans"] or "") if usage else ""
            plan = usage_plans.split(",", 1)[0] if usage_plans else "community"
        current_lane = {
            "airport_iata": str(interest["airport_iata"] or "") if interest else "",
            "airport_icao": str(interest["airport_icao"] or "") if interest else "",
            "client_kind": _clean_client_kind(interest["client_kind"]) if interest else "",
            "timezone": str(interest["timezone"] or "") if interest else "",
            "display_grace_minutes": int(interest["display_grace_minutes"] or 0) if interest else 0,
            "display_horizon_hours": int(interest["display_horizon_hours"] or 0) if interest else 0,
            "refresh_seconds": int(interest["refresh_seconds"] or 0) if interest else 0,
            "last_seen": str(interest["last_seen"] or "") if interest else "",
        }
        fleet.append(
            {
                "install_fingerprint": _public_install_id(install_id),
                "action_ref": _admin_action_ref(conn, "inst", install_id),
                "first_seen": first_seen,
                "last_seen": last_seen,
                "last_heartbeat_at": profile_heartbeat,
                "last_checkin_at": profile_checkin,
                "last_relay_activity_at": last_relay_activity_at,
                "presence_source": presence_source,
                "presence_status": presence_status,
                "status": status,
                "plan": plan,
                "managed": bool(token and not token["revoked_at"]),
                "blocked": bool(block),
                "blocked_reason": str(block["reason"] or "") if block else "",
                "app_version": str((profile["app_version"] if profile else "") or (latest_request["app_version"] if latest_request else "") or ""),
                "client_kind": str(profile["client_kind"] or "") if profile else (str(interest["client_kind"] or "") if interest else ""),
                "device_type": str(profile["device_type"] or "") if profile else "",
                "airport_iata": str(profile["airport_iata"] or "") if profile else "",
                "airport_icao": str(profile["airport_icao"] or "") if profile else "",
                "timezone": str(profile["timezone"] or "") if profile else "",
                "os_family": str(profile["os_family"] or "") if profile else "",
                "os_version": str(profile["os_version"] or "") if profile else "",
                "arch": str(profile["arch"] or "") if profile else "",
                "requested_gui": str((profile["requested_gui"] if profile else "") or (latest_request["requested_mode"] if latest_request else "") or ""),
                "effective_gui": str(profile["effective_gui"] or "") if profile else "",
                "source_mode": str(profile["source_mode"] or "") if profile else "",
                "diagnostics_mode": str(profile["diagnostics_mode"] or "") if profile else "",
                "companion_count": int(profile["companion_count"] or 0) if profile else 0,
                "matrix_count": int(profile["matrix_count"] or 0) if profile else 0,
                "matrix_online_count": int(profile["matrix_online_count"] or 0) if profile else 0,
                "schedule_calls": int(usage["schedule_calls"] or 0) if usage else 0,
                "radar_calls": int(usage["radar_calls"] or 0) if usage else 0,
                "current_lane": current_lane,
                "token_prefix": str(token["token_prefix"] or "") if token else "",
                "token_label": str(token["label"] or "") if token else "",
                "activation_status": str(latest_request["status"] or "") if latest_request else "",
            }
        )
    fleet.sort(key=lambda row: (str(row.get("last_seen") or ""), str(row.get("first_seen") or "")), reverse=True)
    return fleet[:20000]


def _admin_fleet_metrics(rows: list[Dict[str, Any]]) -> Dict[str, Any]:
    active = [row for row in rows if row.get("status") == "active"]
    return {
        "known_installs": len(rows),
        "active_installs_24h": len(active),
        "presence_fresh": sum(1 for row in rows if row.get("presence_status") == "fresh"),
        "presence_recent": sum(1 for row in rows if row.get("presence_status") == "recent"),
        "presence_stale": sum(1 for row in rows if row.get("presence_status") == "stale"),
        "presence_unknown": sum(1 for row in rows if row.get("presence_status") == "unknown"),
        "managed_installs": sum(1 for row in rows if row.get("managed")),
        "blocked_installs": sum(1 for row in rows if row.get("blocked")),
        "companion_installs": sum(1 for row in rows if int(row.get("companion_count") or 0) > 0),
        "matrix_installs": sum(1 for row in rows if int(row.get("matrix_count") or 0) > 0),
        "os": _admin_count_values(rows, "os_family"),
        "gui": _admin_count_values(rows, "effective_gui"),
        "plans": _admin_count_values(rows, "plan"),
        "client_kind": _admin_count_values(rows, "client_kind"),
    }


def _admin_heartbeat_summary(rows: list[Dict[str, Any]]) -> Dict[str, Any]:
    latest_heartbeat = max([str(row.get("last_heartbeat_at") or "") for row in rows if row.get("last_heartbeat_at")] or [""])
    latest_checkin = max([str(row.get("last_checkin_at") or "") for row in rows if row.get("last_checkin_at")] or [""])
    latest_activity = max(
        [str(row.get("last_relay_activity_at") or "") for row in rows if row.get("last_relay_activity_at")] or [""]
    )
    return {
        "cadence_seconds": 30 * 60,
        "cooldown_seconds": _HEARTBEAT_MIN_INTERVAL_S,
        "fresh": sum(1 for row in rows if row.get("presence_status") == "fresh"),
        "recent": sum(1 for row in rows if row.get("presence_status") == "recent"),
        "stale": sum(1 for row in rows if row.get("presence_status") == "stale"),
        "unknown": sum(1 for row in rows if row.get("presence_status") == "unknown"),
        "latest_heartbeat_at": latest_heartbeat,
        "latest_checkin_at": latest_checkin,
        "latest_relay_activity_at": latest_activity,
    }


def _admin_count_values(rows: list[Dict[str, Any]], key: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        value = _admin_nested_value(row, key)
        label = str(value or "unknown").strip().lower() or "unknown"
        counts[label] = counts.get(label, 0) + 1
    return counts


_ADMIN_MAX_PAGE_LIMIT = 500
_ADMIN_DEFAULT_PAGE_LIMIT = 100


def _admin_nested_value(row: Dict[str, Any], key: str) -> Any:
    value: Any = row
    for part in (key or "").split("."):
        if not isinstance(value, dict):
            return ""
        value = value.get(part)
    return value


def _admin_clean_query(value: Any, *, limit: int = 120) -> str:
    return _coarse_admin_text(value, limit=limit).strip()


def _admin_bool_param(value: Any) -> Optional[bool]:
    if value is None:
        return None
    clean = str(value).strip().lower()
    if clean in {"1", "true", "yes", "on"}:
        return True
    if clean in {"0", "false", "no", "off"}:
        return False
    return None


def _admin_page_limit(value: int | None) -> int:
    try:
        limit = int(value or _ADMIN_DEFAULT_PAGE_LIMIT)
    except Exception:
        limit = _ADMIN_DEFAULT_PAGE_LIMIT
    return max(1, min(_ADMIN_MAX_PAGE_LIMIT, limit))


def _admin_cursor_offset(cursor: str | None) -> int:
    try:
        return max(0, int(str(cursor or "0").strip() or "0"))
    except Exception:
        return 0


def _admin_sort_rows(rows: list[Dict[str, Any]], *, sort: str = "", direction: str = "desc") -> list[Dict[str, Any]]:
    sort_key = _admin_clean_query(sort, limit=48)
    if not sort_key:
        return rows
    reverse = str(direction or "desc").strip().lower() != "asc"

    def _key(row: Dict[str, Any]) -> tuple[int, Any]:
        value = _admin_nested_value(row, sort_key)
        if value is None or value == "":
            return (1, "")
        if isinstance(value, bool):
            return (0, int(value))
        if isinstance(value, (int, float)):
            return (0, value)
        text = str(value)
        try:
            return (0, float(text.replace(",", "")))
        except Exception:
            return (0, text.lower())

    return sorted(rows, key=_key, reverse=reverse)


def _admin_q_match(row: Dict[str, Any], query: str) -> bool:
    query = _admin_clean_query(query).lower()
    if not query:
        return True
    return query in json.dumps(row, sort_keys=True, default=str).lower()


def _admin_page_payload(
    rows: list[Dict[str, Any]],
    *,
    total_estimate: int,
    limit: int | None,
    cursor: str | None,
    sort: str = "",
    direction: str = "desc",
    filters: Dict[str, Any] | None = None,
    facets: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    page_limit = _admin_page_limit(limit)
    offset = _admin_cursor_offset(cursor)
    page = rows[offset : offset + page_limit]
    next_offset = offset + page_limit
    return {
        "rows": page,
        "next_cursor": str(next_offset) if next_offset < len(rows) else "",
        "total_estimate": int(total_estimate),
        "filtered_estimate": len(rows),
        "facets": facets or {},
        "sort": {"key": sort or "", "dir": "asc" if str(direction).lower() == "asc" else "desc"},
        "filters": filters or {},
    }


def _admin_fleet_facets(rows: list[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "os_family": _admin_count_values(rows, "os_family"),
        "effective_gui": _admin_count_values(rows, "effective_gui"),
        "app_version": _admin_count_values(rows, "app_version"),
        "plan": _admin_count_values(rows, "plan"),
        "airport_iata": _admin_count_values(rows, "current_lane.airport_iata"),
        "status": _admin_count_values(rows, "status"),
        "presence_status": _admin_count_values(rows, "presence_status"),
        "presence_source": _admin_count_values(rows, "presence_source"),
        "has_companion": {
            "yes": sum(1 for row in rows if int(row.get("companion_count") or 0) > 0),
            "no": sum(1 for row in rows if int(row.get("companion_count") or 0) <= 0),
        },
        "has_matrix": {
            "yes": sum(1 for row in rows if int(row.get("matrix_count") or 0) > 0),
            "no": sum(1 for row in rows if int(row.get("matrix_count") or 0) <= 0),
        },
        "managed": {
            "yes": sum(1 for row in rows if bool(row.get("managed"))),
            "no": sum(1 for row in rows if not bool(row.get("managed"))),
        },
        "blocked": {
            "yes": sum(1 for row in rows if bool(row.get("blocked"))),
            "no": sum(1 for row in rows if not bool(row.get("blocked"))),
        },
    }


def _admin_filter_fleet_rows(
    rows: list[Dict[str, Any]],
    *,
    q: str = "",
    status: str = "",
    plan: str = "",
    os_family: str = "",
    effective_gui: str = "",
    app_version: str = "",
    presence_status: str = "",
    presence_source: str = "",
    airport_iata: str = "",
    has_companion: Any = None,
    has_matrix: Any = None,
    blocked: Any = None,
    managed: Any = None,
    first_seen_from: str = "",
    last_seen_from: str = "",
) -> tuple[list[Dict[str, Any]], Dict[str, Any]]:
    filters = {
        "q": _admin_clean_query(q),
        "status": _admin_clean_query(status, limit=48).lower(),
        "plan": _admin_clean_query(plan, limit=48).lower(),
        "os_family": _admin_clean_query(os_family, limit=48).lower(),
        "effective_gui": _admin_clean_query(effective_gui, limit=48).lower(),
        "app_version": _admin_clean_query(app_version, limit=48),
        "presence_status": _admin_clean_query(presence_status, limit=48).lower(),
        "presence_source": _admin_clean_query(presence_source, limit=48).lower(),
        "airport_iata": _admin_clean_query(airport_iata, limit=8).upper(),
        "has_companion": _admin_bool_param(has_companion),
        "has_matrix": _admin_bool_param(has_matrix),
        "blocked": _admin_bool_param(blocked),
        "managed": _admin_bool_param(managed),
        "first_seen_from": _admin_clean_query(first_seen_from, limit=32),
        "last_seen_from": _admin_clean_query(last_seen_from, limit=32),
    }
    filtered: list[Dict[str, Any]] = []
    for row in rows:
        if not _admin_q_match(row, filters["q"]):
            continue
        if filters["status"] and str(row.get("status") or "").lower() != filters["status"]:
            continue
        if filters["plan"] and str(row.get("plan") or "").lower() != filters["plan"]:
            continue
        if filters["os_family"] and str(row.get("os_family") or "").lower() != filters["os_family"]:
            continue
        if filters["effective_gui"] and str(row.get("effective_gui") or row.get("requested_gui") or "").lower() != filters["effective_gui"]:
            continue
        if filters["app_version"] and str(row.get("app_version") or "") != filters["app_version"]:
            continue
        if filters["presence_status"] and str(row.get("presence_status") or "").lower() != filters["presence_status"]:
            continue
        if filters["presence_source"] and str(row.get("presence_source") or "").lower() != filters["presence_source"]:
            continue
        if filters["airport_iata"] and str(_admin_nested_value(row, "current_lane.airport_iata") or "").upper() != filters["airport_iata"]:
            continue
        if filters["has_companion"] is not None and (int(row.get("companion_count") or 0) > 0) != filters["has_companion"]:
            continue
        if filters["has_matrix"] is not None and (int(row.get("matrix_count") or 0) > 0) != filters["has_matrix"]:
            continue
        if filters["blocked"] is not None and bool(row.get("blocked")) != filters["blocked"]:
            continue
        if filters["managed"] is not None and bool(row.get("managed")) != filters["managed"]:
            continue
        if filters["first_seen_from"] and str(row.get("first_seen") or "") < filters["first_seen_from"]:
            continue
        if filters["last_seen_from"] and str(row.get("last_seen") or "") < filters["last_seen_from"]:
            continue
        filtered.append(row)
    return filtered, {key: value for key, value in filters.items() if value not in {"", None}}


def _admin_filter_rows(
    rows: list[Dict[str, Any]],
    *,
    q: str = "",
    filters: Dict[str, Any] | None = None,
) -> tuple[list[Dict[str, Any]], Dict[str, Any]]:
    active_filters: Dict[str, Any] = {"q": _admin_clean_query(q)}
    for key, raw_value in (filters or {}).items():
        clean = _admin_clean_query(raw_value, limit=80)
        if clean:
            active_filters[key] = clean
    filtered: list[Dict[str, Any]] = []
    for row in rows:
        if not _admin_q_match(row, active_filters.get("q", "")):
            continue
        keep = True
        for key, value in active_filters.items():
            if key == "q":
                continue
            row_value = _admin_nested_value(row, key)
            if str(row_value or "").lower() != str(value).lower():
                keep = False
                break
        if keep:
            filtered.append(row)
    return filtered, {key: value for key, value in active_filters.items() if value}


def _list_dicts(value: Any) -> list[Dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _admin_schedule_snapshot_rows(conn: sqlite3.Connection) -> list[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT airport_iata, timezone, display_grace_minutes, display_horizon_hours,
               planner_version, schema_version, provider, generated_at, updated_at,
               meta_json, client_accesses, upstream_pulls, refresh_count, cache_hits,
               stale_serves, last_cache_state, last_error
        FROM schedule_snapshots
        ORDER BY updated_at DESC
        LIMIT 20000
        """
    ).fetchall()
    payload: list[Dict[str, Any]] = []
    for row in rows:
        meta = _admin_json_value(str(row["meta_json"] or "{}"), {})
        payload.append(
            {
                "airport_iata": str(row["airport_iata"] or ""),
                "timezone": str(row["timezone"] or ""),
                "display_grace_minutes": int(row["display_grace_minutes"] or 0),
                "display_horizon_hours": int(row["display_horizon_hours"] or 0),
                "planner_version": str(row["planner_version"] or ""),
                "schema_version": str(row["schema_version"] or ""),
                "provider": str(row["provider"] or ""),
                "generated_at": str(row["generated_at"] or ""),
                "updated_at": str(row["updated_at"] or ""),
                "client_accesses": int(row["client_accesses"] or 0),
                "upstream_pulls": int(row["upstream_pulls"] or 0),
                "refresh_count": int(row["refresh_count"] or 0),
                "cache_hits": int(row["cache_hits"] or 0),
                "stale_serves": int(row["stale_serves"] or 0),
                "last_cache_state": str(row["last_cache_state"] or ""),
                "last_error": str(row["last_error"] or ""),
                "meta": meta if isinstance(meta, dict) else {},
            }
        )
    return payload


def _admin_client_interest_rows(conn: sqlite3.Connection) -> list[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT install_id, plan, airport_iata, timezone, display_grace_minutes,
               display_horizon_hours, refresh_seconds, last_seen
        FROM client_interests
        ORDER BY last_seen DESC
        LIMIT 20000
        """
    ).fetchall()
    return [
        {
            "install_fingerprint": _public_install_id(str(row["install_id"] or "")),
            "plan": str(row["plan"] or ""),
            "airport_iata": str(row["airport_iata"] or ""),
            "timezone": str(row["timezone"] or ""),
            "display_grace_minutes": int(row["display_grace_minutes"] or 0),
            "display_horizon_hours": int(row["display_horizon_hours"] or 0),
            "refresh_seconds": int(row["refresh_seconds"] or 0),
            "last_seen": str(row["last_seen"] or ""),
        }
        for row in rows
    ]


def _admin_surface_rows(conn: sqlite3.Connection) -> list[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT airport_iata, airport_icao, schema_version, provider, center_lat, center_lon,
               radius_nm, generated_at, updated_at, features_json, meta_json, request_count,
               cache_hits, refresh_count, stale_serves, last_cache_state, last_error
        FROM airport_surface_snapshots
        ORDER BY updated_at DESC
        LIMIT 20000
        """
    ).fetchall()
    payload: list[Dict[str, Any]] = []
    for row in rows:
        features = _admin_json_value(str(row["features_json"] or "[]"), [])
        meta = _admin_json_value(str(row["meta_json"] or "{}"), {})
        payload.append(
            {
                "airport_iata": str(row["airport_iata"] or ""),
                "airport_icao": str(row["airport_icao"] or ""),
                "schema_version": str(row["schema_version"] or ""),
                "provider": str(row["provider"] or ""),
                "center": {"lat": float(row["center_lat"] or 0.0), "lon": float(row["center_lon"] or 0.0)},
                "radius_nm": float(row["radius_nm"] or 0.0),
                "generated_at": str(row["generated_at"] or ""),
                "updated_at": str(row["updated_at"] or ""),
                "feature_count": len(features) if isinstance(features, list) else 0,
                "request_count": int(row["request_count"] or 0),
                "cache_hits": int(row["cache_hits"] or 0),
                "refresh_count": int(row["refresh_count"] or 0),
                "stale_serves": int(row["stale_serves"] or 0),
                "last_cache_state": str(row["last_cache_state"] or ""),
                "last_error": str(row["last_error"] or ""),
                "meta": meta if isinstance(meta, dict) else {},
            }
        )
    return payload


def _admin_activation_payload(conn: sqlite3.Connection) -> Dict[str, Any]:
    token_rows = conn.execute(
        """
        SELECT token_hash, token_prefix, label, schedule_limit, radar_limit, created_at, created_by,
               bound_install_id, last_seen, revoked_at
        FROM activation_tokens
        ORDER BY created_at DESC
        LIMIT 150
        """
    ).fetchall()
    request_rows = conn.execute(
        """
        SELECT request_id, install_fingerprint, network_tag, airport_iata, display_name,
               requested_mode, app_version, status, created_at, updated_at, last_seen,
               token_prefix, decision_source, decision_note, approved_at, delivered_at
        FROM activation_requests
        ORDER BY updated_at DESC
        LIMIT 150
        """
    ).fetchall()
    blocked_rows = conn.execute(
        """
        SELECT install_id, reason, created_at
        FROM blocked_installs
        ORDER BY created_at DESC
        LIMIT 150
        """
    ).fetchall()
    return {
        "tokens": [
            {
                "token_prefix": str(row["token_prefix"] or ""),
                "action_ref": _admin_action_ref(conn, "tok", str(row["token_hash"] or "")),
                "label": str(row["label"] or ""),
                "schedule_limit": int(row["schedule_limit"] or 0),
                "radar_limit": int(row["radar_limit"] or 0),
                "created_at": str(row["created_at"] or ""),
                "created_by": str(row["created_by"] or ""),
                "bound_install_fingerprint": _public_install_id(str(row["bound_install_id"] or "")),
                "last_seen": str(row["last_seen"] or ""),
                "revoked": bool(row["revoked_at"]),
                "revoked_at": str(row["revoked_at"] or ""),
            }
            for row in token_rows
        ],
        "requests": [
            {
                "request_id": str(row["request_id"] or ""),
                "action_ref": str(row["request_id"] or ""),
                "install_fingerprint": str(row["install_fingerprint"] or ""),
                "network_tag": str(row["network_tag"] or ""),
                "airport_iata": str(row["airport_iata"] or ""),
                "display_name": str(row["display_name"] or ""),
                "requested_mode": str(row["requested_mode"] or ""),
                "app_version": str(row["app_version"] or ""),
                "status": str(row["status"] or ""),
                "created_at": str(row["created_at"] or ""),
                "updated_at": str(row["updated_at"] or ""),
                "last_seen": str(row["last_seen"] or ""),
                "token_prefix": str(row["token_prefix"] or ""),
                "decision_source": str(row["decision_source"] or ""),
                "decision_note": str(row["decision_note"] or ""),
                "approved_at": str(row["approved_at"] or ""),
                "delivered_at": str(row["delivered_at"] or ""),
            }
            for row in request_rows
        ],
        "blocked_installs": [
            {
                "install_fingerprint": _public_install_id(str(row["install_id"] or "")),
                "action_ref": _admin_action_ref(conn, "inst", str(row["install_id"] or "")),
                "reason": str(row["reason"] or ""),
                "created_at": str(row["created_at"] or ""),
            }
            for row in blocked_rows
        ],
    }


def _admin_report_payload(conn: sqlite3.Connection) -> Dict[str, Any]:
    cutoff = _hours_ago(24)
    summary_rows = conn.execute(
        """
        SELECT report_type, origin, team, status, COUNT(*) AS reports,
               COUNT(DISTINCT install_fingerprint) AS installs, MAX(ts) AS last_seen
        FROM report_events
        WHERE ts >= ?
        GROUP BY report_type, origin, team, status
        ORDER BY reports DESC, last_seen DESC
        LIMIT 80
        """,
        (cutoff,),
    ).fetchall()
    recent_rows = conn.execute(
        """
        SELECT ts, install_fingerprint, network_tag, report_type, origin, team, status, dedupe_key
        FROM report_events
        ORDER BY ts DESC
        LIMIT 20000
        """
    ).fetchall()
    dedupe_rows = conn.execute(
        """
        SELECT team, report_type, origin, url, count, first_seen, last_seen
        FROM report_dedupe
        ORDER BY last_seen DESC
        LIMIT 20000
        """
    ).fetchall()
    return {
        "summary_24h": [
            {
                "report_type": str(row["report_type"] or ""),
                "origin": str(row["origin"] or ""),
                "team": str(row["team"] or ""),
                "status": str(row["status"] or ""),
                "reports": int(row["reports"] or 0),
                "installs": int(row["installs"] or 0),
                "last_seen": str(row["last_seen"] or ""),
            }
            for row in summary_rows
        ],
        "recent_events": [
            {
                "ts": str(row["ts"] or ""),
                "install_fingerprint": str(row["install_fingerprint"] or ""),
                "network_tag": str(row["network_tag"] or ""),
                "report_type": str(row["report_type"] or ""),
                "origin": str(row["origin"] or ""),
                "team": str(row["team"] or ""),
                "status": str(row["status"] or ""),
                "dedupe_key": str(row["dedupe_key"] or "")[:20],
            }
            for row in recent_rows
        ],
        "dedupe": [
            {
                "team": str(row["team"] or ""),
                "report_type": str(row["report_type"] or ""),
                "origin": str(row["origin"] or ""),
                "issue_url": str(row["url"] or ""),
                "count": int(row["count"] or 0),
                "first_seen": str(row["first_seen"] or ""),
                "last_seen": str(row["last_seen"] or ""),
            }
            for row in dedupe_rows
        ],
    }


def _admin_action_response(message: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ok": True,
        "message": message,
        "generated_at": _utc_now(),
    }
    payload.update(extra)
    return payload


def _admin_token_hash_from_prefix(conn: sqlite3.Connection, token_prefix: str) -> str:
    prefix = (token_prefix or "").strip()
    rows = conn.execute(
        "SELECT token_hash FROM activation_tokens WHERE token_prefix=?",
        (prefix,),
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="Activation token prefix not found")
    if len(rows) > 1:
        raise HTTPException(status_code=409, detail="Activation token prefix is not unique")
    return str(rows[0]["token_hash"] or "")


def _admin_token_hash_from_reference(
    conn: sqlite3.Connection,
    *,
    token_ref: str = "",
    token_prefix: str = "",
) -> str:
    ref = (token_ref or "").strip()
    if not ref:
        return _admin_token_hash_from_prefix(conn, token_prefix)
    rows = conn.execute("SELECT token_hash, token_prefix FROM activation_tokens").fetchall()
    matches = [
        str(row["token_hash"] or "")
        for row in rows
        if ref == str(row["token_prefix"] or "") or ref == _admin_action_ref(conn, "tok", str(row["token_hash"] or ""))
    ]
    if not matches:
        raise HTTPException(status_code=404, detail="Activation token reference not found")
    if len(matches) > 1:
        raise HTTPException(status_code=409, detail="Activation token reference is not unique")
    return matches[0]


def _admin_install_candidates(conn: sqlite3.Connection) -> set[str]:
    candidates: set[str] = set()
    for table, column in (
        ("activation_requests", "install_id"),
        ("client_interests", "install_id"),
        ("usage", "install_id"),
        ("blocked_installs", "install_id"),
        ("activation_tokens", "bound_install_id"),
        ("install_profiles", "install_id"),
    ):
        try:
            rows = conn.execute(
                f"SELECT DISTINCT {column} AS install_id FROM {table} WHERE COALESCE({column}, '') <> '' LIMIT 20000"
            ).fetchall()
        except sqlite3.Error:
            continue
        for row in rows:
            install_id = str(row["install_id"] or "").strip()
            if install_id:
                candidates.add(install_id)
    return candidates


def _admin_install_id_from_reference(
    conn: sqlite3.Connection,
    *,
    install_ref: str = "",
    install_fingerprint: str = "",
    install_id: str = "",
) -> str:
    clean_install_id = (install_id or "").strip()
    if clean_install_id:
        return _validate_install_id(clean_install_id)
    ref = (install_ref or "").strip()
    if not ref:
        return _admin_install_id_from_fingerprint(conn, install_fingerprint)
    matches = [
        candidate
        for candidate in _admin_install_candidates(conn)
        if ref == _admin_action_ref(conn, "inst", candidate)
    ]
    if not matches:
        legacy = _admin_install_id_from_fingerprint(conn, ref)
        if legacy:
            return legacy
        raise HTTPException(status_code=404, detail="Install reference not found")
    if len(matches) > 1:
        raise HTTPException(status_code=409, detail="Install reference is not unique")
    return matches[0]


def _admin_install_id_from_fingerprint(conn: sqlite3.Connection, fingerprint: str) -> str:
    target = (fingerprint or "").strip().lower()
    if not target:
        return ""
    for install_id in _admin_install_candidates(conn):
        if _install_fingerprint(install_id) == target:
            return install_id
    return ""


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


def _render_admin_legacy(username: str, *, created_token: str = "", message: str = "") -> str:
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
    installs = _admin_fleet_rows(conn, month)
    fleet_metrics = _admin_fleet_metrics(installs)
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
    aerodatabox_key, aerodatabox_source = _provider_status(
        _SETTING_AERODATABOX_KEY,
        "AERODATABOX_API_KEY",
        conn=conn,
    )
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
  :root {{
    --font-ui: system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    --font-board: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: var(--font-ui); background: #0c1117; color: #e7edf3; line-height: 1.45; }}
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
  .mono {{ font-family: var(--font-board); }}
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

  <div class="split" id="providers">
    <div class="card stack">
      <div>
        <h2>Provider keys</h2>
        <div class="kicker">Managed clients do not receive raw vendor keys. Key changes take effect on the next relay request and advance the provider revision.</div>
        <div class="provider-line"><span>AeroDataBox</span><span>{html.escape(_mask_secret(aerodatabox_key))} <span class="tiny">({html.escape(aerodatabox_source)})</span></span></div>
        <div class="provider-line"><span>AviationStack</span><span>{html.escape(_mask_secret(aviationstack_key))} <span class="tiny">({html.escape(aviationstack_source)})</span></span></div>
        <div class="provider-line"><span>RapidAPI ADS-B</span><span>{html.escape(_mask_secret(rapidapi_key))} <span class="tiny">({html.escape(rapidapi_source)})</span></span></div>
        <div class="provider-line"><span>Community schedule cap</span><span>{_community_schedule_limit()} relay accesses per install / 30-day window</span></div>
        <div class="provider-line"><span>Shared snapshot pool</span><span>{snapshot_refreshes:,} refreshes · {snapshot_stale:,} stale serves</span></div>
        <div class="provider-line"><span>Radar cache</span><span>{_radar_cache_seconds()}s</span></div>
        <div class="provider-line"><span>Raw provider debug</span><span>{'enabled' if _raw_provider_debug_enabled() else 'disabled'}</span></div>
        <div class="provider-line"><span>Activation privacy</span><span>Anonymous network tags only</span></div>
      </div>
      <form method="post" action="/admin/providers/save">
        <label>AeroDataBox key
          <input name="aerodatabox_key" placeholder="Paste a replacement key to store in the relay" />
        </label>
        <label>AviationStack key
          <input name="aviationstack_key" placeholder="Paste a replacement key to store in the relay" />
        </label>
        <label>RapidAPI ADS-B key
          <input name="rapidapi_key" placeholder="Paste a replacement key to store in the relay" />
        </label>
        <button type="submit">Save provider keys</button>
      </form>
      <div>
        {_post_form('/admin/providers/clear', {'provider': 'aerodatabox'}, 'Clear AeroDataBox override', 'slate')}
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
        {_post_form('/admin/maintenance/clean-trial', {}, 'Clean setup trial state', 'amber')}
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


_ADMIN_ASSET_DIR = Path(__file__).resolve().parent / "admin"
_ADMIN_HTML_TEMPLATE = (_ADMIN_ASSET_DIR / "admin.html").read_text(encoding="utf-8")
_ADMIN_CSS = (_ADMIN_ASSET_DIR / "admin.css").read_text(encoding="utf-8")
_ADMIN_JS = (_ADMIN_ASSET_DIR / "admin.js").read_text(encoding="utf-8")
_ADMIN_SHELL = _ADMIN_HTML_TEMPLATE.replace("__ADMIN_CSS__", _ADMIN_CSS).replace("__ADMIN_JS__", _ADMIN_JS)


def _render_admin_shell(username: str, *, created_token: str = "", message: str = "") -> str:
    boot = json.dumps(
        {
            "username": username,
            "createdToken": created_token,
            "message": message,
            "idleSeconds": _admin_idle_seconds(),
        }
    ).replace("<", "\\u003c")
    return _ADMIN_SHELL.replace("__BOOT__", boot)


def _admin_idle_seconds() -> int:
    try:
        value = int(_env("LOCALFLIGHT_NETWORK_ADMIN_IDLE_S", "900"))
    except ValueError:
        return 900
    return max(60, value)


def _render_admin_signed_out() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Signed out — Local Flight Network Admin</title>
<style>
body { margin:0; min-height:100vh; display:grid; place-items:center; color:#edf6ff; font-family:"Segoe UI Variable","SF Pro Display",system-ui,sans-serif; background:#061019; }
.card { max-width:420px; padding:28px 30px; border:1px solid #23364a; border-radius:14px; background:#0a1420; text-align:center; }
h1 { margin:0 0 8px; font-size:1.2rem; letter-spacing:.04em; text-transform:uppercase; }
p { margin:8px 0; color:#92a8bf; line-height:1.5; }
a { display:inline-block; margin-top:14px; padding:9px 14px; border:1px solid #23364a; border-radius:10px; color:#edf6ff; text-decoration:none; font-weight:800; }
a:hover { border-color:#43d8e8; }
small { display:block; margin-top:14px; color:#647b92; }
</style>
</head>
<body>
<div class="card">
<h1>Signed out</h1>
<p>You have been signed out of the Network Admin console.</p>
<a href="/admin">Sign back in</a>
<small>Safari may keep credentials cached for this tab — close the tab if you need a fully clean session.</small>
</div>
</body>
</html>
"""




def _render_admin(username: str, *, created_token: str = "", message: str = "") -> str:
    return _render_admin_shell(username, created_token=created_token, message=message)
    conn = _connect()
    month = _month_key()
    day_cutoff = _hours_ago(24)
    day_cutoff_dt = _parse_utc_dt(day_cutoff) or datetime.now(timezone.utc)

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
    snapshot_pool_count = conn.execute("SELECT COUNT(*) FROM schedule_snapshots").fetchone()[0]
    snapshot_stale_count = conn.execute(
        "SELECT COUNT(*) FROM schedule_snapshots WHERE last_cache_state='stale'"
    ).fetchone()[0]
    snapshot_error_count = conn.execute(
        "SELECT COUNT(*) FROM schedule_snapshots WHERE COALESCE(last_error, '') <> ''"
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
    report_totals_24h = conn.execute(
        """
        SELECT COUNT(*) AS reports,
               COUNT(DISTINCT install_fingerprint) AS installs,
               COALESCE(SUM(CASE WHEN status='filed' THEN 1 ELSE 0 END), 0) AS filed,
               COALESCE(SUM(CASE WHEN status='deduped' THEN 1 ELSE 0 END), 0) AS deduped,
               MAX(ts) AS last_seen
        FROM report_events
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
    report_count_24h = int(report_totals_24h["reports"] or 0) if report_totals_24h else 0
    report_installs_24h = int(report_totals_24h["installs"] or 0) if report_totals_24h else 0
    report_filed_24h = int(report_totals_24h["filed"] or 0) if report_totals_24h else 0
    report_deduped_24h = int(report_totals_24h["deduped"] or 0) if report_totals_24h else 0
    report_key_configured = bool(_linear_reporter_key())
    report_team_config = {
        team: bool(_env(env_key))
        for team, env_key in _REPORT_TEAM_ENV.items()
    }
    report_specific_teams = sum(1 for team, ready in report_team_config.items() if team != "default" and ready)
    report_gateway_ready = report_key_configured and bool(report_team_config.get("default"))
    report_gateway_label = (
        "configured"
        if report_gateway_ready
        else "partial" if report_key_configured or report_specific_teams else "missing"
    )

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
    report_breakdown = [
        dict(r)
        for r in conn.execute(
            """
            SELECT report_type,
                   origin,
                   team,
                   status,
                   COUNT(*) AS reports,
                   COUNT(DISTINCT install_fingerprint) AS installs,
                   MAX(ts) AS last_seen
            FROM report_events
            WHERE ts >= ?
            GROUP BY report_type, origin, team, status
            ORDER BY reports DESC, last_seen DESC
            LIMIT 60
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
    installs = _admin_fleet_rows(conn, month)
    fleet_metrics = _admin_fleet_metrics(installs)
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
    recent_reports = [
        dict(r)
        for r in conn.execute(
            """
            SELECT ts,
                   install_fingerprint,
                   network_tag,
                   report_type,
                   origin,
                   context,
                   team,
                   status
            FROM report_events
            ORDER BY ts DESC
            LIMIT 80
            """
        ).fetchall()
    ]
    report_dedupe_rows = [
        dict(r)
        for r in conn.execute(
            """
            SELECT team,
                   report_type,
                   origin,
                   install_fingerprint,
                   first_seen,
                   last_seen,
                   count,
                   url
            FROM report_dedupe
            ORDER BY last_seen DESC
            LIMIT 80
            """
        ).fetchall()
    ]
    client_interests = [
        dict(r)
        for r in conn.execute(
            """
            SELECT install_id,
                   plan,
                   airport_iata,
                   timezone,
                   display_grace_minutes,
                   display_horizon_hours,
                   refresh_seconds,
                   last_seen
            FROM client_interests
            ORDER BY last_seen DESC
            LIMIT 400
            """
        ).fetchall()
    ]
    snapshots = [
        dict(r)
        for r in conn.execute(
            """
            SELECT *
            FROM schedule_snapshots
            ORDER BY client_accesses DESC, updated_at DESC
            LIMIT 80
            """
        ).fetchall()
    ]
    aerodatabox_key, aerodatabox_source = _provider_status(
        _SETTING_AERODATABOX_KEY,
        "AERODATABOX_API_KEY",
        conn=conn,
    )
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

    service_order = {
        "aviationstack": 0,
        "aerodatabox_upstream_units": 1,
        "aerodatabox_upstream_requests": 2,
        "aviationstack_upstream": 3,
        "radar": 4,
    }
    plan_order = {"community": 0, "managed": 1, "shared": 2}
    service_breakdown.sort(
        key=lambda row: (
            service_order.get(str(row.get("service") or ""), 99),
            plan_order.get(str(row.get("plan") or ""), 99),
            -int(row.get("calls") or 0),
        )
    )
    network_breakdown.sort(
        key=lambda row: (
            service_order.get(str(row.get("service") or ""), 99),
            plan_order.get(str(row.get("plan") or ""), 99),
            -int(row.get("requests") or 0),
        )
    )

    snapshot_by_key = {str(row.get("cache_key") or ""): row for row in snapshots if row.get("cache_key")}
    interest_by_install = {
        str(row.get("install_id") or ""): row for row in client_interests if str(row.get("install_id") or "").strip()
    }
    active_interest_rows = [
        row
        for row in client_interests
        if (_parse_utc_dt(row.get("last_seen")) or datetime.min.replace(tzinfo=timezone.utc)) >= day_cutoff_dt
    ]
    active_clients_24h = len(active_interest_rows)
    active_lanes_map: Dict[str, Dict[str, Any]] = {}
    for row in active_interest_rows:
        airport_iata = str(row.get("airport_iata") or "").strip().upper()
        timezone_name = str(row.get("timezone") or "").strip()
        if not airport_iata or not timezone_name:
            continue
        grace = max(0, int(row.get("display_grace_minutes") or 0))
        horizon = max(1, int(row.get("display_horizon_hours") or 1))
        cache_key = _schedule_cache_key(
            airport_iata=airport_iata,
            timezone_name=timezone_name,
            display_grace_minutes=grace,
            display_horizon_hours=horizon,
        )
        lane = active_lanes_map.setdefault(
            cache_key,
            {
                "cache_key": cache_key,
                "airport_iata": airport_iata,
                "timezone": timezone_name,
                "display_grace_minutes": grace,
                "display_horizon_hours": horizon,
                "refresh_min": max(60, int(row.get("refresh_seconds") or 3600)),
                "refresh_max": max(60, int(row.get("refresh_seconds") or 3600)),
                "install_count": 0,
                "plans": set(),
                "last_seen": str(row.get("last_seen") or ""),
                "install_fingerprints": [],
                "snapshot": snapshot_by_key.get(cache_key),
            },
        )
        refresh_seconds = max(60, int(row.get("refresh_seconds") or 3600))
        lane["install_count"] += 1
        lane["refresh_min"] = min(int(lane["refresh_min"]), refresh_seconds)
        lane["refresh_max"] = max(int(lane["refresh_max"]), refresh_seconds)
        lane["plans"].add(str(row.get("plan") or "community"))
        if str(row.get("last_seen") or "") > str(lane.get("last_seen") or ""):
            lane["last_seen"] = str(row.get("last_seen") or "")
        fingerprint = _install_fingerprint(str(row.get("install_id") or ""))
        if fingerprint and fingerprint not in lane["install_fingerprints"] and len(lane["install_fingerprints"]) < 3:
            lane["install_fingerprints"].append(fingerprint)
    active_lanes = sorted(
        active_lanes_map.values(),
        key=lambda row: (
            -int(row.get("install_count") or 0),
            -int(_snapshot_shared_stats(row.get("snapshot") or {}).get("client_accesses", 0))
            if row.get("snapshot")
            else 0,
            str(row.get("airport_iata") or ""),
        ),
    )
    active_lane_count = len(active_lanes)

    def _fmt_ts(value: Any, default: str = "-") -> str:
        dt = _parse_utc_dt(value)
        if not dt:
            return default
        return dt.strftime("%Y-%m-%d %H:%M UTC")

    def _fmt_age(value: Any, default: str = "-") -> str:
        dt = _parse_utc_dt(value)
        if not dt:
            return default
        seconds = max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))
        if seconds < 60:
            return f"{seconds}s ago"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        return f"{days}d ago"

    def _fmt_refresh(seconds: int) -> str:
        seconds = max(60, int(seconds or 60))
        minutes = seconds // 60
        if minutes % 60 == 0:
            hours = minutes // 60
            return f"{hours}h"
        if minutes >= 60:
            hours = minutes // 60
            remainder = minutes % 60
            return f"{hours}h {remainder}m"
        return f"{minutes}m"

    def _fmt_refresh_range(min_seconds: int, max_seconds: int) -> str:
        min_seconds = max(60, int(min_seconds or 60))
        max_seconds = max(60, int(max_seconds or 60))
        if min_seconds == max_seconds:
            return _fmt_refresh(min_seconds)
        return f"{_fmt_refresh(min_seconds)} to {_fmt_refresh(max_seconds)}"

    def _window_label(grace_minutes: int, horizon_hours: int) -> str:
        return f"-{int(grace_minutes)}m / +{int(horizon_hours)}h"

    def _badge(label: str, tone: str = "slate") -> str:
        safe_tone = tone if tone in {"green", "amber", "red", "slate", "blue", "cyan"} else "slate"
        return f"<span class='badge badge-{safe_tone}'>{html.escape(label)}</span>"

    def _service_label(service: str) -> str:
        mapping = {
            "aviationstack": "Schedule accesses",
            "aviationstack_upstream": "AviationStack upstream",
            "radar": "Radar accesses",
        }
        return mapping.get(service, service.replace("_", " ").title())

    def _service_badge(service: str) -> str:
        tone = {"aviationstack": "blue", "aviationstack_upstream": "cyan", "radar": "amber"}.get(service, "slate")
        return _badge(_service_label(service), tone)

    def _plan_badge(plan: str) -> str:
        tone = {"community": "blue", "managed": "green", "shared": "cyan"}.get(plan, "slate")
        return _badge(plan or "unknown", tone)

    def _cache_badge(state: str, *, has_error: bool = False) -> str:
        normalized = (state or "unknown").strip().lower()
        if has_error and normalized not in {"fresh"}:
            return _badge(normalized or "error", "red")
        tone = {"fresh": "green", "stale": "amber", "miss": "slate", "expired": "red"}.get(normalized, "slate")
        return _badge(normalized or "unknown", tone)

    def _request_status_badge(status: str) -> str:
        normalized = (status or "").strip().lower()
        tone = {
            _REQUEST_STATUS_MANUAL_REVIEW: "amber",
            _REQUEST_STATUS_ISSUED: "green",
            _REQUEST_STATUS_REJECTED: "red",
            _REQUEST_STATUS_PENDING: "slate",
        }.get(normalized, "slate")
        return _badge(normalized.replace("_", " ") or "unknown", tone)

    def _report_status_badge(status: str) -> str:
        normalized = (status or "").strip().lower()
        tone = {
            "filed": "green",
            "deduped": "cyan",
            "failed": "red",
            "rate_limited": "amber",
        }.get(normalized, "slate")
        return _badge(normalized.replace("_", " ") or "unknown", tone)

    def _report_gateway_badge() -> str:
        tone = {"configured": "green", "partial": "amber", "missing": "red"}.get(report_gateway_label, "slate")
        return _badge(report_gateway_label, tone)

    def _http_badge(status_code: int) -> str:
        status_code = int(status_code or 0)
        if status_code == 0 or status_code >= 500:
            tone = "red"
        elif status_code >= 400:
            tone = "amber"
        else:
            tone = "green"
        return _badge(str(status_code), tone)

    def _usage_tone(used: int, limit: int) -> str:
        limit = max(1, int(limit or 1))
        ratio = int(used or 0) / limit
        if ratio >= 1.0:
            return "red"
        if ratio >= 0.8:
            return "amber"
        return "green"

    def _meter(used: int, limit: int) -> str:
        limit = max(1, int(limit or 1))
        used = max(0, int(used or 0))
        percent = max(0, min(100, int(round((used / limit) * 100))))
        tone = _usage_tone(used, limit)
        return (
            "<div class='meter'>"
            f"<div class='meter-fill meter-{tone}' style='width:{percent}%'></div>"
            "</div>"
            f"<div class='tiny'>{used:,} / {limit:,}</div>"
        )

    def _install_lane_summary(install_id: str) -> str:
        row = interest_by_install.get(install_id)
        if not row:
            return "<span class='soft'>No current airport lane</span>"
        airport_iata = html.escape(str(row.get("airport_iata") or "-"))
        timezone_name = html.escape(str(row.get("timezone") or "-"))
        cadence = _fmt_refresh(max(60, int(row.get("refresh_seconds") or 3600)))
        return (
            f"<div class='cell-title mono'>{airport_iata}</div>"
            f"<div class='cell-sub'>{timezone_name} | {_window_label(int(row.get('display_grace_minutes') or 0), int(row.get('display_horizon_hours') or 0))}</div>"
            f"<div class='cell-sub'>Refresh every {cadence}</div>"
        )

    def rows_for_service_breakdown() -> str:
        if not service_breakdown:
            return "<tr><td colspan='5' class='muted'>No monthly usage yet</td></tr>"
        out = []
        for row in service_breakdown:
            service = str(row.get("service") or "")
            plan = str(row.get("plan") or "")
            out.append(
                "<tr>"
                f"<td><div class='cell-title'>{_service_badge(service)}</div><div class='cell-sub mono'>{html.escape(service or '-')}</div></td>"
                f"<td>{_plan_badge(plan)}</td>"
                f"<td>{int(row.get('installs') or 0):,}</td>"
                f"<td>{int(row.get('calls') or 0):,}</td>"
                f"<td><div class='cell-title'>{_fmt_age(row.get('last_seen'))}</div><div class='cell-sub'>{_fmt_ts(row.get('last_seen'))}</div></td>"
                "</tr>"
            )
        return "".join(out)

    def rows_for_network_breakdown() -> str:
        if not network_breakdown:
            return "<tr><td colspan='5' class='muted'>No request logs yet</td></tr>"
        out = []
        for row in network_breakdown:
            service = str(row.get("service") or "")
            plan = str(row.get("plan") or "")
            errors = int(row.get("errors") or 0)
            out.append(
                "<tr>"
                f"<td><div class='cell-title'>{_service_badge(service)}</div><div class='cell-sub mono'>{html.escape(service or '-')}</div></td>"
                f"<td>{_plan_badge(plan)}</td>"
                f"<td>{int(row.get('requests') or 0):,}</td>"
                f"<td>{int(row.get('avg_latency') or 0)}ms</td>"
                f"<td>{_badge(f'{errors:,} error' + ('' if errors == 1 else 's'), 'red' if errors else 'green')}</td>"
                "</tr>"
            )
        return "".join(out)

    def rows_for_report_breakdown() -> str:
        if not report_breakdown:
            return "<tr><td colspan='6' class='muted'>No report gateway events in the last 24 hours</td></tr>"
        out = []
        for row in report_breakdown:
            report_type = str(row.get("report_type") or "")
            origin = str(row.get("origin") or "")
            team = str(row.get("team") or "")
            status = str(row.get("status") or "")
            out.append(
                "<tr>"
                f"<td><div class='cell-title'>{_badge(report_type or 'unknown', 'amber' if report_type == 'crash' else 'blue')}</div><div class='cell-sub mono'>{html.escape(origin or '-')}</div></td>"
                f"<td>{_badge(team or 'default', 'cyan')}</td>"
                f"<td>{_report_status_badge(status)}</td>"
                f"<td>{int(row.get('reports') or 0):,}</td>"
                f"<td>{int(row.get('installs') or 0):,}</td>"
                f"<td><div class='cell-title'>{_fmt_age(row.get('last_seen'))}</div><div class='cell-sub'>{_fmt_ts(row.get('last_seen'))}</div></td>"
                "</tr>"
            )
        return "".join(out)

    def rows_for_recent_reports() -> str:
        if not recent_reports:
            return "<tr><td colspan='7' class='muted'>No report gateway events recorded yet</td></tr>"
        out = []
        for row in recent_reports:
            report_type = str(row.get("report_type") or "")
            origin = str(row.get("origin") or "")
            context = str(row.get("context") or "").strip()
            team = str(row.get("team") or "")
            status = str(row.get("status") or "")
            out.append(
                "<tr>"
                f"<td><div class='cell-title'>{_fmt_age(row.get('ts'))}</div><div class='cell-sub'>{_fmt_ts(row.get('ts'))}</div></td>"
                f"<td class='mono'>{html.escape(str(row.get('install_fingerprint') or '-'))}</td>"
                f"<td><div class='cell-title'>{_badge(report_type or 'unknown', 'amber' if report_type == 'crash' else 'blue')}</div><div class='cell-sub mono'>{html.escape(origin or '-')}</div></td>"
                f"<td><div class='cell-title'>{html.escape(context[:80] or '-')}</div><div class='cell-sub mono'>{html.escape(str(row.get('network_tag') or '-'))}</div></td>"
                f"<td>{_badge(team or 'default', 'cyan')}</td>"
                f"<td>{_report_status_badge(status)}</td>"
                f"<td class='cell-sub mono'>{html.escape(status or '-')}</td>"
                "</tr>"
            )
        return "".join(out)

    def rows_for_report_dedupe() -> str:
        if not report_dedupe_rows:
            return "<tr><td colspan='6' class='muted'>No report dedupe groups recorded yet</td></tr>"
        out = []
        for row in report_dedupe_rows[:30]:
            report_type = str(row.get("report_type") or "")
            origin = str(row.get("origin") or "")
            team = str(row.get("team") or "")
            count = int(row.get("count") or 0)
            url = str(row.get("url") or "").strip()
            out.append(
                "<tr>"
                f"<td><div class='cell-title'>{_badge(report_type or 'unknown', 'amber' if report_type == 'crash' else 'blue')}</div><div class='cell-sub mono'>{html.escape(origin or '-')}</div></td>"
                f"<td>{_badge(team or 'default', 'cyan')}</td>"
                f"<td class='mono'>{html.escape(str(row.get('install_fingerprint') or '-'))}</td>"
                f"<td><div class='cell-title'>{count:,} seen</div><div class='cell-sub'>{'Linear issue filed' if url else 'No issue URL stored'}</div></td>"
                f"<td><div class='cell-title'>{_fmt_age(row.get('last_seen'))}</div><div class='cell-sub'>First {_fmt_age(row.get('first_seen'))}</div></td>"
                f"<td class='cell-sub mono'>{html.escape(url[:92]) if url else '-'}</td>"
                "</tr>"
            )
        return "".join(out)

    def rows_for_snapshot_pool() -> str:
        if not snapshots:
            return "<tr><td colspan='5' class='muted'>No shared schedule snapshots have been cached yet</td></tr>"
        out = []
        for row in snapshots[:18]:
            meta = _load_json_blob(row.get("meta_json"), {})
            stats = _snapshot_shared_stats(row)
            records_count = len(_load_json_blob(row.get("records_json"), []))
            pages_fetched = int(meta.get("pages_fetched", 0) or 0)
            raw_rows = int(meta.get("raw_rows", 0) or 0)
            dates_touched = meta.get("dates_touched", 0)
            if isinstance(dates_touched, list):
                dates_count = len(dates_touched)
            else:
                try:
                    dates_count = int(dates_touched or 0)
                except Exception:
                    dates_count = 0
            last_error = str(row.get("last_error") or "").strip()
            last_state = str(row.get("last_cache_state") or "fresh")
            out.append(
                "<tr>"
                f"<td><div class='cell-title mono'>{html.escape(str(row.get('airport_iata') or '-'))}</div>"
                f"<div class='cell-sub'>{html.escape(str(row.get('timezone') or '-'))}</div>"
                f"<div class='cell-sub'>{_window_label(int(row.get('display_grace_minutes') or 0), int(row.get('display_horizon_hours') or 0))}</div></td>"
                f"<td><div class='cell-title'>{records_count:,} records</div>"
                f"<div class='cell-sub'>{raw_rows:,} raw rows | {pages_fetched} pages | {dates_count} dates</div></td>"
                f"<td><div class='cell-title'>{stats['client_accesses']:,} client serves</div>"
                f"<div class='cell-sub'>{stats['upstream_pulls']:,} upstream pulls | {stats['cache_hit_rate_pct']:.1f}% hit rate | {stats['estimated_savings']:,} saved</div></td>"
                f"<td><div class='cell-title'>{_cache_badge(last_state, has_error=bool(last_error))}</div>"
                f"<div class='cell-sub'>{html.escape(last_error[:88]) if last_error else 'Healthy latest payload'}</div></td>"
                f"<td><div class='cell-title'>{_fmt_age(row.get('updated_at'))}</div>"
                f"<div class='cell-sub'>Generated {_fmt_age(row.get('generated_at'))}</div>"
                f"<div class='cell-sub'>{_fmt_ts(row.get('updated_at'))}</div></td>"
                "</tr>"
            )
        return "".join(out)

    def rows_for_live_lanes() -> str:
        if not active_lanes:
            return "<tr><td colspan='5' class='muted'>No client interests reported in the last 24 hours</td></tr>"
        out = []
        for row in active_lanes[:18]:
            snapshot = row.get("snapshot")
            lifecycle = (
                _snapshot_lifecycle_state(snapshot, refresh_seconds=int(row.get("refresh_min") or 3600))
                if snapshot is not None
                else "miss"
            )
            stats = _snapshot_shared_stats(snapshot or {})
            records_count = len(_load_json_blob((snapshot or {}).get("records_json"), [])) if snapshot else 0
            installs_preview = ", ".join(row.get("install_fingerprints") or [])
            plan_html = " ".join(
                _plan_badge(plan)
                for plan in sorted(
                    row.get("plans") or set(),
                    key=lambda plan: plan_order.get(str(plan or ""), 99),
                )
            )
            out.append(
                "<tr>"
                f"<td><div class='cell-title mono'>{html.escape(str(row.get('airport_iata') or '-'))}</div><div class='cell-sub'>{html.escape(str(row.get('timezone') or '-'))}</div></td>"
                f"<td><div class='cell-title'>{int(row.get('install_count') or 0)} installs</div><div class='cell-sub'>{plan_html or _badge('unknown', 'slate')}</div><div class='cell-sub mono'>{html.escape(installs_preview) if installs_preview else 'No fingerprints yet'}</div></td>"
                f"<td><div class='cell-title'>{_window_label(int(row.get('display_grace_minutes') or 0), int(row.get('display_horizon_hours') or 0))}</div><div class='cell-sub'>Refresh every {_fmt_refresh_range(int(row.get('refresh_min') or 3600), int(row.get('refresh_max') or 3600))}</div></td>"
                f"<td><div class='cell-title'>{_cache_badge(lifecycle, has_error=bool((snapshot or {}).get('last_error')))}</div><div class='cell-sub'>{records_count:,} records | {stats['client_accesses']:,} serves | {stats['estimated_savings']:,} saved</div></td>"
                f"<td><div class='cell-title'>{_fmt_age(row.get('last_seen'))}</div><div class='cell-sub'>Last client {_fmt_ts(row.get('last_seen'))}</div><div class='cell-sub'>Snapshot {(_fmt_age((snapshot or {}).get('generated_at')) if snapshot else '-')}</div></td>"
                "</tr>"
            )
        return "".join(out)

    def rows_for_tokens() -> str:
        if not tokens:
            return "<tr><td colspan='7' class='muted'>No managed activation tokens created yet</td></tr>"
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
                f"<td><div class='cell-title mono'>{html.escape(str(row['token_prefix'] or '-'))}...</div><div class='cell-sub'>{_fmt_ts(row.get('created_at'))}</div></td>"
                f"<td><div class='cell-title'>{html.escape(str(row['label'] or '-'))}</div><div class='cell-sub'>{_plan_badge('managed')}</div></td>"
                f"<td>{_meter(int(row['schedule_used'] or 0), int(row['schedule_limit'] or 0))}</td>"
                f"<td>{_meter(int(row['radar_used'] or 0), int(row['radar_limit'] or 0))}</td>"
                f"<td><div class='cell-title mono'>{html.escape(_install_fingerprint(str(row['bound_install_id'] or ''))) if row['bound_install_id'] else '-'}</div><div class='cell-sub'>{_fmt_ts(row.get('last_seen')) if row['last_seen'] else 'No recent token check-in'}</div></td>"
                f"<td><div class='cell-title'>{_badge(status, 'red' if status == 'revoked' else 'green')}</div><div class='cell-sub'>{'Token can no longer authenticate' if status == 'revoked' else 'Managed access is enabled'}</div></td>"
                f"<td class='actions'>{''.join(action_bits)}</td>"
                "</tr>"
            )
        return "".join(out)

    def rows_for_activation_requests() -> str:
        if not activation_requests:
            return "<tr><td colspan='7' class='muted'>No activation requests have reached the relay yet</td></tr>"
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
            source = str(row["decision_source"] or "-").strip() or "-"
            note = str(row["decision_note"] or "").strip() or "No decision note recorded"
            lifecycle_bits = [f"Created {_fmt_ts(row.get('created_at'))}"]
            if row.get("updated_at"):
                lifecycle_bits.append(f"Updated {_fmt_ts(row.get('updated_at'))}")
            if row.get("last_seen"):
                lifecycle_bits.append(f"Last seen {_fmt_age(row.get('last_seen'))}")
            out.append(
                "<tr>"
                f"<td><div class='cell-title mono'>{html.escape(str(row['install_fingerprint'] or '-'))}</div><div class='cell-sub mono'>{html.escape(str(row['install_id'] or ''))[:12]}...</div></td>"
                f"<td><div class='cell-title mono'>{html.escape(str(row['network_tag'] or '-'))}</div><div class='cell-sub'>{_badge(source, 'slate')}</div></td>"
                f"<td><div class='cell-title'>{html.escape(label)}</div><div class='cell-sub'>{_plan_badge(str(row.get('requested_mode') or 'community'))}</div></td>"
                f"<td><div class='cell-title'>{_request_status_badge(status)}</div><div class='cell-sub'>{html.escape(str(row['token_prefix'] or '-') + ('...' if row['token_prefix'] else ''))}</div></td>"
                f"<td><div class='cell-title'>{html.escape(note[:88])}</div><div class='cell-sub'>{' | '.join(html.escape(bit) for bit in lifecycle_bits)}</div></td>"
                f"<td><div class='cell-title'>{_fmt_age(row.get('created_at'))}</div><div class='cell-sub'>{_fmt_ts(row.get('created_at'))}</div></td>"
                f"<td class='actions'>{''.join(action_bits)}</td>"
                "</tr>"
            )
        return "".join(out)

    def rows_for_installs() -> str:
        if not installs:
            return "<tr><td colspan='10' class='muted'>No relay install usage recorded yet</td></tr>"
        out = []
        for row in installs:
            blocked = bool(row.get("blocked"))
            install_ref = str(row.get("action_ref") or "")
            install_fp = str(row.get("install_fingerprint") or "")
            lane = row.get("current_lane") if isinstance(row.get("current_lane"), dict) else {}
            action_bits = [
                _post_form(
                    "/admin/counters/reset",
                    {"scope": "install", "install_ref": install_ref},
                    "Reset counters",
                    "slate",
                )
            ]
            if blocked:
                action_bits.append(
                    _post_form(
                        "/admin/install/unblock",
                        {"install_ref": install_ref},
                        "Restore access",
                        "green",
                    )
                )
            else:
                action_bits.append(
                    _post_form(
                        "/admin/install/block",
                        {"install_ref": install_ref, "reason": "revoked by admin"},
                        "Revoke access",
                        "red",
                    )
                )
            plan_html = _plan_badge(str(row.get("plan") or "unknown"))
            gui_bits = [
                str(row.get("os_family") or "").strip(),
                str(row.get("effective_gui") or row.get("requested_gui") or "").strip(),
                str(row.get("app_version") or "").strip(),
            ]
            gui_label = " | ".join(bit for bit in gui_bits if bit) or "-"
            airport = str(lane.get("airport_iata") or "-")
            timezone_name = str(lane.get("timezone") or "-")
            refresh_seconds = int(lane.get("refresh_seconds") or 0)
            out.append(
                "<tr>"
                f"<td><div class='cell-title mono'>{html.escape(install_fp or '-')}</div><div class='cell-sub'>First {_fmt_ts(row.get('first_seen'))}</div></td>"
                f"<td><div class='cell-title'>{html.escape(gui_label)}</div><div class='cell-sub'>{html.escape(str(row.get('arch') or '-'))}</div></td>"
                f"<td><div class='cell-title mono'>{html.escape(airport)}</div><div class='cell-sub'>{html.escape(timezone_name)} | {_fmt_refresh(refresh_seconds) if refresh_seconds else '-'}</div></td>"
                f"<td>{plan_html}</td>"
                f"<td><div class='cell-title'>{int(row.get('companion_count') or 0):,}</div><div class='cell-sub'>Companion clients</div></td>"
                f"<td><div class='cell-title'>{int(row.get('matrix_online_count') or 0):,} / {int(row.get('matrix_count') or 0):,}</div><div class='cell-sub'>Matrix online</div></td>"
                f"<td><div class='cell-title'>{int(row.get('schedule_calls') or 0):,}</div><div class='cell-sub'>Schedule accesses</div></td>"
                f"<td><div class='cell-title'>{int(row.get('radar_calls') or 0):,}</div><div class='cell-sub'>Radar accesses</div></td>"
                f"<td><div class='cell-title'>{_badge(str(row.get('status') or 'unknown').replace('_', ' '), 'red' if blocked else ('green' if row.get('status') == 'active' else 'slate'))}</div><div class='cell-sub'>{_fmt_ts(row.get('last_seen'))}</div></td>"
                f"<td class='actions'>{''.join(action_bits)}</td>"
                "</tr>"
            )
        return "".join(out)

    def rows_for_recent() -> str:
        if not recent:
            return "<tr><td colspan='7' class='muted'>No requests yet</td></tr>"
        out = []
        for row in recent:
            service = str(row.get("service") or "")
            plan = str(row.get("plan") or "")
            scope = str(row.get("mode") or "-").replace("_", " ")
            out.append(
                "<tr>"
                f"<td><div class='cell-title'>{_fmt_age(row.get('ts'))}</div><div class='cell-sub'>{_fmt_ts(row.get('ts'))}</div></td>"
                f"<td class='mono'>{html.escape(_install_fingerprint(str(row['install_id'] or '')))}</td>"
                f"<td>{_service_badge(service)}</td>"
                f"<td><div class='cell-title'>{html.escape(scope)}</div><div class='cell-sub'>{_plan_badge(plan)}</div></td>"
                f"<td>{_http_badge(int(row.get('status') or 0))}</td>"
                f"<td>{int(row.get('latency_ms') or 0)}ms</td>"
                f"<td class='cell-sub mono'>{html.escape(service or '-')}</td>"
                "</tr>"
            )
        return "".join(out)

    token_notice = (
        f"<div class='notice ok'><strong>Fresh token:</strong> <span class='mono'>{html.escape(created_token)}</span></div>"
        if created_token
        else ""
    )
    message_notice = f"<div class='notice'>{html.escape(message)}</div>" if message else ""
    activation_open = " open" if pending_requests else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Local Flight Network Admin</title>
<style>
  :root {{
    --bg: #061019;
    --panel: #0f1926;
    --line: #223448;
    --line-soft: #182737;
    --text: #ecf4ff;
    --muted: #91a7c0;
    --soft: #6f849b;
    --blue: #5ca8ff;
    --cyan: #43d8e8;
    --green: #2ad07f;
    --amber: #ffbf59;
    --red: #ff716d;
    --shadow: 0 28px 80px rgba(0, 0, 0, 0.34);
  }}
  * {{ box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; }}
  body {{
    margin: 0;
    min-height: 100vh;
    font-family: "Segoe UI Variable", "Aptos", "SF Pro Display", sans-serif;
    background:
      radial-gradient(circle at top left, rgba(67, 216, 232, 0.12), transparent 28%),
      radial-gradient(circle at top right, rgba(92, 168, 255, 0.10), transparent 24%),
      linear-gradient(180deg, #061019 0%, #0b1723 48%, #08111a 100%);
    color: var(--text);
    line-height: 1.45;
  }}
  .wrap {{ max-width: 1600px; margin: 0 auto; padding: 28px; }}
  .admin-bar {{
    position: sticky;
    top: 0;
    z-index: 30;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 14px;
    margin: -6px 0 16px;
    padding: 10px;
    border: 1px solid rgba(92, 168, 255, 0.18);
    border-radius: 18px;
    background: rgba(6, 16, 25, 0.88);
    box-shadow: 0 18px 44px rgba(0, 0, 0, 0.22);
    backdrop-filter: blur(18px);
  }}
  .brand-chip {{
    display: inline-flex;
    align-items: center;
    gap: 10px;
    min-width: max-content;
    padding: 8px 10px;
    color: var(--text);
    font-weight: 850;
    letter-spacing: .02em;
  }}
  .brand-mark {{
    width: 28px;
    height: 28px;
    display: grid;
    place-items: center;
    border-radius: 9px;
    color: #03111a;
    background: linear-gradient(135deg, var(--cyan), var(--blue));
    font-family: "Cascadia Code", Consolas, monospace;
    font-size: .72rem;
    box-shadow: 0 8px 22px rgba(67, 216, 232, 0.24);
  }}
  .admin-nav {{
    display: flex;
    gap: 6px;
    overflow-x: auto;
    scrollbar-width: thin;
  }}
  .admin-nav a {{
    flex: 0 0 auto;
    padding: 9px 11px;
    border-radius: 12px;
    color: var(--muted);
    text-decoration: none;
    font-size: .82rem;
    font-weight: 800;
    letter-spacing: .02em;
  }}
  .admin-nav a:hover,
  .admin-nav a:focus,
  .admin-nav a.active {{
    color: var(--text);
    background: rgba(92, 168, 255, 0.15);
    outline: none;
  }}
  .hero {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 24px;
    padding: 24px 26px;
    margin-bottom: 16px;
    border-radius: 22px;
    border: 1px solid rgba(92, 168, 255, 0.22);
    background:
      linear-gradient(135deg, rgba(92, 168, 255, 0.16), rgba(15, 25, 38, 0.92) 42%),
      linear-gradient(180deg, rgba(255, 255, 255, 0.03), rgba(255, 255, 255, 0.01));
    box-shadow: var(--shadow);
  }}
  .eyebrow {{
    margin-bottom: 8px;
    color: var(--cyan);
    font-size: .78rem;
    letter-spacing: .14em;
    text-transform: uppercase;
  }}
  h1 {{ margin: 0 0 8px; font-size: 2rem; line-height: 1.05; }}
  .sub {{
    max-width: 860px;
    color: var(--muted);
    font-size: .95rem;
  }}
  .hero-meta {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    justify-content: flex-end;
    align-content: flex-start;
    min-width: 260px;
  }}
  .notice {{
    margin: 0 0 14px;
    padding: 12px 14px;
    border-radius: 14px;
    background: rgba(17, 29, 42, 0.92);
    border: 1px solid var(--line);
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.18);
  }}
  .notice.ok {{
    border-color: rgba(42, 208, 127, 0.42);
    background: rgba(10, 41, 26, 0.88);
  }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-bottom: 18px; }}
  .metric {{
    padding: 14px 15px;
    border-radius: 14px;
    border: 1px solid var(--line);
    background: linear-gradient(180deg, rgba(19, 33, 49, 0.94), rgba(12, 22, 34, 0.96));
    box-shadow: 0 18px 44px rgba(0, 0, 0, 0.18);
  }}
  .metric-label {{
    color: var(--muted);
    font-size: .74rem;
    letter-spacing: .10em;
    text-transform: uppercase;
  }}
  .metric-value {{
    margin-top: 8px;
    font-size: 1.65rem;
    font-weight: 800;
    line-height: 1;
  }}
  .metric-sub {{
    margin-top: 6px;
    color: var(--soft);
    font-size: .82rem;
  }}
  .split {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-bottom: 16px; }}
  .card, .section {{
    scroll-margin-top: 96px;
    border-radius: 16px;
    border: 1px solid var(--line);
    background: linear-gradient(180deg, rgba(14, 25, 38, 0.96), rgba(10, 18, 29, 0.98));
    box-shadow: 0 18px 48px rgba(0, 0, 0, 0.18);
  }}
  .card {{ padding: 16px 18px; }}
  .stack {{ display: grid; gap: 16px; }}
  .section-head {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 16px;
    padding: 16px 18px 0;
  }}
  .section-head h2 {{
    margin: 0 0 6px;
    font-size: .9rem;
    color: var(--text);
    letter-spacing: .12em;
    text-transform: uppercase;
  }}
  .section-copy {{
    color: var(--muted);
    font-size: .88rem;
    max-width: 820px;
  }}
  .section-tools {{ padding: 0 18px 14px; color: var(--soft); font-size: .82rem; }}
  .table-filter {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    margin: 12px 0 0;
  }}
  .table-filter input {{
    max-width: 320px;
    padding: 8px 10px;
    border-radius: 10px;
    font-size: .82rem;
  }}
  .table-filter .tiny {{ min-width: max-content; }}
  .soft {{ color: var(--soft); }}
  .muted {{ color: var(--soft); padding: 24px 14px; text-align: center; }}
  .mono {{ font-family: "Cascadia Code", "SFMono-Regular", Consolas, monospace; }}
  .tiny {{ font-size: .8rem; color: var(--muted); }}
  .cell-title {{ font-weight: 700; }}
  .cell-sub {{ margin-top: 3px; color: var(--soft); font-size: .8rem; }}
  .badge {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 9px;
    border-radius: 999px;
    border: 1px solid transparent;
    font-size: .74rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .08em;
    white-space: nowrap;
  }}
  .badge-blue {{ color: #a7d3ff; background: rgba(92, 168, 255, 0.14); border-color: rgba(92, 168, 255, 0.25); }}
  .badge-cyan {{ color: #b6f6ff; background: rgba(67, 216, 232, 0.14); border-color: rgba(67, 216, 232, 0.28); }}
  .badge-green {{ color: #b9ffd9; background: rgba(42, 208, 127, 0.14); border-color: rgba(42, 208, 127, 0.26); }}
  .badge-amber {{ color: #ffe3a7; background: rgba(255, 191, 89, 0.14); border-color: rgba(255, 191, 89, 0.28); }}
  .badge-red {{ color: #ffd0cd; background: rgba(255, 113, 109, 0.14); border-color: rgba(255, 113, 109, 0.28); }}
  .badge-slate {{ color: #d0dded; background: rgba(145, 167, 192, 0.12); border-color: rgba(145, 167, 192, 0.20); }}
  .stat-list {{ display: grid; gap: 10px; }}
  .stat-row {{
    display: flex;
    justify-content: space-between;
    gap: 16px;
    padding: 10px 0;
    border-bottom: 1px solid var(--line-soft);
    font-size: .92rem;
  }}
  .stat-row:last-child {{ border-bottom: 0; }}
  .stat-row strong {{ color: var(--text); }}
  .table-shell {{
    max-height: min(520px, calc(100vh - 250px));
    padding: 0 18px 18px;
    overflow: auto;
    overscroll-behavior: contain;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: .84rem;
    background: rgba(8, 16, 25, 0.86);
    border: 1px solid var(--line-soft);
    border-radius: 16px;
    overflow: hidden;
  }}
  th {{
    position: sticky;
    top: 0;
    z-index: 5;
    text-align: left;
    padding: 11px 12px;
    background: rgba(15, 25, 38, 0.95);
    border-bottom: 1px solid var(--line);
    color: var(--muted);
    font-size: .72rem;
    letter-spacing: .1em;
    text-transform: uppercase;
  }}
  th[data-sortable] {{ cursor: pointer; user-select: none; }}
  th[data-sortable]::after {{ content: "  sort"; color: var(--soft); font-size: .62rem; }}
  th.sort-asc::after {{ content: "  asc"; color: var(--cyan); }}
  th.sort-desc::after {{ content: "  desc"; color: var(--cyan); }}
  td {{
    padding: 12px;
    border-bottom: 1px solid var(--line-soft);
    vertical-align: top;
  }}
  tr:last-child td {{ border-bottom: 0; }}
  tr:hover td {{ background: rgba(92, 168, 255, 0.04); }}
  .actions {{
    min-width: 220px;
    max-width: 320px;
  }}
  form {{ display: grid; gap: 10px; }}
  .inline {{ display: inline-block; margin: 0 6px 6px 0; }}
  .inline input {{ display: none; }}
  label {{ font-size: .83rem; color: var(--muted); }}
  input {{
    width: 100%;
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 11px 12px;
    background: rgba(5, 11, 18, 0.92);
    color: var(--text);
    outline: none;
  }}
  input:focus {{ border-color: rgba(92, 168, 255, 0.45); box-shadow: 0 0 0 3px rgba(92, 168, 255, 0.12); }}
  button {{
    border: 0;
    border-radius: 12px;
    padding: 10px 13px;
    font-weight: 800;
    cursor: pointer;
    background: var(--green);
    color: #041108;
  }}
  button.red {{ background: var(--red); color: #220605; }}
  button.amber {{ background: var(--amber); color: #261500; }}
  button.slate {{ background: #223447; color: var(--text); }}
  button.green {{ background: var(--green); color: #041108; }}
  .meter {{
    height: 8px;
    border-radius: 999px;
    background: rgba(145, 167, 192, 0.13);
    overflow: hidden;
    margin-bottom: 6px;
  }}
  .meter-fill {{ height: 100%; border-radius: inherit; }}
  .meter-green {{ background: linear-gradient(90deg, rgba(42, 208, 127, 0.45), rgba(42, 208, 127, 0.92)); }}
  .meter-amber {{ background: linear-gradient(90deg, rgba(255, 191, 89, 0.45), rgba(255, 191, 89, 0.92)); }}
  .meter-red {{ background: linear-gradient(90deg, rgba(255, 113, 109, 0.45), rgba(255, 113, 109, 0.92)); }}
  details.section {{ margin-bottom: 16px; overflow: hidden; }}
  details.section > summary {{
    position: sticky;
    top: 70px;
    z-index: 10;
    list-style: none;
    cursor: pointer;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
    padding: 16px 18px;
    font-weight: 700;
    background: linear-gradient(180deg, rgba(14, 25, 38, 0.98), rgba(10, 18, 29, 0.98));
  }}
  details.section > summary::-webkit-details-marker {{ display: none; }}
  details.section[open] > summary {{ border-bottom: 1px solid var(--line); }}
  .summary-meta {{ color: var(--muted); font-size: .82rem; font-weight: 600; }}
  @media (max-width: 1080px) {{
    .split {{ grid-template-columns: 1fr; }}
    .hero {{ flex-direction: column; }}
    .hero-meta {{ justify-content: flex-start; min-width: 0; }}
    .admin-bar {{ align-items: stretch; flex-direction: column; }}
    .brand-chip {{ width: 100%; }}
    .admin-nav {{ width: 100%; }}
  }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <div>
      <div class="eyebrow">Shared Schedule Relay</div>
      <h1>Local Flight Community Relay Admin</h1>
      <div class="sub">This surface is the operator view for shared airport snapshots, activation flow, managed exceptions, radar relay traffic, and upstream provider health. Community and managed installs share cached schedule windows here, while raw provider passthrough stays operator-only.</div>
    </div>
    <div class="hero-meta">
      {_badge(f"Month {month}", "blue")}
      {_badge(f"Revision {provider_revision}", "cyan")}
      {_badge("Raw IP storage disabled", "slate")}
      {_badge("Raw provider debug on" if _raw_provider_debug_enabled() else "Raw provider debug off", "amber" if _raw_provider_debug_enabled() else "slate")}
      {_badge(f"Logged in as {username}", "green")}
    </div>
  </div>
  {token_notice}
  {message_notice}

  <div class="admin-bar" aria-label="Relay admin sections">
    <div class="brand-chip"><span class="brand-mark">LF</span><span>Network Admin</span></div>
    <nav class="admin-nav">
      <a href="#overview">Overview</a>
      <a href="#providers">Providers</a>
      <a href="#traffic">Traffic</a>
      <a href="#reports">Reports</a>
      <a href="#schedules">Schedules</a>
      <a href="#activations">Activations</a>
      <a href="#tokens">Tokens</a>
      <a href="#fleet">Fleet</a>
      <a href="#maintenance">Maintenance</a>
    </nav>
  </div>

  <div class="grid" id="overview">
    <div class="metric"><div class="metric-label">Known installs</div><div class="metric-value">{int(fleet_metrics.get('known_installs', total_installs) or 0):,}</div><div class="metric-sub">Fleet rows with relay activity or heartbeat</div></div>
    <div class="metric"><div class="metric-label">Active installs (24h)</div><div class="metric-value">{int(fleet_metrics.get('active_installs_24h', active_clients_24h) or 0):,}</div><div class="metric-sub">{fleet_metrics.get('companion_installs', 0):,} with companion | {fleet_metrics.get('matrix_installs', 0):,} with matrix</div></div>
    <div class="metric"><div class="metric-label">Active airport lanes</div><div class="metric-value">{active_lane_count:,}</div><div class="metric-sub">Distinct airport and board-window combinations active today</div></div>
    <div class="metric"><div class="metric-label">Schedule accesses</div><div class="metric-value">{int(total_schedule or 0):,}</div><div class="metric-sub">Per-install relay schedule uses this month</div></div>
    <div class="metric"><div class="metric-label">Upstream pulls</div><div class="metric-value">{int(total_schedule_upstream or 0):,}</div><div class="metric-sub">Actual AviationStack page pulls charged upstream</div></div>
    <div class="metric"><div class="metric-label">Snapshot refreshes</div><div class="metric-value">{snapshot_refreshes:,}</div><div class="metric-sub">{snapshot_pool_count:,} cached windows | {snapshot_stale_count:,} currently stale</div></div>
    <div class="metric"><div class="metric-label">Cache hit rate</div><div class="metric-value">{snapshot_hit_rate:.1f}%</div><div class="metric-sub">{snapshot_hits:,} cache hits | {snapshot_stale:,} stale serves</div></div>
    <div class="metric"><div class="metric-label">Estimated savings</div><div class="metric-value">{snapshot_savings:,}</div><div class="metric-sub">Upstream refreshes avoided by sharing airport snapshots</div></div>
    <div class="metric"><div class="metric-label">Radar accesses</div><div class="metric-value">{int(total_radar or 0):,}</div><div class="metric-sub">Relay radar uses this month</div></div>
    <div class="metric"><div class="metric-label">Request errors (24h)</div><div class="metric-value">{int(totals_24h['errors'] or 0):,}</div><div class="metric-sub">{int(totals_24h['requests'] or 0):,} requests | {int(totals_24h['avg_latency'] or 0)}ms average latency</div></div>
    <div class="metric"><div class="metric-label">Reports (24h)</div><div class="metric-value">{report_count_24h:,}</div><div class="metric-sub">{report_filed_24h:,} filed | {report_deduped_24h:,} deduped | {report_installs_24h:,} installs</div></div>
    <div class="metric"><div class="metric-label">Pending reviews</div><div class="metric-value">{int(pending_requests or 0):,}</div><div class="metric-sub">Activation requests waiting for a human decision</div></div>
    <div class="metric"><div class="metric-label">Blocked installs</div><div class="metric-value">{int(blocked_count or 0):,}</div><div class="metric-sub">{snapshot_error_count:,} snapshot rows currently carry a last error note</div></div>
  </div>

  <div class="split" id="providers">
    <div class="card stack">
      <div>
        <div class="eyebrow">Provider State</div>
        <h1 style="font-size:1.35rem;margin:0 0 8px;">Relay keys and shared behavior</h1>
        <div class="section-copy">Managed and community clients do not receive vendor keys directly. The relay keeps provider credentials private, shares airport snapshots across installs, and only exposes Local Flight's canonical schedule records to clients.</div>
      </div>
      <div class="stat-list">
        <div class="stat-row"><span>Provider revision</span><strong>{html.escape(str(provider_revision))}</strong></div>
        <div class="stat-row"><span>AeroDataBox</span><strong>{html.escape(_mask_secret(aerodatabox_key))} <span class="tiny">({html.escape(aerodatabox_source)})</span></strong></div>
        <div class="stat-row"><span>AviationStack</span><strong>{html.escape(_mask_secret(aviationstack_key))} <span class="tiny">({html.escape(aviationstack_source)})</span></strong></div>
        <div class="stat-row"><span>RapidAPI ADS-B</span><strong>{html.escape(_mask_secret(rapidapi_key))} <span class="tiny">({html.escape(rapidapi_source)})</span></strong></div>
        <div class="stat-row"><span>Community schedule cap</span><strong>{_community_schedule_limit()} accesses / install / 30-day window</strong></div>
        <div class="stat-row"><span>Managed defaults</span><strong>{_managed_schedule_limit()} schedule | {_managed_radar_limit()} radar</strong></div>
        <div class="stat-row"><span>Snapshot pool</span><strong>{snapshot_pool_count:,} windows | {snapshot_refreshes:,} refreshes | {snapshot_stale:,} stale serves</strong></div>
        <div class="stat-row"><span>Radar cache</span><strong>{_radar_cache_seconds()} seconds</strong></div>
        <div class="stat-row"><span>Raw provider debug</span><strong>{'Enabled on admin/local only' if _raw_provider_debug_enabled() else 'Disabled'}</strong></div>
        <div class="stat-row"><span>Report gateway</span><strong>{_report_gateway_badge()} <span class="tiny">{report_specific_teams} specific teams + default {'ready' if report_team_config.get('default') else 'missing'}</span></strong></div>
        <div class="stat-row"><span>Activation privacy</span><strong>Anonymous network tags only | no raw IP storage</strong></div>
      </div>
      <form method="post" action="/admin/providers/save">
        <label>AeroDataBox key
          <input name="aerodatabox_key" placeholder="Paste a replacement key to store in the relay" />
        </label>
        <label>AviationStack key
          <input name="aviationstack_key" placeholder="Paste a replacement key to store in the relay" />
        </label>
        <label>RapidAPI ADS-B key
          <input name="rapidapi_key" placeholder="Paste a replacement key to store in the relay" />
        </label>
        <button type="submit">Save provider keys</button>
      </form>
      <div>
        {_post_form('/admin/providers/clear', {'provider': 'aerodatabox'}, 'Clear AeroDataBox override', 'slate')}
        {_post_form('/admin/providers/clear', {'provider': 'aviationstack'}, 'Clear AviationStack override', 'slate')}
        {_post_form('/admin/providers/clear', {'provider': 'rapidapi'}, 'Clear RapidAPI override', 'slate')}
      </div>
    </div>

    <div class="card stack" id="maintenance">
      <div>
        <div class="eyebrow">Operator Controls</div>
        <h1 style="font-size:1.35rem;margin:0 0 8px;">Managed tokens and relay counters</h1>
        <div class="section-copy">Normal installs should keep auto-issuing through the setup flow. This panel exists for managed exceptions, manual quota corrections, reshuffles, revokes, and log resets when you need to intervene.</div>
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
        {_post_form('/admin/maintenance/clean-trial', {}, 'Clean setup trial state', 'amber')}
        <form method="post" action="/admin/counters/correct-schedule" style="margin-top:0.5rem;display:flex;gap:0.4rem;align-items:center">
          <input name="total" type="number" min="0" value="{int(total_schedule or 0)}" style="width:9rem" title="Set known schedule total for this month (includes prior usage outside this relay)" />
          <button type="submit">Correct schedule total</button>
        </form>
      </div>
    </div>
  </div>

  <div class="split" id="traffic">
    <section class="section">
      <div class="section-head">
        <div>
          <h2>Monthly service counters</h2>
          <div class="section-copy">This is the usage view that matters for product policy: per-install schedule accesses, shared upstream pulls, and radar relay traffic, all split by plan.</div>
        </div>
      </div>
      <div class="table-shell">
        <table>
          <thead><tr><th>Service</th><th>Plan</th><th>Installs</th><th>Calls</th><th>Last seen</th></tr></thead>
          <tbody>{rows_for_service_breakdown()}</tbody>
        </table>
      </div>
    </section>
    <section class="section">
      <div class="section-head">
        <div>
          <h2>Transport health (24h)</h2>
          <div class="section-copy">Recent network behavior across the relay. This is the quickest place to spot latency drift, quota failures, or a provider path getting noisy.</div>
        </div>
      </div>
      <div class="table-shell">
        <table>
          <thead><tr><th>Service</th><th>Plan</th><th>Requests</th><th>Avg latency</th><th>Errors</th></tr></thead>
          <tbody>{rows_for_network_breakdown()}</tbody>
        </table>
      </div>
    </section>
  </div>

  <div class="split" id="reports">
    <section class="section">
      <div class="section-head">
        <div>
          <h2>Report gateway (24h)</h2>
          <div class="section-copy">Manual feedback and diagnostics-gated crash reports flow through `/v1/reports`. This panel shows what was filed to Linear, what the relay deduped, and which platform/team bucket handled it.</div>
        </div>
        <div class="summary-meta">{_report_gateway_badge()} | {report_count_24h:,} events</div>
      </div>
      <div class="table-shell">
        <table>
          <thead><tr><th>Type / origin</th><th>Team</th><th>Status</th><th>Events</th><th>Installs</th><th>Last seen</th></tr></thead>
          <tbody>{rows_for_report_breakdown()}</tbody>
        </table>
      </div>
    </section>
    <section class="section">
      <div class="section-head">
        <div>
          <h2>Recent report events</h2>
          <div class="section-copy">A compact tail of the report gateway. Fingerprints and network tags stay anonymized; payload text is not stored here.</div>
        </div>
        <div class="summary-meta">Last {len(recent_reports):,} events</div>
      </div>
      <div class="table-shell">
        <table>
          <thead><tr><th>Time</th><th>Install</th><th>Type</th><th>Context</th><th>Team</th><th>Status</th><th>Wire id</th></tr></thead>
          <tbody>{rows_for_recent_reports()}</tbody>
        </table>
      </div>
    </section>
  </div>

  <div class="split" id="schedules">
    <section class="section">
      <div class="section-head">
        <div>
          <h2>Shared snapshot pool</h2>
          <div class="section-copy">Every row below is one cached airport + timezone + board-window intent. If many installs watch the same lane, they should pile into one of these rows instead of generating duplicate AviationStack traffic.</div>
        </div>
        <div class="summary-meta">{snapshot_pool_count:,} cached windows</div>
      </div>
      <div class="table-shell">
        <table>
          <thead><tr><th>Airport window</th><th>Coverage</th><th>Shared use</th><th>State</th><th>Updated</th></tr></thead>
          <tbody>{rows_for_snapshot_pool()}</tbody>
        </table>
      </div>
    </section>
    <section class="section">
      <div class="section-head">
        <div>
          <h2>Live airport lanes (24h)</h2>
          <div class="section-copy">This is the clean operator view of what clients are actually watching right now. It groups installs by airport lane, shows the cadence they requested, and tells you whether the shared schedule row behind that lane is fresh or drifting.</div>
        </div>
        <div class="summary-meta">{active_lane_count:,} grouped lanes</div>
      </div>
      <div class="table-shell">
        <table>
          <thead><tr><th>Airport</th><th>Watching installs</th><th>Window + cadence</th><th>Snapshot</th><th>Activity</th></tr></thead>
          <tbody>{rows_for_live_lanes()}</tbody>
        </table>
      </div>
    </section>
  </div>

  <details class="section" id="activations"{activation_open}>
    <summary>
      <span>Activation queue</span>
      <span class="summary-meta">{pending_requests:,} pending review | {len(activation_requests):,} total rows</span>
    </summary>
    <div class="section-tools">Use this queue for manual review fallbacks, instant issue, dismissals, and clearing historic activation rows once they are no longer useful.</div>
    <div class="table-shell">
      <table>
        <thead><tr><th>Install</th><th>Network tag</th><th>Request</th><th>Status</th><th>Decision note</th><th>Created</th><th>Actions</th></tr></thead>
        <tbody>{rows_for_activation_requests()}</tbody>
      </table>
    </div>
  </details>

  <details class="section" id="tokens">
    <summary>
      <span>Managed tokens</span>
      <span class="summary-meta">{len(tokens):,} tracked tokens</span>
    </summary>
    <div class="section-tools">Managed tokens are the exception lane. The meters below show this month's relay-facing schedule and radar usage against the limits stored on each token.</div>
    <div class="table-shell">
      <table>
        <thead><tr><th>Token</th><th>Label</th><th>Schedule</th><th>Radar</th><th>Binding</th><th>Status</th><th>Actions</th></tr></thead>
        <tbody>{rows_for_tokens()}</tbody>
      </table>
    </div>
  </details>

  <details class="section" id="fleet">
    <summary>
      <span>Fleet registry</span>
      <span class="summary-meta">{fleet_metrics.get('active_installs_24h', 0):,} active | {len(installs):,} known installs</span>
    </summary>
    <div class="section-tools">Sortable launch-support view by install date, OS, GUI shell, companion/matrix presence, airport lane, usage, and access status. Raw install IDs stay hidden; actions use opaque references.</div>
    <div class="table-shell">
      <table>
        <thead><tr><th>Install</th><th>OS / GUI / Version</th><th>Current lane</th><th>Plan</th><th>Companion</th><th>Matrix</th><th>Schedule</th><th>Radar</th><th>Status</th><th>Actions</th></tr></thead>
        <tbody>{rows_for_installs()}</tbody>
      </table>
    </div>
  </details>

  <details class="section" id="report-dedupe">
    <summary>
      <span>Report dedupe groups</span>
      <span class="summary-meta">{len(report_dedupe_rows):,} recent groups</span>
    </summary>
    <div class="section-tools">These rows explain why repeat crashes or repeated manual reports may not open a new Linear issue every time.</div>
    <div class="table-shell">
      <table>
        <thead><tr><th>Type / origin</th><th>Team</th><th>Install</th><th>Count</th><th>Last seen</th><th>Linear URL</th></tr></thead>
        <tbody>{rows_for_report_dedupe()}</tbody>
      </table>
    </div>
  </details>

  <details class="section" id="recent-requests">
    <summary>
      <span>Recent relay requests</span>
      <span class="summary-meta">Last {len(recent):,} request log rows</span>
    </summary>
    <div class="section-tools">This is the rawer transport tail for the relay. It is useful when you want to eyeball status codes, shared schedule scope, or latency spikes without dropping into logs.</div>
    <div class="table-shell">
      <table>
        <thead><tr><th>Time</th><th>Install</th><th>Service</th><th>Scope</th><th>Status</th><th>Latency</th><th>Wire id</th></tr></thead>
        <tbody>{rows_for_recent()}</tbody>
      </table>
    </div>
  </details>
</div>
<script>
(function () {{
  var navLinks = Array.prototype.slice.call(document.querySelectorAll(".admin-nav a"));
  navLinks.forEach(function (link) {{
    link.addEventListener("click", function () {{
      var target = document.querySelector(link.getAttribute("href"));
      if (target && target.tagName === "DETAILS") {{
        target.open = true;
      }}
    }});
  }});

  if ("IntersectionObserver" in window) {{
    var sections = navLinks
      .map(function (link) {{ return document.querySelector(link.getAttribute("href")); }})
      .filter(Boolean);
    var observer = new IntersectionObserver(function (entries) {{
      entries.forEach(function (entry) {{
        if (!entry.isIntersecting) {{
          return;
        }}
        navLinks.forEach(function (link) {{
          link.classList.toggle("active", link.getAttribute("href") === "#" + entry.target.id);
        }});
      }});
    }}, {{ rootMargin: "-35% 0px -55% 0px", threshold: 0.01 }});
    sections.forEach(function (section) {{ observer.observe(section); }});
  }}

  function cellValue(row, index) {{
    var cell = row.children[index];
    return cell ? cell.textContent.trim() : "";
  }}

  function sortableValue(text) {{
    var normalized = text.replace(/,/g, "").trim();
    var match = normalized.match(/-?\\d+(\\.\\d+)?/);
    if (match && normalized.length < 48) {{
      return Number(match[0]);
    }}
    return text.toLowerCase();
  }}

  document.querySelectorAll("table").forEach(function (table, tableIndex) {{
    var body = table.tBodies[0];
    if (!body) {{
      return;
    }}
    var rows = Array.prototype.slice.call(body.rows);
    var shell = table.closest(".table-shell");
    if (shell && !shell.previousElementSibling?.classList.contains("table-filter")) {{
      var filter = document.createElement("div");
      filter.className = "table-filter";
      filter.innerHTML = '<input type="search" placeholder="Filter this table" aria-label="Filter table"><span class="tiny"></span>';
      shell.parentNode.insertBefore(filter, shell);
      var input = filter.querySelector("input");
      var count = filter.querySelector(".tiny");
      var updateFilter = function () {{
        var term = input.value.trim().toLowerCase();
        var visible = 0;
        rows.forEach(function (row) {{
          var show = !term || row.textContent.toLowerCase().indexOf(term) !== -1;
          row.hidden = !show;
          if (show) {{
            visible += 1;
          }}
        }});
        count.textContent = visible + " / " + rows.length + " rows";
      }};
      input.addEventListener("input", updateFilter);
      updateFilter();
    }}

    Array.prototype.slice.call(table.tHead ? table.tHead.rows[0].cells : []).forEach(function (header, index) {{
      if (header.textContent.trim().toLowerCase() === "actions") {{
        return;
      }}
      header.dataset.sortable = "1";
      header.addEventListener("click", function () {{
        var descending = !header.classList.contains("sort-desc");
        Array.prototype.slice.call(header.parentNode.cells).forEach(function (cell) {{
          cell.classList.remove("sort-asc", "sort-desc");
        }});
        header.classList.add(descending ? "sort-desc" : "sort-asc");
        rows.sort(function (a, b) {{
          var aValue = sortableValue(cellValue(a, index));
          var bValue = sortableValue(cellValue(b, index));
          if (aValue < bValue) {{
            return descending ? 1 : -1;
          }}
          if (aValue > bValue) {{
            return descending ? -1 : 1;
          }}
          return 0;
        }});
        rows.forEach(function (row) {{ body.appendChild(row); }});
      }});
    }});
  }});
}})();
</script>
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
    timezone: str = ""
    device_type: str = "unknown"
    display_name: str = ""
    requested_mode: str = "community"
    app_version: str = ""


class ClientStatusIn(BaseModel):
    install_id: str
    activation_token: str = ""
    app_version: str = ""
    client_kind: str = Field("desktop", max_length=32)
    device_type: str = Field("unknown", max_length=24)
    airport_iata: str = ""
    airport_icao: str = ""
    timezone: str = ""
    display_grace_minutes: int = 30
    display_horizon_hours: int = 12
    refresh_seconds: int = 3600
    os_family: str = Field("", max_length=40)
    os_version: str = Field("", max_length=80)
    arch: str = Field("", max_length=40)
    requested_gui: str = Field("", max_length=24)
    effective_gui: str = Field("", max_length=24)
    source_mode: str = Field("", max_length=32)
    diagnostics_mode: str = Field("", max_length=32)
    companion_count: int = Field(0, ge=0, le=100_000)
    matrix_count: int = Field(0, ge=0, le=100_000)
    matrix_online_count: int = Field(0, ge=0, le=100_000)

    @field_validator(
        "activation_token",
        "app_version",
        "client_kind",
        "device_type",
        "airport_iata",
        "airport_icao",
        "timezone",
        "os_family",
        "os_version",
        "arch",
        "requested_gui",
        "effective_gui",
        "source_mode",
        "diagnostics_mode",
        mode="before",
    )
    @classmethod
    def _coerce_optional_text(cls, value: Any) -> str:
        return _admin_text(value)


class HeartbeatIn(BaseModel):
    install_id: str
    app_version: str = Field("", max_length=40)
    client_kind: str = Field("desktop", max_length=32)
    device_type: str = Field("unknown", max_length=24)
    airport_iata: str = Field("", max_length=4)
    airport_icao: str = Field("", max_length=4)
    timezone: str = Field("", max_length=64)
    os_family: str = Field("", max_length=40)
    os_version: str = Field("", max_length=80)
    arch: str = Field("", max_length=40)
    requested_gui: str = Field("", max_length=24)
    effective_gui: str = Field("", max_length=24)
    source_mode: str = Field("", max_length=32)
    diagnostics_mode: str = Field("", max_length=32)
    companion_count: int = Field(0, ge=0, le=100_000)
    matrix_count: int = Field(0, ge=0, le=100_000)
    matrix_online_count: int = Field(0, ge=0, le=100_000)

    @field_validator(
        "app_version", "client_kind", "device_type", "airport_iata", "airport_icao", "timezone",
        "os_family", "os_version", "arch",
        "requested_gui", "effective_gui", "source_mode", "diagnostics_mode",
        mode="before",
    )
    @classmethod
    def _coerce_optional_text(cls, value: Any) -> str:
        return _admin_text(value)


class ReportIn(BaseModel):
    report_type: str = Field(..., min_length=1, max_length=20)
    origin: str = Field("", max_length=20)
    install_id: str = Field(..., min_length=1, max_length=80)
    install_fingerprint: str = Field(..., min_length=1, max_length=80)
    activation_token: str = Field("", max_length=160)
    title: str = Field("", max_length=200)
    description: str = Field("", max_length=4000)
    message: str = Field("", max_length=500)
    traceback: str = Field("", max_length=5000)
    context: str = Field("", max_length=120)
    client_context: str = Field("", max_length=2000)
    app_version: str = Field("", max_length=80)
    platform: str = Field("", max_length=160)
    os: str = Field("", max_length=160)
    arch: str = Field("", max_length=80)
    python_version: str = Field("", max_length=80)
    airport: str = Field("", max_length=12)
    source: str = Field("", max_length=40)
    api_mode: str = Field("", max_length=40)
    diagnostics_mode: str = Field("", max_length=40)


class MobileAppleIapVerifyIn(BaseModel):
    install_id: str = Field(..., min_length=1, max_length=80)
    app_account_token: str = Field(..., min_length=1, max_length=80)
    app_version: str = Field("", max_length=80)
    product_id: str = Field(..., min_length=1, max_length=160)
    transaction_id: str = Field(..., min_length=1, max_length=160)
    original_transaction_id: str = Field("", max_length=160)
    signed_transaction_info: str = Field("", max_length=20000)
    signed_renewal_info: str = Field("", max_length=20000)
    environment: str = Field("unknown", max_length=24)

    @field_validator(
        "install_id",
        "app_account_token",
        "app_version",
        "product_id",
        "transaction_id",
        "original_transaction_id",
        "signed_transaction_info",
        "signed_renewal_info",
        "environment",
        mode="before",
    )
    @classmethod
    def _coerce_optional_text(cls, value: Any) -> str:
        return _admin_text(value).strip()


def _admin_text(value: Any) -> str:
    return "" if value is None else str(value)


class AdminProviderKeysIn(BaseModel):
    aerodatabox_key: str = Field("", max_length=240)
    aviationstack_key: str = Field("", max_length=240)
    rapidapi_key: str = Field("", max_length=240)

    @field_validator("aerodatabox_key", "aviationstack_key", "rapidapi_key", mode="before")
    @classmethod
    def _coerce_optional_text(cls, value: Any) -> str:
        return _admin_text(value)


class AdminProviderClearIn(BaseModel):
    provider: str = Field(..., min_length=1, max_length=40)

    @field_validator("provider", mode="before")
    @classmethod
    def _coerce_required_text(cls, value: Any) -> str:
        return _admin_text(value)


class AdminActivationCreateIn(BaseModel):
    label: str = Field("", max_length=160)
    schedule_limit: int = Field(10000, ge=1, le=1_000_000)
    radar_limit: int = Field(10000, ge=1, le=1_000_000)

    @field_validator("label", mode="before")
    @classmethod
    def _coerce_optional_text(cls, value: Any) -> str:
        return _admin_text(value)


class AdminTokenActionIn(BaseModel):
    token_prefix: str = Field("", max_length=32)
    token_ref: str = Field("", max_length=120)
    action: str = Field(..., min_length=1, max_length=40)

    @field_validator("token_prefix", "token_ref", "action", mode="before")
    @classmethod
    def _coerce_required_text(cls, value: Any) -> str:
        return _admin_text(value)


class AdminActivationRequestActionIn(BaseModel):
    request_id: str = Field(..., min_length=4, max_length=80)
    action: str = Field(..., min_length=1, max_length=40)
    decision_note: str = Field("dismissed", max_length=240)

    @field_validator("request_id", "action", "decision_note", mode="before")
    @classmethod
    def _coerce_text(cls, value: Any) -> str:
        return _admin_text(value)


class AdminCounterResetIn(BaseModel):
    scope: str = Field(..., min_length=1, max_length=40)
    service: str = Field("", max_length=40)
    token_prefix: str = Field("", max_length=32)
    token_ref: str = Field("", max_length=120)
    install_fingerprint: str = Field("", max_length=32)
    install_ref: str = Field("", max_length=120)

    @field_validator("scope", "service", "token_prefix", "token_ref", "install_fingerprint", "install_ref", mode="before")
    @classmethod
    def _coerce_text(cls, value: Any) -> str:
        return _admin_text(value)


class AdminCounterCorrectIn(BaseModel):
    total: int = Field(..., ge=0, le=100_000_000)


class AdminInstallAccessIn(BaseModel):
    install_id: str = Field("", max_length=80)
    install_fingerprint: str = Field("", max_length=32)
    install_ref: str = Field("", max_length=120)
    action: str = Field(..., min_length=1, max_length=40)
    reason: str = Field("revoked by admin", max_length=240)

    @field_validator("install_id", "install_fingerprint", "install_ref", "action", "reason", mode="before")
    @classmethod
    def _coerce_text(cls, value: Any) -> str:
        return _admin_text(value)


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
    known_install_row = _activation_row_for_install(conn, install_id)
    known_install = activation_row is not None or known_install_row is not None
    if not token_prefix and known_install_row is not None:
        token_prefix = str(known_install_row["token_prefix"] or "")
    aerodatabox_key, _ = _provider_status(_SETTING_AERODATABOX_KEY, "AERODATABOX_API_KEY", conn=conn)
    aviationstack_key, _ = _provider_status(_SETTING_AVIATIONSTACK_KEY, "AVIATIONSTACK_API_KEY", conn=conn)
    rapidapi_key, _ = _provider_status(_SETTING_RAPIDAPI_KEY, "RAPIDAPI_KEY", conn=conn)
    revision = _provider_revision(conn)
    interest = _client_interest_snapshot(conn, install_id)
    shared_schedule_budget = _shared_schedule_budget_payload(conn)
    conn.close()
    schedule_access_budget = _schedule_access_budget_payload(
        install_id=install_id,
        activation_row=activation_row,
        limit=schedule_limit,
        plan=plan,
    )

    return {
        "ok": True,
        "plan": plan,
        "relay_ok": True,
        "provider_revision": revision,
        "install_fingerprint": _install_fingerprint(install_id),
        "known_install": known_install,
        "can_reissue": known_install,
        "token_prefix": token_prefix,
        "label": label,
        "app_version": (app_version or "").strip(),
        "providers": {
            "aerodatabox": bool(aerodatabox_key),
            "aviationstack": bool(aviationstack_key),
            "adsbexchange": bool(rapidapi_key),
        },
        "limits": {
            "schedule": schedule_limit,
            "radar": radar_limit,
        },
        "interest": interest or {},
        "schedule_cache": (interest or {}).get("schedule_cache") or {},
        "shared_schedule_budget": shared_schedule_budget,
        "schedule_access_budget": schedule_access_budget,
    }


def _localflight_version_label() -> str:
    try:
        from importlib.metadata import version

        return version("localflight")
    except Exception:
        return "0.2.6"


def _airport_result_payload(rec: Any, *, include_coords: bool = False) -> Dict[str, Any]:
    try:
        from localflight.core.airports import get_airport_timezone
    except Exception:
        get_airport_timezone = None

    timezone_name = "UTC"
    if get_airport_timezone is not None:
        timezone_name = get_airport_timezone(str(getattr(rec, "country", "") or ""), str(getattr(rec, "region", "") or ""))
    payload = {
        "iata": str(getattr(rec, "iata", "") or "").upper(),
        "icao": str(getattr(rec, "icao", "") or "").upper(),
        "name": str(getattr(rec, "name", "") or ""),
        "city": str(getattr(rec, "city", "") or ""),
        "country": str(getattr(rec, "country", "") or ""),
        "type": str(getattr(rec, "type", "") or ""),
        "timezone": _normalize_timezone_name(timezone_name),
    }
    if include_coords:
        payload["lat"] = getattr(rec, "lat", None)
        payload["lon"] = getattr(rec, "lon", None)
    return payload


def _airport_record_payload(raw: Dict[str, Any], *, include_coords: bool = False) -> Dict[str, Any]:
    try:
        from localflight.core.airports import get_airport_timezone
    except Exception:
        get_airport_timezone = None

    timezone_name = "UTC"
    if get_airport_timezone is not None:
        timezone_name = get_airport_timezone(str(raw.get("country") or ""), str(raw.get("region") or ""))
    payload = {
        "iata": str(raw.get("iata") or "").upper(),
        "icao": str(raw.get("icao") or "").upper(),
        "name": str(raw.get("name") or ""),
        "city": str(raw.get("city") or ""),
        "country": str(raw.get("country") or ""),
        "type": str(raw.get("type") or ""),
        "timezone": _normalize_timezone_name(timezone_name),
    }
    if include_coords:
        payload["lat"] = raw.get("lat") if isinstance(raw.get("lat"), (int, float)) else None
        payload["lon"] = raw.get("lon") if isinstance(raw.get("lon"), (int, float)) else None
    return payload


def _airport_search_score(rec: Dict[str, Any], query: str) -> int:
    q = query.upper()
    iata = str(rec.get("iata") or "").upper()
    icao = str(rec.get("icao") or "").upper()
    city = str(rec.get("city") or "").upper()
    name = str(rec.get("name") or "").upper()
    atype = str(rec.get("type") or "")
    if q == iata or q == icao:
        return 100
    if iata.startswith(q) or icao.startswith(q):
        return 80
    if q == city:
        return 70
    if city.startswith(q):
        return 60 if atype == "large_airport" else 50
    if q in name:
        return 40 if atype == "large_airport" else 30
    if q in city:
        return 20
    return 0


def _lookup_relay_airport(query: str) -> Any:
    clean = _clean_airport(query)
    try:
        from localflight.core.airports import lookup_airport
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Airport index unavailable: {exc}") from exc
    rec = lookup_airport(iata=clean if clean and len(clean) == 3 else None, icao=clean if clean and len(clean) == 4 else None)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Airport not found: {query}")
    return rec


def _require_mobile_standalone_access(
    *,
    install_id: str,
    activation_token: str,
    app_version: str,
    client_kind: str,
    service: str,
    device_type: str = "",
    airport_iata: str = "",
    airport_icao: str = "",
    timezone_name: str = "",
    diagnostics_mode: str = "",
) -> Dict[str, Any]:
    install_id = _validate_install_id(install_id)
    if _clean_client_kind(client_kind) != "mobile_standalone":
        raise HTTPException(status_code=403, detail="client_kind=mobile_standalone is required")
    if not (app_version or "").strip():
        raise HTTPException(status_code=422, detail="app_version is required for mobile standalone clients")
    token = (activation_token or "").strip()
    if not token:
        raise HTTPException(status_code=403, detail="Standalone mobile activation_token is required")
    access = _resolve_access(install_id=install_id, activation_token=token, service=service)
    if access.get("activation_row") is None:
        raise HTTPException(status_code=403, detail="Standalone mobile activation token required")
    _record_install_profile(
        install_id=install_id,
        presence_event="relay_activity",
        client_kind="mobile_standalone",
        device_type=device_type,
        airport_iata=airport_iata,
        airport_icao=airport_icao,
        timezone_name=timezone_name,
        app_version=app_version,
        requested_gui="mobile_standalone",
        effective_gui="mobile",
        source_mode="real",
        diagnostics_mode=diagnostics_mode,
    )
    return access


def _standalone_config_payload(airport: Dict[str, Any], *, diagnostics_mode: str = "manual") -> Dict[str, Any]:
    iata = str(airport.get("iata") or "").upper()
    icao = str(airport.get("icao") or "").upper()
    return {
        "airport_iata": iata,
        "airport_icao": icao,
        "refresh_seconds": _standalone_schedule_min_refresh_seconds(),
        "display_name": f"{iata or icao or 'Mobile'} Standalone",
        "theme": "dark",
        "source": "real",
        "timezone": str(airport.get("timezone") or "UTC"),
        "skin": "technical",
        "display_outputs": ["mobile"],
        "diagnostics_mode": diagnostics_mode or "manual",
        "web_row_limit": 30,
        "web_rotation_seconds": 8,
        "display_grace_minutes": 30,
        "display_horizon_hours": 12,
        "radar_surface_enabled": False,
    }


def _response_json_payload(response: Response) -> Dict[str, Any]:
    body = getattr(response, "body", b"")
    if isinstance(body, str):
        raw = body
    else:
        raw = bytes(body or b"").decode("utf-8")
    try:
        payload = json.loads(raw)
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _parse_iso_utc(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _mobile_fids_rows_from_schedule_payload(
    payload: Dict[str, Any],
    *,
    airport: Dict[str, Any],
    view: str,
    limit: int,
) -> list[Dict[str, Any]]:
    from localflight.decode.normalize import normalize_flights
    from localflight.render.fids import build_fids_context
    from localflight.storage.config import AppConfig
    from localflight.core.models import FlightDirection

    records = payload.get("records") if isinstance(payload.get("records"), list) else []
    flights = normalize_flights(
        records,
        airport_iata=str(airport.get("iata") or ""),
        airport_icao=str(airport.get("icao") or ""),
        source_name=str(payload.get("provider") or "relay"),
    )
    direction = FlightDirection.DEPARTURE if view == "departures" else FlightDirection.ARRIVAL
    filtered = [flight for flight in flights if flight.direction == direction]
    cfg = AppConfig(**_standalone_config_payload(airport))
    ctx = build_fids_context(
        cfg=cfg,
        view=view,
        refresh_seconds=_standalone_schedule_min_refresh_seconds(),
        flights=filtered,
        last_refreshed=_parse_iso_utc(payload.get("generated_at")),
        source_status=str(payload.get("provider") or "relay"),
    )
    return [asdict(row) for row in list(ctx.get("rows") or [])[:limit]]


def _mobile_cache_load(
    *,
    install_id: str,
    service: str,
    cache_key: str,
    max_age_seconds: int,
) -> Optional[Dict[str, Any]]:
    conn = _connect()
    row = conn.execute(
        """
        SELECT last_seen, payload_json
        FROM mobile_standalone_cache
        WHERE install_id=? AND service=? AND cache_key=?
        """,
        (install_id, service, cache_key),
    ).fetchone()
    conn.close()
    if not row:
        return None
    last_seen = _parse_utc_dt(str(row["last_seen"] or ""))
    if not last_seen or (datetime.now(timezone.utc) - last_seen).total_seconds() > max_age_seconds:
        return None
    payload = _load_json_blob(row["payload_json"], {})
    return payload if isinstance(payload, dict) else None


def _mobile_cache_store(*, install_id: str, service: str, cache_key: str, payload: Dict[str, Any]) -> None:
    conn = _connect()
    conn.execute(
        """
        INSERT INTO mobile_standalone_cache (install_id, service, cache_key, last_seen, payload_json)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(install_id, service, cache_key) DO UPDATE SET
            last_seen=excluded.last_seen,
            payload_json=excluded.payload_json
        """,
        (install_id, service, cache_key, _utc_now(), json.dumps(payload, ensure_ascii=False)),
    )
    conn.execute("DELETE FROM mobile_standalone_cache WHERE last_seen < ?", (_hours_ago(24),))
    conn.commit()
    conn.close()


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
    standalone_activation = requested_mode == "mobile_standalone"
    airport_iata = _clean_airport(body.airport_iata) or ""
    airport_icao = _clean_airport(body.airport_icao) or ""
    schedule_limit, radar_limit = _activation_limits_for_requested_mode(requested_mode)

    blocked_reason = _blocked_reason(install_id)
    if blocked_reason:
        raise HTTPException(status_code=403, detail=f"Install access revoked: {blocked_reason}")

    conn = _connect()
    known_install = _activation_row_for_install(conn, install_id) is not None
    counts = _recent_activation_counts(conn, install_id=install_id, network_tag=network_tag)
    manual_review = counts["network_requests"] >= _auto_activation_network_daily_limit() or counts[
        "network_installs"
    ] >= _auto_activation_network_installs_daily_limit()
    event_network_tag = "" if known_install else network_tag

    if manual_review and not known_install:
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
                "known_install": False,
                "can_reissue": False,
                "token_prefix": "",
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
            airport_iata=airport_iata,
            airport_icao=airport_icao,
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
            "known_install": False,
            "can_reissue": False,
            "token_prefix": "",
            "decision_note": "Relay paused automatic activation for this install and queued a manual review.",
        }

    token, token_prefix, issuance = _issue_token_for_install(
        conn,
        install_id=install_id,
        label=display_name or f"Local Flight {expected_fingerprint}",
        created_by="auto-issue",
        schedule_limit=schedule_limit,
        radar_limit=radar_limit,
    )
    response_note = (
        "Relay access reissued for this existing installation after setup reset."
        if known_install
        else "Relay access issued instantly for this installation."
    )
    pending_request = None
    if manual_review and known_install:
        pending_request = conn.execute(
            """
            SELECT request_id
            FROM activation_requests
            WHERE install_id=? AND status=?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (install_id, _REQUEST_STATUS_MANUAL_REVIEW),
        ).fetchone()
        response_note = "Relay access reissued for this existing installation after setup reset."

    if pending_request:
        request_id = str(pending_request["request_id"] or "")
        now = _utc_now()
        conn.execute(
            """
            UPDATE activation_requests
            SET status=?,
                updated_at=?,
                approved_at=?,
                last_seen=?,
                network_tag=?,
                airport_iata=?,
                airport_icao=?,
                display_name=?,
                requested_mode=?,
                app_version=?,
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
                event_network_tag,
                airport_iata or None,
                airport_icao or None,
                display_name or f"Local Flight {expected_fingerprint}",
                requested_mode,
                app_version,
                "auto-existing-install",
                "existing install reissued after setup reset",
                _token_hash(token),
                token_prefix,
                request_id,
            ),
        )
    else:
        request_id = _record_activation_event(
            conn,
            install_id=install_id,
            install_fingerprint=install_fingerprint,
            network_tag=event_network_tag,
            display_name=display_name or f"Local Flight {expected_fingerprint}",
            requested_mode=requested_mode,
            app_version=app_version,
            airport_iata=airport_iata,
            airport_icao=airport_icao,
            status=_REQUEST_STATUS_ISSUED,
            decision_source="auto-existing-install" if known_install else "auto",
            decision_note="existing install reissued after setup reset" if known_install else issuance,
            token_hash=_token_hash(token),
            token_prefix=token_prefix,
        )
    conn.commit()
    conn.close()
    status = _build_client_status(install_id=install_id, activation_token=token, app_version=app_version)
    if standalone_activation:
        _record_install_profile(
            install_id=install_id,
            presence_event="relay_activity",
            client_kind="mobile_standalone",
            device_type=body.device_type or "phone",
            airport_iata=airport_iata,
            airport_icao=airport_icao,
            timezone_name=body.timezone,
            app_version=app_version,
            requested_gui=requested_mode,
            effective_gui="mobile",
            source_mode="real",
        )
    status.update(
        {
            "request_id": request_id,
            "status": _REQUEST_STATUS_ISSUED,
            "known_install": known_install,
            "can_reissue": True,
            "activation_token": token,
            "decision_note": response_note,
        }
    )
    return status


@app.get("/v1/client/status")
def relay_client_status(
    install_id: str = Query(...),
    activation_token: str = Query(""),
    app_version: str = Query(""),
    client_kind: str = Query("desktop"),
    device_type: str = Query("unknown"),
    airport_iata: str = Query(""),
    airport_icao: str = Query(""),
    timezone: str = Query(""),
    os_family: str = Query(""),
    os_version: str = Query(""),
    arch: str = Query(""),
    requested_gui: str = Query(""),
    effective_gui: str = Query(""),
    source_mode: str = Query(""),
    diagnostics_mode: str = Query(""),
    companion_count: int = Query(0, ge=0, le=100_000),
    matrix_count: int = Query(0, ge=0, le=100_000),
    matrix_online_count: int = Query(0, ge=0, le=100_000),
) -> Dict[str, Any]:
    install_id = _validate_install_id(install_id)
    status_payload = _build_client_status(
        install_id=install_id,
        activation_token=(activation_token or "").strip(),
        app_version=app_version,
    )
    _record_install_profile(
        install_id=install_id,
        presence_event="relay_activity",
        client_kind=client_kind,
        device_type=device_type,
        airport_iata=airport_iata,
        airport_icao=airport_icao,
        timezone_name=timezone,
        app_version=app_version,
        os_family=os_family,
        os_version=os_version,
        arch=arch,
        requested_gui=requested_gui,
        effective_gui=effective_gui,
        source_mode=source_mode,
        diagnostics_mode=diagnostics_mode,
        companion_count=companion_count,
        matrix_count=matrix_count,
        matrix_online_count=matrix_online_count,
    )
    return status_payload


@app.post("/v1/client/checkin")
def relay_client_checkin(body: ClientStatusIn) -> Dict[str, Any]:
    install_id = _validate_install_id(body.install_id)
    status = _build_client_status(
        install_id=install_id,
        activation_token=(body.activation_token or "").strip(),
        app_version=body.app_version,
    )
    _record_install_profile(
        install_id=install_id,
        presence_event="checkin",
        client_kind=body.client_kind,
        device_type=body.device_type,
        airport_iata=body.airport_iata,
        airport_icao=body.airport_icao,
        timezone_name=body.timezone,
        app_version=body.app_version,
        os_family=body.os_family,
        os_version=body.os_version,
        arch=body.arch,
        requested_gui=body.requested_gui,
        effective_gui=body.effective_gui,
        source_mode=body.source_mode,
        diagnostics_mode=body.diagnostics_mode,
        companion_count=body.companion_count,
        matrix_count=body.matrix_count,
        matrix_online_count=body.matrix_online_count,
    )
    airport_iata = _clean_airport(body.airport_iata) if (body.airport_iata or "").strip() else None
    timezone_name = (body.timezone or "").strip()
    if airport_iata and timezone_name:
        _record_client_interest(
            install_id=install_id,
            plan=str(status.get("plan") or "community"),
            client_kind=body.client_kind,
            airport_iata=airport_iata,
            airport_icao=body.airport_icao,
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


@app.post("/v1/heartbeat")
def relay_heartbeat(body: HeartbeatIn) -> Dict[str, Any]:
    install_id = _validate_install_id(body.install_id)
    if not _check_heartbeat_rate_limit(install_id):
        raise HTTPException(status_code=429, detail="Heartbeat cooldown: minimum 5 minutes between beats")
    _record_install_profile(
        install_id=install_id,
        presence_event="heartbeat",
        client_kind=body.client_kind,
        device_type=body.device_type,
        airport_iata=body.airport_iata,
        airport_icao=body.airport_icao,
        timezone_name=body.timezone,
        app_version=body.app_version,
        os_family=body.os_family,
        os_version=body.os_version,
        arch=body.arch,
        requested_gui=body.requested_gui,
        effective_gui=body.effective_gui,
        source_mode=body.source_mode,
        diagnostics_mode=body.diagnostics_mode,
        companion_count=body.companion_count,
        matrix_count=body.matrix_count,
        matrix_online_count=body.matrix_online_count,
    )
    return {"ok": True}


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


@app.get("/v1/airports/search")
def relay_airports_search(
    q: str = Query(..., min_length=2, max_length=20),
    limit: int = Query(8, ge=1, le=20),
    all_types: bool = Query(False),
) -> list[Dict[str, Any]]:
    try:
        from localflight.core.airports import _load_index
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Airport index unavailable: {exc}") from exc

    query = q.strip().upper()
    if not query:
        return []
    search_types = {"large_airport", "medium_airport"}
    index = _load_index()
    seen: set[str] = set()
    candidates: list[tuple[int, Dict[str, Any]]] = []
    for raw in list((index.get("by_iata") or {}).values()) + list((index.get("by_icao") or {}).values()):
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("icao") or raw.get("iata") or "").upper()
        if not key or key in seen:
            continue
        seen.add(key)
        airport_type = str(raw.get("type") or "")
        if not all_types and airport_type not in search_types:
            continue
        score = _airport_search_score(raw, query)
        if score > 0:
            candidates.append((score, raw))
    candidates.sort(key=lambda item: (-item[0], 0 if item[1].get("type") == "large_airport" else 1, item[1].get("name") or ""))
    return [_airport_record_payload(raw) for _score, raw in candidates[:limit]]


@app.get("/v1/airports/resolve")
def relay_airports_resolve(q: str = Query(..., min_length=2, max_length=10)) -> Dict[str, Any]:
    return _airport_result_payload(_lookup_relay_airport(q), include_coords=True)


@app.get("/v1/mobile/summary")
def relay_mobile_summary(
    install_id: str = Query(...),
    activation_token: str = Query(...),
    app_version: str = Query(...),
    client_kind: str = Query(...),
    airport_iata: str = Query(...),
    airport_icao: str = Query(""),
    timezone: str = Query(""),
    diagnostics_mode: str = Query("manual"),
    device_type: str = Query("phone"),
) -> Dict[str, Any]:
    airport = _airport_result_payload(_lookup_relay_airport(airport_iata or airport_icao), include_coords=True)
    timezone_name = _normalize_timezone_name(timezone or str(airport.get("timezone") or "UTC"))
    airport["timezone"] = timezone_name
    _require_mobile_standalone_access(
        install_id=install_id,
        activation_token=activation_token,
        app_version=app_version,
        client_kind=client_kind,
        service="aviationstack",
        device_type=device_type,
        airport_iata=str(airport.get("iata") or ""),
        airport_icao=str(airport.get("icao") or ""),
        timezone_name=timezone_name,
        diagnostics_mode=diagnostics_mode,
    )
    status = _build_client_status(install_id=_validate_install_id(install_id), activation_token=activation_token, app_version=app_version)
    metar: Optional[Dict[str, Any]] = None
    if airport.get("icao"):
        try:
            from localflight.sources.web.metar_client import fetch_metar

            metar = fetch_metar(str(airport.get("icao") or ""))
        except Exception:
            metar = None
    return {
        "config": _standalone_config_payload(airport, diagnostics_mode=diagnostics_mode),
        "state": {
            "ok": True,
            "source_name": "relay_standalone",
            "last_success_utc": _utc_now(),
            "last_error": None,
        },
        "system": {
            "version": _localflight_version_label(),
            "python": "relay",
            "platform": "Local Flight hosted relay",
            "client": {
                "mode": "mobile_standalone",
                "managed_status": status.get("plan"),
                "activation_token_prefix": status.get("token_prefix"),
                "shared_snapshot": status.get("schedule_cache") or {},
            },
        },
        "connections": {"count": 0, "companion_count": 0, "companions": []},
        "updates": None,
        "budget": {
            "schedule_policy": {
                "shared_relay": True,
                "active_mode": "standalone",
                "min_refresh_seconds": _standalone_schedule_min_refresh_seconds(),
            },
            "shared_schedule_budget": status.get("shared_schedule_budget") or {},
            "schedule_access_budget": status.get("schedule_access_budget") or {},
            "aviationstack": {
                "mode": "relay",
                "active_mode": "standalone",
                "monthly_limit": (status.get("limits") or {}).get("schedule"),
                "shared_schedule_budget": status.get("shared_schedule_budget") or {},
                "schedule_access_budget": status.get("schedule_access_budget") or {},
            },
            "adsbexchange": {
                "available": bool((status.get("providers") or {}).get("adsbexchange")),
                "monthly_limit": (status.get("limits") or {}).get("radar"),
            },
        },
        "scheduler": None,
        "metar": metar,
    }


@app.post("/v1/mobile/iap/apple/verify")
def relay_mobile_iap_apple_verify(body: MobileAppleIapVerifyIn) -> Dict[str, Any]:
    if body.product_id not in _APPLE_IAP_SUPPORT_PRODUCT_IDS:
        raise HTTPException(status_code=400, detail="Unknown Apple in-app purchase product.")
    _validate_install_id(body.install_id)
    if body.app_account_token and _UUID_RE.match(body.app_account_token) is None:
        raise HTTPException(status_code=400, detail="Invalid Apple app account token.")
    if not body.signed_transaction_info:
        raise HTTPException(status_code=400, detail="Missing Apple signed transaction information.")
    raise HTTPException(
        status_code=503,
        detail=(
            "Apple in-app purchase verification is scaffolded but not configured on this relay yet. "
            "Add App Store Server API credentials before enabling StoreKit purchases."
        ),
    )


@app.get("/v1/mobile/metar")
def relay_mobile_metar(
    install_id: str = Query(...),
    activation_token: str = Query(...),
    app_version: str = Query(...),
    client_kind: str = Query(...),
    airport_iata: str = Query(""),
    airport_icao: str = Query(""),
    timezone: str = Query(""),
    diagnostics_mode: str = Query("manual"),
    device_type: str = Query("phone"),
) -> Dict[str, Any]:
    airport = _airport_result_payload(_lookup_relay_airport(airport_iata or airport_icao), include_coords=True)
    timezone_name = _normalize_timezone_name(timezone or str(airport.get("timezone") or "UTC"))
    _require_mobile_standalone_access(
        install_id=install_id,
        activation_token=activation_token,
        app_version=app_version,
        client_kind=client_kind,
        service="aviationstack",
        device_type=device_type,
        airport_iata=str(airport.get("iata") or ""),
        airport_icao=str(airport.get("icao") or ""),
        timezone_name=timezone_name,
        diagnostics_mode=diagnostics_mode,
    )
    try:
        from localflight.sources.web.metar_client import fetch_metar

        metar = fetch_metar(str(airport.get("icao") or ""))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"METAR unavailable for {airport.get('icao')}: {exc}") from exc
    if not metar:
        raise HTTPException(status_code=503, detail=f"METAR unavailable for {airport.get('icao')}")
    return metar


@app.get("/v1/mobile/fids")
def relay_mobile_fids(
    request: Request,
    install_id: str = Query(...),
    activation_token: str = Query(...),
    app_version: str = Query(...),
    client_kind: str = Query(...),
    airport_iata: str = Query(...),
    airport_icao: str = Query(""),
    timezone: str = Query(""),
    diagnostics_mode: str = Query("manual"),
    view: str = Query("departures", pattern="^(departures|arrivals)$"),
    limit: int = Query(30, ge=1, le=100),
    device_type: str = Query("phone"),
) -> Any:
    airport = _airport_result_payload(_lookup_relay_airport(airport_iata or airport_icao), include_coords=True)
    timezone_name = _normalize_timezone_name(timezone or str(airport.get("timezone") or "UTC"))
    airport["timezone"] = timezone_name
    _require_mobile_standalone_access(
        install_id=install_id,
        activation_token=activation_token,
        app_version=app_version,
        client_kind=client_kind,
        service="aviationstack",
        device_type=device_type,
        airport_iata=str(airport.get("iata") or ""),
        airport_icao=str(airport.get("icao") or ""),
        timezone_name=timezone_name,
        diagnostics_mode=diagnostics_mode,
    )
    schedule_response = relay_schedule(
        request,
        airport_iata=str(airport.get("iata") or airport_iata),
        timezone=timezone_name,
        display_grace_minutes=30,
        display_horizon_hours=12,
        refresh_seconds=_standalone_schedule_min_refresh_seconds(),
        install_id=install_id,
        activation_token=activation_token,
        app_version=app_version,
        client_kind="mobile_standalone",
        device_type=device_type,
        os_family="mobile",
        source_mode="real",
    )
    if schedule_response.status_code >= 400:
        return schedule_response
    payload = _response_json_payload(schedule_response)
    try:
        return _mobile_fids_rows_from_schedule_payload(payload, airport=airport, view=view, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Unable to build mobile FIDS rows: {exc}") from exc


@app.get("/v1/mobile/radar")
def relay_mobile_radar(
    request: Request,
    install_id: str = Query(...),
    activation_token: str = Query(...),
    app_version: str = Query(...),
    client_kind: str = Query(...),
    airport_iata: str = Query(...),
    airport_icao: str = Query(""),
    timezone: str = Query(""),
    diagnostics_mode: str = Query("manual"),
    radius_nm: int = Query(5, ge=1, le=10),
    device_type: str = Query("phone"),
) -> JSONResponse:
    if int(radius_nm) not in _STANDALONE_RADAR_RADII_NM:
        raise HTTPException(status_code=422, detail="Standalone radar radius must be one of 1, 3, 5, or 10 NM")
    airport = _airport_result_payload(_lookup_relay_airport(airport_iata or airport_icao), include_coords=True)
    if airport.get("lat") is None or airport.get("lon") is None:
        raise HTTPException(status_code=404, detail=f"No coordinates for {airport.get('iata') or airport_iata}")
    install_id = _validate_install_id(install_id)
    access = _require_mobile_standalone_access(
        install_id=install_id,
        activation_token=activation_token,
        app_version=app_version,
        client_kind=client_kind,
        service="radar",
        device_type=device_type,
        airport_iata=str(airport.get("iata") or ""),
        airport_icao=str(airport.get("icao") or ""),
        timezone_name=_normalize_timezone_name(timezone or str(airport.get("timezone") or "UTC")),
        diagnostics_mode=diagnostics_mode,
    )
    cache_key = f"{airport.get('iata')}:{int(radius_nm)}"
    cached = _mobile_cache_load(
        install_id=install_id,
        service="radar",
        cache_key=cache_key,
        max_age_seconds=_standalone_radar_min_refresh_seconds(),
    )
    if cached is not None:
        cached = dict(cached)
        cached["source"] = str(cached.get("source") or "adsbexchange_relay_cached")
        cached["refresh_after_s"] = _standalone_radar_min_refresh_seconds()
        return JSONResponse(cached, headers={"X-LF-Mobile-Standalone-Cache": "hit"})

    network_tag = _network_tag(_client_ip(request))
    if access["plan"] == "community":
        _check_and_increment_community_daily_limit(service="radar", network_tag=network_tag)
    month = _month_key()
    current = _get_usage(access["subject_key"], "radar", month)
    if current >= access["limit"]:
        headers = _quota_headers("radar", current, access["limit"], access["plan"])
        headers["Retry-After"] = str(_standalone_radar_min_refresh_seconds())
        return JSONResponse(
            {
                "error": {
                    "code": "quota_exceeded",
                    "info": f"Standalone radar quota exceeded: {current}/{access['limit']} calls used this month.",
                }
            },
            status_code=429,
            headers=headers,
        )

    center_lat = float(airport["lat"])
    center_lon = float(airport["lon"])
    started = time.monotonic()
    raw_payload = _fetch_adsbx_payload(center_lat, center_lon, float(radius_nm))
    latency_ms = int((time.monotonic() - started) * 1000)
    try:
        raw = json.loads(raw_payload.decode("utf-8") if isinstance(raw_payload, bytes) else str(raw_payload))
    except Exception:
        raw = {}
    aircraft = raw.get("ac") if isinstance(raw.get("ac"), list) else []
    from localflight.radar import annotate_blips
    from localflight.radar.normalize import adsbx_aircraft_to_blips

    blips = adsbx_aircraft_to_blips(aircraft, center_lat=center_lat, center_lon=center_lon, radius_nm=float(radius_nm))
    blips = annotate_blips(blips, airport_icao=str(airport.get("icao") or ""), runways=[])
    used = _increment_usage(
        subject_key=access["subject_key"],
        service="radar",
        month=month,
        plan=access["plan"],
        install_id=install_id,
    )
    _log_request(
        install_id=install_id,
        scope=f"mobile_standalone:{int(radius_nm)}nm",
        status=200,
        latency_ms=latency_ms,
        service="radar",
        plan=access["plan"],
    )
    payload = {
        "center": {"lat": center_lat, "lon": center_lon},
        "radius_nm": int(radius_nm),
        "source": "adsbexchange_relay",
        "refresh_after_s": _standalone_radar_min_refresh_seconds(),
        "count": len(blips),
        "radar_mode": "surface" if int(radius_nm) <= 5 else "airborne",
        "ground_filtered": 0,
        "airborne_filtered": 0,
        "hidden_ground_count": 0,
        "hidden_airborne_count": 0,
        "traffic_filter": "all",
        "altitude_filter": {"min_alt_ft": None, "max_alt_ft": None},
        "user_filtered_count": 0,
        "provider_radius_nm": max(5, int(radius_nm)),
        "raw_provider_count": len(aircraft),
        "blips": blips,
    }
    _mobile_cache_store(install_id=install_id, service="radar", cache_key=cache_key, payload=payload)
    return JSONResponse(payload, headers=_quota_headers("radar", used, access["limit"], access["plan"]))


@app.post("/v1/reports")
def relay_reports(body: ReportIn, request: Request) -> Dict[str, Any]:
    report_type = (body.report_type or "").strip().lower()
    if report_type not in _REPORT_ALLOWED_TYPES:
        raise HTTPException(status_code=422, detail="report_type must be manual or crash")

    install_id = _validate_install_id(body.install_id.strip())
    expected_fingerprint = _install_fingerprint(install_id)
    install_fingerprint = (body.install_fingerprint or "").strip()
    if install_fingerprint != expected_fingerprint:
        raise HTTPException(status_code=422, detail="install_fingerprint does not match install_id")

    if body.activation_token.strip():
        _build_client_status(
            install_id=install_id,
            activation_token=body.activation_token.strip(),
            app_version=body.app_version,
        )
    else:
        _ensure_install_allowed(install_id)

    origin = _report_origin(body)
    team = _report_team(origin, body.context)
    team_id = _report_team_id(team)
    if not _linear_reporter_key() or not team_id:
        raise HTTPException(status_code=503, detail="Linear reporting is not configured on the relay")

    message_hash = _normalize_message_hash(body)
    dedupe_key = _report_dedupe_key(
        team=team,
        report_type=report_type,
        origin=origin,
        context=(body.context or "").strip().lower(),
        message_hash=message_hash,
        install_fingerprint=install_fingerprint,
    )
    network_tag = _network_tag(_client_ip(request))

    conn = _connect()
    try:
        _check_report_rate_limit(
            conn,
            report_type=report_type,
            install_fingerprint=install_fingerprint,
            network_tag=network_tag,
        )
        duplicate_url = _dedupe_report(
            conn,
            dedupe_key=dedupe_key,
            team=team,
            report_type=report_type,
            origin=origin,
            install_fingerprint=install_fingerprint,
        )
        if duplicate_url is not None:
            _record_report_event(
                conn,
                install_fingerprint=install_fingerprint,
                network_tag=network_tag,
                report_type=report_type,
                origin=origin,
                context=body.context,
                team=team,
                status="deduped",
                dedupe_key=dedupe_key,
            )
            conn.commit()
            return {"ok": True, "url": None, "team": team, "deduped": True}

        title = _linear_issue_title(body, team=team, origin=origin)
        description = _linear_issue_body(body, team=team, origin=origin, install_fingerprint=install_fingerprint)
        url = _post_linear_issue(team_id=team_id, title=title, description=description)
        _mark_report_filed(conn, dedupe_key=dedupe_key, url=url)
        _record_report_event(
            conn,
            install_fingerprint=install_fingerprint,
            network_tag=network_tag,
            report_type=report_type,
            origin=origin,
            context=body.context,
            team=team,
            status="filed",
            dedupe_key=dedupe_key,
        )
        conn.commit()
        return {"ok": True, "url": url, "team": team, "deduped": False}
    finally:
        conn.close()


@app.get("/v1/schedule")
def relay_schedule(
    request: Request,
    airport_iata: str = Query(...),
    timezone: str = Query(...),
    display_grace_minutes: int = Query(30, ge=0, le=180),
    display_horizon_hours: int = Query(12, ge=1, le=24),
    refresh_seconds: int = Query(3600, ge=60, le=86400),
    install_id: str = Query(...),
    activation_token: str = Query(""),
    app_version: str = Query(""),
    client_kind: str = Query("desktop"),
    device_type: str = Query("unknown"),
    os_family: str = Query(""),
    os_version: str = Query(""),
    arch: str = Query(""),
    requested_gui: str = Query(""),
    effective_gui: str = Query(""),
    source_mode: str = Query(""),
    diagnostics_mode: str = Query(""),
    companion_count: int = Query(0, ge=0, le=100_000),
    matrix_count: int = Query(0, ge=0, le=100_000),
    matrix_online_count: int = Query(0, ge=0, le=100_000),
) -> JSONResponse:
    install_id = _validate_install_id(install_id)
    requested_timezone_name = _normalize_timezone_name(timezone)
    requested_grace_minutes = int(display_grace_minutes)
    requested_horizon_hours = int(display_horizon_hours)
    airport_info = _canonical_schedule_airport(airport_iata)
    airport_iata = airport_info["iata"]
    airport_icao = airport_info["icao"]
    timezone_name = airport_info["timezone"]
    display_grace_minutes, display_horizon_hours = _bucket_schedule_window(
        requested_grace_minutes,
        requested_horizon_hours,
    )
    network_tag = _network_tag(_client_ip(request))
    _check_and_increment_schedule_rpm_limits(install_id=install_id, network_tag=network_tag)

    access = _resolve_access(install_id=install_id, activation_token=activation_token, service="aviationstack")
    client_kind = _clean_client_kind(client_kind)
    if client_kind == "mobile_standalone":
        refresh_seconds = max(int(refresh_seconds), _standalone_schedule_min_refresh_seconds())
    _record_install_profile(
        install_id=install_id,
        presence_event="relay_activity",
        client_kind=client_kind,
        device_type=device_type,
        airport_iata=airport_iata,
        airport_icao=airport_icao,
        timezone_name=timezone_name,
        app_version=app_version,
        os_family=os_family,
        os_version=os_version,
        arch=arch,
        requested_gui=requested_gui,
        effective_gui=effective_gui,
        source_mode=source_mode,
        diagnostics_mode=diagnostics_mode,
        companion_count=companion_count,
        matrix_count=matrix_count,
        matrix_online_count=matrix_online_count,
    )
    plan = str(access["plan"] or "community")
    min_fresh_ttl_s = _schedule_min_fresh_ttl_seconds_for_plan(plan)
    if client_kind == "mobile_standalone":
        min_fresh_ttl_s = max(min_fresh_ttl_s, _standalone_schedule_min_refresh_seconds())
    if plan == "community":
        _check_and_increment_community_daily_limit(
            service="aviationstack",
            network_tag=network_tag,
        )

    cache_key = _schedule_cache_key(
        airport_iata=airport_iata,
        timezone_name=timezone_name,
        display_grace_minutes=display_grace_minutes,
        display_horizon_hours=display_horizon_hours,
    )
    lock = _get_schedule_lock(cache_key)

    conn = _connect()
    snapshot_row = _load_schedule_snapshot_conn(conn, cache_key)
    conn.close()
    if snapshot_row is None:
        _check_and_mark_new_schedule_cache_key(network_tag=network_tag, cache_key=cache_key)

    _record_client_interest(
        install_id=install_id,
        plan=str(access["plan"] or "community"),
        client_kind=client_kind,
        airport_iata=airport_iata,
        airport_icao=airport_icao,
        timezone_name=timezone_name,
        display_grace_minutes=display_grace_minutes,
        display_horizon_hours=display_horizon_hours,
        refresh_seconds=max(refresh_seconds, min_fresh_ttl_s),
    )

    month = _month_key()
    current = _get_usage(access["subject_key"], "aviationstack", month)
    if current >= access["limit"]:
        headers = _quota_headers("aviationstack", current, access["limit"], access["plan"])
        if access["plan"] == "community":
            headers["Retry-After"] = "86400"
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
            headers=headers,
        )

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
        stale_reason: str = "",
        budget_limited_providers: Optional[list[str]] = None,
    ) -> JSONResponse:
        payload = _snapshot_payload_from_row(row, cache_state=cache_state)
        payload["meta"]["served_via"] = served_via
        payload["meta"]["requested_refresh_seconds"] = int(refresh_seconds)
        payload["meta"]["effective_min_fresh_ttl_seconds"] = int(min_fresh_ttl_s)
        payload["meta"]["canonical_airport_iata"] = airport_iata
        payload["meta"]["canonical_airport_icao"] = airport_icao
        payload["meta"]["canonical_timezone"] = timezone_name
        payload["meta"]["canonical_display_grace_minutes"] = int(display_grace_minutes)
        payload["meta"]["canonical_display_horizon_hours"] = int(display_horizon_hours)
        payload["meta"]["requested_timezone"] = requested_timezone_name
        payload["meta"]["requested_display_grace_minutes"] = int(requested_grace_minutes)
        payload["meta"]["requested_display_horizon_hours"] = int(requested_horizon_hours)
        if stale_reason:
            payload["meta"]["stale_reason"] = stale_reason
        if budget_limited_providers:
            payload["meta"]["budget_limited_providers"] = sorted(set(budget_limited_providers))
        if plan == "community":
            payload["meta"]["relay_policy"] = "community schedule snapshots refresh at most once per hour"
        if client_kind == "mobile_standalone":
            payload["meta"]["relay_policy"] = "mobile standalone schedule snapshots refresh at most once every 3 hours"
            payload["meta"]["client_kind"] = "mobile_standalone"
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

    state = _snapshot_lifecycle_state(
        snapshot_row,
        refresh_seconds=refresh_seconds,
        min_fresh_ttl_s=min_fresh_ttl_s,
    )

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
        if snapshot_row is not None and (state == "stale" or _snapshot_stale_if_error_state(snapshot_row)):
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
                stale_reason="refresh_in_progress",
            )

        waited = lock.acquire(timeout=_SHARED_SCHEDULE_LOCK_WAIT_S)
        if waited:
            lock.release()
        conn = _connect()
        latest = _load_schedule_snapshot_conn(conn, cache_key)
        latest_state = _snapshot_lifecycle_state(
            latest,
            refresh_seconds=refresh_seconds,
            min_fresh_ttl_s=min_fresh_ttl_s,
        )
        conn.close()
        if latest is not None and (latest_state in {"fresh", "stale"} or _snapshot_stale_if_error_state(latest)):
            public_latest_state = "fresh" if latest_state == "fresh" else "stale"
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
                cache_state=public_latest_state,
                served_via="awaited-refresh" if public_latest_state == "fresh" else "stale-fallback",
                count_cache_hit=latest_state == "fresh",
                count_stale=public_latest_state == "stale",
                used_count=used,
                stale_reason="" if public_latest_state == "fresh" else "refresh_in_progress",
            )
        raise HTTPException(status_code=503, detail="Relay schedule refresh is already in progress")

    t0 = time.monotonic()
    try:
        conn = _connect()
        latest = _load_schedule_snapshot_conn(conn, cache_key)
        latest_state = _snapshot_lifecycle_state(
            latest,
            refresh_seconds=refresh_seconds,
            min_fresh_ttl_s=min_fresh_ttl_s,
        )
        conn.close()
        if latest is not None and latest_state == "fresh":
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
                cache_state="fresh",
                served_via="coalesced-refresh",
                count_cache_hit=True,
                used_count=used,
            )

        snapshot = _fetch_shared_schedule_from_upstream(
            airport_iata=airport_iata,
            timezone_name=timezone_name,
            display_grace_minutes=display_grace_minutes,
            display_horizon_hours=display_horizon_hours,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        if _schedule_snapshot_is_suspiciously_sparse(snapshot, latest):
            sparse_detail = "suspiciously sparse provider refresh blocked from replacing healthy cache"
            conn = _connect()
            conn.execute(
                "UPDATE schedule_snapshots SET last_error=?, updated_at=? WHERE cache_key=?",
                (sparse_detail, _utc_now(), cache_key),
            )
            conn.commit()
            stale_row = _load_schedule_snapshot_conn(conn, cache_key)
            conn.close()
            if stale_row is not None and _snapshot_stale_if_error_state(stale_row):
                _log_request(
                    install_id=install_id,
                    scope="shared_schedule",
                    status=200,
                    latency_ms=latency_ms,
                    service="aviationstack",
                    plan=access["plan"],
                )
                return _serve_snapshot(
                    stale_row,
                    cache_state="stale",
                    served_via="stale-on-sparse-refresh",
                    count_stale=True,
                    used_count=used,
                    stale_reason="suspicious_sparse_refresh",
                )
            raise HTTPException(status_code=503, detail="Schedule refresh returned suspiciously sparse data")
        pages_fetched = int(((snapshot.get("meta") or {}).get("pages_fetched", 0) or 0))
        upstream_usage_precounted = bool((snapshot.get("meta") or {}).get("upstream_usage_precounted"))
        _store_schedule_snapshot(
            cache_key=cache_key,
            airport_iata=airport_iata,
            timezone_name=timezone_name,
            display_grace_minutes=display_grace_minutes,
            display_horizon_hours=display_horizon_hours,
            payload=snapshot,
            pages_fetched=pages_fetched,
        )
        if pages_fetched > 0 and not upstream_usage_precounted:
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
        fresh_state = _snapshot_lifecycle_state(
            fresh_row,
            refresh_seconds=refresh_seconds,
            min_fresh_ttl_s=min_fresh_ttl_s,
        )
        meta = snapshot.get("meta") if isinstance(snapshot.get("meta"), dict) else {}
        public_state = "miss" if snapshot_row is None and fresh_state == "fresh" else fresh_state
        if public_state not in {"fresh", "stale", "miss"}:
            public_state = "stale" if _snapshot_stale_if_error_state(fresh_row) else "fresh"
        return _serve_snapshot(
            fresh_row,
            cache_state=public_state,
            served_via="cold-fill" if public_state == "miss" else "refresh",
            count_stale=public_state == "stale",
            used_count=used,
            stale_reason=str(meta.get("stale_reason") or "") if public_state == "stale" else "",
        )
    except HTTPException as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        budget_limited = [exc.provider] if isinstance(exc, UpstreamBudgetExceeded) else []
        if snapshot_row is not None and _snapshot_stale_if_error_state(snapshot_row):
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
                    stale_reason="budget_limited" if budget_limited else "upstream_error",
                    budget_limited_providers=budget_limited,
                )
        if isinstance(exc, UpstreamBudgetExceeded):
            exc = HTTPException(
                status_code=503,
                detail=(
                    "No usable schedule cache is available and the upstream provider budget is capped. "
                    "Try again after the monthly window resets or configure another provider."
                ),
            )
        _log_request(
            install_id=install_id,
            scope="shared_schedule",
            status=getattr(exc, "status_code", 502),
            latency_ms=latency_ms,
            service="aviationstack",
            plan=access["plan"],
        )
        raise exc
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
        headers = _quota_headers("aviationstack", current, access["limit"], access["plan"])
        if access["plan"] == "community":
            headers["Retry-After"] = "86400"
        return JSONResponse(
            {
                "error": {
                    "code": "quota_exceeded",
                    "info": f"{access['plan'].title()} schedule quota exceeded: {current}/{access['limit']} calls used this month.",
                }
            },
            status_code=429,
            headers=headers,
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


@app.get("/v1/airport-surface")
def relay_airport_surface(
    request: Request,
    airport_iata: str = Query(...),
    airport_icao: str = Query(""),
    lat: float = Query(...),
    lon: float = Query(...),
    radius_nm: float = Query(5.0, ge=1.0, le=5.0),
) -> JSONResponse:
    if not _airport_surface_enabled():
        raise HTTPException(status_code=503, detail="Airport surface overlay is disabled on this relay")

    airport_iata_clean = _clean_airport(airport_iata) or ""
    airport_icao_clean = _clean_airport(airport_icao) if airport_icao else ""
    cache_key = _airport_surface_cache_key(airport_iata_clean, airport_icao_clean or "")
    lock = _get_airport_surface_lock(cache_key)
    t0 = time.monotonic()

    def _log(status: int) -> None:
        _log_request(
            install_id="",
            scope=airport_iata_clean,
            status=status,
            latency_ms=int((time.monotonic() - t0) * 1000),
            service="airport_surface",
            plan="shared",
        )

    def _serve(
        row: sqlite3.Row,
        *,
        cache_state: str,
        count_cache_hit: bool = False,
        count_stale: bool = False,
        error: str = "",
    ) -> JSONResponse:
        _record_airport_surface_access(
            cache_key=cache_key,
            cache_state=cache_state,
            count_cache_hit=count_cache_hit,
            count_stale=count_stale,
            error=error,
        )
        payload = _airport_surface_payload_from_row(
            row,
            cache_state=cache_state,
            requested_radius_nm=radius_nm,
            error=error,
        )
        payload.setdefault("meta", {})
        if isinstance(payload["meta"], dict):
            payload["meta"]["served_via"] = "surface-cache"
        return JSONResponse(payload)

    conn = _connect()
    snapshot_row = _load_airport_surface_snapshot_conn(conn, cache_key)
    state = _airport_surface_lifecycle_state(snapshot_row)
    conn.close()

    if snapshot_row is not None and state == "fresh":
        _log(200)
        return _serve(snapshot_row, cache_state="fresh", count_cache_hit=True)

    acquired = lock.acquire(blocking=False)
    if not acquired:
        if snapshot_row is not None and state == "stale":
            _log(200)
            return _serve(snapshot_row, cache_state="stale", count_stale=True)

        deadline = time.monotonic() + _AIRPORT_SURFACE_LOCK_WAIT_S
        while time.monotonic() < deadline:
            time.sleep(0.1)
            conn = _connect()
            waited_row = _load_airport_surface_snapshot_conn(conn, cache_key)
            waited_state = _airport_surface_lifecycle_state(waited_row)
            conn.close()
            if waited_row is not None and waited_state in {"fresh", "stale"}:
                _log(200)
                return _serve(
                    waited_row,
                    cache_state=waited_state,
                    count_cache_hit=(waited_state == "fresh"),
                    count_stale=(waited_state == "stale"),
                )

        if snapshot_row is not None:
            _log(200)
            return _serve(snapshot_row, cache_state="stale", count_stale=True, error="Surface refresh still in progress")
        _log(503)
        raise HTTPException(status_code=503, detail="Airport surface refresh in progress")

    try:
        try:
            payload = _fetch_airport_surface_from_osm(
                airport_iata=airport_iata_clean,
                airport_icao=airport_icao_clean or "",
                lat=lat,
                lon=lon,
                radius_nm=radius_nm,
            )
            _store_airport_surface_snapshot(cache_key, payload)
            _record_airport_surface_access(cache_key=cache_key, cache_state="fresh")
            _log(200)
            payload.setdefault("meta", {})
            if isinstance(payload["meta"], dict):
                payload["meta"]["served_via"] = "surface-refresh"
            return JSONResponse(payload)
        except HTTPException as exc:
            error = str(exc.detail)
            conn = _connect()
            stale_row = _load_airport_surface_snapshot_conn(conn, cache_key)
            stale_state = _airport_surface_lifecycle_state(stale_row)
            conn.close()
            if stale_row is not None and stale_state in {"fresh", "stale"}:
                _log(200)
                return _serve(stale_row, cache_state="stale", count_stale=True, error=error)
            _log(exc.status_code)
            raise
        except Exception as exc:
            error = f"Airport surface refresh failed: {exc}"
            conn = _connect()
            stale_row = _load_airport_surface_snapshot_conn(conn, cache_key)
            stale_state = _airport_surface_lifecycle_state(stale_row)
            conn.close()
            if stale_row is not None and stale_state in {"fresh", "stale"}:
                _log(200)
                return _serve(stale_row, cache_state="stale", count_stale=True, error=error)
            _log(502)
            raise HTTPException(status_code=502, detail=error)
    finally:
        lock.release()


@app.get("/v1/radar")
def relay_radar(
    request: Request,
    lat: float = Query(...),
    lon: float = Query(...),
    radius_nm: float = Query(20.0, ge=1.0, le=200.0),
    install_id: str = Query(...),
    activation_token: str = Query(""),
    app_version: str = Query(""),
    client_kind: str = Query("desktop"),
    device_type: str = Query("unknown"),
    os_family: str = Query(""),
    os_version: str = Query(""),
    arch: str = Query(""),
    requested_gui: str = Query(""),
    effective_gui: str = Query(""),
    source_mode: str = Query(""),
    diagnostics_mode: str = Query(""),
    companion_count: int = Query(0, ge=0, le=100_000),
    matrix_count: int = Query(0, ge=0, le=100_000),
    matrix_online_count: int = Query(0, ge=0, le=100_000),
) -> Response:
    install_id = _validate_install_id(install_id)
    client_kind = _clean_client_kind(client_kind)
    if client_kind == "mobile_standalone" and int(radius_nm) not in _STANDALONE_RADAR_RADII_NM:
        raise HTTPException(status_code=422, detail="mobile_standalone radar radius must be one of 1, 3, 5, or 10 NM")
    access = _resolve_access(install_id=install_id, activation_token=activation_token, service="radar")
    _record_install_profile(
        install_id=install_id,
        presence_event="relay_activity",
        client_kind=client_kind,
        device_type=device_type,
        app_version=app_version,
        os_family=os_family,
        os_version=os_version,
        arch=arch,
        requested_gui=requested_gui,
        effective_gui=effective_gui,
        source_mode=source_mode,
        diagnostics_mode=diagnostics_mode,
        companion_count=companion_count,
        matrix_count=matrix_count,
        matrix_online_count=matrix_online_count,
    )
    if access["plan"] == "community":
        _check_and_increment_community_daily_limit(
            service="radar",
            network_tag=_network_tag(_client_ip(request)),
        )
    month = _month_key()
    current = _get_usage(access["subject_key"], "radar", month)
    if current >= access["limit"]:
        headers = _quota_headers("radar", current, access["limit"], access["plan"])
        if access["plan"] == "community":
            headers["Retry-After"] = "86400"
        return JSONResponse(
            {
                "error": {
                    "code": "quota_exceeded",
                    "info": f"{access['plan'].title()} radar quota exceeded: {current}/{access['limit']} calls used this month.",
                }
            },
            status_code=429,
            headers=headers,
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


@app.get("/admin/api/overview")
def admin_api_overview(username: str = Depends(_require_admin)) -> Dict[str, Any]:
    conn = _connect()
    month = _month_key()
    try:
        aerodatabox = _provider_admin_state(conn, _SETTING_AERODATABOX_KEY, "AERODATABOX_API_KEY")
        aviationstack = _provider_admin_state(conn, _SETTING_AVIATIONSTACK_KEY, "AVIATIONSTACK_API_KEY")
        rapidapi = _provider_admin_state(conn, _SETTING_RAPIDAPI_KEY, "RAPIDAPI_KEY")
        fleet_rows = _admin_fleet_rows(conn, month)
        fleet_metrics = _admin_fleet_metrics(fleet_rows)
        heartbeat_summary = _admin_heartbeat_summary(fleet_rows)
        snapshot_totals = conn.execute(
            """
            SELECT COALESCE(SUM(client_accesses), 0) AS client_accesses,
                   COALESCE(SUM(upstream_pulls), 0) AS upstream_pulls,
                   COALESCE(SUM(refresh_count), 0) AS refresh_count,
                   COALESCE(SUM(cache_hits), 0) AS cache_hits,
                   COALESCE(SUM(stale_serves), 0) AS stale_serves
            FROM schedule_snapshots
            """
        ).fetchone()
        surface_totals = conn.execute(
            """
            SELECT COALESCE(SUM(request_count), 0) AS request_count,
                   COALESCE(SUM(cache_hits), 0) AS cache_hits,
                   COALESCE(SUM(refresh_count), 0) AS refresh_count,
                   COALESCE(SUM(stale_serves), 0) AS stale_serves
            FROM airport_surface_snapshots
            """
        ).fetchone()
        return {
            "generated_at": _utc_now(),
            "operator": username,
            "month": month,
            "provider_revision": _provider_revision(conn),
            "providers": {
                "aerodatabox": aerodatabox,
                "aviationstack": aviationstack,
                "rapidapi": rapidapi,
            },
            "limits": {
                "community_schedule": _community_schedule_limit(),
                "community_radar": _community_radar_limit(),
                "managed_schedule_default": _managed_schedule_limit(),
                "managed_radar_default": _managed_radar_limit(),
                "aerodatabox_upstream_units": _aerodatabox_upstream_units_limit(),
                "aerodatabox_fids_units": _aerodatabox_fids_units(),
                "aviationstack_upstream": _aviationstack_upstream_monthly_limit(),
            },
            "features": {
                "raw_provider_debug": _raw_provider_debug_enabled(),
                "airport_surface_overlay": _airport_surface_enabled(),
            },
            "counts": {
                "usage_rows": _admin_count(conn, "SELECT COUNT(*) FROM usage WHERE month=?", (month,)),
                "requests_24h": _admin_count(conn, "SELECT COUNT(*) FROM request_log WHERE ts>=?", (_hours_ago(24),)),
                "activation_tokens_active": _admin_count(
                    conn,
                    "SELECT COUNT(*) FROM activation_tokens WHERE revoked_at IS NULL",
                ),
                "activation_tokens_revoked": _admin_count(
                    conn,
                    "SELECT COUNT(*) FROM activation_tokens WHERE revoked_at IS NOT NULL",
                ),
                "activation_requests_pending": _admin_count(
                    conn,
                    "SELECT COUNT(*) FROM activation_requests WHERE status IN (?, ?)",
                    (_REQUEST_STATUS_PENDING, _REQUEST_STATUS_MANUAL_REVIEW),
                ),
                "blocked_installs": _admin_count(conn, "SELECT COUNT(*) FROM blocked_installs"),
                "schedule_snapshots": _admin_count(conn, "SELECT COUNT(*) FROM schedule_snapshots"),
                "surface_snapshots": _admin_count(conn, "SELECT COUNT(*) FROM airport_surface_snapshots"),
                "client_interests": _admin_count(conn, "SELECT COUNT(*) FROM client_interests"),
                "known_installs": int(fleet_metrics.get("known_installs") or 0),
                "active_installs_24h": int(fleet_metrics.get("active_installs_24h") or 0),
                "companion_installs": int(fleet_metrics.get("companion_installs") or 0),
                "matrix_installs": int(fleet_metrics.get("matrix_installs") or 0),
                "reports_24h": _admin_count(conn, "SELECT COUNT(*) FROM report_events WHERE ts>=?", (_hours_ago(24),)),
            },
            "fleet": fleet_metrics,
            "heartbeat": heartbeat_summary,
            "shared_schedule": {
                "client_accesses": int(snapshot_totals["client_accesses"] or 0),
                "upstream_pulls": int(snapshot_totals["upstream_pulls"] or 0),
                "refresh_count": int(snapshot_totals["refresh_count"] or 0),
                "cache_hits": int(snapshot_totals["cache_hits"] or 0),
                "stale_serves": int(snapshot_totals["stale_serves"] or 0),
            },
            "surface_cache": {
                "request_count": int(surface_totals["request_count"] or 0),
                "refresh_count": int(surface_totals["refresh_count"] or 0),
                "cache_hits": int(surface_totals["cache_hits"] or 0),
                "stale_serves": int(surface_totals["stale_serves"] or 0),
            },
        }
    finally:
        conn.close()


@app.get("/admin/api/usage")
def admin_api_usage(
    username: str = Depends(_require_admin),
    q: str = Query(""),
    service: str = Query(""),
    plan: str = Query(""),
    status: str = Query(""),
    limit: int = Query(_ADMIN_DEFAULT_PAGE_LIMIT, ge=1, le=_ADMIN_MAX_PAGE_LIMIT),
    cursor: str = Query(""),
    sort: str = Query("last_seen"),
    dir: str = Query("desc"),
) -> Dict[str, Any]:
    conn = _connect()
    month = _month_key()
    try:
        service_rows = conn.execute(
            """
            SELECT service, plan, COALESCE(SUM(calls), 0) AS calls,
                   COUNT(DISTINCT COALESCE(NULLIF(install_id, ''), subject_key)) AS subjects,
                   MAX(last_seen) AS last_seen
            FROM usage
            WHERE month=?
            GROUP BY service, plan
            ORDER BY service ASC, calls DESC
            """,
            (month,),
        ).fetchall()
        usage_rows = _admin_usage_rows(conn, month)
        usage_filtered, usage_filters = _admin_filter_rows(
            usage_rows,
            q=q,
            filters={"service": service, "plan": plan},
        )
        usage_filtered = _admin_sort_rows(usage_filtered, sort=sort or "last_seen", direction=dir)

        request_rows = _admin_request_rows(conn)
        request_filters: Dict[str, Any] = {"service": service, "plan": plan}
        if status:
            if status == "error":
                request_rows = [row for row in request_rows if bool(row.get("error"))]
            else:
                request_filters["status"] = status
        request_filtered, request_active_filters = _admin_filter_rows(request_rows, q=q, filters=request_filters)
        request_filtered = _admin_sort_rows(request_filtered, sort=sort or "ts", direction=dir)
        page = _admin_page_payload(
            usage_filtered,
            total_estimate=len(usage_rows),
            limit=limit,
            cursor=cursor,
            sort=sort,
            direction=dir,
            filters=usage_filters,
            facets={
                "service": _admin_count_values(usage_filtered, "service"),
                "plan": _admin_count_values(usage_filtered, "plan"),
            },
        )
        request_page = _admin_page_payload(
            request_filtered,
            total_estimate=len(request_rows),
            limit=limit,
            cursor=cursor,
            sort=sort or "ts",
            direction=dir,
            filters=request_active_filters,
            facets={
                "service": _admin_count_values(request_filtered, "service"),
                "plan": _admin_count_values(request_filtered, "plan"),
                "error": _admin_count_values(request_filtered, "error"),
                "status": _admin_count_values(request_filtered, "status"),
            },
        )
        return {
            "generated_at": _utc_now(),
            "operator": username,
            "month": month,
            "summary": [
                {
                    "service": str(row["service"] or ""),
                    "plan": str(row["plan"] or ""),
                    "calls": int(row["calls"] or 0),
                    "subjects": int(row["subjects"] or 0),
                    "last_seen": str(row["last_seen"] or ""),
                }
                for row in service_rows
            ],
            "rows": page["rows"],
            "next_cursor": page["next_cursor"],
            "total_estimate": page["total_estimate"],
            "filtered_estimate": page["filtered_estimate"],
            "facets": page["facets"],
            "sort": page["sort"],
            "filters": page["filters"],
            "requests": request_page,
        }
    finally:
        conn.close()


@app.get("/admin/api/fleet")
def admin_api_fleet(
    username: str = Depends(_require_admin),
    q: str = Query(""),
    status: str = Query(""),
    plan: str = Query(""),
    os_family: str = Query(""),
    effective_gui: str = Query(""),
    app_version: str = Query(""),
    presence_status: str = Query(""),
    presence_source: str = Query(""),
    airport_iata: str = Query(""),
    has_companion: Optional[bool] = Query(None),
    has_matrix: Optional[bool] = Query(None),
    blocked: Optional[bool] = Query(None),
    managed: Optional[bool] = Query(None),
    first_seen_from: str = Query(""),
    last_seen_from: str = Query(""),
    limit: int = Query(_ADMIN_DEFAULT_PAGE_LIMIT, ge=1, le=_ADMIN_MAX_PAGE_LIMIT),
    cursor: str = Query(""),
    sort: str = Query("last_seen"),
    dir: str = Query("desc"),
) -> Dict[str, Any]:
    conn = _connect()
    month = _month_key()
    try:
        rows = _admin_fleet_rows(conn, month)
        filtered, active_filters = _admin_filter_fleet_rows(
            rows,
            q=q,
            status=status,
            plan=plan,
            os_family=os_family,
            effective_gui=effective_gui,
            app_version=app_version,
            presence_status=presence_status,
            presence_source=presence_source,
            airport_iata=airport_iata,
            has_companion=has_companion,
            has_matrix=has_matrix,
            blocked=blocked,
            managed=managed,
            first_seen_from=first_seen_from,
            last_seen_from=last_seen_from,
        )
        filtered = _admin_sort_rows(filtered, sort=sort or "last_seen", direction=dir)
        page = _admin_page_payload(
            filtered,
            total_estimate=len(rows),
            limit=limit,
            cursor=cursor,
            sort=sort,
            direction=dir,
            filters=active_filters,
            facets=_admin_fleet_facets(filtered),
        )
        return {
            "generated_at": _utc_now(),
            "operator": username,
            "month": month,
            "metrics": _admin_fleet_metrics(rows),
            "heartbeat": _admin_heartbeat_summary(rows),
            "installs": page["rows"],
            "rows": page["rows"],
            "next_cursor": page["next_cursor"],
            "total_estimate": page["total_estimate"],
            "filtered_estimate": page["filtered_estimate"],
            "facets": page["facets"],
            "sort": page["sort"],
            "filters": page["filters"],
        }
    finally:
        conn.close()


@app.get("/admin/api/schedules")
def admin_api_schedules(
    username: str = Depends(_require_admin),
    q: str = Query(""),
    airport_iata: str = Query(""),
    cache_state: str = Query(""),
    limit: int = Query(_ADMIN_DEFAULT_PAGE_LIMIT, ge=1, le=_ADMIN_MAX_PAGE_LIMIT),
    cursor: str = Query(""),
    sort: str = Query("updated_at"),
    dir: str = Query("desc"),
) -> Dict[str, Any]:
    conn = _connect()
    try:
        snapshots = _admin_schedule_snapshot_rows(conn)
        filtered, filters = _admin_filter_rows(
            snapshots,
            q=q,
            filters={"airport_iata": airport_iata.upper(), "last_cache_state": cache_state},
        )
        filtered = _admin_sort_rows(filtered, sort=sort or "updated_at", direction=dir)
        page = _admin_page_payload(
            filtered,
            total_estimate=len(snapshots),
            limit=limit,
            cursor=cursor,
            sort=sort,
            direction=dir,
            filters=filters,
            facets={
                "airport_iata": _admin_count_values(filtered, "airport_iata"),
                "last_cache_state": _admin_count_values(filtered, "last_cache_state"),
            },
        )
        interests = _admin_client_interest_rows(conn)
        return {
            "generated_at": _utc_now(),
            "operator": username,
            "snapshots": page["rows"],
            "rows": page["rows"],
            "next_cursor": page["next_cursor"],
            "total_estimate": page["total_estimate"],
            "filtered_estimate": page["filtered_estimate"],
            "facets": page["facets"],
            "sort": page["sort"],
            "filters": page["filters"],
            "client_interests": interests[: _ADMIN_DEFAULT_PAGE_LIMIT],
        }
    finally:
        conn.close()


@app.get("/admin/api/surfaces")
def admin_api_surfaces(
    username: str = Depends(_require_admin),
    q: str = Query(""),
    airport_iata: str = Query(""),
    cache_state: str = Query(""),
    limit: int = Query(_ADMIN_DEFAULT_PAGE_LIMIT, ge=1, le=_ADMIN_MAX_PAGE_LIMIT),
    cursor: str = Query(""),
    sort: str = Query("updated_at"),
    dir: str = Query("desc"),
) -> Dict[str, Any]:
    conn = _connect()
    try:
        snapshots = _admin_surface_rows(conn)
        filtered, filters = _admin_filter_rows(
            snapshots,
            q=q,
            filters={"airport_iata": airport_iata.upper(), "last_cache_state": cache_state},
        )
        filtered = _admin_sort_rows(filtered, sort=sort or "updated_at", direction=dir)
        page = _admin_page_payload(
            filtered,
            total_estimate=len(snapshots),
            limit=limit,
            cursor=cursor,
            sort=sort,
            direction=dir,
            filters=filters,
            facets={
                "airport_iata": _admin_count_values(filtered, "airport_iata"),
                "last_cache_state": _admin_count_values(filtered, "last_cache_state"),
            },
        )
        return {
            "generated_at": _utc_now(),
            "operator": username,
            "enabled": _airport_surface_enabled(),
            "snapshots": page["rows"],
            "rows": page["rows"],
            "next_cursor": page["next_cursor"],
            "total_estimate": page["total_estimate"],
            "filtered_estimate": page["filtered_estimate"],
            "facets": page["facets"],
            "sort": page["sort"],
            "filters": page["filters"],
        }
    finally:
        conn.close()


@app.get("/admin/api/activations")
def admin_api_activations(username: str = Depends(_require_admin)) -> Dict[str, Any]:
    conn = _connect()
    try:
        payload = _admin_activation_payload(conn)
        payload["generated_at"] = _utc_now()
        payload["operator"] = username
        return payload
    finally:
        conn.close()


@app.get("/admin/api/reports")
def admin_api_reports(
    username: str = Depends(_require_admin),
    q: str = Query(""),
    report_type: str = Query(""),
    origin: str = Query(""),
    team: str = Query(""),
    status: str = Query(""),
    limit: int = Query(_ADMIN_DEFAULT_PAGE_LIMIT, ge=1, le=_ADMIN_MAX_PAGE_LIMIT),
    cursor: str = Query(""),
    sort: str = Query("ts"),
    dir: str = Query("desc"),
) -> Dict[str, Any]:
    conn = _connect()
    try:
        payload = _admin_report_payload(conn)
        recent = _list_dicts(payload.get("recent_events"))
        filtered, filters = _admin_filter_rows(
            recent,
            q=q,
            filters={"report_type": report_type, "origin": origin, "team": team, "status": status},
        )
        filtered = _admin_sort_rows(filtered, sort=sort or "ts", direction=dir)
        page = _admin_page_payload(
            filtered,
            total_estimate=len(recent),
            limit=limit,
            cursor=cursor,
            sort=sort,
            direction=dir,
            filters=filters,
            facets={
                "report_type": _admin_count_values(filtered, "report_type"),
                "origin": _admin_count_values(filtered, "origin"),
                "team": _admin_count_values(filtered, "team"),
                "status": _admin_count_values(filtered, "status"),
            },
        )
        payload["recent_events"] = page["rows"]
        payload["rows"] = page["rows"]
        payload["next_cursor"] = page["next_cursor"]
        payload["total_estimate"] = page["total_estimate"]
        payload["filtered_estimate"] = page["filtered_estimate"]
        payload["facets"] = page["facets"]
        payload["sort"] = page["sort"]
        payload["filters"] = page["filters"]
        payload["generated_at"] = _utc_now()
        payload["operator"] = username
        return payload
    finally:
        conn.close()


@app.post("/admin/api/providers/save")
def admin_api_save_provider_keys(
    body: AdminProviderKeysIn,
    username: str = Depends(_require_admin),
) -> Dict[str, Any]:
    conn = _connect()
    changes: list[str] = []
    try:
        if body.aerodatabox_key.strip():
            _setting_set_conn(conn, _SETTING_AERODATABOX_KEY, body.aerodatabox_key.strip())
            changes.append("AeroDataBox")
        if body.aviationstack_key.strip():
            _setting_set_conn(conn, _SETTING_AVIATIONSTACK_KEY, body.aviationstack_key.strip())
            changes.append("AviationStack")
        if body.rapidapi_key.strip():
            _setting_set_conn(conn, _SETTING_RAPIDAPI_KEY, body.rapidapi_key.strip())
            changes.append("RapidAPI ADS-B")
        if not changes:
            return _admin_action_response("No provider key changes submitted.", operator=username)
        revision = _bump_provider_revision(conn)
        conn.commit()
        return _admin_action_response(
            f"Updated provider key storage for {', '.join(changes)}.",
            operator=username,
            provider_revision=revision,
        )
    finally:
        conn.close()


@app.post("/admin/api/providers/clear")
def admin_api_clear_provider_key(
    body: AdminProviderClearIn,
    username: str = Depends(_require_admin),
) -> Dict[str, Any]:
    mapping = {
        "aerodatabox": (_SETTING_AERODATABOX_KEY, "AeroDataBox"),
        "aviationstack": (_SETTING_AVIATIONSTACK_KEY, "AviationStack"),
        "rapidapi": (_SETTING_RAPIDAPI_KEY, "RapidAPI ADS-B"),
    }
    provider = body.provider.strip().lower()
    if provider not in mapping:
        raise HTTPException(status_code=400, detail="Unknown provider")
    setting_key, label = mapping[provider]
    conn = _connect()
    try:
        _setting_delete_conn(conn, setting_key)
        revision = _bump_provider_revision(conn)
        conn.commit()
        return _admin_action_response(
            f"Cleared relay-stored {label} override.",
            operator=username,
            provider_revision=revision,
        )
    finally:
        conn.close()


@app.post("/admin/api/activation/create")
def admin_api_activation_create(
    body: AdminActivationCreateIn,
    username: str = Depends(_require_admin),
) -> Dict[str, Any]:
    token = _new_activation_token()
    conn = _connect()
    try:
        _store_activation_token(
            conn,
            token=token,
            label=body.label,
            schedule_limit=body.schedule_limit,
            radar_limit=body.radar_limit,
            created_by=username,
        )
        conn.commit()
        return _admin_action_response(
            "Activation token created. Copy it now; it is shown once.",
            operator=username,
            activation_token=token,
            token_prefix=token[:10],
            action_ref=_admin_action_ref(conn, "tok", _token_hash(token)),
        )
    finally:
        conn.close()


@app.post("/admin/api/activation/token-action")
def admin_api_activation_token_action(
    body: AdminTokenActionIn,
    username: str = Depends(_require_admin),
) -> Dict[str, Any]:
    action = body.action.strip().lower()
    conn = _connect()
    try:
        token_hash = _admin_token_hash_from_reference(
            conn,
            token_ref=body.token_ref,
            token_prefix=body.token_prefix,
        )
        if action == "revoke":
            conn.execute(
                "UPDATE activation_tokens SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
                (_utc_now(), token_hash),
            )
            message = "Activation token revoked."
            extra: Dict[str, Any] = {}
        elif action == "reactivate":
            conn.execute("UPDATE activation_tokens SET revoked_at=NULL WHERE token_hash=?", (token_hash,))
            message = "Activation token restored."
            extra = {}
        elif action == "unbind":
            conn.execute(
                "UPDATE activation_tokens SET bound_install_id=NULL, last_seen=NULL WHERE token_hash=?",
                (token_hash,),
            )
            message = "Token binding cleared."
            extra = {}
        elif action == "delete":
            conn.execute("DELETE FROM activation_tokens WHERE token_hash=?", (token_hash,))
            message = "Activation token deleted."
            extra = {}
        elif action == "reset_counters":
            conn.execute(
                "DELETE FROM usage WHERE month=? AND subject_key=?",
                (_month_key(), f"managed:{token_hash}"),
            )
            message = "Counters reset for the selected activation token."
            extra = {}
        elif action == "rotate":
            row = conn.execute(
                "SELECT label, schedule_limit, radar_limit FROM activation_tokens WHERE token_hash=?",
                (token_hash,),
            ).fetchone()
            if not row:
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
                (new_hash, token[:10], username, token_hash),
            )
            conn.execute(
                "UPDATE usage SET subject_key=? WHERE subject_key=?",
                (f"managed:{new_hash}", f"managed:{token_hash}"),
            )
            message = "Activation token reshuffled. Copy the new token now; it is shown once."
            extra = {
                "activation_token": token,
                "token_prefix": token[:10],
                "action_ref": _admin_action_ref(conn, "tok", new_hash),
            }
        else:
            raise HTTPException(status_code=400, detail="Unknown token action")
        conn.commit()
        return _admin_action_response(message, operator=username, **extra)
    finally:
        conn.close()


@app.post("/admin/api/activation/request-action")
def admin_api_activation_request_action(
    body: AdminActivationRequestActionIn,
    username: str = Depends(_require_admin),
) -> Dict[str, Any]:
    action = body.action.strip().lower()
    request_id = body.request_id.strip()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM activation_requests WHERE request_id=?",
            (request_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Activation request not found")
        if action == "approve":
            if str(row["status"] or "") != _REQUEST_STATUS_MANUAL_REVIEW:
                return _admin_action_response("Activation row is no longer waiting for manual review.", operator=username)
            install_id = str(row["install_id"] or "").strip()
            label = str(row["display_name"] or row["install_fingerprint"] or "Managed install")
            schedule_limit, radar_limit = _activation_limits_for_requested_mode(str(row["requested_mode"] or ""))
            token, token_prefix, _issuance = _issue_token_for_install(
                conn,
                install_id=install_id,
                label=label,
                created_by=username,
                schedule_limit=schedule_limit,
                radar_limit=radar_limit,
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
                    request_id,
                ),
            )
            conn.commit()
            return _admin_action_response(
                "Managed access issued. Copy the token now; it is shown once.",
                operator=username,
                activation_token=token,
                token_prefix=token_prefix,
                action_ref=_admin_action_ref(conn, "tok", _token_hash(token)),
            )
        if action == "reject":
            now = _utc_now()
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
                    now,
                    now,
                    username,
                    body.decision_note.strip() or "dismissed",
                    request_id,
                ),
            )
            conn.commit()
            return _admin_action_response("Activation row dismissed.", operator=username)
        if action == "delete":
            conn.execute("DELETE FROM activation_requests WHERE request_id=?", (request_id,))
            conn.commit()
            return _admin_action_response("Activation request deleted.", operator=username)
        raise HTTPException(status_code=400, detail="Unknown activation request action")
    finally:
        conn.close()


@app.post("/admin/api/counters/reset")
def admin_api_reset_counters(
    body: AdminCounterResetIn,
    username: str = Depends(_require_admin),
) -> Dict[str, Any]:
    conn = _connect()
    month = _month_key()
    scope = body.scope.strip().lower()
    try:
        if scope == "all":
            conn.execute("DELETE FROM usage WHERE month=?", (month,))
            message = "Reset all monthly relay counters."
        elif scope == "service":
            service = body.service.strip().lower()
            if service not in {"aviationstack", "radar"}:
                raise HTTPException(status_code=400, detail="Unknown service")
            conn.execute("DELETE FROM usage WHERE month=? AND service=?", (month, service))
            message = f"Reset monthly counters for {service}."
        elif scope == "token":
            token_hash = _admin_token_hash_from_reference(
                conn,
                token_ref=body.token_ref,
                token_prefix=body.token_prefix,
            )
            conn.execute(
                "DELETE FROM usage WHERE month=? AND subject_key=?",
                (month, f"managed:{token_hash}"),
            )
            message = "Reset counters for the selected activation token."
        elif scope == "install":
            install_id = _admin_install_id_from_reference(
                conn,
                install_ref=body.install_ref,
                install_fingerprint=body.install_fingerprint,
            )
            if not install_id:
                raise HTTPException(status_code=404, detail="Install fingerprint not found")
            conn.execute("DELETE FROM usage WHERE month=? AND install_id=?", (month, install_id))
            message = "Reset counters for the selected install."
        elif scope == "logs":
            conn.execute("DELETE FROM request_log")
            message = "Cleared the network request log."
        else:
            raise HTTPException(status_code=400, detail="Unknown reset scope")
        conn.commit()
        return _admin_action_response(message, operator=username)
    finally:
        conn.close()


@app.post("/admin/api/counters/correct-schedule")
def admin_api_correct_schedule(
    body: AdminCounterCorrectIn,
    username: str = Depends(_require_admin),
) -> Dict[str, Any]:
    conn = _connect()
    month = _month_key()
    try:
        db_count = conn.execute(
            "SELECT COALESCE(SUM(calls), 0) FROM usage WHERE month=? AND service='aviationstack'",
            (month,),
        ).fetchone()[0] or 0
        offset = max(0, body.total - db_count)
        _setting_set_conn(conn, f"schedule_counter_offset:{month}", str(offset))
        conn.commit()
        return _admin_action_response(
            f"Schedule total corrected to {body.total:,}.",
            operator=username,
            month=month,
            offset=offset,
        )
    finally:
        conn.close()


@app.post("/admin/api/install/access")
def admin_api_install_access(
    body: AdminInstallAccessIn,
    username: str = Depends(_require_admin),
) -> Dict[str, Any]:
    action = body.action.strip().lower()
    conn = _connect()
    try:
        install_id = _admin_install_id_from_reference(
            conn,
            install_id=body.install_id,
            install_ref=body.install_ref,
            install_fingerprint=body.install_fingerprint,
        )
        if not install_id:
            raise HTTPException(status_code=400, detail="install reference required")

        if action == "block":
            conn.execute(
                """
                INSERT INTO blocked_installs (install_id, reason, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(install_id) DO UPDATE SET
                    reason = excluded.reason,
                    created_at = excluded.created_at
                """,
                (install_id, body.reason.strip() or "revoked by admin", _utc_now()),
            )
            message = "Install access revoked."
        elif action == "unblock":
            conn.execute("DELETE FROM blocked_installs WHERE install_id=?", (install_id,))
            message = "Install access restored."
        else:
            raise HTTPException(status_code=400, detail="Unknown install access action")
        conn.commit()
        return _admin_action_response(message, operator=username, install_fingerprint=_install_fingerprint(install_id))
    finally:
        conn.close()


@app.post("/admin/api/maintenance/clean-trial")
def admin_api_clean_trial_state(username: str = Depends(_require_admin)) -> Dict[str, Any]:
    conn = _connect()
    tables = (
        "request_log",
        "client_interests",
        "schedule_snapshots",
        "provider_schedule_snapshots",
        "provider_circuit_breakers",
        "airport_surface_snapshots",
        "activation_requests",
        "report_events",
        "report_dedupe",
    )
    deleted_total = 0
    try:
        for table in tables:
            row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            deleted_total += int(row["n"] or 0) if row else 0
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
        return _admin_action_response(
            "Cleaned transient setup-trial rows. Provider keys, tokens, blocked installs, and usage counters were kept.",
            operator=username,
            deleted_rows=deleted_total,
        )
    finally:
        conn.close()


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(username: str = Depends(_require_admin)) -> str:
    return _render_admin(username)


@app.post("/admin/api/logout")
def admin_api_logout() -> Response:
    # Rotate the realm so Chrome/Firefox/Edge drop the cached basic-auth credential
    # for the original realm. Safari may still cling — the signed-out page tells the
    # operator to close the tab if so.
    return Response(
        status_code=401,
        headers={"WWW-Authenticate": f'Basic realm="logout-{int(time.time())}"'},
    )


@app.get("/admin/signed-out", response_class=HTMLResponse)
def admin_signed_out() -> str:
    return _render_admin_signed_out()


@app.post("/admin/providers/save")
def admin_save_provider_keys(
    aerodatabox_key: str = Form(""),
    aviationstack_key: str = Form(""),
    rapidapi_key: str = Form(""),
    username: str = Depends(_require_admin),
) -> HTMLResponse:
    conn = _connect()
    changes: list[str] = []
    if aerodatabox_key.strip():
        _setting_set_conn(conn, _SETTING_AERODATABOX_KEY, aerodatabox_key.strip())
        changes.append("AeroDataBox")
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
        "aerodatabox": (_SETTING_AERODATABOX_KEY, "AeroDataBox"),
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
    schedule_limit, radar_limit = _activation_limits_for_requested_mode(str(row["requested_mode"] or ""))
    token, token_prefix, _issuance = _issue_token_for_install(
        conn,
        install_id=install_id,
        label=label,
        created_by=username,
        schedule_limit=schedule_limit,
        radar_limit=radar_limit,
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
    install_id: str = Form(""),
    install_ref: str = Form(""),
    reason: str = Form("revoked by admin"),
    username: str = Depends(_require_admin),
) -> HTMLResponse:
    conn = _connect()
    install_id = _admin_install_id_from_reference(conn, install_id=install_id, install_ref=install_ref)
    if not install_id:
        conn.close()
        raise HTTPException(status_code=400, detail="install reference required")
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
    install_id: str = Form(""),
    install_ref: str = Form(""),
    username: str = Depends(_require_admin),
) -> HTMLResponse:
    conn = _connect()
    install_id = _admin_install_id_from_reference(conn, install_id=install_id, install_ref=install_ref)
    if not install_id:
        conn.close()
        raise HTTPException(status_code=400, detail="install reference required")
    conn.execute("DELETE FROM blocked_installs WHERE install_id=?", (install_id,))
    conn.commit()
    conn.close()
    return HTMLResponse(_render_admin(username, message="Install access restored."))


@app.post("/admin/maintenance/clean-trial")
def admin_clean_trial_state(username: str = Depends(_require_admin)) -> HTMLResponse:
    """Clear transient operator-panel noise without resetting real quota counters."""
    conn = _connect()
    tables = (
        "request_log",
        "client_interests",
        "schedule_snapshots",
        "provider_schedule_snapshots",
        "provider_circuit_breakers",
        "airport_surface_snapshots",
        "activation_requests",
        "report_events",
        "report_dedupe",
    )
    deleted_total = 0
    for table in tables:
        row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
        deleted_total += int(row["n"] or 0) if row else 0
        conn.execute(f"DELETE FROM {table}")
    conn.commit()
    conn.close()
    return HTMLResponse(
        _render_admin(
            username,
            message=(
                f"Cleaned {deleted_total:,} transient setup-trial rows. "
                "Provider keys, activation tokens, blocked installs, and monthly usage counters were kept."
            ),
        )
    )


@app.post("/admin/counters/reset")
def admin_reset_counters(
    scope: str = Form(...),
    service: str = Form(""),
    token_hash: str = Form(""),
    install_id: str = Form(""),
    install_ref: str = Form(""),
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
        install_id = _admin_install_id_from_reference(conn, install_id=install_id, install_ref=install_ref)
        if not install_id:
            conn.close()
            raise HTTPException(status_code=400, detail="install reference required")
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
