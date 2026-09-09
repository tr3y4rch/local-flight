export function resolveDeployment(environment = process.env.LOCALFLIGHT_SITE_DEPLOYMENT || "production") {
  if (environment === "production") {
    return { siteOrigin: "https://beacontools.cc", relayOrigin: "https://relay.beacontools.cc" };
  }
  if (environment === "staging") {
    return { siteOrigin: "https://staging.beacontools.cc", relayOrigin: "https://relay-staging.beacontools.cc" };
  }
  throw new Error("LOCALFLIGHT_SITE_DEPLOYMENT must be production or staging");
}
