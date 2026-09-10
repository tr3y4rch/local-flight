// Relay Access support workspace. No keys, tokens, or exact searches enter URLs
// or browser storage. Authority and action eligibility always belong to server.
const operatorState = { view: "attention", tab: "summary", license: "", detail: null, config: null, generation: 0,
  filters: {}, cursors: [""], page: 0, next: "", requests: new Map() };
const operatorViews = [["attention", "Needs attention"], ["licenses", "Licenses"], ["email", "Email"], ["toolbox", "Toolbox"], ["history", "History"]];
const operatorTabs = [["summary", "Summary"], ["email", "Email"], ["receiver", "Receiver & usage"], ["ownership", "Ownership"], ["history", "History"]];
const opPost = (path, body) => api(`/admin/api/operator/${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const opButton = (label, action, attrs = "", danger = false) => `<button type="button" class="button ${danger ? "button-danger" : "button-quiet"}" data-op-action="${esc(action)}" ${attrs}>${esc(label)}</button>`;
const opWhen = value => value ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "long" }).format(new Date(value)) : "Permanent";
const opReason = { name: "reason", label: "Operator reason (required)", type: "textarea", required: true };
const opTabs = (items, selected, attr) => `<nav class="operator-tabs" aria-label="${attr === "view" ? "Relay Access views" : "License sections"}">${items.map(([id,label]) => `<button class="operator-tab ${selected === id ? "selected" : ""}" type="button" data-op-${attr}="${id}" ${selected === id ? 'aria-current="page"' : ""}>${label}</button>`).join("")}</nav>`;

function opHistory(page) {
  return (page.items || []).length ? `<ol class="operator-timeline">${page.items.map(row => `<li><div><strong>${esc(titleCase(row.action))}</strong>${badge(row.outcome)}</div><p>${esc(row.reason)}</p>${row.note ? `<p class="operator-note">${esc(row.note)}</p>` : ""}<small>${esc(opWhen(row.created_at))} · ${esc(row.actor === "owner" ? "Authenticated owner" : titleCase(row.actor))}</small><details><summary>Change evidence</summary><pre>${esc(JSON.stringify({ before: row.before, after: row.after }, null, 2))}</pre></details></li>`).join("")}</ol>` : emptyTable("No operator actions recorded yet.");
}

function opEmail(page) {
  return `<p class="operator-caution">Accepted by SMTP does not mean delivered to the recipient. ${esc(page.delivery_notice || "Recipient delivery unknown with this mail connection.")}</p>` + ((page.items || []).length ? `<div class="operator-messages">${page.items.map(m => `<article class="operator-message"><header><div><strong>${esc(titleCase(m.purpose))}</strong><p>${esc(m.recipient)} · ${esc(opWhen(m.created_at))}</p></div>${badge(m.evidence_label, m.status === "uncertain" || m.status === "failed" ? "warn" : "muted")}</header><dl class="operator-facts"><div><dt>Message reference</dt><dd class="mono">${esc(m.message_ref)}</dd></div><div><dt>Next retry</dt><dd>${m.next_attempt_at && m.status !== "sent" ? esc(opWhen(m.next_attempt_at)) : "Not scheduled"}</dd></div><div><dt>Attempts</dt><dd>${number(m.attempt_count)}</dd></div></dl><details><summary>SMTP attempt evidence (${(m.attempts || []).length})</summary>${(m.attempts || []).map(a => `<div class="operator-attempt"><strong>${esc(titleCase(a.outcome))} · ${esc(a.stage)}</strong><span>${esc(opWhen(a.started_at))} → ${a.finished_at ? esc(opWhen(a.finished_at)) : "In progress"}</span><code>${esc(a.message_id)}</code><span>${esc(a.detail_code || "No error category")}${a.smtp_code ? " · SMTP " + esc(a.smtp_code) : ""}</span></div>`).join("") || '<p>No per-attempt evidence exists for this historical message.</p>'}</details><div class="action-buttons">${["failed", "uncertain"].includes(m.status) ? opButton(m.status === "uncertain" ? "Review uncertain outcome" : "Retry failed delivery", "retry_mail", `data-kind="${esc(m.kind)}" data-ref="${esc(m.message_ref)}" data-uncertain="${m.status === "uncertain"}"`) : ""}${(m.status === "pending" || (m.status === "failed" && m.next_attempt_at)) ? opButton("Cancel queued message", "cancel_mail", `data-kind="${esc(m.kind)}" data-ref="${esc(m.message_ref)}"`, true) : ""}${m.license_id && !operatorState.license ? opButton("Open license", "open_license", `data-license="${esc(m.license_id)}"`) : ""}</div></article>`).join("")}</div>` : emptyTable("No email messages match this view."));
}

function opPager(page) {
  operatorState.next = page.next_cursor || "";
  return `<div class="operator-pagination"><button class="button button-quiet" type="button" data-op-page="previous" ${operatorState.page ? "" : "disabled"}>Previous</button><span>Page ${operatorState.page + 1}</span><button class="button button-quiet" type="button" data-op-page="next" ${page.has_more ? "" : "disabled"}>Next</button></div>`;
}

function opSearch(view) {
  const f = operatorState.filters;
  return `<form id="operatorSearch" class="operator-search"><label class="field"><span>Secure search</span><input name="q" type="search" value="${esc(f.q || "")}" placeholder="${view === "email" ? "Message reference, purpose, or exact email" : "License, key reference, or exact email"}" maxlength="240" autocomplete="off"></label>${view === "licenses" ? `<label class="field"><span>Source</span><select name="source"><option value="">All sources</option>${["stripe","apple_subscription","google_play_subscription","founder_legacy","apple_app","google_play_product","operator_complimentary","operator_test"].map(v => `<option value="${v}" ${f.source === v ? "selected" : ""}>${esc(titleCase(v))}</option>`).join("")}</select></label><label class="field"><span>Duration</span><select name="expiry">${[["","Any duration"],["permanent","Permanent"],["expiring","Expires within 7 days"],["expired","Expired"]].map(([v,l])=>`<option value="${v}" ${f.expiry===v ? "selected" : ""}>${l}</option>`).join("")}</select></label>` : ""}<label class="field"><span>State</span><select name="state"><option value="">All states</option>${(view === "email" ? ["pending","sending","sent","failed","uncertain","cancelled"] : ["active","grace","cancelled_active","past_due","expired","suspended","revoked","refunded"]).map(v=>`<option value="${v}" ${f.state===v ? "selected" : ""}>${esc(v === "sent" ? "SMTP accepted" : titleCase(v))}</option>`).join("")}</select></label><button class="button button-primary" type="submit">Search</button></form>`;
}

// The relay resolves entitlement facts server-side; these only phrase them.
function opEntitlementKind(a) {
  return (a && a.entitlement_kind) === "subscription" ? "Annual subscription" : "Permanent";
}
function opRenewal(a) {
  if (!a || a.entitlement_kind !== "subscription") return "Permanent · no renewal";
  return a.auto_renews ? "Renews yearly" : "Ends at period end";
}

function opLicenseTable(page) {
  return dataTable("access",page.items || [],[
    {key:"license_id",label:"License",render:r=>opButton(licenseKeyRef(r),"open_license",`data-license="${esc(r.license_id)}"`)},
    {key:"recipient",label:"Protected recipient"},
    {key:"purchase_source",label:"Authority",render:r=>esc(titleCase(r.purchase_source))},
    {key:"status",label:"State",render:r=>badge(r.authority?.effective_state || r.status)},
    {key:"entitlement",label:"Entitlement",render:r=>esc(opEntitlementKind(r.authority))},
    {key:"expires_at",label:"Paid through",render:r=>esc(opWhen(r.authority?.expires_at))},
    {key:"renewal",label:"Renewal",render:r=>badge(opRenewal(r.authority))},
    {key:"device_kind",label:"Receiver",render:r=>esc(r.device_kind || "Not assigned")},
    {key:"delivery",label:"Last email",render:r=>esc(r.delivery?.[0]?.evidence_label || "No email record")},
    {key:"last_seen_at",label:"Last activity",render:r=>dateTime(r.last_seen_at || r.updated_at)},
  ],{sortable:false,empty:"No licenses match your search."});
}

async function renderOperatorWorkspace() {
  const generation = ++operatorState.generation;
  if (operatorState.license) return openOperatorLicense({ license_id:operatorState.license });
  const view = operatorState.view;
  workspace.innerHTML = workspaceHead("Relay Access", "License support · One owner, one receiver per license") + opTabs(operatorViews,view,"view") + '<div id="operatorContent" class="panel-stack" aria-live="polite"><p>Loading support workspace…</p></div>';
  try {
    let body = "";
    const search = { ...operatorState.filters, cursor:operatorState.cursors[operatorState.page] || "", limit:50 };
    if (view === "licenses") {
      const page = await opPost("licenses/search",search);
      body = panel("Licenses", "Exact email searches stay in the request body. Recipient addresses and key references remain masked.",opSearch(view)+opLicenseTable(page)+opPager(page));
    } else if (view === "email") {
      const page = await opPost("email/search",search);
      body = panel("Email evidence", "SMTP transport evidence, not inbox tracking.",opSearch(view)+`<div class="panel-body">${opEmail(page)}${opPager(page)}</div>`);
    } else if (view === "history") {
      const page = await opPost("history/search",search);
      body = panel("Operator history", "Append-only actions and support notes. Mailbox confirmations and automated expiry are attributed separately.",`<div class="panel-body">${opHistory(page)}${opPager(page)}</div>`);
    } else if (view === "toolbox") {
      const [config, grants, founders] = await Promise.all([api("/admin/api/operator/configuration"),opPost("grants/search",search),api("/admin/api/operator/founders")]);
      operatorState.config = config;
      const grantState = config.issuance_ready ? "Ready" : config.issuance_enabled === false ? "Switched off" : "Not ready";
  // Distinguish a deliberate switch from an unmet server gate. Reporting both
  // as "not ready" with no outstanding gates is what made this panel look broken.
  const grantBlocker = config.issuance_ready ? "" : config.issuance_enabled === false
    ? 'disabled title="Issuance is switched off for this deployment"'
    : 'disabled title="Complete the server-side issuance gates first"';
  body = panel("Issue an invitation", "The recipient must explicitly confirm before a license is activated. Operator grants are not paid purchases.",`<div class="panel-body">${detailSection("Issuance readiness",[["Environment",titleCase(config.environment)],["New grants",grantState],["Outstanding gates",config.readiness_problems.join(", ") || "None"],["One receiver", "Normal provider permissions and limits apply"]])}${opButton(config.environment === "production" ? "Issue complimentary license" : "Issue test license","issue_grant",grantBlocker)}</div>`) +
        panel("Mail and recovery configuration", "No secret values can be displayed or exported.",`<div class="panel-body">${detailSection("Readiness",[["SMTP",config.mail_ready ? "Configured" : "Not ready"],["Recipient delivery", "Unknown with this mail connection"],["Verified backup",config.backup.healthy ? "Healthy" : "Needs attention"],["Latest backup",dateTime(config.backup.last_backup_at)]])}<div class="action-buttons">${opButton("Send non-secret SMTP test","smtp_test",config.mail_ready ? "" : "disabled")}${opButton("Create verified backup","create_backup")}${opButton("Verify latest backup","verify_latest")}</div></div>`) +
        panel("Founder migration", "Preserved legacy installs. Counts only; individual founders are stored as keyed references and are not listed here.",`<div class="panel-body">${founders.total ? detailSection("Bridge progress",[["Founder entitlements",String(founders.total)],["Upgraded to a device credential",String(founders.claimed)],["Still on the legacy bridge",String(founders.awaiting_upgrade)],["Immutable cutoff",opWhen(founders.cutoff_at)],["Bridge closes",opWhen(founders.bridge_expires_at)],["Migration mode",founders.migration_active ? "Active" : "Not active"]]) : emptyTable("No founder entitlements recorded.")}</div>`) +
    panel("Operator grants & invitations", "Pending invitations expire after 24 hours or the grant expiry, whichever is sooner.",`<div class="panel-body">${opGrants(grants)}${opPager(grants)}</div>`);
    } else {
      const p = await api("/admin/api/operator/attention");
      operatorState.config = p.configuration;
      const attention = [["email","Email needs review",(p.email.failed || 0)+(p.email.uncertain || 0),"Failed or uncertain SMTP attempts"],["email","Overdue messages",p.overdue,"Queued or sending for over ten minutes"],["toolbox","Pending invitations",p.pending_invitations,"Waiting for recipient confirmation"],["licenses","Expiring grants",p.expiring_grants,"Expiry within seven days"],["toolbox","Readiness",p.configuration.readiness_problems.length,"Keyrings, SMTP, and verified backups"]];
      body = `<div class="operator-attention">${attention.map(([v,t,n,s])=>`<button type="button" class="operator-attention-card" data-op-view="${v}"><span>${t}</span><strong>${number(n)}</strong><small>${s}</small></button>`).join("")}</div>` + panel("Provider checks", "Stored reconciliation evidence; viewing this page never contacts a provider.",`<div class="panel-body">${accessRecordBlock("Reconciliation",p.provider_checks || [],{heading:r=>r.provider,rows:r=>[["State",r.status],["Last attempt",dateTime(r.last_attempt_at)],["Next attempt",dateTime(r.next_attempt_at)],["Category",r.detail_code]]})}</div>`) + panel("Purchase transitions requiring review", "Existing purchase authority remains separate from operator grants.",accessEventTable((p.purchase_events || []).filter(e=>!["processed","completed","success"].includes(e.status))));
    }
    if (generation !== operatorState.generation || activeView !== "access") return;
    el("operatorContent").innerHTML = body;
  } catch(error) {
    if (generation !== operatorState.generation || activeView !== "access") return;
    el("operatorContent").innerHTML = `<div class="callout"><h3>Workspace could not be loaded</h3><p>${esc(error.message)}</p>${opButton("Try again","refresh")}</div>`;
  }
}

function opGrants(page) {
  return (page.items || []).map(g=>`<article class="operator-message"><header><div><strong>${esc(titleCase(g.kind))} · ${esc(g.recipient)}</strong><p>${esc(g.environment)} · ${esc(opWhen(g.expires_at))}</p></div>${badge(g.status)}</header><p class="mono">${esc(g.grant_id)}</p><p>Invitation deadline: ${esc(opWhen(g.invitation_expires_at))}</p><div class="action-buttons">${g.license_id ? opButton("Open license","open_license",`data-license="${esc(g.license_id)}"`) : ""}${(g.status === "pending" ? ["resend_invitation","adjust_expiry","renew","revoke"] : ["adjust_expiry","renew","suspend","revoke"]).map(a=>opButton(titleCase(a),"grant_action",`data-grant="${esc(g.grant_id)}" data-grant-action="${a}"`,["suspend","revoke"].includes(a))).join("")}</div></article>`).join("") || emptyTable("No operator grants have been created.");
}

async function openOperatorLicense(summary) {
  const generation = ++operatorState.generation;
  operatorState.license = summary.license_id;
  activeAccessLicenseId = summary.license_id;
  closeDrawer();
  workspace.innerHTML = workspaceHead("License workspace", "Loading protected license support…",opButton("Back to licenses","back")) + '<p aria-live="polite">Loading…</p>';
  try {
    const detail = await api(`/admin/api/operator/licenses/${encodeURIComponent(summary.license_id)}`);
    if (generation !== operatorState.generation || activeView !== "access") return;
    operatorState.detail = detail;
    activeAccessSummary = detail.license;
    renderOperatorDetail();
  } catch(error) {
    if (generation !== operatorState.generation || activeView !== "access") return;
    workspace.innerHTML = workspaceHead("License unavailable",error.message,opButton("Back to licenses","back"));
  }
}

function renderOperatorDetail() {
  const d = operatorState.detail;
  const tab = operatorState.tab;
  // The server gates only the actions whose availability depends on licence
  // state (resend, recovery, rotate, email change) and returns a reason for
  // each. Any other action is ungated by design and stays clickable; the POST
  // still requires a typed reason plus explicit confirmation and is validated
  // server-side. An absent key therefore means "not gated", not "unavailable".
  const action = (label,key,danger=false) => {
    const state = d.actions[key];
    const blocked = Boolean(state) && !state.enabled;
    return opButton(label,"license_action",`data-license-action="${key}" ${blocked ? `disabled title="${esc(state.reason)}"` : ""}`,danger);
  };
  const primary = action("Resend license","resend_key_email")+action("Send recovery link","send_recovery_link")+opButton("Run diagnostics","diagnostics");
  let body = "";
  if (tab === "summary") {
    const entitlementRows = [["Key reference",licenseKeyRef(d.license)],["Authority",titleCase(d.authority.source || d.license.purchase_source)],["Entitlement",opEntitlementKind(d.authority)],["State",d.authority.effective_state],["Renewal",opRenewal(d.authority)],["Environment",d.authority.environment],[d.authority.entitlement_kind === "subscription" ? "Paid through" : "Duration",opWhen(d.authority.expires_at)]];
    if (d.authority.grace_expires_at) entitlementRows.push(["Billing grace through",opWhen(d.authority.grace_expires_at)]);
    if ((d.authority.source || d.license.purchase_source) === "founder_legacy") entitlementRows.push(["Founder","Preserved permanent access from the migration snapshot"]);
    entitlementRows.push(["Protected recipient",d.recipient],["Email verification",d.email_protected ? "Confirmed" : "Not confirmed"],["Receiver",d.receivers.some(r=>r.status === "active") ? "Assigned · online status not inferred" : "Not assigned"]);
    body = detailSection("Entitlement",entitlementRows)+
      `<section class="detail-section"><h3>Diagnostics</h3><p>Checked ${esc(opWhen(d.diagnostics.checked_at))}. Stored state and configuration only.</p>${d.diagnostics.findings.length ? `<ul>${d.diagnostics.findings.map(f=>`<li>${esc(f.message)}</li>`).join("")}</ul>` : "<p>No stored-state problems found. This does not certify inbox delivery or live connectivity.</p>"}<div class="action-buttons">${opButton("Copy support summary","copy_summary")}${opButton("Download support summary","download_summary")}</div></section>`;
  } else if (tab === "email") {
    body = opEmail(d.email)+opButton("Browse full delivery history","license_email");
  } else if (tab === "receiver") {
    body = d.receivers.map(r=>`<article class="operator-message"><header><strong>${esc(r.device_name || titleCase(r.device_kind))}</strong>${badge(r.status)}</header>${detailSection("Receiver evidence",[["Support ID",r.support_id],["Activated",opWhen(r.activated_at)],["Last activity",dateTime(r.last_seen_at)],["Presence",r.presence],...Object.entries(r.observed).map(([k,v])=>[titleCase(k),v])])}<div class="action-buttons">${opButton("Find in Fleet","fleet",`data-ref="${esc(r.support_id)}"`)}${opButton("Find reports","reports",`data-ref="${esc(r.support_id)}"`)}</div></article>`).join("") || emptyTable("No receiver activations recorded.");
    body += detailSection(`Usage · ${d.usage.period}`,Object.entries(d.usage.limits).map(([service,limit])=>[titleCase(service),`${number(d.usage.items.find(i=>i.service===service)?.calls || 0)} / ${number(limit)}`]))+`<p>Resets ${esc(opWhen(d.usage.reset_at))}. Renewal does not reset usage.</p>`;
  } else if (tab === "ownership") {
    body = detailSection("Authority",[["Source",titleCase(d.authority.source)],["State",d.authority.authority_state],["Duration",opWhen(d.authority.expires_at)],["Grant",d.authority.grant_id || "Purchased license · grant controls unavailable"]]);
    if (d.authority.grant_id) body += `<div class="action-buttons">${["adjust_expiry","renew","suspend","revoke"].map(a=>opButton(titleCase(a),"grant_action",`data-grant="${esc(d.authority.grant_id)}" data-grant-action="${a}"`,["suspend","revoke"].includes(a))).join("")}</div>`;
    if (d.purchases.some(p=>["server_authoritative","device_and_server"].includes(p.reconciliation_mode))) body += action("Run purchase-provider check","retry_reconciliation");
    body += accessRecordBlock("Purchase authority",d.purchases,{heading:r=>`${r.provider} · ${r.environment}`,rows:r=>[["State",r.state],["Reconciliation",r.reconciliation_mode],["Last verified",dateTime(r.last_verified_at)],["Next check",dateTime(r.next_reconcile_at)]]})+
      `<section class="detail-section"><h3>Protected-email change</h3><p>Both current and proposed mailboxes must confirm within 30 minutes. Completion rotates the key and disconnects the receiver. Other licenses are unchanged. An inaccessible old mailbox requires separate ownership review; there is no verification bypass.</p>${action("Request protected-email change","start_email_change")}${d.email_changes.some(c=>c.status === "pending") ? action("Cancel pending change","cancel_email_change",true) : ""}${d.email_changes.map(c=>`<p>${esc(c.recipient)} · ${esc(c.status)} · Current mailbox ${c.old_confirmed ? "confirmed" : "pending"} · New mailbox ${c.new_confirmed ? "confirmed" : "pending"} · Deadline ${esc(opWhen(c.expires_at))}</p>`).join("")}</section>`;
  } else {
    body = `<section class="detail-section"><h3>Support notes</h3><p>Plain text, encrypted at rest, append-only. Add a correction as a new note.</p>${action("Add support note","add_note")}</section>`+opHistory(d.history)+opButton("Browse full operator history","license_history")+accessRecordBlock("Purchase transitions",d.purchase_transitions,{heading:r=>`${r.from_state || "New"} → ${r.to_state}`,rows:r=>[["Source",r.source],["Reason",r.reason_code],["Changed",dateTime(r.created_at)]]});
  }
  workspace.innerHTML = workspaceHead(licenseKeyRef(d.license),`${d.recipient} · ${titleCase(d.authority.effective_state)}`,opButton("Back to licenses","back"))+opTabs(operatorViews,operatorState.view,"view")+`<div class="operator-primary">${primary}</div>`+opTabs(operatorTabs,tab,"tab")+panel(operatorTabs.find(([id])=>id===tab)[1],"",`<div class="panel-body operator-detail">${body}</div>`)+`<details class="operator-danger"><summary>Disruptive actions</summary><p>These actions can stop access or disconnect a receiver. A reason and explicit confirmation are required.</p><div class="action-buttons">${action("Disconnect receiver","revoke_receiver",true)}${action("Rotate key & disconnect","rotate_key",true)}${action("Suspend license","suspend_license",true)}${action("Revoke license","revoke_license",true)}${["suspended","revoked"].includes(d.authority.effective_state) && ["paid","purchased","issued"].includes(d.authority.authority_state) ? action("Restore eligibility","reactivate_license") : ""}</div></details>`;
}

async function opMutate(path,body) {
  const signature = JSON.stringify([path,body]);
  let requestId = operatorState.requests.get(signature);
  if (!requestId) { requestId = crypto.randomUUID(); operatorState.requests.set(signature,requestId); }
  // Retain request IDs in memory so a network retry replays the same operation.
  if (operatorState.requests.size > 100) operatorState.requests.delete(operatorState.requests.keys().next().value);
  const result = await opPost(path,{ ...body,request_id:requestId });
  operatorState.requests.delete(signature);
  return result;
}

async function operatorLicenseAction(action) {
  const d = operatorState.detail;
  if (!d) return;
  if (action === "retry_reconciliation") {
    const values=await ask({title:"Run purchase-provider check",copy:"Contact the purchase provider to reconcile stored ownership authority. This is not an aviation-provider request and does not change provider permissions.",fields:[opReason],confirmLabel:"Queue provider check"});
    if (!values) return;
    await opMutate(`licenses/${encodeURIComponent(d.license.license_id)}/action`,{action,...values});
    return openOperatorLicense({license_id:d.license.license_id});
  }
  const copy = {resend_key_email:"Send the current key to the verified protected address. The key and receiver stay unchanged. A ten-minute cooldown applies.",send_recovery_link:"Send a short-lived recovery/verification link to the bound address. This does not rotate the key.",add_note:"Add an append-only support note, subject to the configured retention period. Credentials and email addresses are redacted. Corrections must be new notes.",start_email_change:"Both mailboxes must explicitly confirm within 30 minutes. Only then will ownership change, the key rotate, and the receiver disconnect.",cancel_email_change:"Cancel pending confirmations; existing ownership stays unchanged.",rotate_key:"Invalidate the old key, disconnect active and pending receivers, and email a replacement only to the verified protected address.",revoke_receiver:"Disconnect the receiver. It must activate again; usage is not reset.",suspend_license:"Suspend access and disconnect the receiver.",revoke_license:"Revoke access and disconnect the receiver.",reactivate_license:"Restore eligibility only if purchase or grant authority allows it. Old receiver credentials are not revived."}[action];
  if (!copy) return;
  const disruptive = !["resend_key_email","send_recovery_link","add_note"].includes(action);
  const fields = [opReason];
  if (action === "start_email_change") fields.unshift({name:"email",label:"Proposed protected email",type:"email",required:true});
  if (action === "add_note") fields.unshift({name:"note",label:"Support note",type:"textarea",required:true});
  const values = await ask({title:titleCase(action),copy,fields,confirmLabel:action === "add_note" ? "Append note" : "Confirm action",tone:disruptive ? "danger" : "",verify:disruptive ? "CONFIRM" : ""});
  if (!values) return;
  await opMutate(`licenses/${encodeURIComponent(d.license.license_id)}/action`,{action,...values,confirmed:true});
  toast("Operator action recorded.","good");
  await openOperatorLicense({license_id:d.license.license_id});
}

async function opGrantWizard(grantId="",action="") {
  const config = operatorState.config || await api("/admin/api/operator/configuration");
  const issue = !grantId;
  const duration = issue || ["renew","adjust_expiry"].includes(action);
  const test = config.environment === "staging";
  const existing = !issue && duration ? (await opPost("grants/search",{q:grantId,limit:1})).items[0] : null;
  const limited = issue ? test : Boolean(existing?.expires_at);
  const suggestedExpiry = existing?.expires_at && new Date(existing.expires_at) > new Date() ? new Date(existing.expires_at) : new Date(Date.now()+7*86400000);
  const fields = [opReason];
  if (issue) fields.unshift({name:"email",label:"Recipient email",type:"email",required:true},{name:"support_reference",label:"Support reference (optional)"});
  if (duration) fields.unshift({name:"duration",label:"Duration",type:"select",value:limited ? "limited" : "permanent",options:[["permanent","Permanent"],["limited","Time-limited"]]}, {name:"expires_at",label:`Expiry date and time (${Intl.DateTimeFormat().resolvedOptions().timeZone})`,type:"datetime-local",value:new Date(suggestedExpiry.getTime()-suggestedExpiry.getTimezoneOffset()*60000).toISOString().slice(0,16),hint:"Used only for time-limited grants. Stored as an absolute UTC timestamp."});
  const values = await ask({title:issue ? `Issue ${test ? "test" : "complimentary"} invitation` : titleCase(action),copy:issue ? "The recipient must confirm the invitation before the license and key delivery are activated." : "Grant-specific action. Normal one-receiver and provider limits apply. Renewal never resets usage or revives old receiver credentials.",fields,confirmLabel:"Review"});
  if (!values) return;
  const expiry = duration && values.duration === "limited" ? new Date(values.expires_at).toISOString() : null;
  if (expiry && new Date(expiry) <= new Date()) throw new Error("Choose a future expiry date and time.");
  const recipient = issue ? values.email.replace(/^(.).*(@.*)$/,"$1***$2") : "Current grant recipient";
  const confirmed = await ask({title:"Confirm operator grant",copy:`Environment: ${config.environment}. Recipient: ${recipient}. ${duration ? "Duration: "+opWhen(expiry)+". " : "Action: "+titleCase(action)+". "}One receiver only; normal provider limits. ${issue ? "Invitation expires after 24 hours or grant expiry, whichever is sooner." : "This changes only the selected operator grant."}`,confirmLabel:issue ? "Queue invitation" : "Apply grant change",verify:issue ? "ISSUE" : "CONFIRM",tone:["suspend","revoke"].includes(action) ? "danger" : ""});
  if (!confirmed) return;
  await opMutate(issue ? "grants" : `grants/${encodeURIComponent(grantId)}/action`,{reason:values.reason,email:values.email || "",support_reference:values.support_reference || "",kind:test ? "test" : "complimentary",expires_at:expiry,action,confirmed:true});
  toast(issue ? "Invitation queued. No license is active until the recipient confirms." : "Grant action recorded.","good");
  await renderOperatorWorkspace();
}

async function operatorCommand(button) {
  const a = button.dataset.opAction;
  if (a === "refresh") return renderOperatorWorkspace();
  if (a === "back") { operatorState.license="";operatorState.tab="summary";operatorState.view="licenses";return renderOperatorWorkspace(); }
  if (a === "open_license") { operatorState.tab="summary";return openOperatorLicense({license_id:button.dataset.license}); }
  if (a === "license_action") return operatorLicenseAction(button.dataset.licenseAction);
  if (a === "diagnostics") { operatorState.tab="summary";return openOperatorLicense({license_id:operatorState.license}); }
  if (a === "issue_grant") return opGrantWizard();
  if (a === "grant_action") return opGrantWizard(button.dataset.grant,button.dataset.grantAction);
  if (["fleet","reports"].includes(a)) { operatorState.license="";return navigate(a,{q:button.dataset.ref}); }
  if (["license_history","license_email"].includes(a)) { operatorState.filters={license_id:operatorState.license};operatorState.license="";operatorState.view=a === "license_history" ? "history" : "email";operatorState.cursors=[""];operatorState.page=0;return renderOperatorWorkspace(); }
  if (["copy_summary","download_summary"].includes(a)) {
    const d = operatorState.detail;
    const summary = JSON.stringify({license_ref:d.license.license_id,key_ref:licenseKeyRef(d.license),authority:d.authority,recipient:d.recipient,receiver_support_ids:d.receivers.map(r=>r.support_id),usage:d.usage,diagnostics:d.diagnostics,recipient_delivery:"Unknown with this mail connection"},null,2);
    if (a === "copy_summary") { await navigator.clipboard.writeText(summary);toast("Sanitized support summary copied.","good"); }
    else { const url=URL.createObjectURL(new Blob([summary],{type:"application/json"}));const link=document.createElement("a");link.href=url;link.download="relay-access-support.json";link.click();setTimeout(()=>URL.revokeObjectURL(url),1000); }
    return;
  }
  const mail = ["retry_mail","cancel_mail"].includes(a);
  const uncertain = button.dataset.uncertain === "true";
  const copy = mail ? uncertain ? "SMTP acceptance is uncertain. Retrying may deliver a duplicate email. This does not rotate the license key." : a === "cancel_mail" ? "Cancel only if sending has not begun. A message already transmitting cannot be recalled." : "Retry this eligible message, retaining all attempt history." : a === "smtp_test" ? "Send a clearly labelled, credential-free test to the configured support reply-to address, falling back to the sender. No license key or recovery link is included." : "Create or verify an encrypted database snapshot. No database download or secrets are exposed.";
  const values=await ask({title:titleCase(a),copy,fields:[opReason],confirmLabel:uncertain ? "Retry — possible duplicate" : "Confirm",verify:uncertain ? "RETRY" : ""});
  if (!values) return;
  await opMutate(mail ? `email/${encodeURIComponent(button.dataset.kind)}/${encodeURIComponent(button.dataset.ref)}/action` : "toolbox/action",{...values,action:mail ? (a === "retry_mail" ? "retry" : "cancel") : a,acknowledge_duplicate:uncertain});
  toast("Action recorded. Email evidence updates after the send attempt.","good");
  return renderOperatorWorkspace();
}

document.addEventListener("click",event=>{
  const button=event.target.closest("button");
  if (!button) return;
  if (button.dataset.opView) { operatorState.generation++;operatorState.view=button.dataset.opView;operatorState.license="";operatorState.filters={};operatorState.cursors=[""];operatorState.page=0;renderOperatorWorkspace(); }
  if (button.dataset.opTab) { operatorState.tab=button.dataset.opTab;renderOperatorDetail(); }
  if (button.dataset.opPage) { if (button.dataset.opPage === "next") operatorState.cursors[++operatorState.page]=operatorState.next;else operatorState.page=Math.max(0,operatorState.page-1);renderOperatorWorkspace(); }
  if (button.dataset.opAction) perform(()=>operatorCommand(button),button);
});
document.addEventListener("submit",event=>{
  if (event.target.id !== "operatorSearch") return;
  event.preventDefault();operatorState.filters=Object.fromEntries(new FormData(event.target).entries());operatorState.cursors=[""];operatorState.page=0;renderOperatorWorkspace();
});
