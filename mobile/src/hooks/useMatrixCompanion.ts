import { useCallback, useEffect, useRef, useState } from "react";

import { getFids, getMatrixConfig, normalizeServerUrl, saveMatrixConfig } from "../api/client";
import type { FidsRow, FlightView, MatrixPresetId, MatrixRuntimeConfigSave } from "../api/types";
import { DEFAULT_MATRIX_CONFIG, MATRIX_PRESETS } from "../domain/constants";
import {
  matrixConfigsEqual,
  normalizeMatrixPreset,
  normalizeMatrixRuntimeConfig,
  normalizeMatrixSkin
} from "../domain/matrix";
import { errorMessage } from "../domain/formatting";
import type { FeedbackTone } from "../domain/types";
import type { MobileSkin } from "../theme/tokens";

export function useMatrixCompanion(serverUrl: string) {
  const [rows, setRows] = useState<FidsRow[]>([]);
  const [savedConfig, setSavedConfig] = useState<MatrixRuntimeConfigSave | null>(null);
  const [draftConfig, setDraftConfig] = useState<MatrixRuntimeConfigSave>(DEFAULT_MATRIX_CONFIG);
  const [serverSkin, setServerSkin] = useState<MobileSkin>("standard");
  const [saving, setSaving] = useState(false);
  const [applyingPreset, setApplyingPreset] = useState<MatrixPresetId | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [saveTone, setSaveTone] = useState<FeedbackTone>("ok");

  const savedRef = useRef<MatrixRuntimeConfigSave | null>(null);
  const draftRef = useRef<MatrixRuntimeConfigSave>(DEFAULT_MATRIX_CONFIG);

  useEffect(() => {
    savedRef.current = savedConfig;
  }, [savedConfig]);

  useEffect(() => {
    draftRef.current = draftConfig;
  }, [draftConfig]);

  const fetchRuntime = useCallback(
    async (normalized: string, syncDraft = false) => {
      const config = await getMatrixConfig(normalized);
      const nextSaved = normalizeMatrixRuntimeConfig(config);
      const currentSaved = savedRef.current;
      const currentDraft = draftRef.current;
      const hasUnsaved = !matrixConfigsEqual(currentDraft, currentSaved || currentDraft);

      setServerSkin(normalizeMatrixSkin(config.skin));
      setSavedConfig(nextSaved);
      if (syncDraft || !hasUnsaved) {
        setDraftConfig(nextSaved);
      }
    },
    []
  );

  const fetchRows = useCallback(
    async (normalized: string, nextView: FlightView, nextRows: number) => {
      const fids = await getFids(normalized, nextView, nextRows);
      setRows(fids);
    },
    []
  );

  const updateDraft = useCallback((patch: Partial<MatrixRuntimeConfigSave>) => {
    setDraftConfig((prev) => normalizeMatrixRuntimeConfig({ ...prev, ...patch }));
    setSaveMessage(null);
  }, []);

  const resetDraft = useCallback(async () => {
    const normalized = normalizeServerUrl(serverUrl);
    setSaveTone("ok");
    if (!normalized) {
      setDraftConfig(savedRef.current || DEFAULT_MATRIX_CONFIG);
      setSaveMessage("Reset local matrix draft.");
      return;
    }

    try {
      await fetchRuntime(normalized, true);
      setSaveMessage("Reloaded server matrix config.");
    } catch (exc) {
      setSaveTone("error");
      setSaveMessage(errorMessage(exc));
    }
  }, [fetchRuntime, serverUrl]);

  const saveDraft = useCallback(async () => {
    const normalized = normalizeServerUrl(serverUrl);
    if (!normalized) {
      setSaveTone("error");
      setSaveMessage("Set the Local Flight server URL first.");
      return;
    }

    setSaving(true);
    setSaveTone("ok");
    setSaveMessage("Saving matrix runtime...");

    try {
      const payload = normalizeMatrixRuntimeConfig(draftRef.current);
      await saveMatrixConfig(normalized, payload);
      await fetchRuntime(normalized, true);
      setSaveMessage("Saved — board picks up in about 60 seconds.");
    } catch (exc) {
      setSaveTone("error");
      setSaveMessage(errorMessage(exc));
    } finally {
      setSaving(false);
    }
  }, [fetchRuntime, serverUrl]);

  const applyPreset = useCallback(async (preset: MatrixPresetId) => {
    const normalized = normalizeServerUrl(serverUrl);
    if (!normalized) {
      setSaveTone("error");
      setSaveMessage("Set the Local Flight server URL first.");
      return;
    }

    const presetConfig = MATRIX_PRESETS.find((item) => item.id === preset) || MATRIX_PRESETS[0]!;
    const current = draftRef.current;
    const palette = presetConfig.palettes.includes(current.palette)
      ? current.palette
      : presetConfig.palettes[0] || DEFAULT_MATRIX_CONFIG.palette;
    const showWeather = Boolean(current.options.show_metar ?? current.options.show_weather ?? true);
    const nextConfig = normalizeMatrixRuntimeConfig({
      ...current,
      preset,
      palette,
      show_gate_info: presetConfig.showGateInfo,
      options: {
        ...current.options,
        palette,
        show_metar: showWeather,
        show_weather: showWeather,
        show_gate_info: presetConfig.showGateInfo,
        animation_mode: current.animation_mode
      }
    });

    setDraftConfig(nextConfig);
    setApplyingPreset(preset);
    setSaving(true);
    setSaveTone("ok");
    setSaveMessage(`Applying ${presetConfig.label} preset...`);

    try {
      await saveMatrixConfig(normalized, nextConfig);
      await fetchRuntime(normalized, true);
      setSaveMessage(`${presetConfig.label} preset saved. Board picks up in about 60 seconds.`);
    } catch (exc) {
      setSaveTone("error");
      setSaveMessage(errorMessage(exc));
    } finally {
      setApplyingPreset(null);
      setSaving(false);
    }
  }, [fetchRuntime, serverUrl]);

  const runtime = normalizeMatrixRuntimeConfig(draftConfig);
  const dirty = savedConfig ? !matrixConfigsEqual(draftConfig, savedConfig) : false;

  return {
    rows,
    savedConfig,
    draftConfig,
    runtime,
    serverSkin,
    preset: normalizeMatrixPreset(runtime.preset),
    dirty,
    saving,
    applyingPreset,
    saveMessage,
    saveTone,
    fetchRuntime,
    fetchRows,
    updateDraft,
    resetDraft,
    saveDraft,
    applyPreset
  };
}
