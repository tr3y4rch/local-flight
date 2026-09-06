#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");
const require = createRequire(import.meta.url);
const appConfig = require(path.join(root, "app.config.js"));
const eas = JSON.parse(read("eas.json"));
const staticApp = JSON.parse(read("app.json")).expo;

const staging = appConfig.resolveRelayDeployment({
  EXPO_PUBLIC_LOCALFLIGHT_DEPLOYMENT: "staging"
});
const production = appConfig.resolveRelayDeployment({
  EXPO_PUBLIC_LOCALFLIGHT_DEPLOYMENT: "production"
});
const playIntegrityProject = appConfig.resolvePlayIntegrityProjectNumber({
  LOCALFLIGHT_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER: "123456789012"
});

assert.equal(staging.deployment, "staging");
assert.deepEqual(staging.acceptedPurchaseEnvironments, ["sandbox", "test"]);
assert.equal(production.deployment, "production");
assert.deepEqual(production.acceptedPurchaseEnvironments, ["production"]);
assert.notEqual(staging.canonicalOrigin, production.canonicalOrigin);
assert.match(staging.canonicalOrigin, /^https:\/\//);
assert.equal(production.canonicalOrigin, "https://relay.beacontools.cc");
assert.equal(playIntegrityProject, "123456789012");
assert.equal(appConfig.resolvePlayIntegrityProjectNumber({}), "");
assert.throws(
  () => appConfig.resolvePlayIntegrityProjectNumber({
    LOCALFLIGHT_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER: "not-a-number"
  }),
  /Google Cloud project number/
);

const configuredPaidAppPlugins = appConfig.configuredPlugins(
  staticApp.plugins,
  playIntegrityProject
);
const paidAppPlugin = configuredPaidAppPlugins.find(
  (plugin) => Array.isArray(plugin) && plugin[0] === "./plugins/with-localflight-paid-app"
);
assert.ok(paidAppPlugin);
assert.equal(
  paidAppPlugin[1].relayAccessProductId,
  appConfig.GOOGLE_PLAY_RELAY_ACCESS_PRODUCT_ID
);
assert.equal(paidAppPlugin[1].playIntegrityCloudProjectNumber, playIntegrityProject);

const custom = appConfig.resolveRelayDeployment({
  EXPO_PUBLIC_LOCALFLIGHT_DEPLOYMENT: "staging",
  EXPO_PUBLIC_LOCALFLIGHT_RELAY_ORIGIN: "https://relay-staging.example.test/",
  EXPO_PUBLIC_LOCALFLIGHT_RELAY_FAILOVER_ORIGINS:
    "https://relay-staging-2.example.test,https://relay-staging-2.example.test,https://relay-staging.example.test"
});
assert.equal(custom.canonicalOrigin, "https://relay-staging.example.test");
assert.deepEqual(custom.failoverOrigins, ["https://relay-staging-2.example.test"]);
assert.throws(
  () => appConfig.resolveRelayDeployment({
    EXPO_PUBLIC_LOCALFLIGHT_DEPLOYMENT: "production",
    EXPO_PUBLIC_LOCALFLIGHT_RELAY_ORIGIN: "http://relay.beacontools.cc"
  }),
  /HTTPS origin/
);
assert.throws(
  () => appConfig.resolveRelayDeployment({
    EXPO_PUBLIC_LOCALFLIGHT_DEPLOYMENT: "production",
    EXPO_PUBLIC_LOCALFLIGHT_RELAY_ORIGIN: "https://relay.beacontools.cc/path"
  }),
  /without credentials, a path, query, or fragment/
);

for (const profileName of ["development", "preview", "beta"]) {
  const profile = eas.build[profileName];
  assert.equal(profile.env.EXPO_PUBLIC_LOCALFLIGHT_DEPLOYMENT, "staging");
  assert.equal(profile.env.EXPO_PUBLIC_LOCALFLIGHT_RELAY_ORIGIN, staging.canonicalOrigin);
  assert.notEqual(profile.env.EXPO_PUBLIC_LOCALFLIGHT_RELAY_ORIGIN, production.canonicalOrigin);
}
assert.equal(eas.build.development.environment, "development");
assert.equal(eas.build.preview.environment, "preview");
assert.equal(eas.build.beta.environment, "preview");
assert.equal(eas.build.production.environment, "production");
assert.equal(eas.build.production.env.EXPO_PUBLIC_LOCALFLIGHT_DEPLOYMENT, "production");
assert.equal(eas.build.production.env.EXPO_PUBLIC_LOCALFLIGHT_RELAY_ORIGIN, production.canonicalOrigin);
assert.equal(eas.build.beta.channel, "staging");
assert.equal(eas.build.production.channel, "production");
assert.equal(staticApp.extra.localFlight.relayOrigin, staging.canonicalOrigin);
assert.deepEqual(staticApp.extra.localFlight.relayFailoverOrigins, []);
assert.deepEqual(staticApp.extra.localFlight.acceptedPurchaseEnvironments, ["sandbox", "test"]);
assert.deepEqual(staticApp.extra.localFlightRelay.acceptedPurchaseEnvironments, ["sandbox", "test"]);

const serializedBuildConfig = JSON.stringify({ eas, staticApp });
assert.doesNotMatch(
  serializedBuildConfig,
  /BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY|api[_-]?key|service[_-]?account|client[_-]?secret/i,
  "tracked build profiles must contain origins and environment labels, never provider secrets"
);

console.log("Mobile staging/production relay profile contract passed.");
