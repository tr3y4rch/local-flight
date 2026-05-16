import * as SQLite from "expo-sqlite";

import type {
  FidsRow,
  HistoryDirection,
  HistoryFlightRow,
  HistoryResponse,
  HistorySummary
} from "../api/types";
import type { StandaloneAirport } from "./settings";

type StoredHistoryRow = {
  id: number;
  snapshot_ts: string;
  airport_iata: string;
  view: string;
  callsign: string;
  flight_number: string | null;
  airline_iata: string | null;
  route_code: string | null;
  status: string;
  gate: string | null;
  terminal: string | null;
  aircraft_type: string | null;
  sched_time: string | null;
  delay_minutes: number | null;
  row_json: string;
};

let dbPromise: Promise<SQLite.SQLiteDatabase> | null = null;

async function db(): Promise<SQLite.SQLiteDatabase> {
  if (!dbPromise) {
    dbPromise = SQLite.openDatabaseAsync("localflight_standalone_history.db").then(async (database) => {
      await database.execAsync(`
        PRAGMA journal_mode = WAL;
        CREATE TABLE IF NOT EXISTS standalone_fids_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          snapshot_ts TEXT NOT NULL,
          airport_iata TEXT NOT NULL,
          view TEXT NOT NULL,
          callsign TEXT NOT NULL,
          flight_number TEXT,
          airline_iata TEXT,
          route_code TEXT,
          status TEXT,
          gate TEXT,
          terminal TEXT,
          aircraft_type TEXT,
          sched_time TEXT,
          delay_minutes INTEGER,
          row_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_standalone_history_seen ON standalone_fids_history (snapshot_ts DESC);
        CREATE INDEX IF NOT EXISTS idx_standalone_history_callsign ON standalone_fids_history (callsign);
      `);
      return database;
    });
  }
  return dbPromise;
}

function directionForView(view: string): "dep" | "arr" {
  return view === "arrivals" ? "arr" : "dep";
}

function nowIso(): string {
  return new Date().toISOString();
}

function cutoffIso(days = 30): string {
  return new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
}

async function pruneHistory(database: SQLite.SQLiteDatabase): Promise<void> {
  await database.runAsync("DELETE FROM standalone_fids_history WHERE snapshot_ts < ?", cutoffIso(30));
  await database.runAsync(`
    DELETE FROM standalone_fids_history
    WHERE id NOT IN (
      SELECT id FROM standalone_fids_history ORDER BY snapshot_ts DESC, id DESC LIMIT 1000
    )
  `);
}

export async function storeStandaloneFidsRows(
  airport: StandaloneAirport,
  rows: FidsRow[],
  snapshotTs = nowIso()
): Promise<void> {
  if (!rows.length) return;
  const database = await db();
  await database.withExclusiveTransactionAsync(async (txn) => {
    for (const row of rows) {
      await txn.runAsync(
        `
        INSERT INTO standalone_fids_history (
          snapshot_ts, airport_iata, view, callsign, flight_number, airline_iata,
          route_code, status, gate, terminal, aircraft_type, sched_time, delay_minutes, row_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        `,
        snapshotTs,
        airport.iata,
        String(row.view || "departures"),
        String(row.callsign || row.id || row.flight_display || "UNKNOWN").toUpperCase(),
        row.flight_number || row.flight_display || null,
        row.airline_iata || null,
        row.route_code || null,
        row.status_display || row.status_kind || "scheduled",
        row.gate_display || row.gate || null,
        row.terminal_display || null,
        row.aircraft_type || null,
        row.time_primary || row.display_time || null,
        typeof row.delay_minutes === "number" ? row.delay_minutes : null,
        JSON.stringify(row)
      );
    }
  });
  await pruneHistory(database);
}

function rowMatchesFilters(row: StoredHistoryRow, callsign: string, airline: string): boolean {
  if (callsign && !String(row.callsign || "").includes(callsign.toUpperCase())) return false;
  if (airline && String(row.airline_iata || "").toUpperCase() !== airline.toUpperCase()) return false;
  return true;
}

function storedToHistory(row: StoredHistoryRow): HistoryFlightRow {
  const view = String(row.view || "departures");
  const route = String(row.route_code || "");
  return {
    id: row.id,
    airport_iata: row.airport_iata,
    callsign: row.callsign,
    flight_number: row.flight_number,
    origin_iata: view === "arrivals" ? route : row.airport_iata,
    dest_iata: view === "departures" ? route : row.airport_iata,
    direction: directionForView(view),
    status: row.status || "scheduled",
    gate: row.gate,
    terminal: row.terminal,
    aircraft_type: row.aircraft_type,
    sched_time: row.sched_time,
    actual_time: null,
    source: "mobile_standalone",
    enriched_by: "relay",
    snapshot_ts: row.snapshot_ts,
    delay_minutes: row.delay_minutes,
    airline_iata: row.airline_iata
  };
}

export async function getStandaloneHistory(
  airport: StandaloneAirport,
  {
    hours = 24,
    direction = "both",
    limit = 120,
    callsign = "",
    airline_iata = ""
  }: {
    hours?: number;
    direction?: HistoryDirection;
    limit?: number;
    callsign?: string;
    airline_iata?: string;
  } = {}
): Promise<HistoryResponse> {
  const database = await db();
  const since = new Date(Date.now() - Math.max(1, hours) * 60 * 60 * 1000).toISOString();
  const directionWhere = direction === "dep"
    ? "AND view = 'departures'"
    : direction === "arr"
      ? "AND view = 'arrivals'"
      : "";
  const rows = await database.getAllAsync<StoredHistoryRow>(
    `
    SELECT *
    FROM standalone_fids_history
    WHERE airport_iata = ? AND snapshot_ts >= ? ${directionWhere}
    ORDER BY snapshot_ts DESC, id DESC
    LIMIT ?
    `,
    airport.iata,
    since,
    Math.max(1, Math.min(1000, limit * 2))
  );
  const filtered = rows
    .filter((row) => rowMatchesFilters(row, callsign, airline_iata))
    .slice(0, limit)
    .map(storedToHistory);
  return {
    airport_iata: airport.iata,
    hours,
    count: filtered.length,
    flights: filtered
  };
}

export async function getStandaloneHistorySummary(
  airport: StandaloneAirport,
  {
    hours = 24,
    direction = "both",
    callsign = "",
    airline_iata = ""
  }: {
    hours?: number;
    direction?: HistoryDirection;
    callsign?: string;
    airline_iata?: string;
  } = {}
): Promise<HistorySummary> {
  const history = await getStandaloneHistory(airport, {
    hours,
    direction,
    callsign,
    airline_iata,
    limit: 1000
  });
  const rows = history.flights;
  const departures = rows.filter((row) => row.direction === "dep").length;
  const arrivals = rows.filter((row) => row.direction === "arr").length;
  const delayed = rows.filter((row) => (row.delay_minutes || 0) > 5 || /delay/i.test(row.status || "")).length;
  const avgDelaySource = rows
    .map((row) => row.delay_minutes)
    .filter((value): value is number => typeof value === "number");
  const avgDelay = avgDelaySource.length
    ? Math.round(avgDelaySource.reduce((sum, value) => sum + value, 0) / avgDelaySource.length)
    : null;
  return {
    airport_iata: airport.iata,
    hours,
    total: rows.length,
    sample_rows: rows.length,
    departures,
    arrivals,
    delayed,
    delayed_pct: rows.length ? Math.round((delayed / rows.length) * 100) : 0,
    on_time_pct: rows.length ? Math.round(((rows.length - delayed) / rows.length) * 100) : 0,
    avg_delay_minutes: avgDelay,
    delay_buckets: [],
    status_mix: [],
    top_airlines: [],
    top_routes: [],
    top_aircraft: [],
    daily_volume: []
  };
}

export async function clearStandaloneHistory(): Promise<void> {
  const database = await db();
  await database.runAsync("DELETE FROM standalone_fids_history");
}
