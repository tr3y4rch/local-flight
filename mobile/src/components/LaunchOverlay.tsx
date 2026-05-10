import { Animated, Image, Text, useWindowDimensions, View } from "react-native";

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

  const { width, height } = useWindowDimensions();
  const compact = height < 720 || width < 360;
  const isWide = width >= 700;
  const isLandscape = width > height;
  const shortestSide = Math.min(width, height);
  const heroSize = Math.max(isLandscape ? 86 : 112, Math.min(isLandscape ? 104 : isWide ? 176 : 148, shortestSide * 0.34));
  const ringSize = Math.max(heroSize * 2.1, shortestSide * (isLandscape ? 0.72 : 0.78));
  const ringTop = Math.max(92, height * (isLandscape ? 0.12 : 0.18));
  const ringLeft = (width - ringSize) / 2;
  const haloScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.94, 1.08] });
  const haloOpacity = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.72, 0.34] });
  const progressWidth = progress.interpolate({ inputRange: [0, 1], outputRange: ["4%", "100%"] });
  const sweepRotate = pulse.interpolate({ inputRange: [0, 1], outputRange: ["-24deg", "42deg"] });
  const boardLift = pulse.interpolate({ inputRange: [0, 1], outputRange: [0, compact ? -2 : -4] });

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
      <View style={styles.launchSkyGrid}>
        {Array.from({ length: 9 }).map((_, index) => (
          <View key={index} style={styles.launchGridLine} />
        ))}
      </View>
      <Animated.View
        style={[
          styles.launchHalo,
          {
            width: ringSize,
            height: ringSize,
            top: ringTop,
            left: ringLeft,
            opacity: haloOpacity,
            transform: [{ scale: haloScale }]
          }
        ]}
      />
      <Animated.View
        style={[
          styles.launchHaloInner,
          {
            width: ringSize * 0.66,
            height: ringSize * 0.66,
            top: ringTop + ringSize * 0.17,
            left: ringLeft + ringSize * 0.17,
            transform: [{ rotate: sweepRotate }]
          }
        ]}
      />
      <View style={[styles.launchRunwayField, compact && styles.launchRunwayFieldCompact]}>
        <View style={styles.launchRunwayPerspective}>
          <View style={styles.launchRunwayEdge} />
          <View style={styles.launchRunwayCenter} />
          <View style={styles.launchRunwayEdge} />
        </View>
      </View>

      <View style={styles.launchTopBar}>
        <Text style={styles.launchTopCode}>LOCAL FLIGHT</Text>
        <Text style={styles.launchTopVersion}>v{APP_VERSION}</Text>
      </View>

      <View style={[styles.launchStage, compact && styles.launchStageCompact]}>
        <View style={styles.launchHeroCard}>
          <View style={[styles.launchMarkWrap, { width: heroSize, height: heroSize }]}>
            <View style={[styles.launchRadarRing, { width: heroSize * 1.08, height: heroSize * 1.08 }]} />
            <View style={[styles.launchRadarRingOuter, { width: heroSize * 1.34, height: heroSize * 1.34 }]} />
            <Animated.View
              style={[
                styles.launchSweep,
                {
                  height: heroSize * 0.54,
                  top: heroSize * 0.02,
                  transform: [{ rotate: sweepRotate }]
                }
              ]}
            />
            <Image
              source={require("../../assets/icon_circle.png")}
              resizeMode="contain"
              style={[styles.launchMark, { width: heroSize * 0.76, height: heroSize * 0.76 }]}
            />
          </View>

          <View style={styles.launchCopy}>
            <Text style={styles.launchEyebrow}>MOBILE COMPANION</Text>
            <Text style={[styles.launchTitle, compact && styles.launchTitleCompact]}>LOCAL FLIGHT</Text>
            <Text style={styles.launchSubtitle}>Server-mediated FIDS, radar, and history on your LAN.</Text>
          </View>
        </View>

        {!isLandscape ? (
          <Animated.View style={[styles.launchBoard, { transform: [{ translateY: boardLift }] }]}>
            {["SERVER HANDSHAKE", "FIDS STANDBY", "RADAR SURFACE"].map((line, index) => (
              <View key={line} style={styles.launchBoardRow}>
                <Text style={styles.launchBoardTime}>{index === 0 ? "LAN" : index === 1 ? "UTC" : "NM"}</Text>
                <Text style={styles.launchBoardText}>{line}</Text>
                <View style={[styles.launchBoardLed, index === 1 && styles.launchBoardLedAmber]} />
              </View>
            ))}
          </Animated.View>
        ) : null}
      </View>

      <View style={styles.launchStatusPanel}>
        <View style={styles.launchStatusRow}>
          <View style={styles.launchStatusDot} />
          <Text style={styles.launchStatus}>{status}</Text>
        </View>
        <View style={styles.launchProgressTrack}>
          <Animated.View style={[styles.launchProgressFill, { width: progressWidth }]} />
        </View>
        <View style={styles.launchFooterCodes}>
          <Text style={styles.launchFooterCode}>LOCAL SERVER</Text>
          <Text style={styles.launchFooterCode}>PRIVATE LAN</Text>
          <Text style={styles.launchFooterCode}>NO DIRECT RELAY</Text>
        </View>
      </View>
    </Animated.View>
  );
}
