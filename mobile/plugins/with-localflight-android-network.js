const { withAndroidManifest } = require("@expo/config-plugins");

function withLocalFlightAndroidNetwork(config) {
  return withAndroidManifest(config, (nextConfig) => {
    const application = nextConfig.modResults.manifest.application?.[0];
    if (application?.$) {
      application.$["android:usesCleartextTraffic"] = "true";
    }
    return nextConfig;
  });
}

module.exports = withLocalFlightAndroidNetwork;
