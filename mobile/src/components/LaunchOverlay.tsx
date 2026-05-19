import { useEffect, useRef } from "react";
import { Animated, Image, Text, useWindowDimensions, View } from "react-native";

import { hideFromAccessibility, useReducedMotionPreference } from "../accessibility/mobileA11y";
import { APP_VERSION } from "../domain/constants";
import { palette } from "../theme/styleBridge";
import { BrandKicker, BrandWordmark } from "./Brand";

type LaunchOverlayProps = {
  visible: boolean;
  opacity: Animated.Value;
  shift: Animated.Value;
  scale: Animated.Value;
  progress: Animated.Value;
  // Slow sinusoidal breath — drives halo scale/opacity, runway lift, status dot,
  // and amber LED glow. Period ~3.2 s.
  pulse: Animated.Value;
  // Independent continuous radar sweep — linear 360° rotation at ~3.2 s/rev.
  // Kept separate from pulse so the needle feels physically detached from the
  // halo breathing.
  sweep: Animated.Value;
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
  sweep,
  status,
  styles
}: LaunchOverlayProps) {
  const { width, height } = useWindowDimensions();
  const reduceMotion = useReducedMotionPreference();

  // Status text cross-fade — quick fade-out → fade-in on each step change.
  const statusFade = useRef(new Animated.Value(1)).current;
  const prevStatusRef = useRef(status);
  useEffect(() => {
    if (prevStatusRef.current === status) return;
    prevStatusRef.current = status;
    if (reduceMotion) {
      statusFade.setValue(1);
      return;
    }
    Animated.sequence([
      Animated.timing(statusFade, { toValue: 0, duration: 60, useNativeDriver: true }),
      Animated.timing(statusFade, { toValue: 1, duration: 140, useNativeDriver: true })
    ]).start();
  }, [status, statusFade, reduceMotion]);

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

  // Halo — breathes slowly with pulse (unchanged from before).
  const haloScale   = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.94, 1.08] });
  const haloOpacity = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.72, 0.34] });

  // Progress bar fill.
  const progressWidth = progress.interpolate({ inputRange: [0, 1], outputRange: ["4%", "100%"] });

  // Radar sweep — full continuous 360° rotation from the independent sweep value.
  const sweepRotate = sweep.interpolate({ inputRange: [0, 1], outputRange: ["0deg", "360deg"] });

  // Runway card gentle float — stays on pulse.
  const runwayLift = pulse.interpolate({ inputRange: [0, 1], outputRange: [0, compact ? -1 : -3] });

  // Status dot breathing scale.
  const dotScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.75, 1.15] });

  // Amber board LED brightness — pulses opposite to halo so it "blinks" independently.
  const amberBlink = pulse.interpolate({ inputRange: [0, 0.5, 1], outputRange: [0.35, 1.0, 0.35] });

  const showBoard = !compact && !isLandscape;

  // Responsive title size — passed directly to BrandWordmark so the component's
  // `size` prop controls fontSize (not the style-factory key, which is overridden).
  const titleSize = compact ? 28 : isWide ? 42 : 34;

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
          <View key={index} style={styles.launchGridLine} {...hideFromAccessibility()} />
        ))}
      </View>

      {/* Outer halo — breathes with pulse */}
      <Animated.View
        {...hideFromAccessibility()}
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

      {/* Inner scanner arc — rotates continuously with sweep, tri-color borders */}
      <Animated.View
        {...hideFromAccessibility()}
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
            <BrandKicker color={palette.textDim}>LOCAL FLIGHT</BrandKicker>
            <Text style={styles.launchTopVersion}>v{APP_VERSION}</Text>
          </View>

          <View style={[styles.launchHeroCard, isWide && styles.launchHeroCardWide]}>
            <View style={[styles.launchMarkWrap, { width: heroSize, height: heroSize }]}>
              <View style={[styles.launchRadarRing, { width: heroSize * 1.08, height: heroSize * 1.08 }]} {...hideFromAccessibility()} />
              <View style={[styles.launchRadarRingOuter, { width: heroSize * 1.34, height: heroSize * 1.34 }]} {...hideFromAccessibility()} />

              {/* Radar needle — continuous 360° rotation, independent of halo breath */}
              <Animated.View
                {...hideFromAccessibility()}
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
              <BrandKicker color={palette.blue2} size={11}>LOCAL FLIGHT MOBILE</BrandKicker>
              <BrandWordmark
                color={palette.text}
                size={titleSize}
                style={[styles.launchTitle, compact && styles.launchTitleCompact, isWide && styles.launchTitleWide]}
                numberOfLines={1}
                adjustsFontSizeToFit
                minimumFontScale={0.72}
              >
                LOCAL FLIGHT
              </BrandWordmark>
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
                    {index === 1 ? (
                      // Amber LED blinks with pulse to signal "pending / connecting"
                      <Animated.View style={[styles.launchBoardLed, styles.launchBoardLedAmber, { opacity: amberBlink }]} />
                    ) : (
                      <View style={styles.launchBoardLed} />
                    )}
                  </View>
                ))}
              </View>
            ) : null}
          </Animated.View>
        </View>
      </View>

      <View style={[styles.launchStatusPanel, { maxWidth: maxFrameWidth }]}>
        <View style={styles.launchStatusRow}>
          {/* Status dot breathes with pulse */}
          <Animated.View style={[styles.launchStatusDot, { transform: [{ scale: dotScale }] }]} />
          <Animated.Text style={[styles.launchStatus, { opacity: statusFade }]}>{status}</Animated.Text>
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
