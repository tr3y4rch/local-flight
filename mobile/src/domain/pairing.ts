import { normalizeServerUrl } from "../api/client";

export type PairingLinkResult = {
  serverUrl: string;
  source: string;
};

export function parsePairingLink(rawUrl: string): PairingLinkResult | null {
  let parsed: URL;
  try {
    parsed = new URL(rawUrl);
  } catch {
    return null;
  }

  if (["http:", "https:"].includes(parsed.protocol)) {
    const normalized = normalizeServerUrl(rawUrl);
    if (!normalized) return null;
    return {
      serverUrl: normalized,
      source: "qr"
    };
  }

  const route = parsed.hostname || parsed.pathname.replace(/^\/+/, "");
  if (parsed.protocol !== "localflight:" || route !== "pair") {
    return null;
  }

  const server = parsed.searchParams.get("server") || "";
  const normalized = normalizeServerUrl(server);
  if (!normalized) {
    return null;
  }

  return {
    serverUrl: normalized,
    source: parsed.searchParams.get("source") || "qr"
  };
}

export function pairingServerUrlProblem(serverUrl: string): string | null {
  const normalized = normalizeServerUrl(serverUrl);
  if (!normalized) {
    return "Pairing QR did not include a Local Flight server URL.";
  }
  try {
    const parsed = new URL(normalized);
    const host = parsed.hostname.replace(/^\[|\]$/g, "").toLowerCase();
    if (["localhost", "127.0.0.1", "::1", "0.0.0.0"].includes(host)) {
      return "Pairing URL points at localhost. Use the Pi/desktop LAN IP or localflight.local so this phone can reach the server.";
    }
    if (!["http:", "https:"].includes(parsed.protocol)) {
      return "Pairing URL must use http:// or https:// for the Local Flight server.";
    }
  } catch {
    return "Pairing QR contained an invalid Local Flight server URL.";
  }
  return null;
}
