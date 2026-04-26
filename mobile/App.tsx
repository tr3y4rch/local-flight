import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Animated,
  FlatList,
  Modal,
  Pressable,
  RefreshControl,
  SafeAreaView,
  ScrollView,
  StatusBar,
  StyleSheet,
  Text,
  TextInput,
  View
} from "react-native";

import {
  getAdminSystem,
  getBudget,
  getConfig,
  getFids,
  getFidsDetail,
  getHealth,
  getHistory,
  getMetar,
  getRadar,
  normalizeServerUrl,
  testConnection,
  wsUrl
} from "./src/api/client";
import type {
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
import { loadServerUrl, saveServerUrl } from "./src/storage/settings";
import { mono, palette } from "./src/theme/tokens";
import { useResponsiveLayout } from "./src/utils/layout";

type Screen = "fids" | "radar" | "history" | "admin" | "settings";
type StatusTone = "scheduled" | "departed" | "boarding" | "delayed" | "cancelled";
type HistoryWindow = 24 | 72 | 168;
type RadarRadius = 20 | 40 | 80;

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

const APP_VERSION = "0.2.2b1";
const HISTORY_WINDOWS: HistoryWindow[] = [24, 72, 168];
const RADAR_RADII: RadarRadius[] = [20, 40, 80];

const EMPTY_SNAPSHOT: DashboardSnapshot = {
  config: null,
  state: null,
  system: null,
  budget: null,
  metar: null
};

function formatUtc(): string {
  return new Date().toLocaleTimeString("en-GB", {
    timeZone: "UTC",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
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
  const match = route.match(/\(([A-Z0-9]{3,4})\)/);
  return match?.[1] || "";
}

function routeName(route: string): string {
  return route.replace(/\s*\([A-Z0-9]{3,4}\)\s*$/, "").trim() || route || "-";
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

export default function App() {
  const layout = useResponsiveLayout();
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
  const [error, setError] = useState<string | null>(null);
  const [utcTime, setUtcTime] = useState(formatUtc());
  const [snapshot, setSnapshot] = useState<DashboardSnapshot>(EMPTY_SNAPSHOT);
  const [rows, setRows] = useState<FidsRow[]>([]);
  const [historyData, setHistoryData] = useState<HistoryResponse | null>(null);
  const [radarData, setRadarData] = useState<RadarResponse | null>(null);
  const [detailVisible, setDetailVisible] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailCallsign, setDetailCallsign] = useState("");
  const [detailData, setDetailData] = useState<FidsDetailResponse | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const detailRequestRef = useRef(0);

  useEffect(() => {
    const timer = setInterval(() => setUtcTime(formatUtc()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    let alive = true;
    loadServerUrl().then((saved) => {
      if (!alive || !saved) return;
      setServerUrl(saved);
      setDraftUrl(saved);
    });
    return () => {
      alive = false;
    };
  }, []);

  const fetchDashboard = useCallback(async (normalized: string) => {
    const [state, config, system, budget] = await Promise.all([
      getHealth(normalized),
      getConfig(normalized),
      getAdminSystem(normalized),
      getBudget(normalized)
    ]);

    let metar = null;
    try {
      metar = await getMetar(normalized);
    } catch {
      metar = null;
    }

    setSnapshot({ state, config, system, budget, metar });
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
      fetchRadarData,
      historyDirection,
      historyHours,
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

  useEffect(() => {
    if (!serverUrl) return;
    void refreshScreen({ target: screen });
  }, [historyDirection, historyHours, radarRadius, refreshScreen, screen, serverUrl, view]);

  useEffect(() => {
    if (!serverUrl || !connected) return;
    const socket = new WebSocket(wsUrl(serverUrl));
    socketRef.current = socket;

    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(String(event.data)) as { type?: string };
        if (message.type === "snapshot_updated") {
          void refreshScreen({ target: screen });
          if (detailVisible && detailCallsign) {
            void loadFlightDetail(detailCallsign);
          }
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
  const isLive = connected && state?.ok !== false;
  const contentWidth = Math.min(layout.contentMaxWidth, layout.width - 24);
  const detail = detailOrNull(detailData);

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar barStyle="light-content" />
      <View style={[styles.appFrame, { maxWidth: contentWidth }]}>
        <Header
          airportCode={airportCode}
          airportName={airportName}
          live={isLive}
          utcTime={utcTime}
          metarCategory={snapshot.metar?.flight_category || snapshot.metar?.category || "--"}
          metarText={snapshot.metar?.decoded_summary || snapshot.metar?.raw_text || "METAR unavailable"}
        />

        <TopTabs active={screen} onChange={setScreen} />

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
          />
        ) : null}

        {screen === "admin" || screen === "settings" ? (
          <ScrollView
            style={styles.screenScroll}
            contentContainerStyle={styles.screenContent}
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
              <AdminScreen snapshot={snapshot} connected={isLive} error={error} />
            ) : null}

            {screen === "settings" ? (
              <SettingsScreen
                serverUrl={serverUrl}
                draftUrl={draftUrl}
                error={error}
                loading={loading}
                isTablet={layout.isTablet}
                isLandscape={layout.isLandscape}
                onChangeUrl={setDraftUrl}
                onConnect={connect}
              />
            ) : null}
          </ScrollView>
        ) : null}

        <BottomNav active={screen} onChange={setScreen} />
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
    </SafeAreaView>
  );
}

function Header({
  airportCode,
  airportName,
  live,
  utcTime,
  metarCategory,
  metarText
}: {
  airportCode: string;
  airportName: string;
  live: boolean;
  utcTime: string;
  metarCategory: string;
  metarText: string;
}) {
  const dotOpacity = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    if (!live) {
      dotOpacity.setValue(1);
      return;
    }
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
      <View style={styles.dynamicIsland} />
      <View style={styles.statusBar}>
        <Text style={styles.statusTime}>{utcTime}</Text>
        <Text style={styles.statusIcons}>{live ? "ONLINE" : "OFFLINE"}</Text>
      </View>

      <View style={styles.headerTop}>
        <View>
          <Text style={styles.airportCode}>{airportCode}</Text>
          <Text style={styles.airportName}>{airportName}</Text>
        </View>
        <View style={styles.headerRight}>
          <View style={[styles.livePill, !live && styles.livePillOff]}>
            <Animated.View style={[styles.liveDot, !live && styles.liveDotOff, { opacity: dotOpacity }]} />
            <Text style={[styles.liveText, !live && styles.liveTextOff]}>{live ? "LIVE" : "OFF"}</Text>
          </View>
          <Text style={styles.utcTime}>UTC {utcTime}</Text>
        </View>
      </View>

      <View style={styles.metarStrip}>
        <Text style={styles.metarCat}>{metarCategory}</Text>
        <Text style={styles.metarText} numberOfLines={1}>{metarText}</Text>
      </View>
    </View>
  );
}

function TopTabs({ active, onChange }: { active: Screen; onChange: (screen: Screen) => void }) {
  const items: Array<{ id: Screen; icon: string; label: string }> = [
    { id: "fids", icon: "DEP", label: "FIDS" },
    { id: "radar", icon: "RAD", label: "RADAR" },
    { id: "history", icon: "HIS", label: "HISTORY" },
    { id: "admin", icon: "ADM", label: "ADMIN" }
  ];

  return (
    <View style={styles.topTabs}>
      {items.map((item) => {
        const selected = active === item.id;
        return (
          <Pressable key={item.id} style={styles.topTab} onPress={() => onChange(item.id)}>
            <Text style={[styles.topTabIcon, selected && styles.topTabActive]}>{item.icon}</Text>
            <Text style={[styles.topTabLabel, selected && styles.topTabActive]}>{item.label}</Text>
            {selected ? <View style={styles.topTabUnderline} /> : null}
          </Pressable>
        );
      })}
    </View>
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
  onOpenDetail
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
}) {
  const pinned = rows.find((row) => /board|gate|approach/i.test(row.status_display)) || rows[0];

  return (
    <FlatList<FidsRow>
      data={rows}
      keyExtractor={(row) => row.id}
      renderItem={({ item }) => (
        <View style={styles.fidsListItem}>
          <FidsRowView row={item} onOpenDetail={onOpenDetail} />
        </View>
      )}
      style={styles.screenScroll}
      contentContainerStyle={styles.screenContent}
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

          {pinned ? <PinnedFlight row={pinned} onOpenDetail={onOpenDetail} /> : null}

          <View style={styles.fidsHeader}>
            <Text style={styles.fidsHeaderText}>TIME</Text>
            <Text style={styles.fidsHeaderText}>FLIGHT</Text>
            <Text style={styles.fidsHeaderText}>TO</Text>
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
  onOpenDetail
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
      contentContainerStyle={styles.screenContent}
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
  onOpenDetail
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
      contentContainerStyle={styles.screenContent}
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

function PinnedFlight({ row, onOpenDetail }: { row: FidsRow; onOpenDetail: (callsign: string) => void }) {
  return (
    <View style={styles.pinnedSection}>
      <Text style={styles.pinnedLabel}>PINNED</Text>
      <Pressable style={styles.pinnedCard} onPress={() => onOpenDetail(row.callsign)}>
        <Text style={styles.pinnedIcon}>DEP</Text>
        <View style={styles.pinnedInfo}>
          <Text style={styles.pinnedFlight}>{row.flight_display || row.callsign || "-"}</Text>
          <Text style={styles.pinnedRoute}>
            {routeName(row.route_display)} {row.aircraft_type ? `- ${row.aircraft_type}` : ""}
          </Text>
        </View>
        <StatusBadge status={row.status_display} statusClass={row.status_class} />
      </Pressable>
    </View>
  );
}

function FidsRowView({ row, onOpenDetail }: { row: FidsRow; onOpenDetail: (callsign: string) => void }) {
  return (
    <Pressable style={styles.fidsRow} onPress={() => onOpenDetail(row.callsign)}>
      <Text style={styles.fidsTime}>{row.display_time || "--:--"}</Text>
      <Text style={styles.fidsFlight} numberOfLines={1}>{row.flight_display || row.callsign || "-"}</Text>
      <View style={styles.fidsDest}>
        <Text style={styles.fidsDestName} numberOfLines={1}>{routeName(row.route_display)}</Text>
        <Text style={styles.fidsDestCode}>{routeCode(row.route_display) || row.gate || "---"}</Text>
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
  connected,
  error
}: {
  snapshot: DashboardSnapshot;
  connected: boolean;
  error: string | null;
}) {
  const budget = snapshot.budget?.aviationstack;
  return (
    <View style={styles.cardStack}>
      <InfoCard label="SERVER" value={connected ? "ONLINE" : "CHECK"} tone={connected ? "green" : "red"} />
      <InfoCard label="VERSION" value={snapshot.system?.version || APP_VERSION} />
      <InfoCard label="LAST FETCH" value={formatRelative(snapshot.state?.last_success_utc)} tone="amber" />
      <InfoCard label="API BUDGET" value={budget?.remaining != null ? `${budget.remaining} CALLS LEFT` : "UNKNOWN"} />
      <InfoCard label="PLATFORM" value={snapshot.system?.platform || "UNKNOWN"} />
      <InfoCard label="MEMORY" value={snapshot.system?.memory_mb != null ? `${snapshot.system.memory_mb} MB` : "-"} />
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
  onChangeUrl,
  onConnect
}: {
  serverUrl: string;
  draftUrl: string;
  error: string | null;
  loading: boolean;
  isTablet: boolean;
  isLandscape: boolean;
  onChangeUrl: (value: string) => void;
  onConnect: () => void;
}) {
  return (
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
      <Text style={styles.settingsHelp}>
        Use the LAN IP of the machine running Local Flight. On a physical iPhone, localhost points at the phone itself.
      </Text>
    </View>
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

function BottomNav({ active, onChange }: { active: Screen; onChange: (screen: Screen) => void }) {
  const items: Array<{ id: Screen; icon: string; label: string }> = [
    { id: "fids", icon: "F", label: "FIDS" },
    { id: "radar", icon: "R", label: "RADAR" },
    { id: "history", icon: "H", label: "HISTORY" },
    { id: "settings", icon: "S", label: "SETTINGS" }
  ];

  return (
    <View style={styles.bottomNav}>
      {items.map((item) => {
        const selected = active === item.id;
        return (
          <Pressable key={item.id} style={styles.navItem} onPress={() => onChange(item.id)}>
            <Text style={[styles.navIcon, selected && styles.navIconActive]}>{item.icon}</Text>
            <Text style={[styles.navLabel, selected && styles.navLabelActive]}>{item.label}</Text>
          </Pressable>
        );
      })}
      <View style={styles.homeIndicator} />
    </View>
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
  header: {
    paddingTop: 12,
    paddingHorizontal: 22,
    paddingBottom: 16,
    backgroundColor: palette.header,
    borderBottomWidth: 1,
    borderBottomColor: palette.lineSoft
  },
  dynamicIsland: {
    alignSelf: "center",
    width: 118,
    height: 34,
    borderRadius: 20,
    backgroundColor: "#000",
    marginBottom: 8
  },
  statusBar: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginBottom: 14
  },
  statusTime: {
    fontFamily: mono,
    color: "#fff",
    fontSize: 13,
    fontWeight: "700"
  },
  statusIcons: {
    fontFamily: mono,
    color: "#fff",
    opacity: 0.8,
    fontSize: 11,
    fontWeight: "700"
  },
  headerTop: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    marginBottom: 14
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
  utcTime: {
    fontFamily: mono,
    color: palette.textDim,
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
  topTabs: {
    flexDirection: "row",
    backgroundColor: "rgba(10,18,32,0.62)",
    borderBottomWidth: 1,
    borderBottomColor: palette.lineSoft
  },
  topTab: {
    flex: 1,
    alignItems: "center",
    paddingTop: 10,
    paddingBottom: 8,
    position: "relative"
  },
  topTabIcon: {
    fontFamily: mono,
    fontSize: 10,
    color: palette.textDim,
    fontWeight: "700",
    marginBottom: 3
  },
  topTabLabel: {
    fontFamily: mono,
    fontSize: 9,
    color: palette.textDim,
    letterSpacing: 1,
    fontWeight: "700"
  },
  topTabActive: {
    color: palette.blue
  },
  topTabUnderline: {
    position: "absolute",
    bottom: 0,
    left: "22%",
    right: "22%",
    height: 2,
    borderTopLeftRadius: 2,
    borderTopRightRadius: 2,
    backgroundColor: palette.blue
  },
  screenScroll: {
    flex: 1
  },
  screenContent: {
    paddingTop: 12,
    paddingBottom: 104
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
  pinnedSection: {
    paddingHorizontal: 12,
    paddingBottom: 9
  },
  pinnedLabel: {
    paddingHorizontal: 10,
    marginBottom: 6,
    fontFamily: mono,
    color: palette.textDim,
    fontSize: 8,
    letterSpacing: 2,
    fontWeight: "700"
  },
  pinnedCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    padding: 14,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "rgba(74,158,218,0.15)",
    backgroundColor: "rgba(74,158,218,0.07)"
  },
  pinnedIcon: {
    fontFamily: mono,
    color: palette.blue,
    fontSize: 12,
    fontWeight: "700"
  },
  pinnedInfo: {
    flex: 1,
    minWidth: 0
  },
  pinnedFlight: {
    fontFamily: mono,
    color: palette.text,
    fontSize: 14,
    fontWeight: "700"
  },
  pinnedRoute: {
    marginTop: 2,
    color: palette.textMuted,
    fontSize: 11
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
  fidsTime: {
    width: 52,
    fontFamily: mono,
    color: palette.text,
    fontSize: 12,
    fontWeight: "700"
  },
  fidsFlight: {
    width: 70,
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
  bottomNav: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    height: 82,
    flexDirection: "row",
    justifyContent: "space-around",
    alignItems: "flex-start",
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: "rgba(255,255,255,0.06)",
    backgroundColor: "rgba(9,14,22,0.97)"
  },
  navItem: {
    alignItems: "center",
    gap: 4,
    minWidth: 62
  },
  navIcon: {
    width: 25,
    height: 25,
    borderRadius: 999,
    textAlign: "center",
    textAlignVertical: "center",
    overflow: "hidden",
    fontFamily: mono,
    color: palette.textDim,
    borderWidth: 1,
    borderColor: "rgba(74,158,218,0.18)",
    fontSize: 12,
    fontWeight: "700"
  },
  navIconActive: {
    color: palette.blue,
    borderColor: "rgba(74,158,218,0.42)",
    backgroundColor: "rgba(74,158,218,0.12)"
  },
  navLabel: {
    fontFamily: mono,
    fontSize: 8,
    color: palette.textDim,
    letterSpacing: 0.5
  },
  navLabelActive: {
    color: palette.blue
  },
  homeIndicator: {
    position: "absolute",
    bottom: 8,
    left: "50%",
    width: 130,
    height: 4,
    marginLeft: -65,
    borderRadius: 3,
    backgroundColor: "rgba(255,255,255,0.25)"
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
