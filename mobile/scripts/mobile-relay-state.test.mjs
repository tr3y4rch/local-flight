#!/usr/bin/env node
import assert from "node:assert/strict";

import {
  activationBlockedByPendingRelease,
  isExpiredPendingActivationCode,
  isStaleActivationGrantCode,
  isStaleMoveCode,
  isTerminalCredentialCode,
  mobileActivationProtocolState,
  mobileAccessAction,
  pendingActivationExpired,
  routeMayUseRelayRuntime,
  terminalAccessStateFromCode
} from "../src/access/mobileRelayState.ts";

assert.equal(mobileAccessAction({ platform: "android", route: "lan_companion", source: "real", hasActivationGrant: false }), "none");
assert.equal(mobileAccessAction({ platform: "android", route: "standalone", source: "virtual", hasActivationGrant: false }), "none");
assert.equal(mobileAccessAction({ platform: "android", route: "standalone", source: "real", hasActivationGrant: false }), "android_purchase");
assert.equal(mobileAccessAction({ platform: "android", route: "standalone", source: "real", hasActivationGrant: true }), "android_integrity_grant");
assert.equal(mobileAccessAction({ platform: "ios", route: "lan_companion", source: "real", hasActivationGrant: false }), "none");
assert.equal(mobileAccessAction({ platform: "ios", route: "standalone", source: "real", hasActivationGrant: false }), "ios_app_transaction");
assert.equal(mobileAccessAction({ platform: "other", route: "standalone", source: "real", hasActivationGrant: false }), "unsupported");

assert.equal(mobileActivationProtocolState({ activated: true, activationState: "", credential: "lfr_legacy" }), "active");
assert.equal(mobileActivationProtocolState({ activated: false, activationState: "pending_commit", credential: "lfr_pending" }), "pending_commit");
assert.equal(mobileActivationProtocolState({ activated: false, activationState: "pending_commit", credential: "" }), "invalid");
assert.equal(mobileActivationProtocolState({ activated: false, activationState: "active", credential: "lfr_uncommitted" }), "invalid");

const runnable = { route: "standalone", source: "real", accessState: "active_here", releasePending: false, hasCredential: true };
assert.equal(routeMayUseRelayRuntime(runnable), true);
for (const accessState of ["suspended", "refunded", "revoked"]) {
  assert.equal(routeMayUseRelayRuntime({ ...runnable, accessState }), false, `${accessState} must block Relay runtime`);
}
assert.equal(routeMayUseRelayRuntime({ ...runnable, accessState: "active_elsewhere" }), false);
assert.equal(routeMayUseRelayRuntime({ ...runnable, accessState: "available" }), false);
assert.equal(routeMayUseRelayRuntime({ ...runnable, source: "virtual", hasCredential: false }), false);
assert.equal(routeMayUseRelayRuntime({ ...runnable, releasePending: true }), false);
assert.equal(routeMayUseRelayRuntime({ ...runnable, hasCredential: false }), false);

assert.equal(activationBlockedByPendingRelease({ route: "standalone", source: "real", releasePending: true }), true);
assert.equal(activationBlockedByPendingRelease({ route: "standalone", source: "virtual", releasePending: true }), false);
assert.equal(activationBlockedByPendingRelease({ route: "lan_companion", source: "real", releasePending: true }), false);

assert.equal(terminalAccessStateFromCode("license_refunded"), "refunded");
assert.equal(terminalAccessStateFromCode("license_revoked"), "revoked");
assert.equal(terminalAccessStateFromCode("license_inactive"), "suspended");
assert.equal(isTerminalCredentialCode("license_not_found"), true);
assert.equal(isTerminalCredentialCode("arbitrary_forbidden"), false);

assert.equal(isStaleMoveCode("move_confirmation_expired"), true);
assert.equal(isStaleMoveCode("invalid_challenge", "Move confirmation is stale"), true);
assert.equal(isStaleMoveCode("invalid_challenge", "Unrelated challenge"), false);
assert.equal(isStaleActivationGrantCode("activation_grant_consumed"), true);
assert.equal(isStaleActivationGrantCode("invalid_challenge", "Activation grant expired"), true);
assert.equal(isStaleActivationGrantCode("invalid_challenge", "Access link has expired"), true);
assert.equal(isExpiredPendingActivationCode("activation_pending_expired"), true);
assert.equal(isExpiredPendingActivationCode("pending_activation_expired"), true);
assert.equal(isExpiredPendingActivationCode("activation_commit_stale"), true);
assert.equal(isExpiredPendingActivationCode("activation_authorization_stale"), true);

assert.equal(pendingActivationExpired("2024-01-01T00:00:00.000Z", Date.parse("2024-01-02T00:00:00.000Z")), true);
assert.equal(pendingActivationExpired("2024-01-03T00:00:00.000Z", Date.parse("2024-01-02T00:00:00.000Z")), false);
assert.equal(pendingActivationExpired("", Date.now()), false);

console.log("Mobile Relay state-machine tests passed.");
