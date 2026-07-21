import { useMemo, type ReactNode } from "react";
import {
  FlatList,
  Platform,
  Pressable,
  RefreshControl,
  StyleSheet,
  View,
  type ViewStyle
} from "react-native";

import type { FidsRow, FlightView, Metar } from "../api/types";
import { accessibleButton, tapTargetHitSlop } from "../accessibility/mobileA11y";
import { BrandWordmark } from "../components/Brand";
import { MotionPressable } from "../components/MotionPressable";
import { V2Text as Text } from "../components/V2Text";
import { ACTION_ICONS, LocalFlightIcon } from "../theme/icons";
import { BOARD_FONT_FAMILY, type MobileAppearance } from "../theme/tokens";
import { useMobileTheme } from "../theme/runtime";
import { hapticLight, hapticSelection } from "../utils/haptics";
import { boardRowsViewModel, type BoardRowViewModel } from "./boardModel";
import { airportHeroViewModel } from "./airportHeroModel";

export type V2LayoutClass = "compact" | "medium" | "expanded" | "large";

export type BoardScreenV2Props = {
  rows: FidsRow[];
  view: FlightView;
  airportCode: string;
  airportName: string;
  airportLocation: string;
  localTime: string;
  utcTime: string;
  updatedLabel: string;
  connectionLabel: string;
  metar: Metar | null;
  pinnedCallsign: string;
  refreshing: boolean;
  error: string | null;
  layoutClass: V2LayoutClass;
  contentPaddingBottom: number;
  /** True only while UIKit owns the compact iPhone tab bar. */
  nativeNavigation?: boolean;
  displayPageSeconds?: number;
  onRefresh: () => void;
  onViewChange: (view: FlightView) => void;
  onOpenDetail: (callsign: string, row?: FidsRow) => void;
  onOpenActions: (row: FidsRow) => void;
  onTogglePin: (row: FidsRow) => void;
  onOpenAirport: () => void;
  onOpenWeather: () => void;
  onOpenDisplay: () => void;
};

function statusColor(row: BoardRowViewModel, appearance: MobileAppearance): string {
  return appearance.status[row.statusTone];
}

function HoverPressable({
  children,
  style,
  onPress,
  onLongPress,
  accessibilityLabel,
  accessibilityHint
}: {
  children: ReactNode;
  style: ViewStyle | ViewStyle[];
  onPress: () => void;
  onLongPress?: () => void;
  accessibilityLabel: string;
  accessibilityHint?: string;
}) {
  return (
    <MotionPressable
      style={style}
      interactiveStyle={localStyles.interactiveHover}
      focusable
      onPress={onPress}
      onLongPress={onLongPress}
      delayLongPress={360}
      hitSlop={tapTargetHitSlop}
      {...accessibleButton({ label: accessibilityLabel, hint: accessibilityHint })}
    >
      {children}
    </MotionPressable>
  );
}

function BoardRowCompact({
  row,
  appearance,
  styles,
  onOpen,
  onActions,
  onTogglePin
}: {
  row: BoardRowViewModel;
  appearance: MobileAppearance;
  styles: ReturnType<typeof makeStyles>;
  onOpen: () => void;
  onActions: () => void;
  onTogglePin: () => void;
}) {
  const tone = statusColor(row, appearance);
  const detail = [row.gate && `Gate ${row.gate}`, row.aviationDetail].filter(Boolean).join(" · ");
  return (
    <HoverPressable
      style={[styles.rowCard, row.pinned ? styles.rowPinned : {}]}
      onPress={onOpen}
      onLongPress={onActions}
      accessibilityLabel={`${row.time}, ${row.flight}, ${row.routeName}, ${row.status}${row.gate ? `, gate ${row.gate}` : ""}`}
      accessibilityHint="Opens flight details. Long press for more actions."
    >
      <View style={styles.rowTopline}>
        <Text style={styles.rowTime}>{row.time}</Text>
        <View style={styles.rowIdentity}>
          <Text style={styles.rowFlight} numberOfLines={1}>{row.flight}</Text>
          {row.airline ? <Text style={styles.rowAirline} numberOfLines={1}>{row.airline}</Text> : null}
        </View>
        <View style={[styles.statusChip, { backgroundColor: `${tone}18` }]}>
          <Text style={[styles.statusText, { color: tone }]} numberOfLines={1}>{row.status}</Text>
        </View>
      </View>
      <View style={styles.rowBottomline}>
        <View style={styles.routeCopy}>
          <Text style={styles.routeName} numberOfLines={1}>{row.routeName}</Text>
          <Text style={styles.routeMeta} numberOfLines={1}>{[row.routeCode, detail].filter(Boolean).join(" · ")}</Text>
        </View>
        <Pressable
          style={[styles.pinButton, row.pinned && styles.pinButtonActive]}
          onPress={(event) => {
            event.stopPropagation();
            hapticSelection();
            onTogglePin();
          }}
          hitSlop={tapTargetHitSlop}
          {...accessibleButton({ label: row.pinned ? `Unpin ${row.flight}` : `Pin ${row.flight}`, selected: row.pinned })}
        >
          <LocalFlightIcon name={row.pinned ? "pin" : "pin-outline"} size={17} color={row.pinned ? appearance.amber : appearance.textMuted} />
        </Pressable>
      </View>
    </HoverPressable>
  );
}

function BoardRowWide({
  row,
  appearance,
  styles,
  onOpen,
  onActions
}: {
  row: BoardRowViewModel;
  appearance: MobileAppearance;
  styles: ReturnType<typeof makeStyles>;
  onOpen: () => void;
  onActions: () => void;
}) {
  const tone = statusColor(row, appearance);
  return (
    <HoverPressable
      style={[styles.wideRow, row.pinned ? styles.rowPinned : {}]}
      onPress={onOpen}
      onLongPress={onActions}
      accessibilityLabel={`${row.time}, ${row.flight}, ${row.routeName}, ${row.status}${row.gate ? `, gate ${row.gate}` : ""}`}
      accessibilityHint="Opens flight details. Long press for more actions."
    >
      <Text style={[styles.wideCellTime, styles.wideTime]}>{row.time}</Text>
      <View style={styles.wideCellFlight}>
        <Text style={styles.wideFlight} numberOfLines={1}>{row.flight}</Text>
        <Text style={styles.wideSubline} numberOfLines={1}>{row.airline || row.callsign}</Text>
      </View>
      <View style={styles.wideCellRoute}>
        <Text style={styles.wideRoute} numberOfLines={1}>{row.routeName}</Text>
        <Text style={styles.wideSubline} numberOfLines={1}>{row.routeCode}</Text>
      </View>
      <View style={styles.wideCellStatus}>
        <Text style={[styles.wideStatus, { color: tone }]} numberOfLines={1}>{row.status}</Text>
      </View>
      <Text style={styles.wideCellAircraft} numberOfLines={1}>{row.aircraft || "—"}</Text>
      <Text style={styles.wideCellGate} numberOfLines={1}>{row.gate || "—"}</Text>
    </HoverPressable>
  );
}

export function BoardScreenV2(props: BoardScreenV2Props) {
  const { appearance } = useMobileTheme();
  const styles = useMemo(
    () => makeStyles(appearance, props.layoutClass),
    [appearance, props.layoutClass]
  );
  const rows = useMemo(
    () => boardRowsViewModel(props.rows, props.pinnedCallsign).filter((row) => row.view === props.view),
    [props.pinnedCallsign, props.rows, props.view]
  );
  const pinned = rows.find((row) => row.pinned) || null;
  const wide = props.layoutClass !== "compact";
  const directionLabel = props.view === "arrivals" ? "Arrivals" : "Departures";
  const airportHero = airportHeroViewModel({
    airportName: props.airportName,
    airportCode: props.airportCode,
    location: props.airportLocation,
    localTime: props.localTime,
    connectionLabel: props.connectionLabel,
    freshnessLabel: props.updatedLabel,
    metar: props.metar
  });

  const header = (
    <>
      <View style={styles.hero}>
        <View style={styles.heroHorizon} />
        <View style={styles.brandRail}>
          <BrandWordmark color={appearance.text} size={wide ? 20 : 17}>Local Flight</BrandWordmark>
        </View>

        <View style={styles.airportRow}>
          <Pressable
            style={styles.airportCopy}
            onPress={() => {
              hapticSelection();
              props.onOpenAirport();
            }}
            {...accessibleButton({ label: `${airportHero.airportName}. Change airport.` })}
          >
            <Text style={styles.airportName} numberOfLines={3}>{airportHero.airportName}</Text>
            <Text style={styles.airportLocation} numberOfLines={2}>
              {airportHero.airportCode ? <Text style={styles.airportCode}>{airportHero.airportCode}</Text> : null}
              {airportHero.airportCode && airportHero.location ? " · " : ""}
              {airportHero.location}
            </Text>
          </Pressable>
          <Pressable
            style={styles.weatherButton}
            onPress={() => {
              hapticLight();
              props.onOpenWeather();
            }}
            {...accessibleButton({ label: `${airportHero.weatherSummary}, ${airportHero.temperature}. Opens weather details.` })}
          >
            <Text style={styles.weatherTemperature}>{airportHero.temperature}</Text>
            <View style={styles.weatherCopy}>
              <Text style={styles.weatherSummary} numberOfLines={2}>{airportHero.weatherSummary}</Text>
              <Text style={styles.weatherMeta}>Tap for weather details</Text>
            </View>
            <Text style={styles.weatherCategory}>{airportHero.weatherCategory}</Text>
          </Pressable>
        </View>

        <View style={styles.clockRail}>
          <View>
            <Text style={styles.clockLabel}>Airport time</Text>
            <Text style={styles.clockValue}>{airportHero.localTime}</Text>
          </View>
          <View style={styles.clockSecondary}>
            <View style={styles.connectionLine}>
              <View style={[styles.connectionDot, { backgroundColor: airportHero.connectionLabel === "Offline" ? appearance.red : appearance.green }]} />
              <Text style={styles.clockLabel}>{airportHero.connectionLabel}</Text>
            </View>
            <Text style={styles.freshness}>{airportHero.freshnessLabel}</Text>
            <Text style={styles.utcValue}>{props.utcTime}Z</Text>
          </View>
        </View>
      </View>

      {pinned ? (
        <MotionPressable
          style={styles.pinnedCard}
          onPress={() => props.onOpenDetail(pinned.callsign, pinned.raw)}
          onLongPress={() => props.onOpenActions(pinned.raw)}
          {...accessibleButton({ label: `Pinned flight ${pinned.flight}, ${pinned.status}. Opens details.` })}
        >
          <View style={styles.pinnedAccent} />
          <View style={styles.pinnedCopy}>
            <Text style={styles.pinnedEyebrow}>Pinned flight</Text>
            <Text style={styles.pinnedFlight}>{pinned.flight}</Text>
            <Text style={styles.pinnedRoute} numberOfLines={1}>{pinned.routeName} · {pinned.time}</Text>
          </View>
          <Text style={[styles.pinnedStatus, { color: statusColor(pinned, appearance) }]}>{pinned.status}</Text>
        </MotionPressable>
      ) : null}

      <View style={styles.boardToolbar}>
        <View style={styles.segmentedControl} accessibilityRole="tablist">
          {(["departures", "arrivals"] as FlightView[]).map((option) => {
            const selected = props.view === option;
            return (
              <Pressable
                key={option}
                style={[styles.segment, selected && styles.segmentSelected]}
                onPress={() => {
                  hapticSelection();
                  props.onViewChange(option);
                }}
                accessibilityRole="tab"
                accessibilityState={{ selected }}
                accessibilityLabel={option === "arrivals" ? "Arrivals" : "Departures"}
              >
                <Text style={[styles.segmentText, selected && styles.segmentTextSelected]}>
                  {option === "arrivals" ? "Arrivals" : "Departures"}
                </Text>
              </Pressable>
            );
          })}
        </View>
        <Pressable
          style={styles.displayButton}
          onPress={() => {
            hapticLight();
            props.onOpenDisplay();
          }}
          {...accessibleButton({ label: `Present ${directionLabel} board in fullscreen display mode.` })}
        >
          <LocalFlightIcon name="monitor-dashboard" size={18} color={appearance.blue} />
          <Text style={styles.displayButtonText}>Display</Text>
        </Pressable>
      </View>

      {wide ? (
        <View style={styles.columnHeader}>
          <Text style={styles.wideCellTime}>Time</Text>
          <Text style={styles.wideCellFlight}>Flight</Text>
          <Text style={styles.wideCellRoute}>Route</Text>
          <Text style={styles.wideCellStatus}>Status</Text>
          <Text style={styles.wideCellAircraft}>Aircraft</Text>
          <Text style={styles.wideCellGate}>Gate</Text>
        </View>
      ) : null}

      {props.error ? (
        <Pressable style={styles.errorCard} onPress={props.onRefresh} {...accessibleButton({ label: `${props.error}. Retry refresh.` })}>
          <LocalFlightIcon name={ACTION_ICONS.retry} size={18} color={appearance.red} />
          <Text style={styles.errorText}>{props.error}</Text>
        </Pressable>
      ) : null}
    </>
  );

  return (
    <FlatList
      data={rows}
      keyExtractor={(item) => item.id}
      renderItem={({ item }) => wide ? (
        <BoardRowWide
          row={item}
          appearance={appearance}
          styles={styles}
          onOpen={() => props.onOpenDetail(item.callsign, item.raw)}
          onActions={() => props.onOpenActions(item.raw)}
        />
      ) : (
        <BoardRowCompact
          row={item}
          appearance={appearance}
          styles={styles}
          onOpen={() => props.onOpenDetail(item.callsign, item.raw)}
          onActions={() => props.onOpenActions(item.raw)}
          onTogglePin={() => props.onTogglePin(item.raw)}
        />
      )}
      ListHeaderComponent={header}
      ListEmptyComponent={
        <View style={styles.emptyState}>
          <LocalFlightIcon name="airplane-clock" size={30} color={appearance.textMuted} />
          <Text style={styles.emptyTitle}>No {directionLabel.toLowerCase()} on the board</Text>
          <Text style={styles.emptyBody}>Pull to refresh. A cached board remains visible whenever Local Flight has one.</Text>
        </View>
      }
      ItemSeparatorComponent={() => <View style={styles.rowGap} />}
      contentContainerStyle={[styles.content, { paddingBottom: props.contentPaddingBottom }]}
      contentInsetAdjustmentBehavior={props.nativeNavigation ? "automatic" : "never"}
      refreshControl={<RefreshControl refreshing={props.refreshing} onRefresh={props.onRefresh} tintColor={appearance.blue} />}
      showsVerticalScrollIndicator={false}
    />
  );
}

const localStyles = StyleSheet.create({
  interactiveHover: {
    transform: [{ translateY: -1 }]
  },
  interactivePressed: {
    opacity: 0.82,
    transform: [{ scale: 0.995 }]
  }
});

function makeStyles(a: MobileAppearance, layoutClass: V2LayoutClass) {
  const roomyBoard = layoutClass === "large";
  const compact = layoutClass === "compact";
  const shadow = Platform.select({
    ios: { shadowColor: "#000", shadowOpacity: a.themeMode === "dark" ? 0.22 : 0.08, shadowRadius: 18, shadowOffset: { width: 0, height: 8 } },
    android: { elevation: 2 },
    default: {}
  });
  return StyleSheet.create({
    content: { width: "100%", maxWidth: 1320, alignSelf: "center", paddingHorizontal: roomyBoard ? 22 : 12, paddingTop: 12 },
    hero: { backgroundColor: a.header, borderRadius: 28, padding: 20, overflow: "hidden", marginBottom: 14, ...shadow },
    heroHorizon: { position: "absolute", width: 280, height: 280, borderRadius: 140, right: -110, top: -170, backgroundColor: `${a.blue}16` },
    brandRail: { flexDirection: "row", alignItems: "center" },
    connectionDot: { width: 7, height: 7, borderRadius: 4 },
    freshness: { color: a.textMuted, fontSize: 12, lineHeight: 16, marginTop: 4, textAlign: "right" },
    airportRow: { flexDirection: compact ? "column" : "row", alignItems: "stretch", gap: compact ? 16 : 18, marginTop: compact ? 22 : 28 },
    airportCopy: { flex: 1, justifyContent: "center", minWidth: 0 },
    airportName: { color: a.text, fontSize: compact ? 30 : 34, lineHeight: compact ? 35 : 40, fontWeight: "700" },
    airportLocation: { color: a.textMuted, fontSize: 15, lineHeight: 21, marginTop: 7 },
    airportCode: { color: a.textMuted, fontFamily: BOARD_FONT_FAMILY, fontWeight: "700" },
    weatherButton: { width: compact ? "100%" : roomyBoard ? 280 : 230, minHeight: compact ? 84 : 118, flexDirection: "row", alignItems: "center", gap: 12, borderRadius: 22, padding: 14, backgroundColor: `${a.blue}10` },
    weatherTemperature: { color: a.text, fontSize: compact ? 28 : 31, lineHeight: 35, fontWeight: "700", fontVariant: ["tabular-nums"] },
    weatherCopy: { flex: 1, minWidth: 0 },
    weatherSummary: { color: a.text, fontSize: 14, lineHeight: 19, fontWeight: "600" },
    weatherMeta: { color: a.textMuted, fontSize: 11, lineHeight: 15, marginTop: 3 },
    weatherCategory: { color: a.green, fontSize: 12, fontFamily: BOARD_FONT_FAMILY, fontWeight: "700" },
    clockRail: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-end", marginTop: 24 },
    clockSecondary: { flex: 1, alignItems: "flex-end", paddingLeft: 18 },
    connectionLine: { flexDirection: "row", alignItems: "center", justifyContent: "flex-end", gap: 7 },
    clockLabel: { color: a.textMuted, fontSize: 12 },
    clockValue: { color: a.text, fontSize: 22, lineHeight: 27, fontFamily: BOARD_FONT_FAMILY, fontVariant: ["tabular-nums"], marginTop: 2 },
    utcValue: { color: a.textMuted, fontSize: 13, fontFamily: BOARD_FONT_FAMILY, fontVariant: ["tabular-nums"], marginTop: 3 },
    pinnedCard: { flexDirection: "row", alignItems: "center", backgroundColor: a.shell, borderRadius: 22, overflow: "hidden", marginBottom: 14, minHeight: 90, ...shadow },
    pinnedAccent: { width: 5, alignSelf: "stretch", backgroundColor: a.amber },
    pinnedCopy: { flex: 1, paddingHorizontal: 16, paddingVertical: 14, minWidth: 0 },
    pinnedEyebrow: { color: a.textMuted, fontSize: 12 },
    pinnedFlight: { color: a.text, fontSize: 20, lineHeight: 25, fontFamily: BOARD_FONT_FAMILY, fontWeight: "700", marginTop: 3 },
    pinnedRoute: { color: a.textMuted, fontSize: 14, marginTop: 3 },
    pinnedStatus: { fontSize: 13, fontWeight: "700", marginRight: 18, maxWidth: 120, textAlign: "right" },
    boardToolbar: { flexDirection: "row", alignItems: "center", gap: 12, marginBottom: 12 },
    segmentedControl: { flex: 1, flexDirection: "row", borderRadius: 16, backgroundColor: a.lineSoft, padding: 4 },
    segment: { flex: 1, minHeight: 44, justifyContent: "center", alignItems: "center", borderRadius: 13 },
    segmentSelected: { backgroundColor: a.shell, ...shadow },
    segmentText: { color: a.textMuted, fontSize: 15, fontWeight: "600" },
    segmentTextSelected: { color: a.text },
    displayButton: { minHeight: 50, flexDirection: "row", alignItems: "center", gap: 7, paddingHorizontal: 14, borderRadius: 16, backgroundColor: `${a.blue}12` },
    displayButtonText: { color: a.blue, fontSize: 14, fontWeight: "700" },
    columnHeader: { flexDirection: "row", alignItems: "center", paddingHorizontal: roomyBoard ? 18 : 12, paddingVertical: 10 },
    rowCard: { backgroundColor: a.shell, borderRadius: 20, padding: 16, ...shadow },
    rowPinned: { backgroundColor: `${a.amber}12` },
    rowTopline: { flexDirection: "row", alignItems: "center", gap: 12 },
    rowTime: { width: 58, color: a.text, fontSize: 18, fontFamily: BOARD_FONT_FAMILY, fontWeight: "700", fontVariant: ["tabular-nums"] },
    rowIdentity: { flex: 1, minWidth: 0 },
    rowFlight: { color: a.text, fontSize: 17, lineHeight: 21, fontFamily: BOARD_FONT_FAMILY, fontWeight: "700" },
    rowAirline: { color: a.textMuted, fontSize: 12, marginTop: 2 },
    statusChip: { maxWidth: 122, minHeight: 36, paddingHorizontal: 11, borderRadius: 12, justifyContent: "center", alignItems: "center" },
    statusText: { fontSize: 12, lineHeight: 16, fontWeight: "700", textAlign: "center" },
    rowBottomline: { flexDirection: "row", alignItems: "flex-end", gap: 10, marginTop: 13, paddingTop: 12, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: a.lineSoft },
    routeCopy: { flex: 1, minWidth: 0 },
    routeName: { color: a.text, fontSize: 16, fontWeight: "600" },
    routeMeta: { color: a.textMuted, fontSize: 12, lineHeight: 17, marginTop: 3 },
    pinButton: { width: 42, height: 42, alignItems: "center", justifyContent: "center", borderRadius: 14, backgroundColor: a.lineSoft },
    pinButtonActive: { backgroundColor: `${a.amber}18` },
    wideRow: { flexDirection: "row", alignItems: "center", minHeight: 78, backgroundColor: a.shell, borderRadius: 18, paddingHorizontal: roomyBoard ? 18 : 12, paddingVertical: 12, ...shadow },
    wideCellTime: { width: roomyBoard ? 84 : 58, color: a.textMuted, fontSize: 12 },
    wideCellFlight: { flex: 0.95, minWidth: roomyBoard ? 100 : 68, color: a.textMuted, fontSize: 12 },
    wideCellRoute: { flex: 1.55, minWidth: roomyBoard ? 150 : 92, color: a.textMuted, fontSize: 12 },
    wideCellStatus: { flex: 1.05, minWidth: roomyBoard ? 110 : 78, color: a.textMuted, fontSize: 12 },
    wideCellAircraft: { width: roomyBoard ? 92 : 68, color: a.textMuted, fontSize: 12 },
    wideCellGate: { width: roomyBoard ? 72 : 48, color: a.textMuted, fontSize: 12, textAlign: "right" },
    wideTime: { color: a.text, fontSize: 18, fontFamily: BOARD_FONT_FAMILY, fontWeight: "700", fontVariant: ["tabular-nums"] },
    wideFlight: { color: a.text, fontSize: 17, fontFamily: BOARD_FONT_FAMILY, fontWeight: "700" },
    wideSubline: { color: a.textMuted, fontSize: 12, marginTop: 3 },
    wideRoute: { color: a.text, fontSize: 16, fontWeight: "600" },
    wideStatus: { fontSize: 13, fontWeight: "700" },
    errorCard: { flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: `${a.red}12`, borderRadius: 16, padding: 14, marginBottom: 12 },
    errorText: { flex: 1, color: a.red, fontSize: 14, lineHeight: 20 },
    emptyState: { alignItems: "center", paddingVertical: 56, paddingHorizontal: 24 },
    emptyTitle: { color: a.text, fontSize: 19, fontWeight: "700", marginTop: 14, textAlign: "center" },
    emptyBody: { color: a.textMuted, fontSize: 15, lineHeight: 22, marginTop: 8, textAlign: "center", maxWidth: 420 },
    rowGap: { height: 10 }
  });
}
