type ReleaseDownload = {
  filename: string;
  url: string;
  size: number;
  checksum_url: string;
};

export {};

type ReleaseManifest = {
  version: string;
  release_url?: string;
  downloads?: Record<string, ReleaseDownload | null>;
};

const releasesUrl = "https://github.com/tr3y4rch/local-flight/releases";

function sizeLabel(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 10 || unit === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`;
}

document.querySelectorAll<HTMLElement>("[data-downloads]").forEach((root) => {
  const releaseStatus = root.querySelector<HTMLElement>("[data-release-status]");
  const targets = [...root.querySelectorAll<HTMLElement>("[data-download-platform]")];

  function setFallback(message: string): void {
    if (releaseStatus) releaseStatus.textContent = message;
    for (const target of targets) {
      const status = target.querySelector<HTMLElement>("[data-download-status]");
      const button = target.querySelector<HTMLAnchorElement>("[data-download-button]");
      const checksum = target.querySelector<HTMLAnchorElement>("[data-download-checksum]");
      if (status) status.textContent = "Open GitHub Releases to see the files currently available.";
      if (button) {
        button.href = releasesUrl;
        button.textContent = "View release files";
        button.removeAttribute("aria-label");
      }
      if (checksum) checksum.hidden = true;
    }
  }

  async function loadDownloads(): Promise<void> {
    try {
      const response = await fetch("/api/releases/latest", { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error("release manifest unavailable");
      const payload = await response.json() as { ok?: boolean; release?: ReleaseManifest | null };
      if (!payload.ok || !payload.release) {
        setFallback("The latest release is still waiting for one or more verified downloads.");
        return;
      }

      const release = payload.release;
      if (releaseStatus) releaseStatus.textContent = `Local Flight ${release.version}: choose your device and, when needed, its processor.`;

      for (const target of targets) {
        const platform = target.dataset.downloadPlatform || "";
        const download = release.downloads?.[platform];
        const status = target.querySelector<HTMLElement>("[data-download-status]");
        const button = target.querySelector<HTMLAnchorElement>("[data-download-button]");
        const checksum = target.querySelector<HTMLAnchorElement>("[data-download-checksum]");
        if (!download) {
          if (status) status.textContent = `This download is not yet available for Local Flight ${release.version}.`;
          if (button) {
            button.href = release.release_url || releasesUrl;
            button.textContent = "View release files";
            button.removeAttribute("aria-label");
          }
          if (checksum) checksum.hidden = true;
          continue;
        }

        const size = sizeLabel(download.size);
        if (status) status.textContent = `${download.filename}${size ? ` · ${size}` : ""}`;
        if (button) {
          button.href = download.url;
          button.textContent = "Download";
          button.setAttribute("aria-label", `Download ${download.filename}`);
        }
        if (checksum) {
          checksum.href = download.checksum_url;
          checksum.textContent = "Verify download (SHA-256)";
          checksum.hidden = false;
        }
      }
    } catch {
      setFallback("We could not check the downloads right now. GitHub Releases remains available.");
    }
  }

  void loadDownloads();
});
