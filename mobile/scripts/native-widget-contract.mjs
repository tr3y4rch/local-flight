import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");
const app = JSON.parse(read("app.json")).expo;
const plugins = app.plugins.map((plugin) => Array.isArray(plugin) ? plugin[0] : plugin);

assert.equal(app.ios.buildNumber, "9");
assert.equal(app.android.versionCode, 12);
assert.ok(plugins.includes("./plugins/with-localflight-ios-widget"));
assert.ok(plugins.includes("./plugins/with-localflight-android-widget"));
assert.ok(plugins.includes("expo-background-task"));
assert.deepEqual(app.ios.entitlements["com.apple.security.application-groups"], [
  "group.cc.beacontools.localflight"
]);
assert.deepEqual(app.extra.eas.build.experimental.ios.appExtensions, [
  {
    targetName: "LocalFlightWidget",
    bundleIdentifier: "cc.beacontools.localflight.widget",
    entitlements: {
      "com.apple.security.application-groups": ["group.cc.beacontools.localflight"]
    }
  }
]);

const iosSnapshot = read("native/ios-widget/WidgetSnapshot.swift");
const iosWidget = read("native/ios-widget/LocalFlightWidget.swift");
const iosDesign = read("native/ios-widget/DesignTokens.swift");
const iosLiveActivity = read("native/ios-widget/LiveActivityViewV2.swift");
const iosPlugin = read("plugins/with-localflight-ios-widget.js");
const privacyPlugin = read("plugins/with-localflight-privacy-manifest.js");
assert.match(iosSnapshot, /maxSnapshotBytes = 64 \* 1024/);
assert.match(iosSnapshot, /resourceValues\(forKeys: \[\.fileSizeKey, \.isRegularFileKey\]\)/);
assert.match(iosWidget, /localflight:\/\/widgets/);
assert.match(iosWidget, /5 \* 60/);
assert.match(iosWidget, /30 \* 60/);
assert.match(iosWidget, /LocalFlightWidgetBundle/);
assert.match(iosWidget, /#available\(iOSApplicationExtension 16\.1/);
assert.match(iosWidget, /\.contentMarginsDisabled\(\)/);
assert.match(iosLiveActivity, /ActivityConfiguration\(for: LocalFlightActivityAttributesV2\.self\)/);
assert.match(iosLiveActivity, /sectionLabel\("Pinned flight"\)/);
assert.match(iosLiveActivity, /Text\(state\.stale \? "Stale" : state\.statusDisplay\)/);
assert.match(iosLiveActivity, /\.font\(LocalFlightWidgetFont\.uiBold\(size: 11\)\)/);
assert.match(iosLiveActivity, /attributes\.direction == "arr"/);
assert.match(iosLiveActivity, /attributes\.airportCode/);
assert.match(iosLiveActivity, /state\.stale \? "Stale" : state\.statusDisplay/);
assert.match(iosLiveActivity, /accessibilityLabel\(state\.stale \? "Flight information stale"/);
assert.match(iosLiveActivity, /DynamicIslandExpandedRegion/);
assert.match(iosLiveActivity, /compactLeading:/);
assert.match(iosLiveActivity, /minimal:/);
assert.match(iosDesign, /#F5F1E8 \/ #FFFDF8 \/ #132638 \/ #536575 \/ #2F6F9F \/ #1F6F61/);
assert.match(iosDesign, /#08141D \/ #102330 \/ #F5F0E8 \/ #A4B3BE \/ #74B5DE \/ #59C1A5/);
assert.match(iosDesign, /static func textDim[\s\S]*?textMuted\(scheme\)/);
assert.match(iosDesign, /scheme == \.dark \? 0\.14 : 0\.04/);
assert.match(iosPlugin, /com\.apple\.security\.application-groups/);
assert.match(iosPlugin, /LocalFlightWidget/);
assert.match(iosPlugin, /LiveActivityViewV2\.swift/);
assert.match(iosPlugin, /NSSupportsLiveActivities = true/);
assert.match(iosPlugin, /ensureTargetDependency/);
assert.match(iosPlugin, /PBXTargetDependency/);
assert.doesNotMatch(privacyPlugin, /delete infoPlist\.NSSupportsLiveActivities/);
assert.doesNotMatch(
  [iosSnapshot, iosWidget, iosLiveActivity, read("native/ios-widget/SmallWidgetViewV2.swift"), read("native/ios-widget/MediumWidgetViewV2.swift")].join("\n"),
  /URLSession|HTTPURLResponse|NWConnection|Network\.framework/
);

const androidProvider = read("native/android-widget/LocalFlightWidgetProvider.kt");
const androidPlugin = read("plugins/with-localflight-android-widget.js");
const androidInfo = read("native/android-widget/res/xml/localflight_widget_info.xml");
const androidLayout = read("native/android-widget/res/layout/localflight_widget.xml");
const androidColors = read("native/android-widget/res/values/localflight_widget_colors.xml");
const androidNightColors = read("native/android-widget/res/values-night/localflight_widget_colors.xml");
const androidThemedColors = read("native/android-widget/res/values-v33/localflight_widget_colors.xml");
const androidThemedNightColors = read("native/android-widget/res/values-night-v33/localflight_widget_colors.xml");
assert.match(androidProvider, /MAX_SNAPSHOT_BYTES = 64 \* 1024/);
assert.match(androidProvider, /File\(context\.filesDir, SNAPSHOT_FILENAME\)/);
assert.match(androidProvider, /SNAPSHOT_SCHEMA_VERSION/);
assert.match(androidProvider, /PendingIntent\.FLAG_IMMUTABLE/);
assert.match(androidProvider, /localflight:\/\/widgets\?refresh=1/);
assert.match(androidProvider, /PendingIntent\.getActivity/);
assert.match(androidProvider, /setContentDescription/);
assert.match(androidProvider, /flight\?\.routeName/);
assert.match(androidProvider, /flight\?\.time/);
assert.match(androidProvider, /OPTION_APPWIDGET_MIN_HEIGHT/);
assert.match(androidProvider, /widget_compact/);
assert.match(androidProvider, /widget_board/);
assert.match(androidProvider, /widget_row_4/);
assert.doesNotMatch(androidProvider, /https?:\/\//i);
assert.doesNotMatch(androidProvider, /OkHttp|HttpURLConnection|Socket|URL\(/);
assert.match(androidPlugin, /android:exported.*false/);
assert.match(androidPlugin, /android\.appwidget\.action\.APPWIDGET_UPDATE/);
assert.match(androidInfo, /android:updatePeriodMillis="1800000"/);
assert.match(androidInfo, /android:minResizeWidth="110dp"/);
assert.match(androidInfo, /android:minResizeHeight="110dp"/);
assert.match(androidLayout, /@\+id\/widget_compact/);
assert.match(androidLayout, /@\+id\/widget_board/);
assert.match(androidLayout, /@\+id\/widget_compact_label_row/);
assert.match(androidProvider, /val short = minHeight < 150/);
assert.match(androidProvider, /val rowLimit = when \{[\s\S]*?minHeight < 170 -> 1[\s\S]*?minHeight < 215 -> 2[\s\S]*?else -> 3/);
assert.doesNotMatch(androidProvider, /else -> 4/);
assert.ok(androidColors.includes("#925D10"), "Android light widget ochre must remain contrast-safe");
for (const color of ["#F5F1E8", "#FFFDF8", "#132638", "#536575", "#2F6F9F", "#1F6F61"]) {
  assert.ok(androidColors.includes(color), `missing Android light widget anchor ${color}`);
}
for (const color of ["#08141D", "#102330", "#F5F0E8", "#A4B3BE", "#74B5DE", "#59C1A5"]) {
  assert.ok(androidNightColors.includes(color), `missing Android dark widget anchor ${color}`);
}
assert.match(androidThemedColors, /@android:color\/system_accent1_600/);
assert.match(androidThemedNightColors, /@android:color\/system_accent1_200/);

const widgetBridge = read("modules/localflight-widget-bridge/src/index.ts");
const widgetBridgeApple = read("modules/localflight-widget-bridge/ios/LocalFlightWidgetBridgeModule.swift");
const liveActivityManager = read("modules/localflight-widget-bridge/ios/LocalFlightLiveActivityManager.swift");
const widgetBridgeAndroid = read("modules/localflight-widget-bridge/android/src/main/java/cc/beacontools/localflight/widgetbridge/LocalFlightWidgetBridgeModule.kt");
const shortcutBridgeAndroid = read("modules/localflight-widget-bridge/android/src/main/java/cc/beacontools/localflight/widgetbridge/LocalFlightShortcutView.kt");
const shortcutHost = read("src/navigation/NativeShortcutHost.tsx");
assert.match(widgetBridge, /reloadLocalFlightWidgets/);
assert.match(widgetBridge, /isLocalFlightLiveActivitySupported/);
assert.match(widgetBridge, /startLocalFlightLiveActivity/);
assert.match(widgetBridge, /updateLocalFlightLiveActivity/);
assert.match(widgetBridge, /endLocalFlightLiveActivity/);
assert.match(widgetBridge, /reconcileLocalFlightLiveActivity/);
assert.match(widgetBridgeApple, /WidgetCenter\.shared\.reloadTimelines/);
for (const method of ["isSupported", "startLiveActivity", "updateLiveActivity", "endLiveActivity", "reconcileLiveActivity"]) {
  assert.ok(widgetBridgeApple.includes(`AsyncFunction("${method}")`), `missing Apple bridge method ${method}`);
  assert.ok(widgetBridgeAndroid.includes(`AsyncFunction("${method}")`), `missing Android fallback ${method}`);
}
assert.match(liveActivityManager, /schemaVersion = 1/);
assert.match(liveActivityManager, /maxSnapshotBytes = 64 \* 1024/);
assert.match(liveActivityManager, /containerURL\(forSecurityApplicationGroupIdentifier:/);
assert.match(liveActivityManager, /#available\(iOS 16\.1/);
assert.match(liveActivityManager, /pushType: nil/);
assert.match(liveActivityManager, /showGateTerminal != false/);
assert.match(liveActivityManager, /flight\.direction == "arr"/);
assert.match(liveActivityManager, /let flight = snapshot\.small\.flight/);
assert.doesNotMatch(liveActivityManager, /snapshot\.liveActivity\.flight \?\?/);
assert.doesNotMatch(liveActivityManager, /URLSession|HTTPURLResponse|NWConnection|HttpURLConnection|Socket/);
assert.match(widgetBridgeAndroid, /ACTION_APPWIDGET_UPDATE/);
assert.match(widgetBridgeApple, /View\(LocalFlightShortcutView\.self\)/);
assert.match(widgetBridgeApple, /UIKeyCommand\.inputEscape/);
assert.match(widgetBridgeApple, /UIKeyModifierFlags\.command/);
assert.match(widgetBridgeApple, /UIKeyModifierFlags\.control/);
assert.match(widgetBridgeAndroid, /View\(LocalFlightShortcutView::class\)/);
assert.match(shortcutBridgeAndroid, /KEYCODE_ESCAPE/);
assert.match(shortcutBridgeAndroid, /event\.isCtrlPressed/);
assert.match(shortcutBridgeAndroid, /event\.isMetaPressed/);
assert.match(shortcutHost, /requireNativeViewManager/);
assert.match(shortcutHost, /NativeShortcutKey/);

const screens = read("src/screens/AppScreens.tsx");
assert.match(screens, /Ready for Android widgets\./);
assert.match(screens, /Ready for iOS widgets\./);
for (const forbidden of [
  "TIP JAR",
  "support tips are being prepared",
  "cc.beacontools.localflight.tip.",
  "buymeacoffee.com"
]) {
  assert.ok(!screens.includes(forbidden), `stale payment UI returned: ${forbidden}`);
}

console.log("Native widget contract passed.");
