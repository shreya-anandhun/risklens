/* RiskLens portal — vanilla JS, talks to the FastAPI backend. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const state = { meta: null, overview: null, suppliers: [], sort: { key: "risk_score", dir: -1 }, band: "all", q: "", heatN: 12, charts: {}, drawerId: null, lastCsv: null };
  const REGIONS = ["South Asia", "Southeast Asia", "East Asia", "Middle East", "Europe", "Africa", "North America", "Latin America"];
  const CATEGORIES = ["Electronics", "Raw Materials", "Machinery", "Chemicals", "Packaging"];
  const BAND_COLOR = { low: "#15803D", elevated: "#B45309", high: "#B91C1C" };

  // ---------- utils ----------
  const fmtUSD = (v) => { v = +v || 0; const a = Math.abs(v); const s = v < 0 ? "-" : ""; if (a >= 1e9) return s + "$" + (a / 1e9).toFixed(2) + "B"; if (a >= 1e6) return s + "$" + (a / 1e6).toFixed(a >= 1e7 ? 1 : 2) + "M"; if (a >= 1e3) return s + "$" + (a / 1e3).toFixed(0) + "K"; return s + "$" + a.toFixed(0); };
  const fmtPct = (v, d = 1) => (+v).toFixed(d) + "%";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const title = (s) => String(s || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
  const toast = (msg) => { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(t._t); t._t = setTimeout(() => t.classList.remove("show"), 2600); };
  const heatColor = (v) => { // 0 → light grey, .5 → amber, 1 → red
    const lerp = (a, b, t) => a + (b - a) * t; const c = (h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
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

  // ---------- navigation ----------
  const PAGES = { overview: ["Overview", "Portfolio-wide disruption risk, 7-day horizon"], suppliers: ["Suppliers", "Editable supplier portfolio. Click a row to inspect, adjust inputs and re-score."], analyze: ["Analyze", "Score a single supplier or a CSV batch against the trained model"], methodology: ["Methodology", "How the parameters, model and rules fit together"] };
  function show(view) {
    $$(".nav-item").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + view));
    $("#page-title").textContent = PAGES[view][0]; $("#page-sub").textContent = PAGES[view][1]; window.scrollTo(0, 0);
    if (view === "overview") renderOverview();
    if (view === "suppliers") renderSuppliers();
    if (view === "methodology") renderMethodology();
  }
  window.addEventListener("hashchange", () => show(location.hash.slice(1) || "overview"));

  // ---------- data ----------
  async function loadAll() {
    const [meta, overview] = await Promise.all([api("/api/meta"), api("/api/overview")]);
    state.meta = meta; state.overview = overview; state.suppliers = overview.suppliers;
    const m = meta.model;
    $("#model-pill").innerHTML = `<span class="dot"></span><span>XGBoost · AUC ${m.metrics.auc_roc.toFixed(2)}</span>`;
    $("#sidebar-meta").innerHTML = `${m.n_suppliers} suppliers · ${meta.data.disruptions} disruption events<br>Signals ${esc(meta.data.window)}<br>Trained ${m.trained_at.slice(0, 10)}`;
  }
  async function refreshOverview() { state.overview = await api("/api/overview"); state.suppliers = state.overview.suppliers; }

  // ---------- overview ----------
  function renderOverview() {
    const o = state.overview, s = o.summary, m = state.meta.model;
    const kpis = [
      ["Supply chain at risk", fmtPct(s.pct_spend_at_risk), `${s.pct_suppliers_at_risk}% of suppliers · ${fmtUSD(s.spend_at_risk_usd)} of ${fmtUSD(s.total_spend_usd)} annual spend`, s.pct_spend_at_risk > 40 ? "high" : s.pct_spend_at_risk > 20 ? "elevated" : "low"],
      ["High-risk suppliers", s.bands.high, `${s.bands.elevated} elevated · ${s.bands.low} low · ${s.flagged} flagged by model threshold`, s.bands.high > 0 ? "high" : "low"],
      ["Expected loss, next 7 days", fmtUSD(s.expected_loss_usd), "Σ probability × estimated disruption cost", ""],
      ["Spend-weighted risk", s.spend_weighted_risk.toFixed(1), `Simple average ${s.avg_risk_score.toFixed(1)} · back-test caught ${o.catch_rate}% of disruptions in advance`, ""],
    ];
    $("#kpi-grid").innerHTML = kpis.map(([l, v, sub, c]) => `<div class="kpi"><div class="kpi-label">${l}</div><div class="kpi-value ${c}">${v}</div><div class="kpi-sub">${sub}</div></div>`).join("");

    const total = s.n || 1;
    $("#band-bars").innerHTML = ["high", "elevated", "low"].map((b) => `<div class="hbar"><span>${chip(b)}</span><span class="track"><span class="fill" style="width:${(s.bands[b] / total) * 100}%;background:${BAND_COLOR[b]}"></span></span><span class="n">${s.bands[b]}</span></div>`).join("");
    const reasons = Object.entries(o.reasons).sort((a, b) => b[1] - a[1]); const rmax = reasons[0]?.[1] || 1;
    $("#reason-bars").innerHTML = reasons.map(([k, v]) => `<div class="hbar"><span title="${esc(k)}" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(k)}</span><span class="track"><span class="fill" style="width:${(v / rmax) * 100}%"></span></span><span class="n">${v}</span></div>`).join("");

    timelineChart(o.timeline, m.risk_bands);
    renderHeatmap();
    $("#top-actions").innerHTML = o.top_actions.length ? o.top_actions.map((a) => `<div class="action"><div><div class="a-title">${esc(a.action)}</div><div class="a-sub"><a href="#" data-open="${a.supplier_id}">${esc(a.supplier_name)}</a> · ${chip(a.risk_band)} ${a.risk_score.toFixed(0)} · ${esc(a.trigger)}</div></div><div class="a-meta">Net benefit<b>${fmtUSD(a.net_benefit_usd)}</b>${esc(a.timeline)}</div></div>`).join("") : `<div class="empty">No mitigations triggered.</div>`;
    $("#catch-rate").textContent = `Model flagged ${o.catch_rate}% of historical disruptions as Elevated or High in the 7 days before they occurred.`;
    $("#recent-disruptions").innerHTML = `<table class="table"><thead><tr><th>Date</th><th>Supplier</th><th>Cause</th><th class="num">Cost</th><th>Flagged</th></tr></thead><tbody>${o.recent_disruptions.map((d) => `<tr><td class="mono">${d.date}</td><td>${esc(d.supplier_name)}<div class="sub">${esc(d.region)}</div></td><td>${esc(d.disruption_reason)}</td><td class="num">${fmtUSD(d.recovery_cost_usd)}</td><td>${d.flagged_in_advance ? '<span class="chip low">yes</span>' : '<span class="chip high">missed</span>'}</td></tr>`).join("")}</tbody></table>`;
  }
  function renderHeatmap() {
    const feats = state.meta.model.features; const rows = [...state.suppliers].sort((a, b) => b.risk_score - a.risk_score).slice(0, state.heatN);
    const h = $("#heatmap"); h.className = "heat"; h.style.gridTemplateColumns = `170px repeat(${feats.length}, 1fr) 64px`;
    let html = `<div class="hh" style="text-align:left">Supplier</div>` + feats.map((f) => `<div class="hh">${esc(f.label)}</div>`).join("") + `<div class="hh">Score</div>`;
    for (const r of rows) {
      const byKey = Object.fromEntries(r.factors.map((f) => [f.key, f.value]));
      html += `<div class="hl" data-open="${r.supplier_id}" title="${esc(r.supplier_name)}">${esc(r.supplier_name)}</div>`;
      html += feats.map((f) => { const v = byKey[f.key]; return `<div class="hc" style="background:${heatColor(v)};color:${textOn(v)}">${v.toFixed(2)}</div>`; }).join("");
      html += `<div class="hs" style="background:${BAND_COLOR[r.risk_band]}1A;color:${BAND_COLOR[r.risk_band]}">${r.risk_score.toFixed(0)}</div>`;
    }
    h.innerHTML = html;
    if (!$("#heatmap + .legend-scale")) h.insertAdjacentHTML("afterend", `<div class="legend-scale"><span>0</span><span class="bar"></span><span>1 (riskiest)</span></div>`);
  }
  function timelineChart(tl, bands) {
    const ctx = $("#chart-timeline"); state.charts.tl?.destroy();
    state.charts.tl = new Chart(ctx, { data: {
      labels: tl.map((d) => d.date),
      datasets: [
        { type: "line", label: "Avg. predicted risk (%)", data: tl.map((d) => d.avg_risk), borderColor: "#0F4C81", backgroundColor: "rgba(15,76,129,.08)", fill: true, tension: .3, pointRadius: 0, borderWidth: 2, yAxisID: "y" },
        { type: "line", label: "Max supplier risk (%)", data: tl.map((d) => d.max_risk), borderColor: "#B45309", borderDash: [4, 3], pointRadius: 0, borderWidth: 1.5, yAxisID: "y" },
        { type: "bar", label: "Disruptions", data: tl.map((d) => d.disruptions), backgroundColor: "rgba(185,28,28,.55)", yAxisID: "y1", barPercentage: .9 },
      ] },
      options: { responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false }, plugins: { legend: { position: "bottom", labels: { boxWidth: 10, font: { size: 11 } } } },
        scales: { x: { ticks: { maxTicksLimit: 8, font: { size: 11 } }, grid: { display: false } }, y: { min: 0, max: 100, title: { display: true, text: "Risk %" }, ticks: { font: { size: 11 } } }, y1: { position: "right", min: 0, suggestedMax: 6, grid: { display: false }, title: { display: true, text: "Events / day" }, ticks: { stepSize: 1, font: { size: 11 } } } } } });
  }
  $("#heat-limit").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; $$("#heat-limit button").forEach((x) => x.classList.toggle("active", x === b)); state.heatN = +b.dataset.n; renderHeatmap(); });

  // ---------- suppliers ----------
  function filteredSuppliers() {
    const q = state.q.toLowerCase(); const { key, dir } = state.sort;
    return state.suppliers.filter((r) => (state.band === "all" || r.risk_band === state.band) && (!q || [r.supplier_name, r.region, r.product_category, r.supplier_id].join(" ").toLowerCase().includes(q)))
      .sort((a, b) => { const x = a[key], y = b[key]; return (typeof x === "number" ? x - y : String(x ?? "").localeCompare(String(y ?? ""))) * dir; });
  }
  function renderSuppliers() {
    const rows = filteredSuppliers();
    $("#sup-count").textContent = `${rows.length} of ${state.suppliers.length} suppliers`;
    $("#sup-table tbody").innerHTML = rows.map((r) => `<tr class="clickable" data-open="${r.supplier_id}"><td><div class="name">${esc(r.supplier_name)}</div><div class="sub mono">${esc(r.supplier_id)}</div></td><td>${esc(r.region || "—")}</td><td>${esc(r.product_category || "—")}</td><td class="num">${fmtUSD(r.annual_spend_usd)}</td><td class="num">${scoreBar(r)}</td><td>${chip(r.risk_band)}${r.flagged ? ' <span class="chip flag">flag</span>' : ""}</td><td>${r.top_driver ? `${esc(r.top_driver.label)} <span class="tag">${r.top_driver.value.toFixed(2)}</span>` : '<span class="tag">none — all factors protective</span>'}</td><td class="num">${fmtUSD(r.expected_loss_usd)}</td><td class="num">${r.recommendations[0].id === "maintain" ? '<span class="tag">monitor</span>' : r.recommendations.length}</td></tr>`).join("") || `<tr><td colspan="9" class="empty">No suppliers match.</td></tr>`;
    $$("#sup-table th[data-sort]").forEach((th) => { th.textContent = th.textContent.replace(/ [↑↓]$/, ""); if (th.dataset.sort === state.sort.key) th.textContent += state.sort.dir > 0 ? " ↑" : " ↓"; });
  }
  $("#sup-search").addEventListener("input", (e) => { state.q = e.target.value; renderSuppliers(); });
  $("#sup-band-filter").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; $$("#sup-band-filter button").forEach((x) => x.classList.toggle("active", x === b)); state.band = b.dataset.band; renderSuppliers(); });
  $("#sup-table thead").addEventListener("click", (e) => { const th = e.target.closest("th[data-sort]"); if (!th) return; const k = th.dataset.sort; state.sort = { key: k, dir: state.sort.key === k ? -state.sort.dir : (k === "supplier_name" || k === "region" || k === "product_category" ? 1 : -1) }; renderSuppliers(); });

  // ---------- drawer (inspect + edit) ----------
  const FIELDS = [
    ["Operational"], ["lead_time_days", "Lead time (days)", "number", { min: 1, max: 365 }], ["lead_time_std_days", "Lead time std dev (days)", "number", { min: 0, step: "any" }], ["reliability_score", "On-time delivery rate (0–1)", "number", { min: 0, max: 1, step: "any" }], ["single_source", "Single-sourced", "select", ["0:No", "1:Yes"]], ["average_cost_per_unit", "Unit cost (USD)", "number", { min: 0, step: "any" }], ["annual_volume_units", "Annual volume (units)", "number", { min: 0 }],
    ["External signals"], ["geopolitical_risk_index", "Geopolitical risk index (0–100)", "number", { min: 0, max: 100, step: "any" }], ["port_congestion_index", "Port congestion index (0–100)", "number", { min: 0, max: 100, step: "any" }], ["weather_risk_index", "Weather risk index (0–100)", "number", { min: 0, max: 100, step: "any" }], ["weather_risk_level", "Weather risk level", "select", ["low:Low", "medium:Medium", "high:High"]], ["price_swing_pct", "Commodity price swing, 30d (%)", "number", { min: 0, max: 100, step: "any" }],
    ["History"], ["days_since_last_disruption", "Days since last disruption", "number", { min: 0, placeholder: "none on record" }],
  ];
  async function openDrawer(sid) {
    state.drawerId = sid;
    const d = $("#drawer"); d.classList.add("open"); d.setAttribute("aria-hidden", "false"); $("#drawer-backdrop").classList.add("open");
    $("#drawer-body").innerHTML = `<div class="empty">Loading…</div>`;
    try { const r = await api(`/api/suppliers/${sid}`); renderDrawer(r); } catch (e) { $("#drawer-body").innerHTML = `<div class="alert error">${esc(e.message)}</div>`; }
  }
  function closeDrawer() { $("#drawer").classList.remove("open"); $("#drawer").setAttribute("aria-hidden", "true"); $("#drawer-backdrop").classList.remove("open"); state.drawerId = null; }
  $("#drawer-close").addEventListener("click", closeDrawer); $("#drawer-backdrop").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => e.key === "Escape" && closeDrawer());

  function resultHTML(r, { compact = false } = {}) {
    const color = BAND_COLOR[r.risk_band]; const maxAbs = Math.max(0.05, ...r.factors.map((f) => Math.abs(f.contribution)));
    return `
      <div class="score-hero">
        <div class="dial" style="background:conic-gradient(${color} ${r.risk_score * 3.6}deg, #EEF0F3 0)"><div class="dv"><b style="color:${color}">${r.risk_score.toFixed(1)}</b><span>7-day risk</span></div></div>
        <div class="hero-stats">
          <div>Band<b>${chip(r.risk_band)}${r.flagged ? ' <span class="chip flag">flagged</span>' : ""}</b></div>
          <div>Model confidence<b>${r.confidence.toFixed(0)}%</b></div>
          <div>Weighted index<b>${r.composite_index.toFixed(1)} / 100</b></div>
          <div>Annual spend<b>${fmtUSD(r.annual_spend_usd)}</b></div>
          <div>Est. disruption cost<b>${fmtUSD(r.estimated_disruption_cost_usd)}</b></div>
          <div>Expected loss (7d)<b style="color:${r.expected_loss_usd > 0 ? "var(--high)" : "inherit"}">${fmtUSD(r.expected_loss_usd)}</b></div>
        </div>
      </div>
      <div>
        <div class="section-title"><span>Parameter scorecard</span><span class="tag">contribution = SHAP value in log-odds</span></div>
        <table class="factor-table"><thead><tr><th>Parameter</th><th style="width:26%">Risk factor (0–1)</th><th class="num">Weight</th><th style="width:22%">Model contribution</th><th class="num">Δ</th></tr></thead><tbody>
        ${r.factors.map((f) => `<tr><td><div style="font-weight:500">${esc(f.label)}</div><div class="tag">${esc(inputSummary(f.key, r.inputs))}</div></td><td><div class="ftrack"><div class="ffill" style="width:${f.value * 100}%;background:${heatColor(f.value)}"></div></div><div class="tag">${f.value.toFixed(2)}</div></td><td class="num">${(f.weight * 100).toFixed(0)}%</td><td><div class="contrib"><div class="l">${f.contribution < 0 ? `<span style="width:${(Math.abs(f.contribution) / maxAbs) * 100}%"></span>` : ""}</div><div class="r">${f.contribution > 0 ? `<span style="width:${(f.contribution / maxAbs) * 100}%"></span>` : ""}</div></div></td><td class="contrib-val ${f.contribution > 0 ? "pos" : "neg"}">${f.contribution > 0 ? "+" : ""}${f.contribution.toFixed(2)}</td></tr>`).join("")}
        </tbody></table>
      </div>
      <div>
        <div class="section-title"><span>Recommended mitigations</span><span class="tag">residual risk after all actions ≈ ${r.residual_risk_score.toFixed(1)}</span></div>
        <div class="action-list">${r.recommendations.map((a) => `<div class="action rec"><div class="a-title">${esc(a.action)} <span class="cost-band">${esc(a.cost_band)} cost</span></div><div class="a-sub">${esc(a.rationale)}</div><div class="a-cost"><span>Trigger <b>${esc(a.trigger)}</b></span><span>Timeline <b>${esc(a.timeline)}</b></span><span>Cost <b>${fmtUSD(a.cost_usd)}</b></span><span>Loss avoided <b>${fmtUSD(a.benefit_usd)}</b></span><span>Net <b style="color:${a.net_benefit_usd >= 0 ? "var(--low)" : "var(--high)"}">${fmtUSD(a.net_benefit_usd)}</b></span><span>Risk reduction <b>${(a.risk_reduction * 100).toFixed(0)}%</b></span></div></div>`).join("")}</div>
      </div>`;
  }
  function inputSummary(key, i) {
    const n = (v, d = 1) => (v == null || v === "" ? "—" : (+v).toFixed(d));
    switch (key) {
      case "reliability_risk": return `on-time rate ${n(i.reliability_score, 2)}`;
      case "lead_time_risk": return `${n(i.lead_time_days, 0)} days`;
      case "lead_time_variability": return `σ ${n(i.lead_time_std_days)} days on ${n(i.lead_time_days, 0)}`;
      case "geopolitical_risk": return `index ${n(i.geopolitical_risk_index)}${i.port_congestion_index != null ? ` · port ${n(i.port_congestion_index)}` : ""}`;
      case "weather_risk": return i.weather_risk_index != null ? `index ${n(i.weather_risk_index)}` : `level ${i.weather_risk_level || "—"}`;
      case "price_volatility": return `${n(i.price_swing_pct)}% swing / 30d`;
      case "disruption_recency": return i.days_since_last_disruption == null || i.days_since_last_disruption >= 999 ? "no disruption on record" : `${n(i.days_since_last_disruption, 0)} days ago`;
    }
    return "";
  }
  function fieldHTML([key, label, type, opts], rec) {
    if (!label) return `<div class="form-section span-2">${key}</div>`;
    const v = rec[key] ?? "";
    if (type === "select") return `<label>${label}<select name="${key}" class="input">${opts.map((o) => { const [val, txt] = o.split(":"); return `<option value="${val}" ${String(v) === val ? "selected" : ""}>${txt}</option>`; }).join("")}</select></label>`;
    return `<label>${label}<input name="${key}" type="number" class="input" value="${v === null ? "" : v}" ${Object.entries(opts).map(([k, x]) => `${k}="${x}"`).join(" ")}></label>`;
  }
  function renderDrawer(r) {
    $("#drawer-eyebrow").innerHTML = `${esc(r.supplier_id)} · ${esc(r.region || "")} · ${esc(r.product_category || "")}`;
    $("#drawer-title").textContent = r.supplier_name;
    const rec = r.record;
    $("#drawer-body").innerHTML = `
      <div id="drawer-result">${resultHTML(r)}</div>
      <div>
        <div class="section-title"><span>Risk history (back-test)</span><span class="tag">predicted 7-day risk vs. actual events</span></div>
        <div class="chart-wrap" style="height:180px"><canvas id="chart-history"></canvas></div>
      </div>
      <div>
        <div class="section-title"><span>Edit inputs</span><span class="tag">score re-computes live · Save to persist</span></div>
        <form id="edit-form" class="form-grid">
          <label class="span-2">Supplier name<input name="supplier_name" class="input" value="${esc(rec.supplier_name)}"></label>
          <label>Region<select name="region" class="input">${REGIONS.map((x) => `<option ${x === rec.region ? "selected" : ""}>${x}</option>`).join("")}</select></label>
          <label>Category<select name="product_category" class="input">${CATEGORIES.map((x) => `<option ${x === rec.product_category ? "selected" : ""}>${x}</option>`).join("")}</select></label>
          ${FIELDS.map((f) => fieldHTML(f, rec)).join("")}
          <div class="span-2 form-actions"><button type="submit" class="btn btn-primary">Save changes</button><button type="button" class="btn btn-danger" id="btn-delete">Delete supplier</button><span class="muted" id="edit-status"></span></div>
        </form>
      </div>`;
    historyChart(r.history);
    const form = $("#edit-form");
    const live = debounce(async () => {
      const body = formToRecord(form); $("#edit-status").textContent = "Re-scoring…";
      try { const res = await api("/api/score", { body }); $("#drawer-result").innerHTML = resultHTML(res); $("#edit-status").textContent = "Unsaved changes"; clearErrors(form); }
      catch (e) { $("#edit-status").textContent = ""; showErrors(form, e); }
    }, 350);
    form.addEventListener("input", live);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try { const res = await api(`/api/suppliers/${r.supplier_id}`, { method: "PUT", body: formToRecord(form) }); $("#drawer-result").innerHTML = resultHTML(res); $("#drawer-title").textContent = res.supplier_name; $("#edit-status").textContent = "Saved"; await refreshOverview(); renderSuppliers(); if ($("#view-overview").classList.contains("active")) renderOverview(); toast(`Saved ${res.supplier_name} · risk ${res.risk_score.toFixed(1)}`); }
      catch (e) { showErrors(form, e); }
    });
    $("#btn-delete").addEventListener("click", async () => {
      if (!confirm(`Remove ${r.supplier_name} from the portfolio?`)) return;
      await api(`/api/suppliers/${r.supplier_id}`, { method: "DELETE" }); closeDrawer(); await refreshOverview(); renderSuppliers(); renderOverview(); toast(`Removed ${r.supplier_name}`);
    });
  }
  function historyChart(h) {
    const ctx = $("#chart-history"); if (!ctx) return; state.charts.h?.destroy();
    if (!h?.length) { ctx.parentElement.innerHTML = `<div class="empty small">No history for this supplier (added via portal).</div>`; return; }
    state.charts.h = new Chart(ctx, { data: { labels: h.map((d) => d.date), datasets: [
      { type: "line", label: "Predicted risk %", data: h.map((d) => d.pred), borderColor: "#0F4C81", backgroundColor: "rgba(15,76,129,.08)", fill: true, tension: .3, pointRadius: 0, borderWidth: 2 },
      { type: "bar", label: "Disruption", data: h.map((d) => (d.disrupted ? 100 : 0)), backgroundColor: "rgba(185,28,28,.45)", barPercentage: .6 } ] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom", labels: { boxWidth: 10, font: { size: 11 } } } }, scales: { x: { ticks: { maxTicksLimit: 6, font: { size: 10 } }, grid: { display: false } }, y: { min: 0, max: 100, ticks: { font: { size: 10 } } } } } });
  }
  function formToRecord(form) {
    const o = {}; new FormData(form).forEach((v, k) => { if (v !== "") o[k] = v; }); return o;
  }
  function clearErrors(form) { $$(".field-error", form).forEach((e) => e.remove()); $$(".invalid", form).forEach((e) => e.classList.remove("invalid")); }
  function showErrors(form, err) {
    clearErrors(form); const errs = err.detail?.errors || [{ field: null, message: err.message }];
    for (const e of errs) { const inp = e.field && form.querySelector(`[name="${e.field}"]`); if (inp) { inp.classList.add("invalid"); inp.closest("label")?.insertAdjacentHTML("beforeend", `<span class="field-error">${esc(e.message)}</span>`); } else toast(e.message); }
  }
  document.addEventListener("click", (e) => { const t = e.target.closest("[data-open]"); if (t) { e.preventDefault(); openDrawer(t.dataset.open); } });

  // ---------- analyze: single ----------
  function initForm() {
    const f = $("#score-form");
    f.region.innerHTML = REGIONS.map((x) => `<option>${x}</option>`).join(""); f.product_category.innerHTML = CATEGORIES.map((x) => `<option>${x}</option>`).join("");
    const run = async () => { try { const res = await api("/api/score", { body: formToRecord(f) }); $("#score-result").innerHTML = resultHTML(res); clearErrors(f); $("#form-status").textContent = ""; } catch (e) { showErrors(f, e); } };
    f.addEventListener("submit", (e) => { e.preventDefault(); run(); });
    f.addEventListener("input", debounce(run, 400));
    $("#btn-save-form").addEventListener("click", async () => {
      try { const res = await api("/api/suppliers", { method: "POST", body: formToRecord(f) }); await refreshOverview(); toast(`Added ${res.supplier_name} to portfolio`); $("#form-status").innerHTML = `Saved as <span class="mono">${esc(res.supplier_id)}</span>`; }
      catch (e) { showErrors(f, e); }
    });
    run();
  }
  $("#btn-new-supplier").addEventListener("click", () => { location.hash = "analyze"; $("#score-form").supplier_name.focus(); });

  // ---------- analyze: csv ----------
  const dz = $("#dropzone"), fi = $("#csv-input");
  $("#csv-browse").addEventListener("click", () => fi.click());
  fi.addEventListener("change", () => fi.files[0] && uploadCsv(fi.files[0]));
  ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
  dz.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) uploadCsv(f); });
  async function uploadCsv(file) {
    const out = $("#csv-result"); out.innerHTML = `<div class="alert ok">Analysing ${esc(file.name)}…</div>`;
    const fd = new FormData(); fd.append("file", file);
    try {
      const r = await api("/api/score/csv", { method: "POST", body: fd }); state.lastCsv = r;
      let html = "";
      if (r.errors.some((e) => e.row === null)) html += r.errors.map((e) => `<div class="alert error">${esc(e.message)}</div>`).join("");
      else html += `<div class="alert ${r.errors.length ? "warn" : "ok"}">Scored ${r.rows_scored} of ${r.rows_total} rows from ${esc(r.filename)}.${r.errors.length ? ` ${r.errors.length} row problem(s) listed below.` : ""}</div>`;
      html += r.warnings.map((w) => `<div class="alert warn">${esc(w)}</div>`).join("");
      if (r.errors.filter((e) => e.row !== null).length) html += `<div class="table-wrap" style="margin-top:12px"><table class="table"><thead><tr><th>Line</th><th>Field</th><th>Problem</th></tr></thead><tbody>${r.errors.filter((e) => e.row !== null).map((e) => `<tr><td class="mono">${e.row}</td><td class="mono">${esc(e.field)}</td><td>${esc(e.message)}</td></tr>`).join("")}</tbody></table></div>`;
      if (r.results.length) {
        const s = r.summary;
        html += `<div class="csv-summary"><span class="kpi-label">Batch summary</span><span>${chip("high")} ${s.bands.high}</span><span>${chip("elevated")} ${s.bands.elevated}</span><span>${chip("low")} ${s.bands.low}</span><span class="muted">Spend at risk ${fmtPct(s.pct_spend_at_risk)} · Expected loss ${fmtUSD(s.expected_loss_usd)}</span><span style="margin-left:auto" class="btn-row"><button class="btn btn-secondary btn-sm" id="csv-add">Add ${r.results.length} to portfolio</button><button class="btn btn-secondary btn-sm" id="csv-download">Download results</button></span></div>`;
        html += `<div class="table-wrap"><table class="table"><thead><tr><th>Supplier</th><th>Region</th><th class="num">Risk score</th><th>Band</th><th>Top driver</th><th>First action</th><th class="num">Expected loss</th></tr></thead><tbody>${r.results.map((x, i) => `<tr class="clickable" data-csv="${i}"><td class="name">${esc(x.supplier_name)}</td><td>${esc(x.region || "—")}</td><td class="num">${scoreBar(x)}</td><td>${chip(x.risk_band)}</td><td>${x.top_driver ? esc(x.top_driver.label) : "—"}</td><td>${esc(x.recommendations[0].action)}</td><td class="num">${fmtUSD(x.expected_loss_usd)}</td></tr>`).join("")}</tbody></table></div><div id="csv-detail"></div>`;
      }
      out.innerHTML = html;
      $("#csv-add")?.addEventListener("click", async () => { const a = await api("/api/suppliers/import", { body: { records: r.records } }); await refreshOverview(); toast(`Added ${a.added} supplier(s) to the portfolio`); });
      $("#csv-download")?.addEventListener("click", () => {
        const cols = ["supplier_name", "region", "risk_score", "risk_band", "flagged", "composite_index", "expected_loss_usd", "top_driver", "actions"];
        const lines = [cols.join(",")].concat(r.results.map((x) => [x.supplier_name, x.region || "", x.risk_score, x.risk_band, x.flagged, x.composite_index, x.expected_loss_usd, (x.top_driver ? x.top_driver.label : ""), x.recommendations.map((a) => a.action).join(" | ")].map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")));
        const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" })); a.download = "risklens_batch_results.csv"; a.click();
      });
      out.addEventListener("click", (e) => { const tr = e.target.closest("[data-csv]"); if (!tr) return; const x = r.results[+tr.dataset.csv]; $("#csv-detail").innerHTML = `<div class="divider"></div><div class="section-title"><span>${esc(x.supplier_name)}</span></div>${resultHTML(x)}`; $("#csv-detail").scrollIntoView({ behavior: "smooth", block: "start" }); });
    } catch (e) { out.innerHTML = `<div class="alert error">${esc(e.message)}</div>`; }
  }

  // ---------- methodology ----------
  function renderMethodology() {
    const m = state.meta.model, mt = m.metrics;
    $("#model-kpis").innerHTML = [["AUC-ROC (time-split test)", mt.auc_roc.toFixed(3), `5-fold CV ${mt.cv_auc_mean.toFixed(2)} ± ${mt.cv_auc_std.toFixed(2)}`], ["Recall at threshold", fmtPct(mt.recall * 100, 0), `Precision ${fmtPct(mt.precision * 100, 0)} · F1 ${mt.f1.toFixed(2)} · threshold ${(mt.decision_threshold * 100).toFixed(0)}%`], ["Average precision", mt.avg_precision.toFixed(3), `Base rate ${fmtPct(mt.base_rate_test * 100, 0)} in test window`], ["Training rows", m.n_train.toLocaleString(), `${m.n_test.toLocaleString()} held-out · ${m.n_suppliers} suppliers`]].map(([l, v, s]) => `<div class="kpi"><div class="kpi-label">${l}</div><div class="kpi-value">${v}</div><div class="kpi-sub">${s}</div></div>`).join("");
    $("#steps").innerHTML = [
      "<b>Ingest</b> supplier master data (lead time, delivery history, spend) and daily external signals (weather, geopolitical index, port congestion, commodity prices).",
      "<b>Normalise</b> every parameter to a 0–1 risk factor with the formulas below, so direction and scale are consistent across parameters.",
      `<b>Predict</b> with XGBoost: ${m.params.n_estimators} trees, depth ${m.params.max_depth}, learning rate ${m.params.learning_rate}. Monotonic constraints guarantee a higher factor never lowers the score.`,
      `<b>Score</b> = probability of a disruption within ${m.horizon_days} days, shown 0–100. The parameter scorecard shows each factor's SHAP contribution in log-odds.`,
      "<b>Recommend</b> via the rules engine: each triggered rule reports cost (scaled to annual spend), timeline, and expected loss avoided.",
      "<b>Monitor</b> portfolio exposure as spend-weighted risk, and back-test how many past disruptions were flagged in advance.",
    ].map((s) => `<li>${s}</li>`).join("");
    importanceChart(m);
    $("#feature-table tbody").innerHTML = m.features.map((f) => `<tr><td style="font-weight:600">${esc(f.label)}<div class="sub mono">${esc(f.key)}</div></td><td class="mono">${esc(f.source)}</td><td class="mono">${esc(f.formula)}</td><td class="num">${(f.weight * 100).toFixed(0)}%</td><td class="sub">${esc(f.explain)}</td></tr>`).join("");
    $("#rules-table tbody").innerHTML = state.meta.rules.map((r) => `<tr><td class="mono">${esc(r.trigger)}</td><td style="font-weight:500">${esc(r.action)}<div class="sub">${esc(r.category)}</div></td><td><span class="cost-band">${esc(r.cost_band)}</span></td><td>${esc(r.timeline)}</td><td class="num">${(r.risk_reduction * 100).toFixed(0)}%</td></tr>`).join("");
    $("#model-card").innerHTML = Object.entries({ Algorithm: m.model, Target: m.target, "Train window": m.train_window.join(" → "), "Test window": m.test_window.join(" → "), "Class weighting": "none (probabilities calibrated to base rate)", "Decision threshold": `${(mt.decision_threshold * 100).toFixed(0)}% (F1-optimal on train)`, "Brier score": mt.brier, Trained: m.trained_at.replace("T", " ").slice(0, 16) + " UTC" }).map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("");
    $("#band-legend").innerHTML = `<div class="band-legend">${state.meta.risk_bands.map((b) => `<div class="row">${chip(b.band)}<span class="mono">${b.min} – ${b.max > 100 ? 100 : b.max}</span></div>`).join("")}<div class="muted small" style="margin-top:6px">Score percentiles in historical data: ${Object.entries(m.score_percentiles).map(([p, v]) => `p${p} ${v}`).join(" · ")}</div></div>`;
    const d = state.meta.data;
    $("#data-card").innerHTML = Object.entries({ "suppliers.csv": `${d.suppliers} supplier master records`, "external_signals.csv": `${d.signal_rows.toLocaleString()} daily signal rows`, "disruptions.csv": `${d.disruptions} historical disruption events`, "supply_chain_features.csv": "engineered daily panel, ML-ready", Window: d.window }).map(([k, v]) => `<dt class="mono">${k}</dt><dd>${esc(v)}</dd>`).join("");
  }
  function importanceChart(m) {
    const ctx = $("#chart-importance"); state.charts.imp?.destroy();
    const labels = Object.keys(m.importance).map((k) => m.features.find((f) => f.key === k)?.label || k);
    state.charts.imp = new Chart(ctx, { type: "bar", data: { labels, datasets: [{ data: Object.values(m.importance).map((v) => v * 100), backgroundColor: "#0F4C81", borderRadius: 4 }] }, options: { indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => c.raw.toFixed(1) + "% of gain" } } }, scales: { x: { ticks: { callback: (v) => v + "%", font: { size: 11 } }, grid: { color: "#EEF0F3" } }, y: { ticks: { font: { size: 11 } }, grid: { display: false } } } } });
  }

  // ---------- global ----------
  $("#btn-reset").addEventListener("click", async () => { if (!confirm("Restore the seeded supplier portfolio? Your edits will be discarded.")) return; await api("/api/suppliers/reset", { method: "POST" }); await refreshOverview(); show(location.hash.slice(1) || "overview"); toast("Portfolio reset"); });

  (async () => {
    try { await loadAll(); initForm(); show(location.hash.slice(1) || "overview"); }
    catch (e) { $("#model-pill").innerHTML = `<span class="dot" style="background:#B91C1C"></span><span>Backend unavailable</span>`; $("#view-overview").innerHTML = `<div class="card"><div class="alert error">Could not reach the RiskLens API: ${esc(e.message)}. Start the server with ./run.sh</div></div>`; }
  })();
})();
