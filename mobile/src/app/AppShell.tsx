import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Animated,
  Linking,
  Modal,
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
import { accessibleButton, tapTargetHitSlop, useReducedMotionPreference } from "../accessibility/mobileA11y";
import { AirportConfigSheet, CompanionSetupScreen, ConnectPrompt, ControlScreen, FidsScreen, FlightActionSheet, FlightDetailSheet, FullscreenFidsDisplay, Header, HistoryScreen, RadarScreen, ScreenActivity, ScreenError, StandaloneSettingsScreen, SupportSheet, type ActivityStatus, type ConnectionState } from "../screens/AppScreens";
import { ACTION_ICONS, LocalFlightIcon, SUPPORT_ICONS } from "../theme/icons";
import {
  getConnections,
  getConfig,
  getFids,
  getHistory,
  getHistorySummary,
  getLastCompanionTransport,
  getMobileSummary,
  configureRemoteCompanionGrant,
  getRadar,
  getRadarGround,
  normalizeServerUrl,
  patchConfig,
  resolveAirport,
  restartScheduler,
  sendCompanionCheckin,
  submitFeedback,
  testConnection,
  wsUrl
} from "../api/client";
import { completeRemoteCompanionPairing } from "../api/remoteCompanion";
import {
  getStandaloneRadarGround,
  getStandaloneFids,
  getStandaloneRadar,
  getStandaloneSummary,
  submitStandaloneFeedback,
  type StandaloneCredentials
} from "../api/standalone";
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
  formatAirportLocalTime,
  formatUtc,
  hexToRgba
} from "../domain/formatting";
import {
  pairingFingerprintProblem,
  pairingServerUrlProblem,
  parsePairingLink,
  type PairingLinkResult,
  type RemoteCompanionInvite
} from "../domain/pairing";
import type {
  FeedbackTone,
  HistoryWindow,
  RadarRadius,
  RefreshOptions,
  Screen
} from "../domain/types";
import {
  buildWidgetExchangeSnapshot,
  deriveWidgetPreviewSnapshot
} from "../domain/widgets";
import { useFlightDetail } from "../hooks/useFlightDetail";
import { type LaunchHydration, useLaunchOverlay } from "../hooks/useLaunchOverlay";
import { useMatrixCompanion } from "../hooks/useMatrixCompanion";
import {
  type ConfigProfile,
  completeMobileSetupState,
  completeStandaloneMobileSetupState,
  incompleteMobileSetupState,
  isMobileSetupComplete,
  saveCachedLanAirport,
  saveCachedLanConfig,
  DEFAULT_WIDGET_PREFERENCES,
  loadRadarDrawingLayers,
  loadWeatherDisplayMode,
  loadWidgetPreferences,
  type MobileRadarDrawingLayers,
  type MobileDiagnosticsMode,
  type MobileSetupState,
  type RemoteCompanionGrant,
  type MobileWidgetPreferences,
  type MobileWeatherDisplayMode,
  saveMobileDiagnosticsMode,
  saveMobileRelayActivationToken,
  saveMobileSetupState,
  savePinnedFlight,
  saveRadarDrawingLayers,
  saveServerUrl,
  saveStandaloneAirport,
  saveWeatherDisplayMode,
  saveWidgetPreferences
} from "../storage/settings";
import { clearStandaloneHistory, getStandaloneHistory, getStandaloneHistorySummary, storeStandaloneFidsRows } from "../storage/standaloneHistory";
import { writeWidgetSnapshot } from "../storage/widgetSnapshot";
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

type SetupSuccessState = {
  mode: "lan_companion" | "standalone";
  title: string;
  body: string;
  meta: string;
};

type WidgetSnapshotStatus = {
  state: "waiting" | "ready" | "stale" | "error";
  detail: string;
};

type WidgetPendingAirport = {
  key: string;
  baselineLastSuccess: string;
};

void SplashScreen.preventAutoHideAsync().catch(() => {
  // Ignore duplicate registration during fast refresh.
});
SplashScreen.setOptions({
  duration: 320,
  fade: true
});

function airportMatchesConfig(airport: AirportResolved | null, config: AppConfig | null | undefined): boolean {
  if (!airport || !config) return false;
  return Boolean(
    (airport.iata && airport.iata === config.airport_iata) ||
    (airport.icao && airport.icao === config.airport_icao)
  );
}

function airportFallbackFromConfig(config: AppConfig | null | undefined): AirportResolved | null {
  const iata = (config?.airport_iata || "").trim().toUpperCase();
  const icao = (config?.airport_icao || "").trim().toUpperCase();
  if (!iata && !icao) return null;
  const displayName = (config?.display_name || "").trim();
  const usefulName = displayName && displayName !== "Local Flight"
    ? displayName
    : [iata, icao].filter(Boolean).join(" / ");
  return {
    iata,
    icao,
    name: usefulName,
    city: "",
    country: "",
    timezone: config?.timezone || undefined,
    type: "large_airport"
  };
}

function widgetUpdatedLabel(value?: string | null): string {
  const timestamp = Date.parse(value || "");
  if (!Number.isFinite(timestamp)) {
    return "Waiting";
  }
  const diffSeconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000));
  if (diffSeconds < 60) return "Updated now";
  const diffMinutes = Math.round(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${Math.round(diffHours / 24)}d ago`;
}

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
  if (target === "control") {
    return {
      label: "Syncing Control",
      detail: "Reading host status and Matrix board live settings."
    };
  }
  return {
    label: "Talking to Local Flight",
    detail: "Checking the connected server over your LAN."
  };
}

function screenNeedsDashboard(target: Screen, standalone: boolean): boolean {
  return standalone
    ? target === "settings"
    : target === "control";
}

export function AppShell() {
  const { appearance, themeMode, skin, setThemeMode, setSkin } = useMobileTheme();
  const layout = useResponsiveLayout();
  const reduceMotion = useReducedMotionPreference();
  const landscapeFidsActive = layout.isLandscape;
  const insets = useSafeAreaInsets();
  const [screen, setScreen] = useState<Screen>("fids");
  const [view, setView] = useState<FlightView>("departures");
  const [historyDirection, setHistoryDirection] = useState<HistoryDirection>("both");
  const [historyHours, setHistoryHours] = useState<HistoryWindow>(24);
  const [historyCallsign, setHistoryCallsign] = useState("");
  const [historyAirline, setHistoryAirline] = useState("");
  const [historySummary, setHistorySummary] = useState<HistorySummary | null>(null);
  const [radarRadius, setRadarRadius] = useState<RadarRadius>(20);
  const [serverUrl, setServerUrl] = useState("");
  const [draftUrl, setDraftUrl] = useState("");
  const [connected, setConnected] = useState(false);
  const [companionTransport, setCompanionTransport] = useState<"lan" | "remote">("lan");
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [activity, setActivity] = useState<ActivityStatus | null>(null);
  const [schedulerRestarting, setSchedulerRestarting] = useState(false);
  const [schedulerMessage, setSchedulerMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [utcTime, setUtcTime] = useState(formatUtc());
  const [localTime, setLocalTime] = useState(formatAirportLocalTime("UTC"));
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
  const [actionRow, setActionRow] = useState<FidsRow | null>(null);
  const [configSheetVisible, setConfigSheetVisible] = useState(false);
  const [profiles, setProfiles] = useState<ConfigProfile[]>([]);
  const [applyingProfileId, setApplyingProfileId] = useState<string | null>(null);
  const [supportVisible, setSupportVisible] = useState(false);
  const [companionIdentity, setCompanionIdentity] = useState<CompanionIdentity | null>(null);
  const [mobileDiagnosticsMode, setMobileDiagnosticsMode] = useState<MobileDiagnosticsMode>("unset");
  const [weatherDisplayMode, setWeatherDisplayMode] = useState<MobileWeatherDisplayMode>("passenger");
  const [widgetPreferences, setWidgetPreferences] = useState<MobileWidgetPreferences>(DEFAULT_WIDGET_PREFERENCES);
  const [widgetSnapshotStatus, setWidgetSnapshotStatus] = useState<WidgetSnapshotStatus>({
    state: "waiting",
    detail: "setup"
  });
  const [widgetPendingAirport, setWidgetPendingAirport] = useState<WidgetPendingAirport | null>(null);
  const [radarDrawingLayers, setRadarDrawingLayers] = useState<MobileRadarDrawingLayers>({
    runways: true,
    surface: true,
    terrain: false
  });
  const [mobileSetupState, setMobileSetupState] = useState<MobileSetupState>(() => incompleteMobileSetupState());
  const [launchHydrated, setLaunchHydrated] = useState(false);
  const [pairingUrl, setPairingUrl] = useState("");
  const [pairingExpectedServerFingerprint, setPairingExpectedServerFingerprint] = useState("");
  const [pairingRemoteInvite, setPairingRemoteInvite] = useState<RemoteCompanionInvite | null>(null);
  const [pendingRemoteCompanionGrant, setPendingRemoteCompanionGrant] = useState<RemoteCompanionGrant | null>(null);
  const [pairingNonce, setPairingNonce] = useState(0);
  const [pairingNotice, setPairingNotice] = useState<string | null>(null);
  const [serverPanelRequest, setServerPanelRequest] = useState(0);
  const [setupSuccess, setSetupSuccess] = useState<SetupSuccessState | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const initialPairingUrlRef = useRef<string | null>(null);
  const radarGroundCacheRef = useRef<Map<string, RadarMapResponse>>(new Map());
  const refreshInFlightRef = useRef<Map<string, Promise<void>>>(new Map());
  const lastRadarRefreshAfterRef = useRef<number | null>(null);
  const widgetSnapshotWasReadyRef = useRef(false);
  const previousWidgetAirportKeyRef = useRef("");
  const screenOpacity = useRef(new Animated.Value(1)).current;
  const screenLift = useRef(new Animated.Value(0)).current;
  const snapshotPulse = useRef(new Animated.Value(0)).current;
  const flightDetail = useFlightDetail(serverUrl, setError);
  const matrix = useMatrixCompanion(serverUrl);
  const {
    runtime: matrixRuntime,
    dirty: matrixDirty,
    saving: matrixSaving,
    saveMessage: matrixSaveMessage,
    saveTone: matrixSaveTone,
    fetchRuntime: fetchMatrixRuntime,
    updateDraft: updateMatrixDraft,
    resetDraft: resetMatrixDraft,
    saveDraft: saveMatrixDraftNow
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

  useEffect(() => {
    if (reduceMotion) {
      screenOpacity.setValue(1);
      screenLift.setValue(0);
      return;
    }
    screenOpacity.setValue(0);
    screenLift.setValue(4);
    Animated.parallel([
      Animated.timing(screenOpacity, {
        toValue: 1,
        duration: 150,
        useNativeDriver: true
      }),
      Animated.spring(screenLift, {
        toValue: 0,
        damping: 18,
        stiffness: 190,
        mass: 0.7,
        useNativeDriver: true
      })
    ]).start();
  }, [screen, screenLift, screenOpacity, reduceMotion]);

  const onLaunchHydrated = useCallback(
    ({
      savedUrl,
      savedPin,
      savedProfiles,
      savedConfig,
      savedAirport,
      identity,
      mobileDiagnosticsMode: hydratedDiagnosticsMode,
      setupState
    }: LaunchHydration) => {
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
      if (setupState.mode === "lan_companion" && savedConfig) {
        setSnapshot((prev) => ({ ...prev, config: savedConfig }));
      }
      if (setupState.mode === "lan_companion" && savedAirport) {
        setAirportDetail(savedAirport);
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
  const dismissSetupSuccess = useCallback(() => setSetupSuccess(null), []);
  const isStandalone = mobileSetupState.mode === "standalone";
  useEffect(() => {
    configureRemoteCompanionGrant(isStandalone ? null : mobileSetupState.remoteCompanion);
  }, [isStandalone, mobileSetupState.remoteCompanion]);
  const standaloneCredentials: StandaloneCredentials | null = useMemo(() =>
    isStandalone &&
    mobileSetupState.relayInstallId &&
    mobileSetupState.relayActivationToken &&
    mobileSetupState.standaloneAirport
      ? {
          installId: mobileSetupState.relayInstallId,
          activationToken: mobileSetupState.relayActivationToken,
          airport: mobileSetupState.standaloneAirport,
          diagnosticsMode: mobileDiagnosticsMode
        }
      : null,
    [
      isStandalone,
      mobileDiagnosticsMode,
      mobileSetupState.relayActivationToken,
      mobileSetupState.relayInstallId,
      mobileSetupState.standaloneAirport
    ]
  );
  const dataReady = isStandalone ? Boolean(standaloneCredentials) : Boolean(serverUrl);
  const standaloneAirportDetail: AirportResolved | null = standaloneCredentials
    ? { ...standaloneCredentials.airport, type: "large_airport" }
    : null;
  const matchingStandaloneAirportDetail =
    airportDetail &&
    standaloneAirportDetail &&
    (
      (airportDetail.iata && airportDetail.iata === standaloneAirportDetail.iata) ||
      (airportDetail.icao && airportDetail.icao === standaloneAirportDetail.icao)
    )
      ? airportDetail
      : null;
  const matchingLanAirportDetail =
    airportDetail &&
    (
      (!snapshot.config?.airport_iata && !snapshot.config?.airport_icao) ||
      (airportDetail.iata && airportDetail.iata === (snapshot.config?.airport_iata || "")) ||
      (airportDetail.icao && airportDetail.icao === (snapshot.config?.airport_icao || ""))
    )
      ? airportDetail
      : null;
  const currentAirportDetail = isStandalone
    ? matchingStandaloneAirportDetail || standaloneAirportDetail
    : matchingLanAirportDetail;
  const airportTimeZone = currentAirportDetail?.timezone || snapshot.config?.timezone || "UTC";

  useEffect(() => {
    const updateClock = () => {
      setUtcTime(formatUtc());
      setLocalTime(formatAirportLocalTime(airportTimeZone));
    };
    updateClock();
    const timer = setInterval(updateClock, 1000);
    return () => clearInterval(timer);
  }, [airportTimeZone]);

  const handlePairingUrl = useCallback((incomingUrl: string) => {
    const parsed = parsePairingLink(incomingUrl);
    if (!parsed) {
      return;
    }

    const problem = pairingServerUrlProblem(parsed.serverUrl);
    if (problem) {
      setError(problem);
      hapticWarning();
      return;
    }

    setDraftUrl(parsed.serverUrl);
    setPairingUrl(parsed.serverUrl);
    setPairingExpectedServerFingerprint(parsed.expectedServerFingerprint || "");
    setPairingRemoteInvite(parsed.remoteCompanionInvite || null);
    setPairingNonce((value) => value + 1);
    setActionRow(null);
    setConfigSheetVisible(false);
    closeFlightDetail();

    if (mobileSetupComplete) {
      setScreen("control");
      setServerPanelRequest((value) => value + 1);
      setPairingNotice(
        parsed.remoteCompanionInvite
          ? `Remote Companion invite loaded from ${parsed.source.toUpperCase()}. Tap CONNECT while on this LAN to pair relay fallback.`
          : `Pairing link loaded from ${parsed.source.toUpperCase()}. Tap CONNECT to pair this device with ${parsed.serverUrl}.`
      );
    } else {
      setError(null);
      setPairingNotice(null);
    }
    hapticLight();
  }, [closeFlightDetail, mobileSetupComplete]);

  useEffect(() => {
    let alive = true;
    void Linking.getInitialURL().then((url) => {
      if (alive && url && initialPairingUrlRef.current !== url) {
        initialPairingUrlRef.current = url;
        handlePairingUrl(url);
      }
    });
    const subscription = Linking.addEventListener("url", (event) => {
      handlePairingUrl(event.url);
    });
    return () => {
      alive = false;
      subscription.remove();
    };
  }, [handlePairingUrl]);

  const chooseMobileDiagnosticsMode = useCallback(async (mode: MobileDiagnosticsMode) => {
    await saveMobileDiagnosticsMode(mode);
    setMobileDiagnosticsMode(mode);
    if (isStandalone && mobileSetupState.relayInstallId && mobileSetupState.relayActivationToken && mobileSetupState.standaloneAirport && mode !== "unset") {
      const nextSetupState = completeStandaloneMobileSetupState({
        relayInstallId: mobileSetupState.relayInstallId,
        relayActivationToken: mobileSetupState.relayActivationToken,
        airport: mobileSetupState.standaloneAirport,
        diagnosticsMode: mode
      });
      await saveMobileSetupState(nextSetupState);
      setMobileSetupState(nextSetupState);
      return;
    }
    if (serverUrl && mode !== "unset") {
      const nextSetupState = completeMobileSetupState(
        serverUrl,
        mode,
        mobileSetupState.remoteCompanion || pendingRemoteCompanionGrant
      );
      await saveMobileSetupState(nextSetupState);
      setMobileSetupState(nextSetupState);
    }
  }, [isStandalone, mobileSetupState, pendingRemoteCompanionGrant, serverUrl]);

  useEffect(() => {
    let alive = true;
    void Promise.all([loadWeatherDisplayMode(), loadRadarDrawingLayers(), loadWidgetPreferences()]).then(([mode, layers, widgets]) => {
      if (alive) {
        setWeatherDisplayMode(mode);
        setRadarDrawingLayers(layers);
        setWidgetPreferences(widgets);
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

  const chooseWidgetPreferences = useCallback(async (next: MobileWidgetPreferences) => {
    const normalized = await saveWidgetPreferences(next);
    setWidgetPreferences(normalized);
  }, []);

  const fetchDashboard = useCallback(async (normalized: string) => {
    if (standaloneCredentials) {
      const summary = await getStandaloneSummary(standaloneCredentials);
      const config = summary.config;
      if (!config) {
        throw new Error("Standalone relay summary did not include config.");
      }
      setAirportDetail({
        ...standaloneCredentials.airport,
        type: "large_airport"
      });
      setSnapshot(summary);
      setConnected(true);
      return;
    }

    const summary = await getMobileSummary(normalized);
    let config = summary.config;
    if (!config) {
      throw new Error("Local Flight host summary did not include config.");
    }
    if (!config.airport_iata && !config.airport_icao) {
      try {
        config = await getConfig(normalized);
        summary.config = config;
      } catch {
        // Keep the summary payload if the companion-only config fallback is not available.
      }
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

    const fallbackAirport = airportFallbackFromConfig(config);
    setAirportDetail((previous) =>
      resolvedAirport || (airportMatchesConfig(previous, config) ? previous : null) || fallbackAirport
    );
    setSnapshot(summary);
    await saveCachedLanConfig(config);
    if (resolvedAirport) {
      await saveCachedLanAirport(resolvedAirport);
    }
    setConnected(true);
  }, [standaloneCredentials]);

  const fetchFidsData = useCallback(async (normalized: string, nextView: FlightView) => {
    if (standaloneCredentials) {
      const fids = await getStandaloneFids(standaloneCredentials, nextView);
      setRows(fids);
      await storeStandaloneFidsRows(standaloneCredentials.airport, fids);
      return;
    }
    const fids = await getFids(normalized, nextView);
    setRows(fids);
  }, [standaloneCredentials]);

  const fetchHistoryData = useCallback(
    async (
      normalized: string,
      nextDirection: HistoryDirection,
      nextHours: HistoryWindow,
      nextCallsign = "",
      nextAirline = ""
    ) => {
      if (standaloneCredentials) {
        const [data, summary] = await Promise.all([
          getStandaloneHistory(standaloneCredentials.airport, {
            direction: nextDirection,
            hours: nextHours,
            limit: 120,
            callsign: nextCallsign,
            airline_iata: nextAirline
          }),
          getStandaloneHistorySummary(standaloneCredentials.airport, {
            hours: nextHours,
            direction: nextDirection,
            callsign: nextCallsign,
            airline_iata: nextAirline
          }).catch(() => null)
        ]);
        setHistoryData(data);
        setHistorySummary(summary);
        return;
      }
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
    [standaloneCredentials]
  );

  const fetchRadarData = useCallback(async (
    normalized: string,
    nextRadius: RadarRadius,
    forceGround = false
  ) => {
    setActivity({
      label: "Loading radar traffic",
      detail: standaloneCredentials
        ? `Asking the hosted relay for standalone tracks inside ${nextRadius} NM.`
        : `Asking the Local Flight server for tracks inside ${nextRadius} NM.`
    });
    if (standaloneCredentials) {
      const data = await getStandaloneRadar(standaloneCredentials, nextRadius);
      lastRadarRefreshAfterRef.current = Number(data.refresh_after_s || 0) || null;
      setRadarData(data);
      const cacheKey = [
        "standalone",
        standaloneCredentials.airport.iata || standaloneCredentials.airport.icao,
        nextRadius,
        Number(data.center?.lat || standaloneCredentials.airport.lat || 0).toFixed(5),
        Number(data.center?.lon || standaloneCredentials.airport.lon || 0).toFixed(5)
      ].join("|");
      const cachedGround = radarGroundCacheRef.current.get(cacheKey) || null;
      if (cachedGround && !forceGround) {
        setRadarGroundData(cachedGround);
        setRadarGroundError(null);
        return;
      }
      try {
        setActivity({
          label: "Loading runway and surface layer",
          detail: "Fetching the relay's shared airport surface snapshot."
        });
        const ground = await getStandaloneRadarGround(standaloneCredentials, Math.min(5, nextRadius));
        radarGroundCacheRef.current.set(cacheKey, ground);
        setRadarGroundData(ground);
        setRadarGroundError(null);
      } catch (exc) {
        setRadarGroundData(cachedGround);
        setRadarGroundError(cachedGround ? null : errorMessage(exc));
      }
      return;
    }
    const data = await getRadar(normalized, nextRadius);
    lastRadarRefreshAfterRef.current = Number(data.refresh_after_s || 0) || null;
    setRadarData(data);

    const cacheKey = [
      normalized,
      nextRadius,
      Number(data.center?.lat || 0).toFixed(5),
      Number(data.center?.lon || 0).toFixed(5),
      radarDrawingLayers.terrain ? "terrain" : "no-terrain"
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
      const ground = await getRadarGround(normalized, nextRadius, radarDrawingLayers.terrain);
      radarGroundCacheRef.current.set(cacheKey, ground);
      setRadarGroundData(ground);
      setRadarGroundError(null);
    } catch (exc) {
      setRadarGroundData(cachedGround);
      setRadarGroundError(cachedGround ? null : errorMessage(exc));
    }
  }, [radarDrawingLayers.terrain, standaloneCredentials]);

  const refreshScreen = useCallback(
    async ({
      nextUrl = serverUrl,
      target = screen,
      nextView = view,
      nextHistoryDirection = historyDirection,
      nextHistoryHours = historyHours,
      nextRadarRadius = radarRadius,
      forceRadarGround = false,
      includeDashboard = true
    }: RefreshOptions = {}) => {
      const normalized = normalizeServerUrl(nextUrl);
      if (!normalized && !standaloneCredentials) {
        setError(isStandalone ? "Finish Standalone setup before loading relay data." : "Enter the Local Flight server URL in Settings.");
        return;
      }
      const refreshKey = [
        normalized,
        target,
        nextView,
        nextHistoryDirection,
        nextHistoryHours,
        historyCallsign,
        historyAirline,
        nextRadarRadius,
        forceRadarGround ? "ground" : "normal",
        includeDashboard ? "dashboard" : "screen"
      ].join("|");
      const existing = refreshInFlightRef.current.get(refreshKey);
      if (existing) {
        await existing;
        return;
      }

      const task = (async () => {
        setRefreshing(true);
        setActivity(includeDashboard ? {
          label: "Talking to Local Flight",
          detail: "Checking server health, config, budget, and live connections."
        } : refreshActivityForTarget(target, landscapeFidsActive));
        setError(null);

        if (includeDashboard) {
          try {
            await fetchDashboard(normalized);
            if (!isStandalone) {
              setCompanionTransport(getLastCompanionTransport());
            }
          } catch (exc) {
            setConnected(false);
            setError(errorMessage(exc));
            return;
          }
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
          } else if (target === "control") {
            await fetchMatrixRuntime(normalized);
          }
          if (!isStandalone) {
            setCompanionTransport(getLastCompanionTransport());
          }
        } catch (exc) {
          setError(errorMessage(exc));
        } finally {
          setRefreshing(false);
          setActivity(null);
        }
      })();
      refreshInFlightRef.current.set(refreshKey, task);
      try {
        await task;
      } finally {
        refreshInFlightRef.current.delete(refreshKey);
      }
    },
    [
      fetchDashboard,
      fetchFidsData,
      fetchHistoryData,
      fetchMatrixRuntime,
      fetchRadarData,
      historyAirline,
      historyCallsign,
      historyDirection,
      historyHours,
      isStandalone,
      landscapeFidsActive,
      radarRadius,
      screen,
      standaloneCredentials,
      serverUrl,
      view
    ]
  );

  const connect = useCallback(async (
    candidateUrl = draftUrl,
    expectedServerFingerprint = "",
    remoteInvite: RemoteCompanionInvite | null = pairingRemoteInvite
  ) => {
    const normalized = normalizeServerUrl(candidateUrl);
    setLoading(true);
    setActivity({
      label: "Testing server URL",
      detail: "Asking the Local Flight server to confirm mobile access."
    });
    setError(null);

    try {
      if (expectedServerFingerprint) {
        const summary = await getMobileSummary(normalized);
        const fingerprintProblem = pairingFingerprintProblem(
          expectedServerFingerprint,
          summary.system?.install_id
        );
        if (fingerprintProblem) {
          throw new Error(fingerprintProblem);
        }
      } else {
        await testConnection(normalized);
      }
      const remoteGrant = remoteInvite
        ? await completeRemoteCompanionPairing(normalized, remoteInvite)
        : null;
      if (remoteGrant) {
        setPendingRemoteCompanionGrant(remoteGrant);
        configureRemoteCompanionGrant(remoteGrant);
      }
      await saveServerUrl(normalized);
      if (mobileDiagnosticsMode !== "unset") {
        const nextSetupState = completeMobileSetupState(normalized, mobileDiagnosticsMode, remoteGrant);
        await saveMobileSetupState(nextSetupState);
        setMobileSetupState(nextSetupState);
      }
      setServerUrl(normalized);
      setDraftUrl(normalized);
      setCompanionTransport("lan");
      setPairingNotice(null);
      setPairingUrl("");
      setPairingExpectedServerFingerprint("");
      setPairingRemoteInvite(null);
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
  }, [draftUrl, mobileDiagnosticsMode, pairingRemoteInvite]);

  const connectPairingUrl = useCallback((pairing: PairingLinkResult) => {
    setDraftUrl(pairing.serverUrl);
    setPairingUrl(pairing.serverUrl);
    setPairingExpectedServerFingerprint(pairing.expectedServerFingerprint || "");
    setPairingRemoteInvite(pairing.remoteCompanionInvite || null);
    setPairingNonce((value) => value + 1);
    setPairingNotice(
      pairing.remoteCompanionInvite
        ? `Remote Companion QR loaded. Connecting to ${pairing.serverUrl} while this phone is on the LAN.`
        : `Pairing QR loaded. Connecting this mobile app to ${pairing.serverUrl}.`
    );
    void connect(pairing.serverUrl, pairing.expectedServerFingerprint, pairing.remoteCompanionInvite || null);
  }, [connect]);

  const chooseRadarDrawingLayers = useCallback(async (next: MobileRadarDrawingLayers) => {
    const normalized = {
      runways: next.runways,
      surface: next.surface,
      terrain: isStandalone ? false : next.terrain
    };
    await saveRadarDrawingLayers(normalized);
    const terrainChanged = normalized.terrain !== radarDrawingLayers.terrain;
    setRadarDrawingLayers(normalized);
    if (screen === "radar" && dataReady && terrainChanged) {
      radarGroundCacheRef.current.clear();
      void refreshScreen({ target: "radar", forceRadarGround: true, includeDashboard: false });
    }
  }, [dataReady, isStandalone, radarDrawingLayers.terrain, refreshScreen, screen]);

  const completeCompanionSetup = useCallback(async ({
    mode,
    serverUrl: nextServerUrl,
    diagnosticsMode,
    config,
    relayInstallId,
    relayActivationToken,
    airport
  }: {
    mode: "lan_companion" | "standalone";
    serverUrl?: string;
    diagnosticsMode: MobileDiagnosticsMode;
    config?: AppConfig;
    relayInstallId?: string;
    relayActivationToken?: string;
    airport?: NonNullable<MobileSetupState["standaloneAirport"]>;
  }) => {
    if (mode === "standalone") {
      if (!relayInstallId || !relayActivationToken || !airport) {
        throw new Error("Standalone setup did not return a relay token and airport.");
      }
      const nextSetupState = completeStandaloneMobileSetupState({
        relayInstallId,
        relayActivationToken,
        airport,
        diagnosticsMode
      });
      await Promise.all([
        saveServerUrl(""),
        saveMobileRelayActivationToken(relayActivationToken),
        saveStandaloneAirport(airport),
        saveMobileDiagnosticsMode(diagnosticsMode),
        saveMobileSetupState(nextSetupState)
      ]);
      setServerUrl("");
      setDraftUrl("");
      setMobileDiagnosticsMode(diagnosticsMode);
      setMobileSetupState(nextSetupState);
      setAirportDetail({ ...airport, type: "large_airport" });
      setConnected(true);
      setError(null);
      setScreen("fids");
      setSetupSuccess({
        mode: "standalone",
        title: "You are ready",
        body: "Standalone board is set up for this phone.",
        meta: airport.iata || airport.icao || airport.name
      });
      hapticSuccess();
      return;
    }

    if (!nextServerUrl || !config) {
      throw new Error("Mobile setup did not return a server URL and config.");
    }
    const normalized = normalizeServerUrl(nextServerUrl);
    const remoteGrant = pendingRemoteCompanionGrant || (
      pairingRemoteInvite
        ? await completeRemoteCompanionPairing(normalized, pairingRemoteInvite)
        : null
    );
    if (remoteGrant) {
      configureRemoteCompanionGrant(remoteGrant);
      setPendingRemoteCompanionGrant(remoteGrant);
    }
    const nextSetupState = completeMobileSetupState(normalized, diagnosticsMode, remoteGrant);
    await Promise.all([
      saveServerUrl(normalized),
      saveMobileDiagnosticsMode(diagnosticsMode),
      saveMobileSetupState(nextSetupState),
      saveCachedLanConfig(config)
    ]);
    setServerUrl(normalized);
    setDraftUrl(normalized);
    setMobileDiagnosticsMode(diagnosticsMode);
    setMobileSetupState(nextSetupState);
    setSnapshot((prev) => ({ ...prev, config }));
    setConnected(true);
    setCompanionTransport("lan");
    setError(null);
    setPairingNotice(null);
    setPairingUrl("");
    setPairingRemoteInvite(null);
    setScreen("fids");
    setSetupSuccess({
      mode: "lan_companion",
      title: "You are connected",
      body: "This phone is paired with your Local Flight host.",
      meta: normalized
    });
    hapticSuccess();
    void refreshScreen({ nextUrl: normalized, target: "fids" });
  }, [pairingRemoteInvite, pendingRemoteCompanionGrant, refreshScreen]);

  const rerunCompanionSetup = useCallback(async () => {
    const nextSetupState = incompleteMobileSetupState(isStandalone ? "" : serverUrl, mobileDiagnosticsMode);
    await saveMobileSetupState(nextSetupState);
    setMobileSetupState(nextSetupState);
    if (isStandalone) {
      await Promise.all([
        saveMobileRelayActivationToken(""),
        saveStandaloneAirport(null),
        clearStandaloneHistory()
      ]);
      setConnected(false);
      setServerUrl("");
      setDraftUrl("");
    }
    setActionRow(null);
    setConfigSheetVisible(false);
    closeFlightDetail();
    setError(null);
    setSetupSuccess(null);
    setPendingRemoteCompanionGrant(null);
    setPairingRemoteInvite(null);
    configureRemoteCompanionGrant(null);
    setCompanionTransport("lan");
  }, [closeFlightDetail, isStandalone, mobileDiagnosticsMode, serverUrl]);

  const forgetRemoteCompanion = useCallback(async () => {
    if (isStandalone || !mobileSetupState.complete || mobileSetupState.mode !== "lan_companion") {
      return;
    }
    const nextSetupState = {
      ...mobileSetupState,
      remoteCompanion: null
    };
    await saveMobileSetupState(nextSetupState);
    setMobileSetupState(nextSetupState);
    setPendingRemoteCompanionGrant(null);
    configureRemoteCompanionGrant(null);
    setCompanionTransport("lan");
    setPairingNotice("Remote Companion fallback forgotten on this phone. Pair again from Local Flight Settings to restore away-from-LAN access.");
  }, [isStandalone, mobileSetupState]);

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
    if (!normalized && !standaloneCredentials) {
      setFeedbackTone("error");
      setFeedbackMessage("Set up Mobile or Standalone mode first.");
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
      if (standaloneCredentials) {
        await submitStandaloneFeedback(standaloneCredentials, {
          title: feedbackTitle.trim(),
          description: feedbackDescription.trim(),
          client_context: mobileClientContext("standalone-relay", snapshot, companionIdentity, "standalone")
        });
      } else {
        await submitFeedback(normalized, {
          title: feedbackTitle.trim(),
          description: feedbackDescription.trim(),
          client_context: mobileClientContext(normalized, snapshot, companionIdentity, "lan_companion")
        });
      }
      setFeedbackTone("ok");
      setFeedbackMessage(standaloneCredentials ? "Feedback sent through the hosted relay." : "Feedback sent to the Local Flight Reports board.");
      setFeedbackTitle("");
      setFeedbackDescription("");
    } catch (exc) {
      setFeedbackTone("error");
      setFeedbackMessage(errorMessage(exc));
    } finally {
      setFeedbackSending(false);
    }
  }, [companionIdentity, feedbackDescription, feedbackTitle, serverUrl, snapshot, standaloneCredentials]);

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

  const openFlightDetailWithHaptic = useCallback((callsign: string) => {
    hapticLight();
    openFlightDetail(callsign);
  }, [openFlightDetail]);

  const triggerSnapshotPulse = useCallback(() => {
    if (reduceMotion) return;
    snapshotPulse.stopAnimation();
    snapshotPulse.setValue(0);
    Animated.sequence([
      Animated.timing(snapshotPulse, { toValue: 1, duration: 120, useNativeDriver: true }),
      Animated.timing(snapshotPulse, { toValue: 0, duration: 260, useNativeDriver: true })
    ]).start();
  }, [snapshotPulse, reduceMotion]);

  useEffect(() => {
    if (!landscapeFidsActive) return;

    setActionRow(null);
    setConfigSheetVisible(false);
    closeFlightDetail();

    if (dataReady) {
      void refreshScreen({ target: "fids" });
    }
  }, [closeFlightDetail, dataReady, landscapeFidsActive, refreshScreen]);

  useEffect(() => {
    if (!dataReady) return;
    void refreshScreen({ target: screen });
  }, [dataReady, historyDirection, historyHours, radarRadius, refreshScreen, screen, view]);

  useEffect(() => {
    if (isStandalone || !serverUrl || screen !== "control") return;
    const normalized = normalizeServerUrl(serverUrl);
    if (!normalized) return;
    void fetchMatrixRuntime(normalized).catch((exc) => {
      setError(errorMessage(exc));
    });
  }, [fetchMatrixRuntime, isStandalone, screen, serverUrl]);

  useEffect(() => {
    if (!isStandalone) return;
    if (![1, 3, 5, 10].includes(radarRadius)) {
      setRadarRadius(5);
    }
    if (screen === "control" || screen === "help") {
      setScreen("settings");
    }
  }, [isStandalone, radarRadius, screen]);

  useEffect(() => {
    if (!isStandalone && screen === "help") {
      setScreen("control");
    }
  }, [isStandalone, screen]);

  useEffect(() => {
    if (isStandalone || !serverUrl || !connected) return;
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
          void refreshScreen({ target: screen, includeDashboard: screenNeedsDashboard(screen, isStandalone) });
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
          void refreshScreen({ target: screen, includeDashboard: screenNeedsDashboard(screen, isStandalone) });
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
  }, [connected, detailCallsign, detailVisible, isStandalone, refreshFlightDetail, refreshScreen, screen, serverUrl, triggerSnapshotPulse]);

  const cfg: AppConfig | null = snapshot.config || (standaloneCredentials
    ? {
        airport_iata: standaloneCredentials.airport.iata,
        airport_icao: standaloneCredentials.airport.icao,
        refresh_seconds: 3 * 60 * 60,
        display_name: standaloneCredentials.airport.name,
        theme: "standard",
        source: "real",
        timezone: standaloneCredentials.airport.timezone || "UTC",
        skin: "standard",
        display_outputs: ["mobile"]
      }
    : null);
  const state = snapshot.state;
  const activeProfileId =
    profiles.find((profile) =>
      profile.iata === cfg?.airport_iata &&
      profile.icao === cfg?.airport_icao &&
      profile.timezone === cfg?.timezone &&
      profile.source === cfg?.source &&
      profile.refresh_seconds === cfg?.refresh_seconds
    )?.id || null;
  const airportCode = cfg?.airport_iata || currentAirportDetail?.iata || "---";
  const airportIcao = cfg?.airport_icao || currentAirportDetail?.icao || "";
  const hasConfiguredAirport = Boolean(airportCode !== "---" || airportIcao);
  const fallbackDisplayName =
    cfg?.display_name && cfg.display_name !== "Local Flight"
      ? cfg.display_name
      : hasConfiguredAirport
        ? [cfg?.airport_iata, cfg?.airport_icao].filter(Boolean).join(" / ")
        : rows.length || serverUrl || isStandalone
          ? "Tap to set airport"
          : "Connect your server";
  const airportName = currentAirportDetail?.name || fallbackDisplayName;
  const airportLocation = [currentAirportDetail?.city, currentAirportDetail?.country].filter(Boolean).join(" · ");
  const sourceLabel = state?.source_name || cfg?.source || "VATSIM";
  const widgetAirportKey = `${isStandalone ? "standalone" : "lan"}:${airportCode}:${airportIcao || "---"}`;
  const widgetLastSuccess = state?.last_success_utc || "";
  const widgetAirportChangedBeforeEffect = Boolean(
    mobileSetupComplete &&
    previousWidgetAirportKeyRef.current &&
    previousWidgetAirportKeyRef.current !== widgetAirportKey
  );
  const widgetRowsPendingAirport =
    widgetAirportChangedBeforeEffect || widgetPendingAirport?.key === widgetAirportKey;
  const widgetRowsForPreview = useMemo(
    () => widgetRowsPendingAirport ? [] : rows,
    [rows, widgetRowsPendingAirport]
  );
  const widgetPreview = useMemo(() => deriveWidgetPreviewSnapshot({
    rows: widgetRowsForPreview,
    pinnedCallsign,
    airportCode,
    airportName,
    updatedLabel: widgetUpdatedLabel(state?.last_success_utc),
    view,
    preferences: widgetPreferences
  }), [
    airportCode,
    airportName,
    pinnedCallsign,
    widgetRowsForPreview,
    state?.last_success_utc,
    view,
    widgetPreferences
  ]);
  const isLive = connected && state?.ok !== false;
  const connectionState: ConnectionState = error
    ? refreshing ? "retrying" : "offline"
    : isLive ? (isStandalone ? "live" : companionTransport) : "offline";
  const radarSyncIntervalMs = Math.min(
    30 * 60 * 1000,
    Math.max(60 * 1000, (lastRadarRefreshAfterRef.current || 60) * 1000)
  );
  const syncIntervalMs = isStandalone
    ? (screen === "radar" ? 5 * 60 * 1000 : 3 * 60 * 60 * 1000)
    : (screen === "radar" ? radarSyncIntervalMs : companionSyncMs(cfg?.refresh_seconds));
  const widgetSnapshotLabel = `Snapshot ${widgetSnapshotStatus.state} · ${widgetSnapshotStatus.detail}`;

  useEffect(() => {
    if (!mobileSetupComplete) {
      previousWidgetAirportKeyRef.current = "";
      setWidgetPendingAirport(null);
      return;
    }
    if (!previousWidgetAirportKeyRef.current) {
      previousWidgetAirportKeyRef.current = widgetAirportKey;
      return;
    }
    if (previousWidgetAirportKeyRef.current !== widgetAirportKey) {
      previousWidgetAirportKeyRef.current = widgetAirportKey;
      setWidgetPendingAirport({
        key: widgetAirportKey,
        baselineLastSuccess: widgetLastSuccess
      });
    }
  }, [mobileSetupComplete, widgetAirportKey, widgetLastSuccess]);

  useEffect(() => {
    if (!widgetPendingAirport || widgetPendingAirport.key !== widgetAirportKey) return;
    if (widgetLastSuccess && widgetLastSuccess !== widgetPendingAirport.baselineLastSuccess) {
      setWidgetPendingAirport(null);
    }
  }, [widgetAirportKey, widgetLastSuccess, widgetPendingAirport]);

  useEffect(() => {
    if (!launchHydrated) return;
    if (!mobileSetupComplete && !widgetSnapshotWasReadyRef.current) {
      setWidgetSnapshotStatus({ state: "waiting", detail: "setup" });
      return;
    }
    const writePreview = mobileSetupComplete
      ? widgetPreview
      : deriveWidgetPreviewSnapshot({
          rows: [],
          pinnedCallsign: "",
          airportCode: "---",
          airportName: "Local Flight Airport",
          updatedLabel: "Setup reset",
          view,
          preferences: widgetPreferences
        });
    const payload = buildWidgetExchangeSnapshot({
      preview: writePreview,
      preferences: widgetPreferences,
      mode: isStandalone ? "standalone" : "lan_companion",
      stale: !mobileSetupComplete || !connected || Boolean(error) || widgetRowsPendingAirport,
      sourceLabel
    });
    let alive = true;
    void writeWidgetSnapshot(payload, { force: !mobileSetupComplete }).then((result) => {
      if (!alive) return;
      if (result.ok) {
        if (mobileSetupComplete) {
          widgetSnapshotWasReadyRef.current = true;
        }
        setWidgetSnapshotStatus({
          state: payload.stale ? "stale" : "ready",
          detail: result.sharedContainer ? "app group" : "app sandbox"
        });
      } else {
        setWidgetSnapshotStatus({
          state: "error",
          detail: result.error || "write failed"
        });
      }
    });
    return () => {
      alive = false;
    };
  }, [
    connected,
    error,
    isStandalone,
    launchHydrated,
    mobileSetupComplete,
    sourceLabel,
    view,
    widgetRowsPendingAirport,
    widgetPreferences,
    widgetPreview
  ]);

  useEffect(() => {
    if (!dataReady || !connected) return;
    const timer = setInterval(() => {
      void refreshScreen({ target: screen, includeDashboard: screenNeedsDashboard(screen, isStandalone) });
    }, syncIntervalMs);
    return () => clearInterval(timer);
  }, [connected, dataReady, isStandalone, refreshScreen, screen, syncIntervalMs]);

  useEffect(() => {
    if (isStandalone || !serverUrl || !connected || !companionIdentity) return;
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
  }, [companionIdentity, connected, isStandalone, serverUrl]);

  const contentWidth = Math.min(layout.contentMaxWidth, layout.width - 24);
  const pinnedRow = pinnedCallsign
    ? rows.find((row) => flightPinKey(row) === pinnedCallsign) || null
    : null;
  const islandRow =
    pinnedRow || rows.find((row) => /board|gate|approach/i.test(row.status_display)) || rows[0] || null;
  const screenContentPadding = Math.max(20, insets.bottom + 14);
  const effectiveRadarDrawingLayers = isStandalone
    ? { runways: radarDrawingLayers.runways, surface: radarDrawingLayers.surface, terrain: false }
    : radarDrawingLayers;
  const statusBarStyle = themeMode === "light" ? "dark-content" : "light-content";

  if (!mobileSetupComplete) {
    return (
      <SafeAreaView style={styles.setupSafe} edges={["top", "bottom", "left", "right"]}>
        <StatusBar barStyle={statusBarStyle} hidden={false} />
        {launchHydrated ? (
          <CompanionSetupScreen
            initialUrl={draftUrl || serverUrl}
            pairingUrl={pairingUrl}
            pairingNonce={pairingNonce}
            pairingExpectedServerFingerprint={pairingExpectedServerFingerprint}
            initialDiagnosticsMode={mobileDiagnosticsMode}
            onPairingLoaded={(pairing) => {
              setPairingUrl(pairing.serverUrl);
              setPairingExpectedServerFingerprint(pairing.expectedServerFingerprint || "");
              setPairingRemoteInvite(pairing.remoteCompanionInvite || null);
            }}
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
          beacon={launch.beacon}
          sweep={launch.sweep}
          orbitFast={launch.orbitFast}
          orbitMedium={launch.orbitMedium}
          orbitSlow={launch.orbitSlow}
          ready={launch.ready}
          onEnter={launch.enter}
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
          variant={screen === "fids" ? "expanded" : "compact"}
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
          onOpenConfig={() => {
            if (isStandalone) {
              void rerunCompanionSetup();
              return;
            }
            setConfigSheetVisible(true);
          }}
          onOpenWeather={() => {
            if (isStandalone) {
              setScreen("settings");
              return;
            }
            setScreen("control");
          }}
          onOpenBoard={() => setScreen("fids")}
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
              showConnectPrompt={!dataReady && !isStandalone}
              standalone={isStandalone}
              onOpenSettings={() => setScreen(isStandalone ? "settings" : "control")}
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
              showConnectPrompt={!dataReady && !isStandalone}
              standalone={isStandalone}
              onOpenSettings={() => setScreen(isStandalone ? "settings" : "control")}
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
              showConnectPrompt={!dataReady && !isStandalone}
              onOpenSettings={() => setScreen(isStandalone ? "settings" : "control")}
              onRefresh={() => { hapticLight(); refreshScreen({ target: "radar", forceRadarGround: true }); }}
              onRadiusChange={setRadarRadius}
              radiusOptions={isStandalone ? [1, 3, 5, 10] : undefined}
              drawingLayers={effectiveRadarDrawingLayers}
              standalone={isStandalone}
              onDrawingLayersChange={chooseRadarDrawingLayers}
              onOpenDetail={openFlightDetail}
              compact={false}
              contentPaddingBottom={screenContentPadding}
            />
          ) : null}

          {screen === "control" || screen === "settings" ? (
            <ScrollView
              style={styles.screenScroll}
              contentContainerStyle={[styles.screenContent, { paddingBottom: screenContentPadding }]}
              refreshControl={
                <RefreshControl
                  refreshing={refreshing}
                  tintColor={palette.blue}
                  onRefresh={() => refreshScreen({ target: screen, includeDashboard: screenNeedsDashboard(screen, isStandalone) })}
                />
              }
            >
              {!dataReady && !isStandalone ? (
                <ConnectPrompt onSettings={() => setScreen("control")} />
              ) : null}

              {activity && !error && !refreshing ? <ScreenActivity activity={activity} /> : null}

              {error && !refreshing ? (
                <ScreenError
                  message={error}
                  retrying={false}
                  onRetry={() => { hapticLight(); refreshScreen({ target: screen }); }}
                />
              ) : null}

              {screen === "settings" && isStandalone ? (
                <StandaloneSettingsScreen
                  snapshot={snapshot}
                  rows={rows}
                  view={view}
                  pinnedCallsign={pinnedCallsign}
                  companionIdentity={companionIdentity}
                  connected={isLive}
                  airportCode={airportCode}
                  airportName={airportName}
                  relayTokenPrefix={mobileSetupState.relayActivationToken?.slice(0, 10) || "not set"}
                  themeMode={themeMode}
                  skin={skin}
                  weatherDisplayMode={weatherDisplayMode}
                  widgetPreferences={widgetPreferences}
                  widgetSnapshotLabel={widgetSnapshotLabel}
                  mobileDiagnosticsMode={mobileDiagnosticsMode}
                  feedbackTitle={feedbackTitle}
                  feedbackDescription={feedbackDescription}
                  feedbackSending={feedbackSending}
                  feedbackMessage={feedbackMessage}
                  feedbackTone={feedbackTone}
                  onThemeModeChange={setThemeMode}
                  onSkinChange={setSkin}
                  onWeatherDisplayModeChange={chooseWeatherDisplayMode}
                  onWidgetPreferencesChange={(next) => void chooseWidgetPreferences(next)}
                  onMobileDiagnosticsModeChange={chooseMobileDiagnosticsMode}
                  onRerunSetup={rerunCompanionSetup}
                  onOpenSupport={() => setSupportVisible(true)}
                  onFeedbackTitleChange={setFeedbackTitle}
                  onFeedbackDescriptionChange={setFeedbackDescription}
                  onSubmitFeedback={sendFeedbackReport}
                />
              ) : null}

              {screen === "control" && !isStandalone ? (
                <ControlScreen
                  snapshot={snapshot}
                  rows={rows}
                  view={view}
                  pinnedCallsign={pinnedCallsign}
                  error={error}
                  serverUrl={serverUrl}
                  draftUrl={draftUrl}
                  loading={loading}
                  isTablet={layout.isTablet}
                  isLandscape={layout.isLandscape}
                  themeMode={themeMode}
                  skin={skin}
                  weatherDisplayMode={weatherDisplayMode}
                  widgetPreferences={widgetPreferences}
                  widgetSnapshotLabel={widgetSnapshotLabel}
                  mobileDiagnosticsMode={mobileDiagnosticsMode}
                  profiles={profiles}
                  activeProfileId={activeProfileId}
                  applyingProfileId={applyingProfileId}
                  outputs={snapshot.config?.display_outputs || []}
                  refreshSeconds={snapshot.config?.refresh_seconds ?? null}
                  schedulerRestarting={schedulerRestarting}
                  schedulerMessage={schedulerMessage}
                  pairingNotice={pairingNotice}
                  serverPanelRequest={serverPanelRequest}
                  matrixRuntime={matrixRuntime}
                  matrixDirty={matrixDirty}
                  matrixSaving={matrixSaving}
                  matrixSaveMessage={matrixSaveMessage}
                  matrixSaveTone={matrixSaveTone}
                  companionIdentity={companionIdentity}
                  connected={isLive}
                  connectionState={connectionState}
                  remoteCompanionGrant={mobileSetupState.remoteCompanion || null}
                  onThemeModeChange={setThemeMode}
                  onSkinChange={setSkin}
                  onWeatherDisplayModeChange={chooseWeatherDisplayMode}
                  onWidgetPreferencesChange={(next) => void chooseWidgetPreferences(next)}
                  onMobileDiagnosticsModeChange={chooseMobileDiagnosticsMode}
                  onMatrixPresetChange={(preset) => updateMatrixDraft({ preset })}
                  onMatrixViewChange={(nextView) => updateMatrixDraft({ default_view: nextView })}
                  onMatrixWeatherToggle={(enabled) => updateMatrixDraft({
                    options: {
                      ...matrixRuntime.options,
                      show_metar: enabled,
                      show_weather: enabled
                    }
                  })}
                  onMatrixGateToggle={(enabled) => updateMatrixDraft({
                    show_gate_info: enabled,
                    options: {
                      ...matrixRuntime.options,
                      show_gate_info: enabled
                    }
                  })}
                  onMatrixPaletteChange={(nextPalette) => updateMatrixDraft({
                    palette: nextPalette,
                    options: {
                      ...matrixRuntime.options,
                      palette: nextPalette
                    }
                  })}
                  onMatrixBrightnessChange={(brightness) => updateMatrixDraft({ brightness })}
                  onMatrixRowsChange={(maxRows) => updateMatrixDraft({ max_rows: maxRows })}
                  onMatrixRotationChange={(pageRotationSeconds) => updateMatrixDraft({ page_rotation_seconds: pageRotationSeconds })}
                  onMatrixAnimationModeChange={(animationMode) => updateMatrixDraft({
                    animation_enabled: animationMode !== "static",
                    animation_mode: animationMode,
                    options: {
                      ...matrixRuntime.options,
                      animation_mode: animationMode
                    }
                  })}
                  onMatrixAnimationSpeedChange={(animationSpeed) => updateMatrixDraft({ animation_speed: animationSpeed })}
                  onMatrixStatusAnimationToggle={(enabled) => updateMatrixDraft({ status_animation_enabled: enabled })}
                  onMatrixRefreshChange={(nextRefreshSeconds) => updateMatrixDraft({ refresh_seconds: nextRefreshSeconds })}
                  onMatrixSave={() => void saveMatrixDraftNow()}
                  onMatrixReset={() => void resetMatrixDraft()}
                  onApplyProfile={(profile) => void applySettingsProfile(profile)}
                  onOpenConfig={() => setConfigSheetVisible(true)}
                  onOpenSupport={() => setSupportVisible(true)}
                  feedbackTitle={feedbackTitle}
                  feedbackDescription={feedbackDescription}
                  feedbackSending={feedbackSending}
                  feedbackMessage={feedbackMessage}
                  feedbackTone={feedbackTone}
                  onFeedbackTitleChange={setFeedbackTitle}
                  onFeedbackDescriptionChange={setFeedbackDescription}
                  onSubmitFeedback={sendFeedbackReport}
                  onRestartScheduler={restartSchedulerNow}
                  onRerunSetup={rerunCompanionSetup}
                  onForgetRemoteCompanion={() => void forgetRemoteCompanion()}
                  onChangeUrl={setDraftUrl}
                  onPairingUrl={connectPairingUrl}
                  onConnect={() => void connect()}
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
          standalone={isStandalone}
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
        budget={snapshot.budget}
        profiles={profiles}
        onClose={() => setConfigSheetVisible(false)}
        onApplied={(newConfig) => {
          setSnapshot((prev) => ({ ...prev, config: newConfig }));
          void saveCachedLanConfig(newConfig);
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
        beacon={launch.beacon}
        sweep={launch.sweep}
        orbitFast={launch.orbitFast}
        orbitMedium={launch.orbitMedium}
        orbitSlow={launch.orbitSlow}
        ready={launch.ready}
        onEnter={launch.enter}
        status={launch.status}
        styles={styles}
      />
      {setupSuccess ? (
        <SetupCompleteOverlay success={setupSuccess} onDismiss={dismissSetupSuccess} />
      ) : null}
    </SafeAreaView>
  );
}

function SetupCompleteOverlay({
  success,
  onDismiss
}: {
  success: SetupSuccessState;
  onDismiss: () => void;
}) {
  const reduceMotion = useReducedMotionPreference();
  const opacity = useRef(new Animated.Value(reduceMotion ? 1 : 0)).current;
  const scale = useRef(new Animated.Value(reduceMotion ? 1 : 0.96)).current;
  const dismissedRef = useRef(false);

  const dismiss = useCallback(() => {
    if (dismissedRef.current) return;
    dismissedRef.current = true;
    if (reduceMotion) {
      onDismiss();
      return;
    }
    Animated.parallel([
      Animated.timing(opacity, {
        toValue: 0,
        duration: 180,
        useNativeDriver: true
      }),
      Animated.timing(scale, {
        toValue: 0.98,
        duration: 180,
        useNativeDriver: true
      })
    ]).start(() => onDismiss());
  }, [opacity, onDismiss, reduceMotion, scale]);

  useEffect(() => {
    dismissedRef.current = false;
    if (reduceMotion) {
      opacity.setValue(1);
      scale.setValue(1);
    } else {
      opacity.setValue(0);
      scale.setValue(0.96);
      Animated.parallel([
        Animated.timing(opacity, {
          toValue: 1,
          duration: 220,
          useNativeDriver: true
        }),
        Animated.spring(scale, {
          toValue: 1,
          damping: 17,
          stiffness: 190,
          mass: 0.8,
          useNativeDriver: true
        })
      ]).start();
    }
    const timer = setTimeout(dismiss, 1850);
    return () => clearTimeout(timer);
  }, [dismiss, opacity, reduceMotion, scale, success]);

  return (
    <Animated.View
      pointerEvents="auto"
      style={[
        styles.setupSuccessOverlay,
        {
          opacity,
          transform: [{ scale }]
        }
      ]}
    >
      <View style={styles.setupSuccessCard}>
        <View style={styles.setupSuccessIconWrap}>
          <View style={styles.setupSuccessIconHalo} />
          <LocalFlightIcon name={ACTION_ICONS.finish} size={34} color={palette.green} />
        </View>
        <Text style={styles.setupSuccessTitle}>{success.title}</Text>
        <Text style={styles.setupSuccessBody}>{success.body}</Text>
        <Text style={styles.setupSuccessMeta} numberOfLines={1}>{success.meta}</Text>
        <Pressable
          style={styles.setupSuccessButton}
          onPress={dismiss}
          {...accessibleButton({
            label: "Open board",
            hint: "Dismiss setup complete and show the board."
          })}
        >
          <Text style={styles.setupSuccessButtonText}>OPEN BOARD</Text>
        </Pressable>
      </View>
    </Animated.View>
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
  const reduceMotion = useReducedMotionPreference();
  const landscapeOpacity = useRef(new Animated.Value(0)).current;
  const landscapeScale = useRef(new Animated.Value(0.985)).current;

  useEffect(() => {
    if (reduceMotion) {
      landscapeOpacity.setValue(1);
      landscapeScale.setValue(1);
      return;
    }
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
  }, [landscapeOpacity, landscapeScale, reduceMotion]);

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
  const splashBg = lightMode ? "#f5f9fc" : "#080c12";
  const splashAtmosphere = lightMode ? hexToRgba(palette.blue, 0.16) : "rgba(18,102,139,0.22)";
  const splashLine = lightMode ? hexToRgba(palette.line, 0.32) : "rgba(82,246,255,0.13)";
  const splashLineSoft = lightMode ? hexToRgba(palette.line, 0.18) : "rgba(213,244,255,0.08)";
  const splashAccent = lightMode ? palette.blue : "#52f6ff";
  const splashAccentSoft = lightMode ? hexToRgba(palette.blue, 0.28) : "rgba(82,246,255,0.34)";
  const splashAccentFaint = lightMode ? hexToRgba(palette.blue, 0.10) : "rgba(82,246,255,0.08)";
  const splashTextMuted = lightMode ? hexToRgba(palette.text, 0.72) : "rgba(213,226,235,0.76)";
  const splashTextDim = lightMode ? hexToRgba(palette.text, 0.50) : "rgba(213,226,235,0.52)";
  const splashTextGhost = lightMode ? hexToRgba(palette.text, 0.40) : "rgba(213,226,235,0.40)";
  const splashPlate = lightMode ? "rgba(255,255,255,0.86)" : "rgba(5,12,20,0.84)";
  const splashPlateInner = lightMode ? "rgba(245,250,255,0.94)" : "#060e18";
  const splashPlateBorder = lightMode ? hexToRgba(palette.blue, 0.34) : "rgba(216,247,255,0.30)";
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
  setupSuccessOverlay: {
    ...StyleSheet.absoluteFillObject,
    zIndex: 90,
    alignItems: "center",
    justifyContent: "center",
    padding: 22,
    backgroundColor: lightMode ? "rgba(245,249,252,0.72)" : "rgba(3,7,12,0.76)"
  },
  setupSuccessCard: {
    width: "100%",
    maxWidth: 360,
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 22,
    paddingVertical: 24,
    borderRadius: 24,
    borderWidth: 1,
    borderColor: success25,
    backgroundColor: lightMode ? "rgba(255,255,255,0.94)" : "rgba(8,16,25,0.94)",
    shadowColor: lightMode ? palette.blue : "#000000",
    shadowOpacity: lightMode ? 0.16 : 0.46,
    shadowRadius: 28,
    shadowOffset: { width: 0, height: 16 }
  },
  setupSuccessIconWrap: {
    width: 72,
    height: 72,
    borderRadius: 24,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: success25,
    backgroundColor: success10,
    overflow: "hidden"
  },
  setupSuccessIconHalo: {
    position: "absolute",
    width: 96,
    height: 96,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: accent20,
    borderTopColor: success25
  },
  setupSuccessTitle: {
    marginTop: 4,
    fontFamily: mono,
    color: palette.text,
    fontSize: 22,
    lineHeight: 28,
    fontWeight: "900",
    letterSpacing: 0.6,
    textAlign: "center",
    includeFontPadding: false
  },
  setupSuccessBody: {
    color: palette.textMuted,
    fontSize: 13,
    lineHeight: 19,
    textAlign: "center"
  },
  setupSuccessMeta: {
    maxWidth: "100%",
    color: palette.blue2,
    fontFamily: mono,
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 0.8,
    textTransform: "uppercase",
    includeFontPadding: false
  },
  setupSuccessButton: {
    marginTop: 6,
    minHeight: 42,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 18,
    borderRadius: 999,
    backgroundColor: palette.green
  },
  setupSuccessButtonText: {
    fontFamily: mono,
    color: onGreenText,
    fontSize: 11,
    fontWeight: "900",
    letterSpacing: 1,
    includeFontPadding: false
  },
  companionSetupKeyboard: {
    flex: 1,
    backgroundColor: splashBg
  },
  companionSetupScroll: {
    flex: 1,
    backgroundColor: splashBg
  },
  companionSetupContent: {
    flexGrow: 1,
    alignItems: "center",
    justifyContent: "flex-start",
    paddingHorizontal: 14,
    paddingTop: 12,
    paddingBottom: 20,
    overflow: "hidden"
  },
  companionSetupGlowA: {
    position: "absolute",
    top: -120,
    right: -120,
    width: 310,
    height: 310,
    borderRadius: 999,
    backgroundColor: splashAccentFaint
  },
  companionSetupGlowB: {
    position: "absolute",
    bottom: -150,
    left: -110,
    width: 340,
    height: 340,
    borderRadius: 999,
    backgroundColor: splashAccentFaint
  },
  companionSetupShell: {
    width: "100%",
    maxWidth: 760,
    gap: 12
  },
  companionSetupHero: {
    alignItems: "center",
    paddingHorizontal: 16,
    paddingTop: 16,
    paddingBottom: 14,
    borderRadius: 22,
    borderWidth: 1,
    borderColor: splashLineSoft,
    backgroundColor: lightMode ? "rgba(255,255,255,0.68)" : "rgba(14,23,34,0.84)",
    shadowColor: "#000",
    shadowOpacity: 0.18,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 14 }
  },
  companionSetupLogoWrap: {
    width: 104,
    height: 104,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 10
  },
  companionSetupLogoRing: {
    position: "absolute",
    width: 96,
    height: 96,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: splashAccentSoft
  },
  companionSetupLogoRingOuter: {
    position: "absolute",
    width: 120,
    height: 120,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: splashLineSoft,
    borderTopColor: splashAccentSoft,
    borderRightColor: splashAccentFaint
  },
  companionSetupLogoPlate: {
    width: 76,
    height: 76,
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
    borderWidth: 1,
    borderColor: splashPlateBorder,
    backgroundColor: splashPlate,
    shadowColor: splashAccent,
    shadowOpacity: lightMode ? 0.14 : 0.32,
    shadowRadius: 22,
    shadowOffset: { width: 0, height: 10 }
  },
  companionSetupLogoMark: {
    width: 82,
    height: 82
  },
  companionSetupCompactRail: {
    overflow: "hidden",
    padding: 12,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: splashLineSoft,
    backgroundColor: lightMode ? "rgba(255,255,255,0.64)" : "rgba(14,23,34,0.82)"
  },
  companionSetupCompactBrand: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10
  },
  companionSetupCompactLogo: {
    width: 38,
    height: 38,
    borderRadius: 13,
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
    borderWidth: 1,
    borderColor: splashPlateBorder,
    backgroundColor: splashPlate
  },
  companionSetupCompactLogoMark: {
    width: 42,
    height: 42
  },
  companionSetupCompactCopy: {
    flex: 1,
    minWidth: 0
  },
  companionSetupCompactTitle: {
    fontFamily: brand,
    color: palette.text,
    fontSize: 19,
    lineHeight: 22,
    fontWeight: "400",
    includeFontPadding: false
  },
  companionSetupCompactMeta: {
    marginTop: 3,
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 8,
    fontWeight: "900",
    letterSpacing: 1.3,
    textTransform: "uppercase",
    includeFontPadding: false
  },
  companionSetupCompactBeacon: {
    position: "absolute",
    top: 18,
    right: 14,
    width: 78,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    opacity: lightMode ? 0.42 : 0.62
  },
  companionSetupCompactBeaconDot: {
    width: 6,
    height: 6,
    borderRadius: 999,
    backgroundColor: splashAccent
  },
  companionSetupCompactBeaconLine: {
    flex: 1,
    height: 1,
    borderRadius: 999,
    backgroundColor: splashAccentFaint
  },
  companionSetupCompactProgress: {
    marginTop: 12,
    height: 4,
    overflow: "hidden",
    borderRadius: 999,
    backgroundColor: lightMode ? hexToRgba(palette.line, 0.28) : "rgba(213,244,255,0.12)"
  },
  companionSetupCompactProgressFill: {
    height: "100%",
    borderRadius: 999,
    backgroundColor: splashAccent
  },
  companionSetupEyebrow: {
    color: palette.blue2,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 2.4,
    textAlign: "center"
  },
  companionSetupTitle: {
    marginTop: 7,
    fontFamily: mono,
    color: palette.text,
    fontSize: 27,
    fontWeight: "800",
    letterSpacing: 0.8,
    textAlign: "center"
  },
  companionSetupBody: {
    marginTop: 8,
    color: palette.textMuted,
    fontSize: 12.5,
    lineHeight: 18,
    textAlign: "center"
  },
  companionSetupRoute: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "center",
    gap: 6,
    marginTop: 16,
    width: "100%"
  },
  companionSetupRouteItem: {
    flex: 1,
    alignItems: "center",
    gap: 6
  },
  companionSetupStepDot: {
    width: 24,
    height: 24,
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
    fontSize: 9,
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
    fontSize: 7,
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
    gap: 10,
    padding: 16,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: splashLineSoft,
    backgroundColor: lightMode ? "rgba(255,255,255,0.66)" : "rgba(14,23,34,0.82)"
  },
  companionSetupWelcomePanel: {
    backgroundColor: lightMode ? "rgba(255,255,255,0.7)" : "rgba(14,23,34,0.76)"
  },
  companionSetupPanelTitle: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 17,
    fontWeight: "800",
    letterSpacing: 0.6,
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
    padding: 10,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: accent14,
    backgroundColor: accent06
  },
  companionSetupChecklistIcon: {
    width: 32,
    height: 32,
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
    fontSize: 12,
    fontWeight: "800"
  },
  companionSetupChecklistBody: {
    marginTop: 2,
    color: palette.textMuted,
    fontSize: 10.5,
    lineHeight: 15
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
    padding: 11,
    borderRadius: 14,
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
    fontSize: 11,
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
    minHeight: 46,
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
  activityPillCompact: {
    minHeight: 0,
    alignSelf: "flex-start",
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
    gap: 0
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
    gap: 14,
    backgroundColor: splashBg,
    overflow: "hidden"
  },
  launchAtmosphere: {
    position: "absolute",
    top: -110,
    left: -110,
    right: -110,
    height: "62%",
    borderBottomLeftRadius: 999,
    borderBottomRightRadius: 999,
    backgroundColor: splashAtmosphere,
    opacity: lightMode ? 0.86 : 0.74
  },
  launchGlowNorth: {
    position: "absolute",
    top: -180,
    left: "12%",
    right: "12%",
    height: 360,
    borderRadius: 999,
    backgroundColor: splashAccentFaint
  },
  launchGlowSouth: {
    position: "absolute",
    left: -70,
    right: -70,
    bottom: -160,
    height: 320,
    borderRadius: 999,
    backgroundColor: lightMode ? hexToRgba(palette.blue2, 0.08) : splashAccentFaint
  },
  launchSkyGrid: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    justifyContent: "space-evenly",
    opacity: lightMode ? 0.34 : 0.22
  },
  launchGridLine: {
    height: 1,
    backgroundColor: splashLine
  },
  launchCrosshairHorizontal: {
    position: "absolute",
    left: 0,
    right: 0,
    height: 1,
    backgroundColor: splashLineSoft
  },
  launchCrosshairVertical: {
    position: "absolute",
    top: 0,
    bottom: 0,
    width: 1,
    backgroundColor: splashLineSoft
  },
  launchParticle: {
    position: "absolute",
    borderRadius: 999,
    backgroundColor: splashAccent,
    shadowColor: splashAccent,
    shadowOpacity: lightMode ? 0.32 : 0.72,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 0 }
  },
  launchOrbitRing: {
    position: "absolute",
    borderRadius: 999,
    borderWidth: 1
  },
  launchOrbitRingSlow: {
    borderColor: splashLineSoft,
    borderLeftColor: splashAccentSoft,
    borderBottomColor: splashAccentFaint
  },
  launchOrbitRingMedium: {
    borderWidth: 2,
    borderColor: lightMode ? hexToRgba(palette.blue, 0.16) : "rgba(213,244,255,0.14)",
    borderTopColor: splashAccentSoft,
    borderRightColor: lightMode ? hexToRgba(palette.blue2, 0.28) : "rgba(82,246,255,0.42)"
  },
  launchOrbitRingFast: {
    borderColor: lightMode ? hexToRgba(palette.blue, 0.20) : "rgba(107,231,255,0.22)",
    borderTopColor: splashAccent,
    borderLeftColor: "transparent"
  },
  launchSweepRotor: {
    position: "absolute",
    alignItems: "center"
  },
  launchSweep: {
    position: "absolute",
    top: "9%",
    width: 3,
    borderRadius: 999,
    backgroundColor: splashAccent,
    shadowColor: splashAccent,
    shadowOpacity: lightMode ? 0.28 : 0.8,
    shadowRadius: 14,
    shadowOffset: { width: 0, height: 0 }
  },
  launchContentStack: {
    width: "100%",
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 0
  },
  launchScene: {
    width: "100%",
    alignItems: "center",
    justifyContent: "center",
    gap: 20,
    paddingVertical: 8
  },
  launchSceneCompact: {
    gap: 14,
    paddingVertical: 2
  },
  launchMarkWrap: {
    alignItems: "center",
    justifyContent: "center"
  },
  launchHeroAura: {
    position: "absolute",
    borderRadius: 999,
    backgroundColor: splashAccentFaint,
    shadowColor: splashAccent,
    shadowOpacity: lightMode ? 0.20 : 0.42,
    shadowRadius: 32,
    shadowOffset: { width: 0, height: 0 }
  },
  launchBeaconPing: {
    position: "absolute",
    borderWidth: 1,
    borderColor: splashAccentSoft,
    backgroundColor: "transparent"
  },
  launchRadarRing: {
    position: "absolute",
    borderRadius: 999,
    borderWidth: 2,
    borderColor: lightMode ? hexToRgba(palette.blue, 0.22) : "rgba(216,247,255,0.22)"
  },
  launchRadarRingOuter: {
    position: "absolute",
    borderRadius: 999,
    borderWidth: 1,
    borderColor: splashLineSoft,
    borderLeftColor: splashAccentSoft,
    borderBottomColor: splashAccentFaint
  },
  launchTarget: {
    position: "absolute",
    borderRadius: 999,
    borderWidth: 2,
    borderColor: splashAccentSoft,
    backgroundColor: splashAccentFaint
  },
  launchTargetCore: {
    position: "absolute",
    borderRadius: 999,
    borderWidth: 3,
    borderColor: splashBg,
    backgroundColor: splashAccent,
    shadowColor: splashAccent,
    shadowOpacity: lightMode ? 0.36 : 0.9,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 0 }
  },
  launchIconBloom: {
    alignItems: "center",
    justifyContent: "center",
    shadowColor: splashAccent,
    shadowOpacity: lightMode ? 0.26 : 0.46,
    shadowRadius: 34,
    shadowOffset: { width: 0, height: 0 }
  },
  launchIconPlate: {
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: splashPlate,
    borderWidth: 1,
    borderColor: splashPlateBorder,
    shadowColor: lightMode ? palette.blue : "#000000",
    shadowOpacity: lightMode ? 0.18 : 0.52,
    shadowRadius: 30,
    shadowOffset: { width: 0, height: 16 }
  },
  launchMarkCrop: {
    overflow: "hidden",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: splashPlateInner,
    borderWidth: 1,
    borderColor: splashPlateBorder
  },
  launchMark: {
    width: "108%",
    height: "108%"
  },
  launchCopy: {
    width: "100%",
    maxWidth: 400,
    alignItems: "center"
  },
  launchTitle: {
    marginTop: 0,
    fontFamily: brand,
    color: palette.text,
    fontSize: 38,
    lineHeight: 42,
    fontWeight: "400",
    letterSpacing: 0,
    textAlign: "center",
    includeFontPadding: false
  },
  launchTitleCompact: {
    fontSize: 31,
    lineHeight: 35
  },
  launchSubtitle: {
    marginTop: 10,
    color: splashTextMuted,
    fontSize: 14,
    lineHeight: 20,
    textAlign: "center",
    maxWidth: 360
  },
  launchStatusPanel: {
    width: "100%",
    maxWidth: 360,
    marginTop: 18,
    paddingHorizontal: 14
  },
  launchStatusRow: {
    width: "100%",
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 9
  },
  launchStatusDot: {
    width: 8,
    height: 8,
    borderRadius: 999,
    backgroundColor: splashAccent,
    shadowColor: splashAccent,
    shadowOpacity: lightMode ? 0.36 : 0.9,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 0 }
  },
  launchStatus: {
    fontFamily: mono,
    color: splashTextDim,
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 1.4,
    textTransform: "uppercase",
    includeFontPadding: false
  },
  launchProgressTrack: {
    width: "100%",
    height: 4,
    marginTop: 13,
    overflow: "hidden",
    borderRadius: 999,
    backgroundColor: lightMode ? hexToRgba(palette.line, 0.28) : "rgba(213,244,255,0.12)"
  },
  launchProgressFill: {
    height: "100%",
    borderRadius: 999,
    backgroundColor: splashAccent
  },
  launchEnterButton: {
    alignSelf: "center",
    marginTop: 15,
    minHeight: 39,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 18,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: splashAccentSoft,
    backgroundColor: lightMode ? hexToRgba(palette.blue2, 0.14) : "rgba(82,246,255,0.12)"
  },
  launchEnterText: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 1.2,
    includeFontPadding: false
  },
  launchBottomMeta: {
    width: "100%",
    alignItems: "center",
    justifyContent: "flex-end",
    minHeight: 56
  },
  launchVersion: {
    marginLeft: 5,
    fontFamily: mono,
    color: splashTextGhost,
    fontSize: 9,
    fontWeight: "800",
    letterSpacing: 0.9,
    includeFontPadding: false
  },
  launchBeaconFooter: {
    minHeight: 20,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 7,
    opacity: lightMode ? 0.86 : 0.78
  },
  launchBeaconText: {
    fontFamily: mono,
    color: splashTextGhost,
    fontSize: 9,
    fontWeight: "900",
    letterSpacing: 1.6,
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
  headerCompact: {
    paddingTop: 8,
    paddingHorizontal: 14,
    paddingBottom: 9,
    position: "relative"
  },
  headerCompactTopRail: {
    minHeight: 54,
    position: "relative"
  },
  headerBoardTopRail: {
    minHeight: 38,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12
  },
  headerBoardBrand: {
    flex: 1,
    minHeight: 38,
    justifyContent: "center"
  },
  headerBoardClock: {
    minHeight: 38,
    minWidth: 112,
    alignItems: "flex-end",
    justifyContent: "center"
  },
  headerCompactRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingTop: 16,
    paddingRight: 104
  },
  headerCompactBrand: {
    flex: 1,
    minWidth: 0,
    minHeight: 36,
    justifyContent: "center"
  },
  headerCompactSubline: {
    marginTop: 2,
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 7,
    fontWeight: "900",
    letterSpacing: 1.1,
    includeFontPadding: false
  },
  headerCompactWeather: {
    position: "absolute",
    left: "50%",
    top: 17,
    width: 76,
    marginLeft: -38,
    minHeight: 34,
    justifyContent: "center",
    zIndex: 3
  },
  headerCompactRightColumn: {
    position: "absolute",
    right: 0,
    top: 0,
    zIndex: 2,
    width: 96,
    minHeight: 54,
    alignItems: "flex-end",
    justifyContent: "flex-start",
    gap: 4
  },
  headerCompactMeta: {
    flex: 0.72,
    minWidth: 0,
    minHeight: 44,
    alignItems: "flex-end",
    justifyContent: "flex-end",
    paddingTop: 14
  },
  headerCompactCodes: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "flex-end",
    flexWrap: "wrap",
    gap: 5
  },
  headerCompactCodeBadge: {
    paddingHorizontal: 6,
    paddingVertical: 3,
    fontSize: 8
  },
  headerCompactClock: {
    minHeight: 24,
    minWidth: 96,
    alignItems: "flex-end",
    justifyContent: "flex-start"
  },
  headerCompactUtc: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 10,
    fontWeight: "900",
    includeFontPadding: false
  },
  headerCompactLocal: {
    fontFamily: mono,
    color: palette.textMuted,
    fontSize: 9,
    includeFontPadding: false
  },
  headerCompactFlightChip: {
    width: "100%",
    minHeight: 22,
    alignItems: "flex-end",
    justifyContent: "center",
    gap: 1,
    paddingHorizontal: 5,
    paddingVertical: 3,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: hairlineSoft,
    backgroundColor: softPanel
  },
  headerCompactFlightChipPinned: {
    borderColor: warn24,
    backgroundColor: warn07
  },
  headerCompactFlightText: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 6.5,
    fontWeight: "900",
    letterSpacing: 0.5,
    includeFontPadding: false
  },
  headerCompactFlightRoute: {
    flex: 1,
    minWidth: 0,
    color: palette.textMuted,
    fontSize: 10,
    includeFontPadding: false
  },
  headerCompactFlightStatus: {
    fontFamily: mono,
    fontSize: 7,
    fontWeight: "900",
    letterSpacing: 0.4,
    includeFontPadding: false
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
  airportHeroRowUnified: {
    marginTop: 4
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
  airportHeroToplineUnified: {
    justifyContent: "flex-start"
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
  boardHeroWeatherCard: {
    width: 148,
    alignSelf: "flex-end",
    marginTop: 26,
    flexShrink: 0
  },
  boardHeroWeatherCardStacked: {
    width: "72%",
    minWidth: 220,
    maxWidth: 320,
    alignSelf: "center",
    marginTop: 0
  },
  boardHeroWeatherInner: {
    minHeight: 78,
    justifyContent: "center",
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 17,
    borderWidth: 1
  },
  boardHeroWeatherTop: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8
  },
  boardHeroWeatherTemp: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 16,
    lineHeight: 19,
    fontWeight: "900",
    includeFontPadding: false
  },
  boardHeroWeatherCondition: {
    color: palette.textMuted,
    fontSize: 10,
    lineHeight: 13,
    textAlign: "center",
    includeFontPadding: false
  },
  boardHeroWeatherConditionRaw: {
    fontFamily: mono,
    fontSize: 8,
    lineHeight: 10,
    letterSpacing: 0.2
  },
  boardHeroWeatherPills: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6
  },
  boardHeroWeatherPill: {
    maxWidth: 64,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: hairline,
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 8,
    lineHeight: 10,
    fontWeight: "900",
    letterSpacing: 0.7,
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
    marginTop: 0,
    color: palette.text,
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
  weatherRailGroup: {
    width: "100%",
    minHeight: 32,
    justifyContent: "center",
    gap: 2,
    paddingHorizontal: 5,
    paddingVertical: 4,
    borderRadius: 10,
    borderWidth: 1
  },
  weatherRailTop: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 4
  },
  weatherRailTemp: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 10,
    lineHeight: 12,
    fontWeight: "900",
    includeFontPadding: false
  },
  weatherRailPills: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 3
  },
  weatherRailPill: {
    maxWidth: 32,
    paddingHorizontal: 3,
    paddingVertical: 1,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: hairline,
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 6,
    lineHeight: 8,
    fontWeight: "900",
    letterSpacing: 0.5,
    includeFontPadding: false
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
  weatherCompactInline: {
    minHeight: 42,
    gap: 6,
    paddingHorizontal: 8,
    paddingVertical: 6,
    borderRadius: 13
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
  weatherCompactTempInline: {
    fontSize: 12,
    lineHeight: 15
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
  weatherCompactMetaInline: {
    marginTop: 1,
    fontSize: 7,
    letterSpacing: 0.3
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
  radarLayerPanel: {
    marginHorizontal: 12,
    marginBottom: 12,
    padding: 12,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: accent14,
    backgroundColor: softPanel
  },
  radarLayerHeader: {
    marginBottom: 10
  },
  radarLayerTitle: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 9,
    fontWeight: "900",
    letterSpacing: 1.2,
    includeFontPadding: false
  },
  radarLayerHint: {
    marginTop: 3,
    color: palette.textMuted,
    fontSize: 11,
    lineHeight: 15
  },
  radarLayerChips: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8
  },
  radarLayerChip: {
    minWidth: 118,
    flexGrow: 1,
    flexBasis: "30%",
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 10,
    paddingVertical: 9,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: accent14,
    backgroundColor: fieldPanel
  },
  radarLayerChipActive: {
    borderColor: accent40,
    backgroundColor: accent10
  },
  radarLayerDot: {
    width: 8,
    height: 8,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: palette.textDim,
    backgroundColor: "transparent"
  },
  radarLayerDotActive: {
    borderColor: palette.green,
    backgroundColor: palette.green
  },
  radarLayerCopy: {
    flex: 1,
    minWidth: 0
  },
  radarLayerLabel: {
    fontFamily: mono,
    color: palette.textMuted,
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 0.8,
    includeFontPadding: false
  },
  radarLayerLabelActive: {
    color: palette.blue2
  },
  radarLayerDetail: {
    marginTop: 2,
    color: palette.textDim,
    fontSize: 10,
    lineHeight: 13
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
    paddingBottom: 12
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
    flexWrap: "wrap",
    gap: 8
  },
  filterWrap: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 10
  },
  optionChip: {
    minWidth: 86,
    minHeight: 54,
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
    flexWrap: "wrap",
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
    paddingHorizontal: 10,
    paddingTop: 6,
    paddingBottom: 5
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
    marginBottom: 5,
    paddingBottom: 5
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
    marginTop: 2,
    fontSize: 18,
    lineHeight: 20,
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
    minHeight: 34,
    gap: 8,
    marginBottom: 4,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 10
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
    width: 26,
    height: 26,
    borderRadius: 8
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
    fontSize: 11,
    lineHeight: 13
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
  fullscreenWeatherSummaryCompact: {
    marginTop: 2,
    fontSize: 10,
    lineHeight: 12
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
    paddingTop: 4,
    paddingBottom: 4,
    marginBottom: 3,
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
    width: 74
  },
  fullscreenFidsFlightColumn: {
    width: 170
  },
  fullscreenFidsFlightColumnCompact: {
    width: 136
  },
  fullscreenFidsRouteColumn: {
    flex: 1,
    minWidth: 0
  },
  fullscreenFidsStatusColumn: {
    width: 150
  },
  fullscreenFidsStatusColumnCompact: {
    width: 112
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
    width: 104,
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
    paddingVertical: 3,
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
  fullscreenFidsTimeCompact: {
    fontSize: 17,
    lineHeight: 20,
    includeFontPadding: false
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
  fullscreenFidsFlightCompact: {
    fontSize: 16,
    lineHeight: 18,
    includeFontPadding: false
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
  fullscreenFidsRouteNameCompact: {
    fontSize: 15,
    lineHeight: 18,
    includeFontPadding: false
  },
  fullscreenFidsRouteMeta: {
    marginTop: 2,
    fontFamily: mono,
    color: palette.textMuted,
    fontSize: 10,
    letterSpacing: 0.6
  },
  fullscreenFidsRouteMetaCompact: {
    marginTop: 1,
    fontSize: 9,
    lineHeight: 11
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
  scopeSweepLayer: {
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
    gap: 10
  },
  infoCard: {
    flex: 1,
    minWidth: 0,
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
    fontWeight: "700",
    includeFontPadding: false,
    lineHeight: 18,
    maxWidth: "100%"
  },
  settingsCard: {
    marginHorizontal: 12,
    padding: 16,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: accent15,
    backgroundColor: palette.row
  },
  controlAccordionCard: {
    padding: 0,
    overflow: "hidden"
  },
  controlAccordionHeader: {
    minHeight: 70,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingHorizontal: 14,
    paddingVertical: 12
  },
  controlAccordionBody: {
    borderTopWidth: 1,
    borderTopColor: palette.lineSoft,
    paddingHorizontal: 16,
    paddingTop: 16,
    paddingBottom: 18,
    gap: 10
  },
  settingsTitle: {
    fontFamily: mono,
    color: palette.blue,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 1.2,
    marginBottom: 10
  },
  helpHeaderRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    marginBottom: 6
  },
  helpHeaderCopy: {
    flex: 1,
    minWidth: 0
  },
  helpBackButton: {
    minHeight: 34,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 10,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: accent18,
    backgroundColor: accent08
  },
  helpBackText: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 0.8,
    includeFontPadding: false,
    lineHeight: 12
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
  pairingChoiceRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 10,
    marginTop: 14,
    marginBottom: 12
  },
  pairingChoiceCard: {
    flex: 1,
    minWidth: 180,
    minHeight: 76,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    padding: 12,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: accent18,
    backgroundColor: accent08
  },
  pairingChoiceIcon: {
    width: 34,
    height: 34,
    borderRadius: 12,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: accent12
  },
  pairingChoiceCopy: {
    flex: 1,
    minWidth: 0
  },
  pairingChoiceTitle: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 12,
    fontWeight: "800",
    letterSpacing: 0.8,
    includeFontPadding: false,
    lineHeight: 15
  },
  pairingChoiceBody: {
    marginTop: 5,
    color: palette.textMuted,
    fontSize: 11,
    lineHeight: 15
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
    gap: 8,
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
  widgetNotice: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    padding: 14,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: accent18,
    backgroundColor: accent08
  },
  widgetPreviewCard: {
    marginTop: 14,
    padding: 13,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: accent14,
    backgroundColor: softPanel
  },
  widgetPreviewCardNested: {
    marginTop: 10,
    backgroundColor: fieldPanel
  },
  widgetSmallTracker: {
    overflow: "hidden",
    backgroundColor: palette.row
  },
  widgetPreviewHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10
  },
  widgetPreviewTitle: {
    fontFamily: mono,
    color: palette.blue,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 1.1,
    includeFontPadding: false,
    lineHeight: 12,
    textTransform: "uppercase"
  },
  widgetPreviewMeta: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 9,
    fontWeight: "800",
    letterSpacing: 0.8,
    includeFontPadding: false,
    lineHeight: 11
  },
  widgetFlightMain: {
    marginTop: 10,
    fontFamily: mono,
    color: palette.text,
    fontSize: 21,
    fontWeight: "800",
    letterSpacing: 0.7,
    includeFontPadding: false,
    lineHeight: 26
  },
  widgetFlightSub: {
    marginTop: 4,
    color: palette.textMuted,
    fontSize: 12,
    lineHeight: 16
  },
  widgetTrackerRoute: {
    marginTop: 8,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: palette.lineSoft,
    color: palette.blue2,
    fontSize: 12,
    fontWeight: "700",
    lineHeight: 16
  },
  widgetTrackerEmpty: {
    marginTop: 10,
    paddingVertical: 6
  },
  widgetEmptyTitle: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 13,
    fontWeight: "800",
    letterSpacing: 0.5,
    includeFontPadding: false,
    lineHeight: 16
  },
  widgetFidsBoard: {
    marginTop: 14,
    padding: 11,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: accent18,
    backgroundColor: palette.bg,
    overflow: "hidden"
  },
  widgetFidsTop: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 8,
    paddingBottom: 9,
    borderBottomWidth: 1,
    borderBottomColor: palette.lineSoft
  },
  widgetFidsBeaconWatermark: {
    width: 44,
    alignItems: "flex-start",
    justifyContent: "center",
    opacity: 0.82
  },
  widgetFidsIdentity: {
    flex: 1,
    minWidth: 0,
    alignItems: "center",
    justifyContent: "center",
    gap: 5
  },
  widgetFidsKickerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 7,
    flexWrap: "wrap"
  },
  widgetFidsKicker: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 1.8,
    includeFontPadding: false,
    lineHeight: 12
  },
  widgetFidsBoardBadge: {
    paddingHorizontal: 7,
    paddingVertical: 3,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: accent18,
    backgroundColor: accent08,
    fontFamily: mono,
    color: palette.textMuted,
    fontSize: 8,
    fontWeight: "900",
    letterSpacing: 0.8,
    includeFontPadding: false,
    lineHeight: 10,
    textAlign: "center",
    overflow: "hidden"
  },
  widgetFidsTitle: {
    color: palette.text,
    fontSize: 14,
    fontWeight: "800",
    lineHeight: 17,
    textAlign: "center",
    maxWidth: "100%"
  },
  widgetFidsMeta: {
    width: 108,
    alignItems: "flex-end",
    justifyContent: "center",
    gap: 4,
    flexShrink: 0
  },
  widgetFidsBrand: {
    maxWidth: 108,
    textAlign: "right",
    lineHeight: 17
  },
  widgetFidsLive: {
    fontFamily: mono,
    color: palette.green,
    fontSize: 9,
    fontWeight: "900",
    letterSpacing: 1.1,
    includeFontPadding: false,
    lineHeight: 11
  },
  widgetFidsSource: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 8,
    fontWeight: "800",
    letterSpacing: 0.8,
    includeFontPadding: false,
    lineHeight: 10
  },
  widgetFidsColumns: {
    marginTop: 10,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 8,
    paddingVertical: 5,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: hairlineSoft,
    backgroundColor: palette.header
  },
  widgetFidsColumnText: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 7,
    fontWeight: "900",
    letterSpacing: 0.8,
    includeFontPadding: false,
    lineHeight: 9
  },
  widgetFidsTimeColumn: {
    width: 48
  },
  widgetFidsFlightColumn: {
    width: 74
  },
  widgetFidsRouteColumn: {
    flex: 1,
    minWidth: 0
  },
  widgetFidsStatusColumn: {
    width: 78,
    alignItems: "flex-start"
  },
  widgetFidsInfoColumn: {
    width: 52,
    textAlign: "right"
  },
  widgetFidsRows: {
    marginTop: 6,
    gap: 6
  },
  widgetFidsRow: {
    minHeight: 48,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 8,
    paddingVertical: 6,
    borderRadius: 9,
    borderWidth: 1,
    borderColor: hairlineSoft,
    backgroundColor: palette.row
  },
  widgetFidsRowPinned: {
    borderColor: warn24,
    backgroundColor: warn07
  },
  widgetFidsTime: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 13,
    fontWeight: "900",
    includeFontPadding: false,
    lineHeight: 16
  },
  widgetFidsFlightCell: {
    minWidth: 0
  },
  widgetFidsFlight: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 12,
    fontWeight: "900",
    letterSpacing: 0.4,
    includeFontPadding: false,
    lineHeight: 14
  },
  widgetFidsSubline: {
    marginTop: 2,
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 7,
    fontWeight: "900",
    letterSpacing: 0.7,
    includeFontPadding: false,
    lineHeight: 9
  },
  widgetFidsRouteCell: {
    minWidth: 0
  },
  widgetFidsRouteName: {
    color: palette.text,
    fontSize: 12,
    fontWeight: "700",
    includeFontPadding: false,
    lineHeight: 15
  },
  widgetFidsRouteMeta: {
    marginTop: 2,
    fontFamily: mono,
    color: palette.textMuted,
    fontSize: 8,
    fontWeight: "700",
    letterSpacing: 0.5,
    includeFontPadding: false,
    lineHeight: 10
  },
  widgetFidsInfoValue: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 8,
    fontWeight: "800",
    includeFontPadding: false,
    lineHeight: 10
  },
  widgetFidsEmpty: {
    padding: 14,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: hairlineSoft,
    backgroundColor: palette.row
  },
  widgetLiveRows: {
    marginTop: 10,
    gap: 8
  },
  widgetPreviewRow: {
    minHeight: 48,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 8,
    borderTopWidth: 1,
    borderTopColor: palette.lineSoft
  },
  widgetRowTime: {
    width: 48,
    fontFamily: mono,
    color: palette.text,
    fontSize: 13,
    fontWeight: "800",
    includeFontPadding: false,
    lineHeight: 16
  },
  widgetRowCopy: {
    flex: 1,
    minWidth: 0
  },
  widgetRowFlight: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 12,
    fontWeight: "800",
    includeFontPadding: false,
    lineHeight: 15
  },
  widgetRowRoute: {
    marginTop: 3,
    color: palette.textMuted,
    fontSize: 11,
    includeFontPadding: false,
    lineHeight: 14
  },
  widgetEmptyText: {
    marginTop: 10,
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
  supportTierTagline: {
    marginTop: 5,
    color: palette.textDim,
    fontSize: 11,
    lineHeight: 15
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
    minHeight: 66,
    paddingTop: 6,
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
    width: 33,
    height: 33,
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
    lineHeight: 23
  },
  navLabel: {
    fontFamily: mono,
    fontSize: 9,
    color: palette.textDim,
    fontWeight: "800",
    letterSpacing: 0.75,
    includeFontPadding: false,
    lineHeight: 11
  },
  navLabelActive: {
    color: palette.blue
  },
  navDot: {
    width: 4,
    height: 4,
    borderRadius: 2,
    backgroundColor: palette.blue,
    marginTop: 2
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
  pairingScannerSheet: {
    minHeight: "72%"
  },
  pairingScannerBody: {
    paddingHorizontal: 18,
    paddingBottom: 20,
    gap: 12
  },
  pairingCameraFrame: {
    height: 330,
    overflow: "hidden",
    borderRadius: 22,
    borderWidth: 1,
    borderColor: accent25,
    backgroundColor: scopePanel
  },
  pairingCamera: {
    flex: 1
  },
  pairingScannerReticle: {
    position: "absolute",
    left: 46,
    right: 46,
    top: 58,
    bottom: 58,
    borderRadius: 24,
    borderWidth: 1,
    borderColor: accent40,
    backgroundColor: "rgba(0,0,0,0.02)"
  },
  pairingScannerCorner: {
    position: "absolute",
    left: -1,
    top: -1,
    width: 38,
    height: 38,
    borderLeftWidth: 4,
    borderTopWidth: 4,
    borderColor: palette.blue,
    borderTopLeftRadius: 24
  },
  pairingPermissionCard: {
    minHeight: 260,
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
    padding: 18,
    borderRadius: 22,
    borderWidth: 1,
    borderColor: accent18,
    backgroundColor: accent06
  },
  pairingPermissionTitle: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 15,
    fontWeight: "800",
    letterSpacing: 0.8,
    textAlign: "center"
  },
  pairingPermissionBody: {
    color: palette.textMuted,
    fontSize: 12,
    lineHeight: 17,
    textAlign: "center"
  },
  pairingScannerHint: {
    color: palette.textMuted,
    fontSize: 11,
    lineHeight: 16
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
    paddingBottom: 72,
    gap: 12
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
  matrixLiveSheetCard: {
    minHeight: "62%",
    maxHeight: "86%",
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24
  },
  matrixLiveSheetHeader: {
    alignItems: "center",
    paddingTop: 14,
    paddingBottom: 14,
    paddingHorizontal: 16
  },
  matrixLiveSheetTitle: {
    marginTop: 2,
    fontSize: 18,
    lineHeight: 22
  },
  matrixLiveSheetAction: {
    minHeight: 42,
    minWidth: 76,
    paddingHorizontal: 12
  },
  matrixLiveSheetContent: {
    paddingTop: 18,
    paddingHorizontal: 16,
    paddingBottom: 84,
    gap: 14
  },
  matrixLiveStatusStrip: {
    minHeight: 40,
    marginHorizontal: 0,
    marginBottom: 2,
    paddingHorizontal: 12,
    paddingVertical: 9,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: accent14,
    backgroundColor: accent06,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10
  },
  matrixLiveStatusText: {
    flex: 1,
    fontFamily: mono,
    color: palette.textMuted,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 0.8,
    includeFontPadding: false,
    lineHeight: 13,
    textTransform: "uppercase"
  },
  matrixLiveStatusAccent: {
    flex: 0,
    color: palette.green,
    textAlign: "right"
  },
  matrixLiveStatusWarn: {
    color: palette.amber
  },
  matrixLivePresetRow: {
    gap: 10
  },
  matrixLivePresetChip: {
    minHeight: 58,
    justifyContent: "center",
    paddingHorizontal: 12,
    paddingVertical: 9,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: accent14,
    backgroundColor: accent06
  },
  matrixLivePresetChipActive: {
    borderColor: success25,
    backgroundColor: success08
  },
  matrixLivePresetLabel: {
    color: palette.text,
    fontSize: 12,
    fontWeight: "800",
    includeFontPadding: false,
    lineHeight: 15
  },
  matrixLivePresetMeta: {
    marginTop: 4,
    color: palette.textMuted,
    fontSize: 10,
    lineHeight: 13
  },
  matrixLiveSubRow: {
    marginTop: 10
  },
  matrixLivePaletteRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 10
  },
  matrixLivePaletteChip: {
    width: "48%",
    minWidth: 132,
    minHeight: 56,
    justifyContent: "center",
    paddingHorizontal: 11,
    paddingVertical: 9,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: accent14,
    backgroundColor: softPanel
  },
  filterHelper: {
    color: palette.textMuted,
    fontSize: 13,
    lineHeight: 18,
    marginBottom: 10
  },
  matrixActionRow: {
    flexDirection: "row",
    gap: 10,
    marginTop: 4
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
