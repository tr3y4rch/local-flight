import { appVersion } from "../device/identity";
import { preferredStandaloneRelayUrl } from "./standalone";

const APP_ID = "cc.beacontools.localflight";

async function purchaseResponse(url: string, init?: RequestInit): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12_000);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

export type VerifySupportPurchaseInput = {
  platform: "ios" | "android";
  installId: string;
  productId: string;
  transactionId?: string | null;
  purchaseToken?: string | null;
};

export type VerifySupportPurchaseResponse = {
  ok: true;
  verified: true;
  duplicate: boolean;
  platform: "ios" | "android";
  product_id: string;
  transaction_ref: string;
  environment: string;
  finish_transaction: boolean;
};

export type SupportPurchaseReadinessResponse = {
  ok: true;
  platform: "ios" | "android";
  purchases_enabled: boolean;
  verification_ready: boolean;
  product_ids: string[];
  message: string;
};

export class IapVerificationApiError extends Error {
  constructor(message: string, public readonly status?: number) {
    super(message);
    this.name = "IapVerificationApiError";
  }
}

function retryable(status?: number): boolean {
  return status == null || status >= 500;
}

async function delay(milliseconds: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, milliseconds));
}

export async function getSupportPurchaseReadiness(
  platform: "ios" | "android"
): Promise<SupportPurchaseReadinessResponse> {
  let response: Response;
  try {
    response = await purchaseResponse(
      `${preferredStandaloneRelayUrl()}/v1/mobile/iap/status?platform=${encodeURIComponent(platform)}`,
      { headers: { Accept: "application/json" } }
    );
  } catch {
    throw new IapVerificationApiError("Optional support is temporarily unavailable.");
  }
  if (!response.ok) {
    throw new IapVerificationApiError("Optional support is temporarily unavailable.", response.status);
  }
  return response.json() as Promise<SupportPurchaseReadinessResponse>;
}

async function verifyOnce(input: VerifySupportPurchaseInput): Promise<VerifySupportPurchaseResponse> {
  let response: Response;
  try {
    response = await purchaseResponse(`${preferredStandaloneRelayUrl()}/v1/mobile/iap/verify`, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({
        platform: input.platform,
        install_id: input.installId,
        product_id: input.productId,
        transaction_id: input.platform === "ios" ? input.transactionId || "" : "",
        purchase_token: input.platform === "android" ? input.purchaseToken || "" : "",
        app_version: appVersion(),
        bundle_id: APP_ID
      })
    });
  } catch {
    throw new IapVerificationApiError("The purchase is safe in the store, but Local Flight could not reach verification yet.");
  }

  if (!response.ok) {
    let message = "The store purchase could not be verified yet.";
    try {
      const body = (await response.json()) as { detail?: string | { message?: string } };
      if (typeof body.detail === "string") message = body.detail;
      else if (body.detail?.message) message = body.detail.message;
    } catch {
      // Keep the safe, user-facing fallback.
    }
    throw new IapVerificationApiError(message, response.status);
  }
  return response.json() as Promise<VerifySupportPurchaseResponse>;
}

export async function verifySupportPurchase(
  input: VerifySupportPurchaseInput
): Promise<VerifySupportPurchaseResponse> {
  try {
    return await verifyOnce(input);
  } catch (error) {
    const apiError = error instanceof IapVerificationApiError ? error : new IapVerificationApiError("Purchase verification is temporarily unavailable.");
    if (!retryable(apiError.status)) throw apiError;
    await delay(1200);
    return verifyOnce(input);
  }
}
