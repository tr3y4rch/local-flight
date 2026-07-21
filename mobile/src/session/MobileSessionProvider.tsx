import { createContext, useContext, type ReactNode } from "react";

import type { ClientNotice } from "../api/types";
import type { BoardScreenV2Props } from "../v2/BoardScreenV2";
import type { HistoryScreenV2Props } from "../v2/HistoryScreenV2";
import type { RadarScreenV2Props } from "../v2/RadarScreenV2";

export type MobileSection = "board" | "radar" | "history" | "more";

/**
 * Stable feature-facing session contract. Transport and storage stay owned by
 * the session controller while V2 routes consume only the state and actions
 * they need. This keeps LAN, Remote Companion and Standalone details out of
 * presentation components.
 */
export type MobileSessionValue = {
  board: BoardScreenV2Props;
  radar: RadarScreenV2Props;
  history: HistoryScreenV2Props;
  notices: ClientNotice[];
  onNoticeAction: (notice: ClientNotice) => void;
  onSectionFocus: (section: MobileSection) => void;
  onRefreshCurrent: () => void;
  onOpenSearchOrFilter: () => void;
  onDismissTransientSurface: () => void;
};

const MobileSessionContext = createContext<MobileSessionValue | null>(null);

export function MobileSessionProvider({
  value,
  children
}: {
  value: MobileSessionValue;
  children: ReactNode;
}) {
  return (
    <MobileSessionContext.Provider value={value}>
      {children}
    </MobileSessionContext.Provider>
  );
}

export function useMobileSession(): MobileSessionValue {
  const value = useContext(MobileSessionContext);
  if (!value) {
    throw new Error("useMobileSession must be used inside MobileSessionProvider");
  }
  return value;
}
