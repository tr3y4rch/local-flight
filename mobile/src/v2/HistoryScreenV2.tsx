import { useEffect, useMemo, useState } from "react";
import {
  FlatList,
  Modal,
  Pressable,
  RefreshControl,
  SafeAreaView,
  StyleSheet,
  TextInput,
  View
} from "react-native";

import type {
  HistoryDirection,
  HistoryFlightRow,
  HistoryResponse,
  HistorySummary
} from "../api/types";
import { accessibleButton, tapTargetHitSlop } from "../accessibility/mobileA11y";
import { MotionPressable } from "../components/MotionPressable";
import { V2Text as Text } from "../components/V2Text";
import type { HistoryWindow } from "../domain/types";
import { LocalFlightIcon } from "../theme/icons";
import { useMobileTheme } from "../theme/runtime";
import { BOARD_FONT_FAMILY, type MobileAppearance } from "../theme/tokens";
import { hapticLight, hapticSelection } from "../utils/haptics";
import type { LayoutWidthClass } from "../utils/layout";

const HISTORY_WINDOWS: HistoryWindow[] = [24, 72, 168, 720, 2160];

export type HistoryScreenV2Props = {
  data: HistoryResponse | null;
  summary: HistorySummary | null;
  direction: HistoryDirection;
  hours: HistoryWindow;
  callsign: string;
  airline: string;
  refreshing: boolean;
  error: string | null;
  layoutClass: LayoutWidthClass;
  contentPaddingBottom: number;
  /** True only while UIKit owns the compact iPhone tab bar. */
  nativeNavigation?: boolean;
  filterRequestKey: number;
  dismissRequestKey?: number;
  onRefresh: () => void;
  onApplyFilters: (filters: HistoryFilterValues) => void;
  onOpenDetail: (callsign: string, row?: HistoryFlightRow) => void;
};

export type HistoryFilterValues = {
  direction: HistoryDirection;
  hours: HistoryWindow;
  callsign: string;
  airline: string;
};

function periodLabel(hours: HistoryWindow): string {
  if (hours === 24) return "24 hours";
  if (hours === 72) return "3 days";
  if (hours === 168) return "7 days";
  if (hours === 720) return "30 days";
  return "90 days";
}

function shortPeriodLabel(hours: HistoryWindow): string {
  if (hours === 24) return "24h";
  if (hours === 72) return "3d";
  if (hours === 168) return "7d";
  if (hours === 720) return "30d";
  return "90d";
}

function formatMovementTime(row: HistoryFlightRow): string {
  const raw = row.actual_time || row.sched_time || row.event_time || row.snapshot_ts;
  const parsed = Date.parse(raw || "");
  if (!Number.isFinite(parsed)) return "--:--";
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(parsed));
}

function routeLabel(row: HistoryFlightRow): string {
  const origin = row.origin_iata || "—";
  const destination = row.dest_iata || "—";
  return `${origin} → ${destination}`;
}

function statusTone(row: HistoryFlightRow, appearance: MobileAppearance): string {
  const value = row.status.toLowerCase();
  if (value.includes("cancel")) return appearance.red;
  if (value.includes("delay") || (row.delay_minutes || 0) >= 5) return appearance.amber;
  if (value.includes("arriv") || value.includes("depart")) return appearance.green;
  return appearance.blue;
}

function Metric({
  label,
  value,
  note,
  color,
  styles
}: {
  label: string;
  value: string;
  note: string;
  color?: string;
  styles: ReturnType<typeof makeStyles>;
}) {
  return (
    <View style={styles.metricCard}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={[styles.metricValue, color ? { color } : null]}>{value}</Text>
      <Text style={styles.metricNote}>{note}</Text>
    </View>
  );
}

function FilterSheet({
  visible,
  props,
  appearance,
  styles,
  onClose
}: {
  visible: boolean;
  props: HistoryScreenV2Props;
  appearance: MobileAppearance;
  styles: ReturnType<typeof makeStyles>;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<HistoryFilterValues>({
    direction: props.direction,
    hours: props.hours,
    callsign: props.callsign,
    airline: props.airline
  });

  useEffect(() => {
    if (!visible) return;
    setDraft({
      direction: props.direction,
      hours: props.hours,
      callsign: props.callsign,
      airline: props.airline
    });
  }, [props.airline, props.callsign, props.direction, props.hours, visible]);

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}
    >
      <SafeAreaView style={styles.sheetSafe}>
        <View style={styles.sheetHeader}>
          <Pressable style={styles.sheetHeaderButton} onPress={onClose} {...accessibleButton({ label: "Cancel history filters" })}>
            <Text style={styles.sheetCancel}>Cancel</Text>
          </Pressable>
          <Text style={styles.sheetTitle}>Filter history</Text>
          <Pressable
            style={styles.sheetHeaderButton}
            onPress={() => {
              hapticLight();
              props.onApplyFilters(draft);
              onClose();
            }}
            {...accessibleButton({ label: "Apply history filters" })}
          >
            <Text style={styles.sheetDone}>Apply</Text>
          </Pressable>
        </View>

        <View style={styles.sheetBody}>
          <Text style={styles.fieldLabel}>Direction</Text>
          <View style={styles.choiceRow}>
            {([
              ["both", "All"],
              ["dep", "Departures"],
              ["arr", "Arrivals"]
            ] as Array<[HistoryDirection, string]>).map(([value, label]) => {
              const selected = draft.direction === value;
              return (
                <Pressable
                  key={value}
                  style={[styles.choice, selected && styles.choiceSelected]}
                  onPress={() => {
                    hapticSelection();
                    setDraft((current) => ({ ...current, direction: value }));
                  }}
                  {...accessibleButton({ label, selected })}
                >
                  <Text style={[styles.choiceText, selected && styles.choiceTextSelected]}>{label}</Text>
                </Pressable>
              );
            })}
          </View>

          <Text style={styles.fieldLabel}>Period</Text>
          <View style={styles.choiceRow}>
            {HISTORY_WINDOWS.map((value) => {
              const selected = draft.hours === value;
              return (
                <Pressable
                  key={value}
                  style={[styles.choice, selected && styles.choiceSelected]}
                  onPress={() => {
                    hapticSelection();
                    setDraft((current) => ({ ...current, hours: value }));
                  }}
                  {...accessibleButton({ label: periodLabel(value), selected })}
                >
                  <Text style={[styles.choiceText, selected && styles.choiceTextSelected]}>{shortPeriodLabel(value)}</Text>
                </Pressable>
              );
            })}
          </View>

          <Text style={styles.fieldLabel}>Callsign or flight</Text>
          <TextInput
            style={styles.input}
            value={draft.callsign}
            onChangeText={(value) => setDraft((current) => ({ ...current, callsign: value.toUpperCase() }))}
            placeholder="Optional"
            placeholderTextColor={appearance.textDim}
            autoCapitalize="characters"
            autoCorrect={false}
            returnKeyType="search"
          />

          <Text style={styles.fieldLabel}>Airline code</Text>
          <TextInput
            style={styles.input}
            value={draft.airline}
            onChangeText={(value) => setDraft((current) => ({ ...current, airline: value.toUpperCase() }))}
            placeholder="Optional"
            placeholderTextColor={appearance.textDim}
            autoCapitalize="characters"
            autoCorrect={false}
            maxLength={3}
            returnKeyType="search"
          />
        </View>
      </SafeAreaView>
    </Modal>
  );
}

export function HistoryScreenV2(props: HistoryScreenV2Props) {
  const { appearance } = useMobileTheme();
  const styles = useMemo(() => makeStyles(appearance, props.layoutClass), [appearance, props.layoutClass]);
  const [filtersVisible, setFiltersVisible] = useState(false);

  useEffect(() => {
    if (props.filterRequestKey > 0) setFiltersVisible(true);
  }, [props.filterRequestKey]);

  useEffect(() => {
    if (props.dismissRequestKey) setFiltersVisible(false);
  }, [props.dismissRequestKey]);
  const flights = props.data?.flights || [];
  const summary = props.summary;
  const observed = summary?.movement_count ?? summary?.total ?? props.data?.movement_count ?? props.data?.count ?? 0;
  const filterCount = Number(props.direction !== "both") + Number(props.hours !== 24) + Number(Boolean(props.callsign)) + Number(Boolean(props.airline));

  const header = (
    <>
      <View style={styles.titleRow}>
        <View style={styles.titleCopy}>
          <Text style={styles.eyebrow}>This device · {periodLabel(props.hours)}</Text>
          <Text style={styles.title}>History</Text>
          <Text style={styles.subtitle}>A human-scale summary of the arrivals and departures Local Flight observed here.</Text>
        </View>
        <MotionPressable
          style={styles.filterButton}
          interactiveStyle={styles.pressed}
          onPress={() => setFiltersVisible(true)}
          {...accessibleButton({ label: filterCount ? `Filter history, ${filterCount} active filters` : "Filter history" })}
        >
          <LocalFlightIcon name="filter-variant" size={19} color={appearance.blue} />
          <Text style={styles.filterText}>Filter{filterCount ? ` · ${filterCount}` : ""}</Text>
        </MotionPressable>
      </View>

      {props.error ? (
        <Pressable style={styles.errorCard} onPress={props.onRefresh} {...accessibleButton({ label: `${props.error}. Try again.` })}>
          <LocalFlightIcon name="alert-circle-outline" size={20} color={appearance.red} />
          <View style={styles.errorCopy}>
            <Text style={styles.errorTitle}>History could not refresh</Text>
            <Text style={styles.errorBody}>{props.error}</Text>
          </View>
        </Pressable>
      ) : null}

      <View style={styles.metricGrid}>
        <Metric label="Flights observed" value={String(observed)} note="Deduplicated movements" styles={styles} />
        <Metric label="Departures" value={String(summary?.departures ?? "—")} note="Observed outbound" color={appearance.blue} styles={styles} />
        <Metric label="Arrivals" value={String(summary?.arrivals ?? "—")} note="Observed inbound" color={appearance.green} styles={styles} />
        <Metric label="Delayed" value={summary ? `${summary.delayed_pct}%` : "—"} note="Five minutes or more" color={appearance.amber} styles={styles} />
      </View>

      {(summary?.delay_buckets?.length || 0) > 0 ? (
        <View style={styles.summaryPanel}>
          <Text style={styles.panelTitle}>Delay breakdown</Text>
          <View style={styles.delayTrack}>
            {summary!.delay_buckets.map((bucket) => (
              <View
                key={bucket.bucket}
                style={[
                  styles.delaySegment,
                  {
                    width: `${Math.max(bucket.pct, bucket.count ? 2 : 0)}%` as `${number}%`,
                    backgroundColor: bucket.bucket.includes("bad")
                      ? appearance.red
                      : bucket.bucket.includes("warn")
                        ? appearance.amber
                        : bucket.bucket === "early"
                          ? appearance.green
                          : appearance.blue
                  }
                ]}
              />
            ))}
          </View>
          <View style={styles.breakdownRows}>
            {summary!.delay_buckets.map((bucket) => (
              <View key={`label-${bucket.bucket}`} style={styles.breakdownRow}>
                <Text style={styles.breakdownLabel}>{bucket.label}</Text>
                <Text style={styles.breakdownValue}>{bucket.count} · {bucket.pct}%</Text>
              </View>
            ))}
          </View>
        </View>
      ) : null}

      {(summary?.top_airlines?.length || 0) > 0 ? (
        <View style={styles.summaryPanel}>
          <Text style={styles.panelTitle}>Airlines in this local history</Text>
          <Text style={styles.panelNote}>These are incomplete local observations, not a ranking or a measure of airline performance.</Text>
          <View style={styles.airlineWrap}>
            {summary!.top_airlines.slice(0, 8).map((airline) => (
              <View key={airline.code} style={styles.airlineChip}>
                <Text style={styles.airlineCode}>{airline.code || "—"}</Text>
                <Text style={styles.airlineCount}>{airline.count}</Text>
              </View>
            ))}
          </View>
        </View>
      ) : null}

      <View style={styles.listHeading}>
        <Text style={styles.listTitle}>Recent movements</Text>
        <Text style={styles.listMeta}>{flights.length} shown</Text>
      </View>
    </>
  );

  return (
    <>
      <FlatList
        data={flights}
        keyExtractor={(row) => String(row.movement_key || row.id)}
        contentContainerStyle={[styles.content, { paddingBottom: props.contentPaddingBottom }]}
        contentInsetAdjustmentBehavior={props.nativeNavigation ? "automatic" : "never"}
        refreshControl={<RefreshControl refreshing={props.refreshing} tintColor={appearance.blue} onRefresh={props.onRefresh} />}
        ListHeaderComponent={header}
        renderItem={({ item }) => {
          const flight = item.flight_number || item.callsign;
          const tone = statusTone(item, appearance);
          return (
            <MotionPressable
              style={styles.movementRow}
              interactiveStyle={styles.pressed}
              onPress={() => props.onOpenDetail(item.callsign, item)}
              hitSlop={tapTargetHitSlop}
              {...accessibleButton({ label: `${flight}, ${routeLabel(item)}, ${item.status}. Opens details.` })}
            >
              <Text style={styles.movementTime}>{formatMovementTime(item)}</Text>
              <View style={styles.movementMain}>
                <Text style={styles.movementFlight}>{flight}</Text>
                <Text style={styles.movementRoute}>{routeLabel(item)}</Text>
              </View>
              <View style={styles.movementStatusWrap}>
                <Text style={[styles.movementStatus, { color: tone }]} numberOfLines={1}>{item.status || "Observed"}</Text>
                <Text style={styles.movementDirection}>{item.direction === "arr" ? "Arrival" : item.direction === "dep" ? "Departure" : "Movement"}</Text>
              </View>
              <LocalFlightIcon name="chevron-right" size={18} color={appearance.textDim} />
            </MotionPressable>
          );
        }}
        ItemSeparatorComponent={() => <View style={styles.separator} />}
        ListEmptyComponent={
          <View style={styles.empty}>
            <LocalFlightIcon name="history" size={32} color={appearance.textMuted} />
            <Text style={styles.emptyTitle}>No movement history yet</Text>
            <Text style={styles.emptyBody}>History appears after this device observes arrivals or departures.</Text>
          </View>
        }
        showsVerticalScrollIndicator={false}
      />
      <FilterSheet
        visible={filtersVisible}
        props={props}
        appearance={appearance}
        styles={styles}
        onClose={() => setFiltersVisible(false)}
      />
    </>
  );
}

function makeStyles(a: MobileAppearance, layoutClass: LayoutWidthClass) {
  const expanded = layoutClass === "expanded" || layoutClass === "large";
  return StyleSheet.create({
    content: { paddingHorizontal: expanded ? 30 : 16, paddingTop: expanded ? 28 : 18, maxWidth: 1180, width: "100%", alignSelf: "center" },
    titleRow: { flexDirection: "row", alignItems: "flex-start", gap: 16, marginBottom: 18 },
    titleCopy: { flex: 1 },
    eyebrow: { color: a.textMuted, fontSize: 13, marginBottom: 6 },
    title: { color: a.text, fontSize: expanded ? 34 : 28, lineHeight: expanded ? 40 : 34, fontWeight: "700" },
    subtitle: { color: a.textMuted, fontSize: 15, lineHeight: 21, marginTop: 7, maxWidth: 680 },
    filterButton: { minHeight: 44, flexDirection: "row", alignItems: "center", gap: 7, paddingHorizontal: 14, borderRadius: 15, backgroundColor: `${a.blue}12` },
    filterText: { color: a.blue, fontSize: 14, fontWeight: "600" },
    errorCard: { flexDirection: "row", gap: 12, alignItems: "center", padding: 14, borderRadius: 18, backgroundColor: `${a.red}12`, marginBottom: 14 },
    errorCopy: { flex: 1 },
    errorTitle: { color: a.text, fontSize: 14, fontWeight: "700" },
    errorBody: { color: a.textMuted, fontSize: 13, lineHeight: 18, marginTop: 2 },
    metricGrid: { flexDirection: "row", flexWrap: "wrap", gap: expanded ? 14 : 10, marginBottom: 16 },
    metricCard: { flexGrow: 1, flexBasis: expanded ? "22%" : "46%", minWidth: expanded ? 180 : 140, backgroundColor: a.shell, borderRadius: 20, padding: 16 },
    metricLabel: { color: a.textMuted, fontSize: 13 },
    metricValue: { color: a.text, fontSize: 27, lineHeight: 34, fontWeight: "700", fontVariant: ["tabular-nums"], marginTop: 5 },
    metricNote: { color: a.textDim, fontSize: 12, lineHeight: 17, marginTop: 2 },
    summaryPanel: { backgroundColor: a.shell, borderRadius: 22, padding: 18, marginBottom: 14 },
    panelTitle: { color: a.text, fontSize: 17, fontWeight: "700" },
    panelNote: { color: a.textMuted, fontSize: 13, lineHeight: 19, marginTop: 5, maxWidth: 760 },
    delayTrack: { height: 9, overflow: "hidden", borderRadius: 9, flexDirection: "row", backgroundColor: a.lineSoft, marginTop: 16 },
    delaySegment: { height: 9 },
    breakdownRows: { marginTop: 12, gap: 8 },
    breakdownRow: { flexDirection: "row", justifyContent: "space-between", gap: 16 },
    breakdownLabel: { color: a.textMuted, fontSize: 13 },
    breakdownValue: { color: a.text, fontSize: 13, fontVariant: ["tabular-nums"] },
    airlineWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 14 },
    airlineChip: { minHeight: 40, flexDirection: "row", alignItems: "center", gap: 9, paddingHorizontal: 12, borderRadius: 14, backgroundColor: a.lineSoft },
    airlineCode: { color: a.text, fontSize: 14, fontFamily: BOARD_FONT_FAMILY, fontWeight: "700" },
    airlineCount: { color: a.textMuted, fontSize: 13 },
    listHeading: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: 8, marginBottom: 10 },
    listTitle: { color: a.text, fontSize: 18, fontWeight: "700" },
    listMeta: { color: a.textMuted, fontSize: 13 },
    movementRow: { minHeight: 72, flexDirection: "row", alignItems: "center", gap: 13, backgroundColor: a.shell, paddingHorizontal: 15, paddingVertical: 12, borderRadius: 17 },
    pressed: { opacity: 0.74, transform: [{ scale: 0.995 }] },
    movementTime: { width: 58, color: a.text, fontSize: 15, fontFamily: BOARD_FONT_FAMILY, fontVariant: ["tabular-nums"] },
    movementMain: { flex: 1, minWidth: 0 },
    movementFlight: { color: a.text, fontSize: 15, fontFamily: BOARD_FONT_FAMILY, fontWeight: "700" },
    movementRoute: { color: a.textMuted, fontSize: 13, marginTop: 3 },
    movementStatusWrap: { alignItems: "flex-end", maxWidth: 128 },
    movementStatus: { fontSize: 13, fontWeight: "700" },
    movementDirection: { color: a.textDim, fontSize: 11, marginTop: 3 },
    separator: { height: 7 },
    empty: { alignItems: "center", paddingVertical: 52, paddingHorizontal: 20 },
    emptyTitle: { color: a.text, fontSize: 18, fontWeight: "700", marginTop: 13 },
    emptyBody: { color: a.textMuted, fontSize: 14, lineHeight: 20, textAlign: "center", marginTop: 5, maxWidth: 380 },
    sheetSafe: { flex: 1, backgroundColor: a.bg },
    sheetHeader: { height: 58, flexDirection: "row", alignItems: "center", justifyContent: "space-between", borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: a.line, paddingHorizontal: 10 },
    sheetHeaderButton: { minWidth: 66, minHeight: 44, justifyContent: "center", paddingHorizontal: 8 },
    sheetCancel: { color: a.textMuted, fontSize: 16 },
    sheetTitle: { color: a.text, fontSize: 16, fontWeight: "700" },
    sheetDone: { color: a.blue, fontSize: 16, fontWeight: "700", textAlign: "right" },
    sheetBody: { paddingHorizontal: 20, paddingTop: 20 },
    fieldLabel: { color: a.text, fontSize: 14, fontWeight: "600", marginTop: 15, marginBottom: 9 },
    choiceRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
    choice: { minHeight: 44, alignItems: "center", justifyContent: "center", paddingHorizontal: 14, borderRadius: 14, backgroundColor: a.shell },
    choiceSelected: { backgroundColor: `${a.blue}18` },
    choiceText: { color: a.textMuted, fontSize: 14 },
    choiceTextSelected: { color: a.blue, fontWeight: "700" },
    input: { minHeight: 50, color: a.text, fontSize: 16, backgroundColor: a.shell, borderRadius: 15, paddingHorizontal: 14, fontFamily: BOARD_FONT_FAMILY }
  });
}
