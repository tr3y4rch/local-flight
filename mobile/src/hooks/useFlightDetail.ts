import { useCallback, useRef, useState } from "react";

import { getFidsDetail, normalizeServerUrl } from "../api/client";
import type { FidsDetailResponse } from "../api/types";
import { detailOrNull } from "../domain/flights";
import { errorMessage } from "../domain/formatting";

export function useFlightDetail(serverUrl: string, onError: (message: string) => void) {
  const [visible, setVisible] = useState(false);
  const [loading, setLoading] = useState(false);
  const [callsign, setCallsign] = useState("");
  const [data, setData] = useState<FidsDetailResponse | null>(null);
  const requestRef = useRef(0);

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
        }
      } finally {
        if (requestRef.current === requestId) {
          setLoading(false);
        }
      }
    },
    [onError, serverUrl]
  );

  const open = useCallback(
    (nextCallsign: string) => {
      if (!nextCallsign) return;
      setCallsign(nextCallsign);
      setData(null);
      setVisible(true);
      void load(nextCallsign);
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
