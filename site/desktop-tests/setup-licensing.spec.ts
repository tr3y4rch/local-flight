import { expect, test } from "@playwright/test";

const clientInfo = {
  install_id: "desktop-test-install",
  install_fingerprint: "abc123def456",
  relay_url: "https://relay.beacontools.cc",
  activation_token_present: false,
  activation_token_prefix: "",
  relay_state: "none",
  access_state: "",
  reason_code: "",
  license_reference: "",
  masked_key_reference: "",
  purchase_source: "",
  current_main_device_description: "",
  last_successful_check_time: "",
  master_key_allowed: true,
  provider_keys: {
    aerodatabox_configured: false,
    aviationstack_configured: false,
    adsbexchange_configured: false,
    opensky_configured: false
  },
  config: {
    airport_iata: "ZRH",
    airport_icao: "LSZH",
    timezone: "Europe/Zurich",
    display_name: "Local Flight desktop",
    diagnostics_mode: "manual",
    source: "real",
    data_route: "relay"
  }
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/setup/client-info", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(clientInfo) })
  );
  await page.route("**/api/setup/access/catalog?**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, sales_available: false })
    })
  );
});

async function openDataRoutes(page: import("@playwright/test").Page): Promise<void> {
  await page.goto("/setup");
  await expect(page.locator("#airportSelected")).toContainText("ZRH");
  await page.locator("#nextBtn").click();
  await expect(page.getByRole("heading", { name: "Choose your airport" })).toBeVisible();
  await page.locator("#nextBtn").click();
  await expect(page.getByRole("heading", { name: "Choose how flight data should work" })).toBeVisible();
}

test("keeps the three data routes usable when new Relay sales are unavailable", async ({ page }) => {
  await openDataRoutes(page);

  const routes = page.getByRole("radio");
  await expect(routes).toHaveCount(3);
  await expect(page.getByRole("radio", { name: /Beacon Relay/ })).toBeVisible();
  await expect(page.getByRole("radio", { name: /Bring Your Own Keys/ })).toBeVisible();
  await expect(page.getByRole("radio", { name: /VATSIM/ })).toBeVisible();
  await expect(page.getByRole("link", { name: "Get Relay Access" })).toBeHidden();
  await expect(page.getByText(/New purchases are temporarily unavailable/)).toBeVisible();

  await page.getByRole("radio", { name: /Bring Your Own Keys/ }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("radio", { name: /Bring Your Own Keys/ })).toHaveAttribute("aria-checked", "true");
  await expect(page.locator("#relaySetupBox")).toBeHidden();

  await page.getByRole("radio", { name: /VATSIM/ }).focus();
  await page.keyboard.press("Space");
  await expect(page.getByRole("radio", { name: /VATSIM/ })).toHaveAttribute("aria-checked", "true");
});

test("requires a named confirmation before moving Relay Access", async ({ page }) => {
  const activationBodies: Array<Record<string, unknown>> = [];
  await page.route("**/api/setup/activate", async (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>;
    activationBodies.push(body);
    if (body.confirm_move_token !== "move_once_123") {
      await route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({
          ok: false,
          status: "seat_in_use",
          move_token: "move_once_123",
          current_receiver: { device_kind: "desktop", device_name: "Kitchen board" }
        })
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, status: "active", activation_token_prefix: "lfr_device_" })
    });
  });
  await page.route("**/api/setup/test-activation", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, status: "active", access_state: "active" })
    })
  );

  await openDataRoutes(page);
  await page.locator("#activationToken").fill("LFRA-AAAA-BBBB-CCCC-DDDD");
  await page.getByRole("button", { name: "Activate this desktop" }).click();
  await expect(page.getByRole("alert")).toContainText("Kitchen board");
  await expect(page.getByRole("button", { name: "Move to this desktop" })).toBeVisible();

  await page.locator("#activationToken").fill("LFRA-AAAA-BBBB-CCCC-EEEE");
  await expect(page.getByRole("alert")).toBeHidden();
  await page.getByRole("button", { name: "Activate this desktop" }).click();
  await page.getByRole("button", { name: "Move to this desktop" }).click();

  await expect(page.getByText("Relay Access works on this desktop.")).toBeVisible();
  expect(activationBodies).toHaveLength(3);
  expect(activationBodies[0]?.confirm_move_token).toBe("");
  expect(activationBodies[1]?.confirm_move_token).toBe("");
  expect(activationBodies[2]?.confirm_move_token).toBe("move_once_123");
  expect(activationBodies[2]?.license_key).toBe("LFRA-AAAA-BBBB-CCCC-EEEE");
});
