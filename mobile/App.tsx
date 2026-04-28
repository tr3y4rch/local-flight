import { useCallback, useEffect, useRef, useState, type ComponentProps } from "react";
import {
  ActivityIndicator,
  Animated,
  Easing,
  FlatList,
  Image,
  Linking,
  Modal,
  PanResponder,
  Pressable,
  RefreshControl,
  ScrollView,
  StatusBar,
  StyleSheet,
  Text,
  TextInput,
  View
} from "react-native";
import { MaterialCommunityIcons } from "@expo/vector-icons";
import * as SplashScreen from "expo-splash-screen";
import { SafeAreaProvider, SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";

import {
  getAdminSystem,
  getBudget,
  getConnections,
  getConfig,
  getFids,
  getFidsDetail,
  getHealth,
  getHistory,
  getMetar,
  getRadar,
  getUpdates,
  normalizeServerUrl,
  patchConfig,
  restartScheduler,
  searchAirports,
  sendCompanionCheckin,
  submitFeedback,
  testConnection,
  wsUrl
} from "./src/api/client";
import type {
  AppConfig,
  AirportResult,
  ConfigPatch,
  DashboardSnapshot,
  FidsDetailResponse,
  FidsRow,
  FlightDetail,
  FlightView,
  HistoryDirection,
  HistoryFlightRow,
  HistoryResponse,
  RadarBlip,
  RadarResponse
} from "./src/api/types";
import { CrashBoundary } from "./src/crash/CrashBoundary";
import { installGlobalCrashReporter, reportMobileCrash } from "./src/crash/reporter";
import { appVersion, getCompanionIdentity, platformPairLabel, type CompanionIdentity } from "./src/device/identity";
import { type ConfigProfile, loadPinnedFlight, loadProfiles, loadServerUrl, savePinnedFlight, saveProfiles, saveServerUrl } from "./src/storage/settings";
import { mono, palette } from "./src/theme/tokens";
import { useResponsiveLayout } from "./src/utils/layout";

type Screen = "fids" | "radar" | "history" | "matrix" | "admin" | "settings";
type StatusTone = "scheduled" | "departed" | "boarding" | "delayed" | "cancelled";
type HistoryWindow = 24 | 72 | 168;
type RadarRadius = 20 | 40 | 80;
type MaterialIconName = ComponentProps<typeof MaterialCommunityIcons>["name"];
type FeedbackTone = "ok" | "error";
type MatrixPreset = {
  label: string;
  panelW: number;
  panelH: number;
  modules: string;
};

type RefreshOptions = {
  nextUrl?: string;
  target?: Screen;
  nextView?: FlightView;
  nextHistoryDirection?: HistoryDirection;
  nextHistoryHours?: HistoryWindow;
  nextRadarRadius?: RadarRadius;
};

type ProjectedBlip = {
  blip: RadarBlip;
  left: number;
  top: number;
  distanceNm: number;
};

const APP_VERSION = appVersion();
const COMPANION_PING_MS = 10 * 60 * 1000;
const HISTORY_WINDOWS: HistoryWindow[] = [24, 72, 168];
const RADAR_RADII: RadarRadius[] = [20, 40, 80];
const MATRIX_PRESETS: MatrixPreset[] = [
  { label: "64x32", panelW: 64, panelH: 32, modules: "1 module" },
  { label: "128x32", panelW: 128, panelH: 32, modules: "2 modules" },
  { label: "256x32", panelW: 256, panelH: 32, modules: "4 modules" },
  { label: "128x64", panelW: 128, panelH: 64, modules: "2 panels" },
  { label: "256x64", panelW: 256, panelH: 64, modules: "4-panel starter" },
  { label: "384x64", panelW: 384, panelH: 64, modules: "6-panel wide" }
];
const MATRIX_ROWS = [2, 3, 4, 5, 6];
const MATRIX_BRIGHTNESS = [40, 60, 80, 100];
const LAUNCH_MIN_MS = 6200;
const LAUNCH_NATIVE_MIN_MS = 420;
const LAUNCH_ANIMATION_DELAY_MS = 180;
const LAUNCH_STATUS_STEPS = [
  "Starting companion",
  "Loading saved server",
  "Checking flight board",
  "Priming radar sweep",
  "Syncing local profile",
  "Opening companion"
];
const REFRESH_OPTIONS: Array<{ seconds: number; label: string }> = [
  { seconds: 900,   label: "15 min" },
  { seconds: 1800,  label: "30 min" },
  { seconds: 2700,  label: "45 min" },
  { seconds: 3600,  label: "1 h" },
  { seconds: 7200,  label: "2 h" },
  { seconds: 14400, label: "4 h" },
  { seconds: 28800, label: "8 h" },
  { seconds: 43200, label: "12 h" },
  { seconds: 86400, label: "24 h" },
];

const EMPTY_SNAPSHOT: DashboardSnapshot = {
  config: null,
  state: null,
  system: null,
  connections: null,
  updates: null,
  budget: null,
  metar: null
};

void SplashScreen.preventAutoHideAsync().catch(() => {
  // Ignore duplicate registration during fast refresh.
});
SplashScreen.setOptions({
  duration: 320,
  fade: true
});

function formatUtc(): string {
  return new Date().toLocaleTimeString("en-GB", {
    timeZone: "UTC",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
  });
}

function formatLocalTime(): string {
  return new Date().toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  });
}

function formatRelative(value?: string | null): string {
  if (!value) return "Never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  return date.toLocaleString();
}

function formatDateTime(value?: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function formatClock(value?: string | null): string {
  if (!value) return "--:--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  });
}

function routeCode(route: string): string {
  const trimmed = route.trim();
  const match = trimmed.match(/\(([A-Z0-9]{3,4})\)/);
  if (match?.[1]) return match[1];
  const plainCode = trimmed.match(/^([A-Z0-9]{3,4})$/);
  return plainCode?.[1] || "";
}

function routeName(route: string): string {
  const trimmed = route.trim();
  if (!trimmed) return "-";
  const code = routeCode(trimmed);
  if (code && trimmed === code) return code;
  return trimmed.replace(/\s*\([A-Z0-9]{3,4}\)\s*$/, "").trim() || code || "-";
}

function routeMeta(row: FidsRow): string {
  const code = routeCode(row.route_display);
  const gate = row.gate && row.gate !== "-" ? `G${row.gate}` : "";
  if (code && gate) return `${code} · ${gate}`;
  if (code) return code;
  if (gate) return gate;
  return "---";
}

function statusTone(status: string): StatusTone {
  const value = status.toLowerCase();
  if (value.includes("board") || value.includes("land") || value.includes("arriv")) return "boarding";
  if (value.includes("delay")) return "delayed";
  if (value.includes("depart") || value.includes("dept")) return "departed";
  if (value.includes("cancel")) return "cancelled";
  return "scheduled";
}

function formatAltitudeFeet(value?: number | null): string {
  if (value == null) return "-";
  return `${Math.round(value * 3.28084)} ft`;
}

function formatSpeedKnots(value?: number | null): string {
  if (value == null) return "-";
  return `${Math.round(value * 1.94384)} kt`;
}

function formatHeading(value?: number | null): string {
  if (value == null) return "-";
  return `${Math.round(value)} deg`;
}

function detailOrNull(value: FidsDetailResponse | null): FlightDetail | null {
  if (!value?.detail || typeof value.detail !== "object") {
    return null;
  }
  if (!("callsign" in value.detail) || typeof value.detail.callsign !== "string") {
    return null;
  }
  return value.detail as FlightDetail;
}

function historyRouteLabel(row: HistoryFlightRow): string {
  if (row.direction === "ARR") {
    return `FROM ${row.origin_iata || "---"}`;
  }
  if (row.direction === "DEP") {
    return `TO ${row.dest_iata || "---"}`;
  }
  return `${row.origin_iata || "---"} / ${row.dest_iata || "---"}`;
}

function detailRouteLabel(detail: FlightDetail | null, fallback: string): string {
  if (!detail) return fallback;
  const origin = detail.origin_iata || "---";
  const dest = detail.dest_iata || "---";
  return `${origin} -> ${dest}`;
}

function projectBlip(
  blip: RadarBlip,
  center: { lat: number; lon: number },
  radiusNm: number,
  scopeSize: number
): ProjectedBlip | null {
  const latDeltaNm = (blip.lat - center.lat) * 60;
  const lonDeltaNm =
    (blip.lon - center.lon) * 60 * Math.cos((center.lat * Math.PI) / 180);
  const distanceNm = Math.sqrt(latDeltaNm ** 2 + lonDeltaNm ** 2);

  if (!Number.isFinite(distanceNm) || distanceNm > radiusNm) {
    return null;
  }

  const usableRadiusPx = scopeSize * 0.42;
  const dotOffset = 5;
  const x = scopeSize / 2 + (lonDeltaNm / radiusNm) * usableRadiusPx - dotOffset;
  const y = scopeSize / 2 - (latDeltaNm / radiusNm) * usableRadiusPx - dotOffset;

  return { blip, left: x, top: y, distanceNm };
}

function errorMessage(value: unknown): string {
  return value instanceof Error ? value.message : String(value);
}

function metarAccentColor(category: string): string {
  switch (category.toUpperCase()) {
    case "VFR":  return palette.green;
    case "MVFR": return palette.blue;
    case "IFR":  return palette.amber;
    case "LIFR": return palette.red;
    default:     return palette.blue;
  }
}

function parseMetarChips(metar: string): Array<{ label: string; value: string }> {
  const chips: Array<{ label: string; value: string }> = [];
  const windM = metar.match(/(\d{3}|VRB)(\d{2,3})(G(\d+))?KT/);
  if (windM) {
    const dir = windM[1] === "VRB" ? "VRB" : `${windM[1] ?? "000"}°`;
    const gust = windM[4] ? `G${windM[4]}` : "";
    chips.push({ label: "WND", value: `${dir} ${parseInt(windM[2] ?? "0")}${gust}kt` });
  }
  const visM = metar.match(/\b(9999|\d{4})\b(?!KT)/);
  if (visM) {
    const v = parseInt(visM[1] ?? "0");
    chips.push({ label: "VIS", value: v >= 9999 ? ">10km" : `${(v / 1000).toFixed(1)}km` });
  }
  const cldM = metar.match(/(FEW|SCT|BKN|OVC)(\d{3})/);
  if (cldM) chips.push({ label: cldM[1] ?? "CLD", value: `${parseInt(cldM[2] ?? "0") * 100}ft` });
  const tmpM = metar.match(/\b(M?\d{1,2})\/(M?\d{1,2})\b/);
  if (tmpM) chips.push({ label: "TMP", value: `${(tmpM[1] ?? "").replace("M", "-")}°C` });
  const qnhM = metar.match(/Q(\d{4})/);
  if (qnhM) chips.push({ label: "QNH", value: qnhM[1] ?? "" });
  return chips;
}

function formatInterval(seconds: number): string {
  const opt = REFRESH_OPTIONS.find(o => o.seconds === seconds);
  if (opt) return opt.label;
  return seconds < 3600 ? `${Math.round(seconds / 60)}m` : `${Math.round(seconds / 3600)}h`;
}

function companionSyncMs(seconds?: number | null): number {
  const serverMs = Math.max(60, seconds || 60) * 1000;
  return Math.min(serverMs, 30 * 60 * 1000);
}

function flightPinKey(row: FidsRow): string {
  return row.callsign || row.id;
}

function mobileClientContext(
  serverUrl: string,
  snapshot?: DashboardSnapshot,
  companion?: CompanionIdentity | null
): string {
  const mobileOs = companion?.mobileOs || "Unknown mobile OS";
  const companionId = companion?.companionId || "unknown";
  const serverPlatform = snapshot?.system?.platform || "unknown";
  return [
    `Reporter       ${companion?.clientName || "Local Flight Companion"}`,
    `Companion ID   ${companionId}`,
    `App version    ${companion?.appVersion || APP_VERSION}`,
    `Companion OS   ${mobileOs}`,
    `Server install ${snapshot?.system?.install_id || "unknown"}`,
    `Platform pair  ${platformPairLabel(serverPlatform, mobileOs)}`,
    `Server URL     ${normalizeServerUrl(serverUrl) || "not set"}`,
    `Airport        ${snapshot?.config?.airport_iata || "---"}`,
    `Source         ${snapshot?.state?.source_name || snapshot?.config?.source || "unknown"}`
  ].join("\n");
}

function statusShort(status: string): string {
  const normalized = status.replace(/\s+/g, " ").trim().toUpperCase();
  if (!normalized) return "WAIT";
  if (normalized.startsWith("DELAYED")) {
    const mins = normalized.match(/[+-]?\d+/)?.[0];
    return mins ? `DLY${mins}` : "DELAY";
  }
  if (normalized.startsWith("BOARD")) return "BOARD";
  if (normalized.startsWith("SCHEDULED")) return "SCHED";
  if (normalized.startsWith("DEPART")) return "DEPT";
  if (normalized.startsWith("ARRIV") || normalized.startsWith("LANDED")) return "LAND";
  if (normalized.startsWith("APPR")) return normalized.slice(0, 7);
  return normalized.slice(0, 7);
}

function matrixPreviewLines(rows: FidsRow[]): string[] {
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

function matrixClientConfig(opts: {
  serverUrl: string;
  airportIata?: string | null;
  airportIcao?: string | null;
  preset: MatrixPreset;
  rows: number;
  brightness: number;
  view: FlightView;
}): string {
  let host = "192.168.1.100";
  let port = "8000";

  try {
    const parsed = new URL(normalizeServerUrl(opts.serverUrl));
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
    `BRIGHTNESS    = ${(opts.brightness / 100).toFixed(1)}`,
    `DEFAULT_VIEW  = "${opts.view}"`,
    `REFRESH_S     = 60`,
    `PING_S        = 600`
  ].join("\n");
}

export default function App() {
  return (
    <SafeAreaProvider>
      <CrashBoundary>
        <AppShell />
      </CrashBoundary>
    </SafeAreaProvider>
  );
}

function AppShell() {
  const layout = useResponsiveLayout();
  const insets = useSafeAreaInsets();
  const [screen, setScreen] = useState<Screen>("fids");
  const [view, setView] = useState<FlightView>("departures");
  const [historyDirection, setHistoryDirection] = useState<HistoryDirection>("both");
  const [historyHours, setHistoryHours] = useState<HistoryWindow>(24);
  const [radarRadius, setRadarRadius] = useState<RadarRadius>(20);
  const [serverUrl, setServerUrl] = useState("");
  const [draftUrl, setDraftUrl] = useState("");
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [schedulerRestarting, setSchedulerRestarting] = useState(false);
  const [schedulerMessage, setSchedulerMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [utcTime, setUtcTime] = useState(formatUtc());
  const [localTime, setLocalTime] = useState(formatLocalTime());
  const [snapshot, setSnapshot] = useState<DashboardSnapshot>(EMPTY_SNAPSHOT);
  const [rows, setRows] = useState<FidsRow[]>([]);
  const [historyData, setHistoryData] = useState<HistoryResponse | null>(null);
  const [radarData, setRadarData] = useState<RadarResponse | null>(null);
  const [detailVisible, setDetailVisible] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailCallsign, setDetailCallsign] = useState("");
  const [detailData, setDetailData] = useState<FidsDetailResponse | null>(null);
  const [feedbackTitle, setFeedbackTitle] = useState("");
  const [feedbackDescription, setFeedbackDescription] = useState("");
  const [feedbackSending, setFeedbackSending] = useState(false);
  const [feedbackMessage, setFeedbackMessage] = useState<string | null>(null);
  const [feedbackTone, setFeedbackTone] = useState<FeedbackTone>("ok");
  const [autoReportMessage, setAutoReportMessage] = useState<string | null>(null);
  const [matrixView, setMatrixView] = useState<FlightView>("departures");
  const [matrixPreset, setMatrixPreset] = useState<MatrixPreset>(MATRIX_PRESETS[4]!);
  const [matrixRows, setMatrixRows] = useState(4);
  const [matrixBrightness, setMatrixBrightness] = useState(80);
  const [matrixData, setMatrixData] = useState<FidsRow[]>([]);
  const [launchVisible, setLaunchVisible] = useState(true);
  const [launchStatusIndex, setLaunchStatusIndex] = useState(0);
  const [pinnedCallsign, setPinnedCallsign] = useState("");
  const [actionRow, setActionRow] = useState<FidsRow | null>(null);
  const [configSheetVisible, setConfigSheetVisible] = useState(false);
  const [profiles, setProfiles] = useState<ConfigProfile[]>([]);
  const [companionIdentity, setCompanionIdentity] = useState<CompanionIdentity | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const detailRequestRef = useRef(0);
  const launchOpacity = useRef(new Animated.Value(1)).current;
  const launchScale = useRef(new Animated.Value(1)).current;
  const launchShift = useRef(new Animated.Value(0)).current;
  const launchProgress = useRef(new Animated.Value(0)).current;
  const launchPulse = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    installGlobalCrashReporter();
  }, []);

  useEffect(() => {
    const timer = setInterval(() => {
      setUtcTime(formatUtc());
      setLocalTime(formatLocalTime());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    let alive = true;
    const startedAt = Date.now();
    let nativeHideTimer: ReturnType<typeof setTimeout> | null = null;
    let hideTimer: ReturnType<typeof setTimeout> | null = null;
    let fadeTimer: ReturnType<typeof setTimeout> | null = null;
    const statusTimer = setInterval(() => {
      const elapsed = Date.now() - startedAt;
      const progress = Math.min(1, elapsed / LAUNCH_MIN_MS);
      setLaunchStatusIndex(Math.min(LAUNCH_STATUS_STEPS.length - 1, Math.floor(progress * LAUNCH_STATUS_STEPS.length)));
    }, 420);
    const pulseAnim = Animated.loop(
      Animated.sequence([
        Animated.timing(launchPulse, {
          toValue: 1,
          duration: 1600,
          easing: Easing.inOut(Easing.quad),
          useNativeDriver: true
        }),
        Animated.timing(launchPulse, {
          toValue: 0,
          duration: 1600,
          easing: Easing.inOut(Easing.quad),
          useNativeDriver: true
        })
      ])
    );

    launchProgress.setValue(0);
    launchPulse.setValue(0);
    Animated.timing(launchProgress, {
      toValue: 1,
      duration: LAUNCH_MIN_MS,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: false
    }).start();
    pulseAnim.start();

    Promise.all([loadServerUrl(), loadPinnedFlight(), loadProfiles(), getCompanionIdentity()])
      .then(([savedUrl, savedPin, savedProfiles, identity]) => {
        if (!alive) return;
        if (savedUrl) {
          setServerUrl(savedUrl);
          setDraftUrl(savedUrl);
        }
        if (savedPin) {
          setPinnedCallsign(savedPin);
        }
        if (savedProfiles.length) {
          setProfiles(savedProfiles);
        }
        setCompanionIdentity(identity);
      })
      .finally(() => {
        if (!alive) return;
        const nativeRemaining = Math.max(0, LAUNCH_NATIVE_MIN_MS - (Date.now() - startedAt));
        nativeHideTimer = setTimeout(() => {
          if (!alive) return;
          void SplashScreen.hideAsync().catch(() => {
            // Ignore splash hide races during simulator reloads.
          });
        }, nativeRemaining);

        const remaining = Math.max(0, LAUNCH_MIN_MS - (Date.now() - startedAt));
        hideTimer = setTimeout(() => {
          if (!alive) return;
          setLaunchStatusIndex(LAUNCH_STATUS_STEPS.length - 1);
          fadeTimer = setTimeout(() => {
            if (!alive) return;
            Animated.parallel([
              Animated.timing(launchOpacity, {
                toValue: 0,
                duration: 420,
                useNativeDriver: true
              }),
              Animated.timing(launchShift, {
                toValue: -12,
                duration: 420,
                useNativeDriver: true
              }),
              Animated.timing(launchScale, {
                toValue: 0.965,
                duration: 420,
                useNativeDriver: true
              })
            ]).start(({ finished }) => {
              if (finished && alive) {
                setLaunchVisible(false);
              }
            });
          }, LAUNCH_ANIMATION_DELAY_MS);
        }, remaining);
      });

    return () => {
      alive = false;
      clearInterval(statusTimer);
      pulseAnim.stop();
      launchProgress.stopAnimation();
      if (nativeHideTimer) clearTimeout(nativeHideTimer);
      if (hideTimer) clearTimeout(hideTimer);
      if (fadeTimer) clearTimeout(fadeTimer);
    };
  }, [launchOpacity, launchProgress, launchPulse, launchScale, launchShift]);

  const fetchDashboard = useCallback(async (normalized: string) => {
    const [state, config, system, connections, updates, budget] = await Promise.all([
      getHealth(normalized),
      getConfig(normalized),
      getAdminSystem(normalized),
      getConnections(normalized),
      getUpdates(normalized),
      getBudget(normalized)
    ]);

    let metar = null;
    try {
      metar = await getMetar(normalized);
    } catch {
      metar = null;
    }

    setSnapshot({ state, config, system, connections, updates, budget, metar });
    setConnected(true);
  }, []);

  const fetchFidsData = useCallback(async (normalized: string, nextView: FlightView) => {
    const fids = await getFids(normalized, nextView);
    setRows(fids);
  }, []);

  const fetchHistoryData = useCallback(
    async (
      normalized: string,
      nextDirection: HistoryDirection,
      nextHours: HistoryWindow
    ) => {
      const data = await getHistory(normalized, {
        direction: nextDirection,
        hours: nextHours,
        limit: 120
      });
      setHistoryData(data);
    },
    []
  );

  const fetchRadarData = useCallback(async (normalized: string, nextRadius: RadarRadius) => {
    const data = await getRadar(normalized, nextRadius);
    setRadarData(data);
  }, []);

  const fetchMatrixData = useCallback(
    async (normalized: string, nextView: FlightView, nextRows: number) => {
      const fids = await getFids(normalized, nextView, nextRows);
      setMatrixData(fids);
    },
    []
  );

  const loadFlightDetail = useCallback(
    async (callsign: string) => {
      const normalized = normalizeServerUrl(serverUrl);
      if (!normalized || !callsign) return;

      const requestId = detailRequestRef.current + 1;
      detailRequestRef.current = requestId;
      setDetailLoading(true);

      try {
        const data = await getFidsDetail(normalized, callsign);
        if (detailRequestRef.current === requestId) {
          setDetailData(data);
        }
      } catch (exc) {
        if (detailRequestRef.current === requestId) {
          setDetailData(null);
          setError(errorMessage(exc));
        }
      } finally {
        if (detailRequestRef.current === requestId) {
          setDetailLoading(false);
        }
      }
    },
    [serverUrl]
  );

  const openFlightDetail = useCallback(
    (callsign: string) => {
      if (!callsign) return;
      setDetailCallsign(callsign);
      setDetailData(null);
      setDetailVisible(true);
      void loadFlightDetail(callsign);
    },
    [loadFlightDetail]
  );

  const refreshScreen = useCallback(
    async ({
      nextUrl = serverUrl,
      target = screen,
      nextView = view,
      nextHistoryDirection = historyDirection,
      nextHistoryHours = historyHours,
      nextRadarRadius = radarRadius
    }: RefreshOptions = {}) => {
      const normalized = normalizeServerUrl(nextUrl);
      if (!normalized) {
        setError("Enter the Local Flight server URL in Settings.");
        return;
      }

      setRefreshing(true);
      setError(null);

      try {
        await fetchDashboard(normalized);
      } catch (exc) {
        setConnected(false);
        setError(errorMessage(exc));
        setRefreshing(false);
        return;
      }

      try {
        if (target === "fids") {
          await fetchFidsData(normalized, nextView);
        } else if (target === "history") {
          await fetchHistoryData(normalized, nextHistoryDirection, nextHistoryHours);
        } else if (target === "radar") {
          await fetchRadarData(normalized, nextRadarRadius);
        } else if (target === "matrix") {
          await fetchMatrixData(normalized, matrixView, matrixRows);
        }
      } catch (exc) {
        setError(errorMessage(exc));
      } finally {
        setRefreshing(false);
      }
    },
    [
      fetchDashboard,
      fetchFidsData,
      fetchHistoryData,
      fetchMatrixData,
      fetchRadarData,
      historyDirection,
      historyHours,
      matrixRows,
      matrixView,
      radarRadius,
      screen,
      serverUrl,
      view
    ]
  );

  const connect = useCallback(async () => {
    const normalized = normalizeServerUrl(draftUrl);
    setLoading(true);
    setError(null);

    try {
      await testConnection(normalized);
      await saveServerUrl(normalized);
      setServerUrl(normalized);
      setDraftUrl(normalized);
      setScreen("fids");
    } catch (exc) {
      setConnected(false);
      setError(errorMessage(exc));
    } finally {
      setLoading(false);
    }
  }, [draftUrl]);

  const restartSchedulerNow = useCallback(async () => {
    const normalized = normalizeServerUrl(serverUrl);
    if (!normalized) {
      setSchedulerMessage("Set the Local Flight server URL first.");
      return;
    }

    setSchedulerRestarting(true);
    setSchedulerMessage("Restarting scheduler...");
    setError(null);

    try {
      const result = await restartScheduler(normalized);
      setSchedulerMessage(result.message || (result.ok ? "Scheduler restarted." : "Scheduler is still stopping."));
      if (result.ok) {
        await refreshScreen({ target: screen });
      }
    } catch (exc) {
      setSchedulerMessage(errorMessage(exc));
    } finally {
      setSchedulerRestarting(false);
    }
  }, [refreshScreen, screen, serverUrl]);

  const sendFeedbackReport = useCallback(async () => {
    const normalized = normalizeServerUrl(serverUrl);
    if (!normalized) {
      setFeedbackTone("error");
      setFeedbackMessage("Set the Local Flight server URL first.");
      return;
    }
    if (!feedbackTitle.trim()) {
      setFeedbackTone("error");
      setFeedbackMessage("Add a short title before sending feedback.");
      return;
    }

    setFeedbackSending(true);
    setFeedbackMessage(null);

    try {
      await submitFeedback(normalized, {
        title: feedbackTitle.trim(),
        description: feedbackDescription.trim(),
        client_context: mobileClientContext(normalized, snapshot, companionIdentity)
      });
      setFeedbackTone("ok");
      setFeedbackMessage("Feedback sent to the Local Flight Reports board.");
      setFeedbackTitle("");
      setFeedbackDescription("");
    } catch (exc) {
      setFeedbackTone("error");
      setFeedbackMessage(errorMessage(exc));
    } finally {
      setFeedbackSending(false);
    }
  }, [companionIdentity, feedbackDescription, feedbackTitle, serverUrl, snapshot]);

  const sendAutoReportTest = useCallback(async () => {
    setAutoReportMessage("Sending auto-report test...");
    await reportMobileCrash({
      message: "Intentional mobile auto-report test",
      traceback: "Triggered from the Admin screen to verify Linear crash wiring.",
      context: "mobile/manual-auto-test",
      client_context: mobileClientContext(serverUrl, snapshot, companionIdentity)
    });
    setAutoReportMessage("Auto-report test sent with the crash route.");
  }, [companionIdentity, serverUrl, snapshot]);

  const togglePinnedFlight = useCallback(
    async (row: FidsRow) => {
      const key = flightPinKey(row);
      const next = pinnedCallsign === key ? "" : key;
      setPinnedCallsign(next);
      setActionRow(null);
      await savePinnedFlight(next);
    },
    [pinnedCallsign]
  );

  useEffect(() => {
    if (!serverUrl) return;
    void refreshScreen({ target: screen });
  }, [historyDirection, historyHours, matrixRows, matrixView, radarRadius, refreshScreen, screen, serverUrl, view]);

  useEffect(() => {
    if (!serverUrl || !connected) return;
    const socket = new WebSocket(wsUrl(serverUrl));
    socketRef.current = socket;

    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(String(event.data)) as {
          type?: string;
          config?: AppConfig;
          message?: string;
          ok?: boolean;
        };
        if (message.type === "snapshot_updated") {
          void refreshScreen({ target: screen });
          if (detailVisible && detailCallsign) {
            void loadFlightDetail(detailCallsign);
          }
        } else if (message.type === "config_updated") {
          if (message.config) {
            setSnapshot((prev) => ({ ...prev, config: message.config || prev.config }));
          }
          void refreshScreen({ target: screen });
        } else if (message.type === "scheduler_restarted") {
          setSchedulerMessage(message.message || (message.ok ? "Scheduler restarted." : "Scheduler is still stopping."));
          void refreshScreen({ target: screen });
        }
      } catch {
        // Ignore non-JSON messages.
      }
    };

    socket.onerror = () => socket.close();

    return () => {
      socket.close();
      if (socketRef.current === socket) {
        socketRef.current = null;
      }
    };
  }, [connected, detailCallsign, detailVisible, loadFlightDetail, refreshScreen, screen, serverUrl]);

  const cfg = snapshot.config;
  const state = snapshot.state;
  const airportCode = cfg?.airport_iata || "---";
  const airportName = cfg?.airport_icao ? `${cfg.airport_icao} Local Flight` : "Connect your server";
  const sourceLabel = state?.source_name || cfg?.source || "VATSIM";
  const isLive = connected && state?.ok !== false;
  const syncIntervalMs = companionSyncMs(cfg?.refresh_seconds);

  useEffect(() => {
    if (!serverUrl || !connected) return;
    const timer = setInterval(() => {
      void refreshScreen({ target: screen });
    }, syncIntervalMs);
    return () => clearInterval(timer);
  }, [connected, refreshScreen, screen, serverUrl, syncIntervalMs]);

  useEffect(() => {
    if (!serverUrl || !connected || !companionIdentity) return;
    const normalized = normalizeServerUrl(serverUrl);
    if (!normalized) return;

    let alive = true;
    const sendCheckin = async () => {
      try {
        await sendCompanionCheckin(normalized, {
          companion_id: companionIdentity.companionId,
          client_name: companionIdentity.clientName,
          app_version: companionIdentity.appVersion,
          mobile_os: companionIdentity.mobileOs,
          device_type: companionIdentity.deviceType
        });
        const connections = await getConnections(normalized);
        if (alive) {
          setSnapshot((prev) => ({ ...prev, connections }));
        }
      } catch {
        // Presence check-in is best-effort and should not disturb the main UI.
      }
    };

    void sendCheckin();
    const timer = setInterval(() => {
      void sendCheckin();
    }, COMPANION_PING_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [companionIdentity, connected, serverUrl]);

  const contentWidth = Math.min(layout.contentMaxWidth, layout.width - 24);
  const detail = detailOrNull(detailData);
  const pinnedRow = pinnedCallsign
    ? rows.find((row) => flightPinKey(row) === pinnedCallsign) || null
    : null;
  const islandRow =
    pinnedRow || rows.find((row) => /board|gate|approach/i.test(row.status_display)) || rows[0] || null;
  const screenContentPadding = Math.max(20, insets.bottom + 14);
  const matrixConfigText = matrixClientConfig({
    serverUrl,
    airportIata: cfg?.airport_iata,
    airportIcao: cfg?.airport_icao,
    preset: matrixPreset,
    rows: matrixRows,
    brightness: matrixBrightness,
    view: matrixView
  });

  return (
    <SafeAreaView style={styles.safe} edges={["top", "left", "right"]}>
      <StatusBar barStyle="light-content" />
      <View style={[styles.appFrame, { maxWidth: contentWidth }]}>
        <Header
          airportCode={airportCode}
          airportIcao={cfg?.airport_icao || ""}
          airportName={airportName}
          live={isLive}
          sourceLabel={sourceLabel}
          utcTime={utcTime}
          localTime={localTime}
          metarCategory={snapshot.metar?.flight_category || snapshot.metar?.category || "--"}
          metarText={snapshot.metar?.decoded_summary || snapshot.metar?.raw_text || "METAR unavailable"}
          rowCount={rows.length}
          view={view}
          pinnedRow={islandRow}
          onOpenDetail={openFlightDetail}
          onOpenActions={setActionRow}
          onOpenConfig={() => setConfigSheetVisible(true)}
        />

        <View style={styles.mainArea}>
          {screen === "fids" ? (
            <FidsScreen
              rows={rows}
              view={view}
              loading={refreshing}
              refreshing={refreshing}
              error={error}
              showConnectPrompt={!serverUrl}
              onOpenSettings={() => setScreen("settings")}
              onRefresh={() => refreshScreen({ target: "fids" })}
              onViewChange={setView}
              onOpenDetail={openFlightDetail}
              onOpenActions={setActionRow}
              pinnedCallsign={pinnedCallsign}
              contentPaddingBottom={screenContentPadding}
            />
          ) : null}

          {screen === "history" ? (
            <HistoryScreen
              data={historyData}
              direction={historyDirection}
              hours={historyHours}
              loading={refreshing}
              refreshing={refreshing}
              error={error}
              showConnectPrompt={!serverUrl}
              onOpenSettings={() => setScreen("settings")}
              onRefresh={() => refreshScreen({ target: "history" })}
              onDirectionChange={setHistoryDirection}
              onHoursChange={setHistoryHours}
              onOpenDetail={openFlightDetail}
              contentPaddingBottom={screenContentPadding}
            />
          ) : null}

          {screen === "radar" ? (
            <RadarScreen
              data={radarData}
              radiusNm={radarRadius}
              loading={refreshing}
              refreshing={refreshing}
              error={error}
              showConnectPrompt={!serverUrl}
              onOpenSettings={() => setScreen("settings")}
              onRefresh={() => refreshScreen({ target: "radar" })}
              onRadiusChange={setRadarRadius}
              onOpenDetail={openFlightDetail}
              contentPaddingBottom={screenContentPadding}
            />
          ) : null}

          {screen === "matrix" ? (
            <MatrixScreen
              rows={matrixData}
              view={matrixView}
              preset={matrixPreset}
              brightness={matrixBrightness}
              maxRows={matrixRows}
              configText={matrixConfigText}
              matrixEnabled={snapshot.config?.display_outputs?.includes("matrix") || false}
              matrixLastSeen={snapshot.connections?.matrix_last_seen || null}
              refreshing={refreshing}
              error={error}
              showConnectPrompt={!serverUrl}
              onOpenSettings={() => setScreen("settings")}
              onRefresh={() => refreshScreen({ target: "matrix" })}
              onViewChange={setMatrixView}
              onPresetChange={setMatrixPreset}
              onBrightnessChange={setMatrixBrightness}
              onRowsChange={setMatrixRows}
              onBackSettings={() => setScreen("settings")}
              contentPaddingBottom={screenContentPadding}
            />
          ) : null}

          {screen === "admin" || screen === "settings" ? (
            <ScrollView
              style={styles.screenScroll}
              contentContainerStyle={[styles.screenContent, { paddingBottom: screenContentPadding }]}
              refreshControl={
                <RefreshControl
                  refreshing={refreshing}
                  tintColor={palette.blue}
                  onRefresh={() => refreshScreen({ target: screen })}
                />
              }
            >
              {!serverUrl ? (
                <ConnectPrompt onSettings={() => setScreen("settings")} />
              ) : null}

              {error ? <ScreenError message={error} /> : null}

              {screen === "admin" ? (
                <AdminScreen
                  snapshot={snapshot}
                  companionIdentity={companionIdentity}
                  connected={isLive}
                  error={error}
                  rows={rows}
                  view={view}
                  feedbackTitle={feedbackTitle}
                  feedbackDescription={feedbackDescription}
                  feedbackSending={feedbackSending}
                  feedbackMessage={feedbackMessage}
                  feedbackTone={feedbackTone}
                  autoReportMessage={autoReportMessage}
                  onFeedbackTitleChange={setFeedbackTitle}
                  onFeedbackDescriptionChange={setFeedbackDescription}
                  onSubmitFeedback={sendFeedbackReport}
                  onSendAutoReportTest={sendAutoReportTest}
                  onBackSettings={() => setScreen("settings")}
                />
              ) : null}

              {screen === "settings" ? (
                <SettingsScreen
                  serverUrl={serverUrl}
                  draftUrl={draftUrl}
                  error={error}
                  loading={loading}
                  isTablet={layout.isTablet}
                  isLandscape={layout.isLandscape}
                  outputs={snapshot.config?.display_outputs || []}
                  refreshSeconds={snapshot.config?.refresh_seconds ?? null}
                  schedulerRestarting={schedulerRestarting}
                  schedulerMessage={schedulerMessage}
                  onOpenAdmin={() => setScreen("admin")}
                  onOpenMatrix={() => setScreen("matrix")}
                  onOpenCoffee={() => void Linking.openURL("https://buymeacoffee.com/localflight")}
                  onRestartScheduler={restartSchedulerNow}
                  onChangeUrl={setDraftUrl}
                  onConnect={connect}
                />
              ) : null}
            </ScrollView>
          ) : null}
        </View>

        <BottomNav active={screen} onChange={setScreen} insetBottom={insets.bottom} />
      </View>

      <FlightDetailSheet
        visible={detailVisible}
        callsign={detailCallsign}
        detail={detail}
        history={detailData?.history || []}
        loading={detailLoading}
        onClose={() => setDetailVisible(false)}
        onRefresh={() => loadFlightDetail(detailCallsign)}
      />

      <FlightActionSheet
        row={actionRow}
        visible={Boolean(actionRow)}
        isPinned={Boolean(actionRow && flightPinKey(actionRow) === pinnedCallsign)}
        onClose={() => setActionRow(null)}
        onOpenDetail={(callsign) => {
          setActionRow(null);
          openFlightDetail(callsign);
        }}
        onTogglePin={togglePinnedFlight}
      />

      <AirportConfigSheet
        visible={configSheetVisible}
        serverUrl={serverUrl}
        currentConfig={snapshot.config}
        profiles={profiles}
        onClose={() => setConfigSheetVisible(false)}
        onApplied={(newConfig) => {
          setSnapshot((prev) => ({ ...prev, config: newConfig }));
          setConfigSheetVisible(false);
          void refreshScreen({ target: screen });
        }}
        onProfilesChange={setProfiles}
      />

      <LaunchOverlay
        visible={launchVisible}
        opacity={launchOpacity}
        shift={launchShift}
        scale={launchScale}
        progress={launchProgress}
        pulse={launchPulse}
        status={LAUNCH_STATUS_STEPS[launchStatusIndex] || LAUNCH_STATUS_STEPS[0]}
      />
    </SafeAreaView>
  );
}

function LaunchOverlay({
  visible,
  opacity,
  shift,
  scale,
  progress,
  pulse,
  status
}: {
  visible: boolean;
  opacity: Animated.Value;
  shift: Animated.Value;
  scale: Animated.Value;
  progress: Animated.Value;
  pulse: Animated.Value;
  status: string;
}) {
  if (!visible) return null;

  const haloScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.94, 1.08] });
  const haloOpacity = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.72, 0.34] });
  const progressWidth = progress.interpolate({ inputRange: [0, 1], outputRange: ["4%", "100%"] });
  const sweepRotate = pulse.interpolate({ inputRange: [0, 1], outputRange: ["-18deg", "18deg"] });

  return (
    <Animated.View
      style={[
        { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 },
        styles.launchOverlay,
        {
          opacity,
          transform: [{ translateY: shift }, { scale }]
        }
      ]}
    >
      <Animated.View style={[styles.launchHalo, { opacity: haloOpacity, transform: [{ scale: haloScale }] }]} />
      <Animated.View style={[styles.launchHaloInner, { transform: [{ rotate: sweepRotate }] }]} />
      <View style={styles.launchPanel}>
        <View style={styles.launchMarkWrap}>
          <View style={styles.launchRadarRing} />
          <Animated.View style={[styles.launchSweep, { transform: [{ rotate: sweepRotate }] }]} />
          <Image
            source={require("./assets/icon_circle.png")}
            resizeMode="contain"
            style={styles.launchMark}
          />
        </View>
        <Text style={styles.launchEyebrow}>LOCAL FLIGHT</Text>
        <Text style={styles.launchTitle}>COMPANION</Text>
        <Text style={styles.launchVersion}>v{APP_VERSION}</Text>
        <View style={styles.launchStatusRow}>
          <Text style={styles.launchStatus}>{status}</Text>
        </View>
        <View style={styles.launchProgressTrack}>
          <Animated.View style={[styles.launchProgressFill, { width: progressWidth }]} />
        </View>
      </View>
    </Animated.View>
  );
}

function Header({
  airportCode,
  airportIcao,
  airportName,
  live,
  sourceLabel,
  utcTime,
  localTime,
  metarCategory,
  metarText,
  rowCount,
  view,
  pinnedRow,
  onOpenDetail,
  onOpenActions,
  onOpenConfig,
}: {
  airportCode: string;
  airportIcao: string;
  airportName: string;
  live: boolean;
  sourceLabel: string;
  utcTime: string;
  localTime: string;
  metarCategory: string;
  metarText: string;
  rowCount: number;
  view: FlightView;
  pinnedRow: FidsRow | null;
  onOpenDetail: (callsign: string) => void;
  onOpenActions: (row: FidsRow) => void;
  onOpenConfig: () => void;
}) {
  const accent = metarAccentColor(metarCategory);
  const dotOpacity = useRef(new Animated.Value(1)).current;
  const chips = parseMetarChips(metarText);

  useEffect(() => {
    if (!live) { dotOpacity.setValue(1); return; }
    const anim = Animated.loop(
      Animated.sequence([
        Animated.timing(dotOpacity, { toValue: 0.2, duration: 850, useNativeDriver: true }),
        Animated.timing(dotOpacity, { toValue: 1, duration: 850, useNativeDriver: true })
      ])
    );
    anim.start();
    return () => anim.stop();
  }, [dotOpacity, live]);

  return (
    <View style={styles.header}>
      {/* Left accent bar — color-coded to METAR category */}
      <View style={[styles.headerAccentBar, { backgroundColor: accent }]} />

      {/* Identity band — tap to configure */}
      <Pressable style={styles.identityBand} onPress={onOpenConfig}>
        <View style={styles.identityLeft}>
          <Text style={[styles.airportCode, {
            color: accent,
            textShadowColor: accent,
            textShadowOffset: { width: 0, height: 0 },
            textShadowRadius: 10
          }]}>
            {airportCode}
          </Text>
          <Text style={styles.airportName} numberOfLines={1}>
            {airportName}
            {airportIcao ? <Text style={styles.airportIcao}> · {airportIcao}</Text> : null}
          </Text>
          <View style={styles.configHint}>
            <MaterialCommunityIcons name="tune-variant" size={10} color={palette.textDim} />
            <Text style={styles.configHintText}>tap to configure</Text>
          </View>
        </View>
        <View style={styles.identityRight}>
          <Text style={styles.utcTime}>{utcTime}<Text style={styles.utcSuffix}>Z</Text></Text>
          <Text style={styles.localTime}>{localTime} <Text style={styles.localSuffix}>LOC</Text></Text>
          <View style={[styles.metarCatBadge, { borderColor: `${accent}55`, backgroundColor: `${accent}22` }]}>
            <Text style={[styles.metarCatBadgeText, { color: accent }]}>{metarCategory || "--"}</Text>
          </View>
        </View>
      </Pressable>

      {/* Telemetry strip */}
      <View style={styles.telemetryStrip}>
        <View style={[styles.livePill, !live && styles.livePillOff]}>
          <Animated.View style={[styles.liveDot, !live && styles.liveDotOff, { opacity: dotOpacity }]} />
          <Text style={[styles.liveText, !live && styles.liveTextOff]}>{live ? "LIVE" : "OFF"}</Text>
        </View>
        <View style={styles.sourcePill}>
          <Text style={styles.sourceText}>{sourceLabel.toUpperCase()}</Text>
        </View>
        <View style={styles.countPill}>
          <Text style={styles.countText}>
            {view === "departures" ? "↑" : "↓"}{rowCount}
          </Text>
        </View>
      </View>

      {/* Flight Island */}
      <FlightIsland
        row={pinnedRow}
        live={live}
        utcTime={utcTime}
        onOpenDetail={onOpenDetail}
        onOpenActions={onOpenActions}
      />

      {/* METAR strip — decoded chips when parseable, raw text fallback */}
      <View style={styles.metarStrip}>
        {chips.length > 0 ? (
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.metarChipRow}
          >
            {chips.map((chip, i) => (
              <View key={i} style={styles.metarChip}>
                <Text style={styles.metarChipLabel}>{chip.label}</Text>
                <Text style={styles.metarChipValue}>{chip.value}</Text>
              </View>
            ))}
          </ScrollView>
        ) : (
          <Text style={styles.metarText} numberOfLines={1}>{metarText}</Text>
        )}
      </View>
    </View>
  );
}

function FlightIsland({
  row,
  live,
  utcTime,
  onOpenDetail,
  onOpenActions
}: {
  row: FidsRow | null;
  live: boolean;
  utcTime: string;
  onOpenDetail: (callsign: string) => void;
  onOpenActions: (row: FidsRow) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const expandAnim = useRef(new Animated.Value(0)).current;
  const hintAnim = useRef(new Animated.Value(0)).current;

  const toggle = useCallback(
    (next: boolean) => {
      setExpanded(next);
      Animated.spring(expandAnim, {
        toValue: next ? 1 : 0,
        damping: 18,
        stiffness: 180,
        mass: 0.8,
        useNativeDriver: false
      }).start();
    },
    [expandAnim]
  );

  useEffect(() => {
    const anim = Animated.loop(
      Animated.sequence([
        Animated.timing(hintAnim, { toValue: 1, duration: 800, useNativeDriver: true }),
        Animated.timing(hintAnim, { toValue: 0, duration: 800, useNativeDriver: true })
      ])
    );
    anim.start();
    return () => anim.stop();
  }, [hintAnim]);

  useEffect(() => {
    if (!row && expanded) {
      toggle(false);
    }
  }, [expanded, row, toggle]);

  const panResponder = useRef(
    PanResponder.create({
      onMoveShouldSetPanResponder: (_, gesture) =>
        Math.abs(gesture.dy) > 8 && Math.abs(gesture.dy) > Math.abs(gesture.dx),
      onPanResponderRelease: (_, gesture) => {
        if (gesture.dy > 22) {
          toggle(true);
          return;
        }
        if (gesture.dy < -22) {
          toggle(false);
        }
      }
    })
  ).current;

  const hintOffset = hintAnim.interpolate({
    inputRange: [0, 1],
    outputRange: [0, expanded ? -3 : 3]
  });

  return (
    <Animated.View
      {...panResponder.panHandlers}
      style={[
        styles.islandShell,
        {
          width: expandAnim.interpolate({ inputRange: [0, 1], outputRange: [164, 324] }),
          minHeight: expandAnim.interpolate({ inputRange: [0, 1], outputRange: [42, 102] })
        }
      ]}
    >
      <Pressable
        style={styles.islandPressable}
        delayLongPress={360}
        onLongPress={() => {
          if (row) onOpenActions(row);
        }}
        onPress={() => {
          if (expanded && row?.callsign) {
            onOpenDetail(row.callsign);
            return;
          }
          toggle(!expanded);
        }}
      >
        <View style={styles.islandCompactRow}>
          <View style={styles.islandLead}>
            <MaterialCommunityIcons
              name={row?.view === "arrivals" ? "airplane-landing" : "airplane-takeoff"}
              size={15}
              color={live ? palette.blue2 : palette.textDim}
            />
            <View style={styles.islandTextWrap}>
              <Text style={styles.islandFlight} numberOfLines={1}>
                {row?.flight_display || (live ? "LOCAL FLIGHT" : "OFFLINE")}
              </Text>
              <Text style={styles.islandMeta} numberOfLines={1}>
                {row ? `${routeName(row.route_display)} · ${row.display_time}` : `UTC ${utcTime}`}
              </Text>
            </View>
          </View>

          <View style={styles.islandTrail}>
            <Text style={[styles.islandStatus, { color: live ? palette.green : palette.red }]}>
              {row ? statusShort(row.status_display) : live ? "READY" : "OFF"}
            </Text>
            <Animated.View style={{ transform: [{ translateY: hintOffset }] }}>
              <MaterialCommunityIcons
                name={expanded ? "chevron-up" : "chevron-down"}
                size={16}
                color={palette.textMuted}
              />
            </Animated.View>
          </View>
        </View>

        <Animated.View
          style={[
            styles.islandExpanded,
            {
              height: expandAnim.interpolate({ inputRange: [0, 1], outputRange: [0, 52] }),
              opacity: expandAnim
            }
          ]}
        >
          <Text style={styles.islandExpandedLine} numberOfLines={1}>
            {row ? `${routeMeta(row)} · ${row.aircraft_type || "A/C PENDING"}` : "Swipe down to surface the pinned flight."}
          </Text>
          <Text style={styles.islandExpandedHint} numberOfLines={1}>
            {row ? "Tap open for full detail. Swipe up to tuck away." : "Live status stays up here while the rest of the board scrolls."}
          </Text>
        </Animated.View>
      </Pressable>
    </Animated.View>
  );
}

function FidsScreen({
  rows,
  view,
  loading,
  refreshing,
  error,
  showConnectPrompt,
  onOpenSettings,
  onRefresh,
  onViewChange,
  onOpenDetail,
  onOpenActions,
  pinnedCallsign,
  contentPaddingBottom
}: {
  rows: FidsRow[];
  view: FlightView;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  showConnectPrompt: boolean;
  onOpenSettings: () => void;
  onRefresh: () => void;
  onViewChange: (view: FlightView) => void;
  onOpenDetail: (callsign: string) => void;
  onOpenActions: (row: FidsRow) => void;
  pinnedCallsign: string;
  contentPaddingBottom: number;
}) {
  const pinned = pinnedCallsign
    ? rows.find((row) => flightPinKey(row) === pinnedCallsign) || null
    : null;
  const displayRows = pinned
    ? [pinned, ...rows.filter((row) => flightPinKey(row) !== pinnedCallsign)]
    : rows;

  return (
    <FlatList<FidsRow>
      data={displayRows}
      keyExtractor={(row) => row.id}
      renderItem={({ item }) => (
        <View style={styles.fidsListItem}>
          <FidsRowView
            row={item}
            isPinned={flightPinKey(item) === pinnedCallsign}
            onOpenDetail={onOpenDetail}
            onOpenActions={onOpenActions}
          />
        </View>
      )}
      style={styles.screenScroll}
      contentContainerStyle={[styles.screenContent, { paddingBottom: contentPaddingBottom }]}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          tintColor={palette.blue}
          onRefresh={onRefresh}
        />
      }
      ListHeaderComponent={
        <>
          {showConnectPrompt ? <ConnectPrompt onSettings={onOpenSettings} /> : null}
          {error ? <ScreenError message={error} /> : null}

          <View style={styles.dirToggle}>
            <DirectionButton
              active={view === "departures"}
              label="DEPARTURES"
              onPress={() => onViewChange("departures")}
            />
            <DirectionButton
              active={view === "arrivals"}
              label="ARRIVALS"
              onPress={() => onViewChange("arrivals")}
            />
          </View>

          <View style={styles.fidsHeader}>
            <Text style={styles.fidsHeaderText}>TIME</Text>
            <Text style={styles.fidsHeaderText}>FLIGHT</Text>
            <Text style={styles.fidsHeaderText}>{view === "arrivals" ? "FROM" : "TO"}</Text>
            <Text style={styles.fidsHeaderText}>STATUS</Text>
            <Text style={[styles.fidsHeaderText, styles.alignRight]}>A/C</Text>
          </View>
        </>
      }
      ListEmptyComponent={
        loading ? (
          <ActivityIndicator color={palette.blue} style={styles.loader} />
        ) : (
          <Text style={styles.empty}>No rows yet. Complete setup or run a snapshot fetch on the server.</Text>
        )
      }
      showsVerticalScrollIndicator={false}
    />
  );
}

function HistoryScreen({
  data,
  direction,
  hours,
  loading,
  refreshing,
  error,
  showConnectPrompt,
  onOpenSettings,
  onRefresh,
  onDirectionChange,
  onHoursChange,
  onOpenDetail,
  contentPaddingBottom
}: {
  data: HistoryResponse | null;
  direction: HistoryDirection;
  hours: HistoryWindow;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  showConnectPrompt: boolean;
  onOpenSettings: () => void;
  onRefresh: () => void;
  onDirectionChange: (value: HistoryDirection) => void;
  onHoursChange: (value: HistoryWindow) => void;
  onOpenDetail: (callsign: string) => void;
  contentPaddingBottom: number;
}) {
  const flights = data?.flights || [];

  return (
    <FlatList<HistoryFlightRow>
      data={flights}
      keyExtractor={(row) => String(row.id)}
      renderItem={({ item }) => (
        <HistoryRow row={item} onOpenDetail={onOpenDetail} />
      )}
      style={styles.screenScroll}
      contentContainerStyle={[styles.screenContent, { paddingBottom: contentPaddingBottom }]}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          tintColor={palette.blue}
          onRefresh={onRefresh}
        />
      }
      ListHeaderComponent={
        <>
          {showConnectPrompt ? <ConnectPrompt onSettings={onOpenSettings} /> : null}
          {error ? <ScreenError message={error} /> : null}

          <FilterSection title="DIRECTION">
            <View style={styles.filterRow}>
              <DirectionButton active={direction === "both"} label="ALL" onPress={() => onDirectionChange("both")} />
              <DirectionButton active={direction === "dep"} label="DEPARTURES" onPress={() => onDirectionChange("dep")} />
              <DirectionButton active={direction === "arr"} label="ARRIVALS" onPress={() => onDirectionChange("arr")} />
            </View>
          </FilterSection>

          <FilterSection title="WINDOW">
            <View style={styles.filterRow}>
              {HISTORY_WINDOWS.map((item) => (
                <DirectionButton
                  key={item}
                  active={hours === item}
                  label={item === 168 ? "7 DAYS" : `${item} HOURS`}
                  onPress={() => onHoursChange(item)}
                />
              ))}
            </View>
          </FilterSection>

          <View style={styles.metricRow}>
            <InfoCard label="ROWS" value={data ? String(data.count) : "..."} />
            <InfoCard label="FILTER" value={direction.toUpperCase()} tone="green" />
            <InfoCard label="WINDOW" value={hours === 168 ? "7 DAYS" : `${hours}H`} tone="amber" />
          </View>
        </>
      }
      ListEmptyComponent={
        loading ? (
          <ActivityIndicator color={palette.blue} style={styles.loader} />
        ) : (
          <Text style={styles.empty}>No recent history yet. Once snapshots have run, flights will appear here.</Text>
        )
      }
      ItemSeparatorComponent={() => <View style={styles.historyGap} />}
      showsVerticalScrollIndicator={false}
    />
  );
}

function RadarScreen({
  data,
  radiusNm,
  loading,
  refreshing,
  error,
  showConnectPrompt,
  onOpenSettings,
  onRefresh,
  onRadiusChange,
  onOpenDetail,
  contentPaddingBottom
}: {
  data: RadarResponse | null;
  radiusNm: RadarRadius;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  showConnectPrompt: boolean;
  onOpenSettings: () => void;
  onRefresh: () => void;
  onRadiusChange: (value: RadarRadius) => void;
  onOpenDetail: (callsign: string) => void;
  contentPaddingBottom: number;
}) {
  const blips = data?.blips || [];

  return (
    <FlatList<RadarBlip>
      data={blips}
      keyExtractor={(row, index) => `${row.callsign}-${index}`}
      renderItem={({ item }) => (
        <RadarBlipRow blip={item} onOpenDetail={onOpenDetail} />
      )}
      style={styles.screenScroll}
      contentContainerStyle={[styles.screenContent, { paddingBottom: contentPaddingBottom }]}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          tintColor={palette.blue}
          onRefresh={onRefresh}
        />
      }
      ListHeaderComponent={
        <>
          {showConnectPrompt ? <ConnectPrompt onSettings={onOpenSettings} /> : null}
          {error ? <ScreenError message={error} /> : null}

          <FilterSection title="RADIUS">
            <View style={styles.filterRow}>
              {RADAR_RADII.map((item) => (
                <DirectionButton
                  key={item}
                  active={radiusNm === item}
                  label={`${item} NM`}
                  onPress={() => onRadiusChange(item)}
                />
              ))}
            </View>
          </FilterSection>

          <View style={styles.metricRow}>
            <InfoCard label="BLIPS" value={data ? String(data.count) : "..."} />
            <InfoCard label="SOURCE" value={data?.source?.toUpperCase() || "WAIT"} tone="green" />
            <InfoCard label="RANGE" value={`${radiusNm} NM`} tone="amber" />
          </View>

          <RadarScope data={data} onOpenDetail={onOpenDetail} />
        </>
      }
      ListEmptyComponent={
        loading ? (
          <ActivityIndicator color={palette.blue} style={styles.loader} />
        ) : (
          <Text style={styles.empty}>No radar tracks available for the current range.</Text>
        )
      }
      ItemSeparatorComponent={() => <View style={styles.historyGap} />}
      showsVerticalScrollIndicator={false}
    />
  );
}

function MatrixScreen({
  rows,
  view,
  preset,
  brightness,
  maxRows,
  configText,
  matrixEnabled,
  matrixLastSeen,
  refreshing,
  error,
  showConnectPrompt,
  onOpenSettings,
  onRefresh,
  onViewChange,
  onPresetChange,
  onBrightnessChange,
  onRowsChange,
  onBackSettings,
  contentPaddingBottom
}: {
  rows: FidsRow[];
  view: FlightView;
  preset: MatrixPreset;
  brightness: number;
  maxRows: number;
  configText: string;
  matrixEnabled: boolean;
  matrixLastSeen: string | null;
  refreshing: boolean;
  error: string | null;
  showConnectPrompt: boolean;
  onOpenSettings: () => void;
  onRefresh: () => void;
  onViewChange: (value: FlightView) => void;
  onPresetChange: (value: MatrixPreset) => void;
  onBrightnessChange: (value: number) => void;
  onRowsChange: (value: number) => void;
  onBackSettings: () => void;
  contentPaddingBottom: number;
}) {
  const lines = matrixPreviewLines(rows);
  const brightnessAlpha = Math.max(0.28, Math.min(1, brightness / 100));

  return (
    <ScrollView
      style={styles.screenScroll}
      contentContainerStyle={[styles.screenContent, { paddingBottom: contentPaddingBottom }]}
      refreshControl={
        <RefreshControl refreshing={refreshing} tintColor={palette.blue} onRefresh={onRefresh} />
      }
      showsVerticalScrollIndicator={false}
    >
      {showConnectPrompt ? <ConnectPrompt onSettings={onOpenSettings} /> : null}
      {error ? <ScreenError message={error} /> : null}

      <View style={styles.cardStack}>
        <HiddenToolHeader
          icon="view-grid"
          title="Matrix"
          detail="Panel preview and client staging"
          onBack={onBackSettings}
        />

        <View style={styles.metricRow}>
          <InfoCard label="PANEL" value={`${preset.panelW}x${preset.panelH}`} />
          <InfoCard label="ROWS" value={String(maxRows)} tone="green" />
          <InfoCard label="BRIGHT" value={`${brightness}%`} tone="amber" />
        </View>

        <View style={styles.metricRow}>
          <InfoCard label="VIEW" value={view === "arrivals" ? "ARR" : "DEP"} />
          <InfoCard label="DEVICE" value={matrixEnabled ? "ENABLED" : "OFF"} tone={matrixEnabled ? "green" : "red"} />
          <InfoCard label="LAST PING" value={matrixLastSeen ? formatRelative(matrixLastSeen) : "NEVER"} tone="amber" />
        </View>

        <View style={styles.settingsCard}>
          <Text style={styles.settingsTitle}>MATRIX PREVIEW TOOL</Text>
          <Text style={styles.moduleIntro}>
            Tune the layout here before shipping it to the Interstate 75 W or a similar HUB75 panel client.
          </Text>

          <FilterSection title="VIEW">
            <View style={styles.filterRow}>
              <DirectionButton active={view === "departures"} label="DEPARTURES" onPress={() => onViewChange("departures")} />
              <DirectionButton active={view === "arrivals"} label="ARRIVALS" onPress={() => onViewChange("arrivals")} />
            </View>
          </FilterSection>

          <FilterSection title="PANEL PRESET">
            <View style={styles.filterWrap}>
              {MATRIX_PRESETS.map((item) => (
                <OptionChip
                  key={item.label}
                  active={preset.label === item.label}
                  label={item.label}
                  meta={item.modules}
                  onPress={() => onPresetChange(item)}
                />
              ))}
            </View>
          </FilterSection>

          <FilterSection title="ROWS">
            <View style={styles.filterWrap}>
              {MATRIX_ROWS.map((item) => (
                <OptionChip
                  key={item}
                  active={maxRows === item}
                  label={`${item}`}
                  meta="rows"
                  onPress={() => onRowsChange(item)}
                />
              ))}
            </View>
          </FilterSection>

          <FilterSection title="BRIGHTNESS">
            <View style={styles.filterWrap}>
              {MATRIX_BRIGHTNESS.map((item) => (
                <OptionChip
                  key={item}
                  active={brightness === item}
                  label={`${item}%`}
                  meta="output"
                  onPress={() => onBrightnessChange(item)}
                />
              ))}
            </View>
          </FilterSection>
        </View>

        <View style={styles.matrixToolShell}>
          <View style={styles.matrixToolBezel}>
            <View style={styles.matrixToolHeader}>
              <Text style={styles.matrixToolTitle}>INTERSTATE 75 W PREVIEW</Text>
              <Text style={styles.matrixToolMeta}>{preset.panelW}x{preset.panelH} · {preset.modules}</Text>
            </View>

            <View style={[styles.matrixPixelBoard, { opacity: brightnessAlpha }]}>
              <Text style={styles.matrixToolAirport}>
                {(rows[0]?.view || view) === "arrivals" ? "ARR" : "DEP"} · {preset.panelW}x{preset.panelH}
              </Text>
              {lines.map((line, index) => (
                <Text key={`${index}-${line}`} style={styles.matrixPixelLine}>
                  {line}
                </Text>
              ))}
            </View>
          </View>
        </View>

        <View style={styles.settingsCard}>
          <Text style={styles.settingsTitle}>MICROPYTHON CONFIG</Text>
          <Text style={styles.moduleIntro}>
            Paste this block into `client.py` later. It stays aligned with your selected panel preset and current server address.
          </Text>
          <View style={styles.feedbackContextBox}>
            <Text style={styles.feedbackContextText}>{configText}</Text>
          </View>
          <Text style={styles.settingsHelp}>
            The physical client still polls `/api/fids` and pings `/api/admin/ping`; this screen is the mobile staging tool for that output path.
          </Text>
        </View>
      </View>
    </ScrollView>
  );
}

function DirectionButton({ active, label, onPress }: { active: boolean; label: string; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={[styles.dirButton, active && styles.dirButtonActive]}>
      <Text style={[styles.dirButtonText, active && styles.dirButtonTextActive]}>{label}</Text>
    </Pressable>
  );
}

function FilterSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.filterSection}>
      <Text style={styles.filterLabel}>{title}</Text>
      {children}
    </View>
  );
}

function OptionChip({
  active,
  label,
  meta,
  onPress
}: {
  active: boolean;
  label: string;
  meta: string;
  onPress: () => void;
}) {
  return (
    <Pressable onPress={onPress} style={[styles.optionChip, active && styles.optionChipActive]}>
      <Text style={[styles.optionChipLabel, active && styles.optionChipLabelActive]}>{label}</Text>
      <Text style={[styles.optionChipMeta, active && styles.optionChipMetaActive]}>{meta}</Text>
    </Pressable>
  );
}

function FidsRowView({
  row,
  isPinned,
  onOpenDetail,
  onOpenActions
}: {
  row: FidsRow;
  isPinned: boolean;
  onOpenDetail: (callsign: string) => void;
  onOpenActions: (row: FidsRow) => void;
}) {
  return (
    <Pressable
      style={[styles.fidsRow, isPinned && styles.fidsRowPinned]}
      delayLongPress={360}
      onLongPress={() => onOpenActions(row)}
      onPress={() => onOpenDetail(row.callsign)}
    >
      <Text style={styles.fidsTime}>{row.display_time || "--:--"}</Text>
      <View style={styles.fidsFlightWrap}>
        <Text style={styles.fidsFlight} numberOfLines={1}>{row.flight_display || row.callsign || "-"}</Text>
        {isPinned ? <MaterialCommunityIcons name="pin" size={11} color={palette.amber} /> : null}
      </View>
      <View style={styles.fidsDest}>
        <Text style={styles.fidsDestName} numberOfLines={1}>{routeName(row.route_display)}</Text>
        <Text style={styles.fidsDestCode}>{routeMeta(row)}</Text>
      </View>
      <StatusBadge status={row.status_display} statusClass={row.status_class} compact />
      <Text style={styles.fidsAircraft} numberOfLines={1}>{row.aircraft_type || "-"}</Text>
    </Pressable>
  );
}

function HistoryRow({ row, onOpenDetail }: { row: HistoryFlightRow; onOpenDetail: (callsign: string) => void }) {
  return (
    <Pressable style={styles.historyRow} onPress={() => onOpenDetail(row.callsign)}>
      <View style={styles.historyTimeBox}>
        <Text style={styles.historyTime}>{formatClock(row.snapshot_ts)}</Text>
        <Text style={styles.historyDate}>{formatClock(row.sched_time)}</Text>
      </View>

      <View style={styles.historyMain}>
        <Text style={styles.historyFlight}>{row.flight_number || row.callsign || "-"}</Text>
        <Text style={styles.historyRoute} numberOfLines={1}>{historyRouteLabel(row)}</Text>
        <Text style={styles.historyMeta} numberOfLines={1}>
          {row.aircraft_type || "Aircraft pending"} {row.gate ? `- Gate ${row.gate}` : ""}
          {row.delay_minutes ? ` - ${row.delay_minutes}m delay` : ""}
        </Text>
      </View>

      <View style={styles.historyTrail}>
        <Text style={styles.historyDir}>{row.direction}</Text>
        <StatusBadge status={row.status} statusClass={row.status} compact />
      </View>
    </Pressable>
  );
}

function RadarBlipRow({ blip, onOpenDetail }: { blip: RadarBlip; onOpenDetail: (callsign: string) => void }) {
  return (
    <Pressable style={styles.historyRow} onPress={() => onOpenDetail(blip.callsign)}>
      <View style={styles.historyTimeBox}>
        <Text style={styles.historyTime}>{blip.callsign || "TRACK"}</Text>
        <Text style={styles.historyDate}>{blip.flight_number || "LIVE"}</Text>
      </View>

      <View style={styles.historyMain}>
        <Text style={styles.historyFlight}>{blip.status || "Tracked target"}</Text>
        <Text style={styles.historyRoute} numberOfLines={1}>
          {formatAltitudeFeet(blip.altitude_m)} - {formatSpeedKnots(blip.speed_ms)}
        </Text>
        <Text style={styles.historyMeta} numberOfLines={1}>
          {formatHeading(blip.heading)} {blip.on_ground ? "- on ground" : ""}
        </Text>
      </View>

      <View style={styles.historyTrail}>
        <Text style={styles.historyDir}>{blip.enriched ? "LIVE" : "RAW"}</Text>
        <View style={[styles.radarDotLarge, { backgroundColor: radarTone(blip) }]} />
      </View>
    </Pressable>
  );
}

function RadarScope({
  data,
  onOpenDetail
}: {
  data: RadarResponse | null;
  onOpenDetail: (callsign: string) => void;
}) {
  const scopeSize = 280;
  const projected = (data?.blips || [])
    .map((blip) => data ? projectBlip(blip, data.center, data.radius_nm, scopeSize) : null)
    .filter((item): item is ProjectedBlip => Boolean(item))
    .sort((a, b) => a.distanceNm - b.distanceNm);

  return (
    <View style={styles.scopeCard}>
      <Text style={styles.scopeTitle}>RADAR SCOPE</Text>
      <View style={[styles.scopeFrame, { width: scopeSize, height: scopeSize }]}>
        <View style={styles.scopeRingOuter} />
        <View style={styles.scopeRingMid} />
        <View style={styles.scopeRingInner} />
        <View style={styles.scopeCrossVertical} />
        <View style={styles.scopeCrossHorizontal} />
        <View style={styles.scopeCenterDot} />

        {projected.map((item, index) => (
          <Pressable
            key={`${item.blip.callsign}-${index}`}
            style={[styles.scopeDotWrap, { left: item.left, top: item.top }]}
            onPress={() => onOpenDetail(item.blip.callsign)}
          >
            <View style={[styles.scopeDot, { backgroundColor: radarTone(item.blip) }]} />
            {index < 10 ? (
              <Text style={styles.scopeLabel} numberOfLines={1}>
                {item.blip.callsign}
              </Text>
            ) : null}
          </Pressable>
        ))}

        {!data || projected.length === 0 ? (
          <View style={styles.scopeEmpty}>
            <Text style={styles.scopeEmptyText}>No targets in range</Text>
          </View>
        ) : null}
      </View>
    </View>
  );
}

function radarTone(blip: RadarBlip): string {
  if (blip.on_ground) return palette.amber;
  if (blip.enriched) return palette.green;
  return palette.blue2;
}

function FlightDetailSheet({
  visible,
  callsign,
  detail,
  history,
  loading,
  onClose,
  onRefresh
}: {
  visible: boolean;
  callsign: string;
  detail: FlightDetail | null;
  history: Array<{ date: string; status?: string | null; delay_minutes?: number | null; gate?: string | null }>;
  loading: boolean;
  onClose: () => void;
  onRefresh: () => void;
}) {
  return (
    <Modal visible={visible} animationType="slide" transparent statusBarTranslucent>
      <View style={styles.sheetBackdrop}>
        <Pressable style={styles.sheetBackdropPress} onPress={onClose} />
        <View style={styles.sheetCard}>
          <View style={styles.sheetHandle} />

          <View style={styles.sheetHeader}>
            <View style={styles.sheetHeaderText}>
              <Text style={styles.sheetEyebrow}>FLIGHT DETAIL</Text>
              <Text style={styles.sheetTitle}>{detail?.flight_number || callsign || "TRACKED FLIGHT"}</Text>
              <Text style={styles.sheetSubtitle}>{detailRouteLabel(detail, callsign)}</Text>
            </View>

            <View style={styles.sheetActions}>
              <Pressable style={styles.sheetAction} onPress={onRefresh}>
                <Text style={styles.sheetActionText}>REFRESH</Text>
              </Pressable>
              <Pressable style={styles.sheetAction} onPress={onClose}>
                <Text style={styles.sheetActionText}>CLOSE</Text>
              </Pressable>
            </View>
          </View>

          <ScrollView style={styles.sheetScroll} contentContainerStyle={styles.sheetContent}>
            {loading ? <ActivityIndicator color={palette.blue} style={styles.loader} /> : null}

            {!loading && detail ? (
              <>
                <View style={styles.sheetSummary}>
                  <StatusBadge status={detail.status || "Tracked"} statusClass={detail.status || ""} />
                  <Text style={styles.sheetSummaryText}>
                    {detail.airline || "Unknown carrier"} {detail.aircraft_type ? `- ${detail.aircraft_type}` : ""}
                  </Text>
                </View>

                <View style={styles.sheetMetricRow}>
                  <SheetMetric label="SCHEDULED" value={formatDateTime(detail.sched_time)} />
                  <SheetMetric label="ESTIMATED" value={formatDateTime(detail.est_time)} />
                </View>
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label="ACTUAL" value={formatDateTime(detail.actual_time)} />
                  <SheetMetric label="DELAY" value={detail.delay_minutes != null ? `${detail.delay_minutes}m` : "-"} />
                </View>
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label="GATE" value={detail.gate || "-"} />
                  <SheetMetric label="TERMINAL" value={detail.terminal || "-"} />
                </View>

                <SectionTitle label="TRACK" />
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label="ALTITUDE" value={formatAltitudeFeet(detail.position?.altitude_m)} />
                  <SheetMetric label="SPEED" value={formatSpeedKnots(detail.position?.speed_ms)} />
                </View>
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label="HEADING" value={formatHeading(detail.position?.heading)} />
                  <SheetMetric label="GROUND" value={detail.position?.on_ground ? "YES" : "NO"} />
                </View>

                <SectionTitle label="7-DAY HISTORY" />
                {history.length > 0 ? (
                  history.map((item) => (
                    <View key={`${item.date}-${item.status || "status"}`} style={styles.sheetHistoryRow}>
                      <Text style={styles.sheetHistoryDate}>{item.date}</Text>
                      <Text style={styles.sheetHistoryStatus}>{item.status || "Tracked"}</Text>
                      <Text style={styles.sheetHistoryMeta}>
                        {item.gate ? `Gate ${item.gate}` : "Gate -"}
                        {item.delay_minutes ? ` - ${item.delay_minutes}m` : ""}
                      </Text>
                    </View>
                  ))
                ) : (
                  <Text style={styles.sheetEmpty}>No recent history for this callsign yet.</Text>
                )}
              </>
            ) : null}

            {!loading && !detail ? (
              <>
                <Text style={styles.sheetEmpty}>
                  This flight is not in the current live snapshot. If it flew recently, its history still appears below.
                </Text>
                <SectionTitle label="7-DAY HISTORY" />
                {history.length > 0 ? (
                  history.map((item) => (
                    <View key={`${item.date}-${item.status || "status"}`} style={styles.sheetHistoryRow}>
                      <Text style={styles.sheetHistoryDate}>{item.date}</Text>
                      <Text style={styles.sheetHistoryStatus}>{item.status || "Tracked"}</Text>
                      <Text style={styles.sheetHistoryMeta}>
                        {item.gate ? `Gate ${item.gate}` : "Gate -"}
                        {item.delay_minutes ? ` - ${item.delay_minutes}m` : ""}
                      </Text>
                    </View>
                  ))
                ) : (
                  <Text style={styles.sheetEmpty}>No recent history available.</Text>
                )}
              </>
            ) : null}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

function FlightActionSheet({
  row,
  visible,
  isPinned,
  onClose,
  onOpenDetail,
  onTogglePin
}: {
  row: FidsRow | null;
  visible: boolean;
  isPinned: boolean;
  onClose: () => void;
  onOpenDetail: (callsign: string) => void;
  onTogglePin: (row: FidsRow) => void;
}) {
  if (!row) return null;

  return (
    <Modal visible={visible} animationType="fade" transparent statusBarTranslucent>
      <View style={styles.sheetBackdrop}>
        <Pressable style={styles.sheetBackdropPress} onPress={onClose} />
        <View style={styles.actionSheetCard}>
          <View style={styles.sheetHandle} />
          <Text style={styles.sheetEyebrow}>FLIGHT ACTIONS</Text>
          <Text style={styles.actionSheetTitle}>{row.flight_display || row.callsign || "Tracked flight"}</Text>
          <Text style={styles.actionSheetSubtitle} numberOfLines={1}>
            {routeName(row.route_display)} - {row.display_time || "--:--"}
          </Text>

          <View style={styles.actionSheetButtons}>
            <Pressable style={styles.actionButton} onPress={() => onTogglePin(row)}>
              <MaterialCommunityIcons
                name={isPinned ? "pin-off" : "pin"}
                size={18}
                color={isPinned ? palette.amber : palette.blue}
              />
              <Text style={styles.actionButtonText}>{isPinned ? "UNPIN FLIGHT" : "PIN TO TOP"}</Text>
            </Pressable>
            <Pressable style={styles.actionButton} onPress={() => onOpenDetail(row.callsign)}>
              <MaterialCommunityIcons name="card-search-outline" size={18} color={palette.blue} />
              <Text style={styles.actionButtonText}>OPEN DETAIL</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

function SectionTitle({ label }: { label: string }) {
  return <Text style={styles.sectionTitle}>{label}</Text>;
}

function SheetMetric({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.sheetMetric}>
      <Text style={styles.sheetMetricLabel}>{label}</Text>
      <Text style={styles.sheetMetricValue}>{value}</Text>
    </View>
  );
}

function StatusBadge({
  status,
  statusClass,
  compact
}: {
  status: string;
  statusClass: string;
  compact?: boolean;
}) {
  const tone = statusTone(`${status} ${statusClass}`);
  return (
    <View style={[styles.statusBadge, statusBadgeStyle(tone), compact && styles.statusBadgeCompact]}>
      <Text style={[styles.statusBadgeText, statusTextStyle(tone)]} numberOfLines={1}>
        {(status || "SCHED").replace(/\s+/g, " ").slice(0, compact ? 8 : 12)}
      </Text>
    </View>
  );
}

function AdminScreen({
  snapshot,
  companionIdentity,
  connected,
  error,
  rows,
  view,
  feedbackTitle,
  feedbackDescription,
  feedbackSending,
  feedbackMessage,
  feedbackTone,
  autoReportMessage,
  onFeedbackTitleChange,
  onFeedbackDescriptionChange,
  onSubmitFeedback,
  onSendAutoReportTest,
  onBackSettings
}: {
  snapshot: DashboardSnapshot;
  companionIdentity: CompanionIdentity | null;
  connected: boolean;
  error: string | null;
  rows: FidsRow[];
  view: FlightView;
  feedbackTitle: string;
  feedbackDescription: string;
  feedbackSending: boolean;
  feedbackMessage: string | null;
  feedbackTone: FeedbackTone;
  autoReportMessage: string | null;
  onFeedbackTitleChange: (value: string) => void;
  onFeedbackDescriptionChange: (value: string) => void;
  onSubmitFeedback: () => void;
  onSendAutoReportTest: () => void;
  onBackSettings: () => void;
}) {
  const budget = snapshot.budget?.aviationstack;
  const matrixEnabled = snapshot.config?.display_outputs?.includes("matrix") || false;
  const matrixLastSeen = snapshot.connections?.matrix_last_seen;
  const companionRecord =
    snapshot.connections?.companions?.find((item) => item.companion_id === companionIdentity?.companionId) || null;
  const matrixOnline =
    !!matrixLastSeen && Date.now() - new Date(matrixLastSeen).getTime() < 5 * 60 * 1000;
  const updateValue = snapshot.updates?.update_available
    ? `V${snapshot.updates.latest || "NEW"} READY`
    : `V${snapshot.updates?.current || snapshot.system?.version || APP_VERSION}`;
  const platformPair = platformPairLabel(snapshot.system?.platform, companionIdentity?.mobileOs);
  const feedbackContext = [
    `Reporter      ${companionIdentity?.clientName || "Local Flight Companion"}`,
    `Companion ID  ${companionIdentity?.companionId || "UNKNOWN"}`,
    `Companion OS  ${companionIdentity?.mobileOs || "UNKNOWN"}`,
    `Build         ${companionIdentity?.appVersion || APP_VERSION}`,
    `Server ID     ${snapshot.system?.install_id || "UNKNOWN"}`,
    `Platform pair ${platformPair}`,
    `Airport       ${snapshot.config?.airport_iata || "---"}`,
    `Source        ${snapshot.state?.source_name || snapshot.config?.source || "UNKNOWN"}`
  ].join("\n");

  return (
    <View style={styles.cardStack}>
      <HiddenToolHeader
        icon="tools"
        title="Admin"
        detail="Server health, Linear reports, and diagnostics"
        onBack={onBackSettings}
      />

      <View style={styles.metricRow}>
        <InfoCard label="SERVER" value={connected ? "ONLINE" : "CHECK"} tone={connected ? "green" : "red"} />
        <InfoCard label="VERSION" value={snapshot.system?.version || APP_VERSION} />
        <InfoCard
          label="UPDATE"
          value={updateValue}
          tone={snapshot.updates?.update_available ? "amber" : "blue"}
        />
      </View>
      <View style={styles.metricRow}>
        <InfoCard label="LAST FETCH" value={formatRelative(snapshot.state?.last_success_utc)} tone="amber" />
        <InfoCard label="WEBSOCKETS" value={String(snapshot.connections?.count ?? 0)} />
        <InfoCard label="API BUDGET" value={budget?.remaining != null ? `${budget.remaining} LEFT` : "UNKNOWN"} />
      </View>
      <View style={styles.metricRow}>
        <InfoCard label="PAIR" value={companionRecord?.platform_pair || platformPair} />
        <InfoCard label="MEMORY" value={snapshot.system?.memory_mb != null ? `${snapshot.system.memory_mb} MB` : "-"} />
        <InfoCard label="MATRIX" value={matrixOnline ? "ONLINE" : matrixEnabled ? "WAITING" : "DISABLED"} tone={matrixOnline ? "green" : matrixEnabled ? "amber" : "red"} />
      </View>

      <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>COMPANION LINK</Text>
        <Text style={styles.moduleIntro}>
          Separate mobile identity used for server presence, request tracing, and Linear reports.
        </Text>
        <InfoLine label="Companion ID" value={companionIdentity?.companionId || "Loading..."} />
        <InfoLine label="Companion OS" value={companionIdentity?.mobileOs || "Loading..."} />
        <InfoLine label="Server install" value={snapshot.system?.install_id || "Unknown"} />
        <InfoLine label="Platform pair" value={companionRecord?.platform_pair || platformPair} />
        <InfoLine label="Last check-in" value={companionRecord?.last_seen ? formatRelative(companionRecord.last_seen) : "Not seen yet"} />
      </View>

      <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>MATRIX OUTPUT</Text>
        <Text style={styles.moduleIntro}>
          Mirrors the LED output path from the main app using the same `/api/fids` rows.
        </Text>
        <InfoLine label="Enabled" value={matrixEnabled ? "Yes, matrix is selected in server outputs." : "No, enable Matrix in desktop Settings first."} />
        <InfoLine label="Last seen" value={matrixLastSeen ? formatRelative(matrixLastSeen) : "Never pinged"} />
        <InfoLine label="Preview mode" value={`${snapshot.config?.airport_iata || "---"} ${view === "arrivals" ? "ARRIVALS" : "DEPARTURES"}`} />

        <View style={styles.matrixBoard}>
          <View style={styles.matrixHeaderRow}>
            <Text style={styles.matrixBoardTitle}>INTERSTATE 75 W</Text>
            <Text style={styles.matrixBoardSub}>{matrixOnline ? "LIVE PANEL" : "SIM PREVIEW"}</Text>
          </View>
          {matrixPreviewLines(rows).map((line, index) => (
            <Text key={`${index}-${line}`} style={styles.matrixBoardLine}>
              {line}
            </Text>
          ))}
        </View>

        <Text style={styles.settingsHelp}>
          The physical matrix client polls the server directly and reports here through `/api/admin/ping`.
        </Text>
      </View>

      <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>REPORT TO DEVELOPER</Text>
        <Text style={styles.moduleIntro}>
          Sends directly to the dedicated Local Flight Reports Linear workspace.
        </Text>
        <TextInput
          value={feedbackTitle}
          onChangeText={onFeedbackTitleChange}
          placeholder="Short summary, for example Matrix not updating"
          placeholderTextColor={palette.textDim}
          style={styles.serverInput}
        />
        <TextInput
          value={feedbackDescription}
          onChangeText={onFeedbackDescriptionChange}
          placeholder="What happened, what you expected, and how to reproduce it"
          placeholderTextColor={palette.textDim}
          multiline
          textAlignVertical="top"
          style={[styles.serverInput, styles.feedbackInput]}
        />
        <View style={styles.feedbackContextBox}>
          <Text style={styles.feedbackContextText}>{feedbackContext}</Text>
        </View>
        <Pressable style={[styles.connectButton, feedbackSending && styles.connectButtonDisabled]} onPress={onSubmitFeedback} disabled={feedbackSending}>
          {feedbackSending ? <ActivityIndicator color="#000" /> : <Text style={styles.connectButtonText}>SEND REPORT</Text>}
        </Pressable>
        {feedbackMessage ? (
          <Text style={[styles.feedbackMessage, feedbackTone === "ok" ? styles.feedbackMessageOk : styles.feedbackMessageError]}>
            {feedbackMessage}
          </Text>
        ) : null}
      </View>

      {__DEV__ ? (
        <View style={styles.settingsCard}>
          <Text style={styles.settingsTitle}>AUTO REPORT TEST</Text>
          <Text style={styles.moduleIntro}>
            Developer-only helpers to verify the mobile crash pipeline before a real failure happens.
          </Text>
          <Pressable style={styles.connectButton} onPress={onSendAutoReportTest}>
            <Text style={styles.connectButtonText}>SEND AUTO TEST</Text>
          </Pressable>
          <Pressable
            style={[styles.connectButton, styles.crashButton]}
            onPress={() => {
              setTimeout(() => {
                throw new Error("Intentional mobile crash test");
              }, 10);
            }}
          >
            <Text style={styles.connectButtonText}>TRIGGER TEST CRASH</Text>
          </Pressable>
          {autoReportMessage ? <Text style={[styles.feedbackMessage, styles.feedbackMessageOk]}>{autoReportMessage}</Text> : null}
        </View>
      ) : null}

      {error ? <Text style={styles.errorText}>{error}</Text> : null}
    </View>
  );
}

function SettingsScreen({
  serverUrl,
  draftUrl,
  error,
  loading,
  isTablet,
  isLandscape,
  outputs,
  refreshSeconds,
  schedulerRestarting,
  schedulerMessage,
  onOpenAdmin,
  onOpenMatrix,
  onOpenCoffee,
  onRestartScheduler,
  onChangeUrl,
  onConnect
}: {
  serverUrl: string;
  draftUrl: string;
  error: string | null;
  loading: boolean;
  isTablet: boolean;
  isLandscape: boolean;
  outputs: string[];
  refreshSeconds: number | null;
  schedulerRestarting: boolean;
  schedulerMessage: string | null;
  onOpenAdmin: () => void;
  onOpenMatrix: () => void;
  onOpenCoffee: () => void;
  onRestartScheduler: () => void;
  onChangeUrl: (value: string) => void;
  onConnect: () => void;
}) {
  return (
    <View style={styles.cardStack}>
      <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>LOCAL SERVER</Text>
        <TextInput
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          placeholder="http://192.168.1.42:8000"
          placeholderTextColor={palette.textDim}
          value={draftUrl}
          onChangeText={onChangeUrl}
          style={styles.serverInput}
        />
        <Pressable style={styles.connectButton} onPress={onConnect} disabled={loading}>
          {loading ? <ActivityIndicator color="#000" /> : <Text style={styles.connectButtonText}>CONNECT</Text>}
        </Pressable>
        {error ? <Text style={styles.errorText}>{error}</Text> : null}
        <InfoLine label="Saved server" value={serverUrl || "Not set"} />
        <InfoLine label="Companion build" value={APP_VERSION} />
        <InfoLine label="Layout" value={isTablet ? `iPad ${isLandscape ? "landscape" : "portrait"}` : "iPhone"} />
        <InfoLine label="Outputs" value={outputs.length ? outputs.join(", ").toUpperCase() : "WEB"} />
        <InfoLine label="Update interval" value={refreshSeconds ? formatInterval(refreshSeconds) : "Not synced"} />
        <Text style={styles.settingsHelp}>
          Use the LAN IP of the machine running Local Flight. On a physical iPhone, localhost points at the phone itself.
        </Text>
      </View>

      <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>TOOLS</Text>
        <SettingsToolPill
          icon="restart"
          label="Restart scheduler"
          value={schedulerMessage || "Reload config and run a fresh fetch cycle"}
          onPress={onRestartScheduler}
          loading={schedulerRestarting}
          disabled={schedulerRestarting}
        />
        <SettingsToolPill
          icon="view-grid"
          label="Matrix panel"
          value="Preview and configure HUB75 output"
          onPress={onOpenMatrix}
        />
        <SettingsToolPill
          icon="tools"
          label="Admin panel"
          value="Diagnostics, budgets, and reports"
          onPress={onOpenAdmin}
        />
      </View>

      <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>ABOUT</Text>
        <Text style={styles.settingsHelp}>
          Local Flight is a local-first flight information display. All flight data, history, and config stay on your machine — nothing is uploaded, synced, or tracked beyond the configured aviation data sources.
        </Text>
        <Text style={styles.settingsHelp}>
          The only data that leaves your machine without your action is an automatic crash report if the server encounters an unhandled error. It contains the version, OS, airport code, and a traceback — no API keys, no IP address, no personal information.
        </Text>
        <SettingsToolPill
          icon="shield-lock-outline"
          label="Privacy"
          value="What stays local and what the crash reporter sends"
          onPress={() => Linking.openURL("https://github.com/tr3y4rch/local-flight/blob/main/PRIVACY.md")}
        />
        <SettingsToolPill
          icon="github"
          label="Source & releases"
          value="github.com/tr3y4rch/local-flight"
          onPress={() => Linking.openURL("https://github.com/tr3y4rch/local-flight")}
        />
        <SettingsToolPill
          icon="format-list-bulleted"
          label="Changelog"
          value="Release history and version notes"
          onPress={() => Linking.openURL("https://github.com/tr3y4rch/local-flight/blob/main/CHANGELOG.md")}
        />
      </View>

      <Pressable style={styles.coffeeCard} onPress={onOpenCoffee}>
        <View style={styles.coffeeIcon}>
          <MaterialCommunityIcons name="coffee" size={19} color="#111" />
        </View>
        <View style={styles.coffeeCopy}>
          <Text style={styles.coffeeTitle}>BUY ME A COFFEE</Text>
          <Text style={styles.coffeeBody}>Support Local Flight and keep the boards glowing.</Text>
        </View>
        <MaterialCommunityIcons name="open-in-new" size={16} color={palette.amber} />
      </Pressable>
    </View>
  );
}

function SettingsToolPill({
  icon,
  label,
  value,
  onPress,
  loading = false,
  disabled = false
}: {
  icon: MaterialIconName;
  label: string;
  value: string;
  onPress: () => void;
  loading?: boolean;
  disabled?: boolean;
}) {
  return (
    <Pressable
      style={[styles.settingsPill, disabled && styles.settingsPillDisabled]}
      onPress={onPress}
      disabled={disabled}
    >
      <View style={styles.settingsPillIcon}>
        <MaterialCommunityIcons name={icon} size={18} color={palette.blue2} />
      </View>
      <View style={styles.settingsPillCopy}>
        <Text style={styles.settingsPillLabel}>{label}</Text>
        <Text style={styles.settingsPillValue}>{value}</Text>
      </View>
      {loading ? (
        <ActivityIndicator color={palette.blue} />
      ) : (
        <MaterialCommunityIcons name="chevron-right" size={18} color={palette.textDim} />
      )}
    </Pressable>
  );
}

function ConnectPrompt({ onSettings }: { onSettings: () => void }) {
  return (
    <Pressable style={styles.connectPrompt} onPress={onSettings}>
      <Text style={styles.connectPromptTitle}>Connect Local Flight</Text>
      <Text style={styles.connectPromptBody}>Tap here to set the server URL before live rows can load.</Text>
    </Pressable>
  );
}

function HiddenToolHeader({
  icon,
  title,
  detail,
  onBack
}: {
  icon: MaterialIconName;
  title: string;
  detail: string;
  onBack: () => void;
}) {
  return (
    <View style={styles.hiddenToolHeader}>
      <View style={styles.hiddenToolTitleRow}>
        <View style={styles.hiddenToolIcon}>
          <MaterialCommunityIcons name={icon} size={18} color={palette.blue} />
        </View>
        <View style={styles.hiddenToolCopy}>
          <Text style={styles.hiddenToolTitle}>{title}</Text>
          <Text style={styles.hiddenToolDetail}>{detail}</Text>
        </View>
      </View>
      <Pressable style={styles.hiddenToolBack} onPress={onBack}>
        <MaterialCommunityIcons name="chevron-left" size={18} color={palette.blue2} />
        <Text style={styles.hiddenToolBackText}>SETTINGS</Text>
      </Pressable>
    </View>
  );
}

function ScreenError({ message }: { message: string }) {
  return (
    <View style={styles.errorBanner}>
      <Text style={styles.errorBannerLabel}>DATA ISSUE</Text>
      <Text style={styles.errorBannerText}>{message}</Text>
    </View>
  );
}

function InfoCard({ label, value, tone = "blue" }: { label: string; value: string; tone?: "blue" | "green" | "amber" | "red" }) {
  return (
    <View style={styles.infoCard}>
      <Text style={styles.infoLabel}>{label}</Text>
      <Text style={[styles.infoValue, { color: palette[tone] }]}>{value}</Text>
    </View>
  );
}

function InfoLine({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.infoLine}>
      <Text style={styles.infoLineLabel}>{label}</Text>
      <Text style={styles.infoLineValue}>{value}</Text>
    </View>
  );
}

function BottomNav({
  active,
  onChange,
  insetBottom
}: {
  active: Screen;
  onChange: (screen: Screen) => void;
  insetBottom: number;
}) {
  const items: Array<{ id: Screen; icon: MaterialIconName; label: string }> = [
    { id: "fids", icon: "airplane-takeoff", label: "FIDS" },
    { id: "radar", icon: "radar", label: "RADAR" },
    { id: "history", icon: "history", label: "HISTORY" },
    { id: "settings", icon: "cog-outline", label: "SETTINGS" }
  ];

  return (
    <View style={[styles.bottomNav, { paddingBottom: Math.max(insetBottom, 10) }]}>
      {items.map((item) => {
        const selected = active === item.id || ((active === "matrix" || active === "admin") && item.id === "settings");
        return (
          <Pressable key={item.id} style={styles.navItem} onPress={() => onChange(item.id)}>
            <View style={[styles.navIcon, selected && styles.navIconActive]}>
              <MaterialCommunityIcons
                name={item.icon}
                size={15}
                color={selected ? palette.blue : palette.textDim}
                style={styles.navIconGlyph}
              />
            </View>
            <Text style={[styles.navLabel, selected && styles.navLabelActive]}>{item.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function AirportConfigSheet({
  visible,
  serverUrl,
  currentConfig,
  profiles,
  onClose,
  onApplied,
  onProfilesChange
}: {
  visible: boolean;
  serverUrl: string;
  currentConfig: AppConfig | null;
  profiles: ConfigProfile[];
  onClose: () => void;
  onApplied: (config: AppConfig) => void;
  onProfilesChange: (profiles: ConfigProfile[]) => void;
}) {
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<AirportResult[]>([]);
  const [selectedAirport, setSelectedAirport] = useState<AirportResult | null>(null);
  const [source, setSource] = useState<"real" | "virtual">("real");
  const [refreshSecs, setRefreshSecs] = useState(3600);
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [profileName, setProfileName] = useState("");
  const [applyingProfileId, setApplyingProfileId] = useState<string | null>(null);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!visible) return;
    setSelectedAirport(
      currentConfig?.airport_iata
        ? {
            iata: currentConfig.airport_iata,
            icao: currentConfig.airport_icao || "",
            name: currentConfig.display_name || currentConfig.airport_iata,
            city: "",
            country: "",
            type: "",
            timezone: currentConfig.timezone
          }
        : null
    );
    setSource(currentConfig?.source === "virtual" ? "virtual" : "real");
    setRefreshSecs(currentConfig?.refresh_seconds || 3600);
    setQuery("");
    setSearchResults([]);
    setApplyError(null);
    setProfileName("");
  }, [visible, currentConfig]);

  const doSearch = useCallback(
    (text: string) => {
      if (!text.trim()) { setSearchResults([]); return; }
      void searchAirports(serverUrl, text).then(setSearchResults).catch(() => {});
    },
    [serverUrl]
  );

  const onQueryChange = useCallback(
    (text: string) => {
      setQuery(text);
      if (searchTimer.current) clearTimeout(searchTimer.current);
      searchTimer.current = setTimeout(() => doSearch(text), 300);
    },
    [doSearch]
  );

  const apply = useCallback(async () => {
    setApplying(true);
    setApplyError(null);
    try {
      const patch: ConfigPatch = { source, refresh_seconds: refreshSecs };
      if (selectedAirport) {
        patch.airport_iata = selectedAirport.iata;
        patch.airport_icao = selectedAirport.icao;
        if (selectedAirport.timezone) patch.timezone = selectedAirport.timezone;
      }
      onApplied(await patchConfig(serverUrl, patch));
    } catch (e) {
      setApplyError(e instanceof Error ? e.message : String(e));
    } finally {
      setApplying(false);
    }
  }, [onApplied, refreshSecs, selectedAirport, serverUrl, source]);

  const saveProfile = useCallback(async () => {
    if (!profileName.trim() || !selectedAirport) return;
    const next: ConfigProfile[] = [
      ...profiles.filter((p) => p.name !== profileName.trim()),
      {
        id: String(Date.now()),
        name: profileName.trim(),
        iata: selectedAirport.iata,
        icao: selectedAirport.icao,
        timezone: selectedAirport.timezone,
        source,
        refresh_seconds: refreshSecs
      }
    ];
    await saveProfiles(next);
    onProfilesChange(next);
    setProfileName("");
  }, [onProfilesChange, profileName, profiles, refreshSecs, selectedAirport, source]);

  const deleteProfile = useCallback(
    async (id: string) => {
      const next = profiles.filter((p) => p.id !== id);
      await saveProfiles(next);
      onProfilesChange(next);
    },
    [onProfilesChange, profiles]
  );

  const applyProfile = useCallback(
    async (p: ConfigProfile) => {
      setApplyingProfileId(p.id);
      setApplyError(null);
      try {
        const patch: ConfigPatch = {
          airport_iata: p.iata,
          airport_icao: p.icao,
          timezone: p.timezone,
          source: p.source,
          refresh_seconds: p.refresh_seconds
        };
        onApplied(await patchConfig(serverUrl, patch));
      } catch (e) {
        setApplyError(e instanceof Error ? e.message : String(e));
      } finally {
        setApplyingProfileId(null);
      }
    },
    [onApplied, serverUrl]
  );

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}
    >
      <View style={styles.configSheetBg}>
        <View style={styles.configSheet}>
          <View style={styles.configSheetHandle} />
          <View style={styles.configSheetHeader}>
            <Text style={styles.configSheetTitle}>CONFIGURE SERVER</Text>
            <Pressable onPress={onClose} style={styles.configSheetClose}>
              <MaterialCommunityIcons name="close" size={20} color={palette.textMuted} />
            </Pressable>
          </View>

          <ScrollView style={styles.configSheetScroll} keyboardShouldPersistTaps="handled">
            <Text style={styles.configSectionLabel}>AIRPORT</Text>
            <TextInput
              style={styles.configSearchInput}
              placeholder="Search by name, IATA or city…"
              placeholderTextColor={palette.textDim}
              value={query}
              onChangeText={onQueryChange}
              autoCapitalize="characters"
              returnKeyType="search"
            />
            {searchResults.length > 0 && (
              <View style={styles.configSearchResults}>
                {searchResults.map((r) => (
                  <Pressable
                    key={r.iata}
                    style={[
                      styles.configSearchRow,
                      selectedAirport?.iata === r.iata && styles.configSearchRowSelected
                    ]}
                    onPress={() => { setSelectedAirport(r); setQuery(""); setSearchResults([]); }}
                  >
                    <Text style={styles.configSearchIata}>{r.iata}</Text>
                    <View style={styles.configSearchInfo}>
                      <Text style={styles.configSearchName} numberOfLines={1}>{r.name}</Text>
                      <Text style={styles.configSearchMeta}>{r.city} · {r.country}</Text>
                    </View>
                  </Pressable>
                ))}
              </View>
            )}
            {selectedAirport ? (
              <View style={styles.configSelectedAirport}>
                <MaterialCommunityIcons name="check-circle" size={14} color={palette.green} />
                <Text style={styles.configSelectedText}>
                  {selectedAirport.iata}
                  {selectedAirport.icao ? ` / ${selectedAirport.icao}` : ""}
                  {selectedAirport.name ? ` — ${selectedAirport.name}` : ""}
                </Text>
              </View>
            ) : null}

            <Text style={styles.configSectionLabel}>DATA SOURCE</Text>
            <View style={styles.configSegControl}>
              {(["real", "virtual"] as const).map((opt) => (
                <Pressable
                  key={opt}
                  style={[styles.configSegOption, source === opt && styles.configSegOptionActive]}
                  onPress={() => setSource(opt)}
                >
                  <Text style={[styles.configSegText, source === opt && styles.configSegTextActive]}>
                    {opt === "real" ? "REAL" : "VIRTUAL / VATSIM"}
                  </Text>
                </Pressable>
              ))}
            </View>

            <Text style={styles.configSectionLabel}>REFRESH INTERVAL</Text>
            <View style={styles.configIntervalGrid}>
              {REFRESH_OPTIONS.map((opt) => (
                <Pressable
                  key={opt.seconds}
                  style={[styles.configIntervalCell, refreshSecs === opt.seconds && styles.configIntervalCellActive]}
                  onPress={() => setRefreshSecs(opt.seconds)}
                >
                  <Text style={[styles.configIntervalText, refreshSecs === opt.seconds && styles.configIntervalTextActive]}>
                    {opt.label}
                  </Text>
                </Pressable>
              ))}
            </View>

            <Text style={styles.configSectionLabel}>PROFILES</Text>
            {profiles.length > 0 && (
              <View style={styles.configProfileList}>
                {profiles.map((p) => {
                  const isApplyingThis = applyingProfileId === p.id;
                  return (
                    <View key={p.id} style={styles.configProfileRow}>
                      <Pressable
                        style={styles.configProfileLoad}
                        onPress={() => void applyProfile(p)}
                        disabled={applyingProfileId !== null}
                      >
                        <Text style={styles.configProfileName}>{p.name}</Text>
                        <Text style={styles.configProfileMeta}>
                          {p.iata} · {p.source === "virtual" ? "VATSIM" : "REAL"} · {formatInterval(p.refresh_seconds)}
                        </Text>
                      </Pressable>
                      {isApplyingThis
                        ? <ActivityIndicator size="small" color={palette.blue2} style={{ marginRight: 14 }} />
                        : (
                          <Pressable
                            onPress={() => void deleteProfile(p.id)}
                            style={styles.configProfileDelete}
                            disabled={applyingProfileId !== null}
                          >
                            <MaterialCommunityIcons name="trash-can-outline" size={16} color={palette.textDim} />
                          </Pressable>
                        )
                      }
                    </View>
                  );
                })}
              </View>
            )}
            <View style={styles.configSaveRow}>
              <TextInput
                style={styles.configProfileInput}
                placeholder="Profile name…"
                placeholderTextColor={palette.textDim}
                value={profileName}
                onChangeText={setProfileName}
              />
              <Pressable
                style={[styles.configSaveBtn, (!profileName.trim() || !selectedAirport) && styles.configSaveBtnDisabled]}
                onPress={() => void saveProfile()}
                disabled={!profileName.trim() || !selectedAirport}
              >
                <Text style={styles.configSaveBtnText}>SAVE</Text>
              </Pressable>
            </View>

            {applyError ? <Text style={styles.configErrorText}>{applyError}</Text> : null}
            <Pressable
              style={[styles.configApplyBtn, applying && styles.configApplyBtnBusy]}
              onPress={() => void apply()}
              disabled={applying}
            >
              {applying
                ? <ActivityIndicator size="small" color={palette.bg} />
                : <Text style={styles.configApplyBtnText}>APPLY TO SERVER</Text>
              }
            </Pressable>
            <View style={{ height: 36 }} />
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: palette.bg,
    alignItems: "center"
  },
  appFrame: {
    flex: 1,
    width: "100%",
    backgroundColor: palette.shell,
    borderLeftWidth: 1,
    borderRightWidth: 1,
    borderColor: palette.line
  },
  launchOverlay: {
    zIndex: 40,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: palette.bg
  },
  launchHalo: {
    position: "absolute",
    width: 360,
    height: 360,
    borderRadius: 999,
    backgroundColor: "rgba(74,158,218,0.14)"
  },
  launchHaloInner: {
    position: "absolute",
    width: 238,
    height: 238,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "rgba(122,176,216,0.24)",
    borderTopColor: "rgba(41,226,135,0.72)",
    borderRightColor: "rgba(240,180,41,0.38)",
    backgroundColor: "rgba(255,255,255,0.018)"
  },
  launchPanel: {
    minWidth: 250,
    paddingHorizontal: 28,
    paddingVertical: 30,
    borderRadius: 28,
    borderWidth: 1,
    borderColor: "rgba(74,158,218,0.16)",
    backgroundColor: "rgba(7,12,18,0.88)",
    alignItems: "center"
  },
  launchMarkWrap: {
    width: 126,
    height: 126,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 18
  },
  launchRadarRing: {
    position: "absolute",
    width: 122,
    height: 122,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "rgba(122,176,216,0.24)"
  },
  launchSweep: {
    position: "absolute",
    width: 2,
    height: 58,
    top: 6,
    borderRadius: 999,
    backgroundColor: "rgba(41,226,135,0.72)"
  },
  launchMark: {
    width: 96,
    height: 96
  },
  launchEyebrow: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 2.4
  },
  launchTitle: {
    marginTop: 8,
    color: palette.text,
    fontSize: 24,
    fontWeight: "800",
    letterSpacing: 1.6
  },
  launchVersion: {
    marginTop: 10,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "rgba(74,158,218,0.18)",
    backgroundColor: "rgba(74,158,218,0.08)",
    fontFamily: mono,
    color: palette.textMuted,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 1
  },
  launchStatusRow: {
    width: "100%",
    marginTop: 18,
    alignItems: "center"
  },
  launchStatus: {
    fontFamily: mono,
    color: palette.textMuted,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 1.2,
    textTransform: "uppercase"
  },
  launchProgressTrack: {
    width: "100%",
    height: 4,
    marginTop: 12,
    overflow: "hidden",
    borderRadius: 999,
    backgroundColor: "rgba(255,255,255,0.09)"
  },
  launchProgressFill: {
    height: "100%",
    borderRadius: 999,
    backgroundColor: palette.green
  },
  header: {
    paddingTop: 10,
    paddingHorizontal: 22,
    paddingBottom: 16,
    backgroundColor: palette.header,
    borderBottomWidth: 1,
    borderBottomColor: palette.lineSoft
  },
  mainArea: {
    flex: 1
  },
  islandShell: {
    alignSelf: "center",
    marginBottom: 14,
    borderRadius: 22,
    borderWidth: 1,
    borderColor: "rgba(74,158,218,0.16)",
    backgroundColor: "rgba(0,0,0,0.58)",
    overflow: "hidden"
  },
  islandPressable: {
    paddingHorizontal: 14,
    paddingTop: 9,
    paddingBottom: 8
  },
  islandCompactRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12
  },
  islandLead: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    flex: 1
  },
  islandTextWrap: {
    flex: 1,
    minWidth: 0
  },
  islandFlight: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 0.8
  },
  islandMeta: {
    marginTop: 2,
    color: palette.textMuted,
    fontSize: 11
  },
  islandTrail: {
    alignItems: "flex-end",
    gap: 1
  },
  islandStatus: {
    fontFamily: mono,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.8
  },
  islandExpanded: {
    overflow: "hidden"
  },
  islandExpandedLine: {
    marginTop: 8,
    color: palette.text,
    fontFamily: mono,
    fontSize: 11
  },
  islandExpandedHint: {
    marginTop: 4,
    color: palette.textMuted,
    fontSize: 10
  },
  headerTop: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    marginBottom: 14
  },
  headerLeft: {
    flex: 1,
    minWidth: 0
  },
  airportCode: {
    fontFamily: mono,
    fontSize: 34,
    fontWeight: "700",
    color: "#fff",
    letterSpacing: 2
  },
  airportName: {
    marginTop: 2,
    color: palette.textMuted,
    fontSize: 12,
    letterSpacing: 0.5
  },
  headerRight: {
    alignItems: "flex-end",
    gap: 7
  },
  headerStatusRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 7,
    marginTop: 9,
    flexWrap: "wrap"
  },
  livePill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: "rgba(0,192,64,0.25)",
    backgroundColor: "rgba(0,192,64,0.10)"
  },
  livePillOff: {
    borderColor: "rgba(255,107,107,0.25)",
    backgroundColor: "rgba(255,107,107,0.10)"
  },
  liveDot: {
    width: 5,
    height: 5,
    borderRadius: 999,
    backgroundColor: palette.green
  },
  liveDotOff: {
    backgroundColor: palette.red
  },
  liveText: {
    fontFamily: mono,
    fontSize: 10,
    color: palette.green,
    letterSpacing: 1,
    fontWeight: "700"
  },
  liveTextOff: {
    color: palette.red
  },
  sourcePill: {
    paddingHorizontal: 9,
    paddingVertical: 5,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "rgba(74,158,218,0.18)",
    backgroundColor: "rgba(74,158,218,0.08)"
  },
  sourceText: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 9,
    fontWeight: "700",
    letterSpacing: 0.8
  },
  utcTime: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 12,
    fontWeight: "700"
  },
  localTime: {
    fontFamily: mono,
    color: palette.textMuted,
    fontSize: 11
  },
  metarStrip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderRadius: 8,
    backgroundColor: "rgba(255,255,255,0.03)"
  },
  metarCat: {
    fontFamily: mono,
    color: "#000",
    backgroundColor: palette.green,
    fontSize: 9,
    fontWeight: "700",
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    letterSpacing: 1
  },
  metarText: {
    flex: 1,
    color: palette.textMuted,
    fontSize: 11
  },
  headerAccentBar: {
    position: "absolute",
    top: 0,
    bottom: 0,
    left: 0,
    width: 4,
    borderTopRightRadius: 2,
    borderBottomRightRadius: 2
  },
  identityBand: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    marginBottom: 10
  },
  identityLeft: {
    flex: 1,
    minWidth: 0
  },
  airportIcao: {
    color: palette.textDim,
    fontSize: 11
  },
  configHint: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    marginTop: 3
  },
  configHintText: {
    color: palette.textDim,
    fontSize: 10
  },
  identityRight: {
    alignItems: "flex-end",
    gap: 6,
    paddingLeft: 10
  },
  utcSuffix: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 11,
    fontWeight: "400"
  },
  localSuffix: {
    color: palette.textDim,
    fontSize: 10
  },
  metarCatBadge: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
    borderWidth: 1
  },
  metarCatBadgeText: {
    fontFamily: mono,
    fontSize: 11,
    fontWeight: "700"
  },
  telemetryStrip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 7,
    marginBottom: 10,
    flexWrap: "wrap"
  },
  countPill: {
    paddingHorizontal: 9,
    paddingVertical: 5,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.12)",
    backgroundColor: "rgba(255,255,255,0.05)"
  },
  countText: {
    fontFamily: mono,
    color: palette.textMuted,
    fontSize: 9,
    fontWeight: "700"
  },
  metarChipRow: {
    flexDirection: "row",
    gap: 6,
    paddingVertical: 4
  },
  metarChip: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "rgba(74,158,218,0.16)",
    backgroundColor: "rgba(74,158,218,0.06)",
    alignItems: "center",
    gap: 2
  },
  metarChipLabel: {
    fontFamily: mono,
    fontSize: 9,
    fontWeight: "700",
    color: palette.textDim,
    letterSpacing: 0.8
  },
  metarChipValue: {
    fontFamily: mono,
    fontSize: 12,
    fontWeight: "700",
    color: palette.text
  },
  screenScroll: {
    flex: 1
  },
  screenContent: {
    paddingTop: 12,
    paddingBottom: 20
  },
  errorBanner: {
    marginHorizontal: 12,
    marginBottom: 10,
    padding: 14,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "rgba(255,107,107,0.18)",
    backgroundColor: "rgba(255,107,107,0.08)"
  },
  errorBannerLabel: {
    fontFamily: mono,
    color: palette.red,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 1.2
  },
  errorBannerText: {
    marginTop: 5,
    color: palette.text,
    fontSize: 12,
    lineHeight: 18
  },
  filterSection: {
    paddingHorizontal: 12,
    paddingBottom: 10
  },
  filterLabel: {
    paddingHorizontal: 10,
    marginBottom: 6,
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 8,
    letterSpacing: 2,
    fontWeight: "700"
  },
  filterRow: {
    flexDirection: "row",
    gap: 8
  },
  filterWrap: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8
  },
  optionChip: {
    minWidth: 82,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.08)",
    backgroundColor: "rgba(255,255,255,0.03)"
  },
  optionChipActive: {
    borderColor: "rgba(74,158,218,0.4)",
    backgroundColor: "rgba(74,158,218,0.12)"
  },
  optionChipLabel: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 11,
    fontWeight: "700"
  },
  optionChipLabelActive: {
    color: palette.blue
  },
  optionChipMeta: {
    marginTop: 3,
    color: palette.textDim,
    fontSize: 10
  },
  optionChipMetaActive: {
    color: palette.textMuted
  },
  dirToggle: {
    flexDirection: "row",
    marginHorizontal: 22,
    marginBottom: 10,
    padding: 3,
    borderRadius: 8,
    backgroundColor: "rgba(255,255,255,0.04)"
  },
  dirButton: {
    flex: 1,
    paddingVertical: 8,
    alignItems: "center",
    borderRadius: 6,
    borderWidth: 1,
    borderColor: "transparent"
  },
  dirButtonActive: {
    backgroundColor: "rgba(74,158,218,0.12)",
    borderColor: "rgba(74,158,218,0.20)"
  },
  dirButtonText: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 1
  },
  dirButtonTextActive: {
    color: palette.blue
  },
  metricRow: {
    flexDirection: "row",
    gap: 8,
    paddingHorizontal: 12,
    paddingBottom: 12
  },
  fidsHeader: {
    flexDirection: "row",
    paddingHorizontal: 22,
    paddingBottom: 6,
    gap: 4
  },
  fidsHeaderText: {
    fontFamily: mono,
    flex: 1,
    color: palette.line,
    fontSize: 8,
    fontWeight: "700",
    letterSpacing: 1
  },
  alignRight: {
    textAlign: "right",
    flex: 0.48
  },
  fidsListItem: {
    paddingHorizontal: 12
  },
  fidsRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    minHeight: 55,
    paddingHorizontal: 10,
    paddingVertical: 9,
    marginBottom: 3,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.03)",
    backgroundColor: palette.row
  },
  fidsRowPinned: {
    borderColor: "rgba(240,180,41,0.24)",
    backgroundColor: "rgba(240,180,41,0.07)"
  },
  fidsTime: {
    width: 52,
    fontFamily: mono,
    color: palette.text,
    fontSize: 12,
    fontWeight: "700"
  },
  fidsFlightWrap: {
    width: 70,
    flexDirection: "row",
    alignItems: "center",
    gap: 4
  },
  fidsFlight: {
    flex: 1,
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 11
  },
  fidsDest: {
    flex: 1,
    minWidth: 0
  },
  fidsDestName: {
    color: "#8aaccc",
    fontSize: 12
  },
  fidsDestCode: {
    marginTop: 1,
    fontFamily: mono,
    color: "#3a6a9a",
    fontSize: 9
  },
  fidsAircraft: {
    width: 34,
    textAlign: "right",
    fontFamily: mono,
    color: "#2a4a6a",
    fontSize: 9
  },
  historyGap: {
    height: 8
  },
  historyRow: {
    flexDirection: "row",
    gap: 12,
    marginHorizontal: 12,
    padding: 14,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.05)",
    backgroundColor: palette.row
  },
  historyTimeBox: {
    width: 68
  },
  historyTime: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 13,
    fontWeight: "700"
  },
  historyDate: {
    marginTop: 4,
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 10
  },
  historyMain: {
    flex: 1,
    minWidth: 0
  },
  historyFlight: {
    color: palette.text,
    fontSize: 14,
    fontWeight: "700"
  },
  historyRoute: {
    marginTop: 3,
    color: palette.blue2,
    fontSize: 12,
    fontWeight: "600"
  },
  historyMeta: {
    marginTop: 4,
    color: palette.textMuted,
    fontSize: 11
  },
  historyTrail: {
    alignItems: "flex-end",
    gap: 8
  },
  historyDir: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 9,
    letterSpacing: 1
  },
  scopeCard: {
    marginHorizontal: 12,
    marginBottom: 12,
    padding: 18,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: "rgba(74,158,218,0.14)",
    backgroundColor: "rgba(9,15,23,0.88)"
  },
  scopeTitle: {
    marginBottom: 12,
    fontFamily: mono,
    color: palette.blue,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 1.3
  },
  scopeFrame: {
    alignSelf: "center",
    justifyContent: "center",
    alignItems: "center",
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "rgba(74,158,218,0.18)",
    backgroundColor: "rgba(0,0,0,0.18)",
    overflow: "hidden"
  },
  scopeRingOuter: {
    position: "absolute",
    width: "100%",
    height: "100%",
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "rgba(74,158,218,0.12)"
  },
  scopeRingMid: {
    position: "absolute",
    width: "66%",
    height: "66%",
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "rgba(74,158,218,0.10)"
  },
  scopeRingInner: {
    position: "absolute",
    width: "33%",
    height: "33%",
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "rgba(74,158,218,0.08)"
  },
  scopeCrossVertical: {
    position: "absolute",
    width: 1,
    top: 0,
    bottom: 0,
    backgroundColor: "rgba(74,158,218,0.12)"
  },
  scopeCrossHorizontal: {
    position: "absolute",
    height: 1,
    left: 0,
    right: 0,
    backgroundColor: "rgba(74,158,218,0.12)"
  },
  scopeCenterDot: {
    width: 8,
    height: 8,
    borderRadius: 999,
    backgroundColor: palette.blue
  },
  scopeDotWrap: {
    position: "absolute"
  },
  scopeDot: {
    width: 10,
    height: 10,
    borderRadius: 999
  },
  scopeLabel: {
    position: "absolute",
    left: 12,
    top: -4,
    width: 72,
    fontFamily: mono,
    color: palette.text,
    fontSize: 9
  },
  scopeEmpty: {
    position: "absolute",
    alignItems: "center",
    justifyContent: "center"
  },
  scopeEmptyText: {
    color: palette.textMuted,
    fontSize: 12
  },
  radarDotLarge: {
    width: 10,
    height: 10,
    borderRadius: 999
  },
  statusBadge: {
    maxWidth: 92,
    paddingHorizontal: 8,
    paddingVertical: 5,
    borderRadius: 5,
    alignItems: "center"
  },
  statusBadgeCompact: {
    width: 78,
    paddingHorizontal: 5
  },
  status_scheduled: { backgroundColor: "rgba(74,158,218,0.10)" },
  status_departed: { backgroundColor: "rgba(74,158,218,0.06)", opacity: 0.68 },
  status_boarding: { backgroundColor: "rgba(0,192,64,0.12)" },
  status_delayed: { backgroundColor: "rgba(240,180,41,0.11)" },
  status_cancelled: { backgroundColor: "rgba(255,107,107,0.12)" },
  statusBadgeText: {
    fontFamily: mono,
    fontSize: 8,
    fontWeight: "700",
    letterSpacing: 0.5
  },
  statusText_scheduled: { color: palette.status.scheduled },
  statusText_departed: { color: palette.status.departed },
  statusText_boarding: { color: palette.status.boarding },
  statusText_delayed: { color: palette.status.delayed },
  statusText_cancelled: { color: palette.status.cancelled },
  loader: {
    marginTop: 28
  },
  empty: {
    color: palette.textMuted,
    textAlign: "center",
    padding: 22,
    lineHeight: 20
  },
  connectPrompt: {
    marginHorizontal: 12,
    marginBottom: 10,
    padding: 14,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "rgba(240,180,41,0.18)",
    backgroundColor: "rgba(240,180,41,0.07)"
  },
  connectPromptTitle: {
    fontFamily: mono,
    color: palette.amber,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 1
  },
  connectPromptBody: {
    marginTop: 5,
    color: palette.textMuted,
    fontSize: 12,
    lineHeight: 18
  },
  cardStack: {
    paddingHorizontal: 12,
    gap: 8
  },
  infoCard: {
    flex: 1,
    padding: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.05)",
    backgroundColor: palette.row
  },
  infoLabel: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 9,
    fontWeight: "700",
    letterSpacing: 1.4
  },
  infoValue: {
    marginTop: 5,
    fontFamily: mono,
    fontSize: 15,
    fontWeight: "700"
  },
  settingsCard: {
    marginHorizontal: 12,
    padding: 16,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "rgba(74,158,218,0.15)",
    backgroundColor: palette.row
  },
  settingsTitle: {
    fontFamily: mono,
    color: palette.blue,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 1.2,
    marginBottom: 10
  },
  moduleIntro: {
    color: palette.textMuted,
    fontSize: 12,
    lineHeight: 18
  },
  settingsPill: {
    minHeight: 58,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    marginTop: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "rgba(74,158,218,0.14)",
    backgroundColor: "rgba(255,255,255,0.03)"
  },
  settingsPillDisabled: {
    opacity: 0.72
  },
  settingsPillIcon: {
    width: 34,
    height: 34,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(74,158,218,0.10)"
  },
  settingsPillCopy: {
    flex: 1,
    minWidth: 0
  },
  settingsPillLabel: {
    color: palette.text,
    fontSize: 13,
    fontWeight: "700"
  },
  settingsPillValue: {
    marginTop: 3,
    color: palette.textMuted,
    fontSize: 11
  },
  hiddenToolHeader: {
    marginHorizontal: 12,
    marginBottom: 4,
    padding: 14,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "rgba(74,158,218,0.14)",
    backgroundColor: "rgba(74,158,218,0.06)"
  },
  hiddenToolTitleRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10
  },
  hiddenToolIcon: {
    width: 38,
    height: 38,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(74,158,218,0.10)"
  },
  hiddenToolCopy: {
    flex: 1,
    minWidth: 0
  },
  hiddenToolTitle: {
    color: palette.text,
    fontSize: 16,
    fontWeight: "800"
  },
  hiddenToolDetail: {
    marginTop: 3,
    color: palette.textMuted,
    fontSize: 11
  },
  hiddenToolBack: {
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-start",
    gap: 2,
    marginTop: 12,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
    backgroundColor: "rgba(255,255,255,0.04)"
  },
  hiddenToolBackText: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 9,
    fontWeight: "700",
    letterSpacing: 0.8
  },
  coffeeCard: {
    marginHorizontal: 12,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    padding: 14,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "rgba(240,180,41,0.22)",
    backgroundColor: "rgba(240,180,41,0.08)"
  },
  coffeeIcon: {
    width: 36,
    height: 36,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: palette.amber
  },
  coffeeCopy: {
    flex: 1,
    minWidth: 0
  },
  coffeeTitle: {
    fontFamily: mono,
    color: palette.amber,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 1
  },
  coffeeBody: {
    marginTop: 3,
    color: palette.textMuted,
    fontSize: 11
  },
  serverInput: {
    minHeight: 46,
    paddingHorizontal: 12,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.08)",
    color: palette.text,
    backgroundColor: "rgba(0,0,0,0.18)",
    fontFamily: mono,
    fontSize: 12
  },
  connectButton: {
    marginTop: 10,
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8,
    backgroundColor: palette.green
  },
  connectButtonDisabled: {
    opacity: 0.5
  },
  crashButton: {
    backgroundColor: palette.amber
  },
  connectButtonText: {
    fontFamily: mono,
    color: "#000",
    fontWeight: "700",
    fontSize: 11,
    letterSpacing: 1
  },
  errorText: {
    marginTop: 10,
    color: palette.red,
    fontSize: 12,
    lineHeight: 18
  },
  infoLine: {
    marginTop: 12,
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: "rgba(255,255,255,0.05)"
  },
  infoLineLabel: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 9,
    fontWeight: "700",
    letterSpacing: 1
  },
  infoLineValue: {
    marginTop: 4,
    color: palette.text,
    fontSize: 12,
    fontWeight: "600"
  },
  settingsHelp: {
    marginTop: 14,
    color: palette.textMuted,
    fontSize: 12,
    lineHeight: 18
  },
  feedbackInput: {
    minHeight: 108,
    paddingTop: 12,
    marginTop: 10
  },
  feedbackContextBox: {
    marginTop: 10,
    padding: 12,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "rgba(74,158,218,0.14)",
    backgroundColor: "rgba(0,0,0,0.18)"
  },
  feedbackContextText: {
    fontFamily: mono,
    color: palette.textMuted,
    fontSize: 11,
    lineHeight: 18
  },
  feedbackMessage: {
    marginTop: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 10,
    fontSize: 12,
    lineHeight: 18
  },
  feedbackMessageOk: {
    color: palette.green,
    backgroundColor: "rgba(0,192,64,0.10)",
    borderWidth: 1,
    borderColor: "rgba(0,192,64,0.18)"
  },
  feedbackMessageError: {
    color: palette.red,
    backgroundColor: "rgba(255,107,107,0.10)",
    borderWidth: 1,
    borderColor: "rgba(255,107,107,0.18)"
  },
  matrixBoard: {
    marginTop: 12,
    padding: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "rgba(0,192,64,0.16)",
    backgroundColor: "#041108"
  },
  matrixHeaderRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 10
  },
  matrixBoardTitle: {
    fontFamily: mono,
    color: "#58f28a",
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 1
  },
  matrixBoardSub: {
    fontFamily: mono,
    color: "#2cab57",
    fontSize: 9,
    letterSpacing: 0.8
  },
  matrixBoardLine: {
    fontFamily: mono,
    color: "#8cffad",
    fontSize: 12,
    lineHeight: 20,
    letterSpacing: 0.8
  },
  matrixToolShell: {
    marginHorizontal: 12,
    padding: 14,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.04)",
    backgroundColor: "#010101"
  },
  matrixToolBezel: {
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
    borderColor: "#111",
    backgroundColor: "#060606"
  },
  matrixToolHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 10
  },
  matrixToolTitle: {
    fontFamily: mono,
    color: "#58f28a",
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.8
  },
  matrixToolMeta: {
    fontFamily: mono,
    color: "#2cab57",
    fontSize: 9
  },
  matrixPixelBoard: {
    borderRadius: 10,
    padding: 14,
    borderWidth: 1,
    borderColor: "rgba(88,242,138,0.12)",
    backgroundColor: "#021006"
  },
  matrixToolAirport: {
    fontFamily: mono,
    color: "#49e47b",
    fontSize: 10,
    marginBottom: 8,
    letterSpacing: 1.2
  },
  matrixPixelLine: {
    fontFamily: mono,
    color: "#8cffad",
    fontSize: 12,
    lineHeight: 20,
    letterSpacing: 0.5
  },
  bottomNav: {
    flexDirection: "row",
    justifyContent: "space-around",
    alignItems: "center",
    minHeight: 72,
    paddingTop: 10,
    paddingHorizontal: 12,
    borderTopWidth: 1,
    borderTopColor: "rgba(255,255,255,0.06)",
    backgroundColor: "rgba(9,14,22,0.97)"
  },
  navItem: {
    alignItems: "center",
    gap: 4,
    minWidth: 54
  },
  navIcon: {
    width: 25,
    height: 25,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: "rgba(74,158,218,0.18)"
  },
  navIconActive: {
    borderColor: "rgba(74,158,218,0.42)",
    backgroundColor: "rgba(74,158,218,0.12)"
  },
  navIconGlyph: {
    lineHeight: 15
  },
  navLabel: {
    fontFamily: mono,
    fontSize: 7,
    color: palette.textDim,
    letterSpacing: 0.5
  },
  navLabelActive: {
    color: palette.blue
  },
  sheetBackdrop: {
    flex: 1,
    justifyContent: "flex-end",
    backgroundColor: "rgba(0,0,0,0.48)"
  },
  sheetBackdropPress: {
    flex: 1
  },
  sheetCard: {
    minHeight: "62%",
    maxHeight: "88%",
    borderTopLeftRadius: 28,
    borderTopRightRadius: 28,
    borderWidth: 1,
    borderColor: "rgba(74,158,218,0.16)",
    backgroundColor: "#0b121c",
    paddingTop: 10
  },
  actionSheetCard: {
    marginHorizontal: 12,
    marginBottom: 12,
    padding: 18,
    borderRadius: 24,
    borderWidth: 1,
    borderColor: "rgba(74,158,218,0.16)",
    backgroundColor: "#0b121c"
  },
  actionSheetTitle: {
    marginTop: 8,
    color: palette.text,
    fontSize: 20,
    fontWeight: "800"
  },
  actionSheetSubtitle: {
    marginTop: 4,
    color: palette.textMuted,
    fontSize: 12
  },
  actionSheetButtons: {
    marginTop: 16,
    gap: 8
  },
  actionButton: {
    minHeight: 48,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 14,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.06)",
    backgroundColor: "rgba(255,255,255,0.035)"
  },
  actionButtonText: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.8
  },
  sheetHandle: {
    alignSelf: "center",
    width: 54,
    height: 5,
    borderRadius: 999,
    backgroundColor: "rgba(255,255,255,0.18)"
  },
  sheetHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: 12,
    paddingHorizontal: 18,
    paddingTop: 16,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: "rgba(255,255,255,0.05)"
  },
  sheetHeaderText: {
    flex: 1,
    minWidth: 0
  },
  sheetEyebrow: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 9,
    fontWeight: "700",
    letterSpacing: 1.4
  },
  sheetTitle: {
    marginTop: 4,
    color: palette.text,
    fontSize: 20,
    fontWeight: "800"
  },
  sheetSubtitle: {
    marginTop: 4,
    color: palette.textMuted,
    fontSize: 12
  },
  sheetActions: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 8
  },
  sheetAction: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "rgba(74,158,218,0.18)",
    backgroundColor: "rgba(74,158,218,0.08)"
  },
  sheetActionText: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 1
  },
  sheetScroll: {
    flex: 1
  },
  sheetContent: {
    padding: 18,
    paddingBottom: 36
  },
  sheetSummary: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    marginBottom: 16
  },
  sheetSummaryText: {
    flex: 1,
    color: palette.textMuted,
    fontSize: 12
  },
  sheetMetricRow: {
    flexDirection: "row",
    gap: 10,
    marginBottom: 10
  },
  sheetMetric: {
    flex: 1,
    padding: 14,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.05)",
    backgroundColor: "rgba(255,255,255,0.025)"
  },
  sheetMetricLabel: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 9,
    fontWeight: "700",
    letterSpacing: 1.2
  },
  sheetMetricValue: {
    marginTop: 6,
    color: palette.text,
    fontSize: 14,
    fontWeight: "700"
  },
  sectionTitle: {
    marginTop: 8,
    marginBottom: 10,
    fontFamily: mono,
    color: palette.blue,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 1.4
  },
  sheetHistoryRow: {
    paddingVertical: 10,
    borderTopWidth: 1,
    borderTopColor: "rgba(255,255,255,0.05)"
  },
  sheetHistoryDate: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 12,
    fontWeight: "700"
  },
  sheetHistoryStatus: {
    marginTop: 3,
    color: palette.blue2,
    fontSize: 12,
    fontWeight: "600"
  },
  sheetHistoryMeta: {
    marginTop: 3,
    color: palette.textMuted,
    fontSize: 11
  },
  sheetEmpty: {
    color: palette.textMuted,
    fontSize: 12,
    lineHeight: 18
  },
  configSheetBg: {
    flex: 1,
    justifyContent: "flex-end",
    backgroundColor: "rgba(0,0,0,0.5)"
  },
  configSheet: {
    backgroundColor: palette.shell,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    borderWidth: 1,
    borderBottomWidth: 0,
    borderColor: palette.line,
    maxHeight: "88%"
  },
  configSheetHandle: {
    alignSelf: "center",
    marginTop: 10,
    marginBottom: 6,
    width: 36,
    height: 4,
    borderRadius: 2,
    backgroundColor: "rgba(255,255,255,0.16)"
  },
  configSheetHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 20,
    paddingBottom: 14,
    paddingTop: 4,
    borderBottomWidth: 1,
    borderBottomColor: palette.lineSoft
  },
  configSheetTitle: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 13,
    fontWeight: "700",
    letterSpacing: 1.2
  },
  configSheetClose: {
    padding: 6
  },
  configSheetScroll: {
    paddingHorizontal: 20
  },
  configSectionLabel: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 1.4,
    marginTop: 20,
    marginBottom: 8
  },
  configSearchInput: {
    backgroundColor: "rgba(255,255,255,0.05)",
    borderWidth: 1,
    borderColor: palette.line,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 10,
    color: palette.text,
    fontFamily: mono,
    fontSize: 13
  },
  configSearchResults: {
    marginTop: 6,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: palette.line,
    overflow: "hidden"
  },
  configSearchRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: palette.lineSoft
  },
  configSearchRowSelected: {
    backgroundColor: "rgba(74,158,218,0.10)"
  },
  configSearchIata: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 14,
    fontWeight: "700",
    width: 36
  },
  configSearchInfo: {
    flex: 1,
    minWidth: 0
  },
  configSearchName: {
    color: palette.text,
    fontSize: 13
  },
  configSearchMeta: {
    color: palette.textMuted,
    fontSize: 11,
    marginTop: 1
  },
  configSelectedAirport: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginTop: 8,
    paddingHorizontal: 10,
    paddingVertical: 7,
    borderRadius: 8,
    backgroundColor: "rgba(0,192,64,0.08)",
    borderWidth: 1,
    borderColor: "rgba(0,192,64,0.18)"
  },
  configSelectedText: {
    flex: 1,
    color: palette.green,
    fontSize: 12,
    fontFamily: mono
  },
  configSegControl: {
    flexDirection: "row",
    borderRadius: 10,
    borderWidth: 1,
    borderColor: palette.line,
    overflow: "hidden"
  },
  configSegOption: {
    flex: 1,
    paddingVertical: 10,
    alignItems: "center",
    backgroundColor: "rgba(255,255,255,0.03)"
  },
  configSegOptionActive: {
    backgroundColor: "rgba(74,158,218,0.16)"
  },
  configSegText: {
    fontFamily: mono,
    fontSize: 11,
    color: palette.textMuted,
    fontWeight: "700",
    letterSpacing: 0.6
  },
  configSegTextActive: {
    color: palette.blue2
  },
  configIntervalGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8
  },
  configIntervalCell: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: palette.line,
    backgroundColor: "rgba(255,255,255,0.03)"
  },
  configIntervalCellActive: {
    borderColor: "rgba(74,158,218,0.40)",
    backgroundColor: "rgba(74,158,218,0.12)"
  },
  configIntervalText: {
    fontFamily: mono,
    fontSize: 12,
    color: palette.textMuted
  },
  configIntervalTextActive: {
    color: palette.blue2,
    fontWeight: "700"
  },
  configProfileList: {
    borderRadius: 10,
    borderWidth: 1,
    borderColor: palette.line,
    overflow: "hidden",
    marginBottom: 10
  },
  configProfileRow: {
    flexDirection: "row",
    alignItems: "center",
    borderBottomWidth: 1,
    borderBottomColor: palette.lineSoft
  },
  configProfileLoad: {
    flex: 1,
    paddingHorizontal: 14,
    paddingVertical: 10
  },
  configProfileName: {
    color: palette.text,
    fontSize: 13,
    fontWeight: "600"
  },
  configProfileMeta: {
    color: palette.textMuted,
    fontSize: 11,
    fontFamily: mono,
    marginTop: 2
  },
  configProfileDelete: {
    padding: 14
  },
  configSaveRow: {
    flexDirection: "row",
    gap: 8,
    alignItems: "center"
  },
  configProfileInput: {
    flex: 1,
    backgroundColor: "rgba(255,255,255,0.05)",
    borderWidth: 1,
    borderColor: palette.line,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 10,
    color: palette.text,
    fontFamily: mono,
    fontSize: 13
  },
  configSaveBtn: {
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 10,
    backgroundColor: "rgba(74,158,218,0.16)",
    borderWidth: 1,
    borderColor: "rgba(74,158,218,0.30)"
  },
  configSaveBtnDisabled: {
    opacity: 0.35
  },
  configSaveBtnText: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 0.6
  },
  configErrorText: {
    color: palette.red,
    fontSize: 12,
    marginTop: 10,
    marginBottom: 4
  },
  configApplyBtn: {
    marginTop: 16,
    paddingVertical: 14,
    borderRadius: 12,
    backgroundColor: palette.blue,
    alignItems: "center",
    justifyContent: "center"
  },
  configApplyBtnBusy: {
    opacity: 0.6
  },
  configApplyBtnText: {
    fontFamily: mono,
    color: palette.bg,
    fontSize: 13,
    fontWeight: "800",
    letterSpacing: 1.2
  }
});

function statusBadgeStyle(tone: StatusTone) {
  switch (tone) {
    case "departed":
      return styles.status_departed;
    case "boarding":
      return styles.status_boarding;
    case "delayed":
      return styles.status_delayed;
    case "cancelled":
      return styles.status_cancelled;
    case "scheduled":
    default:
      return styles.status_scheduled;
  }
}

function statusTextStyle(tone: StatusTone) {
  switch (tone) {
    case "departed":
      return styles.statusText_departed;
    case "boarding":
      return styles.statusText_boarding;
    case "delayed":
      return styles.statusText_delayed;
    case "cancelled":
      return styles.statusText_cancelled;
    case "scheduled":
    default:
      return styles.statusText_scheduled;
  }
}
