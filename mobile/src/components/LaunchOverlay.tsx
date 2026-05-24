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
  orbitFast: Animated.Value;
  orbitMedium: Animated.Value;
  orbitSlow: Animated.Value;
  status: string;
  styles: Record<string, any>;
};

const PARTICLES = [
  { left: "13%", top: "17%", size: 2, opacity: 0.45 },
  { left: "67%", top: "15%", size: 2, opacity: 0.34 },
  { left: "83%", top: "27%", size: 1.5, opacity: 0.38 },
  { left: "24%", top: "34%", size: 1.5, opacity: 0.32 },
  { left: "9%", top: "56%", size: 2, opacity: 0.35 },
  { left: "88%", top: "59%", size: 1.5, opacity: 0.4 },
  { left: "20%", top: "81%", size: 2, opacity: 0.44 },
  { left: "62%", top: "86%", size: 1.5, opacity: 0.32 }
] as const;

export function LaunchOverlay({
  visible,
  opacity,
  shift,
  scale,
  progress,
  pulse,
  sweep,
  orbitFast,
  orbitMedium,
  orbitSlow,
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
  const longestSide = Math.max(width, height);
  const sidePadding = Math.max(22, Math.min(isWide ? 72 : 34, width * 0.072));
  const topPadding = Math.max(insets.top + 18, Math.min(isWide ? 76 : 52, height * 0.062));
  const bottomPadding = Math.max(insets.bottom + 18, Math.min(isWide ? 50 : 36, height * 0.048));
  const maxFrameWidth = Math.min(width - sidePadding * 2, isWide ? 650 : 450);
  const heroSize = Math.max(isLandscape ? 118 : compact ? 152 : 176, Math.min(isWide ? 288 : 222, shortestSide * (isWide ? 0.34 : 0.53)));
  const iconSize = heroSize * 0.74;
  const glassSize = heroSize * 0.94;
  const titleSize = Math.max(compact ? 32 : 36, Math.min(isWide ? 54 : 42, width * (isWide ? 0.068 : 0.102)));
  const titleLineHeight = Math.round(titleSize * 1.16);
  const titleWidth = Math.min(maxFrameWidth, isWide ? 520 : 370);
  const orbitCenterY = height * (isLandscape ? 0.48 : 0.43);
  const orbitBase = Math.max(longestSide * 1.16, shortestSide * 1.62, 520);
  const orbitMediumSize = orbitBase * 0.82;
  const orbitSlowSize = orbitBase * 1.24;
  const orbitFastSize = orbitBase * 0.58;
  const targetSize = Math.max(44, heroSize * 0.24);
  const isDark = palette.themeMode !== "light";
  const brandAsset = LOCAL_FLIGHT_BRAND_ASSETS[palette.themeMode].icon;
  const watermarkColor = isDark ? "rgba(205,238,248,0.54)" : "rgba(33,75,112,0.54)";
  const watermarkWindow = isDark ? "#080c12" : "#f8fbff";

  const haloScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.96, 1.07] });
  const iconScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.985, 1.018] });
  const pingScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.72, 1.42] });
  const pingOpacity = pulse.interpolate({ inputRange: [0, 0.72, 1], outputRange: [0.68, 0.2, 0] });
  const dotScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.78, 1.18] });
  const progressWidth = progress.interpolate({ inputRange: [0, 1], outputRange: ["4%", "100%"] });
  const sweepRotate = sweep.interpolate({ inputRange: [0, 1], outputRange: ["0deg", "360deg"] });
  const orbitFastRotate = orbitFast.interpolate({ inputRange: [0, 1], outputRange: ["0deg", "360deg"] });
  const orbitMediumRotate = orbitMedium.interpolate({ inputRange: [0, 1], outputRange: ["360deg", "0deg"] });
  const orbitSlowRotate = orbitSlow.interpolate({ inputRange: [0, 1], outputRange: ["-18deg", "342deg"] });

  const orbitStyle = (size: number) => ({
    width: size,
    height: size,
    left: (width - size) / 2,
    top: orbitCenterY - size / 2
  });

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
      <View style={styles.launchGlowNorth} {...hideFromAccessibility()} />
      <View style={styles.launchGlowSouth} {...hideFromAccessibility()} />
      <View style={styles.launchSkyGrid} {...hideFromAccessibility()}>
        {Array.from({ length: 8 }).map((_, index) => (
          <View key={index} style={styles.launchGridLine} />
        ))}
      </View>
      <View style={[styles.launchCrosshairHorizontal, { top: orbitCenterY }]} {...hideFromAccessibility()} />
      <View style={[styles.launchCrosshairVertical, { left: width / 2 }]} {...hideFromAccessibility()} />
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

      <Animated.View
        style={[
          styles.launchOrbitRing,
          styles.launchOrbitRingSlow,
          orbitStyle(orbitSlowSize),
          { transform: [{ rotate: orbitSlowRotate }, { scale: haloScale }] }
        ]}
        {...hideFromAccessibility()}
      />
      <Animated.View
        style={[
          styles.launchOrbitRing,
          styles.launchOrbitRingMedium,
          orbitStyle(orbitMediumSize),
          { transform: [{ rotate: orbitMediumRotate }] }
        ]}
        {...hideFromAccessibility()}
      />
      <Animated.View
        style={[
          styles.launchOrbitRing,
          styles.launchOrbitRingFast,
          orbitStyle(orbitFastSize),
          { transform: [{ rotate: orbitFastRotate }] }
        ]}
        {...hideFromAccessibility()}
      />
      <Animated.View
        style={[
          styles.launchSweepRotor,
          orbitStyle(orbitMediumSize * 0.78),
          { transform: [{ rotate: sweepRotate }] }
        ]}
        {...hideFromAccessibility()}
      >
        <View style={[styles.launchSweep, { height: orbitMediumSize * 0.34 }]} />
      </Animated.View>

      <View style={[styles.launchContentStack, { maxWidth: maxFrameWidth }]}>
        <View style={[styles.launchScene, compact && styles.launchSceneCompact]}>
          <View style={[styles.launchMarkWrap, { width: heroSize, height: heroSize }]}>
            <View style={[styles.launchHeroAura, { width: heroSize * 1.22, height: heroSize * 1.22 }]} {...hideFromAccessibility()} />
            <View style={[styles.launchRadarRingOuter, { width: heroSize * 1.36, height: heroSize * 1.36 }]} {...hideFromAccessibility()} />
            <View style={[styles.launchRadarRing, { width: heroSize * 1.04, height: heroSize * 1.04 }]} {...hideFromAccessibility()} />
            <Animated.View
              style={[
                styles.launchTarget,
                {
                  width: targetSize,
                  height: targetSize,
                  right: heroSize * 0.08,
                  top: heroSize * 0.17,
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
                  right: heroSize * 0.08 + targetSize * 0.29,
                  top: heroSize * 0.17 + targetSize * 0.29
                }
              ]}
              {...hideFromAccessibility()}
            />

            <Animated.View style={[styles.launchIconBloom, { transform: [{ scale: iconScale }] }]}>
              <View style={[styles.launchIconPlate, { width: glassSize, height: glassSize, borderRadius: glassSize * 0.24 }]}>
                <View style={[styles.launchMarkCrop, { width: iconSize, height: iconSize, borderRadius: iconSize * 0.22 }]}>
                  <Image source={brandAsset} resizeMode="cover" style={styles.launchMark} />
                </View>
              </View>
            </Animated.View>
          </View>

          <View style={styles.launchCopy}>
            <BrandWordmark
              color={palette.text}
              size={titleSize}
              style={[
                styles.launchTitle,
                compact && styles.launchTitleCompact,
                { width: titleWidth, lineHeight: titleLineHeight }
              ]}
              numberOfLines={1}
            >
              Local Flight
            </BrandWordmark>
            <Text style={styles.launchSubtitle}>Flight boards, radar, and history for your airport.</Text>
            <View style={styles.launchStatusPanel}>
              <View style={styles.launchStatusRow}>
                <Animated.View style={[styles.launchStatusDot, { transform: [{ scale: dotScale }] }]} />
                <Animated.Text style={[styles.launchStatus, { opacity: statusFade }]}>{status}</Animated.Text>
              </View>
              <View style={styles.launchProgressTrack}>
                <Animated.View style={[styles.launchProgressFill, { width: progressWidth }]} />
              </View>
            </View>
          </View>
        </View>
      </View>

      <View style={styles.launchBottomMeta}>
        <Text style={styles.launchVersion}>v{APP_VERSION}</Text>
        <View style={styles.launchBeaconFooter}>
          <BeaconToolsMark size={compact ? 14 : 16} color={watermarkColor} windowColor={watermarkWindow} />
          <Text style={styles.launchBeaconText}>BEACON TOOLS</Text>
        </View>
      </View>
    </Animated.View>
  );
}
