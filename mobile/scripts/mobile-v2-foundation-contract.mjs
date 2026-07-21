#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const mobileRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (relativePath) => fs.readFileSync(path.join(mobileRoot, relativePath), "utf8");

const tokens = read("src/theme/tokens.ts");
const runtime = read("src/theme/runtime.tsx");
const settings = read("src/storage/settings.ts");
const layout = read("src/utils/layout.ts");
const copy = read("src/content/en.ts");
const glossary = read("src/content/glossary.ts");
const appConfig = JSON.parse(read("app.json"));
const iosWidget = read("native/ios-widget/SmallWidgetViewV2.swift");
const androidWidget = read("native/android-widget/LocalFlightWidgetProvider.kt");
const androidWidgetStrings = read("native/android-widget/res/values/localflight_widget_strings.xml");
const standaloneApi = read("src/api/standalone.ts");
const appShell = read("src/app/AppShell.tsx");
const widgetRefresh = read("src/background/widgetRefresh.ts");
const userFacingCopy = [
  copy,
  read("src/domain/formatting.ts"),
  read("src/api/remoteCompanion.ts"),
  read("src/screens/AppScreens.tsx"),
  read("src/v2/MoreScreenV2.tsx")
].join("\n");

function requireText(source, value, label) {
  assert.ok(source.includes(value), `${label}: missing ${value}`);
}

const semanticAnchors = {
  "light cloud": "#f5f1e8",
  "light surface": "#fffdf8",
  "light ink": "#132638",
  "light muted": "#536575",
  "light sky": "#2f6f9f",
  "light sea": "#1f6f61",
  "dark midnight": "#08141d",
  "dark surface": "#102330",
  "dark warm white": "#f5f0e8",
  "dark muted": "#a4b3be",
  "dark sky": "#74b5de",
  "dark sea": "#59c1a5"
};
for (const [label, color] of Object.entries(semanticAnchors)) {
  requireText(tokens, color, `semantic theme ${label}`);
}

function relativeLuminance(hex) {
  const channels = [1, 3, 5].map((offset) => parseInt(hex.slice(offset, offset + 2), 16) / 255);
  const [red, green, blue] = channels.map((channel) =>
    channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
  );
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

function contrastRatio(foreground, background) {
  const foregroundLuminance = relativeLuminance(foreground);
  const backgroundLuminance = relativeLuminance(background);
  return (Math.max(foregroundLuminance, backgroundLuminance) + 0.05) /
    (Math.min(foregroundLuminance, backgroundLuminance) + 0.05);
}

for (const [foregroundLabel, foreground, backgroundLabel, background] of [
  ["light ink", "#132638", "light cloud", "#f5f1e8"],
  ["light muted", "#536575", "light cloud", "#f5f1e8"],
  ["light sky", "#2f6f9f", "light cloud", "#f5f1e8"],
  ["light sea", "#1f6f61", "light cloud", "#f5f1e8"],
  ["dark warm white", "#f5f0e8", "dark midnight", "#08141d"],
  ["dark muted", "#a4b3be", "dark midnight", "#08141d"],
  ["dark sky", "#74b5de", "dark midnight", "#08141d"],
  ["dark sea", "#59c1a5", "dark midnight", "#08141d"]
]) {
  const ratio = contrastRatio(foreground, background);
  assert.ok(
    ratio >= 4.5,
    `${foregroundLabel} on ${backgroundLabel} must remain at least 4.5:1; received ${ratio.toFixed(2)}:1`
  );
}
for (const exportName of [
  "MobileThemePreference",
  "MobileContrastPreference",
  "MobileSemanticColors",
  "MobileSemanticTheme",
  "MOBILE_SEMANTIC_THEMES",
  "getMobileSemanticTheme",
  "mobileAppearanceFromSemanticTheme"
]) {
  requireText(tokens, exportName, "semantic theme API");
}
for (const compatibilityExport of [
  "MobileAppearance",
  "MobileSkin",
  "MOBILE_THEME_OPTIONS",
  "MOBILE_SKIN_OPTIONS",
  "DEFAULT_MOBILE_APPEARANCE",
  "getMobileAppearance"
]) {
  requireText(tokens, compatibilityExport, "V1 theme compatibility");
}
assert.match(tokens, /flightStatus:\s*\{[\s\S]*?delayed:\s*"#8b5c13"[\s\S]*?cancelled:\s*"#a8473d"/);
assert.match(tokens, /flightStatus:\s*\{[\s\S]*?delayed:\s*"#e3ad58"[\s\S]*?cancelled:\s*"#ed8b7c"/);
assert.match(tokens, /defineSemanticTheme\("high_contrast",\s*"dark",\s*"high"/);
assert.match(tokens, /defineSemanticTheme\("high_contrast_light",\s*"light",\s*"high"/);
assert.match(tokens, /return mode === "light" \? HIGH_CONTRAST_LIGHT_THEME : HIGH_CONTRAST_THEME/);

for (const runtimeContract of [
  "useColorScheme",
  "isHighTextContrastEnabled",
  "loadMobileThemePreferences",
  "saveMobileThemePreferences",
  "preference",
  "resolvedThemeMode",
  "isHighContrast"
]) {
  requireText(runtime, runtimeContract, "theme runtime");
}
for (const storageKey of [
  "localflight.mobileTheme",
  "localflight.mobileSkin",
  "localflight.mobileThemePreference",
  "localflight.mobileContrastPreference"
]) {
  requireText(settings, storageKey, "appearance storage compatibility");
}
for (const migrationApi of [
  "legacySkinToContrastPreference",
  "loadMobileThemePreferences",
  "saveMobileThemePreferences",
  "loadAppearancePrefs",
  "saveAppearancePrefs"
]) {
  requireText(settings, migrationApi, "appearance preference migration");
}

assert.match(layout, /export type LayoutWidthClass = "compact" \| "medium" \| "expanded" \| "large"/);
for (const [sizeClass, anchor] of Object.entries({ compact: 0, medium: 600, expanded: 840, large: 1200 })) {
  assert.match(layout, new RegExp(`${sizeClass}: ${anchor}(?:,|\\n)`), `${sizeClass} breakpoint must remain ${anchor}px`);
}
for (const layoutApi of ["layoutClassForWidth", "resolveResponsiveLayout", "useResponsiveLayout"]) {
  requireText(layout, layoutApi, "responsive layout API");
}

for (const exactCopy of [
  'board: "Board"',
  'radar: "Radar"',
  'history: "History"',
  'more: "More"',
  'label: "Connect to a Local Flight host"',
  'label: "Use without a Local Flight host"',
  'label: "Connected nearby"',
  'label: "Connected remotely"',
  'label: "Offline"',
  'label: "Plain language"',
  'label: "Aviation details"',
  'label: "Raw METAR"'
]) {
  requireText(copy, exactCopy, "English copy contract");
}
for (const platformCopy of [
  'camera: "Local Flight scans pairing QR codes shown by your Local Flight host."',
  'localNetwork: "Local Flight connects to a Local Flight host on the same Wi-Fi."',
  'pinnedFlight: "Pinned flight"',
  'pinAndShow: "Pin & show on Lock Screen"',
  'airlineSchedules: "Airline schedules"',
  'vatsimTraffic: "VATSIM traffic"'
]) {
  requireText(copy, platformCopy, "native and store copy catalog");
}
assert.equal(
  appConfig.expo.ios.infoPlist.NSCameraUsageDescription,
  "Local Flight scans pairing QR codes shown by your Local Flight host."
);
assert.equal(
  appConfig.expo.ios.infoPlist.NSLocalNetworkUsageDescription,
  "Local Flight connects to a Local Flight host on the same Wi-Fi."
);
requireText(iosWidget, 'Text("Pinned flight")', "iOS widget terminology");
requireText(androidWidgetStrings, '<string name="localflight_widget_pinned_flight">Pinned flight</string>', "Android widget terminology");
requireText(androidWidget, "R.string.localflight_widget_pinned_flight", "Android widget resource usage");
assert.doesNotMatch(userFacingCopy, /\bthis phone\b|phone localhost|fastest and safest/i, "User-facing copy must remain device-neutral and substantiated.");
assert.match(standaloneApi, /ROUTE_UNAVAILABLE_STATUSES = new Set\(\[404, 405\]\)/);
assert.match(standaloneApi, /getStandaloneFids\(\s*credentials,\s*"departures",\s*STANDALONE_BOARD_ROWS_PER_DIRECTION\s*\)/);
assert.match(standaloneApi, /getStandaloneFids\(\s*credentials,\s*"arrivals",\s*STANDALONE_BOARD_ROWS_PER_DIRECTION\s*\)/);
assert.doesNotMatch(standaloneApi, /Promise\.all\(\[\s*getStandaloneFids/);
assert.match(standaloneApi, /cache_state: "legacy-fids-compatibility"/);
assert.match(standaloneApi, /generated_at: ""/);
assert.match(appShell, /board\.generated_at \|\| current\.state\?\.last_success_utc \|\| ""/);
assert.match(widgetRefresh, /board\.generated_at \|\| summary\.state\?\.last_success_utc \|\| previous\?\.source\.updatedAt \|\| ""/);
for (const glossaryTerm of [
  "flight board",
  "Companion",
  "Standalone",
  "Remote Companion",
  "Community Relay",
  "Support ID",
  "movement",
  "FIDS",
  "METAR"
]) {
  requireText(glossary, `term: "${glossaryTerm}"`, "English glossary");
}

console.log("Mobile V2 foundation contract checks passed.");
