import type { ComponentProps } from "react";
import type { StyleProp, TextStyle } from "react-native";
import { MaterialCommunityIcons } from "@expo/vector-icons";

import type { Metar } from "../api/types";
import type { Screen } from "../domain/types";

export type LocalFlightIconName = ComponentProps<typeof MaterialCommunityIcons>["name"];

type LocalFlightIconProps = Omit<ComponentProps<typeof MaterialCommunityIcons>, "name" | "size" | "color"> & {
  name: LocalFlightIconName;
  size?: number;
  color: string;
  style?: StyleProp<TextStyle>;
};

export function LocalFlightIcon({
  name,
  size = 18,
  color,
  style,
  ...rest
}: LocalFlightIconProps) {
  return <MaterialCommunityIcons name={name} size={size} color={color} style={style} {...rest} />;
}

export const NAV_ICONS: Record<Extract<Screen, "fids" | "radar" | "history" | "control" | "help" | "settings">, LocalFlightIconName> = {
  fids: "airplane-takeoff",
  radar: "radar",
  history: "history",
  control: "tune-variant",
  help: "lifebuoy",
  settings: "cog-outline"
};

export const SUPPORT_ICONS = {
  github: "github",
  support: "heart-outline",
  coffee: "coffee-outline",
  feedback: "message-alert-outline"
} as const satisfies Record<string, LocalFlightIconName>;

export const STATUS_ICONS = {
  live: "check-circle",
  retrying: "progress-clock",
  offline: "alert-circle-outline",
  unavailable: "cloud-alert-outline"
} as const satisfies Record<string, LocalFlightIconName>;

export const SOURCE_ICONS = {
  real: "broadcast",
  virtual: "controller-classic-outline",
  relay: "server-network",
  byok: "key-variant",
  local: "home-variant-outline"
} as const satisfies Record<string, LocalFlightIconName>;

export const ACTION_ICONS = {
  back: "chevron-left",
  next: "arrow-right",
  openExternal: "open-in-new",
  retry: "refresh",
  close: "close",
  delete: "trash-can-outline",
  search: "card-search-outline",
  connect: "lan-connect",
  finish: "airplane-takeoff",
  checklist: "clipboard-check-outline",
  progress: "progress-clock",
  pin: "pin",
  configured: "check-circle",
  supportExpand: "chevron-up",
  drillIn: "chevron-right"
} as const satisfies Record<string, LocalFlightIconName>;

export const TOOL_ICONS = {
  appearance: "palette-outline",
  matrix: "view-grid",
  admin: "tools",
  history: "history",
  docs: "book-open-variant",
  privacy: "shield-lock-outline",
  displayModes: "monitor-dashboard",
  install: "book-open-page-variant",
  changelog: "format-list-bulleted",
  setup: "restart-alert",
  github: "github",
  control: "tune-variant",
  help: "lifebuoy",
  report: "alert-circle-outline"
} as const satisfies Record<string, LocalFlightIconName>;

export const SETUP_ICONS = {
  server: "server-network",
  lan: "wifi",
  privacy: "shield-check",
  scan: "qrcode-scan",
  keyboard: "keyboard-outline",
  link: "link-variant",
  ok: "check-circle",
  error: "alert-circle",
  checking: "progress-clock"
} as const satisfies Record<string, LocalFlightIconName>;

const WEATHER_ICON_ALIASES: Record<string, LocalFlightIconName> = {
  clear: "weather-sunny",
  sun: "weather-sunny",
  sunny: "weather-sunny",
  vfr: "weather-sunny",
  partly: "weather-partly-cloudy",
  partly_cloudy: "weather-partly-cloudy",
  "partly cloudy": "weather-partly-cloudy",
  cloud: "weather-cloudy",
  cloudy: "weather-cloudy",
  overcast: "weather-cloudy",
  rain: "weather-rainy",
  showers: "weather-rainy",
  drizzle: "weather-rainy",
  storm: "weather-lightning-rainy",
  thunder: "weather-lightning-rainy",
  thunderstorm: "weather-lightning-rainy",
  snow: "weather-snowy",
  fog: "weather-fog",
  mist: "weather-fog",
  haze: "weather-fog",
  wind: "weather-windy",
  windy: "weather-windy",
  ice: "snowflake-alert",
  unknown: "weather-cloudy-alert"
};
const DEFAULT_WEATHER_ICON: LocalFlightIconName = "weather-cloudy-alert";

function normalizeWeatherKey(value: unknown): string {
  return String(value || "").trim().toLowerCase().replace(/[-\s]+/g, "_");
}

export function weatherIconForMetar(metar: Metar | null | undefined): LocalFlightIconName {
  const semantic = normalizeWeatherKey(metar?.weather_icon || metar?.weather_condition || metar?.weather_label);
  if (semantic && WEATHER_ICON_ALIASES[semantic]) {
    return WEATHER_ICON_ALIASES[semantic];
  }

  const text = [
    metar?.weather_summary,
    metar?.decoded_summary,
    metar?.raw_text,
    metar?.weather_label,
    metar?.flight_cat,
    metar?.flight_category,
    metar?.category
  ].join(" ").toLowerCase();

  if (/thunder|tsra|ts\b|storm/.test(text)) return WEATHER_ICON_ALIASES.storm || DEFAULT_WEATHER_ICON;
  if (/snow|\bsn\b|ice|freez/.test(text)) return WEATHER_ICON_ALIASES.snow || DEFAULT_WEATHER_ICON;
  if (/rain|showers|\bra\b|drizzle|\bdz\b/.test(text)) return WEATHER_ICON_ALIASES.rain || DEFAULT_WEATHER_ICON;
  if (/fog|mist|\bfg\b|\bbr\b|haze/.test(text)) return WEATHER_ICON_ALIASES.fog || DEFAULT_WEATHER_ICON;
  if (/wind|gust|squall/.test(text)) return WEATHER_ICON_ALIASES.wind || DEFAULT_WEATHER_ICON;
  if (/overcast|broken|\bovc\b|\bbkn\b|cloud/.test(text)) return WEATHER_ICON_ALIASES.cloud || DEFAULT_WEATHER_ICON;
  if (/few|scattered|\bfew\b|\bsct\b|partly/.test(text)) return WEATHER_ICON_ALIASES.partly || DEFAULT_WEATHER_ICON;
  if (/cavok|clear|sun|no significant|vfr/.test(text)) return WEATHER_ICON_ALIASES.sun || DEFAULT_WEATHER_ICON;
  return WEATHER_ICON_ALIASES.unknown || DEFAULT_WEATHER_ICON;
}
