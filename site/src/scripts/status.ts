export {};

type StatusState = "operational" | "degraded" | "outage" | "unknown";

type StatusEntry = {
  key: string;
  label?: string;
  state: StatusState;
  uptime?: Record<string, number> | null;
};

type StatusNotice = { key: string; tone: string; text: string };

type StatusPayload = {
  ok?: boolean;
  overall?: StatusState;
  generated_at?: string;
  services?: StatusEntry[];
  components?: StatusEntry[];
  notices?: StatusNotice[];
  build?: { version?: string; revision?: string; environment?: string } | null;
  sources?: { live?: boolean; history?: boolean };
};

const stateLabels: Record<StatusState, string> = {
  operational: "Operational",
  degraded: "Degraded",
  outage: "Not reachable",
  unknown: "Unknown",
};

const overallLabels: Record<StatusState, string> = {
  operational: "All services are operating normally.",
  degraded: "Some services are degraded.",
  outage: "There is an active outage.",
  unknown: "Current status could not be determined.",
};

const periods = ["day", "week", "month", "quarter"] as const;

function knownState(value: unknown): StatusState {
  return value === "operational" || value === "degraded" || value === "outage" ? value : "unknown";
}

function ratioLabel(value: number | undefined): string {
  if (!Number.isFinite(value as number)) return "—";
  const ratio = value as number;
  return ratio >= 100 ? "100%" : `${ratio.toFixed(2)}%`;
}

// Formatted in UTC rather than the reader's locale: the value is cached and shared by
// every reader, and a locale-dependent string would make the visual baseline unstable.
function checkedLabel(generatedAt: string | undefined): string {
  const stamp = new Date(String(generatedAt || ""));
  if (Number.isNaN(stamp.getTime())) return "";
  const time = `${String(stamp.getUTCHours()).padStart(2, "0")}:${String(stamp.getUTCMinutes()).padStart(2, "0")}`;
  return `Checked ${stamp.getUTCFullYear()}-${String(stamp.getUTCMonth() + 1).padStart(2, "0")}-${String(stamp.getUTCDate()).padStart(2, "0")} at ${time} UTC.`;
}

function applyRow(row: HTMLElement | null, entry: StatusEntry | undefined): void {
  if (!row) return;
  const state = knownState(entry?.state);
  const dot = row.querySelector<HTMLElement>(".status-dot");
  const label = row.querySelector<HTMLElement>("[data-status-state]");
  if (dot) dot.dataset.state = state;
  if (label) {
    label.textContent = stateLabels[state];
    label.dataset.state = state;
  }

  const uptime = row.querySelector<HTMLElement>("[data-status-uptime]");
  if (!uptime) return;
  const ratios = entry?.uptime;
  if (!ratios) {
    uptime.hidden = true;
    return;
  }
  uptime.hidden = false;
  for (const period of periods) {
    const cell = uptime.querySelector<HTMLElement>(`[data-status-uptime-period="${period}"]`);
    if (cell) cell.textContent = ratioLabel(ratios[period]);
  }
}

function renderNotices(container: HTMLElement | null, notices: StatusNotice[]): void {
  if (!container) return;
  container.textContent = "";
  if (!notices.length) {
    container.hidden = true;
    return;
  }
  for (const notice of notices) {
    const item = document.createElement("li");
    item.dataset.tone = notice.tone === "degraded" ? "degraded" : "info";
    item.textContent = notice.text;
    container.append(item);
  }
  container.hidden = false;
}

const board = document.querySelector<HTMLElement>("[data-status-board]");

if (board) {
  const overall = document.querySelector<HTMLElement>("[data-status-overall]");
  const build = document.querySelector<HTMLElement>("[data-status-build]");
  const fallback = document.querySelector<HTMLElement>("[data-status-fallback]");
  const notices = document.querySelector<HTMLElement>("[data-status-notices]");

  function setFallback(message: string): void {
    if (overall) {
      overall.dataset.state = "unknown";
      overall.textContent = overallLabels.unknown;
    }
    for (const row of document.querySelectorAll<HTMLElement>("[data-status-service], [data-status-component]")) {
      applyRow(row, undefined);
    }
    if (!fallback) return;
    fallback.textContent = message;
    const fallbackUrl = fallback.dataset.fallbackUrl;
    if (fallbackUrl) {
      const link = document.createElement("a");
      link.className = "action-link";
      link.href = fallbackUrl;
      link.textContent = "Independent status page";
      fallback.append(" ", link);
    }
    fallback.hidden = false;
  }

  async function loadStatus(): Promise<void> {
    try {
      const response = await fetch("/api/status", { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error("status unavailable");
      const payload = await response.json() as StatusPayload;
      if (!payload.ok) throw new Error("status unavailable");

      const state = knownState(payload.overall);
      if (overall) {
        overall.dataset.state = state;
        overall.textContent = `${overallLabels[state]} ${checkedLabel(payload.generated_at)}`.trim();
      }

      const services = new Map((payload.services || []).map((entry) => [entry.key, entry]));
      for (const row of document.querySelectorAll<HTMLElement>("[data-status-service]")) {
        applyRow(row, services.get(row.dataset.statusService || ""));
      }

      const components = new Map((payload.components || []).map((entry) => [entry.key, entry]));
      for (const row of document.querySelectorAll<HTMLElement>("[data-status-component]")) {
        applyRow(row, components.get(row.dataset.statusComponent || ""));
      }

      renderNotices(notices, payload.notices || []);

      if (build) {
        const version = payload.build?.version;
        const revision = payload.build?.revision;
        build.textContent = version ? `Beacon Relay ${version}${revision ? ` · build ${revision}` : ""}` : "";
        build.hidden = !version;
      }
      if (fallback) fallback.hidden = true;
    } catch {
      setFallback("Current status could not be loaded.");
    }
  }

  void loadStatus();
}
