const GITHUB_REPOSITORY = "BeaconTools/local-flight";
const GITHUB_RELEASES_API = `https://api.github.com/repos/${GITHUB_REPOSITORY}/releases?per_page=20`;
const GITHUB_RELEASES_PAGE = `https://github.com/${GITHUB_REPOSITORY}/releases`;
const RELEASE_CACHE_SECONDS = 1800;
const MINIMUM_PUBLIC_VERSION = "0.7.1";

const STATUS_CACHE_SECONDS = 30;
// The monitoring service checks every five minutes, so re-asking more often than
// that buys nothing and only spends the free tier's 10 requests per minute.
const MONITOR_CACHE_SECONDS = 300;
const STATUS_PROBE_TIMEOUT_MS = 5000;
// Uptime ratios over four periods are a far heavier query than a health ping, so
// the monitoring call gets its own budget rather than sharing the relay's.
const MONITOR_PROBE_TIMEOUT_MS = 10000;
const UPTIME_MONITORS_API = "https://api.uptimerobot.com/v2/getMonitors";
// Periods requested from UptimeRobot, in the order `uptimeRatios` unpacks them:
// 24 hours, 7 days, 30 days, 90 days.
const UPTIME_RATIO_PERIODS = "1-7-30-90";

// Public service rows, joined to UptimeRobot by friendly name rather than numeric
// monitor id so the mapping stays readable and survives a monitor being recreated.
// A monitor with no entry here is simply not published, so operator-only checks can
// exist upstream without appearing on the public page.
const STATUS_SERVICES = [
  { key: "website", monitor: "website", label: "Website" },
  { key: "relay_api", monitor: "relay-api", label: "Relay API" },
  { key: "licensing", monitor: "licensing", label: "Licensing and activation" },
  { key: "mobile", monitor: "mobile-gateway", label: "Mobile gateway" },
  { key: "downloads", monitor: "downloads", label: "Downloads" },
];

const DOWNLOAD_FILENAMES = {
  windows: (version) => `LocalFlight-${version}-Setup.exe`,
  macos_arm64: (version) => `LocalFlight-${version}-macos-arm64.pkg`,
  macos_x86_64: (version) => `LocalFlight-${version}-macos-x86_64.pkg`,
  linux_appimage_x86_64: (version) => `LocalFlight-${version}-linux-x86_64.AppImage`,
  linux_appimage_aarch64: (version) => `LocalFlight-${version}-linux-aarch64.AppImage`,
  linux_deb_desktop_amd64: (version) => `localflight-desktop_${version}_amd64.deb`,
  linux_deb_desktop_arm64: (version) => `localflight-desktop_${version}_arm64.deb`,
  linux_deb_server_amd64: (version) => `localflight-server_${version}_amd64.deb`,
  linux_deb_server_arm64: (version) => `localflight-server_${version}_arm64.deb`,
  pi: (version) => `LocalFlight-pi-source-${version}.zip`,
};

const RELEASE_CACHE_CONTROL = `public, max-age=300, s-maxage=${RELEASE_CACHE_SECONDS}, stale-while-revalidate=86400`;
// Deliberately no stale-while-revalidate. Serving a stale "all clear" during an
// incident is the one failure this page exists to avoid, and it stays short-lived in
// the browser as well as at the edge so a reader can refresh their way to the truth.
const STATUS_CACHE_CONTROL = `public, max-age=${STATUS_CACHE_SECONDS}, s-maxage=${STATUS_CACHE_SECONDS}`;

function jsonResponse(payload, status = 200, cacheControl = RELEASE_CACHE_CONTROL) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": status === 200 ? cacheControl : "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

function publicAssetResponse(response) {
  const contentType = response.headers.get("Content-Type") || "";
  if (!contentType.toLowerCase().startsWith("text/html")) return response;
  const headers = new Headers(response.headers);
  // Cloudflare Web Analytics can inject a browser beacon into otherwise static
  // HTML at the edge. This source-controlled boundary prevents that response
  // transformation and keeps the public site free of behavioral analytics.
  headers.set("Cache-Control", "public, max-age=0, must-revalidate, no-transform");
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function normalizedVersion(tagName) {
  const value = String(tagName || "").trim().replace(/^v/i, "");
  return /^[0-9][0-9A-Za-z.-]{0,39}$/.test(value) ? value : "";
}

function versionAtLeast(version, minimum) {
  const parse = (value) => {
    const match = String(value).match(/^(\d+)\.(\d+)\.(\d+)/);
    return match ? match.slice(1).map(Number) : null;
  };
  const current = parse(version);
  const floor = parse(minimum);
  if (!current || !floor) return false;
  for (let index = 0; index < 3; index += 1) {
    if (current[index] !== floor[index]) return current[index] > floor[index];
  }
  return true;
}

function safeGitHubUrl(rawUrl, expectedPrefix) {
  try {
    const url = new URL(String(rawUrl || ""));
    if (url.protocol !== "https:" || url.hostname !== "github.com") return "";
    return url.pathname.startsWith(expectedPrefix) ? url.toString() : "";
  } catch {
    return "";
  }
}

function releaseDownload(release, version, platform) {
  const filename = DOWNLOAD_FILENAMES[platform](version);
  const checksumFilename = `${filename}.sha256`;
  const expectedPrefix = `/${GITHUB_REPOSITORY}/releases/download/`;
  const assets = Array.isArray(release?.assets) ? release.assets : [];
  const artifact = assets.find((asset) => asset?.name === filename);
  const checksum = assets.find((asset) => asset?.name === checksumFilename);
  const artifactUrl = safeGitHubUrl(artifact?.browser_download_url, expectedPrefix);
  const checksumUrl = safeGitHubUrl(checksum?.browser_download_url, expectedPrefix);
  if (!artifactUrl || !checksumUrl) return null;
  return {
    filename,
    url: artifactUrl,
    size: Number.isFinite(artifact?.size) && artifact.size >= 0 ? artifact.size : 0,
    checksum_filename: checksumFilename,
    checksum_url: checksumUrl,
  };
}

export function buildReleaseManifest(release) {
  if (!release || release.draft || release.prerelease) return null;
  const version = normalizedVersion(release.tag_name);
  if (!version || !versionAtLeast(version, MINIMUM_PUBLIC_VERSION)) return null;
  const releaseUrl = safeGitHubUrl(
    release.html_url,
    `/${GITHUB_REPOSITORY}/releases/tag/`,
  );
  if (!releaseUrl) return null;

  const downloads = Object.fromEntries(
    Object.keys(DOWNLOAD_FILENAMES).map((platform) => [
      platform,
      releaseDownload(release, version, platform),
    ]),
  );

  // Keep the original public key for older download clients. Starting with
  // 0.5.2 it points to the Apple silicon package; new clients should use the
  // architecture-specific keys above.
  downloads.macos = downloads.macos_arm64;

  return {
    version,
    tag: String(release.tag_name),
    name: String(release.name || `Local Flight ${version}`).slice(0, 120),
    published_at: String(release.published_at || ""),
    prerelease: false,
    release_url: releaseUrl,
    downloads,
  };
}

export function selectLatestPackagedRelease(releases) {
  if (!Array.isArray(releases)) return null;
  for (const release of releases.slice(0, 20)) {
    const manifest = buildReleaseManifest(release);
    const complete = manifest && Object.keys(DOWNLOAD_FILENAMES).every(
      (platform) => Boolean(manifest.downloads[platform]),
    );
    if (complete) return manifest;
  }
  return null;
}

async function latestReleaseResponse(request, _env, context) {
  const cache = caches.default;
  const cacheUrl = new URL("/api/releases/latest", request.url);
  cacheUrl.searchParams.set("manifest", MINIMUM_PUBLIC_VERSION);
  const cacheKey = new Request(cacheUrl, { method: "GET" });
  const cached = await cache.match(cacheKey);
  if (cached) return cached;

  try {
    const upstream = await fetch(GITHUB_RELEASES_API, {
      headers: {
        Accept: "application/vnd.github+json",
        "User-Agent": "Beacon-Tools-Release-Manifest",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      cf: { cacheEverything: true, cacheTtl: RELEASE_CACHE_SECONDS },
    });
    if (!upstream.ok) throw new Error(`GitHub releases returned ${upstream.status}`);
    const manifest = selectLatestPackagedRelease(await upstream.json());
    const response = jsonResponse({
      ok: true,
      source: "github_releases",
      repository: GITHUB_REPOSITORY,
      releases_url: GITHUB_RELEASES_PAGE,
      release: manifest,
    });
    context.waitUntil(cache.put(cacheKey, response.clone()));
    return response;
  } catch {
    return jsonResponse({
      ok: false,
      source: "github_releases",
      releases_url: GITHUB_RELEASES_PAGE,
      error: "release_manifest_unavailable",
    }, 503);
  }
}

function readiness(value) {
  return value ? "operational" : "degraded";
}

export function relayComponentRows(health) {
  const access = health?.access;
  if (!access) return [];
  return [
    { key: "catalog", label: "Product catalog", state: readiness(access.catalog_ready) },
    // The relay already computes `license_core_ready` as `config_ready && keyrings_ready`,
    // so it is the single signal worth publishing for licence issuing.
    { key: "licensing", label: "License issuing", state: readiness(access.license_core_ready) },
    // Deliberately `providers.stripe` rather than `sales_ready`: the relay folds the
    // RELAY_ACCESS_SALES_ENABLED business toggle into `sales_ready`, so pausing sales
    // on purpose would otherwise be published as a fault. Stripe readiness is the
    // infrastructure signal; a deliberate pause is reported through `relayNotices`.
    { key: "purchases", label: "Purchases and billing", state: readiness(access.providers?.stripe) },
    { key: "email", label: "License email delivery", state: readiness(access.smtp_ready) },
    { key: "backups", label: "Backups", state: readiness(access.backup_ready) },
  ];
}

export function relayNotices(health) {
  const access = health?.access;
  if (!access) return [];
  const notices = [];
  if (access.schema_version !== access.expected_schema_version) {
    notices.push({ key: "schema", tone: "degraded", text: "A database migration is still being applied." });
  }
  if (access.providers?.stripe && access.sales_ready === false) {
    notices.push({ key: "sales", tone: "info", text: "New purchases are paused. Existing licences are unaffected." });
  }
  return notices;
}

// UptimeRobot monitor status: 0 paused, 1 not checked yet, 2 up, 8 seems down, 9 down.
function monitorState(status) {
  if (status === 2) return "operational";
  if (status === 8) return "degraded";
  if (status === 9) return "outage";
  return "unknown";
}

function uptimeRatios(raw) {
  const periods = ["day", "week", "month", "quarter"];
  const parts = String(raw ?? "").split("-");
  const ratios = {};
  periods.forEach((period, index) => {
    const value = Number.parseFloat(parts[index]);
    if (Number.isFinite(value)) ratios[period] = Math.round(value * 1000) / 1000;
  });
  return ratios;
}

export function normalizeUptimeMonitors(payload) {
  const allowed = new Map(STATUS_SERVICES.map((service) => [service.monitor, service.key]));
  const monitors = Array.isArray(payload?.monitors) ? payload.monitors : [];
  const normalized = {};
  for (const monitor of monitors) {
    const key = allowed.get(String(monitor?.friendly_name || "").trim());
    if (!key) continue;
    normalized[key] = {
      state: monitorState(Number(monitor?.status)),
      uptime: uptimeRatios(monitor?.custom_uptime_ratio),
    };
  }
  return normalized;
}

// Signals derivable from this request alone, which stay correct even when the
// monitoring API is unreachable. `null` means "no live signal, defer to the monitor".
function liveServiceState(key, health) {
  // Serving this response is itself proof that the website is reachable.
  if (key === "website") return "operational";
  if (key === "relay_api") return health?.ok === true ? "operational" : "outage";
  if (key === "licensing") {
    if (health?.ok !== true) return "outage";
    return readiness(health.access?.catalog_ready);
  }
  return null;
}

// A live probe and an external monitor answer different questions: ours says the
// relay responds to this Worker, theirs says it responds from outside our hosting.
// When they disagree, one of them is wrong and we do not know which, so the honest
// answer is degraded rather than quietly preferring our own view.
export function reconcileState(liveState, observedState) {
  if (!liveState) return observedState || "unknown";
  if (!observedState || observedState === "unknown") return liveState;
  return liveState === observedState ? liveState : "degraded";
}

function overallState(states) {
  const known = states.filter((state) => state !== "unknown");
  if (!known.length) return "unknown";
  if (known.includes("outage")) return "outage";
  if (known.includes("degraded")) return "degraded";
  return "operational";
}

export function buildStatusPayload({ health, monitors, now }) {
  const live = health?.ok === true;
  const history = monitors && Object.keys(monitors).length > 0 ? monitors : null;
  const disagreements = [];
  const services = STATUS_SERVICES.map((service) => {
    const observed = history?.[service.key] || null;
    const liveState = liveServiceState(service.key, health);
    const observedState = observed?.state || null;
    if (liveState && observedState && observedState !== "unknown" && liveState !== observedState) {
      disagreements.push({ service, liveState, observedState });
    }
    return {
      key: service.key,
      label: service.label,
      state: reconcileState(liveState, observedState),
      checks: { live: liveState, monitor: observedState },
      uptime: observed?.uptime || null,
    };
  });
  const components = live ? relayComponentRows(health) : [];
  const notices = live ? relayNotices(health) : [];
  for (const { service, liveState, observedState } of disagreements) {
    notices.push({
      key: `disagreement_${service.key}`,
      tone: "degraded",
      text: observedState === "operational"
        ? `${service.label} answers external monitoring but not our own checks. Treat it as unconfirmed until the two agree.`
        : `${service.label} answers our own checks, but external monitoring cannot reach it from outside. Treat it as unconfirmed until the two agree.`,
    });
  }

  return {
    ok: true,
    generated_at: (now instanceof Date ? now : new Date()).toISOString(),
    overall: overallState([
      ...services.map((service) => service.state),
      ...components.map((component) => component.state),
      ...notices.filter((notice) => notice.tone === "degraded").map(() => "degraded"),
    ]),
    services,
    components,
    notices,
    build: live
      ? {
          version: String(health.version || ""),
          revision: String(health.revision || "").slice(0, 12),
          environment: String(health.access?.deployment_environment || ""),
        }
      : null,
    sources: { live, history: Boolean(history) },
  };
}

function relayOrigin(request, env) {
  const configured = String(env?.RELAY_ORIGIN || "").trim();
  if (configured) return configured.replace(/\/+$/, "");
  // Mirrors resolveDeployment() in site/deployment.mjs so the Worker and the site
  // always agree about which relay belongs to which site origin.
  return new URL(request.url).hostname === "staging.beacontools.cc"
    ? "https://relay-staging.beacontools.cc"
    : "https://relay.beacontools.cc";
}

async function relayHealth(origin) {
  const response = await fetch(`${origin}/health`, {
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(STATUS_PROBE_TIMEOUT_MS),
  });
  if (!response.ok) throw new Error(`Relay health returned ${response.status}`);
  return await response.json();
}

async function uptimeMonitors(apiKey) {
  const response = await fetch(UPTIME_MONITORS_API, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      Accept: "application/json",
    },
    body: new URLSearchParams({
      api_key: apiKey,
      format: "json",
      custom_uptime_ratios: UPTIME_RATIO_PERIODS,
    }),
    signal: AbortSignal.timeout(MONITOR_PROBE_TIMEOUT_MS),
  });
  if (!response.ok) throw new Error(`UptimeRobot returned ${response.status}`);
  const payload = await response.json();
  if (payload?.stat !== "ok") {
    throw new Error(`UptimeRobot rejected the request: ${JSON.stringify(payload?.error ?? payload).slice(0, 200)}`);
  }
  return payload;
}

export function freshMonitorRecord(record, now) {
  if (!record || typeof record.fetched_at !== "number") return null;
  return now - record.fetched_at < MONITOR_CACHE_SECONDS * 1000 ? record.monitors : null;
}

async function cachedUptimeMonitors(apiKey, request, context) {
  const cache = caches.default;
  // Not a routed path; it exists only as a cache key beside the status response.
  const cacheKey = new Request(new URL("/api/status/monitors", request.url), { method: "GET" });
  let previous = null;
  const cached = await cache.match(cacheKey);
  if (cached) {
    const record = await cached.json().catch(() => null);
    const fresh = freshMonitorRecord(record, Date.now());
    if (fresh) return fresh;
    previous = record?.monitors ?? null;
  }

  try {
    const monitors = normalizeUptimeMonitors(await uptimeMonitors(apiKey));
    const record = JSON.stringify({ fetched_at: Date.now(), monitors });
    context.waitUntil(cache.put(cacheKey, new Response(record, {
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        // Retained well past the point it stops counting as fresh, so it survives
        // as a fallback when the monitoring API is slow or refuses a request.
        "Cache-Control": `public, max-age=${MONITOR_CACHE_SECONDS * 6}`,
      },
    })));
    return monitors;
  } catch (error) {
    console.warn("status: uptime monitors failed:", String(error));
    // Last known history beats dropping the column entirely.
    return previous;
  }
}

async function statusResponse(request, env, context) {
  const cache = caches.default;
  const cacheKey = new Request(new URL("/api/status", request.url), { method: "GET" });
  const cached = await cache.match(cacheKey);
  if (cached) return cached;

  const apiKey = String(env?.UPTIMEROBOT_API_KEY || "").trim();
  // Settled rather than all: either source failing must still produce a page, and a
  // dead relay is itself the most important thing this endpoint has to report.
  const [health, monitors] = await Promise.allSettled([
    relayHealth(relayOrigin(request, env)),
    // Without a key the page still renders live component health and simply omits the
    // uptime history, which keeps `wrangler dev` usable with no secrets configured.
    apiKey ? cachedUptimeMonitors(apiKey, request, context) : Promise.resolve(null),
  ]);
  // Logged, never returned: both sources are allowed to fail quietly for readers, but
  // silent failure with no trace is untriageable. Observability is on for this Worker.
  if (health.status === "rejected") console.warn("status: relay health failed:", String(health.reason));
  if (monitors.status === "rejected") console.warn("status: uptime monitors failed:", String(monitors.reason));

  const response = jsonResponse(
    buildStatusPayload({
      health: health.status === "fulfilled" ? health.value : null,
      monitors: monitors.status === "fulfilled" ? monitors.value : null,
      now: new Date(),
    }),
    200,
    STATUS_CACHE_CONTROL,
  );
  context.waitUntil(cache.put(cacheKey, response.clone()));
  return response;
}

async function jsonRouteResponse(handler, request, env, context) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return jsonResponse({ ok: false, error: "method_not_allowed" }, 405);
  }
  const response = await handler(request, env, context);
  return request.method === "HEAD"
    ? new Response(null, { status: response.status, headers: response.headers })
    : response;
}

export default {
  async fetch(request, env, context) {
    const url = new URL(request.url);

    if (url.pathname === "/local-flight/privacy" || url.pathname === "/local-flight/privacy/") {
      return Response.redirect(new URL("/privacy", url), 301);
    }

    if (url.pathname === "/api/releases/latest") {
      return jsonRouteResponse(latestReleaseResponse, request, env, context);
    }

    if (url.pathname === "/api/status") {
      return jsonRouteResponse(statusResponse, request, env, context);
    }

    if (request.method === "HEAD") {
      const getRequest = new Request(request, { method: "GET" });
      const response = publicAssetResponse(await env.ASSETS.fetch(getRequest));
      return new Response(null, {
        status: response.status,
        statusText: response.statusText,
        headers: response.headers,
      });
    }

    return publicAssetResponse(await env.ASSETS.fetch(request));
  },
};
