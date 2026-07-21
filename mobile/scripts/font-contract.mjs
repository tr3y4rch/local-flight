import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const mobileRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(mobileRoot, "..");
const canonicalRoot = path.join(repoRoot, "src", "localflight", "ui", "static", "fonts");

const fontFiles = [
  "DMSans.ttf",
  "Audiowide-Regular.ttf",
  "SpaceMono-Regular.ttf",
  "SpaceMono-Bold.ttf"
];
const licenseFiles = ["OFL-DMSans.txt", "OFL-Audiowide.txt", "OFL-SpaceMono.txt"];
const androidNames = new Map([
  ["DMSans.ttf", "dm_sans.ttf"],
  ["Audiowide-Regular.ttf", "audiowide_regular.ttf"],
  ["SpaceMono-Regular.ttf", "space_mono_regular.ttf"],
  ["SpaceMono-Bold.ttf", "space_mono_bold.ttf"]
]);

function digest(file) {
  return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

function requireMatch(source, copy, label) {
  if (!fs.existsSync(copy)) throw new Error(`${label} is missing: ${path.relative(repoRoot, copy)}`);
  if (digest(source) !== digest(copy)) {
    throw new Error(`${label} does not match the Qt/LAN master: ${path.relative(repoRoot, copy)}`);
  }
}

for (const file of fontFiles) {
  const source = path.join(canonicalRoot, file);
  if (!fs.existsSync(source)) throw new Error(`canonical font is missing: ${file}`);
  requireMatch(source, path.join(mobileRoot, "assets", "fonts", file), "React Native font");
  requireMatch(source, path.join(mobileRoot, "native", "ios-widget", "Fonts", file), "iOS extension font");
  requireMatch(
    source,
    path.join(mobileRoot, "native", "android-widget", "res", "font", androidNames.get(file)),
    "Android widget font"
  );
}

for (const file of licenseFiles) {
  const source = path.join(canonicalRoot, file);
  requireMatch(source, path.join(mobileRoot, "assets", "fonts", file), "React Native font licence");
  requireMatch(source, path.join(mobileRoot, "native", "ios-widget", "Fonts", file), "iOS extension font licence");
  requireMatch(
    source,
    path.join(mobileRoot, "native", "android-widget", "assets", "licenses", file),
    "Android widget font licence"
  );
}

const manifest = JSON.parse(fs.readFileSync(path.join(repoRoot, "assets", "brand-manifest.json"), "utf8"));
const roles = manifest.font_contract?.roles;
if (!roles) throw new Error("brand manifest is missing font_contract.roles");
for (const role of Object.values(roles)) {
  const source = path.join(canonicalRoot, role.file);
  if (!fs.existsSync(source) || digest(source) !== role.sha256) {
    throw new Error(`brand manifest font hash is stale for ${role.file}`);
  }
  if (!fs.existsSync(path.join(canonicalRoot, role.license))) {
    throw new Error(`brand manifest font licence is missing for ${role.file}`);
  }
}

const appSource = fs.readFileSync(path.join(mobileRoot, "App.tsx"), "utf8");
for (const token of ["UI_FONT_FAMILY", "BRAND_FONT_FAMILY", "BOARD_FONT_FAMILY", "BOARD_BOLD_FONT_FAMILY"]) {
  if (!appSource.includes(token)) throw new Error(`App font bootstrap is missing ${token}`);
}

console.log("Font contract OK: Qt/LAN masters match React Native, iOS, Android, licences, and manifest hashes.");
