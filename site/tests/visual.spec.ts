import { test, expect } from "@playwright/test";

const visualRoutes = [
  ["home", "/"],
  ["product", "/local-flight/"],
  ["mobile-product", "/local-flight/mobile/"],
  ["relay-product", "/local-flight/relay-access/"],
  ["network", "/network/"],
  ["privacy", "/privacy/"],
  ["support", "/support/"],
] as const;

for (const theme of ["dark", "light"] as const) {
  for (const [name, route] of visualRoutes) {
    test(`${name} ${theme} visual baseline`, async ({ page }, testInfo) => {
      test.skip(testInfo.project.name !== "desktop");
      await page.clock.setFixedTime(new Date("2026-07-20T12:34:00Z"));
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.route("**/api/releases/latest", async (request) => {
        await request.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ ok: false }) });
      });
      await page.route("**/v1/access/catalog", async (request) => {
        await request.fulfill({
          contentType: "application/json",
          body: JSON.stringify({
            ok: true,
            product: {
              product_code: "beacon_relay_lifetime_v1",
              independent_receivers: 1,
              purchase_sources: {
                stripe: { available: true },
                apple_app: { available: false, testing_available: true, state: "testing", verification_ready: true, included_with_paid_app: true },
                google_play: { available: false, testing_available: true, state: "testing", verification_ready: true, included_with_paid_app: false, acquisition_model: "free_download_in_app_purchase", free_modes: ["companion", "vatsim"] },
              },
            },
            capabilities: { sales: true, schedule: true, radar: true, remote_companion: true },
          }),
        });
      });
      await page.goto(route);
      await page.evaluate(async () => {
        document.querySelectorAll<HTMLImageElement>('img[loading="lazy"]').forEach((image) => { image.loading = "eager"; });
        const viewportStep = Math.max(window.innerHeight - 120, 600);
        for (let position = 0; position < document.documentElement.scrollHeight; position += viewportStep) {
          window.scrollTo(0, position);
          await new Promise<void>((resolve) => setTimeout(resolve, 80));
        }
        window.scrollTo(0, 0);
        await Promise.all([...document.images].map((image) => image.complete
          ? Promise.resolve()
          : new Promise<void>((resolve) => {
              image.addEventListener("load", () => resolve(), { once: true });
              image.addEventListener("error", () => resolve(), { once: true });
            })));
      });
      await expect.poll(() => page.locator("img").evaluateAll((images) => images.every((image) => (image as HTMLImageElement).naturalWidth > 0))).toBe(true);
      await page.locator("img").evaluateAll(async (images) => {
        await Promise.all(images.map((image) => (image as HTMLImageElement).decode().catch(() => undefined)));
      });
      await page.evaluate((selectedTheme) => {
        localStorage.setItem("beacontools.theme", selectedTheme);
        document.documentElement.dataset.theme = selectedTheme;
        document.documentElement.dataset.reduceMotion = "true";
        document.querySelectorAll<HTMLElement>("[data-reveal]").forEach((element) => { element.dataset.visible = "true"; });
      }, theme);
      await expect(page).toHaveScreenshot(`${name}-${theme}.png`, {
        fullPage: true,
        maxDiffPixelRatio: 0.02,
      });
    });
  }
}

const visualLicense = {
  license_ref: "license_visual_mobile",
  purchase_source: "apple_app",
  status: "active",
  key_ref: "LFRA-VISUAL…52XR",
  created_at: "2026-09-01T12:00:00Z",
  receiver: { device_kind: "mobile_standalone", device_name: "Current phone" },
  key_delivery: { state: "sent" },
};

for (const theme of ["dark", "light"] as const) {
  test(`populated Relay management ${theme} visual baseline`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop");
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.route("**/v1/access/magic-links/exchange", (route) => route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ ok: true, holder_session: "lfrhs_visual_session", licenses: [visualLicense] }),
    }));
    await page.goto("/local-flight/relay-access/manage/#token=lfrm_visual_management_token");
    await page.evaluate((selectedTheme) => {
      localStorage.setItem("beacontools.theme", selectedTheme);
      document.documentElement.dataset.theme = selectedTheme;
      document.documentElement.dataset.reduceMotion = "true";
    }, theme);
    await expect(page.locator(".relay-license")).toHaveCount(1);
    await expect(page).toHaveScreenshot(`relay-management-${theme}.png`, { fullPage: true, maxDiffPixelRatio: 0.02 });
  });

  for (const [name, route] of [
    ["relay-product", "/local-flight/relay-access/"],
    ["relay-management", "/local-flight/relay-access/manage/#token=lfrm_visual_management_token"],
  ] as const) {
    test(`${name} ${theme} narrow visual baseline`, async ({ page }, testInfo) => {
      test.skip(testInfo.project.name !== "mobile");
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.route("**/v1/access/catalog", (request) => request.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          product: {
            product_code: "beacon_relay_lifetime_v1",
            independent_receivers: 1,
            purchase_sources: {
              stripe: { available: false },
              apple_app: { available: false, included_with_paid_app: true },
              google_play: { available: false, included_with_paid_app: false, acquisition_model: "free_download_in_app_purchase", free_modes: ["companion", "vatsim"] },
            },
          },
          capabilities: { sales: false, schedule: false, radar: false, remote_companion: false },
        }),
      }));
      await page.route("**/v1/access/magic-links/exchange", (request) => request.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ ok: true, holder_session: "lfrhs_visual_session", licenses: [visualLicense] }),
      }));
      await page.goto(route);
      await page.evaluate((selectedTheme) => {
        localStorage.setItem("beacontools.theme", selectedTheme);
        document.documentElement.dataset.theme = selectedTheme;
        document.documentElement.dataset.reduceMotion = "true";
        document.querySelectorAll<HTMLElement>("[data-reveal]").forEach((element) => { element.dataset.visible = "true"; });
      }, theme);
      await expect(page).toHaveScreenshot(`${name}-${theme}-narrow.png`, { fullPage: true, maxDiffPixelRatio: 0.02 });
    });
  }
}
