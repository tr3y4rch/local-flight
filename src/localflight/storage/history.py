"""
localflight/storage/history.py

Local SQLite flight history database.

Stores every flight snapshot for trend analysis, gate history,
and "what flew yesterday" queries.

Schema:
  flights
    id            INTEGER PRIMARY KEY
    airport_iata  TEXT
    callsign      TEXT
    flight_number TEXT
    origin_iata   TEXT
    dest_iata     TEXT
    direction     TEXT  (DEP / ARR)
    status        TEXT
    gate          TEXT
    terminal      TEXT
    aircraft_type TEXT
    sched_time    TEXT  (ISO8601 UTC)
    actual_time   TEXT  (ISO8601 UTC)
    lat           REAL
    lon           REAL
    altitude_m    REAL
    source        TEXT
    enriched_by   TEXT
    snapshot_ts   TEXT  (ISO8601 UTC — when this snapshot was taken)

Retention:
  Rows older than HISTORY_DAYS are pruned on each write.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from localflight.storage.config import AppConfig, config_path

log = logging.getLogger(__name__)

HISTORY_DAYS = 90  # keep 90 days of history


def _db_path() -> Path:
    return config_path().parent / "history.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # safe concurrent writes
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS flights (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            airport_iata  TEXT,
            callsign      TEXT,
            flight_number TEXT,
            origin_iata   TEXT,
            dest_iata     TEXT,
            direction     TEXT,
            status        TEXT,
            gate          TEXT,
            terminal      TEXT,
            aircraft_type TEXT,
            sched_time    TEXT,
            actual_time   TEXT,
            lat           REAL,
            lon           REAL,
            altitude_m    REAL,
            source        TEXT,
            enriched_by   TEXT,
            snapshot_ts   TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_airport_ts
        ON flights (airport_iata, snapshot_ts)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_callsign
        ON flights (callsign)
    """)
    conn.commit()


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Add columns that didn't exist in the original schema. Idempotent."""
    for col, typedef in [("delay_minutes", "INTEGER"), ("airline_iata", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE flights ADD COLUMN {col} {typedef}")
            conn.commit()
            log.info("History: added column %s", col)
        except sqlite3.OperationalError:
            pass  # column already exists


def _prune_old_rows(conn: sqlite3.Connection) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)).isoformat()
    cur    = conn.execute("DELETE FROM flights WHERE snapshot_ts < ?", (cutoff,))
    if cur.rowcount > 0:
        log.info("History: pruned %d rows older than %d days", cur.rowcount, HISTORY_DAYS)
    conn.commit()


def write_snapshot_to_history(flights: Any, cfg: AppConfig) -> None:
    """
    Write a list of Flight objects to the history database.
    Called by runtime.py after each successful fetch.
    Prunes old rows automatically.
    """
    if not flights:
        return

    snapshot_ts = datetime.now(timezone.utc).isoformat()

    try:
        conn = _connect()
        _ensure_schema(conn)
        _migrate_schema(conn)
        _prune_old_rows(conn)

        rows = []
        for f in flights:
            try:
                sched  = f.times.scheduled.isoformat()  if f.times.scheduled else None
                actual = f.times.actual.isoformat()      if f.times.actual    else None
                lat    = f.position.lat        if f.position else None
                lon    = f.position.lon        if f.position else None
                alt    = f.position.altitude_baro if f.position else None
                airline_iata = (f.airline.iata if f.airline else None)

                rows.append((
                    cfg.airport_iata,
                    f.callsign,
                    f.flight_number,
                    f.origin.iata      if f.origin      else None,
                    f.destination.iata if f.destination else None,
                    f.direction.value,
                    f.status.value,
                    f.gate,
                    f.terminal,
                    f.aircraft_type,
                    sched,
                    actual,
                    lat,
                    lon,
                    alt,
                    f.source,
                    f.enriched_by,
                    snapshot_ts,
                    f.delay_minutes,
                    airline_iata,
                ))
            except Exception as exc:
                log.debug("History: skipping malformed flight: %s", exc)

        conn.executemany("""
            INSERT INTO flights (
                airport_iata, callsign, flight_number,
                origin_iata, dest_iata, direction,
                status, gate, terminal, aircraft_type,
                sched_time, actual_time,
                lat, lon, altitude_m,
                source, enriched_by, snapshot_ts,
                delay_minutes, airline_iata
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, rows)

        conn.commit()
        conn.close()
        log.info("History: wrote %d flights for %s", len(rows), cfg.airport_iata)

    except Exception as exc:
        log.warning("History write error: %s", exc)


# ── Query helpers ──────────────────────────────────────────────────────────────

def query_recent(
    airport_iata: str,
    hours: int = 24,
    direction: Optional[str] = None,
    limit: int = 100,
    status: Optional[str] = None,
    callsign: Optional[str] = None,
    airline_iata: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Return flights from the last N hours for an airport.
    direction: "DEP", "ARR", or None for both.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    where, params = _history_where(
        airport_iata=airport_iata,
        cutoff=cutoff,
        direction=direction,
        status=status,
        callsign=callsign,
        airline_iata=airline_iata,
    )
    sql = f"SELECT * FROM flights WHERE {where}"
    sql += " ORDER BY sched_time DESC LIMIT ?"
    params.append(limit)

    try:
        conn = _connect()
        _ensure_schema(conn)
        _migrate_schema(conn)
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        conn.close()
        return rows
    except Exception as exc:
        log.warning("History query error: %s", exc)
        return []


def _clean_filter(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _history_where(
    *,
    airport_iata: str,
    cutoff: str,
    direction: Optional[str] = None,
    status: Optional[str] = None,
    callsign: Optional[str] = None,
    airline_iata: Optional[str] = None,
) -> tuple[str, list[Any]]:
    clauses = ["airport_iata = ?", "snapshot_ts >= ?"]
    params: list[Any] = [airport_iata, cutoff]

    direction_clean = _clean_filter(direction)
    if direction_clean and direction_clean.lower() not in {"both", "all"}:
        value = direction_clean.upper()
        if value.startswith("DEP"):
            clauses.append("direction = ?")
            params.append("DEP")
        elif value.startswith("ARR"):
            clauses.append("direction = ?")
            params.append("ARR")

    status_clean = _clean_filter(status)
    if status_clean and status_clean.lower() not in {"all", "all statuses"}:
        clauses.append("LOWER(COALESCE(status, '')) LIKE ?")
        params.append(f"%{status_clean.lower()}%")

    callsign_clean = _clean_filter(callsign)
    if callsign_clean:
        term = f"%{callsign_clean.upper()}%"
        clauses.append("(UPPER(COALESCE(callsign, '')) LIKE ? OR UPPER(COALESCE(flight_number, '')) LIKE ?)")
        params.extend([term, term])

    airline_clean = _clean_filter(airline_iata)
    if airline_clean:
        clauses.append("UPPER(COALESCE(airline_iata, '')) = ?")
        params.append(airline_clean.upper())

    return " AND ".join(clauses), params


def _pct(part: int | float | None, total: int | float | None) -> Optional[float]:
    if not part or not total:
        return 0.0 if total else None
    return round((float(part) / float(total)) * 100, 1)


def _delay_bucket_case() -> str:
    return """
        CASE
            WHEN delay_minutes IS NULL THEN 'unknown'
            WHEN delay_minutes <= -5 THEN 'early'
            WHEN delay_minutes BETWEEN -4 AND 4 THEN 'on_time'
            WHEN delay_minutes BETWEEN 5 AND 15 THEN 'delayed_warn'
            WHEN delay_minutes > 15 THEN 'delayed_bad'
            ELSE 'unknown'
        END
    """


def _bucket_label(bucket: str) -> str:
    return {
        "early": "Early",
        "on_time": "On time",
        "delayed_warn": "Delayed 5-15m",
        "delayed_bad": "Delayed >15m",
        "unknown": "Unknown",
    }.get(bucket, bucket.replace("_", " ").title())


def _status_label(status: str) -> str:
    cleaned = (status or "unknown").strip().replace("_", " ")
    return cleaned.title() if cleaned else "Unknown"


def query_flight_history(callsign: str, days: int = 7) -> List[Dict[str, Any]]:
    """Return all records for a specific callsign over the last N days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        conn  = _connect()
        _ensure_schema(conn)
        _migrate_schema(conn)
        rows  = [dict(r) for r in conn.execute(
            "SELECT * FROM flights WHERE callsign = ? AND snapshot_ts >= ? ORDER BY snapshot_ts DESC",
            (callsign.upper(), cutoff),
        ).fetchall()]
        conn.close()
        return rows
    except Exception as exc:
        log.warning("History query error: %s", exc)
        return []


def query_summary(
    airport_iata: str,
    hours: int = 720,
    direction: Optional[str] = None,
    status: Optional[str] = None,
    callsign: Optional[str] = None,
    airline_iata: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Aggregate stats for the history Stats tab.
    Returns top airlines, routes, aircraft types, on-time rate, avg delay.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    try:
        conn = _connect()
        _ensure_schema(conn)
        _migrate_schema(conn)
        where, params = _history_where(
            airport_iata=airport_iata,
            cutoff=cutoff,
            direction=direction,
            status=status,
            callsign=callsign,
            airline_iata=airline_iata,
        )

        def _rows(sql: str, extra: tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
            return [dict(r) for r in conn.execute(sql, tuple(params) + extra).fetchall()]

        def _one(sql: str, extra: tuple[Any, ...] = ()) -> Any:
            row = conn.execute(sql, tuple(params) + extra).fetchone()
            return row[0] if row else None

        total = int(_one(f"SELECT COUNT(*) FROM flights WHERE {where}") or 0)
        dep_count = int(_one(f"SELECT COUNT(*) FROM flights WHERE {where} AND direction='DEP'") or 0)
        arr_count = int(_one(f"SELECT COUNT(*) FROM flights WHERE {where} AND direction='ARR'") or 0)
        delayed = int(_one(f"SELECT COUNT(*) FROM flights WHERE {where} AND delay_minutes >= 5") or 0)
        on_time = int(_one(f"SELECT COUNT(*) FROM flights WHERE {where} AND delay_minutes BETWEEN -4 AND 4") or 0)
        avg_delay = _one(f"SELECT AVG(delay_minutes) FROM flights WHERE {where} AND delay_minutes > 0")

        bucket_rows = _rows(f"""
            SELECT {_delay_bucket_case()} AS bucket, COUNT(*) as count
            FROM flights
            WHERE {where}
            GROUP BY bucket
        """)
        bucket_counts = {str(row.get("bucket")): int(row.get("count") or 0) for row in bucket_rows}
        delay_buckets = []
        for bucket in ("early", "on_time", "delayed_warn", "delayed_bad", "unknown"):
            count = bucket_counts.get(bucket, 0)
            delay_buckets.append({
                "bucket": bucket,
                "label": _bucket_label(bucket),
                "count": count,
                "pct": _pct(count, total),
            })

        status_rows = _rows(f"""
            SELECT LOWER(COALESCE(NULLIF(status, ''), 'unknown')) as status, COUNT(*) as count
            FROM flights
            WHERE {where}
            GROUP BY LOWER(COALESCE(NULLIF(status, ''), 'unknown'))
            ORDER BY count DESC
        """)
        status_mix = [
            {
                "status": str(row.get("status") or "unknown"),
                "label": _status_label(str(row.get("status") or "unknown")),
                "count": int(row.get("count") or 0),
                "pct": _pct(int(row.get("count") or 0), total),
            }
            for row in status_rows
        ]

        top_airlines = _rows(f"""
            SELECT
                airline_iata as code,
                COUNT(*) as count,
                SUM(CASE WHEN delay_minutes >= 5 THEN 1 ELSE 0 END) as delayed_count,
                SUM(CASE WHEN delay_minutes BETWEEN -4 AND 4 THEN 1 ELSE 0 END) as on_time_count,
                AVG(CASE WHEN delay_minutes > 0 THEN delay_minutes END) as avg_delay_minutes
            FROM flights
            WHERE {where} AND airline_iata IS NOT NULL AND airline_iata!=''
            GROUP BY airline_iata ORDER BY count DESC LIMIT 10
        """)
        for row in top_airlines:
            count = int(row.get("count") or 0)
            row["delay_rate_pct"] = _pct(int(row.get("delayed_count") or 0), count)
            row["on_time_pct"] = _pct(int(row.get("on_time_count") or 0), count)
            avg = row.get("avg_delay_minutes")
            row["avg_delay_minutes"] = round(float(avg), 1) if avg is not None else None

        top_destinations = _rows(f"""
            SELECT dest_iata as code, COUNT(*) as count
            FROM flights
            WHERE {where} AND direction='DEP' AND dest_iata IS NOT NULL AND dest_iata!=''
            GROUP BY dest_iata ORDER BY count DESC LIMIT 10
        """)
        top_origins = _rows(f"""
            SELECT origin_iata as code, COUNT(*) as count
            FROM flights
            WHERE {where} AND direction='ARR' AND origin_iata IS NOT NULL AND origin_iata!=''
            GROUP BY origin_iata ORDER BY count DESC LIMIT 10
        """)
        top_aircraft = _rows(f"""
            SELECT aircraft_type, COUNT(*) as count
            FROM flights
            WHERE {where} AND aircraft_type IS NOT NULL AND aircraft_type!=''
            GROUP BY aircraft_type ORDER BY count DESC LIMIT 10
        """)

        top_routes = _rows(f"""
            SELECT
                origin_iata as origin,
                dest_iata as destination,
                direction,
                COUNT(*) as count,
                SUM(CASE WHEN delay_minutes >= 5 THEN 1 ELSE 0 END) as delayed_count
            FROM flights
            WHERE {where}
              AND origin_iata IS NOT NULL AND origin_iata!=''
              AND dest_iata IS NOT NULL AND dest_iata!=''
            GROUP BY origin_iata, dest_iata, direction
            ORDER BY count DESC LIMIT 10
        """)
        for row in top_routes:
            count = int(row.get("count") or 0)
            row["delay_rate_pct"] = _pct(int(row.get("delayed_count") or 0), count)

        daily_volume = _rows(f"""
            SELECT
                SUBSTR(COALESCE(sched_time, snapshot_ts), 1, 10) as date,
                SUM(CASE WHEN direction='DEP' THEN 1 ELSE 0 END) as departures,
                SUM(CASE WHEN direction='ARR' THEN 1 ELSE 0 END) as arrivals,
                COUNT(*) as total,
                SUM(CASE WHEN delay_minutes >= 5 THEN 1 ELSE 0 END) as delayed
            FROM flights
            WHERE {where} AND COALESCE(sched_time, snapshot_ts) IS NOT NULL
            GROUP BY date
            ORDER BY date ASC
        """)

        hourly_profile = _rows(f"""
            SELECT
                CAST(SUBSTR(COALESCE(sched_time, snapshot_ts), 12, 2) AS INTEGER) as hour,
                SUM(CASE WHEN direction='DEP' THEN 1 ELSE 0 END) as departures,
                SUM(CASE WHEN direction='ARR' THEN 1 ELSE 0 END) as arrivals,
                COUNT(*) as total,
                SUM(CASE WHEN delay_minutes >= 5 THEN 1 ELSE 0 END) as delayed
            FROM flights
            WHERE {where} AND COALESCE(sched_time, snapshot_ts) IS NOT NULL
            GROUP BY hour
            ORDER BY hour ASC
        """)

        conn.close()

        return {
            "airport_iata":       airport_iata,
            "hours":              hours,
            "total":              total,
            "departures":         dep_count,
            "arrivals":           arr_count,
            "delayed":            delayed,
            "delayed_pct":        _pct(delayed, total),
            "on_time_pct":        _pct(on_time, total),
            "avg_delay_minutes":  round(float(avg_delay), 1) if avg_delay is not None else None,
            "delay_buckets":      delay_buckets,
            "status_mix":         status_mix,
            "top_airlines":       top_airlines,
            "top_destinations":   top_destinations,
            "top_origins":        top_origins,
            "top_aircraft":       top_aircraft,
            "top_routes":         top_routes,
            "daily_volume":       daily_volume,
            "hourly_profile":     hourly_profile,
            "filters": {
                "direction": direction or "both",
                "status": status or "",
                "callsign": callsign or "",
                "airline_iata": airline_iata or "",
            },
        }
    except Exception as exc:
        log.warning("History summary error: %s", exc)
        return {"error": str(exc)}


def db_stats() -> Dict[str, Any]:
    """Return basic stats about the history database."""
    try:
        conn  = _connect()
        _ensure_schema(conn)
        _migrate_schema(conn)
        total = conn.execute("SELECT COUNT(*) FROM flights").fetchone()[0]
        oldest = conn.execute("SELECT MIN(snapshot_ts) FROM flights").fetchone()[0]
        newest = conn.execute("SELECT MAX(snapshot_ts) FROM flights").fetchone()[0]
        airports = [r[0] for r in conn.execute(
            "SELECT DISTINCT airport_iata FROM flights ORDER BY airport_iata"
        ).fetchall()]
        conn.close()
        size_mb = round(_db_path().stat().st_size / 1_048_576, 2) if _db_path().exists() else 0
        return {
            "total_rows":  total,
            "oldest":      oldest,
            "newest":      newest,
            "airports":    airports,
            "size_mb":     size_mb,
            "db_path":     str(_db_path()),
        }
    except Exception as exc:
        return {"error": str(exc)}
