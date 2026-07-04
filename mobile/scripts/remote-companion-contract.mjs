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

function assertOrder(source, first, second, label) {
  const firstIndex = source.indexOf(first);
  const secondIndex = source.indexOf(second);
  assert.notEqual(firstIndex, -1, `${label}: missing ${first}`);
  assert.notEqual(secondIndex, -1, `${label}: missing ${second}`);
  assert.ok(firstIndex < secondIndex, `${label}: expected ${first} before ${second}`);
}

assertOrder(
  clientSource,
  "response = await fetch(`${base}${path}`",
  'return remoteJson<T>("GET", path);',
  "GET LAN-first fallback"
);
assertOrder(
  clientSource,
  'method: "POST"',
  'return remoteJson<T>("POST", path, body);',
  "POST LAN-first fallback"
);
assertOrder(
  clientSource,
  'method: "PATCH"',
  'return remoteJson<T>("PATCH", path, body);',
  "PATCH LAN-first fallback"
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
  appShellSource,
  /const \[companionTransport, setCompanionTransport\] = useState<"lan" \| "remote">\("lan"\);/,
  "AppShell must track the last successful Companion transport."
);
assert.match(
  appShellSource,
  /isLive \? \(isStandalone \? "live" : companionTransport\) : "offline"/,
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
  /FORGET REMOTE/,
  "Connection settings should let the phone forget its Remote Companion grant."
);
assert.match(
  remoteSource,
  /\/v1\/remote-companion\/request/,
  "Remote Companion requests must go through the relay request endpoint."
);
assert.match(
  remoteSource,
  /throw new Error\(data\.detail \|\| `Remote Companion relay returned HTTP \$\{response\.status\}`\);/,
  "Relay HTTP failures should surface relay detail for friendly formatting."
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
  settingsSource,
  /revokedAt: typeof raw\.revokedAt === "string"/,
  "Stored Remote Companion grants must preserve revokedAt for filtering."
);

console.log("Remote Companion mobile contract checks passed.");
