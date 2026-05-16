import * as Crypto from "expo-crypto";

import type {
  AirportResolved,
  AirportResult,
  DashboardSnapshot,
  FidsRow,
  FlightView,
  Metar,
  RadarMapResponse,
  RadarSurfaceResponse,
  RadarResponse
} from "./types";
import { LocalFlightApiError, normalizeServerUrl } from "./client";
import { appVersion, getCompanionIdentity, mobileOsLabel } from "../device/identity";
import type { MobileDiagnosticsMode, StandaloneAirport } from "../storage/settings";

export const DEFAULT_RELAY_URL = "https://localflight-community-relay.fly.dev";
const CLIENT_KIND = "mobile_standalone";

export type StandaloneCredentials = {
  relayUrl?: string;
  installId: string;
  activationToken: string;
  airport: StandaloneAirport;
  diagnosticsMode: MobileDiagnosticsMode;
};

export type StandaloneActivationResult = {
  activationToken: string;
  tokenPrefix: string;
  status: string;
  decisionNote?: string;
};

function relayBase(relayUrl?: string): string {
  return normalizeServerUrl(relayUrl || DEFAULT_RELAY_URL);
}

async function installFingerprint(installId: string): Promise<string> {
  const digest = await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, installId);
  return digest.slice(0, 12);
}

async function fetchRelayJson<T>(
  relayUrl: string | undefined,
  path: string,
  init?: RequestInit
): Promise<T> {
  const base = relayBase(relayUrl);
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers || {})
    }
  });
  if (!response.ok) {
    let message = `Relay HTTP ${response.status} for ${path}`;
    try {
      const data = (await response.json()) as { detail?: string; error?: { info?: string } };
      message = data.detail || data.error?.info || message;
    } catch {
      // Ignore non-JSON relay errors.
    }
    throw new LocalFlightApiError(message, response.status);
  }
  return response.json() as Promise<T>;
}

async function standaloneParams(credentials: StandaloneCredentials): Promise<URLSearchParams> {
  const identity = await getCompanionIdentity();
  return new URLSearchParams({
    install_id: credentials.installId,
    activation_token: credentials.activationToken,
    app_version: appVersion(),
    client_kind: CLIENT_KIND,
    device_type: identity.deviceType,
    airport_iata: credentials.airport.iata,
    airport_icao: credentials.airport.icao,
    timezone: credentials.airport.timezone || "UTC",
    diagnostics_mode: credentials.diagnosticsMode
  });
}

export function searchStandaloneAirports(q: string, limit = 8, relayUrl?: string): Promise<AirportResult[]> {
  const params = new URLSearchParams({ q, limit: String(limit) });
  return fetchRelayJson<AirportResult[]>(relayUrl, `/v1/airports/search?${params}`);
}

export function resolveStandaloneAirport(q: string, relayUrl?: string): Promise<AirportResolved> {
  const params = new URLSearchParams({ q });
  return fetchRelayJson<AirportResolved>(relayUrl, `/v1/airports/resolve?${params}`);
}

export async function activateStandalone(
  input: {
    installId: string;
    airport: StandaloneAirport;
    relayUrl?: string;
  }
): Promise<StandaloneActivationResult> {
  const identity = await getCompanionIdentity();
  const fingerprint = await installFingerprint(input.installId);
  const payload = await fetchRelayJson<{
    activation_token?: string;
    token_prefix?: string;
    status?: string;
    decision_note?: string;
  }>(input.relayUrl, "/v1/activate", {
    method: "POST",
    body: JSON.stringify({
      install_id: input.installId,
      install_fingerprint: fingerprint,
      airport_iata: input.airport.iata,
      airport_icao: input.airport.icao,
      timezone: input.airport.timezone || "UTC",
      device_type: identity.deviceType,
      display_name: `Local Flight Mobile ${input.airport.iata || input.airport.icao}`,
      requested_mode: CLIENT_KIND,
      app_version: appVersion()
    })
  });
  if (!payload.activation_token) {
    throw new LocalFlightApiError(payload.decision_note || "Relay activation is pending manual review.");
  }
  return {
    activationToken: payload.activation_token,
    tokenPrefix: payload.token_prefix || payload.activation_token.slice(0, 10),
    status: payload.status || "issued",
    decisionNote: payload.decision_note
  };
}

export async function getStandaloneSummary(credentials: StandaloneCredentials): Promise<DashboardSnapshot> {
  const params = await standaloneParams(credentials);
  return fetchRelayJson<DashboardSnapshot>(credentials.relayUrl, `/v1/mobile/summary?${params}`);
}

export async function getStandaloneFids(
  credentials: StandaloneCredentials,
  view: FlightView,
  limit = 30
): Promise<FidsRow[]> {
  const params = await standaloneParams(credentials);
  params.set("view", view);
  params.set("limit", String(limit));
  return fetchRelayJson<FidsRow[]>(credentials.relayUrl, `/v1/mobile/fids?${params}`);
}

export async function getStandaloneRadar(
  credentials: StandaloneCredentials,
  radiusNm = 5
): Promise<RadarResponse> {
  const params = await standaloneParams(credentials);
  params.set("radius_nm", String(radiusNm));
  return fetchRelayJson<RadarResponse>(credentials.relayUrl, `/v1/mobile/radar?${params}`);
}

function radarMapFromSurface(surface: RadarSurfaceResponse, radiusNm: number): RadarMapResponse {
  const features = surface.features || [];
  const runways = features.filter((feature) => String(feature.kind || "").toLowerCase() === "runway");
  const surfaceFeatures = features.filter((feature) => String(feature.kind || "").toLowerCase() !== "runway");
  return {
    center: surface.center,
    radius_nm: radiusNm,
    schema_version: "mobile-standalone-surface-v1",
    runways,
    surface_features: surfaceFeatures,
    map_features: [],
    attribution: surface.attribution ? [surface.attribution] : [],
    sources: {
      runways: runways.length ? "relay-surface" : "none",
      surface: surface.provider || "relay-surface",
      surface_cache_state: surface.cache_state || "unknown",
      map: "none",
      map_cache_state: "standalone-off",
      terrain: "none",
      terrain_cache_state: "standalone-off"
    },
    confidence: {
      runway_count: runways.length,
      surface_feature_count: surfaceFeatures.length,
      standalone: true
    }
  };
}

export async function getStandaloneRadarGround(
  credentials: StandaloneCredentials,
  radiusNm = 5
): Promise<RadarMapResponse> {
  const airport = credentials.airport;
  if (airport.lat == null || airport.lon == null) {
    throw new LocalFlightApiError("Standalone airport coordinates are not available for radar drawings.");
  }
  const params = new URLSearchParams({
    airport_iata: airport.iata,
    airport_icao: airport.icao || "",
    lat: String(airport.lat),
    lon: String(airport.lon),
    radius_nm: String(Math.max(1, Math.min(5, radiusNm)))
  });
  const surface = await fetchRelayJson<RadarSurfaceResponse>(credentials.relayUrl, `/v1/airport-surface?${params}`);
  return radarMapFromSurface(surface, radiusNm);
}

export async function getStandaloneMetar(credentials: StandaloneCredentials): Promise<Metar> {
  const params = await standaloneParams(credentials);
  return fetchRelayJson<Metar>(credentials.relayUrl, `/v1/mobile/metar?${params}`);
}

export async function submitStandaloneFeedback(
  credentials: StandaloneCredentials,
  input: { title: string; description: string; client_context?: string }
): Promise<{ ok: boolean; url?: string | null; deduped?: boolean }> {
  const fingerprint = await installFingerprint(credentials.installId);
  return fetchRelayJson(credentials.relayUrl, "/v1/reports", {
    method: "POST",
    body: JSON.stringify({
      report_type: "manual",
      origin: "ios",
      install_id: credentials.installId,
      install_fingerprint: fingerprint,
      activation_token: credentials.activationToken,
      title: input.title,
      description: input.description,
      context: "mobile_standalone/manual",
      client_context: input.client_context || "",
      app_version: appVersion(),
      platform: "mobile_standalone",
      os: mobileOsLabel(),
      airport: credentials.airport.iata,
      source: "real",
      api_mode: "relay",
      diagnostics_mode: credentials.diagnosticsMode
    })
  });
}

export async function submitStandaloneCrash(
  credentials: StandaloneCredentials,
  input: { message: string; traceback?: string; context?: string; client_context?: string }
): Promise<{ ok: boolean; url?: string | null; deduped?: boolean }> {
  const fingerprint = await installFingerprint(credentials.installId);
  return fetchRelayJson(credentials.relayUrl, "/v1/reports", {
    method: "POST",
    body: JSON.stringify({
      report_type: "crash",
      origin: "ios",
      install_id: credentials.installId,
      install_fingerprint: fingerprint,
      activation_token: credentials.activationToken,
      message: input.message,
      traceback: input.traceback || "",
      context: input.context || "mobile_standalone/crash",
      client_context: input.client_context || "",
      app_version: appVersion(),
      platform: "mobile_standalone",
      os: mobileOsLabel(),
      airport: credentials.airport.iata,
      source: "real",
      api_mode: "relay",
      diagnostics_mode: credentials.diagnosticsMode
    })
  });
}
