export type MobilePlatform = "ios" | "android" | "other";
export type MobileSetupRoute = "lan_companion" | "standalone";
export type MobileFlightSource = "real" | "virtual";
export type MobileAccessAction = "none" | "ios_app_transaction" | "android_purchase" | "android_integrity_grant" | "unsupported";

const TERMINAL_ACCESS_STATES = new Set(["suspended", "refunded", "revoked"]);
const NON_RUNTIME_ACCESS_STATES = new Set(["available", "active_elsewhere", ...TERMINAL_ACCESS_STATES]);
const TERMINAL_CREDENTIAL_CODES = new Set([
  "license_inactive",
  "license_not_found",
  "license_suspended",
  "license_refunded",
  "license_revoked",
  "relay_credential_required",
  "activation_revoked"
]);
const STALE_MOVE_CODES = new Set([
  "move_confirmation_expired",
  "move_confirmation_invalid",
  "move_confirmation_stale",
  "invalid_move_confirmation"
]);
const STALE_GRANT_CODES = new Set([
  "activation_grant_expired",
  "activation_grant_invalid",
  "activation_grant_consumed",
  "invalid_activation_grant"
]);
const EXPIRED_PENDING_CODES = new Set([
  "activation_pending_expired",
  "activation_pending_invalid",
  "pending_activation_expired",
  "pending_activation_invalid",
  "activation_commit_expired",
  "activation_commit_stale",
  "activation_authorization_stale",
  "pending_credential_expired",
  "pending_credential_invalid"
]);

export type MobileActivationProtocolState = "active" | "pending_commit" | "invalid";

export function mobileActivationProtocolState(input: {
  activated: boolean;
  activationState: string;
  credential: string;
}): MobileActivationProtocolState {
  if (!input.credential.startsWith("lfr_")) return "invalid";
  if (input.activationState === "pending_commit") return "pending_commit";
  return input.activated ? "active" : "invalid";
}

export function platformUsesIncludedPaidAppAccess(platform: MobilePlatform): boolean {
  return platform === "ios";
}

export function routeNeedsRelayAccess(route: MobileSetupRoute, source: MobileFlightSource): boolean {
  return route === "standalone" && source === "real";
}

export function mobileAccessAction(input: {
  platform: MobilePlatform;
  route: MobileSetupRoute;
  source: MobileFlightSource;
  hasActivationGrant: boolean;
}): MobileAccessAction {
  if (!routeNeedsRelayAccess(input.route, input.source)) return "none";
  if (input.platform === "ios") return "ios_app_transaction";
  if (input.platform === "android") {
    return input.hasActivationGrant ? "android_integrity_grant" : "android_purchase";
  }
  return "unsupported";
}

export function activationBlockedByPendingRelease(input: {
  route: MobileSetupRoute;
  source: MobileFlightSource;
  releasePending: boolean;
}): boolean {
  return input.releasePending && routeNeedsRelayAccess(input.route, input.source);
}

export function routeMayUseRelayRuntime(input: {
  route: MobileSetupRoute;
  source: MobileFlightSource;
  accessState: string;
  releasePending: boolean;
  hasCredential: boolean;
}): boolean {
  return routeNeedsRelayAccess(input.route, input.source)
    && input.hasCredential
    && !input.releasePending
    && !NON_RUNTIME_ACCESS_STATES.has(input.accessState);
}

export function terminalAccessStateFromCode(code: string): "suspended" | "refunded" | "revoked" | null {
  const normalized = code.trim().toLowerCase();
  if (normalized === "license_refunded" || normalized === "purchase_refunded") return "refunded";
  if (
    normalized === "license_revoked"
    || normalized === "purchase_revoked"
    || normalized === "license_not_found"
    || normalized === "activation_revoked"
    || normalized === "relay_credential_required"
  ) return "revoked";
  if (
    normalized === "license_suspended"
    || normalized === "purchase_suspended"
    || normalized === "license_inactive"
  ) return "suspended";
  return null;
}

export function isTerminalCredentialCode(code: string): boolean {
  return TERMINAL_CREDENTIAL_CODES.has(code.trim().toLowerCase());
}

export function isStaleMoveCode(code: string, message = ""): boolean {
  const normalized = code.trim().toLowerCase();
  return STALE_MOVE_CODES.has(normalized)
    || (normalized === "invalid_challenge" && /move|confirmation/i.test(message));
}

export function isStaleActivationGrantCode(code: string, message = ""): boolean {
  const normalized = code.trim().toLowerCase();
  return STALE_GRANT_CODES.has(normalized)
    || (normalized === "invalid_challenge" && /activation grant|transfer|access link (?:is |has )?(?:invalid|expired|already been used)/i.test(message));
}

export function isExpiredPendingActivationCode(code: string): boolean {
  return EXPIRED_PENDING_CODES.has(code.trim().toLowerCase());
}

export function pendingActivationExpired(expiresAt: string, nowMs = Date.now()): boolean {
  const expiresMs = Date.parse(expiresAt);
  return Number.isFinite(expiresMs) && expiresMs <= nowMs;
}
