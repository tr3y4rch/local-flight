import * as SecureStore from "expo-secure-store";

const SERVER_URL_KEY = "localflight.serverUrl";
const PINNED_FLIGHT_KEY = "localflight.pinnedFlight";
const PROFILES_KEY = "localflight.profiles";

export type ConfigProfile = {
  id: string;
  name: string;
  iata: string;
  icao: string;
  timezone?: string;
  source: "real" | "virtual";
  refresh_seconds: number;
};

export async function loadServerUrl(): Promise<string> {
  return (await SecureStore.getItemAsync(SERVER_URL_KEY)) || "";
}

export async function saveServerUrl(serverUrl: string): Promise<void> {
  await SecureStore.setItemAsync(SERVER_URL_KEY, serverUrl);
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
