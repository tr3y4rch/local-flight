#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");
const require = createRequire(import.meta.url);

const app = JSON.parse(read("app.json")).expo;
const packageJson = JSON.parse(read("package.json"));
const modulePackage = JSON.parse(read("modules/localflight-paid-app/package.json"));
const plugins = app.plugins.map((plugin) => Array.isArray(plugin) ? plugin[0] : plugin);
const billingPermission = "com.android.vending.BILLING";
const legacyPermission = "com.android.vending.CHECK_LICENSE";
const productId = "cc.beacontools.localflight.relay_access";

assert.equal(app.version, packageJson.version);
assert.equal(modulePackage.version, packageJson.version);
assert.ok(plugins.includes("./plugins/with-localflight-paid-app"));
assert.ok(app.android.permissions.includes(billingPermission));
assert.ok(!app.android.permissions.includes(legacyPermission));

const manifestPlugin = require(path.join(root, "plugins", "with-localflight-paid-app.js"));
assert.equal(manifestPlugin.BILLING_PERMISSION, billingPermission);
assert.equal(manifestPlugin.LEGACY_LICENSE_PERMISSION, legacyPermission);
assert.equal(manifestPlugin.RELAY_ACCESS_PRODUCT_ID, productId);
assert.equal(manifestPlugin.normalizeProjectNumber(" 123456789012 "), "123456789012");
assert.throws(() => manifestPlugin.normalizeProjectNumber("project-id"));

const manifest = {
  "uses-permission": [
    { $: { "android:name": "android.permission.CAMERA" } },
    { $: { "android:name": legacyPermission } },
  ],
  application: [{ "meta-data": [] }],
};
manifestPlugin.configurePaidAppManifest(manifest, {
  playIntegrityCloudProjectNumber: "123456789012",
});
manifestPlugin.configurePaidAppManifest(manifest, {
  playIntegrityCloudProjectNumber: "123456789012",
});
assert.equal(
  manifest["uses-permission"].filter((item) => item.$?.["android:name"] === billingPermission).length,
  1,
  "the app manifest must contain BILLING exactly once"
);
assert.equal(
  manifest["uses-permission"].filter((item) => item.$?.["android:name"] === legacyPermission).length,
  0,
  "the obsolete LVL permission must be removed"
);
const configuredMetadata = manifest.application[0]["meta-data"];
assert.equal(
  configuredMetadata.find((item) => item.$?.["android:name"] === manifestPlugin.PRODUCT_ID_METADATA)?.$?.["android:value"],
  productId
);
assert.equal(
  configuredMetadata.find((item) => item.$?.["android:name"] === manifestPlugin.INTEGRITY_PROJECT_METADATA)?.$?.["android:value"],
  "project:123456789012"
);

const bridge = read("modules/localflight-paid-app/src/index.ts");
const apple = read("modules/localflight-paid-app/ios/LocalFlightPaidAppModule.swift");
const applePodspec = read("modules/localflight-paid-app/ios/LocalFlightPaidApp.podspec");
const android = read(
  "modules/localflight-paid-app/android/src/main/java/cc/beacontools/localflight/paidapp/LocalFlightPaidAppModule.kt"
);
const androidManifest = read("modules/localflight-paid-app/android/src/main/AndroidManifest.xml");
const generatedAndroidManifest = read("android/app/src/main/AndroidManifest.xml");
const generatedAndroidBuild = read("android/app/build.gradle");
const androidBuild = read("modules/localflight-paid-app/android/build.gradle");
const privacyPlugin = read("plugins/with-localflight-privacy-manifest.js");
const privacyManifest = read("ios/LocalFlight/PrivacyInfo.xcprivacy");
const xcodeProject = read("ios/LocalFlight.xcodeproj/project.pbxproj");
const readme = read("README.md");
const appStoreReviewNotes = read("APP_STORE_REVIEW_NOTES.md");
const playStoreReviewNotes = read("PLAY_STORE_REVIEW_NOTES.md");

const proofErrorCodes = [
  "store_cancelled",
  "store_unavailable",
  "ownership_unverified",
  "device_verification_missing",
  "store_timeout",
  "unsupported_build",
  "purchase_pending",
];
for (const code of proofErrorCodes) {
  assert.ok(bridge.includes(`"${code}"`), `bridge is missing stable error ${code}`);
  assert.ok(apple.includes(`"${code}"`), `iOS bridge is missing stable error ${code}`);
  assert.ok(android.includes(`"${code}"`), `Android bridge is missing stable error ${code}`);
}

assert.match(bridge, /GOOGLE_PLAY_RELAY_ACCESS_PRODUCT_ID/);
assert.match(bridge, /queryGooglePlayRelayAccessPurchase/);
assert.match(bridge, /purchaseGooglePlayRelayAccess/);
assert.match(bridge, /requestGooglePlayIntegrityToken/);
assert.match(bridge, /state: GooglePlayRelayAccessPurchaseState/);
assert.match(bridge, /purchaseToken: string/);
assert.match(bridge, /export function paidAppProofErrorCode/);
assert.match(bridge, /class PaidAppProofError extends Error/);

assert.match(apple, /AppTransaction\.refresh\(\)/);
assert.match(apple, /case \.userCancelled/);
assert.match(apple, /case \.verified/);
assert.match(apple, /AppStore\.deviceVerificationID/);
assert.match(apple, /jwsRepresentation/);
assert.match(apple, /requestGooglePlayIntegrityToken/);
assert.match(applePodspec, /:ios => "16\.0"/);
assert.doesNotMatch(apple, /AppTransaction\.shared/);

assert.match(androidBuild, /com\.android\.billingclient:billing:9\.1\.0/);
assert.match(androidBuild, /com\.google\.android\.play:integrity:1\.6\.0/);
assert.doesNotMatch(androidBuild, /aidl true/);
assert.match(androidManifest, /com\.android\.vending\.BILLING/);
assert.doesNotMatch(androidManifest, /com\.android\.vending\.CHECK_LICENSE/);
for (const legacyAidl of ["ILicenseResultListener.aidl", "ILicensingService.aidl"]) {
  assert.equal(
    fs.existsSync(path.join(
      root,
      "modules/localflight-paid-app/android/src/main/aidl/com/android/vending/licensing",
      legacyAidl
    )),
    false,
    `${legacyAidl} must be removed`
  );
}

assert.match(android, /BillingClient\.newBuilder/);
assert.match(android, /enableOneTimeProducts\(\)/);
assert.match(android, /queryPurchasesAsync/);
assert.match(android, /queryProductDetailsAsync/);
assert.match(android, /launchBillingFlow/);
assert.match(android, /Purchase\.PurchaseState\.PURCHASED/);
assert.match(android, /Purchase\.PurchaseState\.PENDING/);
assert.match(android, /IntegrityManagerFactory\.createStandard/);
assert.match(android, /prepareIntegrityToken/);
assert.match(android, /setRequestHash\(requestHash\)/);
assert.match(android, /response\.token\(\)/);
assert.match(android, /localflight-relay-grant-v1/);
assert.match(android, /"\$\{PaidAppConfiguration\.INTEGRITY_BINDING_VERSION\}:\$nonce:\$installId:\$activationGrant"/);
assert.match(android, /MessageDigest\.getInstance\("SHA-256"\)/);
assert.match(android, /Base64\.URL_SAFE or Base64\.NO_WRAP or Base64\.NO_PADDING/);
assert.doesNotMatch(android, /ILicensingService|checkLicense|LICENSED_OLD_KEY/);
assert.doesNotMatch(android, /public.?key|BASE64_PUBLIC|Signature\.getInstance/i);

assert.match(generatedAndroidManifest, /com\.android\.vending\.BILLING/);
assert.doesNotMatch(generatedAndroidManifest, /com\.android\.vending\.CHECK_LICENSE/);
assert.match(generatedAndroidManifest, /cc\.beacontools\.localflight\.RELAY_ACCESS_PRODUCT_ID/);
assert.match(generatedAndroidManifest, /cc\.beacontools\.localflight\.PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER/);
assert.match(generatedAndroidBuild, /LOCALFLIGHT_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER/);
assert.match(generatedAndroidBuild, /manifestPlaceholders\["localFlightPlayIntegrityCloudProjectNumber"\]/);

assert.match(privacyPlugin, /NSPrivacyCollectedDataTypePurchaseHistory/);
assert.match(privacyPlugin, /NSPrivacyCollectedDataTypeDeviceID/);
assert.match(privacyPlugin, /addResourceFileToGroup/);
assert.match(privacyManifest, /NSPrivacyCollectedDataTypePurchaseHistory/);
assert.match(privacyManifest, /<key>NSPrivacyTracking<\/key>[\s\S]*?<false\/>/);
assert.match(xcodeProject, /PrivacyInfo\.xcprivacy in Resources/);
const mainResources = xcodeProject.match(
  /13B07F8E1A680F5B00A75B9A \/\* Resources \*\/ = \{[\s\S]*?files = \(([\s\S]*?)\);/
);
assert.ok(mainResources, "main iOS application Resources phase is missing");
assert.match(mainResources[1], /PrivacyInfo\.xcprivacy in Resources/);

assert.match(readme, /iOS `0\.6\.0 \(13\)` and Android `0\.6\.0 \(16\)`/);
assert.match(appStoreReviewNotes, /Build number: `13`/);
assert.match(appStoreReviewNotes, /Verify App Store purchase & open Board/);
assert.match(appStoreReviewNotes, /AppTransaction\.refresh\(\)/);
assert.match(playStoreReviewNotes, /Version code: `16`/);
assert.match(playStoreReviewNotes, /Google Play Billing/);
assert.match(playStoreReviewNotes, /Play Integrity/);
assert.match(playStoreReviewNotes, /android-manifest:contract/);
assert.doesNotMatch(
  [appStoreReviewNotes, playStoreReviewNotes].join("\n"),
  /universal, permanent|unconditional lifetime/i
);

console.log("Native store proof, Play Integrity, manifests, and iOS privacy contracts passed.");
