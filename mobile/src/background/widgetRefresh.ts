import * as BackgroundTask from "expo-background-task";
import * as TaskManager from "expo-task-manager";

import { getFids, getMobileSummary, normalizeServerUrl } from "../api/client";
import { getStandaloneBoard, getStandaloneSummary, type StandaloneCredentials } from "../api/standalone";
import type { AppConfig, FlightView } from "../api/types";
import {
  buildWidgetExchangeSnapshot,
  deriveWidgetPreviewSnapshot,
  widgetSnapshotStaleAfterMs
} from "../domain/widgets";
import {
  isMobileSetupComplete,
  loadCachedLanAirport,
  loadCachedLanConfig,
  loadMobileSetupState,
  loadPinnedFlightReference,
  loadWidgetPreferences
} from "../storage/settings";
import { readWidgetSnapshot, writeWidgetSnapshot } from "../storage/widgetSnapshot";

export const LOCAL_FLIGHT_WIDGET_BACKGROUND_TASK = "localflight-widget-background-refresh";
export const WIDGET_BACKGROUND_MINIMUM_INTERVAL_MINUTES = 30;
const STANDALONE_BOARD_PROJECTION_MINIMUM_MS = 5 * 60 * 1000;

function updatedLabel(value?: string | null): string {
  const parsed = Date.parse(String(value || ""));
  if (!Number.isFinite(parsed)) return "Updated now";
  const minutes = Math.max(0, Math.round((Date.now() - parsed) / 60000));
  if (minutes < 1) return "Updated now";
  if (minutes < 60) return `Updated ${minutes}m ago`;
  return `Updated ${Math.round(minutes / 60)}h ago`;
}

function companionAirportName(config: AppConfig, cachedName?: string | null): string {
  return cachedName || (
    config.display_name && config.display_name !== "Local Flight"
      ? config.display_name
      : config.airport_iata || config.airport_icao || "Local Flight Airport"
  );
}

export async function refreshWidgetSnapshotInBackground(): Promise<boolean> {
  const [setup, preferences, pinnedCallsign, previous] = await Promise.all([
    loadMobileSetupState(),
    loadWidgetPreferences(),
    loadPinnedFlightReference(),
    readWidgetSnapshot()
  ]);
  if (!preferences.automaticRefresh || !isMobileSetupComplete(setup)) return true;

  const view: FlightView = previous?.airport.view === "arrivals" ? "arrivals" : "departures";
  if (setup.mode === "standalone") {
    const previousProjectionTime = Date.parse(previous?.generatedAt || "");
    if (
      previous?.mode === "standalone" &&
      Number.isFinite(previousProjectionTime) &&
      Date.now() - previousProjectionTime < STANDALONE_BOARD_PROJECTION_MINIMUM_MS
    ) {
      return true;
    }
    if (!setup.relayInstallId || !setup.relayActivationToken || !setup.standaloneAirport) return false;
    const credentials: StandaloneCredentials = {
      installId: setup.relayInstallId,
      activationToken: setup.relayActivationToken,
      airport: setup.standaloneAirport,
      diagnosticsMode: setup.diagnosticsMode
    };
    const [summary, board] = await Promise.all([
      getStandaloneSummary(credentials),
      getStandaloneBoard(credentials)
    ]);
    const rows = [...board.departures, ...board.arrivals];
    const sourceUpdatedAt = board.generated_at || summary.state?.last_success_utc || previous?.source.updatedAt || "";
    const preview = deriveWidgetPreviewSnapshot({
      rows,
      pinnedCallsign,
      airportCode: setup.standaloneAirport.iata || setup.standaloneAirport.icao,
      airportName: setup.standaloneAirport.name,
      updatedLabel: updatedLabel(sourceUpdatedAt),
      view,
      preferences
    });
    const result = await writeWidgetSnapshot(buildWidgetExchangeSnapshot({
      preview,
      preferences,
      mode: "standalone",
      // A successful bounded snapshot remains useful while offline. Freshness
      // is derived from its source timestamp/expiry, not current connectivity.
      stale: false,
      sourceLabel: summary.state?.source_name || summary.config?.source || "relay",
      sourceUpdatedAt,
      staleAfterMs: widgetSnapshotStaleAfterMs("standalone")
    }));
    return result.ok;
  }

  const serverUrl = normalizeServerUrl(setup.serverUrl);
  if (!serverUrl) return false;
  const [summary, departures, arrivals, cachedConfig, cachedAirport] = await Promise.all([
    getMobileSummary(serverUrl),
    getFids(serverUrl, "departures"),
    getFids(serverUrl, "arrivals"),
    loadCachedLanConfig(),
    loadCachedLanAirport()
  ]);
  const config = summary.config || cachedConfig;
  if (!config) return false;
  const rows = [...departures, ...arrivals];
  const sourceUpdatedAt = summary.state?.last_success_utc || new Date().toISOString();
  const preview = deriveWidgetPreviewSnapshot({
    rows,
    pinnedCallsign,
    airportCode: config.airport_iata || config.airport_icao,
    airportName: companionAirportName(config, cachedAirport?.name),
    updatedLabel: updatedLabel(sourceUpdatedAt),
    view,
    preferences
  });
  const result = await writeWidgetSnapshot(buildWidgetExchangeSnapshot({
    preview,
    preferences,
    mode: "lan_companion",
    stale: false,
    sourceLabel: summary.state?.source_name || config.source || "host",
    sourceUpdatedAt,
    staleAfterMs: widgetSnapshotStaleAfterMs("lan_companion", config.refresh_seconds)
  }));
  return result.ok;
}

if (!TaskManager.isTaskDefined(LOCAL_FLIGHT_WIDGET_BACKGROUND_TASK)) {
  TaskManager.defineTask(LOCAL_FLIGHT_WIDGET_BACKGROUND_TASK, async () => {
    try {
      return await refreshWidgetSnapshotInBackground()
        ? BackgroundTask.BackgroundTaskResult.Success
        : BackgroundTask.BackgroundTaskResult.Failed;
    } catch {
      return BackgroundTask.BackgroundTaskResult.Failed;
    }
  });
}

export async function configureWidgetBackgroundRefresh(enabled: boolean): Promise<"active" | "restricted" | "off"> {
  try {
    const registered = await TaskManager.isTaskRegisteredAsync(LOCAL_FLIGHT_WIDGET_BACKGROUND_TASK);
    if (!enabled) {
      if (registered) await BackgroundTask.unregisterTaskAsync(LOCAL_FLIGHT_WIDGET_BACKGROUND_TASK);
      return "off";
    }
    const status = await BackgroundTask.getStatusAsync();
    if (status !== BackgroundTask.BackgroundTaskStatus.Available) return "restricted";
    if (!registered) {
      await BackgroundTask.registerTaskAsync(LOCAL_FLIGHT_WIDGET_BACKGROUND_TASK, {
        minimumInterval: WIDGET_BACKGROUND_MINIMUM_INTERVAL_MINUTES
      });
    }
    return "active";
  } catch {
    return "restricted";
  }
}
