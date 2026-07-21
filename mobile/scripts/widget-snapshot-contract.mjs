import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const mobileRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const tempRoot = mkdtempSync(path.join(tmpdir(), "localflight-widget-contract-"));
const outDir = path.join(tempRoot, "out");
const tsconfigPath = path.join(tempRoot, "tsconfig.json");

writeFileSync(tsconfigPath, JSON.stringify({
  compilerOptions: {
    target: "ES2022",
    module: "CommonJS",
    moduleResolution: "Node",
    rootDir: path.join(mobileRoot, "src"),
    outDir,
    strict: true,
    esModuleInterop: true,
    skipLibCheck: true,
    jsx: "react-jsx"
  },
  include: [
    path.join(mobileRoot, "src/domain/widgets.ts"),
    path.join(mobileRoot, "src/domain/flights.ts"),
    path.join(mobileRoot, "src/storage/standaloneHistory.ts"),
    path.join(mobileRoot, "src/storage/widgetSnapshot.ts")
  ]
}, null, 2));

try {
  execFileSync(process.execPath, [
    path.join(mobileRoot, "node_modules/typescript/bin/tsc"),
    "-p",
    tsconfigPath
  ], { cwd: mobileRoot, stdio: "pipe" });

  const fakeFileSystemDir = path.join(outDir, "node_modules/expo-file-system");
  mkdirSync(fakeFileSystemDir, { recursive: true });
  writeFileSync(path.join(fakeFileSystemDir, "index.js"), `
const path = require("node:path");
const state = globalThis.__localFlightExpoFileSystemMock || (globalThis.__localFlightExpoFileSystemMock = {});
function resetDefaults() {
  state.files ||= new Map();
  state.documentUri ||= "mock://document";
  state.sharedContainers ||= {};
  state.tempCreateUris ||= [];
  state.createCount ||= 0;
  state.writeCount ||= 0;
  state.moveCount ||= 0;
}
function uriFor(base, name) {
  const root = typeof base === "string" ? base : base && base.uri ? base.uri : String(base || "");
  return name ? root.replace(/\\/$/, "") + "/" + name : root;
}
class Directory {
  constructor(uri) {
    this.uri = String(uri || "").replace(/\\/$/, "");
  }
}
class File {
  constructor(base, name) {
    resetDefaults();
    this.uri = uriFor(base, name);
  }
  get parentDirectory() {
    return new Directory(path.posix.dirname(this.uri));
  }
  get exists() {
    return state.files.has(this.uri);
  }
  create() {
    state.createCount += 1;
    if (state.failAllCreates || (state.failTempCreateOnce && this.uri.endsWith(".tmp"))) {
      state.failTempCreateOnce = false;
      throw new Error("mock create failed");
    }
    if (this.uri.endsWith(".tmp")) {
      state.tempCreateUris.push(this.uri);
    }
    state.files.set(this.uri, state.files.get(this.uri) || "");
  }
  write(value) {
    state.writeCount += 1;
    if (state.failAllWrites || (state.failTempWriteOnce && this.uri.endsWith(".tmp"))) {
      state.failTempWriteOnce = false;
      throw new Error("mock write failed");
    }
    state.files.set(this.uri, String(value));
  }
  delete() {
    state.files.delete(this.uri);
  }
  move(target) {
    state.moveCount += 1;
    state.files.set(target.uri, state.files.get(this.uri) || "");
    state.files.delete(this.uri);
  }
  async text() {
    return state.files.get(this.uri) || "";
  }
}
const Paths = {};
Object.defineProperty(Paths, "document", {
  enumerable: true,
  get() {
    resetDefaults();
    return new Directory(state.documentUri);
  }
});
Object.defineProperty(Paths, "appleSharedContainers", {
  enumerable: true,
  get() {
    resetDefaults();
    return state.sharedContainers;
  }
});
module.exports = { File, Paths };
`);

  const fakeWidgetBridgeDir = path.join(outDir, "node_modules/localflight-widget-bridge");
  mkdirSync(fakeWidgetBridgeDir, { recursive: true });
  writeFileSync(path.join(fakeWidgetBridgeDir, "index.js"), `
const state = globalThis.__localFlightWidgetBridgeMock || (globalThis.__localFlightWidgetBridgeMock = { reloadCount: 0 });
async function reloadLocalFlightWidgets() {
  state.reloadCount += 1;
  return { available: true, widgetCount: 1 };
}
module.exports = { reloadLocalFlightWidgets };
`);

  const fakeSqliteDir = path.join(outDir, "node_modules/expo-sqlite");
  mkdirSync(fakeSqliteDir, { recursive: true });
  writeFileSync(path.join(fakeSqliteDir, "index.js"), `
const state = globalThis.__localFlightExpoSqliteMock || (globalThis.__localFlightExpoSqliteMock = {});
function resetDefaults() {
  state.rows ||= [];
  state.openCount ||= 0;
  state.execCount ||= 0;
  state.runCount ||= 0;
  state.getAllCount ||= 0;
  state.getFirstCount ||= 0;
  state.transactionCount ||= 0;
  state.nextId ||= 1;
  state.failNextRunBusyCount ||= 0;
}
const columnNames = [
  "movement_key", "airport_key", "snapshot_ts", "event_time", "first_seen_ts", "last_seen_ts",
  "observation_count", "airport_iata", "view", "callsign", "flight_number",
  "airline_iata", "route_code", "status", "gate", "terminal", "aircraft_type",
  "sched_time", "actual_time", "delay_minutes", "codeshares_json", "sold_as_json",
  "operating_callsign", "identity_source", "row_json"
];
function busyError() {
  const err = new Error("database is locked");
  err.code = 5;
  return err;
}
function makeDatabase() {
  return {
    async execAsync() {
      resetDefaults();
      state.execCount += 1;
    },
    async getAllAsync(sql, ...params) {
      resetDefaults();
      state.getAllCount += 1;
      const text = String(sql || "");
      if (/PRAGMA table_info/i.test(text)) {
        return columnNames.map((name) => ({ name }));
      }
      if (/movement_key IS NULL/i.test(text)) {
        return state.rows.filter((row) => !row.movement_key);
      }
      if (/FROM standalone_fids_history/i.test(text)) {
        const [airport, since, upper, limit] = params;
        return state.rows
          .filter((row) => !airport || (row.airport_key || row.airport_iata) === airport)
          .filter((row) => !since || String(row.event_time || row.snapshot_ts) >= String(since))
          .filter((row) => !upper || String(row.event_time || row.snapshot_ts) <= String(upper))
          .sort((a, b) => String(b.event_time || b.snapshot_ts).localeCompare(String(a.event_time || a.snapshot_ts)))
          .slice(0, Number(limit || state.rows.length));
      }
      return [];
    },
    async getFirstAsync() {
      resetDefaults();
      state.getFirstCount += 1;
      return null;
    },
    async runAsync(sql, ...params) {
      resetDefaults();
      state.runCount += 1;
      const text = String(sql || "").trim();
      if (/^DELETE FROM standalone_fids_history$/i.test(text)) {
        state.rows = [];
        return {};
      }
      if (!/INSERT INTO standalone_fids_history/i.test(text)) {
        return {};
      }
      if (state.failNextRunBusyCount > 0) {
        state.failNextRunBusyCount -= 1;
        throw busyError();
      }
      const [
        movement_key, airport_key, snapshot_ts, event_time, first_seen_ts, last_seen_ts,
        airport_iata, view, callsign, flight_number, airline_iata, route_code,
        status, gate, terminal, aircraft_type, sched_time, actual_time,
        delay_minutes, codeshares_json, sold_as_json, operating_callsign,
        identity_source, row_json
      ] = params;
      const existing = state.rows.find((row) => row.movement_key === movement_key);
      if (existing) {
        Object.assign(existing, {
          snapshot_ts, event_time: event_time || existing.event_time, last_seen_ts,
          observation_count: (existing.observation_count || 1) + 1,
          callsign: callsign || existing.callsign,
          flight_number: flight_number || existing.flight_number,
          airline_iata: airline_iata || existing.airline_iata,
          route_code: route_code || existing.route_code,
          status: status || existing.status,
          gate: gate || existing.gate,
          terminal: terminal || existing.terminal,
          aircraft_type: aircraft_type || existing.aircraft_type,
          sched_time: sched_time || existing.sched_time,
          actual_time: actual_time || existing.actual_time,
          delay_minutes: delay_minutes ?? existing.delay_minutes,
          codeshares_json,
          sold_as_json,
          operating_callsign: operating_callsign || existing.operating_callsign,
          identity_source: identity_source || existing.identity_source,
          airport_key: airport_key || existing.airport_key,
          row_json
        });
      } else {
        state.rows.push({
          id: state.nextId++,
          movement_key, snapshot_ts, event_time, first_seen_ts, last_seen_ts,
          observation_count: 1, airport_key, airport_iata, view, callsign, flight_number,
          airline_iata, route_code, status, gate, terminal, aircraft_type,
          sched_time, actual_time, delay_minutes, codeshares_json, sold_as_json,
          operating_callsign, identity_source, row_json
        });
      }
      return {};
    },
    async withExclusiveTransactionAsync(task) {
      resetDefaults();
      state.transactionCount += 1;
      await task(this);
    }
  };
}
async function openDatabaseAsync() {
  resetDefaults();
  state.openCount += 1;
  return makeDatabase();
}
module.exports = { openDatabaseAsync };
`);

  const requireCompiled = createRequire(path.join(outDir, "contract.cjs"));
  const widgets = requireCompiled(path.join(outDir, "domain/widgets.js"));
  const flightsDomain = requireCompiled(path.join(outDir, "domain/flights.js"));
  const standaloneHistory = requireCompiled(path.join(outDir, "storage/standaloneHistory.js"));
  const storage = requireCompiled(path.join(outDir, "storage/widgetSnapshot.js"));
  const future = new Date("2030-01-01T00:00:00.000Z");
  const laterFuture = new Date("2030-01-01T00:01:00.000Z");
  const past = new Date("2020-01-01T00:00:00.000Z");
  const prefs3 = { mediumRowCount: 3, showGateTerminal: true, automaticRefresh: true };
  const prefs2 = { mediumRowCount: 2, showGateTerminal: false, automaticRefresh: false };

  const row = (index, overrides = {}) => ({
    id: `row-${index}`,
    callsign: `LX${2800 + index}`,
    flight_display: `LX ${2800 + index}`,
    route_display: `${overrides.route || "Geneva"} (${overrides.routeCode || "GVA"})`,
    route_code: overrides.routeCode || "GVA",
    display_time: overrides.displayTime || "17:10",
    status_display: overrides.status || "Scheduled",
    view: overrides.view || "departures",
    gate_display: overrides.gate || "A62",
    terminal_display: overrides.terminal || "1",
    gate: overrides.gate || "A62",
    actual_time: overrides.actualTime || null
  });
  const rows = [
    row(0, { status: "Delayed" }),
    row(1, { route: "Nice", routeCode: "NCE" }),
    row(2, { route: "Bordeaux", routeCode: "BDS" }),
    row(3, { route: "London Heathrow", routeCode: "LHR" }),
    row(4, { route: "Madrid", routeCode: "MAD" })
  ];

  const preview = widgets.deriveWidgetPreviewSnapshot({
    rows,
    pinnedCallsign: "LX2800",
    airportCode: "ZRH",
    airportName: "Zurich Airport",
    updatedLabel: "Updated now",
    view: "departures",
    preferences: prefs3
  });
  assert.equal(preview.smallSource, "pinned");
  assert.equal(preview.pinnedFlight.flightDisplay, "LX 2800");
  assert.equal(preview.liveFlights.length, 3);

  const snapshot = widgets.buildWidgetExchangeSnapshot({
    preview,
    preferences: prefs3,
    mode: "lan_companion",
    generatedAt: future,
    stale: false,
    sourceLabel: "relay",
    sourceUpdatedAt: future.toISOString()
  });
  assert.equal(snapshot.schemaVersion, 1);
  assert.equal(snapshot.small.flight.flightDisplay, "LX 2800");
  assert.equal(snapshot.liveActivity.stale, false);
  assert.equal(snapshot.medium.rows.length, 4);
  assert.equal(snapshot.medium.rows[0].pinned, true);

  const snapshot2Rows = widgets.buildWidgetExchangeSnapshot({
    preview,
    preferences: prefs2,
    mode: "standalone",
    generatedAt: future
  });
  assert.equal(snapshot2Rows.mode, "standalone");
  assert.equal(snapshot2Rows.medium.rowCount, 2);
  assert.equal(snapshot2Rows.medium.rows.length, 3);

  const missingPinPreview = widgets.deriveWidgetPreviewSnapshot({
    rows,
    pinnedCallsign: "NO_SUCH_PIN",
    airportCode: "ZRH",
    airportName: "Zurich Airport",
    view: "departures",
    preferences: prefs3
  });
  const missingPinSnapshot = widgets.buildWidgetExchangeSnapshot({
    preview: missingPinPreview,
    preferences: prefs3,
    mode: "lan_companion",
    generatedAt: future
  });
  assert.equal(missingPinSnapshot.small.source, "empty");
  assert.equal(missingPinSnapshot.small.flight, null);
  assert.equal(missingPinSnapshot.liveActivity.stale, true);
  assert.equal(missingPinSnapshot.medium.rows.some((flight) => flight.pinned), false);

  const tooLong = "A".repeat(140);
  const normalized = widgets.normalizeWidgetExchangeSnapshot({
    schemaVersion: 1,
    generatedAt: future.toISOString(),
    expiresAt: future.toISOString(),
    mode: "nonsense",
    stale: false,
    airport: { code: "VERYLONGAIRPORT", name: tooLong, view: "sideways" },
    source: { label: tooLong, lastUpdatedLabel: tooLong },
    preferences: { mediumRowCount: 99, showGateTerminal: false },
    small: { source: "empty", flight: { id: "BAD", flightDisplay: "BAD", statusTone: "delayed" } },
    medium: {
      rowCount: 99,
      rows: Array.from({ length: 8 }, (_, index) => ({
        id: `dirty-${index}`,
        flightDisplay: `${tooLong}-${index}`,
        direction: "sideways",
        routeName: tooLong,
        routeCode: "TOOLONGCODE",
        displayTime: "123456789012345",
        statusDisplay: tooLong,
        statusTone: "purple",
        pinned: index === 0
      }))
    },
    liveActivity: {
      flight: {
        id: "SHOULD_NOT_PROMOTE",
        flightDisplay: "UA 1",
        direction: "dep",
        routeName: "Ghost",
        routeCode: "GST",
        displayTime: "00:00",
        statusDisplay: "SCHEDULE",
        statusTone: "scheduled"
      },
      stale: false
    }
  });
  assert.equal(normalized.mode, "lan_companion");
  assert.equal(normalized.airport.view, "departures");
  assert.equal(normalized.airport.code.length, 8);
  assert.equal(normalized.preferences.mediumRowCount, 3);
  assert.equal(normalized.preferences.showGateTerminal, false);
  assert.equal(normalized.small.flight, null);
  assert.equal(normalized.liveActivity.flight, null);
  assert.equal(normalized.liveActivity.stale, true);
  assert.equal(normalized.medium.rows.length, 4);
  assert.equal(normalized.medium.rows[0].statusTone, "scheduled");
  assert.equal(normalized.medium.rows[0].direction, "dep");
  assert.equal(normalized.medium.rows[0].flightDisplay.length, 24);

  const expired = widgets.normalizeWidgetExchangeSnapshot({
    ...snapshot,
    generatedAt: past.toISOString(),
    expiresAt: past.toISOString(),
    stale: false
  });
  assert.equal(expired.stale, true);
  assert.equal(expired.liveActivity.stale, true);
  assert.equal(widgets.isWidgetSnapshotExpired(expired, future), true);
  assert.equal(widgets.isWidgetSnapshotExpired(snapshot, past), false);

  assert.equal(widgets.parseWidgetExchangeSnapshot("{ nope"), null);
  assert.equal(widgets.normalizeWidgetExchangeSnapshot({ schemaVersion: 999 }), null);
  assert.ok(
    Buffer.byteLength(widgets.serializeWidgetExchangeSnapshot(snapshot), "utf8") <=
      widgets.WIDGET_SNAPSHOT_MAX_BYTES
  );
  const serializedSnapshot = widgets.serializeWidgetExchangeSnapshot(snapshot);
  for (const privateField of [
    "activationToken",
    "installId",
    "companionId",
    "serverUrl",
    "remoteKey",
    "diagnosticsMode"
  ]) {
    assert.ok(!serializedSnapshot.includes(privateField), `private field leaked into widget snapshot: ${privateField}`);
  }

  const sameMeaningLater = widgets.buildWidgetExchangeSnapshot({
    preview,
    preferences: prefs3,
    mode: "lan_companion",
    generatedAt: laterFuture,
    stale: false,
    sourceLabel: "relay",
    sourceUpdatedAt: future.toISOString()
  });
  assert.equal(
    widgets.widgetSnapshotSemanticKey(snapshot),
    widgets.widgetSnapshotSemanticKey(sameMeaningLater)
  );
  const refreshedSource = widgets.buildWidgetExchangeSnapshot({
    preview,
    preferences: prefs3,
    mode: "lan_companion",
    generatedAt: laterFuture,
    sourceLabel: "relay",
    sourceUpdatedAt: laterFuture.toISOString()
  });
  assert.notEqual(
    widgets.widgetSnapshotSemanticKey(snapshot),
    widgets.widgetSnapshotSemanticKey(refreshedSource)
  );
  assert.equal(widgets.widgetSnapshotStaleAfterMs("standalone"), 90 * 60 * 1000);
  assert.equal(widgets.widgetSnapshotStaleAfterMs("lan_companion", 8 * 60 * 60), 16 * 60 * 60 * 1000);

  const fsMock = globalThis.__localFlightExpoFileSystemMock;
  const resetFsMock = ({ sharedContainer = false } = {}) => {
    fsMock.files = new Map();
    fsMock.documentUri = "mock://document";
    fsMock.sharedContainers = sharedContainer
      ? { [widgets.WIDGET_APP_GROUP_ID]: { uri: "mock://app-group" } }
      : {};
    fsMock.createCount = 0;
    fsMock.writeCount = 0;
    fsMock.moveCount = 0;
    fsMock.tempCreateUris = [];
    fsMock.failAllCreates = false;
    fsMock.failAllWrites = false;
    fsMock.failTempCreateOnce = false;
    fsMock.failTempWriteOnce = false;
    storage.resetWidgetSnapshotWriteMemo();
  };

  resetFsMock();
  globalThis.__localFlightWidgetBridgeMock.reloadCount = 0;
  assert.equal(storage.shouldWriteWidgetSnapshot(snapshot), true);
  const firstWrite = await storage.writeWidgetSnapshot(snapshot);
  assert.equal(firstWrite.ok, true);
  assert.equal(firstWrite.sharedContainer, false);
  assert.equal(firstWrite.skipped, undefined);
  assert.equal(globalThis.__localFlightWidgetBridgeMock.reloadCount, 1);
  assert.equal(storage.shouldWriteWidgetSnapshot(snapshot), false);
  const writeCountAfterFirst = fsMock.writeCount;
  const skippedWrite = await storage.writeWidgetSnapshot(sameMeaningLater);
  assert.equal(skippedWrite.ok, true);
  assert.equal(skippedWrite.skipped, true);
  assert.equal(fsMock.writeCount, writeCountAfterFirst);
  assert.equal(globalThis.__localFlightWidgetBridgeMock.reloadCount, 1);
  const readBack = await storage.readWidgetSnapshot();
  assert.equal(readBack.small.flight.flightDisplay, "LX 2800");

  resetFsMock({ sharedContainer: true });
  const sharedWrite = await storage.writeWidgetSnapshot(snapshot);
  assert.equal(sharedWrite.ok, true);
  assert.equal(sharedWrite.sharedContainer, true);

  resetFsMock();
  fsMock.failTempCreateOnce = true;
  const fallbackWrite = await storage.writeWidgetSnapshot(snapshot);
  assert.equal(fallbackWrite.ok, true);
  assert.equal(fallbackWrite.sharedContainer, false);

  resetFsMock();
  fsMock.failAllCreates = true;
  const failedWrite = await storage.writeWidgetSnapshot(snapshot, { force: true });
  assert.equal(failedWrite.ok, false);
  assert.match(failedWrite.error, /mock create failed/);

  resetFsMock();
  const [concurrentWriteA, concurrentWriteB] = await Promise.all([
    storage.writeWidgetSnapshot(snapshot, { force: true }),
    storage.writeWidgetSnapshot(snapshot2Rows, { force: true })
  ]);
  assert.equal(concurrentWriteA.ok, true);
  assert.equal(concurrentWriteB.ok, true);
  assert.equal(fsMock.tempCreateUris.length, 2);
  assert.equal(new Set(fsMock.tempCreateUris).size, 2);
  assert.equal((await storage.readWidgetSnapshot()).mode, "standalone");

  const sqliteMock = globalThis.__localFlightExpoSqliteMock;
  const resetSqliteMock = () => {
    sqliteMock.rows = [];
    sqliteMock.openCount = 0;
    sqliteMock.execCount = 0;
    sqliteMock.runCount = 0;
    sqliteMock.getAllCount = 0;
    sqliteMock.getFirstCount = 0;
    sqliteMock.transactionCount = 0;
    sqliteMock.nextId = 1;
    sqliteMock.failNextRunBusyCount = 0;
  };
  const airport = {
    iata: "ZRH",
    icao: "LSZH",
    name: "Zurich Airport",
    city: "Zurich",
    country: "CH",
    timezone: "Europe/Zurich"
  };
  const recentEventTime = new Date(Date.now() - 60 * 1000).toISOString();
  const historyRows = rows.slice(0, 4).map((historyRow, index) => ({
    ...historyRow,
    actual_time: recentEventTime,
    airline_iata: "LX",
    delay_minutes: index === 0 ? 5 : 0
  }));

  resetSqliteMock();
  sqliteMock.failNextRunBusyCount = 1;
  await standaloneHistory.storeStandaloneFidsRows(airport, historyRows.slice(0, 2), recentEventTime);
  assert.equal(sqliteMock.rows.length, 2);
  assert.equal(sqliteMock.transactionCount, 2);
  const [history, historySummary] = await Promise.all([
    standaloneHistory.getStandaloneHistory(airport, { hours: 24, limit: 10 }),
    standaloneHistory.getStandaloneHistorySummary(airport, { hours: 24 })
  ]);
  assert.equal(history.flights.length, 2);
  assert.equal(historySummary.total, 2);
  assert.equal(historySummary.delayed, 1);
  assert.equal(historySummary.delayed_pct, 50);
  assert.equal(historySummary.on_time_pct, 50);
  assert.deepEqual(
    historySummary.delay_buckets.map(({ bucket, count }) => [bucket, count]),
    [
      ["early", 0],
      ["on_time", 1],
      ["delayed_warn", 1],
      ["delayed_bad", 0],
      ["unknown", 0]
    ]
  );
  assert.deepEqual(historySummary.top_airlines, [{
    code: "LX",
    count: 2,
    delay_rate_pct: 50,
    on_time_pct: 50,
    avg_delay_minutes: 5
  }]);
  assert.equal(history.standalone_storage.airport_key, "ZRH");
  assert.equal(history.standalone_storage.last_store_rows, 2);
  assert.equal(history.standalone_storage.last_store_error, null);
  assert.equal((await standaloneHistory.getStandaloneHistory(airport, { hours: 24, direction: "dep", limit: 10 })).flights.length, 2);
  assert.equal((await standaloneHistory.getStandaloneHistory(airport, { hours: 24, callsign: "LX2800", limit: 10 })).flights.length, 1);
  assert.equal((await standaloneHistory.getStandaloneHistory(airport, { hours: 24, airline_iata: "LX", limit: 10 })).flights.length, 2);
  assert.ok(flightsDomain.fidsRowDetailResponse(historyRows[0], "ZRH").detail.callsign);
  assert.ok(flightsDomain.radarBlipDetailResponse({
    callsign: "LX2800",
    display_title: "LX 2800",
    lat: 47.46,
    lon: 8.55,
    altitude_ft: 4000,
    speed_kt: 180,
    heading_deg: 90,
    radar_status_label: "Tracked target",
    source: "standalone_radar"
  }).detail.position);
  assert.ok(flightsDomain.historyRowDetailResponse(history.flights[0]).detail.callsign);

  const icaoOnlyAirport = {
    iata: "",
    icao: "RJAA",
    name: "Narita",
    city: "Tokyo",
    country: "JP",
    timezone: "Asia/Tokyo"
  };
  resetSqliteMock();
  await standaloneHistory.storeStandaloneFidsRows(icaoOnlyAirport, [
    row(20, {
      route: "Sapporo",
      routeCode: "CTS",
      actualTime: new Date(Date.now() - 30 * 60 * 1000).toISOString()
    })
  ]);
  const icaoHistory = await standaloneHistory.getStandaloneHistory(icaoOnlyAirport, { hours: 24, limit: 10 });
  assert.equal(icaoHistory.flights.length, 1);
  assert.equal(icaoHistory.airport_iata, "RJAA");
  assert.equal(icaoHistory.standalone_storage.airport_key, "RJAA");

  resetSqliteMock();
  await standaloneHistory.storeStandaloneFidsRows(airport, [
    row(30, {
      route: "Oslo",
      routeCode: "OSL",
      actualTime: new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString()
    })
  ]);
  const pendingHistory = await standaloneHistory.getStandaloneHistory(airport, { hours: 24, limit: 10 });
  assert.equal(pendingHistory.flights.length, 0);
  assert.equal(pendingHistory.pending_future_rows, 1);

  await Promise.all([
    standaloneHistory.storeStandaloneFidsRows(airport, historyRows.slice(2, 4), recentEventTime),
    standaloneHistory.getStandaloneHistory(airport, { hours: 24, limit: 10 }),
    standaloneHistory.clearStandaloneHistory()
  ]);
  const afterClear = await standaloneHistory.getStandaloneHistory(airport, { hours: 24, limit: 10 });
  assert.equal(afterClear.flights.length, 0);

  const appScreenSource = readFileSync(path.join(mobileRoot, "src/screens/AppScreens.tsx"), "utf8");
  const backgroundRefreshSource = readFileSync(path.join(mobileRoot, "src/background/widgetRefresh.ts"), "utf8");
  assert.match(backgroundRefreshSource, /STANDALONE_FIDS_MINIMUM_REFRESH_MS/);
  assert.match(backgroundRefreshSource, /configureWidgetBackgroundRefresh/);
  assert.match(backgroundRefreshSource, /getStandaloneBoard/);
  assert.match(backgroundRefreshSource, /board\.generated_at/);
  assert.match(backgroundRefreshSource, /getFids/);
  for (const forbidden of [
    "TIP JAR",
    "support tips are being prepared",
    "cc.beacontools.localflight.tip.",
    "buymeacoffee.com"
  ]) {
    assert.equal(appScreenSource.includes(forbidden), false, `AppScreens.tsx should not expose ${forbidden}`);
  }

  console.log("Widget snapshot contract checks passed.");
} finally {
  rmSync(tempRoot, { recursive: true, force: true });
}
