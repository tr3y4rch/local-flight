#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const mobileRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const screensSource = fs.readFileSync(path.join(mobileRoot, "src/screens/AppScreens.tsx"), "utf8");
const appShellSource = fs.readFileSync(path.join(mobileRoot, "src/app/AppShell.tsx"), "utf8");
const styleBridgeSource = fs.readFileSync(path.join(mobileRoot, "src/theme/styleBridge.ts"), "utf8");
const flightDetailHookSource = fs.readFileSync(path.join(mobileRoot, "src/hooks/useFlightDetail.ts"), "utf8");
const flightDomainSource = fs.readFileSync(path.join(mobileRoot, "src/domain/flights.ts"), "utf8");
const boardModelSource = fs.readFileSync(path.join(mobileRoot, "src/v2/boardModel.ts"), "utf8");

function sourceSection(source, startMarker, endMarker, label) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start + startMarker.length);
  assert.notEqual(start, -1, `${label}: missing ${startMarker}`);
  assert.notEqual(end, -1, `${label}: missing ${endMarker}`);
  return source.slice(start, end);
}

const radarLayers = sourceSection(
  screensSource,
  "function RadarLayerControls(",
  "function radarBlipIsGround(",
  "Radar layer controls"
);
assert.match(
  radarLayers,
  /hitSlop=\{tapTargetHitSlop\}/,
  "Radar drawing chips must retain the shared expanded touch target."
);
assert.match(
  radarLayers,
  /accessibleButton\(\{/,
  "Radar drawing chips must retain explicit accessibility labels."
);
assert.doesNotMatch(
  radarLayers,
  /compactTapTargetHitSlop/,
  "Radar drawing chips must not regress to the compact touch-target override."
);

const delayColors = sourceSection(
  screensSource,
  "function delayBucketColor(",
  "export function HistoryScreen(",
  "History delay colors"
);
for (const [bucket, semanticColor] of [
  ["early", "green"],
  ["on_time", "blue"],
  ["delayed_warn", "amber"],
  ["delayed_bad", "red"]
]) {
  assert.match(
    delayColors,
    new RegExp(`case "${bucket}":[\\s\\S]*?return palette\\.${semanticColor};`),
    `History delay bucket ${bucket} must use palette.${semanticColor}.`
  );
}
assert.match(
  delayColors,
  /return hexToRgba\(palette\.textMuted, 0\.45\);/,
  "Unknown delay buckets must use the active muted palette treatment."
);
assert.doesNotMatch(screensSource, /DELAY_BUCKET_COLORS/, "Hardcoded delay bucket maps must not return.");
for (const staleColor of ["#18d66a", "#4a9eda", "#f2b84b", "#ff5d5d", '"#888"']) {
  assert.equal(
    screensSource.toLowerCase().includes(staleColor.toLowerCase()),
    false,
    `AppScreens.tsx must not restore stale History delay color ${staleColor}.`
  );
}

assert.match(
  appShellSource,
  /setStyleBridge\(styles, palette\);/,
  "Runtime appearance changes must continue updating the shared style bridge."
);
assert.match(
  styleBridgeSource,
  /export let palette: MobileAppearance/,
  "Extracted screens need the live runtime palette binding."
);

const flightDetailSheet = sourceSection(
  screensSource,
  "export function FlightDetailSheet(",
  "export function FlightActionSheet(",
  "Flight detail sheet"
);
assert.match(
  flightDetailSheet,
  /\{detail \? \(/,
  "Seeded flight details must remain visible while live enrichment loads."
);
assert.doesNotMatch(
  flightDetailSheet,
  /!loading && detail \? \(/,
  "Loading enrichment must not blank an already available flight detail."
);
const detailFailure = sourceSection(
  flightDetailHookSource,
  "} catch (exc) {",
  "} finally {",
  "Flight detail failure fallback"
);
assert.doesNotMatch(
  detailFailure,
  /setData\(null\)/,
  "A failed enrichment request must not erase seeded board details."
);
assert.match(
  flightDetailHookSource,
  /preserveAvailableDetail/,
  "Empty enrichment responses must preserve usable seeded flight details."
);
assert.match(
  flightDomainSource,
  /origin_iata: row\.origin_iata \|\| origin \|\| null/,
  "Standalone Board details must retain supplied origin information."
);
assert.match(
  flightDomainSource,
  /sched_time: row\.sched_time \|\| row\.time_primary \|\| row\.display_time \|\| null/,
  "Standalone Board details must retain supplied schedule timing."
);
assert.match(
  boardModelSource,
  /row\.callsign\) \|\| clean\(row\.flight_number\) \|\| clean\(row\.flight_display\)/,
  "Board rows without a canonical callsign must still open schedule details."
);

console.log("Mobile visual contract checks passed.");
