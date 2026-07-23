import { getConfig, normalizeServerUrl, submitCrashReport } from "../api/client";
import { submitStandaloneCrash } from "../api/standalone";
import { getCompanionIdentity } from "../device/identity";
import { loadMobileDiagnosticsMode, loadMobileSetupState, loadServerUrl } from "../storage/settings";

type ErrorUtilsHandler = (error: Error, isFatal?: boolean) => void;

type ErrorUtilsShape = {
  getGlobalHandler?: () => ErrorUtilsHandler | undefined;
  setGlobalHandler?: (handler: ErrorUtilsHandler, allowInDev?: boolean) => void;
};

type CrashInput = {
  message: string;
  traceback?: string;
  context: string;
  client_context?: string;
};

const RECENT_REPORTS = new Map<string, number>();
const DEDUPE_WINDOW_MS = 10 * 60 * 1000;

let installed = false;

function fingerprint(input: CrashInput): string {
  return `${input.context}|${input.message}|${input.traceback?.slice(0, 200) || ""}`;
}

function pruneRecent(now: number): void {
  for (const [key, ts] of RECENT_REPORTS.entries()) {
    if (now - ts > DEDUPE_WINDOW_MS) {
      RECENT_REPORTS.delete(key);
    }
  }
}

function hasRecent(fp: string): boolean {
  const now = Date.now();
  pruneRecent(now);
  const previous = RECENT_REPORTS.get(fp);
  return Boolean(previous && now - previous < DEDUPE_WINDOW_MS);
}

function rememberRecent(fp: string): void {
  const now = Date.now();
  pruneRecent(now);
  RECENT_REPORTS.set(fp, now);
}

async function mobileCrashContext(serverUrl: string, mobileDiagnosticsMode: string, extraContext = ""): Promise<string> {
  const identity = await getCompanionIdentity();
  const base = [
    `Reporter      ${identity.clientName}`,
    `Mobile ID     ${identity.companionId}`,
    `App version   ${identity.appVersion}`,
    `Mobile OS     ${identity.mobileOs}`,
    `Device type   ${identity.deviceType}`,
    `Mobile diag   ${mobileDiagnosticsMode}`,
    `Server URL    ${serverUrl}`
  ].join("\n");
  return extraContext.trim() ? `${base}\n\n${extraContext.trim()}` : base;
}

async function postStandaloneCrash(input: CrashInput): Promise<boolean> {
  const setup = await loadMobileSetupState();
  if (
    setup.mode !== "standalone" ||
    !setup.relayInstallId ||
    !setup.relayActivationToken ||
    !setup.standaloneAirport
  ) {
    return false;
  }
  const mobileDiagnosticsMode = await loadMobileDiagnosticsMode();
  if (!(mobileDiagnosticsMode === "auto" || mobileDiagnosticsMode === "auto_logs")) {
    return false;
  }
  const fp = fingerprint(input);
  if (hasRecent(fp)) return false;
  rememberRecent(fp);
  await submitStandaloneCrash(
    {
      installId: setup.relayInstallId,
      activationToken: setup.relayActivationToken,
      airport: setup.standaloneAirport,
      source: setup.standaloneSource || "real",
      diagnosticsMode: mobileDiagnosticsMode
    },
    {
      ...input,
      context: input.context || "mobile_standalone/crash",
      client_context: await mobileCrashContext("standalone-relay", mobileDiagnosticsMode, input.client_context)
    }
  );
  return true;
}

async function postCrash(input: CrashInput): Promise<boolean> {
  try {
    const setup = await loadMobileSetupState();
    if (setup.mode === "standalone") {
      return await postStandaloneCrash(input);
    }

    const serverUrl = normalizeServerUrl(await loadServerUrl());
    if (!serverUrl) return false;

    const fp = fingerprint(input);

    const mobileDiagnosticsMode = await loadMobileDiagnosticsMode();
    if (!(mobileDiagnosticsMode === "auto" || mobileDiagnosticsMode === "auto_logs")) {
      return false;
    }

    const cfg = await getConfig(serverUrl);
    const diagnosticsMode = String(cfg.diagnostics_mode || "unset").trim().toLowerCase();
    if (!(diagnosticsMode === "auto" || diagnosticsMode === "auto_logs")) {
      return false;
    }

    if (hasRecent(fp)) return false;
    rememberRecent(fp);

    await submitCrashReport(serverUrl, {
      ...input,
      client_context: await mobileCrashContext(serverUrl, mobileDiagnosticsMode, input.client_context)
    });
    return true;
  } catch {
    // Crash reporting is always best-effort on the mobile side.
    return false;
  }
}

export async function reportMobileCrash(input: CrashInput): Promise<boolean> {
  return postCrash(input);
}

export function installGlobalCrashReporter(): void {
  if (installed) return;
  installed = true;

  const globalWithErrorUtils = globalThis as typeof globalThis & {
    ErrorUtils?: ErrorUtilsShape;
  };

  const errorUtils = globalWithErrorUtils.ErrorUtils;
  if (!errorUtils?.setGlobalHandler) {
    return;
  }

  const previous = errorUtils.getGlobalHandler?.();

  errorUtils.setGlobalHandler((error, isFatal) => {
    void postCrash({
      message: `${error.name || "Error"}: ${error.message || "Unknown mobile error"}`,
      traceback: error.stack || "",
      context: isFatal ? "mobile/global-fatal" : "mobile/global"
    });

    previous?.(error, isFatal);
  }, true);
}
