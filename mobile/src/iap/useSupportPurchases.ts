import { useEffect, useRef, useState } from "react";
import { Platform } from "react-native";
import { ErrorCode, type Product, type Purchase, useIAP } from "expo-iap";

import { IapVerificationApiError, verifySupportPurchase } from "../api/iap";
import { loadMobileRelayInstallId } from "../storage/settings";
import { isSupportProductId, SUPPORT_PRODUCT_COPY, SUPPORT_PRODUCT_IDS, type SupportProductId } from "./products";
import type { SupportProductView, SupportPurchaseController, SupportPurchaseStatus } from "./types";

function friendlyPurchaseError(code: ErrorCode | string | undefined): { status: SupportPurchaseStatus; message: string } {
  if (code === ErrorCode.UserCancelled) {
    return { status: "ready", message: "Purchase cancelled. Nothing was charged." };
  }
  if (code === ErrorCode.Pending || code === ErrorCode.DeferredPayment) {
    return { status: "pending", message: "The store is still approving this purchase. Local Flight will check it again later." };
  }
  if (code === ErrorCode.BillingUnavailable || code === ErrorCode.IapNotAvailable || code === ErrorCode.ItemUnavailable) {
    return { status: "unavailable", message: "Support purchases are not available for this store account or build yet." };
  }
  if (code === ErrorCode.NetworkError || code === ErrorCode.ServiceDisconnected || code === ErrorCode.ServiceTimeout) {
    return { status: "error", message: "The store is temporarily offline. Please try again later." };
  }
  return { status: "error", message: "The store could not complete that purchase. No Local Flight feature depends on it." };
}

function productViews(products: Product[]): SupportProductView[] {
  const byId = new Map(products.map((product) => [product.id, product]));
  return SUPPORT_PRODUCT_IDS.flatMap((id) => {
    const product = byId.get(id);
    if (!product?.displayPrice) return [];
    return [{
      id,
      label: product.displayName || product.title || SUPPORT_PRODUCT_COPY[id].label,
      displayPrice: product.displayPrice
    }];
  });
}

export function useSupportPurchases(): SupportPurchaseController {
  const [status, setStatus] = useState<SupportPurchaseStatus>("loading");
  const [message, setMessage] = useState("Connecting to the App Store or Play Store...");
  const [busy, setBusy] = useState(false);
  const processed = useRef(new Set<string>());
  const processPurchaseRef = useRef<(purchase: Purchase) => Promise<void>>(async () => undefined);
  const fetchedProducts = useRef(false);
  const recoveredPurchases = useRef(false);

  const iap = useIAP({
    onPurchaseSuccess: (purchase) => { void processPurchaseRef.current(purchase); },
    onPurchaseError: (error) => {
      const friendly = friendlyPurchaseError(error.code);
      setBusy(false);
      setStatus(friendly.status);
      setMessage(friendly.message);
    },
    onError: () => {
      setBusy(false);
      setStatus("unavailable");
      setMessage("Support purchases are not available for this store account or build yet.");
    }
  });

  const views = productViews(iap.products);

  processPurchaseRef.current = async (purchase: Purchase) => {
    if (!isSupportProductId(purchase.productId)) return;
    if (purchase.purchaseState === "pending") {
      setBusy(false);
      setStatus("pending");
      setMessage("The store is still approving this purchase. Local Flight will check it again later.");
      return;
    }
    const proof = Platform.OS === "ios" ? purchase.transactionId : purchase.purchaseToken;
    if (!proof) {
      setBusy(false);
      setStatus("error");
      setMessage("The store did not provide a verifiable purchase reference. Nothing has been consumed.");
      return;
    }
    const processKey = `${Platform.OS}:${proof}`;
    if (processed.current.has(processKey)) return;
    processed.current.add(processKey);
    setBusy(true);
    setStatus("verifying");
    setMessage("The store completed the purchase. Verifying it securely...");
    try {
      const installId = await loadMobileRelayInstallId();
      const verified = await verifySupportPurchase({
        platform: Platform.OS === "ios" ? "ios" : "android",
        installId,
        productId: purchase.productId,
        transactionId: Platform.OS === "ios" ? purchase.transactionId : null,
        purchaseToken: Platform.OS === "android" ? purchase.purchaseToken : null
      });
      if (!verified.verified || !verified.finish_transaction) {
        throw new Error("Purchase verification did not finish");
      }
      await iap.finishTransaction({ purchase, isConsumable: true });
      setStatus("success");
      setMessage(verified.duplicate
        ? "This support purchase was already verified. Thank you again."
        : "Thank you for supporting Local Flight. No features were locked or changed.");
    } catch (error) {
      processed.current.delete(processKey);
      setStatus("error");
      if (error instanceof IapVerificationApiError && error.status === 409) {
        setStatus("pending");
        setMessage("The store is still approving this purchase. Local Flight will check it again later.");
      } else if (error instanceof IapVerificationApiError && error.status === 429) {
        setMessage("Verification has been rate-limited. The purchase remains unfinished and will be retried later.");
      } else if (error instanceof IapVerificationApiError && [403, 422].includes(error.status || 0)) {
        setMessage("The store evidence was rejected. The purchase was not consumed; please use Report Problem if this persists.");
      } else if (error instanceof IapVerificationApiError && error.status === 503) {
        setMessage("Secure purchase verification is not configured on the relay yet. The purchase remains unfinished.");
      } else {
        setMessage("Verification is delayed. The store keeps this purchase safe and Local Flight will retry before consuming it.");
      }
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!iap.connected || fetchedProducts.current) return;
    fetchedProducts.current = true;
    void iap.fetchProducts({ skus: [...SUPPORT_PRODUCT_IDS], type: "in-app" }).catch(() => {
      fetchedProducts.current = false;
      setStatus("unavailable");
      setMessage("Support products are not configured for this store account or build yet.");
    });
  }, [iap.connected]);

  useEffect(() => {
    if (!iap.connected || recoveredPurchases.current) return;
    recoveredPurchases.current = true;
    void iap.getAvailablePurchases({
      alsoPublishToEventListenerIOS: true,
      onlyIncludeActiveItemsIOS: false
    }).catch(() => {
      recoveredPurchases.current = false;
    });
  }, [iap.connected]);

  useEffect(() => {
    for (const purchase of iap.availablePurchases) {
      void processPurchaseRef.current(purchase);
    }
  }, [iap.availablePurchases]);

  useEffect(() => {
    if (!iap.connected) return;
    if (views.length === SUPPORT_PRODUCT_IDS.length && !busy && status === "loading") {
      setStatus("ready");
      setMessage("Optional one-time support. It unlocks nothing and changes no app features.");
    } else if (iap.products.length > 0 && views.length !== SUPPORT_PRODUCT_IDS.length && !busy) {
      setStatus("unavailable");
      setMessage("The store catalog is incomplete. Support purchases stay disabled until all products are available.");
    }
  }, [iap.connected, iap.products, views.length, busy, status]);

  const purchase = async (productId: SupportProductId): Promise<void> => {
    if (busy || views.length !== SUPPORT_PRODUCT_IDS.length) return;
    setBusy(true);
    setStatus("purchasing");
    setMessage("Opening the store purchase sheet...");
    try {
      await iap.requestPurchase({
        request: {
          apple: { sku: productId },
          google: { skus: [productId] }
        },
        type: "in-app"
      });
    } catch (error) {
      const friendly = friendlyPurchaseError((error as { code?: ErrorCode })?.code);
      setBusy(false);
      setStatus(friendly.status);
      setMessage(friendly.message);
    }
  };

  const refresh = async (): Promise<void> => {
    if (busy) return;
    setStatus("loading");
    setMessage("Refreshing store products and unfinished purchases...");
    try {
      if (!iap.connected) await iap.reconnect();
      await iap.fetchProducts({ skus: [...SUPPORT_PRODUCT_IDS], type: "in-app" });
      await iap.getAvailablePurchases({ alsoPublishToEventListenerIOS: true, onlyIncludeActiveItemsIOS: false });
    } catch {
      setStatus("unavailable");
      setMessage("The store is not available right now. Please try again later.");
    }
  };

  return {
    connected: iap.connected,
    busy,
    products: views,
    status,
    message,
    purchase,
    refresh
  };
}
