import { Platform, UIManager } from "react-native";

import {
  resolveNativeNavigationCapabilities,
  type NativeNavigationCapabilities
} from "./nativeNavigationCapabilities";
import type { LayoutWidthClass } from "../utils/layout";

/**
 * Expo Go or an older development client may not contain the experimental
 * react-native-screens host. Falling back before rendering it avoids a native
 * component error and leaves the regular adaptive navigator fully usable.
 */
export function nativeBottomTabsAvailable(): boolean {
  if (Platform.OS !== "ios") return false;
  try {
    return Boolean(UIManager.getViewManagerConfig?.("RNSBottomTabs"));
  } catch {
    return false;
  }
}

export function runtimeNativeNavigationCapabilities(
  layoutClass: LayoutWidthClass,
  rolloutEnabled: boolean
): NativeNavigationCapabilities {
  const iosPlatform = Platform as typeof Platform & { isPad?: boolean; isTV?: boolean };
  return resolveNativeNavigationCapabilities({
    platform: Platform.OS,
    platformVersion: Platform.Version,
    isPad: iosPlatform.isPad === true,
    isTV: iosPlatform.isTV === true,
    layoutClass,
    rolloutEnabled,
    nativeTabsAvailable: nativeBottomTabsAvailable()
  });
}
