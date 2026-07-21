import { test, expect } from "@playwright/test";

const visualRoutes = [
  ["home", "/"],
  ["product", "/local-flight/"],
  ["mobile-product", "/local-flight/mobile/"],
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
