import { useEffect, useMemo, useRef, useState } from "react";
import { Platform } from "react-native";
import { ErrorCode, type Product, type ProductStatusAndroid, type Purchase, useIAP } from "expo-iap";

import { getSupportPurchaseReadiness, IapVerificationApiError, verifySupportPurchase } from "../api/iap";
import { loadMobileRelayInstallId } from "../storage/settings";
import { isSupportProductId, SUPPORT_PRODUCT_COPY, SUPPORT_PRODUCT_IDS, type SupportProductId } from "./products";
import type { SupportCatalogDiagnostic, SupportProductView, SupportPurchaseController, SupportPurchaseStatus } from "./types";

function friendlyPurchaseError(code: ErrorCode | string | undefined): { status: SupportPurchaseStatus; message: string } {
  if (code === ErrorCode.UserCancelled) {
    return { status: "ready", message: "Purchase cancelled. Nothing was charged." };
  }
  if (code === ErrorCode.Pending || code === ErrorCode.DeferredPayment) {
    return { status: "pending", message: "The store is still approving this purchase. Local Flight will check it again later." };
  }
  if (code === ErrorCode.BillingUnavailable || code === ErrorCode.IapNotAvailable || code === ErrorCode.ItemUnavailable) {
    return { status: "unavailable", message: "Optional support is not available through this store right now." };
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
    if (product.platform === "android" && product.productStatusAndroid && product.productStatusAndroid !== "ok") return [];
    return [{
      id,
      label: product.displayName || product.title || SUPPORT_PRODUCT_COPY[id].label,
      displayPrice: product.displayPrice
    }];
  });
}

export function supportCatalogDiagnostic(products: Product[]): SupportCatalogDiagnostic {
  const byId = new Map(products.map((product) => [product.id, product]));
  const statusCounts: SupportCatalogDiagnostic["statusCounts"] = {};
  let loadedCount = 0;
  for (const id of SUPPORT_PRODUCT_IDS) {
    const product = byId.get(id);
    const status: ProductStatusAndroid | "absent" = !product
      ? "absent"
      : product.platform === "android"
        ? product.productStatusAndroid || (product.displayPrice ? "ok" : "unknown")
        : product.displayPrice ? "ok" : "unknown";
    statusCounts[status] = (statusCounts[status] || 0) + 1;
    if (status === "ok" && Boolean(product?.displayPrice)) loadedCount += 1;
  }
  return {
    loadedCount,
    missingCount: SUPPORT_PRODUCT_IDS.length - loadedCount,
    statusCounts
  };
}

function incompleteCatalogMessage(diagnostic: SupportCatalogDiagnostic): string {
  if (diagnostic.statusCounts["no-offers-available"]) {
    return "Some support choices are not available for this Play Store account or region. Nothing was started.";
  }
  if (diagnostic.statusCounts["not-found"]) {
    return "Some support choices are not available for this version of Local Flight. Nothing was started.";
  }
  if (diagnostic.loadedCount === 0) {
    return "Optional support is not available through this store right now. Every Local Flight feature remains available.";
  }
  return "Not all three support choices are available right now, so no purchase can be started.";
}

export function useSupportPurchases(): SupportPurchaseController {
  const [status, setStatus] = useState<SupportPurchaseStatus>("loading");
  const [message, setMessage] = useState("Connecting to the App Store or Play Store...");
  const [busy, setBusy] = useState(false);
  const [purchasesEnabled, setPurchasesEnabled] = useState(false);
  const [catalogQueried, setCatalogQueried] = useState(false);
  const [verificationReady, setVerificationReady] = useState(false);
  const [readinessChecked, setReadinessChecked] = useState(false);
  const processed = useRef(new Set<string>());
  const statusRef = useRef<SupportPurchaseStatus>(status);
  const processPurchaseRef = useRef<(purchase: Purchase) => Promise<void>>(async () => undefined);
  const fetchedProducts = useRef(false);
  const recoveredPurchases = useRef(false);
  const fetchedReadiness = useRef(false);
  const refreshing = useRef(false);
  const nextRefreshAt = useRef(0);

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
      setMessage("Optional support is not available through this store right now.");
    }
  });

  const views = productViews(iap.products);
  const catalogDiagnostic = useMemo(() => supportCatalogDiagnostic(iap.products), [iap.products]);
  statusRef.current = status;

  useEffect(() => {
    if (iap.connected) return;
    const timer = setTimeout(() => {
      if (statusRef.current !== "loading") return;
      setStatus("unavailable");
      setMessage(Platform.OS === "android"
        ? "Google Play could not be reached. Please try again later."
        : "The App Store could not be reached. Please try again later.");
    }, 5_000);
    return () => clearTimeout(timer);
  }, [iap.connected]);

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
    setMessage("Confirming the purchase securely...");
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
        setMessage("Confirmation is taking longer than usual. The store keeps the purchase safe and Local Flight will try again later.");
      } else if (error instanceof IapVerificationApiError && [403, 422].includes(error.status || 0)) {
        setMessage("The purchase could not be confirmed. Please contact support if it still appears in your store history.");
      } else if (error instanceof IapVerificationApiError && error.status === 503) {
        setMessage("Confirmation is temporarily unavailable. The store keeps the purchase safe and Local Flight will try again later.");
      } else {
        setMessage("Confirmation is delayed. The store keeps the purchase safe and Local Flight will try again later.");
      }
    } finally {
      setBusy(false);
    }
  };

  const checkReadiness = async (): Promise<boolean> => {
    try {
      const result = await getSupportPurchaseReadiness(Platform.OS === "android" ? "android" : "ios");
      setPurchasesEnabled(result.purchases_enabled);
      const expectedProducts = SUPPORT_PRODUCT_IDS.every((id) => result.product_ids.includes(id));
      const ready = result.purchases_enabled && result.verification_ready && expectedProducts;
      setVerificationReady(ready);
      setReadinessChecked(true);
      if (!ready && !busy) {
        setStatus("unavailable");
        setMessage(result.purchases_enabled
          ? "Optional support is temporarily unavailable. Nothing was started."
          : "Optional support is temporarily unavailable. Your existing access is unchanged.");
      }
      return ready;
    } catch {
      setVerificationReady(false);
      setReadinessChecked(true);
      if (!busy) {
        setStatus("unavailable");
        setMessage("Optional support is temporarily unavailable. Nothing was started.");
      }
      return false;
    }
  };

  useEffect(() => {
    if (fetchedReadiness.current || (Platform.OS !== "ios" && Platform.OS !== "android")) return;
    fetchedReadiness.current = true;
    void checkReadiness();
  }, []);

  useEffect(() => {
    if (!purchasesEnabled || !iap.connected || fetchedProducts.current) return;
    fetchedProducts.current = true;
    void iap.fetchProducts({ skus: [...SUPPORT_PRODUCT_IDS], type: "in-app" })
      .then(() => setCatalogQueried(true))
      .catch(() => {
        fetchedProducts.current = false;
        setCatalogQueried(true);
        setStatus("unavailable");
        setMessage("The support choices could not be loaded from the store. Please try again later.");
      });
  }, [iap.connected, purchasesEnabled]);

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
    if (!iap.connected || !readinessChecked) return;
    if (views.length === SUPPORT_PRODUCT_IDS.length && verificationReady && !busy && status === "loading") {
      setStatus("ready");
      setMessage("Optional one-time support. It unlocks nothing and changes no app features.");
    } else if (catalogQueried && views.length !== SUPPORT_PRODUCT_IDS.length && !busy && verificationReady) {
      setStatus("unavailable");
      setMessage(incompleteCatalogMessage(catalogDiagnostic));
    }
  }, [iap.connected, catalogDiagnostic, catalogQueried, views.length, busy, readinessChecked, status, verificationReady]);

  const purchase = async (productId: SupportProductId): Promise<void> => {
    if (busy || !purchasesEnabled || !verificationReady || views.length !== SUPPORT_PRODUCT_IDS.length) return;
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
    if (busy || refreshing.current || Date.now() < nextRefreshAt.current) return;
    refreshing.current = true;
    nextRefreshAt.current = Date.now() + 15_000;
    setStatus("loading");
    setMessage("Checking support choices and previous purchases...");
    setCatalogQueried(false);
    try {
      if (!iap.connected) await iap.reconnect();
      // Sales readiness must not prevent recovery of an already approved tip.
      await iap.getAvailablePurchases({ alsoPublishToEventListenerIOS: true, onlyIncludeActiveItemsIOS: false });
      const ready = await checkReadiness();
      if (!ready) return;
      await iap.fetchProducts({ skus: [...SUPPORT_PRODUCT_IDS], type: "in-app" });
      setCatalogQueried(true);
    } catch {
      setCatalogQueried(true);
      setStatus("unavailable");
      setMessage("The store is not available right now. Please try again later.");
    } finally {
      refreshing.current = false;
    }
  };

  return {
    connected: iap.connected,
    purchasesEnabled,
    verificationReady,
    busy,
    products: views,
    status,
    message,
    catalogDiagnostic,
    purchase,
    refresh
  };
}
