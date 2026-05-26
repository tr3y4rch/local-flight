import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const mobileRoot = path.resolve(new URL("..", import.meta.url).pathname);
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

  const requireCompiled = createRequire(path.join(outDir, "contract.cjs"));
  const widgets = requireCompiled(path.join(outDir, "domain/widgets.js"));
  const storage = requireCompiled(path.join(outDir, "storage/widgetSnapshot.js"));
  const future = new Date("2030-01-01T00:00:00.000Z");
  const laterFuture = new Date("2030-01-01T00:01:00.000Z");
  const past = new Date("2020-01-01T00:00:00.000Z");
  const prefs3 = { mediumRowCount: 3, showGateTerminal: true };
  const prefs2 = { mediumRowCount: 2, showGateTerminal: false };

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
    gate: overrides.gate || "A62"
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
    sourceLabel: "relay"
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

  const sameMeaningLater = widgets.buildWidgetExchangeSnapshot({
    preview,
    preferences: prefs3,
    mode: "lan_companion",
    generatedAt: laterFuture,
    stale: false,
    sourceLabel: "relay"
  });
  assert.equal(
    widgets.widgetSnapshotSemanticKey(snapshot),
    widgets.widgetSnapshotSemanticKey(sameMeaningLater)
  );

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
    fsMock.failAllCreates = false;
    fsMock.failAllWrites = false;
    fsMock.failTempCreateOnce = false;
    fsMock.failTempWriteOnce = false;
    storage.resetWidgetSnapshotWriteMemo();
  };

  resetFsMock();
  assert.equal(storage.shouldWriteWidgetSnapshot(snapshot), true);
  const firstWrite = await storage.writeWidgetSnapshot(snapshot);
  assert.equal(firstWrite.ok, true);
  assert.equal(firstWrite.sharedContainer, false);
  assert.equal(firstWrite.skipped, undefined);
  assert.equal(storage.shouldWriteWidgetSnapshot(snapshot), false);
  const writeCountAfterFirst = fsMock.writeCount;
  const skippedWrite = await storage.writeWidgetSnapshot(sameMeaningLater);
  assert.equal(skippedWrite.ok, true);
  assert.equal(skippedWrite.skipped, true);
  assert.equal(fsMock.writeCount, writeCountAfterFirst);
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

  console.log("Widget snapshot contract checks passed.");
} finally {
  rmSync(tempRoot, { recursive: true, force: true });
}
