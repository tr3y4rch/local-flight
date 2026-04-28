import { normalizeServerUrl, submitCrashReport } from "../api/client";
import { getCompanionIdentity } from "../device/identity";
import { loadServerUrl } from "../storage/settings";

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

function shouldSkipRecent(fp: string): boolean {
  const now = Date.now();
  const previous = RECENT_REPORTS.get(fp);
  if (previous && now - previous < DEDUPE_WINDOW_MS) {
    return true;
  }
  RECENT_REPORTS.set(fp, now);

  for (const [key, ts] of RECENT_REPORTS.entries()) {
    if (now - ts > DEDUPE_WINDOW_MS) {
      RECENT_REPORTS.delete(key);
    }
  }
  return false;
}

async function postCrash(input: CrashInput): Promise<void> {
  const serverUrl = normalizeServerUrl(await loadServerUrl());
  if (!serverUrl) return;

  const fp = fingerprint(input);
  if (shouldSkipRecent(fp)) return;

  try {
    const identity = await getCompanionIdentity();
    await submitCrashReport(serverUrl, {
      ...input,
      client_context:
        input.client_context ||
        [
          `Reporter      ${identity.clientName}`,
          `Companion ID  ${identity.companionId}`,
          `App version   ${identity.appVersion}`,
          `Companion OS  ${identity.mobileOs}`,
          `Server URL    ${serverUrl}`
        ].join("\n")
    });
  } catch {
    // Crash reporting is always best-effort on the mobile side.
  }
}

export async function reportMobileCrash(input: CrashInput): Promise<void> {
  await postCrash(input);
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
