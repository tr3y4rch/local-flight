import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { resolveDeployment } from "../../deployment.mjs";

export type NavKey = "home" | "product" | "mobile" | "relay" | "network" | "privacy" | "support";
export type AvailabilityState = "prelaunch" | "testing" | "live";

export const navItems: Array<{ key: NavKey; label: string; href: string }> = [
  { key: "product", label: "Local Flight", href: "/local-flight/" },
  { key: "mobile", label: "Mobile", href: "/local-flight/mobile/" },
  { key: "relay", label: "Relay Access", href: "/local-flight/relay-access/" },
  { key: "network", label: "How It Connects", href: "/network/" },
  { key: "privacy", label: "Privacy", href: "/privacy/" },
  { key: "support", label: "Support", href: "/support/" },
];

export const githubUrl = "https://github.com/tr3y4rch/local-flight";
export const releasesUrl = `${githubUrl}/releases`;
const projectFile = [
  resolve(process.cwd(), "pyproject.toml"),
  resolve(process.cwd(), "..", "pyproject.toml"),
].find((candidate) => existsSync(candidate));

if (!projectFile) {
  throw new Error("Could not locate pyproject.toml while building the Beacon Tools site");
}

const projectSource = readFileSync(projectFile, "utf8");
const projectVersion = projectSource.match(/^version = "([^"]+)"$/m)?.[1];

if (!projectVersion) {
  throw new Error("pyproject.toml must declare the public Local Flight version");
}

export const candidateRelease = projectVersion;
// Public downloads advance only after the complete signed package matrix is published.
export const currentRelease = "0.6.0";
export const releaseUrl = `${githubUrl}/releases/tag/v${currentRelease}`;
export const relayOrigin = resolveDeployment().relayOrigin;

export const availability = {
  relayAccess: "prelaunch",
  ios: "testing",
  android: "testing",
} as const satisfies Record<string, AvailabilityState>;

export const publicFacts = {
  software: "Local Flight itself remains free and open source.",
  account: "No Beacon Tools account is required for normal Local Flight use.",
  relay: "Beacon Relay is optional paid hosted access for real-flight data.",
  freePaths: "Bring Your Own Keys and VATSIM remain available without Relay Access.",
  receiverRule: "One Relay license can be active on one main device at a time.",
  remotePrivacy: "Remote Companion messages are end-to-end encrypted.",
  diagnostics: "Automatic diagnostics are sent only after you opt in.",
} as const;

export const makerNote = "Local Flight grew from wanting airport-style information on ordinary screens without handing those screens to another cloud account. I wanted the setup, history, and choices to remain close to the person running it—and I did not want advertising, tracking, or cookie strategies to become the business model around it. Beacon Tools is the small home for that work.";

export const paidRelayExplanation = "Local Flight itself remains free and open source. Beacon Relay is paid because an independent hosted service has continuing costs: provider-authorized aviation data, servers, payment and license delivery, abuse protection, and ongoing maintenance. Charging directly helps keep the project sustainable without advertising, tracking, selling usage data, or placing the desktop software behind an account. Bring Your Own Keys and VATSIM remain available without Relay Access.";
