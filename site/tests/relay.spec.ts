import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const relayHtml = readFileSync(new URL("../../relay/public/index.html", import.meta.url), "utf8");

for (const theme of ["dark", "light"] as const) {
  test(`relay landing page is responsive and accessible in ${theme} mode`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
    await page.setContent(relayHtml, { waitUntil: "domcontentloaded" });

    await expect(page.locator("h1")).toHaveText("You’ve reached the Local Flight shared service.");
    await expect(page.getByRole("status")).toContainText("Relay endpoint reached");
    await expect(page.getByRole("link", { name: "/health · JSON" })).toHaveAttribute("href", "/health");
    await expect(page.locator("script")).toHaveCount(0);
    await expect(page.locator("img")).toHaveCount(0);
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", "noindex, nofollow");
    await expect(page.getByRole("link", { name: /See how the shared service works/ })).toHaveAttribute("href", "https://beacontools.cc/network/");
    await expect(page.getByText("Beacon Tools cannot read the request or response.")).toBeVisible();

    const hasHorizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(hasHorizontalOverflow).toBe(false);

    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
  });
}
