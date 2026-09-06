import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const siteRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = path.join(siteRoot, "dist");
const projectSource = fs.readFileSync(path.join(siteRoot, "..", "pyproject.toml"), "utf8");
const projectVersion = projectSource.match(/^version = "([^"]+)"$/m)?.[1];
assert.ok(projectVersion, "pyproject.toml must declare the public release version");
const routes = [
  "index.html",
  "local-flight/index.html",
  "local-flight/mobile/index.html",
  "local-flight/relay-access/index.html",
  "local-flight/relay-access/success/index.html",
  "local-flight/relay-access/manage/index.html",
  "local-flight/relay-access/terms/index.html",
  "network/index.html",
  "privacy/index.html",
  "privacy/choices/index.html",
  "support/index.html",
  "404.html",
];

const builtPages = new Map();

function visibleText(html) {
  return html
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, " ")
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&(?:#39|apos);/g, "'")
    .replace(/&(?:#x27|#x2019|#8217);/gi, "’")
    .replace(/\s+/g, " ")
    .trim();
}

for (const route of routes) {
  const file = path.join(dist, route);
  assert.ok(fs.existsSync(file), `Missing built route: ${route}`);
  const html = fs.readFileSync(file, "utf8");
  builtPages.set(route, html);
  assert.match(html, /<title>[^<]+<\/title>/, `${route} must have a title`);
  assert.equal((html.match(/<h1(?:\s|>)/g) || []).length, 1, `${route} must have one h1`);
  assert.match(html, /href="\/assets\/favicon\.ico"/);
  assert.match(html, /data-theme-toggle/);
  assert.doesNotMatch(html, /fonts\.(googleapis|gstatic)\.com/);
  assert.doesNotMatch(html, /(google-analytics|googletagmanager|segment\.com|plausible\.io)/);
}

for (const [route, html] of builtPages) {
  const routePath = route.endsWith("index.html") ? `/${route.slice(0, -"index.html".length)}` : `/${route}`;
  for (const match of html.matchAll(/<a\b[^>]*href="([^"]+)"/g)) {
    const href = match[1];
    if (!href || href.startsWith("mailto:") || href.startsWith("tel:")) continue;
    const url = new URL(href, `https://beacontools.cc${routePath}`);
    if (url.origin !== "https://beacontools.cc") continue;
    const relativeTarget = decodeURIComponent(url.pathname).replace(/^\//, "");
    const builtTarget = url.pathname.endsWith("/")
      ? path.join(dist, relativeTarget, "index.html")
      : path.join(dist, relativeTarget);
    assert.ok(fs.existsSync(builtTarget), `${route} has a broken internal link: ${href}`);
    if (url.hash && builtTarget.endsWith(".html")) {
      const targetHtml = fs.readFileSync(builtTarget, "utf8");
      const anchor = decodeURIComponent(url.hash.slice(1));
      assert.ok(
        targetHtml.includes(`id="${anchor}"`) || targetHtml.includes(`name="${anchor}"`),
        `${route} links to a missing anchor: ${href}`,
      );
    }
  }
}

const pageText = Object.fromEntries([...builtPages].map(([route, html]) => [route, visibleText(html)]));
const allSiteText = Object.values(pageText).join(" ");

const managementRoute = "local-flight/relay-access/manage/index.html";
const publicRoutes = routes.filter((route) => route !== managementRoute);

for (const route of publicRoutes) {
  const text = pageText[route];
  assert.match(text, /How It Connects/, `${route} must use the plain-language network label`);
  assert.doesNotMatch(text, /\b0\.2\.7\b/, `${route} must not carry the retired release number`);
  const html = builtPages.get(route);
  const navigation = html?.match(/<nav\b[^>]*data-site-nav[\s\S]*?<\/nav>/)?.[0] || "";
  assert.match(navigation, />How It Connects</, `${route} must render the shared destination navigation`);
  assert.match(navigation, />Relay Access</, `${route} must link the universal Relay product`);
  assert.doesNotMatch(navigation, />\s*(?:Home|Network)\s*</, `${route} must not render a legacy navigation label`);
  assert.match(html, /data-menu-toggle/);
  assert.match(html, /data-clock="utc"/);
  assert.match(html, /data-clock="local"/);
  assert.match(html, new RegExp(`data-site-release="${projectVersion}"`));
}

const managementHtml = builtPages.get(managementRoute);
assert.doesNotMatch(managementHtml, /data-site-nav|data-menu-toggle|data-clock=/);
assert.match(managementHtml, /name="robots" content="noindex, nofollow"/);
assert.match(managementHtml, /name="referrer" content="no-referrer"/);
assert.doesNotMatch(managementHtml, /href="\/local-flight\/relay-access\/"|apps\.apple\.com|play\.google\.com|stripe\.com/);

assert.doesNotMatch(allSiteText, /Community Relay/i, "Current public pages must use Beacon Relay");
assert.match(pageText["index.html"], /Your flight board\. Every screen, one ecosystem\./);
assert.match(pageText["index.html"], /Desktop free and open source · Android Companion \+ VATSIM free · One Relay license per purchase · No subscription/);
assert.match(pageText["index.html"], /Stripe, a verified Apple app entitlement, and the Android in-app product all create the same kind of portable Beacon Relay license/);
assert.match(pageText["local-flight/index.html"], /Build your own airport-style flight board\./);
assert.match(pageText["local-flight/index.html"], new RegExp(`Current version: ${projectVersion.replaceAll(".", "\\.")}\\.`));
assert.match(
  builtPages.get("local-flight/index.html"),
  new RegExp(`href="https://github\\.com/tr3y4rch/local-flight/releases/tag/v${projectVersion.replaceAll(".", "\\.")}"`),
  "The product page must link to the same release it displays",
);
assert.match(pageText["local-flight/index.html"], /airport-style arrivals and departures board \(FIDS\)/);
assert.match(pageText["local-flight/index.html"], /live aircraft position data \(ADS-B\)/);
assert.match(pageText["local-flight/index.html"], /Beacon Relay.*Bring Your Own Keys.*VATSIM/);
assert.match(pageText["local-flight/index.html"], /Only Beacon Relay needs a Relay Access license/);
assert.match(pageText["local-flight/mobile/index.html"], /Take your flight board with you\./);
assert.match(pageText["local-flight/mobile/index.html"], /Two store models\. The same portable Relay license\./);
assert.match(pageText["local-flight/mobile/index.html"], /paid iOS app includes Relay Access/);
assert.match(pageText["local-flight/mobile/index.html"], /Android is a free download with an optional one-time Relay purchase/);
assert.match(pageText["local-flight/mobile/index.html"], /Companion and VATSIM work without buying Relay Access/);
assert.match(pageText["local-flight/mobile/index.html"], /Checking current mobile availability\./);
assert.match(pageText["local-flight/mobile/index.html"], /Ask about mobile availability/);
assert.match(builtPages.get("local-flight/mobile/index.html"), /\/v1\/access\/catalog/);
assert.match(builtPages.get("local-flight/mobile/index.html"), /data-mobile-store="apple_app"/);
assert.match(builtPages.get("local-flight/mobile/index.html"), /data-mobile-store="google_play"/);
assert.match(pageText["local-flight/mobile/index.html"], /About 1 h Real-world schedules/);
assert.match(pageText["local-flight/mobile/index.html"], /Between checks Saved board view/);
assert.doesNotMatch(pageText["local-flight/mobile/index.html"], /saved board is re-evaluated every five minutes/i);
assert.match(pageText["local-flight/mobile/index.html"], /About 3 min Real-world Radar/);
assert.match(pageText["local-flight/mobile/index.html"], /About 1 min VATSIM mode/);
assert.doesNotMatch(pageText["local-flight/mobile/index.html"], /Three-hour boards and five-minute visible radar updates/);
assert.match(pageText["local-flight/relay-access/index.html"], /one active main device/);
assert.match(pageText["local-flight/relay-access/index.html"], /Beacon Relay.*Bring Your Own Keys.*VATSIM/);
assert.equal(
  (builtPages
    .get("local-flight/relay-access/index.html")
    .match(/<article class="acquisition-card" data-purchase-source=/g) || []).length,
  3,
);
assert.match(builtPages.get("local-flight/relay-access/index.html"), /\/v1\/access\/catalog/);
assert.match(pageText["local-flight/relay-access/index.html"], /A portable Relay license does not purchase an app from another store/);
assert.match(pageText["local-flight/relay-access/success/index.html"], /Your universal Relay Access key/);
assert.match(pageText["local-flight/relay-access/success/index.html"], /The key never goes into the app/);
assert.match(pageText[managementRoute], /Manage a license without an account\./);
assert.match(pageText[managementRoute], /no checkout, pricing, or app-store links/i);
assert.match(managementHtml, /window\.location\.hash/);
assert.doesNotMatch(managementHtml, /searchParams\.get\(["']token["']\)|\?token=/);
assert.match(managementHtml, /\/v1\/access\/magic-links\/exchange/);
assert.match(managementHtml, /\/v1\/access\/activation-grants/);
assert.match(managementHtml, /\/v1\/access\/licenses\/action/);
assert.match(managementHtml, /localflight:\/\/relay-access#grant=/);
assert.doesNotMatch(managementHtml, /localflight:\/\/relay-access\?(?:grant|activation_grant)=/);
assert.match(pageText["local-flight/relay-access/terms/index.html"], /Non-expiring access—not a promise that a hosted service lasts forever\./);
assert.match(pageText["local-flight/relay-access/terms/index.html"], /Buying more than once creates additional separate licenses/);
assert.match(pageText["local-flight/relay-access/terms/index.html"], /A purchase never overrides a provider contract/);
assert.match(pageText["network/index.html"], /Most of Local Flight stays on your network\./);
assert.match(pageText["network/index.html"], /home or local network \(LAN\)/);
assert.match(pageText["network/index.html"], /Beacon Tools cannot read the message\./);
assert.match(pageText["privacy/index.html"], /Your setup is yours\. Your choices stay clear\./);
assert.match(pageText["privacy/index.html"], /Remote Companion messages are end-to-end encrypted\./);
assert.match(pageText["privacy/index.html"], /Automatic crash reports run only after you opt in\./);
assert.match(pageText["privacy/index.html"], /They unlock nothing and create no lasting paid entitlement\./);
assert.match(pageText["privacy/index.html"], /one active main device/);
assert.match(pageText["privacy/index.html"], /keyed one-way email lookup plus encrypted material/);
assert.doesNotMatch(allSiteText, /paid Android app|paid iOS or Android app/i);
assert.match(pageText["privacy/index.html"], /notification outbox keeps masked references and delivery state/);
assert.match(pageText["privacy/index.html"], /reconcile it against Apple’s signed server response/);
assert.match(pageText["privacy/index.html"], /Purchases and in-app payments \(IAP\)\./);
assert.match(pageText["privacy/index.html"], /Apple transaction ID or Google purchase token/);
assert.match(pageText["privacy/index.html"], /keyed one-way hash and short reference/);
assert.match(pageText["privacy/index.html"], /does not retain the raw Apple transaction ID/);
assert.match(pageText["privacy/index.html"], /use every Local Flight feature without making a support purchase/);
assert.match(pageText["support/index.html"], /Tell us what you’re trying to do\./);
assert.match(pageText["support/index.html"], /You don’t need the technical name\./);
assert.match(pageText["404.html"], /That page isn’t on the board\./);

const safetyText = [
  pageText["index.html"],
  pageText["local-flight/index.html"],
  pageText["local-flight/mobile/index.html"],
  pageText["network/index.html"],
  pageText["support/index.html"],
].join(" ");
assert.match(safetyText, /For display and hobby use only\./);
for (const prohibitedUse of ["navigation", "dispatch", "operational control", "flight planning", "professional aviation work", "safety decisions"]) {
  assert.match(safetyText, new RegExp(prohibitedUse));
}

for (const disallowedTerm of ["bounded", "cadence", "envelope", "platform-wide line"]) {
  assert.doesNotMatch(allSiteText, new RegExp(`\\b${disallowedTerm}\\b`, "i"), `Public copy must not introduce “${disallowedTerm}” without plain-language context`);
}

const product = fs.readFileSync(path.join(dist, "local-flight/index.html"), "utf8");
const platforms = [
  "windows",
  "macos_arm64",
  "macos_x86_64",
  "linux_appimage_x86_64",
  "linux_appimage_aarch64",
  "linux_deb_desktop_amd64",
  "linux_deb_desktop_arm64",
  "linux_deb_server_amd64",
  "linux_deb_server_arm64",
  "pi",
];
assert.equal((product.match(/data-download-platform=/g) || []).length, platforms.length);
for (const platform of platforms) assert.match(product, new RegExp(`data-download-platform="${platform}"`));
assert.match(product, /data-release-status/);
assert.match(product, /data-download-checksum/);

const support = fs.readFileSync(path.join(dist, "support/index.html"), "utf8");
for (const field of ["category", "name", "reply_email", "subject", "message", "surface", "app_version", "platform", "product", "title", "description", "steps", "expected", "actual", "logs"]) {
  assert.match(support, new RegExp(`name="${field}"`), `Support field ${field} must remain available`);
}
assert.equal((support.match(/data-support-form=/g) || []).length, 2);

const themeSource = fs.readFileSync(path.join(siteRoot, "src/layouts/SiteLayout.astro"), "utf8");
assert.match(themeSource, /beacontools\.theme/);
assert.match(themeSource, /saved === "light" \|\| saved === "dark"/);

const relayHtml = fs.readFileSync(path.join(siteRoot, "..", "relay", "public", "index.html"), "utf8");
const relayText = visibleText(relayHtml);
assert.match(relayText, /You’ve reached the Local Flight shared service\./);
assert.match(relayText, /Beacon Relay serves licensed Local Flight receivers/);
assert.match(relayText, /It is not a live flight-tracking website\./);
assert.match(relayText, /See how the shared service works/);
assert.match(relayText, /Beacon Tools cannot read the request or response\./);
assert.doesNotMatch(relayText, /\b(?:bounded|cadence|envelope|surface)\b/i);

console.log("Beacon Tools static-site contract passed.");
