const BOOT = __BOOT__;

const views = [
  { id: "overview", group: "Monitor", icon: "CC", label: "Command center", title: "Command center", description: "System-wide health, demand, provider readiness, and the operator attention queue." },
  { id: "fleet", group: "Monitor", icon: "FL", label: "Install fleet", title: "Install fleet", description: "Find an install, understand its presence and configuration, then take a scoped action." },
  { id: "traffic", group: "Monitor", icon: "TR", label: "Traffic & quota", title: "Traffic & quota", description: "Monthly service consumption and recent request health across the relay." },
  { id: "schedules", group: "Investigate", icon: "SC", label: "Schedule cache", title: "Schedule cache", description: "Shared airport windows, cache efficiency, and current client interests." },
  { id: "surfaces", group: "Investigate", icon: "GC", label: "Ground cache", title: "Ground cache", description: "Airport ground layers, coverage, cache state, and controlled warm jobs." },
  { id: "reports", group: "Investigate", icon: "RP", label: "Reports", title: "Reports", description: "Sanitized report flow, delivery outcomes, and deduplication groups." },
  { id: "activations", group: "Operate", icon: "AC", label: "Access control", title: "Access control", description: "Activation requests, managed tokens, blocked installs, and one-time credentials." },
  { id: "access", group: "Operate", icon: "RA", label: "Relay Access", title: "Relay Access", description: "Licenses, receivers, email delivery, and purchase reconciliation." },
  { id: "providers", group: "Operate", icon: "PR", label: "Providers", title: "Providers", description: "Credential presence, hosted-use authorization, and relay-stored key overrides." },
  { id: "retention", group: "Operate", icon: "RT", label: "Retention", title: "Retention", description: "Retention health, current policy windows, manual runs, and scoped legal holds." },
  { id: "maintenance", group: "System", icon: "MX", label: "Maintenance", title: "Maintenance", description: "Runtime configuration and carefully separated destructive maintenance controls." },
];

const endpoints = {
  overview: "/admin/api/overview",
  fleet: "/admin/api/fleet",
  traffic: "/admin/api/usage",
  schedules: "/admin/api/schedules",
  surfaces: "/admin/api/surfaces",
  reports: "/admin/api/reports",
  activations: "/admin/api/activations",
  retention: "/admin/api/retention",
  access: "/admin/api/access",
};

const defaultSort = {
  fleet: ["last_seen", "desc"],
  traffic: ["last_seen", "desc"],
  schedules: ["updated_at", "desc"],
  surfaces: ["updated_at", "desc"],
  reports: ["ts", "desc"],
};

const state = Object.fromEntries(views.map(view => {
  const sort = defaultSort[view.id] || ["", "desc"];
  return [view.id, { filters: {}, sort: sort[0], dir: sort[1], cursors: [""], cursorIndex: 0, payload: null }];
}));

const el = id => document.getElementById(id);
const workspace = el("workspace");
const nav = el("nav");
const statusRail = el("statusRailEl");
const syncStatus = el("syncStatus");
const drawer = el("drawer");
const drawerBody = el("drawerBody");
const drawerTitle = el("drawerTitle");
const drawerScrim = el("drawerScrim");
const notices = el("notices");

let activeView = "overview";
let overviewCache = null;
let overviewCachedAt = 0;
let activeController = null;
let tableSequence = 0;
let toastSequence = 0;
let dialogResolve = null;
let dialogVerify = "";
let warmJob = null;
let activeAccessLicenseId = "";
let activeAccessSummary = null;
let accessDetailGeneration = 0;

const rowStores = new Map();

function esc(value) {
  const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(value ?? "").replace(/[&<>"']/g, ch => map[ch]);
}

function text(value, fallback = "—") {
  const clean = String(value ?? "").trim();
  return clean || fallback;
}

function number(value) {
  return Number(value || 0).toLocaleString();
}

function valueAt(row, path) {
  return String(path || "").split(".").reduce((value, key) => value && typeof value === "object" ? value[key] : "", row);
}

function titleCase(value) {
  const clean = text(value, "Unknown");
  const known = { macos: "macOS", ios: "iOS", ipados: "iPadOS", api: "API", iap: "IAP", adsb: "ADS-B" };
  if (known[clean.toLowerCase()]) return known[clean.toLowerCase()];
  return clean.replace(/[_-]+/g, " ").replace(/\b\w/g, char => char.toUpperCase());
}

function dateTime(value) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return text(value);
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(parsed);
}

function age(value) {
  if (!value) return "No signal";
  const then = new Date(value).getTime();
  if (!Number.isFinite(then)) return text(value);
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function ratio(part, total) {
  const denominator = Number(total || 0);
  return denominator ? `${Math.round((Number(part || 0) / denominator) * 100)}%` : "0%";
}

function toneFor(value) {
  const lower = String(value ?? "").toLowerCase();
  if (/failed|error|blocked|revoked|denied|unavailable|disabled/.test(lower)) return "bad";
  if (/stale|recent|pending|manual|partial|warning|missing|not.run|unknown/.test(lower)) return "warn";
  if (/ready|fresh|active|configured|enabled|ok|issued|filed|delivered|complete/.test(lower) || lower === "200") return "good";
  return "muted";
}

function badge(value, tone = "") {
  const clean = text(value);
  return `<span class="badge badge-${esc(tone || toneFor(clean))}"><span class="status-dot status-${esc(tone || toneFor(clean))}" aria-hidden="true"></span>${esc(clean)}</span>`;
}

function safeLink(value, label = "Open") {
  try {
    const url = new URL(String(value || ""));
    if (url.protocol !== "https:") return "—";
    return `<a href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`;
  } catch (_) {
    return "—";
  }
}

function setSync(mode, label) {
  syncStatus.className = `sync-status ${mode}`;
  syncStatus.innerHTML = `<span class="status-dot" aria-hidden="true"></span><span>${esc(label)}</span>`;
}

function toast(message, tone = "", persistent = false) {
  const id = `toast-${++toastSequence}`;
  const item = document.createElement("div");
  item.id = id;
  item.className = `toast ${tone ? `toast-${tone}` : ""}`;
  item.innerHTML = `<span>${esc(message)}</span><button type="button" aria-label="Dismiss notification">&times;</button>`;
  item.querySelector("button").addEventListener("click", () => item.remove());
  notices.appendChild(item);
  if (!persistent) setTimeout(() => item.remove(), 6500);
  return id;
}

function loadingState(label = "Loading operator data") {
  workspace.innerHTML = `<div class="loading-state" role="status"><span class="spinner" aria-hidden="true"></span><strong>${esc(label)}</strong><span>Reading the current relay state&hellip;</span></div>`;
}

function errorState(error) {
  workspace.innerHTML = `<div class="error-state" role="alert"><span class="error-code">!</span><strong>This view could not be loaded</strong><span>${esc(error.message || String(error))}</span><button class="button button-primary" data-command="retry">Try again</button></div>`;
}

function workspaceHead(title, copy, actions = "") {
  return `<header class="workspace-head"><div><h2>${esc(title)}</h2><p>${esc(copy)}</p></div>${actions ? `<div class="workspace-actions">${actions}</div>` : ""}</header>`;
}

function panel(title, copy, body, actions = "", tone = "") {
  return `<section class="panel ${tone === "danger" ? "panel-danger" : ""}"><header class="panel-head"><div><h3>${esc(title)}</h3><p>${esc(copy)}</p></div>${actions ? `<div class="panel-tools">${actions}</div>` : ""}</header>${body}</section>`;
}

function metricCards(items) {
  return `<div class="metric-grid">${items.map(item => `<article class="metric-card ${item.tone ? `tone-${esc(item.tone)}` : ""}"><div class="metric-label">${esc(item.label)}</div><div class="metric-value">${esc(item.value)}</div><div class="metric-sub">${esc(item.sub || "")}</div></article>`).join("")}</div>`;
}

function callout(title, copy, tone = "", icon = "i") {
  return `<div class="callout ${esc(tone)}"><span class="callout-icon" aria-hidden="true">${esc(icon)}</span><div><strong>${esc(title)}</strong><p>${esc(copy)}</p></div></div>`;
}

function facetOptions(facets, key) {
  return Object.keys((facets || {})[key] || {}).filter(Boolean).sort().map(value => [value, titleCase(value)]);
}

function filterBar(key, definitions) {
  const values = state[key].filters;
  const fields = definitions.map(def => {
    const value = values[def.name] ?? "";
    const classes = `field ${def.wide ? "filter-wide" : ""}`;
    if (def.type === "select") {
      const options = (def.options || []).map(option => {
        const pair = Array.isArray(option) ? option : [option, titleCase(option)];
        return `<option value="${esc(pair[0])}" ${String(value).toLowerCase() === String(pair[0]).toLowerCase() ? "selected" : ""}>${esc(pair[1])}</option>`;
      }).join("");
      return `<label class="${classes}"><span>${esc(def.label)}</span><select data-filter="${esc(def.name)}"><option value="">All</option>${options}</select></label>`;
    }
    return `<label class="${classes}"><span>${esc(def.label)}</span><input data-filter="${esc(def.name)}" type="${esc(def.type || "search")}" value="${esc(value)}" placeholder="${esc(def.placeholder || "")}"></label>`;
  }).join("");
  return `<div class="filters"><div class="filter-grid">${fields}<div class="filter-actions"><button class="button button-primary" data-apply-filter="${esc(key)}" type="button">Apply</button><button class="button button-quiet" data-clear-filter="${esc(key)}" type="button">Clear</button></div></div></div>`;
}

function rowLink(label, store, index, sub = "") {
  return `<button class="table-link" type="button" data-inspect-store="${esc(store)}" data-inspect-index="${index}">${esc(text(label))}</button>${sub ? `<span class="cell-sub">${esc(sub)}</span>` : ""}`;
}

function dataTable(key, rows, columns, options = {}) {
  const store = `${key}-${++tableSequence}`;
  rowStores.set(store, { kind: options.kind || key, rows: rows || [] });
  const sortable = options.sortable !== false;
  const headers = columns.map(column => {
    if (!sortable || column.sort === false) return `<th scope="col">${esc(column.label)}</th>`;
    const sortKey = column.sort || column.key;
    const selected = state[key].sort === sortKey;
    const className = selected ? `sort-${state[key].dir}` : "";
    const ariaSort = selected ? (state[key].dir === "asc" ? "ascending" : "descending") : "none";
    return `<th scope="col" aria-sort="${ariaSort}"><button class="sort-button ${className}" type="button" data-sort-view="${esc(key)}" data-sort-key="${esc(sortKey)}">${esc(column.label)}</button></th>`;
  }).join("");
  const body = rows && rows.length ? rows.map((row, index) => `<tr>${columns.map(column => {
    const value = valueAt(row, column.key);
    const rendered = column.render ? column.render(row, index, store) : esc(text(value));
    return `<td>${rendered}</td>`;
  }).join("")}</tr>`).join("") : `<tr><td class="empty-table" colspan="${columns.length}">${esc(options.empty || "No rows match this view.")}</td></tr>`;
  return `<div class="data-table-wrap ${options.scroll === false ? "" : "table-scroll"}"><table class="data-table"><thead><tr>${headers}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function pager(key, payload) {
  const cursor = state[key].cursorIndex * 100;
  const visible = (payload.rows || payload.installs || payload.snapshots || payload.recent_events || payload.licenses || []).length;
  const total = Number(payload.filtered_estimate || 0);
  const start = total ? cursor + 1 : 0;
  const end = Math.min(cursor + visible, total);
  return `<div class="pager"><span>Showing ${number(start)}&ndash;${number(end)} of ${number(total)} filtered rows <span class="muted">(${number(payload.total_estimate || 0)} total)</span></span><span class="pager-actions"><button class="button button-quiet" type="button" data-page-prev="${esc(key)}" ${state[key].cursorIndex === 0 ? "disabled" : ""}>Previous</button><button class="button button-quiet" type="button" data-page-next="${esc(key)}" data-next-cursor="${esc(payload.next_cursor || "")}" ${payload.next_cursor ? "" : "disabled"}>Next</button></span></div>`;
}

function buildParams(key) {
  const params = new URLSearchParams();
  Object.entries(state[key].filters).forEach(([name, value]) => {
    if (value !== "" && value !== null && value !== undefined) params.set(name, String(value));
  });
  const cursor = state[key].cursors[state[key].cursorIndex] || "";
  if (cursor) params.set("cursor", cursor);
  params.set("limit", "100");
  if (state[key].sort) params.set("sort", state[key].sort);
  if (state[key].dir) params.set("dir", state[key].dir);
  return params;
}

async function api(path, options = {}) {
  const request = { headers: { "Accept": "application/json", ...(options.headers || {}) }, ...options };
  const response = await fetch(path, request);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail;
    const message = typeof detail === "string" ? detail : detail && typeof detail === "object" ? detail.message || detail.code : "";
    throw new Error(message || `${response.status} ${response.statusText}`);
  }
  return payload;
}

async function getOverview(force = false, signal = undefined) {
  if (!force && overviewCache && Date.now() - overviewCachedAt < 20000) return overviewCache;
  overviewCache = await api(endpoints.overview, { signal });
  overviewCachedAt = Date.now();
  renderStatusRail(overviewCache);
  updateNavCounts(overviewCache);
  return overviewCache;
}

function renderStatusRail(payload) {
  const providers = Object.values(payload.providers || {});
  const configured = providers.filter(item => item && item.configured).length;
  const authorized = providers.filter(item => item && item.hosted_display_enabled).length;
  const pending = Number(payload.counts?.activation_requests_pending || 0);
  const blocked = Number(payload.counts?.blocked_installs || 0);
  const heartbeat = payload.heartbeat || {};
  const retention = payload.retention || {};
  const cards = [
    { label: "Relay signal", value: heartbeat.fresh ? "Fresh" : heartbeat.recent ? "Recent" : heartbeat.stale ? "Stale" : "Unknown", detail: `${number(heartbeat.fresh)} fresh · ${number(heartbeat.stale)} stale`, tone: heartbeat.stale ? "warn" : heartbeat.fresh ? "good" : "warn", jump: "fleet" },
    { label: "Provider paths", value: `${configured}/${providers.length} keyed`, detail: `${authorized}/${providers.length} hosted paths enabled`, tone: configured === providers.length && authorized === providers.length ? "good" : "warn", jump: "providers" },
    { label: "Access queue", value: pending ? `${number(pending)} pending` : "Clear", detail: `${number(blocked)} blocked installs`, tone: pending || blocked ? "warn" : "good", jump: "activations" },
    { label: "Retention", value: titleCase(retention.status || "not run"), detail: `${number(retention.active_legal_holds)} active holds`, tone: toneFor(retention.status || "not run"), jump: "retention" },
  ];
  statusRail.innerHTML = cards.map(card => `<button class="health-card" type="button" data-jump="${esc(card.jump)}"><span class="status-dot status-${esc(card.tone)}" aria-hidden="true"></span><strong>${esc(card.label)} · ${esc(card.value)}</strong><span>${esc(card.detail)}</span></button>`).join("");
}

function updateNavCounts(payload) {
  const counts = {
    activations: Number(payload.counts?.activation_requests_pending || 0),
    fleet: Number(payload.counts?.blocked_installs || 0),
    reports: Number(payload.counts?.reports_24h || 0),
  };
  document.querySelectorAll("[data-nav-count]").forEach(node => {
    const count = counts[node.dataset.navCount] || 0;
    node.textContent = count ? (count > 99 ? "99+" : String(count)) : "";
    node.hidden = !count;
  });
}

function resetPaging(key) {
  state[key].cursors = [""];
  state[key].cursorIndex = 0;
}

async function loadView(key, force = false) {
  const view = views.find(item => item.id === key) || views[0];
  activeView = view.id;
  setActiveNavigation(view.id);
  el("viewKicker").textContent = view.group;
  el("viewTitle").textContent = view.title;
  document.title = `${view.title} · Local Flight Network Operations`;
  closeSidebar();
  closeDrawer();
  loadingState(`Loading ${view.label.toLowerCase()}`);
  setSync("syncing", "Refreshing");
  if (activeController) activeController.abort();
  activeController = new AbortController();
  rowStores.clear();
  tableSequence = 0;
  try {
    let payload;
    if (key === "providers" || key === "maintenance" || key === "overview") {
      payload = await getOverview(true, activeController.signal);
    } else {
      const params = buildParams(key);
      [payload] = await Promise.all([
        key === "access" ? api("/admin/api/access/search", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ limit: 100, cursor: state[key].cursors[state[key].cursorIndex] || "", ...state[key].filters }),
          signal: activeController.signal,
        }) : api(`${endpoints[key]}${params.toString() ? `?${params}` : ""}`, { signal: activeController.signal }),
        getOverview(force, activeController.signal),
      ]);
    }
    if (activeView !== key) return;
    state[key].payload = payload;
    renderView(key, payload);
    setSync("ready", `Updated ${age(payload.generated_at || overviewCache?.generated_at)}`);
  } catch (error) {
    if (error.name === "AbortError") return;
    setSync("error", "Refresh failed");
    errorState(error);
  }
}

function setActiveNavigation(key) {
  document.querySelectorAll(".nav-item").forEach(button => {
    const active = button.dataset.view === key;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
  });
}

function renderView(key, payload) {
  if (key === "overview") renderOverview(payload);
  else if (key === "fleet") renderFleet(payload);
  else if (key === "traffic") renderTraffic(payload);
  else if (key === "schedules") renderSchedules(payload);
  else if (key === "surfaces") renderSurfaces(payload);
  else if (key === "reports") renderReports(payload);
  else if (key === "activations") renderActivations(payload);
  else if (key === "access") renderAccess(payload);
  else if (key === "providers") renderProviders(payload);
  else if (key === "retention") renderRetention(payload);
  else if (key === "maintenance") renderMaintenance(payload);
}

function renderOverview(payload) {
  const c = payload.counts || {};
  const f = payload.fleet || {};
  const h = payload.heartbeat || {};
  const schedule = payload.shared_schedule || {};
  const surface = payload.surface_cache || {};
  const iap = payload.iap || {};
  const stale = Number(h.stale || 0) + Number(h.unknown || 0);
  const providerIssues = Object.values(payload.providers || {}).filter(item => !item.configured || item.hosted_display_enabled === false).length;
  const attention = [
    { label: "Activation requests", copy: "Waiting for an operator decision", count: c.activation_requests_pending, tone: c.activation_requests_pending ? "warn" : "good", view: "activations" },
    { label: "Blocked installs", copy: "Fleet access currently revoked", count: c.blocked_installs, tone: c.blocked_installs ? "bad" : "good", view: "fleet", filters: { blocked: "true" } },
    { label: "Stale or unknown presence", copy: "No recent heartbeat-quality signal", count: stale, tone: stale ? "warn" : "good", view: "fleet", filters: { presence_status: h.stale ? "stale" : "unknown" } },
    { label: "Provider paths needing review", copy: "Credential or hosted-use authorization incomplete", count: providerIssues, tone: providerIssues ? "warn" : "good", view: "providers" },
  ];
  const providerRows = Object.entries(payload.providers || {}).map(([name, item]) => `<div class="detail-row"><span>${esc(titleCase(name))}</span><strong>${badge(item.hosted_display_enabled ? "Ready" : item.configured ? "Keyed / not authorized" : "Missing", item.hosted_display_enabled ? "good" : "warn")}</strong></div>`).join("");
  workspace.innerHTML =
    workspaceHead("Live operational picture", `Generated ${dateTime(payload.generated_at)} · Month ${text(payload.month)} · presence remains intentionally coarse.`, `<button class="button button-primary" type="button" data-jump="fleet">Find an install</button>`) +
    `<div class="panel-stack">` +
      `<div class="metric-grid">${metricCards([
        { label: "Known installs", value: number(c.known_installs || f.known_installs), sub: `${number(c.active_installs_24h || f.active_installs_24h)} seen in 24h`, tone: "good" },
        { label: "Fresh presence", value: number(h.fresh), sub: `${number(h.recent)} recent · ${number(h.stale)} stale`, tone: h.stale ? "warn" : "good" },
        { label: "Requests · 24h", value: number(c.requests_24h), sub: "All relay service traffic" },
        { label: "Reports · 24h", value: number(c.reports_24h), sub: `${number(iap.failed_24h)} purchase checks failed`, tone: iap.failed_24h ? "warn" : "" },
        { label: "Schedule cache", value: ratio(schedule.cache_hits, Number(schedule.cache_hits || 0) + Number(schedule.upstream_pulls || 0)), sub: `${number(schedule.cache_hits)} hits · ${number(schedule.upstream_pulls)} pulls` },
        { label: "Ground cache", value: ratio(surface.cache_hits, Number(surface.cache_hits || 0) + Number(surface.refresh_count || 0)), sub: `${number(surface.request_count)} requests · ${number(surface.stale_serves)} stale` },
      ]).replace('<div class="metric-grid">','').replace(/<\/div>$/, '')}</div>` +
      `<div class="split-grid split-grid-main">` +
        panel("Operator attention", "The shortest path from a symptom to the relevant workflow.", `<div class="panel-body"><div class="attention-list">${attention.map(item => `<button class="attention-item" type="button" data-jump="${esc(item.view)}" data-jump-filters="${esc(JSON.stringify(item.filters || {}))}"><span class="status-dot status-${esc(item.tone)}" aria-hidden="true"></span><span><strong>${esc(item.label)}</strong><small>${esc(item.copy)}</small></span><span class="attention-count">${number(item.count)}</span><span class="chevron" aria-hidden="true">&rsaquo;</span></button>`).join("")}</div></div>`) +
        panel("Runtime readiness", "Secrets stay masked; authorization is an independent gate.", `<div class="panel-body">${providerRows}<div class="detail-row"><span>Provider revision</span><strong>${esc(text(payload.provider_revision))}</strong></div><div class="detail-row"><span>Retention</span><strong>${badge(payload.retention?.status || "not run")}</strong></div><div class="detail-row"><span>Ground cache</span><strong>${badge(payload.features?.airport_ground_cache ? "Enabled" : "Disabled")}</strong></div></div>`) +
      `</div>` +
      panel("Service footprint", "A compact view of product paths using this relay.", `<div class="panel-body">${metricCards([
        { label: "Companion installs", value: number(c.companion_installs), sub: "LAN or remote companion" },
        { label: "Matrix installs", value: number(c.matrix_installs), sub: "Matrix endpoints present" },
        { label: "Active tokens", value: number(c.activation_tokens_active), sub: `${number(c.activation_tokens_revoked)} revoked` },
        { label: "Verified support", value: number(c.iap_verified_total), sub: `${number(c.iap_attempts_24h)} checks in 24h` },
      ])}</div>`) +
    `</div>`;
}

function renderFleet(payload) {
  const facets = payload.facets || {};
  const rows = payload.rows || payload.installs || [];
  const filters = filterBar("fleet", [
    { name: "q", label: "Search", placeholder: "Fingerprint, version, airport…", wide: true },
    { name: "presence_status", label: "Presence", type: "select", options: facetOptions(facets, "presence_status") },
    { name: "status", label: "Access state", type: "select", options: facetOptions(facets, "status") },
    { name: "plan", label: "Plan", type: "select", options: facetOptions(facets, "plan") },
    { name: "os_family", label: "Operating system", type: "select", options: facetOptions(facets, "os_family") },
    { name: "effective_gui", label: "Interface", type: "select", options: facetOptions(facets, "effective_gui") },
    { name: "app_version", label: "App version", type: "select", options: facetOptions(facets, "app_version") },
    { name: "airport_iata", label: "Airport", placeholder: "ZRH" },
    { name: "has_companion", label: "Companion", type: "select", options: [["true", "Present"], ["false", "Not present"]] },
    { name: "has_matrix", label: "Matrix", type: "select", options: [["true", "Present"], ["false", "Not present"]] },
    { name: "blocked", label: "Blocked", type: "select", options: [["true", "Blocked"], ["false", "Not blocked"]] },
    { name: "managed", label: "Managed", type: "select", options: [["true", "Managed"], ["false", "Community"]] },
  ]);
  const table = dataTable("fleet", rows, [
    { key: "install_fingerprint", label: "Install", render: (row, index, store) => rowLink(row.install_fingerprint, store, index, row.plan || "community") },
    { key: "presence_status", label: "Presence", render: row => `${badge(row.presence_status)}<span class="cell-sub">${esc(titleCase(row.presence_source))} · ${esc(age(row.last_heartbeat_at || row.last_checkin_at || row.last_relay_activity_at))}</span>` },
    { key: "last_seen", label: "Last seen", render: row => `<span class="cell-main">${esc(dateTime(row.last_seen))}</span><span class="cell-sub">${esc(age(row.last_seen))}</span>` },
    { key: "os_family", label: "Platform", render: row => `<span class="cell-main">${esc(text(row.os_family))}</span><span class="cell-sub">${esc(text(row.effective_gui || row.requested_gui))} · ${esc(text(row.arch))}</span>` },
    { key: "app_version", label: "Version", render: row => `<span class="mono">${esc(text(row.app_version))}</span><span class="cell-sub">${esc(titleCase(row.client_kind))}</span>` },
    { key: "current_lane.airport_iata", label: "Current lane", render: row => `<span class="cell-main mono">${esc(text(valueAt(row, "current_lane.airport_iata")))}</span><span class="cell-sub">${esc(text(valueAt(row, "current_lane.timezone")))}</span>` },
    { key: "schedule_calls", label: "Usage", render: row => `<span class="cell-main">${number(row.schedule_calls)} / ${number(row.radar_calls)}</span><span class="cell-sub">schedule / radar</span>` },
    { key: "status", label: "Access", render: row => `${badge(row.status)}${row.blocked_reason ? `<span class="cell-sub bad-text">${esc(row.blocked_reason)}</span>` : ""}` },
  ]);
  const metrics = payload.metrics || {};
  workspace.innerHTML = workspaceHead("Install registry", "Search, filter, and inspect without exposing raw install identifiers.", `<button class="button button-quiet" type="button" data-jump="activations">Access control</button>`) +
    `<div class="panel-stack">${metricCards([
      { label: "Known", value: number(metrics.known_installs), sub: "All fleet records" },
      { label: "Fresh", value: number(metrics.presence_fresh), sub: `${number(metrics.presence_recent)} recent`, tone: "good" },
      { label: "Stale", value: number(metrics.presence_stale), sub: `${number(metrics.presence_unknown)} unknown`, tone: metrics.presence_stale ? "warn" : "good" },
      { label: "Managed", value: number(metrics.managed_installs), sub: `${number(metrics.blocked_installs)} blocked`, tone: metrics.blocked_installs ? "bad" : "" },
      { label: "Companion", value: number(metrics.companion_installs), sub: "At least one companion" },
      { label: "Matrix", value: number(metrics.matrix_installs), sub: "At least one matrix" },
    ])}${panel("Fleet", "Select a fingerprint to inspect configuration and scoped controls.", `${filters}${table}${pager("fleet", payload)}`)}</div>`;
}

function renderTraffic(payload) {
  const rows = payload.rows || [];
  const requests = payload.requests?.rows || [];
  const summary = payload.summary || [];
  const totalCalls = summary.reduce((sum, row) => sum + Number(row.calls || 0), 0);
  const subjects = summary.reduce((sum, row) => sum + Number(row.subjects || 0), 0);
  const errors = requests.filter(row => row.error).length;
  const filters = filterBar("traffic", [
    { name: "q", label: "Search", placeholder: "Service, subject, status…", wide: true },
    { name: "service", label: "Service", placeholder: "radar" },
    { name: "plan", label: "Plan", type: "select", options: facetOptions(payload.facets, "plan") },
    { name: "status", label: "Request status", type: "select", options: [["error", "Errors only"], ["200", "200"], ["429", "429"], ["500", "500"]] },
  ]);
  const usageTable = dataTable("traffic", rows, [
    { key: "service", label: "Service", render: row => `<span class="cell-main">${esc(titleCase(row.service))}</span><span class="cell-sub">${esc(text(row.month))}</span>` },
    { key: "plan", label: "Plan", render: row => badge(row.plan) },
    { key: "calls", label: "Calls", render: row => `<span class="cell-main mono">${number(row.calls)}</span>` },
    { key: "subject.fingerprint", label: "Subject", render: (row, index, store) => rowLink(valueAt(row, "subject.fingerprint") || valueAt(row, "subject.tag"), store, index, titleCase(valueAt(row, "subject.kind"))) },
    { key: "last_seen", label: "Last seen", render: row => `<span class="cell-main">${esc(dateTime(row.last_seen))}</span><span class="cell-sub">${esc(age(row.last_seen))}</span>` },
  ], { kind: "usage" });
  const requestTable = dataTable("traffic", requests, [
    { key: "ts", label: "Time", render: (row, index, store) => rowLink(dateTime(row.ts), store, index, age(row.ts)), sort: false },
    { key: "install_fingerprint", label: "Install", render: row => `<span class="mono">${esc(text(row.install_fingerprint))}</span>`, sort: false },
    { key: "service", label: "Service", render: row => esc(titleCase(row.service)), sort: false },
    { key: "scope", label: "Scope", render: row => esc(text(row.scope)), sort: false },
    { key: "status", label: "Status", render: row => badge(row.status, row.error ? "bad" : "good"), sort: false },
    { key: "latency_ms", label: "Latency", render: row => `<span class="mono">${number(row.latency_ms)} ms</span>`, sort: false },
  ], { kind: "request", sortable: false });
  const summaryTable = dataTable("traffic", summary, [
    { key: "service", label: "Service", render: row => esc(titleCase(row.service)) },
    { key: "plan", label: "Plan", render: row => badge(row.plan) },
    { key: "calls", label: "Calls", render: row => number(row.calls) },
    { key: "subjects", label: "Subjects", render: row => number(row.subjects) },
    { key: "last_seen", label: "Last seen", render: row => dateTime(row.last_seen) },
  ], { kind: "usage-summary", sortable: false, scroll: false });
  workspace.innerHTML = workspaceHead("Traffic and quota", `Usage month ${text(payload.month)}. Request rows are sanitized and capped by the relay.`, `<button class="button button-quiet" type="button" data-jump="maintenance">Counter controls</button>`) +
    `<div class="panel-stack">${metricCards([
      { label: "Service calls", value: number(totalCalls), sub: "Across summary rows" },
      { label: "Subjects", value: number(subjects), sub: "Distinct per service/plan" },
      { label: "Request errors", value: number(errors), sub: "On this loaded page", tone: errors ? "bad" : "good" },
      { label: "Service groups", value: number(summary.length), sub: "Service and plan pairs" },
    ])}${panel("Service totals", "Aggregated monthly counters by service and access plan.", summaryTable)}${panel("Usage records", "Filterable subject-level monthly consumption.", `${filters}${usageTable}${pager("traffic", payload)}`)}${panel("Recent request health", "Transport outcomes for the same filter set.", requestTable)}</div>`;
}

function renderSchedules(payload) {
  const rows = payload.rows || payload.snapshots || [];
  const interests = payload.client_interests || [];
  const hits = rows.reduce((sum, row) => sum + Number(row.cache_hits || 0), 0);
  const pulls = rows.reduce((sum, row) => sum + Number(row.upstream_pulls || 0), 0);
  const stale = rows.reduce((sum, row) => sum + Number(row.stale_serves || 0), 0);
  const filters = filterBar("schedules", [
    { name: "q", label: "Search", placeholder: "Airport, provider, schema…", wide: true },
    { name: "airport_iata", label: "Airport", placeholder: "ZRH" },
    { name: "cache_state", label: "Cache state", type: "select", options: facetOptions(payload.facets, "last_cache_state") },
  ]);
  const table = dataTable("schedules", rows, [
    { key: "airport_iata", label: "Window", render: (row, index, store) => rowLink(row.airport_iata, store, index, `${text(row.timezone)} · ${number(row.display_horizon_hours)}h`) },
    { key: "provider", label: "Provider", render: row => `<span class="cell-main">${esc(titleCase(row.provider))}</span><span class="cell-sub">${esc(text(row.planner_version))}</span>` },
    { key: "client_accesses", label: "Client serves", render: row => number(row.client_accesses) },
    { key: "upstream_pulls", label: "Upstream", render: row => number(row.upstream_pulls) },
    { key: "cache_hits", label: "Cache hits", render: row => number(row.cache_hits) },
    { key: "last_cache_state", label: "State", render: row => `${badge(row.last_cache_state)}${row.last_error ? `<span class="cell-sub bad-text">${esc(row.last_error)}</span>` : ""}` },
    { key: "updated_at", label: "Updated", render: row => `<span class="cell-main">${esc(dateTime(row.updated_at))}</span><span class="cell-sub">${esc(age(row.updated_at))}</span>` },
  ]);
  const interestsTable = dataTable("schedules", interests, [
    { key: "install_fingerprint", label: "Install", render: (row, index, store) => rowLink(row.install_fingerprint, store, index, row.plan) },
    { key: "airport_iata", label: "Airport", render: row => `<span class="mono">${esc(text(row.airport_iata))}</span>` },
    { key: "display_horizon_hours", label: "Window", render: row => `${number(row.display_grace_minutes)}m / ${number(row.display_horizon_hours)}h` },
    { key: "refresh_seconds", label: "Cadence", render: row => `${number(row.refresh_seconds)}s` },
    { key: "last_seen", label: "Last seen", render: row => dateTime(row.last_seen) },
  ], { kind: "interest", sortable: false });
  workspace.innerHTML = workspaceHead("Shared schedule windows", "Each row is a canonical airport, timezone, and display-window cache lane shared by clients.") +
    `<div class="panel-stack">${metricCards([
      { label: "Cached windows", value: number(payload.total_estimate), sub: `${number(rows.length)} loaded` },
      { label: "Hit ratio", value: ratio(hits, hits + pulls), sub: `${number(hits)} hits · ${number(pulls)} pulls` },
      { label: "Stale serves", value: number(stale), sub: "Across the loaded page", tone: stale ? "warn" : "good" },
      { label: "Client interests", value: number(interests.length), sub: "Latest bounded rows" },
    ])}${panel("Schedule cache", "Select an airport window for complete cache metadata.", `${filters}${table}${pager("schedules", payload)}`)}${panel("Current client interests", "The bounded operator view of the lanes installs are watching.", interestsTable)}</div>`;
}

function renderWarmJob() {
  if (!warmJob) return "";
  const status = warmJob.status || "queued";
  const results = warmJob.results || [];
  return `<div class="callout ${toneFor(status) === "bad" ? "danger" : toneFor(status) === "warn" ? "warn" : ""}"><span class="callout-icon" aria-hidden="true">W</span><div><strong>Warm job ${esc(text(warmJob.job_id))} · ${esc(titleCase(status))}</strong><p>${number(results.length || warmJob.requested)} airport results · ${number(warmJob.fresh_count)} fresh · ${number(warmJob.refreshed_count)} refreshed · ${number(warmJob.failed_count)} failed</p></div></div>`;
}

function renderSurfaces(payload) {
  const rows = payload.rows || payload.snapshots || [];
  const hits = rows.reduce((sum, row) => sum + Number(row.cache_hits || 0), 0);
  const requests = rows.reduce((sum, row) => sum + Number(row.request_count || 0), 0);
  const stale = rows.reduce((sum, row) => sum + Number(row.stale_serves || 0), 0);
  const filters = filterBar("surfaces", [
    { name: "q", label: "Search", placeholder: "Airport, provider, state…", wide: true },
    { name: "airport_iata", label: "Airport", placeholder: "ZRH" },
    { name: "cache_state", label: "Cache state", type: "select", options: facetOptions(payload.facets, "last_cache_state") },
  ]);
  const table = dataTable("surfaces", rows, [
    { key: "airport_iata", label: "Airport", render: (row, index, store) => rowLink(row.airport_iata || row.airport_icao, store, index, row.airport_icao) },
    { key: "radius_nm", label: "Coverage", render: row => `<span class="cell-main">${number(row.radius_nm)} NM</span><span class="cell-sub">${number(row.feature_count)} features</span>` },
    { key: "provider", label: "Provider", render: row => `<span class="cell-main">${esc(titleCase(row.provider))}</span><span class="cell-sub">${esc(text(row.schema_version))}</span>` },
    { key: "request_count", label: "Requests", render: row => number(row.request_count) },
    { key: "cache_hits", label: "Hits", render: row => number(row.cache_hits) },
    { key: "last_cache_state", label: "State", render: row => `${badge(row.last_cache_state)}${row.last_error ? `<span class="cell-sub bad-text">${esc(row.last_error)}</span>` : ""}` },
    { key: "updated_at", label: "Updated", render: row => `<span class="cell-main">${esc(dateTime(row.updated_at))}</span><span class="cell-sub">${esc(age(row.updated_at))}</span>` },
  ]);
  const groundEnabled = Boolean(overviewCache?.features?.airport_ground_cache);
  workspace.innerHTML = workspaceHead("Airport ground layers", "Warm only known airports. Jobs are queued and bounded by the relay.", `<button class="button button-primary" type="button" data-command="warm-cache" ${groundEnabled ? "" : "disabled"}>Warm cache</button><button class="button button-quiet" type="button" data-command="surface-override" ${groundEnabled ? "" : "disabled"}>Airport override</button>`) +
    `<div class="panel-stack">${groundEnabled ? callout("Ground-cache route enabled", overviewCache?.features?.ground_prewarm ? "Scheduled prewarming is enabled; manual jobs remain available." : "Automatic prewarming is off; manual jobs remain available.", "", "G") : callout("Ground-cache route disabled", "Enable RELAY_AIRPORT_GROUND_ENABLED in the deployment configuration before starting jobs.", "warn", "!")}${renderWarmJob()}${metricCards([
      { label: "Cached airports", value: number(payload.total_estimate), sub: `${number(rows.length)} loaded` },
      { label: "Requests", value: number(requests), sub: "Across the loaded page" },
      { label: "Cache hits", value: number(hits), sub: ratio(hits, requests) + " of requests" },
      { label: "Stale serves", value: number(stale), sub: "Across the loaded page", tone: stale ? "warn" : "good" },
    ])}${panel("Ground cache", "Inspect geometry counts and cache lifecycle without exposing raw OSM payloads.", `${filters}${table}${pager("surfaces", payload)}`)}</div>`;
}

function renderReports(payload) {
  const rows = payload.rows || payload.recent_events || [];
  const summaries = payload.summary_24h || [];
  const dedupe = payload.dedupe || [];
  const filed = summaries.filter(row => /filed|delivered|created/i.test(row.status)).reduce((sum, row) => sum + Number(row.reports || 0), 0);
  const failures = summaries.filter(row => /fail|error/i.test(row.status)).reduce((sum, row) => sum + Number(row.reports || 0), 0);
  const filters = filterBar("reports", [
    { name: "q", label: "Search", placeholder: "Install, type, team…", wide: true },
    { name: "report_type", label: "Report type", type: "select", options: facetOptions(payload.facets, "report_type") },
    { name: "origin", label: "Origin", type: "select", options: facetOptions(payload.facets, "origin") },
    { name: "team", label: "Team", type: "select", options: facetOptions(payload.facets, "team") },
    { name: "status", label: "Status", type: "select", options: facetOptions(payload.facets, "status") },
  ]);
  const summaryTable = dataTable("reports", summaries, [
    { key: "report_type", label: "Type", render: row => esc(titleCase(row.report_type)) },
    { key: "origin", label: "Origin", render: row => esc(titleCase(row.origin)) },
    { key: "team", label: "Team", render: row => esc(text(row.team)) },
    { key: "status", label: "Status", render: row => badge(row.status) },
    { key: "reports", label: "Events", render: row => number(row.reports) },
    { key: "installs", label: "Installs", render: row => number(row.installs) },
    { key: "last_seen", label: "Last seen", render: row => dateTime(row.last_seen) },
  ], { kind: "report-summary", sortable: false, scroll: false });
  const eventTable = dataTable("reports", rows, [
    { key: "ts", label: "Time", render: (row, index, store) => rowLink(dateTime(row.ts), store, index, age(row.ts)) },
    { key: "install_fingerprint", label: "Install", render: row => `<span class="mono">${esc(text(row.install_fingerprint))}</span>` },
    { key: "report_type", label: "Type", render: row => esc(titleCase(row.report_type)) },
    { key: "origin", label: "Origin", render: row => esc(titleCase(row.origin)) },
    { key: "team", label: "Team", render: row => esc(text(row.team)) },
    { key: "status", label: "Status", render: row => badge(row.status) },
  ], { kind: "report" });
  const dedupeTable = dataTable("reports", dedupe, [
    { key: "report_type", label: "Group", render: (row, index, store) => rowLink(titleCase(row.report_type), store, index, `${titleCase(row.origin)} · ${text(row.team)}`), sort: false },
    { key: "count", label: "Count", render: row => number(row.count), sort: false },
    { key: "first_seen", label: "First", render: row => dateTime(row.first_seen), sort: false },
    { key: "last_seen", label: "Last", render: row => dateTime(row.last_seen), sort: false },
    { key: "issue_url", label: "Issue", render: row => safeLink(row.issue_url), sort: false },
  ], { kind: "report-dedupe", sortable: false });
  workspace.innerHTML = workspaceHead("Report gateway", "Only sanitized routing metadata appears here; report bodies and private diagnostics are not retained in this view.") +
    `<div class="panel-stack">${metricCards([
      { label: "24h groups", value: number(summaries.length), sub: "Type/origin/team/status" },
      { label: "Filed", value: number(filed), sub: "Delivered events", tone: "good" },
      { label: "Failures", value: number(failures), sub: "Delivery errors", tone: failures ? "bad" : "good" },
      { label: "Dedupe groups", value: number(dedupe.length), sub: "Bounded recent set" },
    ])}${panel("Delivery summary · 24h", "Aggregated gateway outcomes.", summaryTable)}${panel("Recent report events", "Filter and open a row for routing metadata.", `${filters}${eventTable}${pager("reports", payload)}`)}${panel("Deduplication groups", "Repeated events may update an existing issue instead of creating a new one.", dedupeTable)}</div>`;
}

function renderActivations(payload) {
  const tokens = payload.tokens || [];
  const requests = payload.requests || [];
  const blocked = payload.blocked_installs || [];
  const pending = requests.filter(row => /pending|manual_review/i.test(row.status)).length;
  const revoked = tokens.filter(row => row.revoked).length;
  const tokenTable = dataTable("activations", tokens, [
    { key: "token_prefix", label: "Token", render: (row, index, store) => rowLink(row.token_prefix, store, index, row.label || "Unlabelled") },
    { key: "schedule_limit", label: "Schedule limit", render: row => number(row.schedule_limit) },
    { key: "radar_limit", label: "Radar limit", render: row => number(row.radar_limit) },
    { key: "bound_install_fingerprint", label: "Binding", render: row => `<span class="mono">${esc(text(row.bound_install_fingerprint, "Unbound"))}</span>` },
    { key: "last_seen", label: "Last seen", render: row => dateTime(row.last_seen) },
    { key: "revoked", label: "State", render: row => badge(row.revoked ? "Revoked" : "Active", row.revoked ? "bad" : "good") },
  ], { kind: "token", sortable: false });
  const requestTable = dataTable("activations", requests, [
    { key: "request_id", label: "Request", render: (row, index, store) => rowLink(row.request_id, store, index, row.display_name || row.install_fingerprint) },
    { key: "airport_iata", label: "Airport", render: row => `<span class="mono">${esc(text(row.airport_iata))}</span>` },
    { key: "requested_mode", label: "Mode", render: row => esc(titleCase(row.requested_mode)) },
    { key: "app_version", label: "Version", render: row => `<span class="mono">${esc(text(row.app_version))}</span>` },
    { key: "status", label: "Status", render: row => badge(row.status) },
    { key: "updated_at", label: "Updated", render: row => dateTime(row.updated_at) },
  ], { kind: "activation-request", sortable: false });
  const blockedTable = dataTable("activations", blocked, [
    { key: "install_fingerprint", label: "Install", render: (row, index, store) => rowLink(row.install_fingerprint, store, index, row.reason) },
    { key: "reason", label: "Reason", render: row => esc(text(row.reason)) },
    { key: "created_at", label: "Blocked at", render: row => dateTime(row.created_at) },
  ], { kind: "blocked-install", sortable: false, scroll: false });
  workspace.innerHTML = workspaceHead("Access and activation", "Issue credentials deliberately. New and rotated tokens are displayed exactly once.", `<button class="button button-primary" type="button" data-command="create-token">Create managed token</button>`) +
    `<div class="panel-stack">${metricCards([
      { label: "Managed tokens", value: number(tokens.length), sub: `${number(revoked)} revoked` },
      { label: "Pending review", value: number(pending), sub: "Needs operator decision", tone: pending ? "warn" : "good" },
      { label: "Blocked installs", value: number(blocked.length), sub: "Access currently revoked", tone: blocked.length ? "bad" : "good" },
      { label: "Unbound tokens", value: number(tokens.filter(row => !row.bound_install_fingerprint && !row.revoked).length), sub: "Active and ready to bind" },
    ])}${panel("Managed tokens", "Select a prefix to rotate, revoke, unbind, reset counters, or delete.", tokenTable)}${panel("Activation queue", "Only manual-review rows can be issued. Any returned token is one-time.", requestTable)}${panel("Blocked installs", "Select an install to restore access.", blockedTable)}</div>`;
}

function maskedRef(value, lead = 6, tail = 4) {
  const text = String(value || "").trim();
  if (!text) return "-";
  if (text.length <= lead + tail + 1) return `${text.slice(0, Math.min(lead, text.length))}…`;
  return `${text.slice(0, lead)}…${text.slice(-tail)}`;
}

function licenseKeyRef(row) {
  const supplied = String(row?.key_ref || "").trim();
  if (supplied) return supplied;
  const prefix = String(row?.key_prefix || "").trim();
  const tail = String(row?.key_last_four || "").trim();
  return prefix && tail ? `${prefix}…${tail}` : "not issued";
}

function emptyTable(message) {
  return `<div class="data-table-wrap table-scroll"><table class="data-table"><tbody><tr><td class="muted">${esc(message)}</td></tr></tbody></table></div>`;
}

function accessLicenseTable(rows) {
  return dataTable("access", rows, [
    { key: "key_ref", label: "Key reference", render: (row, index, store) => rowLink(licenseKeyRef(row), store, index, row.product_code) },
    { key: "purchase_source", label: "Source", render: row => esc(titleCase(row.purchase_source)) },
    { key: "status", label: "Status", render: row => badge(row.status) },
    { key: "device_name", label: "Receiver", render: row => esc(text(row.device_name, "No active receiver")) },
    { key: "install_ref", label: "Install reference", render: row => esc(maskedRef(row.install_ref)) },
    { key: "created_at", label: "Created", render: row => dateTime(row.created_at) },
    { key: "last_seen_at", label: "Activity", render: row => dateTime(row.last_seen_at || row.activated_at || row.updated_at) },
  ], { kind: "access_license", sortable: false, empty: "No Relay Access licenses recorded." });
}

function accessDeliveryTable(rows, licenses) {
  if (!rows.length) return emptyTable("No license deliveries recorded.");
  const refs = new Map(licenses.map(row => [row.license_id, licenseKeyRef(row)]));
  return `<div class="data-table-wrap table-scroll access-secondary-table"><table class="data-table"><thead><tr>
    <th>License</th><th>Channel</th><th>Purpose</th><th>Status</th><th>Attempts</th><th>Next attempt</th><th>Detail</th>
  </tr></thead><tbody>${rows.map(row => `<tr>
    <td class="mono">${esc(refs.get(row.license_id) || maskedRef(row.license_id))}</td>
    <td>${esc(row.channel || "-")}</td><td>${esc(row.purpose || "-")}</td><td>${badge(row.status)}</td>
    <td>${Number(row.attempt_count || 0).toLocaleString()}</td><td>${esc(dateTime(row.next_attempt_at || row.delivered_at || row.updated_at))}</td>
    <td>${esc(row.detail_code || "-")}</td>
  </tr>`).join("")}</tbody></table></div>`;
}

function accessEventTable(rows) {
  if (!rows.length) return emptyTable("No purchase events recorded.");
  return `<div class="data-table-wrap table-scroll access-secondary-table"><table class="data-table"><thead><tr>
    <th>Provider</th><th>Event</th><th>Status</th><th>Detail</th><th>Created</th><th>Processed</th><th>Action</th>
  </tr></thead><tbody>${rows.map(row => `<tr>
    <td>${esc(row.provider || "-")}</td><td>${esc(row.event_type || "-")}</td><td>${badge(row.status)}</td>
    <td>${esc(row.detail_code || "-")}</td><td>${esc(dateTime(row.created_at))}</td><td>${esc(dateTime(row.processed_at))}</td>
    <td>${["reconciliation_required", "failed"].includes(String(row.status).toLowerCase())
      ? `<button class="button button-quiet" type="button" data-event-action="mark_resolved" data-event-ref="${esc(row.event_ref || "")}">Resolve</button>`
      : "-"}</td>
  </tr>`).join("")}</tbody></table></div>`;
}

function accessNotificationTable(rows, licenses) {
  if (!rows.length) return emptyTable("No queued notifications or provider operations.");
  const refs = new Map(licenses.map(row => [row.license_id, licenseKeyRef(row)]));
  return `<div class="data-table-wrap table-scroll access-secondary-table"><table class="data-table"><thead><tr>
    <th>License</th><th>Channel</th><th>Purpose</th><th>Status</th><th>Attempts</th><th>Next attempt</th><th>Detail</th>
  </tr></thead><tbody>${rows.map(row => `<tr>
    <td class="mono">${esc(refs.get(row.license_id) || maskedRef(row.license_id))}</td>
    <td>${esc(row.channel || "-")}</td><td>${esc(row.purpose || "-")}</td><td>${badge(row.status)}</td>
    <td>${Number(row.attempt_count || 0).toLocaleString()}</td><td>${esc(dateTime(row.next_attempt_at || row.delivered_at || row.updated_at))}</td>
    <td>${esc(row.detail_code || "-")}</td>
  </tr>`).join("")}</tbody></table></div>`;
}


function renderAccess(payload) {
  const licenses = payload.licenses || [];
  const deliveries = payload.deliveries || [];
  const notifications = payload.notifications || [];
  const events = payload.purchase_events || [];
  const reconciliation = payload.reconciliation_ready || {};
  const health = payload.reconciliation_health || [];
  const backup = payload.backup || {};
  const failed = deliveries.filter(row => row.status === "failed").length;
  const pending = deliveries.filter(row => ["pending", "sending"].includes(row.status)).length;
  const issues = events.filter(row => !["processed", "completed", "success"].includes(row.status)).length;
  const filters = filterBar("access", [
    { name: "q", label: "Secure search", placeholder: "License, key reference, or exact email", wide: true },
    { name: "source", label: "Purchase source", type: "select", options: ["stripe", "apple_app", "google_play_product"] },
    { name: "state", label: "License state", type: "select", options: ["active", "suspended", "refunded", "revoked"] },
  ]);
  const cards = metricCards([
    { label: "Licenses", value: number(payload.filtered_estimate), sub: "Matching licenses" },
    { label: "Delivery queue", value: number(pending + failed), sub: pending + " pending / " + failed + " failed", tone: failed ? "bad" : "good" },
    { label: "Event issues", value: number(issues), sub: events.length + " recent events", tone: issues ? "warn" : "good" },
    { label: "Access mode", value: titleCase(payload.mode), sub: "Schema " + text(payload.schema_version) },
    { label: "Configuration", value: payload.configuration_ready ? "Ready" : "Not ready", sub: "License service preflight", tone: payload.configuration_ready ? "good" : "bad" },
    { label: "License delivery", value: payload.delivery_ready ? "Ready" : "Not ready", sub: "Email and recovery delivery", tone: payload.delivery_ready ? "good" : "warn" },
    { label: "Sales", value: payload.sales_enabled ? "Enabled" : "Disabled", sub: "Commercial checkout gate" },
    { label: "Mobile ownership", value: payload.mobile_ownership_enabled ? "Enabled" : "Disabled", sub: "Apple " + (reconciliation.apple ? "ready" : "not ready") + " / Google " + (reconciliation.google ? "ready" : "not ready") },
  ]);
  const healthTable = dataTable("access", health, [
    { key: "provider", label: "Provider" },
    { key: "status", label: "Status", render: row => badge(row.status) },
    { key: "last_success_at", label: "Last success", render: row => dateTime(row.last_success_at) },
    { key: "last_attempt_at", label: "Last attempt", render: row => dateTime(row.last_attempt_at) },
    { key: "next_attempt_at", label: "Next attempt", render: row => dateTime(row.next_attempt_at) },
    { key: "detail_code", label: "Detail" },
  ], { sortable: false, empty: "No provider reconciliation checks recorded." });
  const backupBody = '<div class="panel-body">' + detailSection("Backup status", [
    ["Health", backup.healthy ? "Healthy" : "Attention"],
    ["Latest verified backup", dateTime(backup.last_backup_at)],
    ["Detail", backup.detail_code],
  ]) + '<div class="action-buttons"><button class="button button-primary" type="button" data-access-backup="create_backup">Create verified backup</button><button class="button button-quiet" type="button" data-access-backup="verify_latest">Verify latest backup</button></div></div>';
  workspace.innerHTML = workspaceHead("Relay Access", "Licenses, receivers, recovery delivery, and purchase reconciliation. Key references and ownership evidence remain masked.") +
    '<div class="panel-stack">' + cards +
    panel("Universal licenses", "One portable license and one active independent receiver. Exact email searches use a private request body.", filters + accessLicenseTable(licenses) + pager("access", payload)) +
    panel("Delivery diagnostics", "License and delivery identifiers remain masked.", accessDeliveryTable(deliveries, licenses)) +
    panel("Notification and provider queue", "Destinations and purchase handles stay hidden.", accessNotificationTable(notifications, licenses)) +
    panel("Provider reconciliation health", "Current authority checks for production access.", healthTable) +
    panel("Encrypted backups", "Create and verify recoverable encrypted database snapshots.", backupBody) +
    panel("Purchase events", "Sanitized provider events and reconciliation outcomes.", accessEventTable(events)) + '</div>';
}

async function fetchAccessDetail(licenseId) {
  return api(`/admin/api/access/${encodeURIComponent(licenseId)}`);
}

async function openAccessDrawer(summary) {
  if (!summary?.license_id) return;
  const generation = ++accessDetailGeneration;
  activeAccessLicenseId = summary.license_id;
  activeAccessSummary = summary;
  drawer.dataset.kind = "access_license";
  delete drawer.dataset.row;
  drawerTitle.textContent = "Relay Access · " + licenseKeyRef(summary);
  drawerBody.innerHTML = '<p class="access-operator-note">Loading masked license diagnostics…</p>';
  drawer.removeAttribute("inert");
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  drawerScrim.classList.add("open");
  el("drawerClose").focus();
  try {
    const detail = await fetchAccessDetail(summary.license_id);
    if (generation !== accessDetailGeneration || activeAccessLicenseId !== summary.license_id) return;
    activeAccessSummary = { ...summary, ...(detail.license || {}), license_id: summary.license_id };
    renderAccessDrawer(activeAccessSummary, detail);
  } catch (error) {
    if (generation !== accessDetailGeneration) return;
    drawerBody.innerHTML = '<p class="access-load-error">' + esc(error.message || "Unable to load license details.") + '</p>';
  }
}

async function runAccessAction(action) {
  const licenseId = activeAccessLicenseId;
  if (!licenseId || !activeAccessSummary) return;
  const ref = licenseKeyRef(activeAccessSummary);
  const descriptions = {
    revoke_license: "Disable the license and revoke its active receiver credential.",
    suspend_license: "Suspend the license and revoke its active receiver credential.",
    reactivate_license: "Restore license eligibility. The receiver must activate again.",
    revoke_receiver: "Revoke the active receiver credential. The device must activate again.",
    retry_deliveries: "Queue failed license email deliveries for retry.",
    retry_notifications: "Retry failed recovery, protection, and provider notifications.",
    retry_reconciliation: "Ask the purchase provider to reconcile this license now.",
    rotate_key: "Revoke the old key and receiver credential. Send the replacement key only to the protected holder email.",
  };
  if (!descriptions[action]) return;
  const destructive = ["revoke_license", "suspend_license", "revoke_receiver", "rotate_key"].includes(action);
  const values = await ask({ title: titleCase(action) + " · " + ref, copy: descriptions[action],
    confirmLabel: titleCase(action), tone: destructive ? "danger" : "", verify: destructive ? "CONFIRM" : "" });
  if (!values) return;
  await api(`/admin/api/access/${encodeURIComponent(licenseId)}/action`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }),
  });
  toast(action === "rotate_key" ? "Master key rotated. Protected email delivery was queued; no raw key was returned." : "Relay Access action completed.", "good");
  closeDrawer();
  await loadView("access", true);
}

function accessRecordBlock(title, rows, fields) {
  if (!rows.length) {
    return `<section class="detail-section access-records"><h3>${esc(title)}</h3><p class="muted">No records.</p></section>`;
  }
  return `<section class="detail-section access-records"><h3>${esc(title)}</h3>${rows.map((row, idx) => `<article class="access-record">
    <div class="access-record-title"><strong>${esc(fields.heading(row, idx))}</strong>${badge(row.status || row.state || "recorded")}</div>
    ${fields.rows(row).map(([label, value]) => `<div><span>${esc(label)}</span><strong>${esc(text(value))}</strong></div>`).join("")}
  </article>`).join("")}</section>`;
}

function accessDrawerActions(summary, detail) {
  const status = String(detail.license?.status || summary.status || "").toLowerCase();
  const activeReceiver = (detail.activations || []).some(row => String(row.status).toLowerCase() === "active");
  const failedDelivery = (detail.deliveries || []).some(row => String(row.status).toLowerCase() === "failed");
  const failedNotification = (detail.notifications || []).some(row => String(row.status).toLowerCase() === "failed");
  const latestPurchase = (detail.purchases || [])[0] || {};
  const purchaseState = String(latestPurchase.state || "").toLowerCase();
  const authoritativePurchase = ["paid", "purchased"].includes(purchaseState);
  const protectedHolder = Boolean(detail.license?.email_protected ?? summary.email_protected);
  const actions = [];
  if (status === "active") actions.push(`<button class="button button-quiet" type="button" data-access-action="suspend_license">Suspend license</button>`);
  if (status !== "revoked") actions.push(`<button class="button button-danger" type="button" data-access-action="revoke_license">Revoke license</button>`);
  if (["suspended", "revoked"].includes(status) && authoritativePurchase) actions.push(`<button class="button button-good" type="button" data-access-action="reactivate_license">Reactivate license</button>`);
  actions.push(`<button class="button button-danger" type="button" data-access-action="revoke_receiver" ${activeReceiver ? "" : "disabled"}>Revoke receiver</button>`);
  actions.push(`<button class="button button-quiet" type="button" data-access-action="retry_deliveries" ${failedDelivery ? "" : "disabled"}>Retry deliveries</button>`);
  actions.push(`<button class="button button-quiet" type="button" data-access-action="retry_notifications" ${failedNotification ? "" : "disabled"}>Retry notifications</button>`);
  if (["server_authoritative", "device_and_server"].includes(String(latestPurchase.reconciliation_mode || ""))) {
    actions.push(`<button class="button button-quiet" type="button" data-access-action="retry_reconciliation">Retry provider check</button>`);
  }
  actions.push(`<button class="button button-danger" type="button" data-access-action="rotate_key" ${status === "active" && protectedHolder ? "" : "disabled"}>Rotate master key</button>`);
  return actions.join("");
}

function renderAccessDrawer(summary, detail) {
  const license = detail.license || {};
  const displayRef = licenseKeyRef(license) !== "not issued" ? licenseKeyRef(license) : licenseKeyRef(summary);
  drawerTitle.textContent = `Relay Access · ${displayRef}`;
  drawerBody.innerHTML = `<div class="drawer-actions">${accessDrawerActions(summary, detail)}</div>
    <p class="access-operator-note">Suspending, revoking, or rotating a license revokes its active receiver. Rotation sends the replacement key only to the protected holder email; it never appears in admin. Reactivation restores license eligibility, not the old receiver credential.</p>
    ${detailSection("License", [["Key reference", displayRef], ["Product", license.product_code || summary.product_code], ["Purchase source", license.purchase_source || summary.purchase_source], ["Status", license.status || summary.status], ["Email protection", license.email_protected ? "protected" : "not protected"], ["Created", dateTime(license.created_at || summary.created_at)]])}
    ${accessRecordBlock("Receiver history", detail.activations || [], {
      heading: row => `${row.device_name || "Unnamed receiver"} · ${row.device_kind || "unknown"}`,
      rows: row => [["Install reference", maskedRef(row.install_ref)], ["Credential prefix", row.credential_prefix ? `${row.credential_prefix}…` : "-"], ["Activated", dateTime(row.activated_at)], ["Last seen", dateTime(row.last_seen_at)], ["Revoked", dateTime(row.revoked_at)], ["Reason", row.revoke_reason || "-"]]
    })}
    ${accessRecordBlock("Purchase records", detail.purchases || [], {
      heading: row => `${row.provider || "unknown"} · ${row.environment || "unknown"}`,
      rows: row => [["Product", row.product_id], ["Evidence reference", maskedRef(row.evidence_ref)], ["Reconciliation", row.reconciliation_mode || "device only"], ["Last reconciled", dateTime(row.last_reconciled_at)], ["Next check", dateTime(row.next_reconcile_at)], ["Acknowledgement", row.acknowledgement_state || "-"], ["Reason", row.state_reason || "-"], ["Last verified", dateTime(row.last_verified_at)], ["State changed", dateTime(row.state_changed_at)], ["Updated", dateTime(row.updated_at)]]
    })}
    ${accessRecordBlock("Purchase transitions", detail.purchase_transitions || [], {
      heading: row => `${row.from_state || "new"} → ${row.to_state || "unknown"}`,
      rows: row => [["Source", row.source || "authority"], ["Reason", row.reason_code || "-"], ["Changed", dateTime(row.created_at)]]
    })}
    ${accessRecordBlock("Delivery history", detail.deliveries || [], {
      heading: row => `${row.channel || "unknown"} · ${row.purpose || "delivery"}`,
      rows: row => [["Key version", row.key_version], ["Attempts", row.attempt_count], ["Delivered", dateTime(row.delivered_at)], ["Updated", dateTime(row.updated_at)], ["Detail", row.detail_code || "-"]]
    })}
    ${accessRecordBlock("Provider event linkage", detail.events || [], {
      heading: row => `${row.provider || "unknown"} · ${row.event_type || "event"}`,
      rows: row => [["Status", row.status], ["Detail", row.detail_code || "-"], ["Created", dateTime(row.created_at)], ["Processed", dateTime(row.processed_at)]]
    })}
    ${accessRecordBlock("Notification history", detail.notifications || [], {
      heading: row => `${row.channel || "unknown"} · ${row.purpose || "notification"}`,
      rows: row => [["Status", row.status], ["Attempts", row.attempt_count], ["Next retry", dateTime(row.next_attempt_at)], ["Detail", row.detail_code || "-"]]
    })}`;
}


function renderProviders(payload) {
  const config = {
    aerodatabox: { label: "AeroDataBox", field: "aerodatabox_key", copy: "Primary real-schedule path when enabled." },
    aviationstack: { label: "AviationStack", field: "aviationstack_key", copy: "Schedule fallback and sparse-field fill path." },
    rapidapi: { label: "RapidAPI ADS-B", field: "rapidapi_key", copy: "ADS-B Exchange live aircraft path." },
  };
  const cards = Object.entries(config).map(([key, meta]) => {
    const item = payload.providers?.[key] || {};
    const ready = Boolean(item.hosted_display_enabled);
    return `<article class="provider-card"><header><div><h4>${esc(meta.label)}</h4><p>${esc(meta.copy)}</p></div>${badge(ready ? "Ready" : item.configured ? "Path disabled" : "Missing key", ready ? "good" : "warn")}</header><div class="provider-meta"><div><span>Credential</span><strong>${esc(text(item.masked, "missing"))}</strong></div><div><span>Source</span><strong>${esc(titleCase(item.source || "none"))}</strong></div><div><span>Licensed-use gate</span><strong>${esc(item.hosted_authorized ? "Enabled" : "Disabled")}</strong></div><div><span>Effective path</span><strong>${esc(ready ? "Enabled" : "Disabled")}</strong></div></div><label class="field"><span>Replacement key</span><input id="provider-key-${esc(key)}" type="password" autocomplete="new-password" placeholder="Paste new key"></label><div class="provider-actions"><button class="button button-primary" type="button" data-save-provider="${esc(key)}" data-provider-field="${esc(meta.field)}">Save replacement</button><button class="button button-danger" type="button" data-clear-provider="${esc(key)}">Clear override</button></div></article>`;
  }).join("");
  workspace.innerHTML = workspaceHead("Provider control", "Provider credentials and licensed-use gates are independent. Effective paths reflect the current legacy or licensed access mode.", `<span class="badge badge-muted">Revision ${esc(text(payload.provider_revision))}</span>`) +
    `<div class="panel-stack">${callout("Credential safety", "Keys are write-only from this page. Existing values are masked and never returned by the admin APIs.", "", "K")}${panel("Relay providers", "Environment values remain the fallback when no relay-stored override exists.", `<div class="panel-body"><div class="provider-grid">${cards}</div></div>`)}</div>`;
}

function renderRetention(payload) {
  const health = payload.health || {};
  const policy = payload.policy || {};
  const holds = payload.holds || [];
  const labels = {
    request_days: ["Request metadata", "days"], report_event_days: ["Report events", "days"], inactive_install_days: ["Inactive installs", "days"], revoked_token_days: ["Revoked tokens", "days"], revoked_remote_grant_days: ["Revoked remote grants", "days"], iap_event_days: ["Purchase attempts", "days"], iap_verified_days: ["Verified purchases", "days"], provider_snapshot_hours: ["Provider snapshots", "hours"], radar_cache_minutes: ["Radar cache", "minutes"], legal_acceptance_days: ["Legal acceptances", "days"],
  };
  const policyCards = Object.entries(labels).map(([key, pair]) => `<article class="policy-card"><h4>${esc(pair[0])}</h4><strong>${number(policy[key])} ${esc(pair[1])}</strong></article>`).join("");
  const holdTable = dataTable("retention", holds, [
    { key: "hold_id", label: "Hold", render: (row, index, store) => rowLink(row.hold_id, store, index, titleCase(row.category)) },
    { key: "category", label: "Category", render: row => esc(titleCase(row.category)) },
    { key: "reason", label: "Reason", render: row => esc(text(row.reason)) },
    { key: "created_at", label: "Placed", render: row => dateTime(row.created_at) },
    { key: "hold_id", label: "Action", render: row => `<button class="button button-danger" type="button" data-release-hold="${esc(row.hold_id)}">Release</button>` },
  ], { kind: "retention-hold", sortable: false, scroll: false, empty: "No active retention holds." });
  workspace.innerHTML = workspaceHead("Retention controls", "Automated cleanup is independent of request traffic. Holds prevent deletion only for the scoped record.", `<button class="button button-primary" type="button" data-command="run-retention">Run retention now</button><button class="button button-quiet" type="button" data-command="place-hold">Place hold</button>`) +
    `<div class="panel-stack">${metricCards([
      { label: "Last run", value: titleCase(health.status || "not run"), sub: dateTime(health.finished_at), tone: toneFor(health.status || "not run") },
      { label: "Deleted last run", value: number(health.deleted_total), sub: "Rows across retention categories" },
      { label: "Active holds", value: number(health.active_legal_holds), sub: "Scoped retained records", tone: health.active_legal_holds ? "warn" : "good" },
      { label: "Last error", value: text(health.error_code, "None"), sub: health.error_code ? "Review relay logs" : "Maintenance healthy", tone: health.error_code ? "bad" : "good" },
    ])}${panel("Policy windows", "Effective cleanup periods configured in the relay.", `<div class="panel-body"><div class="policy-grid">${policyCards}</div></div>`)}${panel("Active holds", "Release only when the legal or operational reason no longer applies.", holdTable)}</div>`;
}

function renderMaintenance(payload) {
  const limits = payload.limits || {};
  const features = payload.features || {};
  const limitRows = Object.entries(limits).map(([key, value]) => `<div class="detail-row"><span>${esc(titleCase(key))}</span><strong>${number(value)}</strong></div>`).join("");
  const featureRows = Object.entries(features).map(([key, value]) => `<div class="detail-row"><span>${esc(titleCase(key))}</span><strong>${Array.isArray(value) ? esc(value.join(", ") || "None") : typeof value === "boolean" ? badge(value ? "Enabled" : "Disabled", value ? "good" : "muted") : esc(titleCase(value))}</strong></div>`).join("");
  const actions = [
    { command: "reset-schedule", label: "Reset schedule counters", copy: "Deletes this month's AviationStack access counters only.", tone: "warn" },
    { command: "reset-radar", label: "Reset radar counters", copy: "Deletes this month's radar access counters only.", tone: "warn" },
    { command: "correct-schedule", label: "Correct schedule total", copy: "Sets a non-negative monthly total using a stored offset.", tone: "warn" },
    { command: "clear-logs", label: "Clear request log", copy: "Deletes the current sanitized request-log rows.", tone: "danger" },
    { command: "clean-trial", label: "Clean setup trial state", copy: "Clears transient trial, cache, activation-request, and report rows; keeps keys, tokens, blocks, and usage.", tone: "danger" },
    { command: "reset-all", label: "Reset all monthly counters", copy: "Deletes every service usage row for the current month.", tone: "danger" },
  ];
  workspace.innerHTML = workspaceHead("Runtime and maintenance", "Read configuration first, then use the narrowest action that resolves the issue.") +
    `<div class="panel-stack"><div class="split-grid">${panel("Runtime limits", `Effective configuration for ${text(payload.month)}.`, `<div class="panel-body">${limitRows}</div>`)}${panel("Feature gates", "Environment-controlled; changes require a deployment configuration update.", `<div class="panel-body">${featureRows}</div>`)}</div>${panel("Maintenance controls", "All write actions require a second, explicit confirmation.", `<div class="panel-body"><div class="action-grid">${actions.map(action => `<article class="action-card"><header><div><h4>${esc(action.label)}</h4><p>${esc(action.copy)}</p></div></header><div class="action-buttons"><button class="button ${action.tone === "danger" ? "button-danger" : "button-warn"}" type="button" data-command="${esc(action.command)}">${esc(action.label)}</button></div></article>`).join("")}</div></div>`, "", "danger")}</div>`;
}

function detailSection(title, rows) {
  return `<section class="detail-section"><h3>${esc(title)}</h3>${rows.map(([label, value, raw]) => `<div class="detail-row"><span>${esc(label)}</span><strong>${raw ? value : esc(text(value))}</strong></div>`).join("")}</section>`;
}

function openDrawer(kind, row) {
  if (kind === "access_license") return openAccessDrawer(row);
  activeAccessLicenseId = "";
  accessDetailGeneration += 1;
  drawer.dataset.kind = kind;
  drawer.dataset.row = JSON.stringify(row);
  let actions = "";
  let sections = "";
  if (kind === "fleet") {
    actions = `<button class="button button-quiet" type="button" data-row-action="reset-install">Reset counters</button>${row.blocked ? `<button class="button button-good" type="button" data-row-action="unblock-install">Restore access</button>` : `<button class="button button-warn" type="button" data-row-action="block-install">Block access</button>`}<button class="button button-danger" type="button" data-row-action="erase-install">Erase hosted data</button>`;
    sections = detailSection("Identity and access", [["Fingerprint", row.install_fingerprint], ["Presence", titleCase(row.presence_status)], ["Presence source", titleCase(row.presence_source)], ["Access", titleCase(row.status)], ["Plan", titleCase(row.plan)], ["Block reason", row.blocked_reason]]) + detailSection("Activity", [["Heartbeat", dateTime(row.last_heartbeat_at)], ["Check-in", dateTime(row.last_checkin_at)], ["Relay activity", dateTime(row.last_relay_activity_at)], ["First seen", dateTime(row.first_seen)], ["Last seen", dateTime(row.last_seen)]]) + detailSection("Client", [["App version", row.app_version], ["OS", `${text(row.os_family)} ${text(row.os_version, "")}`], ["Architecture", row.arch], ["Interface", row.effective_gui || row.requested_gui], ["Client kind", titleCase(row.client_kind)], ["Source mode", row.source_mode], ["Diagnostics", row.diagnostics_mode]]) + detailSection("Display and usage", [["Airport", valueAt(row, "current_lane.airport_iata")], ["Timezone", valueAt(row, "current_lane.timezone")], ["Refresh", `${number(valueAt(row, "current_lane.refresh_seconds"))} seconds`], ["Schedule", number(row.schedule_calls)], ["Radar", number(row.radar_calls)], ["Companions", number(row.companion_count)], ["Matrix", number(row.matrix_count)]]) ;
  } else if (kind === "token") {
    actions = `${row.revoked ? `<button class="button button-good" type="button" data-row-action="reactivate-token">Reactivate</button>` : `<button class="button button-warn" type="button" data-row-action="revoke-token">Revoke</button>`}<button class="button button-primary" type="button" data-row-action="rotate-token">Rotate</button><button class="button button-quiet" type="button" data-row-action="unbind-token">Unbind</button><button class="button button-quiet" type="button" data-row-action="reset-token">Reset counters</button><button class="button button-danger" type="button" data-row-action="delete-token">Delete</button>`;
    sections = detailSection("Managed token", [["Prefix", row.token_prefix], ["Label", row.label], ["State", row.revoked ? "Revoked" : "Active"], ["Created", dateTime(row.created_at)], ["Created by", row.created_by], ["Last seen", dateTime(row.last_seen)]]) + detailSection("Binding and limits", [["Bound install", row.bound_install_fingerprint || "Unbound"], ["Schedule limit", number(row.schedule_limit)], ["Radar limit", number(row.radar_limit)], ["Revoked at", dateTime(row.revoked_at)]]) ;
  } else if (kind === "activation-request") {
    const canIssue = String(row.status || "").toLowerCase() === "manual_review";
    actions = `${canIssue ? `<button class="button button-good" type="button" data-row-action="approve-request">Issue access</button>` : ""}<button class="button button-warn" type="button" data-row-action="reject-request">Dismiss</button><button class="button button-danger" type="button" data-row-action="delete-request">Delete</button>`;
    sections = detailSection("Request", [["Request ID", row.request_id], ["Install", row.install_fingerprint], ["Network", row.network_tag], ["Display name", row.display_name], ["Airport", row.airport_iata], ["Mode", titleCase(row.requested_mode)], ["Version", row.app_version]]) + detailSection("Decision", [["Status", titleCase(row.status)], ["Decision source", row.decision_source], ["Decision note", row.decision_note], ["Created", dateTime(row.created_at)], ["Updated", dateTime(row.updated_at)], ["Approved", dateTime(row.approved_at)], ["Delivered", dateTime(row.delivered_at)]]) ;
  } else if (kind === "blocked-install") {
    actions = `<button class="button button-good" type="button" data-row-action="unblock-install">Restore access</button>`;
    sections = detailSection("Blocked install", [["Fingerprint", row.install_fingerprint], ["Reason", row.reason], ["Blocked at", dateTime(row.created_at)]]) ;
  } else if (kind === "retention-hold") {
    actions = `<button class="button button-danger" type="button" data-release-hold="${esc(row.hold_id)}">Release hold</button>`;
    sections = detailSection("Retention hold", [["Hold ID", row.hold_id], ["Category", titleCase(row.category)], ["Reason", row.reason], ["Placed", dateTime(row.created_at)]]) ;
  } else {
    const entries = Object.entries(row || {}).filter(([, value]) => value === null || ["string", "number", "boolean"].includes(typeof value));
    sections = detailSection(titleCase(kind), entries.map(([key, value]) => [titleCase(key), typeof value === "boolean" ? (value ? "Yes" : "No") : value]));
    const nested = Object.entries(row || {}).filter(([, value]) => value && typeof value === "object");
    if (nested.length) sections += nested.map(([key, value]) => detailSection(titleCase(key), Object.entries(value).map(([nestedKey, nestedValue]) => [titleCase(nestedKey), typeof nestedValue === "object" ? JSON.stringify(nestedValue) : nestedValue]))).join("");
  }
  drawerTitle.textContent = kind === "fleet" ? `Install ${text(row.install_fingerprint)}` : titleCase(kind);
  drawerBody.innerHTML = `${actions ? `<div class="drawer-actions">${actions}</div>` : ""}${sections}`;
  drawer.removeAttribute("inert");
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  drawerScrim.classList.add("open");
  el("drawerClose").focus();
}

function closeDrawer() {
  activeAccessLicenseId = "";
  activeAccessSummary = null;
  accessDetailGeneration += 1;
  drawer.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
  drawer.setAttribute("inert", "");
  drawerScrim.classList.remove("open");
  drawerBody.replaceChildren();
  delete drawer.dataset.row;
  delete drawer.dataset.kind;
}

function renderField(field) {
  if (field.type === "checkbox") return `<label class="checkbox-field"><input name="${esc(field.name)}" type="checkbox" ${field.checked ? "checked" : ""}><span>${esc(field.label)}</span></label>`;
  if (field.type === "select") return `<label class="field"><span>${esc(field.label)}</span><select name="${esc(field.name)}">${(field.options || []).map(option => { const pair = Array.isArray(option) ? option : [option, titleCase(option)]; return `<option value="${esc(pair[0])}" ${String(field.value || "") === String(pair[0]) ? "selected" : ""}>${esc(pair[1])}</option>`; }).join("")}</select>${field.hint ? `<small class="field-hint">${esc(field.hint)}</small>` : ""}</label>`;
  return `<label class="field"><span>${esc(field.label)}</span><input name="${esc(field.name)}" type="${esc(field.type || "text")}" value="${esc(field.value || "")}" placeholder="${esc(field.placeholder || "")}" ${field.required ? "required" : ""} ${field.min !== undefined ? `min="${esc(field.min)}"` : ""} ${field.max !== undefined ? `max="${esc(field.max)}"` : ""}>${field.hint ? `<small class="field-hint">${esc(field.hint)}</small>` : ""}</label>`;
}

function ask(options) {
  const dialog = el("actionDialog");
  dialog.classList.toggle("danger", options.tone === "danger");
  el("actionDialogKicker").textContent = options.kicker || (options.tone === "danger" ? "Destructive action" : "Confirm action");
  el("actionDialogTitle").textContent = options.title;
  el("actionDialogCopy").textContent = options.copy || "";
  el("actionDialogIcon").textContent = options.tone === "danger" ? "!" : "→";
  dialogVerify = options.verify || "";
  const fields = [...(options.fields || [])];
  if (dialogVerify) fields.push({ name: "verification", label: `Type ${dialogVerify} to confirm`, placeholder: dialogVerify, required: true });
  el("actionDialogFields").innerHTML = fields.map(renderField).join("");
  const confirmButton = el("actionDialogConfirm");
  confirmButton.textContent = options.confirmLabel || "Continue";
  confirmButton.className = `button ${options.tone === "danger" ? "button-danger" : "button-primary"}`;
  confirmButton.disabled = Boolean(dialogVerify);
  const verifyInput = dialog.querySelector('[name="verification"]');
  if (verifyInput) verifyInput.addEventListener("input", () => { confirmButton.disabled = verifyInput.value !== dialogVerify; });
  dialog.showModal();
  const firstInput = dialog.querySelector("input:not([type=checkbox]), select");
  if (firstInput) setTimeout(() => firstInput.focus(), 0);
  return new Promise(resolve => { dialogResolve = resolve; });
}

function resolveDialog(value) {
  const dialog = el("actionDialog");
  if (dialog.open) dialog.close();
  const resolve = dialogResolve;
  dialogResolve = null;
  dialogVerify = "";
  if (resolve) resolve(value);
}

function showSecret(token, title = "Copy activation token") {
  el("secretDialogTitle").textContent = title;
  el("secretValue").textContent = token;
  el("copySecretBtn").textContent = "Copy token";
  el("secretDialog").showModal();
  el("copySecretBtn").focus();
}

function closeSecret() {
  el("secretDialog").close();
  el("secretValue").textContent = "";
}

async function mutate(path, body, secretTitle = "Copy activation token") {
  const payload = await api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  toast(payload.message || "Action completed.", "good");
  closeDrawer();
  overviewCache = null;
  overviewCachedAt = 0;
  if (payload.activation_token) showSecret(payload.activation_token, secretTitle);
  loadView(activeView, true).catch(error => toast(error.message, "bad"));
  return payload;
}

async function perform(task, button = null) {
  if (button) button.disabled = true;
  try {
    await task();
  } catch (error) {
    toast(error.message || String(error), "bad", true);
  } finally {
    if (button && document.contains(button)) button.disabled = false;
  }
}

async function command(name, button) {
  const row = JSON.parse(drawer.dataset.row || "{}");
  if (name === "retry") return loadView(activeView, true);
  if (name === "create-token") {
    const limits = overviewCache?.limits || {};
    const values = await ask({ title: "Create managed activation token", copy: "The token will be shown once after creation. Choose limits deliberately.", confirmLabel: "Create token", fields: [
      { name: "label", label: "Deployment label", placeholder: "Client or deployment note", required: true },
      { name: "schedule_limit", label: "Schedule limit", type: "number", min: 1, max: 1000000, value: limits.managed_schedule_default || 10000, required: true },
      { name: "radar_limit", label: "Radar limit", type: "number", min: 1, max: 1000000, value: limits.managed_radar_default || 10000, required: true },
    ] });
    if (!values) return;
    return mutate("/admin/api/activation/create", { label: values.label, schedule_limit: Number(values.schedule_limit), radar_limit: Number(values.radar_limit) }, "New managed activation token");
  }
  if (name === "warm-cache") {
    const values = await ask({ title: "Start ground-cache warm", copy: "Leave airports blank to use the configured manifest, or enter up to 20 IATA/ICAO codes.", confirmLabel: "Queue warm job", fields: [
      { name: "airports", label: "Airports", placeholder: "ZRH, JFK, LHR", hint: "Comma or space separated; known airports only." },
      { name: "force", label: "Refresh even when a layer is fresh", type: "checkbox" },
    ] });
    if (!values) return;
    const airports = String(values.airports || "").split(/[\s,;]+/).map(item => item.trim().toUpperCase()).filter(Boolean).slice(0, 20);
    warmJob = await api("/admin/api/cache-warm", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ airports, force: values.force === "on" }) });
    toast(`Warm job queued for ${number(warmJob.requested)} airports.`, "good");
    renderView("surfaces", state.surfaces.payload);
    pollWarmJob(warmJob.job_id);
    return;
  }
  if (name === "surface-override") {
    const values = await ask({ title: "Set airport ground-cache override", copy: "Pinning keeps the airport in the selected warm set. Disabling excludes it.", confirmLabel: "Save override", fields: [
      { name: "airport", label: "Airport IATA or ICAO", placeholder: "ZRH", required: true },
      { name: "max_radius_nm", label: "Maximum radius", type: "select", value: "20", options: [["5", "5 NM"], ["10", "10 NM"], ["20", "20 NM"]] },
      { name: "enabled", label: "Enable this airport", type: "checkbox", checked: true },
      { name: "pinned", label: "Pin in warm manifest", type: "checkbox" },
    ] });
    if (!values) return;
    return mutate("/admin/api/cache-warm/airport-override", { airport: values.airport, enabled: values.enabled === "on", pinned: values.pinned === "on", max_radius_nm: Number(values.max_radius_nm) });
  }
  if (name === "run-retention") {
    const values = await ask({ title: "Run retention maintenance now", copy: "This permanently removes rows past policy cutoffs unless they are covered by an active hold.", confirmLabel: "Run retention", tone: "danger", verify: "RUN RETENTION" });
    if (!values) return;
    const payload = await api("/admin/api/retention/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    toast(`Retention completed: ${number(payload.result?.deleted_total)} rows removed.`, payload.result?.status === "error" ? "bad" : "good", payload.result?.status === "error");
    overviewCache = null;
    return loadView("retention", true);
  }
  if (name === "place-hold") {
    const values = await ask({ title: "Place scoped retention hold", copy: "Use the exact internal record key for the selected category and record the reason.", confirmLabel: "Place hold", fields: [
      { name: "category", label: "Record category", type: "select", options: ["activation_request", "activation_token", "remote_grant", "report_event", "report", "legal_acceptance", "iap_transaction"] },
      { name: "record_key", label: "Exact record key", required: true },
      { name: "reason", label: "Reason", placeholder: "Legal or operational reason", required: true },
    ] });
    if (!values) return;
    return mutate("/admin/api/retention/hold", { action: "place", category: values.category, record_key: values.record_key, reason: values.reason });
  }
  if (name === "reset-schedule" || name === "reset-radar") {
    const service = name === "reset-schedule" ? "aviationstack" : "radar";
    const values = await ask({ title: `Reset ${service} counters`, copy: `This deletes the current month's ${service} usage rows.`, confirmLabel: "Reset counters", tone: "danger", verify: service.toUpperCase() });
    if (!values) return;
    return mutate("/admin/api/counters/reset", { scope: "service", service });
  }
  if (name === "correct-schedule") {
    const values = await ask({ title: "Correct monthly schedule total", copy: "Enter the known total including usage that occurred outside this relay database.", confirmLabel: "Set total", fields: [{ name: "total", label: "Known schedule total", type: "number", min: 0, max: 100000000, required: true }] });
    if (!values) return;
    return mutate("/admin/api/counters/correct-schedule", { total: Number(values.total) });
  }
  if (name === "clear-logs") {
    const values = await ask({ title: "Clear request log", copy: "All current sanitized request-log rows will be deleted.", confirmLabel: "Clear log", tone: "danger", verify: "CLEAR LOG" });
    if (!values) return;
    return mutate("/admin/api/counters/reset", { scope: "logs" });
  }
  if (name === "clean-trial") {
    const values = await ask({ title: "Clean setup trial state", copy: "This deletes transient request, cache, activation-request, report, and circuit-breaker rows. Keys, tokens, blocks, and usage remain.", confirmLabel: "Clean trial state", tone: "danger", verify: "CLEAN TRIAL" });
    if (!values) return;
    return mutate("/admin/api/maintenance/clean-trial", {});
  }
  if (name === "reset-all") {
    const values = await ask({ title: "Reset all monthly counters", copy: "Every service usage row for the current month will be permanently deleted.", confirmLabel: "Reset all counters", tone: "danger", verify: "RESET ALL" });
    if (!values) return;
    return mutate("/admin/api/counters/reset", { scope: "all" });
  }
  if (name === "reset-install") {
    const values = await ask({ title: `Reset counters for ${row.install_fingerprint}`, copy: "Only this install's current-month counters will be removed.", confirmLabel: "Reset counters" });
    if (!values) return;
    return mutate("/admin/api/counters/reset", { scope: "install", install_ref: row.action_ref });
  }
  if (name === "block-install") {
    const values = await ask({ title: `Block ${row.install_fingerprint}`, copy: "Relay access will be revoked until an operator restores it.", confirmLabel: "Block access", tone: "danger", fields: [{ name: "reason", label: "Operator reason", value: row.blocked_reason || "revoked by admin", required: true }] });
    if (!values) return;
    return mutate("/admin/api/install/access", { install_ref: row.action_ref, action: "block", reason: values.reason });
  }
  if (name === "unblock-install") {
    const values = await ask({ title: `Restore access for ${row.install_fingerprint}`, copy: "The block record will be removed immediately.", confirmLabel: "Restore access" });
    if (!values) return;
    return mutate("/admin/api/install/access", { install_ref: row.action_ref, action: "unblock" });
  }
  if (name === "erase-install") {
    const fingerprint = text(row.install_fingerprint, "ERASE");
    const values = await ask({ title: `Erase hosted data for ${fingerprint}`, copy: "Operational rows will be permanently deleted. Legally retained, pseudonymous evidence may remain.", confirmLabel: "Erase hosted data", tone: "danger", verify: fingerprint });
    if (!values) return;
    return mutate("/admin/api/install/access", { install_ref: row.action_ref, action: "erase_data", reason: "operator erasure" });
  }
  if (name.endsWith("-token")) {
    const action = name.replace("-token", "");
    const labels = { revoke: "Revoke token", reactivate: "Reactivate token", rotate: "Rotate token", unbind: "Clear token binding", reset: "Reset token counters", delete: "Delete token" };
    const destructive = ["revoke", "delete"].includes(action);
    const verify = action === "delete" ? `DELETE ${row.token_prefix}` : "";
    const values = await ask({ title: `${labels[action]} · ${row.token_prefix}`, copy: action === "rotate" ? "The current token stops working and the replacement is shown once." : action === "delete" ? "The token record is permanently removed." : "This action applies only to the selected managed token.", confirmLabel: labels[action], tone: destructive ? "danger" : "", verify });
    if (!values) return;
    if (action === "reset") return mutate("/admin/api/counters/reset", { scope: "token", token_ref: row.action_ref, token_prefix: row.token_prefix });
    return mutate("/admin/api/activation/token-action", { token_ref: row.action_ref, token_prefix: row.token_prefix, action }, action === "rotate" ? "Rotated activation token" : undefined);
  }
  if (name === "approve-request") {
    const values = await ask({ title: `Issue access for ${row.install_fingerprint}`, copy: "A new one-time activation token will be created using the requested mode's limits.", confirmLabel: "Issue access" });
    if (!values) return;
    return mutate("/admin/api/activation/request-action", { request_id: row.action_ref || row.request_id, action: "approve", decision_note: "manual issue completed" }, "Issued activation token");
  }
  if (name === "reject-request") {
    const values = await ask({ title: `Dismiss ${row.request_id}`, copy: "The request remains as a dismissed audit row until retention removes it.", confirmLabel: "Dismiss request", tone: "danger", fields: [{ name: "decision_note", label: "Decision note", value: row.decision_note || "dismissed", required: true }] });
    if (!values) return;
    return mutate("/admin/api/activation/request-action", { request_id: row.action_ref || row.request_id, action: "reject", decision_note: values.decision_note });
  }
  if (name === "delete-request") {
    const values = await ask({ title: `Delete ${row.request_id}`, copy: "The activation-request row will be permanently removed.", confirmLabel: "Delete request", tone: "danger", verify: "DELETE" });
    if (!values) return;
    return mutate("/admin/api/activation/request-action", { request_id: row.action_ref || row.request_id, action: "delete", decision_note: "deleted by admin" });
  }
}

async function pollWarmJob(jobId, attempts = 0) {
  if (!jobId || attempts > 80) return;
  try {
    warmJob = await api(`/admin/api/cache-warm/${encodeURIComponent(jobId)}`);
    if (activeView === "surfaces" && state.surfaces.payload) renderView("surfaces", state.surfaces.payload);
    if (["completed", "partial", "failed"].includes(String(warmJob.status || "").toLowerCase())) {
      toast(`Warm job ${titleCase(warmJob.status)}: ${number(warmJob.refreshed_count)} refreshed, ${number(warmJob.failed_count)} failed.`, warmJob.status === "failed" ? "bad" : warmJob.status === "partial" ? "warn" : "good", warmJob.status === "failed");
      if (activeView === "surfaces") loadView("surfaces", true);
      return;
    }
    setTimeout(() => pollWarmJob(jobId, attempts + 1), 2000);
  } catch (error) {
    toast(`Warm-job status failed: ${error.message}`, "bad", true);
  }
}

function navigate(key, filters = null, updateHash = true) {
  if (!views.some(view => view.id === key)) key = "overview";
  if (filters) {
    state[key].filters = { ...filters };
    resetPaging(key);
  }
  if (updateHash && location.hash !== `#${key}`) {
    location.hash = key;
    return;
  }
  loadView(key, true);
}

function openSidebar() {
  el("sidebar").classList.add("open");
  el("sidebarScrim").classList.add("open");
}

function closeSidebar() {
  el("sidebar").classList.remove("open");
  el("sidebarScrim").classList.remove("open");
}

function initializeNav() {
  const groups = [...new Set(views.map(view => view.group))];
  nav.innerHTML = groups.map(group => `<div class="nav-group"><span class="nav-label">${esc(group)}</span>${views.filter(view => view.group === group).map(view => `<button class="nav-item" type="button" data-view="${esc(view.id)}"><span class="nav-icon" aria-hidden="true">${esc(view.icon)}</span><span>${esc(view.label)}</span><span class="nav-count" data-nav-count="${esc(view.id)}" hidden></span></button>`).join("")}</div>`).join("");
}

document.addEventListener("click", event => {
  const button = event.target.closest("button");
  if (!button) return;
  if (button.dataset.view) return navigate(button.dataset.view);
  if (button.dataset.jump) {
    let filters = null;
    try { filters = button.dataset.jumpFilters ? JSON.parse(button.dataset.jumpFilters) : null; } catch (_) { filters = null; }
    return navigate(button.dataset.jump, filters);
  }
  if (button.dataset.applyFilter) {
    const key = button.dataset.applyFilter;
    const filters = {};
    workspace.querySelectorAll(`[data-filter]`).forEach(input => { if (input.value !== "") filters[input.dataset.filter] = input.value; });
    state[key].filters = filters;
    resetPaging(key);
    return perform(() => loadView(key, true), button);
  }
  if (button.dataset.clearFilter) {
    const key = button.dataset.clearFilter;
    state[key].filters = {};
    resetPaging(key);
    return perform(() => loadView(key, true), button);
  }
  if (button.dataset.sortView) {
    const key = button.dataset.sortView;
    const sortKey = button.dataset.sortKey;
    state[key].dir = state[key].sort === sortKey && state[key].dir === "desc" ? "asc" : "desc";
    state[key].sort = sortKey;
    resetPaging(key);
    return perform(() => loadView(key, true), button);
  }
  if (button.dataset.pageNext) {
    const key = button.dataset.pageNext;
    const next = button.dataset.nextCursor;
    if (!next) return;
    state[key].cursors = state[key].cursors.slice(0, state[key].cursorIndex + 1);
    state[key].cursors.push(next);
    state[key].cursorIndex += 1;
    return perform(() => loadView(key, true), button);
  }
  if (button.dataset.pagePrev) {
    const key = button.dataset.pagePrev;
    if (state[key].cursorIndex > 0) state[key].cursorIndex -= 1;
    return perform(() => loadView(key, true), button);
  }
  if (button.dataset.inspectStore) {
    const store = rowStores.get(button.dataset.inspectStore);
    const row = store?.rows?.[Number(button.dataset.inspectIndex)];
    if (store && row) openDrawer(store.kind, row);
    return;
  }
  if (button.dataset.accessAction) return perform(() => runAccessAction(button.dataset.accessAction), button);
  if (button.dataset.eventAction && button.dataset.eventRef) return perform(async () => {
    const values = await ask({ title: "Resolve provider event", copy: "Mark this masked provider event as resolved after investigation.", confirmLabel: "Resolve event" });
    if (!values) return;
    await mutate(`/admin/api/access/events/${encodeURIComponent(button.dataset.eventRef)}/action`, { action: button.dataset.eventAction });
  }, button);
  if (button.dataset.accessBackup) return perform(async () => {
    const action = button.dataset.accessBackup;
    const values = await ask({ title: action === "create_backup" ? "Create verified backup" : "Verify latest backup", copy: "Check the encrypted Relay Access backup and its recovery status.", confirmLabel: "Continue" });
    if (!values) return;
    const result = await api("/admin/api/access-backups/action", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }) });
    toast(result.backup?.healthy === false ? "Backup needs attention. Review its status below." : "Backup operation completed.", result.backup?.healthy === false ? "warn" : "good");
    await loadView("access", true);
  }, button);
  if (button.dataset.command) return perform(() => command(button.dataset.command, button), button);
  if (button.dataset.rowAction) return perform(() => command(button.dataset.rowAction, button), button);
  if (button.dataset.saveProvider) {
    const provider = button.dataset.saveProvider;
    const input = el(`provider-key-${provider}`);
    if (!input?.value.trim()) return toast("Enter a replacement key first.", "warn");
    return perform(async () => {
      const values = await ask({ title: `Replace ${titleCase(provider)} key`, copy: "The new secret will be stored by the relay and will not render back in the page.", confirmLabel: "Save replacement" });
      if (!values) return;
      await mutate("/admin/api/providers/save", { [button.dataset.providerField]: input.value.trim() });
      input.value = "";
    }, button);
  }
  if (button.dataset.clearProvider) {
    const provider = button.dataset.clearProvider;
    return perform(async () => {
      const values = await ask({ title: `Clear ${titleCase(provider)} override`, copy: "The environment value, if any, becomes effective after the relay-stored override is removed.", confirmLabel: "Clear override", tone: "danger", verify: "CLEAR" });
      if (!values) return;
      await mutate("/admin/api/providers/clear", { provider });
    }, button);
  }
  if (button.dataset.releaseHold) {
    const holdId = button.dataset.releaseHold;
    return perform(async () => {
      const values = await ask({ title: `Release hold ${holdId}`, copy: "The protected record becomes eligible for deletion on the next retention run.", confirmLabel: "Release hold", tone: "danger", verify: "RELEASE" });
      if (!values) return;
      await mutate("/admin/api/retention/hold", { action: "release", category: "legal_acceptance", hold_id: holdId, record_key: "" });
    }, button);
  }
});

document.addEventListener("keydown", event => {
  if (event.key === "Escape") closeDrawer();
  if (event.key === "/" && !/INPUT|SELECT|TEXTAREA/.test(document.activeElement?.tagName || "")) {
    const search = workspace.querySelector('input[data-filter="q"]');
    if (search) { event.preventDefault(); search.focus(); }
  }
  if (event.key === "Enter" && event.target.matches("[data-filter]")) {
    const apply = workspace.querySelector(`[data-apply-filter="${activeView}"]`);
    if (apply) { event.preventDefault(); apply.click(); }
  }
});

el("actionDialogForm").addEventListener("submit", event => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(event.currentTarget).entries());
  if (dialogVerify && values.verification !== dialogVerify) return;
  resolveDialog(values);
});
el("actionDialogCancel").addEventListener("click", () => resolveDialog(null));
el("actionDialog").addEventListener("cancel", event => { event.preventDefault(); resolveDialog(null); });
el("closeSecretBtn").addEventListener("click", closeSecret);
el("secretDialog").addEventListener("cancel", event => { event.preventDefault(); closeSecret(); });
el("copySecretBtn").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(el("secretValue").textContent || "");
    el("copySecretBtn").textContent = "Copied";
    toast("Activation token copied.", "good");
  } catch (_) {
    toast("Clipboard access was unavailable. Select and copy the token manually.", "warn", true);
  }
});

el("drawerClose").addEventListener("click", closeDrawer);
drawerScrim.addEventListener("click", closeDrawer);
el("menuButton").addEventListener("click", openSidebar);
el("sidebarClose").addEventListener("click", closeSidebar);
el("sidebarScrim").addEventListener("click", closeSidebar);
el("refreshBtn").addEventListener("click", event => perform(() => loadView(activeView, true), event.currentTarget));
el("userName").textContent = BOOT.username || "operator";

function signOut() {
  fetch("/admin/api/logout", { method: "POST", headers: { "Authorization": "Basic " + btoa("logout:logout") } }).catch(() => {}).finally(() => window.location.replace("/admin/signed-out"));
}
el("signOutBtn").addEventListener("click", signOut);

const IDLE_MS = Math.max(60, Number(BOOT.idleSeconds || 900)) * 1000;
const WARN_MS = Math.min(60000, Math.max(5000, IDLE_MS - 5000));
let idleTimer = null;
let signoutTimer = null;
let idleToast = "";
function clearIdleWarning() {
  if (idleToast) el(idleToast)?.remove();
  idleToast = "";
  if (signoutTimer) clearTimeout(signoutTimer);
  signoutTimer = null;
}
function warnIdle() {
  clearIdleWarning();
  idleToast = toast(`No activity detected. Signing out in ${Math.round(WARN_MS / 1000)} seconds.`, "warn", true);
  signoutTimer = setTimeout(signOut, WARN_MS);
}
function resetIdle() {
  clearIdleWarning();
  if (idleTimer) clearTimeout(idleTimer);
  idleTimer = setTimeout(warnIdle, Math.max(5000, IDLE_MS - WARN_MS));
}
["pointerdown", "keydown", "scroll"].forEach(name => window.addEventListener(name, resetIdle, { passive: true }));

initializeNav();
if (BOOT.message) toast(BOOT.message, "good");
if (BOOT.createdToken) showSecret(BOOT.createdToken, "New activation token");
window.addEventListener("hashchange", () => navigate(location.hash.slice(1) || "overview", null, false));
resetIdle();
navigate(location.hash.slice(1) || "overview", null, false);
