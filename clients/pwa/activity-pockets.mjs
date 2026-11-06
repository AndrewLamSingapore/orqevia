import {canonicalView, errorMessage, safeID} from './core.mjs';

// Activity runs share the existing workspace, session and owned service.
const root = typeof document === 'undefined' ? null : document.getElementById('activity-pockets-module');
if (root) {
  let session = null;
  let active = canonicalView(new URL(location.href).searchParams.get('view'));
  let generation = 0;
  let request = null;
  const make = (tag, text) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = String(text);
    return node;
  };
  async function api(path = '', body, key) {
    const headers = {'X-ORQEVIA-PWA': '1'};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (key) headers['Idempotency-Key'] = key;
    const response = await fetch('/api/activity-pockets' + path, {
      method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin',
      headers, signal: request.signal,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) throw Object.assign(new Error('Activity request failed'), {status: response.status});
    return response.json();
  }
  async function render() {
    const epoch = ++generation;
    request?.abort();
    request = new AbortController();
    root.replaceChildren();
    if (active !== 'workspace' || !session?.authenticated) return;
    root.append(make('h3', 'Activity runs'));
    const state = make('p', 'Loading your activity runs…');
    state.setAttribute('role', 'status');
    state.setAttribute('aria-live', 'polite');
    root.append(state);
    try {
      const [health, response] = await Promise.all([api('/status'), api()]);
      if (epoch !== generation) return;
      const sources = (Array.isArray(health.sources) ? health.sources : []).filter(source => safeID(source.id));
      state.textContent = sources.length
        ? 'Run bounded catalogue extraction from your approved sources using tested extraction rules. Agent role evidence is shown separately.'
        : 'No approved catalogue source is configured. Existing runs and evidence stay available.';
      const refresh = make('button', 'Refresh activity runs');
      refresh.type = 'button';
      refresh.addEventListener('click', () => void render());
      root.append(refresh);
      const items = Array.isArray(response) ? response : response.items || response.pockets || [];
      const list = make('div');
      for (const item of items) {
        if (!safeID(item.id)) continue;
        const card = make('article');
        card.className = 'oq-module';
        card.append(make('h4', item.manifest?.objective || item.objective || 'Activity run'));
        card.append(make('p', item.state || 'State unavailable'));
        for (const action of ['pause', 'resume', 'cancel', 'retire']) {
          const button = make('button', action[0].toUpperCase() + action.slice(1));
          button.type = 'button';
          button.addEventListener('click', async () => {
            if (button.disabled || epoch !== generation) return;
            button.disabled = true;
            try {
              await api('/' + encodeURIComponent(item.id) + '/' + action, {idempotency_key: crypto.randomUUID()});
              if (epoch === generation) await render();
            } catch (error) {
              if (epoch === generation) { state.textContent = errorMessage(error); button.disabled = false; }
            }
          });
          card.append(button);
        }
        const archive = make('button', 'Read preserved results');
        archive.type = 'button';
        archive.addEventListener('click', async () => {
          try {
            const value = await api('/' + encodeURIComponent(item.id) + '/archive');
            if (epoch !== generation) return;
            const details = make('details');
            details.append(make('summary', 'Preserved activity results'));
            const content = make('pre', JSON.stringify(value.outputs || [], null, 2));
            content.style.whiteSpace = 'pre-wrap';
            content.style.overflowWrap = 'anywhere';
            details.append(content);
            card.append(details);
            details.open = true;
          } catch (error) { if (epoch === generation) state.textContent = errorMessage(error); }
        });
        card.append(archive);
        list.append(card);
      }
      root.append(list);
      if (!items.length) list.append(make('p', 'You have no activity runs yet.'));
      if (!sources.length) return;
      const form = make('form');
      const label = make('label', 'Activity objective');
      const objective = make('textarea');
      objective.required = true;
      objective.minLength = 10;
      objective.maxLength = 4000;
      label.append(objective);
      const sourceLabel = make('label', 'Approved source');
      const source = make('select');
      for (const value of sources) { const option = make('option', value.id); option.value = value.id; source.append(option); }
      sourceLabel.append(source);
      const submit = make('button', 'Create activity run');
      submit.type = 'submit';
      form.append(label, sourceLabel, submit);
      let retryKey = crypto.randomUUID();
      form.addEventListener('input', () => { retryKey = crypto.randomUUID(); });
      form.addEventListener('submit', async event => {
        event.preventDefault();
        if (submit.disabled || epoch !== generation) return;
        submit.disabled = true;
        try {
          await api('/create', {objective: objective.value, source_id: source.value}, retryKey);
          if (epoch === generation) await render();
        } catch (error) {
          if (epoch === generation) { state.textContent = errorMessage(error); submit.disabled = false; }
        }
      });
      root.append(form);
    } catch (error) { if (epoch === generation && error.name !== 'AbortError') state.textContent = errorMessage(error); }
  }
  window.addEventListener('orqevia-view', event => { active = canonicalView(event.detail.name); void render(); });
  window.addEventListener('orqevia-session', event => { session = event.detail; void render(); });
}
