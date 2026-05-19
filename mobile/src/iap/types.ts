import type { SupportProduct } from "../domain/support";

export type AppleIapEnvironment = "sandbox" | "production" | "xcode" | "unknown";

export type AppleStoreProduct = {
  productId: string;
  title: string;
  description: string;
  priceLabel: string;
};

export type AppleIapTransaction = {
  productId: string;
  transactionId: string;
  originalTransactionId?: string;
  appAccountToken?: string;
  signedTransactionInfo?: string;
  signedRenewalInfo?: string;
  environment?: AppleIapEnvironment;
  purchaseDate?: string;
};

export type AppleIapVerificationPayload = {
  installId: string;
  appAccountToken: string;
  appVersion: string;
  productId: string;
  transactionId: string;
  originalTransactionId?: string;
  signedTransactionInfo?: string;
  signedRenewalInfo?: string;
  environment?: AppleIapEnvironment;
};

export type AppleIapVerificationResult = {
  ok: boolean;
  status: "verified" | "pending" | "unavailable" | "invalid";
  message: string;
};

export interface NativeAppleIapAdapter {
  isAvailable: () => Promise<boolean>;
  loadProducts: (productIds: string[]) => Promise<AppleStoreProduct[]>;
  requestPurchase: (product: SupportProduct, appAccountToken: string) => Promise<AppleIapTransaction>;
  finishTransaction: (transaction: AppleIapTransaction) => Promise<void>;
}
