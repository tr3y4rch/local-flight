const { withAndroidManifest } = require("@expo/config-plugins");

const BILLING_PERMISSION = "com.android.vending.BILLING";
const LEGACY_LICENSE_PERMISSION = "com.android.vending.CHECK_LICENSE";
const RELAY_ACCESS_PRODUCT_ID = "cc.beacontools.localflight.relay_access";
const PRODUCT_ID_METADATA = "cc.beacontools.localflight.RELAY_ACCESS_PRODUCT_ID";
const INTEGRITY_PROJECT_METADATA =
  "cc.beacontools.localflight.PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER";

function normalizeProjectNumber(value) {
  const normalized = String(value || "").trim();
  if (!normalized) return "";
  if (!/^[1-9][0-9]{5,19}$/.test(normalized)) {
    throw new Error(
      "playIntegrityCloudProjectNumber must be a 6-20 digit Google Cloud project number."
    );
  }
  return normalized;
}

function ensurePermission(manifest, permissionName) {
  const permissions = manifest["uses-permission"] || [];
  const withoutLegacy = permissions.filter(
    (permission) => permission?.$?.["android:name"] !== LEGACY_LICENSE_PERMISSION
  );
  if (
    !withoutLegacy.some(
      (permission) => permission?.$?.["android:name"] === permissionName
    )
  ) {
    withoutLegacy.push({ $: { "android:name": permissionName } });
  }
  manifest["uses-permission"] = withoutLegacy;
}

function upsertMetadata(application, name, value) {
  const metadata = application["meta-data"] || [];
  const matches = metadata.filter((item) => item?.$?.["android:name"] === name);
  const entry = matches[0] || { $: {} };
  entry.$["android:name"] = name;
  entry.$["android:value"] = value;
  application["meta-data"] = [
    ...metadata.filter((item) => item?.$?.["android:name"] !== name),
    entry,
  ];
}

function configurePaidAppManifest(manifest, options = {}) {
  ensurePermission(manifest, BILLING_PERMISSION);
  const applications = manifest.application || [];
  const application = applications[0];
  if (!application) {
    throw new Error("Local Flight's Android manifest must contain an application element.");
  }

  upsertMetadata(
    application,
    PRODUCT_ID_METADATA,
    String(options.relayAccessProductId || RELAY_ACCESS_PRODUCT_ID).trim()
  );
  const projectNumber = normalizeProjectNumber(
    options.playIntegrityCloudProjectNumber ||
      process.env.LOCALFLIGHT_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER
  );
  if (projectNumber) {
    // Prefixing keeps AAPT from parsing a 12+ digit project number as an
    // overflowing Android integer instead of a string.
    upsertMetadata(
      application,
      INTEGRITY_PROJECT_METADATA,
      `project:${projectNumber}`
    );
  } else {
    application["meta-data"] = (application["meta-data"] || []).filter(
      (item) => item?.$?.["android:name"] !== INTEGRITY_PROJECT_METADATA
    );
  }
  return manifest;
}

function withLocalFlightPaidApp(config, options = {}) {
  return withAndroidManifest(config, (nextConfig) => {
    nextConfig.modResults.manifest = configurePaidAppManifest(
      nextConfig.modResults.manifest,
      options
    );
    return nextConfig;
  });
}

module.exports = withLocalFlightPaidApp;
module.exports.BILLING_PERMISSION = BILLING_PERMISSION;
module.exports.LEGACY_LICENSE_PERMISSION = LEGACY_LICENSE_PERMISSION;
module.exports.RELAY_ACCESS_PRODUCT_ID = RELAY_ACCESS_PRODUCT_ID;
module.exports.PRODUCT_ID_METADATA = PRODUCT_ID_METADATA;
module.exports.INTEGRITY_PROJECT_METADATA = INTEGRITY_PROJECT_METADATA;
module.exports.configurePaidAppManifest = configurePaidAppManifest;
module.exports.normalizeProjectNumber = normalizeProjectNumber;
