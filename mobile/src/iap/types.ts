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

export type SupportPurchaseController = {
  connected: boolean;
  busy: boolean;
  products: SupportProductView[];
  status: SupportPurchaseStatus;
  message: string;
  purchase: (productId: SupportProductId) => Promise<void>;
  refresh: () => Promise<void>;
};
