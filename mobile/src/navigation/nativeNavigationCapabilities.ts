import type { LayoutWidthClass } from "../utils/layout";

/**
 * Native bottom tabs are intentionally an internal, capability-gated V2
 * enhancement. UIKit owns the Liquid Glass material; the regular React
 * Navigation tabs remain the safe fallback on every other configuration.
 */
export const LIQUID_GLASS_MIN_IOS_MAJOR = 26;

export type NativeNavigationEnvironment = {
  platform: string;
  platformVersion: string | number;
  isPad: boolean;
  isTV: boolean;
  layoutClass: LayoutWidthClass;
  rolloutEnabled: boolean;
  nativeTabsAvailable: boolean;
};

export type NativeNavigationCapabilities = {
  iosMajorVersion: number;
  supportsLiquidGlass: boolean;
  isCompactPhone: boolean;
  nativeTabsAvailable: boolean;
  usesNativeLiquidGlassTabs: boolean;
};

export function iosMajorVersion(version: string | number): number {
  const parsed = typeof version === "number"
    ? version
    : Number.parseFloat(version);
  return Number.isFinite(parsed) ? Math.max(0, Math.trunc(parsed)) : 0;
}

export function resolveNativeNavigationCapabilities(
  environment: NativeNavigationEnvironment
): NativeNavigationCapabilities {
  const iosMajor = iosMajorVersion(environment.platformVersion);
  const supportsLiquidGlass = environment.platform === "ios" && iosMajor >= LIQUID_GLASS_MIN_IOS_MAJOR;
  const isCompactPhone = environment.layoutClass === "compact" && !environment.isPad && !environment.isTV;
  const usesNativeLiquidGlassTabs = environment.rolloutEnabled
    && environment.nativeTabsAvailable
    && supportsLiquidGlass
    && isCompactPhone;

  return {
    iosMajorVersion: iosMajor,
    supportsLiquidGlass,
    isCompactPhone,
    nativeTabsAvailable: environment.nativeTabsAvailable,
    usesNativeLiquidGlassTabs
  };
}
