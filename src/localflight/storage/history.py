"""
localflight/storage/history.py

Local SQLite flight history database.

History keeps two layers:
  flights
    Raw observations written after every successful fetched snapshot.

  history_movements
    Deduped user-facing movement facts. Repeated snapshots and linked
    codeshare aliases are collapsed into one movement while the raw
    observations remain available locally for diagnostics.

User-facing history windows are based on movement event_time, not snapshot
write time. A scheduled board row seen in a fresh snapshot only appears in
History once its scheduled/actual movement time is current or past.

Retention:
  Rows/movements older than HISTORY_DAYS are pruned on each write.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from localflight.storage.config import AppConfig, config_path

log = logging.getLogger(__name__)

HISTORY_DAYS = 90
HISTORY_FUTURE_GRACE_MINUTES = 30


def _db_path() -> Path:
    return config_path().parent / "history.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
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
        CREATE TABLE IF NOT EXISTS history_movements (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            movement_key      TEXT UNIQUE NOT NULL,
            airport_iata      TEXT,
            callsign          TEXT,
            flight_number     TEXT,
            operating_callsign TEXT,
            airline_iata      TEXT,
            origin_iata       TEXT,
            dest_iata         TEXT,
            direction         TEXT,
            status            TEXT,
            gate              TEXT,
            terminal          TEXT,
            aircraft_type     TEXT,
            sched_time        TEXT,
            actual_time       TEXT,
            event_time        TEXT,
            first_seen_ts     TEXT,
            last_seen_ts      TEXT,
            observation_count INTEGER DEFAULT 1,
            codeshares_json   TEXT,
            sold_as_json      TEXT,
            identity_source   TEXT,
            lat               REAL,
            lon               REAL,
            altitude_m        REAL,
            source            TEXT,
            enriched_by       TEXT,
            delay_minutes     INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_airport_ts ON flights (airport_iata, snapshot_ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_callsign ON flights (callsign)")
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_history_movements_airport_event
        ON history_movements (airport_iata, event_time)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_history_movements_identity
        ON history_movements (callsign, flight_number, operating_callsign)
    """)
    conn.commit()


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Add columns that did not exist in older history databases."""
    columns = [
        ("delay_minutes", "INTEGER"),
        ("airline_iata", "TEXT"),
        ("codeshares_json", "TEXT"),
        ("sold_as_json", "TEXT"),
        ("operating_callsign", "TEXT"),
        ("identity_source", "TEXT"),
        ("movement_key", "TEXT"),
        ("event_time", "TEXT"),
    ]
    for col, typedef in columns:
        try:
            conn.execute(f"ALTER TABLE flights ADD COLUMN {col} {typedef}")
            conn.commit()
            log.info("History: added column %s", col)
        except sqlite3.OperationalError:
            pass
    conn.execute("CREATE INDEX IF NOT EXISTS idx_flights_movement_key ON flights (movement_key)")
    conn.commit()
    _backfill_movements(conn)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _now().isoformat()


def _json_list(values: Iterable[Any] | None) -> str:
    cleaned: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return json.dumps(cleaned, separators=(",", ":"))


def _json_load_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    try:
        loaded = json.loads(str(value))
    except Exception:
        return []
    if not isinstance(loaded, list):
        return []
    return [str(item).strip() for item in loaded if str(item).strip()]


def _clean_identity(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


def _norm_code(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper()) or "-"


def _event_time(actual_time: Any, sched_time: Any, snapshot_ts: Any) -> str:
    return str(actual_time or sched_time or snapshot_ts or _iso_now())


def _time_bucket(event_time: str, snapshot_ts: Any) -> str:
    if event_time:
        return event_time[:16]
    fallback = str(snapshot_ts or "")
    return fallback[:13] if fallback else ""


def _service_date(event_time: str, snapshot_ts: Any) -> str:
    if event_time:
        return event_time[:10]
    fallback = str(snapshot_ts or "")
    return fallback[:10] if fallback else ""


def _identity_candidates(row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for field in ("callsign", "flight_number"):
        cleaned = _clean_identity(row.get(field))
        if cleaned and cleaned not in values:
            values.append(cleaned)
    for field in ("codeshares_json", "sold_as_json"):
        for alias in _json_load_list(row.get(field)):
            cleaned = _clean_identity(alias)
            if cleaned and cleaned not in values:
                values.append(cleaned)
    return values


def _movement_identity(row: dict[str, Any]) -> str:
    operating = _clean_identity(row.get("operating_callsign"))
    if operating:
        return operating
    candidates = _identity_candidates(row)
    if candidates:
        return sorted(candidates)[0]
    return f"OBS{_clean_identity(row.get('snapshot_ts'))}{row.get('id') or ''}"


def _movement_key(row: dict[str, Any]) -> str:
    event_time = _event_time(row.get("actual_time"), row.get("sched_time"), row.get("snapshot_ts"))
    identity = _movement_identity(row)
    parts = [
        _norm_code(row.get("airport_iata")),
        _norm_code(row.get("direction")),
        _norm_code(row.get("origin_iata")),
        _norm_code(row.get("dest_iata")),
        _service_date(event_time, row.get("snapshot_ts")),
        _time_bucket(event_time, row.get("snapshot_ts")),
        identity,
    ]
    return "|".join(parts)


def _canonical_row(row: dict[str, Any]) -> dict[str, Any]:
    event_time = _event_time(row.get("actual_time"), row.get("sched_time"), row.get("snapshot_ts"))
    movement_key = str(row.get("movement_key") or "").strip() or _movement_key(row)
    return {
        "movement_key": movement_key,
        "airport_iata": row.get("airport_iata"),
        "callsign": row.get("callsign"),
        "flight_number": row.get("flight_number"),
        "operating_callsign": row.get("operating_callsign"),
        "airline_iata": row.get("airline_iata"),
        "origin_iata": row.get("origin_iata"),
        "dest_iata": row.get("dest_iata"),
        "direction": row.get("direction"),
        "status": row.get("status"),
        "gate": row.get("gate"),
        "terminal": row.get("terminal"),
        "aircraft_type": row.get("aircraft_type"),
        "sched_time": row.get("sched_time"),
        "actual_time": row.get("actual_time"),
        "event_time": event_time,
        "first_seen_ts": row.get("snapshot_ts") or event_time,
        "last_seen_ts": row.get("snapshot_ts") or event_time,
        "codeshares_json": row.get("codeshares_json") or _json_list([]),
        "sold_as_json": row.get("sold_as_json") or _json_list([]),
        "identity_source": row.get("identity_source"),
        "lat": row.get("lat"),
        "lon": row.get("lon"),
        "altitude_m": row.get("altitude_m"),
        "source": row.get("source"),
        "enriched_by": row.get("enriched_by"),
        "delay_minutes": row.get("delay_minutes"),
    }


def _merge_alias_json(existing: Any, incoming: Any) -> str:
    merged: list[str] = []
    for value in _json_load_list(existing) + _json_load_list(incoming):
        if value and value not in merged:
            merged.append(value)
    return _json_list(merged)


def _upsert_movement(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    canonical = _canonical_row(row)
    existing = conn.execute(
        "SELECT codeshares_json, sold_as_json FROM history_movements WHERE movement_key = ?",
        (canonical["movement_key"],),
    ).fetchone()
    if existing:
        canonical["codeshares_json"] = _merge_alias_json(existing["codeshares_json"], canonical["codeshares_json"])
        canonical["sold_as_json"] = _merge_alias_json(existing["sold_as_json"], canonical["sold_as_json"])

    conn.execute(
        """
        INSERT INTO history_movements (
            movement_key, airport_iata, callsign, flight_number, operating_callsign,
            airline_iata, origin_iata, dest_iata, direction, status, gate, terminal,
            aircraft_type, sched_time, actual_time, event_time, first_seen_ts, last_seen_ts,
            observation_count, codeshares_json, sold_as_json, identity_source, lat, lon,
            altitude_m, source, enriched_by, delay_minutes
        ) VALUES (
            :movement_key, :airport_iata, :callsign, :flight_number, :operating_callsign,
            :airline_iata, :origin_iata, :dest_iata, :direction, :status, :gate, :terminal,
            :aircraft_type, :sched_time, :actual_time, :event_time, :first_seen_ts, :last_seen_ts,
            1, :codeshares_json, :sold_as_json, :identity_source, :lat, :lon,
            :altitude_m, :source, :enriched_by, :delay_minutes
        )
        ON CONFLICT(movement_key) DO UPDATE SET
            airport_iata = excluded.airport_iata,
            callsign = COALESCE(excluded.callsign, history_movements.callsign),
            flight_number = COALESCE(excluded.flight_number, history_movements.flight_number),
            operating_callsign = COALESCE(excluded.operating_callsign, history_movements.operating_callsign),
            airline_iata = COALESCE(excluded.airline_iata, history_movements.airline_iata),
            origin_iata = COALESCE(excluded.origin_iata, history_movements.origin_iata),
            dest_iata = COALESCE(excluded.dest_iata, history_movements.dest_iata),
            direction = COALESCE(excluded.direction, history_movements.direction),
            status = COALESCE(excluded.status, history_movements.status),
            gate = COALESCE(excluded.gate, history_movements.gate),
            terminal = COALESCE(excluded.terminal, history_movements.terminal),
            aircraft_type = COALESCE(excluded.aircraft_type, history_movements.aircraft_type),
            sched_time = COALESCE(excluded.sched_time, history_movements.sched_time),
            actual_time = COALESCE(excluded.actual_time, history_movements.actual_time),
            event_time = COALESCE(excluded.event_time, history_movements.event_time),
            first_seen_ts = MIN(COALESCE(history_movements.first_seen_ts, excluded.first_seen_ts), excluded.first_seen_ts),
            last_seen_ts = MAX(COALESCE(history_movements.last_seen_ts, excluded.last_seen_ts), excluded.last_seen_ts),
            observation_count = history_movements.observation_count + 1,
            codeshares_json = excluded.codeshares_json,
            sold_as_json = excluded.sold_as_json,
            identity_source = COALESCE(excluded.identity_source, history_movements.identity_source),
            lat = COALESCE(excluded.lat, history_movements.lat),
            lon = COALESCE(excluded.lon, history_movements.lon),
            altitude_m = COALESCE(excluded.altitude_m, history_movements.altitude_m),
            source = COALESCE(excluded.source, history_movements.source),
            enriched_by = COALESCE(excluded.enriched_by, history_movements.enriched_by),
            delay_minutes = COALESCE(excluded.delay_minutes, history_movements.delay_minutes)
        """,
        canonical,
    )


def _backfill_movements(conn: sqlite3.Connection) -> None:
    """Populate movement rows from old raw observations without deleting raw data."""
    try:
        raw_rows = conn.execute("""
            SELECT *
            FROM flights
            WHERE movement_key IS NULL
               OR movement_key = ''
               OR NOT EXISTS (
                    SELECT 1 FROM history_movements hm
                    WHERE hm.movement_key = flights.movement_key
               )
        """).fetchall()
    except sqlite3.OperationalError:
        return
    if not raw_rows:
        return

    changed = 0
    for sqlite_row in raw_rows:
        row = dict(sqlite_row)
        event_time = _event_time(row.get("actual_time"), row.get("sched_time"), row.get("snapshot_ts"))
        movement_key = _movement_key(row)
        row["event_time"] = event_time
        row["movement_key"] = movement_key
        _upsert_movement(conn, row)
        conn.execute(
            "UPDATE flights SET movement_key = ?, event_time = ? WHERE id = ?",
            (movement_key, event_time, row.get("id")),
        )
        changed += 1
    conn.commit()
    if changed:
        log.info("History: backfilled %d raw observations into movements", changed)


def _prune_old_rows(conn: sqlite3.Connection) -> None:
    cutoff = (_now() - timedelta(days=HISTORY_DAYS)).isoformat()
    raw = conn.execute("DELETE FROM flights WHERE snapshot_ts < ?", (cutoff,))
    movements = conn.execute(
        "DELETE FROM history_movements WHERE COALESCE(event_time, last_seen_ts, first_seen_ts) < ?",
        (cutoff,),
    )
    if raw.rowcount > 0 or movements.rowcount > 0:
        log.info(
            "History: pruned %d raw rows and %d movements older than %d days",
            raw.rowcount,
            movements.rowcount,
            HISTORY_DAYS,
        )
    conn.commit()


def write_snapshot_to_history(flights: Any, cfg: AppConfig) -> None:
    """
    Write a list of Flight objects to the history database.
    Raw observations are kept, while history_movements is upserted for all
    user-facing history views.
    """
    if not flights:
        return

    snapshot_ts = _iso_now()

    try:
        conn = _connect()
        _ensure_schema(conn)
        _migrate_schema(conn)
        _prune_old_rows(conn)

        inserted = 0
        for f in flights:
            try:
                sched = f.times.scheduled.isoformat() if f.times.scheduled else None
                actual = f.times.actual.isoformat() if f.times.actual else None
                lat = f.position.lat if f.position else None
                lon = f.position.lon if f.position else None
                alt = f.position.altitude_baro if f.position else None
                row = {
                    "airport_iata": cfg.airport_iata,
                    "callsign": f.callsign,
                    "flight_number": f.flight_number,
                    "origin_iata": f.origin.iata if f.origin else None,
                    "dest_iata": f.destination.iata if f.destination else None,
                    "direction": f.direction.value,
                    "status": f.status.value,
                    "gate": f.gate,
                    "terminal": f.terminal,
                    "aircraft_type": f.aircraft_type,
                    "sched_time": sched,
                    "actual_time": actual,
                    "lat": lat,
                    "lon": lon,
                    "altitude_m": alt,
                    "source": f.source,
                    "enriched_by": f.enriched_by,
                    "snapshot_ts": snapshot_ts,
                    "delay_minutes": f.delay_minutes,
                    "airline_iata": f.airline.iata if f.airline else None,
                    "codeshares_json": _json_list(getattr(f, "codeshares", [])),
                    "sold_as_json": _json_list(getattr(f, "sold_as", [])),
                    "operating_callsign": getattr(f, "operating_callsign", None),
                    "identity_source": getattr(f, "identity_source", None),
                }
                row["event_time"] = _event_time(row["actual_time"], row["sched_time"], row["snapshot_ts"])
                row["movement_key"] = _movement_key(row)

                cur = conn.execute(
                    """
                    INSERT INTO flights (
                        airport_iata, callsign, flight_number, origin_iata, dest_iata,
                        direction, status, gate, terminal, aircraft_type, sched_time,
                        actual_time, lat, lon, altitude_m, source, enriched_by,
                        snapshot_ts, delay_minutes, airline_iata, codeshares_json,
                        sold_as_json, operating_callsign, identity_source, movement_key, event_time
                    ) VALUES (
                        :airport_iata, :callsign, :flight_number, :origin_iata, :dest_iata,
                        :direction, :status, :gate, :terminal, :aircraft_type, :sched_time,
                        :actual_time, :lat, :lon, :altitude_m, :source, :enriched_by,
                        :snapshot_ts, :delay_minutes, :airline_iata, :codeshares_json,
                        :sold_as_json, :operating_callsign, :identity_source, :movement_key, :event_time
                    )
                    """,
                    row,
                )
                row["id"] = cur.lastrowid
                _upsert_movement(conn, row)
                inserted += 1
            except Exception as exc:
                log.debug("History: skipping malformed flight: %s", exc)

        conn.commit()
        conn.close()
        log.info("History: wrote %d observations for %s", inserted, cfg.airport_iata)

    except Exception as exc:
        log.warning("History write error: %s", exc)


# -- Query helpers -------------------------------------------------------------


def _clean_filter(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _window_bounds(hours: int) -> tuple[str, str]:
    now = _now()
    cutoff = (now - timedelta(hours=hours)).isoformat()
    upper = (now + timedelta(minutes=HISTORY_FUTURE_GRACE_MINUTES)).isoformat()
    return cutoff, upper


def _movement_where(
    *,
    airport_iata: str,
    cutoff: str,
    upper: str,
    direction: Optional[str] = None,
    status: Optional[str] = None,
    callsign: Optional[str] = None,
    airline_iata: Optional[str] = None,
) -> tuple[str, list[Any]]:
    clauses = ["airport_iata = ?", "event_time >= ?", "event_time <= ?"]
    params: list[Any] = [airport_iata, cutoff, upper]

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
        term = f"%{_clean_identity(callsign_clean)}%"
        clauses.append(
            "("
            "REPLACE(UPPER(COALESCE(callsign, '')), ' ', '') LIKE ? OR "
            "REPLACE(UPPER(COALESCE(flight_number, '')), ' ', '') LIKE ? OR "
            "REPLACE(UPPER(COALESCE(operating_callsign, '')), ' ', '') LIKE ? OR "
            "REPLACE(UPPER(COALESCE(codeshares_json, '')), ' ', '') LIKE ? OR "
            "REPLACE(UPPER(COALESCE(sold_as_json, '')), ' ', '') LIKE ?"
            ")"
        )
        params.extend([term, term, term, term, term])

    airline_clean = _clean_filter(airline_iata)
    if airline_clean:
        airline = airline_clean.upper()
        clauses.append(
            "("
            "UPPER(COALESCE(airline_iata, '')) = ? OR "
            "UPPER(COALESCE(flight_number, '')) LIKE ? OR "
            "UPPER(COALESCE(callsign, '')) LIKE ? OR "
            "REPLACE(UPPER(COALESCE(codeshares_json, '')), ' ', '') LIKE ? OR "
            "REPLACE(UPPER(COALESCE(sold_as_json, '')), ' ', '') LIKE ?"
            ")"
        )
        params.extend([airline, f"{airline}%", f"{airline}%", f"%{airline}%", f"%{airline}%"])

    return " AND ".join(clauses), params


def _movement_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    item = dict(row)
    item["snapshot_ts"] = item.get("last_seen_ts")
    item["codeshares"] = _json_load_list(item.pop("codeshares_json", None))
    item["sold_as"] = _json_load_list(item.pop("sold_as_json", None))
    item["raw_observation_rows"] = item.get("observation_count") or 0
    return item


def query_recent(
    airport_iata: str,
    hours: int = 24,
    direction: Optional[str] = None,
    limit: int = 100,
    status: Optional[str] = None,
    callsign: Optional[str] = None,
    airline_iata: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return deduped movements from the last N event hours for an airport."""
    cutoff, upper = _window_bounds(hours)
    where, params = _movement_where(
        airport_iata=airport_iata,
        cutoff=cutoff,
        upper=upper,
        direction=direction,
        status=status,
        callsign=callsign,
        airline_iata=airline_iata,
    )
    sql = f"""
        SELECT *
        FROM history_movements
        WHERE {where}
        ORDER BY event_time DESC, last_seen_ts DESC, COALESCE(flight_number, callsign, '') ASC
        LIMIT ?
    """
    params.append(limit)

    try:
        conn = _connect()
        _ensure_schema(conn)
        _migrate_schema(conn)
        rows = [_movement_to_dict(r) for r in conn.execute(sql, params).fetchall()]
        conn.close()
        return rows
    except Exception as exc:
        log.warning("History query error: %s", exc)
        return []


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
    """Return deduped movements for a callsign/flight number/known alias."""
    return _query_flight_history_any_airport(callsign, days)


def _query_flight_history_any_airport(callsign: str, days: int) -> List[Dict[str, Any]]:
    cutoff, upper = _window_bounds(days * 24)
    term = f"%{_clean_identity(callsign)}%"
    sql = """
        SELECT *
        FROM history_movements
        WHERE event_time >= ?
          AND event_time <= ?
          AND (
            REPLACE(UPPER(COALESCE(callsign, '')), ' ', '') LIKE ?
            OR REPLACE(UPPER(COALESCE(flight_number, '')), ' ', '') LIKE ?
            OR REPLACE(UPPER(COALESCE(operating_callsign, '')), ' ', '') LIKE ?
            OR REPLACE(UPPER(COALESCE(codeshares_json, '')), ' ', '') LIKE ?
            OR REPLACE(UPPER(COALESCE(sold_as_json, '')), ' ', '') LIKE ?
          )
        ORDER BY event_time DESC, last_seen_ts DESC
    """
    try:
        conn = _connect()
        _ensure_schema(conn)
        _migrate_schema(conn)
        rows = [
            _movement_to_dict(r)
            for r in conn.execute(sql, (cutoff, upper, term, term, term, term, term)).fetchall()
        ]
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
    """Aggregate movement stats for the History dashboard."""
    cutoff, upper = _window_bounds(hours)
    try:
        conn = _connect()
        _ensure_schema(conn)
        _migrate_schema(conn)
        where, params = _movement_where(
            airport_iata=airport_iata,
            cutoff=cutoff,
            upper=upper,
            direction=direction,
            status=status,
            callsign=callsign,
            airline_iata=airline_iata,
        )

        movement_source = f"(SELECT * FROM history_movements WHERE {where})"

        def _rows(sql: str, extra: tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
            return [dict(r) for r in conn.execute(sql, tuple(params) + extra).fetchall()]

        def _one(sql: str, extra: tuple[Any, ...] = ()) -> Any:
            row = conn.execute(sql, tuple(params) + extra).fetchone()
            return row[0] if row else None

        total = int(_one(f"SELECT COUNT(*) FROM {movement_source}") or 0)
        raw_observation_rows = int(_one(f"SELECT SUM(COALESCE(observation_count, 1)) FROM {movement_source}") or 0)
        dep_count = int(_one(f"SELECT COUNT(*) FROM {movement_source} WHERE direction='DEP'") or 0)
        arr_count = int(_one(f"SELECT COUNT(*) FROM {movement_source} WHERE direction='ARR'") or 0)
        delayed = int(_one(f"SELECT COUNT(*) FROM {movement_source} WHERE delay_minutes >= 5") or 0)
        on_time = int(_one(f"SELECT COUNT(*) FROM {movement_source} WHERE delay_minutes BETWEEN -4 AND 4") or 0)
        avg_delay = _one(f"SELECT AVG(delay_minutes) FROM {movement_source} WHERE delay_minutes > 0")

        bucket_rows = _rows(f"""
            SELECT {_delay_bucket_case()} AS bucket, COUNT(*) as count
            FROM {movement_source}
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
            FROM {movement_source}
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
            FROM {movement_source}
            WHERE airline_iata IS NOT NULL AND airline_iata!=''
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
            FROM {movement_source}
            WHERE direction='DEP' AND dest_iata IS NOT NULL AND dest_iata!=''
            GROUP BY dest_iata ORDER BY count DESC LIMIT 10
        """)
        top_origins = _rows(f"""
            SELECT origin_iata as code, COUNT(*) as count
            FROM {movement_source}
            WHERE direction='ARR' AND origin_iata IS NOT NULL AND origin_iata!=''
            GROUP BY origin_iata ORDER BY count DESC LIMIT 10
        """)
        top_aircraft = _rows(f"""
            SELECT aircraft_type, COUNT(*) as count
            FROM {movement_source}
            WHERE aircraft_type IS NOT NULL AND aircraft_type!=''
            GROUP BY aircraft_type ORDER BY count DESC LIMIT 10
        """)

        top_routes = _rows(f"""
            SELECT
                origin_iata as origin,
                dest_iata as destination,
                direction,
                COUNT(*) as count,
                SUM(CASE WHEN delay_minutes >= 5 THEN 1 ELSE 0 END) as delayed_count
            FROM {movement_source}
            WHERE origin_iata IS NOT NULL AND origin_iata!=''
              AND dest_iata IS NOT NULL AND dest_iata!=''
            GROUP BY origin_iata, dest_iata, direction
            ORDER BY count DESC LIMIT 10
        """)
        for row in top_routes:
            count = int(row.get("count") or 0)
            row["delay_rate_pct"] = _pct(int(row.get("delayed_count") or 0), count)

        daily_volume = _rows(f"""
            SELECT
                SUBSTR(event_time, 1, 10) as date,
                SUM(CASE WHEN direction='DEP' THEN 1 ELSE 0 END) as departures,
                SUM(CASE WHEN direction='ARR' THEN 1 ELSE 0 END) as arrivals,
                COUNT(*) as total,
                SUM(CASE WHEN delay_minutes >= 5 THEN 1 ELSE 0 END) as delayed
            FROM {movement_source}
            WHERE event_time IS NOT NULL
            GROUP BY date
            ORDER BY date ASC
        """)

        hourly_profile = _rows(f"""
            SELECT
                CAST(SUBSTR(event_time, 12, 2) AS INTEGER) as hour,
                SUM(CASE WHEN direction='DEP' THEN 1 ELSE 0 END) as departures,
                SUM(CASE WHEN direction='ARR' THEN 1 ELSE 0 END) as arrivals,
                COUNT(*) as total,
                SUM(CASE WHEN delay_minutes >= 5 THEN 1 ELSE 0 END) as delayed
            FROM {movement_source}
            WHERE event_time IS NOT NULL
            GROUP BY hour
            ORDER BY hour ASC
        """)

        conn.close()

        return {
            "airport_iata": airport_iata,
            "hours": hours,
            "total": total,
            "movement_count": total,
            "sample_rows": raw_observation_rows,
            "raw_observation_rows": raw_observation_rows,
            "departures": dep_count,
            "arrivals": arr_count,
            "delayed": delayed,
            "delayed_pct": _pct(delayed, total),
            "on_time_pct": _pct(on_time, total),
            "avg_delay_minutes": round(float(avg_delay), 1) if avg_delay is not None else None,
            "delay_buckets": delay_buckets,
            "status_mix": status_mix,
            "top_airlines": top_airlines,
            "top_destinations": top_destinations,
            "top_origins": top_origins,
            "top_aircraft": top_aircraft,
            "top_routes": top_routes,
            "daily_volume": daily_volume,
            "hourly_profile": hourly_profile,
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
        conn = _connect()
        _ensure_schema(conn)
        _migrate_schema(conn)
        total = conn.execute("SELECT COUNT(*) FROM flights").fetchone()[0]
        total_movements = conn.execute("SELECT COUNT(*) FROM history_movements").fetchone()[0]
        oldest = conn.execute("SELECT MIN(snapshot_ts) FROM flights").fetchone()[0]
        newest = conn.execute("SELECT MAX(snapshot_ts) FROM flights").fetchone()[0]
        oldest_movement = conn.execute("SELECT MIN(event_time) FROM history_movements").fetchone()[0]
        newest_movement = conn.execute("SELECT MAX(event_time) FROM history_movements").fetchone()[0]
        airports = [r[0] for r in conn.execute(
            "SELECT DISTINCT airport_iata FROM history_movements ORDER BY airport_iata"
        ).fetchall()]
        if not airports:
            airports = [r[0] for r in conn.execute(
                "SELECT DISTINCT airport_iata FROM flights ORDER BY airport_iata"
            ).fetchall()]
        conn.close()
        size_mb = round(_db_path().stat().st_size / 1_048_576, 2) if _db_path().exists() else 0
        return {
            "total_rows": total,
            "total_movements": total_movements,
            "oldest": oldest,
            "newest": newest,
            "oldest_movement": oldest_movement,
            "newest_movement": newest_movement,
            "airports": airports,
            "size_mb": size_mb,
            "db_path": str(_db_path()),
        }
    except Exception as exc:
        return {"error": str(exc)}
