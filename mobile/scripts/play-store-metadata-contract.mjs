#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const mobileRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const metadataRoot = path.join(mobileRoot, "store", "android", "en-US");
const read = (name) => fs.readFileSync(path.join(metadataRoot, name), "utf8").trim();

const metadata = {
  title: read("title.txt"),
  shortDescription: read("short_description.txt"),
  fullDescription: read("full_description.txt"),
  websiteUrl: read("website_url.txt"),
  supportUrl: read("support_url.txt"),
  privacyUrl: read("privacy_url.txt"),
};

assert.ok(metadata.title.length >= 2 && metadata.title.length <= 30, "Play title must be 2-30 characters.");
assert.ok(metadata.shortDescription.length <= 80, "Play short description must be at most 80 characters.");
assert.ok(metadata.fullDescription.length <= 4000, "Play full description must be at most 4,000 characters.");
assert.match(metadata.fullDescription, /Android app is free to download/i);
assert.match(metadata.fullDescription, /one-time in-app purchase of Beacon Relay Access, with no subscription/i);
assert.match(metadata.fullDescription, /one phone using real-flight Standalone or one Local Flight desktop/);
assert.match(metadata.fullDescription, /Purchase or restore starts only after.*explicit real-flight setup action/is);
assert.match(metadata.fullDescription, /Companion and VATSIM are free to use and do not require or consume Relay Access/is);
assert.match(metadata.fullDescription, /Remote Companion requires Relay Access on its desktop host/);
assert.match(metadata.fullDescription, /named confirmation/);
assert.match(metadata.fullDescription, /integrity-protected transfer/i);
assert.match(metadata.fullDescription, /without another Google Play purchase/i);
assert.match(metadata.fullDescription, /never asks for or displays an LFRA key/i);
assert.match(metadata.fullDescription, /No Local Flight account required/);
assert.match(metadata.fullDescription, /support choices.*unlock nothing, add no subscription, and never create Relay Access/is);
assert.match(metadata.fullDescription, /Do not use Local Flight for navigation, dispatch, operational control/);
assert.doesNotMatch(metadata.fullDescription, /paid Google Play download|included Relay Access|access included|no extra purchase/i);
assert.doesNotMatch(metadata.fullDescription, /App Store|StoreKit|TestFlight|Stripe checkout|activation token/i);
assert.doesNotMatch(metadata.fullDescription, /\breceiver(?:s)?\b|\bseat(?:s)?\b|\bentitlement(?:s)?\b|provider evidence/i);

for (const [label, value] of Object.entries(metadata)) {
  if (label.endsWith("Url")) {
    assert.match(value, /^https:\/\/beacontools\.cc\//, `${label} must use the public Beacon Tools HTTPS site.`);
  }
}

console.log(
  `Google Play metadata checks passed: short description ${metadata.shortDescription.length}/80, ` +
  `full description ${metadata.fullDescription.length}/4000.`,
);
