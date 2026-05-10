import type {
  FidsRow,
  FlightView,
  MatrixAnimationMode,
  MatrixPaletteId,
  MatrixRuntimeConfig,
  MatrixRuntimeConfigSave
} from "../api/types";
import type { MobileSkin } from "../theme/tokens";
import { DEFAULT_MATRIX_CONFIG, MATRIX_PALETTE_OPTIONS } from "./constants";
import { routeCode, routeName, statusShort } from "./flights";

export const MATRIX_SKIN_PALETTES: Record<MobileSkin, {
  off: string;
  green: string;
  white: string;
  dim: string;
  amber: string;
  red: string;
  cyan: string;
}> = {
  standard: { off: "#060806", green: "#00dc3c", white: "#dcffe0", dim: "#005012", amber: "#ffa000", red: "#dc1e1e", cyan: "#00ccff" },
  technical: { off: "#040608", green: "#4a9eda", white: "#c8d8e8", dim: "#1a3a5a", amber: "#d4a020", red: "#c04040", cyan: "#4a9eda" },
  neon: { off: "#000d00", green: "#00ff50", white: "#00ff50", dim: "#007a28", amber: "#aaff00", red: "#ff4040", cyan: "#00ff50" },
  cyan: { off: "#00080f", green: "#00ccff", white: "#00ffcc", dim: "#006688", amber: "#ffcc00", red: "#ff4060", cyan: "#00ccff" },
  crt: { off: "#060400", green: "#ffaa00", white: "#ffcc44", dim: "#7a5000", amber: "#ffdd00", red: "#ff4020", cyan: "#ffaa00" }
};

export const MATRIX_LED_PALETTES = Object.fromEntries(
  MATRIX_PALETTE_OPTIONS.map((item) => [item.id, item.colors])
) as Record<MatrixPaletteId, {
  off: string;
  green: string;
  white: string;
  dim: string;
  amber: string;
  red: string;
  cyan: string;
}>;

export function normalizeMatrixDefaultView(value?: string | null): FlightView {
  return value === "arrivals" ? "arrivals" : "departures";
}

export function normalizeMatrixSkin(value?: string | null): MobileSkin {
  switch (value) {
    case "standard":
    case "technical":
    case "neon":
    case "cyan":
    case "crt":
      return value;
    default:
      return "standard";
  }
}

export function normalizeMatrixPalette(value?: string | null): MatrixPaletteId {
  return MATRIX_PALETTE_OPTIONS.some((item) => item.id === value)
    ? value as MatrixPaletteId
    : DEFAULT_MATRIX_CONFIG.palette;
}

export function normalizeMatrixAnimationMode(value?: string | null): MatrixAnimationMode {
  switch (value) {
    case "split_flap":
    case "slide_left":
    case "slide_right":
    case "static":
      return value;
    default:
      return DEFAULT_MATRIX_CONFIG.animation_mode;
  }
}

function normalizeMatrixShowWeather(value?: MatrixRuntimeConfig | MatrixRuntimeConfigSave | null): boolean {
  const options = value?.options || {};
  if (typeof options.show_metar === "boolean") return options.show_metar;
  if (typeof options.show_weather === "boolean") return options.show_weather;
  return Boolean(DEFAULT_MATRIX_CONFIG.options.show_metar);
}

export function normalizeMatrixRuntimeConfig(
  value?: MatrixRuntimeConfig | MatrixRuntimeConfigSave | null
): MatrixRuntimeConfigSave {
  const palette = normalizeMatrixPalette(value?.palette || value?.options?.palette);
  const animationEnabled = value?.animation_enabled ?? DEFAULT_MATRIX_CONFIG.animation_enabled;
  const animationMode = animationEnabled === false
    ? "static"
    : normalizeMatrixAnimationMode(value?.animation_mode || value?.options?.animation_mode);
  const showWeather = normalizeMatrixShowWeather(value);

  return {
    brightness: Math.max(0.05, Math.min(1, Number(value?.brightness ?? DEFAULT_MATRIX_CONFIG.brightness) || DEFAULT_MATRIX_CONFIG.brightness)),
    max_rows: Math.max(1, Math.min(8, Number(value?.max_rows ?? DEFAULT_MATRIX_CONFIG.max_rows) || DEFAULT_MATRIX_CONFIG.max_rows)),
    refresh_seconds: Math.max(10, Math.min(3600, Number(value?.refresh_seconds ?? DEFAULT_MATRIX_CONFIG.refresh_seconds) || DEFAULT_MATRIX_CONFIG.refresh_seconds)),
    default_view: normalizeMatrixDefaultView(value?.default_view),
    page_rotation_seconds: Math.max(3, Math.min(120, Number(value?.page_rotation_seconds ?? DEFAULT_MATRIX_CONFIG.page_rotation_seconds) || DEFAULT_MATRIX_CONFIG.page_rotation_seconds)),
    animation_enabled: animationMode !== "static",
    animation_mode: animationMode,
    animation_speed: Math.max(1, Math.min(5, Number(value?.animation_speed ?? DEFAULT_MATRIX_CONFIG.animation_speed) || DEFAULT_MATRIX_CONFIG.animation_speed)),
    status_animation_enabled: value?.status_animation_enabled ?? DEFAULT_MATRIX_CONFIG.status_animation_enabled,
    palette,
    options: {
      ...(value?.options || {}),
      palette,
      show_metar: showWeather,
      show_weather: showWeather,
      animation_mode: animationMode
    }
  };
}

export function matrixConfigsEqual(
  left?: MatrixRuntimeConfigSave | null,
  right?: MatrixRuntimeConfigSave | null
): boolean {
  if (!left && !right) return true;
  if (!left || !right) return false;
  return (
    left.brightness === right.brightness &&
    left.max_rows === right.max_rows &&
    left.refresh_seconds === right.refresh_seconds &&
    left.default_view === right.default_view &&
    left.page_rotation_seconds === right.page_rotation_seconds &&
    left.animation_enabled === right.animation_enabled &&
    left.animation_mode === right.animation_mode &&
    left.animation_speed === right.animation_speed &&
    left.status_animation_enabled === right.status_animation_enabled &&
    left.palette === right.palette &&
    Boolean(left.options.show_metar) === Boolean(right.options.show_metar)
  );
}

export function matrixPreviewLines(rows: FidsRow[]): string[] {
  if (!rows.length) {
    return ["NO DATA LINK", "RUN SNAPSHOT", "THEN REFRESH", "MATRIX READY"];
  }

  return rows.slice(0, 4).map((row) => {
    const time = (row.display_time || "--:--").replace(/\s*\([^)]*\)\s*/g, "").slice(0, 5).padEnd(5, " ");
    const flight = (row.flight_display || row.callsign || "--").replace(/\s+/g, "").slice(0, 7).padEnd(7, " ");
    const route = (routeCode(row.route_display) || routeName(row.route_display)).replace(/\s+/g, "").slice(0, 4).padEnd(4, " ");
    const status = statusShort(row.status_display).slice(0, 6).padEnd(6, " ");
    return `${time} ${flight} ${route} ${status}`.trimEnd();
  });
}
