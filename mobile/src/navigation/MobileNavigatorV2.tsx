import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Animated, Platform, Pressable, StyleSheet, View } from "react-native";
import * as ScreenOrientation from "expo-screen-orientation";
import {
  CommonActions,
  NavigationContainer,
  createNavigationContainerRef,
  useFocusEffect,
  useNavigation,
  type LinkingOptions,
  type NavigationProp,
  type NavigatorScreenParams,
  type RouteProp,
  type Theme
} from "@react-navigation/native";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import {
  createNativeBottomTabNavigator,
  type NativeBottomTabIcon
} from "@react-navigation/bottom-tabs/unstable";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import type { ClientNotice } from "../api/types";
import { accessibleButton, useReducedMotionPreference } from "../accessibility/mobileA11y";
import { V2_MOTION } from "../components/MotionPressable";
import { V2Text as Text } from "../components/V2Text";
import { useMobileSession, type MobileSection } from "../session/MobileSessionProvider";
import { LocalFlightIcon, type LocalFlightIconName } from "../theme/icons";
import { useMobileTheme } from "../theme/runtime";
import type { MobileAppearance } from "../theme/tokens";
import { hapticSelection } from "../utils/haptics";
import { useResponsiveLayout } from "../utils/layout";
import type { NativeNavigationCapabilities } from "./nativeNavigationCapabilities";
import { NativeShortcutHost, type NativeShortcutKey } from "./NativeShortcutHost";
import { BoardScreenV2 } from "../v2/BoardScreenV2";
import { DisplayScreenV2 } from "../v2/DisplayScreenV2";
import { HistoryScreenV2 } from "../v2/HistoryScreenV2";
import { MoreScreenV2, type MorePanel, type MoreScreenV2Props } from "../v2/MoreScreenV2";
import { RadarScreenV2 } from "../v2/RadarScreenV2";

export type MobileTabParamList = {
  Board: undefined;
  Radar: undefined;
  History: undefined;
  More: { panel?: Exclude<MorePanel, null>; requestKey?: number } | undefined;
};

export type MobileRootStackParamList = {
  Main: NavigatorScreenParams<MobileTabParamList> | undefined;
  Display: { entry?: "manual" | "rotation" | "deep-link" } | undefined;
  Pairing: undefined;
  Widgets: undefined;
  WidgetRefresh: undefined;
  Flight: { pin?: string; source?: string } | undefined;
};

const Tabs = createBottomTabNavigator<MobileTabParamList>();
const NativeTabs = createNativeBottomTabNavigator<MobileTabParamList>();
const Stack = createNativeStackNavigator<MobileRootStackParamList>();

export const mobileNavigationRef = createNavigationContainerRef<MobileRootStackParamList>();

export function navigateMobileSection(section: MobileSection) {
  if (!mobileNavigationRef.isReady()) return;
  const screen = section === "board" ? "Board" : section === "radar" ? "Radar" : section === "history" ? "History" : "More";
  mobileNavigationRef.dispatch(CommonActions.navigate({ name: "Main", params: { screen } }));
}

export function openMobileDisplay(entry: "manual" | "rotation" | "deep-link" = "manual") {
  if (mobileNavigationRef.isReady()) mobileNavigationRef.navigate("Display", { entry });
}

export function openMobileMorePanel(panel?: Exclude<MorePanel, null>) {
  if (!mobileNavigationRef.isReady()) return;
  mobileNavigationRef.dispatch(CommonActions.navigate({
    name: "Main",
    params: {
      screen: "More",
      params: panel ? { panel, requestKey: Date.now() } : undefined
    }
  }));
}

const linking: LinkingOptions<MobileRootStackParamList> = {
  prefixes: ["localflight://", "https://beacontools.cc/local-flight/mobile"],
  config: {
    screens: {
      Main: {
        screens: {
          Board: "board",
          Radar: "radar",
          History: "history",
          More: {
            path: "more",
            alias: ["settings"]
          }
        }
      },
      Display: "display",
      Pairing: { path: "pairing", alias: ["pair"] },
      Widgets: "widgets",
      WidgetRefresh: { path: "widget-refresh", alias: ["refresh-widget"] },
      Flight: "flight"
    }
  }
};

function noticeAccent(notice: ClientNotice, appearance: MobileAppearance): string {
  if (notice.tone === "error") return appearance.red;
  if (notice.tone === "warning") return appearance.amber;
  if (notice.tone === "success") return appearance.green;
  return appearance.blue;
}

function NoticeStack() {
  const { notices, onNoticeAction } = useMobileSession();
  const { appearance } = useMobileTheme();
  if (!notices.length) return null;
  return (
    <View style={navigationStyles.noticeStack}>
      {notices.slice(0, 2).map((notice) => {
        const accent = noticeAccent(notice, appearance);
        return (
          <View key={notice.code} style={[navigationStyles.notice, { backgroundColor: appearance.shell }]} accessible accessibilityRole="alert">
            <View style={[navigationStyles.noticeAccent, { backgroundColor: accent }]} />
            <View style={navigationStyles.noticeCopy}>
              <Text style={[navigationStyles.noticeMessage, { color: appearance.text }]}>{notice.message}</Text>
              {notice.next_step ? <Text style={[navigationStyles.noticeNext, { color: appearance.textMuted }]}>{notice.next_step}</Text> : null}
            </View>
            {notice.action?.label ? (
              <Pressable style={navigationStyles.noticeButton} onPress={() => onNoticeAction(notice)} {...accessibleButton({ label: notice.action.label })}>
                <Text style={[navigationStyles.noticeAction, { color: accent }]}>{notice.action.label}</Text>
              </Pressable>
            ) : null}
          </View>
        );
      })}
    </View>
  );
}

function FeatureFrame({ children, nativeScrollRoot = false }: { children: ReactNode; nativeScrollRoot?: boolean }) {
  const { appearance } = useMobileTheme();
  const reduceMotion = useReducedMotionPreference();
  const opacity = useRef(new Animated.Value(1)).current;
  const shift = useRef(new Animated.Value(0)).current;
  useFocusEffect(useCallback(() => {
    if (reduceMotion) {
      opacity.setValue(1);
      shift.setValue(0);
      return undefined;
    }
    opacity.setValue(0);
    shift.setValue(8);
    const animation = Animated.parallel([
      Animated.timing(opacity, { toValue: 1, duration: V2_MOTION.pageRevealMs, useNativeDriver: true }),
      Animated.timing(shift, { toValue: 0, duration: V2_MOTION.pageRevealMs, useNativeDriver: true })
    ]);
    animation.start();
    return () => animation.stop();
  }, [opacity, reduceMotion, shift]));
  if (nativeScrollRoot) {
    return (
      <>
        {children}
        <View pointerEvents="box-none" style={navigationStyles.nativeNoticeOverlay}>
          <NoticeStack />
        </View>
      </>
    );
  }
  return (
    <View style={[navigationStyles.featureFrame, { backgroundColor: appearance.bg }]}>
      <NoticeStack />
      <Animated.View style={[navigationStyles.featureContent, { opacity, transform: [{ translateY: shift }] }]}>{children}</Animated.View>
    </View>
  );
}

function useSectionFocus(section: MobileSection) {
  const { onSectionFocus } = useMobileSession();
  useFocusEffect(useCallback(() => {
    onSectionFocus(section);
  }, [onSectionFocus, section]));
}

function BoardRoute({ nativeScrollRoot = false }: { nativeScrollRoot?: boolean }) {
  useSectionFocus("board");
  const { board } = useMobileSession();
  const navigation = useNavigation<NavigationProp<MobileRootStackParamList>>();
  return (
    <FeatureFrame nativeScrollRoot={nativeScrollRoot}>
      <BoardScreenV2 {...board} onOpenDisplay={() => navigation.navigate("Display", { entry: "manual" })} />
    </FeatureFrame>
  );
}

function RadarRoute({ dismissRequestKey }: { dismissRequestKey: number }) {
  useSectionFocus("radar");
  const { radar } = useMobileSession();
  return <FeatureFrame><RadarScreenV2 {...radar} dismissRequestKey={dismissRequestKey} /></FeatureFrame>;
}

function HistoryRoute({ dismissRequestKey, nativeScrollRoot = false }: { dismissRequestKey: number; nativeScrollRoot?: boolean }) {
  useSectionFocus("history");
  const { history } = useMobileSession();
  return <FeatureFrame nativeScrollRoot={nativeScrollRoot}><HistoryScreenV2 {...history} dismissRequestKey={dismissRequestKey} /></FeatureFrame>;
}

function MoreRoute({
  more,
  route,
  dismissRequestKey
}: {
  more: MoreScreenV2Props;
  route: RouteProp<MobileTabParamList, "More">;
  dismissRequestKey: number;
}) {
  useSectionFocus("more");
  return (
    <FeatureFrame>
      <MoreScreenV2
        {...more}
        requestedPanel={route.params?.panel}
        panelRequestKey={route.params?.requestKey}
        dismissRequestKey={dismissRequestKey}
      />
    </FeatureFrame>
  );
}

function DeepLinkActionRoute({
  action,
  more
}: {
  action: "pairing" | "widgets" | "widget-refresh";
  more: MoreScreenV2Props;
}) {
  const { appearance } = useMobileTheme();
  const navigation = useNavigation<NavigationProp<MobileRootStackParamList>>();
  const handled = useRef(false);

  useEffect(() => {
    if (handled.current) return;
    handled.current = true;
    if (action === "pairing" && more.standalone) {
      more.onRerunSetup();
      return;
    }
    const requestKey = Date.now();
    if (action === "widget-refresh") more.onRefreshWidget();
    navigation.dispatch(CommonActions.reset({
      index: 0,
      routes: [{
        name: "Main",
        params: {
          screen: action === "pairing" ? "More" : "Board",
          params: action === "pairing" ? { panel: "host", requestKey } : undefined
        }
      }]
    }));
  }, [action, more, navigation]);

  return <View style={{ flex: 1, backgroundColor: appearance.bg }} />;
}

function DisplayRoute({
  route,
  onExit
}: {
  route: RouteProp<MobileRootStackParamList, "Display">;
  onExit: () => void;
}) {
  const { board } = useMobileSession();
  return (
    <DisplayScreenV2
      rows={board.rows}
      view={board.view}
      airportCode={board.airportCode}
      airportName={board.airportName}
      airportLocation={board.airportLocation}
      localTime={board.localTime}
      updatedLabel={board.updatedLabel}
      metar={board.metar}
      pinnedCallsign={board.pinnedCallsign}
      pageSeconds={board.displayPageSeconds}
      entryReason={route.params?.entry || "deep-link"}
      autoDisplayOnRotate={board.autoDisplayOnRotate}
      onAutoDisplayOnRotateChange={board.onAutoDisplayOnRotateChange}
      onExit={onExit}
    />
  );
}

function tabIcon(name: keyof MobileTabParamList, focused: boolean): LocalFlightIconName {
  if (name === "Board") return focused ? "view-list" : "view-list-outline";
  if (name === "Radar") return "radar";
  if (name === "History") return focused ? "history" : "history";
  return focused ? "dots-horizontal-circle" : "dots-horizontal-circle-outline";
}

function nativeTabIcon(name: keyof MobileTabParamList, focused: boolean): NativeBottomTabIcon {
  const symbol = name === "Board"
    ? "list.bullet"
    : name === "Radar"
      ? "scope"
      : name === "History"
        ? "clock.arrow.circlepath"
        : focused
          ? "ellipsis.circle.fill"
          : "ellipsis.circle";
  return { type: "sfSymbol", name: symbol };
}

function LiquidGlassTabs({
  more,
  dismissRequestKey
}: {
  more: MoreScreenV2Props;
  dismissRequestKey: number;
}) {
  const { appearance } = useMobileTheme();
  const initialRouteRef = useRef<keyof MobileTabParamList>("Board");
  const appearanceKeyRef = useRef(appearance.key);
  if (appearanceKeyRef.current !== appearance.key) {
    const currentRoute = mobileNavigationRef.isReady() ? mobileNavigationRef.getCurrentRoute()?.name : undefined;
    if (currentRoute === "Board" || currentRoute === "Radar" || currentRoute === "History" || currentRoute === "More") {
      initialRouteRef.current = currentRoute;
    }
    appearanceKeyRef.current = appearance.key;
  }
  return (
    <NativeTabs.Navigator
      key={appearance.key}
      initialRouteName={initialRouteRef.current}
      screenOptions={({ route }) => ({
        // Root V2 screens own their content headings. The UIKit tab bar is the
        // only native chrome here, so it can render its iOS 26 material without
        // a second header competing with the airport and freshness hierarchy.
        headerShown: false,
        title: route.name,
        tabBarLabel: route.name,
        tabBarIcon: ({ focused }) => nativeTabIcon(route.name, focused),
        tabBarActiveTintColor: appearance.blue,
        tabBarControllerMode: "tabBar",
        tabBarMinimizeBehavior: route.name === "Board" || route.name === "History"
          ? "onScrollDown"
          : "none",
        // The native implementation follows the first descendant scroll view
        // and preserves rows behind the translucent Liquid Glass tab bar.
        overrideScrollViewContentInsetAdjustmentBehavior: true
      })}
      screenListeners={{
        tabPress: () => hapticSelection()
      }}
    >
      <NativeTabs.Screen name="Board">{() => <BoardRoute nativeScrollRoot />}</NativeTabs.Screen>
      <NativeTabs.Screen name="Radar">{() => <RadarRoute dismissRequestKey={dismissRequestKey} />}</NativeTabs.Screen>
      <NativeTabs.Screen name="History">{() => <HistoryRoute dismissRequestKey={dismissRequestKey} nativeScrollRoot />}</NativeTabs.Screen>
      <NativeTabs.Screen name="More">
        {({ route }) => <MoreRoute more={more} route={route} dismissRequestKey={dismissRequestKey} />}
      </NativeTabs.Screen>
    </NativeTabs.Navigator>
  );
}

function AdaptiveTabs({
  more,
  dismissRequestKey,
  nativeNavigation
}: {
  more: MoreScreenV2Props;
  dismissRequestKey: number;
  nativeNavigation: NativeNavigationCapabilities;
}) {
  const { appearance } = useMobileTheme();
  const layout = useResponsiveLayout();
  const insets = useSafeAreaInsets();
  if (nativeNavigation.usesNativeLiquidGlassTabs) {
    return <LiquidGlassTabs more={more} dismissRequestKey={dismissRequestKey} />;
  }
  const rail = !layout.isCompact;
  const compactRail = layout.sizeClass === "medium";
  return (
    <Tabs.Navigator
      initialRouteName="Board"
      screenOptions={({ route }) => ({
        headerShown: false,
        animation: "fade",
        sceneStyle: { backgroundColor: appearance.bg },
        tabBarPosition: rail ? "left" : "bottom",
        tabBarVariant: rail ? "material" : "uikit",
        tabBarLabelPosition: rail && !compactRail ? "beside-icon" : "below-icon",
        tabBarActiveTintColor: appearance.blue,
        tabBarInactiveTintColor: appearance.textMuted,
        tabBarActiveBackgroundColor: `${appearance.blue}12`,
        tabBarHideOnKeyboard: true,
        tabBarStyle: rail
          ? {
              width: compactRail ? 88 : 214,
              backgroundColor: appearance.shell,
              borderRightWidth: StyleSheet.hairlineWidth,
              borderRightColor: appearance.line,
              paddingHorizontal: compactRail ? 8 : 12,
              paddingVertical: 12
            }
          : {
              minHeight: 66 + insets.bottom,
              backgroundColor: appearance.shell,
              borderTopWidth: StyleSheet.hairlineWidth,
              borderTopColor: appearance.line,
              paddingTop: 6,
              paddingBottom: Math.max(6, insets.bottom)
            },
        tabBarItemStyle: rail
          ? { minHeight: 54, borderRadius: 16, marginVertical: 3 }
          : { minHeight: 54, borderRadius: 15, marginHorizontal: 3 },
        tabBarLabelStyle: {
          fontSize: rail && !compactRail ? 14 : 11,
          fontWeight: "600"
        },
        tabBarIcon: ({ color, size, focused }) => (
          <LocalFlightIcon name={tabIcon(route.name, focused)} size={Math.max(21, size)} color={color} />
        )
      })}
      screenListeners={{
        tabPress: () => hapticSelection()
      }}
    >
      <Tabs.Screen name="Board" component={BoardRoute} />
      <Tabs.Screen name="Radar">{() => <RadarRoute dismissRequestKey={dismissRequestKey} />}</Tabs.Screen>
      <Tabs.Screen name="History">{() => <HistoryRoute dismissRequestKey={dismissRequestKey} />}</Tabs.Screen>
      <Tabs.Screen name="More">
        {({ route }) => <MoreRoute more={more} route={route} dismissRequestKey={dismissRequestKey} />}
      </Tabs.Screen>
    </Tabs.Navigator>
  );
}

function useWebKeyboardShortcuts(onShortcut: (key: NativeShortcutKey) => void) {
  useEffect(() => {
    if (Platform.OS !== "web" || typeof document === "undefined") return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onShortcut("escape");
        return;
      }
      if (!(event.metaKey || event.ctrlKey)) return;
      const key = event.key.toLowerCase();
      if (key === "1" || key === "2" || key === "3" || key === "4" || key === "r" || key === "f") {
        event.preventDefault();
        onShortcut(key);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onShortcut]);
}

export function MobileNavigatorV2({
  more,
  nativeNavigation
}: {
  more: MoreScreenV2Props;
  nativeNavigation: NativeNavigationCapabilities;
}) {
  const { theme, appearance } = useMobileTheme();
  const {
    onDismissTransientSurface,
    onOpenSearchOrFilter,
    onRefreshCurrent,
    rotationDisplayBlocked
  } = useMobileSession();
  const [dismissRequestKey, setDismissRequestKey] = useState(0);
  const [currentRouteName, setCurrentRouteName] = useState<string>("Board");
  const currentRouteNameRef = useRef(currentRouteName);
  const rotationReentrySuppressedRef = useRef(false);
  const landscapeRef = useRef(false);

  useEffect(() => {
    currentRouteNameRef.current = currentRouteName;
  }, [currentRouteName]);

  const updateCurrentRoute = useCallback(() => {
    if (!mobileNavigationRef.isReady()) return;
    const name = mobileNavigationRef.getCurrentRoute()?.name || "Board";
    currentRouteNameRef.current = name;
    setCurrentRouteName(name);
  }, []);

  const closeDisplay = useCallback(() => {
    if (landscapeRef.current) rotationReentrySuppressedRef.current = true;
    if (mobileNavigationRef.isReady() && mobileNavigationRef.canGoBack()) mobileNavigationRef.goBack();
  }, []);

  useEffect(() => {
    if (Platform.OS !== "ios" && Platform.OS !== "android") return;
    const handleOrientation = (orientation: ScreenOrientation.Orientation) => {
      const landscape = orientation === ScreenOrientation.Orientation.LANDSCAPE_LEFT
        || orientation === ScreenOrientation.Orientation.LANDSCAPE_RIGHT;
      const portrait = orientation === ScreenOrientation.Orientation.PORTRAIT_UP
        || orientation === ScreenOrientation.Orientation.PORTRAIT_DOWN;
      if (!landscape && !portrait) return;
      landscapeRef.current = landscape;
      if (portrait) {
        rotationReentrySuppressedRef.current = false;
        const route = mobileNavigationRef.isReady() ? mobileNavigationRef.getCurrentRoute() : undefined;
        const params = route?.params as MobileRootStackParamList["Display"];
        if (route?.name === "Display" && params?.entry === "rotation" && mobileNavigationRef.canGoBack()) {
          mobileNavigationRef.goBack();
        }
        return;
      }
      if (
        more.autoDisplayOnRotate
        && !rotationDisplayBlocked
        && !rotationReentrySuppressedRef.current
        && currentRouteNameRef.current === "Board"
        && mobileNavigationRef.isReady()
      ) {
        currentRouteNameRef.current = "Display";
        mobileNavigationRef.navigate("Display", { entry: "rotation" });
      }
    };
    void ScreenOrientation.getOrientationAsync().then(handleOrientation).catch(() => undefined);
    const subscription = ScreenOrientation.addOrientationChangeListener((event) => handleOrientation(event.orientationInfo.orientation));
    return () => ScreenOrientation.removeOrientationChangeListener(subscription);
  }, [more.autoDisplayOnRotate, rotationDisplayBlocked]);
  const handleShortcut = useCallback((key: NativeShortcutKey) => {
    if (key === "escape") {
      if (mobileNavigationRef.isReady() && mobileNavigationRef.getCurrentRoute()?.name === "Display") {
        closeDisplay();
      } else {
        onDismissTransientSurface();
        setDismissRequestKey((value) => value + 1);
      }
      return;
    }
    if (key === "r") {
      onRefreshCurrent();
      return;
    }
    if (key === "f") {
      onOpenSearchOrFilter();
      return;
    }
    const screen = key === "1" ? "Board" : key === "2" ? "Radar" : key === "3" ? "History" : "More";
    if (mobileNavigationRef.isReady()) {
      mobileNavigationRef.dispatch(CommonActions.navigate({ name: "Main", params: { screen } }));
    }
  }, [closeDisplay, onDismissTransientSurface, onOpenSearchOrFilter, onRefreshCurrent]);
  useWebKeyboardShortcuts(handleShortcut);
  const navigationTheme = useMemo<Theme>(() => ({
    dark: theme.mode === "dark",
    colors: {
      primary: appearance.blue,
      background: appearance.bg,
      card: appearance.shell,
      text: appearance.text,
      border: appearance.line,
      notification: appearance.red
    },
    fonts: {
      regular: { fontFamily: "System", fontWeight: "400" },
      medium: { fontFamily: "System", fontWeight: "500" },
      bold: { fontFamily: "System", fontWeight: "700" },
      heavy: { fontFamily: "System", fontWeight: "800" }
    }
  }), [appearance, theme.mode]);

  return (
    <NativeShortcutHost onShortcut={handleShortcut}>
      <NavigationContainer
        ref={mobileNavigationRef}
        linking={linking}
        theme={navigationTheme}
        onReady={updateCurrentRoute}
        onStateChange={updateCurrentRoute}
      >
        <Stack.Navigator
          screenOptions={{
            headerShown: false,
            contentStyle: { backgroundColor: appearance.bg },
            animation: "fade_from_bottom",
            animationDuration: 200,
            fullScreenGestureEnabled: true
          }}
        >
          <Stack.Screen name="Main">
            {() => (
              <AdaptiveTabs
                more={more}
                dismissRequestKey={dismissRequestKey}
                nativeNavigation={nativeNavigation}
              />
            )}
          </Stack.Screen>
          <Stack.Screen
            name="Display"
            options={{ presentation: "fullScreenModal", animation: "fade", gestureEnabled: false }}
          >
            {({ route }) => <DisplayRoute route={route} onExit={closeDisplay} />}
          </Stack.Screen>
          <Stack.Screen name="Pairing" options={{ animation: "none" }}>
            {() => <DeepLinkActionRoute action="pairing" more={more} />}
          </Stack.Screen>
          <Stack.Screen name="Widgets" options={{ animation: "none" }}>
            {() => <DeepLinkActionRoute action="widgets" more={more} />}
          </Stack.Screen>
          <Stack.Screen name="WidgetRefresh" options={{ animation: "none" }}>
            {() => <DeepLinkActionRoute action="widget-refresh" more={more} />}
          </Stack.Screen>
          <Stack.Screen name="Flight" options={{ animation: "none" }}>
            {() => <DeepLinkActionRoute action="widgets" more={more} />}
          </Stack.Screen>
        </Stack.Navigator>
      </NavigationContainer>
    </NativeShortcutHost>
  );
}

const navigationStyles = StyleSheet.create({
  featureFrame: { flex: 1 },
  featureContent: { flex: 1 },
  noticeStack: { paddingHorizontal: 12, paddingTop: 7, gap: 6 },
  notice: { minHeight: 54, flexDirection: "row", alignItems: "center", overflow: "hidden", borderRadius: 16, paddingRight: 10 },
  noticeAccent: { width: 4, alignSelf: "stretch" },
  noticeCopy: { flex: 1, paddingHorizontal: 11, paddingVertical: 9 },
  noticeMessage: { fontSize: 13, fontWeight: "700" },
  noticeNext: { fontSize: 12, lineHeight: 16, marginTop: 2 },
  noticeButton: { minHeight: 44, justifyContent: "center", paddingHorizontal: 7 },
  noticeAction: { fontSize: 13, fontWeight: "700" },
  nativeNoticeOverlay: { ...StyleSheet.absoluteFillObject, bottom: undefined, zIndex: 5 }
});
