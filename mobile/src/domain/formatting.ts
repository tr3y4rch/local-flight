import { REFRESH_OPTIONS } from "./constants";

export function hexToRgba(value: string, opacity: number): string {
  const hex = value.replace("#", "");
  const normalized = hex.length === 3
    ? hex.split("").map((part) => part + part).join("")
    : hex;
  const int = parseInt(normalized, 16);
  const r = (int >> 16) & 255;
  const g = (int >> 8) & 255;
  const b = int & 255;
  return `rgba(${r},${g},${b},${opacity})`;
}

export function formatUtc(): string {
  return new Date().toLocaleTimeString("en-GB", {
    timeZone: "UTC",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
  });
}

export function formatLocalTime(): string {
  return new Date().toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  });
}

export function formatRelative(value?: string | null): string {
  if (!value) return "Never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  return date.toLocaleString();
}

export function formatDateTime(value?: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

export function formatClock(value?: string | null): string {
  if (!value) return "--:--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  });
}

export function errorMessage(value: unknown): string {
  return value instanceof Error ? value.message : String(value);
}

export function parseMetarChips(metar: string): Array<{ label: string; value: string }> {
  const chips: Array<{ label: string; value: string }> = [];
  const windM = metar.match(/(\d{3}|VRB)(\d{2,3})(G(\d+))?KT/);
  if (windM) {
    const dir = windM[1] === "VRB" ? "VRB" : `${windM[1] ?? "000"}°`;
    const gust = windM[4] ? `G${windM[4]}` : "";
    chips.push({ label: "WND", value: `${dir} ${parseInt(windM[2] ?? "0")}${gust}kt` });
  }
  const visM = metar.match(/\b(9999|\d{4})\b(?!KT)/);
  if (visM) {
    const v = parseInt(visM[1] ?? "0");
    chips.push({ label: "VIS", value: v >= 9999 ? ">10km" : `${(v / 1000).toFixed(1)}km` });
  }
  const cldM = metar.match(/(FEW|SCT|BKN|OVC)(\d{3})/);
  if (cldM) chips.push({ label: cldM[1] ?? "CLD", value: `${parseInt(cldM[2] ?? "0") * 100}ft` });
  const tmpM = metar.match(/\b(M?\d{1,2})\/(M?\d{1,2})\b/);
  if (tmpM) chips.push({ label: "TMP", value: `${(tmpM[1] ?? "").replace("M", "-")}°C` });
  const qnhM = metar.match(/Q(\d{4})/);
  if (qnhM) chips.push({ label: "QNH", value: qnhM[1] ?? "" });
  return chips;
}

export function formatInterval(seconds: number): string {
  const opt = REFRESH_OPTIONS.find((item) => item.seconds === seconds);
  if (opt) return opt.label;
  return seconds < 3600 ? `${Math.round(seconds / 60)}m` : `${Math.round(seconds / 3600)}h`;
}

export function companionSyncMs(seconds?: number | null): number {
  const serverMs = Math.max(60, seconds || 60) * 1000;
  return Math.min(serverMs, 30 * 60 * 1000);
}
