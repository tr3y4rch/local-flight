import { Platform } from "react-native";
import { requireNativeModule } from "expo-modules-core";

export const GOOGLE_PLAY_RELAY_ACCESS_PRODUCT_ID =
  "cc.beacontools.localflight.relay_access" as const;

export type GooglePlayRelayAccessPurchaseState =
  | "purchased"
  | "pending"
  | "not_owned";

/** Transient store evidence. Callers must not persist purchaseToken. */
export type GooglePlayRelayAccessPurchase = {
  owned: boolean;
  state: GooglePlayRelayAccessPurchaseState;
  productId: string;
  purchaseToken: string;
  acknowledged: boolean;
};

/** Transient encrypted token. Beacon Relay must decode and verify it server-side. */
export type GooglePlayIntegrityProof = {
  token: string;
  requestHash: string;
};

export type AppleAppTransactionProof = {
  signedAppTransaction: string;
  deviceVerificationId: string;
};

export const PAID_APP_PROOF_ERROR_CODES = {
  storeCancelled: "store_cancelled",
  storeUnavailable: "store_unavailable",
  ownershipUnverified: "ownership_unverified",
  deviceVerificationMissing: "device_verification_missing",
  storeTimeout: "store_timeout",
  unsupportedBuild: "unsupported_build",
  purchasePending: "purchase_pending"
} as const;

export type PaidAppProofErrorCode =
  (typeof PAID_APP_PROOF_ERROR_CODES)[keyof typeof PAID_APP_PROOF_ERROR_CODES];

export class PaidAppProofError extends Error {
  readonly code: PaidAppProofErrorCode;
  readonly cause?: unknown;

  constructor(code: PaidAppProofErrorCode, message: string, cause?: unknown) {
    super(message);
    this.name = "PaidAppProofError";
    this.code = code;
    this.cause = cause;
  }
}

type PaidAppNativeModule = {
  getFreshAppleAppTransactionProof(): Promise<AppleAppTransactionProof>;
  queryGooglePlayRelayAccessPurchase(): Promise<GooglePlayRelayAccessPurchase>;
  purchaseGooglePlayRelayAccess(): Promise<GooglePlayRelayAccessPurchase>;
  requestGooglePlayIntegrityToken(
    nonce: string,
    installId: string,
    activationGrant: string
  ): Promise<GooglePlayIntegrityProof>;
};

let nativeModule: PaidAppNativeModule | null | undefined;

function module(): PaidAppNativeModule {
  if (nativeModule === undefined) {
    try {
      nativeModule = requireNativeModule<PaidAppNativeModule>("LocalFlightPaidApp");
    } catch {
      nativeModule = null;
    }
  }
  if (!nativeModule) {
    throw new PaidAppProofError(
      PAID_APP_PROOF_ERROR_CODES.unsupportedBuild,
      "Native Relay Access verification is unavailable in this build."
    );
  }
  return nativeModule;
}

function unsupportedPlatform(message: string): PaidAppProofError {
  return new PaidAppProofError(PAID_APP_PROOF_ERROR_CODES.unsupportedBuild, message);
}

export async function getFreshAppleAppTransactionProof(): Promise<AppleAppTransactionProof> {
  if (Platform.OS !== "ios") throw unsupportedPlatform("Apple app ownership is available only on iOS.");
  return module().getFreshAppleAppTransactionProof();
}

export async function queryGooglePlayRelayAccessPurchase(): Promise<GooglePlayRelayAccessPurchase> {
  if (Platform.OS !== "android") {
    throw unsupportedPlatform("Google Play purchasing is available only on Android.");
  }
  return module().queryGooglePlayRelayAccessPurchase();
}

export async function purchaseGooglePlayRelayAccess(): Promise<GooglePlayRelayAccessPurchase> {
  if (Platform.OS !== "android") {
    throw unsupportedPlatform("Google Play purchasing is available only on Android.");
  }
  return module().purchaseGooglePlayRelayAccess();
}

export async function requestGooglePlayIntegrityToken(
  nonce: string,
  installId: string,
  activationGrant: string
): Promise<GooglePlayIntegrityProof> {
  if (Platform.OS !== "android") {
    throw unsupportedPlatform("Google Play device verification is available only on Android.");
  }
  return module().requestGooglePlayIntegrityToken(nonce, installId, activationGrant);
}

export function paidAppProofErrorCode(error: unknown): PaidAppProofErrorCode | null {
  if (!error || typeof error !== "object" || !("code" in error)) return null;
  const code = String((error as { code?: unknown }).code || "") as PaidAppProofErrorCode;
  return (Object.values(PAID_APP_PROOF_ERROR_CODES) as string[]).includes(code) ? code : null;
}
