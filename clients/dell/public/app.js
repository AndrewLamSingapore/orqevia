const $ = id => document.getElementById(id);
let activeTask = '';
let events;

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || `Request failed (${response.status})`);
  return value;
}

function showTask(task) {
  activeTask = task.taskId;
  $('taskId').textContent = task.taskId || 'No active task';
  $('state').textContent = task.state;
  $('message').textContent = task.message || 'No status detail supplied.';
  $('cancel').disabled = !activeTask || ['COMPLETED', 'FAILED'].includes(task.state);
  $('refresh').disabled = !activeTask;
  if (['COMPLETED', 'FAILED'].includes(task.state)) loadArtifacts();
}

function connectEvents(taskId) {
  events?.close();
  events = new EventSource(`/api/tasks/${encodeURIComponent(taskId)}/events`);
  events.onmessage = event => { try { showTask(JSON.parse(event.data)); } catch {} };
  events.onerror = () => { $('message').textContent = 'Status stream interrupted. ORQEVIA will reconnect automatically.'; };
}

async function loadArtifacts() {
  if (!activeTask) return;
  try {
    const value = await api(`/api/tasks/${encodeURIComponent(activeTask)}/artifacts`);
    const items = Array.isArray(value.artifacts) ? value.artifacts : [];
    $('artifacts').className = items.length ? '' : 'empty';
    $('artifacts').innerHTML = items.length ? items.map(item => `<div class="artifact"><div><strong>${escapeHtml(item.name || item.artifactId)}</strong><small>${escapeHtml(item.type || 'file')} · ${escapeHtml(item.status || 'UNKNOWN')} · ${escapeHtml(item.sha256 || 'hash unavailable')}</small></div><a href="/api/artifacts/${encodeURIComponent(item.artifactId)}/download"><button>Download</button></a></div>`).join('') : 'No artifacts reported for this task.';
  } catch (error) { $('artifacts').className = 'empty error'; $('artifacts').textContent = error.message; }
}

function escapeHtml(value) { const span = document.createElement('span'); span.textContent = String(value); return span.innerHTML; }

$('send').onclick = async () => {
  const objective = $('objective').value.trim();
  if (!objective) return;
  $('send').disabled = true;
  try {
    const task = await api('/api/objectives', { method: 'POST', headers: { 'content-type': 'application/json', 'idempotency-key': crypto.randomUUID() }, body: JSON.stringify({ objective }) });
    showTask(task); connectEvents(task.taskId); $('objective').value = '';
  } catch (error) { $('message').className = 'error'; $('message').textContent = error.message; }
  finally { $('send').disabled = false; }
};
$('cancel').onclick = async () => { try { showTask(await api(`/api/tasks/${encodeURIComponent(activeTask)}/cancel`, { method: 'POST' })); } catch (error) { $('message').textContent = error.message; } };
$('refresh').onclick = loadArtifacts;

try {
  const status = await api('/api/local/status');
  $('connection').textContent = status.configured ? 'LOCKED TO ABEX' : 'SETUP REQUIRED';
  $('connection').classList.toggle('error', !status.configured);
  $('identity').textContent = status.configured ? `${status.expectedHost} · ${status.upstream} · ${status.clientId}` : status.errors.join(' · ');
  $('send').disabled = !status.configured;
  $('message').textContent = status.configured ? 'Ready to verify ABEX identity and submit an objective.' : 'Fail-closed: configure the approved ABEX endpoint, identity pin and client credential.';
} catch (error) { $('connection').textContent = 'LOCAL ERROR'; $('message').textContent = error.message; }
