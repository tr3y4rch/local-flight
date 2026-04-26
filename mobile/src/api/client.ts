import type {
  AdminConnections,
  AdminSystem,
  AdminUpdates,
  AirportResult,
  AppConfig,
  AppState,
  Budget,
  ConfigPatch,
  FidsDetailResponse,
  FidsRow,
  FlightHistoryResponse,
  FlightView,
  HistoryDirection,
  HistoryResponse,
  Metar,
  RadarResponse,
  SchedulerRestartResponse
} from "./types";

export class LocalFlightApiError extends Error {
  constructor(message: string, public readonly status?: number) {
    super(message);
    this.name = "LocalFlightApiError";
  }
}

export function normalizeServerUrl(input: string): string {
  const trimmed = input.trim();
  if (!trimmed) {
    return "";
  }

  const withScheme = /^https?:\/\//i.test(trimmed)
    ? trimmed
    : `http://${trimmed}`;

  return withScheme.replace(/\/+$/, "");
}

export function wsUrl(serverUrl: string): string {
  return normalizeServerUrl(serverUrl).replace(/^http/i, "ws") + "/ws";
}

async function fetchJson<T>(serverUrl: string, path: string): Promise<T> {
  const base = normalizeServerUrl(serverUrl);
  if (!base) {
    throw new LocalFlightApiError("Set a Local Flight server URL first.");
  }

  const response = await fetch(`${base}${path}`, {
    headers: { Accept: "application/json" }
  });

  if (!response.ok) {
    throw new LocalFlightApiError(`HTTP ${response.status} for ${path}`, response.status);
  }

  return response.json() as Promise<T>;
}

async function sendJson<T>(
  serverUrl: string,
  path: string,
  body: Record<string, unknown>
): Promise<T> {
  const base = normalizeServerUrl(serverUrl);
  if (!base) {
    throw new LocalFlightApiError("Set a Local Flight server URL first.");
  }

  const response = await fetch(`${base}${path}`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json"
    },
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    let message = `HTTP ${response.status} for ${path}`;
    try {
      const data = (await response.json()) as { detail?: string };
      if (data.detail) {
        message = data.detail;
      }
    } catch {
      // Ignore non-JSON error responses.
    }
    throw new LocalFlightApiError(message, response.status);
  }

  return response.json() as Promise<T>;
}

export function getHealth(serverUrl: string): Promise<AppState> {
  return fetchJson<AppState>(serverUrl, "/api/health");
}

export function getConfig(serverUrl: string): Promise<AppConfig> {
  return fetchJson<AppConfig>(serverUrl, "/api/config");
}

export function getAdminSystem(serverUrl: string): Promise<AdminSystem> {
  return fetchJson<AdminSystem>(serverUrl, "/api/admin/system");
}

export function getConnections(serverUrl: string): Promise<AdminConnections> {
  return fetchJson<AdminConnections>(serverUrl, "/api/admin/connections");
}

export function getUpdates(serverUrl: string): Promise<AdminUpdates> {
  return fetchJson<AdminUpdates>(serverUrl, "/api/admin/updates");
}

export function getBudget(serverUrl: string): Promise<Budget> {
  return fetchJson<Budget>(serverUrl, "/api/admin/budget");
}

export function restartScheduler(serverUrl: string): Promise<SchedulerRestartResponse> {
  return sendJson<SchedulerRestartResponse>(serverUrl, "/api/admin/scheduler/restart", {});
}

export function getMetar(serverUrl: string): Promise<Metar> {
  return fetchJson<Metar>(serverUrl, "/api/metar");
}

export function getFids(
  serverUrl: string,
  view: FlightView,
  limit = 30
): Promise<FidsRow[]> {
  return fetchJson<FidsRow[]>(
    serverUrl,
    `/api/fids?view=${encodeURIComponent(view)}&limit=${limit}`
  );
}

export function getFidsDetail(
  serverUrl: string,
  callsign: string
): Promise<FidsDetailResponse> {
  return fetchJson<FidsDetailResponse>(
    serverUrl,
    `/api/fids/detail?callsign=${encodeURIComponent(callsign)}`
  );
}

export function getHistory(
  serverUrl: string,
  {
    hours = 24,
    direction = "both",
    limit = 100
  }: {
    hours?: number;
    direction?: HistoryDirection;
    limit?: number;
  } = {}
): Promise<HistoryResponse> {
  return fetchJson<HistoryResponse>(
    serverUrl,
    `/api/history?hours=${hours}&direction=${encodeURIComponent(direction)}&limit=${limit}`
  );
}

export function getHistoryFlight(
  serverUrl: string,
  callsign: string,
  days = 7
): Promise<FlightHistoryResponse> {
  return fetchJson<FlightHistoryResponse>(
    serverUrl,
    `/api/history/flight?callsign=${encodeURIComponent(callsign)}&days=${days}`
  );
}

export function getRadar(
  serverUrl: string,
  radiusNm = 20
): Promise<RadarResponse> {
  return fetchJson<RadarResponse>(
    serverUrl,
    `/api/radar?radius_nm=${radiusNm}`
  );
}

export function searchAirports(serverUrl: string, q: string, limit = 8): Promise<AirportResult[]> {
  return fetchJson<AirportResult[]>(
    serverUrl,
    `/api/airports/search?q=${encodeURIComponent(q)}&limit=${limit}`
  );
}

export async function patchConfig(serverUrl: string, patch: ConfigPatch): Promise<AppConfig> {
  const base = normalizeServerUrl(serverUrl);
  if (!base) throw new LocalFlightApiError("Set a Local Flight server URL first.");

  const response = await fetch(`${base}/api/config`, {
    method: "PATCH",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(patch)
  });

  if (!response.ok) {
    let message = `HTTP ${response.status} for /api/config`;
    try {
      const data = (await response.json()) as { detail?: string };
      if (data.detail) message = data.detail;
    } catch { /* ignore */ }
    throw new LocalFlightApiError(message, response.status);
  }
  return response.json() as Promise<AppConfig>;
}

export async function testConnection(serverUrl: string): Promise<boolean> {
  await getHealth(serverUrl);
  return true;
}

export function submitFeedback(
  serverUrl: string,
  input: { title: string; description: string; client_context?: string }
): Promise<{ ok: boolean; url?: string | null }> {
  return sendJson<{ ok: boolean; url?: string | null }>(serverUrl, "/api/feedback", input);
}

export function submitCrashReport(
  serverUrl: string,
  input: { message: string; traceback?: string; context?: string; client_context?: string }
): Promise<{ ok: boolean; url?: string | null }> {
  return sendJson<{ ok: boolean; url?: string | null }>(serverUrl, "/api/feedback/crash", input);
}
