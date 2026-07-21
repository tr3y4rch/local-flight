import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Animated,
  Linking,
  Modal,
  Platform,
  Pressable,
  StatusBar,
  StyleSheet,
  Text,
  View
} from "react-native";
import * as SplashScreen from "expo-splash-screen";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";

import { LaunchOverlay } from "../components/LaunchOverlay";
import { accessibleButton, tapTargetHitSlop, useReducedMotionPreference } from "../accessibility/mobileA11y";
import { AirportConfigSheet, CompanionSetupScreen, FlightActionSheet, FlightDetailSheet, StandaloneAirportSheet, WeatherDetailsSheet, type ActivityStatus, type ConnectionState } from "../screens/AppScreens";
import { ACTION_ICONS, LocalFlightIcon } from "../theme/icons";
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
import { completeRemoteCompanionPairing, testRemoteCompanionProbe } from "../api/remoteCompanion";
import {
  getStandaloneRadarGround,
  getStandaloneBoard,
  getStandaloneRadar,
  getStandaloneSummary,
  submitStandaloneFeedback,
  type StandaloneCredentials
} from "../api/standalone";
import type {
  AppConfig,
  AirportResolved,
  ClientNotice,
  ConfigPatch,
  DashboardSnapshot,
  FidsRow,
  FlightView,
  HistoryDirection,
  HistoryFlightRow,
  HistoryResponse,
  HistorySummary,
  MobileBoardResponse,
  RadarBlip,
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
import { fidsRowDetailResponse, flightPinKey, historyRowDetailResponse, radarBlipDetailResponse } from "../domain/flights";
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
  deriveWidgetPreviewSnapshot,
  widgetSnapshotStaleAfterMs,
  type WidgetFlightPreview
} from "../domain/widgets";
import { configureWidgetBackgroundRefresh } from "../background/widgetRefresh";
import { useFlightDetail } from "../hooks/useFlightDetail";
import { type LaunchDataOutcome, type LaunchHydration, useLaunchOverlay } from "../hooks/useLaunchOverlay";
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
  migrateStandaloneGroundLayers,
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
import { readWidgetSnapshot, writeWidgetSnapshot } from "../storage/widgetSnapshot";
import { useMobileTheme } from "../theme/runtime";
import { useSupportPurchases } from "../iap/useSupportPurchases";
import { setStyleBridge } from "../theme/styleBridge";
import {
  DEFAULT_MOBILE_APPEARANCE,
  NATIVE_FONT_FAMILY,
  UI_FONT_FAMILY,
  type MobileAppearance
} from "../theme/tokens";
import { hapticLight, hapticSuccess, hapticWarning } from "../utils/haptics";
import { useResponsiveLayout } from "../utils/layout";
import { runtimeNativeNavigationCapabilities } from "../navigation/runtimeNativeNavigation";
import {
  endLocalFlightLiveActivity,
  isLocalFlightLiveActivitySupported,
  startLocalFlightLiveActivity
} from "localflight-widget-bridge";
import {
  MobileNavigatorV2,
  navigateMobileSection,
  openMobileDisplay,
  openMobileMorePanel
} from "../navigation/MobileNavigatorV2";
import {
  MobileSessionProvider,
  type MobileSection,
  type MobileSessionValue
} from "../session/MobileSessionProvider";
import {
  MOBILE_V2_NATIVE_NAVIGATION_ENABLED,
  MOBILE_V2_ROLLOUT_ENABLED
} from "../v2/featureGate";

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

function boardFreshnessLabel(value?: string | null, cached = false): string {
  const timestamp = Date.parse(value || "");
  if (!Number.isFinite(timestamp)) return cached ? "Cached" : "Waiting for an update";
  const diffSeconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000));
  const prefix = cached ? "Cached · " : "";
  if (diffSeconds < 60) return `${prefix}Updated now`;
  const diffMinutes = Math.round(diffSeconds / 60);
  if (diffMinutes < 60) return `${prefix}Updated ${diffMinutes} ${diffMinutes === 1 ? "minute" : "minutes"} ago`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `${prefix}Updated ${diffHours} ${diffHours === 1 ? "hour" : "hours"} ago`;
  const diffDays = Math.round(diffHours / 24);
  return `${prefix}Updated ${diffDays} ${diffDays === 1 ? "day" : "days"} ago`;
}

function radarGroundSurfaceReady(payload: RadarMapResponse | null, requestedRadiusNm: number): boolean {
  if (!payload) return false;
  const centerLat = Number(payload.center?.lat);
  const centerLon = Number(payload.center?.lon);
  if (!Number.isFinite(centerLat) || !Number.isFinite(centerLon)) return false;
  const surfaceState = String(payload.sources?.surface_cache_state || "").trim().toLowerCase();
  if (surfaceState === "disabled") return true;
  const coverage = Number(payload.coverage_radius_nm || payload.radius_nm || 0);
  if (coverage > 0 && coverage + 0.05 < Math.min(5, requestedRadiusNm)) return false;
  const drawableCount = [...(payload.runways || []), ...(payload.surface_features || [])]
    .filter((feature) => Array.isArray(feature.points) && feature.points.length >= 2)
    .length;
  if (drawableCount > 0) return true;
  // An empty payload advertised as ready previously blocked all subsequent
  // surface attempts. Treat it as partial regardless of its cache label.
  return false;
}

function refreshActivityForTarget(target: Screen): ActivityStatus {
  if (target === "fids") {
    return {
      label: "Refreshing Board",
      detail: "Asking Local Flight for the latest flights."
    };
  }
  if (target === "radar") {
    return {
      label: "Loading radar traffic",
      detail: "Asking Local Flight for nearby aircraft."
    };
  }
  if (target === "history") {
    return {
      label: "Reading history",
      detail: "Reading recent local flight history."
    };
  }
  if (target === "control") {
    return {
      label: "Syncing host settings",
      detail: "Reading Local Flight host and display settings."
    };
  }
  return {
    label: "Talking to Local Flight",
    detail: "Checking the connected Local Flight host."
  };
}

function screenNeedsDashboard(target: Screen, standalone: boolean): boolean {
  return standalone
    ? target === "settings"
    : target === "control";
}

export function AppShell() {
  const { appearance, themeMode, skin, hydrated: themeHydrated, setThemeMode, setSkin } = useMobileTheme();
  const supportPurchases = useSupportPurchases();
  const layout = useResponsiveLayout();
  const insets = useSafeAreaInsets();
  const nativeNavigation = runtimeNativeNavigationCapabilities(
    layout.sizeClass,
    MOBILE_V2_ROLLOUT_ENABLED && MOBILE_V2_NATIVE_NAVIGATION_ENABLED
  );
  const [screen, setScreen] = useState<Screen>("fids");
  const [view, setView] = useState<FlightView>("departures");
  const [historyDirection, setHistoryDirection] = useState<HistoryDirection>("both");
  const [historyHours, setHistoryHours] = useState<HistoryWindow>(24);
  const [historyCallsign, setHistoryCallsign] = useState("");
  const [historyAirline, setHistoryAirline] = useState("");
  const [historyFilterRequestKey, setHistoryFilterRequestKey] = useState(0);
  const [historySummary, setHistorySummary] = useState<HistorySummary | null>(null);
  const [radarRadius, setRadarRadius] = useState<RadarRadius>(20);
  const [serverUrl, setServerUrl] = useState("");
  const [draftUrl, setDraftUrl] = useState("");
  const [connected, setConnected] = useState(false);
  const [companionTransport, setCompanionTransport] = useState<"lan" | "remote">("lan");
  const [loading, setLoading] = useState(false);
  const [refreshingByTarget, setRefreshingByTarget] = useState<Partial<Record<Screen, boolean>>>({});
  const [refreshErrorByTarget, setRefreshErrorByTarget] = useState<Partial<Record<Screen, string | null>>>({});
  const [, setActivity] = useState<ActivityStatus | null>(null);
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
  const [weatherSheetVisible, setWeatherSheetVisible] = useState(false);
  const [profiles, setProfiles] = useState<ConfigProfile[]>([]);
  const [applyingProfileId, setApplyingProfileId] = useState<string | null>(null);
  const [standaloneAirportSheetVisible, setStandaloneAirportSheetVisible] = useState(false);
  const [companionIdentity, setCompanionIdentity] = useState<CompanionIdentity | null>(null);
  const [mobileDiagnosticsMode, setMobileDiagnosticsMode] = useState<MobileDiagnosticsMode>("unset");
  const [weatherDisplayMode, setWeatherDisplayMode] = useState<MobileWeatherDisplayMode>("passenger");
  const [widgetPreferences, setWidgetPreferences] = useState<MobileWidgetPreferences>(DEFAULT_WIDGET_PREFERENCES);
  const [widgetSnapshotStatus, setWidgetSnapshotStatus] = useState<WidgetSnapshotStatus>({
    state: "waiting",
    detail: "setup"
  });
  const [widgetBackgroundState, setWidgetBackgroundState] = useState<"checking" | "active" | "restricted" | "off">("checking");
  const [widgetRefreshRequest, setWidgetRefreshRequest] = useState(0);
  const [widgetPendingAirport, setWidgetPendingAirport] = useState<WidgetPendingAirport | null>(null);
  const [widgetSnapshotHydrated, setWidgetSnapshotHydrated] = useState(false);
  const [liveActivitySupported, setLiveActivitySupported] = useState(false);
  const [radarDrawingLayers, setRadarDrawingLayers] = useState<MobileRadarDrawingLayers>({
    runways: true,
    surface: true,
    terrain: true
  });
  const [mobileSetupState, setMobileSetupState] = useState<MobileSetupState>(() => incompleteMobileSetupState());
  const [launchHydrated, setLaunchHydrated] = useState(false);
  const [launchDataOutcome, setLaunchDataOutcome] = useState<LaunchDataOutcome>("pending");
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
  const pendingLaunchUrlRef = useRef<string | null>(null);
  const radarGroundCacheRef = useRef<Map<string, RadarMapResponse>>(new Map());
  const refreshInFlightRef = useRef<Map<string, Promise<void>>>(new Map());
  const dashboardRequestGenerationRef = useRef(0);
  const targetRequestGenerationByTargetRef = useRef<Map<Screen, number>>(new Map());
  const foregroundRefreshGenerationByTargetRef = useRef<Map<Screen, number>>(new Map());
  const foregroundRefreshCountByTargetRef = useRef<Map<Screen, number>>(new Map());
  const fidsRequestGenerationRef = useRef(0);
  const historyRequestGenerationRef = useRef(0);
  const radarRequestGenerationRef = useRef(0);
  const lastFidsRefreshAtRef = useRef(0);
  const lastRadarRefreshAfterRef = useRef<number | null>(null);
  const widgetSnapshotWasReadyRef = useRef(false);
  const lastPinnedWidgetFlightRef = useRef<WidgetFlightPreview | null>(null);
  const liveActivityStartFlightRef = useRef("");
  const previousWidgetAirportKeyRef = useRef("");
  const standaloneBoardRef = useRef<MobileBoardResponse | null>(null);
  const standaloneBoardReadAtRef = useRef(0);
  const flightDetail = useFlightDetail(serverUrl);
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
    notice: detailNotice,
    open: openFlightDetail,
    close: closeFlightDetail,
    refresh: refreshFlightDetail
  } = flightDetail;

  useEffect(() => {
    installGlobalCrashReporter();
  }, []);

  useEffect(() => {
    if (Platform.OS !== "ios") return;
    let alive = true;
    void isLocalFlightLiveActivitySupported().then((result) => {
      if (alive) setLiveActivitySupported(result.supported && result.enabled);
    });
    return () => {
      alive = false;
    };
  }, []);

  if (palette.key !== appearance.key) {
    palette = appearance;
    brand = appearance.brand;
    mono = appearance.mono;
    styles = createStyles();
    setStyleBridge(styles, palette);
  }

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
      setLaunchDataOutcome(
        isMobileSetupComplete(setupState, effectiveSavedUrl || "", hydratedDiagnosticsMode)
          ? "pending"
          : "setup"
      );
      setLaunchHydrated(true);
    },
    []
  );
  const launch = useLaunchOverlay(onLaunchHydrated, launchDataOutcome, themeHydrated);
  const mobileSetupComplete = launchHydrated && isMobileSetupComplete(mobileSetupState, serverUrl, mobileDiagnosticsMode);
  const dismissSetupSuccess = useCallback(() => setSetupSuccess(null), []);
  const isStandalone = mobileSetupState.mode === "standalone";
  useEffect(() => {
    configureRemoteCompanionGrant(isStandalone ? null : mobileSetupState.remoteCompanion);
  }, [isStandalone, mobileSetupState.remoteCompanion]);
  useEffect(() => {
    if (!launchHydrated || !isStandalone) return;
    void migrateStandaloneGroundLayers().then(setRadarDrawingLayers);
  }, [isStandalone, launchHydrated]);
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
    if (/^localflight:\/\/widgets(?:[/?#]|$)/i.test(incomingUrl)) {
      setScreen(isStandalone ? "settings" : "control");
      openMobileMorePanel("widgets");
      if (/[?&]refresh=1(?:&|$)/i.test(incomingUrl)) {
        setWidgetRefreshRequest((value) => value + 1);
      }
      return;
    }
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
      openMobileMorePanel("host");
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
  }, [closeFlightDetail, isStandalone, mobileSetupComplete]);

  const queueOrHandlePairingUrl = useCallback((incomingUrl: string) => {
    if (!launchHydrated) {
      pendingLaunchUrlRef.current = incomingUrl;
      return;
    }
    handlePairingUrl(incomingUrl);
  }, [handlePairingUrl, launchHydrated]);

  useEffect(() => {
    if (!launchHydrated || !pendingLaunchUrlRef.current) return;
    const pendingUrl = pendingLaunchUrlRef.current;
    pendingLaunchUrlRef.current = null;
    handlePairingUrl(pendingUrl);
  }, [handlePairingUrl, launchHydrated]);

  useEffect(() => {
    let alive = true;
    void Linking.getInitialURL().then((url) => {
      if (alive && url && initialPairingUrlRef.current !== url) {
        initialPairingUrlRef.current = url;
        queueOrHandlePairingUrl(url);
      }
    });
    const subscription = Linking.addEventListener("url", (event) => {
      queueOrHandlePairingUrl(event.url);
    });
    return () => {
      alive = false;
      subscription.remove();
    };
  }, [queueOrHandlePairingUrl]);

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
    void Promise.all([
      loadWeatherDisplayMode(),
      loadRadarDrawingLayers(),
      loadWidgetPreferences(),
      readWidgetSnapshot()
    ])
      .then(([mode, layers, widgets, existingWidgetSnapshot]) => {
        if (!alive) return;
        setWeatherDisplayMode(mode);
        setRadarDrawingLayers(layers);
        setWidgetPreferences(widgets);
        if (existingWidgetSnapshot?.small.flight) {
          lastPinnedWidgetFlightRef.current = existingWidgetSnapshot.small.flight;
        }
        widgetSnapshotWasReadyRef.current = Boolean(existingWidgetSnapshot);
      })
      .finally(() => {
        if (alive) setWidgetSnapshotHydrated(true);
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
    if (!normalized.liveActivityEnabled) {
      liveActivityStartFlightRef.current = "";
      await endLocalFlightLiveActivity().catch(() => undefined);
    }
  }, []);

  useEffect(() => {
    if (!launchHydrated) return;
    let alive = true;
    void configureWidgetBackgroundRefresh(mobileSetupComplete && widgetPreferences.automaticRefresh)
      .then((next) => {
        if (alive) setWidgetBackgroundState(next);
      });
    return () => {
      alive = false;
    };
  }, [launchHydrated, mobileSetupComplete, widgetPreferences.automaticRefresh]);

  const fetchDashboard = useCallback(async (normalized: string, requestGeneration: number) => {
    if (standaloneCredentials) {
      const summary = await getStandaloneSummary(standaloneCredentials);
      const config = summary.config;
      if (!config) {
        throw new Error("Standalone relay summary did not include config.");
      }
      if (requestGeneration !== dashboardRequestGenerationRef.current) return;
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
    if (requestGeneration !== dashboardRequestGenerationRef.current) return;
    setAirportDetail((previous) =>
      resolvedAirport || (airportMatchesConfig(previous, config) ? previous : null) || fallbackAirport
    );
    setSnapshot(summary);
    setConnected(true);
    await saveCachedLanConfig(config).catch(() => undefined);
    if (resolvedAirport) {
      await saveCachedLanAirport(resolvedAirport).catch(() => undefined);
    }
  }, [standaloneCredentials]);

  const fetchFidsData = useCallback(async (normalized: string, nextView: FlightView) => {
    const requestGeneration = ++fidsRequestGenerationRef.current;
    if (standaloneCredentials) {
      const existing = standaloneBoardRef.current;
      const existingAgeMs = Date.now() - standaloneBoardReadAtRef.current;
      if (existing && existingAgeMs < Math.max(60, existing.refresh_after_s) * 1000) {
        if (requestGeneration === fidsRequestGenerationRef.current) {
          setRows(nextView === "arrivals" ? existing.arrivals : existing.departures);
          setLaunchDataOutcome((current) => current === "pending" ? "cached" : current);
        }
        return;
      }
      const board = await getStandaloneBoard(standaloneCredentials);
      standaloneBoardRef.current = board;
      standaloneBoardReadAtRef.current = Date.now();
      await Promise.all([
        storeStandaloneFidsRows(standaloneCredentials.airport, board.departures),
        storeStandaloneFidsRows(standaloneCredentials.airport, board.arrivals)
      ]);
      lastFidsRefreshAtRef.current = Date.now();
      if (requestGeneration === fidsRequestGenerationRef.current) {
        setRows(nextView === "arrivals" ? board.arrivals : board.departures);
        setSnapshot((current) => ({
          ...current,
          state: {
            ...(current.state || { ok: true }),
            ok: current.state?.ok !== false,
            last_success_utc: board.generated_at,
            source_name: current.state?.source_name || "relay_standalone"
          }
        }));
        setLaunchDataOutcome((current) => current === "pending" ? "live" : current);
      }
      return;
    }
    const fids = await getFids(normalized, nextView);
    lastFidsRefreshAtRef.current = Date.now();
    if (requestGeneration === fidsRequestGenerationRef.current) {
      setRows(fids);
      setLaunchDataOutcome((current) => current === "pending" ? "live" : current);
    }
  }, [standaloneCredentials]);

  const fetchHistoryData = useCallback(
    async (
      normalized: string,
      nextDirection: HistoryDirection,
      nextHours: HistoryWindow,
      nextCallsign = "",
      nextAirline = ""
    ) => {
      const requestGeneration = ++historyRequestGenerationRef.current;
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
        if (requestGeneration === historyRequestGenerationRef.current) {
          setHistoryData(data);
          setHistorySummary(summary);
        }
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
      if (requestGeneration === historyRequestGenerationRef.current) {
        setHistoryData(data);
        setHistorySummary(summary);
      }
    },
    [standaloneCredentials]
  );

  const fetchRadarData = useCallback(async (
    normalized: string,
    nextRadius: RadarRadius,
    forceGround = false
  ) => {
    const requestGeneration = ++radarRequestGenerationRef.current;
    const isCurrentRadarRequest = () => requestGeneration === radarRequestGenerationRef.current;
    setActivity({
      label: "Loading radar traffic",
      detail: standaloneCredentials
        ? `Asking the hosted relay for standalone tracks inside ${nextRadius} NM.`
        : `Asking the Local Flight host for tracks inside ${nextRadius} NM.`
    });
    if (standaloneCredentials) {
      const data = await getStandaloneRadar(standaloneCredentials, nextRadius);
      if (!isCurrentRadarRequest()) return;
      lastRadarRefreshAfterRef.current = Number(data.refresh_after_s || 0) || null;
      setRadarData(data);
      const cacheKey = [
        "standalone",
        standaloneCredentials.airport.iata || standaloneCredentials.airport.icao,
        nextRadius,
        Number(data.center?.lat || standaloneCredentials.airport.lat || 0).toFixed(5),
        Number(data.center?.lon || standaloneCredentials.airport.lon || 0).toFixed(5)
      ].join("|");
      if (data.radar_map && radarGroundSurfaceReady(data.radar_map, nextRadius)) {
        radarGroundCacheRef.current.set(cacheKey, data.radar_map);
      } else if (data.radar_map) {
        setRadarGroundData(data.radar_map);
      }
      const cachedGround = radarGroundCacheRef.current.get(cacheKey) || null;
      if (cachedGround && !forceGround) {
        setRadarGroundData(cachedGround);
        setRadarGroundError(data.radar_map_error || null);
        return;
      }
      try {
        setActivity({
          label: "Loading runway and surface layer",
          detail: "Fetching the relay's shared airport surface snapshot."
        });
        const ground = await getStandaloneRadarGround(standaloneCredentials, Math.min(10, nextRadius));
        if (!isCurrentRadarRequest()) return;
        if (radarGroundSurfaceReady(ground, Math.min(10, nextRadius))) {
          radarGroundCacheRef.current.set(cacheKey, ground);
        }
        setRadarGroundData(ground);
        setRadarGroundError(radarGroundSurfaceReady(ground, Math.min(10, nextRadius)) ? null : "Surface loading");
      } catch (exc) {
        if (!isCurrentRadarRequest()) return;
        setRadarGroundData(cachedGround);
        setRadarGroundError(cachedGround ? null : errorMessage(exc));
      }
      return;
    }
    const data = await getRadar(normalized, nextRadius);
    if (!isCurrentRadarRequest()) return;
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
        detail: "Fetching runway and surface geometry through the Local Flight host."
      });
      const ground = await getRadarGround(normalized, nextRadius, radarDrawingLayers.terrain);
      if (!isCurrentRadarRequest()) return;
      if (radarGroundSurfaceReady(ground, nextRadius)) {
        radarGroundCacheRef.current.set(cacheKey, ground);
      }
      setRadarGroundData(ground);
      setRadarGroundError(radarGroundSurfaceReady(ground, nextRadius) ? null : "Surface loading");
    } catch (exc) {
      if (!isCurrentRadarRequest()) return;
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
      nextHistoryCallsign = historyCallsign,
      nextHistoryAirline = historyAirline,
      nextRadarRadius = radarRadius,
      forceRadarGround = false,
      includeDashboard = true,
      includeBoardSnapshot = false,
      background = false
    }: RefreshOptions = {}) => {
      const normalized = normalizeServerUrl(nextUrl);
      if (!normalized && !standaloneCredentials) {
        setError(isStandalone ? "Finish Standalone setup before loading relay data." : "Enter the Local Flight host address in More.");
        if (target === "fids") {
          setLaunchDataOutcome((current) => current === "pending" ? "offline" : current);
        }
        return;
      }
      const refreshKey = [
        normalized,
        target,
        nextView,
        nextHistoryDirection,
        nextHistoryHours,
        nextHistoryCallsign,
        nextHistoryAirline,
        nextRadarRadius,
        forceRadarGround ? "ground" : "normal",
        includeDashboard ? "dashboard" : "screen",
        includeBoardSnapshot ? "board" : "target",
        background ? "background" : "foreground"
      ].join("|");
      const existing = refreshInFlightRef.current.get(refreshKey);
      if (existing) {
        await existing;
        return;
      }
      if (background && (foregroundRefreshCountByTargetRef.current.get(target) || 0) > 0) return;

      const refreshGeneration = background
        ? 0
        : (foregroundRefreshGenerationByTargetRef.current.get(target) || 0) + 1;
      if (!background) foregroundRefreshGenerationByTargetRef.current.set(target, refreshGeneration);
      const isCurrentForegroundRefresh = () =>
        !background && refreshGeneration === foregroundRefreshGenerationByTargetRef.current.get(target);
      const dashboardGeneration = includeDashboard ? ++dashboardRequestGenerationRef.current : 0;
      const isCurrentDashboardRequest = () =>
        includeDashboard && dashboardGeneration === dashboardRequestGenerationRef.current;
      const targetGeneration = (targetRequestGenerationByTargetRef.current.get(target) || 0) + 1;
      targetRequestGenerationByTargetRef.current.set(target, targetGeneration);
      const isCurrentTargetRequest = () =>
        targetGeneration === targetRequestGenerationByTargetRef.current.get(target);
      const task = (async () => {
        if (!background) {
          const activeCount = (foregroundRefreshCountByTargetRef.current.get(target) || 0) + 1;
          foregroundRefreshCountByTargetRef.current.set(target, activeCount);
          setRefreshingByTarget((previous) => ({ ...previous, [target]: true }));
          setRefreshErrorByTarget((previous) => ({ ...previous, [target]: null }));
          setActivity(includeDashboard ? {
            label: "Talking to Local Flight",
            detail: "Checking Local Flight host health, settings, budget, and live connections."
          } : refreshActivityForTarget(target));
          setError(null);
        }

        try {
          if (includeDashboard) {
            try {
              await fetchDashboard(normalized, dashboardGeneration);
              if (!isStandalone && isCurrentDashboardRequest()) {
                setCompanionTransport(getLastCompanionTransport());
              }
            } catch (exc) {
              if (isCurrentDashboardRequest()) {
                setConnected(false);
                if (isCurrentForegroundRefresh()) {
                  setRefreshErrorByTarget((previous) => ({ ...previous, [target]: errorMessage(exc) }));
                }
                if (target === "fids") {
                  setLaunchDataOutcome((current) => current === "pending" ? "offline" : current);
                }
                return;
              }
              if (!isCurrentTargetRequest()) return;
            }
          }

          if (!isCurrentTargetRequest()) return;

          try {
            if (isCurrentForegroundRefresh()) setActivity(refreshActivityForTarget(target));
            if (target === "fids") {
              await fetchFidsData(normalized, nextView);
            } else if (target === "history") {
              await fetchHistoryData(normalized, nextHistoryDirection, nextHistoryHours, nextHistoryCallsign, nextHistoryAirline);
            } else if (target === "radar") {
              await fetchRadarData(normalized, nextRadarRadius, forceRadarGround);
            } else if (target === "control") {
              await fetchMatrixRuntime(normalized);
            }
            if (includeBoardSnapshot && target !== "fids") {
              await fetchFidsData(normalized, nextView);
            }
            if (!isStandalone) {
              setCompanionTransport(getLastCompanionTransport());
            }
          } catch (exc) {
            if (isCurrentForegroundRefresh()) {
              setRefreshErrorByTarget((previous) => ({ ...previous, [target]: errorMessage(exc) }));
            }
            if (target === "fids") {
              setLaunchDataOutcome((current) => current === "pending" ? "offline" : current);
            }
          }
        } finally {
          if (!background) {
            const remaining = Math.max(0, (foregroundRefreshCountByTargetRef.current.get(target) || 1) - 1);
            if (remaining) foregroundRefreshCountByTargetRef.current.set(target, remaining);
            else foregroundRefreshCountByTargetRef.current.delete(target);
            const stillRefreshing = remaining > 0;
            setRefreshingByTarget((previous) => ({ ...previous, [target]: stillRefreshing }));
            const anyForegroundRefresh = Array.from(foregroundRefreshCountByTargetRef.current.values())
              .some((count) => count > 0);
            if (!anyForegroundRefresh) setActivity(null);
          }
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
      radarRadius,
      screen,
      standaloneCredentials,
      serverUrl,
      view
    ]
  );

  const refreshWidgetSnapshotNow = useCallback(async () => {
    setWidgetSnapshotStatus({ state: "waiting", detail: "refreshing board" });
    await refreshScreen({ target: "fids", includeDashboard: true });
  }, [refreshScreen]);

  useEffect(() => {
    if (!widgetRefreshRequest || !mobileSetupComplete) return;
    void refreshWidgetSnapshotNow();
  }, [mobileSetupComplete, refreshWidgetSnapshotNow, widgetRefreshRequest]);

  const connect = useCallback(async (
    candidateUrl = draftUrl,
    expectedServerFingerprint = "",
    remoteInvite: RemoteCompanionInvite | null = pairingRemoteInvite
  ) => {
    const normalized = normalizeServerUrl(candidateUrl);
    setLoading(true);
    setActivity({
      label: "Checking Local Flight host address",
      detail: "Asking the Local Flight host to confirm access for this device."
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
        setActivity({
          label: "Verifying Remote Companion",
          detail: "Sending one encrypted test through the relay before saving this pairing."
        });
        const verification = await testRemoteCompanionProbe(remoteGrant, { bypassCooldown: true });
        if (!verification.ok) {
          const failureCode = verification.status === "crypto_failed"
            ? "remote_crypto_failed"
            : `remote_pairing_${verification.status}`;
          throw new Error(`${failureCode}: ${verification.message}`);
        }
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
      setPairingNotice(
        remoteGrant
          ? "Connected on this LAN. Encrypted Remote Companion backup is verified and ready."
          : "Connected on this LAN. Scan the host's LAN + Remote QR later if you also want away-from-home access."
      );
      setPairingUrl("");
      setPairingExpectedServerFingerprint("");
      setPairingRemoteInvite(null);
      setScreen(mobileSetupComplete ? "control" : "fids");
      hapticSuccess();
    } catch (exc) {
      setConnected(false);
      setError(errorMessage(exc));
      hapticWarning();
    } finally {
      setLoading(false);
      setActivity(null);
    }
  }, [draftUrl, mobileDiagnosticsMode, mobileSetupComplete, pairingRemoteInvite]);

  const connectPairingUrl = useCallback((pairing: PairingLinkResult) => {
    setDraftUrl(pairing.serverUrl);
    setPairingUrl(pairing.serverUrl);
    setPairingExpectedServerFingerprint(pairing.expectedServerFingerprint || "");
    setPairingRemoteInvite(pairing.remoteCompanionInvite || null);
    setPairingNonce((value) => value + 1);
    setPairingNotice(
      pairing.remoteCompanionInvite
        ? `Remote Companion QR loaded. Connecting to ${pairing.serverUrl} while this device is on the same Wi-Fi.`
        : `Pairing QR loaded. Connecting this mobile app to ${pairing.serverUrl}.`
    );
    void connect(pairing.serverUrl, pairing.expectedServerFingerprint, pairing.remoteCompanionInvite || null);
  }, [connect]);

  const chooseRadarDrawingLayers = useCallback(async (next: MobileRadarDrawingLayers) => {
    const normalized = { ...next };
    await saveRadarDrawingLayers(normalized);
    const terrainChanged = normalized.terrain !== radarDrawingLayers.terrain;
    setRadarDrawingLayers(normalized);
    if (screen === "radar" && dataReady && terrainChanged) {
      radarGroundCacheRef.current.clear();
      void refreshScreen({ target: "radar", forceRadarGround: true, includeDashboard: false });
    }
  }, [dataReady, radarDrawingLayers.terrain, refreshScreen, screen]);

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
        body: "Standalone is set up for this device.",
        meta: airport.iata || airport.icao || airport.name
      });
      hapticSuccess();
      return;
    }

    if (!nextServerUrl || !config) {
      throw new Error("Mobile setup did not return a Local Flight host address and settings.");
    }
    const normalized = normalizeServerUrl(nextServerUrl);
    const remoteGrantAlreadyVerified = Boolean(pendingRemoteCompanionGrant);
    const remoteGrant = pendingRemoteCompanionGrant || (
      pairingRemoteInvite
        ? await completeRemoteCompanionPairing(normalized, pairingRemoteInvite)
        : null
    );
    if (remoteGrant && !remoteGrantAlreadyVerified) {
      const verification = await testRemoteCompanionProbe(remoteGrant, { bypassCooldown: true });
      if (!verification.ok) {
        const failureCode = verification.status === "crypto_failed"
          ? "remote_crypto_failed"
          : `remote_pairing_${verification.status}`;
        throw new Error(`${failureCode}: ${verification.message}`);
      }
      configureRemoteCompanionGrant(remoteGrant);
      setPendingRemoteCompanionGrant(remoteGrant);
    } else if (remoteGrant) {
      configureRemoteCompanionGrant(remoteGrant);
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
    setPairingNotice(
      remoteGrant
        ? "LAN connection and encrypted Remote Companion backup verified."
        : "LAN connection ready. Remote Companion was not added."
    );
    setPairingUrl("");
    setPairingRemoteInvite(null);
    setScreen("fids");
    setSetupSuccess({
      mode: "lan_companion",
      title: "You are connected",
      body: "This device is paired with your Local Flight host.",
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
    setPairingNotice("Remote Companion fallback forgotten on this device. Pair again from Local Flight Settings to restore access away from the same Wi-Fi.");
  }, [isStandalone, mobileSetupState]);

  const restartSchedulerNow = useCallback(async () => {
    const normalized = normalizeServerUrl(serverUrl);
    if (!normalized) {
      setSchedulerMessage("Set the Local Flight host address first.");
      return;
    }

    setSchedulerRestarting(true);
    setSchedulerMessage("Restarting scheduler...");
    setActivity({
      label: "Restarting Local Flight host update",
      detail: "Asking the Local Flight host for a fresh update."
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
      setError("Set the Local Flight host address first.");
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
      detail: "Saving the profile on the Local Flight host and requesting a fresh update."
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
        : "Automatic diagnostics are disabled on the connected Local Flight host."
    );
  }, [companionIdentity, serverUrl, snapshot]);

  const togglePinnedFlight = useCallback(
    async (row: FidsRow) => {
      const key = flightPinKey(row);
      const next = pinnedCallsign === key ? "" : key;
      liveActivityStartFlightRef.current = next && widgetPreferences.liveActivityEnabled ? next : "";
      if (!next) {
        // Unpinning is an explicit user dismissal. End immediately instead of
        // waiting for the next bounded snapshot write to reconcile ActivityKit.
        await endLocalFlightLiveActivity().catch(() => undefined);
      }
      setPinnedCallsign(next);
      setActionRow(null);
      await savePinnedFlight(next);
    },
    [pinnedCallsign, widgetPreferences.liveActivityEnabled]
  );

  const pinAndShowOnLockScreen = useCallback(async (row: FidsRow) => {
    const key = flightPinKey(row);
    const nextPreferences = await saveWidgetPreferences({
      ...widgetPreferences,
      liveActivityEnabled: true
    });
    setWidgetPreferences(nextPreferences);
    liveActivityStartFlightRef.current = key;
    setPinnedCallsign(key);
    setActionRow(null);
    await savePinnedFlight(key);
    hapticSuccess();
    // The snapshot writer starts ActivityKit only after the pinned snapshot is
    // safely in the shared app-group container. No extension performs a fetch.
  }, [widgetPreferences]);

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
    let disposed = false;
    let retryAttempt = 0;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let activeSocket: WebSocket | null = null;

    const connectSocket = () => {
      if (disposed) return;
      const socket = new WebSocket(wsUrl(serverUrl));
      activeSocket = socket;
      socketRef.current = socket;

      socket.onopen = () => {
        retryAttempt = 0;
      };
      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(String(event.data)) as {
            type?: string;
            config?: AppConfig;
            message?: string;
            ok?: boolean;
          };
          if (message.type === "snapshot_updated") {
            void refreshScreen({
              target: screen,
              includeDashboard: true,
              includeBoardSnapshot: true,
              background: true
            });
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
            void refreshScreen({ target: screen, background: true });
          } else if (message.type === "scheduler_restarted") {
            setSchedulerMessage(message.message || (message.ok ? "Scheduler restarted." : "Scheduler is still stopping."));
            void refreshScreen({
              target: screen,
              includeDashboard: screenNeedsDashboard(screen, isStandalone),
              background: true
            });
          }
        } catch {
          // Ignore non-JSON messages.
        }
      };
      socket.onerror = () => socket.close();
      socket.onclose = () => {
        if (socketRef.current === socket) socketRef.current = null;
        if (disposed || activeSocket !== socket) return;
        const retryDelayMs = Math.min(30_000, 1_000 * (2 ** Math.min(retryAttempt, 5)));
        retryAttempt += 1;
        retryTimer = setTimeout(connectSocket, retryDelayMs);
      };
    };

    connectSocket();

    return () => {
      disposed = true;
      if (retryTimer) clearTimeout(retryTimer);
      if (activeSocket) activeSocket.close();
      if (socketRef.current === activeSocket) socketRef.current = null;
    };
  }, [connected, detailCallsign, detailVisible, isStandalone, refreshFlightDetail, refreshScreen, screen, serverUrl]);

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
          : "Connect to a Local Flight host";
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
    () => widgetRowsPendingAirport
      ? []
      : rows.filter((row) => (row.view === "arrivals" ? "arrivals" : "departures") === view),
    [rows, view, widgetRowsPendingAirport]
  );
  const widgetPreview = useMemo(() => {
    const next = deriveWidgetPreviewSnapshot({
      rows: widgetRowsForPreview,
      pinnedCallsign,
      airportCode,
      airportName,
      updatedLabel: widgetUpdatedLabel(state?.last_success_utc),
      view,
      preferences: widgetPreferences
    });
    if (next.pinnedFlight) {
      lastPinnedWidgetFlightRef.current = next.pinnedFlight;
      return next;
    }
    if (pinnedCallsign && lastPinnedWidgetFlightRef.current?.id === pinnedCallsign) {
      return {
        ...next,
        smallSource: "pinned" as const,
        pinnedFlight: lastPinnedWidgetFlightRef.current
      };
    }
    if (!pinnedCallsign) lastPinnedWidgetFlightRef.current = null;
    return next;
  }, [
    airportCode,
    airportName,
    pinnedCallsign,
    widgetRowsForPreview,
    state?.last_success_utc,
    view,
    widgetPreferences
  ]);
  const refreshing = Boolean(refreshingByTarget[screen]);
  const visibleError = refreshErrorByTarget[screen] || error;
  const boardError = refreshErrorByTarget.fids || error;
  const radarError = refreshErrorByTarget.radar || error;
  const historyError = refreshErrorByTarget.history || error;
  const isLive = connected && state?.ok !== false;
  const connectionState: ConnectionState = isLive
    ? (isStandalone ? "live" : companionTransport)
    : refreshing && visibleError ? "retrying" : "offline";
  const radarSyncIntervalMs = Math.min(
    30 * 60 * 1000,
    Math.max(60 * 1000, (lastRadarRefreshAfterRef.current || 60) * 1000)
  );
  const standaloneBoardIntervalMs = Math.max(
    60 * 1000,
    Number(snapshot.standalone_policy?.board_refresh_seconds || 3600) * 1000
  );
  const standaloneRadarIntervalMs = Math.max(
    60 * 1000,
    Number(snapshot.standalone_policy?.radar_refresh_seconds || 180) * 1000
  );
  const syncIntervalMs = isStandalone
    ? (screen === "radar" ? standaloneRadarIntervalMs : standaloneBoardIntervalMs)
    : (screen === "radar" ? radarSyncIntervalMs : companionSyncMs(cfg?.refresh_seconds));
  const widgetAutomaticLabel = widgetBackgroundState === "active"
    ? "automatic refresh on"
    : widgetBackgroundState === "restricted"
      ? "automatic refresh limited by device"
      : widgetBackgroundState === "off"
        ? "automatic refresh off"
        : "checking automatic refresh";
  const widgetSnapshotLabel = `Snapshot ${widgetSnapshotStatus.state} · ${widgetSnapshotStatus.detail} · ${widgetAutomaticLabel}`;
  const enrichDetailsFromLan = !isStandalone && Boolean(serverUrl);
  const openFidsDetail = useCallback((callsign: string, row?: FidsRow) => {
    const normalizedCallsign = callsign || row?.callsign || row?.id || "";
    if (!normalizedCallsign) return;
    hapticLight();
    openFlightDetail(
      normalizedCallsign,
      row ? fidsRowDetailResponse(row, airportCode) : null,
      { fetch: enrichDetailsFromLan }
    );
  }, [airportCode, enrichDetailsFromLan, openFlightDetail]);
  const openRadarDetail = useCallback((callsign: string, blip?: RadarBlip) => {
    const normalizedCallsign = callsign || blip?.callsign || blip?.flight_number || blip?.display_title || blip?.icao24 || "";
    if (!normalizedCallsign) return;
    hapticLight();
    openFlightDetail(
      normalizedCallsign,
      blip ? radarBlipDetailResponse(blip) : null,
      { fetch: enrichDetailsFromLan }
    );
  }, [enrichDetailsFromLan, openFlightDetail]);
  const openHistoryDetail = useCallback((callsign: string, row?: HistoryFlightRow) => {
    const normalizedCallsign = callsign || row?.callsign || row?.flight_number || String(row?.id || "");
    if (!normalizedCallsign) return;
    hapticLight();
    openFlightDetail(
      normalizedCallsign,
      row ? historyRowDetailResponse(row) : null,
      { fetch: enrichDetailsFromLan }
    );
  }, [enrichDetailsFromLan, openFlightDetail]);

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
    if (!launchHydrated || !widgetSnapshotHydrated) return;
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
      stale: !mobileSetupComplete || !connected || Boolean(boardError) || widgetRowsPendingAirport || Boolean(pinnedCallsign && !rows.some((row) => flightPinKey(row) === pinnedCallsign)),
      sourceLabel,
      sourceUpdatedAt: widgetLastSuccess || null,
      staleAfterMs: widgetSnapshotStaleAfterMs(
        isStandalone ? "standalone" : "lan_companion",
        cfg?.refresh_seconds
      )
    });
    let alive = true;
    void writeWidgetSnapshot(payload, { force: !mobileSetupComplete })
      .then((result) => {
        if (!alive) return;
        if (result.ok) {
          if (mobileSetupComplete) {
            widgetSnapshotWasReadyRef.current = true;
          }
          setWidgetSnapshotStatus({
            state: payload.stale ? "stale" : "ready",
            detail: result.sharedContainer ? "app group" : "app sandbox"
          });
          const requestedFlight = liveActivityStartFlightRef.current;
          if (requestedFlight && payload.liveActivity.flight?.id === requestedFlight) {
            liveActivityStartFlightRef.current = "";
            void startLocalFlightLiveActivity();
          }
        } else {
          setWidgetSnapshotStatus({
            state: "waiting",
            detail: "write deferred"
          });
        }
      })
      .catch(() => {
        if (!alive) return;
        setWidgetSnapshotStatus({
          state: "waiting",
          detail: "write deferred"
        });
      });
    return () => {
      alive = false;
    };
  }, [
    connected,
    boardError,
    isStandalone,
    launchHydrated,
    mobileSetupComplete,
    sourceLabel,
    view,
    widgetRowsPendingAirport,
    pinnedCallsign,
    rows,
    widgetPreferences,
    widgetPreview,
    widgetSnapshotHydrated
  ]);

  useEffect(() => {
    if (!dataReady) return;
    const retryIntervalMs = isStandalone ? 5 * 60 * 1000 : 60 * 1000;
    const effectiveIntervalMs = connected ? syncIntervalMs : Math.min(syncIntervalMs, retryIntervalMs);
    const timer = setInterval(() => {
      void refreshScreen({
        target: screen,
        includeDashboard: true,
        // Companion snapshots can update the Board opportunistically. Standalone
        // Board traffic remains on its conservative three-hour schedule even
        // while Radar refreshes more frequently.
        includeBoardSnapshot: !isStandalone,
        background: true
      });
    }, effectiveIntervalMs);
    return () => clearInterval(timer);
  }, [connected, dataReady, isStandalone, refreshScreen, screen, syncIntervalMs]);

  useEffect(() => {
    if (!dataReady || !connected || !isStandalone || screen === "fids") return;
    const boardIntervalMs = standaloneBoardIntervalMs;
    let cancelled = false;
    let timeout: ReturnType<typeof setTimeout> | null = null;
    const scheduleBoardRefresh = (minimumDelayMs = 1_000) => {
      if (cancelled) return;
      const elapsed = lastFidsRefreshAtRef.current
        ? Date.now() - lastFidsRefreshAtRef.current
        : boardIntervalMs;
      const delay = Math.max(minimumDelayMs, boardIntervalMs - elapsed);
      timeout = setTimeout(() => {
        if (cancelled) return;
        const elapsedAtFire = lastFidsRefreshAtRef.current
          ? Date.now() - lastFidsRefreshAtRef.current
          : boardIntervalMs;
        if (elapsedAtFire < boardIntervalMs) {
          scheduleBoardRefresh();
          return;
        }
        void refreshScreen({ target: "fids", includeDashboard: false, background: true })
          .finally(() => scheduleBoardRefresh(5 * 60 * 1000));
      }, delay);
    };
    scheduleBoardRefresh();
    return () => {
      cancelled = true;
      if (timeout) clearTimeout(timeout);
    };
  }, [connected, dataReady, isStandalone, refreshScreen, screen, standaloneBoardIntervalMs]);

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

  // UIKit owns the compact iPhone tab-bar inset on the Liquid Glass path. The
  // V2 lists opt into automatic adjustment there; every fallback retains the
  // explicit safe-area padding used by the adaptive React Navigation bar.
  const screenContentPadding = nativeNavigation.usesNativeLiquidGlassTabs
    ? 20
    : Math.max(20, insets.bottom + 14);
  const effectiveRadarDrawingLayers = radarDrawingLayers;
  const statusBarStyle = themeMode === "light" ? "dark-content" : "light-content";
  const visibleNotices = [
    ...(snapshot.notices || []),
    ...(screen === "radar" ? (radarData?.notices || []) : [])
  ].filter((notice, index, all) => all.findIndex((item) => item.code === notice.code) === index).slice(0, 2);
  const handleNoticeAction = (notice: ClientNotice) => {
    const action = notice.action;
    if (!action) return;
    if (action.kind === "refresh") {
      void refreshScreen({ target: screen, includeDashboard: screenNeedsDashboard(screen, isStandalone) });
      return;
    }
    if (action.kind === "settings" || action.kind === "logs" || action.kind === "report") {
      setScreen(isStandalone ? "settings" : "control");
      openMobileMorePanel(action.kind === "settings" ? undefined : "advanced");
      return;
    }
    const target = ((action.target || "").split(/[?#]/, 1)[0] || "").replace(/\/$/, "");
    if (target === "/radar") navigateMobileSection("radar");
    else if (target === "/display") openMobileDisplay();
    else if (target === "/fids") navigateMobileSection("board");
    else if (target === "/history") navigateMobileSection("history");
    else if (target === "/settings" || target === "/control") openMobileMorePanel();
    else if (target === "/admin" || target === "/logs" || target === "/feedback") {
      setScreen(isStandalone ? "settings" : "control");
      openMobileMorePanel("advanced");
    } else if (target === "/matrix-preview" || target === "/matrix") {
      setScreen(isStandalone ? "settings" : "control");
      openMobileMorePanel(isStandalone ? "advanced" : "host");
    } else if (target === "/setup") {
      void rerunCompanionSetup();
    }
    else setScreen(isStandalone ? "settings" : "control");
  };

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
          sequence={launch.sequence}
          ambientSweep={launch.ambientSweep}
          logoBreath={launch.logoBreath}
          sequenceComplete={launch.sequenceComplete}
          reduceMotion={launch.reduceMotion}
          ready={launch.ready}
          onEnter={launch.enter}
          status={launch.status}
          qualifier={launch.qualifier}
          entryLabel="Continue setup"
          onFirstFrame={launch.markFirstFrameReady}
        />
      </SafeAreaView>
    );
  }

  if (setupSuccess) {
    return (
      <SafeAreaView style={styles.setupSafe} edges={["top", "bottom", "left", "right"]}>
        <StatusBar barStyle={statusBarStyle} hidden={false} />
        <SetupCompleteOverlay success={setupSuccess} onDismiss={dismissSetupSuccess} />
      </SafeAreaView>
    );
  }

  if (!MOBILE_V2_ROLLOUT_ENABLED) {
    return (
      <SafeAreaView style={styles.setupSafe} edges={["top", "bottom", "left", "right"]}>
        <StatusBar barStyle={statusBarStyle} hidden={false} />
        <View style={styles.setupSuccessCard}>
          <Text style={styles.setupSuccessTitle}>Mobile V2 is disabled for this internal build.</Text>
        </View>
      </SafeAreaView>
    );
  }

  const connectionLabel = connectionState === "lan"
    ? "Connected nearby"
    : connectionState === "remote" || connectionState === "live"
      ? "Connected remotely"
      : "Offline";
  const freshnessLabel = boardFreshnessLabel(state?.last_success_utc, !isLive || Boolean(boardError));
  const handleV2SectionFocus = (section: MobileSection) => {
    const target: Screen = section === "board"
      ? "fids"
      : section === "radar"
        ? "radar"
        : section === "history"
          ? "history"
          : isStandalone
            ? "settings"
            : "control";
    setScreen(target);
  };

  const mobileSession: MobileSessionValue = {
    board: {
      rows,
      view,
      airportCode,
      airportName,
      airportLocation,
      localTime,
      utcTime,
      updatedLabel: freshnessLabel,
      connectionLabel,
      metar: snapshot.metar,
      pinnedCallsign,
      refreshing: Boolean(refreshingByTarget.fids),
      error: boardError,
      layoutClass: layout.sizeClass,
      contentPaddingBottom: screenContentPadding,
      nativeNavigation: nativeNavigation.usesNativeLiquidGlassTabs,
      displayPageSeconds: snapshot.standalone_policy?.display_page_seconds || cfg?.web_rotation_seconds || 8,
      onRefresh: () => { hapticLight(); void refreshScreen({ target: "fids" }); },
      onViewChange: setView,
      onOpenDetail: openFidsDetail,
      onOpenActions: setActionRow,
      onTogglePin: (row) => void togglePinnedFlight(row),
      onOpenAirport: () => isStandalone ? setStandaloneAirportSheetVisible(true) : setConfigSheetVisible(true),
      onOpenWeather: () => setWeatherSheetVisible(true),
      onOpenDisplay: openMobileDisplay
    },
    radar: {
      data: radarData,
      groundData: radarGroundData,
      groundError: radarGroundError,
      metar: snapshot.metar,
      radiusNm: radarRadius,
      radiusOptions: isStandalone ? [1, 3, 5, 10] : [1, 2, 3, 5, 10, 20, 40],
      drawingLayers: effectiveRadarDrawingLayers,
      standalone: isStandalone,
      refreshing: Boolean(refreshingByTarget.radar),
      error: radarError,
      updatedLabel: freshnessLabel,
      layoutClass: layout.sizeClass,
      contentPaddingBottom: screenContentPadding,
      nativeNavigation: nativeNavigation.usesNativeLiquidGlassTabs,
      onRefresh: () => { hapticLight(); void refreshScreen({ target: "radar", forceRadarGround: true }); },
      onRadiusChange: setRadarRadius,
      onDrawingLayersChange: chooseRadarDrawingLayers,
      onOpenDetail: openRadarDetail,
      onOpenWeather: () => setWeatherSheetVisible(true)
    },
    history: {
      data: historyData,
      summary: historySummary,
      direction: historyDirection,
      hours: historyHours,
      callsign: historyCallsign,
      airline: historyAirline,
      refreshing: Boolean(refreshingByTarget.history),
      error: historyError,
      layoutClass: layout.sizeClass,
      contentPaddingBottom: screenContentPadding,
      nativeNavigation: nativeNavigation.usesNativeLiquidGlassTabs,
      filterRequestKey: historyFilterRequestKey,
      onRefresh: () => { hapticLight(); void refreshScreen({ target: "history" }); },
      onApplyFilters: (filters) => {
        const unchanged = filters.direction === historyDirection
          && filters.hours === historyHours
          && filters.callsign === historyCallsign
          && filters.airline === historyAirline;
        setHistoryDirection(filters.direction);
        setHistoryHours(filters.hours);
        setHistoryCallsign(filters.callsign);
        setHistoryAirline(filters.airline);
        if (unchanged) void refreshScreen({ target: "history" });
      },
      onOpenDetail: openHistoryDetail
    },
    notices: visibleNotices,
    onNoticeAction: handleNoticeAction,
    onSectionFocus: handleV2SectionFocus,
    onRefreshCurrent: () => void refreshScreen({
      target: screen,
      forceRadarGround: screen === "radar",
      includeDashboard: screenNeedsDashboard(screen, isStandalone)
    }),
    onOpenSearchOrFilter: () => {
      navigateMobileSection("history");
      setHistoryFilterRequestKey((value) => value + 1);
    },
    onDismissTransientSurface: () => {
      setActionRow(null);
      setConfigSheetVisible(false);
      setWeatherSheetVisible(false);
      setStandaloneAirportSheetVisible(false);
      closeFlightDetail();
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "left", "right"]}>
      <StatusBar barStyle={statusBarStyle} hidden={false} />
      <MobileSessionProvider value={mobileSession}>
        <MobileNavigatorV2
          nativeNavigation={nativeNavigation}
          more={{
            airportCode,
            airportName,
            connectionLabel,
            standalone: isStandalone,
            layoutClass: layout.sizeClass,
            refreshing,
            widgetRefreshing: Boolean(refreshingByTarget.fids),
            contentPaddingBottom: screenContentPadding,
            nativeNavigation: nativeNavigation.usesNativeLiquidGlassTabs,
            supportPurchases,
            widgetPreview,
            widgetPreferences,
            widgetSnapshotLabel,
            liveActivitySupported,
            weatherDisplayMode,
            diagnosticsMode: mobileDiagnosticsMode,
            onRefresh: () => void refreshScreen({
              target: isStandalone ? "settings" : "control",
              includeDashboard: true
            }),
            onRefreshWidget: () => void refreshWidgetSnapshotNow(),
            onWidgetPreferencesChange: (next) => void chooseWidgetPreferences(next),
            onWeatherDisplayModeChange: (next) => void chooseWeatherDisplayMode(next),
            onDiagnosticsModeChange: (next) => void chooseMobileDiagnosticsMode(next),
            onOpenAirport: () => isStandalone ? setStandaloneAirportSheetVisible(true) : setConfigSheetVisible(true),
            onRerunSetup: rerunCompanionSetup
          }}
        />
      </MobileSessionProvider>

      <FlightDetailSheet
        visible={detailVisible}
        callsign={detailCallsign}
        detail={detail}
        history={detailHistory}
        notice={detailNotice}
        loading={detailLoading}
        onClose={closeFlightDetail}
        onRefresh={refreshFlightDetail}
      />

      <WeatherDetailsSheet
        visible={weatherSheetVisible}
        airportCode={airportCode}
        airportName={airportName}
        metar={snapshot.metar}
        mode={weatherDisplayMode}
        onModeChange={(next) => void chooseWeatherDisplayMode(next)}
        onClose={() => setWeatherSheetVisible(false)}
      />

      <FlightActionSheet
        row={actionRow}
        visible={Boolean(actionRow)}
        isPinned={actionRow ? flightPinKey(actionRow) === pinnedCallsign : false}
        onClose={() => setActionRow(null)}
        onOpenDetail={(callsign) => {
          setActionRow(null);
          openFidsDetail(callsign, actionRow || undefined);
        }}
        onTogglePin={togglePinnedFlight}
        onPinAndShow={pinAndShowOnLockScreen}
        canShowLiveActivity={liveActivitySupported}
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
          setSchedulerMessage("Host settings saved. Asking Local Flight for a fresh board…");
          void restartSchedulerNow();
        }}
        onProfilesChange={setProfiles}
      />

      <StandaloneAirportSheet
        visible={standaloneAirportSheetVisible}
        currentAirport={standaloneCredentials?.airport || null}
        onClose={() => setStandaloneAirportSheetVisible(false)}
        onApplied={async (airport) => {
          if (!mobileSetupState.relayInstallId || !mobileSetupState.relayActivationToken) return;
          const nextSetupState = completeStandaloneMobileSetupState({
            relayInstallId: mobileSetupState.relayInstallId,
            relayActivationToken: mobileSetupState.relayActivationToken,
            airport,
            diagnosticsMode: mobileDiagnosticsMode
          });
          await Promise.all([saveStandaloneAirport(airport), saveMobileSetupState(nextSetupState)]);
          setMobileSetupState(nextSetupState);
          setAirportDetail({ ...airport, type: "large_airport" });
          standaloneBoardRef.current = null;
          standaloneBoardReadAtRef.current = 0;
          setRows([]);
          setHistoryData(null);
          setHistorySummary(null);
          setRadarData(null);
          setRadarGroundData(null);
          setRadarGroundError(null);
          radarGroundCacheRef.current.clear();
          setStandaloneAirportSheetVisible(false);
          setScreen("fids");
          navigateMobileSection("board");
          hapticSuccess();
        }}
      />

      <LaunchOverlay
        visible={launch.visible}
        opacity={launch.opacity}
        shift={launch.shift}
        scale={launch.scale}
        sequence={launch.sequence}
        ambientSweep={launch.ambientSweep}
        logoBreath={launch.logoBreath}
        sequenceComplete={launch.sequenceComplete}
        reduceMotion={launch.reduceMotion}
        ready={launch.ready}
        onEnter={launch.enter}
        status={launch.status}
        qualifier={launch.qualifier}
        entryLabel="Open Board"
        onFirstFrame={launch.markFirstFrameReady}
      />
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
  const opacity = useRef(new Animated.Value(0)).current;
  const scale = useRef(new Animated.Value(0.96)).current;
  const dismissedRef = useRef(false);

  const dismiss = useCallback(() => {
    if (dismissedRef.current) return;
    dismissedRef.current = true;
    Animated.parallel([
      Animated.timing(opacity, {
        toValue: 0,
        duration: reduceMotion ? 140 : 180,
        useNativeDriver: true
      }),
      Animated.timing(scale, {
        toValue: reduceMotion ? 0.995 : 0.98,
        duration: reduceMotion ? 140 : 180,
        useNativeDriver: true
      })
    ]).start(() => onDismiss());
  }, [opacity, onDismiss, reduceMotion, scale]);

  useEffect(() => {
    dismissedRef.current = false;
    opacity.setValue(0);
    scale.setValue(reduceMotion ? 0.985 : 0.96);
    Animated.parallel([
      Animated.timing(opacity, {
        toValue: 1,
        duration: reduceMotion ? 180 : 220,
        useNativeDriver: true
      }),
      Animated.spring(scale, {
        toValue: 1,
        damping: reduceMotion ? 24 : 17,
        stiffness: reduceMotion ? 160 : 190,
        mass: 0.8,
        useNativeDriver: true
      })
    ]).start();
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
  // Companion onboarding still shares this restrained brand palette. The
  // launch scene itself owns its semantic styles in LaunchOverlay.
  const splashBg = lightMode ? "#f5f9fc" : "#080c12";
  const splashLineSoft = lightMode ? hexToRgba(palette.line, 0.18) : "rgba(213,244,255,0.08)";
  const splashAccent = lightMode ? palette.blue : "#52f6ff";
  const splashAccentSoft = lightMode ? hexToRgba(palette.blue, 0.28) : "rgba(82,246,255,0.34)";
  const splashAccentFaint = lightMode ? hexToRgba(palette.blue, 0.10) : "rgba(82,246,255,0.08)";
  const splashPlate = lightMode ? "rgba(255,255,255,0.86)" : "rgba(5,12,20,0.84)";
  const splashPlateBorder = lightMode ? hexToRgba(palette.blue, 0.34) : "rgba(216,247,255,0.30)";
  const onGreenText = lightMode && palette.skin === "high_contrast" ? "#ffffff" : "#051009";
  const onBlueText = lightMode && ["standard", "technical", "high_contrast"].includes(palette.skin) ? "#ffffff" : "#051009";
  return StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: palette.bg
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
    fontFamily: UI_FONT_FAMILY,
    color: palette.text,
    fontSize: 22,
    lineHeight: 28,
    fontWeight: "900",
    letterSpacing: 0.6,
    textAlign: "center",
    includeFontPadding: false
  },
  setupSuccessBody: {
    fontFamily: UI_FONT_FAMILY,
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
    fontFamily: UI_FONT_FAMILY,
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
    fontFamily: UI_FONT_FAMILY,
    color: palette.blue2,
    fontSize: 11,
    fontWeight: "700",
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
    fontFamily: UI_FONT_FAMILY,
    color: palette.blue2,
    fontSize: 12,
    fontWeight: "800",
    letterSpacing: 2.4,
    textAlign: "center"
  },
  companionSetupTitle: {
    marginTop: 7,
    fontFamily: UI_FONT_FAMILY,
    color: palette.text,
    fontSize: 27,
    fontWeight: "800",
    textAlign: "center"
  },
  companionSetupBody: {
    fontFamily: UI_FONT_FAMILY,
    marginTop: 8,
    color: palette.textMuted,
    fontSize: 15,
    lineHeight: 21,
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
    fontSize: 11,
    fontWeight: "900",
    textAlign: "center",
    includeFontPadding: false
  },
  companionSetupStepNumberActive: {
    color: palette.green
  },
  companionSetupStepLabel: {
    fontFamily: UI_FONT_FAMILY,
    color: palette.textDim,
    fontSize: 11,
    fontWeight: "700",
    textAlign: "center",
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
    fontFamily: UI_FONT_FAMILY,
    color: palette.text,
    fontSize: 19,
    fontWeight: "800",
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
    fontFamily: UI_FONT_FAMILY,
    color: palette.text,
    fontSize: 14,
    fontWeight: "800"
  },
  companionSetupChecklistBody: {
    fontFamily: UI_FONT_FAMILY,
    marginTop: 2,
    color: palette.textMuted,
    fontSize: 13,
    lineHeight: 18
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
    fontFamily: UI_FONT_FAMILY,
    color: palette.textDim,
    fontSize: 11,
    fontWeight: "700"
  },
  companionSetupInfoValue: {
    marginTop: 5,
    fontFamily: UI_FONT_FAMILY,
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
    fontFamily: UI_FONT_FAMILY,
    color: palette.textDim,
    fontSize: 11,
    fontWeight: "700",
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
    fontFamily: NATIVE_FONT_FAMILY,
    fontSize: 15
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
    fontFamily: UI_FONT_FAMILY,
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
    fontFamily: UI_FONT_FAMILY,
    color: onGreenText,
    fontSize: 15,
    fontWeight: "700",
    textAlign: "center",
    includeFontPadding: false,
    lineHeight: 20
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
    fontFamily: UI_FONT_FAMILY,
    color: palette.blue2,
    fontSize: 14,
    fontWeight: "700",
    textAlign: "center",
    includeFontPadding: false,
    lineHeight: 19
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
    fontFamily: UI_FONT_FAMILY,
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
    fontFamily: UI_FONT_FAMILY,
    color: palette.textDim,
    fontSize: 11,
    fontWeight: "700",
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
    fontFamily: UI_FONT_FAMILY,
    color: palette.text,
    fontSize: 15,
    fontWeight: "800"
  },
  companionSetupRecommended: {
    fontFamily: UI_FONT_FAMILY,
    color: palette.green,
    fontSize: 11,
    fontWeight: "700",
    includeFontPadding: false
  },
  companionSetupOptionBody: {
    marginTop: 5,
    fontFamily: UI_FONT_FAMILY,
    color: palette.textMuted,
    fontSize: 14,
    lineHeight: 20
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
    fontFamily: UI_FONT_FAMILY,
    color: palette.amber,
    fontSize: 12,
    fontWeight: "700"
  },
  companionSetupErrorText: {
    marginTop: 5,
    fontFamily: UI_FONT_FAMILY,
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
  airportIdentityBand: {
    marginTop: 4,
    minHeight: 78,
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 12
  },
  airportHeroPressable: {
    flex: 1,
    minWidth: 0
  },
  identityConnectionBadge: {
    flexShrink: 0,
    minHeight: 30,
    marginTop: 2,
    paddingHorizontal: 9,
    paddingVertical: 6,
    borderRadius: 999,
    borderWidth: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: 6
  },
  identityConnectionDot: {
    width: 7,
    height: 7,
    borderRadius: 4
  },
  identityConnectionText: {
    fontFamily: mono,
    fontSize: 8,
    lineHeight: 10,
    fontWeight: "900",
    letterSpacing: 0.8,
    includeFontPadding: false
  },
  boardHeroWeatherCard: {
    width: "100%",
    alignSelf: "stretch",
    marginTop: 2
  },
  boardHeroWeatherInner: {
    minHeight: 92,
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
  boardHeroWeatherAction: {
    marginTop: 2,
    paddingTop: 7,
    borderTopWidth: 1,
    borderTopColor: hairlineSoft,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 5
  },
  boardHeroWeatherActionLabel: {
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 7,
    lineHeight: 9,
    fontWeight: "900",
    letterSpacing: 1.1,
    includeFontPadding: false
  },
  boardHeroWeatherActionTrail: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5
  },
  boardHeroWeatherActionText: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 7,
    lineHeight: 9,
    fontWeight: "900",
    letterSpacing: 1.1,
    includeFontPadding: false
  },
  boardHeroWeatherActionChevron: {
    color: palette.blue2,
    fontSize: 14,
    lineHeight: 14,
    fontWeight: "800",
    includeFontPadding: false
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
  weatherSheetHero: {
    minHeight: 112,
    padding: 15,
    borderRadius: 20,
    borderWidth: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: 12
  },
  weatherSheetIcon: {
    width: 54,
    height: 54,
    borderRadius: 18,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center"
  },
  weatherSheetHeroCopy: {
    flex: 1,
    minWidth: 0
  },
  weatherSheetAirport: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 13,
    lineHeight: 17,
    fontWeight: "900",
    includeFontPadding: false
  },
  weatherSheetCondition: {
    marginTop: 5,
    color: palette.textMuted,
    fontSize: 12,
    lineHeight: 17
  },
  weatherSheetReading: {
    alignItems: "flex-end",
    gap: 5
  },
  weatherSheetTemperature: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 19,
    lineHeight: 23,
    fontWeight: "900",
    includeFontPadding: false
  },
  weatherSheetCategory: {
    fontFamily: mono,
    fontSize: 10,
    lineHeight: 13,
    fontWeight: "900",
    letterSpacing: 1,
    includeFontPadding: false
  },
  weatherSheetRawCard: {
    padding: 14,
    borderRadius: 15,
    borderWidth: 1,
    borderColor: hairlineSoft,
    backgroundColor: fieldPanel,
    gap: 8
  },
  weatherSheetRawLabel: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 9,
    lineHeight: 12,
    fontWeight: "900",
    letterSpacing: 1.3,
    includeFontPadding: false
  },
  weatherSheetRawText: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 11,
    lineHeight: 17
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
  fidsBoardToolbar: {
    minHeight: 32,
    marginHorizontal: 22,
    marginBottom: 8,
    paddingHorizontal: 10,
    paddingVertical: 7,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: hairlineSoft,
    backgroundColor: palette.rowAlt,
    flexDirection: "row",
    alignItems: "center",
    gap: 8
  },
  fidsBoardControls: {
    marginBottom: 10
  },
  fidsBoardDirectionToggle: {
    marginBottom: 6
  },
  fidsBoardMetaText: {
    flexShrink: 1,
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 8,
    lineHeight: 10,
    fontWeight: "800",
    letterSpacing: 0.7,
    includeFontPadding: false
  },
  fidsBoardMetaDivider: {
    color: palette.textDim,
    fontSize: 8,
    includeFontPadding: false
  },
  snapshotArrivalCue: {
    width: 16,
    height: 16,
    marginLeft: "auto",
    alignItems: "center",
    justifyContent: "center"
  },
  snapshotArrivalRing: {
    position: "absolute",
    width: 10,
    height: 10,
    borderRadius: 5,
    borderWidth: 1,
    borderColor: palette.blue2
  },
  snapshotArrivalCore: {
    width: 4,
    height: 4,
    borderRadius: 2,
    backgroundColor: palette.blue2
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
  historyPanelHint: {
    color: palette.textMuted,
    fontSize: 12,
    lineHeight: 17,
    marginTop: -4,
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
  scopeDotFlash: {
    width: 14,
    height: 14,
    marginLeft: -2,
    marginTop: -2
  },
  scopeDotDiamond: {
    borderRadius: 2,
    transform: [{ rotate: "45deg" }]
  },
  scopeDotHollow: {
    borderWidth: 1.5
  },
  scopeDotFocused: {
    width: 14,
    height: 14,
    marginLeft: -2,
    marginTop: -2,
    borderWidth: 2
  },
  scopeLabelStack: {
    position: "absolute",
    left: 12,
    top: -4,
    width: 82
  },
  scopeLabel: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 9
  },
  scopePhaseLabel: {
    marginTop: 1,
    fontFamily: mono,
    fontSize: 7,
    fontWeight: "800",
    letterSpacing: 0.4
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
