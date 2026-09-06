#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");

const pkg = JSON.parse(read("package.json"));
assert.equal(pkg.dependencies["localflight-paid-app"], "file:modules/localflight-paid-app");

const access = read("src/access/paidAppAccess.ts");
const standalone = read("src/api/standalone.ts");
const shell = read("src/app/AppShell.tsx");
const screens = read("src/screens/AppScreens.tsx");
const more = read("src/v2/MoreScreenV2.tsx");
const settings = read("src/storage/settings.ts");
const content = read("src/content/en.ts");
const relayOrigins = read("src/access/relayOrigins.ts");
const launchOverlay = read("src/hooks/useLaunchOverlay.ts");
const appStoreReviewNotes = read("APP_STORE_REVIEW_NOTES.md");
const playStoreReviewNotes = read("PLAY_STORE_REVIEW_NOTES.md");
const ios = read("modules/localflight-paid-app/ios/LocalFlightPaidAppModule.swift");
const iosPodspec = read("modules/localflight-paid-app/ios/LocalFlightPaidApp.podspec");

assert.match(ios, /AppTransaction\.refresh\(\)/);
assert.match(ios, /case \.verified/);
assert.match(ios, /AppStore\.deviceVerificationID/);
assert.match(ios, /jwsRepresentation/);
assert.match(iosPodspec, /:ios => "16\.0"/);
assert.match(access, /\/v1\/access\/mobile\/attestation\/challenge/);
assert.match(access, /\/v1\/access\/mobile\/attestation\/verify/);
assert.match(access, /MobileAccessIntent = "inspect" \| "companion" \| "standalone"/);
assert.match(access, /intent: input\.intent/);
assert.match(access, /platform === "android" && input\.intent !== "standalone"/);
assert.match(access, /activation_grant: input\.activationGrant/);
assert.match(access, /proof\.device_verification_id = transaction\.deviceVerificationId/);
assert.match(access, /proof\.google_play_purchase_token = purchase\.purchaseToken/);
assert.match(access, /proof\.google_play_product_id = purchase\.productId/);
assert.match(access, /proof\.play_integrity_token = integrity\.token/);
assert.doesNotMatch(access, /requestGooglePlayLicense|proof\.response_data|proof\.signature|proof\.response_code/);
for (const code of ["store_cancelled", "store_unavailable", "ownership_unverified", "device_verification_missing", "store_timeout", "unsupported_build"]) {
  assert.match(access, new RegExp(`"${code}"`));
}
for (const state of ["verification_needed", "checking", "available", "active_here", "active_elsewhere", "suspended", "refunded", "revoked", "retryable_unavailable", "release_pending"]) {
  assert.match(access, new RegExp(`"${state}"`));
}
assert.match(access, /access_state/);
assert.match(access, /reason_code/);
assert.match(access, /delivery_claim/);
assert.match(access, /\/v1\/access\/magic-links\/request/);
assert.match(access, /purpose: "protect_and_deliver"/);
assert.match(access, /export async function inspectPaidMobileOwnership/);
assert.match(access, /export async function getRelayAccessStatus/);
assert.match(access, /\/v1\/access\/status/);
assert.match(access, /license\?\.receiver \|\| data\.receiver \|\| data\.current_receiver/);
assert.match(access, /export async function deactivateRelayReceiver/);
assert.match(access, /\/v1\/access\/deactivate/);
assert.match(access, /export async function commitPendingRelayActivation/);
assert.match(access, /\/v1\/access\/activate\/commit/);
assert.match(access, /mobileActivationProtocolState/);
assert.match(access, /const activationCommitted = committed\.data\.activated === true/);
assert.match(standalone, /activationGrant: input\.activationGrant/);
assert.match(standalone, /Authorization: `Bearer \$\{credentials\.deviceCredential\}`/);
assert.match(standalone, /credentials\.source === "real" && credentials\.deviceCredential\.startsWith\("lfr_"\)/, "VATSIM data requests must not attach a retained Relay credential.");
assert.match(relayOrigins, /EXPO_PUBLIC_LOCALFLIGHT_RELAY_ORIGIN/);
assert.match(relayOrigins, /EXPO_PUBLIC_LOCALFLIGHT_RELAY_FAILOVER_ORIGINS/);
assert.match(relayOrigins, /SAFE_DEFAULT_RELAY_ORIGIN = "https:\/\/relay-staging\.beacontools\.cc"/);
assert.match(relayOrigins, /if \(preferred !== canonical\)|fixedOrigin|explicitOrigin/, "Custom relay overrides must stay isolated from configured failovers.");
assert.ok(shell.includes("relay-access"));
assert.match(shell, /initialRelayActivationGrant=\{pendingRelayActivationGrant\}/);
assert.match(shell, /new URLSearchParams\(parsed\.hash\.replace/);
assert.match(shell, /fragment\.get\("grant"\)/);
assert.doesNotMatch(shell, /searchParams\.get\("(?:grant|activation_grant)"\)/);
assert.match(shell, /relayReleasePending/);
assert.match(shell, /setRelayReleaseRetryNonce/);
assert.match(shell, /deactivateRelayReceiver/);
assert.match(shell, /intent: "companion"/);
assert.match(shell, /platformUsesIncludedPaidAppAccess/);
assert.match(shell, /Platform\.OS === "ios"/);
assert.match(shell, /Platform\.OS === "android" && !\(isStandalone && standaloneSource === "real"\)/, "Android Companion and VATSIM must route to setup before any access proof.");
assert.match(shell, /mobileRelayAccessFailureSnapshot\(verificationError, relayAccess\)/);
assert.match(shell, /saveMobileRelayAccessSummary/);
assert.match(shell, /setupDraftOpen/);
assert.match(shell, /initialStandaloneMove=\{setupDraftSeed\?\.move \|\| null\}/);
assert.match(shell, /stagePendingRelayActivation/);
assert.match(shell, /commitStandaloneCredential/);
assert.match(shell, /retryPendingRelayRelease/);
const rerunSetup = shell.slice(shell.indexOf("const rerunCompanionSetup"), shell.indexOf("const retryPendingRelayRelease"));
assert.doesNotMatch(rerunSetup, /saveMobileSetupState|clearStandaloneHistory|saveStandaloneAirport/, "Opening setup must not mutate the active route.");
assert.match(screens, /initialRelayActivationGrant\.startsWith\("lfrag_"\)/);
assert.match(screens, /if \(accessAction === "none"\)/);
assert.ok(screens.indexOf('if (accessAction === "none")') < screens.indexOf("const activation = await activateStandalone"), "Free VATSIM must finish before any access activation.");
assert.match(content, /Beacon Relay Access included/);
assert.match(content, /There is no subscription or extra purchase/);
assert.match(content, /This paid app includes Beacon Relay Access\. Companion uses your desktop host/);
assert.match(content, /Verify \$\{storeName\} purchase & open Board/);
assert.match(screens, /Move Relay Access here/);
assert.match(screens, /Use Companion instead/);
assert.match(screens, /Relay Access is currently used by \{standaloneMove\.mainDeviceName\}\. Moving it here will stop direct Relay use there\./);
assert.match(more, /Verify Relay Access/);
assert.match(more, /Restore Relay Access/);
assert.match(more, /Source: \{relayAccess\.sourceLabel\}/);
assert.match(more, /Main device: \{relayAccess\.currentMainDeviceDescription\}/);
assert.doesNotMatch(more, /relay-access\/manage/);
assert.doesNotMatch(more, /setPanel\("relay"\);[\s\S]{0,120}onVerifyRelayAccess/, "Opening Relay Access must not refresh the store automatically.");
assert.match(settings, /localflight\.relayDeviceCredential/);
assert.match(settings, /localflight\.pendingRelayDeviceCredential/);
assert.match(settings, /stagePendingRelayActivation/);
assert.match(settings, /clearPendingRelayActivation/);
assert.match(settings, /localflight\.mobileRelayAccessSummary/);
assert.match(settings, /LEGACY_MOBILE_RELAY_ACTIVATION_TOKEN_KEY/);
assert.doesNotMatch(settings, /relayActivationToken\?: string/);
assert.doesNotMatch(settings, /relayCredentialPrefix\?: string/);
assert.match(launchOverlay, /resolveMobileSetupState[\s\S]*loadRelayDeviceCredential\(\)/);
assert.match(launchOverlay, /loadMobileRelayAccessSummary\(\)/);
assert.doesNotMatch(appStoreReviewNotes, /relay-access\?grant=/);
assert.doesNotMatch(playStoreReviewNotes, /relay-access\?grant=/);
assert.match(settings, /relayCredentialPresent\?: boolean/);
assert.match(shell, /standaloneSource === "virtual" \|\| relayRuntimeAllowed/);
assert.doesNotMatch(access.slice(access.indexOf("export function isTerminalRelayCredentialError")), /error\.status === 401|error\.status === 403/, "Credential cleanup must use stable codes, not broad HTTP status.");

const mobileSources = fs.readdirSync(path.join(root, "src"), { recursive: true })
  .filter((entry) => typeof entry === "string" && /\.(?:ts|tsx)$/.test(entry))
  .map((entry) => read(path.join("src", entry)))
  .join("\n");
assert.doesNotMatch(mobileSources, /enter (?:a )?license key|paste (?:a |your )?license key/i);

const ordinaryUi = [screens, more, content].join("\n");
assert.doesNotMatch(ordinaryUi, /receiver seat|independent receiver|license entitlement/i);
assert.doesNotMatch(ordinaryUi, /Stripe checkout|Get Relay Access/i);

const summaryWriter = settings.slice(
  settings.indexOf("export async function saveMobileRelayAccessSummary"),
  settings.indexOf("export async function loadStandaloneAirport")
);
assert.doesNotMatch(summaryWriter, /deliveryClaim|claimToken|moveToken|holderSession|credentialPrefix|signedAppTransaction|responseData/);

console.log("Mobile Relay Access setup, state, persistence, and no-key-entry contract passed.");
