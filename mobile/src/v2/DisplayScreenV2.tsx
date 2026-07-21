import { useEffect, useMemo, useState } from "react";
import { Dimensions, Pressable, StatusBar, StyleSheet, useWindowDimensions, View } from "react-native";
import * as ScreenOrientation from "expo-screen-orientation";
import { useKeepAwake } from "expo-keep-awake";
import { SafeAreaView } from "react-native-safe-area-context";

import type { FidsRow, FlightView, Metar } from "../api/types";
import { accessibleButton, useReducedMotionPreference } from "../accessibility/mobileA11y";
import { BrandWordmark } from "../components/Brand";
import { V2Text as Text } from "../components/V2Text";
import { LocalFlightIcon } from "../theme/icons";
import { BOARD_FONT_FAMILY, type MobileAppearance } from "../theme/tokens";
import { useMobileTheme } from "../theme/runtime";
import { boardRowsViewModel, type BoardRowViewModel } from "./boardModel";
import { airportHeroViewModel } from "./airportHeroModel";

export type DisplayScreenV2Props = {
  rows: FidsRow[];
  view: FlightView;
  airportCode: string;
  airportName: string;
  airportLocation?: string;
  localTime: string;
  updatedLabel: string;
  metar: Metar | null;
  pinnedCallsign: string;
  pageSeconds?: number;
  onExit: () => void;
};

function chunkRows<T>(rows: T[], size: number): T[][] {
  if (!rows.length) return [[]];
  const pages: T[][] = [];
  for (let index = 0; index < rows.length; index += size) {
    pages.push(rows.slice(index, index + size));
  }
  return pages;
}

function statusColor(row: BoardRowViewModel, a: MobileAppearance): string {
  return a.status[row.statusTone];
}

export function DisplayScreenV2({
  rows,
  view,
  airportCode,
  airportName,
  airportLocation = "",
  localTime,
  updatedLabel,
  metar,
  pinnedCallsign,
  pageSeconds = 8,
  onExit
}: DisplayScreenV2Props) {
  useKeepAwake();
  const reduceMotion = useReducedMotionPreference();
  const { appearance } = useMobileTheme();
  const { width, height } = useWindowDimensions();
  const styles = useMemo(() => makeStyles(appearance), [appearance]);
  const [paused, setPaused] = useState(reduceMotion);
  const [pageIndex, setPageIndex] = useState(0);
  // Orientation is the one place where the physical screen matters: a tablet
  // in Split View can have a phone-width window but must still respect the
  // user's current window orientation. All composition remains width-driven.
  const screen = Dimensions.get("screen");
  const compactScreen = Math.min(screen.width, screen.height) < 600;
  const pageSize = height < 430 ? 4 : height < 650 ? 6 : 8;
  const boardRows = useMemo(
    () => boardRowsViewModel(rows, pinnedCallsign).filter((row) => row.view === view),
    [pinnedCallsign, rows, view]
  );
  const pages = useMemo(() => chunkRows(boardRows, pageSize), [boardRows, pageSize]);
  const page = pages[Math.min(pageIndex, pages.length - 1)] || [];
  const airportHero = airportHeroViewModel({
    airportName,
    airportCode,
    location: airportLocation,
    localTime,
    freshnessLabel: updatedLabel,
    metar
  });

  useEffect(() => {
    setPaused(reduceMotion);
  }, [reduceMotion]);

  useEffect(() => {
    if (!compactScreen) return;
    void ScreenOrientation.lockAsync(ScreenOrientation.OrientationLock.LANDSCAPE).catch(() => undefined);
    return () => {
      void ScreenOrientation.unlockAsync().catch(() => undefined);
    };
  }, [compactScreen]);

  useEffect(() => {
    setPageIndex((current) => Math.min(current, Math.max(0, pages.length - 1)));
  }, [pages.length]);

  useEffect(() => {
    if (paused || reduceMotion || pages.length <= 1) return;
    const timer = setInterval(() => {
      setPageIndex((current) => (current + 1) % pages.length);
    }, Math.max(3, pageSeconds) * 1000);
    return () => clearInterval(timer);
  }, [pageSeconds, pages.length, paused, reduceMotion]);

  const nextPage = () => {
    setPaused(true);
    setPageIndex((current) => (current + 1) % pages.length);
  };

  const previousPage = () => {
    setPaused(true);
    setPageIndex((current) => (current - 1 + pages.length) % pages.length);
  };

  return (
    <SafeAreaView
      style={styles.safe}
      edges={["top", "bottom", "left", "right"]}
      onAccessibilityEscape={onExit}
    >
      <StatusBar hidden />
      <View style={styles.header}>
        <View style={styles.brandBlock}>
          <BrandWordmark color={appearance.text} size={18}>Local Flight</BrandWordmark>
          <Text style={styles.airport} numberOfLines={2} adjustsFontSizeToFit minimumFontScale={0.78}>{airportHero.airportName}</Text>
          <Text style={styles.airportIdentity} numberOfLines={1}>
            {airportHero.airportCode ? <Text style={styles.airportCode}>{airportHero.airportCode}</Text> : null}
            {airportHero.airportCode && airportHero.location ? " · " : ""}
            {airportHero.location}
          </Text>
        </View>
        <View style={styles.headerCenter}>
          <Text style={styles.boardTitle}>{view === "arrivals" ? "Arrivals" : "Departures"}</Text>
          <Text style={styles.update} numberOfLines={2}>{airportHero.freshnessLabel}</Text>
        </View>
        <View style={styles.headerMeta}>
          <View style={styles.weatherLine}>
            <Text style={styles.localTime}>{airportHero.localTime}</Text>
            <Text style={styles.weatherTemperature}>{airportHero.temperature}</Text>
          </View>
          <Text style={styles.weather} numberOfLines={2}>{airportHero.weatherSummary} · {airportHero.weatherCategory}</Text>
        </View>
        <Pressable style={styles.exitButton} onPress={onExit} {...accessibleButton({ label: "Exit fullscreen board display" })}>
          <LocalFlightIcon name="close" size={22} color={appearance.text} />
        </Pressable>
      </View>

      <View style={styles.columnHeader}>
        <Text style={[styles.heading, styles.timeColumn]}>Time</Text>
        <Text style={[styles.heading, styles.flightColumn]}>Flight</Text>
        <Text style={[styles.heading, styles.routeColumn]}>{view === "arrivals" ? "From" : "To"}</Text>
        <Text style={[styles.heading, styles.statusColumn]}>Status</Text>
        <Text style={[styles.heading, styles.aircraftColumn]}>Aircraft</Text>
        <Text style={[styles.heading, styles.gateColumn]}>Gate</Text>
      </View>

      <View style={styles.board} onTouchStart={() => setPaused(true)}>
        {page.length ? page.map((row) => (
          <View
            key={row.id}
            style={[styles.row, row.pinned && styles.pinnedRow]}
            accessible
            accessibilityLabel={`${row.time}, ${row.flight}, ${row.routeName}, ${row.status}`}
            accessibilityActions={[{ name: "activate", label: "Pause automatic paging" }]}
            onAccessibilityAction={() => setPaused(true)}
            onFocus={() => setPaused(true)}
          >
            <Text style={[styles.time, styles.timeColumn]}>{row.time}</Text>
            <View style={styles.flightColumn}>
              <Text style={styles.flight} numberOfLines={1}>{row.flight}</Text>
              <Text style={styles.subline} numberOfLines={1}>{row.airline || row.callsign}</Text>
            </View>
            <View style={styles.routeColumn}>
              <Text style={styles.route} numberOfLines={1}>{row.routeName}</Text>
              <Text style={styles.subline} numberOfLines={1}>{row.routeCode}</Text>
            </View>
            <Text style={[styles.status, styles.statusColumn, { color: statusColor(row, appearance) }]} numberOfLines={2}>{row.status}</Text>
            <Text style={[styles.detail, styles.aircraftColumn]} numberOfLines={1}>{row.aircraft || "—"}</Text>
            <Text style={[styles.gate, styles.gateColumn]} numberOfLines={1}>{row.gate || "—"}</Text>
          </View>
        )) : (
          <View style={styles.empty}>
            <LocalFlightIcon name="airplane-clock" size={34} color={appearance.textMuted} />
            <Text style={styles.emptyTitle}>Waiting for board data</Text>
            <Text style={styles.emptyBody}>The latest known board will appear here after refresh.</Text>
          </View>
        )}
      </View>

      <View style={styles.footer}>
        <Pressable style={styles.footerButton} onPress={previousPage} disabled={pages.length <= 1} {...accessibleButton({ label: "Previous board page", disabled: pages.length <= 1 })}>
          <LocalFlightIcon name="chevron-left" size={20} color={pages.length <= 1 ? appearance.textDim : appearance.text} />
        </Pressable>
        <Text style={styles.pageLabel}>Page {Math.min(pageIndex + 1, pages.length)} of {pages.length}</Text>
        <Pressable
          style={styles.pauseButton}
          onPress={() => setPaused((value) => !value)}
          disabled={reduceMotion || pages.length <= 1}
          {...accessibleButton({ label: paused ? "Resume automatic board paging" : "Pause automatic board paging", disabled: reduceMotion || pages.length <= 1 })}
        >
          <LocalFlightIcon name={paused ? "play" : "pause"} size={17} color={appearance.blue} />
          <Text style={styles.pauseText}>{paused ? "Paused" : `Auto page · ${Math.max(3, pageSeconds)} sec`}</Text>
        </Pressable>
        <Pressable style={styles.footerButton} onPress={nextPage} disabled={pages.length <= 1} {...accessibleButton({ label: "Next board page", disabled: pages.length <= 1 })}>
          <LocalFlightIcon name="chevron-right" size={20} color={pages.length <= 1 ? appearance.textDim : appearance.text} />
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

function makeStyles(a: MobileAppearance) {
  return StyleSheet.create({
    safe: { flex: 1, backgroundColor: a.bg, padding: 12 },
    header: { minHeight: 104, flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: a.header, borderRadius: 22, paddingHorizontal: 15, paddingVertical: 12 },
    brandBlock: { flex: 1.65, minWidth: 0 },
    airport: { color: a.text, fontSize: 15, lineHeight: 18, fontWeight: "700", marginTop: 5 },
    airportIdentity: { color: a.textMuted, fontSize: 11, marginTop: 3 },
    airportCode: { fontFamily: BOARD_FONT_FAMILY, fontWeight: "700" },
    headerCenter: { flex: 0.9, alignItems: "center" },
    boardTitle: { color: a.text, fontSize: 20, fontWeight: "700" },
    update: { color: a.textMuted, fontSize: 11, lineHeight: 15, marginTop: 4, textAlign: "center" },
    headerMeta: { flex: 1.1, minWidth: 110, alignItems: "flex-end" },
    weatherLine: { flexDirection: "row", alignItems: "baseline", justifyContent: "flex-end", gap: 9 },
    localTime: { color: a.text, fontSize: 20, fontFamily: BOARD_FONT_FAMILY, fontVariant: ["tabular-nums"] },
    weatherTemperature: { color: a.blue, fontSize: 18, fontWeight: "700" },
    weather: { color: a.textMuted, fontSize: 11, lineHeight: 15, marginTop: 3, textAlign: "right" },
    exitButton: { width: 44, height: 44, borderRadius: 15, backgroundColor: a.lineSoft, alignItems: "center", justifyContent: "center" },
    columnHeader: { flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 10 },
    heading: { color: a.textMuted, fontSize: 12, fontWeight: "600" },
    board: { flex: 1, gap: 6 },
    row: { flex: 1, minHeight: 54, maxHeight: 88, flexDirection: "row", alignItems: "center", backgroundColor: a.shell, borderRadius: 16, paddingHorizontal: 12, paddingVertical: 8 },
    pinnedRow: { backgroundColor: `${a.amber}16` },
    timeColumn: { width: 72 },
    flightColumn: { flex: 1.05, minWidth: 78 },
    routeColumn: { flex: 1.65, minWidth: 104 },
    statusColumn: { flex: 1.1, minWidth: 84 },
    aircraftColumn: { width: 72 },
    gateColumn: { width: 50, textAlign: "right" },
    time: { color: a.text, fontSize: 19, fontWeight: "700", fontFamily: BOARD_FONT_FAMILY, fontVariant: ["tabular-nums"] },
    flight: { color: a.text, fontSize: 18, fontWeight: "700", fontFamily: BOARD_FONT_FAMILY },
    route: { color: a.text, fontSize: 17, fontWeight: "600" },
    subline: { color: a.textMuted, fontSize: 12, marginTop: 2 },
    status: { fontSize: 14, fontWeight: "700" },
    detail: { color: a.textMuted, fontSize: 13, fontFamily: BOARD_FONT_FAMILY },
    gate: { color: a.text, fontSize: 17, fontWeight: "700", fontFamily: BOARD_FONT_FAMILY },
    empty: { flex: 1, alignItems: "center", justifyContent: "center" },
    emptyTitle: { color: a.text, fontSize: 22, fontWeight: "700", marginTop: 14 },
    emptyBody: { color: a.textMuted, fontSize: 14, marginTop: 6 },
    footer: { minHeight: 56, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 12, paddingTop: 8 },
    footerButton: { width: 44, height: 44, borderRadius: 14, alignItems: "center", justifyContent: "center", backgroundColor: a.lineSoft },
    pageLabel: { color: a.textMuted, fontSize: 13, minWidth: 100, textAlign: "center" },
    pauseButton: { minHeight: 44, flexDirection: "row", alignItems: "center", gap: 7, paddingHorizontal: 14, borderRadius: 14, backgroundColor: `${a.blue}12` },
    pauseText: { color: a.blue, fontSize: 13, fontWeight: "600" }
  });
}
