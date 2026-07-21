#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);
const mobileRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(mobileRoot, "..");
const contract = JSON.parse(fs.readFileSync(path.join(repoRoot, "contracts/radar-presentation-v1.json"), "utf8"));
const browserPresentation = require(path.join(repoRoot, "src/localflight/ui/static/radar-presentation.js"));
const mobilePresentationPath = path.join(mobileRoot, "src/domain/radarPresentation.ts");
const mobilePresentation = await import(pathToFileURL(mobilePresentationPath).href);
const mobilePresentationSource = fs.readFileSync(mobilePresentationPath, "utf8");
const screensSource = fs.readFileSync(path.join(mobileRoot, "src/screens/AppScreens.tsx"), "utf8");
const v2ScopeSource = fs.readFileSync(path.join(mobileRoot, "src/v2/RadarScopeV2.tsx"), "utf8");
const appShellSource = fs.readFileSync(path.join(mobileRoot, "src/app/AppShell.tsx"), "utf8");

function sourceSection(source, startMarker, endMarker, label) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start + startMarker.length);
  assert.notEqual(start, -1, `${label}: missing ${startMarker}`);
  assert.notEqual(end, -1, `${label}: missing ${endMarker}`);
  return source.slice(start, end);
}

assert.equal(browserPresentation.VERSION, contract.version);
assert.equal(browserPresentation.REVOLUTION_MS, contract.revolution_ms);
assert.equal(browserPresentation.FRAME_INTERVAL_MS, contract.frame_interval_ms);
assert.equal(browserPresentation.TRAIL_DEGREES, contract.trail_degrees);
assert.equal(browserPresentation.FLASH_DEGREES, contract.flash_degrees);
assert.equal(browserPresentation.FOCUSED_MIN_OPACITY, contract.focused_min_opacity);

for (const vector of contract.bearing_vectors) {
  assert.ok(
    Math.abs(browserPresentation.bearingFromOffset(vector.x_nm, vector.y_nm) - vector.bearing) < 0.000001,
    `${vector.name} bearing must match the cross-platform contract.`
  );
  assert.ok(
    Math.abs(mobilePresentation.radarBearingFromOffset(vector.x_nm, vector.y_nm) - vector.bearing) < 0.000001,
    `${vector.name} mobile bearing must match the cross-platform contract.`
  );
}
for (const vector of contract.opacity_vectors) {
  assert.ok(
    Math.abs(browserPresentation.blipOpacity(vector.target, vector.sweep, false) - vector.opacity) < 0.000001,
    `${vector.name} opacity must match the cross-platform contract.`
  );
  assert.ok(
    Math.abs(mobilePresentation.radarSweepOpacity(vector.target, vector.sweep, false) - vector.opacity) < 0.000001,
    `${vector.name} mobile opacity must match the cross-platform contract.`
  );
}

for (const [name, value] of [
  ["RADAR_PRESENTATION_VERSION", contract.version],
  ["RADAR_REVOLUTION_MS", contract.revolution_ms],
  ["RADAR_FRAME_INTERVAL_MS", contract.frame_interval_ms],
  ["RADAR_TRAIL_DEGREES", contract.trail_degrees],
  ["RADAR_FLASH_DEGREES", contract.flash_degrees],
  ["RADAR_FOCUSED_MIN_OPACITY", contract.focused_min_opacity]
]) {
  assert.match(mobilePresentationSource, new RegExp(`export const ${name} = ${String(value).replace("15000", "15_000")}`));
}
assert.match(mobilePresentationSource, /radarAngularAge\(sweepAngle, targetBearing\)/);
assert.doesNotMatch(mobilePresentationSource, /age\s*>?=\s*356/);
assert.match(mobilePresentationSource, /return palette\.textMuted;/, "Stale targets must use a muted palette tone.");
assert.doesNotMatch(mobilePresentationSource, /return palette\.red;/, "Stale tracks must not look like alarm failures.");

const sweepLayer = sourceSection(screensSource, "function RadarSweepLayer(", "function radarPresentationNow(", "Radar sweep layer");
assert.match(sweepLayer, /-farAge, -nearAge/, "The illuminated fan must trail behind the leading line.");
assert.equal((sweepLayer.match(/<Line/g) || []).length, 1, "The radar must draw exactly one scan line.");
assert.match(screensSource, /pointerEvents=\{interactive \? "auto" : "none"\}/, "Invisible targets must not intercept touches.");
assert.match(screensSource, /radarVisibleLabelKeys\(projected, scopeSize\)/, "Scope labels must use collision-aware priority selection.");
assert.match(screensSource, /const selectedTargetPresent =/, "Selected-target cleanup must not rerun solely because the sweep angle changed.");
assert.doesNotMatch(screensSource, /RADAR_BLIP_BASE_OPACITY|RADAR_SWEEP_STEP_DEG/, "Persistent blips and tick-count timing must not return.");
assert.match(v2ScopeSource, /layer === "runway"[\s\S]*?a\.amber/, "V2 runway geometry must retain the amber aviation treatment.");
assert.match(v2ScopeSource, /kind === "taxiway"[\s\S]*?a\.amber/, "V2 taxiways must remain distinct and visible.");
assert.match(v2ScopeSource, /const polygon = Boolean\(item\.feature\.closed && item\.points\.length >= 3\)/, "Closed runway areas must render as areas rather than collapsed outlines.");
assert.match(v2ScopeSource, /function RunwayIndicators\(/, "V2 runways must expose threshold and designator indicators.");
assert.match(v2ScopeSource, /runwayDesignators/, "V2 runway labels must distinguish opposite runway ends.");
assert.match(v2ScopeSource, /if \(\/band\|tile\|cell\|grid\/\.test\(kind\)\) return false/, "Terrain tiles and filled elevation grids must not appear as scope squares.");
assert.match(v2ScopeSource, /radarLabelPriority/, "Dense V2 labels must use semantic Radar priority.");
assert.match(v2ScopeSource, /const labelBudget =/, "Dense V2 scopes must enforce a bounded label budget.");
assert.match(v2ScopeSource, /radarSweepOpacity\(item\.angleDeg, sweepDeg, focused\)/, "V2 targets must be revealed by the sweep rather than persistently displayed.");
assert.match(v2ScopeSource, /accessibilityElementsHidden=\{!interactive\}/, "Unrevealed V2 targets must not remain in the accessibility tree.");
const v2SweepLayer = sourceSection(v2ScopeSource, "{!reduceMotion ? (", ") : null}", "V2 radar sweep layer");
assert.equal((v2SweepLayer.match(/<Line/g) || []).length, 1, "V2 Radar must draw exactly one leading sweep line.");
assert.match(appShellSource, /const fallbackGround = cachedGround \|\| data\.radar_map \|\| null/, "A failed full-ground request must preserve the embedded runway and surface fallback.");

console.log("Cross-platform radar presentation contract checks passed.");
