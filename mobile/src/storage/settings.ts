import * as SecureStore from "expo-secure-store";
import type { MobileSkin, MobileThemeMode } from "../theme/tokens";

const SERVER_URL_KEY = "localflight.serverUrl";
const PINNED_FLIGHT_KEY = "localflight.pinnedFlight";
const PROFILES_KEY = "localflight.profiles";
const COMPANION_ID_KEY = "localflight.companionId";
const APPEARANCE_THEME_KEY = "localflight.mobileTheme";
const APPEARANCE_SKIN_KEY = "localflight.mobileSkin";
const WEATHER_DISPLAY_KEY = "localflight.weatherDisplayMode";
const MOBILE_DIAGNOSTICS_KEY = "localflight.mobileDiagnosticsMode";
const MOBILE_SETUP_STATE_KEY = "localflight.mobileSetupState";

const DEFAULT_THEME_MODE: MobileThemeMode = "dark";
const DEFAULT_SKIN: MobileSkin = "technical";

let companionIdCache: string | null = null;

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
export type MobileWeatherDisplayMode = "friendly" | "light" | "raw";
export type MobileSetupMode = "lan_companion";

export type MobileSetupState = {
  complete: boolean;
  mode: MobileSetupMode;
  serverUrl: string;
  diagnosticsMode: MobileDiagnosticsMode;
  completedAt: string | null;
};

function createCompanionId(): string {
  const part = () => Math.floor(Math.random() * 0xffffffff).toString(16).padStart(8, "0");
  return `lfc_${part()}${part()}${Date.now().toString(16).slice(-8)}`;
}

export async function loadServerUrl(): Promise<string> {
  return (await SecureStore.getItemAsync(SERVER_URL_KEY)) || "";
}

export async function saveServerUrl(serverUrl: string): Promise<void> {
  await SecureStore.setItemAsync(SERVER_URL_KEY, serverUrl);
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

export async function loadPinnedFlight(): Promise<string> {
  return (await SecureStore.getItemAsync(PINNED_FLIGHT_KEY)) || "";
}

export async function savePinnedFlight(value: string): Promise<void> {
  if (!value) {
    await SecureStore.deleteItemAsync(PINNED_FLIGHT_KEY);
    return;
  }
  await SecureStore.setItemAsync(PINNED_FLIGHT_KEY, value);
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

function normalizeSkin(value: string | null | undefined): MobileSkin {
  switch (value) {
    case "standard":
    case "technical":
    case "neon":
    case "cyan":
    case "crt":
      return value;
    default:
      return DEFAULT_SKIN;
  }
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
    case "light":
    case "raw":
      return value;
    default:
      return "friendly";
  }
}

export function incompleteMobileSetupState(
  serverUrl = "",
  diagnosticsMode: MobileDiagnosticsMode = "unset"
): MobileSetupState {
  return {
    complete: false,
    mode: "lan_companion",
    serverUrl,
    diagnosticsMode: normalizeDiagnosticsMode(diagnosticsMode),
    completedAt: null
  };
}

export function completeMobileSetupState(
  serverUrl: string,
  diagnosticsMode: MobileDiagnosticsMode
): MobileSetupState {
  return {
    complete: true,
    mode: "lan_companion",
    serverUrl,
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
  const serverUrl = typeof state.serverUrl === "string" ? state.serverUrl : "";
  const complete = Boolean(state.complete && serverUrl && diagnosticsMode !== "unset");
  return {
    complete,
    mode: "lan_companion",
    serverUrl,
    diagnosticsMode,
    completedAt: complete && typeof state.completedAt === "string" ? state.completedAt : null
  };
}

export function isMobileSetupComplete(
  state: MobileSetupState,
  serverUrl = state.serverUrl,
  diagnosticsMode: MobileDiagnosticsMode = state.diagnosticsMode
): boolean {
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

export async function saveAppearancePrefs(value: {
  themeMode: MobileThemeMode;
  skin: MobileSkin;
}): Promise<void> {
  await Promise.all([
    SecureStore.setItemAsync(APPEARANCE_THEME_KEY, normalizeThemeMode(value.themeMode)),
    SecureStore.setItemAsync(APPEARANCE_SKIN_KEY, normalizeSkin(value.skin))
  ]);
}

export async function loadWeatherDisplayMode(): Promise<MobileWeatherDisplayMode> {
  return normalizeWeatherDisplayMode(await SecureStore.getItemAsync(WEATHER_DISPLAY_KEY));
}

export async function saveWeatherDisplayMode(value: MobileWeatherDisplayMode): Promise<void> {
  await SecureStore.setItemAsync(WEATHER_DISPLAY_KEY, normalizeWeatherDisplayMode(value));
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
