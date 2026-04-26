import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
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
  getHealth,
  getMetar,
  normalizeServerUrl,
  testConnection,
  wsUrl
} from "./src/api/client";
import type { DashboardSnapshot, FidsRow, FlightView } from "./src/api/types";
import { loadServerUrl, saveServerUrl } from "./src/storage/settings";
import { useResponsiveLayout } from "./src/utils/layout";

type Screen = "fids" | "radar" | "history" | "admin" | "alerts" | "settings";
type StatusTone = "scheduled" | "departed" | "boarding" | "delayed" | "cancelled";

const APP_VERSION = "0.2.2b1";

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

export default function App() {
  const layout = useResponsiveLayout();
  const [screen, setScreen] = useState<Screen>("fids");
  const [view, setView] = useState<FlightView>("departures");
  const [serverUrl, setServerUrl] = useState("");
  const [draftUrl, setDraftUrl] = useState("");
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [utcTime, setUtcTime] = useState(formatUtc());
  const [snapshot, setSnapshot] = useState<DashboardSnapshot>(EMPTY_SNAPSHOT);
  const [rows, setRows] = useState<FidsRow[]>([]);
  const socketRef = useRef<WebSocket | null>(null);

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

  const refreshAll = useCallback(async (url = serverUrl, nextView = view) => {
    const normalized = normalizeServerUrl(url);
    if (!normalized) {
      setError("Enter the Local Flight server URL in Settings.");
      return;
    }

    setRefreshing(true);
    setError(null);
    try {
      const [state, config, system, budget, fids] = await Promise.all([
        getHealth(normalized),
        getConfig(normalized),
        getAdminSystem(normalized),
        getBudget(normalized),
        getFids(normalized, nextView)
      ]);

      let metar = null;
      try {
        metar = await getMetar(normalized);
      } catch {
        metar = null;
      }

      setSnapshot({ state, config, system, budget, metar });
      setRows(fids);
      setConnected(true);
    } catch (exc) {
      setConnected(false);
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setRefreshing(false);
    }
  }, [serverUrl, view]);

  const connect = useCallback(async () => {
    const normalized = normalizeServerUrl(draftUrl);
    setLoading(true);
    setError(null);
    try {
      await testConnection(normalized);
      await saveServerUrl(normalized);
      setServerUrl(normalized);
      setDraftUrl(normalized);
      setConnected(true);
      await refreshAll(normalized);
    } catch (exc) {
      setConnected(false);
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  }, [draftUrl, refreshAll]);

  useEffect(() => {
    if (!serverUrl) return;
    refreshAll(serverUrl, view);
  }, [serverUrl, view, refreshAll]);

  useEffect(() => {
    if (!serverUrl || !connected) return;
    const socket = new WebSocket(wsUrl(serverUrl));
    socketRef.current = socket;

    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(String(event.data)) as { type?: string };
        if (message.type === "snapshot_updated") {
          refreshAll(serverUrl, view);
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
  }, [connected, refreshAll, serverUrl, view]);

  const cfg = snapshot.config;
  const state = snapshot.state;
  const airportCode = cfg?.airport_iata || "---";
  const airportName = cfg?.airport_icao ? `${cfg.airport_icao} Local Flight` : "Connect your server";
  const isLive = connected && state?.ok !== false;
  const contentWidth = Math.min(layout.contentMaxWidth, layout.width - 24);

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

        <ScrollView
          style={styles.screenScroll}
          contentContainerStyle={styles.screenContent}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              tintColor={palette.blue}
              onRefresh={() => refreshAll()}
            />
          }
        >
          {!serverUrl ? (
            <ConnectPrompt onSettings={() => setScreen("settings")} />
          ) : null}

          {screen === "fids" ? (
            <FidsScreen rows={rows} view={view} onViewChange={setView} loading={refreshing} />
          ) : null}

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

          {screen === "radar" ? <PlaceholderScreen title="Radar" body="Native radar comes next with react-native-svg." /> : null}
          {screen === "history" ? <PlaceholderScreen title="History" body="Flight history detail sheets will land after pairing/auth." /> : null}
          {screen === "alerts" ? <PlaceholderScreen title="Alerts" body="Pinned flight alerts and notifications are queued for the next mobile slice." /> : null}
        </ScrollView>

        <BottomNav active={screen} onChange={setScreen} />
      </View>
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
  return (
    <View style={styles.header}>
      <View style={styles.dynamicIsland} />
      <View style={styles.statusBar}>
        <Text style={styles.statusTime}>09:41</Text>
        <Text style={styles.statusIcons}>WiFi 100%</Text>
      </View>

      <View style={styles.headerTop}>
        <View>
          <Text style={styles.airportCode}>{airportCode}</Text>
          <Text style={styles.airportName}>{airportName}</Text>
        </View>
        <View style={styles.headerRight}>
          <View style={[styles.livePill, !live && styles.livePillOff]}>
            <View style={[styles.liveDot, !live && styles.liveDotOff]} />
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
  onViewChange,
  loading
}: {
  rows: FidsRow[];
  view: FlightView;
  onViewChange: (view: FlightView) => void;
  loading: boolean;
}) {
  const pinned = rows.find((row) => /board|gate|approach/i.test(row.status_display)) || rows[0];

  return (
    <View>
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

      {pinned ? <PinnedFlight row={pinned} /> : null}

      <View style={styles.fidsHeader}>
        <Text style={styles.fidsHeaderText}>TIME</Text>
        <Text style={styles.fidsHeaderText}>FLIGHT</Text>
        <Text style={styles.fidsHeaderText}>TO</Text>
        <Text style={styles.fidsHeaderText}>STATUS</Text>
        <Text style={[styles.fidsHeaderText, styles.alignRight]}>A/C</Text>
      </View>

      <View style={styles.fidsList}>
        {rows.map((row) => <FidsRowView key={row.id} row={row} />)}
        {loading && rows.length === 0 ? <ActivityIndicator color={palette.blue} style={styles.loader} /> : null}
        {!loading && rows.length === 0 ? (
          <Text style={styles.empty}>No rows yet. Complete setup or run a snapshot fetch on the server.</Text>
        ) : null}
      </View>
    </View>
  );
}

function DirectionButton({ active, label, onPress }: { active: boolean; label: string; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={[styles.dirButton, active && styles.dirButtonActive]}>
      <Text style={[styles.dirButtonText, active && styles.dirButtonTextActive]}>{label}</Text>
    </Pressable>
  );
}

function PinnedFlight({ row }: { row: FidsRow }) {
  return (
    <View style={styles.pinnedSection}>
      <Text style={styles.pinnedLabel}>PINNED</Text>
      <View style={styles.pinnedCard}>
        <Text style={styles.pinnedIcon}>DEP</Text>
        <View style={styles.pinnedInfo}>
          <Text style={styles.pinnedFlight}>{row.flight_display || row.callsign || "-"}</Text>
          <Text style={styles.pinnedRoute}>{routeName(row.route_display)} {row.aircraft_type ? `- ${row.aircraft_type}` : ""}</Text>
        </View>
        <StatusBadge status={row.status_display} statusClass={row.status_class} />
      </View>
    </View>
  );
}

function FidsRowView({ row }: { row: FidsRow }) {
  return (
    <Pressable style={styles.fidsRow}>
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

function PlaceholderScreen({ title, body }: { title: string; body: string }) {
  return (
    <View style={styles.placeholderCard}>
      <Text style={styles.placeholderTitle}>{title}</Text>
      <Text style={styles.placeholderBody}>{body}</Text>
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
    { id: "alerts", icon: "A", label: "ALERTS" },
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

const palette = {
  bg: "#080c12",
  shell: "#0d1520",
  header: "#0a1220",
  line: "#1e3a5a",
  lineSoft: "rgba(255,255,255,0.05)",
  row: "rgba(255,255,255,0.022)",
  rowAlt: "rgba(255,255,255,0.03)",
  text: "#e8f0fe",
  textMuted: "#4a7aaa",
  textDim: "#2a5a8a",
  blue: "#4a9eda",
  blue2: "#7ab0d8",
  green: "#00c040",
  amber: "#f0b429",
  red: "#ff6b6b",
  status: {
    scheduled: "#4a9eda",
    departed: "#7ab0d8",
    boarding: "#00c040",
    delayed: "#f0b429",
    cancelled: "#ff6b6b"
  }
};

const mono = "Menlo";

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
  fidsList: {
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
  placeholderCard: {
    marginHorizontal: 12,
    padding: 18,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "rgba(74,158,218,0.14)",
    backgroundColor: palette.row
  },
  placeholderTitle: {
    fontFamily: mono,
    color: palette.blue,
    fontSize: 18,
    fontWeight: "700"
  },
  placeholderBody: {
    marginTop: 8,
    color: palette.textMuted,
    fontSize: 13,
    lineHeight: 20
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
