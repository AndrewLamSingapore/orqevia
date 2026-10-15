"use strict";

const STORE = {
  ideas: "orqevia.ideas",
  readiness: "orqevia.readiness",
  settings: "orqevia.settings",
};

const state = {
  manifest: null,
  status: null,
  agents: [],
  connected: false,
  paused: false,
  stopped: false,
  safeMode: false,
  activity: [],
};

const esc = (s) => String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

const $ = (id) => document.getElementById(id);

function loadJSON(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function saveJSON(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

async function api(path) {
  if (path !== 'api/status') return { connected: false, reason: 'not_exposed_by_intelligence_surface' };
  try {
    const res = await fetch('/api/orqevia/intelligence/health', { headers: { Accept: "application/json" } });
    const body = await res.json();
    return {connected:res.ok && body.ok === true,data:body,scope:'intelligence_companion'};
  } catch {
    return { connected: false, reason: "unreachable" };
  }
}

async function loadManifest() {
  try {
    const res = await fetch("/api/orqevia/manifest", { headers: { Accept: "application/json" } });
    state.manifest = await res.json();
    $("setting-upstream").textContent = state.manifest.upstream.base_url;
    renderBoundaries(state.manifest.boundaries);
  } catch {
    $("setting-upstream").textContent = "unavailable";
  }
}

function renderBoundaries(boundaries) {
  if (!boundaries) return;
  const labels = {
    autonomous_actions: "Autonomous actions",
    runtime_mutation: "Runtime mutation",
    physical_actuation: "Physical actuation",
    production_deploy: "Production deployment",
    live_pwa_change: "Live PWA change",
    public_website_change: "Public website change",
    sensitive_operations_require_human_approval: "Sensitive operations require human approval",
  };
  const html = Object.entries(boundaries).map(([k, v]) => {
    const on = labels[k] || k;
    const mark = v ? "🔓 ALLOWED" : "🔒 BLOCKED";
    return `<li><b>${esc(on)}</b> — <span class="muted">${mark}</span></li>`;
  }).join("");
  $("boundaries").innerHTML = html || '<li class="muted">Boundaries unavailable.</li>';
}

function setPill() {
  const pill = $("connection-pill");
  pill.classList.remove("pill-offline", "pill-online", "pill-degraded");
  if (state.stopped) {
    pill.textContent = "STOPPED";
    pill.classList.add("pill-offline");
  } else if (state.connected) {
    pill.textContent = "ONLINE";
    pill.classList.add("pill-online");
  } else {
    pill.textContent = "OFFLINE";
    pill.classList.add("pill-offline");
  }

  const mode = $("mode-pill");
  mode.classList.remove("stopped", "safe");
  mode.textContent = state.stopped ? "EMERGENCY STOP" : state.safeMode ? "SAFE MODE" : "NORMAL";
  if (state.stopped) mode.classList.add("stopped");
  if (state.safeMode) mode.classList.add("safe");

  const banner = $("banner");
  if (state.stopped) {
    banner.textContent = "Emergency stop engaged (local UI state). Polling halted; PRIME runtime has not been commanded.";
    banner.className = "banner stop";
  } else if (state.safeMode) {
    banner.textContent = "Safe mode engaged (local UI state). Mutating-looking controls are disabled.";
    banner.className = "banner";
  } else {
    banner.className = "banner hidden";
  }

  const mutating = ["btn-pause", "btn-stop", "btn-safe", "btn-resume", "btn-clear"];
  mutating.forEach((id) => {
    const el = $(id);
    if (el) el.disabled = state.safeMode || state.stopped;
  });
  $("idea-form")?.querySelector("button") && ($("idea-form").querySelector("button").disabled = state.safeMode || state.stopped);
}

function logActivity(message) {
  state.activity.unshift({ time: new Date().toLocaleTimeString(), message });
  state.activity = state.activity.slice(0, 30);
  renderActivity();
}

function renderActivity() {
  $("activity").innerHTML = state.activity
    .map((a) => `<li><span class="time">${esc(a.time)}</span>${esc(a.message)}</li>`)
    .join("") || '<li class="muted">No local activity yet.</li>';
}

function metric(label, value, kind) {
  const cls = kind === "good" ? "good" : kind === "warn" ? "warn" : kind === "bad" ? "bad" : "";
  return `<div class="metric"><div class="value">${esc(value)}</div><div class="label">${esc(label)}</div></div>`;
}

function renderMetrics() {
  const d = state.status ? state.status.data : null;
  if (state.connected && state.status.scope === 'intelligence_companion') {
    $('metrics').innerHTML = metric('Intelligence service','Connected','good') +
      metric('Persisted observations',d.observation_count) +
      metric('Ingestion',d.ingestion_suspended ? 'Suspended' : 'Owner initiated');
    return;
  }
  if (!state.connected || !d) {
    $("metrics").innerHTML =
      metric("Connection", "OFFLINE", "bad") +
      metric("Objective", "PRIME unavailable", "warn") +
      metric("Evidence", "No simulated data", "warn");
    return;
  }
  const fast = d.fast_ready ? "Ready" : "Preparing";
  const mem = d.memory_ready ? "Ready" : "Preparing";
  $("metrics").innerHTML =
    metric("AI models", fast, d.fast_ready ? "good" : "warn") +
    metric("Memory", mem, d.memory_ready ? "good" : "warn") +
    metric("Objectives", d.objectives ?? 0) +
    metric("Projects", d.projects ?? 0) +
    metric("Portfolios", d.portfolios ?? 0) +
    metric("Agent jobs", d.agent_jobs ?? 0) +
    metric("Pending approvals", d.pending_approvals ?? 0) +
    metric("Verified artifacts", d.verified_artifacts ?? 0);
}

function renderIntel() {
  const zone = $("intel-agents");
  if (state.connected && state.status.scope === 'intelligence_companion') {
    zone.className='state-zone online';
    zone.textContent='Public geospatial observations are available in God\'s Eye. Agent activation is separately governed.';
    $('intel-telemetry').textContent='Connected to the authenticated intelligence companion; this view does not assert peer or agent runtime readiness.';
    return;
  }
  if (!state.connected) {
    zone.className = "state-zone error";
    zone.textContent = "PRIME unavailable — agent fleet not loaded.";
    return;
  }
  const agents = Object.values((state.status && state.status.data && state.status.data.agents) || {});
  zone.className = "state-zone online";
  zone.innerHTML = agents.length
    ? agents.map((a) => `<div class="line"><b>${esc(a.name || a.id)}</b> — ${esc(a.purpose || "—")}</div>`).join("")
    : "No agent fleet data returned.";
  $("intel-telemetry").className = "state-zone online";
  $("intel-telemetry").textContent = "Telemetry is sourced from PRIME /api/status only when connected.";
}

function renderAgents() {
  const grid = $("agent-grid");
  if (!state.connected || !state.agents.length) {
    grid.innerHTML = `<div class="state-zone error">PRIME unavailable — 21-agent registry not loaded. Roles are never invented.</div>`;
    return;
  }
  grid.innerHTML = state.agents
    .map(
      (a) =>
        `<div class="agent-card"><div class="agent-name">${esc(a.name || a.id)}</div><div class="agent-purpose">${esc(a.purpose || a.role || "—")}</div></div>`
    )
    .join("");
}

function renderRouting() {
  const zone = $("routing");
  const manifest = state.status && state.status.data && state.status.data.control
    ? state.status.data.control
    : null;
  if (!state.connected || !manifest) {
    zone.className = "state-zone error";
    zone.textContent = "Routing policy unavailable until PRIME is connected.";
    return;
  }
  zone.className = "state-zone online";
  zone.innerHTML = `<div><b>Mode:</b> ${esc(manifest.mode || "—")}</div><div><b>Authority:</b> ${esc(manifest.authority || "—")}</div>`;
}

async function refreshStatus() {
  if (state.paused || state.stopped) return;
  const status = await api("api/status");
  state.connected = !!status.connected;
  state.status = status;
  if (state.connected) {
    logActivity("ORQEVIA intelligence connected — status refreshed");
  } else {
    logActivity("ORQEVIA intelligence unreachable — showing offline/unavailable states");
  }
  renderMetrics();
  renderIntel();
  renderRouting();
  setPill();
}

async function refreshAgents() {
  if (state.paused || state.stopped) return;
  const res = await api("api/agents");
  state.agents = res.connected && res.data && res.data.agents ? Object.values(res.data.agents) : [];
  renderAgents();
}

function initNav() {
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".nav-btn").forEach((b) => b.classList.toggle("active", b === btn));
      document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + btn.dataset.view));
    });
  });
}

function initIdeas() {
  const render = () => {
    const items = loadJSON(STORE.ideas, []);
    $("idea-list").innerHTML = items
      .map((it, i) => `<li><b>${esc(it.title)}</b><div class="muted">${esc(it.body)}</div><div class="muted small">Local draft #${i + 1}</div></li>`)
      .join("") || '<li class="muted">No local drafts yet.</li>';
  };
  $("idea-form").addEventListener("submit", (e) => {
    e.preventDefault();
    if (state.safeMode || state.stopped) return;
    const items = loadJSON(STORE.ideas, []);
    items.unshift({ title: $("idea-title").value.trim(), body: $("idea-body").value.trim() });
    saveJSON(STORE.ideas, items);
    $("idea-title").value = "";
    $("idea-body").value = "";
    render();
    logActivity("Saved a local objective draft");
  });
  render();
}

function initReadiness() {
  const defaults = [
    { id: "design", label: "ORQEVIA branding applied from the approved asset", done: true },
    { id: "responsive", label: "Responsive iPhone and Dell layouts", done: true },
    { id: "offline", label: "Explicit offline / stale / unavailable / error states", done: true },
    { id: "audit", label: "Tamper-evident audit trail available", done: false },
    { id: "cert", label: "21/21 agents operational and L7 certified", done: false },
  ];
  const saved = loadJSON(STORE.readiness, null);
  let items = saved && saved.length ? saved : defaults;
  const render = () => {
    $("readiness").innerHTML = items
      .map(
        (it, i) =>
          `<li><input type="checkbox" data-i="${i}" ${it.done ? "checked" : ""}> <span>${esc(it.label)}</span></li>`
      )
      .join("");
  };
  $("readiness").addEventListener("change", (e) => {
    const i = Number(e.target.dataset.i);
    if (Number.isInteger(i) && items[i]) {
      items[i].done = e.target.checked;
      saveJSON(STORE.readiness, items);
    }
  });
  render();
}

function initSettings() {
  const settings = loadJSON(STORE.settings, { safeMode: false, dark: true });
  state.safeMode = !!settings.safeMode;
  $("setting-safe").checked = state.safeMode;
  $("setting-dark").checked = settings.dark !== false;

  $("setting-safe").addEventListener("change", (e) => {
    state.safeMode = e.target.checked;
    saveJSON(STORE.settings, { safeMode: state.safeMode, dark: $("setting-dark").checked });
    logActivity(state.safeMode ? "Safe mode enabled (UI only)" : "Safe mode disabled");
    setPill();
  });
  $("setting-dark").addEventListener("change", () => {
    saveJSON(STORE.settings, { safeMode: state.safeMode, dark: $("setting-dark").checked });
  });

  $("btn-clear").addEventListener("click", () => {
    if (state.safeMode || state.stopped) return;
    localStorage.removeItem(STORE.ideas);
    localStorage.removeItem(STORE.readiness);
    localStorage.removeItem(STORE.settings);
    logActivity("Cleared local drafts and settings");
    location.reload();
  });
}

function initControls() {
  $("btn-pause").addEventListener("click", () => {
    state.paused = !state.paused;
    $("btn-pause").textContent = state.paused ? "Resume refresh" : "Pause refresh";
    logActivity(state.paused ? "Refresh paused" : "Refresh resumed");
  });
  $("btn-stop").addEventListener("click", () => {
    state.stopped = true;
    logActivity("Emergency stop engaged (local UI only)");
    setPill();
  });
  $("btn-safe").addEventListener("click", () => {
    state.safeMode = !state.safeMode;
    $("setting-safe").checked = state.safeMode;
    saveJSON(STORE.settings, { safeMode: state.safeMode, dark: $("setting-dark").checked });
    logActivity(state.safeMode ? "Safe mode enabled (UI only)" : "Safe mode disabled");
    setPill();
  });
  $("btn-resume").addEventListener("click", () => {
    state.stopped = false;
    state.paused = false;
    $("btn-pause").textContent = "Pause refresh";
    logActivity("Resumed normal operation (local UI only)");
    setPill();
  });
}

async function boot() {
  initNav();
  initIdeas();
  initReadiness();
  initSettings();
  initControls();
  renderActivity();
  setPill();
  await loadManifest();
  await refreshStatus();
  await refreshAgents();
  setInterval(() => {
    refreshStatus();
    refreshAgents();
  }, 5000);
}

boot();
