import {
  AESEncryptionKey,
  AESSealedData,
  aesDecryptAsync,
  aesEncryptAsync
} from "expo-crypto/build/aes";
import { getCompanionIdentity } from "../device/identity";
import type { RemoteCompanionInvite } from "../domain/pairing";
import type { RemoteCompanionGrant } from "../storage/settings";

type RemoteEnvelope = {
  alg?: string;
  nonce: string;
  ciphertext: string;
  tag: string;
};

export type RemoteCompanionHttpResponse<T = unknown> = {
  ok: boolean;
  status: number;
  body: T;
};

export type RemoteCompanionProbeStatus =
  | "ok"
  | "cooldown"
  | "not_configured"
  | "relay_unreachable"
  | "host_offline"
  | "host_timeout"
  | "grant_revoked"
  | "rate_limited"
  | "crypto_failed"
  | "host_error"
  | "unknown";

export type RemoteCompanionProbeResult = {
  ok: boolean;
  status: RemoteCompanionProbeStatus;
  message: string;
  nextStep: string;
  attempts: number;
  retryAfterSeconds?: number;
  hostTime?: string | null;
  relayUrl?: string;
};

type RemoteProbeBody = {
  ok?: boolean;
  probe?: string;
  client_probe?: string;
  host_time?: string;
  app_version?: string;
  install_ref?: string;
  detail?: string;
};

export class RemoteCompanionRelayError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
    public readonly retryAfterSeconds?: number
  ) {
    super(message);
    this.name = "RemoteCompanionRelayError";
  }
}

export class RemoteCompanionCryptoError extends Error {
  constructor(message = "remote_crypto_failed") {
    super(message);
    this.name = "RemoteCompanionCryptoError";
  }
}

const REMOTE_PROBE_PATH = "/api/mobile/remote/probe";
const REMOTE_PROBE_RETRY_DELAY_MS = 2500;
const REMOTE_PROBE_COOLDOWN_MS = 10_000;
const REMOTE_REQUEST_TIMEOUT_MS = 32_000;
let lastProbeStartedAt = 0;

function normalizeServerUrl(input: string): string {
  const trimmed = input.trim();
  if (!trimmed) return "";
  const withScheme = /^https?:\/\//i.test(trimmed) ? trimmed : `http://${trimmed}`;
  return withScheme.replace(/\/+$/, "");
}

function requestId(): string {
  const rand = () => Math.floor(Math.random() * 0xffffffff).toString(16).padStart(8, "0");
  return `rcr_${Date.now().toString(16)}${rand()}${rand()}`;
}

const BASE64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

function bytesToBase64(value: Uint8Array): string {
  let result = "";
  for (let index = 0; index < value.length; index += 3) {
    const first = value[index] || 0;
    const second = value[index + 1] || 0;
    const third = value[index + 2] || 0;
    const combined = (first << 16) | (second << 8) | third;
    result += BASE64_ALPHABET[(combined >> 18) & 63];
    result += BASE64_ALPHABET[(combined >> 12) & 63];
    result += index + 1 < value.length ? BASE64_ALPHABET[(combined >> 6) & 63] : "=";
    result += index + 2 < value.length ? BASE64_ALPHABET[combined & 63] : "=";
  }
  return result;
}

function base64ToBytes(value: string): Uint8Array {
  const normalized = value
    .trim()
    .replace(/-/g, "+")
    .replace(/_/g, "/")
    .replace(/\s+/g, "")
    .replace(/=+$/, "");
  if (!normalized || normalized.length % 4 === 1) {
    throw new RemoteCompanionCryptoError("remote_crypto_invalid_base64");
  }
  const output: number[] = [];
  let buffer = 0;
  let bits = 0;
  for (const character of normalized) {
    const position = BASE64_ALPHABET.indexOf(character);
    if (position < 0) {
      throw new RemoteCompanionCryptoError("remote_crypto_invalid_base64");
    }
    buffer = (buffer << 6) | position;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      output.push((buffer >> bits) & 0xff);
    }
  }
  return new Uint8Array(output);
}

function encodeUtf8(value: string): Uint8Array {
  if (typeof TextEncoder !== "undefined") {
    return new TextEncoder().encode(value);
  }
  const bytes: number[] = [];
  for (const char of Array.from(value)) {
    const codePoint = char.codePointAt(0) || 0;
    if (codePoint <= 0x7f) {
      bytes.push(codePoint);
    } else if (codePoint <= 0x7ff) {
      bytes.push(0xc0 | (codePoint >> 6), 0x80 | (codePoint & 0x3f));
    } else if (codePoint <= 0xffff) {
      bytes.push(0xe0 | (codePoint >> 12), 0x80 | ((codePoint >> 6) & 0x3f), 0x80 | (codePoint & 0x3f));
    } else {
      bytes.push(
        0xf0 | (codePoint >> 18),
        0x80 | ((codePoint >> 12) & 0x3f),
        0x80 | ((codePoint >> 6) & 0x3f),
        0x80 | (codePoint & 0x3f)
      );
    }
  }
  return new Uint8Array(bytes);
}

function decodeUtf8(bytes: Uint8Array): string {
  if (typeof TextDecoder !== "undefined") {
    return new TextDecoder().decode(bytes);
  }
  let escaped = "";
  bytes.forEach((byte) => {
    escaped += `%${byte.toString(16).padStart(2, "0")}`;
  });
  return decodeURIComponent(escaped);
}

function aadBytes({
  installRef,
  grantRef,
  requestId: id,
  direction
}: {
  installRef: string;
  grantRef: string;
  requestId: string;
  direction: "request" | "response";
}): Uint8Array {
  const payload = JSON.stringify({
    direction,
    grant_ref: grantRef,
    install_ref: installRef,
    request_id: id
  });
  return encodeUtf8(payload);
}

async function importRemoteKey(remoteKey: string): Promise<AESEncryptionKey> {
  const keyBytes = base64ToBytes(remoteKey);
  if (keyBytes.length !== 32) {
    throw new RemoteCompanionCryptoError("remote_crypto_invalid_key");
  }
  return AESEncryptionKey.import(keyBytes) as Promise<AESEncryptionKey>;
}

async function encryptPayload(
  payload: Record<string, unknown>,
  grant: RemoteCompanionGrant,
  id: string
): Promise<RemoteEnvelope> {
  const key = await importRemoteKey(grant.remoteKey);
  const sealed = await aesEncryptAsync(
    encodeUtf8(JSON.stringify(payload)),
    key,
    {
      nonce: { length: 12 },
      tagLength: 16,
      additionalData: aadBytes({
        installRef: grant.installRef,
        grantRef: grant.grantRef,
        requestId: id,
        direction: "request"
      })
    }
  );
  const [nonce, ciphertext, tag] = await Promise.all([
    sealed.iv(),
    sealed.ciphertext(),
    sealed.tag()
  ]);
  return {
    alg: "A256GCM",
    nonce: bytesToBase64(nonce),
    ciphertext: bytesToBase64(ciphertext),
    tag: bytesToBase64(tag)
  };
}

async function decryptPayload<T>(
  envelope: RemoteEnvelope,
  grant: RemoteCompanionGrant,
  id: string
): Promise<T> {
  if ((envelope.alg || "A256GCM") !== "A256GCM") {
    throw new RemoteCompanionCryptoError("remote_crypto_unsupported_algorithm");
  }
  const key = await importRemoteKey(grant.remoteKey);
  const nonce = base64ToBytes(envelope.nonce);
  const ciphertext = base64ToBytes(envelope.ciphertext);
  const tag = base64ToBytes(envelope.tag);
  if (nonce.length !== 12 || tag.length !== 16) {
    throw new RemoteCompanionCryptoError("remote_crypto_invalid_envelope");
  }
  const ciphertextWithTag = new Uint8Array(ciphertext.length + tag.length);
  ciphertextWithTag.set(ciphertext, 0);
  ciphertextWithTag.set(tag, ciphertext.length);
  const sealed = AESSealedData.fromParts(nonce, ciphertextWithTag, tag.length);
  const bytes = await aesDecryptAsync(sealed, key, {
    additionalData: aadBytes({
      installRef: grant.installRef,
      grantRef: grant.grantRef,
      requestId: id,
      direction: "response"
    })
  });
  const text = decodeUtf8(bytes as Uint8Array);
  return JSON.parse(text) as T;
}

async function readJsonObject(response: Response): Promise<Record<string, unknown>> {
  try {
    const data = await response.json();
    return data && typeof data === "object" ? data as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function classifyProbeFailure(error: unknown): Omit<RemoteCompanionProbeResult, "attempts" | "relayUrl"> {
  const message = error instanceof Error ? error.message : String(error);
  if (/Remote Companion is not configured/i.test(message)) {
    return {
      ok: false,
      status: "not_configured",
      message: "Remote Companion is not paired on this phone yet.",
      nextStep: "Scan a Remote Companion QR from Local Flight Settings while this phone is on the same Wi-Fi."
    };
  }
  if (/remote_host_offline/i.test(message)) {
    return {
      ok: false,
      status: "host_offline",
      message: "The relay answered, but your Local Flight host is not connected to Remote Companion.",
      nextStep: "Open Local Flight on the host, keep it online, then try the test again."
    };
  }
  if (/remote_host_timeout/i.test(message)) {
    return {
      ok: false,
      status: "host_timeout",
      message: "The relay forwarded the signal, but the host did not answer in time.",
      nextStep: "Check whether the host is asleep, busy, or blocked from reaching the relay."
    };
  }
  if (/remote_grant_revoked|Remote Companion grant is not active/i.test(message)) {
    return {
      ok: false,
      status: "grant_revoked",
      message: "This phone's Remote Companion grant is no longer active.",
      nextStep: "Pair this phone again from the same Local Flight host."
    };
  }
  if (error instanceof RemoteCompanionRelayError && error.status === 429) {
    return {
      ok: false,
      status: "rate_limited",
      message: "Remote Companion asked this phone to slow down.",
      nextStep: `Wait ${error.retryAfterSeconds || 60} seconds before testing again.`,
      retryAfterSeconds: error.retryAfterSeconds || 60
    };
  }
  if (error instanceof RemoteCompanionCryptoError || /remote_crypto_failed|decrypt|authentication|A256GCM|AES|key/i.test(message)) {
    return {
      ok: false,
      status: "crypto_failed",
      message: "LAN is unaffected, but this phone's encrypted remote backup could not be verified.",
      nextStep: "While on the host's Wi-Fi, choose Create LAN + Remote QR and scan it once. Local Flight will replace the old remote access automatically."
    };
  }
  if (/Network request failed|Failed to fetch|NetworkError|fetch/i.test(message)) {
    return {
      ok: false,
      status: "relay_unreachable",
      message: "This phone could not reach the Remote Companion relay.",
      nextStep: "Check internet access, VPN/firewall settings, and try again in a moment."
    };
  }
  if (/Remote Companion HTTP|host did not return|HTTP 5\d\d|HTTP 4\d\d/i.test(message)) {
    return {
      ok: false,
      status: "host_error",
      message: "Remote Companion reached the route, but the host returned an error.",
      nextStep: "Open Local Flight on the host and send a report if this repeats."
    };
  }
  return {
    ok: false,
    status: "unknown",
    message: "Remote Companion could not complete the encrypted test signal.",
    nextStep: "Try once more later, then re-pair this phone if the same message returns."
  };
}

function shouldRetryProbe(status: RemoteCompanionProbeStatus): boolean {
  return status === "relay_unreachable" || status === "host_offline" || status === "host_timeout" || status === "unknown";
}

export async function completeRemoteCompanionPairing(
  serverUrl: string,
  invite: RemoteCompanionInvite
): Promise<RemoteCompanionGrant> {
  const base = normalizeServerUrl(serverUrl);
  if (!base) {
    throw new Error("Set a Local Flight server URL first.");
  }
  const identity = await getCompanionIdentity();
  const response = await fetch(`${base}/api/mobile/remote/pair`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-LocalFlight-Client-Type": "mobile-companion",
      "X-LocalFlight-Companion-Id": identity.companionId,
      "X-LocalFlight-Client-Name": identity.clientName,
      "X-LocalFlight-Client-Platform": identity.mobileOs,
      "X-LocalFlight-Device-Type": identity.deviceType,
      "X-LocalFlight-App-Version": identity.appVersion
    },
    body: JSON.stringify({
      companion_id: identity.companionId,
      client_name: identity.clientName,
      app_version: identity.appVersion,
      mobile_os: identity.mobileOs,
      device_type: identity.deviceType,
      invite_id: invite.inviteId,
      install_ref: invite.installRef,
      relay_url: invite.relayUrl,
      remote_key: invite.remoteKey
    })
  });
  const data = await readJsonObject(response);
  if (!response.ok) {
    throw new Error(String(data.detail || `HTTP ${response.status} for /api/mobile/remote/pair`));
  }
  const grant = data.remote_companion || {};
  if (
    !grant ||
    typeof grant !== "object" ||
    !("grant_ref" in grant) ||
    !(("relay_url" in grant && grant.relay_url) || invite.relayUrl) ||
    !(("install_ref" in grant && grant.install_ref) || invite.installRef) ||
    !(("remote_key" in grant && grant.remote_key) || invite.remoteKey)
  ) {
    throw new Error("Remote Companion grant response was incomplete.");
  }
  const remoteGrant = grant as Record<string, unknown>;
  return {
    grantRef: String(remoteGrant.grant_ref || ""),
    relayUrl: String(remoteGrant.relay_url || invite.relayUrl).replace(/\/+$/, ""),
    installRef: String(remoteGrant.install_ref || invite.installRef),
    remoteKey: String(remoteGrant.remote_key || invite.remoteKey),
    createdAt: typeof remoteGrant.created_at === "string" ? remoteGrant.created_at : null,
    lastSeenRemoteAt: typeof remoteGrant.last_seen_remote_at === "string" ? remoteGrant.last_seen_remote_at : null,
    revokedAt: typeof remoteGrant.revoked_at === "string" ? remoteGrant.revoked_at : null
  };
}

export async function sendRemoteCompanionRequest<T>(
  grant: RemoteCompanionGrant,
  method: "GET" | "POST" | "PATCH",
  path: string,
  body?: Record<string, unknown>
): Promise<RemoteCompanionHttpResponse<T>> {
  const id = requestId();
  const envelope = await encryptPayload({ method, path, body: body || null }, grant, id);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REMOTE_REQUEST_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(`${grant.relayUrl}/v1/remote-companion/request`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        install_ref: grant.installRef,
        grant_ref: grant.grantRef,
        request_id: id,
        envelope
      }),
      signal: controller.signal
    });
  } catch (error) {
    if (controller.signal.aborted) {
      throw new RemoteCompanionRelayError("remote_relay_timeout", 504);
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
  const data = await readJsonObject(response);
  if (!response.ok) {
    const retryAfter = Number.parseInt(response.headers.get("Retry-After") || "", 10);
    throw new RemoteCompanionRelayError(
      String(data.detail || `Remote Companion relay returned HTTP ${response.status}`),
      response.status,
      Number.isFinite(retryAfter) ? retryAfter : undefined
    );
  }
  if (!data.envelope) {
    throw new RemoteCompanionRelayError(
      String(data.error || "Remote Companion host did not return an encrypted response."),
      response.status
    );
  }
  try {
    return await decryptPayload<RemoteCompanionHttpResponse<T>>(data.envelope as RemoteEnvelope, grant, id);
  } catch {
    throw new RemoteCompanionCryptoError("remote_crypto_failed");
  }
}

export async function testRemoteCompanionProbe(
  grant: RemoteCompanionGrant | null | undefined,
  options: { bypassCooldown?: boolean } = {}
): Promise<RemoteCompanionProbeResult> {
  if (!grant || grant.revokedAt) {
    return {
      ok: false,
      status: "not_configured",
      message: "Remote Companion is not paired on this phone yet.",
      nextStep: "Scan a Remote Companion QR from Local Flight Settings while this phone is on the same Wi-Fi.",
      attempts: 0
    };
  }

  const now = Date.now();
  if (!options.bypassCooldown && now - lastProbeStartedAt < REMOTE_PROBE_COOLDOWN_MS) {
    return {
      ok: false,
      status: "cooldown",
      message: "Remote Companion test was just run.",
      nextStep: "Wait a few seconds before testing again so the relay is not spammed.",
      attempts: 0,
      relayUrl: grant.relayUrl
    };
  }
  lastProbeStartedAt = now;

  let attempts = 0;
  let lastFailure: Omit<RemoteCompanionProbeResult, "attempts" | "relayUrl"> | null = null;
  const probeRef = `rcp_${Date.now().toString(16)}_${Math.floor(Math.random() * 0xffffffff).toString(16)}`;
  const path = `${REMOTE_PROBE_PATH}?client_probe=${encodeURIComponent(probeRef)}`;

  for (let attempt = 1; attempt <= 2; attempt += 1) {
    attempts = attempt;
    try {
      const result = await sendRemoteCompanionRequest<RemoteProbeBody>(grant, "GET", path);
      if (!result.ok) {
        const detail = result.body && typeof result.body === "object"
          ? String((result.body as RemoteProbeBody).detail || "")
          : "";
        throw new RemoteCompanionRelayError(detail || `Remote Companion HTTP ${result.status}`, result.status);
      }
      if (result.body?.probe !== "remote_companion" || result.body?.client_probe !== probeRef) {
        return {
          ok: false,
          status: "host_error",
          message: "Remote Companion answered, but the probe response did not match this phone's test signal.",
          nextStep: "Pair this phone again from the intended host before relying on remote access.",
          attempts,
          relayUrl: grant.relayUrl
        };
      }
      return {
        ok: true,
        status: "ok",
        message: attempts > 1
          ? "Encrypted Remote Companion test passed after one retry."
          : "Encrypted Remote Companion test passed.",
        nextStep: "Remote fallback is ready when LAN is unavailable.",
        attempts,
        hostTime: result.body.host_time || null,
        relayUrl: grant.relayUrl
      };
    } catch (error) {
      lastFailure = classifyProbeFailure(error);
      if (attempt === 1 && shouldRetryProbe(lastFailure.status)) {
        await delay(REMOTE_PROBE_RETRY_DELAY_MS);
        continue;
      }
      break;
    }
  }

  return {
    ...(lastFailure || {
      ok: false,
      status: "unknown" as const,
      message: "Remote Companion could not complete the encrypted test signal.",
      nextStep: "Try once more later, then re-pair this phone if the same message returns."
    }),
    attempts,
    relayUrl: grant.relayUrl
  };
}
