import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const standalone = fs.readFileSync(path.join(root, "src/api/standalone.ts"), "utf8");
const screens = fs.readFileSync(path.join(root, "src/screens/AppScreens.tsx"), "utf8");
const settings = fs.readFileSync(path.join(root, "src/storage/settings.ts"), "utf8");

const failures = [];
const requireMatch = (source, pattern, message) => {
  if (!pattern.test(source)) failures.push(message);
};
const rejectMatch = (source, pattern, message) => {
  if (pattern.test(source)) failures.push(message);
};

requireMatch(standalone, /\/v1\/airport-ground\?\$\{params\}/, "Standalone must use the authenticated combined ground endpoint.");
rejectMatch(standalone, /\/v1\/airport-surface\?/, "Standalone must not fall back to the coordinate-trusting legacy surface route.");
requireMatch(screens, /radarDrawableFeatures\(groundData\.map_features\)/, "Radar must render relay map context.");
requireMatch(screens, /layer="map"/, "Map context must have an explicit render layer.");
requireMatch(screens, /road_class/, "Road styling must distinguish main and secondary roads.");
requireMatch(settings, /STANDALONE_GROUND_LAYERS_VERSION_KEY/, "Standalone ground-layer defaults require a one-time migration marker.");
requireMatch(settings, /terrain: true/, "Standalone ground layers must default terrain on.");
rejectMatch(screens, /standalone\s*\?\s*\{[^}]*terrain:\s*false/s, "Standalone must not force terrain off.");

if (failures.length) {
  console.error(failures.map((failure) => `- ${failure}`).join("\n"));
  process.exit(1);
}

console.log("Ground-layer mobile contract passed.");
