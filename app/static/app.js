/* RiskLens client portal — vanilla JS over the FastAPI backend. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const state = { meta: null, overview: null, rows: [], sort: { key: "risk_score", dir: -1 }, band: "all", q: "", charts: {} };
  const REGIONS = ["East Asia", "Southeast Asia", "Middle East", "Europe", "North America"];
  const CATEGORIES = ["Electronics", "Textiles", "Perishables", "Pharmaceuticals", "Automotive"];
  const MODES = ["Sea", "Air", "Road", "Rail"];
  const PORT_LIST = ["Antwerp", "Busan", "Dubai", "Hamburg", "Los Angeles", "Marseille", "Rotterdam", "Shanghai", "Singapore"];
  const WEATHER_LIST = ["Clear", "Rain", "Fog", "Storm", "Hurricane"];
  const BAND_COLOR = { low: "#15803D", elevated: "#B45309", high: "#B91C1C" };

  // ---------- utils ----------
  const fmtUSD = (v) => { v = +v || 0; const a = Math.abs(v), s = v < 0 ? "-" : ""; if (a >= 1e6) return s + "$" + (a / 1e6).toFixed(a >= 1e7 ? 1 : 2) + "M"; if (a >= 1e3) return s + "$" + (a / 1e3).toFixed(0) + "K"; return s + "$" + a.toFixed(0); };
  const fmtDate = (iso) => { if (!iso) return "—"; const d = new Date(iso + "T00:00:00"); return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }); };
  const fmtDateY = (iso) => { if (!iso) return "—"; const d = new Date(String(iso).length === 7 ? iso + "-01T00:00:00" : iso + "T00:00:00"); return d.toLocaleDateString("en-GB", String(iso).length === 7 ? { month: "short", year: "numeric" } : { day: "numeric", month: "short", year: "numeric" }); };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
  const toast = (msg) => { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(t._t); t._t = setTimeout(() => t.classList.remove("show"), 2800); };
  const heatColor = (v) => {
    const lerp = (a, b, t) => a + (b - a) * t; const c = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
    const [a, b, t] = v < 0.5 ? [c("#F2F4F7"), c("#FDE68A"), v / 0.5] : [c("#FDE68A"), c("#DC2626"), (v - 0.5) / 0.5];
    return `rgb(${a.map((x, i) => Math.round(lerp(x, b[i], t))).join(",")})`;
  };
  const textOn = (v) => (v > 0.72 ? "#fff" : "#101828");
  async function api(path, opts = {}) {
    const isForm = opts.body instanceof FormData;
    const res = await fetch(path, { method: opts.method || (opts.body ? "POST" : "GET"), headers: opts.body && !isForm ? { "Content-Type": "application/json" } : {}, body: opts.body && !isForm ? JSON.stringify(opts.body) : opts.body });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { const err = new Error(typeof data.detail === "string" ? data.detail : "Request failed"); err.detail = data.detail; throw err; }
    return data;
  }
  const chip = (band) => `<span class="chip ${band}">${band}</span>`;
  const scoreBar = (r) => `<span class="scorebar"><span class="track"><span class="fill ${r.risk_band}" style="width:${Math.max(2, r.risk_score)}%"></span></span><span class="val">${r.risk_score.toFixed(1)}</span></span>`;
  const route = (r) => `${esc(r.origin_port || "—")} <span class="arrow">→</span> ${esc(r.destination_port || "—")}`;
  const routeText = (r) => `${r.origin_port || "—"} → ${r.destination_port || "—"}`;
  const days = (n) => (n === 0 ? "same day" : `${n > 0 ? "+" : "−"}${Math.abs(n)} d`);

  // ---------- navigation ----------
  const PAGES = {
    overview: ["Overview", () => { const s = state.overview?.summary; return s ? `${s.n} active consignments · ${s.in_transit} in transit, ${s.scheduled} scheduled · as of ${fmtDateY(s.as_of)}` : ""; }],
    consignments: ["Consignments", () => "Your consignment book. Click a consignment for its cargo profile: what it is, the load, and how it must be handled."],
    actions: ["Recommended actions", () => "Mitigations across your consignments, ranked by net benefit."],
    workflow: ["Intelligent workflow", () => "Two agents agree the plan, the stakeholder signs off, and RiskLens deploys the action."],
    whatif: ["What-if analysis", () => "Test a planned consignment or a batch before you book it."],
  };
  function show(view) {
    if (!PAGES[view]) view = "overview";
    closeDrawer();
    $$(".nav-item").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + view));
    $("#page-title").textContent = PAGES[view][0]; $("#page-sub").textContent = PAGES[view][1]();
    window.scrollTo(0, 0);
    if (view === "overview") { renderOverview(); globeResume(); } else globePause();
    if (view === "consignments") renderBoard();
    if (view === "actions") renderActions();
    if (view === "workflow") renderWorkflowPage();
  }
  window.addEventListener("hashchange", () => show(location.hash.slice(1) || "overview"));
  const currentView = () => (PAGES[location.hash.slice(1)] ? location.hash.slice(1) : "overview");

  // ---------- data ----------
  async function loadAll() {
    const [meta, overview] = await Promise.all([api("/api/meta"), api("/api/overview")]);
    state.meta = meta; state.overview = overview; state.rows = overview.consignments;
    const c = meta.company;
    $("#company").innerHTML = `<span class="company-mark">${esc(c.short)}</span><div><div class="company-name">${esc(c.name)}</div><div class="company-team">${esc(c.team)}</div></div>`;
    $("#model-pill").innerHTML = `<span class="dot"></span><span>Risk engine live</span>`;
    $("#sidebar-meta").innerHTML = `${meta.sources.length} Kaggle datasets · as of ${esc(fmtDateY(meta.as_of))}<br>Model AUC ${meta.model.auc_roc.toFixed(2)} on ${meta.model.n_test.toLocaleString()} test shipments`;
    updateCounts();
  }
  function updateCounts() { $("#nav-count").textContent = state.rows.length; $("#nav-actions").textContent = state.overview.top_actions.length; $("#nav-workflow").textContent = state.overview.workflows_done || ""; }
  async function refresh() {
    state.overview = await api("/api/overview"); state.rows = state.overview.consignments; updateCounts();
    const v = currentView();
    if (v === "overview") renderOverview(); else state.globeDirty = true;
    if (v === "consignments") renderBoard();
    if (v === "actions") renderActions();
    if (v === "workflow") renderWorkflowPage({ keep: true });
    $("#page-sub").textContent = PAGES[v][1]();
  }

  // ---------- overview ----------
  function countUp(el, finalText) {
    const m = finalText.match(/^([^0-9]*)([0-9]+(?:\.[0-9]+)?)(.*)$/);
    if (!m || matchMedia("(prefers-reduced-motion: reduce)").matches) { el.textContent = finalText; return; }
    const [, pre, num, post] = m, target = parseFloat(num), dec = (num.split(".")[1] || "").length, t0 = performance.now(), dur = 900;
    const step = (t) => { const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3); el.textContent = pre + (target * e).toFixed(dec) + post; if (k < 1) requestAnimationFrame(step); else el.textContent = finalText; };
    requestAnimationFrame(step);
  }
  function renderOverview() {
    const o = state.overview, s = o.summary;
    const kpis = [
      ["Active consignments", `${s.n}`, `${fmtUSD(s.total_value_usd)} cargo value · ${s.in_transit} in transit · ${s.departing_7d} departing in 7 days`, ""],
      ["Consignments at risk", `${s.n_at_risk} of ${s.n}`, `${fmtUSD(s.value_at_risk_usd)} (${s.pct_value_at_risk}%) of cargo value is High or Elevated · ${s.bands.high} High`, s.bands.high ? "high" : s.n_at_risk ? "elevated" : "low"],
      ["Expected disruption loss", fmtUSD(s.expected_loss_usd), "Probability of disruption × estimated cost of the delay", ""],
      ["Savings from alternatives", fmtUSD(s.alternative_savings_usd), `${s.alternatives_available} consignment${s.alternatives_available === 1 ? " has" : "s have"} a better route, carrier or timing`, s.alternative_savings_usd > 0 ? "low" : ""],
    ];
    $("#kpi-grid").innerHTML = kpis.map(([l, v, sub, c]) => `<div class="kpi"><div class="kpi-label">${l}</div><div class="kpi-value ${c}" data-final="${esc(v)}">${esc(v)}</div><div class="kpi-sub">${sub}</div></div>`).join("");
    $$("#kpi-grid .kpi-value").forEach((el) => countUp(el, el.dataset.final));
    $("#catch-rate").textContent = o.catch_rate == null ? "" : `Real disrupted shipments from the dataset on the same lanes as your book. Across all ${o.catch_n.toLocaleString()} disrupted shipments from ${fmtDateY(o.catch_window[0])}, which the model never trained on, RiskLens rated ${o.catch_rate}% Elevated or High.`;
    $("#recent-disruptions").innerHTML = `<table class="table"><thead><tr><th>Date</th><th>Lane</th><th>Main signals</th><th class="num">Model score</th><th class="num">Est. cost</th><th>Warned</th></tr></thead><tbody>${o.recent_disruptions.map((d) => `<tr><td class="mono">${fmtDate(d.date)}</td><td>${esc(d.lane)}<div class="sub mono">${esc(d.shipment_id)} · ${esc(d.mode)}</div></td><td>${esc(d.disruption_reason)}</td><td class="num">${d.risk_score.toFixed(0)}</td><td class="num">${fmtUSD(d.recovery_cost_usd)}</td><td>${d.flagged_in_advance ? '<span class="chip low">yes</span>' : '<span class="chip high">missed</span>'}</td></tr>`).join("")}</tbody></table>`;
    renderSources(o);
    renderGlobe();
  }
  function renderSources(o) {
    const m = state.meta.model, g = o.gpr_global;
    const per = (p) => (!p ? "" : `${fmtDateY(p[0])} – ${fmtDateY(p[1])}`);
    $("#data-sources").innerHTML = `<div class="ds-grid">${o.sources.map((x) => `<div class="ds">
        <div class="ds-n">${esc(x.name)}</div>
        <div class="ds-m">${x.rows ? `<b>${x.rows.toLocaleString()}</b> rows` : "<b>Monthly</b> readings"}${x.period ? ` · ${esc(per(x.period))}` : ""}</div>
        <div class="ds-u">${esc(x.used_for)}</div>
        <a class="ds-k mono" href="https://www.kaggle.com/datasets/${esc(x.kaggle)}" target="_blank" rel="noopener">kaggle.com/datasets/${esc(x.kaggle)}</a></div>`).join("")}</div>
      <div class="ds-foot"><span><b>Model</b> XGBoost trained on ${m.n_train.toLocaleString()} shipments, tested on ${m.n_test.toLocaleString()} later ones (${esc(per(m.test_window))}): AUC ${m.auc_roc.toFixed(2)}, ${Math.round(m.recall * 100)}% of disruptions caught.</span>
      ${g ? `<span><b>World GPR</b> 7-day average ${g.ma7.toFixed(0)} on ${esc(fmtDateY(g.day))} against a 1-year average of ${g.year_average.toFixed(0)}${g.events.length ? ` · latest flagged event: ${esc(g.events[g.events.length - 1].event)}` : ""}</span>` : ""}</div>`;
  }

  // ---------- actions page ----------
  function ring(pct, color, size = 58) {
    const r = size / 2 - 5, c = 2 * Math.PI * r;
    return `<svg class="ring" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" aria-hidden="true"><circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="#EEF0F3" stroke-width="6"/><circle class="ring-v" cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${color}" stroke-width="6" stroke-linecap="round" stroke-dasharray="${c}" style="--c:${c};--off:${c * (1 - pct)}" transform="rotate(-90 ${size / 2} ${size / 2})"/></svg>`;
  }
  const actKey = (a) => `${a.consignment_id}|${a.id}`;
  const openImpact = new Set();
  const fmtWhen = (iso) => new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const names = (list) => (list.length <= 2 ? list.join(" and ") : `${list.slice(0, -1).join(", ")} and ${list[list.length - 1]}`);
  function impactHTML(a) {
    const m = a.impact, s = state.overview.summary, maxL = Math.max(1, m.loss_before);
    const bookAfter = s.expected_loss_usd - m.loss_avoided;
    return `<div class="impact">
      <div class="im-head"><span class="im-kicker">If this is fixed</span><span class="tag">expected effect on ${esc(a.consignment_id)}</span></div>
      <div class="im-grid">
        <div class="im-block">
          <span class="im-l">Disruption risk</span>
          <div class="im-flow"><span class="im-score" style="--c:${BAND_COLOR[m.band_before]}">${m.risk_before.toFixed(0)}<small>${m.band_before}</small></span>
            <span class="im-arrow"><i></i></span>
            <span class="im-score after" style="--c:${BAND_COLOR[m.band_after]}">${m.risk_after.toFixed(0)}<small>${m.band_after}</small></span></div>
          <span class="im-note">${(a.risk_reduction * 100).toFixed(0)}% lower chance of disruption${m.band_before !== m.band_after ? ` · moves from ${m.band_before} to ${m.band_after}` : ""}</span>
        </div>
        <div class="im-block">
          <span class="im-l">Expected loss</span>
          <div class="im-bars"><div><span>Now</span><i><em class="bad" style="--w:100%"></em></i><b>${fmtUSD(m.loss_before)}</b></div>
            <div><span>After</span><i><em class="good" style="--w:${(m.loss_after / maxL) * 100}%"></em></i><b>${fmtUSD(m.loss_after)}</b></div></div>
          <span class="im-note"><b class="good">${fmtUSD(m.loss_avoided)}</b> avoided · book total ${fmtUSD(s.expected_loss_usd)} → ${fmtUSD(bookAfter)}</span>
        </div>
      </div>
      <div class="im-sub">What gets better</div>
      <ul class="im-effects">${m.effects.map((e, i) => `<li style="animation-delay:${0.05 + i * 0.07}s"><span class="ck">✓</span>${esc(e)}</li>`).join("")}</ul>
      <div class="im-who"><span>Warehouses involved</span>${a.affected.map((w) => `<span class="wh-chip"><em>${esc(w.role)}</em>${esc(w.name)}</span>`).join("")}</div>
    </div>`;
  }
  function renderActions() {
    const o = state.overview;
    const done = (a) => !!(a.deployed || a.executed);
    const ordered = [...o.top_actions].sort((x, y) => done(x) - done(y));
    $("#top-actions").innerHTML = ordered.length ? ordered.map((a) => {
      const k = actKey(a), n = a.notified, open = openImpact.has(k), dep = a.deployed;
      if (done(a)) return `<div class="act-item deployed" data-key="${esc(k)}">
      <div class="action"><div><div class="a-title">${esc(a.action)}</div><div class="a-sub"><a href="#" data-open="${esc(a.consignment_id)}">${esc(a.consignment_id)}</a> · ${esc(a.lane)} · ${chip(a.risk_band)}</div></div><div class="a-meta"><span class="dep-stamp">Deployed</span>${dep ? esc(fmtWhen(dep.deployed_at)) : "by workflow"}</div></div>
      <div class="act-extra"><span class="sent-badge"><span class="sb-ic">✓</span>${dep ? esc(dep.result.summary) : "Executed through the intelligent workflow."}</span>${dep ? `<span class="ae-btns"><a class="btn btn-sm btn-ghost" href="#workflow" data-workflow-open="${esc(dep.id)}">View the run →</a></span>` : ""}</div></div>`;
      return `<div class="act-item ${n ? "sent" : ""}" data-key="${esc(k)}">
      <div class="action"><div><div class="a-title">${esc(a.action)}</div><div class="a-sub"><a href="#" data-open="${esc(a.consignment_id)}">${esc(a.consignment_id)}</a> · ${esc(a.lane)} · ${chip(a.risk_band)}</div><div class="a-sub">${esc(a.trigger)}</div></div><div class="a-meta">Net benefit<b class="${a.net_benefit_usd >= 0 ? "good" : "bad"}">${fmtUSD(a.net_benefit_usd)}</b>${esc(a.timeline)}</div></div>
      <div class="act-extra">
        ${n ? `<span class="sent-badge"><span class="sb-ic">✓</span>Notification sent to ${esc(names(n.recipients.map((r) => r.name)))} · ${esc(fmtWhen(n.sent_at))}</span>` : `<span class="muted small">Affects ${esc(names(a.affected.map((w) => w.name)))}</span>`}
        <span class="ae-btns"><button class="btn btn-sm btn-ghost ${open ? "on" : ""}" data-impact="${esc(k)}" aria-expanded="${open}">Impact if fixed <span class="chev">▾</span></button>
        <button class="btn btn-sm ${n ? "btn-secondary" : "btn-primary"}" data-notify="${esc(k)}">${n ? "Notify again" : "Notify warehouses"}</button>${n ? `<button class="btn btn-sm btn-primary wf-go" data-workflow="${esc(k)}">Run intelligent workflow →</button>` : ""}</span>
      </div>
      ${open ? impactHTML(a) : ""}
    </div>`;
    }).join("") : `<div class="empty">No actions needed. Every consignment is within tolerance.</div>`;
    renderNotifLog(); renderDeployedLog();
  }
  async function renderDeployedLog() {
    const card = $("#deployed-card"); let runs = [];
    try { runs = (await api("/api/workflows")).filter((w) => w.status === "done"); } catch (e) { runs = []; }
    card.hidden = !runs.length; if (!runs.length) return;
    $("#deployed-log").innerHTML = `<div class="dep-list">${runs.map((w) => { const d = w.steps.deploy; return `<div class="dep-item">
      <div class="im-flow dep-flow"><span class="im-score" style="--c:${BAND_COLOR[d.band_before]}">${d.risk_before.toFixed(0)}<small>${d.band_before}</small></span><span class="im-arrow"><i></i></span><span class="im-score after" style="--c:${BAND_COLOR[d.band_after]}">${d.risk_after.toFixed(0)}<small>${d.band_after}</small></span></div>
      <div class="dep-main"><div class="a-title">${esc(w.action)}</div><div class="a-sub"><a href="#" data-open="${esc(w.consignment_id)}">${esc(w.consignment_id)}</a> · ${esc(w.lane)} · ${d.kind === "alternative" ? "applied “" + esc(d.title) + "” and re-scored by the model" : "recorded as executed"}${d.eta_after !== d.eta_before ? ` · ETA ${esc(fmtDate(d.eta_before))} → ${esc(fmtDate(d.eta_after))}` : ""}</div>
        <div class="a-sub">Signed off by ${esc(w.stakeholder.name)}, ${esc(w.stakeholder.org)} · ${esc(fmtWhen(w.deployed_at))}</div></div>
      <div class="dep-side"><span class="dep-stamp">Deployed</span><a class="btn btn-sm btn-ghost" href="#workflow" data-workflow-open="${esc(w.id)}">View the run →</a></div></div>`; }).join("")}</div>`;
  }
  async function renderNotifLog() {
    const el = $("#notif-log"); if (!el) return;
    let log = [];
    try { log = await api("/api/notifications"); } catch (e) { el.innerHTML = `<div class="alert error">${esc(e.message)}</div>`; return; }
    el.innerHTML = log.length ? `<ol class="nlog">${log.map((n) => `<li><span class="nl-dot"></span><div class="nl-main"><div class="nl-top"><b>${esc(n.action)}</b><span class="nl-when">${esc(fmtWhen(n.sent_at))}</span></div>
        <div class="nl-sub"><span class="mono">${esc(n.consignment_id)}</span> · ${esc(n.lane)} · to ${esc(names(n.recipients.map((r) => r.name)))}</div>
        <details><summary>View message</summary><div class="nl-msg"><b>${esc(n.subject)}</b><pre>${esc(n.body)}</pre><div class="nl-to">${n.recipients.map((r) => `<span>${esc(r.name)} &lt;${esc(r.email)}&gt;</span>`).join("")}</div></div></details></div>
        <span class="nl-st">✓ Sent</span></li>`).join("")}</ol>` : `<div class="empty small">No notifications sent yet. Use “Notify warehouses” on an action above.</div>`;
  }
  $("#top-actions").addEventListener("click", (e) => {
    const ib = e.target.closest("[data-impact]"); if (ib) { const k = ib.dataset.impact; openImpact.has(k) ? openImpact.delete(k) : openImpact.add(k); renderActions(); return; }
    const nb = e.target.closest("[data-notify]"); if (nb) openNotify(nb.dataset.notify);
  });
  document.addEventListener("click", (e) => {
    const wb = e.target.closest("[data-workflow]"); if (wb) { WF.pending = wb.dataset.workflow; location.hash = "workflow"; }
    const wo = e.target.closest("[data-workflow-open]"); if (wo) { WF.open = wo.dataset.workflowOpen; }
  });

  // ---------- notify modal ----------
  async function openNotify(k) {
    const [cid, aid] = k.split("|"), m = $("#notify-modal");
    m.classList.add("open"); m.setAttribute("aria-hidden", "false"); $("#modal-backdrop").classList.add("open");
    $("#notify-body").innerHTML = `<div class="empty">Preparing message…</div>`;
    let d; try { d = await api(`/api/actions/${encodeURIComponent(cid)}/${encodeURIComponent(aid)}/draft`); } catch (e) { $("#notify-body").innerHTML = `<div class="alert error">${esc(e.message)}</div>`; return; }
    const imp = d.impact;
    $("#notify-body").innerHTML = `
      <div class="nm-head"><div><div class="eyebrow">Notify affected warehouses</div><h2 id="nm-title">${esc(d.action)}</h2><div class="muted">${esc(cid)} · risk ${imp.risk_before.toFixed(0)} → ${imp.risk_after.toFixed(0)} once done</div></div><button class="icon-btn" data-close aria-label="Close">✕</button></div>
      <div class="nm-demo">Demo mode: the message is recorded in RiskLens and shown in the log. It is not emailed or texted to anyone.</div>
      <div class="nm-sec">Recipients</div>
      <div class="nm-recip">${d.recipients.map((r) => `<label class="rc"><input type="checkbox" value="${esc(r.key)}" checked><span class="rc-box">
        <span class="rc-top"><b>${esc(r.name)}</b><em>${esc(r.role)}</em></span><span class="rc-sub">${esc(r.location)} · ${esc(r.contact)} · <span class="mono">${esc(r.email)}</span></span>
        <span class="rc-task">${esc(r.task)}</span></span></label>`).join("")}</div>
      <div class="nm-sec">Message</div>
      <label class="nm-field">Subject<input class="input" id="nm-subject" value="${esc(d.subject)}"></label>
      <label class="nm-field">Body<textarea class="input" id="nm-text" rows="9">${esc(d.body)}</textarea></label>
      <div class="nm-foot"><span class="muted small" id="nm-count"></span><button class="btn btn-secondary" data-close>Cancel</button><button class="btn btn-primary" id="nm-send">Send notification</button></div>`;
    const count = () => { const n = $$("#notify-body .rc input:checked").length; $("#nm-count").textContent = `${n} of ${d.recipients.length} warehouse${d.recipients.length === 1 ? "" : "s"} selected`; $("#nm-send").disabled = !n; $("#nm-send").textContent = n > 1 ? `Send to ${n} warehouses` : "Send notification"; };
    $$("#notify-body .rc input").forEach((i) => i.addEventListener("change", count)); count();
    $("#nm-send").addEventListener("click", async () => {
      const btn = $("#nm-send"); btn.disabled = true; btn.textContent = "Sending…";
      try {
        const res = await api("/api/notifications", { body: { consignment_id: cid, action_id: aid, recipients: $$("#notify-body .rc input:checked").map((i) => i.value), subject: $("#nm-subject").value, body: $("#nm-text").value } });
        closeNotify(); await refresh();
        toast(`Notification sent to ${res.recipients.length} warehouse${res.recipients.length === 1 ? "" : "s"}`);
        const item = document.querySelector(`.act-item[data-key="${CSS.escape(k)}"]`); if (item) { item.classList.add("just-sent"); item.scrollIntoView({ behavior: "smooth", block: "center" }); }
      } catch (e) { btn.disabled = false; btn.textContent = "Send notification"; toast(e.message); }
    });
    setTimeout(() => $("#nm-send")?.focus(), 50);
  }
  function closeNotify() { const m = $("#notify-modal"); m.classList.remove("open"); m.setAttribute("aria-hidden", "true"); $("#modal-backdrop").classList.remove("open"); }
  $("#notify-modal").addEventListener("click", (e) => { if (e.target.closest("[data-close]") || e.target === $("#notify-modal")) closeNotify(); });
  $("#modal-backdrop").addEventListener("click", closeNotify);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeNotify(); });

  // ---------- globe ----------
  const SVG = (d) => `<svg viewBox="0 0 24 24" aria-hidden="true">${d}</svg>`;
  const ICONS = {
    sea: SVG('<path d="M2 20c2 1 4 1 6 0s4-1 6 0 4 1 6 0"/><path d="M4 17.5 3 13h18l-2 4.5"/><path d="M6 13V8h12v5"/><path d="M12 8V4"/>'),
    air: SVG('<path d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z"/>'),
    road: SVG('<path d="M1 4h14v12H1z"/><path d="M15 8h4l4 4v4h-8z"/><circle cx="5.5" cy="18" r="2"/><circle cx="18.5" cy="18" r="2"/>'),
    rail: SVG('<path d="M12 2c-4 0-8 .5-8 4v9.5A3.5 3.5 0 0 0 7.5 19L6 20.5V21h12v-.5L16.5 19a3.5 3.5 0 0 0 3.5-3.5V6c0-3.5-4-4-8-4z"/><path d="M4 11h16"/><path d="M12 3v8"/>'),
    flag: SVG('<path d="M4 22V4"/><path d="M4 4h13l-2 4 2 4H4"/>'),
    anchor: SVG('<circle cx="12" cy="5" r="3"/><path d="M12 22V8"/><path d="M5 12H2a10 10 0 0 0 20 0h-3"/>'),
    alert: SVG('<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>'),
  };
  const modeKey = (m) => ({ sea: "sea", air: "air", road: "road", rail: "rail" }[String(m || "").toLowerCase()] || "sea");
  const RGB = { low: "34,197,94", elevated: "251,146,60", high: "248,64,64" };  // bright enough to read on the #235696 ocean
  const FACTOR_NAME = { weather_risk_index: "Weather severity", geopolitical_risk_index: "Geopolitical risk" };
  const SITUATION = {
    weather_risk: "Severe weather on the route", geopolitical_risk: "High geopolitical risk on the corridor",
    reliability_risk: "Carrier reliability is weak", fuel_price_risk: "Fuel prices are near the top of the range",
    distance_risk: "Long route with more time exposed",
  };
  const levelBand = (v) => (v >= 60 ? "high" : v >= 40 ? "elevated" : "low");
  // spherical helpers
  const rad = (d) => (d * Math.PI) / 180, deg = (r) => (r * 180) / Math.PI;
  const vec = ([la, lo]) => [Math.cos(rad(la)) * Math.cos(rad(lo)), Math.cos(rad(la)) * Math.sin(rad(lo)), Math.sin(rad(la))];
  const ll = ([x, y, z]) => [deg(Math.atan2(z, Math.hypot(x, y))), deg(Math.atan2(y, x))];
  const ang = (p, q) => { const a = vec(p), b = vec(q); return Math.acos(Math.max(-1, Math.min(1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]))); };
  function slerp(p, q, t) { const w = ang(p, q); if (w < 1e-9) return p; const a = vec(p), b = vec(q), s1 = Math.sin((1 - t) * w) / Math.sin(w), s2 = Math.sin(t * w) / Math.sin(w); return ll([0, 1, 2].map((i) => a[i] * s1 + b[i] * s2)); }
  function along(pts, t) {
    const seg = []; let tot = 0; for (let i = 0; i < pts.length - 1; i++) { const d = ang(pts[i], pts[i + 1]); seg.push(d); tot += d; }
    let rem = t * tot; for (let i = 0; i < seg.length; i++) { if (rem <= seg[i]) return slerp(pts[i], pts[i + 1], seg[i] ? rem / seg[i] : 0); rem -= seg[i]; }
    return pts[pts.length - 1];
  }
  const G = { g: null, band: "all", focus: null, mouse: [0, 0], ready: false, loading: null, near: false, rotateWanted: true, idle: null };

  function signalBars(i) {
    const rows = [[i.weather_condition || "Weather", i.weather_risk_index], ["Geopolitical", i.geopolitical_risk_index],
      ["Carrier risk", i.reliability_score != null ? (1 - i.reliability_score) * 100 : null], ["Fuel price", i.fuel_price_index != null ? ((i.fuel_price_index - 1.2) / 3.3) * 100 : null]].filter(([, v]) => v != null);
    return `<div class="gt-bars">${rows.map(([k, v]) => `<span>${k}</span><span class="tr"><span style="width:${Math.min(100, v)}%;background:${BAND_COLOR[levelBand(v)]}"></span></span><span class="n">${(+v).toFixed(0)}</span>`).join("")}</div>`;
  }
  function lastDisruption(r) {
    const l = r.context?.lane;
    if (!l) return "No shipments on this lane in the dataset.";
    const last = l.last_disruption;
    return `Lane history: ${l.disrupted} of ${l.shipments} dataset shipments disrupted (${Math.round(l.disrupted_share * 100)}%)${last ? ` · last on ${esc(fmtDate(last.date))}, ${esc(last.weather.toLowerCase())}` : ""}.`;
  }
  function gprLine(g, label) {
    if (!g) return "";
    const hot = g.ratio >= 1.25, c = hot ? BAND_COLOR.high : g.ratio >= 1 ? BAND_COLOR.elevated : BAND_COLOR.low;
    return `<div class="gt-gpr"><span>${label || "GPR index"} · ${esc(g.country)}${g.proxy ? " (nearest covered)" : ""}</span><b style="color:${c}">${g.value.toFixed(2)}</b><em>${g.ratio.toFixed(1)}× its 2019–24 average · ${esc(fmtDateY(g.month))}</em></div>`;
  }
  const relText = (r) => (r.inputs?.reliability_score != null ? `carrier reliability ${(+r.inputs.reliability_score).toFixed(2)}` : "");
  function headline(r) { return r.risk_band === "low" ? "Operating normally" : SITUATION[r.top_driver?.key] || "Risk signals elevated"; }
  function statusLine(r) { const j = r.journey; if (!j) return ""; return j.status === "In transit" ? `In transit · day ${j.elapsed_days} of ${j.total_days} · ETA ${fmtDate(j.eta_date)}` : j.status === "Scheduled" ? `Departs ${fmtDate(j.dispatch_date)} · ETA ${fmtDate(j.eta_date)}` : "Arrived"; }

  function tipConsignment(r, kind) {
    return `<div class="gt-top"><span class="gt-kind">${ICONS[modeKey(r.mode)]}${kind}</span>${chip(r.risk_band)}</div>
      <div class="gt-title">${esc(routeText(r))}</div><div class="gt-sub"><span class="mono">${esc(r.consignment_id)}</span> · ${esc(r.cargo || "")} · ${fmtUSD(r.cargo_value_usd)}</div>
      <div class="gt-sec"><div class="gt-headline" style="--c:${BAND_COLOR[r.risk_band]}">${esc(headline(r))}</div><div class="gt-sub">${esc(statusLine(r))} · ${esc(r.mode || "")} · ${esc(relText(r))}</div></div>
      <div class="gt-sec"><div class="gt-sec-h">Signals on this lane</div>${signalBars(r.inputs)}<div class="gt-sub" style="margin-top:6px">${lastDisruption(r)}</div></div>
      <div class="gt-row" style="margin-top:6px"><span>Disruption risk <b style="color:${BAND_COLOR[r.risk_band]}">${r.risk_score.toFixed(1)}</b></span><span>${r.best_alternative ? "Best option: " + esc(r.best_alternative.title) : "Stay on current plan"}</span></div>
      <div class="gt-foot">Click to open the consignment →</div>`;
  }
  function tipPlace(p) {
    const worst = p.items.reduce((a, b) => (b.r.risk_score > a.r.risk_score ? b : a));
    return `<div class="gt-top"><span class="gt-kind">${p.dest ? ICONS.flag + "Destination" : ICONS.anchor + "Origin"}${p.dest && p.origin ? " & origin" : ""}</span>${chip(worst.r.risk_band)}</div>
      <div class="gt-title">${esc(p.name)}</div><div class="gt-sub">${esc(p.country)}</div>
      <div class="gt-about">${esc(p.about)}</div>
      ${p.gpr ? `<div class="gt-sec"><div class="gt-sec-h">Real-world geopolitical index</div>${gprLine(p.gpr, "GPR")}</div>` : ""}
      <div class="gt-sec"><div class="gt-sec-h">Situation</div><div class="gt-headline" style="--c:${BAND_COLOR[worst.r.risk_band]}">${esc(headline(worst.r))}</div>${signalBars(worst.r.inputs)}<div class="gt-sub" style="margin-top:6px">${lastDisruption(worst.r)}</div></div>
      <div class="gt-sec"><div class="gt-sec-h">Consignments here</div>${p.items.map(({ r, role }) => `<div class="gt-row"><span><b>${esc(r.consignment_id)}</b> ${role === "dest" ? "arriving" : "departing"} · ${role === "dest" ? "ETA " + fmtDate(r.journey?.eta_date) : fmtDate(r.journey?.dispatch_date)}</span><span style="color:${BAND_COLOR[r.risk_band]};font-weight:700">${r.risk_score.toFixed(0)}</span></div>`).join("")}</div>`;
  }
  function tipHotspot(h) {
    return `<div class="gt-top"><span class="gt-kind">${ICONS.alert}Risk hotspot</span>${chip(h.band)}</div>
      <div class="gt-title">${esc(h.name)}</div><div class="gt-about">${esc(h.about)}</div>
      <div class="gt-sec"><div class="gt-sec-h">Current signal</div><div class="gt-bars"><span>${FACTOR_NAME[h.factor]}</span><span class="tr"><span style="width:${Math.min(100, h.level)}%;background:${BAND_COLOR[h.band]}"></span></span><span class="n">${h.level.toFixed(0)}</span></div>${h.gpr ? gprLine(h.gpr, "GPR") : ""}</div>
      <div class="gt-sec"><div class="gt-sec-h">Consignments passing</div>${h.items.map((r) => `<div class="gt-row"><span><b>${esc(r.consignment_id)}</b> ${esc(routeText(r))}</span><span style="color:${BAND_COLOR[r.risk_band]};font-weight:700">${r.risk_score.toFixed(0)}</span></div>`).join("")}</div>`;
  }
  function showTip(html) { const t = $("#globe-tip"); t.innerHTML = html; t.classList.add("show"); placeTip(); }
  function hideTip() { $("#globe-tip").classList.remove("show"); }
  function placeTip() {
    const t = $("#globe-tip"), st = $("#globe-stage"); if (!t.classList.contains("show")) return;
    const [x, y] = G.mouse, w = t.offsetWidth, h = t.offsetHeight, W = st.clientWidth, H = st.clientHeight;
    t.style.left = Math.max(10, Math.min(W - w - 10, x + 16 > W - w - 290 ? x - w - 16 : x + 16)) + "px";
    t.style.top = Math.max(10, Math.min(H - h - 10, y - 20)) + "px";
  }

  function buildGlobeData() {
    const geo = state.overview.geo, rows = state.rows.filter((r) => geo.routes[r.consignment_id]);
    const vis = (r) => G.band === "all" || r.risk_band === G.band;
    const paths = [], arcs = [], markers = [], rings = [];
    const places = {};
    for (const r of rows) {
      const g = geo.routes[r.consignment_id], on = vis(r), col = RGB[r.risk_band];
      if (g.air) {
        arcs.push({ r, kind: "base", on, sLat: g.origin.lat, sLng: g.origin.lng, eLat: g.destination.lat, eLng: g.destination.lng });
        arcs.push({ r, kind: "flow", on, sLat: g.origin.lat, sLng: g.origin.lng, eLat: g.destination.lat, eLng: g.destination.lng });
      } else {
        paths.push({ r, kind: "base", on, points: g.points }); paths.push({ r, kind: "flow", on, points: g.points });
      }
      for (const [role, pl] of [["origin", g.origin], ["dest", g.destination]]) {
        const p = (places[pl.name] ||= { ...pl, items: [], origin: false, dest: false });
        p.items.push({ r, role }); p[role] = true;
      }
      const j = r.journey, moving = j && j.status === "In transit";
      const pos = moving ? along(g.points, j.progress) : j && j.status === "Arrived" ? [g.destination.lat, g.destination.lng] : [g.origin.lat, g.origin.lng];
      markers.push({ type: "vehicle", r, on, lat: pos[0], lng: pos[1], alt: g.air && moving ? 0.12 : 0.012 });
      if (r.risk_band === "high") rings.push({ lat: pos[0], lng: pos[1], band: "high", max: 4.5, on });
    }
    for (const p of Object.values(places)) {
      const on = p.items.some(({ r }) => vis(r));
      markers.push({ type: "place", p, on, lat: p.lat, lng: p.lng, alt: 0.006 });
    }
    const byId = Object.fromEntries(rows.map((r) => [r.consignment_id, r]));
    const hot = geo.hotspots.map((h) => {
      const items = h.lanes.map((c) => byId[c]).filter(Boolean);
      const level = Math.max(...items.map((r) => +r.inputs[h.factor] || 0));
      return { ...h, items, level, band: levelBand(level) };
    }).filter((h) => h.items.length);
    for (const h of hot) {
      const on = h.items.some(vis);
      markers.push({ type: "hot", h, on, lat: h.lat, lng: h.lng, alt: 0.008 });
      if (h.band !== "low") rings.push({ lat: h.lat, lng: h.lng, band: h.band, max: h.band === "high" ? 6 : 4, on });
    }
    return { paths, arcs, markers, rings, hot, rows };
  }

  function markerEl(d) {
    const el = document.createElement("div");
    el.className = "gm " + (d.type === "vehicle" ? "vehicle" : d.type === "hot" ? "hot" : d.p.dest ? "dest" : "origin") + (d.on ? "" : " dim");
    if (d.type === "vehicle") {
      const r = d.r, c = BAND_COLOR[r.risk_band];
      el.style.setProperty("--c", c); el.style.setProperty("--cp", `rgba(${RGB[r.risk_band]},.45)`);
      el.innerHTML = `<div class="in"><span class="dot"></span><span class="badge">${ICONS[modeKey(r.mode)]}</span><span class="lbl">${esc(r.consignment_id)}<small>${r.risk_score.toFixed(0)}</small></span></div>`;
      el.onmouseenter = () => showTip(tipConsignment(r, r.journey?.status === "In transit" ? `${r.mode} · en route` : `${r.mode} · at origin`));
      el.onclick = () => openDrawer(r.consignment_id);
    } else if (d.type === "place") {
      const worst = d.p.items.reduce((a, b) => (b.r.risk_score > a.r.risk_score ? b : a)).r;
      el.style.setProperty("--c", d.p.dest ? BAND_COLOR[worst.risk_band] : "#667085");
      el.innerHTML = `<div class="in"><span class="dot"></span><span class="badge">${d.p.dest ? ICONS.flag : ICONS.anchor}</span><span class="lbl">${esc(d.p.name)}<small>${esc(d.p.country)}</small></span></div>`;
      el.onmouseenter = () => showTip(tipPlace(d.p));
      el.onclick = () => flyTo(d.lat, d.lng, 0.9);
    } else {
      el.style.setProperty("--c", BAND_COLOR[d.h.band]);
      el.innerHTML = `<div class="in"><span class="dot"></span><span class="badge">${ICONS.alert}</span><span class="lbl">${esc(d.h.name)}</span></div>`;
      el.onmouseenter = () => showTip(tipHotspot(d.h));
      el.onclick = () => flyTo(d.lat, d.lng, 0.9);
    }
    el.onmouseleave = hideTip;
    el.style.pointerEvents = "auto";
    return el;
  }

  function onZoom({ altitude }) {
    const near = altitude < 1.45, ctr = G.g.controls();
    // Slower, finer control up close; faster when viewing the whole planet.
    ctr.rotateSpeed = Math.max(0.12, Math.min(1.1, altitude * 0.42));
    ctr.zoomSpeed = Math.max(0.5, Math.min(1.4, altitude * 0.55));
    if (near !== G.near) { G.near = near; $("#globe-stage").classList.toggle("near", near); G.g.polygonStrokeColor(G.g.polygonStrokeColor()); if (near) ctr.autoRotate = false; }
    declutter();
  }
  // Hide map labels that would collide with a higher-priority label (vehicle > destination > origin > hotspot).
  const LABEL_RANK = { vehicle: 0, dest: 1, origin: 2, hot: 3 };
  let declutterQueued = false;
  function declutter() {
    if (declutterQueued) return; declutterQueued = true;
    requestAnimationFrame(() => {
      declutterQueued = false;
      const stage = $("#globe-stage"); if (!stage.classList.contains("near")) return;
      const marks = [...stage.querySelectorAll(".gm")].filter((m) => !m.classList.contains("hidden-behind") && m.style.display !== "none");
      const rank = (m) => LABEL_RANK[["vehicle", "dest", "origin", "hot"].find((c) => m.classList.contains(c))] ?? 9;
      marks.sort((a, b) => rank(a) - rank(b));
      const kept = marks.map((m) => m.querySelector(".badge")?.getBoundingClientRect()).filter((r) => r && r.width);
      const hit = (a, b) => !(a.right + 4 <= b.left || b.right + 4 <= a.left || a.bottom + 2 <= b.top || b.bottom + 2 <= a.top);
      for (const m of marks) {
        const l = m.querySelector(".lbl"); if (!l) continue;
        l.classList.remove("lbl-hide");
        const r = l.getBoundingClientRect();
        if (kept.some((k) => hit(r, k))) l.classList.add("lbl-hide"); else kept.push(r);
      }
    });
  }
  function scheduleResume() { clearTimeout(G.idle); if (!G.rotateWanted) return; G.idle = setTimeout(() => { if (G.rotateWanted && !G.near && G.g) G.g.controls().autoRotate = true; }, 6000); }
  function flyTo(lat, lng, altitude = 1.1) { if (!G.g) return; clearTimeout(G.idle); G.g.controls().autoRotate = false; hideTip(); G.g.pointOfView({ lat, lng, altitude }, 1400); setTimeout(scheduleResume, 1500); }
  function setRotate(on) { if (!G.g) return; G.rotateWanted = on; clearTimeout(G.idle); G.g.controls().autoRotate = on && !G.near; $("#gc-rotate").classList.toggle("active", on); $("#gc-rotate").setAttribute("aria-pressed", on); $("#gc-rotate").title = on ? "Auto-rotate on" : "Auto-rotate off"; }
  function focusConsignment(cid) {
    const r = state.rows.find((x) => x.consignment_id === cid), g = state.overview.geo.routes[cid]; if (!r || !g) return;
    G.focus = G.focus === cid ? null : cid; paintGlobe();
    const j = r.journey, pos = j && j.status === "In transit" ? along(g.points, j.progress) : along(g.points, 0.5);
    flyTo(pos[0], pos[1], G.focus ? 1.25 : 2.35);
  }

  function paintGlobe() {
    const g = G.g; if (!g) return;
    const D = buildGlobeData(); G.data = D;
    const alpha = (d, a) => (d.on && (!G.focus || d.r.consignment_id === G.focus) ? a : a * 0.12);
    g.pathsData(D.paths).arcsData(D.arcs).ringsData(D.rings.filter((x) => x.on)).htmlElementsData(D.markers);
    g.pathColor((d) => (d.kind === "base" ? `rgba(${RGB[d.r.risk_band]},${alpha(d, 0.8)})` : [`rgba(${RGB[d.r.risk_band]},${alpha(d, 0.2)})`, `rgba(${RGB[d.r.risk_band]},${alpha(d, 1)})`]));
    g.arcColor((d) => (d.kind === "base" ? `rgba(${RGB[d.r.risk_band]},${alpha(d, 0.75)})` : [`rgba(${RGB[d.r.risk_band]},${alpha(d, 0.15)})`, `rgba(${RGB[d.r.risk_band]},${alpha(d, 1)})`]));
    // lists
    $("#gp-count").textContent = `${D.rows.filter((r) => G.band === "all" || r.risk_band === G.band).length} of ${D.rows.length}`;
    $("#globe-list").innerHTML = D.rows.map((r) => `<div class="gp-item ${G.focus === r.consignment_id ? "on" : ""} ${G.band !== "all" && r.risk_band !== G.band ? "off" : ""}" data-focus="${esc(r.consignment_id)}" role="button" tabindex="0" title="Fly to ${esc(routeText(r))}">
      <span class="d" style="background:${BAND_COLOR[r.risk_band]}"></span>
      <span class="gp-txt"><span class="t">${esc(routeText(r))}</span><span class="s">${esc(r.consignment_id)} · ${esc(r.mode || "")} · ${esc(r.journey?.status || "")}</span></span>
      <span class="v" style="color:${BAND_COLOR[r.risk_band]}">${r.risk_score.toFixed(0)}</span>
      <button class="gp-open" data-open="${esc(r.consignment_id)}" title="Open ${esc(r.consignment_id)} details" aria-label="Open ${esc(r.consignment_id)} details">→</button></div>`).join("");
    const hs = [...D.hot].sort((a, b) => b.level - a.level);
    $("#hotspot-count").textContent = `${hs.filter((h) => h.band !== "low").length} active`;
    $("#hotspot-list").innerHTML = hs.map((h) => `<div class="gp-item hot" data-hot="${esc(h.id)}" role="button" tabindex="0" title="Fly to ${esc(h.name)}"><span class="d" style="background:${BAND_COLOR[h.band]}"></span><span class="gp-txt"><span class="t">${esc(h.name)}</span><span class="s">${FACTOR_NAME[h.factor]} ${h.level.toFixed(0)}</span></span><span class="v band" style="color:${BAND_COLOR[h.band]}">${h.band}</span></div>`).join("");
    setTimeout(declutter, 60);
    const unm = state.overview.geo.unmapped.length;
    $("#globe-sub").textContent = `${D.rows.length} routes · ${hs.filter((h) => h.band !== "low").length} active risk hotspots${unm ? ` · ${unm} consignment${unm > 1 ? "s" : ""} with ports not on the map` : ""}`;
  }

  async function renderGlobe() {
    if (G.g) { paintGlobe(); return; }
    if (G.loading) return G.loading;
    const fb = $("#globe-fallback");
    if (typeof Globe !== "function" || typeof topojson === "undefined") { fb.hidden = false; fb.textContent = "The 3D map could not load in this browser."; return; }
    G.loading = (async () => {
      const world = await fetch("/static/vendor/countries-110m.json").then((r) => r.json());
      const land = topojson.feature(world, world.objects.countries).features.filter((f) => f.id !== "010");
      const el = $("#globe"), stage = $("#globe-stage");
      let g;
      try { g = new Globe(el, { animateIn: true }); } catch (e) { g = Globe({ animateIn: true })(el); }
      G.g = g;
      g.width(el.clientWidth).height(el.clientHeight).backgroundColor("rgba(0,0,0,0)")
        .globeImageUrl("/static/vendor/earth/earth-light-ocean.jpg").bumpImageUrl("/static/vendor/earth/earth-topology.png")
        .showAtmosphere(true).atmosphereColor("#9CC8F0").atmosphereAltitude(0.16)
        .polygonsData(land).polygonAltitude(0.0012).polygonCapColor(() => "rgba(0,0,0,0)").polygonSideColor(() => "rgba(0,0,0,0)")
        .polygonStrokeColor(() => (G.near ? "rgba(255,255,255,0.55)" : "rgba(255,255,255,0.14)")).polygonsTransitionDuration(0)
        .pathPoints("points").pathPointLat((p) => p[0]).pathPointLng((p) => p[1]).pathPointAlt(0.006).pathResolution(2)
        .pathStroke((d) => (d.kind === "base" ? 1.1 : 2.4)).pathDashLength((d) => (d.kind === "base" ? 1 : 0.06)).pathDashGap((d) => (d.kind === "base" ? 0 : 0.04))
        .pathDashAnimateTime((d) => (d.kind === "base" ? 0 : 14000)).pathTransitionDuration(0)
        .arcStartLat("sLat").arcStartLng("sLng").arcEndLat("eLat").arcEndLng("eLng").arcAltitudeAutoScale(0.4)
        .arcStroke((d) => (d.kind === "base" ? 0.5 : 0.9)).arcDashLength((d) => (d.kind === "base" ? 1 : 0.2)).arcDashGap((d) => (d.kind === "base" ? 0 : 0.15))
        .arcDashAnimateTime((d) => (d.kind === "base" ? 0 : 3000)).arcsTransitionDuration(0)
        .ringColor((d) => (t) => `rgba(${RGB[d.band]},${Math.max(0, 0.75 - t)})`).ringMaxRadius("max").ringPropagationSpeed(2.2).ringRepeatPeriod(1100).ringAltitude(0.005)
        .htmlLat("lat").htmlLng("lng").htmlAltitude("alt").htmlElement(markerEl).htmlTransitionDuration(0)
        .htmlElementVisibilityModifier((elm, visible) => elm.classList.toggle("hidden-behind", !visible))
        .onPathHover((d) => { el.style.cursor = d ? "pointer" : ""; d ? showTip(tipConsignment(d.r, `${d.r.mode} route`)) : hideTip(); })
        .onArcHover((d) => { el.style.cursor = d ? "pointer" : ""; d ? showTip(tipConsignment(d.r, "Air route")) : hideTip(); })
        .onPathClick((d) => openDrawer(d.r.consignment_id)).onArcClick((d) => openDrawer(d.r.consignment_id))
        .onZoom(onZoom)
        .onGlobeReady(() => { const m = g.globeMaterial(); if (m.map) { m.map.anisotropy = g.renderer().capabilities.getMaxAnisotropy(); m.map.needsUpdate = true; } if ("bumpScale" in m) m.bumpScale = 6; if ("shininess" in m) m.shininess = 12; stage.classList.add("ready"); });
      g.renderer().setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
      const ctr = g.controls(); ctr.autoRotate = true; ctr.autoRotateSpeed = 0.3; ctr.minDistance = 108; ctr.maxDistance = 560;
      ctr.enableDamping = true; ctr.dampingFactor = 0.08; ctr.enablePan = false;
      // Pause auto-rotate while the user drags or zooms; resume after a few idle seconds (never when zoomed in).
      ctr.addEventListener("start", () => { clearTimeout(G.idle); ctr.autoRotate = false; hideTip(); });
      ctr.addEventListener("end", scheduleResume);
      ctr.addEventListener("change", declutter);
      // Grab-and-drag (Google Earth style): the point under the cursor stays under the cursor,
      // and the globe coasts briefly on release. OrbitControls keeps zoom and pinch.
      ctr.enableRotate = false;
      const drag = { on: false, x: 0, y: 0, vx: 0, vy: 0, t: 0, raf: 0, pointers: new Set() };
      const degPerPx = () => {
        const cam = g.camera(), R = 100, d = cam.position.length(), half = (cam.fov * Math.PI) / 360;
        const rpx = (R / Math.sqrt(Math.max(1, d * d - R * R))) / Math.tan(half) * (el.clientHeight / 2);
        return (180 / Math.PI) / Math.max(20, rpx);
      };
      const spin = (dx, dy) => {
        const k = degPerPx(), p = g.pointOfView();
        g.pointOfView({ lat: Math.max(-85, Math.min(85, p.lat + dy * k)), lng: p.lng - dx * k, altitude: p.altitude }, 0);
        declutter();
      };
      const onMove = (e) => {
        if (!drag.on || drag.pointers.size > 1) return;
        const dx = e.clientX - drag.x, dy = e.clientY - drag.y, now = performance.now(), dt = Math.max(1, now - drag.t);
        drag.x = e.clientX; drag.y = e.clientY; drag.t = now;
        drag.vx = 0.75 * drag.vx + 0.25 * (dx / dt); drag.vy = 0.75 * drag.vy + 0.25 * (dy / dt);
        if (dx || dy) spin(dx, dy);
      };
      const onUp = (e) => {
        drag.pointers.delete(e.pointerId);
        if (!drag.on || drag.pointers.size) return;
        drag.on = false; el.classList.remove("dragging");
        window.removeEventListener("pointermove", onMove); window.removeEventListener("pointerup", onUp); window.removeEventListener("pointercancel", onUp);
        let vx = drag.vx * 16, vy = drag.vy * 16;
        if (performance.now() - drag.t > 90 || matchMedia("(prefers-reduced-motion: reduce)").matches) vx = vy = 0;
        const coast = () => { if (Math.abs(vx) < 0.05 && Math.abs(vy) < 0.05) { scheduleResume(); return; } spin(vx, vy); vx *= 0.92; vy *= 0.92; drag.raf = requestAnimationFrame(coast); };
        coast();
      };
      el.addEventListener("pointerdown", (e) => {
        if (e.button !== 0 || e.target.closest(".gm")) return;
        drag.pointers.add(e.pointerId);
        if (drag.pointers.size > 1) return; // second finger: let OrbitControls pinch-zoom
        cancelAnimationFrame(drag.raf);
        Object.assign(drag, { on: true, x: e.clientX, y: e.clientY, vx: 0, vy: 0, t: performance.now() });
        clearTimeout(G.idle); ctr.autoRotate = false; hideTip(); el.classList.add("dragging");
        window.addEventListener("pointermove", onMove); window.addEventListener("pointerup", onUp); window.addEventListener("pointercancel", onUp);
      });
      g.pointOfView({ lat: 18, lng: 30, altitude: 2.35 });
      stage.addEventListener("mousemove", (e) => { const b = stage.getBoundingClientRect(); G.mouse = [e.clientX - b.left, e.clientY - b.top]; placeTip(); });
      stage.addEventListener("mouseleave", hideTip);
      new ResizeObserver(() => g.width(el.clientWidth).height(el.clientHeight)).observe(el);
      paintGlobe();
    })();
    return G.loading;
  }
  function globePause() { if (G.g) G.g.pauseAnimation(); hideTip(); }
  function globeResume() { if (G.g) { G.g.resumeAnimation(); if (state.globeDirty) { state.globeDirty = false; paintGlobe(); } } }
  $("#gc-rotate").addEventListener("click", () => setRotate(!G.rotateWanted));
  $("#gc-reset").addEventListener("click", () => { if (!G.g) return; G.focus = null; paintGlobe(); hideTip(); G.g.pointOfView({ lat: 18, lng: 30, altitude: 2.35 }, 1200); setTimeout(() => setRotate(true), 1250); });
  const zoomBy = (k) => { if (!G.g) return; clearTimeout(G.idle); G.g.controls().autoRotate = false; const p = G.g.pointOfView(); G.g.pointOfView({ ...p, altitude: Math.max(0.08, Math.min(4.2, p.altitude * k)) }, 450); setTimeout(scheduleResume, 500); };
  $("#gc-in").addEventListener("click", () => zoomBy(0.65)); $("#gc-out").addEventListener("click", () => zoomBy(1.5));
  $("#globe-filter").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; $$("#globe-filter button").forEach((x) => x.classList.toggle("active", x === b)); G.band = b.dataset.band; G.focus = null; paintGlobe(); });
  $("#globe-list").addEventListener("click", (e) => { if (e.target.closest("[data-open]")) return; const it = e.target.closest("[data-focus]"); if (it) focusConsignment(it.dataset.focus); });
  const flyHot = (id) => { const h = G.data?.hot.find((x) => x.id === id); if (h) flyTo(h.lat, h.lng, 0.95); };
  $("#hotspot-list").addEventListener("click", (e) => { const it = e.target.closest("[data-hot]"); if (it) flyHot(it.dataset.hot); });
  $("#globe-panel").addEventListener("keydown", (e) => { if (e.key !== "Enter" && e.key !== " ") return; const f = e.target.closest("[data-focus]"), h = e.target.closest("[data-hot]"); if (e.target.closest("button")) return; if (f) { e.preventDefault(); focusConsignment(f.dataset.focus); } else if (h) { e.preventDefault(); flyHot(h.dataset.hot); } });

  function sparkline(vals, band) {
    if (!vals?.length) return `<span class="tag">no history</span>`;
    const w = 96, h = 30, n = vals.length;
    const pts = vals.map((v, i) => [(i / Math.max(1, n - 1)) * (w - 4) + 2, h - 3 - (Math.min(100, v) / 100) * (h - 6)]);
    const last = pts[pts.length - 1];
    return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-label="30-day risk trend"><line x1="0" x2="${w}" y1="${h - 3 - 0.3 * (h - 6)}" y2="${h - 3 - 0.3 * (h - 6)}" stroke="#E4E7EC" stroke-dasharray="2 3"/><polyline fill="none" stroke="${BAND_COLOR[band]}" stroke-width="1.6" stroke-linejoin="round" points="${pts.map((p) => p.map((x) => x.toFixed(1)).join(",")).join(" ")}"/><circle cx="${last[0]}" cy="${last[1]}" r="2.6" fill="${BAND_COLOR[band]}"/></svg>`;
  }
  function journeyHTML(j) {
    if (!j) return `<span class="tag">dates not set</span>`;
    const cls = j.status === "In transit" ? "intransit" : j.status === "Scheduled" ? "scheduled" : "arrived";
    const label = j.status === "In transit" ? `In transit · day ${j.elapsed_days} of ${j.total_days}` : j.status === "Scheduled" ? `Departs ${fmtDate(j.dispatch_date)}` : "Arrived";
    return `<div class="journey ${cls}"><span class="jstatus ${cls}">${label}</span><div class="jtrack"><div class="jfill" style="width:${j.progress * 100}%"></div><div class="jdot" style="left:${j.progress * 100}%"></div></div><div class="jlabels"><span>${fmtDate(j.dispatch_date)}</span><span>ETA ${fmtDate(j.eta_date)}</span></div></div>`;
  }
  function altCell(r) {
    const b = r.best_alternative;
    if (b) return `<b>${esc(b.title)}</b><span class="save">Risk ${r.risk_score.toFixed(0)} → ${b.risk_score.toFixed(0)} · saves ${fmtUSD(b.net_benefit_usd)}</span>`;
    return `<span class="none">${r.risk_band === "low" ? "Stay on current plan" : "No cheaper option than the mitigations"}</span>`;
  }
  function renderBoard() {
    const heads = ["Consignment", "Route", "Journey", "30-day trend", "Risk", "Best alternative"];
    $("#board").innerHTML = heads.map((h) => `<div class="bh">${h}</div>`).join("") + state.rows.map((r) => `
      <div class="br" data-cargo="${esc(r.consignment_id)}" title="Open cargo profile">
        <div><span class="cid">${esc(r.consignment_id)}</span><span class="cargo" title="${esc(r.cargo)}">${esc(r.cargo || r.supplier_name || "")}</span><span class="route-sub">${fmtUSD(r.cargo_value_usd)} · ${esc(r.supplier_name || "")}</span></div>
        <div><span class="route">${route(r)}</span><span class="route-sub"><span class="mode">${esc(r.mode || "—")}</span>${esc(r.inputs?.weather_condition || "")}${r.inputs?.reliability_score != null ? ` · reliability ${(+r.inputs.reliability_score).toFixed(2)}` : ""}</span></div>
        <div>${journeyHTML(r.journey)}</div>
        <div>${sparkline(r.trend, r.risk_band)}</div>
        <div class="risk-cell"><span class="risk-num" style="color:${BAND_COLOR[r.risk_band]}">${r.risk_score.toFixed(0)}</span>${chip(r.risk_band)}</div>
        <div class="alt-cell">${altCell(r)}</div>
      </div>`).join("");
  }

  // ---------- forms (shared by edit drawer and what-if) ----------
  const opt = (list) => list.map((x) => `${x}:${x}`);
  const FIELDS = [
    ["Shipment"],
    ["cargo", "Cargo", "text", { placeholder: "e.g. Consumer electronics" }], ["supplier_name", "Supplier", "text", {}],
    ["product_category", "Category", "select", opt(CATEGORIES)], ["mode", "Mode", "select", opt(MODES)],
    ["weight_t", "Weight (tonnes)", "number", { min: 0, step: "any" }], ["average_cost_per_unit", "Value per unit (USD)", "number", { min: 0, step: "any" }],
    ["Route"],
    ["origin_port", "From", "select", opt(PORT_LIST)], ["destination_port", "To", "select", opt(PORT_LIST)],
    ["dispatch_date", "Dispatch date", "date", {}], ["eta_date", "ETA", "date", {}],
    ["distance_km", "Distance (km)", "number", { min: 0, step: "any" }], ["lead_time_days", "Planned lead time (days)", "number", { min: 0, max: 400 }],
    ["Signals"],
    ["reliability_score", "Carrier reliability (0–1)", "number", { min: 0, max: 1, step: "any" }], ["geopolitical_risk_index", "Geopolitical risk (0–100)", "number", { min: 0, max: 100, step: "any" }],
    ["weather_condition", "Weather", "select", opt(WEATHER_LIST)], ["fuel_price_index", "Fuel price index (1.2–4.5)", "number", { min: 0, max: 10, step: "any" }],
  ];
  function fieldHTML([key, label, type, opts], rec) {
    if (!label) return `<div class="form-section span-2">${key}</div>`;
    const v = rec[key] ?? "";
    if (type === "select") return `<label>${label}<select name="${key}" class="input">${key === "weather_condition" ? "" : '<option value="">—</option>'}${opts.map((o) => { const i = o.indexOf(":"); const val = o.slice(0, i), txt = o.slice(i + 1); return `<option value="${esc(val)}" ${String(v) === val ? "selected" : ""}>${esc(txt)}</option>`; }).join("")}</select></label>`;
    return `<label>${label}<input name="${key}" type="${type}" class="input" value="${esc(v)}" ${Object.entries(opts).map(([k, x]) => `${k}="${esc(x)}"`).join(" ")}></label>`;
  }
  const formToRecord = (form) => { const o = {}; new FormData(form).forEach((v, k) => { if (v !== "") o[k] = v; }); return o; };
  function clearErrors(form) { $$(".field-error", form).forEach((e) => e.remove()); $$(".invalid", form).forEach((e) => e.classList.remove("invalid")); }
  function showErrors(form, err) {
    clearErrors(form); const errs = err.detail?.errors || [{ field: null, message: err.message }];
    for (const e of errs) { const inp = e.field && form.querySelector(`[name="${e.field}"]`); if (inp) { inp.classList.add("invalid"); inp.closest("label")?.insertAdjacentHTML("beforeend", `<span class="field-error">${esc(e.message)}</span>`); } else toast(e.message); }
  }

  // ---------- result rendering ----------
  function fmtN(v, d = 1) { return v == null || v === "" ? "—" : (+v).toFixed(d); }
  function alternativesHTML(r, { applyable }) {
    if (!r.alternatives) return "";
    const cur = `<tr class="current"><td><div class="alt-title">Current plan${r.applied_alternative ? '<span class="badge-applied">updated</span>' : ""}</div><div class="alt-desc">${esc(r.mode || "")} · ${esc(r.inputs?.weather_condition || "")} · ${esc(routeText(r))}${r.route_via ? ` via ${esc(r.route_via)}` : ""}</div></td><td class="num"><b style="color:${BAND_COLOR[r.risk_band]}">${r.risk_score.toFixed(1)}</b></td><td class="num">—</td><td class="num">—</td><td class="num">${fmtUSD(r.expected_loss_usd)}</td><td class="num">—</td>${applyable ? "<td></td>" : ""}</tr>`;
    const rows = r.alternatives.map((a) => `<tr class="${a.recommended ? "rec" : ""}">
      <td><div class="alt-title">${esc(a.title)}${a.recommended ? '<span class="badge-rec">Recommended</span>' : ""}</div><div class="alt-desc">${esc(a.description)}</div><div class="diffs">${a.diffs.map((d) => `<span class="diff">${esc(d)}</span>`).join("")}</div></td>
      <td class="num"><b style="color:${BAND_COLOR[a.risk_band]}">${a.risk_score.toFixed(1)}</b><div class="delta ${a.delta_risk <= 0 ? "down" : "up"}">${a.delta_risk > 0 ? "+" : ""}${a.delta_risk.toFixed(1)}</div></td>
      <td class="num">${days(a.eta_delta_days)}</td>
      <td class="num ${a.cost_usd < 0 ? "good" : ""}">${a.cost_usd < 0 ? "saves " + fmtUSD(-a.cost_usd) : fmtUSD(a.cost_usd)}</td>
      <td class="num">${fmtUSD(a.expected_loss_usd)}</td>
      <td class="num"><b class="${a.net_benefit_usd >= 0 ? "good" : "bad"}">${fmtUSD(a.net_benefit_usd)}</b></td>
      ${applyable ? `<td class="num"><button class="btn btn-sm ${a.recommended ? "btn-primary" : "btn-secondary"}" data-apply="${esc(a.id)}">Apply</button></td>` : ""}</tr>`).join("");
    return `<div><div class="section-title"><span>Alternatives</span><span class="tag">each option re-scored by the risk model</span></div>
      <div class="table-wrap"><table class="alt-table"><thead><tr><th>Option</th><th class="num">Risk</th><th class="num">ETA</th><th class="num">Extra cost</th><th class="num">Exp. loss</th><th class="num">Net benefit</th>${applyable ? "<th></th>" : ""}</tr></thead><tbody>${cur}${rows || ""}</tbody></table></div>
      ${r.alternatives.length ? "" : '<div class="muted small" style="margin-top:8px">No other alternatives on file for this consignment.</div>'}
      <div class="muted small" style="margin-top:8px">Net benefit = expected loss avoided − extra cost. A negative value means the option costs more than the risk it removes.</div></div>`;
  }

  // ---------- drawer ----------
  async function openDrawer(cid) {
    const d = $("#drawer"); d.classList.add("open"); d.setAttribute("aria-hidden", "false"); $("#drawer-backdrop").classList.add("open");
    $("#drawer-body").innerHTML = `<div class="empty">Loading…</div>`;
    try { renderDrawer(await api(`/api/consignments/${encodeURIComponent(cid)}`)); } catch (e) { $("#drawer-body").innerHTML = `<div class="alert error">${esc(e.message)}</div>`; }
  }
  function closeDrawer() { $("#drawer").classList.remove("open"); $("#drawer").setAttribute("aria-hidden", "true"); $("#drawer-backdrop").classList.remove("open"); }
  $("#drawer-close").addEventListener("click", closeDrawer); $("#drawer-backdrop").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => e.key === "Escape" && closeDrawer());
  // Drawer = route journey diagram, score summary, option comparison and the alternatives table.
  function laneGeometry(r) {
    const g = state.overview?.geo?.routes?.[r.consignment_id]; if (!g) return null;
    const pts = g.points, seg = []; let tot = 0;
    for (let i = 0; i < pts.length - 1; i++) { const d = ang(pts[i], pts[i + 1]); seg.push(d); tot += d; }
    const cum = [0]; seg.forEach((d) => cum.push(cum[cum.length - 1] + d));
    const hot = (state.overview.geo.hotspots || []).filter((h) => h.lanes.includes(r.consignment_id)).map((h) => {
      let best = 0, bd = Infinity; pts.forEach((p, i) => { const d = ang(p, [h.lat, h.lng]); if (d < bd) { bd = d; best = i; } });
      const level = +r.inputs[h.factor] || 0;
      return { ...h, t: tot ? cum[best] / tot : 0.5, level, band: levelBand(level) };
    }).sort((x, y) => x.t - y.t);
    return { g, km: Math.round(tot * 6371), hot };
  }
  function journeyHTML2(r) {
    const j = r.journey || {}, geo = laneGeometry(r), c = BAND_COLOR[r.risk_band];
    const W = 640, x0 = 56, x1 = 584, y = 64, X = (t) => x0 + (x1 - x0) * t;
    const prog = j.status === "In transit" ? j.progress : j.status === "Arrived" ? 1 : 0;
    const air = String(r.mode || "").toLowerCase() === "air";
    const line = air ? `M${x0},${y} Q${(x0 + x1) / 2},${y - 46} ${x1},${y}` : `M${x0},${y} L${x1},${y}`;
    // hotspot labels alternate above/below so they never collide
    const hots = (geo?.hot || []).map((h, i) => {
      const hx = X(Math.min(0.82, Math.max(0.18, h.t))), up = i % 2 === 0, hc = BAND_COLOR[h.band];
      return `<g class="jd-hot" style="animation-delay:${0.35 + i * 0.12}s"><title>${esc(h.name)}: ${esc(FACTOR_NAME[h.factor])} ${h.level.toFixed(0)}</title>
        <line x1="${hx}" x2="${hx}" y1="${y}" y2="${up ? y - 22 : y + 22}" stroke="${hc}" stroke-dasharray="2 2"/>
        <path d="M${hx},${(up ? y - 34 : y + 22)} l7,12 h-14z" fill="${hc}" stroke="#fff" stroke-width="1.5"/>
        <text x="${hx}" y="${up ? y - 40 : y + 48}" text-anchor="middle" class="jd-hl">${esc(h.name)}</text>
        <text x="${hx}" y="${up ? y - 52 : y + 60}" text-anchor="middle" class="jd-hv" fill="${hc}">${esc(FACTOR_NAME[h.factor].replace(" index", ""))} ${h.level.toFixed(0)}</text></g>`;
    }).join("");
    const vx = air ? null : X(prog);
    const vehicle = air ? "" : `<g class="jd-veh" style="--tx:${vx - x0}px"><circle cx="${x0}" cy="${y}" r="15" fill="${c}" opacity=".18" class="jd-pulse"/><circle cx="${x0}" cy="${y}" r="11" fill="${c}" stroke="#fff" stroke-width="2.5"/><g transform="translate(${x0 - 7},${y - 7}) scale(.58)" stroke="#fff" fill="none" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">${ICONS[modeKey(r.mode)].replace(/<\/?svg[^>]*>/g, "")}</g></g>`;
    const planeDot = air ? `<circle r="6" fill="${c}" stroke="#fff" stroke-width="2"><animateMotion dur="3.2s" repeatCount="indefinite" path="${line}"/></circle>` : "";
    const statusTxt = j.status === "In transit" ? `Day ${j.elapsed_days} of ${j.total_days}` : j.status === "Scheduled" ? `departs in ${Math.max(0, j.days_to_eta - j.total_days)} days` : j.status || "";
    return `<div class="jd card-lite">
      <div class="jd-top"><span class="section-title" style="margin:0">Journey</span><span class="jd-status ${j.status === "In transit" ? "on" : ""}"><span class="jd-dot"></span>${esc(j.status || "Not dated")}${statusTxt ? " · " + esc(statusTxt) : ""}</span></div>
      <svg class="jd-svg" viewBox="0 0 ${W} 132" role="img" aria-label="Journey from ${esc(r.origin_port || "")} to ${esc(r.destination_port || "")}">
        <defs><linearGradient id="jdg" x1="0" x2="1"><stop offset="0" stop-color="${c}" stop-opacity=".9"/><stop offset="1" stop-color="${c}" stop-opacity=".55"/></linearGradient></defs>
        <path d="${line}" fill="none" stroke="#E4E7EC" stroke-width="6" stroke-linecap="round"/>
        <path d="${line}" fill="none" stroke="${c}" stroke-width="2" stroke-dasharray="1 7" stroke-linecap="round" class="jd-flow"/>
        ${air ? "" : `<path d="M${x0},${y} L${vx},${y}" fill="none" stroke="url(#jdg)" stroke-width="6" stroke-linecap="round" class="jd-done" style="--len:${Math.max(1, vx - x0)}"/>`}
        ${hots}
        <g><circle cx="${x0}" cy="${y}" r="8" fill="#fff" stroke="#667085" stroke-width="2.5"/><circle cx="${x1}" cy="${y}" r="9" fill="${c}" stroke="#fff" stroke-width="3"/><circle cx="${x1}" cy="${y}" r="15" fill="none" stroke="${c}" stroke-width="1.5" class="jd-ring"/></g>
        ${vehicle}${planeDot}
        <text x="${x0}" y="${y + 30}" text-anchor="middle" class="jd-port">${esc(r.origin_port || "—")}</text>
        <text x="${x0}" y="${y + 44}" text-anchor="middle" class="jd-sub">${esc(fmtDate(j.dispatch_date))}</text>
        <text x="${x1}" y="${y + 30}" text-anchor="middle" class="jd-port">${esc(r.destination_port || "—")}</text>
        <text x="${x1}" y="${y + 44}" text-anchor="middle" class="jd-sub">ETA ${esc(fmtDate(j.eta_date))}</text>
      </svg>
      <div class="jd-stats">
        <div><span>Distance</span><b>${geo ? "≈ " + geo.km.toLocaleString() + " km" : "—"}</b></div>
        <div><span>Transit</span><b>${j.total_days ? j.total_days + " days" : "—"}</b></div>
        <div><span>Mode</span><b><span class="mode">${esc(r.mode || "—")}</span></b></div>
        <div><span>Carrier reliability</span><b>${r.inputs?.reliability_score != null ? (+r.inputs.reliability_score).toFixed(2) : "—"}</b></div>
        <div><span>Hotspots on route</span><b>${geo ? geo.hot.length : "—"}</b></div>
      </div>
    </div>`;
  }
  function scoreHTML(r) {
    const c = BAND_COLOR[r.risk_band], best = r.best_alternative;
    const [e0, h0] = [state.meta.risk_bands[1].min, state.meta.risk_bands[2].min];
    // piecewise scale with each band a third of the track
    const pos = (v) => (v <= e0 ? (v / e0) * 33.3 : v <= h0 ? 33.3 + ((v - e0) / (h0 - e0)) * 33.3 : 66.6 + ((Math.min(100, v) - h0) / (100 - h0)) * 33.4);
    const bandText = { low: "Low risk: normal tracking", elevated: "Elevated: watch closely", high: "High: act before it slips" }[r.risk_band];
    return `<div class="sh card-lite">
      <div class="sh-dial" style="--c:${c};--target:${r.risk_score}"><div class="sh-dial-in"><b class="sh-num" data-final="${r.risk_score.toFixed(1)}">${r.risk_score.toFixed(1)}</b><span>Disruption risk</span></div></div>
      <div class="sh-main">
        <div class="sh-row">${chip(r.risk_band)}<span class="sh-band">${bandText}</span></div>
        <div class="sh-scale">
          <div class="sh-track"><span class="z low"></span><span class="z elevated"></span><span class="z high"></span></div>
          <div class="sh-mark now" style="--x:${pos(r.risk_score)}%"><i style="background:${c}"></i><em>Now ${r.risk_score.toFixed(0)}</em></div>
          ${best ? `<div class="sh-mark alt" style="--x:${pos(best.risk_score)}%"><i></i><em>With best option ${best.risk_score.toFixed(0)}</em></div>` : ""}
          <div class="sh-ticks"><span style="left:0">0</span><span style="left:33.3%">${e0}</span><span style="left:66.6%">${h0}</span><span style="left:100%">100</span></div>
        </div>
        <div class="sh-stats">
          <div><span>Cargo value</span><b>${fmtUSD(r.cargo_value_usd)}</b></div>
          <div><span>Cost if disrupted</span><b>${fmtUSD(r.estimated_disruption_cost_usd)}</b></div>
          <div><span>Expected loss</span><b class="bad">${fmtUSD(r.expected_loss_usd)}</b></div>
          <div><span>Confidence</span><b>${r.confidence.toFixed(0)}%</b><i class="sh-conf"><span style="--w:${r.confidence}%;width:${r.confidence}%"></span></i></div>
        </div>
      </div>
    </div>`;
  }
  function compareHTML(r) {
    const alts = r.alternatives || []; if (!alts.length) return "";
    const rows = [{ title: "Current plan", risk: r.risk_score, band: r.risk_band, net: 0, cur: true }, ...alts.map((a) => ({ title: a.title, risk: a.risk_score, band: a.risk_band, net: a.net_benefit_usd, rec: a.recommended, delta: a.delta_risk, eta: a.eta_delta_days }))];
    const maxNet = Math.max(1, ...rows.map((x) => Math.abs(x.net)));
    return `<div class="cmp card-lite"><div class="section-title"><span>Compare options</span><span class="tag">risk after the change · net benefit</span></div>
      <div class="cmp-head"><span></span><span>Disruption risk</span><span>Net benefit</span></div>
      ${rows.map((x, i) => `<div class="cmp-row ${x.cur ? "cur" : ""} ${x.rec ? "rec" : ""}" style="animation-delay:${0.08 * i}s">
        <span class="cmp-t">${x.rec ? '<span class="star">★</span>' : ""}${esc(x.title)}${x.eta ? `<small>${days(x.eta)}</small>` : ""}</span>
        <span class="cmp-risk"><span class="cmp-bar"><span style="--w:${Math.max(1.5, x.risk)}%;background:${BAND_COLOR[x.band]}"></span>${x.cur ? "" : `<i class="cmp-ghost" style="left:${r.risk_score}%"></i>`}</span><b style="color:${BAND_COLOR[x.band]}">${x.risk.toFixed(0)}</b>${x.cur ? "" : `<em class="${x.delta <= 0 ? "down" : "up"}">${x.delta > 0 ? "+" : ""}${x.delta.toFixed(0)}</em>`}</span>
        <span class="cmp-net">${x.cur ? '<span class="tag">baseline</span>' : `<span class="cmp-div"><span class="${x.net >= 0 ? "pos" : "neg"}" style="--w:${(Math.abs(x.net) / maxNet) * 50}%"></span></span><b class="${x.net >= 0 ? "good" : "bad"}">${fmtUSD(x.net)}</b>`}</span>
      </div>`).join("")}
    </div>`;
  }
  function drawerHTML(r) {
    return `${journeyHTML2(r)}${scoreHTML(r)}${compareHTML(r)}<div class="card-lite alt-wrap">${alternativesHTML(r, { applyable: true })}</div>`;
  }
  function renderDrawer(r) {
    $("#drawer-eyebrow").textContent = `${r.consignment_id} · ${r.cargo || ""}`;
    $("#drawer-title").textContent = routeText(r);
    $("#drawer-sub").textContent = `${r.supplier_name || ""}${r.product_category ? " · " + r.product_category : ""}`;
    const body = $("#drawer-body");
    body.innerHTML = `<div id="drawer-result" class="drawer-stack">${drawerHTML(r)}</div>`;
    body.scrollTop = 0;
    const num = body.querySelector(".sh-num"); if (num) countUp(num, num.dataset.final);
    bindApply(r.consignment_id);
  }
  function bindApply(cid) {
    $$("#drawer-result [data-apply]").forEach((b) => b.addEventListener("click", async () => {
      const title = b.closest("tr").querySelector(".alt-title").childNodes[0].textContent;
      if (!confirm(`Apply "${title}" to ${cid}? The consignment's route, carrier and dates will be updated.`)) return;
      try { const res = await api(`/api/consignments/${encodeURIComponent(cid)}/apply/${encodeURIComponent(b.dataset.apply)}`, { method: "POST" }); await refresh(); toast(`${cid} updated · risk now ${res.risk_score.toFixed(1)}`); openDrawer(cid); }
      catch (e) { toast(e.message); }
    }));
  }

  document.addEventListener("click", (e) => { const t = e.target.closest("[data-open]"); if (t) { e.preventDefault(); openDrawer(t.dataset.open); } });

  // ---------- cargo profile (opened from the consignment board) ----------
  const HICON = {
    dry: '<path d="M12 3a9 9 0 0 1 9 9H3a9 9 0 0 1 9-9z"/><path d="M12 12v6a2 2 0 0 0 4 0"/>',
    temp: '<path d="M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4.5 4.5 0 1 0 5 0z"/>',
    fragile: '<path d="M8 2h8l-1 7a3 3 0 0 1-6 0z"/><path d="M12 12v8M8 22h8"/>',
    up: '<path d="M7 19V5M4 8l3-3 3 3M17 19V5M14 8l3-3 3 3"/><path d="M3 22h18"/>',
    nostack: '<rect x="6" y="13" width="12" height="8"/><rect x="6" y="3" width="12" height="8"/><path d="M3 3l18 18"/>',
    esd: '<path d="M13 2 3 14h9l-1 8 10-12h-9z"/>',
    hazard: '<path d="M12 2 22 12 12 22 2 12z"/><path d="M12 8v5M12 16h.01"/>',
    vent: '<path d="M3 8h11a3 3 0 1 0-3-3"/><path d="M3 16h15a3 3 0 1 1-3 3"/><path d="M3 12h18"/>',
    segregate: '<path d="M12 3v18"/><rect x="3" y="7" width="6" height="10" rx="1"/><rect x="15" y="7" width="6" height="10" rx="1"/>',
    heavy: '<path d="M6 8h12l2 13H4z"/><circle cx="12" cy="5" r="3"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    moisture: '<path d="M12 2.7s7 7.3 7 12.3a7 7 0 0 1-14 0c0-5 7-12.3 7-12.3z"/>',
    secure: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    shock: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    dust: '<path d="M17.5 19H7a5 5 0 1 1 1.1-9.9A6 6 0 0 1 20 11a4 4 0 0 1-2.5 8z"/>',
    seal: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
    box: '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="M3 8l9 5 9-5M12 13v8"/>',
    container: '<rect x="2" y="6" width="20" height="12" rx="1"/><path d="M6 6v12M10 6v12M14 6v12M18 6v12"/>',
    ship: '<path d="M2 20c2 1 4 1 6 0s4-1 6 0 4 1 6 0"/><path d="M4 17.5 3 13h18l-2 4.5"/><path d="M6 13V8h12v5"/>',
    doc: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h5"/>',
    shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  };
  const ic = (k) => `<svg viewBox="0 0 24 24" aria-hidden="true">${HICON[k] || HICON.box}</svg>`;
  const CAT_TILE = { Electronics: "esd", Textiles: "box", Perishables: "temp", Pharmaceuticals: "seal", Automotive: "heavy" };
  const plural = (n, w) => `${Number(n).toLocaleString()} ${w}${n === 1 || /s$/.test(w) ? "" : "s"}`;
  const fmtT = (t) => (t >= 100 ? Math.round(t).toLocaleString() : t.toFixed(1)) + " t";

  async function openCargo(cid) {
    const d = $("#drawer"); d.classList.add("open"); d.setAttribute("aria-hidden", "false"); $("#drawer-backdrop").classList.add("open");
    $("#drawer-body").innerHTML = `<div class="empty">Loading cargo profile…</div>`;
    try {
      const { consignment: c, profile: p } = await api(`/api/consignments/${encodeURIComponent(cid)}/cargo`);
      $("#drawer-eyebrow").textContent = `${c.consignment_id} · Cargo profile`;
      $("#drawer-title").textContent = c.cargo || p.commodity;
      $("#drawer-sub").textContent = `${routeText(c)} · ${c.mode || ""}${c.supplier_name ? " · supplier " + c.supplier_name : ""}`;
      const body = $("#drawer-body");
      body.innerHTML = `<div class="drawer-stack cargo-profile">${cargoHero(c, p)}${cargoLoad(p)}${cargoCarried(c, p)}${cargoHandling(p)}${cargoSensors(c, p)}${cargoDocs(p)}</div>`;
      body.scrollTop = 0;
      requestAnimationFrame(() => $$("#drawer-body .ring-v, #drawer-body .cf-fill, #drawer-body .sn-mark").forEach((el) => el.classList.add("go")));
    } catch (e) { $("#drawer-body").innerHTML = `<div class="alert error">${esc(e.message)}</div>`; }
  }
  function cargoHero(c, p) {
    const hz = p.hazard;
    return `<div class="card-lite cg-hero">
      <div class="cg-top"><span class="cg-tile">${ic(CAT_TILE[c.product_category] || "box")}</span>
        <div><div class="cg-kicker">What it is</div><h3 class="cg-name">${esc(p.commodity)}</h3></div></div>
      <p class="cg-about">${esc(p.about)}</p>
      <div class="cg-chips">
        ${p.hs_code ? `<span class="cg-chip" title="${esc(p.hs_desc || "")}"><em>HS</em>${esc(p.hs_code)}</span>` : ""}
        ${hz ? `<span class="cg-chip dg"><em>DG</em>${esc(hz.label)}</span>` : `<span class="cg-chip ok"><em>✓</em>Non-hazardous</span>`}
        ${p.incoterm ? `<span class="cg-chip"><em>Terms</em>${esc(p.incoterm)}</span>` : ""}
        <span class="cg-chip"><em>Value</em>${fmtUSD(p.value_usd)}</span>
        ${p.generic ? `<span class="cg-chip warn"><em>!</em>Standard profile</span>` : ""}
      </div>
      ${hz ? `<div class="cg-dg"><div class="dg-diamond"><span>${esc(hz.code)}</span></div><div class="dg-txt"><b>${esc(hz.name)}</b><span>${[hz.un, hz.pg ? "Packing group " + hz.pg : null, hz.marine_pollutant ? "Marine pollutant" : null].filter(Boolean).map(esc).join(" · ") || esc(hz.label)}</span></div></div>` : ""}
    </div>`;
  }
  function cargoLoad(p) {
    const L = p.load, eq = p.equipment, n = L.equipment_count, show = Math.min(n, 12), fill = Math.max(L.fill_weight, L.fill_volume);
    const glyph = (i) => `<svg class="cf" viewBox="0 0 60 26" style="animation-delay:${i * 0.05}s"><rect x="1" y="1" width="58" height="24" rx="2" fill="#F8FAFC" stroke="#98A2B3"/><rect class="cf-fill" x="2.5" y="2.5" height="21" rx="1" fill="#0F4C81" opacity=".82" style="--w:${55 * fill}px"/>${[10, 20, 30, 40, 50].map((x) => `<line x1="${x}" x2="${x}" y1="3" y2="23" stroke="#fff" stroke-opacity=".35"/>`).join("")}</svg>`;
    return `<div class="card-lite">
      <div class="section-title"><span>How much is loaded</span><span class="tag">derived from ${plural(L.units, p.unit_label)}</span></div>
      <div class="cg-stats">
        <div><span>Quantity</span><b>${Number(L.units).toLocaleString()}</b><small>${esc(p.unit_label)}${L.units === 1 ? "" : "s"}</small></div>
        <div><span>Net weight</span><b>${fmtT(L.net_t)}</b><small>cargo only</small></div>
        <div><span>Gross weight</span><b>${fmtT(L.gross_t)}</b><small>with packing</small></div>
        <div><span>Volume</span><b>${Math.round(L.volume_m3).toLocaleString()} m³</b><small>stowed</small></div>
        <div><span>Packages</span><b>${Number(L.packages).toLocaleString()}</b><small>${esc(p.package_label)}${L.packages === 1 ? "" : "s"}</small></div>
      </div>
      <div class="cg-eq">
        <div class="cg-eq-vis">${Array.from({ length: show }, (_, i) => glyph(i)).join("")}${n > show ? `<span class="cg-more">+${n - show}</span>` : ""}</div>
        <div class="cg-eq-txt"><b>${n} × ${esc(eq.name)}</b>
          <div class="cg-fill"><span>By weight</span><i><em style="--w:${L.fill_weight * 100}%"></em></i><b>${(L.fill_weight * 100).toFixed(0)}%</b></div>
          <div class="cg-fill"><span>By volume</span><i><em style="--w:${L.fill_volume * 100}%"></em></i><b>${(L.fill_volume * 100).toFixed(0)}%</b></div>
          <small>Limited by ${esc(L.limited_by)} · max ${eq.payload_t} t and ${eq.volume_m3} m³ each</small></div>
      </div>
    </div>`;
  }
  function cargoCarried(c, p) {
    const steps = [["box", "Packed", p.packing], ["container", "Equipment", `${p.load.equipment_count} × ${p.equipment.name}`], ["ship", "Stowage", p.stowage], ["secure", "Secured", p.securing]];
    return `<div class="card-lite"><div class="section-title"><span>How it's carried</span><span class="tag">${esc(c.mode || "")}</span></div>
      <ol class="cg-steps">${steps.map(([k, t, d], i) => `<li style="animation-delay:${0.1 + i * 0.08}s"><span class="st-ic">${ic(k)}</span><div><b>${t}</b><p>${esc(d)}</p></div></li>`).join("")}</ol></div>`;
  }
  function cargoHandling(p) {
    const hs = [...p.handling].sort((a, b) => b.critical - a.critical);
    return `<div class="card-lite"><div class="section-title"><span>Handling requirements</span><span class="tag">${hs.filter((h) => h.critical).length} critical</span></div>
      <div class="cg-hand">${hs.map((h, i) => `<div class="hd ${h.critical ? "crit" : ""}" style="animation-delay:${0.1 + i * 0.07}s"><span class="hd-ic">${ic(h.icon)}</span><div><b>${esc(h.title)}${h.critical ? '<span class="crit-tag">Critical</span>' : ""}</b><p>${esc(h.text)}</p></div></div>`).join("")}</div></div>`;
  }
  function cargoSensors(c, p) {
    if (!p.sensors.length) return `<div class="card-lite"><div class="section-title"><span>Condition monitor</span></div><div class="empty small">No sensors assigned to this consignment yet.</div></div>`;
    const live = c.journey?.status === "In transit";
    const rows = p.sensors.map((s) => {
      if (s.text) return `<div class="sn"><span class="sn-n">${esc(s.name)}</span><span class="sn-pill ok">${esc(s.text)}</span><span class="sn-st ok">OK</span></div>`;
      const lo = s.min ?? null, hi = s.max ?? null;
      const d0 = Math.min(0, lo ?? 0, s.value), d1 = Math.max(hi != null ? hi * 1.25 : (lo ?? 1) * 2.5, s.value * 1.1);
      const X = (v) => ((v - d0) / (d1 - d0)) * 100, safeL = X(lo ?? d0), safeR = X(hi ?? d1);
      const lab = { ok: "OK", watch: "Watch", breach: "Breach" }[s.status];
      return `<div class="sn"><span class="sn-n">${esc(s.name)}<small>${lo != null && hi != null ? `safe ${lo}–${hi} ${esc(s.unit)}` : hi != null ? `max ${hi} ${esc(s.unit)}` : `min ${lo} ${esc(s.unit)}`}</small></span>
        <span class="sn-bar"><span class="sn-safe" style="left:${safeL}%;width:${safeR - safeL}%"></span>${hi != null ? `<span class="sn-lim" style="left:${safeR}%"></span>` : ""}${lo != null ? `<span class="sn-lim" style="left:${safeL}%"></span>` : ""}<span class="sn-mark ${s.status}" style="--x:${X(s.value)}%"><b>${s.value}${esc(s.unit.startsWith("%") || s.unit === "°" ? s.unit.replace(" RH", "") : " " + s.unit)}</b></span></span>
        <span class="sn-st ${s.status}">${lab}</span></div>`;
    }).join("");
    const worst = p.sensors.some((s) => s.status === "breach") ? "breach" : p.sensors.some((s) => s.status === "watch") ? "watch" : "ok";
    return `<div class="card-lite"><div class="section-title"><span>Condition monitor</span><span class="sn-live ${live ? "on" : ""}"><span class="jd-dot"></span>${live ? "In transit" : "Pre-shipment reading at origin"}</span></div>${p.sensor_note ? `<div class="muted small" style="margin:-4px 0 8px">${esc(p.sensor_note)}</div>` : ""}
      <div class="sn-sum ${worst}">${worst === "ok" ? "All readings inside safe limits." : worst === "watch" ? "One or more readings are close to a limit. Keep an eye on it." : "A reading is outside its safe limit. Act now."}</div>${rows}</div>`;
  }
  function cargoDocs(p) {
    const n = p.documents.length, r = p.documents_ready;
    return `<div class="cg-two">
      <div class="card-lite"><div class="section-title"><span>Documents</span><span class="tag">${r} of ${n} ready</span></div>
        <div class="doc-top">${ring(n ? r / n : 0, "#0F4C81", 52)}<div><b>${r === n ? "Ready to ship" : `${n - r} still pending`}</b><span class="muted small">Paperwork needed to move and clear this load</span></div></div>
        <ul class="docs">${p.documents.map((d) => `<li class="${d.status}"><span class="doc-ic">${ic("doc")}</span>${esc(d.name)}<span class="doc-st">${d.status === "ready" ? "✓ Ready" : "Pending"}</span></li>`).join("")}</ul></div>
      <div class="card-lite"><div class="section-title"><span>Cover &amp; parties</span></div>
        <div class="cover"><span class="cv-ic">${ic("shield")}</span><div><span>Insured value</span><b>${fmtUSD(p.insured_value_usd)}</b><small>110% of cargo value</small></div></div>
        <dl class="cv-dl"><dt>Insurance</dt><dd>${esc(p.insurance || "Not arranged")}</dd><dt>Incoterm</dt><dd>${esc(p.incoterm || "—")}</dd><dt>Consignee</dt><dd>${esc(p.consignee || "—")}</dd><dt>HS code</dt><dd>${esc(p.hs_code ? p.hs_code + " · " + p.hs_desc : "—")}</dd></dl></div>
    </div>`;
  }
  document.addEventListener("click", (e) => { const t = e.target.closest("[data-cargo]"); if (t) { e.preventDefault(); openCargo(t.dataset.cargo); } });


  // ---------- intelligent workflow ----------
  const WF = { current: null, runs: [], playing: false, pending: null, open: null };
  const STEP_LABEL = {
    notify: "Notification sent to the warehouse", questions: "Warehouse system asks its questions", answers: "RiskLens answers from the data",
    mail: "Consolidated mail to the stakeholder", reply: "Stakeholder reply received", understand: "Reply understood: decision, date, constraint", deploy: "Action deployed on the consignment",
  };
  const STEP_WAIT = { questions: 1500, answers: 1700, mail: 1600, reply: 2400, understand: 2000, deploy: 1600 };
  const TYPING = { questions: ["warehouse", "Warehouse system is asking…"], answers: ["risklens", "RiskLens agent is answering from the data…"], mail: ["risklens", "RiskLens agent is composing the mail…"],
    reply: ["stakeholder", "Waiting for the stakeholder…"], understand: ["risklens", "RiskLens agent is reading the reply…"], deploy: ["risklens", "RiskLens agent is deploying the action…"] };
  const initials = (n) => n.split(/\s+/).map((x) => x[0]).join("").slice(0, 2).toUpperCase();
  const avatar = (who, w) => who === "stakeholder" ? `<span class="wf-av human">${esc(initials(w.stakeholder.name))}</span>` : `<span class="wf-av ${who}">${esc(w.agents[who].short)}</span>`;
  const who = (k, w) => (k === "stakeholder" ? w.stakeholder.name : w.agents[k].name);
  const revealed = (w) => ["notify", "questions", "answers", "mail", "reply", "understand", "deploy"].slice(0, w.revealed);
  const pre = (t) => `<pre class="wf-pre">${esc(t)}</pre>`;

  function wfPicker() {
    const acts = (state.overview?.top_actions || []).filter((a) => !a.deployed && !a.executed);
    const sel = $("#wf-action");
    sel.innerHTML = acts.length ? acts.map((a) => `<option value="${esc(actKey(a))}">${esc(a.action)} · ${esc(a.consignment_id)} · ${esc(a.lane)}${a.notified ? " · notified" : ""}</option>`).join("") : `<option value="">No open actions</option>`;
    const notified = acts.filter((a) => a.notified).sort((x, y) => y.notified.sent_at.localeCompare(x.notified.sent_at));
    if (WF.pending && acts.some((a) => actKey(a) === WF.pending)) sel.value = WF.pending; else if (notified.length) sel.value = actKey(notified[0]);
    $("#wf-run").disabled = !acts.length || WF.playing;
  }
  function wfRuns() {
    const el = $("#wf-runs");
    el.innerHTML = WF.runs.length ? `<span class="wf-runs-l">Runs</span>` + WF.runs.map((r) => `<button class="wf-run-chip ${WF.current?.id === r.id ? "on" : ""} ${r.status}" data-wf="${esc(r.id)}"><span class="d"></span>${esc(r.action)}<small>${esc(r.consignment_id)} · ${r.status === "done" ? "deployed " + esc(fmtWhen(r.deployed_at)) : "in progress"}</small></button>`).join("") : "";
  }
  async function renderWorkflowPage(opts = {}) {
    try { WF.runs = await api("/api/workflows"); } catch (e) { WF.runs = []; }
    wfPicker(); wfRuns();
    if (WF.open) { const r = WF.runs.find((x) => x.id === WF.open); WF.open = null; if (r) { WF.current = r; renderWorkflow(r); return; } }
    if (WF.pending && !WF.playing) { const k = WF.pending; WF.pending = null; if ($("#wf-action").value === k) { startWorkflow(k); return; } }
    if (opts.keep && WF.current) { const r = WF.runs.find((x) => x.id === WF.current.id); if (r && !WF.playing) { WF.current = r; renderWorkflow(r); } return; }
    if (!WF.current && WF.runs.length) { WF.current = WF.runs[0]; renderWorkflow(WF.runs[0]); }
    else if (WF.current) renderWorkflow(WF.current);
  }
  async function startWorkflow(k) {
    const [cid, aid] = k.split("|");
    $("#wf-run").disabled = true;
    try {
      const w = await api("/api/workflows", { body: { consignment_id: cid, action_id: aid } });
      WF.current = w; WF.runs.unshift(w); wfRuns(); renderWorkflow(w, { animate: true });
      playWorkflow(w.id);
    } catch (e) { toast(e.message); $("#wf-run").disabled = false; }
  }
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  async function playWorkflow(id) {
    WF.playing = true; $("#wf-run").disabled = true;
    try {
      let w = WF.current;
      while (w && w.id === id && w.status !== "done" && currentView() === "workflow") {
        const next = ["notify", "questions", "answers", "mail", "reply", "understand", "deploy"][w.revealed];
        showTyping(next, w); await sleep(STEP_WAIT[next] || 1200);
        w = await api(`/api/workflows/${encodeURIComponent(id)}/advance`, { method: "POST" });
        if (WF.current?.id !== id) break;
        WF.current = w; const i = WF.runs.findIndex((x) => x.id === id); if (i >= 0) WF.runs[i] = w;
        renderWorkflow(w, { animate: true, just: next });
        if (w.status === "done") { await refresh(); wfRuns(); toast(`${w.consignment_id}: action deployed by the RiskLens agent`); }
      }
    } catch (e) { toast(e.message); }
    WF.playing = false; wfPicker();
  }
  function showTyping(step, w) {
    const [k, label] = TYPING[step] || ["risklens", "Working…"];
    const t = $("#wf-thread"); t.querySelector(".wf-typing")?.remove();
    t.insertAdjacentHTML("beforeend", `<div class="wf-msg ${k === "risklens" ? "left" : "right"} wf-typing">${avatar(k, w)}<div class="wf-bubble"><span class="wf-dots"><i></i><i></i><i></i></span>${esc(label)}</div></div>`);
    t.scrollTo({ top: t.scrollHeight, behavior: "smooth" });
    railRender(w, step);
  }
  function msg(k, w, inner, cls = "") {
    const side = k === "risklens" ? "left" : "right";
    return `<div class="wf-msg ${side} ${cls}">${avatar(k, w)}<div class="wf-bubble-wrap"><span class="wf-who">${esc(who(k, w))}${k === "stakeholder" ? '<em class="wf-sim">simulated reply</em>' : ""}</span>${inner}</div></div>`;
  }
  function stepHTML(step, w) {
    const S = w.steps;
    if (step === "notify") return msg("risklens", w, `<div class="wf-bubble"><b>Notification sent to ${esc(names(S.notify.to))}</b>${S.notify.sent_at ? `<span class="wf-meta">from Recommended actions · ${esc(fmtWhen(S.notify.sent_at))}</span>` : ""}
      <details class="wf-det"><summary>${esc(S.notify.subject)}</summary>${pre(S.notify.body)}</details></div>`);
    if (step === "questions") return `<div class="wf-group">${S.questions.map((q, i) => msg("warehouse", w, `<div class="wf-bubble q" style="--i:${i}"><span class="wf-qn">Q${i + 1}</span>${esc(q)}</div>`, i ? "cont" : "")).join("")}</div>`;
    if (step === "answers") return `<div class="wf-group">${S.answers.map((x, i) => msg("risklens", w, `<div class="wf-bubble a" style="--i:${i}"><span class="wf-qref">Q${i + 1} · ${esc(x.q)}</span>${esc(x.a)}<span class="wf-src">${esc(x.source)}</span></div>`, i ? "cont" : "")).join("")}</div>`;
    if (step === "mail") { const m = S.mail; return msg("risklens", w, `<div class="wf-mail sent"><div class="wf-mail-top"><span class="wf-env">✉</span><div><div class="wf-mail-k">Consolidated mail · to ${esc(m.to.name)}, ${esc(m.to.org)}</div><div class="wf-mail-addr mono">${esc(m.to.email)}${m.cc.length ? " · cc " + esc(m.cc.join(", ")) : ""}</div></div><span class="wf-stamp">Sent</span></div>
      <div class="wf-mail-subj">${esc(m.subject)}</div>${pre(m.body)}</div>`); }
    if (step === "reply") { const r = S.reply; return msg("stakeholder", w, `<div class="wf-mail reply"><div class="wf-mail-top"><span class="wf-env">↩</span><div><div class="wf-mail-k">From ${esc(r.from.name)}, ${esc(r.from.org)}</div><div class="wf-mail-addr mono">${esc(r.from.email)}</div></div></div>
      <div class="wf-mail-subj">${esc(r.subject)}</div>${pre(r.body)}</div>`); }
    if (step === "understand") { const u = S.understand, r = S.reply; return msg("risklens", w, `<div class="wf-read"><div class="wf-read-k">Reading the reply</div>
      <p class="wf-read-txt">${r.segments.map((g, i) => g.kind ? `<mark class="${g.kind}" style="--i:${i}"><em>${g.kind}</em>${esc(g.text)}</mark>` : esc(g.text)).join("")}</p>
      <ul class="wf-checks">${u.checks.map((c, i) => `<li style="--i:${i}"><span class="ck">✓</span><b>${esc(c.label)}</b><span>${esc(c.detail)}</span></li>`).join("")}</ul>
      <div class="wf-plan"><span>Decision</span><b>${esc(u.plan)}</b></div></div>`); }
    if (step === "deploy" && S.deploy) { const d = S.deploy; return msg("risklens", w, `<div class="wf-deploy"><div class="wf-deploy-top"><span class="wf-deploy-k">Action deployed</span><span class="wf-stamp big">Deployed</span></div>
      <div class="wf-deploy-grid"><div class="im-flow"><span class="im-score" style="--c:${BAND_COLOR[d.band_before]}">${d.risk_before.toFixed(0)}<small>${d.band_before}</small></span><span class="im-arrow"><i></i></span><span class="im-score after" style="--c:${BAND_COLOR[d.band_after]}">${d.risk_after.toFixed(0)}<small>${d.band_after}</small></span></div>
        <dl class="wf-dl"><dt>${d.kind === "alternative" ? "Applied" : "Recorded"}</dt><dd>${esc(d.title)}</dd>${d.changes.length ? `<dt>Changes</dt><dd>${esc(d.changes.join(" · "))}</dd>` : ""}<dt>ETA</dt><dd>${esc(fmtDate(d.eta_before))}${d.eta_after !== d.eta_before ? ` → ${esc(fmtDate(d.eta_after))}` : " (unchanged)"}</dd><dt>Expected loss</dt><dd>${fmtUSD(d.loss_before)} → <b class="good">${fmtUSD(d.loss_after)}</b></dd></dl></div>
      <p class="wf-deploy-sum">${esc(d.summary)} ${d.rescored ? "" : "The estimate uses the action's expected risk reduction."}</p>
      <div class="wf-deploy-links"><a href="#" class="btn btn-sm btn-secondary" data-open="${esc(w.consignment_id)}">Open ${esc(w.consignment_id)}</a><a href="#actions" class="btn btn-sm btn-ghost">Back to actions</a></div></div>`); }
    return "";
  }
  function renderWorkflow(w, opts = {}) {
    $("#wf-parties").innerHTML = ["risklens", "warehouse", "stakeholder"].map((k) => `<span class="wf-party">${avatar(k, w)}<span><b>${esc(who(k, w))}</b><small>${k === "stakeholder" ? esc(w.stakeholder.org) : k === "risklens" ? "answers from the data" : "asks what it needs"}</small></span></span>`).join("");
    $("#wf-status").textContent = `${w.consignment_id} · ${w.action} · risk ${w.risk_before.toFixed(0)}`;
    const t = $("#wf-thread"), steps = revealed(w);
    if (opts.just) { t.querySelector(".wf-typing")?.remove(); t.insertAdjacentHTML("beforeend", `<div class="wf-step new">${stepHTML(opts.just, w)}</div>`); }
    else t.innerHTML = steps.map((s) => `<div class="wf-step ${opts.animate ? "new" : ""}">${stepHTML(s, w)}</div>`).join("");
    t.scrollTo({ top: t.scrollHeight, behavior: opts.just ? "smooth" : "auto" });
    railRender(w, null); wfRuns();
  }
  function railRender(w, active) {
    const done = new Set(revealed(w));
    $("#wf-rail-tag").textContent = w.status === "done" ? "complete" : active ? "running" : `${done.size} of 7 steps`;
    $("#wf-steps").innerHTML = w.phases.map(([key, title, subs]) => `<li class="wf-phase ${subs.every((s) => done.has(s)) ? "done" : subs.some((s) => done.has(s) || s === active) ? "on" : ""}">
      <div class="wf-phase-h"><span class="wf-phase-n">${subs.every((s) => done.has(s)) ? "✓" : ""}</span><b>${esc(title)}</b></div>
      <ol>${subs.map((s) => `<li class="${done.has(s) ? "done" : s === active ? "active" : ""}"><span class="wf-node"></span>${esc(STEP_LABEL[s])}</li>`).join("")}</ol></li>`).join("");
    const d = w.steps.deploy;
    $("#wf-outcome").innerHTML = d ? `<div class="wf-out"><span class="wf-out-k">Outcome</span><b>${d.risk_before.toFixed(0)} → ${d.risk_after.toFixed(0)}</b><span>${esc(d.title)}</span><small>${esc(fmtWhen(w.deployed_at))}</small></div>` : "";
  }
  $("#wf-run").addEventListener("click", () => { const k = $("#wf-action").value; if (k) startWorkflow(k); });
  $("#wf-runs").addEventListener("click", (e) => { const b = e.target.closest("[data-wf]"); if (!b || WF.playing) return; const r = WF.runs.find((x) => x.id === b.dataset.wf); if (r) { WF.current = r; renderWorkflow(r); } });

  // ---------- what-if (one page: CSV on top, a compact single check below) ----------
  const WI_FIELDS = [
    ["product_category", "Category", "select", opt(CATEGORIES)],
    ["origin_port", "From", "select", opt(PORT_LIST)], ["destination_port", "To", "select", opt(PORT_LIST)],
    ["mode", "Mode", "select", opt(MODES)], ["weight_t", "Weight (tonnes)", "number", { min: 0, step: "any" }],
    ["reliability_score", "Carrier reliability (0–1)", "number", { min: 0, max: 1, step: "any" }],
    ["geopolitical_risk_index", "Geopolitical risk (0–100)", "number", { min: 0, max: 100, step: "any" }],
    ["weather_condition", "Weather", "select", opt(WEATHER_LIST)],
    ["fuel_price_index", "Fuel price index (1.2–4.5)", "number", { min: 0, max: 10, step: "any" }],
  ];
  const WI_DEFAULTS = { product_category: "Electronics", origin_port: "Shanghai", destination_port: "Rotterdam", mode: "Sea", weight_t: 180, reliability_score: 0.78, geopolitical_risk_index: 55, weather_condition: "Storm", fuel_price_index: 3.1 };
  function wiRecord(form) {
    const o = formToRecord(form);
    o.consignment_id = "What-if";
    o.cargo = o.product_category ? `${o.product_category} shipment` : "Planned shipment";
    return o;
  }
  function wiResultHTML(r, label) {
    const c = BAND_COLOR[r.risk_band], best = r.best_alternative;
    const drivers = r.factors.filter((f) => f.contribution > 0).slice(0, 3);
    const maxC = Math.max(0.05, ...drivers.map((f) => f.contribution));
    const bandText = { low: "Low risk: normal tracking", elevated: "Elevated: watch closely", high: "High: act before it slips" }[r.risk_band];
    return `<div class="wr">
      <div class="wr-top">${label ? `<span class="eyebrow">${esc(label)}</span>` : ""}</div>
      <div class="wr-head">
        <div class="sh-dial wr-dial" style="--c:${c};--target:${r.risk_score}"><div class="sh-dial-in"><b>${r.risk_score.toFixed(1)}</b><span>Disruption risk</span></div></div>
        <div class="wr-kpis"><div class="wr-band">${chip(r.risk_band)}<span>${bandText}</span></div>
          <div class="wr-nums"><div><span>Expected loss</span><b class="bad">${fmtUSD(r.expected_loss_usd)}</b></div><div><span>Cargo value</span><b>${fmtUSD(r.cargo_value_usd)}</b></div></div></div>
      </div>
      <div class="wr-sec">What drives the risk</div>
      ${drivers.length ? drivers.map((f) => `<div class="wr-drv"><span>${esc(f.label)}</span><i><em style="--w:${(f.contribution / maxC) * 100}%"></em></i><b>${f.value.toFixed(2)}</b></div>`).join("") : `<div class="muted small">No parameter is pushing the risk up.</div>`}
      <div class="wr-best ${best ? "yes" : ""}">${best ? `<span class="wb-k">Best option</span><b>${esc(best.title)}</b><span>Risk ${r.risk_score.toFixed(0)} → ${best.risk_score.toFixed(0)} · saves ${fmtUSD(best.net_benefit_usd)}</span>` : `<span class="wb-k">Best option</span><b>Keep the current plan</b><span>No alternative saves more than it costs</span>`}</div>
    </div>`;
  }
  function initWhatIf() {
    const f = $("#score-form");
    f.innerHTML = WI_FIELDS.map((x) => fieldHTML(x, WI_DEFAULTS)).join("") + `<div class="wi-actions"><button type="submit" class="btn btn-primary">Assess risk</button><button type="button" class="btn btn-secondary" id="btn-save-form">Add to consignments</button><span class="muted small" id="form-status"></span></div>`;
    const run = async () => { try { const res = await api("/api/score", { body: wiRecord(f) }); $("#score-result").innerHTML = wiResultHTML(res); clearErrors(f); $("#form-status").textContent = ""; } catch (e) { showErrors(f, e); } };
    f.addEventListener("submit", (e) => { e.preventDefault(); run(); });
    f.addEventListener("input", debounce(run, 400));
    $("#btn-save-form").addEventListener("click", async () => {
      try { const res = await api("/api/consignments", { method: "POST", body: wiRecord(f) }); await refresh(); toast(`Added ${res.consignment_id} to consignments`); $("#form-status").innerHTML = `Saved as <span class="mono">${esc(res.consignment_id)}</span>`; }
      catch (e) { showErrors(f, e); }
    });
    run();
  }
  $("#btn-new").addEventListener("click", () => { location.hash = "whatif"; setTimeout(() => $("#score-form [name=cargo]")?.focus(), 50); });

  // ---------- csv ----------
  const dz = $("#dropzone"), fi = $("#csv-input");
  $("#csv-browse").addEventListener("click", () => fi.click());
  dz.addEventListener("click", (e) => { if (!e.target.closest("button")) fi.click(); });
  fi.addEventListener("change", () => { if (fi.files[0]) uploadCsv(fi.files[0]); fi.value = ""; });
  ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
  dz.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) uploadCsv(f); });
  async function uploadCsv(file) {
    const out = $("#csv-result"); out.innerHTML = `<div class="csv-bar"><span class="muted">Checking ${esc(file.name)}…</span></div>`;
    const fd = new FormData(); fd.append("file", file);
    try {
      const r = await api("/api/score/csv", { method: "POST", body: fd });
      const fileErr = r.errors.filter((e) => e.row === null), rowErrs = r.errors.filter((e) => e.row !== null);
      if (fileErr.length) { out.innerHTML = fileErr.map((e) => `<div class="alert error">${esc(e.message)}</div>`).join(""); return; }
      const s = r.summary;
      let html = `<div class="csv-bar"><span class="csv-file">${esc(r.filename)}</span><span>Scored <b>${r.rows_scored}</b> of ${r.rows_total}</span>`;
      if (s) html += `<span>${chip("high")} ${s.bands.high}</span><span>${chip("elevated")} ${s.bands.elevated}</span><span>${chip("low")} ${s.bands.low}</span><span class="muted">Expected loss ${fmtUSD(s.expected_loss_usd)}</span>`;
      if (r.outcome) html += `<span class="csv-outcome" title="The file includes Disruption_Occurred, so predictions are checked against what happened">Matched the actual outcome on <b>${Math.round(r.outcome.agreement * 100)}%</b> of rows${r.outcome.caught != null ? ` · caught ${Math.round(r.outcome.caught * 100)}% of ${r.outcome.disrupted.toLocaleString()} disruptions` : ""}</span>`;
      if (rowErrs.length) html += `<span class="csv-warn" title="${esc(rowErrs.map((e) => `Line ${e.row}: ${e.message}`).join("\n"))}">⚠ ${rowErrs.length} row problem${rowErrs.length > 1 ? "s" : ""}</span>`;
      html += `<span class="csv-btns">${r.results.length ? `<button class="btn btn-secondary btn-sm" id="csv-add">Add to consignments</button><button class="btn btn-secondary btn-sm" id="csv-download">Download results</button>` : ""}<button class="btn btn-ghost btn-sm" id="csv-clear">Clear</button></span></div>`;
      html += `<div class="csv-list">`;
      html += rowErrs.map((e) => `<div class="csv-row err"><span class="mono">Line ${e.row}</span><span class="mono">${esc(e.field)}</span><span>${esc(e.message)}</span></div>`).join("");
      html += r.results.map((x, i) => `<div class="csv-row" data-csv="${i}" role="button" tabindex="0"><span class="mono cid">${esc(x.consignment_id || x.supplier_name || "—")}</span><span>${route(x)}</span><span class="csv-score" style="color:${BAND_COLOR[x.risk_band]}">${x.risk_score.toFixed(0)}</span>${chip(x.risk_band)}<span class="muted">${x.top_driver ? esc(x.top_driver.label) : "—"}</span><span class="num">${fmtUSD(x.expected_loss_usd)}</span></div>`).join("");
      html += `</div>`;
      out.innerHTML = html;
      $("#csv-clear").addEventListener("click", () => { out.innerHTML = ""; });
      $("#csv-add")?.addEventListener("click", async () => { const a = await api("/api/consignments/import", { body: { records: r.records } }); await refresh(); toast(a.added ? `Added ${a.added} consignment(s)` : "Nothing added: those consignment IDs already exist"); });
      $("#csv-download")?.addEventListener("click", () => {
        const cols = ["consignment_id", "route", "risk_score", "risk_band", "expected_loss_usd", "main_driver", "best_alternative"];
        const lines = [cols.join(",")].concat(r.results.map((x) => [x.consignment_id || "", routeText(x), x.risk_score, x.risk_band, x.expected_loss_usd, x.top_driver ? x.top_driver.label : "", x.best_alternative ? x.best_alternative.title : ""].map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")));
        const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" })); a.download = "risklens_batch_results.csv"; a.click();
      });
      const pick = (el) => { const x = r.results[+el.dataset.csv]; $$("#csv-result .csv-row").forEach((q) => q.classList.toggle("on", q === el)); $("#score-result").innerHTML = wiResultHTML(x, `From ${r.filename} · ${x.consignment_id || x.supplier_name || ""}`); };
      out.onclick = (e) => { const el = e.target.closest("[data-csv]"); if (el) pick(el); };
      out.onkeydown = (e) => { const el = e.target.closest("[data-csv]"); if (el && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); pick(el); } };
    } catch (e) { out.innerHTML = `<div class="alert error">${esc(e.message)}</div>`; }
  }

  // ---------- global ----------
  $("#btn-reset").addEventListener("click", async () => { if (!confirm("Restore the original demo consignments? Your edits will be discarded.")) return; await api("/api/consignments/reset", { method: "POST" }); await refresh(); toast("Demo data restored"); });

  (async () => {
    try { await loadAll(); initWhatIf(); show(location.hash.slice(1) || "overview"); }
    catch (e) { $("#model-pill").innerHTML = `<span class="dot" style="background:#B91C1C;box-shadow:none"></span><span>Service unavailable</span>`; $("#view-overview").innerHTML = `<div class="card"><div class="alert error">Could not reach the RiskLens service: ${esc(e.message)}. Start it with ./run.sh</div></div>`; }
  })();
})();
