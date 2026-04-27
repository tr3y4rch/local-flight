"""
localflight/storage/request_log.py

HTTP request log for the Traffic Hub.

Logs every incoming request to a local SQLite database so operators can
see who is hitting their local server — desktop browser tabs, mobile
companion app, matrix client, or direct API callers.

Schema:
  requests
    id          INTEGER PRIMARY KEY
    ts          TEXT     (ISO8601 UTC)
    method      TEXT     (GET / POST / …)
    path        TEXT
    status_code INTEGER
    latency_ms  INTEGER
    ip          TEXT     (anonymized network label)
    user_agent  TEXT     (coarse client family only)
    client_type TEXT     (desktop / mobile / matrix / api / unknown)

Retention: 7 days, pruned on every write.
"""
from __future__ import annotations

import ipaddress
import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

REQUEST_LOG_DAYS = 7

# Paths that generate too much noise to log
_SKIP_PREFIXES = (
    "/static/",
    "/logs/tail",
    "/api/admin/requests",
)
_SKIP_EXACT = {"/ws", "/health"}
_SAFE_PATH_RE = re.compile(r"[^A-Za-z0-9_./{}()=: -]")


def _db_path() -> Path:
    from localflight.storage.config import config_path
    return config_path().parent / "requests.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL,
            method      TEXT,
            path        TEXT,
            status_code INTEGER,
            latency_ms  INTEGER,
            ip          TEXT,
            user_agent  TEXT,
            client_type TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_req_ts     ON requests (ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_req_client ON requests (client_type, ts)")
    conn.commit()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _should_log(path: str) -> bool:
    if path in _SKIP_EXACT:
        return False
    for prefix in _SKIP_PREFIXES:
        if path.startswith(prefix):
            return False
    return True


def _client_type(user_agent: str, path: str) -> str:
    if "device=matrix" in path or "matrix" in path.lower():
        return "matrix"
    ua = (user_agent or "").lower()
    if any(tok in ua for tok in ("expo", "okhttp", "react-native", "dalvik")):
        return "mobile"
    if any(tok in ua for tok in ("chrome", "chromium", "firefox", "safari", "edge", "webkit", "gecko")):
        return "desktop"
    if path.startswith("/api/"):
        return "api"
    return "unknown"


def _anonymize_ip(ip: str) -> str:
    raw = (ip or "").strip()
    if not raw or raw.lower() == "unknown":
        return "unknown"
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return "unknown"
    if addr.is_loopback:
        return "local"
    if addr.version == 4:
        parts = raw.split(".")
        if addr.is_private:
            return f"{parts[0]}.{parts[1]}.{parts[2]}.x"
        return f"{parts[0]}.{parts[1]}.x.x"
    if addr.is_private:
        return ":".join(addr.exploded.split(":")[:4]) + "::"
    return ":".join(addr.exploded.split(":")[:3]) + "::"


def _user_agent_family(user_agent: str) -> str:
    ua = (user_agent or "").lower()
    if "localflight-matrix" in ua or "micropython" in ua:
        return "matrix"
    if any(tok in ua for tok in ("expo", "react-native", "okhttp", "dalvik")):
        return "mobile"
    if "edg/" in ua:
        return "edge"
    if "chrome" in ua or "chromium" in ua:
        return "chromium"
    if "firefox" in ua:
        return "firefox"
    if "safari" in ua or "webkit" in ua:
        return "safari"
    if ua:
        return "api-client"
    return "unknown"


def _safe_path(path: str) -> str:
    clean = (path or "/").split("?", 1)[0][:160]
    return _SAFE_PATH_RE.sub("_", clean)


def _sanitize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    safe = dict(row)
    safe["path"] = _safe_path(str(safe.get("path") or ""))
    safe["ip"] = _anonymize_ip(str(safe.get("ip") or ""))
    safe["user_agent"] = _user_agent_family(str(safe.get("user_agent") or ""))
    safe["method"] = str(safe.get("method") or "").upper()[:8]
    return safe


def log_request(
    method: str,
    path: str,
    status_code: int,
    latency_ms: int,
    ip: str,
    user_agent: str,
) -> None:
    if not _should_log(path):
        return
    safe_path = _safe_path(path)
    client_type = _client_type(user_agent, safe_path)
    ts = _utcnow().isoformat()
    cutoff = (_utcnow() - timedelta(days=REQUEST_LOG_DAYS)).isoformat()
    try:
        conn = _connect()
        _ensure_schema(conn)
        conn.execute(
            """INSERT INTO requests
               (ts, method, path, status_code, latency_ms, ip, user_agent, client_type)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                ts,
                method.upper()[:8],
                safe_path,
                status_code,
                latency_ms,
                _anonymize_ip(ip),
                _user_agent_family(user_agent),
                client_type,
            ),
        )
        conn.execute("DELETE FROM requests WHERE ts < ?", (cutoff,))
        conn.commit()
        conn.close()
    except Exception as exc:
        log.debug("Request log write failed (non-fatal): %s", exc)


def query_recent(
    *,
    hours: int = 24,
    limit: int = 200,
    client_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    try:
        conn = _connect()
        _ensure_schema(conn)
        cutoff = (_utcnow() - timedelta(hours=hours)).isoformat()
        params: list = [cutoff]
        sql = "SELECT * FROM requests WHERE ts >= ?"
        if client_type:
            sql += " AND client_type = ?"
            params.append(client_type)
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        rows = [_sanitize_row(dict(r)) for r in conn.execute(sql, params).fetchall()]
        conn.close()
        return rows
    except Exception as exc:
        log.warning("Request log query failed: %s", exc)
        return []


def query_summary(*, hours: int = 24) -> Dict[str, Any]:
    try:
        conn = _connect()
        _ensure_schema(conn)
        cutoff = (_utcnow() - timedelta(hours=hours)).isoformat()

        total = conn.execute(
            "SELECT COUNT(*) FROM requests WHERE ts >= ?", (cutoff,)
        ).fetchone()[0]

        by_client: Dict[str, int] = {}
        for row in conn.execute(
            "SELECT client_type, COUNT(*) as c FROM requests WHERE ts >= ? GROUP BY client_type",
            (cutoff,),
        ).fetchall():
            by_client[row[0]] = row[1]

        top_paths = [
            {"path": _safe_path(str(r["path"] or "")), "count": r["count"]}
            for r in conn.execute(
            """SELECT path, COUNT(*) as count
               FROM requests WHERE ts >= ?
               GROUP BY path ORDER BY count DESC LIMIT 10""",
            (cutoff,),
            ).fetchall()
        ]

        # Hourly buckets — oldest first (capped to hours, max 24 shown)
        n_buckets = min(hours, 24)
        now = _utcnow()
        hourly: List[int] = []
        for h in range(n_buckets - 1, -1, -1):
            b_start = (now - timedelta(hours=h + 1)).isoformat()
            b_end   = (now - timedelta(hours=h)).isoformat()
            count   = conn.execute(
                "SELECT COUNT(*) FROM requests WHERE ts >= ? AND ts < ?",
                (b_start, b_end),
            ).fetchone()[0]
            hourly.append(count)

        conn.close()
        return {
            "hours":    hours,
            "total":    total,
            "by_client": by_client,
            "top_paths": top_paths,
            "hourly":   hourly,
        }
    except Exception as exc:
        log.warning("Request log summary failed: %s", exc)
        return {"error": str(exc)}
