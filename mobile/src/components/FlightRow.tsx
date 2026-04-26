import { StyleSheet, Text, View } from "react-native";

import type { FidsRow } from "../api/types";
import { colors, radius, spacing } from "../theme/tokens";

type Props = {
  row: FidsRow;
};

function statusTone(statusClass: string): string {
  const value = statusClass.toLowerCase();
  if (value.includes("delay") || value.includes("cancel")) return colors.red;
  if (value.includes("board") || value.includes("land") || value.includes("arriv")) return colors.green;
  if (value.includes("gate") || value.includes("approach")) return colors.amber;
  return colors.blue;
}

export function FlightRow({ row }: Props) {
  const tone = statusTone(row.status_class || row.status_display);

  return (
    <View style={styles.row}>
      <View style={styles.timeBox}>
        <Text style={styles.time}>{row.display_time || "--:--"}</Text>
        <Text style={styles.gate}>Gate {row.gate || "-"}</Text>
      </View>

      <View style={styles.main}>
        <Text style={styles.flight}>{row.flight_display || row.callsign || "-"}</Text>
        <Text style={styles.route} numberOfLines={1}>{row.route_display || "Unknown route"}</Text>
      </View>

      <View style={[styles.status, { borderColor: tone }]}>
        <Text style={[styles.statusText, { color: tone }]} numberOfLines={1}>
          {row.status_display || "Scheduled"}
        </Text>
      </View>
    </View>
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
    color: colors.dim,
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
    borderWidth: 1,
    backgroundColor: "rgba(255,255,255,0.035)"
  },
  statusText: {
    fontSize: 11,
    fontWeight: "900",
    letterSpacing: 0.5,
    textTransform: "uppercase"
  }
});
