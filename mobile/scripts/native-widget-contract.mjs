import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");
const app = JSON.parse(read("app.json")).expo;
const plugins = app.plugins.map((plugin) => Array.isArray(plugin) ? plugin[0] : plugin);

assert.equal(app.ios.buildNumber, "6");
assert.equal(app.android.versionCode, 9);
assert.ok(plugins.includes("./plugins/with-localflight-ios-widget"));
assert.ok(plugins.includes("./plugins/with-localflight-android-widget"));
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
const iosPlugin = read("plugins/with-localflight-ios-widget.js");
assert.match(iosSnapshot, /maxSnapshotBytes = 64 \* 1024/);
assert.match(iosSnapshot, /resourceValues\(forKeys: \[\.fileSizeKey, \.isRegularFileKey\]\)/);
assert.match(iosWidget, /localflight:\/\/widgets/);
assert.match(iosWidget, /5 \* 60/);
assert.match(iosWidget, /30 \* 60/);
assert.match(iosPlugin, /com\.apple\.security\.application-groups/);
assert.match(iosPlugin, /LocalFlightWidget/);
assert.match(iosPlugin, /ensureTargetDependency/);
assert.match(iosPlugin, /PBXTargetDependency/);
assert.doesNotMatch(
  [iosSnapshot, iosWidget, read("native/ios-widget/SmallWidgetViewV2.swift"), read("native/ios-widget/MediumWidgetViewV2.swift")].join("\n"),
  /URLSession|HTTPURLResponse|NWConnection|Network\.framework/
);

const androidProvider = read("native/android-widget/LocalFlightWidgetProvider.kt");
const androidPlugin = read("plugins/with-localflight-android-widget.js");
const androidInfo = read("native/android-widget/res/xml/localflight_widget_info.xml");
const androidNightColors = read("native/android-widget/res/values-night/localflight_widget_colors.xml");
assert.match(androidProvider, /MAX_SNAPSHOT_BYTES = 64 \* 1024/);
assert.match(androidProvider, /File\(context\.filesDir, SNAPSHOT_FILENAME\)/);
assert.match(androidProvider, /SNAPSHOT_SCHEMA_VERSION/);
assert.match(androidProvider, /PendingIntent\.FLAG_IMMUTABLE/);
assert.match(androidProvider, /ACTION_REFRESH/);
assert.match(androidProvider, /setContentDescription/);
assert.doesNotMatch(androidProvider, /https?:\/\//i);
assert.doesNotMatch(androidProvider, /OkHttp|HttpURLConnection|Socket|URL\(/);
assert.match(androidPlugin, /android:exported.*false/);
assert.match(androidPlugin, /android\.appwidget\.action\.APPWIDGET_UPDATE/);
assert.match(androidInfo, /android:updatePeriodMillis="1800000"/);
assert.match(androidNightColors, /#0A111B/);

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
