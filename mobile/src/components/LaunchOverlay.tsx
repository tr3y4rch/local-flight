import { useEffect, useRef } from "react";
import { Animated, Image, Text, useWindowDimensions, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { hideFromAccessibility, useReducedMotionPreference } from "../accessibility/mobileA11y";
import { APP_VERSION } from "../domain/constants";
import { LOCAL_FLIGHT_BRAND_ASSETS } from "../theme/brandAssets";
import { palette } from "../theme/styleBridge";
import { BeaconToolsMark } from "./BeaconToolsMark";
import { BrandWordmark } from "./Brand";

type LaunchOverlayProps = {
  visible: boolean;
  opacity: Animated.Value;
  shift: Animated.Value;
  scale: Animated.Value;
  progress: Animated.Value;
  pulse: Animated.Value;
  sweep: Animated.Value;
  status: string;
  styles: Record<string, any>;
};

const PARTICLES = [
  { left: "18%", top: "18%", size: 2, opacity: 0.55 },
  { left: "77%", top: "17%", size: 2, opacity: 0.5 },
  { left: "28%", top: "31%", size: 1.5, opacity: 0.38 },
  { left: "67%", top: "36%", size: 2.5, opacity: 0.42 },
  { left: "12%", top: "52%", size: 1.5, opacity: 0.32 },
  { left: "87%", top: "58%", size: 1.5, opacity: 0.35 },
  { left: "25%", top: "78%", size: 2, opacity: 0.44 },
  { left: "72%", top: "82%", size: 1.5, opacity: 0.34 }
] as const;

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
  const insets = useSafeAreaInsets();
  const reduceMotion = useReducedMotionPreference();

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
  const sidePadding = Math.max(20, Math.min(isWide ? 64 : 32, width * 0.07));
  const topPadding = Math.max(insets.top + 24, Math.min(isWide ? 80 : 58, height * 0.07));
  const bottomPadding = Math.max(insets.bottom + 18, Math.min(isWide ? 56 : 38, height * 0.05));
  const maxFrameWidth = Math.min(width - sidePadding * 2, isWide ? 620 : 430);
  const heroSize = Math.max(isLandscape ? 126 : 170, Math.min(isWide ? 280 : 228, shortestSide * (isWide ? 0.36 : 0.57)));
  const radarSize = Math.max(heroSize * 1.72, Math.min(Math.max(width, height) * 0.62, shortestSide * (isWide ? 0.82 : 1.08)));
  const targetSize = Math.max(42, heroSize * 0.25);
  const titleSize = compact ? 30 : isWide ? 44 : 36;

  const haloScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.94, 1.07] });
  const haloOpacity = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.64, 0.34] });
  const iconScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.985, 1.015] });
  const pingScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.68, 1.34] });
  const pingOpacity = pulse.interpolate({ inputRange: [0, 0.7, 1], outputRange: [0.66, 0.22, 0] });
  const dotScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.78, 1.16] });
  const progressWidth = progress.interpolate({ inputRange: [0, 1], outputRange: ["4%", "100%"] });
  const sweepRotate = sweep.interpolate({ inputRange: [0, 1], outputRange: ["0deg", "360deg"] });

  return (
    <Animated.View
      accessibilityLabel="Local Flight is opening"
      style={[
        { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 },
        styles.launchOverlay,
        {
          opacity,
          paddingHorizontal: sidePadding,
          paddingTop: topPadding,
          paddingBottom: bottomPadding,
          transform: [{ translateY: shift }, { scale }]
        }
      ]}
    >
      <View style={styles.launchAtmosphere} {...hideFromAccessibility()} />
      <View style={styles.launchSkyGrid} {...hideFromAccessibility()}>
        {Array.from({ length: 7 }).map((_, index) => (
          <View key={index} style={styles.launchGridLine} />
        ))}
      </View>
      {PARTICLES.map((particle, index) => (
        <View
          key={index}
          style={[
            styles.launchParticle,
            {
              left: particle.left,
              top: particle.top,
              width: particle.size,
              height: particle.size,
              opacity: particle.opacity
            }
          ]}
          {...hideFromAccessibility()}
        />
      ))}

      <View style={[styles.launchContentStack, { maxWidth: maxFrameWidth }]}>
        <View style={[styles.launchScene, compact && styles.launchSceneCompact]}>
          <Animated.View
            style={[
              styles.launchHalo,
              {
                width: radarSize,
                height: radarSize,
                opacity: haloOpacity,
                transform: [{ scale: haloScale }]
              }
            ]}
            {...hideFromAccessibility()}
          />
          <Animated.View
            style={[
              styles.launchHaloInner,
              {
                width: radarSize * 0.66,
                height: radarSize * 0.66,
                transform: [{ rotate: sweepRotate }]
              }
            ]}
            {...hideFromAccessibility()}
          />

          <View style={[styles.launchMarkWrap, { width: heroSize, height: heroSize }]}>
            <View style={[styles.launchRadarRingOuter, { width: heroSize * 1.4, height: heroSize * 1.4 }]} {...hideFromAccessibility()} />
            <View style={[styles.launchRadarRing, { width: heroSize * 1.12, height: heroSize * 1.12 }]} {...hideFromAccessibility()} />

            <Animated.View
              style={[
                styles.launchSweepRotor,
                {
                  width: heroSize * 1.2,
                  height: heroSize * 1.2,
                  transform: [{ rotate: sweepRotate }]
                }
              ]}
              {...hideFromAccessibility()}
            >
              <View style={[styles.launchSweep, { height: heroSize * 0.52 }]} />
            </Animated.View>

            <Animated.View
              style={[
                styles.launchTarget,
                {
                  width: targetSize,
                  height: targetSize,
                  right: heroSize * 0.09,
                  top: heroSize * 0.18,
                  transform: [{ scale: pingScale }],
                  opacity: pingOpacity
                }
              ]}
              {...hideFromAccessibility()}
            />
            <View
              style={[
                styles.launchTargetCore,
                {
                  width: targetSize * 0.42,
                  height: targetSize * 0.42,
                  right: heroSize * 0.09 + targetSize * 0.29,
                  top: heroSize * 0.18 + targetSize * 0.29
                }
              ]}
              {...hideFromAccessibility()}
            />

            <Animated.View style={[styles.launchIconBloom, { transform: [{ scale: iconScale }] }]}>
              <View style={[styles.launchMarkCrop, { width: heroSize * 0.82, height: heroSize * 0.82 }]}>
                <Image source={LOCAL_FLIGHT_BRAND_ASSETS.dark.icon} resizeMode="cover" style={styles.launchMark} />
              </View>
            </Animated.View>
          </View>

          <View style={styles.launchCopy}>
            <BrandWordmark
              color={palette.text}
              size={titleSize}
              style={[styles.launchTitle, compact && styles.launchTitleCompact]}
              numberOfLines={1}
              adjustsFontSizeToFit
              minimumFontScale={0.74}
            >
              LOCAL FLIGHT
            </BrandWordmark>
            <Text style={styles.launchSubtitle}>Flight boards, radar, and history for your airport.</Text>
            <Text style={styles.launchVersion}>v{APP_VERSION}</Text>
          </View>
        </View>
      </View>

      <View style={[styles.launchStatusPanel, { maxWidth: maxFrameWidth }]}>
        <View style={styles.launchStatusRow}>
          <Animated.View style={[styles.launchStatusDot, { transform: [{ scale: dotScale }] }]} />
          <Animated.Text style={[styles.launchStatus, { opacity: statusFade }]}>{status}</Animated.Text>
        </View>
        <View style={styles.launchProgressTrack}>
          <Animated.View style={[styles.launchProgressFill, { width: progressWidth }]} />
        </View>
        <View style={styles.launchBeaconFooter}>
          <BeaconToolsMark size={compact ? 14 : 16} color="rgba(205,238,248,0.54)" windowColor="#080c12" />
          <Text style={styles.launchBeaconText}>BEACON TOOLS</Text>
        </View>
      </View>
    </Animated.View>
  );
}
