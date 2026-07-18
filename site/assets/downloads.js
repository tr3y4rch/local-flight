(() => {
  const releasesUrl = "https://github.com/tr3y4rch/local-flight/releases";
  const root = document.querySelector("[data-downloads]");
  if (!root) return;

  const releaseStatus = root.querySelector("[data-release-status]");
  // Each target is one exact operating-system/CPU package. Several targets can
  // live in the same visual card, so availability is never inferred from a
  // neighbouring architecture.
  const targets = [...root.querySelectorAll("[data-download-platform]")];

  function sizeLabel(bytes) {
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

  function setFallback(message) {
    if (releaseStatus) releaseStatus.textContent = message;
    for (const target of targets) {
      const status = target.querySelector("[data-download-status]");
      const button = target.querySelector("[data-download-button]");
      const checksum = target.querySelector("[data-download-checksum]");
      if (status) status.textContent = "Open GitHub to see currently published files.";
      if (button) {
        button.href = releasesUrl;
        button.textContent = "View release files";
      }
      if (checksum) checksum.hidden = true;
    }
  }

  async function loadDownloads() {
    try {
      const response = await fetch("/api/releases/latest", {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error("release manifest unavailable");
      const payload = await response.json();
      if (!payload?.ok || !payload.release) {
        setFallback("No complete platform packages are published yet.");
        return;
      }

      const release = payload.release;
      if (releaseStatus) {
        releaseStatus.textContent = `Packaged release ${release.version}: choose your system and processor.`;
      }

      for (const target of targets) {
        const platform = target.dataset.downloadPlatform;
        const download = release.downloads?.[platform];
        const status = target.querySelector("[data-download-status]");
        const button = target.querySelector("[data-download-button]");
        const checksum = target.querySelector("[data-download-checksum]");
        if (!download) {
          if (status) status.textContent = `Not yet published for release ${release.version}.`;
          if (button) {
            button.href = release.release_url || releasesUrl;
            button.textContent = "View release files";
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
          checksum.textContent = "SHA256 checksum";
          checksum.hidden = false;
        }
      }
    } catch {
      setFallback("Downloads are temporarily unavailable here. GitHub Releases remains available.");
    }
  }

  void loadDownloads();
})();
