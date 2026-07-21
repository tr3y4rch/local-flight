import { requireNativeModule } from "expo-modules-core";

type WidgetReloadResult = {
  available: boolean;
  widgetCount?: number;
};

export type LocalFlightLiveActivityAction =
  | "status"
  | "started"
  | "updated"
  | "ended"
  | "no_activity"
  | "no_pinned_flight"
  | "disabled"
  | "unsupported"
  | "failed";

export type LocalFlightLiveActivityResult = {
  supported: boolean;
  enabled: boolean;
  active: boolean;
  action: LocalFlightLiveActivityAction;
};

type LocalFlightWidgetBridgeNativeModule = {
  reload(): Promise<WidgetReloadResult>;
  isSupported?(): Promise<LocalFlightLiveActivityResult>;
  startLiveActivity?(): Promise<LocalFlightLiveActivityResult>;
  updateLiveActivity?(): Promise<LocalFlightLiveActivityResult>;
  endLiveActivity?(): Promise<LocalFlightLiveActivityResult>;
  reconcileLiveActivity?(): Promise<LocalFlightLiveActivityResult>;
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
  const module = getNativeModule();
  if (!module) return { available: false };

  let reloadResult: WidgetReloadResult;
  try {
    reloadResult = await module.reload();
  } catch {
    reloadResult = { available: false };
  }

  // A snapshot write is also the safest time to reconcile a local pinned-flight
  // activity. This remains best-effort and never prevents the widget reload.
  try {
    await module.reconcileLiveActivity?.();
  } catch {
    // ActivityKit may be unavailable or disabled; the Home Screen widget still works.
  }
  return reloadResult;
}

const unsupportedLiveActivity = (): LocalFlightLiveActivityResult => ({
  supported: false,
  enabled: false,
  active: false,
  action: "unsupported"
});

async function callLiveActivity(
  method: keyof Pick<
    LocalFlightWidgetBridgeNativeModule,
    "isSupported" | "startLiveActivity" | "updateLiveActivity" | "endLiveActivity" | "reconcileLiveActivity"
  >
): Promise<LocalFlightLiveActivityResult> {
  const module = getNativeModule();
  const nativeMethod = module?.[method];
  if (!nativeMethod) return unsupportedLiveActivity();
  try {
    return await nativeMethod.call(module);
  } catch {
    return unsupportedLiveActivity();
  }
}

export function isLocalFlightLiveActivitySupported(): Promise<LocalFlightLiveActivityResult> {
  return callLiveActivity("isSupported");
}

export function startLocalFlightLiveActivity(): Promise<LocalFlightLiveActivityResult> {
  return callLiveActivity("startLiveActivity");
}

export function updateLocalFlightLiveActivity(): Promise<LocalFlightLiveActivityResult> {
  return callLiveActivity("updateLiveActivity");
}

export function endLocalFlightLiveActivity(): Promise<LocalFlightLiveActivityResult> {
  return callLiveActivity("endLiveActivity");
}

export function reconcileLocalFlightLiveActivity(): Promise<LocalFlightLiveActivityResult> {
  return callLiveActivity("reconcileLiveActivity");
}
