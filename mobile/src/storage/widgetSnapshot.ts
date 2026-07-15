import { File, Paths } from "expo-file-system";
import { reloadLocalFlightWidgets } from "localflight-widget-bridge";

import {
  parseWidgetExchangeSnapshot,
  serializeWidgetExchangeSnapshot,
  WIDGET_APP_GROUP_ID,
  WIDGET_SNAPSHOT_FILENAME,
  widgetSnapshotSemanticKey,
  type LocalFlightWidgetSnapshot
} from "../domain/widgets";

export type WidgetSnapshotWriteResult = {
  ok: boolean;
  uri: string;
  sharedContainer: boolean;
  skipped?: boolean;
  error?: string;
};

let lastWidgetSnapshotWriteKey = "";
let widgetSnapshotWriteQueue: Promise<void> = Promise.resolve();
let widgetSnapshotTempNonce = 0;

function enqueueWidgetSnapshotWrite<T>(task: () => Promise<T>): Promise<T> {
  const run = widgetSnapshotWriteQueue.then(task, task);
  widgetSnapshotWriteQueue = run.then(
    () => undefined,
    () => undefined
  );
  return run;
}

function errorText(value: unknown): string {
  return value instanceof Error ? value.message : String(value || "write failed");
}

function nextTempSnapshotName(): string {
  widgetSnapshotTempNonce = (widgetSnapshotTempNonce + 1) % 100000;
  return `${WIDGET_SNAPSHOT_FILENAME}.${Date.now()}.${widgetSnapshotTempNonce}.tmp`;
}

function resolveSharedContainerFile(): File | null {
  try {
    const container = Paths.appleSharedContainers?.[WIDGET_APP_GROUP_ID];
    return container ? new File(container, WIDGET_SNAPSHOT_FILENAME) : null;
  } catch {
    return null;
  }
}

function resolveFallbackFile(): File {
  return new File(Paths.document, WIDGET_SNAPSHOT_FILENAME);
}

export function getWidgetSnapshotFile(): { file: File; sharedContainer: boolean } {
  const sharedFile = resolveSharedContainerFile();
  if (sharedFile) {
    return { file: sharedFile, sharedContainer: true };
  }
  return { file: resolveFallbackFile(), sharedContainer: false };
}

export function getWidgetSnapshotUri(): string {
  return getWidgetSnapshotFile().file.uri;
}

export function resetWidgetSnapshotWriteMemo(): void {
  lastWidgetSnapshotWriteKey = "";
  widgetSnapshotWriteQueue = Promise.resolve();
  widgetSnapshotTempNonce = 0;
}

export function shouldWriteWidgetSnapshot(snapshot: LocalFlightWidgetSnapshot): boolean {
  return widgetSnapshotSemanticKey(snapshot) !== lastWidgetSnapshotWriteKey;
}

export async function writeWidgetSnapshot(
  snapshot: LocalFlightWidgetSnapshot,
  options: { force?: boolean } = {}
): Promise<WidgetSnapshotWriteResult> {
  return enqueueWidgetSnapshotWrite(async () => {
    let file: File | null = null;
    let sharedContainer = false;
    try {
      const target = getWidgetSnapshotFile();
      file = target.file;
      sharedContainer = target.sharedContainer;
      const writeKey = widgetSnapshotSemanticKey(snapshot);
      if (!options.force && writeKey === lastWidgetSnapshotWriteKey) {
        return { ok: true, uri: file.uri, sharedContainer, skipped: true };
      }
      const json = serializeWidgetExchangeSnapshot(snapshot);
      const tempFile = new File(file.parentDirectory, nextTempSnapshotName());

      try {
        tempFile.create({ overwrite: true, intermediates: true });
        tempFile.write(json);
        if (file.exists) {
          file.delete();
        }
        tempFile.move(file);
      } catch (exc) {
        try {
          if (tempFile.exists) {
            tempFile.delete();
          }
        } catch {
          // Temp cleanup is best-effort; the fallback write below is authoritative.
        }
        try {
          file.create({ overwrite: true, intermediates: true });
          file.write(json);
        } catch (fallbackExc) {
          return {
            ok: false,
            uri: file.uri,
            sharedContainer,
            error: errorText(fallbackExc || exc)
          };
        }
      }
      lastWidgetSnapshotWriteKey = writeKey;
      await reloadLocalFlightWidgets();
      return { ok: true, uri: file.uri, sharedContainer };
    } catch (exc) {
      return {
        ok: false,
        uri: file?.uri || "",
        sharedContainer,
        error: errorText(exc)
      };
    }
  });
}

export async function readWidgetSnapshot(): Promise<LocalFlightWidgetSnapshot | null> {
  const { file } = getWidgetSnapshotFile();
  try {
    if (!file.exists) {
      return null;
    }
    return parseWidgetExchangeSnapshot(await file.text());
  } catch {
    return null;
  }
}
