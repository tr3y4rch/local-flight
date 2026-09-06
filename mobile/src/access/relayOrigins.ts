import { NativeModules } from "react-native";

const SAFE_DEFAULT_RELAY_ORIGIN = "https://relay-staging.beacontools.cc";

type UnknownRecord = Record<string, unknown>;

function asRecord(value: unknown): UnknownRecord | null {
  return value && typeof value === "object" ? value as UnknownRecord : null;
}

function parsedRecord(value: unknown): UnknownRecord | null {
  if (typeof value !== "string") return asRecord(value);
  try {
    return asRecord(JSON.parse(value));
  } catch {
    return null;
  }
}

function expoLocalFlightExtra(): UnknownRecord | null {
  const constants = asRecord((NativeModules as UnknownRecord).ExponentConstants);
  if (!constants) return null;

  const expoConfig = parsedRecord(constants.expoConfig);
  const manifest = parsedRecord(constants.manifest);
  const manifest2 = parsedRecord(constants.manifest2);
  const manifest2Extra = asRecord(manifest2?.extra);
  const expoClient = asRecord(manifest2Extra?.expoClient);
  const candidates = [
    asRecord(asRecord(expoConfig?.extra)?.localFlight),
    asRecord(asRecord(manifest?.extra)?.localFlight),
    asRecord(asRecord(expoClient?.extra)?.localFlight),
    asRecord(manifest2Extra?.localFlight)
  ];
  return candidates.find(Boolean) || null;
}

function normalizeOrigin(value: unknown): string {
  const text = typeof value === "string" ? value.trim().replace(/\/+$/, "") : "";
  if (!text) return "";
  try {
    const parsed = new URL(text);
    if (parsed.protocol !== "https:") return "";
    if (!parsed.hostname || parsed.username || parsed.password || parsed.search || parsed.hash) return "";
    return parsed.toString().replace(/\/+$/, "");
  } catch {
    return "";
  }
}

function configuredFailovers(value: unknown): string[] {
  const entries = Array.isArray(value)
    ? value
    : typeof value === "string"
      ? value.split(",")
      : [];
  return entries.map(normalizeOrigin).filter(Boolean);
}

/**
 * Returns the relay origins baked into this build profile. An explicit origin
 * is kept isolated so a custom relay can never spill over to a Beacon Tools
 * production or staging deployment.
 */
export function mobileRelayOrigins(explicitOrigin?: string): string[] {
  const explicit = normalizeOrigin(explicitOrigin);
  if (explicit) return [explicit];

  const extra = expoLocalFlightExtra();
  const envOrigin = process.env.EXPO_PUBLIC_LOCALFLIGHT_RELAY_ORIGIN;
  const envFailovers = process.env.EXPO_PUBLIC_LOCALFLIGHT_RELAY_FAILOVER_ORIGINS;
  const canonical = normalizeOrigin(envOrigin || extra?.relayOrigin) || SAFE_DEFAULT_RELAY_ORIGIN;
  const failovers = configuredFailovers(envFailovers || extra?.relayFailoverOrigins);
  return Array.from(new Set([canonical, ...failovers])).filter(Boolean);
}

export function primaryMobileRelayOrigin(explicitOrigin?: string): string {
  return mobileRelayOrigins(explicitOrigin)[0] || SAFE_DEFAULT_RELAY_ORIGIN;
}
