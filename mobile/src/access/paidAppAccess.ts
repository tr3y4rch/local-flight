import { Platform } from "react-native";
import {
  GOOGLE_PLAY_RELAY_ACCESS_PRODUCT_ID,
  getFreshAppleAppTransactionProof,
  purchaseGooglePlayRelayAccess,
  queryGooglePlayRelayAccessPurchase,
  requestGooglePlayIntegrityToken
} from "localflight-paid-app";

import { LocalFlightApiError } from "../api/client";
import { getCompanionIdentity } from "../device/identity";
import { mobileRelayOrigins } from "./relayOrigins";
import {
  isExpiredPendingActivationCode,
  isStaleActivationGrantCode,
  isStaleMoveCode,
  isTerminalCredentialCode,
  mobileActivationProtocolState,
  terminalAccessStateFromCode
} from "./mobileRelayState";

const RELAY_ACCESS_TIMEOUT_MS = 20_000;
const FAILOVER_ROUTE_STATUSES = new Set([404, 405]);

export type MobileAccessIntent = "inspect" | "companion" | "standalone";
export type RelayLicenseAccessState = "active" | "suspended" | "refunded" | "revoked";
export type MobileRelayAccessState =
  | "verification_needed"
  | "checking"
  | "available"
  | "active_here"
  | "active_elsewhere"
  | "suspended"
  | "refunded"
  | "revoked"
  | "retryable_unavailable"
  | "release_pending";

/** The complete allowlist for Relay Access information saved outside a request. */
export type MobileRelayAccessSummary = {
  licenseRef: string;
  maskedKeyRef: string;
  sourceLabel: string;
  state: MobileRelayAccessState;
  protectionEnabled: boolean;
  currentMainDeviceDescription: string;
  lastSuccessfulCheckAt: string;
};

export type MobileRelayAccessSnapshot = MobileRelayAccessSummary & {
  accessState: RelayLicenseAccessState;
  reasonCode: string;
  message: string;
  /** Short-lived authorization used only by an explicit email-protection action. */
  deliveryClaim: string;
};

export const EMPTY_MOBILE_RELAY_ACCESS: MobileRelayAccessSnapshot = {
  licenseRef: "",
  maskedKeyRef: "",
  sourceLabel: "",
  state: "verification_needed",
  protectionEnabled: false,
  currentMainDeviceDescription: "",
  lastSuccessfulCheckAt: "",
  accessState: "active",
  reasonCode: "",
  deliveryClaim: "",
  message: Platform.OS === "android"
    ? "Get or restore Relay Access when you want real-flight Standalone mode. Companion and VATSIM do not require it."
    : "Verify the Relay Access included with this paid app when you are ready."
};

export type PaidAppActivation = {
  activated: boolean;
  credential: string;
  credentialPrefix: string;
  status: "active" | "main_device_in_use";
  activationState: "active" | "pending_commit";
  pendingExpiresIn: number;
  relayOrigin: string;
  access: MobileRelayAccessSnapshot;
  moveToken?: string;
  currentMainDeviceDescription?: string;
};

export type MobileAccessErrorPresentation = {
  state: Exclude<MobileRelayAccessState, "checking" | "available" | "active_here" | "active_elsewhere" | "release_pending">;
  title: string;
  body: string;
  action: "Try again" | "Verify included access" | "Restore included access" | "Get or restore Relay Access" | "Restore Relay Access";
};

type ApiErrorPayload = {
  code?: string;
  reason_code?: string;
  access_state?: string;
  message?: string;
  detail?: string | { code?: string; reason_code?: string; access_state?: string; message?: string };
  error?: string | { code?: string; reason_code?: string; access_state?: string; message?: string; info?: string };
};

type RawMainDevice = {
  device_kind?: string;
  device_name?: string;
  activated_at?: string;
  last_seen_at?: string;
};

type RawLicense = {
  license_ref?: string;
  product_code?: string;
  purchase_source?: string;
  status?: string;
  access_state?: string;
  reason_code?: string;
  key_ref?: string;
  created_at?: string;
  receiver?: RawMainDevice | null;
};

type OwnershipVerification = ApiErrorPayload & {
  verified?: boolean;
  activated?: boolean;
  activation_state?: string;
  pending_expires_in?: number;
  committed?: boolean;
  credential?: string;
  credential_prefix?: string;
  intent?: MobileAccessIntent;
  license?: RawLicense;
  included_license?: RawLicense;
  seat_state?: string;
  email_protected?: boolean;
  delivery_claim?: string;
  claim_token?: string;
  move_token?: string;
  receiver?: RawMainDevice;
  current_receiver?: RawMainDevice;
  current_main_device?: RawMainDevice;
};

function sourceLabel(source: string): string {
  const normalized = source.trim().toLowerCase();
  if (["apple_app", "app_store", "apple_app_store", "ios_app"].includes(normalized)) return "App Store";
  if (["google_app", "google_play", "google_play_billing", "android_app"].includes(normalized)) return "Google Play";
  if (["stripe", "website", "web"].includes(normalized)) return "Beacon Tools website";
  return source ? "Beacon Tools" : "";
}

function safeReasonCode(value: unknown): string {
  const text = typeof value === "string" ? value.trim().toLowerCase() : "";
  return /^[a-z0-9_.-]{1,64}$/.test(text) ? text : "";
}

function normalizeAccessState(value: unknown): RelayLicenseAccessState {
  const state = String(value || "").trim().toLowerCase();
  return state === "suspended" || state === "refunded" || state === "revoked" ? state : "active";
}

function rawErrorMetadata(error: unknown): {
  code: string;
  reasonCode: string;
  accessState: RelayLicenseAccessState | null;
  explicitAccessState: RelayLicenseAccessState | null;
  credentialState: string;
  currentMainDeviceDescription: string;
} {
  const source = error instanceof LocalFlightApiError ? error.details : error;
  const raw = errorRecord(source);
  const detail = errorRecord(raw.detail);
  const nested = errorRecord(raw.error);
  const license = errorRecord(raw.license || raw.included_license || detail.license || detail.included_license || nested.license || nested.included_license);
  const code = safeReasonCode(
    error instanceof LocalFlightApiError
      ? error.code
      : raw.code || detail.code || nested.code
  );
  const reasonCode = safeReasonCode(raw.reason_code || detail.reason_code || nested.reason_code || license.reason_code || code);
  const explicitState = String(raw.access_state || detail.access_state || nested.access_state || license.access_state || "").toLowerCase();
  const explicitAccessState = explicitState === "active" || explicitState === "suspended" || explicitState === "refunded" || explicitState === "revoked"
    ? explicitState
    : null;
  const accessState = explicitAccessState === "active"
    ? null
    : explicitAccessState || terminalAccessStateFromCode(code);
  const credentialState = safeReasonCode(raw.credential_state || detail.credential_state || nested.credential_state);
  const currentMainDevice = errorRecord(raw.current_main_device || detail.current_main_device || nested.current_main_device);
  return {
    code,
    reasonCode,
    accessState,
    explicitAccessState,
    credentialState,
    currentMainDeviceDescription: mainDeviceDescription(currentMainDevice as RawMainDevice)
  };
}

export function mobileAccessErrorCode(error: unknown): string {
  if (error instanceof LocalFlightApiError && error.code) return safeReasonCode(error.code);
  return rawErrorMetadata(error).code;
}

function safeMaskedKeyRef(value: unknown): string {
  const text = typeof value === "string" ? value.trim() : "";
  if (!text || text.startsWith("lfr_")) return "";
  if (/^LFRA/i.test(text) && !/[.…*•]/.test(text)) return "";
  return text.slice(0, 48);
}

function mainDeviceDescription(value: RawMainDevice | null | undefined): string {
  if (!value) return "";
  const named = String(value.device_name || "").trim();
  if (named) return named.slice(0, 80);
  const kind = String(value.device_kind || "").toLowerCase();
  if (kind.includes("desktop")) return "your Local Flight desktop";
  if (kind.includes("mobile")) return "another phone";
  return kind ? "another main device" : "";
}

function errorParts(data: unknown, fallback: string): { message: string; code: string } {
  if (!data || typeof data !== "object") return { message: fallback, code: "" };
  const value = data as ApiErrorPayload;
  if (typeof value.detail === "string" && value.detail) {
    return { message: value.detail, code: value.code || "" };
  }
  if (value.detail && typeof value.detail === "object") {
    return {
      message: value.detail.message || fallback,
      code: value.detail.code || value.code || ""
    };
  }
  if (typeof value.error === "string" && value.error) {
    return { message: value.error, code: value.code || "" };
  }
  if (value.error && typeof value.error === "object") {
    return {
      message: value.error.message || value.error.info || fallback,
      code: value.error.code || value.code || ""
    };
  }
  return { message: value.message || fallback, code: value.code || "" };
}

async function readJson<T>(response: Response, fallback: string): Promise<T> {
  try {
    return await response.json() as T;
  } catch {
    throw new LocalFlightApiError(fallback, response.status, "invalid_relay_response");
  }
}

async function postAtOrigin<T>(origin: string, path: string, body: unknown, authorization: string): Promise<{ response: Response; data: T }> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), RELAY_ACCESS_TIMEOUT_MS);
  try {
    const response = await fetch(`${origin}${path}`, {
      method: "POST",
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        ...(authorization ? { Authorization: `Bearer ${authorization}` } : {})
      },
      body: JSON.stringify(body)
    });
    return {
      response,
      data: await readJson<T>(response, "Beacon Relay returned an invalid access response.")
    };
  } catch (error) {
    if (controller.signal.aborted) {
      throw new LocalFlightApiError("Beacon Relay did not answer in time.", undefined, "relay_timeout");
    }
    if (error instanceof LocalFlightApiError) throw error;
    throw new LocalFlightApiError("Beacon Relay could not be reached.", undefined, "relay_unavailable");
  } finally {
    clearTimeout(timer);
  }
}

async function relayPost<T>(
  relayUrl: string | undefined,
  path: string,
  body: unknown,
  authorization = "",
  fixedOrigin = ""
): Promise<{ response: Response; data: T; origin: string }> {
  const origins = fixedOrigin ? [fixedOrigin] : mobileRelayOrigins(relayUrl);
  let lastError: unknown = null;
  for (const [index, origin] of origins.entries()) {
    try {
      const result = await postAtOrigin<T>(origin, path, body, authorization);
      if (FAILOVER_ROUTE_STATUSES.has(result.response.status) && index < origins.length - 1) continue;
      return { ...result, origin };
    } catch (error) {
      lastError = error;
      if (index === origins.length - 1) throw error;
    }
  }
  throw lastError || new LocalFlightApiError("Beacon Relay could not be reached.", undefined, "relay_unavailable");
}

function throwAccessError(response: Response, data: unknown, fallback: string): never {
  const detail = errorParts(data, fallback);
  throw new LocalFlightApiError(detail.message, response.status, detail.code, data);
}

function rawLicense(data: OwnershipVerification): RawLicense | null {
  return data.license || data.included_license || null;
}

function rawMainDevice(data: OwnershipVerification): RawMainDevice | null {
  const license = rawLicense(data);
  return license?.receiver || data.receiver || data.current_receiver || data.current_main_device || null;
}

function normalizedClientState(data: OwnershipVerification, accessState: RelayLicenseAccessState): MobileRelayAccessState {
  if (accessState !== "active") return accessState;
  const explicit = String(data.seat_state || "").toLowerCase();
  if (explicit === "active_receiver") return "active_here";
  if (explicit === "available" || explicit === "active_here" || explicit === "active_elsewhere") return explicit;
  if (data.activated) return "active_here";
  if (rawMainDevice(data)) return "active_elsewhere";
  return rawLicense(data)?.license_ref ? "available" : "verification_needed";
}

export function mobileRelayAccessMessage(summary: Pick<MobileRelayAccessSummary, "state" | "currentMainDeviceDescription">): string {
  switch (summary.state) {
    case "active_here":
      return "This phone is the current main device for Relay Access.";
    case "active_elsewhere":
      return `Relay Access is currently used by ${summary.currentMainDeviceDescription || "another main device"}.`;
    case "available":
      return "Relay Access is available for a desktop or a phone in Standalone mode.";
    case "suspended":
      return "Relay Access is suspended. Verify the store purchase for the latest status.";
    case "refunded":
      return "The store reports that this purchase was refunded, so Relay Access is unavailable.";
    case "revoked":
      return "Relay Access has been revoked and cannot be used on a main device.";
    case "retryable_unavailable":
      return Platform.OS === "android"
        ? "Relay Access could not be checked. Your saved setup has not changed."
        : "The included access could not be checked. Your saved setup has not changed.";
    case "release_pending":
      return "Companion is ready. Relay Access will be freed from this phone when Beacon Relay is reachable.";
    case "checking":
      return Platform.OS === "android" ? "Checking Google Play Relay Access…" : "Checking the paid app purchase…";
    case "verification_needed":
    default:
      return Platform.OS === "android"
        ? "Get or restore Relay Access when you want real-flight Standalone mode. Companion and VATSIM do not require it."
        : "Verify the Relay Access included with this paid app when you are ready.";
  }
}

export function mobileRelayAccessSnapshotFromSummary(summary: MobileRelayAccessSummary): MobileRelayAccessSnapshot {
  const normalized: MobileRelayAccessSummary = {
    licenseRef: String(summary.licenseRef || "").slice(0, 80),
    maskedKeyRef: safeMaskedKeyRef(summary.maskedKeyRef),
    sourceLabel: String(summary.sourceLabel || "").slice(0, 40),
    state: summary.state === "checking" ? "verification_needed" : summary.state,
    protectionEnabled: Boolean(summary.protectionEnabled),
    currentMainDeviceDescription: String(summary.currentMainDeviceDescription || "").slice(0, 80),
    lastSuccessfulCheckAt: String(summary.lastSuccessfulCheckAt || "")
  };
  return {
    ...EMPTY_MOBILE_RELAY_ACCESS,
    ...normalized,
    accessState: normalized.state === "suspended" || normalized.state === "refunded" || normalized.state === "revoked"
      ? normalized.state
      : "active",
    message: mobileRelayAccessMessage(normalized)
  };
}

function snapshotFromVerification(data: OwnershipVerification): MobileRelayAccessSnapshot {
  const license = rawLicense(data);
  const accessState = normalizeAccessState(data.access_state || license?.access_state || license?.status);
  const state = normalizedClientState(data, accessState);
  const summary: MobileRelayAccessSummary = {
    licenseRef: String(license?.license_ref || "").slice(0, 80),
    maskedKeyRef: safeMaskedKeyRef(license?.key_ref),
    sourceLabel: sourceLabel(String(license?.purchase_source || "")),
    state,
    protectionEnabled: Boolean(data.email_protected),
    currentMainDeviceDescription: mainDeviceDescription(rawMainDevice(data)),
    lastSuccessfulCheckAt: new Date().toISOString()
  };
  return {
    ...summary,
    accessState,
    reasonCode: safeReasonCode(data.reason_code || license?.reason_code),
    deliveryClaim: data.delivery_claim || data.claim_token || "",
    message: mobileRelayAccessMessage(summary)
  };
}

function errorRecord(error: unknown): Record<string, unknown> {
  return error && typeof error === "object" ? error as Record<string, unknown> : {};
}

function normalizedNativeError(error: unknown): LocalFlightApiError {
  if (error instanceof LocalFlightApiError) return error;
  const raw = errorRecord(error);
  const nativeCode = String(raw.code || "").toLowerCase();
  const message = error instanceof Error ? error.message : "";
  const haystack = `${nativeCode} ${message}`.toLowerCase();
  const directCodes = new Set([
    "store_cancelled",
    "store_unavailable",
    "ownership_unverified",
    "device_verification_missing",
    "store_timeout",
    "unsupported_build",
    "purchase_pending",
    "purchase_required",
    "activation_commit_pending",
    "credential_write_failed"
  ]);
  let code = directCodes.has(nativeCode) ? nativeCode : "";
  if (!code && /cancel|user_cancel/.test(haystack)) code = "store_cancelled";
  else if (!code && /timeout|timed out|err_play_timeout/.test(haystack)) code = "store_timeout";
  else if (!code && /device.verification|verification.id|err_device/.test(haystack)) code = "device_verification_missing";
  else if (!code && /pending purchase|purchase pending/.test(haystack)) code = "purchase_pending";
  else if (!code && /unverified|could not verify|not licensed|err_unverified/.test(haystack)) code = "ownership_unverified";
  else if (!code && /unsupported|unavailable in this build|requires ios|native_ownership_unavailable/.test(haystack)) code = "unsupported_build";
  else if (!code && /unavailable|disconnected|could not start|store service|err_play/.test(haystack)) code = "store_unavailable";
  else if (!code) code = "store_unavailable";

  const store = paidAppStoreLabel();
  const safeMessage = code === "store_cancelled"
    ? `${store} purchase verification was cancelled.`
    : code === "store_unavailable"
      ? `${store} could not verify this purchase right now.`
      : code === "ownership_unverified"
        ? Platform.OS === "android" ? `${store} could not confirm Relay Access ownership.` : `${store} could not confirm ownership of this paid app.`
        : code === "device_verification_missing"
          ? "This device could not complete the store verification."
          : code === "store_timeout"
            ? `${store} did not answer in time.`
            : code === "purchase_pending"
              ? "The Google Play purchase is still pending."
              : code === "purchase_required"
                ? "Relay Access has not been purchased from Google Play."
                : code === "activation_commit_pending"
                  ? "Relay activation is safely staged and waiting for Beacon Relay."
                  : code === "credential_write_failed"
                    ? "This device could not safely store the Relay credential."
                    : "Store ownership verification is not supported in this build.";
  return new LocalFlightApiError(safeMessage, undefined, code);
}

function accessStateFromError(error: unknown): RelayLicenseAccessState | null {
  return rawErrorMetadata(error).accessState;
}

export function paidAppStoreLabel(): "App Store" | "Google Play" | "app store" {
  if (Platform.OS === "ios") return "App Store";
  if (Platform.OS === "android") return "Google Play";
  return "app store";
}

export function mobileAccessErrorPresentation(error: unknown): MobileAccessErrorPresentation {
  const normalized = normalizedNativeError(error);
  const terminal = accessStateFromError(normalized);
  const code = normalized.code.toLowerCase();
  const store = paidAppStoreLabel();
  if (terminal === "suspended" || code === "license_suspended") {
    return { state: "suspended", title: "Relay Access is suspended", body: "Verify the store purchase for the latest status. Companion remains available.", action: Platform.OS === "android" ? "Restore Relay Access" : "Restore included access" };
  }
  if (terminal === "refunded" || code === "license_refunded") {
    return { state: "refunded", title: "Purchase refunded", body: "The store reports that this purchase was refunded, so Relay Access cannot be activated.", action: Platform.OS === "android" ? "Restore Relay Access" : "Restore included access" };
  }
  if (terminal === "revoked" || code === "license_revoked") {
    return { state: "revoked", title: "Relay Access revoked", body: "Relay Access cannot be activated from this purchase. Companion remains available.", action: Platform.OS === "android" ? "Restore Relay Access" : "Restore included access" };
  }
  if (code === "store_cancelled") {
    return { state: "verification_needed", title: "Purchase check cancelled", body: "Nothing changed. Try again when you’re ready.", action: "Try again" };
  }
  if (code === "purchase_required") {
    return { state: "verification_needed", title: "Relay Access required", body: "Companion and VATSIM remain free. Get or restore Relay Access to use real-flight Standalone mode.", action: "Get or restore Relay Access" };
  }
  if (code === "purchase_pending") {
    return { state: "verification_needed", title: "Purchase pending", body: "Google Play is still processing the Relay Access purchase. Try again after it completes.", action: "Try again" };
  }
  if (code === "activation_commit_pending") {
    return { state: "retryable_unavailable", title: "Activation safely staged", body: "The credential is protected on this device. Retry to finish activation without purchasing again.", action: "Try again" };
  }
  if (code === "credential_write_failed") {
    return { state: "retryable_unavailable", title: "Secure storage unavailable", body: "Relay Access was not finalized because this device could not safely store its credential. Try again.", action: "Try again" };
  }
  if (code === "ownership_unverified") {
    return { state: "verification_needed", title: "Purchase not verified", body: Platform.OS === "android" ? `${store} could not confirm Relay Access ownership.` : `${store} could not confirm this paid-app purchase.`, action: "Try again" };
  }
  if (code === "device_verification_missing") {
    return { state: "verification_needed", title: "Device verification unavailable", body: "This device could not complete the store verification. Try again after restarting the app.", action: "Try again" };
  }
  if (code === "unsupported_build") {
    return { state: "retryable_unavailable", title: "Verification unavailable in this build", body: Platform.OS === "android" ? "Install a supported Google Play build to verify Relay Access." : "Install a supported App Store build to verify the included access.", action: "Try again" };
  }
  if (code === "store_timeout") {
    return { state: "retryable_unavailable", title: `${store} took too long`, body: "The purchase check timed out. Check the connection and try again.", action: "Try again" };
  }
  if (code === "store_unavailable") {
    return { state: "retryable_unavailable", title: `${store} is unavailable`, body: Platform.OS === "android" ? "Relay Access could not be checked right now. Try again when Google Play is reachable." : "The paid-app purchase could not be checked right now. Try again when the store service is reachable.", action: "Try again" };
  }
  return { state: "retryable_unavailable", title: "Relay Access unavailable", body: Platform.OS === "android" ? "Beacon Relay could not check Relay Access. Your saved setup has not changed." : "Beacon Relay could not check the included access. Your saved setup has not changed.", action: "Try again" };
}

export function mobileRelayAccessFailureSnapshot(
  error: unknown,
  current: MobileRelayAccessSnapshot = EMPTY_MOBILE_RELAY_ACCESS
): MobileRelayAccessSnapshot {
  const presentation = mobileAccessErrorPresentation(error);
  const metadata = rawErrorMetadata(error);
  if (metadata.explicitAccessState === "active" && isTerminalCredentialCode(metadata.code)) {
    const state = metadata.currentMainDeviceDescription ? "active_elsewhere" as const : "available" as const;
    return {
      ...current,
      state,
      accessState: "active",
      reasonCode: metadata.reasonCode,
      currentMainDeviceDescription: metadata.currentMainDeviceDescription,
      deliveryClaim: "",
      message: mobileRelayAccessMessage({ state, currentMainDeviceDescription: metadata.currentMainDeviceDescription })
    };
  }
  return {
    ...current,
    state: presentation.state,
    accessState: presentation.state === "suspended" || presentation.state === "refunded" || presentation.state === "revoked"
      ? presentation.state
      : current.accessState,
    reasonCode: metadata.reasonCode,
    deliveryClaim: "",
    message: presentation.body
  };
}

async function verifyPaidMobileOwnership(input: {
  installId: string;
  relayUrl?: string;
  intent: MobileAccessIntent;
  activationGrant?: string;
  confirmMoveToken?: string;
  allowPurchase?: boolean;
}): Promise<{ response: Response; data: OwnershipVerification; origin: string }> {
  if (Platform.OS !== "ios" && Platform.OS !== "android") {
    throw new LocalFlightApiError(
      "Paid-app ownership verification is not supported in this build.",
      undefined,
      "unsupported_build"
    );
  }
  const platform = Platform.OS;
  if (platform === "android" && input.intent !== "standalone") {
    throw new LocalFlightApiError(
      "Android Companion and VATSIM do not require Relay Access verification.",
      undefined,
      "relay_access_not_required"
    );
  }
  const challenge = await relayPost<{ nonce?: string } & ApiErrorPayload>(
    input.relayUrl,
    "/v1/access/mobile/attestation/challenge",
    { platform, install_id: input.installId, intent: input.intent }
  );
  if (!challenge.response.ok || !challenge.data.nonce) {
    throwAccessError(challenge.response, challenge.data, "Beacon Relay could not start ownership verification.");
  }

  const identity = await getCompanionIdentity();
  const proof: Record<string, string | number> = {};
  try {
    if (platform === "ios") {
      const transaction = await getFreshAppleAppTransactionProof();
      proof.signed_app_transaction = transaction.signedAppTransaction;
      proof.device_verification_id = transaction.deviceVerificationId;
    } else if (input.activationGrant) {
      const integrity = await requestGooglePlayIntegrityToken(
        challenge.data.nonce,
        input.installId,
        input.activationGrant
      );
      if (!integrity.token) {
        throw new LocalFlightApiError(
          "Google Play could not verify this app installation.",
          undefined,
          "ownership_unverified"
        );
      }
      proof.play_integrity_token = integrity.token;
    } else {
      const purchase = input.allowPurchase
        ? await purchaseGooglePlayRelayAccess()
        : await queryGooglePlayRelayAccessPurchase();
      if (purchase.state === "pending") {
        throw new LocalFlightApiError(
          "Google Play is still processing the Relay Access purchase.",
          undefined,
          "purchase_pending"
        );
      }
      if (!purchase.owned || !purchase.purchaseToken) {
        throw new LocalFlightApiError(
          "Relay Access has not been purchased from Google Play.",
          undefined,
          "purchase_required"
        );
      }
      proof.google_play_purchase_token = purchase.purchaseToken;
      proof.google_play_product_id = purchase.productId || GOOGLE_PLAY_RELAY_ACCESS_PRODUCT_ID;
    }
  } catch (error) {
    throw normalizedNativeError(error);
  }

  const verified = await relayPost<OwnershipVerification>(input.relayUrl, "/v1/access/mobile/attestation/verify", {
    platform,
    install_id: input.installId,
    intent: input.intent,
    // Kept during the additive backend cutover for released relay builds.
    mode: input.intent === "standalone" ? "standalone" : "companion",
    device_name: identity.clientName,
    nonce: challenge.data.nonce,
    activation_grant: input.activationGrant || "",
    confirm_move_token: input.confirmMoveToken || "",
    ...proof
  }, "", challenge.origin);
  return verified;
}

export async function inspectPaidMobileOwnership(input: {
  installId: string;
  relayUrl?: string;
  intent?: "inspect" | "companion";
  allowPurchase?: boolean;
}): Promise<MobileRelayAccessSnapshot> {
  const verified = await verifyPaidMobileOwnership({
    ...input,
    intent: input.intent || "inspect"
  });
  if (!verified.response.ok || !verified.data.verified) {
    throwAccessError(verified.response, verified.data, "Paid-app ownership could not be verified.");
  }
  return snapshotFromVerification(verified.data);
}

export async function activatePaidMobileOwnership(input: {
  installId: string;
  relayUrl?: string;
  activationGrant?: string;
  confirmMoveToken?: string;
}): Promise<PaidAppActivation> {
  const verified = await verifyPaidMobileOwnership({ ...input, intent: "standalone", allowPurchase: true });
  if (verified.response.status === 409 && verified.data.move_token) {
    const access = snapshotFromVerification(verified.data);
    return {
      activated: false,
      credential: "",
      credentialPrefix: "",
      status: "main_device_in_use",
      activationState: "active",
      pendingExpiresIn: 0,
      relayOrigin: verified.origin,
      access,
      moveToken: verified.data.move_token,
      currentMainDeviceDescription: access.currentMainDeviceDescription || mainDeviceDescription(verified.data.current_receiver)
    };
  }
  const credential = verified.data.credential || "";
  const activationState = mobileActivationProtocolState({
    activated: Boolean(verified.data.activated),
    activationState: verified.data.activation_state || "",
    credential
  });
  if (!verified.response.ok || activationState === "invalid") {
    throwAccessError(verified.response, verified.data, "Paid-app ownership could not activate Relay Access.");
  }
  return {
    activated: true,
    credential,
    credentialPrefix: verified.data.credential_prefix || credential.slice(0, 12),
    status: "active",
    activationState,
    pendingExpiresIn: Math.max(0, Number(verified.data.pending_expires_in || 0)),
    relayOrigin: verified.origin,
    access: snapshotFromVerification({ ...verified.data, seat_state: "active_here" })
  };
}

export async function commitPendingRelayActivation(input: {
  installId: string;
  credential: string;
  relayOrigin?: string;
}): Promise<MobileRelayAccessSnapshot | null> {
  const committed = await relayPost<OwnershipVerification>(
    input.relayOrigin,
    "/v1/access/activate/commit",
    { install_id: input.installId },
    input.credential
  );
  const activationCommitted = committed.data.activated === true
    || committed.data.committed === true
    || committed.data.activation_state === "active";
  if (!committed.response.ok || !activationCommitted || committed.data.activation_state === "pending_commit") {
    throwAccessError(committed.response, committed.data, "Relay Access activation could not be committed.");
  }
  return rawLicense(committed.data)
    ? snapshotFromVerification({ ...committed.data, activated: true, seat_state: "active_here" })
    : null;
}

async function requestProtectionEmail(email: string, proofToken: string, relayUrl?: string): Promise<string> {
  const requested = await relayPost<ApiErrorPayload>(
    relayUrl,
    "/v1/access/magic-links/request",
    { email: email.trim(), purpose: "protect_and_deliver" },
    proofToken
  );
  if (!requested.response.ok && requested.response.status !== 202) {
    throwAccessError(requested.response, requested.data, "The verification email could not be requested.");
  }
  return "Check your email to confirm the address. Beacon Tools will then send a one-time management link for recovery or moving access.";
}

export async function protectPaidMobileOwnershipByEmail(input: {
  email: string;
  installId: string;
  relayUrl?: string;
}): Promise<string> {
  if (Platform.OS !== "ios") {
    throw new LocalFlightApiError(
      "Activate Relay Access in real-flight Standalone before adding recovery email.",
      undefined,
      "relay_credential_required"
    );
  }
  const inspected = await inspectPaidMobileOwnership({
    installId: input.installId,
    relayUrl: input.relayUrl,
    intent: "companion"
  });
  if (!inspected.deliveryClaim.startsWith("lfrclaim_")) {
    throw new LocalFlightApiError(
      "Beacon Relay did not issue a license-delivery claim.",
      502,
      "license_delivery_unavailable"
    );
  }
  return requestProtectionEmail(input.email, inspected.deliveryClaim, input.relayUrl);
}

export async function protectRelayAccessByEmail(input: {
  email: string;
  credential: string;
  relayUrl?: string;
}): Promise<string> {
  return requestProtectionEmail(input.email, input.credential, input.relayUrl);
}

export async function getRelayAccessStatus(input: {
  installId: string;
  credential: string;
  relayUrl?: string;
}): Promise<MobileRelayAccessSnapshot> {
  const origins = mobileRelayOrigins(input.relayUrl);
  let lastError: unknown = null;
  for (const [index, base] of origins.entries()) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), RELAY_ACCESS_TIMEOUT_MS);
    try {
      const params = new URLSearchParams({ install_id: input.installId });
      const response = await fetch(`${base}/v1/access/status?${params}`, {
        signal: controller.signal,
        headers: { Accept: "application/json", Authorization: `Bearer ${input.credential}` }
      });
      const data = await readJson<OwnershipVerification & {
        license_ref?: string;
        product_code?: string;
        purchase_source?: string;
        status?: string;
        key_ref?: string;
        created_at?: string;
        device_kind?: string;
        device_name?: string;
        activated_at?: string;
        last_seen_at?: string;
      }>(response, "Beacon Relay returned an invalid license status.");
      if (FAILOVER_ROUTE_STATUSES.has(response.status) && index < origins.length - 1) continue;
      if (!response.ok) throwAccessError(response, data, "Relay Access status could not be checked.");
      return snapshotFromVerification({
        ...data,
        activated: true,
        seat_state: data.seat_state || "active_here",
        license: data.license || {
          license_ref: data.license_ref,
          product_code: data.product_code,
          purchase_source: data.purchase_source,
          status: data.access_state || data.status || "active",
          access_state: data.access_state,
          reason_code: data.reason_code,
          key_ref: data.key_ref,
          created_at: data.created_at,
          receiver: {
            device_kind: data.device_kind,
            device_name: data.device_name,
            activated_at: data.activated_at,
            last_seen_at: data.last_seen_at
          }
        }
      });
    } catch (error) {
      lastError = controller.signal.aborted
        ? new LocalFlightApiError("Beacon Relay did not answer in time.", undefined, "relay_timeout")
        : error;
      if (error instanceof LocalFlightApiError && error.status && !FAILOVER_ROUTE_STATUSES.has(error.status)) throw error;
      if (index === origins.length - 1) throw lastError;
    } finally {
      clearTimeout(timer);
    }
  }
  throw lastError || new LocalFlightApiError("Beacon Relay could not be reached.", undefined, "relay_unavailable");
}

export async function deactivateRelayReceiver(input: {
  installId: string;
  credential: string;
  relayUrl?: string;
}): Promise<{
  state: "available" | "active_elsewhere";
  accessState: RelayLicenseAccessState;
  reasonCode: string;
  currentMainDeviceDescription: string;
}> {
  const result = await relayPost<ApiErrorPayload & {
    deactivated?: boolean;
    seat_state?: string;
    current_main_device?: RawMainDevice;
  }>(
    input.relayUrl,
    "/v1/access/deactivate",
    { install_id: input.installId },
    input.credential
  );
  if (!result.response.ok) {
    throwAccessError(result.response, result.data, "Relay Access could not be freed from this phone.");
  }
  const currentMainDeviceDescription = mainDeviceDescription(result.data.current_main_device);
  return {
    state: result.data.seat_state === "active_elsewhere" || currentMainDeviceDescription ? "active_elsewhere" : "available",
    accessState: normalizeAccessState(result.data.access_state),
    reasonCode: safeReasonCode(result.data.reason_code),
    currentMainDeviceDescription
  };
}

export function isTerminalRelayCredentialError(error: unknown): boolean {
  return Boolean(accessStateFromError(error)) || isTerminalCredentialCode(mobileAccessErrorCode(error));
}

export function isStaleMoveConfirmationError(error: unknown): boolean {
  const metadata = rawErrorMetadata(error);
  return isStaleMoveCode(metadata.code, error instanceof Error ? error.message : "")
    || isStaleMoveCode(metadata.reasonCode);
}

export function isStaleRelayActivationGrantError(error: unknown): boolean {
  const metadata = rawErrorMetadata(error);
  return isStaleActivationGrantCode(metadata.code, error instanceof Error ? error.message : "")
    || isStaleActivationGrantCode(metadata.reasonCode);
}

export function isExpiredPendingRelayActivationError(error: unknown): boolean {
  const metadata = rawErrorMetadata(error);
  return isExpiredPendingActivationCode(metadata.code) || isExpiredPendingActivationCode(metadata.reasonCode);
}
