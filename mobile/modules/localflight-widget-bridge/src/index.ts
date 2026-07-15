import { requireNativeModule } from "expo-modules-core";

type WidgetReloadResult = {
  available: boolean;
  widgetCount?: number;
};

type LocalFlightWidgetBridgeNativeModule = {
  reload(): Promise<WidgetReloadResult>;
};

let nativeModule: LocalFlightWidgetBridgeNativeModule | null | undefined;

function getNativeModule(): LocalFlightWidgetBridgeNativeModule | null {
  if (nativeModule !== undefined) return nativeModule;
  try {
    nativeModule = requireNativeModule<LocalFlightWidgetBridgeNativeModule>("LocalFlightWidgetBridge");
  } catch {
    nativeModule = null;
  }
  return nativeModule;
}

export async function reloadLocalFlightWidgets(): Promise<WidgetReloadResult> {
  try {
    return await getNativeModule()?.reload() || { available: false };
  } catch {
    return { available: false };
  }
}
