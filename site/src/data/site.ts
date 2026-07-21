export type NavKey = "home" | "product" | "mobile" | "network" | "privacy" | "support";

export const navItems: Array<{ key: NavKey; label: string; href: string }> = [
  { key: "product", label: "Local Flight", href: "/local-flight/" },
  { key: "mobile", label: "Mobile", href: "/local-flight/mobile/" },
  { key: "network", label: "How It Connects", href: "/network/" },
  { key: "privacy", label: "Privacy", href: "/privacy/" },
  { key: "support", label: "Support", href: "/support/" },
];

export const githubUrl = "https://github.com/tr3y4rch/local-flight";
export const releasesUrl = `${githubUrl}/releases`;
export const currentRelease = "0.5.2";
export const releaseUrl = `${githubUrl}/releases/tag/v${currentRelease}`;
