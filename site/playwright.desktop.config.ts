import { defineConfig, devices } from "@playwright/test";
import { existsSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const siteRoot = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(siteRoot, "..");
const isolatedHome = mkdtempSync(path.join(tmpdir(), "localflight-desktop-wizard-"));
const localPython = path.join(repositoryRoot, ".venv", "bin", "python");
const python = process.env.LOCALFLIGHT_DESKTOP_TEST_PYTHON || (existsSync(localPython) ? localPython : "python");

export default defineConfig({
  testDir: path.join(siteRoot, "desktop-tests"),
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  outputDir: path.join(siteRoot, "test-results", "desktop-wizard"),
  use: {
    baseURL: "http://127.0.0.1:4323",
    trace: "on-first-retry",
    screenshot: "only-on-failure"
  },
  webServer: {
    command: `"${python}" -m uvicorn localflight.ui.server:app --host 127.0.0.1 --port 4323`,
    url: "http://127.0.0.1:4323/setup",
    reuseExistingServer: false,
    timeout: 30_000,
    env: {
      ...process.env,
      LOCALFLIGHT_HOME: isolatedHome,
      LOCALFLIGHT_GUI_MODE: "browser",
      PYTHONPATH: path.join(repositoryRoot, "src")
    }
  },
  projects: [
    {
      name: "compact",
      use: { ...devices["Desktop Chrome"], viewport: { width: 820, height: 900 } }
    },
    {
      name: "wide",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } }
    }
  ]
});
