import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const mobileRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const readSource = (...parts) => readFileSync(path.join(mobileRoot, ...parts), "utf8");

const clientSource = readSource("src", "api", "client.ts");
const appShellSource = readSource("src", "app", "AppShell.tsx");
const screensSource = readSource("src", "screens", "AppScreens.tsx");
const remoteSource = readSource("src", "api", "remoteCompanion.ts");
const formattingSource = readSource("src", "domain", "formatting.ts");
const settingsSource = readSource("src", "storage", "settings.ts");

assert.match(
  clientSource,
  /response = await fetchWithTimeout\([\s\S]*?COMPANION_LAN_TIMEOUT_MS,[\s\S]*?return remoteJson<T>\("GET", path\);/,
  "GET requests must attempt bounded LAN access before remote fallback."
);
assert.match(
  clientSource,
  /method: "POST"[\s\S]*?COMPANION_LAN_TIMEOUT_MS,[\s\S]*?return remoteJson<T>\("POST", path, body\);/,
  "POST requests must attempt bounded LAN access before remote fallback."
);
assert.match(
  clientSource,
  /method: "PATCH"[\s\S]*?COMPANION_LAN_TIMEOUT_MS,[\s\S]*?return remoteJson<T>\("PATCH", path, body\);/,
  "PATCH requests must attempt bounded LAN access before remote fallback."
);
assert.match(
  clientSource,
  /configuredRemoteCompanionGrant = grant && !grant\.revokedAt \? grant : null;/,
  "Revoked Remote Companion grants must not configure fallback transport."
);
assert.match(
  clientSource,
  /export function getLastCompanionTransport\(\): CompanionTransportState/,
  "Mobile UI needs a stable LAN/Remote transport status signal."
);
assert.match(
  clientSource,
  /COMPANION_LAN_TIMEOUT_MS = 4_500/,
  "LAN-first requests need a short bound so unreachable private addresses can fall back remotely."
);
assert.match(
  clientSource,
  /COMPANION_LAN_RETRY_DELAY_MS = 30_000/,
  "An unreachable LAN path should be cooled down instead of probed for every remote request."
);
assert.match(
  clientSource,
  /if \(shouldSkipLan\(base\)\) \{\s+return remoteJson<T>\("GET", path\);/,
  "Remote refreshes should reuse the short LAN failure circuit."
);
assert.match(
  appShellSource,
  /const \[companionTransport, setCompanionTransport\] = useState<"lan" \| "remote">\("lan"\);/,
  "AppShell must track the last successful Companion transport."
);
assert.match(
  appShellSource,
  /isLive\s*\? \(isStandalone \? "live" : companionTransport\)[\s\S]*?: "offline"/,
  "Companion mode should surface LAN or Remote instead of a generic live state."
);
assert.match(
  screensSource,
  /export type ConnectionState = "lan" \| "remote" \| "live" \| "retrying" \| "offline";/,
  "Connection state must include LAN, Remote, and Offline labels."
);
assert.match(
  screensSource,
  /<InfoCard label="PATH" value=\{pathLabel\} tone=\{pathTone\} \/>/,
  "Connection settings should expose the active LAN/Remote/Offline path."
);
assert.match(
  screensSource,
  /REMOVE REMOTE/,
  "Connection settings should let the phone forget its Remote Companion grant."
);
assert.match(
  screensSource,
  /TEST REMOTE/,
  "Connection settings should expose a user-triggered encrypted Remote Companion probe."
);
assert.match(
  screensSource,
  /testRemoteCompanionProbe/,
  "Connection settings should use the typed probe instead of generic fetch errors."
);
assert.match(
  remoteSource,
  /\/v1\/remote-companion\/request/,
  "Remote Companion requests must go through the relay request endpoint."
);
assert.match(
  remoteSource,
  /sealed\.ciphertext\(\)/,
  "Remote Companion must read native ciphertext bytes before encoding the envelope."
);
assert.match(
  remoteSource,
  /ciphertext: bytesToBase64\(ciphertext\)/,
  "Remote Companion must encode ciphertext bytes as real Base64."
);
assert.doesNotMatch(
  remoteSource,
  /ciphertext\(\{\s*encoding:\s*["']base64["']/,
  "Expo native ignores the old ciphertext encoding option and returns raw bytes."
);
assert.match(
  remoteSource,
  /AESSealedData\.fromParts\(nonce, ciphertextWithTag, tag\.length\)/,
  "Remote replies should avoid native tag-overload ambiguity by joining ciphertext and tag bytes."
);
assert.match(
  remoteSource,
  /options: \{ bypassCooldown\?: boolean \} = \{\}/,
  "A newly created grant needs one immediate verification even after a recent manual probe."
);
assert.match(
  appShellSource,
  /testRemoteCompanionProbe\(remoteGrant, \{ bypassCooldown: true \}\)/,
  "The app must verify encrypted fallback before saving a newly scanned remote grant."
);
assert.match(
  remoteSource,
  /REMOTE_REQUEST_TIMEOUT_MS = 32_000/,
  "Relay requests need a client-side bound beyond the relay host timeout."
);
assert.match(
  remoteSource,
  /signal: controller\.signal/,
  "Relay requests must be abortable when the network never settles."
);
assert.match(
  appShellSource,
  /finally \{\s+if \(!background\) \{[\s\S]*?setRefreshingByTarget\([\s\S]*?anyForegroundRefresh[\s\S]*?setActivity\(null\);/,
  "Every foreground refresh outcome must release its target-specific pull-to-refresh indicator."
);
assert.match(
  appShellSource,
  /try \{\s+if \(includeDashboard\) \{[\s\S]*?isCurrentDashboardRequest\(\)[\s\S]*?return;[\s\S]*?finally \{\s+if \(!background\)/,
  "Dashboard failure must return through the refresh cleanup block."
);
assert.match(
  appShellSource,
  /foregroundRefreshGenerationByTargetRef\.current\.get\(target\)[\s\S]*?isCurrentForegroundRefresh/,
  "Superseded foreground failures must not overwrite the active request state for that feature."
);
assert.match(
  appShellSource,
  /dashboardRequestGenerationRef[\s\S]*?isCurrentDashboardRequest/,
  "Dashboard connectivity writes must be guarded across foreground and background refreshes."
);
assert.match(
  appShellSource,
  /targetRequestGenerationByTargetRef[\s\S]*?isCurrentTargetRequest/,
  "A superseded dashboard request must not launch stale work for the same feature."
);
assert.match(
  appShellSource,
  /if \(!dataReady\) return;[\s\S]*?effectiveIntervalMs = connected \? syncIntervalMs :/,
  "Fallback polling must keep retrying connectivity while the UI is offline."
);
assert.match(
  appShellSource,
  /socket\.onclose = \(\) => \{[\s\S]*?retryDelayMs[\s\S]*?setTimeout\(connectSocket, retryDelayMs\)/,
  "Companion WebSockets must reconnect with bounded exponential backoff after a dropped channel."
);
assert.match(
  remoteSource,
  /class RemoteCompanionRelayError extends Error/,
  "Relay failures need typed errors for friendly user-facing probe results."
);
assert.match(
  remoteSource,
  /class RemoteCompanionCryptoError extends Error/,
  "Crypto failures need typed errors so the app can recommend re-pairing."
);
assert.match(
  remoteSource,
  /export async function testRemoteCompanionProbe/,
  "Mobile must expose an encrypted Remote Companion probe for real-world networking smoke tests."
);
assert.match(
  remoteSource,
  /REMOTE_PROBE_COOLDOWN_MS = 10_000/,
  "Remote Companion probe must debounce repeat taps instead of spamming the relay."
);
assert.match(
  remoteSource,
  /REMOTE_PROBE_RETRY_DELAY_MS = 2500/,
  "Remote Companion probe should retry transient failures gently."
);
assert.match(
  remoteSource,
  /status: "crypto_failed"/,
  "Remote Companion probe should display key/decryption mismatches as re-pair guidance."
);
assert.match(
  remoteSource,
  /status: "rate_limited"/,
  "Remote Companion probe should display relay rate limits without retrying."
);
assert.match(
  remoteSource,
  /const REMOTE_PROBE_PATH = "\/api\/mobile\/remote\/probe"/,
  "Remote Companion probe must use a harmless encrypted host route."
);
assert.match(
  remoteSource,
  /\$\{REMOTE_PROBE_PATH\}\?client_probe=/,
  "Remote Companion probe should echo a harmless encrypted client probe reference."
);
assert.doesNotMatch(
  remoteSource,
  /provider_key/i,
  "Remote Companion probe code must not send provider credentials."
);
assert.match(
  remoteSource,
  /String\(data\.detail \|\| `Remote Companion relay returned HTTP \$\{response\.status\}`\)/,
  "Relay HTTP failures should surface relay detail for friendly formatting."
);
assert.match(
  formattingSource,
  /remote_relay_timeout/,
  "Relay safety timeouts need a user-readable message."
);
assert.match(
  formattingSource,
  /remote_host_offline/,
  "Remote host offline errors need a user-readable message."
);
assert.match(
  formattingSource,
  /remote_host_timeout/,
  "Remote host timeout errors need a user-readable message."
);
assert.match(
  formattingSource,
  /remote_grant_revoked\|Remote Companion grant is not active/,
  "Revoked grant errors need a user-readable message."
);
assert.match(
  formattingSource,
  /remote_crypto_failed/,
  "Crypto/key mismatch errors need a user-readable message."
);
assert.match(
  formattingSource,
  /rate limit reached/,
  "Relay rate-limit errors need a user-readable message."
);
assert.match(
  settingsSource,
  /revokedAt: typeof raw\.revokedAt === "string"/,
  "Stored Remote Companion grants must preserve revokedAt for filtering."
);

console.log("Remote Companion mobile contract checks passed.");
