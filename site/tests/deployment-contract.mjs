import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolveDeployment } from "../deployment.mjs";

assert.deepEqual(resolveDeployment("production"), {
  siteOrigin: "https://beacontools.cc", relayOrigin: "https://relay.beacontools.cc"
});
assert.deepEqual(resolveDeployment("staging"), {
  siteOrigin: "https://staging.beacontools.cc", relayOrigin: "https://relay-staging.beacontools.cc"
});
assert.throws(() => resolveDeployment("preview"), /production or staging/);
const supportSource = readFileSync(new URL("../src/scripts/support.ts", import.meta.url), "utf8");
assert.doesNotMatch(supportSource, /https:\/\/relay\.beacontools\.cc/);
assert.match(supportSource, /form\.dataset\.relayOrigin/);
console.log("Site deployment separation contract passed.");
