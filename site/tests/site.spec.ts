import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const routes = [
  "/",
  "/local-flight/",
  "/local-flight/mobile/",
  "/network/",
  "/privacy/",
  "/privacy/choices/",
  "/support/",
  "/404.html",
];

for (const route of routes) {
  test(`${route} renders with accessible structure`, async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto(route);
    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.locator("main")).toBeVisible();
    await expect(page.locator("footer")).toBeVisible();
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
  });
}

test("theme choice persists locally", async ({ page }) => {
  await page.goto("/");
  const before = await page.locator("html").getAttribute("data-theme");
  await page.locator("[data-theme-toggle]").click();
  const after = before === "dark" ? "light" : "dark";
  await expect(page.locator("html")).toHaveAttribute("data-theme", after);
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", after);
  expect(await page.evaluate(() => localStorage.getItem("beacontools.theme"))).toBe(after);
});

test("mobile navigation opens, closes, and exposes every destination", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile");
  await page.goto("/");
  const toggle = page.locator("[data-menu-toggle]");
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator("[data-site-nav] a")).toHaveCount(6);
  await page.keyboard.press("Escape");
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
});

test("mobile mode switcher is keyboard operable", async ({ page }) => {
  await page.goto("/local-flight/mobile/");
  const companion = page.locator("#tab-companion");
  const standalone = page.locator("#tab-standalone");
  await expect(companion).toHaveAttribute("aria-selected", "true");
  await companion.focus();
  await page.keyboard.press("ArrowRight");
  await expect(standalone).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("#panel-standalone")).toBeVisible();
});

test("responsive product media preserves its intrinsic proportions", async ({ page }) => {
  await page.goto("/local-flight/mobile/");
  const proportions = await page.locator(".phone-composition img").evaluateAll((images) => images.map((image) => {
    const element = image as HTMLImageElement;
    const style = getComputedStyle(element);
    return {
      intrinsic: Number(element.getAttribute("width")) / Number(element.getAttribute("height")),
      rendered: Number.parseFloat(style.width) / Number.parseFloat(style.height),
    };
  }));
  expect(proportions).toHaveLength(2);
  for (const proportion of proportions) {
    expect(proportion.rendered).toBeCloseTo(proportion.intrinsic, 2);
  }
});

test("download board preserves gated package and checksum behavior", async ({ page }) => {
  await page.route("**/api/releases/latest", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        release: {
          version: "0.5.2",
          release_url: "https://github.com/tr3y4rch/local-flight/releases/tag/v0.5.2",
          downloads: {
            windows: {
              filename: "LocalFlight-0.5.2-Setup.exe",
              url: "https://github.com/tr3y4rch/local-flight/releases/download/v0.5.2/LocalFlight-0.5.2-Setup.exe",
              size: 12_345_678,
              checksum_url: "https://github.com/tr3y4rch/local-flight/releases/download/v0.5.2/LocalFlight-0.5.2-Setup.exe.sha256",
            },
          },
        },
      }),
    });
  });
  await page.goto("/local-flight/#downloads");
  const windows = page.locator('[data-download-platform="windows"]');
  await expect(windows.locator("[data-download-button]")).toHaveText("Download");
  await expect(windows.locator("[data-download-checksum]")).toHaveText("Verify download (SHA-256)");
  await expect(windows.locator("[data-download-checksum]")).toBeVisible();
  const mac = page.locator('[data-download-platform="macos_arm64"]');
  await expect(mac.locator("[data-download-button]")).toHaveText("View release files");
  await expect(mac.locator("[data-download-checksum]")).toBeHidden();
});

test("download board fails safely to GitHub Releases", async ({ page }) => {
  await page.route("**/api/releases/latest", (route) => route.abort());
  await page.goto("/local-flight/#downloads");
  await expect(page.locator("[data-release-status]")).toContainText("could not check the downloads");
  await expect(page.locator('[data-download-platform="windows"] [data-download-button]')).toHaveAttribute("href", "https://github.com/tr3y4rch/local-flight/releases");
});

test("download board handles an incomplete release without exposing partial packages", async ({ page }) => {
  await page.route("**/api/releases/latest", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ ok: true, release: null }),
    });
  });
  await page.goto("/local-flight/#downloads");
  await expect(page.locator("[data-release-status]")).toHaveText("The latest release is still waiting for one or more verified downloads.");
  await expect(page.locator('[data-download-platform="windows"] [data-download-button]')).toHaveText("View release files");
  await expect(page.locator('[data-download-platform="windows"] [data-download-checksum]')).toBeHidden();
});

test("support contact form submits only the preserved payload", async ({ page }) => {
  let payload: Record<string, unknown> | undefined;
  await page.route("https://relay.beacontools.cc/v1/site/contact", async (route) => {
    payload = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ ok: true, message: "Message accepted." }) });
  });
  await page.goto("/support/#message");
  const form = page.locator('[data-support-form="contact"]');
  await form.locator('[name="subject"]').fill("Testing support contract");
  await form.locator('[name="message"]').fill("This request is intercepted by Playwright.");
  await form.locator('button[type="submit"]').click();
  await expect(form.locator(".form-status")).toHaveText("Message accepted.");
  expect(payload).toMatchObject({
    category: "general",
    subject: "Testing support contract",
    message: "This request is intercepted by Playwright.",
    website_context: "/support/",
  });
});

test("support bug report preserves the multipart endpoint contract", async ({ page }) => {
  let submittedBody = "";
  await page.route("https://relay.beacontools.cc/v1/site/bug-report", async (route) => {
    submittedBody = route.request().postData() || "";
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ ok: true, message: "Report accepted." }) });
  });
  await page.goto("/support/#bug-report");
  const form = page.locator('[data-support-form="bug"]');
  await form.locator('[name="title"]').fill("Testing bug report contract");
  await form.locator('[name="description"]').fill("This multipart request is intercepted by Playwright.");
  await form.locator('button[type="submit"]').click();
  await expect(form.locator(".form-status")).toHaveText("Report accepted.");
  expect(submittedBody).toContain('name="product"');
  expect(submittedBody).toContain("local-flight");
  expect(submittedBody).toContain('name="website_context"');
  expect(submittedBody).toContain("/support/");
  expect(submittedBody).toContain("Testing bug report contract");
});
