#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { shouldRetryOfficialPublicRelay } from "../src/api/relayFallbackPolicy.ts";

const mobileRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const shell = fs.readFileSync(path.join(mobileRoot, "src/app/AppShell.tsx"), "utf8");
const standalone = fs.readFileSync(path.join(mobileRoot, "src/api/standalone.ts"), "utf8");

for (const status of [404, 405, 408, 500, 502, 503]) {
  assert.equal(shouldRetryOfficialPublicRelay({ status, contentType: "application/json", hasJsonPayload: true }), true);
}
for (const status of [401, 403, 409, 422, 429]) {
  assert.equal(shouldRetryOfficialPublicRelay({ status, contentType: "application/json", hasJsonPayload: true }), false);
}
assert.equal(shouldRetryOfficialPublicRelay({ status: 403, contentType: "text/html", hasJsonPayload: false }), true);
assert.equal(shouldRetryOfficialPublicRelay({ status: 429, contentType: "application/json", hasJsonPayload: false }), false);
assert.equal(shouldRetryOfficialPublicRelay({ status: 429, contentType: "text/html", hasJsonPayload: false }), false);
assert.equal(shouldRetryOfficialPublicRelay({ status: 200, contentType: "text/html", hasJsonPayload: false }), true);

assert.match(standalone, /recoveredByOfficialFallback: response\.ok && index > 0/);
assert.match(standalone, /routeFamily/);
assert.match(standalone, /httpClass/);
const diagnosticShape = standalone.match(/export type StandaloneRelayDiagnostic = \{[\s\S]*?\n\};/)?.[0] || "";
assert.doesNotMatch(diagnosticShape, /activationToken|installId|relayUrl/);
assert.match(shell, /dashboardError = exc;[\s\S]*?await fetchFidsData\(normalized, nextView\)/);
assert.doesNotMatch(shell, /dashboardError = exc;[\s\S]{0,180}?setRows\(\[\]\)/);

console.log("Relay resilience contract checks passed.");
