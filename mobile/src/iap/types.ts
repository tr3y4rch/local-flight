import type { SupportProductId } from "./products";

export type SupportPurchaseStatus =
  | "loading"
  | "ready"
  | "purchasing"
  | "pending"
  | "verifying"
  | "success"
  | "error"
  | "unavailable";

export type SupportProductView = {
  id: SupportProductId;
  label: string;
  displayPrice: string;
};

export type SupportCatalogDiagnostic = {
  loadedCount: number;
  missingCount: number;
  statusCounts: Partial<Record<"ok" | "not-found" | "no-offers-available" | "unknown" | "absent", number>>;
};

export type SupportPurchaseController = {
  connected: boolean;
  purchasesEnabled: boolean;
  verificationReady: boolean;
  busy: boolean;
  products: SupportProductView[];
  status: SupportPurchaseStatus;
  message: string;
  catalogDiagnostic: SupportCatalogDiagnostic;
  purchase: (productId: SupportProductId) => Promise<void>;
  refresh: () => Promise<void>;
};
