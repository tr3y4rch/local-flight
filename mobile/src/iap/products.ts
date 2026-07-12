export const SUPPORT_PRODUCT_IDS = [
  "cc.beacontools.localflight.support.small",
  "cc.beacontools.localflight.support.medium",
  "cc.beacontools.localflight.support.large"
] as const;

export type SupportProductId = typeof SUPPORT_PRODUCT_IDS[number];

export const SUPPORT_PRODUCT_COPY: Record<SupportProductId, { label: string }> = {
  "cc.beacontools.localflight.support.small": {
    label: "Runway Snack"
  },
  "cc.beacontools.localflight.support.medium": {
    label: "Gate Coffee"
  },
  "cc.beacontools.localflight.support.large": {
    label: "Long-Haul Fuel"
  }
};

export function isSupportProductId(value: string): value is SupportProductId {
  return SUPPORT_PRODUCT_IDS.includes(value as SupportProductId);
}
