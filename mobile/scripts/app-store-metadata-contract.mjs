#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const mobileRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const metadataRoot = path.join(mobileRoot, "store", "ios", "en-US");
const read = (name) => fs.readFileSync(path.join(metadataRoot, name), "utf8").trim();

const metadata = {
  name: read("name.txt"),
  subtitle: read("subtitle.txt"),
  promotionalText: read("promotional_text.txt"),
  keywords: read("keywords.txt"),
  description: read("description.txt"),
  marketingUrl: read("marketing_url.txt"),
  supportUrl: read("support_url.txt"),
  privacyUrl: read("privacy_url.txt"),
};

assert.ok(metadata.name.length >= 2 && metadata.name.length <= 30, "App name must be 2-30 characters.");
assert.ok(metadata.subtitle.length <= 30, "Subtitle must be at most 30 characters.");
assert.ok(metadata.promotionalText.length <= 170, "Promotional text must be at most 170 characters.");
assert.ok(metadata.description.length <= 4000, "Description must be at most 4,000 characters.");
assert.ok(Buffer.byteLength(metadata.keywords, "utf8") <= 100, "Keywords must be at most 100 UTF-8 bytes.");

assert.equal(metadata.name, "Local Flight");
assert.match(metadata.promotionalText, /Companion/);
assert.match(metadata.promotionalText, /Standalone/);
assert.match(metadata.description, /end-to-end encrypted relay routing/);
assert.match(metadata.description, /NO HOST\? USE STANDALONE\./);
assert.match(metadata.description, /Connect to a Local Flight host/);
assert.match(metadata.description, /Use without a Local Flight host/);
assert.match(metadata.description, /real airline data|airline schedules/i);
assert.match(metadata.description, /VATSIM (?:virtual )?traffic/);
assert.match(metadata.description, /Home Screen widgets/);
assert.match(metadata.description, /pinned-flight Live Activity/);
assert.match(metadata.description, /Board \/ Radar \/ History \/ More/);
assert.match(metadata.description, /VATSIM-focused virtual view/);
assert.match(metadata.description, /No Local Flight account required/);
assert.match(metadata.description, /paid App Store download includes Beacon Relay Access/i);
assert.match(metadata.description, /There is no subscription or extra purchase/);
assert.match(metadata.description, /one phone using real-flight Standalone or one Local Flight desktop/);
assert.match(metadata.description, /explicit real-flight setup or restore action/);
assert.match(metadata.description, /VATSIM virtual traffic does not use Relay Access/);
assert.match(metadata.description, /never asks for or displays an LFRA key/);
assert.match(metadata.description, /leaves the included Relay Access available for another main device/);
assert.match(metadata.description, /Remote Companion.*requires.*Relay Access on that host/is);
assert.match(metadata.description, /named confirmation/);
assert.match(metadata.description, /previous main device stays active until the receiving device stores and commits its new credential/);
assert.match(metadata.description, /No advertising SDKs or cross-app tracking/);
assert.match(metadata.description, /Three one-time App Store support choices/);
assert.match(metadata.description, /They unlock nothing, add no subscription/);
assert.match(metadata.description, /Do not use Local Flight for navigation, dispatch, operational control/);

for (const [label, value] of Object.entries(metadata)) {
  if (label.endsWith("Url")) {
    assert.match(value, /^https:\/\/beacontools\.cc\//, `${label} must use the public Beacon Tools HTTPS site.`);
  }
}

const appleCopy = [
  metadata.name,
  metadata.subtitle,
  metadata.promotionalText,
  metadata.keywords,
  metadata.description,
].join("\n");
assert.doesNotMatch(appleCopy, /\bAndroid\b|Google Play|TestFlight|\bbeta\b/i, "Public Apple copy must remain Apple-specific and release-ready.");
assert.doesNotMatch(appleCopy, /provider secret|activation token|operator|admin endpoint|Linear team/i, "Internal implementation language must not leak into store copy.");
assert.doesNotMatch(appleCopy, /\bthis phone\b|phone-only|fastest and safest/i, "Public copy must use device-neutral, substantiated language.");
assert.doesNotMatch(appleCopy, /\breceiver(?:s)?\b|\bseat(?:s)?\b|\bentitlement(?:s)?\b|provider evidence/i, "Public licensing copy must use main-device language.");
assert.doesNotMatch(appleCopy, /Stripe|checkout|purchase link/i, "The paid mobile app must not advertise web checkout.");

console.log(
  `Apple App Store metadata checks passed: subtitle ${metadata.subtitle.length}/30, ` +
  `promotional text ${metadata.promotionalText.length}/170, ` +
  `keywords ${Buffer.byteLength(metadata.keywords, "utf8")}/100 bytes, ` +
  `description ${metadata.description.length}/4000.`
);
