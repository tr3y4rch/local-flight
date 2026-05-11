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
  const { width, height } = useWindowDimensions();

  if (!visible) return null;

  const compact = height < 720 || width < 360;
  const isWide = width >= 700;
  const isLandscape = width > height;
  const shortestSide = Math.min(width, height);
  const sidePadding = Math.max(18, Math.min(isWide ? 48 : 28, width * 0.055));
  const verticalPaddingTop = Math.max(30, Math.min(isWide ? 72 : 54, height * 0.058));
  const verticalPaddingBottom = Math.max(22, Math.min(isWide ? 44 : 32, height * 0.038));
  const maxFrameWidth = Math.min(width - sidePadding * 2, isWide ? 760 : 520);
  const contentGap = Math.max(12, Math.min(24, height * 0.018));
  const scenePadding = Math.max(compact ? 12 : 16, Math.min(isWide ? 26 : 20, shortestSide * 0.042));
  const heroSize = Math.max(isLandscape ? 70 : 88, Math.min(isLandscape ? 96 : isWide ? 152 : 122, shortestSide * (isWide ? 0.18 : 0.29)));
  const ringSize = Math.max(heroSize * 2.5, Math.min(Math.max(width, height) * 0.58, shortestSide * (isLandscape ? 0.82 : isWide ? 0.88 : 1.18)));
  const ringTop = Math.max(verticalPaddingTop + 36, height * (isLandscape ? 0.12 : 0.22));
  const ringLeft = (width - ringSize) / 2;
  const haloScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.94, 1.08] });
  const haloOpacity = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.72, 0.34] });
  const progressWidth = progress.interpolate({ inputRange: [0, 1], outputRange: ["4%", "100%"] });
  const sweepRotate = pulse.interpolate({ inputRange: [0, 1], outputRange: ["-24deg", "42deg"] });
  const runwayLift = pulse.interpolate({ inputRange: [0, 1], outputRange: [0, compact ? -1 : -3] });
  const showBoard = !compact && !isLandscape;

  return (
    <Animated.View
      style={[
        { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 },
        styles.launchOverlay,
        {
          opacity,
          paddingHorizontal: sidePadding,
          paddingTop: verticalPaddingTop,
          paddingBottom: verticalPaddingBottom,
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
      <View style={[styles.launchContentStack, { maxWidth: maxFrameWidth, gap: contentGap }]}>
        <View style={[styles.launchScene, compact && styles.launchSceneCompact, { padding: scenePadding }]}>
          <View style={styles.launchTopBar}>
            <Text style={styles.launchTopCode}>LOCAL FLIGHT</Text>
            <Text style={styles.launchTopVersion}>v{APP_VERSION}</Text>
          </View>

          <View style={[styles.launchHeroCard, isWide && styles.launchHeroCardWide]}>
            <View style={[styles.launchMarkWrap, { width: heroSize, height: heroSize }]}>
              <View style={[styles.launchRadarRing, { width: heroSize * 1.08, height: heroSize * 1.08 }]} />
              <View style={[styles.launchRadarRingOuter, { width: heroSize * 1.34, height: heroSize * 1.34 }]} />
              <Animated.View
                style={[
                  styles.launchSweepRotor,
                  {
                    width: heroSize,
                    height: heroSize,
                    transform: [{ rotate: sweepRotate }]
                  }
                ]}
              >
                <View style={[styles.launchSweep, { height: heroSize * 0.42 }]} />
              </Animated.View>
              <View style={[styles.launchMarkCrop, { width: heroSize * 0.78, height: heroSize * 0.78 }]}>
                <Image
                  source={require("../../assets/localflight-logo.png")}
                  resizeMode="cover"
                  style={styles.launchMark}
                />
              </View>
            </View>

            <View style={[styles.launchCopy, isWide && styles.launchCopyWide]}>
              <Text style={styles.launchEyebrow}>MOBILE COMPANION</Text>
              <Text
                style={[styles.launchTitle, compact && styles.launchTitleCompact, isWide && styles.launchTitleWide]}
                numberOfLines={1}
                adjustsFontSizeToFit
                minimumFontScale={0.72}
              >
                LOCAL FLIGHT
              </Text>
              <Text style={[styles.launchSubtitle, isWide && styles.launchSubtitleWide]}>
                Server-mediated FIDS, radar, and history on your LAN.
              </Text>
            </View>
          </View>

          <Animated.View
            style={[
              styles.launchRunwayDeck,
              compact && styles.launchRunwayDeckCompact,
              { transform: [{ translateY: runwayLift }] }
            ]}
          >
            <View style={styles.launchRunwayDeckHeader}>
              <Text style={styles.launchRunwayDeckKicker}>RUNWAY READY</Text>
              <Text style={styles.launchRunwayDeckMeta}>{isLandscape ? "LAN" : "LOCAL SERVER"}</Text>
            </View>
            <View style={styles.launchRunwayPerspective}>
              <View style={styles.launchRunwayEdge} />
              <View style={styles.launchRunwayCenter}>
                {Array.from({ length: compact ? 4 : 6 }).map((_, index) => (
                  <View key={index} style={styles.launchRunwayCenterMark} />
                ))}
              </View>
              <View style={styles.launchRunwayEdge} />
            </View>
            {showBoard ? (
              <View style={styles.launchBoard}>
                {["SERVER HANDSHAKE", "FIDS STANDBY", "RADAR SURFACE"].map((line, index) => (
                  <View key={line} style={styles.launchBoardRow}>
                    <Text style={styles.launchBoardTime}>{index === 0 ? "LAN" : index === 1 ? "UTC" : "NM"}</Text>
                    <Text style={styles.launchBoardText}>{line}</Text>
                    <View style={[styles.launchBoardLed, index === 1 && styles.launchBoardLedAmber]} />
                  </View>
                ))}
              </View>
            ) : null}
          </Animated.View>
        </View>
      </View>

      <View style={[styles.launchStatusPanel, { maxWidth: maxFrameWidth }]}>
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
