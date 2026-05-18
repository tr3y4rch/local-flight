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
  movement_key: string;
  snapshot_ts: string;
  event_time: string;
  first_seen_ts: string;
  last_seen_ts: string;
  observation_count: number;
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
  actual_time: string | null;
  delay_minutes: number | null;
  codeshares_json: string | null;
  sold_as_json: string | null;
  operating_callsign: string | null;
  identity_source: string | null;
  row_json: string;
};

type StoredInsert = {
  movementKey: string;
  snapshotTs: string;
  eventTime: string;
  airportIata: string;
  view: string;
  callsign: string;
  flightNumber: string | null;
  airlineIata: string | null;
  routeCode: string | null;
  status: string;
  gate: string | null;
  terminal: string | null;
  aircraftType: string | null;
  schedTime: string | null;
  actualTime: string | null;
  delayMinutes: number | null;
  codesharesJson: string;
  soldAsJson: string;
  operatingCallsign: string | null;
  identitySource: string | null;
  rowJson: string;
};

let dbPromise: Promise<SQLite.SQLiteDatabase> | null = null;

async function db(): Promise<SQLite.SQLiteDatabase> {
  if (!dbPromise) {
    dbPromise = SQLite.openDatabaseAsync("localflight_standalone_history.db").then(async (database) => {
      await database.execAsync(`
        PRAGMA journal_mode = WAL;
        CREATE TABLE IF NOT EXISTS standalone_fids_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          movement_key TEXT,
          snapshot_ts TEXT NOT NULL,
          event_time TEXT,
          first_seen_ts TEXT,
          last_seen_ts TEXT,
          observation_count INTEGER DEFAULT 1,
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
          actual_time TEXT,
          delay_minutes INTEGER,
          codeshares_json TEXT,
          sold_as_json TEXT,
          operating_callsign TEXT,
          identity_source TEXT,
          row_json TEXT NOT NULL
        );
      `);
      await ensureHistoryMigrations(database);
      await backfillLegacyMovements(database);
      await database.execAsync(`
        CREATE UNIQUE INDEX IF NOT EXISTS idx_standalone_history_movement
          ON standalone_fids_history (movement_key);
        CREATE INDEX IF NOT EXISTS idx_standalone_history_event
          ON standalone_fids_history (airport_iata, event_time DESC);
        CREATE INDEX IF NOT EXISTS idx_standalone_history_seen
          ON standalone_fids_history (last_seen_ts DESC);
        CREATE INDEX IF NOT EXISTS idx_standalone_history_callsign
          ON standalone_fids_history (callsign);
      `);
      return database;
    });
  }
  return dbPromise;
}

async function ensureHistoryMigrations(database: SQLite.SQLiteDatabase): Promise<void> {
  const columns = await database.getAllAsync<{ name: string }>("PRAGMA table_info(standalone_fids_history)");
  const existing = new Set(columns.map((column) => column.name));
  const additions: Array<[string, string]> = [
    ["movement_key", "TEXT"],
    ["event_time", "TEXT"],
    ["first_seen_ts", "TEXT"],
    ["last_seen_ts", "TEXT"],
    ["observation_count", "INTEGER DEFAULT 1"],
    ["actual_time", "TEXT"],
    ["codeshares_json", "TEXT"],
    ["sold_as_json", "TEXT"],
    ["operating_callsign", "TEXT"],
    ["identity_source", "TEXT"]
  ];
  for (const [name, definition] of additions) {
    if (!existing.has(name)) {
      await database.runAsync(`ALTER TABLE standalone_fids_history ADD COLUMN ${name} ${definition}`);
    }
  }
  await database.runAsync(`
    UPDATE standalone_fids_history
    SET event_time = COALESCE(event_time, sched_time, snapshot_ts),
        first_seen_ts = COALESCE(first_seen_ts, snapshot_ts),
        last_seen_ts = COALESCE(last_seen_ts, snapshot_ts),
        observation_count = COALESCE(observation_count, 1)
    WHERE event_time IS NULL OR first_seen_ts IS NULL OR last_seen_ts IS NULL OR observation_count IS NULL
  `);
}

async function backfillLegacyMovements(database: SQLite.SQLiteDatabase): Promise<void> {
  const rows = await database.getAllAsync<StoredHistoryRow>(`
    SELECT *
    FROM standalone_fids_history
    WHERE movement_key IS NULL OR movement_key = ''
    ORDER BY snapshot_ts ASC, id ASC
  `);
  for (const row of rows) {
    const eventTime = row.event_time || row.sched_time || row.snapshot_ts;
    const identity = cleanIdentity(row.operating_callsign || row.callsign || row.flight_number) || cleanIdentity(String(row.id));
    const route = String(row.route_code || "").toUpperCase().replace(/[^A-Z0-9]+/g, "") || "-";
    const direction = directionForView(row.view).toUpperCase();
    const origin = row.view === "arrivals" ? route : row.airport_iata;
    const destination = row.view === "departures" ? route : row.airport_iata;
    const movementKey = [
      row.airport_iata,
      direction,
      origin || "-",
      destination || "-",
      eventTime.slice(0, 10),
      eventTime.slice(0, 16),
      identity
    ].join("|");
    const existing = await database.getFirstAsync<{ id: number; observation_count: number | null }>(
      "SELECT id, observation_count FROM standalone_fids_history WHERE movement_key = ? AND id != ?",
      movementKey,
      row.id
    );
    if (existing?.id) {
      await database.runAsync(
        `
        UPDATE standalone_fids_history
        SET last_seen_ts = MAX(COALESCE(last_seen_ts, snapshot_ts), ?),
            observation_count = COALESCE(observation_count, 1) + 1
        WHERE id = ?
        `,
        row.last_seen_ts || row.snapshot_ts,
        existing.id
      );
      await database.runAsync("DELETE FROM standalone_fids_history WHERE id = ?", row.id);
    } else {
      await database.runAsync(
        `
        UPDATE standalone_fids_history
        SET movement_key = ?,
            event_time = COALESCE(event_time, sched_time, snapshot_ts),
            first_seen_ts = COALESCE(first_seen_ts, snapshot_ts),
            last_seen_ts = COALESCE(last_seen_ts, snapshot_ts),
            observation_count = COALESCE(observation_count, 1)
        WHERE id = ?
        `,
        movementKey,
        row.id
      );
    }
  }
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

function upperBoundIso(): string {
  return new Date(Date.now() + 30 * 60 * 1000).toISOString();
}

function jsonList(values?: readonly unknown[]): string {
  const cleaned: string[] = [];
  for (const value of values || []) {
    const text = String(value || "").trim();
    if (text && !cleaned.includes(text)) cleaned.push(text);
  }
  return JSON.stringify(cleaned);
}

function parseJsonList(value?: string | null): string[] {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.map((item) => String(item || "").trim()).filter(Boolean) : [];
  } catch {
    return [];
  }
}

function cleanIdentity(value?: unknown): string {
  return String(value || "").toUpperCase().replace(/[^A-Z0-9]+/g, "");
}

function field(row: FidsRow, key: string): string | null {
  const value = (row as FidsRow & Record<string, unknown>)[key];
  const text = String(value || "").trim();
  return text || null;
}

function isoFromValue(value: string | null | undefined, snapshotTs: string): string | null {
  const text = String(value || "").trim();
  if (!text) return null;
  if (/^\d{4}-\d{2}-\d{2}T/.test(text)) return text;
  const match = text.match(/(\d{1,2}):(\d{2})/);
  if (!match) return null;
  const hour = (match[1] || "0").padStart(2, "0");
  const minute = (match[2] || "0").padStart(2, "0");
  return `${snapshotTs.slice(0, 10)}T${hour}:${minute}:00.000Z`;
}

function eventTimeForRow(row: FidsRow, snapshotTs: string): { eventTime: string; schedTime: string | null; actualTime: string | null } {
  const actualTime = isoFromValue(field(row, "actual_time"), snapshotTs);
  const schedTime = isoFromValue(field(row, "sched_time") || row.time_primary || row.display_time, snapshotTs);
  return {
    eventTime: actualTime || schedTime || snapshotTs,
    schedTime,
    actualTime
  };
}

function movementKeyForRow(
  airport: StandaloneAirport,
  row: FidsRow,
  snapshotTs: string,
  eventTime: string,
  view: string
): string {
  const route = String(row.route_code || "").toUpperCase().replace(/[^A-Z0-9]+/g, "") || "-";
  const direction = directionForView(view).toUpperCase();
  const origin = view === "arrivals" ? route : airport.iata;
  const destination = view === "departures" ? route : airport.iata;
  const operating = cleanIdentity(row.operating_callsign);
  const aliases = [
    row.callsign,
    row.flight_number,
    row.flight_display,
    ...(row.codeshares || []),
    ...(row.sold_as || [])
  ].map(cleanIdentity).filter(Boolean).sort();
  const identity = operating || aliases[0] || cleanIdentity(row.id) || cleanIdentity(snapshotTs);
  return [
    airport.iata,
    direction,
    origin || "-",
    destination || "-",
    eventTime.slice(0, 10),
    eventTime.slice(0, 16),
    identity
  ].join("|");
}

function rowToInsert(airport: StandaloneAirport, row: FidsRow, snapshotTs: string): StoredInsert {
  const view = String(row.view || "departures");
  const callsign = String(row.callsign || row.id || row.flight_display || "UNKNOWN").toUpperCase();
  const { eventTime, schedTime, actualTime } = eventTimeForRow(row, snapshotTs);
  return {
    movementKey: movementKeyForRow(airport, row, snapshotTs, eventTime, view),
    snapshotTs,
    eventTime,
    airportIata: airport.iata,
    view,
    callsign,
    flightNumber: row.flight_number || row.flight_display || null,
    airlineIata: row.airline_iata || null,
    routeCode: row.route_code || null,
    status: row.status_display || row.status_kind || "scheduled",
    gate: row.gate_display || row.gate || null,
    terminal: row.terminal_display || null,
    aircraftType: row.aircraft_type || null,
    schedTime,
    actualTime,
    delayMinutes: typeof row.delay_minutes === "number" ? row.delay_minutes : null,
    codesharesJson: jsonList(row.codeshares),
    soldAsJson: jsonList(row.sold_as),
    operatingCallsign: row.operating_callsign || null,
    identitySource: row.identity_source || null,
    rowJson: JSON.stringify(row)
  };
}

async function pruneHistory(database: SQLite.SQLiteDatabase): Promise<void> {
  await database.runAsync("DELETE FROM standalone_fids_history WHERE COALESCE(event_time, last_seen_ts, snapshot_ts) < ?", cutoffIso(30));
  await database.runAsync(`
    DELETE FROM standalone_fids_history
    WHERE id NOT IN (
      SELECT id FROM standalone_fids_history
      ORDER BY COALESCE(event_time, last_seen_ts, snapshot_ts) DESC, id DESC
      LIMIT 1000
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
      const stored = rowToInsert(airport, row, snapshotTs);
      await txn.runAsync(
        `
        INSERT INTO standalone_fids_history (
          movement_key, snapshot_ts, event_time, first_seen_ts, last_seen_ts,
          observation_count, airport_iata, view, callsign, flight_number, airline_iata,
          route_code, status, gate, terminal, aircraft_type, sched_time, actual_time,
          delay_minutes, codeshares_json, sold_as_json, operating_callsign,
          identity_source, row_json
        ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(movement_key) DO UPDATE SET
          snapshot_ts = excluded.snapshot_ts,
          event_time = COALESCE(excluded.event_time, standalone_fids_history.event_time),
          last_seen_ts = excluded.last_seen_ts,
          observation_count = COALESCE(standalone_fids_history.observation_count, 1) + 1,
          callsign = COALESCE(excluded.callsign, standalone_fids_history.callsign),
          flight_number = COALESCE(excluded.flight_number, standalone_fids_history.flight_number),
          airline_iata = COALESCE(excluded.airline_iata, standalone_fids_history.airline_iata),
          route_code = COALESCE(excluded.route_code, standalone_fids_history.route_code),
          status = COALESCE(excluded.status, standalone_fids_history.status),
          gate = COALESCE(excluded.gate, standalone_fids_history.gate),
          terminal = COALESCE(excluded.terminal, standalone_fids_history.terminal),
          aircraft_type = COALESCE(excluded.aircraft_type, standalone_fids_history.aircraft_type),
          sched_time = COALESCE(excluded.sched_time, standalone_fids_history.sched_time),
          actual_time = COALESCE(excluded.actual_time, standalone_fids_history.actual_time),
          delay_minutes = COALESCE(excluded.delay_minutes, standalone_fids_history.delay_minutes),
          codeshares_json = excluded.codeshares_json,
          sold_as_json = excluded.sold_as_json,
          operating_callsign = COALESCE(excluded.operating_callsign, standalone_fids_history.operating_callsign),
          identity_source = COALESCE(excluded.identity_source, standalone_fids_history.identity_source),
          row_json = excluded.row_json
        `,
        stored.movementKey,
        stored.snapshotTs,
        stored.eventTime,
        stored.snapshotTs,
        stored.snapshotTs,
        stored.airportIata,
        stored.view,
        stored.callsign,
        stored.flightNumber,
        stored.airlineIata,
        stored.routeCode,
        stored.status,
        stored.gate,
        stored.terminal,
        stored.aircraftType,
        stored.schedTime,
        stored.actualTime,
        stored.delayMinutes,
        stored.codesharesJson,
        stored.soldAsJson,
        stored.operatingCallsign,
        stored.identitySource,
        stored.rowJson
      );
    }
  });
  await pruneHistory(database);
}

function rowMatchesFilters(row: StoredHistoryRow, callsign: string, airline: string): boolean {
  const callsignTerm = cleanIdentity(callsign);
  if (callsignTerm) {
    const haystack = [
      row.callsign,
      row.flight_number,
      row.operating_callsign,
      ...parseJsonList(row.codeshares_json),
      ...parseJsonList(row.sold_as_json)
    ].map(cleanIdentity).join(" ");
    if (!haystack.includes(callsignTerm)) return false;
  }
  if (airline) {
    const airlineTerm = airline.toUpperCase();
    const haystack = [
      row.airline_iata,
      row.callsign,
      row.flight_number,
      ...parseJsonList(row.codeshares_json),
      ...parseJsonList(row.sold_as_json)
    ].map((value) => String(value || "").toUpperCase()).join(" ");
    if (!haystack.includes(airlineTerm)) return false;
  }
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
    actual_time: row.actual_time,
    source: "mobile_standalone",
    enriched_by: "relay",
    snapshot_ts: row.last_seen_ts || row.snapshot_ts,
    event_time: row.event_time,
    first_seen_ts: row.first_seen_ts,
    last_seen_ts: row.last_seen_ts,
    observation_count: row.observation_count || 1,
    raw_observation_rows: row.observation_count || 1,
    movement_key: row.movement_key,
    delay_minutes: row.delay_minutes,
    airline_iata: row.airline_iata,
    codeshares: parseJsonList(row.codeshares_json),
    sold_as: parseJsonList(row.sold_as_json),
    operating_callsign: row.operating_callsign,
    identity_source: row.identity_source
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
  const upper = upperBoundIso();
  const directionWhere = direction === "dep"
    ? "AND view = 'departures'"
    : direction === "arr"
      ? "AND view = 'arrivals'"
      : "";
  const rows = await database.getAllAsync<StoredHistoryRow>(
    `
    SELECT *
    FROM standalone_fids_history
    WHERE airport_iata = ?
      AND COALESCE(event_time, snapshot_ts) >= ?
      AND COALESCE(event_time, snapshot_ts) <= ?
      ${directionWhere}
    ORDER BY COALESCE(event_time, snapshot_ts) DESC, COALESCE(last_seen_ts, snapshot_ts) DESC, id DESC
    LIMIT ?
    `,
    airport.iata,
    since,
    upper,
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
    movement_count: filtered.length,
    raw_observation_rows: filtered.reduce((sum, row) => sum + (row.observation_count || 1), 0),
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
  const daily = new Map<string, { departures: number; arrivals: number; total: number; delayed: number }>();
  for (const row of rows) {
    const date = String(row.event_time || row.snapshot_ts || "").slice(0, 10);
    if (!date) continue;
    const entry = daily.get(date) || { departures: 0, arrivals: 0, total: 0, delayed: 0 };
    entry.total += 1;
    if (row.direction === "dep") entry.departures += 1;
    if (row.direction === "arr") entry.arrivals += 1;
    if ((row.delay_minutes || 0) > 5 || /delay/i.test(row.status || "")) entry.delayed += 1;
    daily.set(date, entry);
  }
  return {
    airport_iata: airport.iata,
    hours,
    total: rows.length,
    movement_count: rows.length,
    sample_rows: history.raw_observation_rows || rows.length,
    raw_observation_rows: history.raw_observation_rows || rows.length,
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
    daily_volume: Array.from(daily.entries()).sort(([a], [b]) => a.localeCompare(b)).map(([date, value]) => ({ date, ...value }))
  };
}

export async function clearStandaloneHistory(): Promise<void> {
  const database = await db();
  await database.runAsync("DELETE FROM standalone_fids_history");
}
