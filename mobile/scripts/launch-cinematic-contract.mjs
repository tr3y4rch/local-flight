#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const mobileRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (relativePath) => fs.readFileSync(path.join(mobileRoot, relativePath), "utf8");
const presentation = await import(pathToFileURL(path.join(mobileRoot, "src/domain/launchPresentation.ts")).href);
const overlay = read("src/components/LaunchOverlay.tsx");
const hook = read("src/hooks/useLaunchOverlay.ts");
const shell = read("src/app/AppShell.tsx");

assert.equal(presentation.LAUNCH_MIN_MS, 6_000);
assert.equal(presentation.LAUNCH_NETWORK_CEILING_MS, 7_000);
assert.equal(presentation.LAUNCH_REDUCED_MOTION_MS, 1_200);
assert.equal(presentation.LAUNCH_AMBIENT_SWEEP_MS, 7_200);
assert.equal(presentation.LAUNCH_AMBIENT_BREATH_MS, 3_800);

for (const [elapsed, phase] of [
  [500, "atmosphere"],
  [1_200, "radar_wake"],
  [2_000, "aircraft_orbit"],
  [4_000, "intercept"],
  [5_200, "brand_resolve"],
  [6_000, "ambient"]
]) {
  assert.equal(presentation.launchCinematicPhaseAt(elapsed), phase, `incorrect cinematic phase at ${elapsed}ms`);
}
assert.equal(presentation.launchCinematicPhaseAt(500, true), "brand_resolve");
assert.equal(presentation.launchCinematicPhaseAt(1_200, true), "ambient");

const baseReadiness = {
  hydrated: true,
  sequenceComplete: true,
  dataOutcome: "pending",
  networkCeilingReached: false
};
assert.equal(presentation.launchCanEnter({ ...baseReadiness, sequenceComplete: false, dataOutcome: "live" }), false);
assert.equal(presentation.launchCanEnter({ ...baseReadiness, hydrated: false, dataOutcome: "live" }), false);
assert.equal(presentation.launchCanEnter({ ...baseReadiness, dataOutcome: "live" }), true);
assert.equal(presentation.launchCanEnter({ ...baseReadiness, dataOutcome: "cached" }), true);
assert.equal(presentation.launchCanEnter({ ...baseReadiness, networkCeilingReached: true }), true);

assert.deepEqual(
  presentation.launchStatusPresentation({ hydrated: false, ready: false, dataOutcome: "pending", networkCeilingReached: false }),
  { status: "Restoring this device", qualifier: null }
);
assert.deepEqual(
  presentation.launchStatusPresentation({ hydrated: true, ready: true, dataOutcome: "offline", networkCeilingReached: false }),
  { status: "Checking shared information", qualifier: "Offline · cached information may be shown" }
);

for (const token of [
  "AircraftGlyph",
  "RadarVectorLayer",
  "SweepLayer",
  "BLIPS",
  "routeTrace",
  "aircraftRoutePath",
  "aircraftRouteKeyframes",
  "ambientSweepRotation",
  "breathingScale",
  "Tap anywhere to enter",
  "Tap anywhere to continue setup"
]) {
  assert.ok(overlay.includes(token), `cinematic launcher is missing ${token}`);
}
assert.doesNotMatch(overlay, /progressTrack|progressFill|enterButton|statusCard/);
assert.doesNotMatch(overlay, /AircraftGlyph color=\{appearance\.text\} accent=/, "the moving aircraft must not carry the logo accent");
assert.match(overlay, /styles\.aircraftMotion[\s\S]*translateX: aircraftX[\s\S]*styles\.aircraftLockMotion/, "aircraft and lock must share one translated route");
assert.doesNotMatch(overlay, /expo-haptics|expo-av|Audio\./);
assert.match(hook, /requestAnimationFrame\(startCinematic\)/, "cinematic must begin after the native-splash handoff");
assert.match(hook, /AppState\.addEventListener\("change"/);
assert.match(hook, /stopAmbient\(\)/);
assert.match(hook, /sequenceCompleteRef\.current/);
assert.equal((hook.match(/Animated\.loop\(/g) || []).length, 2, "only the bounded sweep and breathing loops are expected");
assert.doesNotMatch(hook, /setInterval|autoEnter|setTimeout\([^)]*enter/);
assert.doesNotMatch(shell, /launchOverlay:|launchProgressTrack:|launchEnterButton:/, "obsolete shell launcher styles remain active");

console.log("Cinematic launcher timing, readiness, motion, copy, and cleanup contracts passed.");
