#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const mobileRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(mobileRoot, "..");
const activeFiles = [
  "mobile/src/content/en.ts",
  "mobile/src/screens/AppScreens.tsx",
  "mobile/src/v2/MoreScreenV2.tsx",
  "mobile/README.md",
  "site/src/pages/local-flight/mobile/index.astro",
  "site/src/pages/network/index.astro",
  "docs/display-modes.md",
  "docs/install.md"
];

const forbidden = [
  /every\s+3\s+hours?/i,
  /every\s+three\s+hours?/i,
  /every\s+5\s+minutes?/i,
  /every\s+five\s+minutes?/i,
  /\b3H\s*\/\s*5M\b/i,
  /\b3\s*h\b[\s\S]{0,60}\b5\s*min\b/i
];

for (const relativePath of activeFiles) {
  const source = fs.readFileSync(path.join(repoRoot, relativePath), "utf8");
  for (const pattern of forbidden) {
    assert.doesNotMatch(source, pattern, `${relativePath} contains retired Standalone cadence wording`);
  }
}

const catalog = fs.readFileSync(path.join(mobileRoot, "src/content/en.ts"), "utf8");
for (const required of [
  "Airline schedules usually refresh about once an hour.",
  "Nearby traffic can refresh about every 3 minutes while Radar is open.",
  "Shows up to 50 current departures and 50 arrivals when supplied.",
  "Shared information may still be cached or delayed.",
  "Check the latest shared information."
]) {
  assert.ok(catalog.includes(required), `copy catalog missing: ${required}`);
}

console.log("Standalone wording contract checks passed.");
