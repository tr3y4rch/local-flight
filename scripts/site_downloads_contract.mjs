#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const workerSource = fs.readFileSync(path.join(root, "workers/beacontools.js"), "utf8");
const workerModule = await import(`data:text/javascript;base64,${Buffer.from(workerSource).toString("base64")}`);

const version = "0.6.0";
const asset = (name, host = "github.com") => ({
  name,
  size: 12_345_678,
  browser_download_url: `https://${host}/tr3y4rch/local-flight/releases/download/v${version}/${name}`,
});

const filenames = {
  windows: `LocalFlight-${version}-Setup.exe`,
  macos_arm64: `LocalFlight-${version}-macos-arm64.pkg`,
  macos_x86_64: `LocalFlight-${version}-macos-x86_64.pkg`,
  linux_appimage_x86_64: `LocalFlight-${version}-linux-x86_64.AppImage`,
  linux_appimage_aarch64: `LocalFlight-${version}-linux-aarch64.AppImage`,
  linux_deb_desktop_amd64: `localflight-desktop_${version}_amd64.deb`,
  linux_deb_desktop_arm64: `localflight-desktop_${version}_arm64.deb`,
  linux_deb_server_amd64: `localflight-server_${version}_amd64.deb`,
  linux_deb_server_arm64: `localflight-server_${version}_arm64.deb`,
  pi: `LocalFlight-pi-source-${version}.zip`,
};
const release = {
  tag_name: `v${version}`,
  name: `Local Flight ${version}`,
  html_url: `https://github.com/tr3y4rch/local-flight/releases/tag/v${version}`,
  published_at: "2026-07-18T12:00:00Z",
  prerelease: false,
  draft: false,
  assets: Object.values(filenames).flatMap((name) => [asset(name), asset(`${name}.sha256`)]),
};

const manifest = workerModule.buildReleaseManifest(release);
assert.equal(manifest.version, version);
for (const [platform, filename] of Object.entries(filenames)) {
  assert.equal(manifest.downloads[platform].filename, filename);
  const missingChecksum = workerModule.buildReleaseManifest({
    ...release,
    assets: release.assets.filter((item) => item.name !== `${filename}.sha256`),
  });
  assert.equal(
    missingChecksum.downloads[platform],
    null,
    `${platform} must not become a direct download without its checksum.`,
  );
}
assert.strictEqual(
  manifest.downloads.macos,
  manifest.downloads.macos_arm64,
  "The deprecated macos key must remain an Apple silicon alias.",
);
assert.equal(workerModule.selectLatestPackagedRelease([{ ...release, draft: true }, release]).version, version);
assert.equal(workerModule.buildReleaseManifest({ ...release, prerelease: true }), null);

const partialRelease = {
  ...release,
  assets: release.assets.filter((item) => item.name !== `${filenames.linux_deb_server_arm64}.sha256`),
};
assert.equal(
  workerModule.selectLatestPackagedRelease([partialRelease]),
  null,
  "A release must not be promoted until all ten package/checksum pairs exist.",
);
assert.equal(
  workerModule.selectLatestPackagedRelease([partialRelease, release]).version,
  version,
  "An incomplete release must be skipped in favor of the next complete release.",
);

const foreignHost = workerModule.buildReleaseManifest({
  ...release,
  assets: release.assets.map((item) => item.name === filenames.macos_arm64 ? asset(item.name, "example.com") : item),
});
assert.equal(foreignHost.downloads.macos_arm64, null, "Only this repository's GitHub download URLs are allowed.");
assert.equal(foreignHost.downloads.macos, null, "The legacy alias must preserve checksum and host gating.");

const staleAsset = workerModule.buildReleaseManifest({
  ...release,
  assets: [asset("LocalFlight-0.2.7-Setup.exe"), asset("LocalFlight-0.2.7-Setup.exe.sha256")],
});
assert.equal(staleAsset.downloads.windows, null, "Asset versions must match the release tag.");

assert.equal(workerModule.buildReleaseManifest({
  ...release,
  tag_name: "v0.2.7",
  html_url: "https://github.com/tr3y4rch/local-flight/releases/tag/v0.2.7",
}), null, "Packages older than the current public release line must not be promoted.");

const builtPagePath = path.join(root, "site/dist/local-flight/index.html");
assert.ok(
  fs.existsSync(builtPagePath),
  "Build the Astro site with `npm --prefix site run build` before running the site contract.",
);
const page = fs.readFileSync(builtPagePath, "utf8");
const client = fs.readFileSync(path.join(root, "site/src/scripts/downloads.ts"), "utf8");
for (const platform of Object.keys(filenames)) {
  assert.match(page, new RegExp(`data-download-platform="${platform}"`));
}
assert.equal((page.match(/data-download-platform="/g) || []).length, Object.keys(filenames).length);
assert.match(page, /data-release-status/);
assert.match(page, /Verify download \(SHA-256\)/);
assert.match(page, /GitHub Releases remains the file host and source of record/);
assert.match(client, /\/api\/releases\/latest/);
assert.match(client, /Verify download \(SHA-256\)/);

console.log("Beacon Tools download manifest contract passed.");
