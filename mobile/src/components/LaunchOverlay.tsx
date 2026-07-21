import { useEffect, useMemo, useRef } from "react";
import {
  Animated,
  Pressable,
  StyleSheet,
  useWindowDimensions,
  View
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import Svg, { Circle, G, Line, Path } from "react-native-svg";

import { hideFromAccessibility } from "../accessibility/mobileA11y";
import { APP_VERSION } from "../domain/constants";
import { LOCAL_FLIGHT_BRAND_ASSETS } from "../theme/brandAssets";
import { useMobileTheme } from "../theme/runtime";
import { UI_FONT_FAMILY, type MobileAppearance } from "../theme/tokens";
import { BeaconToolsMark } from "./BeaconToolsMark";
import { BrandWordmark } from "./Brand";
import { V2Text as Text } from "./V2Text";

type LaunchOverlayProps = {
  visible: boolean;
  opacity: Animated.Value;
  shift: Animated.Value;
  scale: Animated.Value;
  sequence: Animated.Value;
  ambientSweep: Animated.Value;
  logoBreath: Animated.Value;
  sequenceComplete: boolean;
  reduceMotion: boolean;
  ready: boolean;
  onEnter: () => void;
  status: string;
  qualifier?: string | null;
  entryLabel?: string;
  onFirstFrame?: () => void;
};

type BlipSpec = {
  x: number;
  y: number;
  acquire: number;
  glint: number;
  size: number;
};

type NormalizedPoint = {
  x: number;
  y: number;
};

type CubicRouteSegment = {
  control1: NormalizedPoint;
  control2: NormalizedPoint;
  end: NormalizedPoint;
};

const AnimatedPressable = Animated.createAnimatedComponent(Pressable);

const NAVIGATION_POINTS = [
  { left: "10%", top: "17%", size: 2, opacity: 0.28 },
  { left: "24%", top: "10%", size: 1.5, opacity: 0.22 },
  { left: "72%", top: "15%", size: 2, opacity: 0.32 },
  { left: "89%", top: "31%", size: 1.5, opacity: 0.24 },
  { left: "8%", top: "54%", size: 1.5, opacity: 0.2 },
  { left: "91%", top: "63%", size: 2, opacity: 0.25 },
  { left: "18%", top: "84%", size: 2, opacity: 0.2 },
  { left: "78%", top: "88%", size: 1.5, opacity: 0.22 }
] as const;

const BLIPS: BlipSpec[] = [
  { x: 0.27, y: 0.32, acquire: 0.36, glint: 0.18, size: 8 },
  { x: 0.72, y: 0.26, acquire: 0.43, glint: 0.36, size: 6 },
  { x: 0.79, y: 0.61, acquire: 0.55, glint: 0.58, size: 9 },
  { x: 0.34, y: 0.73, acquire: 0.62, glint: 0.77, size: 7 },
  { x: 0.18, y: 0.55, acquire: 0.68, glint: 0.91, size: 5 }
];

const AIRCRAFT_ROUTE_START: NormalizedPoint = { x: 1.08, y: 0.18 };
const AIRCRAFT_ROUTE_SEGMENTS: CubicRouteSegment[] = [
  {
    control1: { x: 0.92, y: 0.1 },
    control2: { x: 0.69, y: 0.08 },
    end: { x: 0.48, y: 0.11 }
  },
  {
    control1: { x: 0.2, y: 0.12 },
    control2: { x: 0.07, y: 0.36 },
    end: { x: 0.1, y: 0.6 }
  },
  {
    control1: { x: 0.14, y: 0.85 },
    control2: { x: 0.4, y: 0.92 },
    end: { x: 0.65, y: 0.82 }
  },
  {
    control1: { x: 0.83, y: 0.72 },
    control2: { x: 0.8, y: 0.56 },
    end: { x: 0.66, y: 0.48 }
  },
  {
    control1: { x: 0.58, y: 0.45 },
    control2: { x: 0.5, y: 0.56 },
    end: { x: 0.5, y: 0.5 }
  }
];
const AIRCRAFT_ROUTE_START_TIME = 0.25;
const AIRCRAFT_ROUTE_END_TIME = 0.79;
const AIRCRAFT_ROUTE_SAMPLE_COUNT = 19;

function cubicPoint(
  start: NormalizedPoint,
  segment: CubicRouteSegment,
  progress: number
): NormalizedPoint {
  const inverse = 1 - progress;
  const inverseSquared = inverse * inverse;
  const progressSquared = progress * progress;
  return {
    x: inverseSquared * inverse * start.x +
      3 * inverseSquared * progress * segment.control1.x +
      3 * inverse * progressSquared * segment.control2.x +
      progressSquared * progress * segment.end.x,
    y: inverseSquared * inverse * start.y +
      3 * inverseSquared * progress * segment.control1.y +
      3 * inverse * progressSquared * segment.control2.y +
      progressSquared * progress * segment.end.y
  };
}

function cubicTangent(
  start: NormalizedPoint,
  segment: CubicRouteSegment,
  progress: number
): NormalizedPoint {
  const inverse = 1 - progress;
  return {
    x: 3 * inverse * inverse * (segment.control1.x - start.x) +
      6 * inverse * progress * (segment.control2.x - segment.control1.x) +
      3 * progress * progress * (segment.end.x - segment.control2.x),
    y: 3 * inverse * inverse * (segment.control1.y - start.y) +
      6 * inverse * progress * (segment.control2.y - segment.control1.y) +
      3 * progress * progress * (segment.end.y - segment.control2.y)
  };
}

function aircraftRouteSample(progress: number): { point: NormalizedPoint; angle: number } {
  const bounded = clamp(progress, 0, 1);
  const scaled = bounded * AIRCRAFT_ROUTE_SEGMENTS.length;
  const segmentIndex = Math.min(AIRCRAFT_ROUTE_SEGMENTS.length - 1, Math.floor(scaled));
  const localProgress = segmentIndex === AIRCRAFT_ROUTE_SEGMENTS.length - 1 && bounded === 1
    ? 1
    : scaled - segmentIndex;
  const segment = AIRCRAFT_ROUTE_SEGMENTS[segmentIndex]!;
  const start = segmentIndex === 0 ? AIRCRAFT_ROUTE_START : AIRCRAFT_ROUTE_SEGMENTS[segmentIndex - 1]!.end;
  const point = cubicPoint(start, segment, localProgress);
  const tangent = cubicTangent(start, segment, localProgress);
  return {
    point,
    // The aircraft glyph points north at zero degrees. Align that nose with
    // the actual curve tangent instead of rotating the translated position.
    angle: Math.atan2(tangent.y, tangent.x) * 180 / Math.PI + 90
  };
}

function unwrapAngles(angles: number[]): number[] {
  const unwrapped: number[] = [];
  angles.forEach((angle, index) => {
    if (index === 0) {
      unwrapped.push(angle);
      return;
    }
    let next = angle;
    const previous = unwrapped[index - 1]!;
    while (next - previous > 180) next -= 360;
    while (next - previous < -180) next += 360;
    unwrapped.push(next);
  });
  return unwrapped;
}

function aircraftRoutePath(size: number): string {
  let path = `M ${AIRCRAFT_ROUTE_START.x * size} ${AIRCRAFT_ROUTE_START.y * size}`;
  AIRCRAFT_ROUTE_SEGMENTS.forEach((segment) => {
    path += ` C ${segment.control1.x * size} ${segment.control1.y * size}, ${segment.control2.x * size} ${segment.control2.y * size}, ${segment.end.x * size} ${segment.end.y * size}`;
  });
  return path;
}

function aircraftRouteKeyframes(size: number) {
  const samples = Array.from({ length: AIRCRAFT_ROUTE_SAMPLE_COUNT }, (_, index) =>
    aircraftRouteSample(index / (AIRCRAFT_ROUTE_SAMPLE_COUNT - 1))
  );
  const times = samples.map((_, index) =>
    AIRCRAFT_ROUTE_START_TIME +
    (AIRCRAFT_ROUTE_END_TIME - AIRCRAFT_ROUTE_START_TIME) * index / (AIRCRAFT_ROUTE_SAMPLE_COUNT - 1)
  );
  const angles = unwrapAngles(samples.map((sample) => sample.angle));
  const firstSample = samples[0]!;
  const firstAngle = angles[0]!;
  const lastAngle = angles[angles.length - 1]!;
  return {
    inputRange: [0, ...times, 1],
    x: [(firstSample.point.x - 0.5) * size, ...samples.map((sample) => (sample.point.x - 0.5) * size), 0],
    y: [(firstSample.point.y - 0.5) * size, ...samples.map((sample) => (sample.point.y - 0.5) * size), 0],
    rotation: [`${firstAngle}deg`, ...angles.map((angle) => `${angle}deg`), `${lastAngle}deg`]
  };
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

function polarPoint(center: number, radius: number, angleDeg: number): { x: number; y: number } {
  const angle = (angleDeg - 90) * Math.PI / 180;
  return {
    x: center + radius * Math.cos(angle),
    y: center + radius * Math.sin(angle)
  };
}

function sweepSectorPath(size: number, startDeg = -46, endDeg = 0): string {
  const center = size / 2;
  const radius = size * 0.455;
  const start = polarPoint(center, radius, startDeg);
  const end = polarPoint(center, radius, endDeg);
  return `M ${center} ${center} L ${start.x} ${start.y} A ${radius} ${radius} 0 0 1 ${end.x} ${end.y} Z`;
}

function AircraftGlyph({ color }: { color: string }) {
  return (
    <Svg width="100%" height="100%" viewBox="0 0 80 80">
      <Path
        d="M40 5 C43 5 45 8 45 12 L47 30 L69 43 L67 49 L47 43 L47 61 L56 69 L53 75 L40 69 L27 75 L24 69 L33 61 L33 43 L13 49 L11 43 L33 30 L35 12 C35 8 37 5 40 5 Z"
        fill={color}
      />
    </Svg>
  );
}

function RadarVectorLayer({ size, appearance, highContrast }: { size: number; appearance: MobileAppearance; highContrast: boolean }) {
  const center = size / 2;
  const outer = size * 0.455;
  const ringColor = highContrast ? `${appearance.blue}C8` : `${appearance.blue}70`;
  const softRing = highContrast ? `${appearance.green}A8` : `${appearance.green}48`;
  const gridColor = highContrast ? `${appearance.textMuted}8A` : `${appearance.blue}34`;
  return (
    <Svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <Path
        d={`M ${size * 0.04} ${size * 0.72} C ${size * 0.24} ${size * 0.55}, ${size * 0.45} ${size * 0.84}, ${size * 0.68} ${size * 0.61} S ${size * 0.95} ${size * 0.38}, ${size * 1.04} ${size * 0.27}`}
        fill="none"
        stroke={`${appearance.green}${highContrast ? "86" : "3D"}`}
        strokeWidth={highContrast ? 1.8 : 1.1}
        strokeDasharray="5 9"
      />
      <Circle cx={center} cy={center} r={outer} fill={`${appearance.blue}08`} stroke={ringColor} strokeWidth={highContrast ? 2.1 : 1.2} />
      <Circle cx={center} cy={center} r={outer * 0.72} fill="none" stroke={softRing} strokeWidth={highContrast ? 1.7 : 1} />
      <Circle cx={center} cy={center} r={outer * 0.42} fill="none" stroke={ringColor} strokeWidth={highContrast ? 1.7 : 1} />
      <Circle cx={center} cy={center} r={outer * 0.15} fill="none" stroke={softRing} strokeWidth={highContrast ? 1.5 : 1} />
      <Line x1={center - outer} y1={center} x2={center + outer} y2={center} stroke={gridColor} strokeWidth={1} />
      <Line x1={center} y1={center - outer} x2={center} y2={center + outer} stroke={gridColor} strokeWidth={1} />
      <G>
        {Array.from({ length: 24 }).map((_, index) => {
          const angle = index * 15;
          const inner = polarPoint(center, outer - (index % 3 === 0 ? 10 : 6), angle);
          const edge = polarPoint(center, outer, angle);
          return (
            <Line
              key={`bearing-${angle}`}
              x1={inner.x}
              y1={inner.y}
              x2={edge.x}
              y2={edge.y}
              stroke={gridColor}
              strokeWidth={index % 3 === 0 ? 1.3 : 0.8}
            />
          );
        })}
      </G>
      <Circle cx={center} cy={center} r={3.5} fill={appearance.green} stroke={appearance.bg} strokeWidth={2} />
    </Svg>
  );
}

function SweepLayer({ size, appearance, highContrast }: { size: number; appearance: MobileAppearance; highContrast: boolean }) {
  const center = size / 2;
  return (
    <Svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <Path d={sweepSectorPath(size)} fill={`${appearance.green}${highContrast ? "30" : "1B"}`} />
      <Line
        x1={center}
        y1={center}
        x2={center}
        y2={size * 0.045}
        stroke={appearance.green}
        strokeWidth={highContrast ? 2.4 : 1.7}
      />
    </Svg>
  );
}

export function LaunchOverlay({
  visible,
  opacity,
  shift,
  scale,
  sequence,
  ambientSweep,
  logoBreath,
  sequenceComplete,
  reduceMotion,
  ready,
  onEnter,
  status,
  qualifier,
  entryLabel = "Open Board",
  onFirstFrame
}: LaunchOverlayProps) {
  const { appearance, isHighContrast } = useMobileTheme();
  const { width, height } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const expanded = width >= 700;
  const landscape = width > height;
  const compactHeight = height < 720;
  const scopeSize = clamp(
    Math.min(width * (expanded ? 0.56 : 0.84), height * (landscape ? 0.58 : compactHeight ? 0.43 : 0.46)),
    landscape ? 190 : 246,
    expanded ? 430 : 342
  );
  const markSize = scopeSize * (expanded ? 0.4 : 0.43);
  const aircraftSize = scopeSize * 0.135;
  const routeKeyframes = useMemo(() => aircraftRouteKeyframes(scopeSize), [scopeSize]);
  const interceptPoint = aircraftRouteSample(0.72).point;
  const interceptBearing = Math.atan2(interceptPoint.x - 0.5, 0.5 - interceptPoint.y) * 180 / Math.PI;
  const styles = useMemo(
    () => makeStyles(appearance, expanded, compactHeight, isHighContrast),
    [appearance, compactHeight, expanded, isHighContrast]
  );
  const brandAsset = LOCAL_FLIGHT_BRAND_ASSETS[appearance.themeMode].icon;
  const footerMark = appearance.themeMode === "dark" ? appearance.textMuted : appearance.textDim;
  const readyPrompt = entryLabel === "Continue setup"
    ? "Tap anywhere to continue setup"
    : "Tap anywhere to enter";
  const visibleCaption = ready ? readyPrompt : status;
  const statusFade = useRef(new Animated.Value(1)).current;
  const previousCaptionRef = useRef(visibleCaption);

  useEffect(() => {
    if (previousCaptionRef.current === visibleCaption) return;
    previousCaptionRef.current = visibleCaption;
    if (reduceMotion) {
      statusFade.setValue(1);
      return;
    }
    Animated.sequence([
      Animated.timing(statusFade, { toValue: 0, duration: 90, useNativeDriver: true }),
      Animated.timing(statusFade, { toValue: 1, duration: 220, useNativeDriver: true })
    ]).start();
  }, [reduceMotion, statusFade, visibleCaption]);

  const atmosphereOpacity = sequence.interpolate({
    inputRange: [0, 0.13, 1],
    outputRange: [0, 1, 1],
    extrapolate: "clamp"
  });
  const scopeOpacity = sequence.interpolate({
    inputRange: [0, 0.13, 0.34, 0.74, 1],
    outputRange: [0, 0.12, 1, 0.88, 0.38],
    extrapolate: "clamp"
  });
  const scopeScale = sequence.interpolate({
    inputRange: [0, 0.18, 0.72, 1],
    outputRange: [0.88, 1, 1.025, 1.08],
    extrapolate: "clamp"
  });
  const sequenceSweepRotation = sequence.interpolate({
    inputRange: [0, 0.13, 0.64, 0.76, 1],
    outputRange: ["-125deg", "-125deg", `${interceptBearing}deg`, `${interceptBearing + 92}deg`, `${interceptBearing + 92}deg`],
    extrapolate: "clamp"
  });
  const sequenceSweepOpacity = sequence.interpolate({
    inputRange: [0, 0.13, 0.26, 0.72, 0.84, 1],
    outputRange: [0, 0, 0.9, 0.82, 0, 0],
    extrapolate: "clamp"
  });
  const ambientSweepRotation = ambientSweep.interpolate({
    inputRange: [0, 1],
    outputRange: ["0deg", "360deg"]
  });
  const ambientRingRotation = ambientSweep.interpolate({
    inputRange: [0, 1],
    outputRange: ["-8deg", "352deg"]
  });
  const ambientRingScale = ambientSweep.interpolate({
    inputRange: [0, 0.5, 1],
    outputRange: [1, 1.025, 1]
  });
  const aircraftOpacity = sequence.interpolate({
    inputRange: [0, 0.25, 0.29, 0.77, 0.79, 0.8, 1],
    outputRange: [0, 0, 1, 1, 1, 0, 0],
    extrapolate: "clamp"
  });
  const aircraftX = sequence.interpolate({
    inputRange: routeKeyframes.inputRange,
    outputRange: routeKeyframes.x,
    extrapolate: "clamp"
  });
  const aircraftY = sequence.interpolate({
    inputRange: routeKeyframes.inputRange,
    outputRange: routeKeyframes.y,
    extrapolate: "clamp"
  });
  const aircraftRotation = sequence.interpolate({
    inputRange: routeKeyframes.inputRange,
    outputRange: routeKeyframes.rotation,
    extrapolate: "clamp"
  });
  const aircraftScale = sequence.interpolate({
    inputRange: [0, 0.25, 0.31, 0.66, 0.79, 1],
    outputRange: [0.7, 0.7, 0.84, 1, 0.9, 0.9],
    extrapolate: "clamp"
  });
  const routeOpacity = sequence.interpolate({
    inputRange: [0, 0.25, 0.31, 0.72, 0.8, 1],
    outputRange: [0, 0, 0.68, 0.5, 0, 0],
    extrapolate: "clamp"
  });
  const lockOpacity = sequence.interpolate({
    inputRange: [0, 0.6, 0.635, 0.71, 0.78, 0.8, 1],
    outputRange: [0, 0, 1, 0.78, 0.35, 0, 0],
    extrapolate: "clamp"
  });
  const lockScale = sequence.interpolate({
    inputRange: [0, 0.6, 0.65, 0.79, 1],
    outputRange: [1.38, 1.38, 1, 0.78, 0.78],
    extrapolate: "clamp"
  });
  const finalMarkOpacity = sequence.interpolate({
    inputRange: [0, 0.805, 0.865, 1],
    outputRange: [0, 0, 1, 1],
    extrapolate: "clamp"
  });
  const finalMarkScale = sequence.interpolate({
    inputRange: [0, 0.805, 0.885, 1],
    outputRange: [0.86, 0.86, 1.025, 1],
    extrapolate: "clamp"
  });
  const breathingScale = logoBreath.interpolate({
    inputRange: [0, 1],
    outputRange: [0.99, 1.018]
  });
  const brandOpacity = sequence.interpolate({
    inputRange: [0, 0.82, 0.94, 1],
    outputRange: [0, 0, 1, 1],
    extrapolate: "clamp"
  });
  const brandShift = sequence.interpolate({
    inputRange: [0, 0.82, 1],
    outputRange: [12, 12, 0],
    extrapolate: "clamp"
  });
  const captionOpacity = sequence.interpolate({
    inputRange: [0, 0.08, 0.18, 1],
    outputRange: [0, 0, 1, 1],
    extrapolate: "clamp"
  });

  if (!visible) return null;

  return (
    <AnimatedPressable
      onLayout={onFirstFrame}
      onPress={ready ? onEnter : undefined}
      accessible
      accessibilityRole={ready ? "button" : undefined}
      accessibilityLabel={ready ? `Local Flight is ready. ${readyPrompt}.` : `Local Flight is opening. ${status}.`}
      accessibilityHint={ready ? "Opens Local Flight." : undefined}
      accessibilityState={{ disabled: !ready, busy: !ready }}
      style={[
        styles.overlay,
        {
          paddingTop: insets.top + (landscape ? 8 : 18),
          paddingBottom: insets.bottom + 16,
          opacity,
          transform: [{ translateY: shift }, { scale }]
        }
      ]}
    >
      <Animated.View style={[styles.atmosphere, { opacity: atmosphereOpacity }]} {...hideFromAccessibility()}>
        <View style={styles.northGlow} />
        <View style={styles.horizonGlow} />
        <View style={styles.horizonLine} />
        <View style={styles.southArc} />
        {NAVIGATION_POINTS.map((point, index) => (
          <View
            key={`nav-point-${index}`}
            style={[
              styles.navigationPoint,
              {
                left: point.left,
                top: point.top,
                width: point.size,
                height: point.size,
                opacity: isHighContrast ? Math.min(0.78, point.opacity * 2) : point.opacity
              }
            ]}
          />
        ))}
      </Animated.View>

      <View style={styles.content}>
        <View style={[styles.scene, { width: scopeSize, height: scopeSize }]} {...hideFromAccessibility()}>
          <Animated.View
            style={[
              styles.scopeLayer,
              {
                opacity: scopeOpacity,
                transform: [{ scale: scopeScale }]
              }
            ]}
          >
            <RadarVectorLayer size={scopeSize} appearance={appearance} highContrast={isHighContrast} />
          </Animated.View>

          {sequenceComplete && !reduceMotion ? (
            <Animated.View
              style={[
                styles.ambientRing,
                {
                  width: scopeSize * 0.88,
                  height: scopeSize * 0.88,
                  borderRadius: scopeSize,
                  transform: [{ rotate: ambientRingRotation }, { scale: ambientRingScale }]
                }
              ]}
            />
          ) : null}

          {!reduceMotion ? (
            <Animated.View
              style={[
                styles.sweepLayer,
                {
                  opacity: sequenceSweepOpacity,
                  transform: [{ rotate: sequenceSweepRotation }]
                }
              ]}
            >
              <SweepLayer size={scopeSize} appearance={appearance} highContrast={isHighContrast} />
            </Animated.View>
          ) : null}

          {sequenceComplete && !reduceMotion ? (
            <Animated.View style={[styles.sweepLayer, { opacity: 0.54, transform: [{ rotate: ambientSweepRotation }] }]}>
              <SweepLayer size={scopeSize} appearance={appearance} highContrast={isHighContrast} />
            </Animated.View>
          ) : null}

          <Animated.View style={[styles.routeTrace, { width: scopeSize, height: scopeSize, opacity: routeOpacity }]}>
            <Svg width={scopeSize} height={scopeSize} viewBox={`0 0 ${scopeSize} ${scopeSize}`}>
              <Path
                d={aircraftRoutePath(scopeSize)}
                fill="none"
                stroke={appearance.green}
                strokeWidth={isHighContrast ? 2.2 : 1.5}
                strokeDasharray="7 8"
              />
            </Svg>
          </Animated.View>

          {BLIPS.map((blip, index) => {
            const acquiredOpacity = sequence.interpolate({
              inputRange: [0, blip.acquire - 0.04, blip.acquire, 1],
              outputRange: [0.08, 0.08, 1, 1],
              extrapolate: "clamp"
            });
            const glintOpacity = ambientSweep.interpolate({
              inputRange: [0, Math.max(0.01, blip.glint - 0.035), blip.glint, Math.min(0.99, blip.glint + 0.09), 1],
              outputRange: [0.34, 0.34, 1, 0.4, 0.34],
              extrapolate: "clamp"
            });
            const glintScale = ambientSweep.interpolate({
              inputRange: [0, Math.max(0.01, blip.glint - 0.035), blip.glint, Math.min(0.99, blip.glint + 0.09), 1],
              outputRange: [1, 1, 1.65, 1, 1],
              extrapolate: "clamp"
            });
            return (
              <Animated.View
                key={`launch-blip-${index}`}
                style={[
                  styles.blipWrap,
                  {
                    left: blip.x * scopeSize - blip.size,
                    top: blip.y * scopeSize - blip.size,
                    width: blip.size * 2,
                    height: blip.size * 2,
                    opacity: reduceMotion ? finalMarkOpacity : acquiredOpacity
                  }
                ]}
              >
                <Animated.View
                  style={[
                    styles.blipHalo,
                    {
                      width: blip.size * 2,
                      height: blip.size * 2,
                      borderRadius: blip.size,
                      opacity: sequenceComplete && !reduceMotion ? glintOpacity : 0.36,
                      transform: [{ scale: sequenceComplete && !reduceMotion ? glintScale : 1 }]
                    }
                  ]}
                />
                <View style={[styles.blipCore, { width: Math.max(3, blip.size * 0.62), height: Math.max(3, blip.size * 0.62) }]} />
              </Animated.View>
            );
          })}

          {!reduceMotion ? (
            <Animated.View
              style={[
                styles.aircraftMotion,
                {
                  opacity: aircraftOpacity,
                  transform: [{ translateX: aircraftX }, { translateY: aircraftY }]
                }
              ]}
            >
              <Animated.View
                style={{
                  width: aircraftSize,
                  height: aircraftSize,
                  marginLeft: -aircraftSize / 2,
                  marginTop: -aircraftSize / 2,
                  transform: [{ rotate: aircraftRotation }, { scale: aircraftScale }]
                }}
              >
                <AircraftGlyph color={appearance.text} />
              </Animated.View>
            </Animated.View>
          ) : null}

          {!reduceMotion ? (
            <Animated.View
              style={[
                styles.aircraftLockMotion,
                {
                  opacity: lockOpacity,
                  transform: [{ translateX: aircraftX }, { translateY: aircraftY }]
                }
              ]}
            >
              <Animated.View
                style={[
                  styles.aircraftLockRing,
                  {
                    width: aircraftSize * 1.65,
                    height: aircraftSize * 1.65,
                    marginLeft: -aircraftSize * 0.825,
                    marginTop: -aircraftSize * 0.825,
                    borderRadius: aircraftSize,
                    transform: [{ scale: lockScale }]
                  }
                ]}
              />
            </Animated.View>
          ) : null}

          <Animated.View
            style={[
              styles.finalMark,
              {
                width: markSize,
                height: markSize,
                marginLeft: -markSize / 2,
                marginTop: -markSize / 2,
                opacity: finalMarkOpacity,
                transform: [{ scale: finalMarkScale }]
              }
            ]}
          >
            <Animated.View style={{ flex: 1, transform: [{ scale: sequenceComplete && !reduceMotion ? breathingScale : 1 }] }}>
              <Animated.Image
                source={brandAsset}
                resizeMode="contain"
                style={styles.markImage}
                accessibilityIgnoresInvertColors
              />
            </Animated.View>
          </Animated.View>
        </View>

        <Animated.View style={[styles.brandCopy, { opacity: brandOpacity, transform: [{ translateY: brandShift }] }]}>
          <BrandWordmark
            color={appearance.text}
            size={expanded ? 46 : compactHeight ? 31 : 37}
            style={styles.wordmark}
            adjustsFontSizeToFit
            minimumFontScale={0.72}
            numberOfLines={1}
          >
            Local Flight
          </BrandWordmark>
          <Text style={styles.subtitle}>Your airport, at a glance.</Text>
        </Animated.View>

        <Animated.View
          style={[styles.captionBlock, { opacity: captionOpacity }]}
          accessibilityLiveRegion="polite"
        >
          <Animated.Text style={[styles.caption, { opacity: statusFade }]}>{visibleCaption}</Animated.Text>
          {ready && qualifier ? <Text style={styles.qualifier}>{qualifier}</Text> : null}
        </Animated.View>
      </View>

      <View style={[styles.footer, { bottom: insets.bottom + 14 }]}>
        <BeaconToolsMark size={15} color={footerMark} windowColor={appearance.bg} />
        <Text style={styles.footerText}>Beacon Tools · v{APP_VERSION}</Text>
      </View>
    </AnimatedPressable>
  );
}

function makeStyles(a: MobileAppearance, expanded: boolean, compactHeight: boolean, highContrast: boolean) {
  const dark = a.themeMode === "dark";
  return StyleSheet.create({
    overlay: {
      ...StyleSheet.absoluteFillObject,
      zIndex: 1000,
      overflow: "hidden",
      alignItems: "center",
      justifyContent: "center",
      backgroundColor: a.bg,
      paddingHorizontal: expanded ? 42 : 20
    },
    atmosphere: {
      ...StyleSheet.absoluteFillObject,
      overflow: "hidden"
    },
    northGlow: {
      position: "absolute",
      width: expanded ? 820 : 480,
      height: expanded ? 520 : 360,
      borderRadius: 999,
      top: expanded ? -270 : -210,
      alignSelf: "center",
      backgroundColor: highContrast ? "transparent" : `${a.blue}${dark ? "14" : "10"}`
    },
    horizonGlow: {
      position: "absolute",
      left: -80,
      right: -80,
      height: expanded ? 220 : 160,
      top: expanded ? "38%" : "34%",
      borderRadius: 999,
      backgroundColor: highContrast ? "transparent" : `${a.green}${dark ? "0D" : "0A"}`
    },
    horizonLine: {
      position: "absolute",
      left: "5%",
      right: "5%",
      top: expanded ? "49%" : "45%",
      height: StyleSheet.hairlineWidth,
      backgroundColor: `${a.blue}${highContrast ? "62" : "2E"}`
    },
    southArc: {
      position: "absolute",
      width: expanded ? 780 : 520,
      height: expanded ? 780 : 520,
      borderRadius: 999,
      borderWidth: highContrast ? 1.5 : 1,
      borderColor: `${a.blue}${highContrast ? "72" : "2F"}`,
      left: expanded ? -360 : -330,
      bottom: expanded ? -530 : -370
    },
    navigationPoint: {
      position: "absolute",
      borderRadius: 999,
      backgroundColor: a.blue
    },
    content: {
      width: "100%",
      maxWidth: 700,
      alignItems: "center",
      justifyContent: "center",
      paddingBottom: compactHeight ? 26 : 44
    },
    scene: {
      alignItems: "center",
      justifyContent: "center"
    },
    scopeLayer: {
      ...StyleSheet.absoluteFillObject
    },
    ambientRing: {
      position: "absolute",
      alignSelf: "center",
      top: "6%",
      borderWidth: highContrast ? 1.5 : 1,
      borderColor: `${a.blue}${highContrast ? "90" : "48"}`,
      borderTopColor: a.green,
      borderLeftColor: "transparent"
    },
    sweepLayer: {
      ...StyleSheet.absoluteFillObject
    },
    routeTrace: {
      ...StyleSheet.absoluteFillObject
    },
    blipWrap: {
      position: "absolute",
      alignItems: "center",
      justifyContent: "center"
    },
    blipHalo: {
      position: "absolute",
      backgroundColor: `${a.green}${highContrast ? "7A" : "42"}`
    },
    blipCore: {
      borderRadius: 999,
      backgroundColor: a.green,
      borderWidth: highContrast ? 1 : 0,
      borderColor: a.text
    },
    aircraftMotion: {
      position: "absolute",
      left: "50%",
      top: "50%"
    },
    aircraftLockMotion: {
      position: "absolute",
      left: "50%",
      top: "50%",
      alignItems: "center",
      justifyContent: "center"
    },
    aircraftLockRing: {
      borderWidth: highContrast ? 2.2 : 1.5,
      borderColor: a.green,
      backgroundColor: "transparent"
    },
    finalMark: {
      position: "absolute",
      left: "50%",
      top: "50%"
    },
    markImage: {
      width: "100%",
      height: "100%"
    },
    brandCopy: {
      width: "100%",
      alignItems: "center",
      marginTop: compactHeight ? 4 : 10
    },
    wordmark: {
      width: "100%",
      maxWidth: expanded ? 560 : 380,
      textAlign: "center"
    },
    subtitle: {
      color: highContrast ? a.text : a.textMuted,
      fontSize: expanded ? 19 : compactHeight ? 15 : 17,
      lineHeight: expanded ? 27 : compactHeight ? 21 : 24,
      marginTop: 8,
      textAlign: "center"
    },
    captionBlock: {
      minHeight: compactHeight ? 44 : 54,
      width: "100%",
      maxWidth: 420,
      alignItems: "center",
      justifyContent: "flex-start",
      marginTop: compactHeight ? 18 : 25,
      paddingHorizontal: 12
    },
    caption: {
      fontFamily: UI_FONT_FAMILY,
      color: highContrast ? a.text : a.textDim,
      fontSize: expanded ? 16 : 15,
      lineHeight: expanded ? 23 : 22,
      fontWeight: "500",
      textAlign: "center"
    },
    qualifier: {
      color: highContrast ? a.textMuted : a.textDim,
      fontSize: expanded ? 14 : 13,
      lineHeight: expanded ? 20 : 18,
      marginTop: 4,
      textAlign: "center"
    },
    footer: {
      position: "absolute",
      flexDirection: "row",
      alignItems: "center",
      gap: 8,
      opacity: highContrast ? 0.9 : 0.72
    },
    footerText: {
      color: highContrast ? a.textMuted : a.textDim,
      fontSize: 12
    }
  });
}
