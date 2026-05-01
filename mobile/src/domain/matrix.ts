import type { FidsRow, FlightView, MatrixRuntimeConfig, MatrixRuntimeConfigSave } from "../api/types";
import type { MobileSkin } from "../theme/tokens";
import { DEFAULT_MATRIX_CONFIG } from "./constants";
import { routeCode, routeName, statusShort } from "./flights";
import type { MatrixPreset } from "./types";

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

export function normalizeMatrixRuntimeConfig(
  value?: MatrixRuntimeConfig | MatrixRuntimeConfigSave | null
): MatrixRuntimeConfigSave {
  return {
    brightness: Math.max(0, Math.min(1, Number(value?.brightness ?? DEFAULT_MATRIX_CONFIG.brightness) || DEFAULT_MATRIX_CONFIG.brightness)),
    max_rows: Math.max(1, Math.min(8, Number(value?.max_rows ?? DEFAULT_MATRIX_CONFIG.max_rows) || DEFAULT_MATRIX_CONFIG.max_rows)),
    refresh_seconds: Math.max(10, Math.min(3600, Number(value?.refresh_seconds ?? DEFAULT_MATRIX_CONFIG.refresh_seconds) || DEFAULT_MATRIX_CONFIG.refresh_seconds)),
    default_view: normalizeMatrixDefaultView(value?.default_view)
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
    left.default_view === right.default_view
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

export function matrixClientConfig(opts: {
  serverUrl: string;
  airportIata?: string | null;
  airportIcao?: string | null;
  preset: MatrixPreset;
  rows: number;
  brightness: number;
  refreshSeconds: number;
  view: FlightView;
  normalizeServerUrl: (value: string) => string;
}): string {
  let host = "192.168.1.100";
  let port = "8000";

  try {
    const parsed = new URL(opts.normalizeServerUrl(opts.serverUrl));
    host = parsed.hostname || host;
    port = parsed.port || (parsed.protocol === "https:" ? "443" : "8000");
  } catch {
    // Keep the friendly defaults when the URL is not available yet.
  }

  return [
    `API_HOST      = "${host}"`,
    `API_PORT      = ${port}`,
    `AIRPORT_IATA  = "${opts.airportIata || "ZRH"}"`,
    `AIRPORT_ICAO  = "${opts.airportIcao || "LSZH"}"`,
    `PANEL_W       = ${opts.preset.panelW}`,
    `PANEL_H       = ${opts.preset.panelH}`,
    `MAX_ROWS      = ${opts.rows}`,
    `BRIGHTNESS    = ${opts.brightness.toFixed(2)}`,
    `DEFAULT_VIEW  = "${opts.view}"`,
    `REFRESH_S     = ${opts.refreshSeconds}`,
    `PING_S        = 600`
  ].join("\n");
}
