import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import { redactSensitiveReportText } from "../src/utils/reportRedaction.ts";

const relaySecrets = [
  "LFRA-0000-0000-0000-0000-0000-0000-000",
  "LFRA000000000000000000000000000",
  "lfr_device-credential_fixture",
  "lfrs_result-secret_fixture",
  "lfrclaim_delivery-claim_fixture",
  "lfrws_websocket-ticket_fixture",
  "lfrm_move-token_fixture",
  "lfrml_management-link_fixture",
  "lfrhs_management-session_fixture",
  "lfrag_activation-grant_fixture"
];

for (const secret of relaySecrets) {
  const redacted = redactSensitiveReportText(`safe-before ${secret} safe-after`);
  assert.equal(redacted.includes(secret), false, `relay secret was not redacted: ${secret}`);
  assert.match(redacted, /safe-before/);
  assert.match(redacted, /safe-after/);
}

const legacyFixture = [
  "AVIATIONSTACK_API_KEY=provider-secret",
  "lin_api_linear-secret",
  "lfm_legacy-activation-secret",
  "access_key=query-secret",
  "Authorization: Bearer bearer-secret",
  "192.168.1.44"
].join(" ");
const legacyRedacted = redactSensitiveReportText(legacyFixture);
for (const raw of [
  "provider-secret",
  "lin_api_linear-secret",
  "lfm_legacy-activation-secret",
  "access_key=query-secret",
  "bearer-secret",
  "192.168.1.44"
]) {
  assert.equal(legacyRedacted.includes(raw), false, `existing redaction regressed: ${raw}`);
}

const clientSource = await readFile(new URL("../src/api/client.ts", import.meta.url), "utf8");
const standaloneSource = await readFile(new URL("../src/api/standalone.ts", import.meta.url), "utf8");

for (const field of ["input.title", "input.description", "input.client_context"]) {
  assert.match(clientSource, new RegExp(`redactSensitiveReportText\\(${field.replace(".", "\\.")}\\)`));
  assert.match(standaloneSource, new RegExp(`redactSensitiveReportText\\(${field.replace(".", "\\.")}\\)`));
}
for (const field of ["input.message", "input.traceback", "input.context"]) {
  assert.match(clientSource, new RegExp(`redactSensitiveReportText\\(${field.replace(".", "\\.")}`));
  assert.match(standaloneSource, new RegExp(`redactSensitiveReportText\\(${field.replace(".", "\\.")}`));
}

console.log("report redaction contract: ok");
