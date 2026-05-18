import { normalizeServerUrl } from "../api/client";

export type PairingLinkResult = {
  serverUrl: string;
  source: string;
  expectedServerFingerprint?: string;
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
    source: parsed.searchParams.get("source") || "qr",
    expectedServerFingerprint: normalizedPairingFingerprint(parsed.searchParams.get("server_fingerprint") || "")
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
      return "Pairing URL points at localhost. Use the LAN IP shown in Local Flight Settings; localflight.local is only safe when one Local Flight server is on the LAN.";
    }
    if (!["http:", "https:"].includes(parsed.protocol)) {
      return "Pairing URL must use http:// or https:// for the Local Flight server.";
    }
  } catch {
    return "Pairing QR contained an invalid Local Flight server URL.";
  }
  return null;
}

export function normalizedPairingFingerprint(value: string | null | undefined): string {
  return String(value || "").trim().toLowerCase();
}

export function pairingFingerprintProblem(expected: string | null | undefined, actual: string | null | undefined): string | null {
  const expectedNormalized = normalizedPairingFingerprint(expected);
  if (!expectedNormalized) {
    return null;
  }
  const actualNormalized = normalizedPairingFingerprint(actual);
  if (!actualNormalized) {
    return "Pairing QR is tied to a Local Flight server, but the server did not report its fingerprint. Update the desktop/Pi app or enter the LAN IP manually.";
  }
  if (expectedNormalized !== actualNormalized) {
    return `Pairing QR belongs to server ${expectedNormalized}, but ${actualNormalized} answered. Use the QR/IP from the Local Flight server you want to control.`;
  }
  return null;
}
