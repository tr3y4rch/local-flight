#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const mobileRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const capabilitiesPath = path.join(mobileRoot, "src/navigation/nativeNavigationCapabilities.ts");
const navigatorPath = path.join(mobileRoot, "src/navigation/MobileNavigatorV2.tsx");
const featureGatePath = path.join(mobileRoot, "src/v2/featureGate.ts");
const appShellPath = path.join(mobileRoot, "src/app/AppShell.tsx");
const packagePath = path.join(mobileRoot, "package.json");
const packageLockPath = path.join(mobileRoot, "package-lock.json");
const screensPatchPath = path.join(mobileRoot, "scripts/patch-react-native-screens.mjs");

const {
  LIQUID_GLASS_MIN_IOS_MAJOR,
  iosMajorVersion,
  resolveNativeNavigationCapabilities
} = await import(pathToFileURL(capabilitiesPath).href);

assert.equal(LIQUID_GLASS_MIN_IOS_MAJOR, 26);
assert.equal(iosMajorVersion("26.1"), 26);
assert.equal(iosMajorVersion(26.9), 26);
assert.equal(iosMajorVersion("unavailable"), 0);

const eligible = {
  platform: "ios",
  platformVersion: "26.0",
  isPad: false,
  isTV: false,
  layoutClass: "compact",
  rolloutEnabled: true,
  nativeTabsAvailable: true
};

assert.equal(resolveNativeNavigationCapabilities(eligible).usesNativeLiquidGlassTabs, true);
for (const partial of [
  { platformVersion: "25.6" },
  { isPad: true },
  { isTV: true },
  { layoutClass: "medium" },
  { platform: "android" },
  { rolloutEnabled: false },
  { nativeTabsAvailable: false }
]) {
  assert.equal(
    resolveNativeNavigationCapabilities({ ...eligible, ...partial }).usesNativeLiquidGlassTabs,
    false,
    `Liquid Glass must fall back for ${JSON.stringify(partial)}`
  );
}

const navigator = fs.readFileSync(navigatorPath, "utf8");
const featureGate = fs.readFileSync(featureGatePath, "utf8");
const appShell = fs.readFileSync(appShellPath, "utf8");
const packageJson = JSON.parse(fs.readFileSync(packagePath, "utf8"));
const packageLock = JSON.parse(fs.readFileSync(packageLockPath, "utf8"));
const screensPatch = fs.readFileSync(screensPatchPath, "utf8");

// Expo SDK 55 supplies react-native-screens 4.23. Its Tabs API expects the
// selected screen through `isFocused`; bottom-tabs 7.16+ instead uses the new
// controlled navigation-state request added in screens 4.25. Mixing the two
// mounts UIKit with zero focused tabs and triggers RNSTabBarController's
// invariant on iOS. Keep this bridge exact until Expo moves screens forward.
assert.equal(packageJson.dependencies["@react-navigation/bottom-tabs"], "7.15.13");
assert.equal(packageJson.dependencies["react-native-screens"], "4.23.0");
assert.equal(
  packageJson.scripts.postinstall,
  "node scripts/patch-react-native-screens.mjs && node scripts/patch-audited-transitives.mjs"
);
assert.equal(
  packageLock.packages["node_modules/@react-navigation/bottom-tabs"].version,
  "7.15.13"
);

assert.match(navigator, /createNativeBottomTabNavigator/);
assert.match(navigator, /<NativeTabs\.Screen name="Board"/);
assert.match(navigator, /<NativeTabs\.Screen name="Radar"/);
assert.match(navigator, /<NativeTabs\.Screen name="History"/);
assert.match(navigator, /<NativeTabs\.Screen name="More"/);
assert.match(navigator, /tabBarMinimizeBehavior:[\s\S]*?"onScrollDown"/);
assert.match(navigator, /overrideScrollViewContentInsetAdjustmentBehavior: true/);
assert.match(navigator, /nativeScrollRoot/);
assert.match(screensPatch, /LOCAL_FLIGHT_CONTENT_SCROLL_VIEW_PATCH_V1/);
assert.match(screensPatch, /contentScrollViewForEdge/);
assert.match(navigator, /type: "sfSymbol"/);
assert.doesNotMatch(navigator, /bottomAccessory:/);
assert.match(featureGate, /MOBILE_V2_NATIVE_NAVIGATION_ENABLED = true/);
assert.match(appShell, /nativeNavigation\.usesNativeLiquidGlassTabs/);
assert.match(appShell, /await endLocalFlightLiveActivity\(\)\.catch/);

console.log("Native navigation capability contract checks passed.");
