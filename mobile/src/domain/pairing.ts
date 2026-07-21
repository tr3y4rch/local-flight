import { normalizeServerUrl } from "../api/client";

export type PairingLinkResult = {
  serverUrl: string;
  source: string;
  expectedServerFingerprint?: string;
  remoteCompanionInvite?: RemoteCompanionInvite;
};

export type RemoteCompanionInvite = {
  relayUrl: string;
  installRef: string;
  inviteId: string;
  remoteKey: string;
  expiresAt: string;
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

  const remoteCompanionInvite = parseRemoteCompanionInvite(parsed);
  if (parsed.searchParams.get("remote") === "1" && !remoteCompanionInvite) {
    return null;
  }

  return {
    serverUrl: normalized,
    source: parsed.searchParams.get("source") || "qr",
    expectedServerFingerprint: normalizedPairingFingerprint(parsed.searchParams.get("server_fingerprint") || ""),
    remoteCompanionInvite
  };
}

function parseRemoteCompanionInvite(parsed: URL): RemoteCompanionInvite | undefined {
  if (parsed.searchParams.get("remote") !== "1") {
    return undefined;
  }
  const relayUrl = normalizeServerUrl(parsed.searchParams.get("relay") || "");
  const installRef = (parsed.searchParams.get("install_ref") || "").trim();
  const inviteId = (parsed.searchParams.get("invite_id") || "").trim();
  const remoteKey = (parsed.searchParams.get("remote_key") || "").trim();
  const expiresAt = (parsed.searchParams.get("expires_at") || "").trim();
  if (!relayUrl || !installRef || !inviteId || !remoteKey || !expiresAt) {
    return undefined;
  }
  if (remoteKey.length < 40 || remoteKey.length > 80) {
    return undefined;
  }
  return { relayUrl, installRef, inviteId, remoteKey, expiresAt };
}

export function pairingServerUrlProblem(serverUrl: string): string | null {
  const normalized = normalizeServerUrl(serverUrl);
  if (!normalized) {
    return "Pairing QR did not include a Local Flight host address.";
  }
  try {
    const parsed = new URL(normalized);
    const host = parsed.hostname.replace(/^\[|\]$/g, "").toLowerCase();
    if (["localhost", "127.0.0.1", "::1", "0.0.0.0"].includes(host)) {
      return "Pairing address points at localhost. Use the LAN IP shown in Local Flight Settings; localflight.local is only safe when one Local Flight host is on the same Wi-Fi.";
    }
    if (!["http:", "https:"].includes(parsed.protocol)) {
      return "The Local Flight host address must use http:// or https://.";
    }
  } catch {
    return "Pairing QR contained an invalid Local Flight host address.";
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
    return "Pairing QR is tied to a Local Flight host, but the host did not report its fingerprint. Update Local Flight on the host or enter its LAN IP manually.";
  }
  if (expectedNormalized !== actualNormalized) {
    return `Pairing QR belongs to host ${expectedNormalized}, but ${actualNormalized} answered. Use the QR or IP address from the Local Flight host you want to connect.`;
  }
  return null;
}
