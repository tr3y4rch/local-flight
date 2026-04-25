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
) -> List[Dict[str, Any]]:
    """
    Return flights from the last N hours for an airport.
    direction: "DEP", "ARR", or None for both.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    params: list = [airport_iata, cutoff]

    sql = """
        SELECT * FROM flights
        WHERE airport_iata = ? AND snapshot_ts >= ?
    """
    if direction:
        sql    += " AND direction = ?"
        params.append(direction.upper())

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


def query_summary(airport_iata: str, hours: int = 720) -> Dict[str, Any]:
    """
    Aggregate stats for the history Stats tab.
    Returns top airlines, routes, aircraft types, on-time rate, avg delay.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    try:
        conn = _connect()
        _ensure_schema(conn)
        _migrate_schema(conn)

        def _top(sql: str) -> List[Dict[str, Any]]:
            return [dict(r) for r in conn.execute(sql, (airport_iata, cutoff)).fetchall()]

        top_airlines = _top("""
            SELECT airline_iata as code, COUNT(*) as count
            FROM flights
            WHERE airport_iata=? AND snapshot_ts>=? AND airline_iata IS NOT NULL AND airline_iata!=''
            GROUP BY airline_iata ORDER BY count DESC LIMIT 10
        """)
        top_destinations = _top("""
            SELECT dest_iata as code, COUNT(*) as count
            FROM flights
            WHERE airport_iata=? AND snapshot_ts>=? AND direction='DEP' AND dest_iata IS NOT NULL AND dest_iata!=''
            GROUP BY dest_iata ORDER BY count DESC LIMIT 10
        """)
        top_origins = _top("""
            SELECT origin_iata as code, COUNT(*) as count
            FROM flights
            WHERE airport_iata=? AND snapshot_ts>=? AND direction='ARR' AND origin_iata IS NOT NULL AND origin_iata!=''
            GROUP BY origin_iata ORDER BY count DESC LIMIT 10
        """)
        top_aircraft = _top("""
            SELECT aircraft_type, COUNT(*) as count
            FROM flights
            WHERE airport_iata=? AND snapshot_ts>=? AND aircraft_type IS NOT NULL AND aircraft_type!=''
            GROUP BY aircraft_type ORDER BY count DESC LIMIT 10
        """)

        total   = conn.execute("SELECT COUNT(*) FROM flights WHERE airport_iata=? AND snapshot_ts>=?", (airport_iata, cutoff)).fetchone()[0]
        delayed = conn.execute("SELECT COUNT(*) FROM flights WHERE airport_iata=? AND snapshot_ts>=? AND delay_minutes>=15", (airport_iata, cutoff)).fetchone()[0]
        avg_row = conn.execute("SELECT AVG(delay_minutes) FROM flights WHERE airport_iata=? AND snapshot_ts>=? AND delay_minutes>0", (airport_iata, cutoff)).fetchone()
        avg_delay = avg_row[0] if avg_row else None

        dep_count = conn.execute("SELECT COUNT(*) FROM flights WHERE airport_iata=? AND snapshot_ts>=? AND direction='DEP'", (airport_iata, cutoff)).fetchone()[0]
        arr_count = conn.execute("SELECT COUNT(*) FROM flights WHERE airport_iata=? AND snapshot_ts>=? AND direction='ARR'", (airport_iata, cutoff)).fetchone()[0]

        conn.close()

        return {
            "airport_iata":       airport_iata,
            "hours":              hours,
            "total":              total,
            "departures":         dep_count,
            "arrivals":           arr_count,
            "delayed":            delayed,
            "on_time_pct":        round((1 - delayed / total) * 100, 1) if total > 0 else None,
            "avg_delay_minutes":  round(avg_delay, 1) if avg_delay else None,
            "top_airlines":       top_airlines,
            "top_destinations":   top_destinations,
            "top_origins":        top_origins,
            "top_aircraft":       top_aircraft,
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