import { DEFAULT_RELAY_URL } from "./standalone";
import { LocalFlightApiError, normalizeServerUrl } from "./client";
import type { AppleIapVerificationPayload, AppleIapVerificationResult } from "../iap/types";

async function postRelayJson<T>(relayUrl: string | undefined, path: string, body: unknown): Promise<T> {
  const base = normalizeServerUrl(relayUrl || DEFAULT_RELAY_URL);
  const response = await fetch(`${base}${path}`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json"
    },
    body: JSON.stringify(body)
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload && typeof payload === "object" && "detail" in payload
      ? String((payload as { detail?: unknown }).detail || "")
      : "";
    throw new LocalFlightApiError(detail || `Relay HTTP ${response.status} for ${path}`, response.status);
  }
  return payload as T;
}

export function verifyAppleIapPurchase(
  payload: AppleIapVerificationPayload,
  relayUrl?: string
): Promise<AppleIapVerificationResult> {
  return postRelayJson<AppleIapVerificationResult>(relayUrl, "/v1/mobile/iap/apple/verify", {
    install_id: payload.installId,
    app_account_token: payload.appAccountToken,
    app_version: payload.appVersion,
    product_id: payload.productId,
    transaction_id: payload.transactionId,
    original_transaction_id: payload.originalTransactionId || "",
    signed_transaction_info: payload.signedTransactionInfo || "",
    signed_renewal_info: payload.signedRenewalInfo || "",
    environment: payload.environment || "unknown"
  });
}
