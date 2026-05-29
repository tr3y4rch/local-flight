import { useCallback, useRef, useState } from "react";

import { getFidsDetail, LocalFlightApiError, normalizeServerUrl } from "../api/client";
import type { FidsDetailResponse } from "../api/types";
import { reportMobileCrash } from "../crash/reporter";
import { detailOrNull } from "../domain/flights";
import { errorMessage } from "../domain/formatting";

export function useFlightDetail(serverUrl: string, onError: (message: string) => void) {
  const [visible, setVisible] = useState(false);
  const [loading, setLoading] = useState(false);
  const [callsign, setCallsign] = useState("");
  const [data, setData] = useState<FidsDetailResponse | null>(null);
  const requestRef = useRef(0);

  const reportDetailFailure = useCallback((exc: unknown, nextCallsign: string, normalized: string) => {
    const shouldReport =
      exc instanceof LocalFlightApiError
        ? Boolean(exc.status && exc.status >= 500)
        : exc instanceof SyntaxError;
    if (!shouldReport) return;

    void reportMobileCrash({
      message: `Flight detail fetch failed: ${errorMessage(exc)}`,
      traceback: exc instanceof Error ? exc.stack || "" : "",
      context: "mobile/fids-detail",
      client_context: [
        "Endpoint      /api/fids/detail",
        `Callsign      ${nextCallsign}`,
        `Server URL    ${normalized}`,
        `Error class   ${exc instanceof Error ? exc.name : typeof exc}`
      ].join("\n")
    });
  }, []);

  const load = useCallback(
    async (nextCallsign: string) => {
      const normalized = normalizeServerUrl(serverUrl);
      if (!normalized || !nextCallsign) return;

      const requestId = requestRef.current + 1;
      requestRef.current = requestId;
      setLoading(true);

      try {
        const detailData = await getFidsDetail(normalized, nextCallsign);
        if (requestRef.current === requestId) {
          setData(detailData);
        }
      } catch (exc) {
        if (requestRef.current === requestId) {
          setData(null);
          onError(errorMessage(exc));
          reportDetailFailure(exc, nextCallsign, normalized);
        }
      } finally {
        if (requestRef.current === requestId) {
          setLoading(false);
        }
      }
    },
    [onError, reportDetailFailure, serverUrl]
  );

  const open = useCallback(
    (
      nextCallsign: string,
      seed: FidsDetailResponse | null = null,
      options: { fetch?: boolean } = {}
    ) => {
      if (!nextCallsign) return;
      const shouldFetch = options.fetch ?? true;
      setCallsign(nextCallsign);
      setData(seed);
      setVisible(true);
      if (shouldFetch) {
        void load(nextCallsign);
      } else {
        setLoading(false);
      }
    },
    [load]
  );

  const close = useCallback(() => {
    setVisible(false);
  }, []);

  const refresh = useCallback(() => {
    void load(callsign);
  }, [callsign, load]);

  return {
    visible,
    loading,
    callsign,
    data,
    detail: detailOrNull(data),
    history: data?.history || [],
    open,
    close,
    refresh
  };
}
