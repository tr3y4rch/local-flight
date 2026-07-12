const GITHUB_REPOSITORY = "tr3y4rch/local-flight";
const GITHUB_RELEASES_API = `https://api.github.com/repos/${GITHUB_REPOSITORY}/releases?per_page=20`;
const GITHUB_RELEASES_PAGE = `https://github.com/${GITHUB_REPOSITORY}/releases`;
const RELEASE_CACHE_SECONDS = 1800;
const MINIMUM_PUBLIC_VERSION = "0.5.1";

const DOWNLOAD_FILENAMES = {
  windows: (version) => `LocalFlight-${version}-Setup.exe`,
  macos: (version) => `LocalFlight-${version}-macos.zip`,
  pi: (version) => `LocalFlight-pi-source-${version}.zip`,
};

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": status === 200
        ? `public, max-age=300, s-maxage=${RELEASE_CACHE_SECONDS}, stale-while-revalidate=86400`
        : "no-store",
      "X-Content-Type-Options": "nosniff",
    },
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
  if (!release || release.draft) return null;
  const version = normalizedVersion(release.tag_name);
  if (!version || !versionAtLeast(version, MINIMUM_PUBLIC_VERSION)) return null;
  const releaseUrl = safeGitHubUrl(
    release.html_url,
    `/${GITHUB_REPOSITORY}/releases/tag/`,
  );
  if (!releaseUrl) return null;

  return {
    version,
    tag: String(release.tag_name),
    name: String(release.name || `Local Flight ${version}`).slice(0, 120),
    published_at: String(release.published_at || ""),
    prerelease: Boolean(release.prerelease),
    release_url: releaseUrl,
    downloads: {
      windows: releaseDownload(release, version, "windows"),
      macos: releaseDownload(release, version, "macos"),
      pi: releaseDownload(release, version, "pi"),
    },
  };
}

export function selectLatestPackagedRelease(releases) {
  if (!Array.isArray(releases)) return null;
  for (const release of releases.slice(0, 20)) {
    const manifest = buildReleaseManifest(release);
    if (manifest && Object.values(manifest.downloads).some(Boolean)) return manifest;
  }
  return null;
}

async function latestReleaseResponse(request, context) {
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

export default {
  async fetch(request, env, context) {
    const url = new URL(request.url);

    if (url.pathname === "/local-flight/privacy" || url.pathname === "/local-flight/privacy/") {
      return Response.redirect(new URL("/privacy", url), 301);
    }

    if (url.pathname === "/api/releases/latest") {
      if (request.method !== "GET" && request.method !== "HEAD") {
        return jsonResponse({ ok: false, error: "method_not_allowed" }, 405);
      }
      const response = await latestReleaseResponse(request, context);
      return request.method === "HEAD"
        ? new Response(null, { status: response.status, headers: response.headers })
        : response;
    }

    if (request.method === "HEAD") {
      const getRequest = new Request(request, { method: "GET" });
      const response = await env.ASSETS.fetch(getRequest);
      return new Response(null, {
        status: response.status,
        statusText: response.statusText,
        headers: response.headers,
      });
    }

    return env.ASSETS.fetch(request);
  },
};
