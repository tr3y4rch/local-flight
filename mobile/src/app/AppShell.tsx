import { useCallback, useEffect, useRef, useState } from "react";
import {
  Linking,
  RefreshControl,
  ScrollView,
  StatusBar,
  StyleSheet,
  View
} from "react-native";
import * as SplashScreen from "expo-splash-screen";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";

import { BottomNav } from "../components/BottomNav";
import { LaunchOverlay } from "../components/LaunchOverlay";
import { AdminScreen, AirportConfigSheet, ConnectPrompt, FidsScreen, FlightActionSheet, FlightDetailSheet, Header, HistoryScreen, LandscapeDisplay, MatrixScreen, RadarScreen, ScreenError, SettingsScreen } from "../screens/AppScreens";
import {
  getAdminSystem,
  getBudget,
  getConnections,
  getConfig,
  getFids,
  getHealth,
  getHistory,
  getMetar,
  getRadar,
  getUpdates,
  normalizeServerUrl,
  restartScheduler,
  sendCompanionCheckin,
  submitFeedback,
  testConnection,
  wsUrl
} from "../api/client";
import type {
  AppConfig,
  DashboardSnapshot,
  FidsRow,
  FlightView,
  HistoryDirection,
  HistoryResponse,
  RadarResponse
} from "../api/types";
import { installGlobalCrashReporter, reportMobileCrash } from "../crash/reporter";
import type { CompanionIdentity } from "../device/identity";
import {
  COMPANION_PING_MS,
  EMPTY_SNAPSHOT,
  MATRIX_PRESETS
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
import { matrixClientConfig } from "../domain/matrix";
import type {
  FeedbackTone,
  HistoryWindow,
  MatrixPreset,
  RadarRadius,
  RefreshOptions,
  Screen
} from "../domain/types";
import { useFlightDetail } from "../hooks/useFlightDetail";
import { type LaunchHydration, useLaunchOverlay } from "../hooks/useLaunchOverlay";
import { useMatrixCompanion } from "../hooks/useMatrixCompanion";
import { type ConfigProfile, savePinnedFlight, saveServerUrl } from "../storage/settings";
import { useMobileTheme } from "../theme/runtime";
import { setStyleBridge } from "../theme/styleBridge";
import {
  DEFAULT_MOBILE_APPEARANCE,
  type MobileAppearance
} from "../theme/tokens";
import { useResponsiveLayout } from "../utils/layout";

let palette: MobileAppearance = DEFAULT_MOBILE_APPEARANCE;
let mono = DEFAULT_MOBILE_APPEARANCE.mono;

void SplashScreen.preventAutoHideAsync().catch(() => {
  // Ignore duplicate registration during fast refresh.
});
SplashScreen.setOptions({
  duration: 320,
  fade: true
});

export function AppShell() {
  const { appearance, themeMode, skin, setThemeMode, setSkin } = useMobileTheme();
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
  const [feedbackTitle, setFeedbackTitle] = useState("");
  const [feedbackDescription, setFeedbackDescription] = useState("");
  const [feedbackSending, setFeedbackSending] = useState(false);
  const [feedbackMessage, setFeedbackMessage] = useState<string | null>(null);
  const [feedbackTone, setFeedbackTone] = useState<FeedbackTone>("ok");
  const [autoReportMessage, setAutoReportMessage] = useState<string | null>(null);
  const [matrixPreset, setMatrixPreset] = useState<MatrixPreset>(MATRIX_PRESETS[4]!);
  const [pinnedCallsign, setPinnedCallsign] = useState("");
  const [actionRow, setActionRow] = useState<FidsRow | null>(null);
  const [configSheetVisible, setConfigSheetVisible] = useState(false);
  const [profiles, setProfiles] = useState<ConfigProfile[]>([]);
  const [companionIdentity, setCompanionIdentity] = useState<CompanionIdentity | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const flightDetail = useFlightDetail(serverUrl, setError);
  const matrix = useMatrixCompanion(serverUrl);
  const {
    rows: matrixRows,
    runtime: matrixRuntime,
    serverSkin: matrixServerSkin,
    dirty: matrixDirty,
    saving: matrixSaving,
    saveMessage: matrixSaveMessage,
    saveTone: matrixSaveTone,
    fetchRows: fetchMatrixRows,
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
    mono = appearance.mono;
    styles = createStyles();
    setStyleBridge(styles, palette);
  }

  useEffect(() => {
    const timer = setInterval(() => {
      setUtcTime(formatUtc());
      setLocalTime(formatLocalTime());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const onLaunchHydrated = useCallback(
    ({ savedUrl, savedPin, savedProfiles, identity }: LaunchHydration) => {
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
    },
    []
  );
  const launch = useLaunchOverlay(onLaunchHydrated);

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
        if (layout.isLandscape && (target === "fids" || target === "radar")) {
          await Promise.all([
            fetchFidsData(normalized, nextView),
            fetchRadarData(normalized, nextRadarRadius)
          ]);
        } else if (target === "fids") {
          await fetchFidsData(normalized, nextView);
        } else if (target === "history") {
          await fetchHistoryData(normalized, nextHistoryDirection, nextHistoryHours);
        } else if (target === "radar") {
          await fetchRadarData(normalized, nextRadarRadius);
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
      }
    },
    [
      fetchDashboard,
      fetchFidsData,
      fetchHistoryData,
      fetchMatrixRows,
      fetchMatrixRuntime,
      fetchRadarData,
      historyDirection,
      historyHours,
      layout.isLandscape,
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
          void refreshScreen({ target: screen });
          if (detailVisible && detailCallsign) {
            refreshFlightDetail();
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
  }, [connected, detailCallsign, detailVisible, refreshFlightDetail, refreshScreen, screen, serverUrl]);

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
  const pinnedRow = pinnedCallsign
    ? rows.find((row) => flightPinKey(row) === pinnedCallsign) || null
    : null;
  const islandRow =
    pinnedRow || rows.find((row) => /board|gate|approach/i.test(row.status_display)) || rows[0] || null;
  const screenContentPadding = Math.max(20, insets.bottom + 14);
  const matrixPreviewView = matrixRuntime.default_view;
  const matrixPreviewRows = matrixRuntime.max_rows;
  const matrixBrightness = matrixRuntime.brightness;
  const showLandscapeDisplay = layout.isLandscape && (screen === "fids" || screen === "radar");
  const statusBarStyle = themeMode === "light" ? "dark-content" : "light-content";
  const matrixConfigText = matrixClientConfig({
    serverUrl,
    airportIata: cfg?.airport_iata,
    airportIcao: cfg?.airport_icao,
    preset: matrixPreset,
    rows: matrixPreviewRows,
    brightness: matrixBrightness,
    refreshSeconds: matrixRuntime.refresh_seconds,
    view: matrixPreviewView,
    normalizeServerUrl
  });

  return (
    <SafeAreaView style={styles.safe} edges={["top", "left", "right"]}>
      <StatusBar barStyle={statusBarStyle} />
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
          {showLandscapeDisplay ? (
            <LandscapeDisplay
              primary={screen}
              rows={rows}
              view={view}
              radarData={radarData}
              radarRadius={radarRadius}
              refreshing={refreshing}
              error={error}
              showConnectPrompt={!serverUrl}
              onOpenSettings={() => setScreen("settings")}
              onRefreshFids={() => refreshScreen({ target: "fids" })}
              onRefreshRadar={() => refreshScreen({ target: "radar" })}
              onViewChange={setView}
              onRadiusChange={setRadarRadius}
              onOpenDetail={openFlightDetail}
              onOpenActions={setActionRow}
              pinnedCallsign={pinnedCallsign}
              contentPaddingBottom={screenContentPadding}
            />
          ) : null}

          {!showLandscapeDisplay && screen === "fids" ? (
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

          {!showLandscapeDisplay && screen === "radar" ? (
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
              compact={false}
              contentPaddingBottom={screenContentPadding}
            />
          ) : null}

          {screen === "matrix" ? (
            <MatrixScreen
              rows={matrixRows}
              view={matrixPreviewView}
              preset={matrixPreset}
              brightness={matrixBrightness}
              maxRows={matrixPreviewRows}
              refreshSeconds={matrixRuntime.refresh_seconds}
              configText={matrixConfigText}
              matrixSkin={matrixServerSkin}
              matrixEnabled={snapshot.config?.display_outputs?.includes("matrix") || false}
              matrixLastSeen={snapshot.connections?.matrix_last_seen || null}
              dirty={matrixDirty}
              saving={matrixSaving}
              saveMessage={matrixSaveMessage}
              saveTone={matrixSaveTone}
              refreshing={refreshing}
              error={error}
              showConnectPrompt={!serverUrl}
              onOpenSettings={() => setScreen("settings")}
              onRefresh={() => refreshScreen({ target: "matrix" })}
              onViewChange={(value) => updateMatrixDraft({ default_view: value })}
              onPresetChange={setMatrixPreset}
              onBrightnessChange={(value) => updateMatrixDraft({ brightness: value })}
              onRowsChange={(value) => updateMatrixDraft({ max_rows: value })}
              onRefreshSecondsChange={(value) => updateMatrixDraft({ refresh_seconds: value })}
              onSave={saveMatrixDraftNow}
              onReset={resetMatrixDraft}
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
                  themeMode={themeMode}
                  skin={skin}
                  outputs={snapshot.config?.display_outputs || []}
                  refreshSeconds={snapshot.config?.refresh_seconds ?? null}
                  schedulerRestarting={schedulerRestarting}
                  schedulerMessage={schedulerMessage}
                  onThemeModeChange={setThemeMode}
                  onSkinChange={setSkin}
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

        <BottomNav
          active={screen}
          onChange={setScreen}
          insetBottom={insets.bottom}
          palette={palette}
          styles={styles}
        />
      </View>

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
          void refreshScreen({ target: screen });
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
  const accent30 = hexToRgba(palette.blue, 0.30);
  const accent40 = hexToRgba(palette.blue, 0.40);
  const accent42 = hexToRgba(palette.blue, 0.42);
  const success08 = hexToRgba(palette.green, 0.08);
  const success10 = hexToRgba(palette.green, 0.10);
  const success12 = hexToRgba(palette.green, 0.12);
  const success16 = hexToRgba(palette.green, 0.16);
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
  return StyleSheet.create({
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
    backgroundColor: accent14
  },
  launchHaloInner: {
    position: "absolute",
    width: 238,
    height: 238,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "rgba(122,176,216,0.24)",
    borderTopColor: "rgba(41,226,135,0.72)",
    borderRightColor: warn38,
    backgroundColor: "rgba(255,255,255,0.018)"
  },
  launchPanel: {
    minWidth: 250,
    paddingHorizontal: 28,
    paddingVertical: 30,
    borderRadius: 28,
    borderWidth: 1,
    borderColor: accent16,
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
    borderColor: accent18,
    backgroundColor: accent08,
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
    borderColor: accent16,
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
    borderColor: success25,
    backgroundColor: success10
  },
  livePillOff: {
    borderColor: error25,
    backgroundColor: error10
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
    borderColor: error18,
    backgroundColor: error08
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
    borderColor: accent40,
    backgroundColor: accent12
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
    backgroundColor: accent12,
    borderColor: accent20
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
    borderColor: warn24,
    backgroundColor: warn07
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
    borderColor: accent14,
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
    borderColor: accent18,
    backgroundColor: "rgba(0,0,0,0.18)",
    overflow: "hidden"
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
    alignItems: "center"
  },
  statusBadgeCompact: {
    width: 78,
    paddingHorizontal: 5
  },
  status_scheduled: { backgroundColor: accent10 },
  status_departed: { backgroundColor: accent06, opacity: 0.68 },
  status_boarding: { backgroundColor: success12 },
  status_delayed: { backgroundColor: warn11 },
  status_cancelled: { backgroundColor: error12 },
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
    borderColor: warn22,
    backgroundColor: warn08
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
    borderColor: accent14,
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
  matrixBoard: {
    marginTop: 12,
    padding: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: success16,
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
    backgroundColor: "#0b121c",
    paddingTop: 10
  },
  actionSheetCard: {
    marginHorizontal: 12,
    marginBottom: 12,
    padding: 18,
    borderRadius: 24,
    borderWidth: 1,
    borderColor: accent16,
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
    borderColor: accent18,
    backgroundColor: accent08
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
    paddingVertical: 10,
    alignItems: "center",
    backgroundColor: "rgba(255,255,255,0.03)"
  },
  configSegOptionActive: {
    backgroundColor: accent16
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
    borderColor: accent40,
    backgroundColor: accent12
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
  },
  splitDisplay: {
    flex: 1,
    flexDirection: "row",
    gap: 8,
    paddingHorizontal: 8
  },
  splitPane: {
    flex: 1,
    minWidth: 0
  },
  splitPanePrimary: {
    flex: 1.12
  },
  splitPaneSecondary: {
    flex: 0.88
  },
  scopeFooter: {
    marginTop: 12,
    gap: 10
  },
  scopeHint: {
    color: palette.textMuted,
    fontSize: 11
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
  matrixActionRow: {
    flexDirection: "row",
    gap: 10,
    marginTop: 14
  },
  matrixActionButton: {
    minHeight: 44,
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 10,
    paddingHorizontal: 12,
    borderWidth: 1
  },
  matrixActionPrimary: {
    backgroundColor: palette.blue,
    borderColor: accent30
  },
  matrixActionSecondary: {
    backgroundColor: "rgba(255,255,255,0.03)",
    borderColor: accent16
  },
  matrixActionPrimaryText: {
    fontFamily: mono,
    color: palette.bg,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.8
  },
  matrixActionSecondaryText: {
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.8
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
    fontFamily: mono,
    color: palette.blue2,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 1
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
