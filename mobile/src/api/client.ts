import type {
  AdminSystem,
  AppConfig,
  AppState,
  Budget,
  FidsDetailResponse,
  FidsRow,
  FlightHistoryResponse,
  FlightView,
  HistoryDirection,
  HistoryResponse,
  Metar,
  RadarResponse
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

export function getHealth(serverUrl: string): Promise<AppState> {
  return fetchJson<AppState>(serverUrl, "/api/health");
}

export function getConfig(serverUrl: string): Promise<AppConfig> {
  return fetchJson<AppConfig>(serverUrl, "/api/config");
}

export function getAdminSystem(serverUrl: string): Promise<AdminSystem> {
  return fetchJson<AdminSystem>(serverUrl, "/api/admin/system");
}

export function getBudget(serverUrl: string): Promise<Budget> {
  return fetchJson<Budget>(serverUrl, "/api/admin/budget");
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

export async function testConnection(serverUrl: string): Promise<boolean> {
  await getHealth(serverUrl);
  return true;
}
