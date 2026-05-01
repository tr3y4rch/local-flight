import type { DashboardSnapshot, MatrixRuntimeConfigSave } from "../api/types";
import { appVersion } from "../device/identity";
import type { HistoryWindow, MatrixPreset, RadarRadius } from "./types";

export const APP_VERSION = appVersion();
export const COMPANION_PING_MS = 10 * 60 * 1000;

export const HISTORY_WINDOWS: HistoryWindow[] = [24, 72, 168];
export const RADAR_RADII: RadarRadius[] = [10, 20, 40, 80];

export const MATRIX_PRESETS: MatrixPreset[] = [
  { label: "64x32", panelW: 64, panelH: 32, modules: "1 module" },
  { label: "128x32", panelW: 128, panelH: 32, modules: "2 modules" },
  { label: "256x32", panelW: 256, panelH: 32, modules: "4 modules" },
  { label: "128x64", panelW: 128, panelH: 64, modules: "2 panels" },
  { label: "256x64", panelW: 256, panelH: 64, modules: "4-panel starter" },
  { label: "384x64", panelW: 384, panelH: 64, modules: "6-panel wide" }
];

export const MATRIX_ROWS = [2, 3, 4, 5, 6];
export const MATRIX_BRIGHTNESS = [0.4, 0.6, 0.8, 1];
export const MATRIX_REFRESH_SECONDS = [30, 60, 120, 300];

export const LAUNCH_MIN_MS = 6200;
export const LAUNCH_NATIVE_MIN_MS = 420;
export const LAUNCH_ANIMATION_DELAY_MS = 180;
export const LAUNCH_STATUS_STEPS = [
  "Starting companion",
  "Loading saved server",
  "Checking flight board",
  "Priming radar sweep",
  "Syncing local profile",
  "Opening companion"
];

export const REFRESH_OPTIONS: Array<{ seconds: number; label: string }> = [
  { seconds: 900, label: "15 min" },
  { seconds: 1800, label: "30 min" },
  { seconds: 2700, label: "45 min" },
  { seconds: 3600, label: "1 h" },
  { seconds: 7200, label: "2 h" },
  { seconds: 14400, label: "4 h" },
  { seconds: 28800, label: "8 h" },
  { seconds: 43200, label: "12 h" },
  { seconds: 86400, label: "24 h" }
];

export const EMPTY_SNAPSHOT: DashboardSnapshot = {
  config: null,
  state: null,
  system: null,
  connections: null,
  updates: null,
  budget: null,
  metar: null
};

export const DEFAULT_MATRIX_CONFIG: MatrixRuntimeConfigSave = {
  brightness: 0.8,
  max_rows: 4,
  refresh_seconds: 60,
  default_view: "departures"
};
