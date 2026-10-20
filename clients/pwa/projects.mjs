const $ = id => document.getElementById(id);
let selectedRun = null, selectedAgent = null, session = null;
const terminal = new Set(["COMPLETED", "FAILED", "CANCELLED", "PARTIAL"]);

async function request(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      "X-ORQEVIA-PWA": "1",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
    ...options,
  });
  const type = response.headers.get("content-type") || "";
  const value = type.includes("json") ? await response.json() : await response.text();
  if (!response.ok) {
    const error = new Error(typeof value === "string" ? value : value?.detail || "Request failed");
    error.status = response.status;
    throw error;
  }
  return value;
}

function setMessage(text, error = false) {
  $("workflow-message").textContent = text;
  $("workflow-message").classList.toggle("bad", error);
}

function pill(text, state = "") {
  const node = document.createElement("span");
  node.className = "pill " + state;
  node.textContent = text;
  return node;
}

function mutate(path, method, body) {
  return request(path, { method, body: JSON.stringify(body), headers: { "X-ORQEVIA-PWA": "1" } });
}

async function loadSession() {
  session = await request("/pwa/api/session");
  const ok = session?.authenticated && session.role === "OWNER";
  $("session-state").textContent = ok ? "Owner connected" : "Owner required";
  $("session-state").className = "pill " + (ok ? "ok" : "bad");
  if (!ok) setMessage("Open ORQEVIA first and verify Owner access.", true);
  return ok;
}

async function loadTemplates() {
  try {
    const value = await request("/pwa/api/project-workflows/templates");
    const template = value.templates?.find(item => item.template_id === "sme-profitability.v1");
    $("template-state").textContent = template ? `${template.agent_count} agents · verified template` : "Template unavailable";
    $("template-state").className = "pill " + (template ? "ok" : "bad");
  } catch (error) {
    $("template-state").textContent = "Template unavailable";
    $("template-state").className = "pill bad";
  }
}

function statusClass(status) {
  return "status-" + String(status || "").toLowerCase();
}

function renderRun(run) {
  const detail = $("run-detail");
  detail.replaceChildren();
  detail.classList.remove("hidden");
  const title = document.createElement("div");
  title.className = "card-title";
  const heading = document.createElement("div");
  const eyebrow = document.createElement("p");
  eyebrow.className = "eyebrow";
  eyebrow.textContent = run.project_id;
  const h3 = document.createElement("h3");
  h3.textContent = `${run.state} · phase ${run.current_phase}`;
  heading.append(eyebrow, h3);
  title.append(heading, pill(`${run.summary.completed}/21 agents`, run.summary.completed === 21 ? "ok" : "warn"));
  detail.append(title);
  const progress = document.createElement("div");
  progress.className = "progress";
  const bar = document.createElement("span");
  bar.style.width = `${Math.round(run.summary.completed / 21 * 100)}%`;
  progress.append(bar);
  detail.append(progress);
  const meta = document.createElement("p");
  meta.className = "muted";
  meta.textContent = `Run ${run.run_id} · ${run.summary.handoffs} handoffs · ${run.summary.failed} failed`;
  detail.append(meta);
  if (!terminal.has(run.state) && !run.cancel_requested) {
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "secondary";
    cancel.textContent = "Cancel run";
    cancel.addEventListener("click", async () => {
      setMessage("Cancellation requested. Waiting for ORQEVIA to confirm.");
      selectedRun = await mutate(`/pwa/api/project-workflows/${encodeURIComponent(run.run_id)}/cancel`, "POST", {});
      renderRun(selectedRun);
    });
    detail.append(cancel);
  }
  if (run.state === "AWAITING_RESTART_VERIFICATION") {
    const note = document.createElement("p");
    note.className = "message";
    note.textContent = "Artifacts are ready. Restart the backend, then verify the saved decision from the execution environment.";
    detail.append(note);
  }
  const grid = document.createElement("div");
  grid.className = "task-grid";
  for (const task of run.tasks) {
    const row = document.createElement("div");
    row.className = "task";
    const agent = document.createElement("strong");
    agent.textContent = `${task.agent_id.toUpperCase()} · ${task.responsibility}`;
    const state = document.createElement("small");
    state.className = statusClass(task.status);
    state.textContent = `${task.status} · ${task.queue_job_id || "pending"}`;
    row.append(agent, state);
    grid.append(row);
  }
  detail.append(grid);
  if (run.artifacts.length) {
    const artifacts = document.createElement("div");
    artifacts.className = "artifacts";
    for (const artifact of run.artifacts) {
      const link = document.createElement("a");
      link.href = `/pwa/api/project-workflows/${encodeURIComponent(run.run_id)}/artifacts/${encodeURIComponent(artifact.name)}`;
      link.download = artifact.name;
      link.textContent = artifact.name;
      artifacts.append(link);
    }
    detail.append(artifacts);
  }
}

async function loadRuns(select = selectedRun?.run_id) {
  const value = await request("/pwa/api/project-workflows?limit=20");
  const runs = value.runs || [];
  const list = $("runs");
  list.replaceChildren();
  if (!runs.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No workflow runs yet.";
    list.append(empty);
    return;
  }
  for (const run of runs) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "run-item";
    const body = document.createElement("span");
    const name = document.createElement("strong");
    name.textContent = `${run.project_id} · ${run.state}`;
    const meta = document.createElement("small");
    meta.textContent = `${run.summary.completed}/21 completed · ${run.run_id.slice(0, 8)} · ${run.updated_at}`;
    body.append(name, meta);
    button.append(body, pill(`${run.summary.handoffs} handoffs`));
    button.addEventListener("click", () => {
      selectedRun = run;
      renderRun(run);
    });
    list.append(button);
    if (select === run.run_id) selectedRun = run;
  }
  if (selectedRun) renderRun(selectedRun);
}

async function pollRun() {
  if (!selectedRun || terminal.has(selectedRun.state)) return;
  try {
    selectedRun = await request(`/pwa/api/project-workflows/${encodeURIComponent(selectedRun.run_id)}`);
    renderRun(selectedRun);
    await loadRuns(selectedRun.run_id);
    if (!terminal.has(selectedRun.state)) setTimeout(pollRun, 2000);
  } catch (error) {
    setMessage(error.message, true);
    setTimeout(pollRun, 5000);
  }
}

$("workflow-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (!session?.authenticated || session.role !== "OWNER") {
    setMessage("Owner access is required.", true);
    return;
  }
  const form = new FormData(event.currentTarget);
  const body = {
    template_id: "sme-profitability.v1",
    project_key: String(form.get("project_key") || "").trim(),
    title: String(form.get("title") || "").trim(),
    currency: "SGD",
    idempotency_key: `ui-${crypto.randomUUID()}`,
    inputs: Object.fromEntries(
      ["revenue", "rent", "salaries", "inventory", "utilities", "marketing", "other_expenses"]
        .map(key => [key, Number(form.get(key))])
    ),
  };
  setMessage("Starting the durable workflow…");
  try {
    selectedRun = await mutate("/pwa/api/project-workflows", "POST", body);
    setMessage(`Run ${selectedRun.run_id} started.`);
    renderRun(selectedRun);
    await loadRuns(selectedRun.run_id);
    setTimeout(pollRun, 1000);
  } catch (error) {
    setMessage(error.message, true);
  }
});

$("refresh-runs").addEventListener("click", () => loadRuns().catch(error => setMessage(error.message, true)));

async function loadNotebooks() {
  try {
    const health = await request("/pwa/api/notebooks/health");
    $("notebook-health").textContent = `${health.agents_provisioned}/21 ready · ${health.indexed} indexed`;
    $("notebook-health").className = "pill " + (health.status === "READY" ? "ok" : "warn");
    const directory = await request("/pwa/api/notebooks");
    const node = $("agent-directory");
    node.replaceChildren();
    for (const agent of directory.agents) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "agent-button";
      const name = document.createElement("strong");
      name.textContent = `${agent.agent_id.toUpperCase()} · ${agent.name}`;
      const role = document.createElement("small");
      role.textContent = agent.role;
      button.append(name, role);
      button.addEventListener("click", () => openNotebook(agent.agent_id, button));
      node.append(button);
    }
  } catch (error) {
    $("notebook-health").textContent = "Unavailable";
    $("notebook-health").className = "pill bad";
  }
}

async function openNotebook(agentId, button) {
  selectedAgent = agentId;
  for (const item of document.querySelectorAll(".agent-button")) item.classList.remove("active");
  button?.classList.add("active");
  $("notebook-title").textContent = agentId.toUpperCase();
  $("export-notebook").disabled = false;
  $("record-form").classList.remove("hidden");
  const value = await request(`/pwa/api/notebooks/${encodeURIComponent(agentId)}?limit=100`);
  renderRecords(value.records || []);
  const profile = await request(`/pwa/api/notebooks/conditioning/${encodeURIComponent(agentId)}`);
  $("conditioning-state").textContent = profile.profile.enabled ? "Enabled" : "Disabled by default";
  $("conditioning-state").className = "pill " + (profile.profile.enabled ? "warn" : "");
}

function renderRecords(records) {
  const node = $("notebook-records");
  node.replaceChildren();
  if (!records.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No records in this notebook yet.";
    node.append(empty);
    return;
  }
  for (const record of records) {
    const row = document.createElement("div");
    row.className = "memory-record";
    const header = document.createElement("header");
    const title = document.createElement("strong");
    title.textContent = `${record.section} · ${record.record_type}`;
    const meta = document.createElement("small");
    meta.textContent = `${record.verification_status} · v${record.version} · ${record.updated_at}`;
    header.append(title, meta);
    const content = document.createElement("pre");
    content.textContent = JSON.stringify(record.content, null, 2);
    const source = document.createElement("small");
    source.className = "muted";
    source.textContent = `Source: ${record.source}${record.source_ref ? ` · ${record.source_ref}` : ""}`;
    row.append(header, content, source);
    node.append(row);
  }
}

$("notebook-search").addEventListener("submit", async event => {
  event.preventDefault();
  if (!selectedAgent) return;
  const query = String(new FormData(event.currentTarget).get("query") || "").trim();
  if (!query) return;
  try {
    const value = await mutate("/pwa/api/notebooks/search", "POST", { query, agent_id: selectedAgent, limit: 20 });
    $("notebook-search-results").replaceChildren();
    const summary = document.createElement("p");
    summary.className = "muted";
    summary.textContent = `${value.results.length} result(s) · ${value.retrieval.mode}${value.retrieval.degraded ? " · degraded" : ""}`;
    $("notebook-search-results").append(summary);
    renderRecords(value.results);
  } catch (error) {
    $("notebook-search-results").textContent = error.message;
  }
});

$("record-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (!selectedAgent) return;
  const form = new FormData(event.currentTarget);
  try {
    await mutate(`/pwa/api/notebooks/${encodeURIComponent(selectedAgent)}/records`, "POST", {
      section: String(form.get("section")),
      content: { text: String(form.get("content")) },
      source: String(form.get("source")),
      verification_status: "agent_reported",
      confidence: 0.7,
      idempotency_key: `ui-note-${crypto.randomUUID()}`,
    });
    event.currentTarget.reset();
    await openNotebook(selectedAgent, document.querySelector(".agent-button.active"));
  } catch (error) {
    $("notebook-search-results").textContent = error.message;
  }
});

$("export-notebook").addEventListener("click", () => {
  if (selectedAgent) location.href = `/pwa/api/notebooks/${encodeURIComponent(selectedAgent)}/export`;
});

async function setConditioning(enabled) {
  if (!selectedAgent) return;
  const form = new FormData($("conditioning-form"));
  const mbti = String(form.get("mbti_tag") || "").trim().toUpperCase() || null;
  try {
    await mutate(`/pwa/api/notebooks/conditioning/${encodeURIComponent(selectedAgent)}`, "PUT", {
      enabled,
      profile_id: enabled ? "owner-configured" : "neutral",
      decision_style: String(form.get("decision_style")),
      challenge_style: String(form.get("challenge_style")),
      directness: 0.5,
      exploration: 0.5,
      collaboration: 0.5,
      verbosity: Number(form.get("verbosity")),
      mbti_tag: mbti,
    });
    $("conditioning-state").textContent = enabled ? "Enabled" : "Disabled by default";
    $("conditioning-state").className = "pill " + (enabled ? "warn" : "");
  } catch (error) {
    $("notebook-search-results").textContent = error.message;
  }
}

$("conditioning-form").addEventListener("submit", event => {
  event.preventDefault();
  setConditioning(true);
});
$("disable-conditioning").addEventListener("click", () => setConditioning(false));

for (const button of document.querySelectorAll("[data-tab]")) {
  button.addEventListener("click", () => {
    for (const item of document.querySelectorAll("[data-tab]")) item.classList.toggle("active", item === button);
    const notebooks = button.dataset.tab === "notebooks";
    $("workflow-panel").classList.toggle("hidden", notebooks);
    $("notebooks-panel").classList.toggle("hidden", !notebooks);
    if (notebooks) void loadNotebooks();
  });
}

(async () => {
  if (await loadSession()) {
    await loadTemplates();
    await loadRuns();
  }
})();
