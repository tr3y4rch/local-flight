import { Dimensions, Platform } from "react-native";

import { loadCompanionId } from "../storage/settings";

const APP_CONFIG = require("../../app.json") as {
  expo?: {
    version?: string;
    extra?: {
      localFlightVersion?: string;
    };
  };
};

const COMPANION_APP_VERSION = String(
  APP_CONFIG?.expo?.extra?.localFlightVersion ||
  APP_CONFIG?.expo?.version ||
  "0.2.5"
);

export type CompanionIdentity = {
  companionId: string;
  clientName: string;
  appVersion: string;
  mobileOs: string;
  deviceType: "phone" | "tablet" | "desktop" | "unknown";
};

function humanPlatformName(): string {
  if (Platform.OS === "ios") return "iOS";
  if (Platform.OS === "android") return "Android";
  if (Platform.OS === "web") return "Web";
  return Platform.OS || "Unknown";
}

function platformVersionLabel(): string {
  const raw = Platform.Version;
  if (raw == null) return "unknown";
  return String(raw);
}

function detectDeviceType(): "phone" | "tablet" | "desktop" | "unknown" {
  const size = Dimensions.get("window");
  const shortest = Math.min(size.width, size.height);
  const longest = Math.max(size.width, size.height);

  if (Platform.OS === "web") {
    if (shortest >= 900 || longest >= 1400) return "desktop";
    if (shortest >= 700) return "tablet";
    return "phone";
  }
  if (Platform.OS === "ios" && typeof Platform.isPad === "boolean") {
    return Platform.isPad ? "tablet" : "phone";
  }
  if (shortest >= 700 || longest >= 1200) return "tablet";
  if (shortest > 0) return "phone";
  return "unknown";
}

export function appVersion(): string {
  return COMPANION_APP_VERSION;
}

export function mobileOsLabel(): string {
  const deviceType = detectDeviceType();
  return `${humanPlatformName()} ${platformVersionLabel()} (${deviceType})`;
}

export function platformPairLabel(serverPlatform?: string | null, mobileOs?: string): string {
  return `${serverPlatform || "Unknown server"} / ${mobileOs || mobileOsLabel()}`;
}

export async function getCompanionIdentity(): Promise<CompanionIdentity> {
  return {
    companionId: await loadCompanionId(),
    clientName: "Local Flight Companion",
    appVersion: appVersion(),
    mobileOs: mobileOsLabel(),
    deviceType: detectDeviceType()
  };
}
