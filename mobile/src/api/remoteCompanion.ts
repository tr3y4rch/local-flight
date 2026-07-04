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

function base64UrlToBase64(value: string): string {
  const clean = value.replace(/-/g, "+").replace(/_/g, "/");
  return clean + "=".repeat((4 - (clean.length % 4)) % 4);
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
  return AESEncryptionKey.import(base64UrlToBase64(remoteKey), "base64") as Promise<AESEncryptionKey>;
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
    sealed.iv("base64"),
    sealed.ciphertext({ encoding: "base64" }),
    sealed.tag("base64")
  ]);
  return {
    alg: "A256GCM",
    nonce: String(nonce),
    ciphertext: String(ciphertext),
    tag: String(tag)
  };
}

async function decryptPayload<T>(
  envelope: RemoteEnvelope,
  grant: RemoteCompanionGrant,
  id: string
): Promise<T> {
  const key = await importRemoteKey(grant.remoteKey);
  const sealed = AESSealedData.fromParts(envelope.nonce, envelope.ciphertext, envelope.tag);
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
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || `HTTP ${response.status} for /api/mobile/remote/pair`);
  }
  const grant = data.remote_companion || {};
  if (!grant.grant_ref || !(grant.relay_url || invite.relayUrl) || !(grant.install_ref || invite.installRef) || !(grant.remote_key || invite.remoteKey)) {
    throw new Error("Remote Companion grant response was incomplete.");
  }
  return {
    grantRef: String(grant.grant_ref || ""),
    relayUrl: String(grant.relay_url || invite.relayUrl).replace(/\/+$/, ""),
    installRef: String(grant.install_ref || invite.installRef),
    remoteKey: String(grant.remote_key || invite.remoteKey),
    createdAt: grant.created_at || null,
    lastSeenRemoteAt: grant.last_seen_remote_at || null,
    revokedAt: grant.revoked_at || null
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
  const response = await fetch(`${grant.relayUrl}/v1/remote-companion/request`, {
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
    })
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || `Remote Companion relay returned HTTP ${response.status}`);
  }
  if (!data.envelope) {
    throw new Error(data.error || "Remote Companion host did not return an encrypted response.");
  }
  return decryptPayload<RemoteCompanionHttpResponse<T>>(data.envelope, grant, id);
}
