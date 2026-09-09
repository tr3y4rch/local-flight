#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const mobileRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(mobileRoot, "..");
const read = (relative) => fs.readFileSync(path.join(mobileRoot, relative), "utf8");

const packageJson = JSON.parse(read("package.json"));
const appJson = JSON.parse(read("app.json"));
const products = read("src/iap/products.ts");
const hook = read("src/iap/useSupportPurchases.ts");
const api = read("src/api/iap.ts");
const screens = read("src/screens/AppScreens.tsx");
const more = read("src/v2/MoreScreenV2.tsx");
const supportContent = read("src/iap/SupportPurchaseContent.tsx");
const relay = fs.readFileSync(path.join(repoRoot, "relay/main.py"), "utf8");

assert.equal(packageJson.dependencies["expo-iap"], "^4.4.1");
assert.ok(appJson.expo.plugins.includes("expo-iap"), "expo-iap config plugin must be enabled");

for (const suffix of ["small", "medium", "large"]) {
  const productId = `cc.beacontools.localflight.support.${suffix}`;
  assert.match(products, new RegExp(productId.replaceAll(".", "\\.")));
  assert.match(relay, new RegExp(productId.replaceAll(".", "\\.")));
}
assert.doesNotMatch(products, /\$|CHF|EUR|USD|displayPrice:\s*["']/i, "Product prices must come from the store");
assert.match(hook, /displayPrice:\s*product\.displayPrice/);
assert.match(hook, /productStatusAndroid/);
assert.match(hook, /no-offers-available/);
assert.match(hook, /not-found/);
assert.match(hook, /supportCatalogDiagnostic/);
assert.match(hook, /loadedCount/);
assert.match(hook, /missingCount/);
assert.match(hook, /views\.length !== SUPPORT_PRODUCT_IDS\.length/);
assert.match(hook, /getSupportPurchaseReadiness/);
assert.match(hook, /result\.purchases_enabled/);
assert.doesNotMatch(hook, /if \(!purchasesEnabled\) return;/, "A new-purchase hold must not block unfinished purchase recovery");
assert.match(hook, /!purchasesEnabled \|\| !iap\.connected/);
assert.match(hook, /!verificationReady/);
assert.match(hook, /verifySupportPurchase\(/);
assert.match(hook, /finishTransaction\(\{ purchase, isConsumable: true \}\)/);
assert.ok(
  hook.indexOf("verifySupportPurchase(") < hook.indexOf("finishTransaction({ purchase, isConsumable: true })"),
  "Relay verification must happen before the consumable transaction is finished."
);
assert.match(hook, /getAvailablePurchases\(/, "Unfinished purchases must be recovered after launch");
assert.match(api, /\/v1\/mobile\/iap\/verify/);
assert.match(api, /\/v1\/mobile\/iap\/status/);
assert.match(api, /await delay\(1200\)/, "Relay verification gets one bounded retry");
assert.match(api, /status == null \|\| status >= 500/, "Rate limits must not trigger an immediate retry");
assert.doesNotMatch([hook, api, screens].join("\n"), /buymeacoffee|patreon|paypal/i);
assert.match(screens, /Every app feature stays the same|unlocks no features/i);
assert.match(screens, /Apple or Google handles payment details/);
assert.match(supportContent, /Tips unlock nothing and do not include Relay Access/);
assert.match(supportContent, /Apple or Google handles payment details/);
assert.match(supportContent, /Purchases on hold/);
assert.match(supportContent, /Existing purchases can still be checked/);
assert.match(more, /Optional one-time support\. No features are locked\./);
assert.ok(
  more.indexOf("styles.supportFooter") > more.indexOf("styles.setupButton"),
  "V2 support must remain a quiet final setting instead of a primary app feature."
);
assert.equal(
  (screens.match(/<SupportFooterButton\s/g) || []).length,
  2,
  "Companion and Standalone must both expose the discreet support button."
);
assert.match(screens, /style=\{styles\.supportFooter\}/);
assert.match(screens, /SUPPORT_ICONS\.support[^\n]+palette\.amber/);
assert.doesNotMatch(
  screens,
  /<ControlActionCard[\s\S]{0,220}title="Support Local Flight"/,
  "Support must remain a discreet amber action rather than another full settings card."
);
assert.match(
  screens,
  /controller\.products\.length === SUPPORT_PRODUCT_IDS\.length/,
  "The purchase sheet must stay disabled until all three allowlisted tiers load."
);
for (const [startMarker, endMarker, label] of [
  ["export function ControlScreen(", "export function StandaloneSettingsScreen(", "Companion Control"],
  ["export function StandaloneSettingsScreen(", "function SupportPurchaseSheet(", "Standalone Settings"]
]) {
  const section = screens.slice(screens.indexOf(startMarker), screens.indexOf(endMarker));
  assert.ok(
    section.indexOf("<SupportFooterButton") > section.indexOf('title="Help & Reports"'),
    `${label} must keep optional support at the bottom of the settings page.`
  );
}
assert.doesNotMatch(screens, /Store price:|label="Recovery"/, "The support sheet must stay concise and user-focused.");

assert.match(relay, /CREATE TABLE IF NOT EXISTS iap_transactions/);
assert.match(relay, /transaction_hash\s+TEXT PRIMARY KEY/);
assert.match(relay, /@app\.post\("\/v1\/mobile\/iap\/verify"\)/);
assert.match(relay, /@app\.get\("\/v1\/mobile\/iap\/status"\)/);
assert.match(relay, /_mobile_iap_verification_ready/);
assert.match(relay, /RELAY_SUPPORT_PURCHASES_ENABLED/);
const verificationRoute = relay.slice(relay.indexOf('def verify_mobile_iap('), relay.indexOf('\n@app.', relay.indexOf('def verify_mobile_iap(')));
assert.doesNotMatch(verificationRoute, /_support_purchases_enabled\(/, "Confirmed purchases remain recoverable during a sales hold");
assert.match(relay, /_verify_apple_iap/);
assert.match(relay, /_verify_google_iap/);
assert.doesNotMatch(
  relay.match(/CREATE TABLE IF NOT EXISTS iap_transactions[\s\S]*?\)\n\s*"""/)?.[0] || "",
  /purchase_token|signed_transaction|raw_receipt|transaction_id/,
  "The IAP ledger must not persist raw store evidence."
);

console.log("Mobile IAP contract checks passed.");
