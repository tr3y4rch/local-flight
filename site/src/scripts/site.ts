const themeKey = "beacontools.theme";
export {};
const root = document.documentElement;

function currentTheme(): "light" | "dark" {
  return root.dataset.theme === "light" ? "light" : "dark";
}

function updateThemeControls(): void {
  const theme = currentTheme();
  document.querySelectorAll<HTMLButtonElement>("[data-theme-toggle]").forEach((button) => {
    const next = theme === "dark" ? "light" : "dark";
    button.setAttribute("aria-label", `Switch to ${next} theme`);
    const label = button.querySelector<HTMLElement>("[data-theme-label]");
    if (label) label.textContent = next === "light" ? "Light" : "Dark";
  });
  const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if (meta) meta.content = theme === "dark" ? "#080c12" : "#f4f7fb";
}

document.querySelectorAll<HTMLButtonElement>("[data-theme-toggle]").forEach((button) => {
  button.addEventListener("click", () => {
    const theme = currentTheme() === "dark" ? "light" : "dark";
    root.dataset.theme = theme;
    root.style.colorScheme = theme;
    try {
      localStorage.setItem(themeKey, theme);
    } catch {}
    updateThemeControls();
  });
});
updateThemeControls();

const menuButton = document.querySelector<HTMLButtonElement>("[data-menu-toggle]");
const navigationElement = document.querySelector<HTMLElement>("[data-site-nav]");

function setMenu(open: boolean): void {
  if (!menuButton || !navigationElement) return;
  menuButton.setAttribute("aria-expanded", String(open));
  navigationElement.dataset.open = String(open);
  const label = menuButton.querySelector<HTMLElement>("[data-menu-label]");
  if (label) label.textContent = open ? "Close" : "Menu";
}

menuButton?.addEventListener("click", () => setMenu(menuButton.getAttribute("aria-expanded") !== "true"));
navigationElement?.querySelectorAll<HTMLAnchorElement>("a").forEach((link) => link.addEventListener("click", () => setMenu(false)));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    setMenu(false);
    menuButton?.focus();
  }
});

const timeFormat = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});
const utcFormat = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
  timeZone: "UTC",
});

function updateClocks(): void {
  const now = new Date();
  document.querySelectorAll<HTMLTimeElement>('[data-clock="utc"]').forEach((clock) => {
    clock.textContent = utcFormat.format(now);
    clock.dateTime = now.toISOString();
  });
  document.querySelectorAll<HTMLTimeElement>('[data-clock="local"]').forEach((clock) => {
    clock.textContent = timeFormat.format(now);
    clock.dateTime = now.toISOString();
  });
}
updateClocks();
window.setInterval(updateClocks, 1000);

const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
if (reduceMotion) {
  root.dataset.reduceMotion = "true";
  document.querySelectorAll<HTMLElement>("[data-reveal]").forEach((item) => item.dataset.visible = "true");
} else {
  const revealObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        (entry.target as HTMLElement).dataset.visible = "true";
        revealObserver.unobserve(entry.target);
      }
    });
  }, { rootMargin: "0px 0px -8%", threshold: 0.08 });
  document.querySelectorAll<HTMLElement>("[data-reveal]").forEach((item) => revealObserver.observe(item));

  const instrumentObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      (entry.target as HTMLElement).dataset.motionActive = String(entry.isIntersecting);
    });
  }, { threshold: 0.05 });
  document.querySelectorAll<HTMLElement>("[data-instrument]").forEach((item) => instrumentObserver.observe(item));
}
