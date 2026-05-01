import type { DashboardSnapshot } from "../api/types";
import { normalizeServerUrl } from "../api/client";
import { platformPairLabel, type CompanionIdentity } from "../device/identity";
import { APP_VERSION } from "./constants";

export function mobileClientContext(
  serverUrl: string,
  snapshot?: DashboardSnapshot,
  companion?: CompanionIdentity | null
): string {
  const mobileOs = companion?.mobileOs || "Unknown mobile OS";
  const companionId = companion?.companionId || "unknown";
  const serverPlatform = snapshot?.system?.platform || "unknown";
  return [
    `Reporter       ${companion?.clientName || "Local Flight Companion"}`,
    `Companion ID   ${companionId}`,
    `App version    ${companion?.appVersion || APP_VERSION}`,
    `Companion OS   ${mobileOs}`,
    `Server install ${snapshot?.system?.install_id || "unknown"}`,
    `Platform pair  ${platformPairLabel(serverPlatform, mobileOs)}`,
    `Server URL     ${normalizeServerUrl(serverUrl) || "not set"}`,
    `Airport        ${snapshot?.config?.airport_iata || "---"}`,
    `Source         ${snapshot?.state?.source_name || snapshot?.config?.source || "unknown"}`
  ].join("\n");
}
