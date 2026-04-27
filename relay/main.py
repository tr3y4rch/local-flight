"""
Local Flight Community Relay

Forwards AviationStack flight requests on behalf of Local Flight installations
that have not supplied their own API key.

Endpoints:
  GET /v1/flights?install_id=UUID&dep_iata=ZRH&limit=50
      → quota check → forward to AviationStack → return response
      → adds X-LF-Quota-Used / X-LF-Quota-Limit headers

  GET /admin   (HTTP Basic Auth — admin only)
      → god hub: all installs, monthly call counts, recent requests

  GET /health  → {"ok": true}

Env vars:
  AVIATIONSTACK_API_KEY     required
  RELAY_ADMIN_PASSWORD      required (change from default)
  RELAY_MONTHLY_LIMIT       default 60
  DB_PATH                   default /data/relay.db
  PORT                      default 8080
"""
from __future__ import annotations

import os
import re
import secrets
import hashlib
import html
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests as _req
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pathlib import Path


# ── Config ─────────────────────────────────────────────────────────────────────

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()

def _aviationstack_key() -> str:
    k = _env("AVIATIONSTACK_API_KEY")
    if not k:
        raise RuntimeError("AVIATIONSTACK_API_KEY not set")
    return k

def _monthly_limit() -> int:
    try:
        return int(_env("RELAY_MONTHLY_LIMIT", "60"))
    except ValueError:
        return 60

def _admin_password() -> str:
    return _env("RELAY_ADMIN_PASSWORD", "changeme")

def _db_path() -> Path:
    return Path(_env("DB_PATH", "./relay.db"))


AVIATIONSTACK_URL = "https://api.aviationstack.com/v1/flights"
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_AIRPORT_RE = re.compile(r"^[A-Z0-9]{2,4}$")


# ── Database ───────────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _ensure_schema() -> None:
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS quota (
            install_id  TEXT NOT NULL,
            month       TEXT NOT NULL,
            calls       INTEGER DEFAULT 0,
            last_seen   TEXT,
            PRIMARY KEY (install_id, month)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS request_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL,
            install_id  TEXT,
            airport     TEXT,
            mode        TEXT,
            status      INTEGER,
            latency_ms  INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_quota_month ON quota (month, calls DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_log_ts ON request_log (ts)")
    conn.commit()
    conn.close()


def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _install_fingerprint(install_id: str) -> str:
    return hashlib.sha256(install_id.encode("utf-8")).hexdigest()[:12]


def _clean_airport(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    clean = value.strip().upper()
    if not _AIRPORT_RE.match(clean):
        raise HTTPException(status_code=400, detail="airport code must be 2-4 letters/numbers")
    return clean


def _get_calls(install_id: str, month: str) -> int:
    conn = _connect()
    row  = conn.execute(
        "SELECT calls FROM quota WHERE install_id=? AND month=?",
        (install_id, month),
    ).fetchone()
    conn.close()
    return row["calls"] if row else 0


def _increment_calls(install_id: str, month: str) -> int:
    """Increment counter and return the new total."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    conn.execute("""
        INSERT INTO quota (install_id, month, calls, last_seen) VALUES (?, ?, 1, ?)
        ON CONFLICT(install_id, month) DO UPDATE SET
            calls     = calls + 1,
            last_seen = excluded.last_seen
    """, (install_id, month, now))
    conn.commit()
    row = conn.execute(
        "SELECT calls FROM quota WHERE install_id=? AND month=?",
        (install_id, month),
    ).fetchone()
    conn.close()
    return row["calls"] if row else 1


def _log_request(
    install_id: str,
    airport: str,
    mode: str,
    status: int,
    latency_ms: int,
) -> None:
    try:
        conn = _connect()
        conn.execute(
            "INSERT INTO request_log (ts, install_id, airport, mode, status, latency_ms) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), install_id, airport, mode, status, latency_ms),
        )
        conn.execute(
            "DELETE FROM request_log WHERE ts < datetime('now', '-30 days')"
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── App ────────────────────────────────────────────────────────────────────────

app      = FastAPI(title="Local Flight Relay", docs_url=None, redoc_url=None)
security = HTTPBasic()


@app.on_event("startup")
def _startup() -> None:
    _db_path().parent.mkdir(parents=True, exist_ok=True)
    _ensure_schema()
    # Fail fast if the key is missing so Fly.io health check catches it
    try:
        _aviationstack_key()
    except RuntimeError as e:
        import logging
        logging.getLogger("relay").critical("STARTUP FAILED: %s", e)


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True}


# ── Relay endpoint ─────────────────────────────────────────────────────────────

@app.get("/v1/flights")
def relay_flights(
    dep_iata:   Optional[str] = Query(None),
    arr_iata:   Optional[str] = Query(None),
    limit:      int           = Query(10, ge=1, le=100),
    install_id: str           = Query(...),
) -> Response:
    if not _UUID_RE.match(install_id):
        raise HTTPException(status_code=400, detail="install_id must be a UUID")
    dep_iata = _clean_airport(dep_iata)
    arr_iata = _clean_airport(arr_iata)
    if not dep_iata and not arr_iata:
        raise HTTPException(status_code=400, detail="dep_iata or arr_iata is required")

    month    = _month_key()
    current  = _get_calls(install_id, month)
    cap      = _monthly_limit()

    if current >= cap:
        return JSONResponse(
            {
                "error": {
                    "code": "quota_exceeded",
                    "info": (
                        f"Community relay quota exceeded: {current}/{cap} calls used "
                        f"this month. Add AVIATIONSTACK_API_KEY to your Local Flight "
                        f".env for your own subscription."
                    ),
                }
            },
            status_code=429,
            headers={"X-LF-Quota-Used": str(current), "X-LF-Quota-Limit": str(cap)},
        )

    params: Dict[str, Any] = {"access_key": _aviationstack_key(), "limit": limit}
    if dep_iata:
        params["dep_iata"] = dep_iata
    if arr_iata:
        params["arr_iata"] = arr_iata

    airport = dep_iata or arr_iata or ""
    mode    = "dep" if dep_iata else "arr"

    t0 = time.monotonic()
    try:
        r = _req.get(
            AVIATIONSTACK_URL,
            params=params,
            headers={"User-Agent": "localflight-relay/1.0"},
            timeout=25,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
    except Exception as exc:
        _log_request(install_id, airport, mode, 0, 0)
        raise HTTPException(status_code=502, detail=f"AviationStack unreachable: {exc}")

    used = _increment_calls(install_id, month)
    _log_request(install_id, airport, mode, r.status_code, latency_ms)

    return Response(
        content    = r.content,
        status_code= r.status_code,
        media_type = "application/json",
        headers    = {
            "X-LF-Quota-Used":  str(used),
            "X-LF-Quota-Limit": str(cap),
        },
    )


# ── Admin dashboard ────────────────────────────────────────────────────────────

def _require_admin(
    creds: HTTPBasicCredentials = Depends(security),
) -> str:
    admin_pw = _admin_password()
    if not admin_pw or admin_pw == "changeme":
        raise HTTPException(status_code=503, detail="RELAY_ADMIN_PASSWORD is not configured")
    if not secrets.compare_digest(creds.password.encode(), admin_pw.encode()):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    return creds.username


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(username: str = Depends(_require_admin)) -> str:
    conn  = _connect()
    month = _month_key()

    total_installs = conn.execute(
        "SELECT COUNT(DISTINCT install_id) FROM quota WHERE month=?", (month,)
    ).fetchone()[0]

    total_calls = conn.execute(
        "SELECT COALESCE(SUM(calls), 0) FROM quota WHERE month=?", (month,)
    ).fetchone()[0]

    installs = [dict(r) for r in conn.execute(
        "SELECT install_id, calls, last_seen FROM quota WHERE month=? ORDER BY calls DESC LIMIT 200",
        (month,),
    ).fetchall()]

    recent = [dict(r) for r in conn.execute(
        "SELECT * FROM request_log ORDER BY ts DESC LIMIT 100",
    ).fetchall()]

    conn.close()

    def _install_rows() -> str:
        if not installs:
            return "<tr><td colspan='3' style='opacity:0.4;text-align:center;padding:20px'>No installs this month</td></tr>"
        return "".join(
            f"<tr>"
            f"<td style='font-family:monospace;font-size:0.85rem'>{_install_fingerprint(r['install_id'])}</td>"
            f"<td>{int(r['calls'] or 0)}</td>"
            f"<td style='opacity:0.5;font-size:0.78rem'>{html.escape((r['last_seen'] or '')[:16].replace('T',' '))}</td>"
            f"</tr>"
            for r in installs
        )

    def _recent_rows() -> str:
        if not recent:
            return "<tr><td colspan='6' style='opacity:0.4;text-align:center;padding:20px'>No requests yet</td></tr>"
        return "".join(
            f"<tr>"
            f"<td style='opacity:0.5;font-size:0.78rem'>{html.escape(r['ts'][:16].replace('T',' '))}</td>"
            f"<td style='font-family:monospace;font-size:0.85rem'>{_install_fingerprint(r['install_id'] or '')}</td>"
            f"<td>{html.escape(r['airport'] or '—')}</td>"
            f"<td>{html.escape(r['mode'] or '—')}</td>"
            f"<td style='color:{'#00c040' if (r['status'] or 0) < 300 else '#ff6060'}'>{r['status'] or '—'}</td>"
            f"<td style='opacity:0.5'>{int(r['latency_ms'] or 0)}ms</td>"
            f"</tr>"
            for r in recent
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Local Flight Relay — Admin</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:system-ui,sans-serif;background:#0d0d0d;color:#e0e0e0;padding:32px;line-height:1.5}}
  h1{{font-size:1.25rem;margin-bottom:4px}}
  .sub{{opacity:.4;font-size:.82rem;margin-bottom:28px}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px;margin-bottom:28px}}
  .card{{background:#181818;border:1px solid #272727;border-radius:10px;padding:14px 18px}}
  .card h2{{font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;opacity:.45;margin-bottom:8px}}
  .big{{font-size:2rem;font-weight:800;line-height:1}}
  h3{{font-size:.88rem;opacity:.55;text-transform:uppercase;letter-spacing:.05em;margin:24px 0 10px}}
  table{{width:100%;border-collapse:collapse;font-size:.83rem}}
  th{{text-align:left;padding:7px 10px;opacity:.4;font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid #222}}
  td{{padding:5px 10px;border-bottom:1px solid #1a1a1a}}
  tr:hover td{{background:#181818}}
</style>
</head>
<body>
<h1>✈ Local Flight Relay</h1>
<div class="sub">Admin · {html.escape(month)} · logged in as {html.escape(username)}</div>

<div class="grid">
  <div class="card"><h2>Active installs</h2><div class="big">{total_installs}</div></div>
  <div class="card"><h2>Calls this month</h2><div class="big">{total_calls}</div></div>
  <div class="card"><h2>Quota / install</h2><div class="big">{_monthly_limit()}</div></div>
  <div class="card"><h2>Relay</h2><div class="big" style="font-size:1.1rem;padding-top:6px">{'✓ key set' if _env('AVIATIONSTACK_API_KEY') else '✗ no key'}</div></div>
</div>

<h3>Installs — {html.escape(month)}</h3>
<table>
  <thead><tr><th>Install fingerprint</th><th>Calls</th><th>Last seen</th></tr></thead>
  <tbody>{_install_rows()}</tbody>
</table>

<h3>Recent requests (last 100)</h3>
<table>
  <thead><tr><th>Time</th><th>Install</th><th>Airport</th><th>Mode</th><th>Status</th><th>Latency</th></tr></thead>
  <tbody>{_recent_rows()}</tbody>
</table>
</body>
</html>"""


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host  = "0.0.0.0",
        port  = int(_env("PORT", "8080")),
        reload= False,
    )
