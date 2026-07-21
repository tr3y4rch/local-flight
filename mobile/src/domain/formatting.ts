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

export function formatUtc(date: Date = new Date()): string {
  return date.toLocaleTimeString("en-GB", {
    timeZone: "UTC",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
  });
}

export function formatAirportLocalTime(timeZone?: string | null, date: Date = new Date()): string {
  const resolvedTimeZone = timeZone?.trim() || "UTC";
  const options: Intl.DateTimeFormatOptions = {
    timeZone: resolvedTimeZone,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  };

  try {
    return date.toLocaleTimeString("en-GB", options);
  } catch {
    return date.toLocaleTimeString("en-GB", {
      timeZone: "UTC",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false
    });
  }
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
  const message = value instanceof Error ? value.message : String(value);
  if (/remote_relay_timeout/i.test(message)) {
    return "Remote Companion could not get a timely answer from the relay. Check this device’s internet connection, then try again.";
  }
  if (/remote_host_offline/i.test(message)) {
    return "Remote Companion cannot reach your Local Flight host right now. Open Local Flight on the host, or reconnect this device to the same Wi-Fi.";
  }
  if (/remote_host_timeout/i.test(message)) {
    return "Remote Companion reached the relay, but your Local Flight host did not answer in time. Try again once the host is awake.";
  }
  if (/remote_grant_revoked|Remote Companion grant is not active/i.test(message)) {
    return "Remote Companion access was revoked on this host. Pair this device again on the same Wi-Fi to restore remote access.";
  }
  if (/remote_crypto_failed/i.test(message)) {
    return "Remote Companion pairing could not be verified. Create one fresh LAN + Remote QR on the intended host and scan it while this device is on the same Wi-Fi.";
  }
  if (/Remote Companion .*rate limit|rate limit reached/i.test(message)) {
    return "Remote Companion is slowing requests down to protect the relay. Wait a moment, then try again.";
  }
  if (/network request failed|failed to fetch|connection|offline|ECONN|ENOTFOUND/i.test(message)) {
    return "Local Flight could not be reached. Check the connection and try again.";
  }
  if (/timed? out|timeout/i.test(message)) {
    return "Local Flight did not answer in time. Try again shortly.";
  }
  if (/\b401\b|\b403\b|unauthorized|forbidden/i.test(message)) {
    return "This connection is no longer authorized. Pair or sign in again.";
  }
  if (/\b429\b|too many requests/i.test(message)) {
    return "Local Flight is slowing requests down. Wait a moment, then try again.";
  }
  return "That action could not be completed. Try again shortly.";
}

export function parseMetarChips(metar: string): Array<{ label: string; value: string }> {
  const chips: Array<{ label: string; value: string }> = [];
  const windM = metar.match(/(\d{3}|VRB)(\d{2,3})(G(\d+))?KT/);
  if (windM) {
    const dir = windM[1] === "VRB" ? "VRB" : `${windM[1] ?? "000"}°`;
    const gust = windM[4] ? `G${windM[4]}` : "";
    const speed = parseInt(windM[2] ?? "0");
    chips.push({ label: "WND", value: speed === 0 ? "Calm" : `${dir} at ${speed}${gust ? ` gusting ${windM[4]}` : ""} kt` });
  }
  const smM = metar.match(/\b(?:(\d{1,2})\s+)?([PM]?\d+\/\d+|P?\d{1,2})SM\b/);
  if (smM) {
    const whole = smM[1] ? `${smM[1]} ` : "";
    const raw = `${whole}${smM[2] || ""}`.replace(/^P/, ">").replace(/^M/, "<");
    chips.push({ label: "VIS", value: `${raw} SM` });
  }
  const visM = metar.match(/\b(9999|\d{4})\b(?!KT)/);
  if (visM && !chips.some((chip) => chip.label === "VIS")) {
    const v = parseInt(visM[1] ?? "0");
    chips.push({ label: "VIS", value: v >= 9999 ? ">10km" : `${(v / 1000).toFixed(1)}km` });
  }
  const cldM = metar.match(/(FEW|SCT|BKN|OVC)(\d{3})/);
  if (cldM) chips.push({ label: cldM[1] ?? "CLD", value: `${parseInt(cldM[2] ?? "0") * 100}ft` });
  const tmpM = metar.match(/\b(M?\d{1,2})\/(M?\d{1,2})\b/);
  if (tmpM) chips.push({ label: "TMP", value: `${(tmpM[1] ?? "").replace("M", "-")}°C` });
  const qnhM = metar.match(/Q(\d{4})/);
  if (qnhM) chips.push({ label: "QNH", value: `${qnhM[1] ?? ""} hPa` });
  const altimeterM = metar.match(/\bA(\d{4})\b/);
  if (!qnhM && altimeterM) {
    const inHg = parseInt(altimeterM[1] || "0", 10) / 100;
    chips.push({ label: "QNH", value: `${Math.round(inHg * 33.8639)} hPa` });
  }
  return chips;
}

export function formatInterval(seconds: number): string {
  const opt = REFRESH_OPTIONS.find((item) => item.seconds === seconds);
  if (opt) return opt.label;
  return seconds < 3600 ? `${Math.round(seconds / 60)}m` : `${Math.round(seconds / 3600)}h`;
}

export function companionSyncMs(seconds?: number | null): number {
  const serverMs = Math.max(300, seconds || 300) * 1000;
  return Math.min(serverMs, 30 * 60 * 1000);
}
