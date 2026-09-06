import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const routes = [
  "/",
  "/local-flight/",
  "/local-flight/mobile/",
  "/local-flight/relay-access/",
  "/local-flight/relay-access/success/",
  "/local-flight/relay-access/manage/",
  "/local-flight/relay-access/terms/",
  "/network/",
  "/privacy/",
  "/privacy/choices/",
  "/support/",
  "/404.html",
];

for (const route of routes) {
  test(`${route} renders with accessible structure`, async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.route("https://relay.beacontools.cc/v1/access/catalog", (request) => request.fulfill({
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
  await expect(page.locator("[data-site-nav] a")).toHaveCount(7);
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

test("mobile store links follow unavailable, testing, and available catalog states", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop");
  const catalogUrl = "https://relay.beacontools.cc/v1/access/catalog";
  const product = (apple: Record<string, unknown>, google: Record<string, unknown>) => ({
    ok: true,
    product: {
      product_code: "beacon_relay_lifetime_v1",
      independent_receivers: 1,
      purchase_sources: { stripe: { available: false }, apple_app: apple, google_play: google },
    },
    capabilities: { sales: false, schedule: false, radar: false, remote_companion: false },
  });

  await page.route(catalogUrl, (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify(product(
      { state: "available", available: false, store_url: "https://apps.apple.com/app/id123456789" },
      { state: "available", available: false, store_url: "https://play.google.com/store/apps/details?id=cc.beacontools.localflight" },
    )),
  }));
  await page.goto("/local-flight/mobile/#availability");
  await expect(page.locator("#mobileAvailabilityTitle")).toHaveText("Mobile purchase routes are not open yet.");
  await expect(page.locator('[data-mobile-store="apple_app"]')).toHaveAttribute("aria-disabled", "true");

  await page.unroute(catalogUrl);
  await page.route(catalogUrl, (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify(product(
      { state: "testing", verification_ready: true, testing_available: true, testing_url: "https://testflight.apple.com/join/example" },
      { state: "testing", verification_ready: true, testing_available: true, testing_url: "https://play.google.com/apps/testing/cc.beacontools.localflight" },
    )),
  }));
  await page.reload();
  await expect(page.locator("#mobileAvailabilityTitle")).toHaveText("The mobile apps are currently in testing.");
  await expect(page.locator('[data-mobile-store="apple_app"]')).toHaveAttribute("href", "https://testflight.apple.com/join/example");

  await page.unroute(catalogUrl);
  await page.route(catalogUrl, (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify(product(
      { state: "available", available: true, store_url: "https://apps.apple.com/app/id123456789" },
      { state: "available", available: true, store_url: "https://play.google.com/store/apps/details?id=cc.beacontools.localflight" },
    )),
  }));
  await page.reload();
  await expect(page.locator("#mobileAvailabilityTitle")).toHaveText("The mobile apps are available.");
  await expect(page.locator('[data-mobile-store="google_play"]')).toHaveAttribute("href", "https://play.google.com/store/apps/details?id=cc.beacontools.localflight");
  await expect(page.locator('[data-mobile-store="google_play"]')).not.toHaveAttribute("aria-disabled", "true");
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

const relayCatalog = (available: boolean) => ({
  ok: true,
  product: {
    name: "Beacon Relay Access",
    product_code: "beacon_relay_lifetime_v1",
    independent_receivers: 1,
    purchase_sources: {
      stripe: { available },
      apple_app: { available, included_with_paid_app: true },
      google_play: { available, included_with_paid_app: false, acquisition_model: "free_download_in_app_purchase", free_modes: ["companion", "vatsim"] },
    },
  },
  capabilities: {
    sales: available,
    schedule: available,
    radar: available,
    remote_companion: available,
  },
});

test("Relay Access catalog fails closed and enables checkout only when every gate is ready", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop");
  await page.route("https://relay.beacontools.cc/v1/access/catalog", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify(relayCatalog(false)),
  }));
  await page.goto("/local-flight/relay-access/");
  await expect(page.locator("#relayCheckout")).toBeDisabled();
  await expect(page.locator("#accessCatalogStatus")).toContainText("not open yet");

  await page.unroute("https://relay.beacontools.cc/v1/access/catalog");
  const availableCatalog = relayCatalog(true);
  availableCatalog.capabilities.schedule = false;
  await page.route("https://relay.beacontools.cc/v1/access/catalog", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify(availableCatalog),
  }));
  await page.reload();
  await expect(page.locator("#relayCheckout")).toBeEnabled();
  await expect(page.locator("#accessCatalogStatus")).toContainText("ready");
});

test("checkout result covers pending, successful one-time reveal, and failed states", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop");
  await page.goto("/");
  await page.evaluate(() => sessionStorage.setItem("beacon.relay.checkout.checkout_pending", "secret_pending_value_123456789"));
  await page.route("https://relay.beacontools.cc/v1/access/stripe/result", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({ ok: true, state: "pending" }),
  }));
  await page.goto("/local-flight/relay-access/success/?checkout_ref=checkout_pending");
  await expect(page.locator("#resultStatus")).toContainText("waiting for signed confirmation");

  await page.unroute("https://relay.beacontools.cc/v1/access/stripe/result");
  await page.evaluate(() => sessionStorage.setItem("beacon.relay.checkout.checkout_success", "secret_success_value_123456789"));
  await page.route("https://relay.beacontools.cc/v1/access/stripe/result", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({ ok: true, state: "active", license_key: "LFRA-AAAA-BBBB-CCCC-DDDD" }),
  }));
  await page.goto("/local-flight/relay-access/success/?checkout_ref=checkout_success");
  await expect(page.locator("#licenseKey")).toHaveValue("LFRA-AAAA-BBBB-CCCC-DDDD");
  await expect(page.locator("#licenseResult")).toBeVisible();
  expect(await page.evaluate(() => sessionStorage.getItem("beacon.relay.checkout.checkout_success"))).toBeNull();

  await page.unroute("https://relay.beacontools.cc/v1/access/stripe/result");
  await page.evaluate(() => sessionStorage.setItem("beacon.relay.checkout.checkout_failed", "secret_failed_value_123456789"));
  await page.route("https://relay.beacontools.cc/v1/access/stripe/result", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({ ok: true, state: "failed" }),
  }));
  await page.goto("/local-flight/relay-access/success/?checkout_ref=checkout_failed");
  await expect(page.locator("#resultStatus")).toContainText("did not complete");
  await expect(page.locator("#licenseResult")).toBeHidden();
});

test("fragment email confirmation reveals one existing key and lists separate licenses", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop");
  await page.route("https://relay.beacontools.cc/v1/access/magic-links/exchange", async (route) => {
    expect(route.request().postDataJSON()).toEqual({ token: "lfrm_test_email_confirmation_token" });
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        holder_session: "lfrhs_verified_holder_session",
        key_delivery: { license_key: "LFRA-MOBILE-EXISTING-KEY1", one_time: true },
        licenses: [
          {
            license_ref: "license_mobile_1",
            product_name: "Beacon Relay Access",
            purchase_source: "apple_app",
            status: "active",
            key_ref: "LFRA-MOBILE…KEY1",
            created_at: "2026-09-01T12:00:00Z",
            receiver: { device_kind: "mobile_standalone", device_name: "Philipp’s iPhone" },
            key_delivery: { state: "revealed" },
          },
          {
            license_ref: "license_web_2",
            product_name: "Beacon Relay Access",
            purchase_source: "stripe",
            status: "active",
            key_ref: "LFRA-WEB…KEY2",
            created_at: "2026-09-02T12:00:00Z",
            receiver: null,
            key_delivery: { state: "sent" },
          },
        ],
      }),
    });
  });
  await page.goto("/local-flight/relay-access/manage/#token=lfrm_test_email_confirmation_token");
  await expect(page).toHaveURL(/\/local-flight\/relay-access\/manage\/$/);
  await expect(page.locator(".relay-license")).toHaveCount(2);
  await expect(page.locator("#managementLicenseKey")).toHaveValue("LFRA-MOBILE-EXISTING-KEY1");
  await expect(page.getByText("IOS / APP STORE")).toBeVisible();
  await expect(page.getByText("WEB / STRIPE")).toBeVisible();
  await expect(page.getByText("Mobile Standalone · Philipp’s iPhone")).toBeVisible();
});

test("management grants require the target flow and receiver actions return fresh state", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop");
  const activeLicense = {
    license_ref: "license_web_1",
    purchase_source: "stripe",
    status: "active",
    key_ref: "LFRA-WEB…0001",
    created_at: "2026-09-01T12:00:00Z",
    receiver: { device_kind: "desktop", device_name: "Office display" },
  };
  await page.route("https://relay.beacontools.cc/v1/access/magic-links/exchange", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({ ok: true, holder_session: "lfrhs_verified_holder_session", licenses: [activeLicense] }),
  }));
  await page.route("https://relay.beacontools.cc/v1/access/activation-grants", async (route) => {
    expect(route.request().headers().authorization).toBe("Bearer lfrhs_verified_holder_session");
    expect(route.request().postDataJSON()).toEqual({ license_id: "license_web_1" });
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ ok: true, activation_grant: "lfrag_one_use_transfer_grant", expires_in: 600 }) });
  });
  await page.goto("/local-flight/relay-access/manage/#token=lfrm_action_test_token_value");
  const card = page.locator(".relay-license");
  await card.getByRole("button", { name: "Create mobile handoff" }).click();
  await expect(card.getByText("Fresh iOS entitlement or Android official-app proof is still required on the receiving device.")).toBeVisible();
  await expect(card.getByRole("link", { name: "Open in Local Flight Mobile" })).toHaveAttribute("href", "localflight://relay-access#grant=lfrag_one_use_transfer_grant");

  page.on("dialog", (dialog) => dialog.accept());
  await page.route("https://relay.beacontools.cc/v1/access/licenses/action", async (route) => {
    const body = route.request().postDataJSON() as { action: string };
    if (body.action === "revoke_receiver") {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ ok: true, licenses: [{ ...activeLicense, receiver: null }] }),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        license_key: "LFRA-ROTATED-SAVE-0002",
        licenses: [{ ...activeLicense, receiver: null, key_ref: "LFRA-ROTATED…0002" }],
      }),
    });
  });
  await card.getByRole("button", { name: "Release current main device" }).click();
  await expect(page.getByText("Available — no active main device")).toBeVisible();
  await page.locator(".relay-license").getByRole("button", { name: "Rotate a lost key" }).click();
  await expect(page.locator("#managementLicenseKey")).toHaveValue("LFRA-ROTATED-SAVE-0002");
});
