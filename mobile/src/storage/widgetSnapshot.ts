import { File, Paths } from "expo-file-system";

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
}

export function shouldWriteWidgetSnapshot(snapshot: LocalFlightWidgetSnapshot): boolean {
  return widgetSnapshotSemanticKey(snapshot) !== lastWidgetSnapshotWriteKey;
}

export async function writeWidgetSnapshot(
  snapshot: LocalFlightWidgetSnapshot,
  options: { force?: boolean } = {}
): Promise<WidgetSnapshotWriteResult> {
  const { file, sharedContainer } = getWidgetSnapshotFile();
  const writeKey = widgetSnapshotSemanticKey(snapshot);
  if (!options.force && writeKey === lastWidgetSnapshotWriteKey) {
    return { ok: true, uri: file.uri, sharedContainer, skipped: true };
  }
  const json = serializeWidgetExchangeSnapshot(snapshot);
  const tempFile = new File(file.parentDirectory, `${WIDGET_SNAPSHOT_FILENAME}.tmp`);

  try {
    tempFile.create({ overwrite: true, intermediates: true });
    tempFile.write(json);
    if (file.exists) {
      file.delete();
    }
    tempFile.move(file);
    lastWidgetSnapshotWriteKey = writeKey;
    return { ok: true, uri: file.uri, sharedContainer };
  } catch (exc) {
    try {
      file.create({ overwrite: true, intermediates: true });
      file.write(json);
      lastWidgetSnapshotWriteKey = writeKey;
      return { ok: true, uri: file.uri, sharedContainer };
    } catch (fallbackExc) {
      return {
        ok: false,
        uri: file.uri,
        sharedContainer,
        error: fallbackExc instanceof Error ? fallbackExc.message : String(fallbackExc || exc)
      };
    }
  }
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
