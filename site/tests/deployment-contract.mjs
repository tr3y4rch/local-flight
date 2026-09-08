import assert from "node:assert/strict";
import { resolveDeployment } from "../deployment.mjs";

assert.deepEqual(resolveDeployment("production"), {
  siteOrigin: "https://beacontools.cc", relayOrigin: "https://relay.beacontools.cc"
});
assert.deepEqual(resolveDeployment("staging"), {
  siteOrigin: "https://staging.beacontools.cc", relayOrigin: "https://relay-staging.beacontools.cc"
});
assert.throws(() => resolveDeployment("preview"), /production or staging/);
console.log("Site deployment separation contract passed.");
