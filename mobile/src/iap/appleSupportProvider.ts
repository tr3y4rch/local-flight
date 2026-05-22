import { Platform } from "react-native";

import { verifyAppleIapPurchase } from "../api/iap";
import { appVersion } from "../device/identity";
import type { SupportProduct, SupportPurchaseProvider, SupportPurchaseResult } from "../domain/support";
import { supportProductPlaceholders } from "../domain/support";
import { loadMobileRelayInstallId } from "../storage/settings";
import type { NativeAppleIapAdapter } from "./types";

export const APPLE_IAP_BUNDLE_ID = "com.localflight.companion";

export function createAppleSupportPurchaseProvider(
  adapter: NativeAppleIapAdapter,
  options: { relayUrl?: string } = {}
): SupportPurchaseProvider {
  return {
    id: "apple-iap",
    async loadProducts() {
      if (Platform.OS !== "ios" || !(await adapter.isAvailable())) {
        return supportProductPlaceholders().map((product) => ({
          ...product,
          availability: "unavailable",
          statusLabel: "App Store unavailable"
        }));
      }
      const storeProducts = await adapter.loadProducts(supportProductPlaceholders().map((product) => product.productId));
      return supportProductPlaceholders().map((product) => {
        const storeProduct = storeProducts.find((candidate) => candidate.productId === product.productId);
        return {
          ...product,
          availability: storeProduct ? "available" : "unavailable",
          priceLabel: storeProduct?.priceLabel || product.priceLabel,
          statusLabel: storeProduct ? "Available" : "Unavailable"
        };
      });
    },
    async purchaseTier(product: SupportProduct): Promise<SupportPurchaseResult> {
      if (product.availability !== "available") {
        return { ok: false, message: "This App Store product is not available yet." };
      }
      const installId = await loadMobileRelayInstallId();
      const transaction = await adapter.requestPurchase(product, installId);
      const verification = await verifyAppleIapPurchase(
        {
          installId,
          appAccountToken: transaction.appAccountToken || installId,
          appVersion: appVersion(),
          productId: transaction.productId,
          transactionId: transaction.transactionId,
          originalTransactionId: transaction.originalTransactionId,
          signedTransactionInfo: transaction.signedTransactionInfo,
          signedRenewalInfo: transaction.signedRenewalInfo,
          environment: transaction.environment
        },
        options.relayUrl
      );
      if (verification.ok) {
        await adapter.finishTransaction(transaction);
      }
      return {
        ok: verification.ok,
        message: verification.message
      };
    }
  };
}

export const appleIapPlaceholderProvider: SupportPurchaseProvider = {
  id: "apple-iap-placeholder",
  async loadProducts() {
    return supportProductPlaceholders();
  },
  async purchaseTier() {
    return {
      ok: false,
      message: "Support tips are scaffolded, but not active in this build yet."
    };
  }
};
