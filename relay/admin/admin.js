const BOOT = __BOOT__;

const views = [
  ["overview", "Overview"],
  ["fleet", "Fleet"],
  ["traffic", "Traffic"],
  ["schedules", "Schedules"],
  ["surfaces", "Surfaces"],
  ["reports", "Reports"],
  ["activations", "Activations"],
  ["access", "Relay Access"],
  ["providers", "Providers"],
  ["maintenance", "Maintenance"]
];

const state = Object.fromEntries(
  views.map(([key]) => [key, { cursor: "", last: "", filters: {}, sort: key === "reports" ? "ts" : key === "access" ? "" : "last_seen", dir: "desc" }])
);

const endpoints = {
  overview: "/admin/api/overview",
  fleet: "/admin/api/fleet",
  traffic: "/admin/api/usage",
  schedules: "/admin/api/schedules",
  surfaces: "/admin/api/surfaces",
  reports: "/admin/api/reports",
  activations: "/admin/api/activations",
  access: "/admin/api/access"
};

let activeAccessLicenseId = "";
let activeAccessSummary = null;

const columns = {
  traffic: [["service", "Service"], ["plan", "Plan"], ["calls", "Calls"], ["subject.fingerprint", "Subject"], ["last_seen", "Last seen"]],
  requests: [["ts", "Time"], ["install_fingerprint", "Install"], ["service", "Service"], ["scope", "Scope"], ["status", "Status"], ["latency_ms", "Latency"]],
  schedules: [["airport_iata", "Airport"], ["timezone", "Timezone"], ["client_accesses", "Serves"], ["upstream_pulls", "Pulls"], ["cache_hits", "Hits"], ["last_cache_state", "State"], ["updated_at", "Updated"]],
  surfaces: [["airport_iata", "IATA"], ["airport_icao", "ICAO"], ["feature_count", "Features"], ["request_count", "Requests"], ["cache_hits", "Hits"], ["last_cache_state", "State"], ["updated_at", "Updated"]],
  reports: [["ts", "Time"], ["install_fingerprint", "Install"], ["report_type", "Type"], ["origin", "Origin"], ["team", "Team"], ["status", "Status"]],
  tokens: [["token_prefix", "Prefix"], ["label", "Label"], ["schedule_limit", "Schedule"], ["radar_limit", "Radar"], ["bound_install_fingerprint", "Bound"], ["last_seen", "Last"], ["revoked", "Revoked"]],
  requestsQueue: [["request_id", "Request"], ["install_fingerprint", "Install"], ["network_tag", "Network"], ["airport_iata", "Airport"], ["display_name", "Display"], ["status", "Status"], ["updated_at", "Updated"]]
};

const quickViewDefs = [
  ["Recently seen", "fleet", { status: "active" }],
  ["Missing heartbeat", "fleet", { presence_status: "unknown" }],
  ["Stale heartbeat", "fleet", { presence_status: "stale" }],
  ["Companion users", "fleet", { has_companion: "true" }],
  ["Matrix installs", "fleet", { has_matrix: "true" }],
  ["macOS native", "fleet", { os_family: "macos", effective_gui: "native" }],
  ["Windows native", "fleet", { os_family: "windows", effective_gui: "native" }],
  ["Pending review", "activations", {}]
];

function esc(value) {
  const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(value ?? "").replace(/[&<>"']/g, ch => map[ch]);
}

function valueAt(row, path) {
  return path.split(".").reduce((v, k) => (v && typeof v === "object" ? v[k] : ""), row);
}

function compact(value, fallback = "-") {
  const text = String(value ?? "").trim();
  return text || fallback;
}

function badge(value) {
  const text = compact(value);
  const lower = text.toLowerCase();
  const tone = lower.includes("fresh") || lower.includes("active") || lower.includes("ready") || lower.includes("processed") || lower.includes("delivered") || lower === "sent" || lower === "revealed" || lower === "200" || lower === "false"
    ? "good"
    : lower.includes("error") || lower.includes("blocked") || lower.includes("revoked") || lower.includes("failed") || lower.includes("refunded") || lower.includes("disputed")
      ? "bad"
      : lower.includes("stale") || lower.includes("recent") || lower.includes("pending") || lower.includes("manual") || lower.includes("suspended")
        ? "warn"
        : lower.includes("unknown") || lower.includes("missing")
          ? "missing"
          : "";
  return `<span class="badge ${tone}"><span class="dot ${tone || "neutral"}"></span>${esc(text)}</span>`;
}

function metric(label, value, sub, tone = "") {
  return `<div class="metric ${tone}"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="muted">${esc(sub || "")}</div></div>`;
}

function metrics(items) {
  return `<div class="grid">${items.map(([label, value, sub, tone]) => metric(label, value, sub, tone)).join("")}</div>`;
}

function panel(key, title, copy, tools, body, pager = "") {
  document.getElementById(key).innerHTML =
    `<div class="panel-head"><div><h2>${esc(title)}</h2><div class="muted">${esc(copy)}</div></div><div class="panel-tools">${tools || ""}</div></div>${body}${pager}`;
}

function statusRail(payload) {
  const providers = payload.providers || {};
  const ready = Object.values(providers).filter(item => item && item.configured).length;
  const providerTotal = Object.keys(providers).length || 0;
  const heartbeat = payload.heartbeat || {};
  const reportReady = (payload.counts?.reports_24h || 0) >= 0 ? "ready" : "missing";
  statusRailEl.innerHTML = [
    ["Relay", "ready", "Admin JSON online"],
    ["Heartbeat", heartbeat.fresh > 0 ? "fresh" : heartbeat.recent > 0 ? "recent" : heartbeat.stale > 0 ? "stale" : "unknown", `${heartbeat.fresh || 0} fresh / ${heartbeat.stale || 0} stale`],
    ["Providers", ready === providerTotal && providerTotal ? "ready" : "missing", `${ready} / ${providerTotal} ready`],
    ["Reports", reportReady, `${payload.counts?.reports_24h || 0} in 24h`]
  ].map(([label, tone, detail]) => `<div class="status-card">${badge(tone)}<strong>${esc(label)}</strong><span>${esc(detail)}</span></div>`).join("");
}

function filters(key, defs) {
  return `<div class="filters">${defs.map(def => {
    const [name, label, type, options] = def;
    const value = state[key].filters[name] || "";
    if (type === "select") {
      return `<select data-filter="${esc(name)}"><option value="">${esc(label)}</option>${(options || []).map(opt => `<option value="${esc(opt)}" ${String(value).toLowerCase() === String(opt).toLowerCase() ? "selected" : ""}>${esc(opt)}</option>`).join("")}</select>`;
    }
    return `<input data-filter="${esc(name)}" type="${type || "search"}" placeholder="${esc(label)}" value="${esc(value)}">`;
  }).join("")}<button data-apply="${key}">Apply</button><button data-clear="${key}">Clear</button></div>`;
}

function table(key, rows, cols, kind) {
  if (!rows || !rows.length) {
    return `<div class="table-wrap compact"><table><tbody><tr><td class="muted">No rows for this view.</td></tr></tbody></table></div>`;
  }
  return `<div class="table-wrap compact"><table><thead><tr>${cols.map(([path, label]) => `<th data-sort="${esc(path)}">${esc(label)}</th>`).join("")}</tr></thead><tbody>${rows.map((row, idx) => `<tr data-kind="${esc(kind || key)}" data-index="${idx}">${cols.map(([path]) => {
    const value = valueAt(row, path);
    const cell = path.includes("status") || path.includes("state") || path === "revoked" ? badge(value) : esc(value);
    return `<td>${cell}</td>`;
  }).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function fleetTable(rows) {
  if (!rows || !rows.length) {
    return `<div class="table-wrap compact"><table><tbody><tr><td class="muted">No installs match this view.</td></tr></tbody></table></div>`;
  }
  return `<div class="table-wrap compact"><table><thead><tr>
    <th data-sort="install_fingerprint">Install</th>
    <th data-sort="presence_status">Presence</th>
    <th data-sort="last_heartbeat_at">Heartbeat</th>
    <th data-sort="os_family">OS / GUI</th>
    <th data-sort="app_version">Version</th>
    <th data-sort="current_lane.airport_iata">Lane</th>
    <th data-sort="schedule_calls">Usage</th>
    <th data-sort="status">Access</th>
  </tr></thead><tbody>${rows.map((row, idx) => `<tr data-kind="fleet" data-index="${idx}">
    <td><strong class="mono">${esc(row.install_fingerprint || "-")}</strong><span class="cell-sub">${esc(row.plan || "community")}</span></td>
    <td>${badge(row.presence_status)}<span class="cell-sub">${esc(row.presence_source || "unknown")}</span></td>
    <td>${esc(shortTime(row.last_heartbeat_at || row.last_checkin_at || row.last_relay_activity_at))}<span class="cell-sub">${esc(shortTime(row.last_seen))}</span></td>
    <td>${esc(row.os_family || "-")}<span class="cell-sub">${esc(row.effective_gui || row.requested_gui || "-")}</span></td>
    <td>${esc(row.app_version || "-")}<span class="cell-sub">${esc(row.arch || "")}</span></td>
    <td>${esc(valueAt(row, "current_lane.airport_iata") || "-")}<span class="cell-sub">${esc(valueAt(row, "current_lane.timezone") || "")}</span></td>
    <td>${Number(row.schedule_calls || 0).toLocaleString()} / ${Number(row.radar_calls || 0).toLocaleString()}<span class="cell-sub">schedule / radar</span></td>
    <td>${badge(row.status)}<span class="cell-sub">${row.blocked ? esc(row.blocked_reason || "blocked") : row.managed ? "managed" : "community"}</span></td>
  </tr>`).join("")}</tbody></table></div>`;
}

function pager(key, payload) {
  return `<div class="pager"><span>${payload.filtered_estimate ?? 0} filtered / ${payload.total_estimate ?? 0} total</span><span><button data-prev="${key}">Previous</button> <button data-next="${key}" ${payload.next_cursor ? "" : "disabled"}>Next</button></span></div>`;
}

function shortTime(value) {
  if (!value) return "-";
  return String(value).slice(0, 16).replace("T", " ");
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
  return `<div class="table-wrap compact"><table><tbody><tr><td class="muted">${esc(message)}</td></tr></tbody></table></div>`;
}

function accessLicenseTable(rows) {
  if (!rows.length) return emptyTable("No Relay Access licenses recorded.");
  return `<div class="table-wrap compact"><table><thead><tr>
    <th>Key reference</th><th>Source</th><th>Status</th><th>Receiver</th><th>Install reference</th><th>Created</th><th>Last activity</th>
  </tr></thead><tbody>${rows.map((row, idx) => `<tr data-kind="access_license" data-index="${idx}">
    <td><strong class="mono">${esc(licenseKeyRef(row))}</strong><span class="cell-sub">${esc(row.product_code || "-")}</span></td>
    <td>${esc(row.purchase_source || "-")}</td>
    <td>${badge(row.status)}</td>
    <td>${esc(row.device_name || "No active receiver")}<span class="cell-sub">${esc(row.device_kind || "available seat")}</span></td>
    <td class="mono">${esc(row.install_ref ? maskedRef(row.install_ref) : "-")}</td>
    <td>${esc(shortTime(row.created_at))}</td>
    <td>${esc(shortTime(row.last_seen_at || row.activated_at || row.updated_at))}</td>
  </tr>`).join("")}</tbody></table></div>`;
}

function accessDeliveryTable(rows, licenses) {
  if (!rows.length) return emptyTable("No license deliveries recorded.");
  const refs = new Map(licenses.map(row => [row.license_id, licenseKeyRef(row)]));
  return `<div class="table-wrap compact access-secondary-table"><table><thead><tr>
    <th>License</th><th>Channel</th><th>Purpose</th><th>Status</th><th>Attempts</th><th>Next attempt</th><th>Detail</th>
  </tr></thead><tbody>${rows.map(row => `<tr>
    <td class="mono">${esc(refs.get(row.license_id) || maskedRef(row.license_id))}</td>
    <td>${esc(row.channel || "-")}</td><td>${esc(row.purpose || "-")}</td><td>${badge(row.status)}</td>
    <td>${Number(row.attempt_count || 0).toLocaleString()}</td><td>${esc(shortTime(row.next_attempt_at || row.delivered_at || row.updated_at))}</td>
    <td>${esc(row.detail_code || "-")}</td>
  </tr>`).join("")}</tbody></table></div>`;
}

function accessEventTable(rows) {
  if (!rows.length) return emptyTable("No purchase events recorded.");
  return `<div class="table-wrap compact access-secondary-table"><table><thead><tr>
    <th>Provider</th><th>Event</th><th>Status</th><th>Detail</th><th>Created</th><th>Processed</th><th>Action</th>
  </tr></thead><tbody>${rows.map(row => `<tr>
    <td>${esc(row.provider || "-")}</td><td>${esc(row.event_type || "-")}</td><td>${badge(row.status)}</td>
    <td>${esc(row.detail_code || "-")}</td><td>${esc(shortTime(row.created_at))}</td><td>${esc(shortTime(row.processed_at))}</td>
    <td>${["reconciliation_required", "failed"].includes(String(row.status).toLowerCase())
      ? `<button data-event-action="mark_resolved" data-event-ref="${esc(row.event_ref || "")}">Resolve</button>`
      : "-"}</td>
  </tr>`).join("")}</tbody></table></div>`;
}

function accessNotificationTable(rows, licenses) {
  if (!rows.length) return emptyTable("No queued notifications or provider operations.");
  const refs = new Map(licenses.map(row => [row.license_id, licenseKeyRef(row)]));
  return `<div class="table-wrap compact access-secondary-table"><table><thead><tr>
    <th>License</th><th>Channel</th><th>Purpose</th><th>Status</th><th>Attempts</th><th>Next attempt</th><th>Detail</th>
  </tr></thead><tbody>${rows.map(row => `<tr>
    <td class="mono">${esc(refs.get(row.license_id) || maskedRef(row.license_id))}</td>
    <td>${esc(row.channel || "-")}</td><td>${esc(row.purpose || "-")}</td><td>${badge(row.status)}</td>
    <td>${Number(row.attempt_count || 0).toLocaleString()}</td><td>${esc(shortTime(row.next_attempt_at || row.delivered_at || row.updated_at))}</td>
    <td>${esc(row.detail_code || "-")}</td>
  </tr>`).join("")}</tbody></table></div>`;
}

function renderAccess(payload) {
  const licenses = payload.licenses || [];
  const deliveries = payload.deliveries || [];
  const notifications = payload.notifications || [];
  const events = payload.purchase_events || [];
  const active = licenses.filter(row => String(row.status).toLowerCase() === "active").length;
  const failedDeliveries = deliveries.filter(row => String(row.status).toLowerCase() === "failed").length;
  const pendingDeliveries = deliveries.filter(row => String(row.status).toLowerCase() === "pending").length;
  const eventIssues = events.filter(row => !["processed", "completed", "success"].includes(String(row.status).toLowerCase())).length;
  const reconciliation = payload.reconciliation_ready || {};
  const reconciliationHealth = payload.reconciliation_health || [];
  const degradedProviders = reconciliationHealth.filter(row => String(row.status || "").toLowerCase() !== "healthy");
  const backup = payload.backup || {};
  const cards = [
    ["Licenses", licenses.length, `${active} active / ${licenses.length - active} inactive`, licenses.length - active ? "warn" : "good"],
    ["Delivery queue", failedDeliveries + pendingDeliveries, `${pendingDeliveries} pending / ${failedDeliveries} failed`, failedDeliveries ? "bad" : pendingDeliveries ? "warn" : "good"],
    ["Event issues", eventIssues, `${events.length} recent events`, eventIssues ? "warn" : "good"],
    ["Access mode", payload.mode || "unknown", `Schema ${payload.schema_version ?? "-"}`, payload.mode === "licensed" ? "good" : "warn"],
    ["Configuration", payload.configuration_ready ? "ready" : "not ready", "License service preflight", payload.configuration_ready ? "good" : "bad"],
    ["License delivery", payload.delivery_ready ? "ready" : "not ready", "Email and recovery delivery", payload.delivery_ready ? "good" : "warn"],
    ["Sales", payload.sales_enabled ? "enabled" : "disabled", "Commercial checkout gate", payload.sales_enabled ? "good" : "warn"],
    ["Mobile ownership", payload.mobile_ownership_enabled ? "enabled" : "disabled", `Apple ${reconciliation.apple ? "ready" : "not ready"} / Google ${reconciliation.google ? "ready" : "not ready"}`, payload.mobile_ownership_enabled && reconciliation.apple && reconciliation.google ? "good" : "warn"],
    ["Provider checks", degradedProviders.length ? "attention" : "healthy", reconciliationHealth.length ? `${reconciliationHealth.length} provider records / ${degradedProviders.length} degraded` : "No provider checks recorded", degradedProviders.length ? "bad" : "good"],
    ["Encrypted backups", backup.healthy ? "healthy" : "attention", backup.last_backup_at ? `Latest ${shortTime(backup.last_backup_at)}${backup.detail_code ? ` · ${backup.detail_code}` : ""}` : "No verified backup", backup.healthy ? "good" : "bad"]
  ];
  const body = filters("access", [
      ["q", "License, key reference, or exact email"],
      ["source", "Purchase source", "select", ["stripe", "apple_app", "google_play_product"]],
      ["state", "License state", "select", ["active", "suspended", "refunded", "revoked"]]
    ]) + `<div class="card-grid">${cards.map(([label, value, sub, tone]) => metric(label, value, sub, tone)).join("")}</div>
    <div class="panel-subhead"><h3>Universal licenses</h3><span>One purchase, one portable license, one active independent receiver. Select a row for safe operations.</span></div>
    ${accessLicenseTable(licenses)}
    <div class="panel-subhead"><h3>Delivery diagnostics</h3><span>License and delivery identifiers remain masked.</span></div>
    ${accessDeliveryTable(deliveries, licenses)}
    <div class="panel-subhead"><h3>Notification and provider queue</h3><span>Destinations, purchase handles, and message payloads remain encrypted and hidden.</span></div>
    ${accessNotificationTable(notifications, licenses)}
    <div class="panel-subhead"><h3>Provider reconciliation health</h3><span>Authority checks must remain current before production access is enabled.</span></div>
    ${reconciliationHealth.length ? `<div class="table-wrap compact access-secondary-table"><table><thead><tr><th>Provider</th><th>Status</th><th>Last success</th><th>Last attempt</th><th>Next attempt</th><th>Detail</th></tr></thead><tbody>${reconciliationHealth.map(row => `<tr><td>${esc(row.provider || "-")}</td><td>${badge(row.status || "unknown")}</td><td>${esc(shortTime(row.last_success_at))}</td><td>${esc(shortTime(row.last_attempt_at))}</td><td>${esc(shortTime(row.next_attempt_at))}</td><td>${esc(row.detail_code || "-")}</td></tr>`).join("")}</tbody></table></div>` : emptyTable("No provider reconciliation checks recorded.")}
    <div class="action-card"><button data-action="createAccessBackup">Create verified backup</button><button data-action="verifyAccessBackup">Verify latest backup</button></div>
    <div class="panel-subhead"><h3>Purchase events</h3><span>Provider events are summarized without raw purchase identifiers or proofs.</span></div>
    ${accessEventTable(events)}`;
  panel("access", "Relay Access", "Universal Stripe, Apple, and Google license operations. Secrets and ownership evidence never render in this view.", "Operate", body, pager("access", payload));
}

function topFacetEntries(facets, name, limit = 5) {
  return Object.entries(facets?.[name] || {}).sort((a, b) => Number(b[1]) - Number(a[1])).slice(0, limit);
}

function cohortCards(payload) {
  const facets = payload.facets || {};
  const metrics = payload.metrics || {};
  const heartbeat = payload.heartbeat || {};
  const cards = [
    ["Heartbeat", `${heartbeat.fresh || 0} fresh`, `${heartbeat.recent || 0} recent / ${heartbeat.stale || 0} stale`, heartbeat.stale ? "warn" : "good"],
    ["Managed", metrics.managed_installs || 0, "Bound managed tokens", ""],
    ["Blocked", metrics.blocked_installs || 0, "Access revoked", metrics.blocked_installs ? "bad" : ""],
    ["Companion", metrics.companion_installs || 0, "Mobile companion present", ""],
    ["Matrix", metrics.matrix_installs || 0, "LED/matrix present", ""],
    ["Unknown", metrics.presence_unknown || 0, "No heartbeat/check-in yet", metrics.presence_unknown ? "missing" : ""]
  ];
  const mixes = [
    ["OS mix", topFacetEntries(facets, "os_family")],
    ["GUI mix", topFacetEntries(facets, "effective_gui")],
    ["Version mix", topFacetEntries(facets, "app_version", 4)]
  ];
  return `<div class="card-grid">${cards.map(([label, value, sub, tone]) => metric(label, value, sub, tone)).join("")}</div>
    <div class="mix-grid">${mixes.map(([label, entries]) => `<div class="mix-card"><strong>${esc(label)}</strong>${entries.length ? entries.map(([name, count]) => `<span><b>${esc(name)}</b>${Number(count).toLocaleString()}</span>`).join("") : `<span><b>unknown</b>0</span>`}</div>`).join("")}</div>`;
}

async function load(key) {
  setNav(key);
  const endpoint = endpoints[key];
  if (!endpoint) return renderStatic(key);
  let response;
  if (key === "access") {
    const filters = state[key]?.filters || {};
    response = await fetch("/admin/api/access/search", {
      method: "POST",
      headers: { "Accept": "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({
        limit: 100,
        cursor: state[key]?.cursor || "",
        q: filters.q || "",
        source: filters.source || "",
        state: filters.state || ""
      })
    });
  } else {
    const qs = paramsFor(key).toString();
    response = await fetch(endpoint + (qs ? "?" + qs : ""), { headers: { "Accept": "application/json" } });
  }
  if (!response.ok) throw new Error(`${key}: HTTP ${response.status}`);
  const payload = await response.json();
  state[key].last = payload;
  render(key, payload);
}

function paramsFor(key) {
  const params = new URLSearchParams();
  Object.entries(state[key]?.filters || {}).forEach(([k, v]) => { if (v !== "" && v != null) params.set(k, v); });
  if (state[key]?.cursor) params.set("cursor", state[key].cursor);
  params.set("limit", "100");
  if (state[key]?.sort) params.set("sort", state[key].sort);
  if (state[key]?.dir) params.set("dir", state[key].dir);
  return params;
}

function setNav(active) {
  document.querySelectorAll(".nav button").forEach(btn => btn.classList.toggle("active", btn.dataset.view === active));
}

function render(key, payload) {
  if (key === "overview") {
    statusRail(payload);
    const c = payload.counts || {}, f = payload.fleet || {}, s = payload.shared_schedule || {}, h = payload.heartbeat || {};
    panel("overview", "Overview", "Card-first launch health. Presence is heartbeat/check-in/relay activity, not live concurrency.", "Monitor", metrics([
      ["Heartbeat pipeline", `${h.fresh || 0} fresh`, `${h.recent || 0} recent / ${h.stale || 0} stale / ${h.unknown || 0} unknown`, h.stale ? "warn" : "good"],
      ["Known installs", c.known_installs || f.known_installs || 0, "Fleet rows", ""],
      ["Seen 24h", c.active_installs_24h || f.active_installs_24h || 0, "Heartbeat or relay activity", ""],
      ["Requests 24h", c.requests_24h || 0, "Relay traffic", ""],
      ["Reports 24h", c.reports_24h || 0, "Report gateway", ""],
      ["Pending review", c.activation_requests_pending || 0, "Activation queue", c.activation_requests_pending ? "warn" : ""],
      ["Cache hits", s.cache_hits || 0, "Shared schedules", ""],
      ["Upstream pulls", s.upstream_pulls || 0, "Provider load", ""],
      ["Blocked installs", c.blocked_installs || 0, "Access revoked", c.blocked_installs ? "bad" : ""]
    ]));
  } else if (key === "fleet") {
    const facets = payload.facets || {};
    const opts = name => Object.keys(facets[name] || {});
    const rows = payload.rows || payload.installs || [];
    const body = filters(key, [
      ["q", "Search fleet"], ["presence_status", "Presence", "select", opts("presence_status")], ["presence_source", "Source", "select", opts("presence_source")],
      ["status", "Access", "select", opts("status")], ["plan", "Plan", "select", opts("plan")], ["os_family", "OS", "select", opts("os_family")],
      ["effective_gui", "GUI", "select", opts("effective_gui")], ["app_version", "Version", "select", opts("app_version")], ["airport_iata", "Airport"],
      ["has_companion", "Companion", "select", ["true", "false"]], ["has_matrix", "Matrix", "select", ["true", "false"]],
      ["blocked", "Blocked", "select", ["true", "false"]], ["managed", "Managed", "select", ["true", "false"]]
    ]) + cohortCards(payload) + fleetTable(rows);
    panel(key, "Fleet", "Card cohorts above a compact sortable install registry. Rows use fingerprints and opaque action refs only.", "Investigate", body, pager(key, payload));
  } else if (key === "traffic") {
    const reqRows = payload.requests?.rows || [];
    const body = filters(key, [["q", "Search traffic"], ["service", "Service"], ["plan", "Plan"], ["status", "Status or error"]])
      + table(key, payload.rows || [], columns.traffic, "usage")
      + `<div class="panel-subhead"><h3>Request health</h3><span>Recent transport status</span></div>`
      + table(key, reqRows, columns.requests, "request");
    panel(key, "Traffic", "Monthly usage and recent request health.", "Monitor", body, pager(key, payload));
  } else if (key === "schedules" || key === "surfaces") {
    const body = filters(key, [["q", "Search cache"], ["airport_iata", "Airport"], ["cache_state", "Cache state"]])
      + table(key, payload.rows || payload.snapshots || [], columns[key], key);
    panel(key, key === "schedules" ? "Schedules" : "Surfaces", key === "schedules" ? "Shared schedule cache lanes." : "Airport surface cache lanes.", "Investigate", body, pager(key, payload));
  } else if (key === "reports") {
    const body = filters(key, [["q", "Search reports"], ["report_type", "Type"], ["origin", "Origin"], ["team", "Team"], ["status", "Status"]])
      + table(key, payload.rows || payload.recent_events || [], columns.reports, "report");
    panel(key, "Reports", "Sanitized report gateway events and dedupe state.", "Investigate", body, pager(key, payload));
  } else if (key === "activations") {
    const body = `<div class="card-grid">${metric("Managed tokens", (payload.tokens || []).length, "Rotate, revoke, unbind in inspector", "")}${metric("Activation queue", (payload.requests || []).length, "Manual review and issued requests", "")}</div>`
      + table(key, payload.tokens || [], columns.tokens, "token")
      + `<div class="panel-subhead"><h3>Activation queue</h3><span>Requests stay sanitized</span></div>`
      + table(key, payload.requests || [], columns.requestsQueue, "activation_request");
    panel(key, "Activations", "Managed tokens and activation queue.", "Operate", body);
  } else if (key === "access") {
    renderAccess(payload);
  }
}

function renderStatic(key) {
  if (key === "providers") panel(key, "Providers", "Save or clear relay provider key overrides. Current secret values never render back.", "Operate", `<div class="action-card"><input id="aeroKey" type="password" placeholder="Replacement AeroDataBox key"><input id="aviKey" type="password" placeholder="Replacement AviationStack key"><input id="rapidKey" type="password" placeholder="Replacement RapidAPI key"><button data-action="saveProviders">Save keys</button><button data-action="clearAero">Clear AeroDataBox</button><button data-action="clearAviation">Clear AviationStack</button><button data-action="clearRapid">Clear RapidAPI</button></div>`);
  if (key === "maintenance") panel(key, "Maintenance", "Danger Zone actions stay separated from monitoring.", "Danger Zone", `<div class="action-card danger-zone"><button data-action="resetAll">Reset all monthly counters</button><button data-action="resetLogs">Clear request log</button><input id="scheduleTotal" type="number" min="0" placeholder="Known schedule total"><button data-action="correctSchedule">Correct schedule total</button><button data-action="cleanTrial">Clean setup trial state</button></div>`);
}

function detailBlock(title, rows) {
  return `<section class="detail-block"><h3>${esc(title)}</h3>${rows.map(([label, value]) => `<div><span>${esc(label)}</span><strong>${esc(compact(value))}</strong></div>`).join("")}</section>`;
}

function openDrawer(kind, row) {
  const actions = [];
  if (kind === "fleet") {
    actions.push(`<button data-drawer-action="resetInstall">Reset counters</button>`);
    actions.push(`<button class="${row.blocked ? "safe" : "danger"}" data-drawer-action="${row.blocked ? "unblockInstall" : "blockInstall"}">${row.blocked ? "Unblock install" : "Block install"}</button>`);
  }
  if (kind === "token") {
    actions.push(`<button data-drawer-action="rotateToken">Rotate</button><button class="danger" data-drawer-action="${row.revoked ? "reactivateToken" : "revokeToken"}">${row.revoked ? "Reactivate" : "Revoke"}</button><button data-drawer-action="unbindToken">Unbind</button>`);
  }
  if (kind === "activation_request") {
    actions.push(`<button class="safe" data-drawer-action="approveRequest">Issue</button><button class="danger" data-drawer-action="rejectRequest">Dismiss</button><button class="danger" data-drawer-action="deleteRequest">Delete</button>`);
  }
  drawer.dataset.kind = kind;
  drawer.dataset.row = JSON.stringify(row);
  drawerTitle.textContent = `${kind.replace("_", " ")} inspector`;
  drawerBody.innerHTML = inspector(kind, row, actions);
  drawer.classList.add("open");
}

function inspector(kind, row, actions) {
  if (kind === "fleet") {
    return `<div class="drawer-actions">${actions.join("")}</div>
      ${detailBlock("Summary", [["Install", row.install_fingerprint], ["Presence", row.presence_status], ["Source", row.presence_source], ["Access", row.status], ["Plan", row.plan]])}
      ${detailBlock("Activity", [["Heartbeat", shortTime(row.last_heartbeat_at)], ["Check-in", shortTime(row.last_checkin_at)], ["Relay activity", shortTime(row.last_relay_activity_at)], ["Last seen", shortTime(row.last_seen)]])}
      ${detailBlock("Metadata", [["OS", row.os_family], ["Version", row.os_version], ["Arch", row.arch], ["GUI", row.effective_gui || row.requested_gui], ["App", row.app_version], ["Source", row.source_mode], ["Diagnostics", row.diagnostics_mode]])}
      ${detailBlock("Companion / Matrix", [["Companions", row.companion_count], ["Matrix", row.matrix_count], ["Matrix online", row.matrix_online_count], ["Airport", valueAt(row, "current_lane.airport_iata")]])}`;
  }
  return `<div class="drawer-actions">${actions.join("")}</div><pre>${esc(JSON.stringify(row, null, 2))}</pre>`;
}

function accessRecordBlock(title, rows, fields) {
  if (!rows.length) {
    return `<section class="detail-block access-records"><h3>${esc(title)}</h3><p class="muted">No records.</p></section>`;
  }
  return `<section class="detail-block access-records"><h3>${esc(title)}</h3>${rows.map((row, idx) => `<article class="access-record">
    <div class="access-record-title"><strong>${esc(fields.heading(row, idx))}</strong>${badge(row.status || row.state || "recorded")}</div>
    ${fields.rows(row).map(([label, value]) => `<div><span>${esc(label)}</span><strong>${esc(compact(value))}</strong></div>`).join("")}
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
  if (status === "active") actions.push(`<button data-access-action="suspend_license">Suspend license</button>`);
  if (status !== "revoked") actions.push(`<button class="danger" data-access-action="revoke_license">Revoke license</button>`);
  if (["suspended", "revoked"].includes(status) && authoritativePurchase) actions.push(`<button class="safe" data-access-action="reactivate_license">Reactivate license</button>`);
  actions.push(`<button class="danger" data-access-action="revoke_receiver" ${activeReceiver ? "" : "disabled"}>Revoke receiver</button>`);
  actions.push(`<button data-access-action="retry_deliveries" ${failedDelivery ? "" : "disabled"}>Retry deliveries</button>`);
  actions.push(`<button data-access-action="retry_notifications" ${failedNotification ? "" : "disabled"}>Retry notifications</button>`);
  if (["server_authoritative", "device_and_server"].includes(String(latestPurchase.reconciliation_mode || ""))) {
    actions.push(`<button data-access-action="retry_reconciliation">Retry provider check</button>`);
  }
  actions.push(`<button class="danger" data-access-action="rotate_key" ${status === "active" && protectedHolder ? "" : "disabled"}>Rotate master key</button>`);
  return actions.join("");
}

function renderAccessDrawer(summary, detail) {
  const license = detail.license || {};
  const displayRef = licenseKeyRef(license) !== "not issued" ? licenseKeyRef(license) : licenseKeyRef(summary);
  drawerTitle.textContent = `Relay Access · ${displayRef}`;
  drawerBody.innerHTML = `<div class="drawer-actions">${accessDrawerActions(summary, detail)}</div>
    <p class="access-operator-note">Suspending, revoking, or rotating a license revokes its active receiver. Rotation sends the replacement key only to the protected holder email; it never appears in admin. Reactivation restores license eligibility, not the old receiver credential.</p>
    ${detailBlock("License", [["Key reference", displayRef], ["Product", license.product_code || summary.product_code], ["Purchase source", license.purchase_source || summary.purchase_source], ["Status", license.status || summary.status], ["Email protection", license.email_protected ? "protected" : "not protected"], ["Created", shortTime(license.created_at || summary.created_at)]])}
    ${accessRecordBlock("Receiver history", detail.activations || [], {
      heading: row => `${row.device_name || "Unnamed receiver"} · ${row.device_kind || "unknown"}`,
      rows: row => [["Install reference", maskedRef(row.install_ref)], ["Credential prefix", row.credential_prefix ? `${row.credential_prefix}…` : "-"], ["Activated", shortTime(row.activated_at)], ["Last seen", shortTime(row.last_seen_at)], ["Revoked", shortTime(row.revoked_at)], ["Reason", row.revoke_reason || "-"]]
    })}
    ${accessRecordBlock("Purchase records", detail.purchases || [], {
      heading: row => `${row.provider || "unknown"} · ${row.environment || "unknown"}`,
      rows: row => [["Product", row.product_id], ["Evidence reference", maskedRef(row.evidence_ref)], ["Reconciliation", row.reconciliation_mode || "device only"], ["Last reconciled", shortTime(row.last_reconciled_at)], ["Next check", shortTime(row.next_reconcile_at)], ["Acknowledgement", row.acknowledgement_state || "-"], ["Reason", row.state_reason || "-"], ["Last verified", shortTime(row.last_verified_at)], ["State changed", shortTime(row.state_changed_at)], ["Updated", shortTime(row.updated_at)]]
    })}
    ${accessRecordBlock("Purchase transitions", detail.purchase_transitions || [], {
      heading: row => `${row.from_state || "new"} → ${row.to_state || "unknown"}`,
      rows: row => [["Source", row.source || "authority"], ["Reason", row.reason_code || "-"], ["Changed", shortTime(row.created_at)]]
    })}
    ${accessRecordBlock("Delivery history", detail.deliveries || [], {
      heading: row => `${row.channel || "unknown"} · ${row.purpose || "delivery"}`,
      rows: row => [["Key version", row.key_version], ["Attempts", row.attempt_count], ["Delivered", shortTime(row.delivered_at)], ["Updated", shortTime(row.updated_at)], ["Detail", row.detail_code || "-"]]
    })}
    ${accessRecordBlock("Provider event linkage", detail.events || [], {
      heading: row => `${row.provider || "unknown"} · ${row.event_type || "event"}`,
      rows: row => [["Status", row.status], ["Detail", row.detail_code || "-"], ["Created", shortTime(row.created_at)], ["Processed", shortTime(row.processed_at)]]
    })}
    ${accessRecordBlock("Notification history", detail.notifications || [], {
      heading: row => `${row.channel || "unknown"} · ${row.purpose || "notification"}`,
      rows: row => [["Status", row.status], ["Attempts", row.attempt_count], ["Next retry", shortTime(row.next_attempt_at)], ["Detail", row.detail_code || "-"]]
    })}`;
}

function apiErrorMessage(payload, fallback) {
  const detail = payload?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (detail && typeof detail === "object") return detail.message || detail.code || fallback;
  return payload?.message || fallback;
}

async function fetchAccessDetail(licenseId) {
  const response = await fetch(`/admin/api/access/${encodeURIComponent(licenseId)}`, { headers: { "Accept": "application/json" } });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(apiErrorMessage(payload, `Relay Access detail: HTTP ${response.status}`));
  return payload;
}

async function openAccessDrawer(summary) {
  if (!summary?.license_id) return;
  activeAccessLicenseId = summary.license_id;
  activeAccessSummary = summary;
  delete drawer.dataset.row;
  drawer.dataset.kind = "access_license";
  drawerTitle.textContent = `Relay Access · ${licenseKeyRef(summary)}`;
  drawerBody.innerHTML = `<p class="muted">Loading masked license diagnostics…</p>`;
  drawer.classList.add("open");
  const selectedId = summary.license_id;
  try {
    const detail = await fetchAccessDetail(selectedId);
    if (activeAccessLicenseId !== selectedId) return;
    activeAccessSummary = { ...summary, ...(detail.license || {}), license_id: selectedId };
    renderAccessDrawer(activeAccessSummary, detail);
  } catch (error) {
    if (activeAccessLicenseId !== selectedId) return;
    drawerBody.innerHTML = `<p class="access-load-error">${esc(error.message || "Unable to load license details.")}</p>`;
  }
}

async function runAccessAction(action, trigger) {
  const licenseId = activeAccessLicenseId;
  if (!licenseId || !activeAccessSummary) return;
  const ref = licenseKeyRef(activeAccessSummary);
  const confirmations = {
    revoke_license: `Revoke ${ref}? This immediately disables the license and revokes its active receiver credential.`,
    suspend_license: `Suspend ${ref}? This immediately revokes its active receiver credential.`,
    reactivate_license: `Reactivate ${ref}? This restores license eligibility, but does not restore a previous receiver credential.`,
    revoke_receiver: `Revoke the active receiver for ${ref}? The device must activate again before using Relay Access.`,
    retry_deliveries: `Retry failed email deliveries for ${ref}?`,
    retry_notifications: `Retry failed recovery, protection, move, or provider notifications for ${ref}?`,
    retry_reconciliation: `Ask the purchase provider to reconcile ${ref} now?`,
    rotate_key: `Rotate the master key for ${ref}? The old key and active receiver credential will be revoked. The replacement key is sent only to the protected holder email and will not appear here.`
  };
  if (!confirm(confirmations[action] || `Run ${action} for ${ref}?`)) return;
  if (trigger) trigger.disabled = true;
  try {
    const response = await fetch(`/admin/api/access/${encodeURIComponent(licenseId)}/action`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify({ action })
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiErrorMessage(payload, `Relay Access action: HTTP ${response.status}`));
    if (action === "rotate_key") {
      const detail = await fetchAccessDetail(licenseId);
      activeAccessSummary = { ...activeAccessSummary, ...(detail.license || {}), license_id: licenseId };
      renderAccessDrawer(activeAccessSummary, detail);
      notice("Master key rotated. Protected email delivery has been queued; no raw key was returned to admin.", "good");
      load("access").catch(error => notice(error.message, "danger"));
      return;
    }
    const messages = {
      revoke_license: "Relay Access license revoked.",
      suspend_license: "Relay Access license suspended.",
      reactivate_license: "Relay Access license reactivated; the receiver must activate again.",
      revoke_receiver: payload.revoked ? "Active receiver revoked." : "No active receiver was attached.",
      retry_deliveries: `${Number(payload.retried || 0)} failed deliveries queued for retry.`,
      retry_notifications: `${Number(payload.retried || 0)} failed notifications queued for retry.`,
      retry_reconciliation: "Provider reconciliation queued."
    };
    notice(messages[action] || "Relay Access action completed.", "good");
    closeDrawer();
    load("access").catch(error => notice(error.message, "danger"));
  } finally {
    if (trigger?.isConnected) trigger.disabled = false;
  }
}

async function post(path, body, confirmText) {
  if (confirmText && !confirm(confirmText)) return;
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", "Accept": "application/json" }, body: JSON.stringify(body || {}) });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(apiErrorMessage(payload, res.statusText));
  notice(payload.message || "Action completed.", "good");
  closeDrawer();
  load(document.querySelector(".nav button.active")?.dataset.view || "overview");
}

function notice(text, kind = "") {
  notices.innerHTML = `<div class="notice ${kind}">${esc(text)}</div>`;
}

document.getElementById("userChip").textContent = "Logged in as " + BOOT.username;
if (BOOT.message) notice(BOOT.message);
if (BOOT.createdToken) notice("Fresh token: " + BOOT.createdToken, "good");
nav.innerHTML = views.map(([key, label]) => `<button data-view="${key}">${label}</button>`).join("");
document.getElementById("quickViews").innerHTML = quickViewDefs.map(([label]) => `<button>${esc(label)}</button>`).join("");

document.addEventListener("click", async ev => {
  const button = ev.target.closest("button");
  const rowEl = ev.target.closest("tr[data-kind]");
  if (button?.dataset.view) { load(button.dataset.view).catch(e => notice(e.message)); return; }
  if (button?.dataset.apply) { const key = button.dataset.apply; state[key].cursor = ""; document.querySelectorAll(`#${key} [data-filter]`).forEach(input => state[key].filters[input.dataset.filter] = input.value); load(key).catch(e => notice(e.message)); return; }
  if (button?.dataset.clear) { const key = button.dataset.clear; state[key].cursor = ""; state[key].filters = {}; load(key).catch(e => notice(e.message)); return; }
  if (button?.dataset.next) { const key = button.dataset.next; state[key].cursor = state[key].last.next_cursor || ""; load(key).catch(e => notice(e.message)); return; }
  if (button?.dataset.prev) { const key = button.dataset.prev; state[key].cursor = ""; load(key).catch(e => notice(e.message)); return; }
  if (button?.dataset.accessAction) {
    try {
      await runAccessAction(button.dataset.accessAction, button);
    } catch (error) {
      notice(error.message || "Relay Access action failed.", "danger");
    }
    return;
  }
  if (button?.dataset.eventAction && button?.dataset.eventRef) {
    return post(
      `/admin/api/access/events/${encodeURIComponent(button.dataset.eventRef)}/action`,
      { action: button.dataset.eventAction },
      "Mark this masked provider event as resolved?"
    );
  }
  if (button?.dataset.action === "createAccessBackup") return post("/admin/api/access-backups/action", { action: "create_backup" }, "Create and verify an encrypted database backup now?");
  if (button?.dataset.action === "verifyAccessBackup") return post("/admin/api/access-backups/action", { action: "verify_latest" });
  if (button?.dataset.action === "saveProviders") return post("/admin/api/providers/save", { aerodatabox_key: aeroKey.value, aviationstack_key: aviKey.value, rapidapi_key: rapidKey.value }, "Save replacement provider keys?");
  if (button?.dataset.action === "clearAero") return post("/admin/api/providers/clear", { provider: "aerodatabox" }, "Clear AeroDataBox override?");
  if (button?.dataset.action === "clearAviation") return post("/admin/api/providers/clear", { provider: "aviationstack" }, "Clear AviationStack override?");
  if (button?.dataset.action === "clearRapid") return post("/admin/api/providers/clear", { provider: "rapidapi" }, "Clear RapidAPI override?");
  if (button?.dataset.action === "resetAll") return post("/admin/api/counters/reset", { scope: "all" }, "Reset all monthly counters?");
  if (button?.dataset.action === "resetLogs") return post("/admin/api/counters/reset", { scope: "logs" }, "Clear request log?");
  if (button?.dataset.action === "correctSchedule") return post("/admin/api/counters/correct-schedule", { total: Number(scheduleTotal.value || 0) }, "Correct schedule total?");
  if (button?.dataset.action === "cleanTrial") return post("/admin/api/maintenance/clean-trial", {}, "Clean setup trial state?");
  if (button?.dataset.drawerAction) {
    const row = JSON.parse(drawer.dataset.row || "{}");
    const action = button.dataset.drawerAction;
    if (action === "resetInstall") return post("/admin/api/counters/reset", { scope: "install", install_ref: row.action_ref }, "Reset install counters?");
    if (action === "blockInstall" || action === "unblockInstall") return post("/admin/api/install/access", { install_ref: row.action_ref, action: action === "blockInstall" ? "block" : "unblock", reason: "revoked by admin" }, "Change install access?");
    if (action.endsWith("Token")) return post("/admin/api/activation/token-action", { token_ref: row.action_ref, token_prefix: row.token_prefix, action: action.replace("Token", "").toLowerCase() }, "Run token action?");
    if (action.endsWith("Request")) return post("/admin/api/activation/request-action", { request_id: row.action_ref || row.request_id, action: action.replace("Request", "").replace("approve", "approve").replace("reject", "reject").replace("delete", "delete").toLowerCase(), decision_note: "dismissed" }, "Run request action?");
  }
  if (rowEl) {
    const active = document.querySelector(".nav button.active")?.dataset.view || "";
    const kind = rowEl.dataset.kind;
    const idx = Number(rowEl.dataset.index);
    const payload = state[active]?.last || {};
    if (kind === "access_license") {
      openAccessDrawer((payload.licenses || [])[idx] || {}).catch(error => notice(error.message, "danger"));
      return;
    }
    const source = kind === "token" ? payload.tokens : kind === "activation_request" ? payload.requests : kind === "request" ? payload.requests?.rows : payload.rows || payload.installs || payload.snapshots || payload.recent_events || [];
    openDrawer(kind, source[idx] || {});
  }
});

document.addEventListener("click", ev => {
  const th = ev.target.closest("th[data-sort]");
  if (!th) return;
  const key = document.querySelector(".nav button.active")?.dataset.view;
  if (!key) return;
  const sort = th.dataset.sort;
  state[key].dir = state[key].sort === sort && state[key].dir === "desc" ? "asc" : "desc";
  state[key].sort = sort;
  state[key].cursor = "";
  load(key).catch(e => notice(e.message));
});

function closeDrawer() {
  drawer.classList.remove("open");
  drawerBody.replaceChildren();
  activeAccessLicenseId = "";
  activeAccessSummary = null;
  delete drawer.dataset.kind;
  delete drawer.dataset.row;
}

drawerClose.onclick = closeDrawer;
document.getElementById("quickViews").querySelectorAll("button").forEach((btn, idx) => btn.onclick = () => {
  const [, key, filters] = quickViewDefs[idx];
  state[key].filters = { ...filters };
  state[key].cursor = "";
  load(key).catch(e => notice(e.message));
  location.hash = key;
});

load("overview").catch(e => notice(e.message));

const IDLE_MS = Math.max(60, BOOT.idleSeconds || 900) * 1000;
const WARN_MS = Math.min(60000, IDLE_MS - 5000);
let _idleTimer = null;
let _warnTimer = null;
function _clearIdleWarn() {
  document.getElementById("idleWarn")?.remove();
  if (_warnTimer) { clearTimeout(_warnTimer); _warnTimer = null; }
}
function _showIdleWarn() {
  _clearIdleWarn();
  const div = document.createElement("div");
  div.id = "idleWarn";
  div.className = "notice warn";
  div.textContent = `Inactive - signing out in ${Math.round(WARN_MS / 1000)}s. Move the mouse or press a key to stay signed in.`;
  notices.appendChild(div);
  _warnTimer = setTimeout(signOut, WARN_MS);
}
function resetIdle() {
  _clearIdleWarn();
  if (_idleTimer) clearTimeout(_idleTimer);
  _idleTimer = setTimeout(_showIdleWarn, IDLE_MS - WARN_MS);
}
function signOut() {
  if (_idleTimer) clearTimeout(_idleTimer);
  _clearIdleWarn();
  fetch("/admin/api/logout", { method: "POST", headers: { "Authorization": "Basic " + btoa("logout:logout") } })
    .catch(() => {})
    .finally(() => { window.location.replace("/admin/signed-out"); });
}
document.getElementById("signOutBtn").onclick = () => {
  if (confirm("Sign out of the Network Admin console?")) signOut();
};
["mousemove", "keydown", "click", "scroll", "touchstart"].forEach(ev =>
  document.addEventListener(ev, resetIdle, { passive: true, capture: true })
);
resetIdle();
