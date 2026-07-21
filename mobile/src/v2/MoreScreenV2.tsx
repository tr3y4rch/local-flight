import { useEffect, useMemo, useState } from "react";
import {
  Linking,
  Modal,
  Pressable,
  RefreshControl,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Switch,
  View
} from "react-native";

import { accessibleButton } from "../accessibility/mobileA11y";
import { englishCopy } from "../content/en";
import { BrandWordmark } from "../components/Brand";
import { MotionPressable } from "../components/MotionPressable";
import { V2Text as Text } from "../components/V2Text";
import type { WidgetFlightPreview, WidgetPreviewSnapshot } from "../domain/widgets";
import { SupportPurchaseContent } from "../iap/SupportPurchaseContent";
import type { SupportPurchaseController } from "../iap/types";
import type { MobileDiagnosticsMode, MobileWeatherDisplayMode, MobileWidgetPreferences } from "../storage/settings";
import { LocalFlightIcon, type LocalFlightIconName } from "../theme/icons";
import { useMobileTheme } from "../theme/runtime";
import type { MobileAppearance, MobileThemePreference } from "../theme/tokens";
import { hapticLight, hapticSelection } from "../utils/haptics";
import type { LayoutWidthClass } from "../utils/layout";

export type MorePanel = "appearance" | "board" | "widgets" | "host" | "help" | "advanced" | "support" | null;

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
  diagnosticsMode: MobileDiagnosticsMode;
  requestedPanel?: Exclude<MorePanel, null>;
  panelRequestKey?: number;
  dismissRequestKey?: number;
  onRefresh: () => void;
  onRefreshWidget: () => void;
  onWidgetPreferencesChange: (next: MobileWidgetPreferences) => void;
  onWeatherDisplayModeChange: (next: MobileWeatherDisplayMode) => void;
  onDiagnosticsModeChange: (next: MobileDiagnosticsMode) => void;
  onOpenAirport: () => void;
  onRerunSetup: () => void;
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
  onWeatherDisplayModeChange
}: {
  appearance: MobileAppearance;
  styles: ReturnType<typeof makeStyles>;
  standalone: boolean;
  weatherDisplayMode: MobileWeatherDisplayMode;
  onWeatherDisplayModeChange: (next: MobileWeatherDisplayMode) => void;
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

function AdvancedPanel({
  diagnosticsMode,
  onDiagnosticsModeChange,
  styles,
  appearance
}: {
  diagnosticsMode: MobileDiagnosticsMode;
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
      <Text style={styles.disclaimer}>Technical identifiers shown here are sanitized. Local paths, activation tokens, provider payloads, and raw private logs are never displayed.</Text>
    </View>
  );
}

function WidgetFlightCard({
  flight,
  emptyLabel,
  appearance,
  styles
}: {
  flight: WidgetFlightPreview | null;
  emptyLabel: string;
  appearance: MobileAppearance;
  styles: ReturnType<typeof makeStyles>;
}) {
  if (!flight) {
    return (
      <View style={styles.widgetEmpty}>
        <LocalFlightIcon name="pin-outline" size={22} color={appearance.textDim} />
        <Text style={styles.widgetEmptyText}>{emptyLabel}</Text>
      </View>
    );
  }
  const gate = [flight.terminal ? `Terminal ${flight.terminal}` : "", flight.gate ? `Gate ${flight.gate}` : ""]
    .filter(Boolean)
    .join(" · ");
  return (
    <View style={styles.widgetFlight}>
      <View style={styles.widgetFlightLead}>
        <Text style={styles.widgetTime}>{flight.displayTime}</Text>
        <Text style={styles.widgetFlightCode}>{flight.flightDisplay}</Text>
      </View>
      <Text style={styles.widgetRoute} numberOfLines={1}>{flight.routeName || flight.routeCode || "Route pending"}</Text>
      <View style={styles.widgetFlightFooter}>
        <Text style={[styles.widgetStatus, { color: appearance.status[flight.statusTone] }]}>{flight.statusDisplay}</Text>
        {gate ? <Text style={styles.widgetGate}>{gate}</Text> : null}
      </View>
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
  return (
    <View style={styles.panelContent}>
      <Text style={styles.panelIntro}>
        Widgets and Live Activity only read the bounded snapshot written by this app. They never contact a Local Flight host, relay, or aviation provider.
      </Text>

      <View style={styles.widgetPreviewCard}>
        <View style={styles.widgetPreviewHeader}>
          <View>
            <Text style={styles.widgetEyebrow}>Small widget · pinned flight</Text>
            <Text style={styles.widgetAirport}>{preview.airportCode} · {preview.airportName}</Text>
          </View>
          <LocalFlightIcon name="widgets-outline" size={22} color={appearance.blue} />
        </View>
        <WidgetFlightCard
          flight={preview.pinnedFlight}
          emptyLabel="Pin a flight from Board to show it here."
          appearance={appearance}
          styles={styles}
        />
        <Text style={styles.widgetFreshness}>{preview.updatedLabel}</Text>
      </View>

      <View style={styles.widgetSection}>
        <Text style={styles.widgetSectionTitle}>Board widget</Text>
        <Text style={styles.widgetSectionBody}>Choose how many stable rows the medium or wide widget can show.</Text>
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
  diagnosticsMode,
  refreshing,
  onRefreshWidget,
  onWidgetPreferencesChange,
  onWeatherDisplayModeChange,
  onDiagnosticsModeChange,
  onOpenAirport,
  onRerunSetup,
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
  diagnosticsMode: MobileDiagnosticsMode;
  refreshing: boolean;
  onRefreshWidget: () => void;
  onWidgetPreferencesChange: (next: MobileWidgetPreferences) => void;
  onWeatherDisplayModeChange: (next: MobileWeatherDisplayMode) => void;
  onDiagnosticsModeChange: (next: MobileDiagnosticsMode) => void;
  onOpenAirport: () => void;
  onRerunSetup: () => void;
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
              onWeatherDisplayModeChange={onWeatherDisplayModeChange}
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
        ) : (
          <ScrollView showsVerticalScrollIndicator={false}>
            <AdvancedPanel
              diagnosticsMode={diagnosticsMode}
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
          diagnosticsMode={props.diagnosticsMode}
          refreshing={props.widgetRefreshing}
          onRefreshWidget={props.onRefreshWidget}
          onWidgetPreferencesChange={props.onWidgetPreferencesChange}
          onWeatherDisplayModeChange={props.onWeatherDisplayModeChange}
          onDiagnosticsModeChange={props.onDiagnosticsModeChange}
          onOpenAirport={props.onOpenAirport}
          onRerunSetup={props.onRerunSetup}
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
    widgetPreviewCard: { borderRadius: 24, backgroundColor: a.shell, padding: 17, marginTop: 18 },
    widgetPreviewHeader: { flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", gap: 12 },
    widgetEyebrow: { color: a.textMuted, fontSize: 12, fontWeight: "600" },
    widgetAirport: { color: a.text, fontSize: 14, fontWeight: "700", marginTop: 4, maxWidth: 560 },
    widgetEmpty: { minHeight: 100, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10, borderRadius: 18, backgroundColor: a.row, marginTop: 14, paddingHorizontal: 18 },
    widgetEmptyText: { color: a.textMuted, fontSize: 14, lineHeight: 20, flexShrink: 1 },
    widgetFlight: { borderRadius: 18, backgroundColor: a.row, padding: 15, marginTop: 14 },
    widgetFlightLead: { flexDirection: "row", alignItems: "baseline", justifyContent: "space-between", gap: 14 },
    widgetTime: { color: a.text, fontFamily: a.mono, fontSize: 22, fontWeight: "700" },
    widgetFlightCode: { color: a.text, fontFamily: a.mono, fontSize: 16, fontWeight: "700" },
    widgetRoute: { color: a.text, fontSize: 15, fontWeight: "600", marginTop: 12 },
    widgetFlightFooter: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 12, marginTop: 10 },
    widgetStatus: { fontSize: 12, fontWeight: "800" },
    widgetGate: { color: a.textMuted, fontSize: 12, fontWeight: "600", textAlign: "right", flexShrink: 1 },
    widgetFreshness: { color: a.textDim, fontSize: 12, marginTop: 10 },
    widgetSection: { borderRadius: 21, backgroundColor: a.shell, padding: 17, marginTop: 14 },
    widgetSectionHeading: { flexDirection: "row", alignItems: "center", gap: 9 },
    widgetSectionTitle: { color: a.text, fontSize: 17, fontWeight: "700" },
    widgetSectionBody: { color: a.textMuted, fontSize: 14, lineHeight: 20, marginTop: 5 },
    rowCountGroup: { flexDirection: "row", gap: 9, marginTop: 14, marginBottom: 4 },
    rowCountButton: { minHeight: 44, minWidth: 96, alignItems: "center", justifyContent: "center", borderRadius: 15, backgroundColor: a.lineSoft },
    rowCountButtonSelected: { backgroundColor: `${a.blue}18` },
    rowCountText: { color: a.textMuted, fontSize: 14, fontWeight: "700" },
    rowCountTextSelected: { color: a.blue },
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
