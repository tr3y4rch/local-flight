export type SupportTipTierId = "tip_2" | "tip_5" | "tip_10" | "tip_20";

export type SupportTipTier = {
  id: SupportTipTierId;
  productId: string;
  amountUsd: number;
  displayAmount: string;
  label: string;
  tagline: string;
};

export type SupportProductAvailability = "available" | "coming_soon" | "unavailable";

export type SupportProduct = SupportTipTier & {
  availability: SupportProductAvailability;
  priceLabel: string;
  statusLabel: string;
};

export type SupportPurchaseResult = {
  ok: boolean;
  message: string;
};

export interface SupportPurchaseProvider {
  id: string;
  loadProducts: () => Promise<SupportProduct[]>;
  purchaseTier: (tier: SupportProduct) => Promise<SupportPurchaseResult>;
}

export const SUPPORT_TIP_TIERS: SupportTipTier[] = [
  {
    id: "tip_2",
    productId: "cc.beacontools.localflight.tip.2",
    amountUsd: 2,
    displayAmount: "$2",
    label: "Small tip",
    tagline: "A quiet thank-you"
  },
  {
    id: "tip_5",
    productId: "cc.beacontools.localflight.tip.5",
    amountUsd: 5,
    displayAmount: "$5",
    label: "Nice tip",
    tagline: "Helps keep the relay warm"
  },
  {
    id: "tip_10",
    productId: "cc.beacontools.localflight.tip.10",
    amountUsd: 10,
    displayAmount: "$10",
    label: "Generous",
    tagline: "Supports polish and testing"
  },
  {
    id: "tip_20",
    productId: "cc.beacontools.localflight.tip.20",
    amountUsd: 20,
    displayAmount: "$20",
    label: "Big support",
    tagline: "Keeps the boards glowing"
  }
];

export function supportProductPlaceholders(): SupportProduct[] {
  return SUPPORT_TIP_TIERS.map((tier) => ({
    ...tier,
    availability: "coming_soon",
    priceLabel: tier.displayAmount,
    statusLabel: "Coming soon"
  }));
}

export const supportStubProvider: SupportPurchaseProvider = {
  id: "stub",
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
