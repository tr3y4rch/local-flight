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
assert.match(hook, /verifySupportPurchase\(/);
assert.match(hook, /finishTransaction\(\{ purchase, isConsumable: true \}\)/);
assert.ok(
  hook.indexOf("verifySupportPurchase(") < hook.indexOf("finishTransaction({ purchase, isConsumable: true })"),
  "Relay verification must happen before the consumable transaction is finished."
);
assert.match(hook, /getAvailablePurchases\(/, "Unfinished purchases must be recovered after launch");
assert.match(api, /\/v1\/mobile\/iap\/verify/);
assert.match(api, /await delay\(1200\)/, "Relay verification gets one bounded retry");
assert.match(api, /status == null \|\| status >= 500/, "Rate limits must not trigger an immediate retry");
assert.doesNotMatch([hook, api, screens].join("\n"), /buymeacoffee|patreon|paypal/i);
assert.match(screens, /Nothing is locked|unlocks no features/i);
assert.match(screens, /Local Flight never receives card details/);
assert.match(supportContent, /Nothing is locked or changed/);
assert.match(supportContent, /Local Flight never receives card details/);
assert.match(more, /Optional one-time support · unlocks nothing/);
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
assert.match(relay, /_verify_apple_iap/);
assert.match(relay, /_verify_google_iap/);
assert.doesNotMatch(
  relay.match(/CREATE TABLE IF NOT EXISTS iap_transactions[\s\S]*?\)\n\s*"""/)?.[0] || "",
  /purchase_token|signed_transaction|raw_receipt|transaction_id/,
  "The IAP ledger must not persist raw store evidence."
);

console.log("Mobile IAP contract checks passed.");
