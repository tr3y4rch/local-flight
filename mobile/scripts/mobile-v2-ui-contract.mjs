#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const mobileRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (relativePath) => fs.readFileSync(path.join(mobileRoot, relativePath), "utf8");

const app = read("App.tsx");
const shell = read("src/app/AppShell.tsx");
const appScreens = read("src/screens/AppScreens.tsx");
const navigator = read("src/navigation/MobileNavigatorV2.tsx");
const nativeShortcutHost = read("src/navigation/NativeShortcutHost.tsx");
const board = read("src/v2/BoardScreenV2.tsx");
const boardModel = read("src/v2/boardModel.ts");
const display = read("src/v2/DisplayScreenV2.tsx");
const radar = read("src/v2/RadarScreenV2.tsx");
const radarScope = read("src/v2/RadarScopeV2.tsx");
const history = read("src/v2/HistoryScreenV2.tsx");
const more = read("src/v2/MoreScreenV2.tsx");
const featureGate = read("src/v2/featureGate.ts");
const settings = read("src/storage/settings.ts");
const nativeActivity = read("modules/localflight-widget-bridge/ios/LocalFlightLiveActivityManager.swift");
const layoutSmoke = read("scripts/ios-layout-smoke.sh");
const launchOverlay = read("src/components/LaunchOverlay.tsx");
const launchHook = read("src/hooks/useLaunchOverlay.ts");
const launchPresentation = read("src/domain/launchPresentation.ts");
const standaloneApi = read("src/api/standalone.ts");
const companionApi = read("src/api/client.ts");

for (const tab of ["Board", "Radar", "History", "More"]) {
  assert.ok(navigator.includes(`<Tabs.Screen name="${tab}"`), `missing stable ${tab} tab`);
}
for (const route of ["board", "radar", "history", "more", "display", "pairing", "widgets", "widget-refresh"]) {
  assert.ok(navigator.includes(`"${route}"`) || navigator.includes(`: "${route}"`), `missing ${route} deep-link route`);
}
assert.match(navigator, /tabBarPosition: rail \? "left" : "bottom"/);
assert.match(navigator, /layout\.sizeClass === "medium"/);
assert.match(navigator, /<NativeShortcutHost onShortcut=\{handleShortcut\}>/);
assert.match(navigator, /key === "1"[\s\S]*key === "4"/);
assert.match(navigator, /key === "r"/);
assert.match(navigator, /key === "f"/);
assert.match(navigator, /key === "escape"/);
assert.match(navigator, /setDismissRequestKey\(\(value\) => value \+ 1\)/);
assert.match(nativeShortcutHost, /"1" \| "2" \| "3" \| "4" \| "r" \| "f" \| "escape"/);
assert.match(nativeShortcutHost, /requireNativeViewManager/);
assert.match(nativeShortcutHost, /Platform\.OS !== "ios" && Platform\.OS !== "android"/);
assert.match(navigator, /openMobileMorePanel/);
assert.match(navigator, /action === "pairing" \? "host" : "widgets"/);

for (const column of ["Time", "Flight", "Route", "Status", "Aircraft", "Gate"]) {
  assert.ok(board.includes(`>${column}<`), `wide Board missing ${column} column`);
}
assert.match(board, /updatedLabel/);
assert.match(board, /connectionLabel/);
assert.doesNotMatch(board, /setInterval|setTimeout/);
assert.match(boardModel, /virtual \? "" :/);
assert.match(boardModel, /flight_rules/);
assert.match(boardModel, /planned_altitude/);
assert.match(boardModel, /squawk \|\| row\.transponder/);
assert.match(boardModel, /if \(row\.detail_mode\) return row\.detail_mode === "virtual"/);
assert.match(boardModel, /occurrenceByIdentity/);
assert.match(boardModel, /`\$\{identity\}:\$\{occurrence\}`/);
assert.match(appScreens, /`radar-target:\$\{keyedPart\(identity\)\}:\$\{keyedPart\(row\.icao24\)\}:\$\{index\}`/);

assert.match(display, /OrientationLock\.LANDSCAPE/);
assert.match(display, /Dimensions\.get\("screen"\)/);
assert.match(display, /pageSeconds/);
assert.match(display, /reduceMotion/);
assert.match(display, /onExit/);
assert.match(display, /Page \{Math\.min\(pageIndex \+ 1/);
assert.doesNotMatch(shell, /landscapeFidsActive|LandscapeFidsMode/);
assert.match(shell, /MobileNavigatorV2/);
assert.doesNotMatch(shell, /safe:\s*\{[^}]*alignItems:\s*"center"/, "The adaptive navigator must retain full window width");

assert.match(radar, /Aviation details/);
assert.match(radar, /dismissRequestKey/);
assert.match(radar, /RadarScopeV2/);
assert.match(radar, /board_status/);
assert.match(radarScope, /groundData\?\.center/);
assert.match(radarScope, /projectBlip\(blip, props\.data\.center/);
assert.match(radarScope, /Airport surface ready/);
assert.match(radarScope, /Surface loading/);
assert.match(radarScope, /Geographic context only/);
assert.doesNotMatch(radarScope, /ground drawings/i);
assert.match(radarScope, /Math\.min\(720, width - 20\)/);
assert.match(history, /Flights observed/);
assert.match(history, /Airlines in this local history/);
assert.match(history, /incomplete local observations/);
assert.match(history, /const \[draft, setDraft\]/);
assert.match(history, /props\.onApplyFilters\(draft\)/);
assert.match(history, /dismissRequestKey/);
for (const section of [
  "Airport & Connection",
  "Appearance",
  "Board & Display",
  "Widgets & Live Activity",
  "Host & Displays",
  "Help & Privacy",
  "Advanced diagnostics"
]) {
  assert.ok(more.includes(section), `More missing ${section}`);
}
assert.match(more, /dismissRequestKey/);
assert.doesNotMatch(more, /legacySettingsContent|hostSettingsContent|advancedSettingsContent|helpSettingsContent/);
assert.match(more, /weatherDisplayMode/);
assert.match(more, /panel === "support"/);
assert.ok(
  more.indexOf("styles.supportFooter") > more.indexOf("styles.setupButton"),
  "optional support must remain the final, quiet More setting"
);
assert.doesNotMatch(shell, /renderLegacySettingsSurface|StandaloneSettingsScreen|ControlScreen/);

assert.doesNotMatch(app, /Text\.defaultProps|installGlobalTextFont/);
assert.match(app, /if \(!fontsLoaded && !fontError\) return null;/);
assert.match(app, /using the system fallback/);
assert.match(featureGate, /MOBILE_V2_ROLLOUT_ENABLED = true/);
assert.match(featureGate, /MOBILE_V2_PUBLIC_TOGGLE = false/);
assert.match(settings, /liveActivityEnabled: false/);
assert.match(nativeActivity, /snapshot\.preferences\.liveActivityEnabled == true/);
assert.match(nativeActivity, /pushType: nil/);
assert.match(nativeActivity, /2 \* 60 \* 60/);
assert.match(nativeActivity, /hadActiveActivity \? await start\(\) : response\(action: "no_activity"\)/);
assert.match(shell, /includeBoardSnapshot: true/);
assert.match(shell, /includeBoardSnapshot: !isStandalone/);
assert.match(shell, /standalone_policy\?\.board_refresh_seconds \|\| 3600/);
assert.match(shell, /standalone_policy\?\.radar_refresh_seconds \|\| 180/);
assert.match(shell, /getStandaloneBoard/);
assert.match(shell, /foregroundRefreshGenerationByTargetRef/);
assert.match(shell, /refreshErrorByTarget/);
assert.match(shell, /dashboardRequestGenerationRef/);
assert.match(shell, /targetRequestGenerationByTargetRef/);
assert.match(shell, /scheduleBoardRefresh/);
assert.match(shell, /elapsedAtFire < boardIntervalMs/);
assert.match(shell, /const connectionState: ConnectionState = isLive/);
assert.match(shell, /queueOrHandlePairingUrl/);
assert.match(shell, /historyRequestGenerationRef/);
assert.match(shell, /radarRequestGenerationRef/);
assert.match(shell, /isCurrentRadarRequest/);
assert.match(shell, /widgetSnapshotHydrated/);
assert.match(shell, /startLocalFlightLiveActivity/);
for (const noticeTarget of ["/admin", "/logs", "/feedback", "/matrix-preview", "/setup"]) {
  assert.ok(shell.includes(`target === "${noticeTarget}"`), `notice route ${noticeTarget} is not handled by the V2 shell`);
}
assert.match(layoutSmoke, /XCODE_SCHEME="\$\{XCODE_SCHEME:-LocalFlight\}"/);
assert.doesNotMatch(layoutSmoke, /LocalFlightCompanion\.xcworkspace|-scheme LocalFlightCompanion/);
assert.match(launchOverlay, /AircraftGlyph/);
assert.match(launchOverlay, /RadarVectorLayer/);
assert.match(launchOverlay, /SweepLayer/);
assert.match(launchOverlay, /ambientSweepRotation/);
assert.match(launchOverlay, /breathingScale/);
assert.match(launchOverlay, /entryLabel/);
assert.match(launchHook, /Animated\.loop/);
assert.match(launchHook, /requestAnimationFrame\(startCinematic\)/);
assert.doesNotMatch(launchHook, /if \(finished\)/, "An interrupted launch fade must not leave an invisible blocking overlay");
assert.match(launchPresentation, /LAUNCH_MIN_MS = 6_000/);
assert.match(launchPresentation, /LAUNCH_NETWORK_CEILING_MS = 7_000/);

const setupStart = appScreens.indexOf("type CompanionSetupStep");
const setupEnd = appScreens.indexOf("function SettingsScreen", setupStart);
assert.ok(setupStart >= 0 && setupEnd > setupStart, "missing mobile onboarding implementation");
const setup = appScreens.slice(setupStart, setupEnd);
assert.match(setup, /\["welcome", "mode", "airport", "review"\]/);
assert.match(setup, /\["welcome", "mode", "pairing", "review"\]/);
assert.doesNotMatch(setup, /step === "(?:server|policy|diagnostics|ready)"/);
assert.doesNotMatch(setup, /\| "(?:server|policy|diagnostics|ready)"/);
for (const onboardingTerm of [
  "Connect to a Local Flight host",
  "Use without a Local Flight host",
  "same Wi-Fi",
  "Airline schedules",
  "VATSIM traffic",
  "Privacy & review"
]) {
  assert.ok(setup.includes(onboardingTerm), `onboarding missing ${onboardingTerm}`);
}
assert.doesNotMatch(setup, /companionSetupLogoRing|companionSetupLogoPlate/);
assert.match(setup, /type AirportSearchState = "idle" \| "loading" \| "results" \| "empty" \| "error"/);
assert.match(setup, /Retry airport search/);
assert.match(setup, /airportCodeFromQuery/);
assert.match(setup, /3-letter IATA or 4-letter ICAO code/);
assert.match(setup, /standaloneAirportLookupErrorMessage/);
assert.match(standaloneApi, /AIRPORT_SEARCH_QUERY_LIMIT = 20/);
assert.match(standaloneApi, /slice\(0, AIRPORT_SEARCH_QUERY_LIMIT\)/);
assert.match(standaloneApi, /RELAY_REQUEST_TIMEOUT_MS/);
assert.match(standaloneApi, /DEFAULT_RELAY_FALLBACK_URL/);
assert.match(standaloneApi, /Platform\.OS === "ios"/);
assert.match(standaloneApi, /preferredStandaloneRelayUrl/);
assert.match(companionApi, /AIRPORT_SEARCH_QUERY_LIMIT = 20/);
assert.match(companionApi, /slice\(0, AIRPORT_SEARCH_QUERY_LIMIT\)/);
assert.match(appScreens, /Retry host airport search/);

console.log("Mobile V2 UI contract checks passed.");
