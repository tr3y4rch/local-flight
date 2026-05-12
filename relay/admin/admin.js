const BOOT = __BOOT__;
const views = [
  ["overview","Overview"],["fleet","Fleet"],["traffic","Traffic"],["schedules","Schedules"],["surfaces","Surfaces"],["reports","Reports"],["activations","Activations"],["providers","Providers"],["maintenance","Maintenance"]
];
const state = Object.fromEntries(views.map(([key]) => [key, {cursor:"", last:"", filters:{}, sort:"last_seen", dir:"desc"}]));
const endpoints = {
  overview:"/admin/api/overview", fleet:"/admin/api/fleet", traffic:"/admin/api/usage", schedules:"/admin/api/schedules",
  surfaces:"/admin/api/surfaces", reports:"/admin/api/reports", activations:"/admin/api/activations"
};
const columns = {
  fleet:[["install_fingerprint","Install"],["first_seen","First seen"],["last_seen","Last seen"],["os_family","OS"],["effective_gui","GUI"],["app_version","Version"],["plan","Plan"],["current_lane.airport_iata","Airport"],["companion_count","Companion"],["matrix_online_count","Matrix"],["schedule_calls","Schedule"],["radar_calls","Radar"],["status","Status"]],
  traffic:[["service","Service"],["plan","Plan"],["calls","Calls"],["subject.fingerprint","Subject"],["last_seen","Last seen"]],
  requests:[["ts","Time"],["install_fingerprint","Install"],["service","Service"],["scope","Scope"],["status","Status"],["latency_ms","Latency"],["plan","Plan"]],
  schedules:[["airport_iata","Airport"],["timezone","Timezone"],["client_accesses","Serves"],["upstream_pulls","Pulls"],["cache_hits","Hits"],["last_cache_state","State"],["updated_at","Updated"],["last_error","Error"]],
  surfaces:[["airport_iata","IATA"],["airport_icao","ICAO"],["feature_count","Features"],["request_count","Requests"],["cache_hits","Hits"],["last_cache_state","State"],["updated_at","Updated"],["last_error","Error"]],
  reports:[["ts","Time"],["install_fingerprint","Install"],["report_type","Type"],["origin","Origin"],["team","Team"],["status","Status"],["network_tag","Network"]],
  tokens:[["token_prefix","Prefix"],["label","Label"],["schedule_limit","Schedule"],["radar_limit","Radar"],["bound_install_fingerprint","Bound"],["last_seen","Last"],["revoked","Revoked"]],
  requestsQueue:[["request_id","Request"],["install_fingerprint","Install"],["network_tag","Network"],["airport_iata","Airport"],["display_name","Display"],["status","Status"],["updated_at","Updated"],["decision_note","Note"]]
};
const quickViewDefs = [
  ["Recently seen (≤24h)","fleet",{status:"active"}],["Blocked/revoked","fleet",{blocked:"true"}],["Companion users","fleet",{has_companion:"true"}],
  ["Matrix installs","fleet",{has_matrix:"true"}],["macOS native","fleet",{os_family:"macos",effective_gui:"native"}],["Windows native","fleet",{os_family:"windows",effective_gui:"native"}],
  ["Stale cache/error lanes","schedules",{cache_state:"stale"}],["Pending activation review","activations",{}]
];
function esc(value) {
  const map = {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"};
  return String(value ?? "").replace(/[&<>"']/g, ch => map[ch]);
}
function valueAt(row, path) { return path.split(".").reduce((v,k) => v && typeof v === "object" ? v[k] : "", row); }
function badge(value) {
  const text = esc(value || "-"); const lower = text.toLowerCase();
  const tone = lower.includes("active") || lower.includes("fresh") || lower === "200" || lower === "false" ? "good" : lower.includes("error") || lower.includes("blocked") || lower.includes("revoked") || lower.includes("failed") ? "bad" : lower.includes("stale") || lower.includes("pending") || lower.includes("manual") ? "warn" : "";
  return `<span class="badge ${tone}">${text}</span>`;
}
function setNav(active) {
  document.querySelectorAll(".nav button").forEach(btn => btn.classList.toggle("active", btn.dataset.view === active));
}
function paramsFor(key) {
  const params = new URLSearchParams();
  Object.entries(state[key]?.filters || {}).forEach(([k,v]) => { if (v !== "" && v != null) params.set(k, v); });
  if (state[key]?.cursor) params.set("cursor", state[key].cursor);
  params.set("limit", "100");
  if (state[key]?.sort) params.set("sort", state[key].sort);
  if (state[key]?.dir) params.set("dir", state[key].dir);
  return params;
}
async function load(key) {
  setNav(key);
  const endpoint = endpoints[key];
  if (!endpoint) return renderStatic(key);
  const qs = paramsFor(key).toString();
  const response = await fetch(endpoint + (qs ? "?" + qs : ""), {headers: {"Accept":"application/json"}});
  if (!response.ok) throw new Error(`${key}: HTTP ${response.status}`);
  const payload = await response.json();
  state[key].last = payload;
  render(key, payload);
}
function panel(key, title, copy, tools, body, pager="") {
  document.getElementById(key).innerHTML = `<div class="panel-head"><div><h2>${esc(title)}</h2><div class="muted">${esc(copy)}</div></div><div class="muted">${tools || ""}</div></div>${body}${pager}`;
}
function metrics(items) {
  return `<div class="grid">${items.map(([label,value,sub]) => `<div class="metric"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="muted">${esc(sub || "")}</div></div>`).join("")}</div>`;
}
function filters(key, defs) {
  return `<div class="filters">${defs.map(def => {
    const [name,label,type,options] = def; const value = state[key].filters[name] || "";
    if (type === "select") return `<select data-filter="${esc(name)}"><option value="">${esc(label)}</option>${(options || []).map(opt => `<option value="${esc(opt)}" ${String(value).toLowerCase() === String(opt).toLowerCase() ? "selected" : ""}>${esc(opt)}</option>`).join("")}</select>`;
    return `<input data-filter="${esc(name)}" type="${type || "search"}" placeholder="${esc(label)}" value="${esc(value)}">`;
  }).join("")}<button data-apply="${key}">Apply</button><button data-clear="${key}">Clear</button></div>`;
}
function table(key, rows, cols, kind) {
  if (!rows || !rows.length) return `<div class="table-wrap"><table><tbody><tr><td class="muted">No rows for this view.</td></tr></tbody></table></div>`;
  return `<div class="table-wrap"><table><thead><tr>${cols.map(([path,label]) => `<th data-sort="${esc(path)}">${esc(label)}</th>`).join("")}</tr></thead><tbody>${rows.map((row,idx) => `<tr data-kind="${esc(kind || key)}" data-index="${idx}">${cols.map(([path]) => {
    const value = valueAt(row,path); const cell = path.includes("status") || path.includes("state") || path === "revoked" ? badge(value) : esc(value);
    return `<td>${cell}</td>`;
  }).join("")}</tr>`).join("")}</tbody></table></div>`;
}
function pager(key, payload) {
  return `<div class="pager"><span>${payload.filtered_estimate ?? 0} filtered / ${payload.total_estimate ?? 0} total</span><span><button data-prev="${key}">Previous</button> <button data-next="${key}" ${payload.next_cursor ? "" : "disabled"}>Next</button></span></div>`;
}
function render(key, payload) {
  if (key === "overview") {
    const c = payload.counts || {}, f = payload.fleet || {}, s = payload.shared_schedule || {};
    panel("overview","Overview","Launch-scale health snapshot. Counts marked 24h are last-seen windows, not live concurrency.","Monitor", metrics([
      ["Known installs", c.known_installs || f.known_installs || 0, "Fleet rows"],
      ["Seen ≤24h", c.active_installs_24h || f.active_installs_24h || 0, "Heartbeat or relay activity"],
      ["Requests 24h", c.requests_24h || 0, "Relay traffic"],
      ["Reports 24h", c.reports_24h || 0, "Report gateway"],
      ["Pending review", c.activation_requests_pending || 0, "Activation queue"],
      ["Cache hits", s.cache_hits || 0, "Shared schedules"],
      ["Upstream pulls", s.upstream_pulls || 0, "Provider load"],
      ["Blocked installs", c.blocked_installs || 0, "Access revoked"]
    ]));
  } else if (key === "fleet") {
    const facets = payload.facets || {};
    const opts = name => Object.keys(facets[name] || {});
    const body = filters(key,[["q","Search fleet"],["status","Status","select",opts("status")],["plan","Plan","select",opts("plan")],["os_family","OS","select",opts("os_family")],["effective_gui","GUI","select",opts("effective_gui")],["app_version","Version","select",opts("app_version")],["airport_iata","Airport"],["has_companion","Companion","select",["true","false"]],["has_matrix","Matrix","select",["true","false"]],["blocked","Blocked","select",["true","false"]],["managed","Managed","select",["true","false"]]]) + table(key,payload.rows || payload.installs || [],columns.fleet,"fleet");
    panel(key,"Fleet","Install registry with server-side filters and opaque action refs. Last seen reflects coarse heartbeat presence (~30 min cadence) and relay activity, not live online status.","Investigate",body,pager(key,payload));
  } else if (key === "traffic") {
    const reqRows = payload.requests?.rows || [];
    const body = filters(key,[["q","Search traffic"],["service","Service"],["plan","Plan"],["status","Status or error"]]) + table(key,payload.rows || [],columns.traffic,"usage") + `<div class="panel-head"><div><h2>Request tail</h2><div class="muted">Recent transport health</div></div></div>` + table(key,reqRows,columns.requests,"request");
    panel(key,"Traffic","Monthly usage and recent request health.","Monitor",body,pager(key,payload));
  } else if (key === "schedules" || key === "surfaces") {
    const body = filters(key,[["q","Search cache"],["airport_iata","Airport"],["cache_state","Cache state"]]) + table(key,payload.rows || payload.snapshots || [],columns[key],key);
    panel(key,key === "schedules" ? "Schedules" : "Surfaces",key === "schedules" ? "Shared schedule cache lanes." : "Airport surface cache lanes.","Investigate",body,pager(key,payload));
  } else if (key === "reports") {
    const body = filters(key,[["q","Search reports"],["report_type","Type"],["origin","Origin"],["team","Team"],["status","Status"]]) + table(key,payload.rows || payload.recent_events || [],columns.reports,"report");
    panel(key,"Reports","Sanitized report gateway events and dedupe state.","Investigate",body,pager(key,payload));
  } else if (key === "activations") {
    const body = table(key,payload.tokens || [],columns.tokens,"token") + `<div class="panel-head"><div><h2>Activation queue</h2><div class="muted">Manual review and issued requests</div></div></div>` + table(key,payload.requests || [],columns.requestsQueue,"activation_request");
    panel(key,"Activations","Managed tokens and activation queue.","Operate",body);
  }
}
function renderStatic(key) {
  if (key === "providers") panel(key,"Providers","Save or clear relay provider key overrides.","Operate",`<div class="filters"><input id="aeroKey" type="password" placeholder="Replacement AeroDataBox key"><input id="aviKey" type="password" placeholder="Replacement AviationStack key"><input id="rapidKey" type="password" placeholder="Replacement RapidAPI key"><button data-action="saveProviders">Save keys</button><button data-action="clearAero">Clear AeroDataBox</button><button data-action="clearAviation">Clear AviationStack</button><button data-action="clearRapid">Clear RapidAPI</button></div>`);
  if (key === "maintenance") panel(key,"Maintenance","Danger Zone actions stay separated from monitoring.","Danger Zone",`<div class="filters"><button data-action="resetAll">Reset all monthly counters</button><button data-action="resetLogs">Clear request log</button><input id="scheduleTotal" type="number" min="0" placeholder="Known schedule total"><button data-action="correctSchedule">Correct schedule total</button><button data-action="cleanTrial">Clean setup trial state</button></div>`);
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
  drawer.dataset.kind = kind; drawer.dataset.row = JSON.stringify(row);
  drawerTitle.textContent = `${kind.replace("_"," ")} details`;
  drawerBody.innerHTML = `<div class="quick">${actions.join("")}</div><pre>${esc(JSON.stringify(row,null,2))}</pre>`;
  drawer.classList.add("open");
}
async function post(path, body, confirmText) {
  if (confirmText && !confirm(confirmText)) return;
  const res = await fetch(path,{method:"POST",headers:{"Content-Type":"application/json","Accept":"application/json"},body:JSON.stringify(body || {})});
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(payload.detail || res.statusText);
  notice(payload.message || "Action completed.", "good");
  drawer.classList.remove("open");
  load(document.querySelector(".nav button.active")?.dataset.view || "overview");
}
function notice(text, kind="") { notices.innerHTML = `<div class="notice ${kind}">${esc(text)}</div>`; }
document.getElementById("userChip").textContent = "Logged in as " + BOOT.username;
if (BOOT.message) notice(BOOT.message);
if (BOOT.createdToken) notice("Fresh token: " + BOOT.createdToken, "good");
nav.innerHTML = views.map(([key,label]) => `<button data-view="${key}">${label}</button>`).join("");
document.getElementById("quickViews").innerHTML = quickViewDefs.map(([label]) => `<button>${esc(label)}</button>`).join("");
document.addEventListener("click", async ev => {
  const button = ev.target.closest("button"); const rowEl = ev.target.closest("tr[data-kind]");
  if (button?.dataset.view) { load(button.dataset.view).catch(e => notice(e.message)); return; }
  if (button?.dataset.apply) { const key = button.dataset.apply; state[key].cursor = ""; document.querySelectorAll(`#${key} [data-filter]`).forEach(input => state[key].filters[input.dataset.filter] = input.value); load(key).catch(e => notice(e.message)); return; }
  if (button?.dataset.clear) { const key = button.dataset.clear; state[key].cursor = ""; state[key].filters = {}; load(key).catch(e => notice(e.message)); return; }
  if (button?.dataset.next) { const key = button.dataset.next; state[key].cursor = state[key].last.next_cursor || ""; load(key).catch(e => notice(e.message)); return; }
  if (button?.dataset.prev) { const key = button.dataset.prev; state[key].cursor = ""; load(key).catch(e => notice(e.message)); return; }
  if (button?.dataset.action === "saveProviders") return post("/admin/api/providers/save",{aerodatabox_key:aeroKey.value,aviationstack_key:aviKey.value,rapidapi_key:rapidKey.value},"Save replacement provider keys?");
  if (button?.dataset.action === "clearAero") return post("/admin/api/providers/clear",{provider:"aerodatabox"},"Clear AeroDataBox override?");
  if (button?.dataset.action === "clearAviation") return post("/admin/api/providers/clear",{provider:"aviationstack"},"Clear AviationStack override?");
  if (button?.dataset.action === "clearRapid") return post("/admin/api/providers/clear",{provider:"rapidapi"},"Clear RapidAPI override?");
  if (button?.dataset.action === "resetAll") return post("/admin/api/counters/reset",{scope:"all"},"Reset all monthly counters?");
  if (button?.dataset.action === "resetLogs") return post("/admin/api/counters/reset",{scope:"logs"},"Clear request log?");
  if (button?.dataset.action === "correctSchedule") return post("/admin/api/counters/correct-schedule",{total:Number(scheduleTotal.value || 0)},"Correct schedule total?");
  if (button?.dataset.action === "cleanTrial") return post("/admin/api/maintenance/clean-trial",{},"Clean setup trial state?");
  if (button?.dataset.drawerAction) {
    const row = JSON.parse(drawer.dataset.row || "{}");
    const action = button.dataset.drawerAction;
    if (action === "resetInstall") return post("/admin/api/counters/reset",{scope:"install",install_ref:row.action_ref},"Reset install counters?");
    if (action === "blockInstall" || action === "unblockInstall") return post("/admin/api/install/access",{install_ref:row.action_ref,action:action === "blockInstall" ? "block" : "unblock",reason:"revoked by admin"},"Change install access?");
    if (action.endsWith("Token")) return post("/admin/api/activation/token-action",{token_ref:row.action_ref,token_prefix:row.token_prefix,action:action.replace("Token","").replace("reactivate","reactivate").toLowerCase()},"Run token action?");
    if (action.endsWith("Request")) return post("/admin/api/activation/request-action",{request_id:row.action_ref || row.request_id,action:action.replace("Request","").replace("approve","approve").replace("reject","reject").replace("delete","delete").toLowerCase(),decision_note:"dismissed"},"Run request action?");
  }
  if (rowEl) {
    const active = document.querySelector(".nav button.active")?.dataset.view || "";
    const kind = rowEl.dataset.kind; const idx = Number(rowEl.dataset.index);
    const payload = state[active]?.last || {}; const source = kind === "token" ? payload.tokens : kind === "activation_request" ? payload.requests : kind === "request" ? payload.requests?.rows : payload.rows || payload.installs || payload.snapshots || payload.recent_events || [];
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
  state[key].sort = sort; state[key].cursor = "";
  load(key).catch(e => notice(e.message));
});
drawerClose.onclick = () => drawer.classList.remove("open");
document.getElementById("quickViews").querySelectorAll("button").forEach((btn, idx) => btn.onclick = () => {
  const [, key, filters] = quickViewDefs[idx]; state[key].filters = {...filters}; state[key].cursor = ""; load(key).catch(e => notice(e.message)); location.hash = key;
});
load("overview").catch(e => notice(e.message));

// ── Sign out + idle auto-logoff ─────────────────────────────────────────────
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
  div.id = "idleWarn"; div.className = "notice warn";
  div.textContent = `Inactive — signing out in ${Math.round(WARN_MS / 1000)}s. Move the mouse or press a key to stay signed in.`;
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
  // Poison the cached basic-auth credential so most browsers re-prompt next visit.
  fetch("/admin/api/logout", {method:"POST", headers:{"Authorization":"Basic " + btoa("logout:logout")}})
    .catch(() => {})
    .finally(() => { window.location.replace("/admin/signed-out"); });
}
document.getElementById("signOutBtn").onclick = () => {
  if (confirm("Sign out of the Network Admin console?")) signOut();
};
["mousemove","keydown","click","scroll","touchstart"].forEach(ev =>
  document.addEventListener(ev, resetIdle, {passive:true, capture:true})
);
resetIdle();
