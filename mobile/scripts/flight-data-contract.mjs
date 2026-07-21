#!/usr/bin/env node
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const mobileRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "localflight-flight-contract-"));
const outDir = path.join(tempRoot, "out");
const tsconfigPath = path.join(tempRoot, "tsconfig.json");
fs.writeFileSync(tsconfigPath, JSON.stringify({
  compilerOptions: {
    target: "ES2022",
    module: "CommonJS",
    moduleResolution: "Node",
    rootDir: path.join(mobileRoot, "src"),
    outDir,
    strict: true,
    esModuleInterop: true,
    skipLibCheck: true
  },
  include: [
    path.join(mobileRoot, "src/api/types.ts"),
    path.join(mobileRoot, "src/domain/*.ts")
  ]
}, null, 2));
execFileSync(process.execPath, [
  path.join(mobileRoot, "node_modules/typescript/bin/tsc"),
  "-p",
  tsconfigPath
], { cwd: mobileRoot, stdio: "pipe" });
const requireCompiled = createRequire(path.join(outDir, "contract.cjs"));
const flights = requireCompiled(path.join(outDir, "domain/flights.js"));
const board = requireCompiled(path.join(outDir, "domain/boardDedupe.js"));
const radar = requireCompiled(path.join(outDir, "domain/radar.js"));
const pins = requireCompiled(path.join(outDir, "domain/pinnedFlight.js"));
const lifecycle = requireCompiled(path.join(outDir, "domain/boardLifecycle.js"));
const screens = fs.readFileSync(path.join(mobileRoot, "src/screens/AppScreens.tsx"), "utf8");
const formattingSource = fs.readFileSync(path.join(mobileRoot, "src/domain/formatting.ts"), "utf8");

const baseRow = {
  id: "schedule:1",
  view: "departures",
  display_time: "21:49",
  flight_display: "LX 1353",
  route_display: "Warsaw (WAW)",
  status_display: "DELAYED +9M",
  status_class: "delayed",
  gate: "A12",
  aircraft_type: "A320",
  callsign: "SWR1353",
  airline_display: "SWISS",
  flight_number: "LX1353",
  airline_iata: "LX",
  airline_icao: "SWR",
  operating_callsign: "SWR1353",
  provider_movement_key: "aerodatabox|DEP|ZRH|WAW|2026-07-21T19:49Z",
  provider_codeshare_status: "Unknown",
  route_code: "WAW",
  time_primary: "21:49",
  delay_minutes: 9,
  sched_time: "2026-07-21T19:49:00Z",
  est_time: "2026-07-21T19:58:00Z",
  origin_iata: "ZRH",
  dest_iata: "WAW",
  sold_as: ["LO5055"],
  aircraft_registration: "HB-JDI",
  icao24: "4b1801"
};

const radarOnly = flights.radarBlipDetailResponse({
  callsign: "SWR1LK",
  lat: 47.4,
  lon: 8.5,
  aircraft_type: "A20N",
  registration: "HB-JDI",
  icao24: "4b1801",
  source: "adsbexchange"
});
assert.equal(radarOnly.detail.callsign, "SWR1LK");
assert.equal(radarOnly.detail.flight_number, null, "An operational callsign must not become a passenger flight number.");

const matched = flights.matchRadarBlipToFidsRows({
  callsign: "SWR1LK",
  lat: 47.4,
  lon: 8.5,
  registration: "HB-JDI",
  icao24: "4b1801"
}, [baseRow]);
assert.equal(matched?.flight_number, "LX1353");
const enriched = flights.radarBlipDetailResponse({
  callsign: "SWR1LK",
  lat: 47.4,
  lon: 8.5,
  registration: "HB-JDI",
  icao24: "4b1801",
  source: "adsbexchange"
}, matched, "ZRH");
assert.equal(enriched.detail.flight_number, "LX1353");
assert.equal(enriched.detail.origin_iata, "ZRH");
assert.equal(enriched.detail.dest_iata, "WAW");
assert.equal(enriched.detail.est_time, "2026-07-21T19:58:00Z");
assert.deepEqual(enriched.detail.sold_as, ["LO5055"]);

const shadow = {
  ...baseRow,
  id: "schedule:shadow",
  callsign: "SWR9GD",
  operating_callsign: "SWR9GD",
  flight_number: "",
  flight_display: "SWR9GD",
  sold_as: []
};
const deduped = board.dedupeBoardRows([shadow, baseRow]);
assert.equal(deduped.length, 1);
assert.equal(deduped[0].flight_number, "LX1353");
assert.ok(!(deduped[0].sold_as || []).includes("SWR9GD"));
const simultaneous = board.dedupeBoardRows([
  { ...baseRow, sold_as: [], aircraft_registration: "HB-JDI", icao24: "4b1801" },
  { ...baseRow, id: "schedule:2", callsign: "SWR979", operating_callsign: "SWR979", flight_number: "LX979", flight_display: "LX 979", sold_as: [], aircraft_registration: "HB-JNA", icao24: "4b1810" }
]);
assert.equal(simultaneous.length, 2, "Route and minute alone must not collapse simultaneous scheduled flights.");

const pinnedArrival = {
  ...baseRow,
  id: "arrival:1",
  view: "arrivals",
  callsign: "SWR8CM",
  operating_callsign: "SWR8CM",
  flight_number: "LX8CM",
  provider_movement_key: "aerodatabox|ARR|AMS|ZRH|2026-07-21T19:49Z",
  route_code: "AMS",
  route_display: "Amsterdam (AMS)"
};
const pinReference = pins.createPinnedFlightReference(pinnedArrival);
assert.ok(pinReference.id.startsWith("pin:v2:"));
assert.equal(pins.findPinnedFlight([baseRow, pinnedArrival], pinReference)?.id, "arrival:1");
assert.equal(pins.findPinnedFlight([baseRow, pinnedArrival], pinnedArrival.callsign)?.id, "arrival:1", "Legacy string pins migrate on the next strong match.");

const projectionNow = new Date("2026-07-21T20:30:00.000Z");
const expiredMovement = {
  ...baseRow,
  id: "completed:expired",
  status_display: "Departed",
  actual_time: "2026-07-21T20:14:00.000Z"
};
const graceMovement = {
  ...baseRow,
  id: "completed:grace",
  status_display: "Landed",
  actual_time: "2026-07-21T20:16:00.000Z"
};
const projected = lifecycle.currentStandaloneRows([expiredMovement, graceMovement], projectionNow.getTime());
assert.deepEqual(projected.map((row) => row.id), ["completed:grace"], "Completed movements retain exactly the 15-minute grace window.");

assert.deepEqual(radar.normalizeRadarCoordinatePair([47.46, 8.55], { lat: 47.45, lon: 8.56 }), { lat: 47.46, lon: 8.55 });
assert.deepEqual(radar.normalizeRadarCoordinatePair([8.55, 47.46], { lat: 47.45, lon: 8.56 }), { lat: 47.46, lon: 8.55 });

assert.ok(formattingSource.includes('const windM = metar.match(/(\\d{3}|VRB)(\\d{2,3})'), "Raw METAR parsing must retain wind direction and speed.");
assert.ok(formattingSource.includes('([PM]?\\d+\\/\\d+|P?\\d{1,2})SM'), "Raw METAR parsing must retain whole, greater-than, and fractional visibility.");
assert.ok(formattingSource.includes('const altimeterM = metar.match(/\\bA(\\d{4})\\b/'), "Raw METAR parsing must convert US altimeter values.");
assert.match(screens, /return rawWeatherChip\(metar, "WND"\) \|\| "--"/);
assert.match(screens, /return rawWeatherChip\(metar, "VIS"\) \|\| "--"/);
assert.match(screens, /return rawWeatherChip\(metar, "QNH"\) \|\| "--"/);

console.log("Flight identity, Board dedupe, detail enrichment, and METAR fallback contracts passed.");
fs.rmSync(tempRoot, { recursive: true, force: true });
