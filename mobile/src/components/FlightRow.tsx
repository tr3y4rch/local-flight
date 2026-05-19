import { Pressable, StyleSheet, Text, View } from "react-native";

import type { FidsRow } from "../api/types";
import { tapTargetHitSlop } from "../accessibility/mobileA11y";
import { colors, radius, spacing } from "../theme/tokens";

type Props = {
  row: FidsRow;
  onPress?: () => void;
};

function statusTone(statusClass: string): string {
  const value = statusClass.toLowerCase();
  if (value.includes("delay") || value.includes("cancel")) return colors.red;
  if (value.includes("board") || value.includes("land") || value.includes("arriv")) return colors.green;
  if (value.includes("gate") || value.includes("approach")) return colors.amber;
  return colors.blue;
}

function hexToRgb(value: string): { r: number; g: number; b: number } | null {
  const normalized = value.trim().replace(/^#/, "");
  const full = normalized.length === 3
    ? normalized.split("").map((char) => char + char).join("")
    : normalized;
  if (!/^[0-9a-f]{6}$/i.test(full)) return null;
  return {
    r: parseInt(full.slice(0, 2), 16),
    g: parseInt(full.slice(2, 4), 16),
    b: parseInt(full.slice(4, 6), 16)
  };
}

function statusFill(tone: string): string {
  const rgb = hexToRgb(tone);
  if (!rgb) return "rgba(255,255,255,0.08)";
  return `rgba(${rgb.r},${rgb.g},${rgb.b},0.12)`;
}

function rowAccessibilityLabel(row: FidsRow): string {
  const flight = row.flight_display || row.callsign || "Unknown flight";
  const route = row.route_display || "unknown route";
  const time = row.display_time || "time unavailable";
  const gate = row.gate ? `gate ${row.gate}` : "gate unassigned";
  const status = row.status_display || "Scheduled";
  return `${flight}, ${route}, ${time}, ${gate}, ${status}`;
}

export function FlightRow({ row, onPress }: Props) {
  const tone = statusTone(row.status_class || row.status_display);

  return (
    <Pressable
      style={styles.row}
      accessibilityRole={onPress ? "button" : undefined}
      accessibilityLabel={rowAccessibilityLabel(row)}
      accessibilityHint={onPress ? "Opens flight details." : undefined}
      hitSlop={tapTargetHitSlop}
      onPress={onPress}
    >
      <View style={styles.timeBox}>
        <Text style={styles.time}>{row.display_time || "--:--"}</Text>
        <Text style={styles.gate}>Gate {row.gate || "-"}</Text>
      </View>

      <View style={styles.main}>
        <Text style={styles.flight}>{row.flight_display || row.callsign || "-"}</Text>
        <Text style={styles.route} numberOfLines={1}>{row.route_display || "Unknown route"}</Text>
      </View>

      <View style={[styles.status, { borderColor: tone, backgroundColor: statusFill(tone) }]}>
        <Text style={[styles.statusText, { color: tone }]} numberOfLines={1}>
          {row.status_display || "Scheduled"}
        </Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    padding: spacing.md,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.07)",
    backgroundColor: colors.panel
  },
  timeBox: {
    width: 74
  },
  time: {
    color: colors.text,
    fontSize: 18,
    fontVariant: ["tabular-nums"],
    fontWeight: "900"
  },
  gate: {
    marginTop: 4,
    color: colors.muted,
    fontSize: 11,
    fontWeight: "700",
    textTransform: "uppercase"
  },
  main: {
    flex: 1,
    minWidth: 0
  },
  flight: {
    color: colors.text,
    fontSize: 17,
    fontWeight: "900"
  },
  route: {
    marginTop: 4,
    color: colors.muted,
    fontSize: 13,
    fontWeight: "600"
  },
  status: {
    maxWidth: 112,
    paddingHorizontal: 10,
    paddingVertical: 7,
    borderRadius: 999,
    borderWidth: 1
  },
  statusText: {
    fontSize: 11,
    fontWeight: "900",
    letterSpacing: 0.5,
    textTransform: "uppercase"
  }
});
