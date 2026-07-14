#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const workerSource = fs.readFileSync(path.join(root, "workers/beacontools.js"), "utf8");
const workerModule = await import(`data:text/javascript;base64,${Buffer.from(workerSource).toString("base64")}`);

const asset = (name, host = "github.com") => ({
  name,
  size: 12_345_678,
  browser_download_url: `https://${host}/tr3y4rch/local-flight/releases/download/v0.5.1/${name}`,
});

const filenames = [
  "LocalFlight-0.5.1-Setup.exe",
  "LocalFlight-0.5.1-macos.pkg",
  "LocalFlight-pi-source-0.5.1.zip",
];
const release = {
  tag_name: "v0.5.1",
  name: "Local Flight 0.5.1",
  html_url: "https://github.com/tr3y4rch/local-flight/releases/tag/v0.5.1",
  published_at: "2026-07-13T12:00:00Z",
  prerelease: false,
  draft: false,
  assets: filenames.flatMap((name) => [asset(name), asset(`${name}.sha256`)]),
};

const manifest = workerModule.buildReleaseManifest(release);
assert.equal(manifest.version, "0.5.1");
assert.equal(manifest.downloads.windows.filename, filenames[0]);
assert.equal(manifest.downloads.macos.filename, filenames[1]);
assert.equal(manifest.downloads.pi.filename, filenames[2]);
assert.equal(workerModule.selectLatestPackagedRelease([{ ...release, draft: true }, release]).version, "0.5.1");

const missingChecksum = workerModule.buildReleaseManifest({
  ...release,
  assets: release.assets.filter((item) => item.name !== `${filenames[0]}.sha256`),
});
assert.equal(missingChecksum.downloads.windows, null, "Packages without checksums must not become direct downloads.");

const foreignHost = workerModule.buildReleaseManifest({
  ...release,
  assets: release.assets.map((item) => item.name === filenames[1] ? asset(item.name, "example.com") : item),
});
assert.equal(foreignHost.downloads.macos, null, "Only this repository's GitHub download URLs are allowed.");

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

const page = fs.readFileSync(path.join(root, "site/local-flight/index.html"), "utf8");
const client = fs.readFileSync(path.join(root, "site/assets/downloads.js"), "utf8");
for (const platform of ["windows", "macos", "pi"]) {
  assert.match(page, new RegExp(`data-download-platform="${platform}"`));
}
assert.match(page, /data-release-status/);
assert.match(client, /\/api\/releases\/latest/);
assert.match(client, /SHA256 checksum/);

console.log("Beacon Tools download manifest contract passed.");
