const baseConfig = require("./app.json").expo;

const DEPLOYMENTS = Object.freeze({
  staging: Object.freeze({
    canonicalOrigin: "https://relay-staging.beacontools.cc",
    acceptedPurchaseEnvironments: Object.freeze(["sandbox", "test"])
  }),
  production: Object.freeze({
    canonicalOrigin: "https://relay.beacontools.cc",
    acceptedPurchaseEnvironments: Object.freeze(["production"])
  })
});

const PAID_APP_PLUGIN = "./plugins/with-localflight-paid-app";
const GOOGLE_PLAY_RELAY_ACCESS_PRODUCT_ID =
  "cc.beacontools.localflight.relay_access";

function normalizeHttpsOrigin(value, label) {
  const normalized = String(value || "").trim().replace(/\/+$/, "");
  let parsed;
  try {
    parsed = new URL(normalized);
  } catch {
    throw new Error(`${label} must be an absolute HTTPS origin.`);
  }
  if (
    parsed.protocol !== "https:" ||
    parsed.username ||
    parsed.password ||
    parsed.origin !== normalized
  ) {
    throw new Error(`${label} must be an HTTPS origin without credentials, a path, query, or fragment.`);
  }
  return normalized;
}

function resolveRelayDeployment(environment = process.env) {
  const selected = String(
    environment.EXPO_PUBLIC_LOCALFLIGHT_DEPLOYMENT ||
      (environment.EAS_BUILD_PROFILE === "production" ? "production" : "staging")
  ).trim().toLowerCase();
  const defaults = DEPLOYMENTS[selected];
  if (!defaults) {
    throw new Error("EXPO_PUBLIC_LOCALFLIGHT_DEPLOYMENT must be staging or production.");
  }

  const canonicalOrigin = normalizeHttpsOrigin(
    environment.EXPO_PUBLIC_LOCALFLIGHT_RELAY_ORIGIN || defaults.canonicalOrigin,
    "EXPO_PUBLIC_LOCALFLIGHT_RELAY_ORIGIN"
  );
  const failoverOrigins = String(
    environment.EXPO_PUBLIC_LOCALFLIGHT_RELAY_FAILOVER_ORIGINS || ""
  )
    .split(",")
    .map((origin) => origin.trim())
    .filter(Boolean)
    .map((origin) => normalizeHttpsOrigin(origin, "EXPO_PUBLIC_LOCALFLIGHT_RELAY_FAILOVER_ORIGINS"))
    .filter((origin, index, origins) => origin !== canonicalOrigin && origins.indexOf(origin) === index);

  return {
    deployment: selected,
    canonicalOrigin,
    failoverOrigins,
    acceptedPurchaseEnvironments: [...defaults.acceptedPurchaseEnvironments]
  };
}

function resolvePlayIntegrityProjectNumber(environment = process.env) {
  const value = String(
    environment.LOCALFLIGHT_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER || ""
  ).trim();
  if (!value) return "";
  if (!/^[1-9][0-9]{5,19}$/.test(value)) {
    throw new Error(
      "LOCALFLIGHT_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER must be a 6-20 digit Google Cloud project number."
    );
  }
  return value;
}

function configuredPlugins(plugins, projectNumber) {
  return (plugins || []).map((plugin) => {
    const name = Array.isArray(plugin) ? plugin[0] : plugin;
    if (name !== PAID_APP_PLUGIN) return plugin;
    return [
      PAID_APP_PLUGIN,
      {
        ...(Array.isArray(plugin) ? plugin[1] : {}),
        relayAccessProductId: GOOGLE_PLAY_RELAY_ACCESS_PRODUCT_ID,
        ...(projectNumber
          ? { playIntegrityCloudProjectNumber: projectNumber }
          : {}),
      },
    ];
  });
}

function createExpoConfig({ config = baseConfig } = {}) {
  const relay = resolveRelayDeployment();
  const playIntegrityProjectNumber = resolvePlayIntegrityProjectNumber();
  return {
    ...config,
    plugins: configuredPlugins(config.plugins, playIntegrityProjectNumber),
    extra: {
      ...config.extra,
      localFlightDeployment: relay.deployment,
      localFlight: {
        deploymentEnvironment: relay.deployment,
        relayOrigin: relay.canonicalOrigin,
        relayFailoverOrigins: relay.failoverOrigins,
        acceptedPurchaseEnvironments: relay.acceptedPurchaseEnvironments,
        playIntegrityConfigured: Boolean(playIntegrityProjectNumber)
      },
      localFlightRelay: {
        canonicalOrigin: relay.canonicalOrigin,
        failoverOrigins: relay.failoverOrigins,
        acceptedPurchaseEnvironments: relay.acceptedPurchaseEnvironments
      }
    }
  };
}

createExpoConfig.DEPLOYMENTS = DEPLOYMENTS;
createExpoConfig.resolveRelayDeployment = resolveRelayDeployment;
createExpoConfig.resolvePlayIntegrityProjectNumber = resolvePlayIntegrityProjectNumber;
createExpoConfig.configuredPlugins = configuredPlugins;
createExpoConfig.GOOGLE_PLAY_RELAY_ACCESS_PRODUCT_ID =
  GOOGLE_PLAY_RELAY_ACCESS_PRODUCT_ID;

module.exports = createExpoConfig;
