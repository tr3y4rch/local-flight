import { useCallback, useEffect, useRef, useState } from "react";
import {
  Animated,
  Pressable,
  RefreshControl,
  ScrollView,
  StatusBar,
  StyleSheet,
  Text,
  View
} from "react-native";
import { useKeepAwake } from "expo-keep-awake";
import * as SplashScreen from "expo-splash-screen";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";

import { BottomNav } from "../components/BottomNav";
import { LaunchOverlay } from "../components/LaunchOverlay";
import { AdminScreen, AirportConfigSheet, CompanionSetupScreen, ConnectPrompt, DocsScreen, FidsScreen, FlightActionSheet, FlightDetailSheet, FullscreenFidsDisplay, Header, HistoryScreen, MatrixScreen, RadarScreen, ScreenActivity, ScreenError, SettingsScreen, SupportSheet, type ActivityStatus, type ConnectionState, type DocSlug } from "../screens/AppScreens";
import {
  getAdminSystem,
  getBudget,
  getConnections,
  getConfig,
  getFids,
  getHealth,
  getHistory,
  getHistorySummary,
  getHistoryStats,
  getMetar,
  getRadar,
  getRadarGround,
  getUpdates,
  normalizeServerUrl,
  patchConfig,
  resolveAirport,
  restartScheduler,
  sendCompanionCheckin,
  submitFeedback,
  testConnection,
  wsUrl
} from "../api/client";
import type {
  AppConfig,
  AirportResolved,
  ConfigPatch,
  DashboardSnapshot,
  FidsRow,
  FlightView,
  HistoryDirection,
  HistoryResponse,
  HistorySummary,
  HistoryStats,
  Metar,
  RadarMapResponse,
  RadarResponse
} from "../api/types";
import { installGlobalCrashReporter, reportMobileCrash } from "../crash/reporter";
import type { CompanionIdentity } from "../device/identity";
import {
  COMPANION_PING_MS,
  EMPTY_SNAPSHOT
} from "../domain/constants";
import { mobileClientContext } from "../domain/feedback";
import { flightPinKey } from "../domain/flights";
import {
  companionSyncMs,
  errorMessage,
  formatLocalTime,
  formatUtc,
  hexToRgba
} from "../domain/formatting";
import type {
  FeedbackTone,
  HistoryWindow,
  RadarRadius,
  RefreshOptions,
  Screen
} from "../domain/types";
import { useFlightDetail } from "../hooks/useFlightDetail";
import { type LaunchHydration, useLaunchOverlay } from "../hooks/useLaunchOverlay";
import { useMatrixCompanion } from "../hooks/useMatrixCompanion";
import {
  type ConfigProfile,
  completeMobileSetupState,
  incompleteMobileSetupState,
  isMobileSetupComplete,
  loadWeatherDisplayMode,
  type MobileDiagnosticsMode,
  type MobileSetupState,
  type MobileWeatherDisplayMode,
  saveMobileDiagnosticsMode,
  saveMobileSetupState,
  savePinnedFlight,
  saveServerUrl,
  saveWeatherDisplayMode
} from "../storage/settings";
import { useMobileTheme } from "../theme/runtime";
import { setStyleBridge } from "../theme/styleBridge";
import {
  DEFAULT_MOBILE_APPEARANCE,
  type MobileAppearance
} from "../theme/tokens";
import { hapticLight, hapticSuccess, hapticWarning } from "../utils/haptics";
import { useResponsiveLayout } from "../utils/layout";

let palette: MobileAppearance = DEFAULT_MOBILE_APPEARANCE;
let brand = DEFAULT_MOBILE_APPEARANCE.brand;
let mono = DEFAULT_MOBILE_APPEARANCE.mono;

void SplashScreen.preventAutoHideAsync().catch(() => {
  // Ignore duplicate registration during fast refresh.
});
SplashScreen.setOptions({
  duration: 320,
  fade: true
});

function refreshActivityForTarget(target: Screen, landscapeFidsActive: boolean): ActivityStatus {
  if (landscapeFidsActive || target === "fids") {
    return {
      label: "Refreshing FIDS",
      detail: "Asking the Local Flight server for the latest board rows."
    };
  }
  if (target === "radar") {
    return {
      label: "Loading radar traffic",
      detail: "Asking the Local Flight server for nearby aircraft and surface data."
    };
  }
  if (target === "history") {
    return {
      label: "Reading history",
      detail: "Asking the Local Flight server for recent local flight records."
    };
  }
  if (target === "matrix") {
    return {
      label: "Syncing Matrix board",
      detail: "Reading the server Matrix runtime and preview rows."
    };
  }
  if (target === "admin") {
    return {
      label: "Checking server status",
      detail: "Refreshing Admin health, budget, update, and connection data."
    };
  }
  return {
    label: "Talking to Local Flight",
    detail: "Checking the connected server over your LAN."
  };
}

export function AppShell() {
  const { appearance, themeMode, skin, setThemeMode, setSkin } = useMobileTheme();
  const layout = useResponsiveLayout();
  const landscapeFidsActive = layout.isLandscape;
  const insets = useSafeAreaInsets();
  const [screen, setScreen] = useState<Screen>("fids");
  const [view, setView] = useState<FlightView>("departures");
  const [historyDirection, setHistoryDirection] = useState<HistoryDirection>("both");
  const [historyHours, setHistoryHours] = useState<HistoryWindow>(24);
  const [historyCallsign, setHistoryCallsign] = useState("");
  const [historyAirline, setHistoryAirline] = useState("");
  const [historySummary, setHistorySummary] = useState<HistorySummary | null>(null);
  const [historyStats, setHistoryStats] = useState<HistoryStats | null>(null);
  const [radarRadius, setRadarRadius] = useState<RadarRadius>(20);
  const [serverUrl, setServerUrl] = useState("");
  const [draftUrl, setDraftUrl] = useState("");
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [activity, setActivity] = useState<ActivityStatus | null>(null);
  const [schedulerRestarting, setSchedulerRestarting] = useState(false);
  const [schedulerMessage, setSchedulerMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [utcTime, setUtcTime] = useState(formatUtc());
  const [localTime, setLocalTime] = useState(formatLocalTime());
  const [snapshot, setSnapshot] = useState<DashboardSnapshot>(EMPTY_SNAPSHOT);
  const [airportDetail, setAirportDetail] = useState<AirportResolved | null>(null);
  const [rows, setRows] = useState<FidsRow[]>([]);
  const [historyData, setHistoryData] = useState<HistoryResponse | null>(null);
  const [radarData, setRadarData] = useState<RadarResponse | null>(null);
  const [radarGroundData, setRadarGroundData] = useState<RadarMapResponse | null>(null);
  const [radarGroundError, setRadarGroundError] = useState<string | null>(null);
  const [feedbackTitle, setFeedbackTitle] = useState("");
  const [feedbackDescription, setFeedbackDescription] = useState("");
  const [feedbackSending, setFeedbackSending] = useState(false);
  const [feedbackMessage, setFeedbackMessage] = useState<string | null>(null);
  const [feedbackTone, setFeedbackTone] = useState<FeedbackTone>("ok");
  const [autoReportMessage, setAutoReportMessage] = useState<string | null>(null);
  const [pinnedCallsign, setPinnedCallsign] = useState("");
  const [docsSlug, setDocsSlug] = useState<DocSlug>("readme");
  const [actionRow, setActionRow] = useState<FidsRow | null>(null);
  const [configSheetVisible, setConfigSheetVisible] = useState(false);
  const [profiles, setProfiles] = useState<ConfigProfile[]>([]);
  const [applyingProfileId, setApplyingProfileId] = useState<string | null>(null);
  const [supportVisible, setSupportVisible] = useState(false);
  const [companionIdentity, setCompanionIdentity] = useState<CompanionIdentity | null>(null);
  const [mobileDiagnosticsMode, setMobileDiagnosticsMode] = useState<MobileDiagnosticsMode>("unset");
  const [weatherDisplayMode, setWeatherDisplayMode] = useState<MobileWeatherDisplayMode>("passenger");
  const [mobileSetupState, setMobileSetupState] = useState<MobileSetupState>(() => incompleteMobileSetupState());
  const [launchHydrated, setLaunchHydrated] = useState(false);

  const socketRef = useRef<WebSocket | null>(null);
  const radarGroundCacheRef = useRef<Map<string, RadarMapResponse>>(new Map());
  const screenOpacity = useRef(new Animated.Value(1)).current;
  const screenLift = useRef(new Animated.Value(0)).current;
  const snapshotPulse = useRef(new Animated.Value(0)).current;
  const flightDetail = useFlightDetail(serverUrl, setError);
  const matrix = useMatrixCompanion(serverUrl);
  const {
    rows: matrixRows,
    runtime: matrixRuntime,
    preset: matrixPreset,
    dirty: matrixDirty,
    saving: matrixSaving,
    applyingPreset: matrixApplyingPreset,
    saveMessage: matrixSaveMessage,
    saveTone: matrixSaveTone,
    fetchRows: fetchMatrixRows,
    fetchRuntime: fetchMatrixRuntime,
    updateDraft: updateMatrixDraft,
    resetDraft: resetMatrixDraft,
    saveDraft: saveMatrixDraftNow,
    applyPreset: applyMatrixPreset
  } = matrix;
  const {
    visible: detailVisible,
    loading: detailLoading,
    callsign: detailCallsign,
    detail,
    history: detailHistory,
    open: openFlightDetail,
    close: closeFlightDetail,
    refresh: refreshFlightDetail
  } = flightDetail;

  useEffect(() => {
    installGlobalCrashReporter();
  }, []);

  if (palette.key !== appearance.key) {
    palette = appearance;
    brand = appearance.brand;
    mono = appearance.mono;
    styles = createStyles();
    setStyleBridge(styles, palette);
  }

  const currentAirportDetail =
    airportDetail &&
    (
      (airportDetail.iata && airportDetail.iata === (snapshot.config?.airport_iata || "")) ||
      (airportDetail.icao && airportDetail.icao === (snapshot.config?.airport_icao || ""))
    )
      ? airportDetail
      : null;
  const airportTimeZone = currentAirportDetail?.timezone || snapshot.config?.timezone || undefined;

  useEffect(() => {
    const updateClock = () => {
      setUtcTime(formatUtc());
      setLocalTime(formatLocalTime(airportTimeZone));
    };
    updateClock();
    const timer = setInterval(updateClock, 1000);
    return () => clearInterval(timer);
  }, [airportTimeZone]);

  useEffect(() => {
    screenOpacity.setValue(0);
    screenLift.setValue(10);
    Animated.parallel([
      Animated.timing(screenOpacity, {
        toValue: 1,
        duration: 180,
        useNativeDriver: true
      }),
      Animated.spring(screenLift, {
        toValue: 0,
        damping: 15,
        stiffness: 240,
        mass: 0.7,
        useNativeDriver: true
      })
    ]).start();
  }, [screen, docsSlug, screenLift, screenOpacity]);

  const onLaunchHydrated = useCallback(
    ({ savedUrl, savedPin, savedProfiles, identity, mobileDiagnosticsMode: hydratedDiagnosticsMode, setupState }: LaunchHydration) => {
      const effectiveSavedUrl = savedUrl || setupState.serverUrl;
      if (effectiveSavedUrl) {
        setServerUrl(effectiveSavedUrl);
        setDraftUrl(effectiveSavedUrl);
      }
      if (savedPin) {
        setPinnedCallsign(savedPin);
      }
      if (savedProfiles.length) {
        setProfiles(savedProfiles);
      }
      setCompanionIdentity(identity);
      setMobileDiagnosticsMode(hydratedDiagnosticsMode);
      setMobileSetupState(setupState);
      setLaunchHydrated(true);
    },
    []
  );
  const launch = useLaunchOverlay(onLaunchHydrated);
  const mobileSetupComplete = launchHydrated && isMobileSetupComplete(mobileSetupState, serverUrl, mobileDiagnosticsMode);

  const chooseMobileDiagnosticsMode = useCallback(async (mode: MobileDiagnosticsMode) => {
    await saveMobileDiagnosticsMode(mode);
    setMobileDiagnosticsMode(mode);
    if (serverUrl && mode !== "unset") {
      const nextSetupState = completeMobileSetupState(serverUrl, mode);
      await saveMobileSetupState(nextSetupState);
      setMobileSetupState(nextSetupState);
    }
  }, [serverUrl]);

  useEffect(() => {
    let alive = true;
    void loadWeatherDisplayMode().then((mode) => {
      if (alive) {
        setWeatherDisplayMode(mode);
      }
    });
    return () => {
      alive = false;
    };
  }, []);

  const chooseWeatherDisplayMode = useCallback(async (mode: MobileWeatherDisplayMode) => {
    await saveWeatherDisplayMode(mode);
    setWeatherDisplayMode(mode);
  }, []);

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

    let histStats: HistoryStats | null = null;
    try {
      histStats = await getHistoryStats(normalized);
    } catch {
      histStats = null;
    }

    let resolvedAirport: AirportResolved | null = null;
    const airportQueries = Array.from(new Set([config.airport_iata, config.airport_icao].filter(Boolean)));
    for (const airportQuery of airportQueries) {
      try {
        resolvedAirport = await resolveAirport(normalized, airportQuery);
        break;
      } catch {
        resolvedAirport = null;
      }
    }

    setAirportDetail(resolvedAirport);
    setHistoryStats(histStats);
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
      nextHours: HistoryWindow,
      nextCallsign = "",
      nextAirline = ""
    ) => {
      const [data, summary] = await Promise.all([
        getHistory(normalized, {
          direction: nextDirection,
          hours: nextHours,
          limit: 120,
          callsign: nextCallsign,
          airline_iata: nextAirline
        }),
        getHistorySummary(normalized, {
          hours: nextHours,
          direction: nextDirection,
          callsign: nextCallsign,
          airline_iata: nextAirline
        }).catch(() => null)
      ]);
      setHistoryData(data);
      setHistorySummary(summary);
    },
    []
  );

  const fetchRadarData = useCallback(async (
    normalized: string,
    nextRadius: RadarRadius,
    forceGround = false
  ) => {
    setActivity({
      label: "Loading radar traffic",
      detail: `Asking the Local Flight server for tracks inside ${nextRadius} NM.`
    });
    const data = await getRadar(normalized, nextRadius);
    setRadarData(data);

    const cacheKey = [
      normalized,
      nextRadius,
      Number(data.center?.lat || 0).toFixed(5),
      Number(data.center?.lon || 0).toFixed(5)
    ].join("|");
    const cachedGround = radarGroundCacheRef.current.get(cacheKey) || null;
    if (cachedGround && !forceGround) {
      setRadarGroundData(cachedGround);
      setRadarGroundError(null);
      return;
    }

    try {
      setActivity({
        label: "Loading airport ground layer",
        detail: "Fetching runway and surface geometry through the Local Flight server."
      });
      const ground = await getRadarGround(normalized, nextRadius);
      radarGroundCacheRef.current.set(cacheKey, ground);
      setRadarGroundData(ground);
      setRadarGroundError(null);
    } catch (exc) {
      setRadarGroundData(cachedGround);
      setRadarGroundError(cachedGround ? null : errorMessage(exc));
    }
  }, []);

  const refreshScreen = useCallback(
    async ({
      nextUrl = serverUrl,
      target = screen,
      nextView = view,
      nextHistoryDirection = historyDirection,
      nextHistoryHours = historyHours,
      nextRadarRadius = radarRadius,
      forceRadarGround = false
    }: RefreshOptions = {}) => {
      const normalized = normalizeServerUrl(nextUrl);
      if (!normalized) {
        setError("Enter the Local Flight server URL in Settings.");
        return;
      }

      setRefreshing(true);
      setActivity({
        label: "Talking to Local Flight",
        detail: "Checking server health, config, budget, and live connections."
      });
      setError(null);

      try {
        await fetchDashboard(normalized);
      } catch (exc) {
        setConnected(false);
        setError(errorMessage(exc));
        setRefreshing(false);
        setActivity(null);
        return;
      }

      try {
        setActivity(refreshActivityForTarget(target, landscapeFidsActive));
        if (landscapeFidsActive) {
          await fetchFidsData(normalized, nextView);
        } else if (target === "fids") {
          await fetchFidsData(normalized, nextView);
        } else if (target === "history") {
          await fetchHistoryData(normalized, nextHistoryDirection, nextHistoryHours, historyCallsign, historyAirline);
        } else if (target === "radar") {
          await fetchRadarData(normalized, nextRadarRadius, forceRadarGround);
        } else if (target === "matrix") {
          await Promise.all([
            fetchMatrixRows(normalized, matrixRuntime.default_view, matrixRuntime.max_rows),
            fetchMatrixRuntime(normalized)
          ]);
        }
      } catch (exc) {
        setError(errorMessage(exc));
      } finally {
        setRefreshing(false);
        setActivity(null);
      }
    },
    [
      fetchDashboard,
      fetchFidsData,
      fetchHistoryData,
      fetchMatrixRows,
      fetchMatrixRuntime,
      fetchRadarData,
      historyAirline,
      historyCallsign,
      historyDirection,
      historyHours,
      landscapeFidsActive,
      matrixRuntime.default_view,
      matrixRuntime.max_rows,
      radarRadius,
      screen,
      serverUrl,
      view
    ]
  );

  const connect = useCallback(async () => {
    const normalized = normalizeServerUrl(draftUrl);
    setLoading(true);
    setActivity({
      label: "Testing server URL",
      detail: "Asking the Local Flight server to confirm companion access."
    });
    setError(null);

    try {
      await testConnection(normalized);
      await saveServerUrl(normalized);
      if (mobileDiagnosticsMode !== "unset") {
        const nextSetupState = completeMobileSetupState(normalized, mobileDiagnosticsMode);
        await saveMobileSetupState(nextSetupState);
        setMobileSetupState(nextSetupState);
      }
      setServerUrl(normalized);
      setDraftUrl(normalized);
      setScreen("fids");
      hapticSuccess();
    } catch (exc) {
      setConnected(false);
      setError(errorMessage(exc));
      hapticWarning();
    } finally {
      setLoading(false);
      setActivity(null);
    }
  }, [draftUrl, mobileDiagnosticsMode]);

  const completeCompanionSetup = useCallback(async ({
    serverUrl: nextServerUrl,
    diagnosticsMode,
    config
  }: {
    serverUrl: string;
    diagnosticsMode: MobileDiagnosticsMode;
    config: AppConfig;
  }) => {
    const normalized = normalizeServerUrl(nextServerUrl);
    const nextSetupState = completeMobileSetupState(normalized, diagnosticsMode);
    await Promise.all([
      saveServerUrl(normalized),
      saveMobileDiagnosticsMode(diagnosticsMode),
      saveMobileSetupState(nextSetupState)
    ]);
    setServerUrl(normalized);
    setDraftUrl(normalized);
    setMobileDiagnosticsMode(diagnosticsMode);
    setMobileSetupState(nextSetupState);
    setSnapshot((prev) => ({ ...prev, config }));
    setConnected(true);
    setError(null);
    setScreen("fids");
    hapticSuccess();
    void refreshScreen({ nextUrl: normalized, target: "fids" });
  }, [refreshScreen]);

  const rerunCompanionSetup = useCallback(async () => {
    const nextSetupState = incompleteMobileSetupState(serverUrl, mobileDiagnosticsMode);
    await saveMobileSetupState(nextSetupState);
    setMobileSetupState(nextSetupState);
    setActionRow(null);
    setConfigSheetVisible(false);
    closeFlightDetail();
    setError(null);
  }, [closeFlightDetail, mobileDiagnosticsMode, serverUrl]);

  const restartSchedulerNow = useCallback(async () => {
    const normalized = normalizeServerUrl(serverUrl);
    if (!normalized) {
      setSchedulerMessage("Set the Local Flight server URL first.");
      return;
    }

    setSchedulerRestarting(true);
    setSchedulerMessage("Restarting scheduler...");
    setActivity({
      label: "Restarting server fetch",
      detail: "Asking the Local Flight server scheduler for a fresh cycle."
    });
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
      setActivity(null);
    }
  }, [refreshScreen, screen, serverUrl]);

  const applySettingsProfile = useCallback(async (profile: ConfigProfile) => {
    const normalized = normalizeServerUrl(serverUrl);
    if (!normalized) {
      setError("Set the Local Flight server URL first.");
      return;
    }

    const patch: ConfigPatch = {
      airport_iata: profile.iata,
      airport_icao: profile.icao,
      timezone: profile.timezone,
      source: profile.source,
      refresh_seconds: profile.refresh_seconds
    };

    setApplyingProfileId(profile.id);
    setActivity({
      label: `Switching to ${profile.name}`,
      detail: "Saving the profile on the Local Flight server and requesting a fresh fetch."
    });
    setError(null);

    try {
      const newConfig = await patchConfig(normalized, patch);
      setSnapshot((prev) => ({ ...prev, config: newConfig }));
      setSchedulerMessage(`Profile "${profile.name}" saved. Asking the Pi for a fresh fetch...`);
      hapticSuccess();
      await restartSchedulerNow();
    } catch (exc) {
      setError(errorMessage(exc));
      hapticWarning();
    } finally {
      setApplyingProfileId(null);
      setActivity(null);
    }
  }, [restartSchedulerNow, serverUrl]);

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
    const sent = await reportMobileCrash({
      message: "Intentional mobile auto-report test",
      traceback: "Triggered from the Admin screen to verify Linear crash wiring.",
      context: "mobile/manual-auto-test",
      client_context: mobileClientContext(serverUrl, snapshot, companionIdentity)
    });
    setAutoReportMessage(
      sent
        ? "Auto-report test sent with the crash route."
        : "Automatic diagnostics are disabled on the connected Local Flight server."
    );
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

  const openDoc = useCallback((slug: DocSlug) => {
    setDocsSlug(slug);
    setScreen("docs");
  }, []);

  const openFlightDetailWithHaptic = useCallback((callsign: string) => {
    hapticLight();
    openFlightDetail(callsign);
  }, [openFlightDetail]);

  const triggerSnapshotPulse = useCallback(() => {
    snapshotPulse.stopAnimation();
    snapshotPulse.setValue(0);
    Animated.sequence([
      Animated.timing(snapshotPulse, { toValue: 1, duration: 120, useNativeDriver: true }),
      Animated.timing(snapshotPulse, { toValue: 0, duration: 260, useNativeDriver: true })
    ]).start();
  }, [snapshotPulse]);

  useEffect(() => {
    if (!landscapeFidsActive) return;

    setActionRow(null);
    setConfigSheetVisible(false);
    closeFlightDetail();

    if (serverUrl) {
      void refreshScreen({ target: "fids" });
    }
  }, [closeFlightDetail, landscapeFidsActive, refreshScreen, serverUrl]);

  useEffect(() => {
    if (!serverUrl) return;
    void refreshScreen({ target: screen });
  }, [historyDirection, historyHours, radarRadius, refreshScreen, screen, serverUrl, view]);

  useEffect(() => {
    if (!serverUrl || screen !== "matrix") return;
    const normalized = normalizeServerUrl(serverUrl);
    if (!normalized) return;
    void fetchMatrixRows(normalized, matrixRuntime.default_view, matrixRuntime.max_rows).catch((exc) => {
      setError(errorMessage(exc));
    });
  }, [fetchMatrixRows, matrixRuntime.default_view, matrixRuntime.max_rows, screen, serverUrl]);

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
          triggerSnapshotPulse();
          void refreshScreen({ target: screen });
          if (detailVisible && detailCallsign) {
            refreshFlightDetail();
          }
        } else if (message.type === "config_updated") {
          if (message.config) {
            setSnapshot((prev) => ({ ...prev, config: message.config || prev.config }));
          }
          radarGroundCacheRef.current.clear();
          setRadarGroundData(null);
          setRadarGroundError(null);
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
  }, [connected, detailCallsign, detailVisible, refreshFlightDetail, refreshScreen, screen, serverUrl, triggerSnapshotPulse]);

  const cfg = snapshot.config;
  const state = snapshot.state;
  const activeProfileId =
    profiles.find((profile) =>
      profile.iata === cfg?.airport_iata &&
      profile.icao === cfg?.airport_icao &&
      profile.timezone === cfg?.timezone &&
      profile.source === cfg?.source &&
      profile.refresh_seconds === cfg?.refresh_seconds
    )?.id || null;
  const airportCode = cfg?.airport_iata || "---";
  const airportIcao = cfg?.airport_icao || "";
  const fallbackDisplayName =
    cfg?.display_name && cfg.display_name !== "Local Flight"
      ? cfg.display_name
      : cfg?.airport_icao
        ? `${cfg.airport_icao} Local Flight`
        : "Connect your server";
  const airportName = currentAirportDetail?.name || fallbackDisplayName;
  const airportLocation = [currentAirportDetail?.city, currentAirportDetail?.country].filter(Boolean).join(" · ");
  const sourceLabel = state?.source_name || cfg?.source || "VATSIM";
  const isLive = connected && state?.ok !== false;
  const connectionState: ConnectionState = error
    ? refreshing ? "retrying" : "offline"
    : isLive ? "live" : "offline";
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
  const pinnedRow = pinnedCallsign
    ? rows.find((row) => flightPinKey(row) === pinnedCallsign) || null
    : null;
  const islandRow =
    pinnedRow || rows.find((row) => /board|gate|approach/i.test(row.status_display)) || rows[0] || null;
  const screenContentPadding = Math.max(20, insets.bottom + 14);
  const matrixPreviewView = matrixRuntime.default_view;
  const matrixPreviewRows = matrixRuntime.max_rows;
  const matrixBrightness = matrixRuntime.brightness;
  const matrixPalette = matrixRuntime.palette;
  const matrixShowWeather = Boolean(matrixRuntime.options.show_metar ?? matrixRuntime.options.show_weather);
  const statusBarStyle = themeMode === "light" ? "dark-content" : "light-content";

  if (!mobileSetupComplete) {
    return (
      <SafeAreaView style={styles.setupSafe} edges={["top", "bottom", "left", "right"]}>
        <StatusBar barStyle={statusBarStyle} hidden={false} />
        {launchHydrated ? (
          <CompanionSetupScreen
            initialUrl={draftUrl || serverUrl}
            initialDiagnosticsMode={mobileDiagnosticsMode}
            onComplete={completeCompanionSetup}
          />
        ) : null}
        <LaunchOverlay
          visible={launch.visible}
          opacity={launch.opacity}
          shift={launch.shift}
          scale={launch.scale}
          progress={launch.progress}
          pulse={launch.pulse}
          status={launch.status}
          styles={styles}
        />
      </SafeAreaView>
    );
  }

  if (landscapeFidsActive) {
    return (
      <LandscapeFidsMode
        rows={rows}
        view={view}
        loading={refreshing}
        error={error}
        live={isLive}
        airportCode={airportCode}
        airportName={airportName}
        sourceLabel={sourceLabel}
        utcTime={utcTime}
        localTime={localTime}
        metar={snapshot.metar}
        weatherDisplayMode={weatherDisplayMode}
        pinnedCallsign={pinnedCallsign}
      />
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top", "left", "right"]}>
      <StatusBar barStyle={statusBarStyle} hidden={false} />
      <View style={[styles.appFrame, { maxWidth: contentWidth }]}>
        <Header
          airportCode={airportCode}
          airportIcao={airportIcao}
          airportName={airportName}
          airportLocation={airportLocation}
          live={isLive}
          error={error}
          connectionState={connectionState}
          sourceLabel={sourceLabel}
          utcTime={utcTime}
          localTime={localTime}
          metar={snapshot.metar}
          weatherDisplayMode={weatherDisplayMode}
          snapshotPulse={snapshotPulse}
          rowCount={rows.length}
          view={view}
          pinnedRow={islandRow}
          islandPinned={Boolean(islandRow && flightPinKey(islandRow) === pinnedCallsign)}
          onOpenDetail={openFlightDetail}
          onOpenActions={setActionRow}
          onTogglePin={togglePinnedFlight}
          onOpenConfig={() => setConfigSheetVisible(true)}
          onOpenWeather={() => setScreen("admin")}
        />

        <Animated.View
          style={[
            styles.mainArea,
            {
              opacity: screenOpacity,
              transform: [{ translateY: screenLift }]
            }
          ]}
        >
          {screen === "fids" ? (
            <FidsScreen
              rows={rows}
              view={view}
              loading={refreshing}
              refreshing={refreshing}
              activity={activity}
              error={error}
              showConnectPrompt={!serverUrl}
              onOpenSettings={() => setScreen("settings")}
              onRefresh={() => { hapticLight(); refreshScreen({ target: "fids" }); }}
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
              summary={historySummary}
              direction={historyDirection}
              hours={historyHours}
              callsign={historyCallsign}
              airline={historyAirline}
              loading={refreshing}
              refreshing={refreshing}
              activity={activity}
              error={error}
              showConnectPrompt={!serverUrl}
              onOpenSettings={() => setScreen("settings")}
              onRefresh={() => { hapticLight(); refreshScreen({ target: "history" }); }}
              onDirectionChange={setHistoryDirection}
              onHoursChange={setHistoryHours}
              onCallsignChange={setHistoryCallsign}
              onAirlineChange={setHistoryAirline}
              onApplyFilters={() => refreshScreen({ target: "history" })}
              onOpenDetail={openFlightDetail}
              contentPaddingBottom={screenContentPadding}
            />
          ) : null}

          {screen === "radar" ? (
            <RadarScreen
              data={radarData}
              groundData={radarGroundData}
              groundError={radarGroundError}
              metar={snapshot.metar}
              weatherDisplayMode={weatherDisplayMode}
              radiusNm={radarRadius}
              loading={refreshing}
              refreshing={refreshing}
              activity={activity}
              error={error}
              showConnectPrompt={!serverUrl}
              onOpenSettings={() => setScreen("settings")}
              onRefresh={() => { hapticLight(); refreshScreen({ target: "radar", forceRadarGround: true }); }}
              onRadiusChange={setRadarRadius}
              onOpenDetail={openFlightDetail}
              compact={false}
              contentPaddingBottom={screenContentPadding}
            />
          ) : null}

          {screen === "matrix" ? (
            <MatrixScreen
              rows={matrixRows}
              view={matrixPreviewView}
              brightness={matrixBrightness}
              maxRows={matrixPreviewRows}
              refreshSeconds={matrixRuntime.refresh_seconds}
              pageRotationSeconds={matrixRuntime.page_rotation_seconds}
              animationMode={matrixRuntime.animation_mode}
              animationSpeed={matrixRuntime.animation_speed}
              statusAnimationEnabled={matrixRuntime.status_animation_enabled}
              showWeather={matrixShowWeather}
              matrixPalette={matrixPalette}
              preset={matrixPreset}
              applyingPreset={matrixApplyingPreset}
              matrixEnabled={snapshot.config?.display_outputs?.includes("matrix") || false}
              matrixLastSeen={snapshot.connections?.matrix_last_seen || null}
              dirty={matrixDirty}
              saving={matrixSaving}
              saveMessage={matrixSaveMessage}
              saveTone={matrixSaveTone}
              refreshing={refreshing}
              activity={activity}
              error={error}
              showConnectPrompt={!serverUrl}
              onOpenSettings={() => setScreen("settings")}
              onRefresh={() => refreshScreen({ target: "matrix" })}
              onViewChange={(value) => updateMatrixDraft({ default_view: value })}
              onBrightnessChange={(value) => updateMatrixDraft({ brightness: value })}
              onRowsChange={(value) => updateMatrixDraft({ max_rows: value })}
              onRefreshSecondsChange={(value) => updateMatrixDraft({ refresh_seconds: value })}
              onPageRotationChange={(value) => updateMatrixDraft({ page_rotation_seconds: value })}
              onAnimationModeChange={(value) => updateMatrixDraft({
                animation_mode: value,
                animation_enabled: value !== "static",
                options: { ...matrixRuntime.options, animation_mode: value }
              })}
              onAnimationSpeedChange={(value) => updateMatrixDraft({ animation_speed: value })}
              onStatusAnimationChange={(value) => updateMatrixDraft({ status_animation_enabled: value })}
              onShowWeatherChange={(value) => updateMatrixDraft({
                options: { ...matrixRuntime.options, show_metar: value, show_weather: value }
              })}
              onMatrixPaletteChange={(value) => updateMatrixDraft({
                palette: value,
                options: { ...matrixRuntime.options, palette: value }
              })}
              onApplyPreset={applyMatrixPreset}
              onSave={saveMatrixDraftNow}
              onReset={resetMatrixDraft}
              onBackSettings={() => setScreen("settings")}
              contentPaddingBottom={screenContentPadding}
            />
          ) : null}

          {screen === "docs" ? (
            <DocsScreen
              slug={docsSlug}
              serverUrl={serverUrl}
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

              <ScreenActivity activity={activity} />

              {error ? (
                <ScreenError
                  message={error}
                  retrying={refreshing}
                  onRetry={() => { hapticLight(); refreshScreen({ target: screen }); }}
                />
              ) : null}

              {screen === "admin" ? (
                <AdminScreen
                  snapshot={snapshot}
                  historyStats={historyStats}
                  companionIdentity={companionIdentity}
                  connected={isLive}
                  error={error}
                  weatherDisplayMode={weatherDisplayMode}
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
                  onOpenMatrix={() => setScreen("matrix")}
                  onOpenSupport={() => setSupportVisible(true)}
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
                  themeMode={themeMode}
                  skin={skin}
                  weatherDisplayMode={weatherDisplayMode}
                  mobileDiagnosticsMode={mobileDiagnosticsMode}
                  profiles={profiles}
                  activeProfileId={activeProfileId}
                  applyingProfileId={applyingProfileId}
                  outputs={snapshot.config?.display_outputs || []}
                  refreshSeconds={snapshot.config?.refresh_seconds ?? null}
                  schedulerRestarting={schedulerRestarting}
                  schedulerMessage={schedulerMessage}
                  onThemeModeChange={setThemeMode}
                  onSkinChange={setSkin}
                  onWeatherDisplayModeChange={chooseWeatherDisplayMode}
                  onMobileDiagnosticsModeChange={chooseMobileDiagnosticsMode}
                  onApplyProfile={(profile) => void applySettingsProfile(profile)}
                  onOpenHistory={() => setScreen("history")}
                  onOpenAdmin={() => setScreen("admin")}
                  onOpenMatrix={() => setScreen("matrix")}
                  onOpenDoc={openDoc}
                  onOpenSupport={() => setSupportVisible(true)}
                  onRestartScheduler={restartSchedulerNow}
                  onRerunSetup={rerunCompanionSetup}
                  onChangeUrl={setDraftUrl}
                  onConnect={connect}
                />
              ) : null}
            </ScrollView>
          ) : null}
        </Animated.View>

        <BottomNav
          active={screen}
          onChange={setScreen}
          insetBottom={insets.bottom}
          palette={palette}
          styles={styles}
        />
      </View>

      <SupportSheet
        visible={supportVisible}
        onClose={() => setSupportVisible(false)}
      />

      <FlightDetailSheet
        visible={detailVisible}
        callsign={detailCallsign}
        detail={detail}
        history={detailHistory}
        loading={detailLoading}
        onClose={closeFlightDetail}
        onRefresh={refreshFlightDetail}
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
          setSchedulerMessage("Server config saved. Asking the Pi for a fresh fetch...");
          void restartSchedulerNow();
        }}
        onProfilesChange={setProfiles}
      />

      <LaunchOverlay
        visible={launch.visible}
        opacity={launch.opacity}
        shift={launch.shift}
        scale={launch.scale}
        progress={launch.progress}
        pulse={launch.pulse}
        status={launch.status}
        styles={styles}
      />
    </SafeAreaView>
  );
}

function LandscapeFidsMode({
  rows,
  view,
  loading,
  error,
  live,
  airportCode,
  airportName,
  sourceLabel,
  utcTime,
  localTime,
  metar,
  weatherDisplayMode,
  pinnedCallsign
}: {
  rows: FidsRow[];
  view: FlightView;
  loading: boolean;
  error: string | null;
  live: boolean;
  airportCode: string;
  airportName: string;
  sourceLabel: string;
  utcTime: string;
  localTime: string;
  metar: Metar | null;
  weatherDisplayMode: MobileWeatherDisplayMode;
  pinnedCallsign: string;
}) {
  useKeepAwake("localflight-landscape-fids", { suppressDeactivateWarnings: true });
  const landscapeOpacity = useRef(new Animated.Value(0)).current;
  const landscapeScale = useRef(new Animated.Value(0.985)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.timing(landscapeOpacity, { toValue: 1, duration: 180, useNativeDriver: true }),
      Animated.spring(landscapeScale, {
        toValue: 1,
        damping: 18,
        stiffness: 180,
        mass: 0.7,
        useNativeDriver: true
      })
    ]).start();
  }, [landscapeOpacity, landscapeScale]);

  return (
    <SafeAreaView style={styles.landscapeSafe} edges={["left", "right"]}>
      <StatusBar hidden />
      <Animated.View
        style={[
          styles.landscapeFidsTransition,
          {
            opacity: landscapeOpacity,
            transform: [{ scale: landscapeScale }]
          }
        ]}
      >
        <FullscreenFidsDisplay
          rows={rows}
          view={view}
          loading={loading}
          error={error}
          live={live}
          airportCode={airportCode}
          airportName={airportName}
          sourceLabel={sourceLabel}
          utcTime={utcTime}
          localTime={localTime}
          metar={metar}
          weatherDisplayMode={weatherDisplayMode}
          pinnedCallsign={pinnedCallsign}
        />
      </Animated.View>
    </SafeAreaView>
  );
}

function createStyles() {
  const accent06 = hexToRgba(palette.blue, 0.06);
  const accent08 = hexToRgba(palette.blue, 0.08);
  const accent10 = hexToRgba(palette.blue, 0.10);
  const accent12 = hexToRgba(palette.blue, 0.12);
  const accent14 = hexToRgba(palette.blue, 0.14);
  const accent15 = hexToRgba(palette.blue, 0.15);
  const accent16 = hexToRgba(palette.blue, 0.16);
  const accent18 = hexToRgba(palette.blue, 0.18);
  const accent20 = hexToRgba(palette.blue, 0.20);
  const accent25 = hexToRgba(palette.blue, 0.25);
  const accent30 = hexToRgba(palette.blue, 0.30);
  const accent40 = hexToRgba(palette.blue, 0.40);
  const accent42 = hexToRgba(palette.blue, 0.42);
  const success08 = hexToRgba(palette.green, 0.08);
  const success10 = hexToRgba(palette.green, 0.10);
  const success12 = hexToRgba(palette.green, 0.12);
  const success18 = hexToRgba(palette.green, 0.18);
  const success25 = hexToRgba(palette.green, 0.25);
  const warn07 = hexToRgba(palette.amber, 0.07);
  const warn08 = hexToRgba(palette.amber, 0.08);
  const warn11 = hexToRgba(palette.amber, 0.11);
  const warn18 = hexToRgba(palette.amber, 0.18);
  const warn22 = hexToRgba(palette.amber, 0.22);
  const warn24 = hexToRgba(palette.amber, 0.24);
  const warn38 = hexToRgba(palette.amber, 0.38);
  const error08 = hexToRgba(palette.red, 0.08);
  const error10 = hexToRgba(palette.red, 0.10);
  const error12 = hexToRgba(palette.red, 0.12);
  const error18 = hexToRgba(palette.red, 0.18);
  const error25 = hexToRgba(palette.red, 0.25);
  const lightMode = palette.themeMode === "light";
  const hairline = lightMode ? palette.lineSoft : "rgba(255,255,255,0.08)";
  const hairlineSoft = lightMode ? hexToRgba(palette.line, 0.42) : "rgba(255,255,255,0.05)";
  const softPanel = lightMode ? palette.row : "rgba(255,255,255,0.03)";
  const softPanelStrong = lightMode ? palette.rowAlt : "rgba(255,255,255,0.045)";
  const fieldPanel = lightMode ? palette.rowAlt : "rgba(0,0,0,0.18)";
  const scopePanel = lightMode ? palette.rowAlt : "rgba(9,15,23,0.88)";
  const scopeField = lightMode ? palette.shell : "rgba(0,0,0,0.18)";
  const modalPanel = palette.shell;
  const handleColor = lightMode ? hexToRgba(palette.line, 0.5) : "rgba(255,255,255,0.18)";
  const onGreenText = lightMode && palette.skin === "high_contrast" ? "#ffffff" : "#051009";
  const onBlueText = lightMode && ["standard", "technical", "high_contrast"].includes(palette.skin) ? "#ffffff" : "#051009";
  return StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: palette.bg,
    alignItems: "center"
  },
  landscapeSafe: {
    flex: 1,
    backgroundColor: palette.bg
  },
  landscapeFidsTransition: {
    flex: 1
  },
  setupSafe: {
    flex: 1,
    backgroundColor: palette.bg
  },
  companionSetupScroll: {
    flex: 1,
    backgroundColor: palette.bg
  },
  companionSetupContent: {
    flexGrow: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 18,
    paddingTop: 18,
    paddingBottom: 24,
    overflow: "hidden"
  },
  companionSetupGlowA: {
    position: "absolute",
    top: -120,
    right: -120,
    width: 310,
    height: 310,
    borderRadius: 999,
    backgroundColor: accent12
  },
  companionSetupGlowB: {
    position: "absolute",
    bottom: -150,
    left: -110,
    width: 340,
    height: 340,
    borderRadius: 999,
    backgroundColor: success08
  },
  companionSetupShell: {
    width: "100%",
    maxWidth: 760,
    gap: 16
  },
  companionSetupHero: {
    alignItems: "center",
    paddingHorizontal: 18,
    paddingTop: 18,
    paddingBottom: 16,
    borderRadius: 28,
    borderWidth: 1,
    borderColor: accent16,
    backgroundColor: softPanelStrong,
    shadowColor: "#000",
    shadowOpacity: 0.18,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 14 }
  },
  companionSetupLogoWrap: {
    width: 116,
    height: 116,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 14
  },
  companionSetupLogoRing: {
    position: "absolute",
    width: 108,
    height: 108,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: accent30
  },
  companionSetupLogoRingOuter: {
    position: "absolute",
    width: 132,
    height: 132,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: hairline,
    borderTopColor: success25,
    borderRightColor: warn24
  },
  companionSetupLogoMark: {
    width: 86,
    height: 86
  },
  companionSetupEyebrow: {
    color: palette.blue2,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 2.4,
    textAlign: "center"
  },
  companionSetupTitle: {
    marginTop: 8,
    fontFamily: mono,
    color: palette.text,
    fontSize: 30,
    fontWeight: "800",
    letterSpacing: 1.2,
    textAlign: "center"
  },
  companionSetupBody: {
    marginTop: 10,
    color: palette.textMuted,
    fontSize: 13,
    lineHeight: 20,
    textAlign: "center"
  },
  companionSetupRoute: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "center",
    gap: 10,
    marginTop: 20,
    width: "100%"
  },
  companionSetupRouteItem: {
    flex: 1,
    alignItems: "center",
    gap: 6
  },
  companionSetupStepDot: {
    width: 28,
    height: 28,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: hairline,
    backgroundColor: softPanelStrong
  },
  companionSetupStepDotActive: {
    borderColor: success25,
    backgroundColor: success12
  },
  companionSetupStepNumber: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 10,
    fontWeight: "900",
    textAlign: "center",
    includeFontPadding: false
  },
  companionSetupStepNumberActive: {
    color: palette.green
  },
  companionSetupStepLabel: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 8,
    fontWeight: "800",
    letterSpacing: 0.8,
    textAlign: "center",
    textTransform: "uppercase",
    includeFontPadding: false
  },
  companionSetupStepLabelActive: {
    color: palette.text
  },
  companionSetupPanel: {
    gap: 12,
    padding: 18,
    borderRadius: 24,
    borderWidth: 1,
    borderColor: accent16,
    backgroundColor: palette.rowAlt
  },
  companionSetupPanelTitle: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 18,
    fontWeight: "800",
    letterSpacing: 0.9,
    textAlign: "center"
  },
  companionSetupChecklist: {
    gap: 8,
    marginTop: 4
  },
  companionSetupChecklistItem: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    padding: 12,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: accent14,
    backgroundColor: accent06
  },
  companionSetupChecklistIcon: {
    width: 34,
    height: 34,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: accent10
  },
  companionSetupChecklistCopy: {
    flex: 1,
    minWidth: 0
  },
  companionSetupChecklistTitle: {
    color: palette.text,
    fontSize: 13,
    fontWeight: "800"
  },
  companionSetupChecklistBody: {
    marginTop: 2,
    color: palette.textMuted,
    fontSize: 11,
    lineHeight: 16
  },
  companionSetupInfoGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginTop: 6
  },
  companionSetupInfoTile: {
    width: "48%",
    minHeight: 68,
    padding: 12,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: accent14,
    backgroundColor: accent06
  },
  companionSetupInfoLabel: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 8,
    fontWeight: "800",
    letterSpacing: 1.3,
    textTransform: "uppercase"
  },
  companionSetupInfoValue: {
    marginTop: 5,
    color: palette.text,
    fontSize: 12,
    fontWeight: "800"
  },
  companionSetupExampleBox: {
    padding: 12,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: accent14,
    backgroundColor: fieldPanel
  },
  companionSetupExampleLabel: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 8,
    fontWeight: "900",
    letterSpacing: 1.3,
    includeFontPadding: false
  },
  companionSetupExampleText: {
    marginTop: 6,
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 12,
    fontWeight: "800"
  },
  companionSetupInputWrap: {
    minHeight: 48,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingLeft: 14,
    paddingRight: 8,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: accent18,
    backgroundColor: palette.row
  },
  companionSetupInputWrapOk: {
    borderColor: success25,
    backgroundColor: success08
  },
  companionSetupInputWrapChecking: {
    borderColor: accent30,
    backgroundColor: accent08
  },
  companionSetupInputWrapError: {
    borderColor: error25,
    backgroundColor: error08
  },
  companionSetupInput: {
    flex: 1,
    minWidth: 0,
    minHeight: 48,
    paddingVertical: 0,
    color: palette.text,
    fontFamily: mono,
    fontSize: 13
  },
  companionSetupInputStatus: {
    width: 32,
    height: 32,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: fieldPanel
  },
  companionSetupUrlHint: {
    marginTop: -4,
    color: palette.textMuted,
    fontSize: 11,
    lineHeight: 16
  },
  companionSetupUrlHintOk: {
    color: palette.green
  },
  companionSetupUrlHintError: {
    color: palette.red
  },
  companionSetupPrimary: {
    minHeight: 48,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    paddingHorizontal: 16,
    borderRadius: 999,
    backgroundColor: palette.green
  },
  companionSetupPrimaryText: {
    fontFamily: mono,
    color: onGreenText,
    fontSize: 12,
    fontWeight: "900",
    letterSpacing: 1.2,
    textAlign: "center",
    includeFontPadding: false,
    lineHeight: 14
  },
  companionSetupSecondary: {
    minHeight: 38,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 14,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: accent14,
    backgroundColor: softPanel
  },
  companionSetupSecondaryText: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 1.1,
    textAlign: "center",
    includeFontPadding: false,
    lineHeight: 12
  },
  companionSetupProgressRail: {
    gap: 10,
    padding: 12,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: hairline,
    backgroundColor: softPanel
  },
  companionSetupProgressRailActive: {
    borderColor: accent30,
    backgroundColor: accent08
  },
  companionSetupProgressHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 9
  },
  companionSetupProgressText: {
    flex: 1,
    color: palette.textMuted,
    fontSize: 12,
    lineHeight: 17
  },
  companionSetupProgressSteps: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8
  },
  companionSetupProgressStep: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 9,
    paddingVertical: 6,
    borderRadius: 999,
    backgroundColor: softPanelStrong
  },
  companionSetupProgressDot: {
    width: 6,
    height: 6,
    borderRadius: 999,
    backgroundColor: palette.textDim
  },
  companionSetupProgressDotActive: {
    backgroundColor: palette.green
  },
  companionSetupProgressStepText: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 8,
    fontWeight: "800",
    letterSpacing: 0.7,
    textTransform: "uppercase",
    includeFontPadding: false
  },
  companionSetupOptionStack: {
    gap: 8,
    marginTop: 4
  },
  companionSetupOption: {
    padding: 14,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: hairline,
    backgroundColor: softPanel
  },
  companionSetupOptionActive: {
    borderColor: success25,
    backgroundColor: success08
  },
  companionSetupOptionTop: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10
  },
  companionSetupOptionTitle: {
    color: palette.text,
    fontSize: 13,
    fontWeight: "800"
  },
  companionSetupRecommended: {
    fontFamily: mono,
    color: palette.green,
    fontSize: 8,
    fontWeight: "900",
    letterSpacing: 1,
    includeFontPadding: false
  },
  companionSetupOptionBody: {
    marginTop: 5,
    color: palette.textMuted,
    fontSize: 11,
    lineHeight: 16
  },
  companionSetupSummary: {
    padding: 12,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: accent14,
    backgroundColor: palette.row
  },
  companionSetupError: {
    marginTop: 14,
    padding: 12,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: warn18,
    backgroundColor: warn08
  },
  companionSetupErrorLabel: {
    fontFamily: mono,
    color: palette.amber,
    fontSize: 9,
    fontWeight: "800",
    letterSpacing: 1.2
  },
  companionSetupErrorText: {
    marginTop: 5,
    color: palette.text,
    fontSize: 12,
    lineHeight: 18
  },
  activityPill: {
    marginHorizontal: 12,
    marginBottom: 12,
    minHeight: 58,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingHorizontal: 13,
    paddingVertical: 11,
    borderRadius: 18,
    borderWidth: 1
  },
  activityPillSync: {
    borderColor: accent18,
    backgroundColor: accent08
  },
  activityPillWarn: {
    borderColor: warn24,
    backgroundColor: warn08
  },
  activityPillOk: {
    borderColor: success25,
    backgroundColor: success08
  },
  activitySpinnerWrap: {
    width: 34,
    height: 34,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: fieldPanel
  },
  activityCopy: {
    flex: 1,
    minWidth: 0
  },
  activityLabel: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 11,
    fontWeight: "900",
    letterSpacing: 0.8,
    textTransform: "uppercase",
    includeFontPadding: false
  },
  activityDetail: {
    marginTop: 3,
    color: palette.textMuted,
    fontSize: 11,
    lineHeight: 16
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
    justifyContent: "space-between",
    gap: 16,
    backgroundColor: palette.bg,
    overflow: "hidden"
  },
  launchSkyGrid: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    justifyContent: "space-evenly",
    opacity: 0.32
  },
  launchGridLine: {
    height: 1,
    backgroundColor: palette.lineSoft
  },
  launchHalo: {
    position: "absolute",
    borderRadius: 999,
    backgroundColor: accent12
  },
  launchHaloInner: {
    position: "absolute",
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "rgba(122,176,216,0.24)",
    borderTopColor: "rgba(41,226,135,0.72)",
    borderRightColor: warn38,
    backgroundColor: "rgba(255,255,255,0.018)"
  },
  launchRunwayField: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: -30,
    height: 230,
    alignItems: "center",
    justifyContent: "flex-end",
    opacity: 0.8
  },
  launchRunwayFieldCompact: {
    opacity: 0.48
  },
  launchRunwayPerspective: {
    width: "78%",
    maxWidth: 520,
    height: 104,
    flexDirection: "row",
    justifyContent: "center",
    gap: 28,
    transform: [{ perspective: 720 }, { rotateX: "56deg" }]
  },
  launchRunwayEdge: {
    width: 2,
    height: "100%",
    borderRadius: 999,
    backgroundColor: accent25
  },
  launchRunwayCenter: {
    width: 18,
    height: "100%",
    alignItems: "center",
    justifyContent: "space-evenly"
  },
  launchRunwayCenterMark: {
    width: 6,
    height: 12,
    borderRadius: 999,
    backgroundColor: warn38
  },
  launchStage: {
    flexGrow: 1,
    flexShrink: 1,
    width: "100%",
    alignItems: "center",
    justifyContent: "flex-end",
    gap: 16,
    paddingTop: 10,
    paddingBottom: 0
  },
  launchStageCompact: {
    gap: 10,
    paddingVertical: 10
  },
  launchContentStack: {
    width: "100%",
    flex: 1,
    alignItems: "center",
    justifyContent: "center"
  },
  launchScene: {
    width: "100%",
    borderRadius: 30,
    borderWidth: 1,
    borderColor: hairline,
    backgroundColor: fieldPanel,
    overflow: "hidden",
    gap: 16,
    shadowColor: "#000",
    shadowOpacity: 0.24,
    shadowRadius: 28,
    shadowOffset: { width: 0, height: 18 }
  },
  launchSceneCompact: {
    borderRadius: 24,
    gap: 10
  },
  launchTopBar: {
    width: "100%",
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 2,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: palette.lineSoft
  },
  launchTopCode: {
    fontFamily: brand,
    color: palette.textDim,
    fontSize: 10,
    fontWeight: "400",
    letterSpacing: 0.8,
    includeFontPadding: false
  },
  launchTopVersion: {
    paddingHorizontal: 11,
    paddingVertical: 6,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: accent18,
    backgroundColor: fieldPanel,
    fontFamily: mono,
    color: palette.textMuted,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 0.8,
    includeFontPadding: false
  },
  launchHeroCard: {
    width: "100%",
    alignItems: "center",
    gap: 14,
    paddingHorizontal: 4,
    paddingTop: 2,
    paddingBottom: 0
  },
  launchHeroCardWide: {
    flexDirection: "row",
    justifyContent: "center",
    gap: 24
  },
  launchMarkWrap: {
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 2
  },
  launchRadarRing: {
    position: "absolute",
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "rgba(122,176,216,0.24)"
  },
  launchRadarRingOuter: {
    position: "absolute",
    borderRadius: 999,
    borderWidth: 1,
    borderColor: hairline,
    borderLeftColor: accent30,
    borderBottomColor: success25
  },
  launchSweepRotor: {
    position: "absolute",
    alignItems: "center"
  },
  launchSweep: {
    position: "absolute",
    top: "9%",
    width: 2,
    borderRadius: 999,
    backgroundColor: "rgba(41,226,135,0.72)"
  },
  launchMarkCrop: {
    borderRadius: 999,
    overflow: "hidden",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: palette.bg,
    borderWidth: 1,
    borderColor: "rgba(122,176,216,0.24)"
  },
  launchMark: {
    width: "122%",
    height: "122%",
    shadowColor: palette.blue,
    shadowOpacity: 0.18,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 10 }
  },
  launchCopy: {
    width: "100%",
    maxWidth: 390,
    alignItems: "center"
  },
  launchCopyWide: {
    flex: 1,
    maxWidth: 470,
    alignItems: "flex-start"
  },
  launchEyebrow: {
    fontFamily: brand,
    color: palette.blue2,
    fontSize: 11,
    fontWeight: "400",
    letterSpacing: 0.8
  },
  launchTitle: {
    marginTop: 8,
    fontFamily: brand,
    color: palette.text,
    fontSize: 34,
    lineHeight: 38,
    fontWeight: "400",
    letterSpacing: 0.8,
    textAlign: "center",
    includeFontPadding: false
  },
  launchTitleCompact: {
    fontSize: 28,
    lineHeight: 32
  },
  launchTitleWide: {
    fontSize: 42,
    lineHeight: 46,
    textAlign: "left"
  },
  launchSubtitle: {
    marginTop: 8,
    color: palette.textMuted,
    fontSize: 13,
    lineHeight: 18,
    textAlign: "center"
  },
  launchSubtitleWide: {
    textAlign: "left",
    fontSize: 14,
    lineHeight: 20
  },
  launchVersion: {
    marginTop: 10,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: accent18,
    backgroundColor: accent08,
    fontFamily: mono,
    color: palette.textMuted,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 1
  },
  launchBoard: {
    width: "100%",
    marginTop: 10,
    padding: 10,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: hairlineSoft,
    backgroundColor: fieldPanel
  },
  launchBoardRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 6
  },
  launchBoardTime: {
    width: 34,
    fontFamily: mono,
    color: palette.green,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 1
  },
  launchBoardText: {
    flex: 1,
    fontFamily: mono,
    color: palette.text,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 1
  },
  launchBoardLed: {
    width: 7,
    height: 7,
    borderRadius: 999,
    backgroundColor: palette.green
  },
  launchBoardLedAmber: {
    backgroundColor: palette.amber
  },
  launchRunwayDeck: {
    width: "100%",
    minHeight: 138,
    paddingHorizontal: 14,
    paddingTop: 12,
    paddingBottom: 12,
    borderRadius: 22,
    borderWidth: 1,
    borderColor: accent16,
    backgroundColor: fieldPanel,
    overflow: "hidden",
    alignItems: "center",
    justifyContent: "center"
  },
  launchRunwayDeckCompact: {
    minHeight: 106,
    paddingTop: 10,
    paddingBottom: 10
  },
  launchRunwayDeckHeader: {
    width: "100%",
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 2
  },
  launchRunwayDeckKicker: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 9,
    fontWeight: "900",
    letterSpacing: 1.8,
    includeFontPadding: false
  },
  launchRunwayDeckMeta: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 9,
    fontWeight: "900",
    letterSpacing: 1.1,
    includeFontPadding: false
  },
  launchStatusDot: {
    width: 7,
    height: 7,
    borderRadius: 999,
    backgroundColor: palette.green
  },
  launchStatusRow: {
    width: "100%",
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8
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
    backgroundColor: softPanelStrong
  },
  launchProgressFill: {
    height: "100%",
    borderRadius: 999,
    backgroundColor: palette.green
  },
  launchFooterCodes: {
    flexDirection: "row",
    flexWrap: "wrap",
    justifyContent: "center",
    gap: 8,
    marginTop: 14
  },
  launchFooterCode: {
    paddingHorizontal: 9,
    paddingVertical: 5,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: hairline,
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 8,
    fontWeight: "800",
    letterSpacing: 0.8
  },
  launchStatusPanel: {
    width: "100%",
    maxWidth: 520,
    padding: 14,
    borderRadius: 22,
    borderWidth: 1,
    borderColor: hairline,
    backgroundColor: fieldPanel
  },
  launchBottomBoard: {
    position: "absolute",
    left: 16,
    right: 16,
    bottom: 18,
    flexDirection: "row",
    gap: 8
  },
  launchBottomCell: {
    flex: 1,
    minHeight: 48,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 14,
    borderWidth: 1,
    borderColor: hairline,
    backgroundColor: fieldPanel
  },
  launchBottomLabel: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 8,
    fontWeight: "900",
    letterSpacing: 1,
    includeFontPadding: false
  },
  launchBottomValue: {
    marginTop: 4,
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 9,
    fontWeight: "900",
    letterSpacing: 0.8,
    includeFontPadding: false
  },
  header: {
    paddingTop: 10,
    paddingHorizontal: 18,
    paddingBottom: 12,
    backgroundColor: palette.header,
    borderBottomWidth: 1,
    borderBottomColor: palette.lineSoft
  },
  mainArea: {
    flex: 1
  },
  islandShell: {
    alignSelf: "flex-start",
    width: "100%",
    maxWidth: 520,
    minHeight: 46,
    marginTop: 12,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: palette.lineSoft,
    backgroundColor: palette.rowAlt,
    overflow: "hidden",
    flexDirection: "row",
    alignItems: "center",
    shadowColor: "#000",
    shadowOpacity: 0.12,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 8 }
  },
  islandShellActive: {
    borderColor: accent30,
    backgroundColor: palette.row
  },
  islandPressable: {
    flex: 1,
    paddingHorizontal: 12,
    paddingTop: 8,
    paddingBottom: 7
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
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.8
  },
  islandMeta: {
    marginTop: 2,
    color: palette.textMuted,
    fontSize: 10
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
  islandActionHint: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 8,
    fontWeight: "800",
    letterSpacing: 0.9
  },
  islandPinButton: {
    width: 38,
    height: 38,
    marginRight: 8,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: accent14,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: accent06
  },
  islandPinButtonActive: {
    borderColor: warn38,
    backgroundColor: warn08
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
    borderColor: success25,
    backgroundColor: success10
  },
  livePillOff: {
    borderColor: error25,
    backgroundColor: error10
  },
  livePillIssue: {
    borderColor: warn24,
    backgroundColor: warn07
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
  liveDotIssue: {
    backgroundColor: palette.amber
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
  liveTextIssue: {
    color: palette.amber
  },
  snapshotPulseDot: {
    width: 7,
    height: 7,
    borderRadius: 999,
    backgroundColor: palette.green,
    shadowColor: palette.green,
    shadowOpacity: 0.65,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 0 }
  },
  sourcePill: {
    paddingHorizontal: 9,
    paddingVertical: 5,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: accent18,
    backgroundColor: accent08
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
    backgroundColor: softPanel
  },
  metarCat: {
    fontFamily: mono,
    color: onGreenText,
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
  airportHeroRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 12
  },
  airportHeroRowStacked: {
    flexDirection: "column",
    alignItems: "stretch",
    gap: 10
  },
  airportHeroPressable: {
    flex: 1,
    minWidth: 0
  },
  airportHeroPressableStacked: {
    flex: 0,
    width: "100%",
    minWidth: 0
  },
  airportHeroTopline: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8
  },
  airportHeroToplineStacked: {
    alignItems: "flex-start"
  },
  airportHeroKicker: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 9,
    fontWeight: "800",
    letterSpacing: 1.3,
    includeFontPadding: false
  },
  airportCodeBadges: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    flexShrink: 0
  },
  airportCodeBadgesStacked: {
    flexShrink: 1,
    flexWrap: "wrap",
    justifyContent: "flex-end"
  },
  airportCodeBadge: {
    paddingHorizontal: 7,
    paddingVertical: 3,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: accent18,
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 9,
    fontWeight: "900",
    letterSpacing: 0.8,
    includeFontPadding: false
  },
  airportHeroName: {
    marginTop: 7,
    fontSize: 25,
    lineHeight: 29,
    fontWeight: "900",
    letterSpacing: 0.2
  },
  airportHeroNameCompact: {
    fontSize: 21,
    lineHeight: 25,
    letterSpacing: 0
  },
  airportHeroLocation: {
    marginTop: 4,
    color: palette.textMuted,
    fontSize: 12,
    lineHeight: 17
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
  headerWeatherRail: {
    width: 136,
    alignItems: "flex-end",
    gap: 6
  },
  headerWeatherRailStacked: {
    width: "100%",
    alignItems: "stretch",
    gap: 8
  },
  headerClockStackInline: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12
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
  weatherCompact: {
    width: "100%",
    minHeight: 58,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderRadius: 16,
    borderWidth: 1
  },
  weatherCompactCopy: {
    flex: 1,
    minWidth: 0
  },
  weatherCompactTemp: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 15,
    fontWeight: "900",
    includeFontPadding: false
  },
  weatherCompactMeta: {
    marginTop: 3,
    fontFamily: mono,
    color: palette.textMuted,
    fontSize: 8,
    fontWeight: "800",
    letterSpacing: 0.5,
    includeFontPadding: false,
    textTransform: "uppercase"
  },
  telemetryStrip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 7,
    marginTop: 9,
    flexWrap: "wrap"
  },
  countPill: {
    paddingHorizontal: 9,
    paddingVertical: 5,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: hairline,
    backgroundColor: softPanelStrong
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
    borderColor: accent16,
    backgroundColor: accent06,
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
  radarWeatherCard: {
    marginHorizontal: 12,
    marginTop: 8,
    marginBottom: 12,
    padding: 13,
    borderRadius: 18,
    borderWidth: 1,
    backgroundColor: palette.rowAlt
  },
  radarLegend: {
    marginHorizontal: 12,
    marginBottom: 8,
    paddingVertical: 9,
    paddingHorizontal: 12,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: hairlineSoft,
    backgroundColor: palette.rowAlt
  },
  radarLegendHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 8
  },
  radarLegendTitle: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 9,
    fontWeight: "700",
    letterSpacing: 1.4
  },
  radarLegendMetaWrap: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8
  },
  radarLegendSource: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.8
  },
  radarLegendAge: {
    fontFamily: mono,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.8
  },
  radarLegendChips: {
    flexDirection: "row",
    gap: 10,
    flexWrap: "wrap"
  },
  radarLegendChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5
  },
  radarLegendDot: {
    width: 6,
    height: 6,
    borderRadius: 999
  },
  radarLegendLabel: {
    fontFamily: mono,
    color: palette.textMuted,
    fontSize: 9,
    fontWeight: "700",
    letterSpacing: 0.8
  },
  radarWeatherHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 11
  },
  radarWeatherIcon: {
    width: 42,
    height: 42,
    borderRadius: 15,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center"
  },
  radarWeatherTitleWrap: {
    flex: 1,
    minWidth: 0
  },
  radarWeatherTitle: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 9,
    fontWeight: "900",
    letterSpacing: 1.2,
    includeFontPadding: false
  },
  radarWeatherBody: {
    marginTop: 4,
    color: palette.text,
    fontSize: 12,
    lineHeight: 17
  },
  radarWeatherCategory: {
    minWidth: 58,
    alignItems: "center",
    paddingHorizontal: 8,
    paddingVertical: 6,
    borderRadius: 13,
    borderWidth: 1
  },
  radarWeatherCategoryText: {
    fontFamily: mono,
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 0.8,
    includeFontPadding: false
  },
  radarWeatherTemp: {
    marginTop: 4,
    fontFamily: mono,
    color: palette.text,
    fontSize: 12,
    fontWeight: "900",
    includeFontPadding: false
  },
  radarWeatherRaw: {
    marginTop: 12,
    padding: 10,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: hairlineSoft,
    backgroundColor: fieldPanel,
    fontFamily: mono,
    color: palette.textMuted,
    fontSize: 10,
    lineHeight: 15
  },
  radarWeatherChips: {
    marginTop: 12,
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 7
  },
  screenScroll: {
    flex: 1
  },
  screenContent: {
    flexGrow: 1,
    paddingTop: 12,
    paddingBottom: 20
  },
  errorBanner: {
    marginHorizontal: 12,
    marginBottom: 10,
    padding: 14,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: error18,
    backgroundColor: error08,
    flexDirection: "row",
    alignItems: "center",
    gap: 10
  },
  errorBannerCopy: {
    flex: 1
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
  errorRetryButton: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: error25,
    backgroundColor: error10
  },
  errorRetryText: {
    fontFamily: mono,
    color: palette.red,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 1
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
    minHeight: 52,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: hairline,
    backgroundColor: softPanel,
    justifyContent: "center"
  },
  optionChipActive: {
    borderColor: accent40,
    backgroundColor: accent12
  },
  paletteChip: {
    minWidth: 132,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: hairline,
    backgroundColor: softPanel
  },
  paletteDots: {
    flexDirection: "row",
    gap: 4,
    marginTop: 8
  },
  paletteDot: {
    width: 14,
    height: 6,
    borderRadius: 999
  },
  optionChipLabel: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 11,
    fontWeight: "700",
    textAlign: "center",
    includeFontPadding: false,
    lineHeight: 13
  },
  optionChipLabelActive: {
    color: palette.blue
  },
  optionChipMeta: {
    marginTop: 3,
    color: palette.textDim,
    fontSize: 10,
    textAlign: "center",
    includeFontPadding: false,
    lineHeight: 12
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
    backgroundColor: softPanelStrong
  },
  dirButton: {
    flex: 1,
    minHeight: 34,
    paddingHorizontal: 8,
    paddingVertical: 8,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 6,
    borderWidth: 1,
    borderColor: "transparent"
  },
  dirButtonActive: {
    backgroundColor: accent12,
    borderColor: accent20
  },
  dirButtonText: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 1,
    textAlign: "center",
    includeFontPadding: false,
    lineHeight: 12
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
  fullscreenFidsShell: {
    flex: 1,
    paddingHorizontal: 18,
    paddingTop: 14,
    paddingBottom: 10,
    backgroundColor: palette.bg
  },
  fullscreenFidsShellCompact: {
    paddingHorizontal: 12,
    paddingTop: 8,
    paddingBottom: 6
  },
  fullscreenFidsTop: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 18,
    marginBottom: 12,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: palette.lineSoft
  },
  fullscreenFidsTopCompact: {
    gap: 10,
    marginBottom: 7,
    paddingBottom: 7
  },
  fullscreenFidsIdentity: {
    flex: 1,
    minWidth: 0
  },
  fullscreenFidsKickerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    flexWrap: "wrap"
  },
  fullscreenFidsKicker: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 2.6
  },
  fullscreenFidsBoardBadge: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: accent18,
    backgroundColor: accent08,
    fontFamily: mono,
    color: palette.textMuted,
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 1.4,
    includeFontPadding: false,
    lineHeight: 12
  },
  fullscreenFidsTitle: {
    marginTop: 5,
    fontFamily: mono,
    color: palette.text,
    fontSize: 28,
    lineHeight: 32,
    fontWeight: "800",
    letterSpacing: 0.8
  },
  fullscreenFidsTitleCompact: {
    marginTop: 3,
    fontSize: 20,
    lineHeight: 23,
    letterSpacing: 0.3
  },
  fullscreenFidsAirport: {
    marginTop: 2,
    color: palette.textMuted,
    fontSize: 13
  },
  fullscreenFidsMeta: {
    alignItems: "flex-end",
    gap: 3,
    paddingTop: 2
  },
  fullscreenFidsLive: {
    fontFamily: mono,
    fontSize: 12,
    fontWeight: "800",
    letterSpacing: 1.4
  },
  fullscreenFidsLiveOn: {
    color: palette.green
  },
  fullscreenFidsLiveOff: {
    color: palette.red
  },
  fullscreenFidsSource: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 1.1
  },
  fullscreenFidsClock: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 13,
    fontWeight: "800"
  },
  fullscreenFidsLocal: {
    color: palette.textMuted,
    fontSize: 11
  },
  fullscreenWeatherHero: {
    minHeight: 62,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    marginBottom: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 14,
    borderWidth: 1
  },
  fullscreenWeatherHeroCompact: {
    minHeight: 44,
    gap: 8,
    marginBottom: 6,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 12
  },
  fullscreenWeatherIcon: {
    width: 44,
    height: 44,
    borderRadius: 14,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0
  },
  fullscreenWeatherIconCompact: {
    width: 32,
    height: 32,
    borderRadius: 10
  },
  fullscreenWeatherCopy: {
    flex: 1,
    minWidth: 0
  },
  fullscreenWeatherTitleRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    flexWrap: "wrap"
  },
  fullscreenWeatherCategory: {
    fontFamily: mono,
    fontSize: 14,
    fontWeight: "900",
    letterSpacing: 1.1,
    includeFontPadding: false,
    lineHeight: 16
  },
  fullscreenWeatherCategoryCompact: {
    fontSize: 12,
    lineHeight: 14
  },
  fullscreenWeatherTemp: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 14,
    fontWeight: "900",
    includeFontPadding: false,
    lineHeight: 16
  },
  fullscreenWeatherMode: {
    paddingHorizontal: 7,
    paddingVertical: 3,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: accent18,
    backgroundColor: softPanelStrong,
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 8,
    fontWeight: "900",
    letterSpacing: 0.9,
    includeFontPadding: false,
    lineHeight: 10
  },
  fullscreenWeatherSummary: {
    marginTop: 5,
    color: palette.textMuted,
    fontSize: 13,
    lineHeight: 17
  },
  fullscreenWeatherChips: {
    maxWidth: 420,
    flexDirection: "row",
    justifyContent: "flex-end",
    flexWrap: "wrap",
    gap: 6,
    flexShrink: 0
  },
  fullscreenWeatherChip: {
    minWidth: 58,
    paddingHorizontal: 8,
    paddingVertical: 5,
    borderRadius: 9,
    borderWidth: 1,
    borderColor: hairline,
    backgroundColor: softPanelStrong,
    alignItems: "center"
  },
  fullscreenWeatherChipLabel: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 8,
    fontWeight: "900",
    letterSpacing: 0.8,
    includeFontPadding: false,
    lineHeight: 10
  },
  fullscreenWeatherChipValue: {
    marginTop: 3,
    fontFamily: mono,
    color: palette.text,
    fontSize: 11,
    fontWeight: "900",
    includeFontPadding: false,
    lineHeight: 13
  },
  fullscreenFidsColumns: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 12,
    paddingTop: 7,
    paddingBottom: 7,
    marginBottom: 6,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: hairlineSoft,
    backgroundColor: palette.header,
    zIndex: 2
  },
  fullscreenFidsColumnsCompact: {
    gap: 7,
    paddingHorizontal: 9,
    paddingTop: 5,
    paddingBottom: 5,
    marginBottom: 4,
    borderRadius: 8
  },
  fullscreenFidsColumnText: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 9,
    fontWeight: "800",
    letterSpacing: 1.4
  },
  fullscreenFidsTimeColumn: {
    width: 78
  },
  fullscreenFidsTimeColumnCompact: {
    width: 60
  },
  fullscreenFidsFlightColumn: {
    width: 170
  },
  fullscreenFidsFlightColumnCompact: {
    width: 132
  },
  fullscreenFidsRouteColumn: {
    flex: 1,
    minWidth: 0
  },
  fullscreenFidsStatusColumn: {
    width: 150
  },
  fullscreenFidsStatusColumnCompact: {
    width: 116
  },
  fullscreenFidsStatusCell: {
    width: 150,
    alignItems: "flex-start"
  },
  fullscreenFidsAircraftColumn: {
    width: 82,
    textAlign: "right"
  },
  fullscreenFidsGateColumn: {
    width: 64,
    textAlign: "right"
  },
  fullscreenFidsInfoColumn: {
    width: 92,
    minWidth: 0,
    alignItems: "flex-end"
  },
  fullscreenFidsList: {
    flex: 1
  },
  fullscreenFidsListContent: {
    paddingBottom: 16
  },
  fullscreenFidsRow: {
    minHeight: 58,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: hairlineSoft,
    backgroundColor: palette.row
  },
  fullscreenFidsRowCompact: {
    gap: 7,
    paddingHorizontal: 9,
    paddingVertical: 5,
    borderRadius: 8
  },
  fullscreenFidsRowPinned: {
    borderColor: warn24,
    backgroundColor: warn07
  },
  fullscreenFidsTime: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 20,
    fontWeight: "800"
  },
  fullscreenFidsFlightCell: {
    minWidth: 0
  },
  fullscreenFidsFlight: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 18,
    fontWeight: "800",
    letterSpacing: 0.8
  },
  fullscreenFidsAirline: {
    flex: 1,
    minWidth: 0,
    marginTop: 2,
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.3
  },
  fullscreenFidsRouteCell: {
    minWidth: 0
  },
  fullscreenFidsRouteName: {
    color: palette.text,
    fontSize: 17,
    fontWeight: "700"
  },
  fullscreenFidsRouteMeta: {
    marginTop: 2,
    fontFamily: mono,
    color: palette.textMuted,
    fontSize: 10,
    letterSpacing: 0.6
  },
  fullscreenFidsAircraft: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 12,
    fontWeight: "700"
  },
  fullscreenFidsGate: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 12,
    fontWeight: "800"
  },
  fullscreenFidsInfoMini: {
    justifyContent: "flex-end",
    gap: 4,
    maxWidth: "100%"
  },
  fullscreenFidsInfoLabel: {
    color: palette.textDim,
    fontSize: 7,
    letterSpacing: 0.7
  },
  fullscreenFidsInfoValue: {
    flexShrink: 1,
    color: palette.blue2,
    fontSize: 9,
    textAlign: "right"
  },
  fullscreenFidsEmpty: {
    flex: 1,
    minHeight: 170,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 24,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: palette.lineSoft,
    backgroundColor: palette.row
  },
  fullscreenFidsEmptyTitle: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 22,
    fontWeight: "800",
    letterSpacing: 1.4
  },
  fullscreenFidsEmptyDetail: {
    marginTop: 8,
    maxWidth: 520,
    color: palette.textMuted,
    fontSize: 13,
    textAlign: "center",
    lineHeight: 19
  },
  fidsHeader: {
    flexDirection: "row",
    alignItems: "center",
    marginHorizontal: 12,
    paddingHorizontal: 10,
    paddingBottom: 6,
    gap: 5
  },
  fidsHeaderText: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 8,
    fontWeight: "700",
    letterSpacing: 1
  },
  fidsColTime: {
    width: 54
  },
  fidsColFlight: {
    width: 78
  },
  fidsColRoute: {
    flex: 1,
    minWidth: 0
  },
  fidsColStatus: {
    width: 86,
    alignItems: "center"
  },
  fidsColStatusCompact: {
    width: 80
  },
  fidsColStatusText: {
    width: 86,
    textAlign: "center"
  },
  fidsColStatusTextCompact: {
    width: 80
  },
  fidsColAircraft: {
    width: 20,
    textAlign: "right"
  },
  fidsColGate: {
    width: 34,
    alignItems: "center"
  },
  fidsColGateText: {
    width: 34,
    textAlign: "center"
  },
  alignRight: {
    textAlign: "right",
    flex: 0.48
  },
  fidsListItem: {
    paddingHorizontal: 12
  },
  fidsRow: {
    minHeight: 55,
    paddingHorizontal: 10,
    paddingVertical: 9,
    marginBottom: 3,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: hairlineSoft,
    backgroundColor: palette.row
  },
  fidsRowMain: {
    width: "100%",
    flexDirection: "row",
    alignItems: "center",
    gap: 5
  },
  fidsRowPinned: {
    borderColor: warn24,
    borderLeftWidth: 3,
    borderLeftColor: palette.amber,
    backgroundColor: warn07
  },
  fidsTimeCell: {
    flexDirection: "column",
    alignItems: "flex-start"
  },
  fidsTime: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 12,
    fontWeight: "700"
  },
  fidsDelayTag: {
    fontFamily: mono,
    fontSize: 9,
    fontWeight: "700",
    paddingHorizontal: 3,
    paddingVertical: 1,
    borderRadius: 3,
    marginTop: 2,
    overflow: "hidden"
  },
  fidsDelayTagEarly: {
    color: palette.green,
    backgroundColor: success08
  },
  fidsDelayTagWarn: {
    color: palette.amber,
    backgroundColor: warn07
  },
  fidsDelayTagBad: {
    color: palette.red,
    backgroundColor: error08
  },
  fidsFlightWrap: {
    flexDirection: "column",
    alignItems: "flex-start"
  },
  fidsFlightTopRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4
  },
  fidsAirlineLine: {
    flex: 1,
    color: palette.textMuted,
    fontFamily: mono,
    fontSize: 9,
    fontWeight: "700",
    letterSpacing: 0.2,
    marginTop: 1
  },
  fidsAirlineLineLabel: {
    color: palette.textDim
  },
  fidsFlight: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 11
  },
  fidsGateVal: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 9,
    textAlign: "center"
  },
  fidsGateEmpty: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 9,
    textAlign: "center"
  },
  fidsDest: {
    flex: 1,
    minWidth: 0
  },
  fidsDestName: {
    color: palette.textMuted,
    fontSize: 12
  },
  fidsDestCode: {
    marginTop: 1,
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 9
  },
  fidsInfoLine: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    minWidth: 0
  },
  fidsInfoRail: {
    width: "100%",
    marginTop: 7,
    paddingTop: 6,
    borderTopWidth: 1,
    borderTopColor: hairlineSoft
  },
  fidsInfoLabel: {
    flexShrink: 0,
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 8,
    fontWeight: "900",
    letterSpacing: 0.8
  },
  fidsInfoValue: {
    flex: 1,
    minWidth: 0,
    fontFamily: mono,
    color: palette.textMuted,
    fontSize: 9,
    fontWeight: "800",
    letterSpacing: 0.2
  },
  fidsInfoValueAccent: {
    color: palette.blue2
  },
  fidsInfoValueWarn: {
    color: palette.amber
  },
  fidsAircraft: {
    textAlign: "right",
    fontFamily: mono,
    color: palette.textDim,
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
    borderColor: hairlineSoft,
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
  historyFilterRow: {
    flexDirection: "row",
    gap: 8,
    marginHorizontal: 12,
    marginBottom: 8,
    alignItems: "center"
  },
  historyFilterInput: {
    flex: 1,
    height: 34,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: hairline,
    backgroundColor: fieldPanel,
    color: palette.text,
    fontFamily: mono,
    fontSize: 11,
    paddingHorizontal: 9
  },
  historyApplyButton: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 8,
    backgroundColor: palette.blue,
    alignItems: "center",
    justifyContent: "center"
  },
  historyApplyButtonText: {
    fontFamily: mono,
    color: onBlueText,
    fontSize: 10,
    fontWeight: "700"
  },
  historyKpiGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
    marginHorizontal: 12,
    marginBottom: 8
  },
  historyKpiCard: {
    flex: 1,
    minWidth: "30%",
    padding: 10,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: hairlineSoft,
    backgroundColor: palette.row,
    alignItems: "flex-start"
  },
  historyKpiLabel: {
    color: palette.textMuted,
    fontSize: 8,
    fontWeight: "700",
    letterSpacing: 0.8
  },
  historyKpiValue: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 22,
    fontWeight: "900",
    lineHeight: 26,
    marginTop: 3
  },
  historyKpiNote: {
    color: palette.textMuted,
    fontSize: 8,
    marginTop: 2
  },
  historyPanel: {
    marginHorizontal: 12,
    marginBottom: 8,
    padding: 12,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: hairlineSoft,
    backgroundColor: palette.row
  },
  historyPanelTitle: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 8,
    fontWeight: "700",
    letterSpacing: 1,
    marginBottom: 10
  },
  historyDelayStack: {
    flexDirection: "row",
    height: 8,
    borderRadius: 99,
    overflow: "hidden",
    backgroundColor: softPanelStrong,
    marginBottom: 10
  },
  historyBarRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginBottom: 5
  },
  historyBarLabel: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 9,
    width: 64
  },
  historyBarTrack: {
    flex: 1,
    height: 6,
    backgroundColor: softPanelStrong,
    borderRadius: 99,
    overflow: "hidden"
  },
  historyBarFill: {
    height: 6,
    borderRadius: 99,
    backgroundColor: palette.blue
  },
  historyBarValue: {
    fontFamily: mono,
    color: palette.textMuted,
    fontSize: 9,
    width: 58,
    textAlign: "right"
  },
  adminSubTitle: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 8,
    fontWeight: "700",
    letterSpacing: 1,
    marginTop: 14,
    marginBottom: 6
  },
  adminBudgetTrack: {
    height: 5,
    borderRadius: 99,
    overflow: "hidden",
    backgroundColor: softPanelStrong,
    marginTop: 8
  },
  adminMetarHero: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    padding: 10,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: accent18,
    backgroundColor: accent08,
    marginBottom: 8
  },
  adminMetarIcon: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: softPanelStrong,
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0
  },
  adminMetarIconText: {
    fontSize: 20
  },
  adminMetarTitle: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 13,
    fontWeight: "900"
  },
  adminMetarTitleRow: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    gap: 7
  },
  adminMetarModePill: {
    paddingHorizontal: 7,
    paddingVertical: 3,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: accent18,
    backgroundColor: accent08
  },
  adminMetarModeText: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 8,
    fontWeight: "900",
    letterSpacing: 0.8,
    includeFontPadding: false,
    lineHeight: 10
  },
  adminMetarSub: {
    color: palette.textMuted,
    fontSize: 11,
    lineHeight: 16,
    marginTop: 2
  },
  adminMetarChipRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
    marginTop: 9
  },
  adminMetarChip: {
    paddingHorizontal: 7,
    paddingVertical: 4,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: hairline,
    backgroundColor: softPanelStrong
  },
  adminMetarChipText: {
    fontFamily: mono,
    color: palette.textMuted,
    fontSize: 9,
    fontWeight: "800",
    includeFontPadding: false,
    lineHeight: 11
  },
  scopeCard: {
    marginHorizontal: 12,
    marginBottom: 12,
    padding: 18,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: accent14,
    backgroundColor: scopePanel
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
    borderColor: accent18,
    backgroundColor: scopeField,
    overflow: "hidden"
  },
  scopeGroundSvg: {
    position: "absolute",
    left: 0,
    top: 0
  },
  scopeRingOuter: {
    position: "absolute",
    width: "100%",
    height: "100%",
    borderRadius: 999,
    borderWidth: 1,
    borderColor: accent12
  },
  scopeRingMid: {
    position: "absolute",
    width: "66%",
    height: "66%",
    borderRadius: 999,
    borderWidth: 1,
    borderColor: accent10
  },
  scopeRingInner: {
    position: "absolute",
    width: "33%",
    height: "33%",
    borderRadius: 999,
    borderWidth: 1,
    borderColor: accent08
  },
  scopeCrossVertical: {
    position: "absolute",
    width: 1,
    top: 0,
    bottom: 0,
    backgroundColor: accent12
  },
  scopeCrossHorizontal: {
    position: "absolute",
    height: 1,
    left: 0,
    right: 0,
    backgroundColor: accent12
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
    borderWidth: 1,
    alignItems: "center"
  },
  statusBadgeCompact: {
    width: 78,
    paddingHorizontal: 5
  },
  status_scheduled: { backgroundColor: accent08, borderColor: accent25 },
  status_departed: { backgroundColor: success18, borderColor: success25 },
  status_boarding: { backgroundColor: success18, borderColor: success25 },
  status_delayed: { backgroundColor: warn18, borderColor: warn38 },
  status_cancelled: { backgroundColor: error18, borderColor: error25 },
  statusBadgeText: {
    fontFamily: mono,
    fontSize: 8,
    fontWeight: "700",
    letterSpacing: 0.5
  },
  statusText_scheduled: { color: palette.blue2 },
  statusText_departed: { color: palette.green },
  statusText_boarding: { color: palette.green },
  statusText_delayed: { color: palette.amber },
  statusText_cancelled: { color: palette.red },
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
    borderColor: warn18,
    backgroundColor: warn07
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
    borderColor: hairlineSoft,
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
    borderColor: accent15,
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
  settingsSectionGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginTop: 14
  },
  settingsProfileBlock: {
    marginTop: 14,
    padding: 12,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: accent14,
    backgroundColor: "rgba(255,255,255,0.025)"
  },
  settingsProfileHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    marginBottom: 10
  },
  settingsProfileTitle: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 1.1,
    includeFontPadding: false,
    lineHeight: 12
  },
  settingsProfileHint: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 9,
    fontWeight: "700",
    letterSpacing: 0.7,
    includeFontPadding: false,
    lineHeight: 11
  },
  settingsProfileChips: {
    gap: 8,
    paddingRight: 4
  },
  settingsProfileChip: {
    width: 142,
    minHeight: 58,
    justifyContent: "center",
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: accent14,
    backgroundColor: accent06
  },
  settingsProfileChipActive: {
    borderColor: success25,
    backgroundColor: success08
  },
  settingsProfileChipDisabled: {
    opacity: 0.42
  },
  settingsProfileChipTop: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8
  },
  settingsProfileName: {
    flex: 1,
    minWidth: 0,
    color: palette.text,
    fontSize: 12,
    fontWeight: "800",
    includeFontPadding: false,
    lineHeight: 15
  },
  settingsProfileNameActive: {
    color: palette.green
  },
  settingsProfileMeta: {
    marginTop: 6,
    fontFamily: mono,
    color: palette.textMuted,
    fontSize: 9,
    fontWeight: "700",
    letterSpacing: 0.5,
    includeFontPadding: false,
    lineHeight: 11
  },
  settingsInlineActions: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginTop: 14,
    marginBottom: 4
  },
  settingsCompactButton: {
    minHeight: 38,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    paddingHorizontal: 12,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: accent18,
    backgroundColor: accent08
  },
  settingsCompactButtonText: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 0.9,
    textAlign: "center",
    includeFontPadding: false,
    lineHeight: 12
  },
  settingsQuickGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 9
  },
  settingsQuickAction: {
    width: "48%",
    minHeight: 104,
    padding: 12,
    borderRadius: 15,
    borderWidth: 1,
    borderColor: accent14,
    backgroundColor: softPanel
  },
  settingsQuickIcon: {
    width: 34,
    height: 34,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 9,
    backgroundColor: accent10
  },
  settingsQuickLabel: {
    color: palette.text,
    fontSize: 13,
    fontWeight: "800"
  },
  settingsQuickValue: {
    marginTop: 4,
    color: palette.textMuted,
    fontSize: 11,
    lineHeight: 15
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
    borderColor: accent14,
    backgroundColor: softPanel
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
    backgroundColor: accent10
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
    borderColor: accent14,
    backgroundColor: accent06
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
    backgroundColor: accent10
  },
  hiddenToolCopy: {
    flex: 1,
    minWidth: 0
  },
  hiddenToolTitle: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 16,
    fontWeight: "800",
    letterSpacing: 0.3
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
    backgroundColor: softPanelStrong
  },
  hiddenToolBackText: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 9,
    fontWeight: "700",
    letterSpacing: 0.8
  },
  supportFooter: {
    alignSelf: "center",
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 7,
    marginTop: 4,
    marginBottom: 18,
    paddingHorizontal: 13,
    paddingVertical: 8,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: warn18,
    backgroundColor: warn07,
    opacity: 0.88
  },
  supportFooterText: {
    fontFamily: mono,
    color: palette.amber,
    fontSize: 9,
    fontWeight: "800",
    letterSpacing: 0.9,
    includeFontPadding: false,
    lineHeight: 11,
    textTransform: "uppercase"
  },
  supportHero: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    padding: 14,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: warn18,
    backgroundColor: warn07
  },
  supportHeroIcon: {
    width: 44,
    height: 44,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: warn22,
    backgroundColor: warn08
  },
  supportHeroCopy: {
    flex: 1,
    minWidth: 0
  },
  supportHeroTitle: {
    color: palette.text,
    fontSize: 14,
    fontWeight: "800",
    lineHeight: 19
  },
  supportHeroBody: {
    marginTop: 3,
    color: palette.textMuted,
    fontSize: 12,
    lineHeight: 17
  },
  supportTierGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 9,
    marginTop: 14
  },
  supportTierCard: {
    width: "48%",
    minHeight: 94,
    padding: 12,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: accent14,
    backgroundColor: softPanel
  },
  supportTierTop: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 8
  },
  supportTierAmount: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 22,
    fontWeight: "900",
    includeFontPadding: false,
    lineHeight: 26
  },
  supportTierStatus: {
    paddingHorizontal: 7,
    paddingVertical: 3,
    borderRadius: 999,
    overflow: "hidden",
    backgroundColor: warn08,
    fontFamily: mono,
    color: palette.amber,
    fontSize: 7,
    fontWeight: "900",
    letterSpacing: 0.7,
    textTransform: "uppercase"
  },
  supportTierLabel: {
    marginTop: 12,
    color: palette.textMuted,
    fontSize: 12,
    fontWeight: "800",
    lineHeight: 16
  },
  supportMessage: {
    marginTop: 12,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: warn18,
    backgroundColor: warn07,
    color: palette.text,
    fontSize: 12,
    lineHeight: 18
  },
  supportFinePrint: {
    marginTop: 12,
    color: palette.textMuted,
    fontSize: 11,
    lineHeight: 16,
    textAlign: "center"
  },
  supportDevFallback: {
    alignSelf: "center",
    minHeight: 34,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 7,
    marginTop: 12,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: hairline,
    backgroundColor: softPanel
  },
  supportDevFallbackText: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 8,
    fontWeight: "900",
    letterSpacing: 0.8,
    includeFontPadding: false,
    lineHeight: 10
  },
  serverInput: {
    minHeight: 46,
    paddingHorizontal: 12,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: hairline,
    color: palette.text,
    backgroundColor: fieldPanel,
    fontFamily: mono,
    fontSize: 12
  },
  connectButton: {
    marginTop: 10,
    minHeight: 44,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    paddingHorizontal: 14,
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
    color: onGreenText,
    fontWeight: "700",
    fontSize: 11,
    letterSpacing: 1,
    textAlign: "center",
    includeFontPadding: false,
    lineHeight: 13
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
    borderTopColor: palette.lineSoft
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
  docsCard: {
    marginHorizontal: 12,
    padding: 16,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: accent14,
    backgroundColor: palette.row
  },
  docTocPill: {
    alignSelf: "flex-start",
    minHeight: 34,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginBottom: 12,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: accent18,
    backgroundColor: accent08
  },
  docTocPillText: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 1,
    includeFontPadding: false,
    lineHeight: 12
  },
  docTocPillCount: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 9,
    fontWeight: "800",
    letterSpacing: 0.8,
    includeFontPadding: false,
    lineHeight: 11
  },
  docTocSheet: {
    maxHeight: "72%",
    marginHorizontal: 12,
    marginBottom: 12,
    borderRadius: 24,
    borderWidth: 1,
    borderColor: accent16,
    backgroundColor: palette.shell,
    paddingTop: 10,
    overflow: "hidden"
  },
  docTocHeader: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 12,
    paddingHorizontal: 18,
    paddingTop: 16,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: palette.lineSoft
  },
  docTocContent: {
    padding: 14,
    paddingBottom: 24,
    gap: 8
  },
  docTocItem: {
    minHeight: 48,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: accent14,
    backgroundColor: softPanel
  },
  docTocItemNested: {
    marginLeft: 14,
    backgroundColor: softPanelStrong
  },
  docTocItemLevel: {
    width: 24,
    fontFamily: mono,
    color: palette.green,
    fontSize: 9,
    fontWeight: "900",
    letterSpacing: 0.8,
    includeFontPadding: false
  },
  docTocItemText: {
    flex: 1,
    minWidth: 0,
    color: palette.text,
    fontSize: 13,
    fontWeight: "700",
    lineHeight: 18
  },
  docTitle: {
    marginBottom: 12,
    color: palette.text,
    fontSize: 24,
    fontWeight: "900",
    letterSpacing: 0.3
  },
  docHeading: {
    marginTop: 16,
    marginBottom: 8,
    fontFamily: mono,
    color: palette.blue,
    fontSize: 14,
    fontWeight: "800",
    letterSpacing: 0.8
  },
  docSubheading: {
    marginTop: 12,
    marginBottom: 6,
    color: palette.text,
    fontSize: 13,
    fontWeight: "800"
  },
  docBody: {
    color: palette.textMuted,
    fontSize: 13,
    lineHeight: 20
  },
  docBulletRow: {
    flexDirection: "row",
    gap: 8,
    marginVertical: 3
  },
  docBulletMark: {
    width: 12,
    color: palette.green,
    fontFamily: mono,
    fontSize: 12,
    fontWeight: "800",
    lineHeight: 20
  },
  docCodeBlock: {
    marginVertical: 8,
    padding: 12,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: accent14,
    backgroundColor: fieldPanel
  },
  docCodeText: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 11,
    lineHeight: 17
  },
  docSpacer: {
    height: 8
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
    borderColor: accent14,
    backgroundColor: fieldPanel
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
    backgroundColor: success10,
    borderWidth: 1,
    borderColor: success18
  },
  feedbackMessageError: {
    color: palette.red,
    backgroundColor: error10,
    borderWidth: 1,
    borderColor: error18
  },
  feedbackSupportHint: {
    marginTop: 8,
    minHeight: 34,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    paddingHorizontal: 11,
    paddingVertical: 8,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: warn18,
    backgroundColor: warn07
  },
  feedbackSupportText: {
    flex: 1,
    minWidth: 0,
    color: palette.textMuted,
    fontSize: 11
  },
  feedbackSupportAction: {
    fontFamily: mono,
    color: palette.amber,
    fontSize: 9,
    fontWeight: "900",
    letterSpacing: 0.9,
    includeFontPadding: false,
    lineHeight: 11
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
    borderTopColor: palette.lineSoft,
    backgroundColor: palette.header
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
    borderColor: accent18
  },
  navIconActive: {
    borderColor: accent42,
    backgroundColor: accent12
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
  navDot: {
    width: 4,
    height: 4,
    borderRadius: 2,
    backgroundColor: palette.blue,
    marginTop: 3
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
    borderColor: accent16,
    backgroundColor: modalPanel,
    paddingTop: 10
  },
  actionSheetCard: {
    marginHorizontal: 12,
    marginBottom: 12,
    padding: 18,
    borderRadius: 24,
    borderWidth: 1,
    borderColor: accent16,
    backgroundColor: modalPanel
  },
  actionSheetTitle: {
    marginTop: 8,
    fontFamily: mono,
    color: palette.text,
    fontSize: 20,
    fontWeight: "800",
    letterSpacing: 0.4
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
    borderColor: hairlineSoft,
    backgroundColor: softPanel
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
    backgroundColor: handleColor
  },
  sheetHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: 12,
    paddingHorizontal: 18,
    paddingTop: 16,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: palette.lineSoft
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
    fontFamily: mono,
    color: palette.text,
    fontSize: 20,
    fontWeight: "800",
    letterSpacing: 0.4
  },
  sheetSubtitle: {
    marginTop: 4,
    color: palette.textMuted,
    fontSize: 12
  },
  sheetActions: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8
  },
  sheetAction: {
    minHeight: 34,
    minWidth: 66,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: accent18,
    backgroundColor: accent08
  },
  sheetActionText: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 1,
    textAlign: "center",
    includeFontPadding: false,
    lineHeight: 12
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
    flexWrap: "wrap",
    gap: 8,
    marginBottom: 16
  },
  sheetSummaryText: {
    flex: 1,
    minWidth: 120,
    color: palette.textMuted,
    fontSize: 12
  },
  sheetSummaryBadge: {
    fontFamily: mono,
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 0.6,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
    overflow: "hidden"
  },
  sheetSummaryGateBadge: {
    color: palette.blue,
    backgroundColor: accent08,
    borderWidth: 1,
    borderColor: accent18
  },
  sheetDelayBadgeEarly: {
    color: palette.green,
    backgroundColor: success08,
    borderWidth: 1,
    borderColor: success25
  },
  sheetDelayBadgeOnTime: {
    color: palette.text,
    backgroundColor: softPanelStrong,
    borderWidth: 1,
    borderColor: hairline
  },
  sheetDelayBadgeWarn: {
    color: palette.amber,
    backgroundColor: warn07,
    borderWidth: 1,
    borderColor: warn24
  },
  sheetDelayBadgeBad: {
    color: palette.red,
    backgroundColor: error08,
    borderWidth: 1,
    borderColor: error18
  },
  sheetSkeleton: {
    paddingTop: 4
  },
  sheetSkeletonBar: {
    height: 18,
    borderRadius: 6,
    backgroundColor: softPanelStrong
  },
  sheetSkeletonCard: {
    flex: 1,
    height: 56,
    borderRadius: 14,
    backgroundColor: softPanelStrong
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
    borderColor: hairlineSoft,
    backgroundColor: softPanel
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
    borderTopColor: palette.lineSoft
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
  configSheetKeyboard: {
    flex: 1
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
    backgroundColor: handleColor
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
    flexGrow: 0,
    paddingHorizontal: 20
  },
  configSheetScrollContent: {
    paddingBottom: 48
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
    backgroundColor: fieldPanel,
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
    backgroundColor: accent10
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
    backgroundColor: success08,
    borderWidth: 1,
    borderColor: success18
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
    minHeight: 42,
    paddingVertical: 10,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: softPanel
  },
  configSegOptionActive: {
    backgroundColor: accent16
  },
  configSegText: {
    fontFamily: mono,
    fontSize: 11,
    color: palette.textMuted,
    fontWeight: "700",
    letterSpacing: 0.6,
    textAlign: "center",
    includeFontPadding: false,
    lineHeight: 13
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
    minHeight: 38,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: palette.line,
    backgroundColor: softPanel
  },
  configIntervalCellActive: {
    borderColor: accent40,
    backgroundColor: accent12
  },
  configIntervalText: {
    fontFamily: mono,
    fontSize: 12,
    color: palette.textMuted,
    textAlign: "center",
    includeFontPadding: false,
    lineHeight: 14
  },
  configIntervalTextActive: {
    color: palette.blue2,
    fontWeight: "700"
  },
  configPolicyText: {
    color: palette.textMuted,
    fontSize: 11,
    lineHeight: 16,
    marginTop: 8
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
    backgroundColor: fieldPanel,
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
    minHeight: 42,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 10,
    backgroundColor: accent16,
    borderWidth: 1,
    borderColor: accent30
  },
  configSaveBtnDisabled: {
    opacity: 0.35
  },
  configSaveBtnText: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 0.6,
    textAlign: "center",
    includeFontPadding: false,
    lineHeight: 14
  },
  configErrorText: {
    color: palette.red,
    fontSize: 12,
    marginTop: 10,
    marginBottom: 4
  },
  configApplyBtn: {
    marginTop: 16,
    minHeight: 50,
    flexDirection: "row",
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
    color: onBlueText,
    fontSize: 13,
    fontWeight: "800",
    letterSpacing: 1.2,
    textAlign: "center",
    includeFontPadding: false,
    lineHeight: 15
  },
  scopeFooter: {
    marginTop: 12,
    gap: 10
  },
  scopeHint: {
    color: palette.textMuted,
    fontSize: 11
  },
  scopeGroundStatus: {
    marginTop: -6,
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 9,
    fontWeight: "700",
    letterSpacing: 0.8,
    textTransform: "uppercase"
  },
  scopeGroundStatusWarn: {
    color: palette.amber
  },
  scopeChipRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8
  },
  scopeChip: {
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: accent18,
    backgroundColor: accent06
  },
  scopeChipActive: {
    borderColor: accent42,
    backgroundColor: accent12
  },
  scopeChipText: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.7
  },
  scopeChipTextActive: {
    color: palette.blue
  },
  matrixPresetRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginTop: 14
  },
  matrixPresetChip: {
    width: "31.5%",
    minWidth: 96,
    minHeight: 76,
    justifyContent: "center",
    paddingHorizontal: 10,
    paddingVertical: 10,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: accent14,
    backgroundColor: accent06
  },
  matrixPresetChipActive: {
    borderColor: success25,
    backgroundColor: success08
  },
  matrixPresetChipDisabled: {
    opacity: 0.45
  },
  matrixPresetTop: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 6
  },
  matrixPresetLabel: {
    flex: 1,
    minWidth: 0,
    color: palette.text,
    fontSize: 11,
    fontWeight: "800",
    includeFontPadding: false,
    lineHeight: 14
  },
  matrixPresetLabelActive: {
    color: palette.green
  },
  matrixPresetMeta: {
    marginTop: 6,
    color: palette.textMuted,
    fontSize: 10,
    lineHeight: 14
  },
  matrixActionRow: {
    flexDirection: "row",
    gap: 10,
    marginTop: 14
  },
  matrixActionButton: {
    minHeight: 44,
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    borderRadius: 10,
    paddingHorizontal: 12,
    borderWidth: 1
  },
  matrixActionPrimary: {
    backgroundColor: palette.blue,
    borderColor: accent30
  },
  matrixActionSecondary: {
    backgroundColor: softPanel,
    borderColor: accent16
  },
  matrixActionPrimaryText: {
    fontFamily: mono,
    color: onBlueText,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.8,
    textAlign: "center",
    includeFontPadding: false,
    lineHeight: 13
  },
  matrixActionSecondaryText: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.8,
    textAlign: "center",
    includeFontPadding: false,
    lineHeight: 13
  },
  diagnosticsBackdrop: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 22,
    backgroundColor: "rgba(0,0,0,0.62)"
  },
  diagnosticsCard: {
    width: "100%",
    maxWidth: 430,
    borderRadius: 22,
    borderWidth: 1,
    borderColor: accent20,
    backgroundColor: palette.rowAlt,
    padding: 20,
    shadowColor: "#000",
    shadowOpacity: 0.35,
    shadowRadius: 22,
    shadowOffset: { width: 0, height: 14 }
  },
  diagnosticsEyebrow: {
    fontFamily: mono,
    color: palette.green,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 1.2
  },
  diagnosticsTitle: {
    marginTop: 8,
    fontFamily: mono,
    color: palette.text,
    fontSize: 21,
    fontWeight: "800",
    letterSpacing: 0.4
  },
  diagnosticsBody: {
    marginTop: 10,
    color: palette.textMuted,
    fontSize: 13,
    lineHeight: 19
  },
  diagnosticsOptionStack: {
    gap: 10,
    marginTop: 16
  },
  diagnosticsOption: {
    borderRadius: 14,
    borderWidth: 1,
    borderColor: accent18,
    backgroundColor: accent06,
    padding: 13
  },
  diagnosticsOptionTitle: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 0.9
  },
  diagnosticsOptionBody: {
    marginTop: 5,
    color: palette.textMuted,
    fontSize: 12,
    lineHeight: 17
  },
  appearancePreview: {
    marginTop: 14,
    padding: 12,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: accent14,
    backgroundColor: accent06
  },
  appearancePreviewCard: {
    padding: 12,
    borderRadius: 10,
    backgroundColor: palette.row
  },
  appearancePreviewTitle: {
    fontFamily: brand,
    color: palette.blue2,
    fontSize: 11,
    fontWeight: "400",
    letterSpacing: 0.6
  },
  companionSetupBrandText: {
    fontFamily: brand,
    fontWeight: "400",
    letterSpacing: 0.8
  },
  companionSetupEyebrowSuffix: {
    fontFamily: brand,
    fontWeight: "400",
    letterSpacing: 0.8
  },
  appearancePreviewBody: {
    marginTop: 5,
    color: palette.textMuted,
    fontSize: 11,
    lineHeight: 16
  },
  appearancePreviewRail: {
    flexDirection: "row",
    gap: 10,
    marginTop: 12
  },
  appearancePreviewDot: {
    width: 16,
    height: 16,
    borderRadius: 999
  },
  });
}

let styles = createStyles();
setStyleBridge(styles, palette);
