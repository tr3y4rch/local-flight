import type {
  AdminConnections,
  AdminSystem,
  AdminUpdates,
  AirportResolved,
  AirportResult,
  AppConfig,
  AppState,
  Budget,
  ConfigPatch,
  DocDocument,
  FidsDetailResponse,
  FidsRow,
  FlightHistoryResponse,
  FlightView,
  HistoryDirection,
  HistoryResponse,
  MatrixRuntimeConfig,
  MatrixRuntimeConfigSave,
  MatrixRuntimeConfigSaveResponse,
  Metar,
  RadarMapResponse,
  RadarResponse,
  RadarSurfaceResponse,
  RequestLogResponse,
  SchedulerRestartResponse
} from "./types";
import { getCompanionIdentity } from "../device/identity";

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

async function companionHeaders(): Promise<Record<string, string>> {
  const identity = await getCompanionIdentity();
  return {
    "X-LocalFlight-Client-Name": identity.clientName,
    "X-LocalFlight-Client-Type": "mobile-companion",
    "X-LocalFlight-Companion-Id": identity.companionId,
    "X-LocalFlight-Client-Platform": identity.mobileOs,
    "X-LocalFlight-Device-Type": identity.deviceType,
    "X-LocalFlight-App-Version": identity.appVersion
  };
}

async function fetchJson<T>(serverUrl: string, path: string): Promise<T> {
  const base = normalizeServerUrl(serverUrl);
  if (!base) {
    throw new LocalFlightApiError("Set a Local Flight server URL first.");
  }

  const headers = await companionHeaders();
  const response = await fetch(`${base}${path}`, {
    headers: { Accept: "application/json", ...headers }
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

  const headers = await companionHeaders();
  const response = await fetch(`${base}${path}`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...headers
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

export async function getRootHealth(serverUrl: string): Promise<{ ok: boolean }> {
  const base = normalizeServerUrl(serverUrl);
  if (!base) {
    throw new LocalFlightApiError("Set a Local Flight server URL first.");
  }

  const response = await fetch(`${base}/health`, {
    headers: { Accept: "application/json" }
  });
  if (!response.ok) {
    throw new LocalFlightApiError(`HTTP ${response.status} for /health`, response.status);
  }

  try {
    return (await response.json()) as { ok: boolean };
  } catch {
    throw new LocalFlightApiError("Local Flight answered /health, but it did not return JSON.");
  }
}

export async function testCompanionSetupServer(serverUrl: string): Promise<{
  normalizedUrl: string;
  state: AppState;
  config: AppConfig;
}> {
  const normalizedUrl = normalizeServerUrl(serverUrl);
  await getRootHealth(normalizedUrl);

  try {
    const [state, config] = await Promise.all([
      getHealth(normalizedUrl),
      getConfig(normalizedUrl)
    ]);
    return { normalizedUrl, state, config };
  } catch {
    throw new LocalFlightApiError(
      "Local Flight answered /health, but setup APIs are not ready. Finish Local Flight setup on the desktop/Pi first, then return here."
    );
  }
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

export function getDoc(serverUrl: string, slug: string): Promise<DocDocument> {
  return fetchJson<DocDocument>(serverUrl, `/api/docs/${encodeURIComponent(slug)}`);
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
    limit = 100,
    callsign = "",
    airline_iata = ""
  }: {
    hours?: number;
    direction?: HistoryDirection;
    limit?: number;
    callsign?: string;
    airline_iata?: string;
  } = {}
): Promise<HistoryResponse> {
  const p = new URLSearchParams({ hours: String(hours), direction, limit: String(limit) });
  if (callsign) p.set("callsign", callsign.toUpperCase());
  if (airline_iata) p.set("airline_iata", airline_iata.toUpperCase());
  return fetchJson<HistoryResponse>(serverUrl, `/api/history?${p}`);
}

export function getHistorySummary(
  serverUrl: string,
  {
    hours = 24,
    direction = "both",
    callsign = "",
    airline_iata = ""
  }: {
    hours?: number;
    direction?: HistoryDirection;
    callsign?: string;
    airline_iata?: string;
  } = {}
): Promise<import("./types").HistorySummary> {
  const p = new URLSearchParams({ hours: String(hours), direction });
  if (callsign) p.set("callsign", callsign.toUpperCase());
  if (airline_iata) p.set("airline_iata", airline_iata.toUpperCase());
  return fetchJson(serverUrl, `/api/history/summary?${p}`);
}

export function getHistoryStats(serverUrl: string): Promise<import("./types").HistoryStats> {
  return fetchJson(serverUrl, "/api/history/stats");
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

export function getRadarMap(
  serverUrl: string,
  radiusNm = 20
): Promise<RadarMapResponse> {
  return fetchJson<RadarMapResponse>(
    serverUrl,
    `/api/radar/map?radius_nm=${radiusNm}&terrain=false`
  );
}

export function getRadarSurface(
  serverUrl: string,
  radiusNm = 5
): Promise<RadarSurfaceResponse> {
  const surfaceRadius = Math.max(1, Math.min(5, radiusNm));
  return fetchJson<RadarSurfaceResponse>(
    serverUrl,
    `/api/radar/surface?radius_nm=${surfaceRadius}`
  );
}

function radarMapFromSurface(surface: RadarSurfaceResponse, radiusNm: number): RadarMapResponse {
  const features = surface.features || [];
  const runways = features.filter((feature) => String(feature.kind || "").toLowerCase() === "runway");
  const surfaceFeatures = features.filter((feature) => String(feature.kind || "").toLowerCase() !== "runway");
  const attribution = surface.attribution ? [surface.attribution] : [];

  return {
    center: surface.center,
    radius_nm: radiusNm,
    schema_version: "radar-map-surface-fallback-v1",
    runways,
    surface_features: surfaceFeatures,
    map_features: [],
    attribution,
    sources: {
      runways: runways.length ? "surface-fallback" : "none",
      surface: surface.provider || "surface-fallback",
      surface_cache_state: surface.cache_state || "unknown",
      map: "none",
      map_cache_state: "fallback"
    },
    confidence: {
      runway_count: runways.length,
      surface_feature_count: surfaceFeatures.length,
      fallback: "surface"
    }
  };
}

export async function getRadarGround(
  serverUrl: string,
  radiusNm = 20
): Promise<RadarMapResponse> {
  try {
    return await getRadarMap(serverUrl, radiusNm);
  } catch {
    return radarMapFromSurface(await getRadarSurface(serverUrl, Math.min(5, radiusNm)), radiusNm);
  }
}

export function getMatrixConfig(serverUrl: string): Promise<MatrixRuntimeConfig> {
  return fetchJson<MatrixRuntimeConfig>(serverUrl, "/api/matrix/config");
}

export async function saveMatrixConfig(
  serverUrl: string,
  body: MatrixRuntimeConfigSave
): Promise<MatrixRuntimeConfigSaveResponse> {
  const base = normalizeServerUrl(serverUrl);
  if (!base) {
    throw new LocalFlightApiError("Set a Local Flight server URL first.");
  }

  const headers = await companionHeaders();
  const response = await fetch(`${base}/api/matrix/config`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...headers
    },
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    let message = `HTTP ${response.status} for /api/matrix/config`;
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

  return response.json() as Promise<MatrixRuntimeConfigSaveResponse>;
}

export function searchAirports(serverUrl: string, q: string, limit = 8): Promise<AirportResult[]> {
  return fetchJson<AirportResult[]>(
    serverUrl,
    `/api/airports/search?q=${encodeURIComponent(q)}&limit=${limit}`
  );
}

export function resolveAirport(serverUrl: string, q: string): Promise<AirportResolved> {
  return fetchJson<AirportResolved>(
    serverUrl,
    `/api/airports/resolve?q=${encodeURIComponent(q)}`
  );
}

export async function patchConfig(serverUrl: string, patch: ConfigPatch): Promise<AppConfig> {
  const base = normalizeServerUrl(serverUrl);
  if (!base) throw new LocalFlightApiError("Set a Local Flight server URL first.");

  const headers = await companionHeaders();
  const response = await fetch(`${base}/api/config`, {
    method: "PATCH",
    headers: { Accept: "application/json", "Content-Type": "application/json", ...headers },
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

export function getRequestLog(
  serverUrl: string,
  { hours = 24, limit = 200, clientType }: { hours?: number; limit?: number; clientType?: string } = {}
): Promise<RequestLogResponse> {
  const params = new URLSearchParams({ hours: String(hours), limit: String(limit) });
  if (clientType) params.set("client_type", clientType);
  return fetchJson<RequestLogResponse>(serverUrl, `/api/admin/requests?${params}`);
}

export async function testConnection(serverUrl: string): Promise<boolean> {
  await getHealth(serverUrl);
  return true;
}

export function sendCompanionCheckin(
  serverUrl: string,
  input: {
    companion_id: string;
    client_name: string;
    app_version: string;
    mobile_os: string;
    device_type: string;
  }
): Promise<{ ok: boolean; recorded_at?: string; platform_pair?: string; server_install_id?: string | null }> {
  return sendJson(serverUrl, "/api/admin/companion/checkin", input);
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
