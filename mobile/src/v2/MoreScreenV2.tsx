import { useEffect, useMemo, useState } from "react";
import {
  Linking,
  Modal,
  Platform,
  Pressable,
  RefreshControl,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Switch,
  TextInput,
  View
} from "react-native";

import { accessibleButton } from "../accessibility/mobileA11y";
import { paidAppStoreLabel, type MobileRelayAccessSnapshot } from "../access/paidAppAccess";
import { englishCopy } from "../content/en";
import { BrandWordmark } from "../components/Brand";
import { MotionPressable } from "../components/MotionPressable";
import { V2Text as Text } from "../components/V2Text";
import type { WidgetFlightPreview, WidgetPreviewSnapshot } from "../domain/widgets";
import { SupportPurchaseContent } from "../iap/SupportPurchaseContent";
import type { SupportPurchaseController } from "../iap/types";
import type {
  MobileDiagnosticsMode,
  MobileWeatherDisplayMode,
  MobileWidgetAppearance,
  MobileWidgetPreferences
} from "../storage/settings";
import { LocalFlightIcon, type LocalFlightIconName } from "../theme/icons";
import { useMobileTheme } from "../theme/runtime";
import type { MobileAppearance, MobileThemePreference } from "../theme/tokens";
import { hapticLight, hapticSelection } from "../utils/haptics";
import type { LayoutWidthClass } from "../utils/layout";

export type MorePanel = "appearance" | "board" | "widgets" | "host" | "relay" | "help" | "advanced" | "support" | null;

export type MoreScreenV2Props = {
  airportCode: string;
  airportName: string;
  connectionLabel: string;
  standalone: boolean;
  layoutClass: LayoutWidthClass;
  refreshing: boolean;
  widgetRefreshing: boolean;
  contentPaddingBottom: number;
  /** True only while UIKit owns the compact iPhone tab bar. */
  nativeNavigation?: boolean;
  supportPurchases: SupportPurchaseController;
  widgetPreview: WidgetPreviewSnapshot;
  widgetPreferences: MobileWidgetPreferences;
  widgetSnapshotLabel: string;
  liveActivitySupported: boolean;
  weatherDisplayMode: MobileWeatherDisplayMode;
  autoDisplayOnRotate: boolean;
  diagnosticsMode: MobileDiagnosticsMode;
  requestedPanel?: Exclude<MorePanel, null>;
  panelRequestKey?: number;
  dismissRequestKey?: number;
  onRefresh: () => void;
  onRefreshWidget: () => void;
  onWidgetPreferencesChange: (next: MobileWidgetPreferences) => void;
  onWeatherDisplayModeChange: (next: MobileWeatherDisplayMode) => void;
  onAutoDisplayOnRotateChange: (next: boolean) => void;
  onDiagnosticsModeChange: (next: MobileDiagnosticsMode) => void;
  onOpenAirport: () => void;
  onRerunSetup: () => void;
  relayAccess: MobileRelayAccessSnapshot;
  relayProtectionAvailable: boolean;
  onVerifyRelayAccess: () => Promise<string | void> | string | void;
  onProtectRelayAccess: (email: string) => Promise<string>;
};

type RowProps = {
  icon: LocalFlightIconName;
  title: string;
  detail: string;
  onPress: () => void;
  appearance: MobileAppearance;
  styles: ReturnType<typeof makeStyles>;
};

function SettingsRow({ icon, title, detail, onPress, appearance, styles }: RowProps) {
  return (
    <MotionPressable
      style={styles.settingsRow}
      interactiveStyle={styles.rowPressed}
      onPress={() => {
        hapticSelection();
        onPress();
      }}
      focusable
      {...accessibleButton({ label: `${title}. ${detail}` })}
    >
      <View style={styles.rowIcon}>
        <LocalFlightIcon name={icon} size={21} color={appearance.blue} />
      </View>
      <View style={styles.rowCopy}>
        <Text style={styles.rowTitle}>{title}</Text>
        <Text style={styles.rowDetail}>{detail}</Text>
      </View>
      <LocalFlightIcon name="chevron-right" size={19} color={appearance.textDim} />
    </MotionPressable>
  );
}

function AppearancePanel({
  appearance,
  styles
}: {
  appearance: MobileAppearance;
  styles: ReturnType<typeof makeStyles>;
}) {
  const {
    preference,
    isHighContrast,
    setPreference,
    setHighContrast
  } = useMobileTheme();
  const choices: Array<{ value: MobileThemePreference; title: string; detail: string; icon: LocalFlightIconName }> = [
    { value: "system", title: englishCopy.settings.appearanceSystem.label, detail: englishCopy.settings.appearanceSystem.description, icon: "theme-light-dark" },
    { value: "light", title: englishCopy.settings.appearanceLight.label, detail: englishCopy.settings.appearanceLight.description, icon: "white-balance-sunny" },
    { value: "dark", title: englishCopy.settings.appearanceDark.label, detail: englishCopy.settings.appearanceDark.description, icon: "weather-night" }
  ];
  return (
    <View style={styles.panelContent}>
      <Text style={styles.panelIntro}>Choose an appearance for this device. Flight status colors always include a text label.</Text>
      <View style={styles.choiceGroup}>
        {choices.map((choice) => {
          const selected = preference === choice.value;
          return (
            <Pressable
              key={choice.value}
              style={[styles.appearanceChoice, selected && styles.appearanceChoiceSelected]}
              onPress={() => {
                hapticSelection();
                setPreference(choice.value);
              }}
              {...accessibleButton({ label: `${choice.title}. ${choice.detail}`, selected })}
            >
              <LocalFlightIcon name={choice.icon} size={21} color={selected ? appearance.blue : appearance.textMuted} />
              <View style={styles.rowCopy}>
                <Text style={styles.rowTitle}>{choice.title}</Text>
                <Text style={styles.rowDetail}>{choice.detail}</Text>
              </View>
              <View style={[styles.radio, selected && styles.radioSelected]}>{selected ? <View style={styles.radioDot} /> : null}</View>
            </Pressable>
          );
        })}
      </View>
      <View style={styles.switchRow}>
        <View style={styles.rowCopy}>
          <Text style={styles.rowTitle}>{englishCopy.settings.highContrast.label}</Text>
          <Text style={styles.rowDetail}>{englishCopy.settings.highContrast.description}</Text>
        </View>
        <Switch
          value={isHighContrast}
          onValueChange={(enabled) => {
            hapticSelection();
            setHighContrast(enabled);
          }}
          trackColor={{ false: appearance.line, true: `${appearance.blue}80` }}
          thumbColor={isHighContrast ? appearance.blue : appearance.textMuted}
          accessibilityLabel="High contrast"
        />
      </View>
    </View>
  );
}

function HelpPanel({ styles }: { styles: ReturnType<typeof makeStyles> }) {
  const open = (url: string) => void Linking.openURL(url);
  return (
    <View style={styles.panelContent}>
      <Text style={styles.panelIntro}>Local Flight is a local-first informational display. It does not replace airport, airline, dispatch, navigation, or operational information.</Text>
      <View style={styles.helpCard}>
        <Text style={styles.helpTitle}>Need a hand?</Text>
        <Text style={styles.helpBody}>Setup and privacy guides use plain language first, with technical detail available when you need it.</Text>
        <Pressable style={styles.linkButton} onPress={() => open("https://beacontools.cc/support")} {...accessibleButton({ label: "Open Local Flight support website" })}>
          <Text style={styles.linkText}>Support</Text>
          <LocalFlightIcon name="open-in-new" size={16} color={styles.linkText.color as string} />
        </Pressable>
        <Pressable style={styles.linkButton} onPress={() => open("https://beacontools.cc/privacy")} {...accessibleButton({ label: "Open Local Flight privacy information" })}>
          <Text style={styles.linkText}>Privacy</Text>
          <LocalFlightIcon name="open-in-new" size={16} color={styles.linkText.color as string} />
        </Pressable>
        <Pressable style={styles.linkButton} onPress={() => open("https://beacontools.cc/network")} {...accessibleButton({ label: "Open Local Flight network explanation" })}>
          <Text style={styles.linkText}>How connections work</Text>
          <LocalFlightIcon name="open-in-new" size={16} color={styles.linkText.color as string} />
        </Pressable>
      </View>
      <Text style={styles.disclaimer}>{englishCopy.app.informationalDisclaimer}</Text>
    </View>
  );
}

function BoardDisplayPanel({
  appearance,
  styles,
  standalone,
  weatherDisplayMode,
  autoDisplayOnRotate,
  onWeatherDisplayModeChange,
  onAutoDisplayOnRotateChange
}: {
  appearance: MobileAppearance;
  styles: ReturnType<typeof makeStyles>;
  standalone: boolean;
  weatherDisplayMode: MobileWeatherDisplayMode;
  autoDisplayOnRotate: boolean;
  onWeatherDisplayModeChange: (next: MobileWeatherDisplayMode) => void;
  onAutoDisplayOnRotateChange: (next: boolean) => void;
}) {
  const weatherChoices: Array<{ value: MobileWeatherDisplayMode; title: string; detail: string; icon: LocalFlightIconName }> = [
    { value: "passenger", title: englishCopy.weather.plainLanguage.label, detail: englishCopy.weather.plainLanguage.description, icon: "weather-partly-cloudy" },
    { value: "pilot", title: englishCopy.weather.aviationDetails.label, detail: englishCopy.weather.aviationDetails.description, icon: "windsock" },
    { value: "vatsim", title: englishCopy.weather.rawMetar.label, detail: englishCopy.weather.rawMetar.description, icon: "code-tags" }
  ];
  return (
    <View style={styles.panelContent}>
      <Text style={styles.panelIntro}>Choose how Board and fullscreen Display explain airport information on this device.</Text>
      <Text style={styles.panelSectionTitle}>Weather detail</Text>
      <View style={styles.choiceGroup}>
        {weatherChoices.map((choice) => {
          const selected = weatherDisplayMode === choice.value;
          return (
            <MotionPressable
              key={choice.value}
              style={[styles.appearanceChoice, selected && styles.appearanceChoiceSelected]}
              onPress={() => {
                hapticSelection();
                onWeatherDisplayModeChange(choice.value);
              }}
              {...accessibleButton({ label: `${choice.title}. ${choice.detail}`, selected })}
            >
              <LocalFlightIcon name={choice.icon} size={21} color={selected ? appearance.blue : appearance.textMuted} />
              <View style={styles.rowCopy}>
                <Text style={styles.rowTitle}>{choice.title}</Text>
                <Text style={styles.rowDetail}>{choice.detail}</Text>
              </View>
              <View style={[styles.radio, selected && styles.radioSelected]}>{selected ? <View style={styles.radioDot} /> : null}</View>
            </MotionPressable>
          );
        })}
      </View>
      <Text style={styles.panelSectionTitle}>Fullscreen Display</Text>
      <View style={styles.widgetSection}>
        <WidgetPreferenceRow
          title="Enter Display when this device rotates"
          detail="While Board is open, rotating this device to landscape enters Display. Rotating back exits only an automatically opened Display."
          value={autoDisplayOnRotate}
          onValueChange={onAutoDisplayOnRotateChange}
          appearance={appearance}
          styles={styles}
        />
      </View>
      <View style={styles.informationCard}>
        <Text style={styles.informationTitle}>{standalone ? "Standalone availability" : "Connected host availability"}</Text>
        <Text style={styles.informationBody}>
          {standalone
            ? [englishCopy.standalone.boardCadence, englishCopy.standalone.rowAvailability, englishCopy.standalone.cacheCaveat].join(" ")
            : "Board follows the update timing configured on your Local Flight host. Display pages advance every eight seconds unless paused."}
        </Text>
      </View>
    </View>
  );
}

function HostPanel({
  airportCode,
  connectionLabel,
  styles,
  onOpenAirport,
  onRerunSetup,
  onClose
}: {
  airportCode: string;
  connectionLabel: string;
  styles: ReturnType<typeof makeStyles>;
  onOpenAirport: () => void;
  onRerunSetup: () => void;
  onClose: () => void;
}) {
  return (
    <View style={styles.panelContent}>
      <Text style={styles.panelIntro}>Pairing and host controls appear here only for devices connected to a Local Flight host.</Text>
      <View style={styles.informationCard}>
        <Text style={styles.informationTitle}>{connectionLabel}</Text>
        <Text style={styles.informationBody}>{airportCode || "Airport not selected"} · Flight and display settings stay on the connected host.</Text>
      </View>
      <Pressable style={styles.primaryButton} onPress={() => { onClose(); onOpenAirport(); }} {...accessibleButton({ label: "Open airport and host settings" })}>
        <Text style={styles.primaryButtonText}>Airport & host settings</Text>
      </Pressable>
      <Pressable style={styles.secondaryButton} onPress={() => { onClose(); onRerunSetup(); }} {...accessibleButton({ label: "Pair this device with a different Local Flight host" })}>
        <Text style={styles.secondaryButtonText}>Review pairing</Text>
      </Pressable>
      <Text style={styles.disclaimer}>Matrix and physical display configuration remains host-owned and is never sent through widget or Live Activity extensions.</Text>
    </View>
  );
}

function RelayAccessPanel({
  styles,
  appearance,
  standalone,
  relayAccess,
  relayProtectionAvailable,
  onVerifyRelayAccess,
  onProtectRelayAccess
}: {
  styles: ReturnType<typeof makeStyles>;
  appearance: MobileAppearance;
  standalone: boolean;
  relayAccess: MobileRelayAccessSnapshot;
  relayProtectionAvailable: boolean;
  onVerifyRelayAccess: () => Promise<string | void> | string | void;
  onProtectRelayAccess: (email: string) => Promise<string>;
}) {
  const [email, setEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [message, setMessage] = useState("");
  const [verifying, setVerifying] = useState(false);
  const checking = relayAccess.state === "checking" || verifying;
  const statusTitle = relayAccess.state === "active_here"
    ? "Active on this phone"
    : relayAccess.state === "active_elsewhere"
      ? "Active on another main device"
      : relayAccess.state === "available"
        ? "Ready to use"
        : relayAccess.state === "suspended"
          ? "Access suspended"
          : relayAccess.state === "refunded"
            ? "Purchase refunded"
            : relayAccess.state === "revoked"
              ? "Access revoked"
              : relayAccess.state === "release_pending"
                ? "Freeing access is pending"
                : relayAccess.state === "retryable_unavailable"
                  ? "Check unavailable"
                  : checking
                    ? "Checking access"
                    : "Verification needed";
  const verifyLabel = relayAccess.state === "release_pending"
    ? "Retry freeing Relay Access"
    : Platform.OS === "android" && relayAccess.state === "verification_needed"
      ? "Get or restore Relay Access"
    : ["suspended", "refunded", "revoked", "retryable_unavailable"].includes(relayAccess.state)
      ? Platform.OS === "android" ? "Restore Relay Access" : "Restore included access"
      : Platform.OS === "android" ? "Verify Relay Access" : "Verify included access";
  const protect = async () => {
    if (sending || checking) return;
    if (!email.trim()) {
      setMessage("Enter an email address first.");
      return;
    }
    setSending(true);
    try {
      setMessage(await onProtectRelayAccess(email.trim()));
      setEmail("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The recovery link could not be requested.");
    } finally {
      setSending(false);
    }
  };
  const verify = async () => {
    if (checking) return;
    setVerifying(true);
    setMessage("");
    try {
      const result = await onVerifyRelayAccess();
      if (result) setMessage(result);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Relay Access could not be checked.");
    } finally {
      setVerifying(false);
    }
  };
  const hasVerifiedSummary = Boolean(relayAccess.licenseRef || relayAccess.lastSuccessfulCheckAt);
  const lastChecked = relayAccess.lastSuccessfulCheckAt
    ? new Date(relayAccess.lastSuccessfulCheckAt).toLocaleString()
    : "Not verified yet";
  return (
    <View style={styles.panelContent}>
      <Text style={styles.panelIntro}>{Platform.OS === "android"
        ? "Companion and VATSIM are free. The one-time Google Play Relay Access product powers one main device: this phone in real-flight Standalone mode or one Local Flight desktop."
        : "This paid app includes one portable Beacon Relay Access license. It can power one main device: this phone in Standalone mode or one Local Flight desktop. Companion follows its host and uses no additional place."}</Text>
      <View style={styles.informationCard}>
        <Text style={styles.informationTitle}>{statusTitle}</Text>
        <Text style={styles.informationBody}>{relayAccess.message}</Text>
        {hasVerifiedSummary ? (
          <>
            {relayAccess.sourceLabel ? <Text style={styles.informationBody}>Source: {relayAccess.sourceLabel}</Text> : null}
            {relayAccess.maskedKeyRef ? <Text style={styles.informationBody}>Reference: {relayAccess.maskedKeyRef}</Text> : null}
            <Text style={styles.informationBody}>Protection: {relayAccess.protectionEnabled ? "On" : "Not added"}</Text>
            {relayAccess.currentMainDeviceDescription ? <Text style={styles.informationBody}>Main device: {relayAccess.currentMainDeviceDescription}</Text> : null}
            <Text style={styles.informationBody}>Last verified: {lastChecked}</Text>
          </>
        ) : null}
      </View>
      <Text style={styles.informationBody}>{paidAppStoreLabel()} may ask you to sign in only after you choose the action below.</Text>
      <Pressable
        style={[styles.secondaryButton, checking && { opacity: 0.6 }]}
        disabled={checking}
        onPress={() => void verify()}
        {...accessibleButton({ label: checking ? "Checking Relay Access" : verifyLabel, disabled: checking, busy: checking })}
      >
        <Text style={styles.secondaryButtonText}>{checking ? "Checking…" : verifyLabel}</Text>
      </Pressable>
      <Text style={styles.informationTitle}>{relayAccess.protectionEnabled
        ? "Recovery and moving access"
        : Platform.OS === "android" ? "Protect Relay Access" : "Protect your included access"}</Text>
      {relayProtectionAvailable ? (
        <>
          <Text style={styles.informationBody}>
            {relayAccess.protectionEnabled
              ? "Request a fresh one-time email link to manage recovery or move Relay Access. No password or Beacon account is created."
              : "Email is optional and creates no account. Confirm it once to protect recovery and moving access between main devices."}
          </Text>
          <TextInput
            value={email}
            onChangeText={setEmail}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="email-address"
            textContentType="emailAddress"
            accessibilityLabel="Email for Relay Access protection and recovery"
            editable={!sending && !checking}
            returnKeyType="send"
            onSubmitEditing={() => void protect()}
            placeholder="you@example.com"
            placeholderTextColor={appearance.textDim}
            style={styles.relayEmailInput}
          />
          <Pressable
            style={[styles.primaryButton, (sending || checking) && { opacity: 0.6 }]}
            disabled={sending || checking}
            onPress={() => void protect()}
            {...accessibleButton({
              label: sending ? "Sending verification email" : relayAccess.protectionEnabled ? "Email a management link" : "Protect Relay Access",
              disabled: sending || checking,
              busy: sending
            })}
          >
            <Text style={styles.primaryButtonText}>{sending ? "Sending…" : relayAccess.protectionEnabled ? "Email a one-time link" : "Protect Relay Access"}</Text>
          </Pressable>
        </>
      ) : (
        <Text style={styles.informationBody}>Activate Relay Access on this phone in real-flight Standalone before adding an optional recovery email.</Text>
      )}
      {message ? <Text style={styles.panelIntro}>{message}</Text> : null}
      <Text style={styles.disclaimer}>{standalone
        ? "Moving Relay Access stops direct Standalone data here. LAN and Remote Companion continue through their desktop host."
        : Platform.OS === "android"
          ? "Remote Companion requires Relay Access on its desktop host. A Google Play Relay Access purchase on this phone cannot substitute for an unlicensed host."
          : "Remote Companion requires Relay Access on its desktop host. The access included with this phone cannot substitute for an unlicensed host."}</Text>
    </View>
  );
}

function AdvancedPanel({
  diagnosticsMode,
  widgetSnapshotLabel,
  onDiagnosticsModeChange,
  styles,
  appearance
}: {
  diagnosticsMode: MobileDiagnosticsMode;
  widgetSnapshotLabel: string;
  onDiagnosticsModeChange: (next: MobileDiagnosticsMode) => void;
  styles: ReturnType<typeof makeStyles>;
  appearance: MobileAppearance;
}) {
  const options: Array<{ value: MobileDiagnosticsMode; title: string; detail: string }> = [
    { value: "manual", title: "Manual reports only", detail: "Nothing is sent unless you choose to send a report." },
    { value: "auto", title: "Automatic crash reports", detail: "Send a sanitized crash signal when the app cannot continue." },
    { value: "auto_logs", title: "Automatic reports with context", detail: "Include a short sanitized diagnostic excerpt; never include tokens or personal aviation data." }
  ];
  return (
    <View style={styles.panelContent}>
      <Text style={styles.panelIntro}>Diagnostics are optional, sanitized, and kept away from everyday flight information.</Text>
      <View style={styles.choiceGroup}>
        {options.map((option) => {
          const selected = diagnosticsMode === option.value;
          return (
            <Pressable
              key={option.value}
              style={[styles.appearanceChoice, selected && styles.appearanceChoiceSelected]}
              onPress={() => onDiagnosticsModeChange(option.value)}
              {...accessibleButton({ label: `${option.title}. ${option.detail}`, selected })}
            >
              <LocalFlightIcon name="stethoscope" size={20} color={selected ? appearance.blue : appearance.textMuted} />
              <View style={styles.rowCopy}>
                <Text style={styles.rowTitle}>{option.title}</Text>
                <Text style={styles.rowDetail}>{option.detail}</Text>
              </View>
              <View style={[styles.radio, selected && styles.radioSelected]}>{selected ? <View style={styles.radioDot} /> : null}</View>
            </Pressable>
          );
        })}
      </View>
      <View style={styles.informationCard}>
        <Text style={styles.informationTitle}>Widget delivery</Text>
        <Text style={styles.informationBody}>{widgetSnapshotLabel}</Text>
      </View>
      <Text style={styles.disclaimer}>Technical identifiers shown here are sanitized. Local paths, activation tokens, provider payloads, and raw private logs are never displayed.</Text>
    </View>
  );
}

type WidgetPreviewPalette = {
  background: string;
  surface: string;
  text: string;
  muted: string;
  dim: string;
  line: string;
  sky: string;
  sea: string;
  amber: string;
  status: MobileAppearance["status"];
};

function resolveWidgetPreviewPalette(
  preference: MobileWidgetAppearance,
  appearance: MobileAppearance
): WidgetPreviewPalette {
  const dark = preference === "dark" || (preference === "system" && appearance.themeMode === "dark");
  if (dark) {
    return {
      background: "#08141D",
      surface: "#102330",
      text: "#F5F0E8",
      muted: "#A4B3BE",
      dim: "#738896",
      line: "#284352",
      sky: "#74B5DE",
      sea: "#59C1A5",
      amber: "#E4B454",
      status: {
        scheduled: "#74B5DE",
        boarding: "#59C1A5",
        delayed: "#E4B454",
        departed: "#59C1A5",
        cancelled: "#F07C62"
      }
    };
  }
  return {
    background: "#F5F1E8",
    surface: "#FFFDF8",
    text: "#132638",
    muted: "#536575",
    dim: "#70808C",
    line: "#D7D1C6",
    sky: "#2F6F9F",
    sea: "#1F6F61",
    amber: "#925D10",
    status: {
      scheduled: "#2F6F9F",
      boarding: "#1F6F61",
      delayed: "#925D10",
      departed: "#1F6F61",
      cancelled: "#A74732"
    }
  };
}

function WidgetFlightCard({
  flight,
  emptyLabel,
  palette,
  styles
}: {
  flight: WidgetFlightPreview | null;
  emptyLabel: string;
  palette: WidgetPreviewPalette;
  styles: ReturnType<typeof makeStyles>;
}) {
  if (!flight) {
    return (
      <View style={[styles.widgetEmpty, { backgroundColor: palette.surface }]}>
        <LocalFlightIcon name="pin-outline" size={22} color={palette.dim} />
        <Text style={[styles.widgetEmptyText, { color: palette.muted }]}>{emptyLabel}</Text>
      </View>
    );
  }
  const gate = [flight.terminal ? `Terminal ${flight.terminal}` : "", flight.gate ? `Gate ${flight.gate}` : ""]
    .filter(Boolean)
    .join(" · ");
  return (
    <View style={[styles.widgetFlight, { backgroundColor: palette.surface }]}>
      <View style={[styles.widgetPinnedAccent, { backgroundColor: palette.amber }]} />
      <Text style={[styles.widgetPinnedLabel, { color: palette.amber }]}>Pinned flight</Text>
      <View style={styles.widgetFlightLead}>
        <Text style={[styles.widgetFlightCode, { color: palette.text }]}>{flight.flightDisplay}</Text>
        <Text style={[styles.widgetTime, { color: palette.text }]}>{flight.displayTime}</Text>
      </View>
      <Text style={[styles.widgetRoute, { color: palette.text }]} numberOfLines={1}>{flight.routeName || flight.routeCode || "Route pending"}</Text>
      <View style={styles.widgetFlightFooter}>
        <Text style={[styles.widgetStatus, { color: palette.status[flight.statusTone] }]}>{flight.statusDisplay}</Text>
        {gate ? <Text style={[styles.widgetGate, { color: palette.muted }]}>{gate}</Text> : null}
      </View>
    </View>
  );
}

function WidgetAppearanceChoice({
  title,
  value,
  onChange,
  styles
}: {
  title: string;
  value: MobileWidgetAppearance;
  onChange: (next: MobileWidgetAppearance) => void;
  styles: ReturnType<typeof makeStyles>;
}) {
  return (
    <View style={styles.widgetAppearanceBlock}>
      <Text style={styles.widgetAppearanceTitle}>{title}</Text>
      <View style={styles.widgetAppearanceGroup}>
        {(["system", "light", "dark"] as const).map((choice) => {
          const selected = value === choice;
          const label = choice === "system" ? "Device" : choice === "light" ? "Light" : "Dark";
          return (
            <Pressable
              key={choice}
              style={[styles.widgetAppearanceButton, selected && styles.widgetAppearanceButtonSelected]}
              onPress={() => {
                hapticSelection();
                onChange(choice);
              }}
              {...accessibleButton({ label: `${title}: ${label}`, selected })}
            >
              <LocalFlightIcon
                name={choice === "system" ? "theme-light-dark" : choice === "light" ? "white-balance-sunny" : "weather-night"}
                size={16}
                color={selected ? styles.widgetAppearanceTextSelected.color as string : styles.widgetAppearanceText.color as string}
              />
              <Text style={[styles.widgetAppearanceText, selected && styles.widgetAppearanceTextSelected]}>{label}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

function WidgetWidePreview({
  preview,
  preferences,
  palette,
  styles
}: {
  preview: WidgetPreviewSnapshot;
  preferences: MobileWidgetPreferences;
  palette: WidgetPreviewPalette;
  styles: ReturnType<typeof makeStyles>;
}) {
  const pinned = preview.pinnedFlight && (
    (preview.view === "arrivals" && preview.pinnedFlight.direction === "arr") ||
    (preview.view === "departures" && preview.pinnedFlight.direction === "dep")
  ) ? preview.pinnedFlight : null;
  const flights = [
    ...(pinned ? [{ flight: pinned, pinned: true }] : []),
    ...preview.liveFlights
      .filter((flight) => !pinned || flight.id !== pinned.id)
      .map((flight) => ({ flight, pinned: false }))
  ].slice(0, preferences.mediumRowCount);
  return (
    <View style={[styles.widgetWidePreview, { backgroundColor: palette.background, borderColor: palette.line }]}>
      <View style={styles.widgetWideHeader}>
        <View style={styles.widgetWideAirportCopy}>
          <Text style={[styles.widgetWideAirport, { color: palette.text }]} numberOfLines={1}>{preview.airportName}</Text>
          <Text style={[styles.widgetWideDirection, { color: palette.sea }]}>{preview.airportCode} · {preview.view === "arrivals" ? "Arrivals" : "Departures"}</Text>
        </View>
        <Text style={[styles.widgetWideFreshness, { color: palette.dim }]} numberOfLines={1}>{preview.updatedLabel}</Text>
      </View>
      <View style={[styles.widgetWideHorizon, { backgroundColor: palette.sky }]} />
      {flights.length ? flights.map(({ flight, pinned: isPinned }) => {
        const info = preferences.showGateTerminal ? flight.gate || flight.terminal || "" : "";
        return (
          <View key={flight.id} style={[styles.widgetWideRow, { backgroundColor: palette.surface }]}>
            {isPinned ? <View style={[styles.widgetWidePinnedAccent, { backgroundColor: palette.amber }]} /> : null}
            <Text style={[styles.widgetWideTime, { color: palette.text }]}>{flight.displayTime}</Text>
            <View style={styles.widgetWideFlightCopy}>
              <Text style={[styles.widgetWideFlight, { color: palette.sky }]} numberOfLines={1}>{flight.flightDisplay}</Text>
              <Text style={[styles.widgetWideRoute, { color: palette.muted }]} numberOfLines={1}>{flight.routeName} · {flight.routeCode}</Text>
            </View>
            <View style={styles.widgetWideStatusCopy}>
              <Text style={[styles.widgetWideStatus, { color: palette.status[flight.statusTone] }]} numberOfLines={1}>{flight.statusDisplay}</Text>
              {info ? <Text style={[styles.widgetWideInfo, { color: palette.muted }]} numberOfLines={1}>{flight.gate ? `Gate ${info}` : `Terminal ${info}`}</Text> : null}
            </View>
          </View>
        );
      }) : (
        <View style={[styles.widgetWideEmpty, { backgroundColor: palette.surface }]}>
          <Text style={[styles.widgetEmptyText, { color: palette.muted }]}>Open Local Flight to prepare the latest Board.</Text>
        </View>
      )}
    </View>
  );
}

function WidgetPreferenceRow({
  title,
  detail,
  value,
  onValueChange,
  appearance,
  styles
}: {
  title: string;
  detail: string;
  value: boolean;
  onValueChange: (enabled: boolean) => void;
  appearance: MobileAppearance;
  styles: ReturnType<typeof makeStyles>;
}) {
  return (
    <View style={styles.widgetPreferenceRow}>
      <View style={styles.rowCopy}>
        <Text style={styles.rowTitle}>{title}</Text>
        <Text style={styles.rowDetail}>{detail}</Text>
      </View>
      <Switch
        value={value}
        onValueChange={(enabled) => {
          hapticSelection();
          onValueChange(enabled);
        }}
        trackColor={{ false: appearance.line, true: `${appearance.blue}80` }}
        thumbColor={value ? appearance.blue : appearance.textMuted}
        accessibilityLabel={title}
      />
    </View>
  );
}

function WidgetsPanel({
  preview,
  preferences,
  snapshotLabel,
  liveActivitySupported,
  refreshing,
  onRefresh,
  onPreferencesChange,
  appearance,
  styles
}: {
  preview: WidgetPreviewSnapshot;
  preferences: MobileWidgetPreferences;
  snapshotLabel: string;
  liveActivitySupported: boolean;
  refreshing: boolean;
  onRefresh: () => void;
  onPreferencesChange: (next: MobileWidgetPreferences) => void;
  appearance: MobileAppearance;
  styles: ReturnType<typeof makeStyles>;
}) {
  const update = (patch: Partial<MobileWidgetPreferences>) => onPreferencesChange({ ...preferences, ...patch });
  const previewPalette = resolveWidgetPreviewPalette(preferences.widgetAppearance, appearance);
  return (
    <View style={styles.panelContent}>
      <Text style={styles.panelIntro}>
        Widgets and Live Activity only read the bounded snapshot written by this app. They never contact a Local Flight host, relay, or aviation provider.
      </Text>

      <View style={[styles.widgetPreviewCard, { backgroundColor: previewPalette.background, borderColor: previewPalette.line }] }>
        <View style={styles.widgetPreviewHeader}>
          <View>
            <Text style={[styles.widgetEyebrow, { color: previewPalette.muted }]}>Small widget</Text>
            <Text style={[styles.widgetAirport, { color: previewPalette.text }]}>{preview.airportCode} · {preview.airportName}</Text>
          </View>
          <LocalFlightIcon name="widgets-outline" size={22} color={previewPalette.sky} />
        </View>
        <WidgetFlightCard
          flight={preview.pinnedFlight}
          emptyLabel="Pin a flight from Board to show it here."
          palette={previewPalette}
          styles={styles}
        />
        <Text style={[styles.widgetFreshness, { color: previewPalette.dim }]}>{preview.updatedLabel}</Text>
      </View>

      <WidgetWidePreview preview={preview} preferences={preferences} palette={previewPalette} styles={styles} />

      <View style={styles.widgetSection}>
        <Text style={styles.widgetSectionTitle}>Board widget</Text>
        <Text style={styles.widgetSectionBody}>Choose how many stable rows the medium or wide widget can show.</Text>
        <WidgetAppearanceChoice
          title="Home Screen widgets"
          value={preferences.widgetAppearance}
          onChange={(widgetAppearance) => update({ widgetAppearance })}
          styles={styles}
        />
        <View style={styles.rowCountGroup}>
          {([2, 3] as const).map((count) => {
            const selected = preferences.mediumRowCount === count;
            return (
              <Pressable
                key={count}
                style={[styles.rowCountButton, selected && styles.rowCountButtonSelected]}
                onPress={() => {
                  hapticSelection();
                  update({ mediumRowCount: count });
                }}
                {...accessibleButton({ label: `Show up to ${count} board rows`, selected })}
              >
                <Text style={[styles.rowCountText, selected && styles.rowCountTextSelected]}>{count} rows</Text>
              </Pressable>
            );
          })}
        </View>
        <WidgetPreferenceRow
          title="Show gate and terminal"
          detail="Only when Airline schedules supply them."
          value={preferences.showGateTerminal}
          onValueChange={(showGateTerminal) => update({ showGateTerminal })}
          appearance={appearance}
          styles={styles}
        />
        <WidgetPreferenceRow
          title="Background widget updates"
          detail="The app updates its private snapshot when the operating system permits background work."
          value={preferences.automaticRefresh}
          onValueChange={(automaticRefresh) => update({ automaticRefresh })}
          appearance={appearance}
          styles={styles}
        />
      </View>

      <View style={styles.widgetSection}>
        <View style={styles.widgetSectionHeading}>
          <LocalFlightIcon name="cellphone-text" size={21} color={appearance.green} />
          <Text style={styles.widgetSectionTitle}>Lock Screen flight</Text>
        </View>
        <Text style={styles.widgetSectionBody}>
          {liveActivitySupported
            ? preferences.liveActivityEnabled
              ? "Enabled for the flight you chose to show on the Lock Screen. It updates from the same app-written snapshot and never fetches on its own."
              : "From Board, choose “Pin & show on Lock Screen” for a flight. Starting it always requires that explicit action."
            : "Live Activity is unavailable on this device. Normal flight pinning and widgets still work."}
        </Text>
        <WidgetAppearanceChoice
          title="Lock Screen Live Activity"
          value={preferences.liveActivityAppearance}
          onChange={(liveActivityAppearance) => update({ liveActivityAppearance })}
          styles={styles}
        />
        <Text style={styles.widgetAppearanceNote}>
          On iPhones with Dynamic Island, touch and hold the flight to expand it. A tap opens its details in Local Flight. Dynamic Island keeps Apple’s system-dark treatment for legibility.
        </Text>
        {liveActivitySupported && preferences.liveActivityEnabled ? (
          <Pressable
            style={styles.secondaryButton}
            onPress={() => {
              hapticLight();
              update({ liveActivityEnabled: false });
            }}
            {...accessibleButton({ label: "Turn off pinned-flight Live Activity" })}
          >
            <Text style={styles.secondaryButtonText}>Turn off Live Activity</Text>
          </Pressable>
        ) : null}
      </View>

      <Text style={styles.widgetSnapshotLabel}>{snapshotLabel}</Text>
      <Pressable
        style={[styles.primaryButton, refreshing && styles.buttonDisabled]}
        disabled={refreshing}
        onPress={() => {
          hapticLight();
          onRefresh();
        }}
        {...accessibleButton({ label: refreshing ? "Refreshing widget snapshot" : "Refresh widget snapshot" })}
      >
        <LocalFlightIcon name="refresh" size={19} color={appearance.bg} />
        <Text style={styles.primaryButtonText}>{refreshing ? "Refreshing…" : "Refresh widget now"}</Text>
      </Pressable>
    </View>
  );
}

function PanelSheet({
  panel,
  appearance,
  styles,
  standalone,
  airportCode,
  connectionLabel,
  supportPurchases,
  widgetPreview,
  widgetPreferences,
  widgetSnapshotLabel,
  liveActivitySupported,
  weatherDisplayMode,
  autoDisplayOnRotate,
  diagnosticsMode,
  refreshing,
  onRefreshWidget,
  onWidgetPreferencesChange,
  onWeatherDisplayModeChange,
  onAutoDisplayOnRotateChange,
  onDiagnosticsModeChange,
  onOpenAirport,
  onRerunSetup,
  relayAccess,
  relayProtectionAvailable,
  onVerifyRelayAccess,
  onProtectRelayAccess,
  onClose
}: {
  panel: Exclude<MorePanel, null>;
  appearance: MobileAppearance;
  styles: ReturnType<typeof makeStyles>;
  standalone: boolean;
  airportCode: string;
  connectionLabel: string;
  supportPurchases: SupportPurchaseController;
  widgetPreview: WidgetPreviewSnapshot;
  widgetPreferences: MobileWidgetPreferences;
  widgetSnapshotLabel: string;
  liveActivitySupported: boolean;
  weatherDisplayMode: MobileWeatherDisplayMode;
  autoDisplayOnRotate: boolean;
  diagnosticsMode: MobileDiagnosticsMode;
  refreshing: boolean;
  onRefreshWidget: () => void;
  onWidgetPreferencesChange: (next: MobileWidgetPreferences) => void;
  onWeatherDisplayModeChange: (next: MobileWeatherDisplayMode) => void;
  onAutoDisplayOnRotateChange: (next: boolean) => void;
  onDiagnosticsModeChange: (next: MobileDiagnosticsMode) => void;
  onOpenAirport: () => void;
  onRerunSetup: () => void;
  relayAccess: MobileRelayAccessSnapshot;
  relayProtectionAvailable: boolean;
  onVerifyRelayAccess: () => Promise<string | void> | string | void;
  onProtectRelayAccess: (email: string) => Promise<string>;
  onClose: () => void;
}) {
  const title = panel === "appearance"
    ? "Appearance"
    : panel === "board"
      ? "Board & Display"
    : panel === "widgets"
      ? "Widgets & Live Activity"
      : panel === "host"
        ? "Host & Displays"
        : panel === "relay"
          ? "Relay Access"
        : panel === "help"
          ? "Help & Privacy"
          : panel === "support"
            ? "Support Local Flight"
          : "Advanced diagnostics";
  return (
    <Modal visible animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <SafeAreaView style={styles.sheetSafe}>
        <View style={styles.sheetHeader}>
          <Text style={styles.sheetTitle}>{title}</Text>
          <Pressable style={styles.closeButton} onPress={onClose} {...accessibleButton({ label: `Close ${title}` })}>
            <LocalFlightIcon name="close" size={21} color={appearance.text} />
          </Pressable>
        </View>
        {panel === "appearance" ? (
          <ScrollView>
            <AppearancePanel
              appearance={appearance}
              styles={styles}
            />
          </ScrollView>
        ) : panel === "board" ? (
          <ScrollView showsVerticalScrollIndicator={false}>
            <BoardDisplayPanel
              appearance={appearance}
              styles={styles}
              standalone={standalone}
              weatherDisplayMode={weatherDisplayMode}
              autoDisplayOnRotate={autoDisplayOnRotate}
              onWeatherDisplayModeChange={onWeatherDisplayModeChange}
              onAutoDisplayOnRotateChange={onAutoDisplayOnRotateChange}
            />
          </ScrollView>
        ) : panel === "widgets" ? (
          <ScrollView showsVerticalScrollIndicator={false}>
            <WidgetsPanel
              preview={widgetPreview}
              preferences={widgetPreferences}
              snapshotLabel={widgetSnapshotLabel}
              liveActivitySupported={liveActivitySupported}
              refreshing={refreshing}
              onRefresh={onRefreshWidget}
              onPreferencesChange={onWidgetPreferencesChange}
              appearance={appearance}
              styles={styles}
            />
          </ScrollView>
        ) : panel === "help" ? (
          <ScrollView><HelpPanel styles={styles} /></ScrollView>
        ) : panel === "support" ? (
          <ScrollView showsVerticalScrollIndicator={false}>
            <SupportPurchaseContent controller={supportPurchases} />
          </ScrollView>
        ) : panel === "host" ? (
          <ScrollView showsVerticalScrollIndicator={false}>
            <HostPanel
              airportCode={airportCode}
              connectionLabel={connectionLabel}
              styles={styles}
              onOpenAirport={onOpenAirport}
              onRerunSetup={onRerunSetup}
              onClose={onClose}
            />
          </ScrollView>
        ) : panel === "relay" ? (
          <ScrollView showsVerticalScrollIndicator={false}>
            <RelayAccessPanel
              styles={styles}
              appearance={appearance}
              standalone={standalone}
              relayAccess={relayAccess}
              relayProtectionAvailable={relayProtectionAvailable}
              onVerifyRelayAccess={onVerifyRelayAccess}
              onProtectRelayAccess={onProtectRelayAccess}
            />
          </ScrollView>
        ) : (
          <ScrollView showsVerticalScrollIndicator={false}>
            <AdvancedPanel
              diagnosticsMode={diagnosticsMode}
              widgetSnapshotLabel={widgetSnapshotLabel}
              onDiagnosticsModeChange={onDiagnosticsModeChange}
              styles={styles}
              appearance={appearance}
            />
          </ScrollView>
        )}
      </SafeAreaView>
    </Modal>
  );
}

export function MoreScreenV2(props: MoreScreenV2Props) {
  const { appearance } = useMobileTheme();
  const styles = useMemo(() => makeStyles(appearance, props.layoutClass), [appearance, props.layoutClass]);
  const [panel, setPanel] = useState<MorePanel>(null);
  const expanded = props.layoutClass === "expanded" || props.layoutClass === "large";
  const includedPrefix = Platform.OS === "android" ? "Relay Access" : "Included access";
  const relayDetail = props.relayAccess.state === "active_here"
    ? "Active on this device · recovery and transfers"
    : props.relayAccess.state === "active_elsewhere"
      ? `Active on ${props.relayAccess.currentMainDeviceDescription || "another main device"}`
      : props.relayAccess.state === "available"
        ? `${includedPrefix} ready for a main device`
        : props.relayAccess.state === "release_pending"
          ? "Freeing access from this phone is pending"
          : props.relayAccess.state === "suspended"
            ? `${includedPrefix} is suspended`
            : props.relayAccess.state === "refunded"
              ? "Store purchase was refunded"
              : props.relayAccess.state === "revoked"
                ? `${includedPrefix} was revoked`
                : props.relayAccess.state === "retryable_unavailable"
                  ? "Verification unavailable · explicit retry"
                  : `${includedPrefix} · verification and recovery`;

  useEffect(() => {
    if (props.requestedPanel) setPanel(props.requestedPanel);
  }, [props.panelRequestKey, props.requestedPanel]);

  useEffect(() => {
    if (props.dismissRequestKey) setPanel(null);
  }, [props.dismissRequestKey]);

  return (
    <>
      <ScrollView
        contentContainerStyle={[styles.content, { paddingBottom: props.contentPaddingBottom }]}
        contentInsetAdjustmentBehavior={props.nativeNavigation ? "automatic" : "never"}
        refreshControl={<RefreshControl refreshing={props.refreshing} tintColor={appearance.blue} onRefresh={props.onRefresh} />}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.hero}>
          <BrandWordmark color={appearance.text} size={expanded ? 22 : 19}>Local Flight</BrandWordmark>
          <Text style={styles.title}>More</Text>
          <Text style={styles.subtitle}>Settings stay organized around what you want to do, with technical detail kept out of the way.</Text>
        </View>

        <MotionPressable
          style={styles.connectionCard}
          interactiveStyle={styles.connectionCardInteractive}
          onPress={() => {
            hapticSelection();
            props.onOpenAirport();
          }}
          {...accessibleButton({ label: `Airport and connection. ${props.airportName}, ${props.airportCode}, ${props.connectionLabel}. Change settings.` })}
        >
          <View style={styles.connectionIcon}>
            <LocalFlightIcon name={props.standalone ? "cellphone-marker" : "access-point-network"} size={23} color={appearance.green} />
          </View>
          <View style={styles.rowCopy}>
            <Text style={styles.connectionEyebrow}>Airport & Connection</Text>
            <Text style={styles.connectionAirport}>{props.airportName}</Text>
            <Text style={styles.connectionMeta}>{props.airportCode} · {props.connectionLabel}</Text>
          </View>
          <View style={styles.changeButton}>
            <Text style={styles.changeText}>Change</Text>
          </View>
        </MotionPressable>

        <Text style={styles.groupTitle}>This device</Text>
        <View style={styles.group}>
          <SettingsRow icon="palette-outline" title="Appearance" detail="Device setting, warm light or midnight dark" onPress={() => setPanel("appearance")} appearance={appearance} styles={styles} />
          <View style={styles.groupSeparator} />
          <SettingsRow icon="monitor-dashboard" title="Board & Display" detail="Weather detail and fullscreen Board behavior" onPress={() => setPanel("board")} appearance={appearance} styles={styles} />
          <View style={styles.groupSeparator} />
          <SettingsRow icon="widgets-outline" title="Widgets & Live Activity" detail="Pinned flight and bounded board snapshots" onPress={() => setPanel("widgets")} appearance={appearance} styles={styles} />
        </View>

        <Text style={styles.groupTitle}>Local Flight</Text>
        <View style={styles.group}>
          {!props.standalone ? (
            <>
              <SettingsRow icon="monitor-dashboard" title="Host & Displays" detail="Pairing, Matrix and connected displays" onPress={() => setPanel("host")} appearance={appearance} styles={styles} />
              <View style={styles.groupSeparator} />
            </>
          ) : null}
          <SettingsRow
            icon="key-variant"
            title="Relay Access"
            detail={relayDetail}
            onPress={() => setPanel("relay")}
            appearance={appearance}
            styles={styles}
          />
          <View style={styles.groupSeparator} />
          <SettingsRow icon="lifebuoy" title="Help & Privacy" detail="Plain-language guidance and privacy choices" onPress={() => setPanel("help")} appearance={appearance} styles={styles} />
          <View style={styles.groupSeparator} />
          <SettingsRow icon="stethoscope" title="Advanced diagnostics" detail="Diagnostic preferences and sanitized technical context" onPress={() => setPanel("advanced")} appearance={appearance} styles={styles} />
        </View>

        <MotionPressable
          style={styles.setupButton}
          onPress={() => {
            hapticLight();
            props.onRerunSetup();
          }}
          {...accessibleButton({ label: "Change how this device uses Local Flight" })}
        >
          <Text style={styles.setupButtonText}>Change setup on this device</Text>
        </MotionPressable>

        <MotionPressable
          style={styles.supportFooter}
          interactiveStyle={styles.supportFooterInteractive}
          onPress={() => {
            hapticSelection();
            setPanel("support");
          }}
          {...accessibleButton({
            label: "Support Local Flight",
            hint: "Opens optional one-time support choices. They unlock nothing."
          })}
        >
          <LocalFlightIcon name="heart-outline" size={16} color={appearance.textDim} />
          <View style={styles.supportFooterCopy}>
            <Text style={styles.supportFooterTitle}>Support Local Flight</Text>
            <Text style={styles.supportFooterDetail}>Optional one-time support · unlocks nothing</Text>
          </View>
          <LocalFlightIcon name="chevron-right" size={17} color={appearance.textDim} />
        </MotionPressable>
      </ScrollView>

      {panel ? (
        <PanelSheet
          panel={panel}
          appearance={appearance}
          styles={styles}
          standalone={props.standalone}
          airportCode={props.airportCode}
          connectionLabel={props.connectionLabel}
          supportPurchases={props.supportPurchases}
          widgetPreview={props.widgetPreview}
          widgetPreferences={props.widgetPreferences}
          widgetSnapshotLabel={props.widgetSnapshotLabel}
          liveActivitySupported={props.liveActivitySupported}
          weatherDisplayMode={props.weatherDisplayMode}
          autoDisplayOnRotate={props.autoDisplayOnRotate}
          diagnosticsMode={props.diagnosticsMode}
          refreshing={props.widgetRefreshing}
          onRefreshWidget={props.onRefreshWidget}
          onWidgetPreferencesChange={props.onWidgetPreferencesChange}
          onWeatherDisplayModeChange={props.onWeatherDisplayModeChange}
          onAutoDisplayOnRotateChange={props.onAutoDisplayOnRotateChange}
          onDiagnosticsModeChange={props.onDiagnosticsModeChange}
          onOpenAirport={props.onOpenAirport}
          onRerunSetup={props.onRerunSetup}
          relayAccess={props.relayAccess}
          relayProtectionAvailable={props.relayProtectionAvailable}
          onVerifyRelayAccess={props.onVerifyRelayAccess}
          onProtectRelayAccess={props.onProtectRelayAccess}
          onClose={() => setPanel(null)}
        />
      ) : null}
    </>
  );
}

function makeStyles(a: MobileAppearance, layoutClass: LayoutWidthClass) {
  const expanded = layoutClass === "expanded" || layoutClass === "large";
  return StyleSheet.create({
    content: { width: "100%", maxWidth: 980, alignSelf: "center", paddingHorizontal: expanded ? 30 : 16, paddingTop: expanded ? 27 : 18 },
    hero: { marginBottom: 19 },
    title: { color: a.text, fontSize: expanded ? 34 : 29, lineHeight: expanded ? 41 : 35, fontWeight: "700", marginTop: 13 },
    subtitle: { color: a.textMuted, fontSize: 15, lineHeight: 21, maxWidth: 640, marginTop: 6 },
    connectionCard: { minHeight: 82, flexDirection: "row", alignItems: "center", gap: 13, backgroundColor: a.shell, paddingHorizontal: 15, paddingVertical: 13, borderRadius: 21, marginBottom: 24, overflow: "hidden" },
    connectionCardInteractive: { backgroundColor: `${a.blue}0D` },
    connectionIcon: { width: 45, height: 45, borderRadius: 15, alignItems: "center", justifyContent: "center", backgroundColor: `${a.green}12` },
    rowCopy: { flex: 1, minWidth: 0 },
    connectionEyebrow: { color: a.textDim, fontSize: 11, fontWeight: "600", marginBottom: 3 },
    connectionAirport: { color: a.text, fontSize: 16, fontWeight: "700" },
    connectionMeta: { color: a.textMuted, fontSize: 13, marginTop: 4 },
    changeButton: { minHeight: 44, justifyContent: "center", paddingHorizontal: 12 },
    changeText: { color: a.blue, fontSize: 14, fontWeight: "700" },
    groupTitle: { color: a.textMuted, fontSize: 13, fontWeight: "600", marginLeft: 5, marginBottom: 8, marginTop: 3 },
    group: { borderRadius: 21, backgroundColor: a.shell, overflow: "hidden", marginBottom: 22 },
    settingsRow: { minHeight: 76, flexDirection: "row", alignItems: "center", gap: 13, paddingHorizontal: 14, paddingVertical: 11 },
    rowFocused: { backgroundColor: `${a.blue}0D` },
    rowPressed: { backgroundColor: `${a.blue}14` },
    rowIcon: { width: 43, height: 43, alignItems: "center", justifyContent: "center", borderRadius: 14, backgroundColor: `${a.blue}10` },
    rowTitle: { color: a.text, fontSize: 15, fontWeight: "600" },
    rowDetail: { color: a.textMuted, fontSize: 12, lineHeight: 17, marginTop: 3 },
    groupSeparator: { height: StyleSheet.hairlineWidth, backgroundColor: a.lineSoft, marginLeft: 70 },
    setupButton: { minHeight: 48, alignItems: "center", justifyContent: "center", borderRadius: 16, backgroundColor: a.lineSoft, marginTop: 2 },
    setupButtonText: { color: a.textMuted, fontSize: 14, fontWeight: "600" },
    supportFooter: { minHeight: 62, flexDirection: "row", alignItems: "center", gap: 11, paddingHorizontal: 8, marginTop: 17, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: a.lineSoft },
    supportFooterInteractive: { backgroundColor: `${a.blue}08` },
    supportFooterCopy: { flex: 1, minWidth: 0 },
    supportFooterTitle: { color: a.textMuted, fontSize: 14, fontWeight: "600" },
    supportFooterDetail: { color: a.textDim, fontSize: 12, lineHeight: 16, marginTop: 2 },
    sheetSafe: { flex: 1, backgroundColor: a.bg },
    sheetHeader: { height: 60, flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 18, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: a.line },
    sheetTitle: { color: a.text, fontSize: 17, fontWeight: "700" },
    closeButton: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: 15, backgroundColor: a.lineSoft },
    panelContent: { padding: 20, width: "100%", maxWidth: 760, alignSelf: "center" },
    panelIntro: { color: a.textMuted, fontSize: 14, lineHeight: 20 },
    relayEmailInput: { minHeight: 50, color: a.text, backgroundColor: a.shell, borderColor: a.line, borderWidth: StyleSheet.hairlineWidth, borderRadius: 16, paddingHorizontal: 15, marginTop: 14 },
    choiceGroup: { borderRadius: 19, backgroundColor: a.shell, overflow: "hidden", marginTop: 18 },
    appearanceChoice: { minHeight: 76, flexDirection: "row", alignItems: "center", gap: 13, paddingHorizontal: 15, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: a.lineSoft },
    appearanceChoiceSelected: { backgroundColor: `${a.blue}0F` },
    radio: { width: 22, height: 22, alignItems: "center", justifyContent: "center", borderRadius: 12, borderWidth: 1.5, borderColor: a.line },
    radioSelected: { borderColor: a.blue },
    radioDot: { width: 11, height: 11, borderRadius: 6, backgroundColor: a.blue },
    switchRow: { minHeight: 78, flexDirection: "row", alignItems: "center", gap: 15, paddingHorizontal: 15, borderRadius: 19, backgroundColor: a.shell, marginTop: 14 },
    panelSectionTitle: { color: a.text, fontSize: 17, fontWeight: "700", marginTop: 24 },
    panelSectionBody: { color: a.textMuted, fontSize: 14, lineHeight: 20, marginTop: 4 },
    informationCard: { borderRadius: 19, backgroundColor: a.shell, padding: 17, marginTop: 18 },
    informationTitle: { color: a.text, fontSize: 16, fontWeight: "700" },
    informationBody: { color: a.textMuted, fontSize: 14, lineHeight: 21, marginTop: 5 },
    widgetPreviewCard: { borderRadius: 24, backgroundColor: a.shell, borderWidth: 1, padding: 17, marginTop: 18, overflow: "hidden" },
    widgetPreviewHeader: { flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", gap: 12 },
    widgetEyebrow: { color: a.textMuted, fontSize: 12, fontWeight: "600" },
    widgetAirport: { color: a.text, fontSize: 14, fontWeight: "700", marginTop: 4, maxWidth: 560 },
    widgetEmpty: { minHeight: 100, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10, borderRadius: 18, backgroundColor: a.row, marginTop: 14, paddingHorizontal: 18 },
    widgetEmptyText: { color: a.textMuted, fontSize: 14, lineHeight: 20, flexShrink: 1 },
    widgetFlight: { borderRadius: 18, backgroundColor: a.row, padding: 15, marginTop: 14, overflow: "hidden" },
    widgetPinnedAccent: { position: "absolute", top: 0, bottom: 0, left: 0, width: 4 },
    widgetPinnedLabel: { fontSize: 11, fontWeight: "700", marginBottom: 7 },
    widgetFlightLead: { flexDirection: "row", alignItems: "baseline", justifyContent: "space-between", gap: 14 },
    widgetTime: { color: a.text, fontFamily: a.mono, fontSize: 22, fontWeight: "700" },
    widgetFlightCode: { color: a.text, fontFamily: a.mono, fontSize: 16, fontWeight: "700" },
    widgetRoute: { color: a.text, fontSize: 15, fontWeight: "600", marginTop: 12 },
    widgetFlightFooter: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 12, marginTop: 10 },
    widgetStatus: { fontSize: 12, fontWeight: "800" },
    widgetGate: { color: a.textMuted, fontSize: 12, fontWeight: "600", textAlign: "right", flexShrink: 1 },
    widgetFreshness: { color: a.textDim, fontSize: 12, marginTop: 10 },
    widgetWidePreview: { borderRadius: 24, borderWidth: 1, padding: 14, marginTop: 14, gap: 7, overflow: "hidden" },
    widgetWideHeader: { flexDirection: "row", alignItems: "center", gap: 12 },
    widgetWideAirportCopy: { flex: 1, minWidth: 0 },
    widgetWideAirport: { fontSize: 15, lineHeight: 19, fontWeight: "700" },
    widgetWideDirection: { fontSize: 11, lineHeight: 15, fontWeight: "700", marginTop: 2 },
    widgetWideFreshness: { fontSize: 11, maxWidth: 150, textAlign: "right" },
    widgetWideHorizon: { height: 3, width: 52, borderRadius: 999, opacity: 0.7 },
    widgetWideRow: { minHeight: 54, borderRadius: 16, flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 11, paddingVertical: 8, overflow: "hidden" },
    widgetWidePinnedAccent: { position: "absolute", top: 0, bottom: 0, left: 0, width: 4 },
    widgetWideTime: { width: 50, fontFamily: a.mono, fontSize: 14, fontWeight: "700" },
    widgetWideFlightCopy: { flex: 1, minWidth: 0 },
    widgetWideFlight: { fontFamily: a.mono, fontSize: 13, fontWeight: "700" },
    widgetWideRoute: { fontSize: 11, lineHeight: 15, marginTop: 1 },
    widgetWideStatusCopy: { width: 104, alignItems: "flex-end" },
    widgetWideStatus: { fontSize: 11, lineHeight: 15, fontWeight: "800", textAlign: "right" },
    widgetWideInfo: { fontSize: 10, lineHeight: 14, marginTop: 2, textAlign: "right" },
    widgetWideEmpty: { minHeight: 70, borderRadius: 16, justifyContent: "center", paddingHorizontal: 16 },
    widgetSection: { borderRadius: 21, backgroundColor: a.shell, padding: 17, marginTop: 14 },
    widgetSectionHeading: { flexDirection: "row", alignItems: "center", gap: 9 },
    widgetSectionTitle: { color: a.text, fontSize: 17, fontWeight: "700" },
    widgetSectionBody: { color: a.textMuted, fontSize: 14, lineHeight: 20, marginTop: 5 },
    rowCountGroup: { flexDirection: "row", gap: 9, marginTop: 14, marginBottom: 4 },
    rowCountButton: { minHeight: 44, minWidth: 96, alignItems: "center", justifyContent: "center", borderRadius: 15, backgroundColor: a.lineSoft },
    rowCountButtonSelected: { backgroundColor: `${a.blue}18` },
    rowCountText: { color: a.textMuted, fontSize: 14, fontWeight: "700" },
    rowCountTextSelected: { color: a.blue },
    widgetAppearanceBlock: { marginTop: 16 },
    widgetAppearanceTitle: { color: a.text, fontSize: 14, lineHeight: 19, fontWeight: "700", marginBottom: 8 },
    widgetAppearanceGroup: { flexDirection: "row", gap: 7 },
    widgetAppearanceButton: { flex: 1, minHeight: 44, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, borderRadius: 14, backgroundColor: a.lineSoft, paddingHorizontal: 8 },
    widgetAppearanceButtonSelected: { backgroundColor: `${a.blue}18`, borderWidth: 1, borderColor: `${a.blue}55` },
    widgetAppearanceText: { color: a.textMuted, fontSize: 12, fontWeight: "700" },
    widgetAppearanceTextSelected: { color: a.blue },
    widgetAppearanceNote: { color: a.textDim, fontSize: 11, lineHeight: 16, marginTop: 8 },
    widgetPreferenceRow: { minHeight: 75, flexDirection: "row", alignItems: "center", gap: 15, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: a.lineSoft, marginTop: 10, paddingTop: 10 },
    secondaryButton: { minHeight: 46, alignItems: "center", justifyContent: "center", alignSelf: "flex-start", borderRadius: 15, backgroundColor: a.lineSoft, paddingHorizontal: 16, marginTop: 14 },
    secondaryButtonText: { color: a.text, fontSize: 14, fontWeight: "700" },
    widgetSnapshotLabel: { color: a.textDim, fontSize: 12, lineHeight: 18, marginTop: 16 },
    primaryButton: { minHeight: 50, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 9, borderRadius: 17, backgroundColor: a.blue, marginTop: 11 },
    primaryButtonText: { color: a.bg, fontSize: 15, fontWeight: "800" },
    buttonDisabled: { opacity: 0.55 },
    helpCard: { borderRadius: 20, backgroundColor: a.shell, padding: 18, marginTop: 18 },
    helpTitle: { color: a.text, fontSize: 18, fontWeight: "700" },
    helpBody: { color: a.textMuted, fontSize: 14, lineHeight: 20, marginTop: 5, marginBottom: 11 },
    linkButton: { minHeight: 48, flexDirection: "row", alignItems: "center", justifyContent: "space-between", borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: a.lineSoft },
    linkText: { color: a.blue, fontSize: 14, fontWeight: "600" },
    disclaimer: { color: a.textDim, fontSize: 12, lineHeight: 18, marginTop: 18 }
  });
}
