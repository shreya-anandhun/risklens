/* RiskLens client portal — vanilla JS over the FastAPI backend. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const state = { meta: null, overview: null, rows: [], sort: { key: "risk_score", dir: -1 }, band: "all", q: "", charts: {} };
  const REGIONS = ["South Asia", "Southeast Asia", "East Asia", "Middle East", "Europe", "Africa", "North America", "Latin America"];
  const CATEGORIES = ["Electronics", "Raw Materials", "Machinery", "Chemicals", "Packaging"];
  const MODES = ["Sea", "Air", "Road", "Rail"];
  const BAND_COLOR = { low: "#15803D", elevated: "#B45309", high: "#B91C1C" };

  // ---------- utils ----------
  const fmtUSD = (v) => { v = +v || 0; const a = Math.abs(v), s = v < 0 ? "-" : ""; if (a >= 1e6) return s + "$" + (a / 1e6).toFixed(a >= 1e7 ? 1 : 2) + "M"; if (a >= 1e3) return s + "$" + (a / 1e3).toFixed(0) + "K"; return s + "$" + a.toFixed(0); };
  const fmtDate = (iso) => { if (!iso) return "—"; const d = new Date(iso + "T00:00:00"); return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }); };
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
    overview: ["Overview", () => { const s = state.overview?.summary; return s ? `${s.n} active consignments · ${s.in_transit} in transit, ${s.scheduled} scheduled · 7-day risk outlook` : ""; }],
    consignments: ["Consignments", () => "Your consignment book. Click a row to inspect risk, compare alternatives and edit details."],
    actions: ["Recommended actions", () => "Mitigations across your consignments, ranked by net benefit."],
    whatif: ["What-if analysis", () => "Test a planned consignment or a batch before you book it."],
  };
  function show(view) {
    if (!PAGES[view]) view = "overview";
    $$(".nav-item").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + view));
    $("#page-title").textContent = PAGES[view][0]; $("#page-sub").textContent = PAGES[view][1]();
    window.scrollTo(0, 0);
    if (view === "overview") { renderOverview(); globeResume(); } else globePause();
    if (view === "consignments") renderBoard();
    if (view === "actions") renderActions();
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
    $("#sidebar-meta").innerHTML = `Signals refreshed daily<br>Model updated ${esc(new Date(meta.model.trained_at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }))}`;
    updateCounts();
  }
  function updateCounts() { $("#nav-count").textContent = state.rows.length; $("#nav-actions").textContent = state.overview.top_actions.length; }
  async function refresh() {
    state.overview = await api("/api/overview"); state.rows = state.overview.consignments; updateCounts();
    const v = currentView();
    if (v === "overview") renderOverview(); else state.globeDirty = true;
    if (v === "consignments") renderBoard();
    if (v === "actions") renderActions();
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
      ["Expected disruption loss", fmtUSD(s.expected_loss_usd), "Next 7 days: probability of disruption × estimated cost of the delay", ""],
      ["Savings from alternatives", fmtUSD(s.alternative_savings_usd), `${s.alternatives_available} consignment${s.alternatives_available === 1 ? " has" : "s have"} a better route, carrier or timing`, s.alternative_savings_usd > 0 ? "low" : ""],
    ];
    $("#kpi-grid").innerHTML = kpis.map(([l, v, sub, c]) => `<div class="kpi"><div class="kpi-label">${l}</div><div class="kpi-value ${c}" data-final="${esc(v)}">${esc(v)}</div><div class="kpi-sub">${sub}</div></div>`).join("");
    $$("#kpi-grid .kpi-value").forEach((el) => countUp(el, el.dataset.final));
    $("#catch-rate").textContent = o.catch_rate == null ? "" : `RiskLens rated ${o.catch_rate}% of these as Elevated or High in the 7 days before they happened.`;
    $("#recent-disruptions").innerHTML = `<table class="table"><thead><tr><th>Date</th><th>Lane</th><th>Cause</th><th class="num">Cost</th><th>Warned</th></tr></thead><tbody>${o.recent_disruptions.map((d) => `<tr><td class="mono">${fmtDate(d.date)}</td><td>${esc(d.lane)}<div class="sub mono">${esc(d.consignment_id)}</div></td><td>${esc(d.disruption_reason)}</td><td class="num">${fmtUSD(d.recovery_cost_usd)}</td><td>${d.flagged_in_advance ? '<span class="chip low">yes</span>' : '<span class="chip high">missed</span>'}</td></tr>`).join("")}</tbody></table>`;
    renderGlobe();
  }

  // ---------- actions page ----------
  function renderActions() {
    const o = state.overview;
    $("#top-actions").innerHTML = o.top_actions.length ? o.top_actions.map((a) => `<div class="action"><div><div class="a-title">${esc(a.action)}</div><div class="a-sub"><a href="#" data-open="${esc(a.consignment_id)}">${esc(a.consignment_id)}</a> · ${esc(a.lane)} · ${chip(a.risk_band)}</div><div class="a-sub">${esc(a.trigger)}</div></div><div class="a-meta">Net benefit<b class="${a.net_benefit_usd >= 0 ? "good" : "bad"}">${fmtUSD(a.net_benefit_usd)}</b>${esc(a.timeline)}</div></div>`).join("") : `<div class="empty">No actions needed. Every consignment is within tolerance.</div>`;
  }

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
  const RGB = { low: "34,197,94", elevated: "251,146,60", high: "248,64,64" };  // bright enough to read on satellite imagery
  const FACTOR_NAME = { weather_risk_index: "Weather index", geopolitical_risk_index: "Geopolitical index", port_congestion_index: "Port congestion" };
  const SITUATION = {
    weather_risk: "Severe weather risk along the lane", geopolitical_risk: "Elevated geopolitical and customs risk on the corridor",
    disruption_recency: "This lane was disrupted recently", lead_time_risk: "Long lead time leaves little room to recover",
    lead_time_variability: "Transit times on this lane are inconsistent", price_volatility: "Fuel and commodity prices are swinging",
    reliability_risk: "Carrier on-time record is weak",
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
    const rows = [["Weather", i.weather_risk_index], ["Geopolitical", i.geopolitical_risk_index], ["Port congestion", i.port_congestion_index]].filter(([, v]) => v != null);
    return `<div class="gt-bars">${rows.map(([k, v]) => `<span>${k}</span><span class="tr"><span style="width:${Math.min(100, v)}%;background:${BAND_COLOR[levelBand(v)]}"></span></span><span class="n">${(+v).toFixed(0)}</span>`).join("")}</div>`;
  }
  function lastDisruption(r) {
    const d = state.overview.recent_disruptions.find((x) => x.consignment_id === r.consignment_id);
    const days = r.inputs.days_since_last_disruption;
    if (days == null || days >= 999) return "No disruption on record for this lane.";
    return `Last lane disruption ${days} day${days === 1 ? "" : "s"} ago${d ? ` · ${esc(d.disruption_reason)}` : ""}.`;
  }
  function headline(r) { return r.risk_band === "low" ? "Operating normally" : SITUATION[r.top_driver?.key] || "Risk signals elevated"; }
  function statusLine(r) { const j = r.journey; if (!j) return ""; return j.status === "In transit" ? `In transit · day ${j.elapsed_days} of ${j.total_days} · ETA ${fmtDate(j.eta_date)}` : j.status === "Scheduled" ? `Departs ${fmtDate(j.dispatch_date)} · ETA ${fmtDate(j.eta_date)}` : "Arrived"; }

  function tipConsignment(r, kind) {
    return `<div class="gt-top"><span class="gt-kind">${ICONS[modeKey(r.mode)]}${kind}</span>${chip(r.risk_band)}</div>
      <div class="gt-title">${esc(routeText(r))}</div><div class="gt-sub"><span class="mono">${esc(r.consignment_id)}</span> · ${esc(r.cargo || "")} · ${fmtUSD(r.cargo_value_usd)}</div>
      <div class="gt-sec"><div class="gt-headline" style="--c:${BAND_COLOR[r.risk_band]}">${esc(headline(r))}</div><div class="gt-sub">${esc(statusLine(r))} · ${esc(r.mode || "")} with ${esc(r.carrier || "—")}</div></div>
      <div class="gt-sec"><div class="gt-sec-h">Signals on this lane</div>${signalBars(r.inputs)}<div class="gt-sub" style="margin-top:6px">${lastDisruption(r)}</div></div>
      <div class="gt-row" style="margin-top:6px"><span>7-day risk <b style="color:${BAND_COLOR[r.risk_band]}">${r.risk_score.toFixed(1)}</b></span><span>${r.best_alternative ? "Best option: " + esc(r.best_alternative.title) : "Stay on current plan"}</span></div>
      <div class="gt-foot">Click to open the consignment →</div>`;
  }
  function tipPlace(p) {
    const worst = p.items.reduce((a, b) => (b.r.risk_score > a.r.risk_score ? b : a));
    return `<div class="gt-top"><span class="gt-kind">${p.dest ? ICONS.flag + "Destination" : ICONS.anchor + "Origin"}${p.dest && p.origin ? " & origin" : ""}</span>${chip(worst.r.risk_band)}</div>
      <div class="gt-title">${esc(p.name)}</div><div class="gt-sub">${esc(p.country)}</div>
      <div class="gt-about">${esc(p.about)}</div>
      <div class="gt-sec"><div class="gt-sec-h">Situation</div><div class="gt-headline" style="--c:${BAND_COLOR[worst.r.risk_band]}">${esc(headline(worst.r))}</div>${signalBars(worst.r.inputs)}<div class="gt-sub" style="margin-top:6px">${lastDisruption(worst.r)}</div></div>
      <div class="gt-sec"><div class="gt-sec-h">Consignments here</div>${p.items.map(({ r, role }) => `<div class="gt-row"><span><b>${esc(r.consignment_id)}</b> ${role === "dest" ? "arriving" : "departing"} · ${role === "dest" ? "ETA " + fmtDate(r.journey?.eta_date) : fmtDate(r.journey?.dispatch_date)}</span><span style="color:${BAND_COLOR[r.risk_band]};font-weight:700">${r.risk_score.toFixed(0)}</span></div>`).join("")}</div>`;
  }
  function tipHotspot(h) {
    return `<div class="gt-top"><span class="gt-kind">${ICONS.alert}Risk hotspot</span>${chip(h.band)}</div>
      <div class="gt-title">${esc(h.name)}</div><div class="gt-about">${esc(h.about)}</div>
      <div class="gt-sec"><div class="gt-sec-h">Current signal</div><div class="gt-bars"><span>${FACTOR_NAME[h.factor]}</span><span class="tr"><span style="width:${Math.min(100, h.level)}%;background:${BAND_COLOR[h.band]}"></span></span><span class="n">${h.level.toFixed(0)}</span></div></div>
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
    g.pathColor((d) => (d.kind === "base" ? `rgba(${RGB[d.r.risk_band]},${alpha(d, 0.6)})` : [`rgba(${RGB[d.r.risk_band]},${alpha(d, 0.2)})`, `rgba(${RGB[d.r.risk_band]},${alpha(d, 1)})`]));
    g.arcColor((d) => (d.kind === "base" ? `rgba(${RGB[d.r.risk_band]},${alpha(d, 0.55)})` : [`rgba(${RGB[d.r.risk_band]},${alpha(d, 0.15)})`, `rgba(${RGB[d.r.risk_band]},${alpha(d, 1)})`]));
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
        .globeImageUrl("/static/vendor/earth/earth-blue-marble.jpg").bumpImageUrl("/static/vendor/earth/earth-topology.png")
        .showAtmosphere(true).atmosphereColor("#8EC5FF").atmosphereAltitude(0.15)
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
      <div class="br" data-open="${esc(r.consignment_id)}">
        <div><span class="cid">${esc(r.consignment_id)}</span><span class="cargo" title="${esc(r.cargo)}">${esc(r.cargo || r.supplier_name || "")}</span><span class="route-sub">${fmtUSD(r.cargo_value_usd)} · ${esc(r.supplier_name || "")}</span></div>
        <div><span class="route">${route(r)}</span><span class="route-sub"><span class="mode">${esc(r.mode || "—")}</span>${esc(r.carrier || "")}</span></div>
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
    ["cargo", "Cargo", "text", { placeholder: "e.g. Power semiconductors" }], ["supplier_name", "Shipper / supplier", "text", {}],
    ["product_category", "Category", "select", opt(CATEGORIES)], ["mode", "Mode", "select", opt(MODES)],
    ["carrier", "Carrier", "text", {}], ["single_source", "Single carrier, no backup", "select", ["0:No", "1:Yes"]],
    ["units", "Units in consignment", "number", { min: 0 }], ["average_cost_per_unit", "Value per unit (USD)", "number", { min: 0, step: "any" }],
    ["Route"],
    ["origin_port", "From (port / city)", "text", {}], ["destination_port", "To (port / city)", "text", {}],
    ["origin_country", "Origin country", "text", {}], ["destination_country", "Destination country", "text", {}],
    ["region", "Origin region", "select", opt(REGIONS)], ["destination_region", "Destination region", "select", opt(REGIONS)],
    ["dispatch_date", "Dispatch date", "date", {}], ["eta_date", "ETA", "date", {}],
    ["Operational"],
    ["lead_time_days", "Lead time, order to delivery (days)", "number", { min: 1, max: 365 }], ["lead_time_std_days", "Lead time spread, std dev (days)", "number", { min: 0, step: "any" }],
    ["reliability_score", "Carrier on-time rate (0–1)", "number", { min: 0, max: 1, step: "any" }], ["annual_volume_units", "Shipper annual volume (units)", "number", { min: 0 }],
    ["External signals"],
    ["geopolitical_risk_index", "Geopolitical risk index (0–100)", "number", { min: 0, max: 100, step: "any" }], ["port_congestion_index", "Port congestion index (0–100)", "number", { min: 0, max: 100, step: "any" }],
    ["weather_risk_index", "Weather risk index (0–100)", "number", { min: 0, max: 100, step: "any", placeholder: "or use level" }], ["weather_risk_level", "Weather risk level", "select", ["low:Low", "medium:Medium", "high:High"]],
    ["price_swing_pct", "Fuel & commodity price swing, 30 days (%)", "number", { min: 0, max: 100, step: "any" }], ["days_since_last_disruption", "Days since last disruption on lane", "number", { min: 0, placeholder: "none on record" }],
  ];
  function fieldHTML([key, label, type, opts], rec) {
    if (!label) return `<div class="form-section span-2">${key}</div>`;
    const v = rec[key] ?? "";
    if (type === "select") return `<label>${label}<select name="${key}" class="input">${key === "weather_risk_level" || key === "single_source" ? "" : '<option value="">—</option>'}${opts.map((o) => { const i = o.indexOf(":"); const val = o.slice(0, i), txt = o.slice(i + 1); return `<option value="${esc(val)}" ${String(v) === val ? "selected" : ""}>${esc(txt)}</option>`; }).join("")}</select></label>`;
    return `<label>${label}<input name="${key}" type="${type}" class="input" value="${esc(v)}" ${Object.entries(opts).map(([k, x]) => `${k}="${esc(x)}"`).join(" ")}></label>`;
  }
  const formToRecord = (form) => { const o = {}; new FormData(form).forEach((v, k) => { if (v !== "") o[k] = v; }); return o; };
  function clearErrors(form) { $$(".field-error", form).forEach((e) => e.remove()); $$(".invalid", form).forEach((e) => e.classList.remove("invalid")); }
  function showErrors(form, err) {
    clearErrors(form); const errs = err.detail?.errors || [{ field: null, message: err.message }];
    for (const e of errs) { const inp = e.field && form.querySelector(`[name="${e.field}"]`); if (inp) { inp.classList.add("invalid"); inp.closest("label")?.insertAdjacentHTML("beforeend", `<span class="field-error">${esc(e.message)}</span>`); } else toast(e.message); }
  }

  // ---------- result rendering ----------
  const INPUT_SUMMARY = {
    reliability_risk: (i) => `on-time rate ${fmtN(i.reliability_score, 2)}`,
    lead_time_risk: (i) => `${fmtN(i.lead_time_days, 0)} days`,
    lead_time_variability: (i) => `±${fmtN(i.lead_time_std_days)} days on ${fmtN(i.lead_time_days, 0)}`,
    geopolitical_risk: (i) => `index ${fmtN(i.geopolitical_risk_index)}${i.port_congestion_index != null ? ` · port ${fmtN(i.port_congestion_index)}` : ""}`,
    weather_risk: (i) => (i.weather_risk_index != null ? `index ${fmtN(i.weather_risk_index)}` : `level ${i.weather_risk_level || "—"}`),
    price_volatility: (i) => `${fmtN(i.price_swing_pct)}% swing / 30 days`,
    disruption_recency: (i) => (i.days_since_last_disruption == null || i.days_since_last_disruption >= 999 ? "none on record" : `${fmtN(i.days_since_last_disruption, 0)} days ago`),
  };
  function fmtN(v, d = 1) { return v == null || v === "" ? "—" : (+v).toFixed(d); }

  function alternativesHTML(r, { applyable }) {
    if (!r.alternatives) return "";
    const cur = `<tr class="current"><td><div class="alt-title">Current plan${r.applied_alternative ? '<span class="badge-applied">updated</span>' : ""}</div><div class="alt-desc">${esc(r.mode || "")} · ${esc(r.carrier || "carrier not set")} · ${esc(routeText(r))}${r.route_via ? ` via ${esc(r.route_via)}` : ""}</div></td><td class="num"><b style="color:${BAND_COLOR[r.risk_band]}">${r.risk_score.toFixed(1)}</b></td><td class="num">—</td><td class="num">—</td><td class="num">${fmtUSD(r.expected_loss_usd)}</td><td class="num">—</td>${applyable ? "<td></td>" : ""}</tr>`;
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

  function resultHTML(r, { applyable = false } = {}) {
    const color = BAND_COLOR[r.risk_band]; const maxAbs = Math.max(0.05, ...r.factors.map((f) => Math.abs(f.contribution)));
    const bandText = { low: "Low risk: normal tracking", elevated: "Elevated: watch closely", high: "High: act before it slips" }[r.risk_band];
    return `
      <div class="score-hero">
        <div class="dial" style="background:conic-gradient(${color} ${r.risk_score * 3.6}deg, #EEF0F3 0)"><div class="dv"><b style="color:${color}">${r.risk_score.toFixed(1)}</b><span>7-day risk</span></div></div>
        <div class="hero-stats">
          <div>Status<b>${chip(r.risk_band)}</b><span class="tag">${bandText}</span></div>
          <div>Confidence<b>${r.confidence.toFixed(0)}%</b></div>
          <div>Weighted index<b>${r.composite_index.toFixed(1)} / 100</b></div>
          <div>Cargo value<b>${fmtUSD(r.cargo_value_usd)}</b></div>
          <div>Cost if disrupted<b>${fmtUSD(r.estimated_disruption_cost_usd)}</b></div>
          <div>Expected loss (7 days)<b style="color:${r.expected_loss_usd > 0 ? "var(--high)" : "inherit"}">${fmtUSD(r.expected_loss_usd)}</b></div>
        </div>
      </div>
      ${alternativesHTML(r, { applyable })}
      <div>
        <div class="section-title"><span>Risk parameters</span><span class="tag">how each parameter moves this score</span></div>
        <table class="factor-table"><thead><tr><th>Parameter</th><th style="width:26%">Risk level (0–1)</th><th class="num">Weight</th><th style="width:22%">Effect on score</th><th class="num">Δ</th></tr></thead><tbody>
        ${r.factors.map((f) => `<tr><td><div style="font-weight:500"><span class="param-name" title="${esc(f.formula)}">${esc(f.label)}</span></div><div class="tag">${esc(INPUT_SUMMARY[f.key]?.(r.inputs) || "")}</div></td><td><div class="ftrack"><div class="ffill" style="width:${f.value * 100}%;background:${heatColor(f.value)}"></div></div><div class="tag">${f.value.toFixed(2)}</div></td><td class="num">${(f.weight * 100).toFixed(0)}%</td><td><div class="contrib"><div class="l">${f.contribution < 0 ? `<span style="width:${(Math.abs(f.contribution) / maxAbs) * 100}%"></span>` : ""}</div><div class="r">${f.contribution > 0 ? `<span style="width:${(f.contribution / maxAbs) * 100}%"></span>` : ""}</div></div></td><td class="contrib-val ${f.contribution > 0 ? "pos" : "neg"}">${f.contribution > 0 ? "+" : ""}${f.contribution.toFixed(2)}</td></tr>`).join("")}
        </tbody></table>
        <details class="calc"><summary>How is this score calculated?</summary>
          <p>Each input is converted to a risk level between 0 (safe) and 1 (riskiest) using the formulas below. The seven levels go into an XGBoost model trained on historical lane data, which returns the probability of a disruption in the next 7 days. Red bars push the score up and green bars pull it down. The weighted index is a simple weighted sum of the same seven levels, shown for reference.</p>
          <dl>${r.factors.map((f) => `<dt>${esc(f.label)}</dt><dd>${esc(f.formula)}</dd>`).join("")}</dl>
          <p>Bands: Low below ${state.meta.risk_bands[1].min}, Elevated ${state.meta.risk_bands[1].min}–${state.meta.risk_bands[2].min}, High ${state.meta.risk_bands[2].min} and above.</p>
        </details>
      </div>
      <div>
        <div class="section-title"><span>Mitigations</span><span class="tag">risk after all mitigations ≈ ${r.residual_risk_score.toFixed(1)}</span></div>
        <div class="action-list">${r.recommendations.map((a) => `<div class="action rec"><div class="a-title">${esc(a.action)} <span class="cost-band">${esc(a.cost_band)} cost</span></div><div class="a-sub">${esc(a.rationale)}</div><div class="a-cost"><span>Why <b>${esc(a.trigger)}</b></span><span>When <b>${esc(a.timeline)}</b></span><span>Cost <b>${fmtUSD(a.cost_usd)}</b></span><span>Loss avoided <b>${fmtUSD(a.benefit_usd)}</b></span><span>Net <b class="${a.net_benefit_usd >= 0 ? "good" : "bad"}">${fmtUSD(a.net_benefit_usd)}</b></span><span>Risk reduction <b>${(a.risk_reduction * 100).toFixed(0)}%</b></span></div></div>`).join("")}</div>
      </div>`;
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
  function routeStrip(r) {
    const j = r.journey || {};
    return `<div><div class="route-strip">
        <div class="pt"><b>${esc(r.origin_port || "—")}</b><span>${esc(r.origin_country || "")}${r.region ? " · " + esc(r.region) : ""}</span></div>
        <div class="mid"><span class="mode">${esc(r.mode || "—")}</span><div class="line"></div>${r.route_via ? "via " + esc(r.route_via) : esc(r.carrier || "")}</div>
        <div class="pt to"><b>${esc(r.destination_port || "—")}</b><span>${esc(r.destination_country || "")}${r.destination_region ? " · " + esc(r.destination_region) : ""}</span></div>
      </div>
      <div class="route-meta"><div>Status<b>${esc(j.status || "—")}</b></div><div>Dispatch<b>${fmtDate(j.dispatch_date)}</b></div><div>ETA<b>${fmtDate(j.eta_date)}</b></div><div>Carrier<b>${esc(r.carrier || "—")}</b></div></div></div>`;
  }
  function renderDrawer(r) {
    $("#drawer-eyebrow").textContent = `${r.consignment_id} · ${r.cargo || ""}`;
    $("#drawer-title").textContent = routeText(r);
    $("#drawer-sub").textContent = `${r.supplier_name || ""}${r.product_category ? " · " + r.product_category : ""}`;
    $("#drawer-body").innerHTML = `
      ${routeStrip(r)}
      <div id="drawer-result">${resultHTML(r, { applyable: true })}</div>
      <div>
        <div class="section-title"><span>Lane risk history</span><span class="tag">predicted 7-day risk vs. actual disruptions on this lane</span></div>
        <div class="chart-wrap" style="height:180px"><canvas id="chart-history"></canvas></div>
      </div>
      <div>
        <div class="section-title"><span>Edit consignment</span><span class="tag">score updates live · Save to keep changes</span></div>
        <form id="edit-form" class="form-grid">${FIELDS.map((f) => fieldHTML(f, r.record)).join("")}
          <div class="span-2 form-actions"><button type="submit" class="btn btn-primary">Save changes</button><button type="button" class="btn btn-danger" id="btn-delete">Remove consignment</button><span class="muted" id="edit-status"></span></div>
        </form>
      </div>`;
    historyChart(r.history);
    bindApply(r.consignment_id);
    const form = $("#edit-form");
    form.addEventListener("input", debounce(async () => {
      $("#edit-status").textContent = "Re-scoring…";
      try { const res = await api("/api/score", { body: { ...formToRecord(form), consignment_id: r.consignment_id } }); res.applied_alternative = r.applied_alternative; $("#drawer-result").innerHTML = resultHTML(res); $("#edit-status").textContent = "Unsaved changes"; clearErrors(form); }
      catch (e) { $("#edit-status").textContent = ""; showErrors(form, e); }
    }, 350));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try { const res = await api(`/api/consignments/${encodeURIComponent(r.consignment_id)}`, { method: "PUT", body: formToRecord(form) }); await refresh(); toast(`Saved ${res.consignment_id} · risk ${res.risk_score.toFixed(1)}`); openDrawer(r.consignment_id); }
      catch (e) { showErrors(form, e); }
    });
    $("#btn-delete").addEventListener("click", async () => {
      if (!confirm(`Remove ${r.consignment_id} from the consignment book?`)) return;
      await api(`/api/consignments/${encodeURIComponent(r.consignment_id)}`, { method: "DELETE" }); closeDrawer(); await refresh(); toast(`Removed ${r.consignment_id}`);
    });
  }
  function bindApply(cid) {
    $$("#drawer-result [data-apply]").forEach((b) => b.addEventListener("click", async () => {
      const title = b.closest("tr").querySelector(".alt-title").childNodes[0].textContent;
      if (!confirm(`Apply "${title}" to ${cid}? The consignment's route, carrier and dates will be updated.`)) return;
      try { const res = await api(`/api/consignments/${encodeURIComponent(cid)}/apply/${encodeURIComponent(b.dataset.apply)}`, { method: "POST" }); await refresh(); toast(`${cid} updated · risk now ${res.risk_score.toFixed(1)}`); openDrawer(cid); }
      catch (e) { toast(e.message); }
    }));
  }
  function historyChart(h) {
    const ctx = $("#chart-history"); if (!ctx) return; state.charts.h?.destroy();
    if (!h?.length) { ctx.parentElement.innerHTML = `<div class="empty small">No lane history for this consignment yet.</div>`; return; }
    state.charts.h = new Chart(ctx, { data: { labels: h.map((d) => fmtDate(d.date)), datasets: [
      { type: "line", label: "Predicted 7-day risk %", data: h.map((d) => d.pred), borderColor: "#0F4C81", backgroundColor: "rgba(15,76,129,.08)", fill: true, tension: .3, pointRadius: 0, borderWidth: 2 },
      { type: "bar", label: "Disruption on lane", data: h.map((d) => (d.disrupted ? 100 : 0)), backgroundColor: "rgba(185,28,28,.45)", barPercentage: .6 } ] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom", labels: { boxWidth: 10, font: { size: 11 } } } }, scales: { x: { ticks: { maxTicksLimit: 6, font: { size: 10 } }, grid: { display: false } }, y: { min: 0, max: 100, ticks: { font: { size: 10 } } } } } });
  }
  document.addEventListener("click", (e) => { const t = e.target.closest("[data-open]"); if (t) { e.preventDefault(); openDrawer(t.dataset.open); } });

  // ---------- what-if ----------
  const WHATIF_DEFAULTS = { cargo: "Lithium battery cells", supplier_name: "Shenzhen Boards", product_category: "Electronics", mode: "Sea", carrier: "Pacific Arc Lines", single_source: "1", units: 20000, average_cost_per_unit: 95, origin_port: "Shenzhen", origin_country: "China", region: "East Asia", destination_port: "Felixstowe", destination_country: "United Kingdom", destination_region: "Europe", lead_time_days: 45, lead_time_std_days: 8, reliability_score: 0.84, geopolitical_risk_index: 48, port_congestion_index: 55, weather_risk_level: "medium", price_swing_pct: 9 };
  function initWhatIf() {
    const f = $("#score-form");
    f.innerHTML = FIELDS.map((x) => fieldHTML(x, WHATIF_DEFAULTS)).join("") + `<div class="span-2 form-actions"><button type="submit" class="btn btn-primary">Assess risk</button><button type="button" class="btn btn-secondary" id="btn-save-form">Add to consignments</button><span class="muted" id="form-status"></span></div>`;
    const run = async () => { try { const res = await api("/api/score", { body: formToRecord(f) }); $("#score-result").innerHTML = resultHTML(res); clearErrors(f); $("#form-status").textContent = ""; } catch (e) { showErrors(f, e); } };
    f.addEventListener("submit", (e) => { e.preventDefault(); run(); });
    f.addEventListener("input", debounce(run, 400));
    $("#btn-save-form").addEventListener("click", async () => {
      try { const res = await api("/api/consignments", { method: "POST", body: formToRecord(f) }); await refresh(); toast(`Added ${res.consignment_id} to consignments`); $("#form-status").innerHTML = `Saved as <a href="#" data-open="${esc(res.consignment_id)}" class="mono">${esc(res.consignment_id)}</a>`; }
      catch (e) { showErrors(f, e); }
    });
    run();
  }
  $("#btn-new").addEventListener("click", () => { location.hash = "whatif"; setTimeout(() => $("#score-form [name=cargo]")?.focus(), 50); });

  // ---------- csv ----------
  const dz = $("#dropzone"), fi = $("#csv-input");
  $("#csv-browse").addEventListener("click", () => fi.click());
  fi.addEventListener("change", () => fi.files[0] && uploadCsv(fi.files[0]));
  ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
  dz.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) uploadCsv(f); });
  async function uploadCsv(file) {
    const out = $("#csv-result"); out.innerHTML = `<div class="alert ok">Checking ${esc(file.name)}…</div>`;
    const fd = new FormData(); fd.append("file", file);
    try {
      const r = await api("/api/score/csv", { method: "POST", body: fd });
      let html = "";
      if (r.errors.some((e) => e.row === null)) html += r.errors.map((e) => `<div class="alert error">${esc(e.message)}</div>`).join("");
      else html += `<div class="alert ${r.errors.length ? "warn" : "ok"}">Scored ${r.rows_scored} of ${r.rows_total} rows from ${esc(r.filename)}.${r.errors.length ? ` ${r.errors.length} problem(s) listed below.` : ""}</div>`;
      html += r.warnings.map((w) => `<div class="alert warn">${esc(w)}</div>`).join("");
      const rowErrs = r.errors.filter((e) => e.row !== null);
      if (rowErrs.length) html += `<div class="table-wrap" style="margin-top:12px"><table class="table"><thead><tr><th>Line</th><th>Field</th><th>Problem</th></tr></thead><tbody>${rowErrs.map((e) => `<tr><td class="mono">${e.row}</td><td class="mono">${esc(e.field)}</td><td>${esc(e.message)}</td></tr>`).join("")}</tbody></table></div>`;
      if (r.results.length) {
        const s = r.summary;
        html += `<div class="csv-summary"><span class="kpi-label">Batch summary</span><span>${chip("high")} ${s.bands.high}</span><span>${chip("elevated")} ${s.bands.elevated}</span><span>${chip("low")} ${s.bands.low}</span><span class="muted">Value at risk ${fmtUSD(s.value_at_risk_usd)} · Expected loss ${fmtUSD(s.expected_loss_usd)}</span><span style="margin-left:auto" class="btn-row"><button class="btn btn-secondary btn-sm" id="csv-add">Add to consignments</button><button class="btn btn-secondary btn-sm" id="csv-download">Download results</button></span></div>`;
        html += `<div class="table-wrap"><table class="table"><thead><tr><th>Consignment</th><th>Route</th><th class="num">Risk score</th><th>Band</th><th>Main driver</th><th>Best alternative</th><th class="num">Expected loss</th></tr></thead><tbody>${r.results.map((x, i) => `<tr class="clickable" data-csv="${i}"><td><div class="cid">${esc(x.consignment_id || "—")}</div><div class="sub">${esc(x.cargo || x.supplier_name || "")}</div></td><td>${route(x)}</td><td class="num">${scoreBar(x)}</td><td>${chip(x.risk_band)}</td><td>${x.top_driver ? esc(x.top_driver.label) : "—"}</td><td class="alt-cell">${altCell(x)}</td><td class="num">${fmtUSD(x.expected_loss_usd)}</td></tr>`).join("")}</tbody></table></div><div id="csv-detail"></div>`;
      }
      out.innerHTML = html;
      $("#csv-add")?.addEventListener("click", async () => { const a = await api("/api/consignments/import", { body: { records: r.records } }); await refresh(); toast(a.added ? `Added ${a.added} consignment(s)` : "Nothing added: those consignment IDs already exist"); });
      $("#csv-download")?.addEventListener("click", () => {
        const cols = ["consignment_id", "route", "risk_score", "risk_band", "expected_loss_usd", "main_driver", "best_alternative", "mitigations"];
        const lines = [cols.join(",")].concat(r.results.map((x) => [x.consignment_id || "", routeText(x), x.risk_score, x.risk_band, x.expected_loss_usd, x.top_driver ? x.top_driver.label : "", x.best_alternative ? x.best_alternative.title : "", x.recommendations.map((a) => a.action).join(" | ")].map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")));
        const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" })); a.download = "risklens_batch_results.csv"; a.click();
      });
      out.onclick = (e) => { const tr = e.target.closest("[data-csv]"); if (!tr) return; const x = r.results[+tr.dataset.csv]; $("#csv-detail").innerHTML = `<div class="divider"></div><div class="section-title"><span>${esc(x.consignment_id || "")} · ${esc(routeText(x))}</span></div>${resultHTML(x)}`; $("#csv-detail").scrollIntoView({ behavior: "smooth", block: "start" }); };
    } catch (e) { out.innerHTML = `<div class="alert error">${esc(e.message)}</div>`; }
  }

  // ---------- global ----------
  $("#btn-reset").addEventListener("click", async () => { if (!confirm("Restore the original demo consignments? Your edits will be discarded.")) return; await api("/api/consignments/reset", { method: "POST" }); await refresh(); toast("Demo data restored"); });

  (async () => {
    try { await loadAll(); initWhatIf(); show(location.hash.slice(1) || "overview"); }
    catch (e) { $("#model-pill").innerHTML = `<span class="dot" style="background:#B91C1C;box-shadow:none"></span><span>Service unavailable</span>`; $("#view-overview").innerHTML = `<div class="card"><div class="alert error">Could not reach the RiskLens service: ${esc(e.message)}. Start it with ./run.sh</div></div>`; }
  })();
})();
