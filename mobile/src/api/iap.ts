import { appVersion } from "../device/identity";
import { DEFAULT_RELAY_URL } from "./standalone";

const APP_ID = "cc.beacontools.localflight";

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

async function verifyOnce(input: VerifySupportPurchaseInput): Promise<VerifySupportPurchaseResponse> {
  let response: Response;
  try {
    response = await fetch(`${DEFAULT_RELAY_URL}/v1/mobile/iap/verify`, {
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
      const body = (await response.json()) as { detail?: string };
      if (body.detail) message = body.detail;
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
