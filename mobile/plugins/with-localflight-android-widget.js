const fs = require("fs");
const path = require("path");
const { withAndroidManifest, withDangerousMod } = require("@expo/config-plugins");

const RECEIVER_SUFFIX = ".widget.LocalFlightWidgetProvider";

function copyTree(source, destination) {
  fs.mkdirSync(destination, { recursive: true });
  for (const entry of fs.readdirSync(source, { withFileTypes: true })) {
    const sourcePath = path.join(source, entry.name);
    const destinationPath = path.join(destination, entry.name);
    if (entry.isDirectory()) {
      copyTree(sourcePath, destinationPath);
    } else {
      fs.mkdirSync(path.dirname(destinationPath), { recursive: true });
      fs.copyFileSync(sourcePath, destinationPath);
    }
  }
}

function withLocalFlightAndroidWidget(config) {
  config = withAndroidManifest(config, (nextConfig) => {
    const application = nextConfig.modResults.manifest.application?.[0];
    const packageName = nextConfig.android?.package || "cc.beacontools.localflight";
    if (!application) {
      return nextConfig;
    }

    application.receiver = application.receiver || [];
    const receiverName = `${packageName}${RECEIVER_SUFFIX}`;
    const existing = application.receiver.find(
      (receiver) => receiver.$?.["android:name"] === receiverName
    );
    const receiver = existing || { $: {} };
    receiver.$["android:name"] = receiverName;
    receiver.$["android:enabled"] = "true";
    receiver.$["android:exported"] = "false";
    receiver["intent-filter"] = [
      {
        action: [
          { $: { "android:name": "android.appwidget.action.APPWIDGET_UPDATE" } }
        ]
      }
    ];
    receiver["meta-data"] = [
      {
        $: {
          "android:name": "android.appwidget.provider",
          "android:resource": "@xml/localflight_widget_info"
        }
      }
    ];
    if (!existing) {
      application.receiver.push(receiver);
    }
    return nextConfig;
  });

  return withDangerousMod(config, [
    "android",
    async (nextConfig) => {
      const projectRoot = nextConfig.modRequest.projectRoot;
      const androidRoot = nextConfig.modRequest.platformProjectRoot;
      const packageName = nextConfig.android?.package || "cc.beacontools.localflight";
      const sourceRoot = path.join(projectRoot, "native", "android-widget");
      const javaRoot = path.join(
        androidRoot,
        "app",
        "src",
        "main",
        "java",
        ...packageName.split("."),
        "widget"
      );
      const resRoot = path.join(androidRoot, "app", "src", "main", "res");
      const assetRoot = path.join(androidRoot, "app", "src", "main", "assets", "localflight-font-licenses");

      fs.mkdirSync(javaRoot, { recursive: true });
      const kotlinTemplate = fs.readFileSync(
        path.join(sourceRoot, "LocalFlightWidgetProvider.kt"),
        "utf8"
      );
      fs.writeFileSync(
        path.join(javaRoot, "LocalFlightWidgetProvider.kt"),
        kotlinTemplate.replaceAll("__PACKAGE_NAME__", packageName)
      );
      copyTree(path.join(sourceRoot, "res"), resRoot);
      copyTree(path.join(sourceRoot, "assets", "licenses"), assetRoot);
      return nextConfig;
    }
  ]);
}

module.exports = withLocalFlightAndroidWidget;
