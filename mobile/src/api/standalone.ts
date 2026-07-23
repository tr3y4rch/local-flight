import * as Crypto from "expo-crypto";
import { Platform } from "react-native";

import type {
  AirportResolved,
  AirportResult,
  DashboardSnapshot,
  FidsRow,
  FlightView,
  MobileBoardResponse,
  Metar,
  RadarMapResponse,
  RadarResponse
} from "./types";
import { LocalFlightApiError, normalizeServerUrl } from "./client";
import { appVersion, getCompanionIdentity, mobileOsLabel, mobileReportOrigin } from "../device/identity";
import type { MobileDiagnosticsMode, StandaloneAirport, StandaloneFlightSource } from "../storage/settings";

export const DEFAULT_RELAY_URL = "https://relay.beacontools.cc";
const CLIENT_KIND = "mobile_standalone";
const AIRPORT_SEARCH_QUERY_LIMIT = 20;
const RELAY_REQUEST_TIMEOUT_MS = 20_000;
const DEFAULT_RELAY_FALLBACK_URL = "https://localflight-community-relay.fly.dev";
const STANDALONE_BOARD_ROWS_PER_DIRECTION = 50;
const STANDALONE_BOARD_REFRESH_SECONDS = 3_600;
const ROUTE_UNAVAILABLE_STATUSES = new Set([404, 405]);
const VATSIM_UNAVAILABLE_MESSAGE = "VATSIM traffic is not available from this relay yet. Your selection is saved; try again after the relay is updated.";

export type StandaloneCredentials = {
  relayUrl?: string;
  installId: string;
  activationToken: string;
  airport: StandaloneAirport;
  diagnosticsMode: MobileDiagnosticsMode;
  source: StandaloneFlightSource;
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

function relayBases(relayUrl?: string): string[] {
  const preferred = relayBase(relayUrl);
  const canonical = normalizeServerUrl(DEFAULT_RELAY_URL);
  if (preferred !== canonical) return [preferred];

  // The canonical hostname is the public, documented entry point. Some iOS
  // URLSession builds can stall before receiving its Cloudflare response,
  // though the same HTTPS relay is reachable directly at its Fly origin. Use
  // that official origin first on iOS and retain it as a recovery path on the
  // other mobile platforms. Custom relay addresses are never redirected.
  return Platform.OS === "ios"
    ? [DEFAULT_RELAY_FALLBACK_URL, canonical]
    : [canonical, DEFAULT_RELAY_FALLBACK_URL];
}

export function preferredStandaloneRelayUrl(relayUrl?: string): string {
  return relayBases(relayUrl)[0] || relayBase(relayUrl);
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
  let response: Response | null = null;
  let lastError: unknown = null;
  for (const base of relayBases(relayUrl)) {
    try {
      response = await fetchRelayResponse(base, path, init);
      // The canonical relay and its official origin can be deployed a few
      // minutes apart. A missing route is a compatibility result, not an
      // authorization failure, so allow the other public entry point to serve
      // it. Never retry authorization or allowance responses on another base.
      if (ROUTE_UNAVAILABLE_STATUSES.has(response.status)) continue;
      break;
    } catch (error) {
      lastError = error;
    }
  }
  if (!response) throw lastError || new LocalFlightApiError("The Local Flight relay could not be reached.");
  if (!response.ok) {
    let message = `Relay HTTP ${response.status} for ${path}`;
    try {
      const data = (await response.json()) as { detail?: unknown; error?: { info?: unknown } };
      if (typeof data.detail === "string" && data.detail.trim()) {
        message = data.detail;
      } else if (typeof data.error?.info === "string" && data.error.info.trim()) {
        message = data.error.info;
      }
    } catch {
      // Ignore non-JSON relay errors.
    }
    throw new LocalFlightApiError(message, response.status);
  }
  return response.json() as Promise<T>;
}

async function fetchRelayResponse(base: string, path: string, init?: RequestInit): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), RELAY_REQUEST_TIMEOUT_MS);
  try {
    return await fetch(`${base}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...(init?.headers || {})
      }
    });
  } catch (error) {
    if (controller.signal.aborted) {
      throw new LocalFlightApiError("The Local Flight relay did not answer in time.");
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

async function standaloneParams(credentials: StandaloneCredentials): Promise<URLSearchParams> {
  const identity = await getCompanionIdentity();
  const params = new URLSearchParams({
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
  params.set("source", credentials.source);
  return params;
}

export function searchStandaloneAirports(q: string, limit = 8, relayUrl?: string): Promise<AirportResult[]> {
  // Released Local Flight hosts and relay versions before Mobile V2 accept at
  // most 20 characters here. A leading name fragment is still enough for the
  // substring search, and keeping the client bounded preserves compatibility
  // while newer servers accept complete airport names.
  const query = q.trim().replace(/\s+/g, " ").slice(0, AIRPORT_SEARCH_QUERY_LIMIT);
  const params = new URLSearchParams({ q: query, limit: String(limit) });
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
  const summary = await fetchRelayJson<DashboardSnapshot>(credentials.relayUrl, `/v1/mobile/summary?${params}`);
  if (
    credentials.source === "virtual"
    && summary.config?.source !== "virtual"
    && summary.standalone_policy?.source !== "virtual"
  ) {
    throw new LocalFlightApiError(VATSIM_UNAVAILABLE_MESSAGE, 503);
  }
  return summary;
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

export async function getStandaloneBoard(
  credentials: StandaloneCredentials
): Promise<MobileBoardResponse> {
  const params = await standaloneParams(credentials);
  try {
    const board = await fetchRelayJson<MobileBoardResponse>(credentials.relayUrl, `/v1/mobile/board?${params}`);
    if (credentials.source === "virtual" && board.source !== "virtual") {
      throw new LocalFlightApiError(VATSIM_UNAVAILABLE_MESSAGE, 503);
    }
    return board;
  } catch (error) {
    if (!(error instanceof LocalFlightApiError) || !ROUTE_UNAVAILABLE_STATUSES.has(error.status || 0)) {
      throw error;
    }
    if (credentials.source === "virtual") {
      throw new LocalFlightApiError(VATSIM_UNAVAILABLE_MESSAGE, 503);
    }

    // Mobile V2 introduced one combined Board response so both directions can
    // share a metered schedule snapshot. During a staged relay rollout, keep
    // released relays usable through the compatible FIDS endpoint instead of
    // presenting an empty Board. The server still owns caching and freshness;
    // an empty generated_at tells callers to retain summary/source freshness.
    // Keep these reads sequential. Older relays can reject one of two
    // simultaneous cache-miss schedule requests while the shared upstream
    // snapshot is being prepared. The first direction establishes that cache;
    // the second direction then reads the same snapshot without racing it.
    const departures = await getStandaloneFids(
      credentials,
      "departures",
      STANDALONE_BOARD_ROWS_PER_DIRECTION
    );
    const arrivals = await getStandaloneFids(
      credentials,
      "arrivals",
      STANDALONE_BOARD_ROWS_PER_DIRECTION
    );
    return {
      schema_version: "mobile-board-v2",
      generated_at: "",
      cache_state: "legacy-fids-compatibility",
      refresh_after_s: STANDALONE_BOARD_REFRESH_SECONDS,
      rows_per_direction: STANDALONE_BOARD_ROWS_PER_DIRECTION,
      departures,
      arrivals
    };
  }
}

export async function getStandaloneRadar(
  credentials: StandaloneCredentials,
  radiusNm = 5
): Promise<RadarResponse> {
  const params = await standaloneParams(credentials);
  params.set("radius_nm", String(radiusNm));
  const radar = await fetchRelayJson<RadarResponse>(credentials.relayUrl, `/v1/mobile/radar?${params}`);
  if (credentials.source === "virtual" && String(radar.source || "").toLowerCase() !== "vatsim") {
    throw new LocalFlightApiError(VATSIM_UNAVAILABLE_MESSAGE, 503);
  }
  return radar;
}

export async function getStandaloneRadarGround(
  credentials: StandaloneCredentials,
  radiusNm = 5
): Promise<RadarMapResponse> {
  const params = await standaloneParams(credentials);
  params.set("radius_nm", String(Math.max(1, Math.min(10, radiusNm))));
  return fetchRelayJson<RadarMapResponse>(credentials.relayUrl, `/v1/airport-ground?${params}`);
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
      origin: mobileReportOrigin(),
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
      source: credentials.source,
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
      origin: mobileReportOrigin(),
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
      source: credentials.source,
      api_mode: "relay",
      diagnostics_mode: credentials.diagnosticsMode
    })
  });
}
