import * as SecureStore from "expo-secure-store";
import type { AirportResolved, AppConfig } from "../api/types";
import {
  normalizePinnedFlightReference,
  pinnedFlightId,
  type PinnedFlightReference
} from "../domain/pinnedFlight";
import {
  DEFAULT_CONTRAST_PREFERENCE,
  DEFAULT_THEME_PREFERENCE,
  resolveMobileThemeMode,
  type MobileContrastPreference,
  type MobileSkin,
  type MobileThemeMode,
  type MobileThemePreference
} from "../theme/tokens";

const SERVER_URL_KEY = "localflight.serverUrl";
const PINNED_FLIGHT_KEY = "localflight.pinnedFlight";
const PROFILES_KEY = "localflight.profiles";
const COMPANION_ID_KEY = "localflight.companionId";
const APPEARANCE_THEME_KEY = "localflight.mobileTheme";
const APPEARANCE_SKIN_KEY = "localflight.mobileSkin";
const APPEARANCE_PREFERENCE_KEY = "localflight.mobileThemePreference";
const APPEARANCE_CONTRAST_KEY = "localflight.mobileContrastPreference";
const WEATHER_DISPLAY_KEY = "localflight.weatherDisplayMode";
const RADAR_DRAWING_LAYERS_KEY = "localflight.radarDrawingLayers";
const STANDALONE_GROUND_LAYERS_VERSION_KEY = "localflight.standaloneGroundLayersVersion";
const MOBILE_DIAGNOSTICS_KEY = "localflight.mobileDiagnosticsMode";
const MOBILE_SETUP_STATE_KEY = "localflight.mobileSetupState";
const WIDGET_PREFERENCES_KEY = "localflight.widgetPreferences";
const MOBILE_RELAY_INSTALL_ID_KEY = "localflight.mobileRelayInstallId";
const MOBILE_RELAY_ACTIVATION_TOKEN_KEY = "localflight.mobileRelayActivationToken";
const STANDALONE_AIRPORT_KEY = "localflight.standaloneAirport";
const CACHED_LAN_CONFIG_KEY = "localflight.cachedLanConfig";
const CACHED_LAN_AIRPORT_KEY = "localflight.cachedLanAirport";

const DEFAULT_THEME_MODE: MobileThemeMode = "dark";
const DEFAULT_SKIN: MobileSkin = "standard";

let companionIdCache: string | null = null;
let relayInstallIdCache: string | null = null;

export type ConfigProfile = {
  id: string;
  name: string;
  iata: string;
  icao: string;
  timezone?: string;
  source: "real" | "virtual";
  refresh_seconds: number;
};

export type MobileDiagnosticsMode = "unset" | "manual" | "auto" | "auto_logs";
export type MobileWeatherDisplayMode = "passenger" | "pilot" | "vatsim";
export type MobileSetupMode = "lan_companion" | "standalone";
export type MobileRadarDrawingLayers = {
  runways: boolean;
  surface: boolean;
  terrain: boolean;
};
export type MobileWidgetPreferences = {
  mediumRowCount: 2 | 3;
  showGateTerminal: boolean;
  automaticRefresh: boolean;
  /** User explicitly enabled pinned-flight presentation on the Lock Screen. */
  liveActivityEnabled: boolean;
};

export type MobileThemePreferences = {
  preference: MobileThemePreference;
  contrast: MobileContrastPreference;
  resolvedThemeMode: MobileThemeMode;
};

export type RemoteCompanionGrant = {
  grantRef: string;
  relayUrl: string;
  installRef: string;
  remoteKey: string;
  createdAt?: string | null;
  lastSeenRemoteAt?: string | null;
  revokedAt?: string | null;
};

const DEFAULT_RADAR_DRAWING_LAYERS: MobileRadarDrawingLayers = {
  runways: true,
  surface: true,
  terrain: true
};
export const DEFAULT_WIDGET_PREFERENCES: MobileWidgetPreferences = {
  mediumRowCount: 3,
  showGateTerminal: true,
  automaticRefresh: true,
  liveActivityEnabled: false
};

export type StandaloneAirport = {
  iata: string;
  icao: string;
  name: string;
  city: string;
  country: string;
  timezone?: string;
  lat?: number | null;
  lon?: number | null;
};

export type MobileSetupState = {
  complete: boolean;
  mode: MobileSetupMode;
  serverUrl: string;
  relayInstallId?: string;
  relayActivationToken?: string;
  remoteCompanion?: RemoteCompanionGrant | null;
  standaloneAirport?: StandaloneAirport | null;
  diagnosticsMode: MobileDiagnosticsMode;
  completedAt: string | null;
};

function createCompanionId(): string {
  const part = () => Math.floor(Math.random() * 0xffffffff).toString(16).padStart(8, "0");
  return `lfc_${part()}${part()}${Date.now().toString(16).slice(-8)}`;
}

function createUuid(): string {
  const bytes = Array.from({ length: 16 }, () => Math.floor(Math.random() * 256));
  bytes[6] = (bytes[6]! & 0x0f) | 0x40;
  bytes[8] = (bytes[8]! & 0x3f) | 0x80;
  const hex = bytes.map((byte) => byte.toString(16).padStart(2, "0"));
  return [
    hex.slice(0, 4).join(""),
    hex.slice(4, 6).join(""),
    hex.slice(6, 8).join(""),
    hex.slice(8, 10).join(""),
    hex.slice(10, 16).join("")
  ].join("-");
}

function normalizeStandaloneAirport(value: unknown): StandaloneAirport | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Partial<StandaloneAirport>;
  const iata = String(raw.iata || "").trim().toUpperCase();
  const icao = String(raw.icao || "").trim().toUpperCase();
  if (!iata && !icao) return null;
  return {
    iata,
    icao,
    name: String(raw.name || iata || icao),
    city: String(raw.city || ""),
    country: String(raw.country || ""),
    timezone: String(raw.timezone || "UTC"),
    lat: typeof raw.lat === "number" ? raw.lat : null,
    lon: typeof raw.lon === "number" ? raw.lon : null
  };
}

function normalizeCachedAirport(value: unknown): AirportResolved | null {
  const airport = normalizeStandaloneAirport(value);
  return airport ? { ...airport, type: "large_airport" } : null;
}

function normalizeCachedConfig(value: unknown): AppConfig | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Partial<AppConfig>;
  const airport_iata = String(raw.airport_iata || "").trim().toUpperCase();
  const airport_icao = String(raw.airport_icao || "").trim().toUpperCase();
  if (!airport_iata && !airport_icao) return null;
  return {
    airport_iata,
    airport_icao,
    refresh_seconds: Number(raw.refresh_seconds || 900),
    display_name: String(raw.display_name || airport_iata || airport_icao),
    theme: String(raw.theme || "standard"),
    source: String(raw.source || "real"),
    timezone: String(raw.timezone || "UTC"),
    skin: String(raw.skin || "standard"),
    display_outputs: Array.isArray(raw.display_outputs) ? raw.display_outputs.map(String) : ["mobile"],
    diagnostics_mode: raw.diagnostics_mode,
    web_row_limit: raw.web_row_limit,
    web_rotation_seconds: raw.web_rotation_seconds,
    display_grace_minutes: raw.display_grace_minutes,
    display_horizon_hours: raw.display_horizon_hours,
    radar_surface_enabled: raw.radar_surface_enabled,
    remote_companion_enabled: raw.remote_companion_enabled
  };
}

export async function loadServerUrl(): Promise<string> {
  return (await SecureStore.getItemAsync(SERVER_URL_KEY)) || "";
}

export async function saveServerUrl(serverUrl: string): Promise<void> {
  await SecureStore.setItemAsync(SERVER_URL_KEY, serverUrl);
}

export async function loadCachedLanConfig(): Promise<AppConfig | null> {
  const raw = await SecureStore.getItemAsync(CACHED_LAN_CONFIG_KEY);
  if (!raw) return null;
  try {
    return normalizeCachedConfig(JSON.parse(raw));
  } catch {
    return null;
  }
}

export async function saveCachedLanConfig(config: AppConfig | null): Promise<void> {
  if (!config) {
    await SecureStore.deleteItemAsync(CACHED_LAN_CONFIG_KEY);
    return;
  }
  await SecureStore.setItemAsync(CACHED_LAN_CONFIG_KEY, JSON.stringify(normalizeCachedConfig(config)));
}

export async function loadCachedLanAirport(): Promise<AirportResolved | null> {
  const raw = await SecureStore.getItemAsync(CACHED_LAN_AIRPORT_KEY);
  if (!raw) return null;
  try {
    return normalizeCachedAirport(JSON.parse(raw));
  } catch {
    return null;
  }
}

export async function saveCachedLanAirport(airport: AirportResolved | null): Promise<void> {
  if (!airport) {
    await SecureStore.deleteItemAsync(CACHED_LAN_AIRPORT_KEY);
    return;
  }
  await SecureStore.setItemAsync(CACHED_LAN_AIRPORT_KEY, JSON.stringify(normalizeCachedAirport(airport)));
}

export async function loadCompanionId(): Promise<string> {
  if (companionIdCache) {
    return companionIdCache;
  }
  const existing = (await SecureStore.getItemAsync(COMPANION_ID_KEY)) || "";
  if (existing) {
    companionIdCache = existing;
    return existing;
  }
  const created = createCompanionId();
  await SecureStore.setItemAsync(COMPANION_ID_KEY, created);
  companionIdCache = created;
  return created;
}

export async function loadMobileRelayInstallId(): Promise<string> {
  if (relayInstallIdCache) {
    return relayInstallIdCache;
  }
  const existing = (await SecureStore.getItemAsync(MOBILE_RELAY_INSTALL_ID_KEY)) || "";
  if (existing) {
    relayInstallIdCache = existing;
    return existing;
  }
  const created = createUuid();
  await SecureStore.setItemAsync(MOBILE_RELAY_INSTALL_ID_KEY, created);
  relayInstallIdCache = created;
  return created;
}

export async function loadMobileRelayActivationToken(): Promise<string> {
  return (await SecureStore.getItemAsync(MOBILE_RELAY_ACTIVATION_TOKEN_KEY)) || "";
}

export async function saveMobileRelayActivationToken(value: string): Promise<void> {
  const token = value.trim();
  if (!token) {
    await SecureStore.deleteItemAsync(MOBILE_RELAY_ACTIVATION_TOKEN_KEY);
    return;
  }
  await SecureStore.setItemAsync(MOBILE_RELAY_ACTIVATION_TOKEN_KEY, token);
}

export async function loadStandaloneAirport(): Promise<StandaloneAirport | null> {
  const raw = await SecureStore.getItemAsync(STANDALONE_AIRPORT_KEY);
  if (!raw) return null;
  try {
    return normalizeStandaloneAirport(JSON.parse(raw));
  } catch {
    return null;
  }
}

export async function saveStandaloneAirport(value: StandaloneAirport | null): Promise<void> {
  const normalized = normalizeStandaloneAirport(value);
  if (!normalized) {
    await SecureStore.deleteItemAsync(STANDALONE_AIRPORT_KEY);
    return;
  }
  await SecureStore.setItemAsync(STANDALONE_AIRPORT_KEY, JSON.stringify(normalized));
}

export async function loadPinnedFlight(): Promise<string> {
  return pinnedFlightId(await loadPinnedFlightReference());
}

export async function loadPinnedFlightReference(): Promise<PinnedFlightReference | null> {
  const raw = await SecureStore.getItemAsync(PINNED_FLIGHT_KEY);
  if (!raw) return null;
  try {
    return normalizePinnedFlightReference(JSON.parse(raw));
  } catch {
    return normalizePinnedFlightReference(raw);
  }
}

export async function savePinnedFlight(value: string | PinnedFlightReference | null): Promise<void> {
  if (!value) {
    await SecureStore.deleteItemAsync(PINNED_FLIGHT_KEY);
    return;
  }
  const normalized = normalizePinnedFlightReference(value);
  if (!normalized) {
    await SecureStore.deleteItemAsync(PINNED_FLIGHT_KEY);
    return;
  }
  await SecureStore.setItemAsync(PINNED_FLIGHT_KEY, JSON.stringify(normalized));
}

export async function loadProfiles(): Promise<ConfigProfile[]> {
  const raw = await SecureStore.getItemAsync(PROFILES_KEY);
  if (!raw) return [];
  try {
    return JSON.parse(raw) as ConfigProfile[];
  } catch {
    return [];
  }
}

export async function saveProfiles(profiles: ConfigProfile[]): Promise<void> {
  await SecureStore.setItemAsync(PROFILES_KEY, JSON.stringify(profiles));
}

function normalizeThemeMode(value: string | null | undefined): MobileThemeMode {
  return value === "light" ? "light" : DEFAULT_THEME_MODE;
}

export function normalizeMobileThemePreference(
  value: string | null | undefined,
  fallback: MobileThemePreference = DEFAULT_THEME_PREFERENCE
): MobileThemePreference {
  switch (value) {
    case "system":
    case "light":
    case "dark":
      return value;
    default:
      return fallback;
  }
}

function normalizeSkin(value: string | null | undefined): MobileSkin {
  switch (value) {
    case "standard":
    case "technical":
    case "neon":
    case "cyan":
    case "crt":
    case "high_contrast":
      return value;
    default:
      return DEFAULT_SKIN;
  }
}

export function legacySkinToContrastPreference(
  value: string | null | undefined
): MobileContrastPreference {
  return normalizeSkin(value) === "high_contrast" ? "high" : DEFAULT_CONTRAST_PREFERENCE;
}

export function normalizeMobileContrastPreference(
  value: string | null | undefined,
  legacySkin?: string | null
): MobileContrastPreference {
  if (value === "high" || value === "standard") {
    return value;
  }
  return legacySkinToContrastPreference(legacySkin);
}

function normalizeDiagnosticsMode(value: string | null | undefined): MobileDiagnosticsMode {
  switch (value) {
    case "manual":
    case "auto":
    case "auto_logs":
      return value;
    default:
      return "unset";
  }
}

function normalizeWeatherDisplayMode(value: string | null | undefined): MobileWeatherDisplayMode {
  switch (value) {
    case "pilot":
    case "light":
      return "pilot";
    case "vatsim":
    case "raw":
      return "vatsim";
    case "passenger":
    case "friendly":
      return "passenger";
    default:
      return "passenger";
  }
}

function normalizeRadarDrawingLayers(value: unknown): MobileRadarDrawingLayers {
  if (!value || typeof value !== "object") {
    return { ...DEFAULT_RADAR_DRAWING_LAYERS };
  }
  const raw = value as Partial<MobileRadarDrawingLayers>;
  return {
    runways: raw.runways !== false,
    surface: raw.surface !== false,
    terrain: raw.terrain === true
  };
}

function normalizeWidgetPreferences(value: unknown): MobileWidgetPreferences {
  if (!value || typeof value !== "object") {
    return { ...DEFAULT_WIDGET_PREFERENCES };
  }
  const raw = value as Partial<MobileWidgetPreferences>;
  return {
    mediumRowCount: raw.mediumRowCount === 2 ? 2 : 3,
    showGateTerminal: raw.showGateTerminal !== false,
    automaticRefresh: raw.automaticRefresh !== false,
    liveActivityEnabled: raw.liveActivityEnabled === true
  };
}

function normalizeRemoteCompanionGrant(value: unknown): RemoteCompanionGrant | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  const grantRef = String(raw.grantRef || raw.grant_ref || "").trim();
  const relayUrl = String(raw.relayUrl || raw.relay_url || "").trim().replace(/\/+$/, "");
  const installRef = String(raw.installRef || raw.install_ref || "").trim();
  const remoteKey = String(raw.remoteKey || raw.remote_key || "").trim();
  if (!grantRef || !relayUrl || !installRef || !remoteKey) return null;
  return {
    grantRef,
    relayUrl,
    installRef,
    remoteKey,
    createdAt: typeof raw.createdAt === "string" ? raw.createdAt : typeof raw.created_at === "string" ? raw.created_at : null,
    lastSeenRemoteAt: typeof raw.lastSeenRemoteAt === "string" ? raw.lastSeenRemoteAt : typeof raw.last_seen_remote_at === "string" ? raw.last_seen_remote_at : null,
    revokedAt: typeof raw.revokedAt === "string" ? raw.revokedAt : typeof raw.revoked_at === "string" ? raw.revoked_at : null
  };
}

export function incompleteMobileSetupState(
  serverUrl = "",
  diagnosticsMode: MobileDiagnosticsMode = "unset"
): MobileSetupState {
  return {
    complete: false,
    mode: "lan_companion",
    serverUrl,
    relayInstallId: "",
    relayActivationToken: "",
    remoteCompanion: null,
    standaloneAirport: null,
    diagnosticsMode: normalizeDiagnosticsMode(diagnosticsMode),
    completedAt: null
  };
}

export function completeMobileSetupState(
  serverUrl: string,
  diagnosticsMode: MobileDiagnosticsMode,
  remoteCompanion: RemoteCompanionGrant | null = null
): MobileSetupState {
  return {
    complete: true,
    mode: "lan_companion",
    serverUrl,
    relayInstallId: "",
    relayActivationToken: "",
    remoteCompanion: normalizeRemoteCompanionGrant(remoteCompanion),
    standaloneAirport: null,
    diagnosticsMode: normalizeDiagnosticsMode(diagnosticsMode),
    completedAt: new Date().toISOString()
  };
}

export function completeStandaloneMobileSetupState({
  relayInstallId,
  relayActivationToken,
  airport,
  diagnosticsMode
}: {
  relayInstallId: string;
  relayActivationToken: string;
  airport: StandaloneAirport;
  diagnosticsMode: MobileDiagnosticsMode;
}): MobileSetupState {
  return {
    complete: true,
    mode: "standalone",
    serverUrl: "",
    relayInstallId: relayInstallId.trim(),
    relayActivationToken: relayActivationToken.trim(),
    remoteCompanion: null,
    standaloneAirport: normalizeStandaloneAirport(airport),
    diagnosticsMode: normalizeDiagnosticsMode(diagnosticsMode),
    completedAt: new Date().toISOString()
  };
}

function normalizeMobileSetupState(raw: unknown): MobileSetupState {
  if (!raw || typeof raw !== "object") {
    return incompleteMobileSetupState();
  }
  const state = raw as Partial<MobileSetupState>;
  const diagnosticsMode = normalizeDiagnosticsMode(state.diagnosticsMode);
  const mode: MobileSetupMode = state.mode === "standalone" ? "standalone" : "lan_companion";
  const serverUrl = typeof state.serverUrl === "string" ? state.serverUrl : "";
  const standaloneAirport = normalizeStandaloneAirport(state.standaloneAirport);
  const relayInstallId = typeof state.relayInstallId === "string" ? state.relayInstallId : "";
  const relayActivationToken = typeof state.relayActivationToken === "string" ? state.relayActivationToken : "";
  const remoteCompanion = normalizeRemoteCompanionGrant(state.remoteCompanion);
  const complete = mode === "standalone"
    ? Boolean(state.complete && relayInstallId && relayActivationToken && standaloneAirport && diagnosticsMode !== "unset")
    : Boolean(state.complete && serverUrl && diagnosticsMode !== "unset");
  return {
    complete,
    mode,
    serverUrl: mode === "lan_companion" ? serverUrl : "",
    relayInstallId: mode === "standalone" ? relayInstallId : "",
    relayActivationToken: mode === "standalone" ? relayActivationToken : "",
    remoteCompanion: mode === "lan_companion" ? remoteCompanion : null,
    standaloneAirport: mode === "standalone" ? standaloneAirport : null,
    diagnosticsMode,
    completedAt: complete && typeof state.completedAt === "string" ? state.completedAt : null
  };
}

export function isMobileSetupComplete(
  state: MobileSetupState,
  serverUrl = state.serverUrl,
  diagnosticsMode: MobileDiagnosticsMode = state.diagnosticsMode
): boolean {
  if (state.mode === "standalone") {
    return Boolean(
      state.complete &&
      state.relayInstallId &&
      state.relayActivationToken &&
      state.standaloneAirport &&
      normalizeDiagnosticsMode(diagnosticsMode) !== "unset"
    );
  }
  return Boolean(
    state.complete &&
    state.mode === "lan_companion" &&
    serverUrl &&
    normalizeDiagnosticsMode(diagnosticsMode) !== "unset"
  );
}

export async function loadAppearancePrefs(): Promise<{
  themeMode: MobileThemeMode;
  skin: MobileSkin;
}> {
  const [themeMode, skin] = await Promise.all([
    SecureStore.getItemAsync(APPEARANCE_THEME_KEY),
    SecureStore.getItemAsync(APPEARANCE_SKIN_KEY)
  ]);
  return {
    themeMode: normalizeThemeMode(themeMode),
    skin: normalizeSkin(skin)
  };
}

/**
 * Loads the V2 theme contract and lazily seeds it from the V1 theme/skin keys.
 * The legacy keys remain readable and writable so upgrades and older clients
 * keep their previous behavior while new screens move to semantic themes.
 */
export async function loadMobileThemePreferences(
  systemThemeMode: MobileThemeMode = DEFAULT_THEME_MODE
): Promise<MobileThemePreferences> {
  const [storedPreference, storedContrast, legacyThemeMode, legacySkin] = await Promise.all([
    SecureStore.getItemAsync(APPEARANCE_PREFERENCE_KEY),
    SecureStore.getItemAsync(APPEARANCE_CONTRAST_KEY),
    SecureStore.getItemAsync(APPEARANCE_THEME_KEY),
    SecureStore.getItemAsync(APPEARANCE_SKIN_KEY)
  ]);
  const legacyPreference = legacyThemeMode === "light" || legacyThemeMode === "dark"
    ? legacyThemeMode
    : DEFAULT_THEME_PREFERENCE;
  const preference = normalizeMobileThemePreference(storedPreference, legacyPreference);
  const contrast = normalizeMobileContrastPreference(storedContrast, legacySkin);

  const migrationWrites: Promise<void>[] = [];
  if (storedPreference !== preference) {
    migrationWrites.push(SecureStore.setItemAsync(APPEARANCE_PREFERENCE_KEY, preference));
  }
  if (storedContrast !== contrast) {
    migrationWrites.push(SecureStore.setItemAsync(APPEARANCE_CONTRAST_KEY, contrast));
  }
  if (migrationWrites.length) {
    await Promise.all(migrationWrites.map((write) => write.catch(() => undefined)));
  }

  return {
    preference,
    contrast,
    resolvedThemeMode: resolveMobileThemeMode(preference, systemThemeMode)
  };
}

export async function saveMobileThemePreferences(value: {
  preference: MobileThemePreference;
  contrast: MobileContrastPreference;
  resolvedThemeMode: MobileThemeMode;
}): Promise<void> {
  const preference = normalizeMobileThemePreference(value.preference);
  const contrast = normalizeMobileContrastPreference(value.contrast);
  const resolvedThemeMode = resolveMobileThemeMode(preference, value.resolvedThemeMode);
  const compatibilitySkin: MobileSkin = contrast === "high" ? "high_contrast" : "standard";
  await Promise.all([
    SecureStore.setItemAsync(APPEARANCE_PREFERENCE_KEY, preference),
    SecureStore.setItemAsync(APPEARANCE_CONTRAST_KEY, contrast),
    SecureStore.setItemAsync(APPEARANCE_THEME_KEY, resolvedThemeMode),
    SecureStore.setItemAsync(APPEARANCE_SKIN_KEY, compatibilitySkin)
  ]);
}

export async function saveAppearancePrefs(value: {
  themeMode: MobileThemeMode;
  skin: MobileSkin;
}): Promise<void> {
  const themeMode = normalizeThemeMode(value.themeMode);
  const skin = normalizeSkin(value.skin);
  await Promise.all([
    SecureStore.setItemAsync(APPEARANCE_THEME_KEY, themeMode),
    SecureStore.setItemAsync(APPEARANCE_SKIN_KEY, skin),
    SecureStore.setItemAsync(APPEARANCE_PREFERENCE_KEY, themeMode),
    SecureStore.setItemAsync(APPEARANCE_CONTRAST_KEY, legacySkinToContrastPreference(skin))
  ]);
}

export async function loadWeatherDisplayMode(): Promise<MobileWeatherDisplayMode> {
  return normalizeWeatherDisplayMode(await SecureStore.getItemAsync(WEATHER_DISPLAY_KEY));
}

export async function saveWeatherDisplayMode(value: MobileWeatherDisplayMode): Promise<void> {
  await SecureStore.setItemAsync(WEATHER_DISPLAY_KEY, normalizeWeatherDisplayMode(value));
}

export async function loadRadarDrawingLayers(): Promise<MobileRadarDrawingLayers> {
  const raw = await SecureStore.getItemAsync(RADAR_DRAWING_LAYERS_KEY);
  if (!raw) {
    return { ...DEFAULT_RADAR_DRAWING_LAYERS };
  }
  try {
    return normalizeRadarDrawingLayers(JSON.parse(raw));
  } catch {
    return { ...DEFAULT_RADAR_DRAWING_LAYERS };
  }
}

export async function saveRadarDrawingLayers(value: MobileRadarDrawingLayers): Promise<void> {
  await SecureStore.setItemAsync(RADAR_DRAWING_LAYERS_KEY, JSON.stringify(normalizeRadarDrawingLayers(value)));
}

export async function migrateStandaloneGroundLayers(): Promise<MobileRadarDrawingLayers> {
  const current = await loadRadarDrawingLayers();
  const version = await SecureStore.getItemAsync(STANDALONE_GROUND_LAYERS_VERSION_KEY);
  if (version === "2") {
    return current;
  }
  const migrated = { ...current, runways: true, surface: true, terrain: true };
  await Promise.all([
    saveRadarDrawingLayers(migrated),
    SecureStore.setItemAsync(STANDALONE_GROUND_LAYERS_VERSION_KEY, "2")
  ]);
  return migrated;
}

export async function loadWidgetPreferences(): Promise<MobileWidgetPreferences> {
  const raw = await SecureStore.getItemAsync(WIDGET_PREFERENCES_KEY);
  if (!raw) {
    return { ...DEFAULT_WIDGET_PREFERENCES };
  }
  try {
    return normalizeWidgetPreferences(JSON.parse(raw));
  } catch {
    return { ...DEFAULT_WIDGET_PREFERENCES };
  }
}

export async function saveWidgetPreferences(value: MobileWidgetPreferences): Promise<MobileWidgetPreferences> {
  const normalized = normalizeWidgetPreferences(value);
  await SecureStore.setItemAsync(WIDGET_PREFERENCES_KEY, JSON.stringify(normalized));
  return normalized;
}

export async function loadMobileDiagnosticsMode(): Promise<MobileDiagnosticsMode> {
  return normalizeDiagnosticsMode(await SecureStore.getItemAsync(MOBILE_DIAGNOSTICS_KEY));
}

export async function saveMobileDiagnosticsMode(value: MobileDiagnosticsMode): Promise<void> {
  await SecureStore.setItemAsync(MOBILE_DIAGNOSTICS_KEY, normalizeDiagnosticsMode(value));
}

export async function loadMobileSetupState(): Promise<MobileSetupState> {
  const raw = await SecureStore.getItemAsync(MOBILE_SETUP_STATE_KEY);
  if (!raw) {
    return incompleteMobileSetupState();
  }
  try {
    return normalizeMobileSetupState(JSON.parse(raw));
  } catch {
    return incompleteMobileSetupState();
  }
}

export async function saveMobileSetupState(value: MobileSetupState): Promise<void> {
  await SecureStore.setItemAsync(MOBILE_SETUP_STATE_KEY, JSON.stringify(normalizeMobileSetupState(value)));
}

export async function resolveMobileSetupState(
  serverUrl: string,
  diagnosticsMode: MobileDiagnosticsMode
): Promise<MobileSetupState> {
  const saved = await loadMobileSetupState();
  if (isMobileSetupComplete(saved, saved.serverUrl, saved.diagnosticsMode)) {
    return saved;
  }
  if (isMobileSetupComplete(saved, serverUrl || saved.serverUrl, diagnosticsMode || saved.diagnosticsMode)) {
    return saved;
  }
  if (serverUrl && normalizeDiagnosticsMode(diagnosticsMode) !== "unset") {
    const migrated = completeMobileSetupState(serverUrl, diagnosticsMode);
    await saveMobileSetupState(migrated);
    return migrated;
  }
  return normalizeMobileSetupState({
    ...saved,
    serverUrl: serverUrl || saved.serverUrl,
    diagnosticsMode: diagnosticsMode || saved.diagnosticsMode,
    complete: false,
    completedAt: null
  });
}
