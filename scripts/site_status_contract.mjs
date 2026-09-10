#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const workerSource = fs.readFileSync(path.join(root, "workers/beacontools.js"), "utf8");
const workerModule = await import(`data:text/javascript;base64,${Buffer.from(workerSource).toString("base64")}`);

const healthyRelay = {
  ok: true,
  service: "beacon-relay",
  version: "0.7.1",
  revision: "55c33d5900efb407fde449e1a62502b94d9b39c0",
  access: {
    mode: "migration",
    deployment_environment: "production",
    schema_version: 9,
    expected_schema_version: 9,
    catalog_ready: true,
    keyrings_ready: true,
    license_core_ready: true,
    smtp_ready: true,
    backup_ready: true,
    sales_ready: true,
    providers: { stripe: true, apple_subscription: false, google_play: false },
  },
};

const withAccess = (patch) => ({ ...healthyRelay, access: { ...healthyRelay.access, ...patch } });
const stateOf = (rows, key) => rows.find((row) => row.key === key)?.state;
const build = (health, monitors = null) => workerModule.buildStatusPayload({
  health,
  monitors,
  now: new Date("2026-07-20T12:34:00Z"),
});

// --- Component mapping -----------------------------------------------------

const healthyRows = workerModule.relayComponentRows(healthyRelay);
assert.deepEqual(
  healthyRows.map((row) => row.key),
  ["catalog", "licensing", "purchases", "email", "backups"],
);
assert.ok(healthyRows.every((row) => row.state === "operational"));
assert.deepEqual(workerModule.relayComponentRows(null), []);
assert.deepEqual(workerModule.relayComponentRows({ ok: true }), []);

assert.equal(
  stateOf(workerModule.relayComponentRows(withAccess({ smtp_ready: false })), "email"),
  "degraded",
  "A real email-delivery fault must be published.",
);
assert.equal(
  stateOf(workerModule.relayComponentRows(withAccess({ backup_ready: false })), "backups"),
  "degraded",
);

// The relay folds the RELAY_ACCESS_SALES_ENABLED business toggle into `sales_ready`
// (relay/main.py), so publishing that field as health would report a deliberate sales
// pause as an outage. Purchases must track Stripe readiness instead.
const salesPaused = build(withAccess({ sales_ready: false }));
assert.equal(
  stateOf(salesPaused.components, "purchases"),
  "operational",
  "Deliberately pausing sales must not be published as a fault.",
);
assert.equal(salesPaused.overall, "operational");
assert.deepEqual(salesPaused.notices.map((notice) => notice.key), ["sales"]);
assert.equal(salesPaused.notices[0].tone, "info");

const stripeDown = build(withAccess({ providers: { stripe: false } }));
assert.equal(stateOf(stripeDown.components, "purchases"), "degraded");
assert.equal(stripeDown.overall, "degraded");

// `access.mode` is a rollout state, not a health state; it must never affect status.
assert.equal(build(withAccess({ mode: "migration" })).overall, "operational");
assert.equal(build(withAccess({ mode: "enforced" })).overall, "operational");

const migrating = build(withAccess({ schema_version: 8 }));
assert.equal(migrating.overall, "degraded", "A pending migration must surface as degraded.");
assert.deepEqual(migrating.notices.map((notice) => notice.key), ["schema"]);

// --- Monitor normalisation -------------------------------------------------

const monitors = workerModule.normalizeUptimeMonitors({
  stat: "ok",
  monitors: [
    { friendly_name: "website", status: 2, custom_uptime_ratio: "100.000-99.985-99.950-99.900" },
    { friendly_name: "relay-api", status: 9, custom_uptime_ratio: "50.000-90.000-95.000-97.500" },
    { friendly_name: "downloads", status: 8, custom_uptime_ratio: "98.200-99.100-99.400-99.600" },
    { friendly_name: "mobile-gateway", status: 2, custom_uptime_ratio: "100.000-99.900-99.800-99.700" },
    { friendly_name: "operator-only-check", status: 2, custom_uptime_ratio: "100.000-100.000-100.000-100.000" },
  ],
});
assert.deepEqual(Object.keys(monitors).sort(), ["downloads", "mobile", "relay_api", "website"]);
assert.equal(
  monitors.operator_only_check,
  undefined,
  "A monitor with no STATUS_SERVICES entry stays internal and is never published.",
);
assert.equal(monitors.mobile.state, "operational");
assert.deepEqual(monitors.mobile.uptime, { day: 100, week: 99.9, month: 99.8, quarter: 99.7 });
assert.deepEqual(monitors.website.uptime, { day: 100, week: 99.985, month: 99.95, quarter: 99.9 });
assert.equal(monitors.relay_api.state, "outage");
assert.equal(monitors.downloads.state, "degraded");
assert.deepEqual(workerModule.normalizeUptimeMonitors({}), {});
assert.deepEqual(workerModule.normalizeUptimeMonitors(null), {});
assert.deepEqual(
  workerModule.normalizeUptimeMonitors({ monitors: [{ friendly_name: "website", status: 1 }] }).website,
  { state: "unknown", uptime: {} },
  "A monitor awaiting its first check must read as unknown, not as an outage.",
);

// --- Payload assembly ------------------------------------------------------

const healthy = build(healthyRelay, monitors);
assert.equal(healthy.ok, true);
assert.equal(healthy.generated_at, "2026-07-20T12:34:00.000Z");
assert.deepEqual(healthy.sources, { live: true, history: true });
assert.deepEqual(healthy.build, { version: "0.7.1", revision: "55c33d5900ef", environment: "production" });
assert.equal(healthy.build.revision.length, 12, "The published revision stays a short prefix.");
// The live probe outranks the monitor: it is fresher than a five-minute poll.
assert.equal(healthy.services.find((service) => service.key === "relay_api").state, "operational");
assert.equal(healthy.services.find((service) => service.key === "downloads").state, "degraded");
assert.equal(healthy.overall, "degraded");

const noHistory = build(healthyRelay, null);
assert.deepEqual(noHistory.sources, { live: true, history: false });
for (const key of ["downloads", "mobile"]) {
  assert.equal(
    noHistory.services.find((service) => service.key === key).state,
    "unknown",
    `Without a monitor, ${key} has no signal and must not be claimed operational.`,
  );
}
assert.equal(
  noHistory.overall,
  "operational",
  "An unknown service must not drag an otherwise healthy board into degraded.",
);
assert.ok(noHistory.services.every((service) => service.uptime === null));

const relayDown = build(null, null);
assert.equal(relayDown.overall, "outage");
assert.equal(relayDown.build, null);
assert.deepEqual(relayDown.components, [], "No component claims are made when the relay is unreachable.");
assert.deepEqual(relayDown.sources, { live: false, history: false });
const downStates = Object.fromEntries(relayDown.services.map((service) => [service.key, service.state]));
assert.equal(downStates.relay_api, "outage");
assert.equal(downStates.licensing, "outage");
assert.equal(
  downStates.website,
  "operational",
  "Serving this response proves the website is reachable.",
);

// --- Route behaviour -------------------------------------------------------

function stubCaches() {
  globalThis.caches = { default: { match: async () => undefined, put: async () => {} } };
}

async function statusRequest({ env = {}, relay, uptime, method = "GET" } = {}) {
  stubCaches();
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    calls.push({ url, body: init?.body ? String(init.body) : "" });
    if (url.includes("/health")) return relay();
    return uptime ? uptime() : new Response("{}", { status: 500 });
  };
  try {
    const response = await workerModule.default.fetch(
      new Request("https://beacontools.cc/api/status", { method }),
      env,
      { waitUntil() {} },
    );
    return { response, calls };
  } finally {
    globalThis.fetch = originalFetch;
  }
}

const okRelay = () => new Response(JSON.stringify(healthyRelay), { headers: { "Content-Type": "application/json" } });

const live = await statusRequest({ relay: okRelay });
assert.equal(live.response.status, 200);
assert.match(live.response.headers.get("Cache-Control"), /max-age=60/);
assert.match(live.response.headers.get("Cache-Control"), /s-maxage=60/);
assert.equal(live.response.headers.get("X-Content-Type-Options"), "nosniff");
const livePayload = await live.response.json();
assert.equal(livePayload.overall, "operational");
assert.deepEqual(livePayload.sources, { live: true, history: false });
assert.equal(
  live.calls.length,
  1,
  "With no API key configured, the monitoring service must not be contacted at all.",
);
assert.match(live.calls[0].url, /^https:\/\/relay\.beacontools\.cc\/health$/);

const staged = await statusRequest({
  env: { RELAY_ORIGIN: "https://relay-staging.beacontools.cc/" },
  relay: okRelay,
});
assert.match(
  staged.calls[0].url,
  /^https:\/\/relay-staging\.beacontools\.cc\/health$/,
  "A configured relay origin must be honoured, with any trailing slash trimmed.",
);

const keyed = await statusRequest({
  env: { UPTIMEROBOT_API_KEY: "ur-read-only-secret" },
  relay: okRelay,
  uptime: () => new Response(JSON.stringify({
    stat: "ok",
    monitors: [{ friendly_name: "downloads", status: 2, custom_uptime_ratio: "100.000-100.000-100.000-100.000" }],
  }), { headers: { "Content-Type": "application/json" } }),
});
const keyedPayload = await keyed.response.json();
assert.deepEqual(keyedPayload.sources, { live: true, history: true });
assert.equal(keyedPayload.services.find((service) => service.key === "downloads").state, "operational");
assert.ok(
  !JSON.stringify(keyedPayload).includes("ur-read-only-secret"),
  "The monitoring credential must never reach the response body.",
);

// A failing monitoring API must degrade to live-only rather than failing the page.
const monitorOutage = await statusRequest({
  env: { UPTIMEROBOT_API_KEY: "ur-read-only-secret" },
  relay: okRelay,
  uptime: () => new Response("rate limited", { status: 429 }),
});
assert.equal(monitorOutage.response.status, 200);
assert.deepEqual((await monitorOutage.response.json()).sources, { live: true, history: false });

// A rejected key returns HTTP 200 with stat "fail"; that must not be read as history.
const rejectedKey = await statusRequest({
  env: { UPTIMEROBOT_API_KEY: "wrong" },
  relay: okRelay,
  uptime: () => new Response(JSON.stringify({ stat: "fail", error: { message: "api_key not found" } }), {
    headers: { "Content-Type": "application/json" },
  }),
});
assert.deepEqual((await rejectedKey.response.json()).sources, { live: true, history: false });

// An unreachable relay must still produce a readable page, not a 5xx.
const relayUnreachable = await statusRequest({ relay: () => { throw new Error("connection refused"); } });
assert.equal(relayUnreachable.response.status, 200);
const unreachablePayload = await relayUnreachable.response.json();
assert.equal(unreachablePayload.overall, "outage");
assert.equal(unreachablePayload.sources.live, false);

const relayError = await statusRequest({ relay: () => new Response("bad gateway", { status: 502 }) });
assert.equal((await relayError.response.json()).overall, "outage");

const rejected = await statusRequest({ relay: okRelay, method: "POST" });
assert.equal(rejected.response.status, 405);
assert.equal(rejected.response.headers.get("Cache-Control"), "no-store");

// The pre-existing release route must be untouched by the shared dispatch.
stubCaches();
const releaseMethodGuard = await workerModule.default.fetch(
  new Request("https://beacontools.cc/api/releases/latest", { method: "DELETE" }),
  {},
  { waitUntil() {} },
);
assert.equal(releaseMethodGuard.status, 405);

// --- Page and script contract ---------------------------------------------

const builtPage = path.join(root, "site/dist/status/index.html");
assert.ok(
  fs.existsSync(builtPage),
  "Build the Astro site with `npm --prefix site run build` before running the status contract.",
);
const page = fs.readFileSync(builtPage, "utf8");
for (const key of ["website", "relay_api", "licensing", "mobile", "downloads"]) {
  assert.match(page, new RegExp(`data-status-service="${key}"`));
}
for (const key of ["catalog", "licensing", "purchases", "email", "backups"]) {
  assert.match(page, new RegExp(`data-status-component="${key}"`));
}
assert.match(page, /data-status-overall/);
assert.match(page, /data-status-fallback/);

const client = fs.readFileSync(path.join(root, "site/src/scripts/status.ts"), "utf8");
assert.match(client, /\/api\/status/);
assert.doesNotMatch(
  client,
  /uptimerobot|api\.uptimerobot\.com/i,
  "The monitoring vendor must stay behind the Worker and out of the browser.",
);
assert.doesNotMatch(
  client,
  /relay(-staging)?\.beacontools\.cc/,
  "The status page must reach the relay through the site origin only.",
);
assert.doesNotMatch(page, /uptimerobot/i);

console.log("Beacon Tools service status contract passed.");
