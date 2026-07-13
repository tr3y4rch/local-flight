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
  airport_key: string | null;
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
  airportKey: string;
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
let historyQueue: Promise<void> = Promise.resolve();

export type StandaloneHistoryDiagnostics = {
  airport_key: string;
  last_store_at: string | null;
  last_store_rows: number;
  last_store_error: string | null;
  pending_future_rows: number;
};

let historyDiagnostics: StandaloneHistoryDiagnostics = {
  airport_key: "",
  last_store_at: null,
  last_store_rows: 0,
  last_store_error: null,
  pending_future_rows: 0
};

const SQLITE_TRANSIENT_RETRIES = 3;
const SQLITE_TRANSIENT_BASE_DELAY_MS = 80;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function transientSqliteMessage(value: unknown): string {
  if (value instanceof Error) {
    return value.message;
  }
  if (typeof value === "object" && value !== null && "message" in value) {
    return String((value as { message?: unknown }).message || "");
  }
  return String(value || "");
}

function isTransientSqliteError(value: unknown): boolean {
  const code = typeof value === "object" && value !== null && "code" in value
    ? String((value as { code?: unknown }).code || "")
    : "";
  const message = transientSqliteMessage(value).toLowerCase();
  return (
    code === "5" ||
    message.includes("code 5") ||
    message.includes("sqlite_busy") ||
    message.includes("database is locked") ||
    message.includes("database table is locked") ||
    message.includes("finalizeasync") ||
    message.includes("finalize failed")
  );
}

async function withTransientSqliteRetry<T>(task: () => Promise<T>): Promise<T> {
  let lastError: unknown;
  for (let attempt = 0; attempt <= SQLITE_TRANSIENT_RETRIES; attempt += 1) {
    try {
      return await task();
    } catch (exc) {
      lastError = exc;
      if (!isTransientSqliteError(exc) || attempt >= SQLITE_TRANSIENT_RETRIES) {
        throw exc;
      }
      await sleep(SQLITE_TRANSIENT_BASE_DELAY_MS * (attempt + 1));
    }
  }
  throw lastError;
}

function enqueueHistory<T>(task: () => Promise<T>): Promise<T> {
  const run = historyQueue.then(
    () => withTransientSqliteRetry(task),
    () => withTransientSqliteRetry(task)
  );
  historyQueue = run.then(
    () => undefined,
    () => undefined
  );
  return run;
}

async function db(): Promise<SQLite.SQLiteDatabase> {
  if (!dbPromise) {
    dbPromise = SQLite.openDatabaseAsync("localflight_standalone_history.db").then(async (database) => {
      await database.execAsync(`
        PRAGMA journal_mode = WAL;
        PRAGMA busy_timeout = 5000;
        CREATE TABLE IF NOT EXISTS standalone_fids_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          movement_key TEXT,
          airport_key TEXT,
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
        CREATE INDEX IF NOT EXISTS idx_standalone_history_airport_key_event
          ON standalone_fids_history (airport_key, event_time DESC);
        CREATE INDEX IF NOT EXISTS idx_standalone_history_seen
          ON standalone_fids_history (last_seen_ts DESC);
        CREATE INDEX IF NOT EXISTS idx_standalone_history_callsign
          ON standalone_fids_history (callsign);
      `);
      return database;
    }).catch((exc) => {
      dbPromise = null;
      throw exc;
    });
  }
  return dbPromise;
}

async function ensureHistoryMigrations(database: SQLite.SQLiteDatabase): Promise<void> {
  const columns = await database.getAllAsync<{ name: string }>("PRAGMA table_info(standalone_fids_history)");
  const existing = new Set(columns.map((column) => column.name));
  const additions: Array<[string, string]> = [
    ["movement_key", "TEXT"],
    ["airport_key", "TEXT"],
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
        airport_key = COALESCE(NULLIF(airport_key, ''), NULLIF(airport_iata, ''), 'UNKNOWN'),
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
    const rowAirportKey = cleanAirportKey(row.airport_key || row.airport_iata);
    const identity = cleanIdentity(row.operating_callsign || row.callsign || row.flight_number) || cleanIdentity(String(row.id));
    const route = String(row.route_code || "").toUpperCase().replace(/[^A-Z0-9]+/g, "") || "-";
    const direction = directionForView(row.view).toUpperCase();
    const origin = row.view === "arrivals" ? route : row.airport_iata;
    const destination = row.view === "departures" ? route : row.airport_iata;
    const movementKey = [
      rowAirportKey,
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
            airport_key = COALESCE(NULLIF(airport_key, ''), NULLIF(airport_iata, ''), ?),
            event_time = COALESCE(event_time, sched_time, snapshot_ts),
            first_seen_ts = COALESCE(first_seen_ts, snapshot_ts),
            last_seen_ts = COALESCE(last_seen_ts, snapshot_ts),
            observation_count = COALESCE(observation_count, 1)
        WHERE id = ?
        `,
        movementKey,
        rowAirportKey,
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

function cleanAirportKey(value?: unknown): string {
  return String(value || "").trim().toUpperCase().replace(/[^A-Z0-9]+/g, "") || "UNKNOWN";
}

function airportKey(airport: StandaloneAirport): string {
  return cleanAirportKey(airport.iata || airport.icao || airport.name);
}

function airportDisplayCode(airport: StandaloneAirport): string {
  return cleanAirportKey(airport.iata || airport.icao);
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

function timezoneParts(date: Date, timezone = "UTC"): { year: number; month: number; day: number } {
  try {
    const formatter = new Intl.DateTimeFormat("en-CA", {
      timeZone: timezone || "UTC",
      year: "numeric",
      month: "2-digit",
      day: "2-digit"
    });
    const parts = Object.fromEntries(formatter.formatToParts(date).map((part) => [part.type, part.value]));
    return {
      year: Number(parts.year || date.getUTCFullYear()),
      month: Number(parts.month || date.getUTCMonth() + 1),
      day: Number(parts.day || date.getUTCDate())
    };
  } catch {
    return {
      year: date.getUTCFullYear(),
      month: date.getUTCMonth() + 1,
      day: date.getUTCDate()
    };
  }
}

function timezoneOffsetMs(timezone: string, instant: Date): number {
  try {
    const formatter = new Intl.DateTimeFormat("en-CA", {
      timeZone: timezone || "UTC",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23"
    });
    const parts = Object.fromEntries(formatter.formatToParts(instant).map((part) => [part.type, part.value]));
    const asUtc = Date.UTC(
      Number(parts.year || instant.getUTCFullYear()),
      Number(parts.month || instant.getUTCMonth() + 1) - 1,
      Number(parts.day || instant.getUTCDate()),
      Number(parts.hour || 0),
      Number(parts.minute || 0),
      Number(parts.second || 0)
    );
    return asUtc - instant.getTime();
  } catch {
    return 0;
  }
}

function zonedClockToIso(hour: string, minute: string, snapshotTs: string, timezone = "UTC"): string {
  const snapshot = new Date(snapshotTs);
  const parts = timezoneParts(Number.isFinite(snapshot.getTime()) ? snapshot : new Date(), timezone);
  let guessMs = Date.UTC(parts.year, parts.month - 1, parts.day, Number(hour), Number(minute), 0, 0);
  for (let i = 0; i < 3; i += 1) {
    guessMs = Date.UTC(parts.year, parts.month - 1, parts.day, Number(hour), Number(minute), 0, 0) - timezoneOffsetMs(timezone, new Date(guessMs));
  }
  const snapshotMs = Number.isFinite(snapshot.getTime()) ? snapshot.getTime() : Date.now();
  if (guessMs < snapshotMs - 18 * 60 * 60 * 1000) {
    guessMs += 24 * 60 * 60 * 1000;
  } else if (guessMs > snapshotMs + 18 * 60 * 60 * 1000) {
    guessMs -= 24 * 60 * 60 * 1000;
  }
  return new Date(guessMs).toISOString();
}

function isoFromValue(value: string | null | undefined, snapshotTs: string, timezone = "UTC"): string | null {
  const text = String(value || "").trim();
  if (!text) return null;
  if (/^\d{4}-\d{2}-\d{2}T/.test(text)) return text;
  const match = text.match(/(\d{1,2}):(\d{2})/);
  if (!match) return null;
  const hour = (match[1] || "0").padStart(2, "0");
  const minute = (match[2] || "0").padStart(2, "0");
  return zonedClockToIso(hour, minute, snapshotTs, timezone);
}

function eventTimeForRow(row: FidsRow, snapshotTs: string, timezone?: string): { eventTime: string; schedTime: string | null; actualTime: string | null } {
  const actualTime = isoFromValue(field(row, "actual_time"), snapshotTs, timezone);
  const schedTime = isoFromValue(field(row, "sched_time") || row.time_primary || row.display_time, snapshotTs, timezone);
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
  const key = airportKey(airport);
  const code = airportDisplayCode(airport);
  const origin = view === "arrivals" ? route : code;
  const destination = view === "departures" ? route : code;
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
    key,
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
  const { eventTime, schedTime, actualTime } = eventTimeForRow(row, snapshotTs, airport.timezone);
  const key = airportKey(airport);
  return {
    movementKey: movementKeyForRow(airport, row, snapshotTs, eventTime, view),
    airportKey: key,
    snapshotTs,
    eventTime,
    airportIata: airportDisplayCode(airport),
    view,
    callsign,
    flightNumber: row.flight_number || row.flight_display || null,
    airlineIata: row.airline_iata || null,
    routeCode: row.route_code || null,
    status: row.status_display || row.status_kind || "scheduled",
    gate: row.terminal_gate_display || row.gate_display || null,
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

async function storeStandaloneFidsRowsNow(
  airport: StandaloneAirport,
  rows: FidsRow[],
  snapshotTs = nowIso()
): Promise<void> {
  const key = airportKey(airport);
  historyDiagnostics = {
    ...historyDiagnostics,
    airport_key: key,
    last_store_at: snapshotTs,
    last_store_rows: rows.length,
    last_store_error: null
  };
  if (!rows.length) return;
  const database = await db();
  await database.withExclusiveTransactionAsync(async (txn) => {
    for (const row of rows) {
      const stored = rowToInsert(airport, row, snapshotTs);
      await txn.runAsync(
        `
        INSERT INTO standalone_fids_history (
          movement_key, airport_key, snapshot_ts, event_time, first_seen_ts, last_seen_ts,
          observation_count, airport_iata, view, callsign, flight_number, airline_iata,
          route_code, status, gate, terminal, aircraft_type, sched_time, actual_time,
          delay_minutes, codeshares_json, sold_as_json, operating_callsign,
          identity_source, row_json
        ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        stored.airportKey,
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

export async function storeStandaloneFidsRows(
  airport: StandaloneAirport,
  rows: FidsRow[],
  snapshotTs = nowIso()
): Promise<void> {
  return enqueueHistory(() => storeStandaloneFidsRowsNow(airport, rows, snapshotTs)).catch((exc) => {
    historyDiagnostics = {
      ...historyDiagnostics,
      airport_key: airportKey(airport),
      last_store_at: snapshotTs,
      last_store_rows: rows.length,
      last_store_error: transientSqliteMessage(exc) || "Standalone history write failed"
    };
    throw exc;
  });
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

async function getStandaloneHistoryNow(
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
  const key = airportKey(airport);
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
    WHERE COALESCE(NULLIF(airport_key, ''), airport_iata) = ?
      AND COALESCE(event_time, snapshot_ts) >= ?
      AND COALESCE(event_time, snapshot_ts) <= ?
      ${directionWhere}
    ORDER BY COALESCE(event_time, snapshot_ts) DESC, COALESCE(last_seen_ts, snapshot_ts) DESC, id DESC
    LIMIT ?
    `,
    key,
    since,
    upper,
    Math.max(1, Math.min(1000, limit * 2))
  );
  const filtered = rows
    .filter((row) => rowMatchesFilters(row, callsign, airline_iata))
    .slice(0, limit)
    .map(storedToHistory);
  const futureRows = await database.getAllAsync<StoredHistoryRow>(
    `
    SELECT *
    FROM standalone_fids_history
    WHERE COALESCE(NULLIF(airport_key, ''), airport_iata) = ?
      AND COALESCE(event_time, snapshot_ts) > ?
      ${directionWhere}
    ORDER BY COALESCE(event_time, snapshot_ts) ASC, id ASC
    LIMIT 1000
    `,
    key,
    upper
  );
  const pendingFutureRows = futureRows.filter((row) => rowMatchesFilters(row, callsign, airline_iata)).length;
  historyDiagnostics = {
    ...historyDiagnostics,
    airport_key: key,
    pending_future_rows: pendingFutureRows
  };
  return {
    airport_iata: airportDisplayCode(airport),
    hours,
    count: filtered.length,
    movement_count: filtered.length,
    raw_observation_rows: filtered.reduce((sum, row) => sum + (row.observation_count || 1), 0),
    pending_future_rows: pendingFutureRows,
    standalone_storage: { ...historyDiagnostics },
    flights: filtered
  } as HistoryResponse;
}

export async function getStandaloneHistory(
  airport: StandaloneAirport,
  options: {
    hours?: number;
    direction?: HistoryDirection;
    limit?: number;
    callsign?: string;
    airline_iata?: string;
  } = {}
): Promise<HistoryResponse> {
  return enqueueHistory(() => getStandaloneHistoryNow(airport, options));
}

function summarizeStandaloneHistoryRows(
  airport: StandaloneAirport,
  hours: number,
  rows: HistoryFlightRow[],
  rawObservationRows: number
): HistorySummary {
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
    airport_iata: airportDisplayCode(airport),
    hours,
    total: rows.length,
    movement_count: rows.length,
    sample_rows: rawObservationRows || rows.length,
    raw_observation_rows: rawObservationRows || rows.length,
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
    daily_volume: Array.from(daily.entries()).sort(([a], [b]) => a.localeCompare(b)).map(([date, value]) => ({ date, ...value })),
    standalone_storage: { ...historyDiagnostics }
  } as HistorySummary;
}

async function getStandaloneHistorySummaryNow(
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
  const history = await getStandaloneHistoryNow(airport, {
    hours,
    direction,
    callsign,
    airline_iata,
    limit: 1000
  });
  return summarizeStandaloneHistoryRows(airport, hours, history.flights, history.raw_observation_rows || history.flights.length);
}

export async function getStandaloneHistorySummary(
  airport: StandaloneAirport,
  options: {
    hours?: number;
    direction?: HistoryDirection;
    callsign?: string;
    airline_iata?: string;
  } = {}
): Promise<HistorySummary> {
  return enqueueHistory(() => getStandaloneHistorySummaryNow(airport, options));
}

export async function clearStandaloneHistory(): Promise<void> {
  return enqueueHistory(async () => {
    const database = await db();
    await database.runAsync("DELETE FROM standalone_fids_history");
  });
}

export function getStandaloneHistoryDiagnostics(): StandaloneHistoryDiagnostics {
  return { ...historyDiagnostics };
}
