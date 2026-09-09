#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const lock = JSON.parse(fs.readFileSync(path.join(root, "package-lock.json"), "utf8"));
let checked = 0;
for (const [location, entry] of Object.entries(lock.packages)) {
  if (!entry.resolved?.startsWith("https://registry.npmjs.org/")) continue;
  const manifest = path.join(root, location, "package.json");
  if (!fs.existsSync(manifest) && entry.optional) continue;
  const installed = JSON.parse(fs.readFileSync(manifest, "utf8"));
  assert.equal(installed.version, entry.version,
    `${location}: a warm npm cache must not hide an incorrect lockfile version`);
  checked += 1;
}
assert.ok(checked > 0, "Install dependencies before checking the lockfile");
console.log(`Dependency lock contract passed for ${checked} installed registry packages.`);
