#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const mobileRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const explicitPath = process.argv[2] ? path.resolve(process.cwd(), process.argv[2]) : "";
const mergedRoot = path.join(mobileRoot, "android", "app", "build", "intermediates");

function findReleaseManifests(directory, found = []) {
  if (!fs.existsSync(directory)) return found;
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const item = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      findReleaseManifests(item, found);
    } else if (
      entry.name === "AndroidManifest.xml" &&
      /merged[_-]?manifest/i.test(item) &&
      /release/i.test(item)
    ) {
      found.push(item);
    }
  }
  return found;
}

const manifests = explicitPath ? [explicitPath] : findReleaseManifests(mergedRoot);
assert.ok(
  manifests.length > 0,
  "No merged release manifest found. Build the release AAB first, then pass its merged AndroidManifest.xml path to this script."
);

for (const manifestPath of manifests) {
  assert.ok(fs.existsSync(manifestPath), `Manifest does not exist: ${manifestPath}`);
  const manifest = fs.readFileSync(manifestPath, "utf8");
  const billingDeclarations = manifest.match(
    /<uses-permission\b[^>]*android:name=["']com\.android\.vending\.BILLING["'][^>]*>/g
  ) || [];
  assert.equal(
    billingDeclarations.length,
    1,
    `${manifestPath} must declare com.android.vending.BILLING exactly once`
  );
  assert.ok(
    !manifest.includes("com.android.vending.CHECK_LICENSE"),
    `${manifestPath} must not contain the obsolete Google Play Licensing permission`
  );
  assert.match(
    manifest,
    /<meta-data\b[^>]*android:name=["']cc\.beacontools\.localflight\.RELAY_ACCESS_PRODUCT_ID["'][^>]*android:value=["']cc\.beacontools\.localflight\.relay_access["'][^>]*>/,
    `${manifestPath} must declare the Relay Access managed product`
  );
  const integrityMetadata = manifest.match(
    /<meta-data\b[^>]*android:name=["']cc\.beacontools\.localflight\.PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER["'][^>]*android:value=["']project:([1-9][0-9]{5,19})["'][^>]*>/
  );
  assert.ok(
    integrityMetadata,
    `${manifestPath} must contain a configured Play Integrity Cloud project number`
  );
  for (const forbidden of [
    "android.permission.RECORD_AUDIO",
    "android.permission.READ_EXTERNAL_STORAGE",
    "android.permission.WRITE_EXTERNAL_STORAGE",
    "android.permission.SYSTEM_ALERT_WINDOW"
  ]) {
    assert.ok(!manifest.includes(forbidden), `${manifestPath} unexpectedly contains ${forbidden}`);
  }
}

console.log(`Merged Android release manifest checks passed (${manifests.length} file${manifests.length === 1 ? "" : "s"}).`);
