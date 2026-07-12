import { useCallback, useRef, useState } from "react";

import { getFidsDetail, LocalFlightApiError, normalizeServerUrl } from "../api/client";
import type { FidsDetailResponse } from "../api/types";
import { reportMobileCrash } from "../crash/reporter";
import { detailOrNull } from "../domain/flights";
import { errorMessage } from "../domain/formatting";

function preserveAvailableDetail(
  response: FidsDetailResponse,
  current: FidsDetailResponse | null
): FidsDetailResponse {
  if (detailOrNull(response) || !detailOrNull(current)) return response;
  return {
    ...response,
    detail: current?.detail || {},
    history: response.history.length ? response.history : current?.history || []
  };
}

export function useFlightDetail(serverUrl: string) {
  const [visible, setVisible] = useState(false);
  const [loading, setLoading] = useState(false);
  const [callsign, setCallsign] = useState("");
  const [data, setData] = useState<FidsDetailResponse | null>(null);
  const [notice, setNotice] = useState("");
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
      setNotice("");

      try {
        const detailData = await getFidsDetail(normalized, nextCallsign);
        if (requestRef.current === requestId) {
          setData((current) => preserveAvailableDetail(detailData, current));
          if (!detailOrNull(detailData)) {
            setNotice("No matching live enrichment was returned. Showing the available board details.");
          }
        }
      } catch (exc) {
        if (requestRef.current === requestId) {
          setNotice("Live enrichment is temporarily unavailable. Showing the available board details.");
          reportDetailFailure(exc, nextCallsign, normalized);
        }
      } finally {
        if (requestRef.current === requestId) {
          setLoading(false);
        }
      }
    },
    [reportDetailFailure, serverUrl]
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
      setNotice("");
      setVisible(true);
      if (shouldFetch) {
        void load(nextCallsign);
      } else {
        requestRef.current += 1;
        setLoading(false);
      }
    },
    [load]
  );

  const close = useCallback(() => {
    requestRef.current += 1;
    setVisible(false);
    setLoading(false);
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
    notice,
    open,
    close,
    refresh
  };
}
