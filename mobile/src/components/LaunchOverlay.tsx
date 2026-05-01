import { Animated, Image, Text, View } from "react-native";

import { APP_VERSION } from "../domain/constants";

type LaunchOverlayProps = {
  visible: boolean;
  opacity: Animated.Value;
  shift: Animated.Value;
  scale: Animated.Value;
  progress: Animated.Value;
  pulse: Animated.Value;
  status: string;
  styles: Record<string, any>;
};

export function LaunchOverlay({
  visible,
  opacity,
  shift,
  scale,
  progress,
  pulse,
  status,
  styles
}: LaunchOverlayProps) {
  if (!visible) return null;

  const haloScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.94, 1.08] });
  const haloOpacity = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.72, 0.34] });
  const progressWidth = progress.interpolate({ inputRange: [0, 1], outputRange: ["4%", "100%"] });
  const sweepRotate = pulse.interpolate({ inputRange: [0, 1], outputRange: ["-18deg", "18deg"] });

  return (
    <Animated.View
      style={[
        { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 },
        styles.launchOverlay,
        {
          opacity,
          transform: [{ translateY: shift }, { scale }]
        }
      ]}
    >
      <Animated.View style={[styles.launchHalo, { opacity: haloOpacity, transform: [{ scale: haloScale }] }]} />
      <Animated.View style={[styles.launchHaloInner, { transform: [{ rotate: sweepRotate }] }]} />
      <View style={styles.launchPanel}>
        <View style={styles.launchMarkWrap}>
          <View style={styles.launchRadarRing} />
          <Animated.View style={[styles.launchSweep, { transform: [{ rotate: sweepRotate }] }]} />
          <Image
            source={require("../../assets/icon_circle.png")}
            resizeMode="contain"
            style={styles.launchMark}
          />
        </View>
        <Text style={styles.launchEyebrow}>LOCAL FLIGHT</Text>
        <Text style={styles.launchTitle}>COMPANION</Text>
        <Text style={styles.launchVersion}>v{APP_VERSION}</Text>
        <View style={styles.launchBoard}>
          {["ZRH  LX  READY", "MUC  LH  SYNC", "RADAR  SWEEP"].map((line, index) => (
            <View key={line} style={styles.launchBoardRow}>
              <Text style={styles.launchBoardTime}>{index === 0 ? "UTC" : index === 1 ? "LAN" : "NM"}</Text>
              <Text style={styles.launchBoardText}>{line}</Text>
            </View>
          ))}
        </View>
        <View style={styles.launchRunway}>
          <View style={styles.launchRunwayLine} />
          <View style={styles.launchRunwayDash} />
          <View style={styles.launchRunwayLine} />
        </View>
        <View style={styles.launchStatusRow}>
          <Text style={styles.launchStatus}>{status}</Text>
        </View>
        <View style={styles.launchProgressTrack}>
          <Animated.View style={[styles.launchProgressFill, { width: progressWidth }]} />
        </View>
      </View>
    </Animated.View>
  );
}
