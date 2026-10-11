(function (root) {
  'use strict';
  const SCHEMA = 'jarvis.gods-eye.v1';
  const SECTIONS = ['overview', 'agents', 'tasks', 'evidence', 'observatory', 'inference', 'semantics', 'gates'];
  const AGENT = /^a[0-9]{2}$/;
  const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
  const SUBJECT = /^[A-Za-z0-9][A-Za-z0-9:._-]{0,159}$/;
  const MAX_RESPONSE = 262144;
  const text = value => typeof value === 'string' && value.length ? value.slice(0, 4000) :
    typeof value === 'number' && Number.isFinite(value) ? String(value) : 'UNKNOWN';
  const object = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const rows = value => Array.isArray(value) ? value.slice(0, 100) : [];

  function metric(value) {
    if (value === null || value === undefined || typeof value === 'boolean') return 'UNKNOWN';
    if (typeof value === 'object') {
      if (['UNKNOWN', 'UNAVAILABLE', 'INVALID', 'UNVERIFIED'].includes(value.status)) return 'UNKNOWN';
      const label = text(value.value);
      return label === 'UNKNOWN' ? label : label + (typeof value.unit === 'string' ? ' ' + value.unit.slice(0, 40) : '');
    }
    return text(value);
  }

  function state(value, stale) {
    const label = text(value);
    return stale ? 'STALE · ' + label : label;
  }

  function certifiedCount(value) {
    const record = object(value);
    return ['OBSERVED', 'VERIFIED'].includes(record.status) && Number.isInteger(record.l7_count) &&
      record.l7_count >= 0 && record.l7_count <= 21 ? String(record.l7_count) : 'UNKNOWN';
  }

  function hfView(value) {
    const part = object(value);
    if (part.schema_version !== 'jarvis.hf-operational-profile.v1') return {
      observation: 'UNKNOWN', registration: 'UNKNOWN', providers: [], agents: []};
    return {observation: text(part.observation_status), registration: text(part.registration_status),
      evidenceWindow: text(part.evidence_window),
      providers: rows(part.providers).slice(0, 32).map(raw => {
        const row = object(raw);
        return {id: text(row.provider_id), model: text(row.model), readiness: text(row.readiness),
          qualification: text(row.qualification_verification), health: text(row.provider_health),
          circuit: text(row.circuit_state)};
      }),
      agents: rows(part.agents).slice(0, 21).filter(raw => AGENT.test(object(raw).agent_id)).map(raw => {
        const row = object(raw), dated = object(row.last_dated_success);
        return {id: row.agent_id, applicability: text(row.applicability),
          execution: text(dated.status), task: typeof dated.objective_id === 'string' && UUID.test(dated.objective_id) ? dated.objective_id : null,
          completed: text(dated.job_completed_at), model: text(dated.selected_model),
          failover: text(row.failover_observation), quality: text(row.role_quality)};
      })};
  }

  function endpoint(kind, subject) {
    if (kind === 'snapshot') return '/api/orqevia/gods-eye';
    if (kind === 'why' && typeof subject === 'string' && AGENT.test(subject)) {
      return '/api/orqevia/gods-eye/why?agent_id=' + encodeURIComponent(subject);
    }
    if (kind === 'dependencies' && typeof subject === 'string' && SUBJECT.test(subject)) {
      return '/api/orqevia/gods-eye/dependencies?subject=' + encodeURIComponent(subject);
    }
    if (kind === 'proof' && typeof subject === 'string' && UUID.test(subject)) {
      return '/api/orqevia/gods-eye/proof?task_id=' + encodeURIComponent(subject);
    }
    throw new Error('INVALID_READ_SUBJECT');
  }

  function route(hash) {
    const match = /^#([a-z]+)(?:\?([^#]*))?$/.exec(typeof hash === 'string' ? hash : '');
    if (!match || !SECTIONS.includes(match[1])) return {section: 'overview'};
    const params = new URLSearchParams(match[2] || '');
    const agent = params.get('agent_id'), task = params.get('task_id'), subject = params.get('subject');
    if (agent && AGENT.test(agent) && match[1] === 'observatory') return {section: match[1], kind: 'why', subject: agent};
    if (task && UUID.test(task) && match[1] === 'evidence') return {section: match[1], kind: 'proof', subject: task};
    if (subject && SUBJECT.test(subject) && match[1] === 'gates') return {section: match[1], kind: 'dependencies', subject};
    return {section: match[1]};
  }

  function snapshot(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value) || value.schema_version !== SCHEMA) {
      throw new Error('INCOMPATIBLE_SNAPSHOT');
    }
    const agents = rows(value.agents);
    const ids = agents.map(row => object(row).agent_id);
    const registry = object(value.registry);
    const declaredValue = registry.authoritative_ids || registry.agent_ids;
    const declared = rows(declaredValue);
    const unique = ids.every(id => typeof id === 'string' && AGENT.test(id)) && new Set(ids).size === ids.length;
    const sameRegistry = Array.isArray(declaredValue) && declared.length === ids.length &&
      new Set(declared).size === declared.length && declared.every(id => typeof id === 'string' && AGENT.test(id) && ids.includes(id));
    const validPopulation = unique && sameRegistry && ids.length === 21 &&
      (registry.count === undefined || registry.count === 21);
    return {value, agents: unique && sameRegistry && ids.length <= 21 ? agents : [], validPopulation,
      populationNote: validPopulation ?
        '21 permanent registry identities. A01–A21 is shorthand, not permission to rename the actual non-contiguous IDs.' :
        'Registry population is incomplete or divergent. No missing agents or certification have been invented.'};
  }

  function drillValue(kind, subject, value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('INVALID_DOMAIN_RESPONSE');
    if (kind === 'proof') {
      const bound = typeof value.record_id === 'string' &&
        new RegExp('^objective:' + subject + ':r[0-9]+$').test(value.record_id);
      if (!bound || value.verification !== 'UNVERIFIED' ||
        value.task_id !== undefined && value.task_id !== subject ||
        object(value.observed).task_id !== undefined && object(value.observed).task_id !== subject) {
        throw new Error('WRONG_PROOF_BINDING');
      }
    } else if (value.schema_version !== 'prime.semantic.query.v1' ||
      kind === 'why' && (value.query_id !== 'why' || value.agent_id !== subject) ||
      kind === 'dependencies' && (value.query_id !== 'depends_on' || value.result_id !== subject)) {
      throw new Error('WRONG_SEMANTIC_BINDING');
    }
    return value;
  }

  function createClient(fetcher, options) {
    const opts = options || {};
    const timer = opts.setTimeout || setTimeout, clear = opts.clearTimeout || clearTimeout;
    let active = false;
    return {
      get busy() {return active;},
      async read(kind, subject) {
        const path = endpoint(kind, subject);
        if (active) throw new Error('READ_ALREADY_ACTIVE');
        active = true;
        const controller = new AbortController();
        const timeout = timer(() => controller.abort(), opts.timeoutMs || 4000);
        try {
          const response = await fetcher(path, {method: 'GET', credentials: 'same-origin',
            cache: 'no-store', redirect: 'error', signal: controller.signal,
            headers: {'Accept': 'application/json'}});
          if (!response || response.ok !== true) throw new Error('READ_UNAVAILABLE');
          const declared = response.headers && response.headers.get('content-length');
          if (declared && (!/^\d+$/.test(declared) || Number(declared) > MAX_RESPONSE)) throw new Error('READ_TOO_LARGE');
          const raw = await response.text();
          if (typeof raw !== 'string' || raw.length > MAX_RESPONSE || new TextEncoder().encode(raw).length > MAX_RESPONSE) {
            throw new Error('READ_TOO_LARGE');
          }
          if (controller.signal.aborted) throw new Error('READ_TIMEOUT');
          return JSON.parse(raw);
        } finally {clear(timeout); active = false;}
      }
    };
  }

  function createPoller(read, options) {
    const opts = options || {}, timer = opts.setTimeout || setTimeout, clear = opts.clearTimeout || clearTimeout;
    let handle, running = false, stopped = false, failures = 0;
    function delay() {return opts.hidden && opts.hidden() ? 30000 : Math.min(30000, 5000 * (1 + failures));}
    function schedule() {if (!stopped) handle = timer(tick, delay());}
    async function tick() {
      if (stopped || running) return false;
      if (handle !== undefined) {clear(handle); handle = undefined;}
      running = true;
      try {await read(); failures = 0;} catch {failures = Math.min(5, failures + 1);}
      finally {running = false; schedule();}
      return true;
    }
    return {tick, stop() {stopped = true; if (handle !== undefined) clear(handle);},
      get running() {return running;}, get nextDelay() {return delay();}};
  }

  function start(document, window) {
    const byId = id => document.getElementById(id);
    const node = (tag, value, className) => {
      const item = document.createElement(tag);
      if (value !== undefined) item.textContent = text(value);
      if (className) item.className = className;
      return item;
    };
    const clear = item => item.replaceChildren();
    const badge = (value, stale) => {
      const label = state(value, stale), level = stale ? 'warning' :
        /^(INVALID|FAIL|FAILED|CONTRADICTED|DIVERGED)$/.test(label) ? 'danger' :
        /^(STALE|DEFERRED|DEGRADED|PARTIAL)$/.test(label) ? 'warning' :
        /^(HEALTHY|COMPLETED)$/.test(label) ? 'positive' : 'neutral';
      return node('span', label, 'badge ' + level);
    };
    const pair = (parent, label, value) => {parent.append(node('dt', label), node('dd', value));};
    const link = (parent, title, hash) => {const anchor = node('a', title); anchor.href = hash; parent.append(anchor);};
    const client = createClient(window.fetch.bind(window));
    let last, lastRead, drillKey;

    function domain(name, value, stale) {
      const host = byId(name + '-content'); clear(host);
      const part = object(value), entries = rows(part.records || part.results || part.metrics || part.rows || part.items);
      host.append(node('p', 'Status: ' + state(part.status, stale) + ' · Domain: ' + text(part.source || part.owner) +
        ' · Currentness: ' + state(part.currentness, stale) + ' · Version: ' + text(part.version || part.schema_version), 'domain-meta'));
      if (name === 'semantics' && typeof part.schema_version === 'string') {
        const summary = node('dl', undefined, 'details-list');
        ['ontology_version', 'shacl_version', 'query_contract_version', 'source_revision', 'snapshot_sha256',
          'asserted_triples', 'inferred_triples', 'accepted_results', 'accepted_metrics', 'production_acceptance',
          'time_freshness', 'authority', 'rdf', 'shacl', 'reasoning'].forEach(field => {
          if (Object.hasOwn(part, field)) pair(summary, field.replaceAll('_', ' '), text(part[field]));
        });
        host.append(summary);
        const quarantined = rows(part.quarantined);
        if (quarantined.length) host.append(node('p', 'Quarantined projected records: ' + quarantined.length +
          '. They do not grant verified capability or routing authority.', 'notice'));
        return;
      }
      if (!entries.length) {host.append(node('p', 'No attributable observations available in this snapshot. UNKNOWN does not mean zero.', 'empty')); return;}
      const wrap = node('div', undefined, 'table-wrap'), table = node('table'), head = node('thead'), body = node('tbody');
      const names = name === 'tasks' ? ['Identity', 'Execution', 'Agent', 'Source / currentness', 'Evidence'] :
        name === 'observatory' ? ['Metric', 'Observed value', 'Agent', 'Source / currentness', 'Derivation'] :
        name === 'gates' ? ['Gate / subject', 'Status', 'Dependency', 'Source / currentness', 'Details'] :
        ['Result / record', 'Claim state', 'Verification', 'Source / currentness', 'Evidence'];
      const header = node('tr'); names.forEach(label => header.append(node('th', label))); head.append(header);
      entries.forEach(raw => {
        const row = object(raw), tr = node('tr'), cells = [];
        const id = name === 'tasks' ? row.task_id || row.id : row.result_id || row.record_id || row.subject || row.id || row.task_id;
        if (name === 'tasks') cells.push(id, state(row.execution_state || row.state || row.status, stale), row.agent_id);
        else if (name === 'observatory') cells.push(row.metric || row.metric_id || row.name,
          metric({value: row.value, unit: row.unit, status: row.status}) + ' · ' + text(row.scope), row.agent_id);
        else if (name === 'gates') cells.push(id, state(row.status, stale), row.dependency_kind || row.dependency);
        else cells.push(id, state(row.claim_state || row.status || row.result_state, stale), row.verification || row.independent_verification);
        cells.push(text(row.source || row.producer) + ' · ' + state(row.currentness, stale));
        cells.forEach(value => tr.append(node('td', value)));
        const actions = node('td');
        if (name === 'observatory' && AGENT.test(row.agent_id)) link(actions, 'WHY', '#observatory?agent_id=' + encodeURIComponent(row.agent_id));
        else if (name === 'gates' && typeof id === 'string' && SUBJECT.test(id)) link(actions, 'Dependencies', '#gates?subject=' + encodeURIComponent(id));
        else if (typeof row.task_id === 'string' && UUID.test(row.task_id)) link(actions, 'PROVE IT', '#evidence?task_id=' + row.task_id);
        else if (name === 'tasks' && typeof row.id === 'string' && UUID.test(row.id)) link(actions, 'PROVE IT', '#evidence?task_id=' + row.id);
        else actions.textContent = 'Reference unavailable';
        if (name === 'evidence' && typeof row.id === 'string' && SUBJECT.test(row.id)) {
          actions.append(node('span', ' · ')); link(actions, 'Dependencies', '#gates?subject=' + encodeURIComponent(row.id));
        }
        tr.append(actions); body.append(tr);
      });
      table.append(head, body); wrap.append(table); host.append(wrap);
    }

    function render(value, stale) {
      const normalized = snapshot(value), runtime = object(value.runtime), registry = object(value.registry);
      byId('snapshot-status').replaceChildren(badge(value.status || value.snapshot_status, stale));
      byId('agent-count').textContent = state(normalized.validPopulation ? '21 / 21 registry rows' : 'UNKNOWN / 21 · DIVERGENCE', stale);
      byId('identity-note').hidden = false; byId('identity-note').textContent = normalized.populationNote;
      const cards = byId('overview-cards'); clear(cards);
      const overview = [
        ['Runtime observation', state(runtime.health || runtime.status || runtime.state, stale), 'Runtime domain, not deployment acceptance'],
        ['Permanent registry', state(normalized.validPopulation ? '21' : 'UNKNOWN', stale), 'No temporary workers counted'],
        ['L7 certification', state(certifiedCount(value.certification), stale), 'Independent per-agent evidence required'],
        ['Evidence currentness', state(object(value.evidence || object(value.domains).evidence).currentness, stale), 'Currentness is scoped to the specific claim']
      ];
      overview.forEach(([label, display, note]) => {const card = node('div', undefined, 'card');
        card.append(node('p', label, 'label'), node('p', display, 'value'), node('p', note, 'note')); cards.append(card);});
      const binding = byId('snapshot-binding'); clear(binding);
      pair(binding, 'Snapshot contract', value.schema_version);
      pair(binding, 'Producer observation', value.observed_at || value.snapshot_at || value.generated_at);
      pair(binding, 'Reported runtime source', runtime.reported_source_revision || runtime.source_revision || value.source_revision);
      pair(binding, 'Reported runtime image', runtime.reported_image || runtime.image_digest);
      pair(binding, 'Environment', runtime.environment || value.environment);
      pair(binding, 'Registry version', registry.version || registry.registry_version);
      pair(binding, 'Runtime binding', runtime.identity_verification || runtime.verification || runtime.binding_status);
      const agents = byId('agent-cards'); clear(agents);
      if (!normalized.agents.length) agents.append(node('p', 'Authoritative agent rows are unavailable or inconsistent.', 'empty'));
      normalized.agents.forEach(raw => {
        const row = object(raw), proven = object(row.proven), provenance = object(row.provenance);
        const card = node('article', undefined, 'card'), heading = node('div', undefined, 'agent-top'), title = node('div');
        title.append(node('p', row.agent_id, 'agent-id'), node('h3', row.name || row.agent_id));
        heading.append(title, badge(row.live_state || row.current_status || row.status || row.runtime_activation, stale));
        card.append(heading, node('p', row.role, 'agent-role'));
        const meta = node('dl', undefined, 'agent-meta');
        pair(meta, 'Certification', state(row.l7_status || row.certification_status || proven.level, stale));
        pair(meta, 'Trust state', row.trust_state || proven.trust_state);
        pair(meta, 'Currentness', state(row.currentness, stale));
        pair(meta, 'Version', row.version || provenance.registry_version);
        pair(meta, 'Source', provenance.source_revision || row.source_revision);
        pair(meta, 'Quality', metric(row.quality));
        pair(meta, 'Latency', metric(row.latency_ms ?? object(row.performance).latency_ms));
        pair(meta, 'Cost', metric(row.cost_usd ?? object(row.performance).cost_usd)); card.append(meta);
        const links = node('div', undefined, 'links');
        link(links, 'WHY / capability', '#observatory?agent_id=' + row.agent_id);
        link(links, 'Dependencies', '#gates?subject=' + row.agent_id);
        const taskId = row.current_task_id || row.task_id;
        if (typeof taskId === 'string' && UUID.test(taskId)) link(links, 'PROVE IT', '#evidence?task_id=' + taskId);
        card.append(links); agents.append(card);
      });
      const hf = hfView(value.hugging_face), inference = byId('inference-content'); clear(inference);
      inference.append(node('p', 'Observation: ' + state(hf.observation, stale) + ' · Registration: ' + state(hf.registration, stale), 'domain-meta'));
      inference.append(node('p', 'Evidence window: ' + text(hf.evidenceWindow) + '. No upstream probe is performed by this view.', 'notice'));
      hf.providers.forEach(row => inference.append(node('p', row.id + ' · ' + row.model +
        ' · Credential readiness: ' + state(row.readiness, stale) + ' · Provider health: ' + state(row.health, stale) +
        ' · Qualification: ' + state(row.qualification, stale) + ' · Process-local circuit: ' + state(row.circuit, stale))));
      hf.agents.forEach(row => {
        const item = node('p', row.id + ' · HF applicability: ' + row.applicability + ' · Execution: ' + state(row.execution, stale) +
          ' · Last completed: ' + row.completed + ' · Failover: ' + state(row.failover, stale) + ' · Role quality: ' + state(row.quality, stale));
        if (row.task) {item.append(node('span', ' · ')); link(item, 'PROVE IT', '#evidence?task_id=' + row.task);}
        inference.append(item);
      });
      ['tasks', 'evidence', 'observatory', 'semantics', 'gates'].forEach(name => {
        const aliases = {evidence: ['evidence', 'evidence_lens'], observatory: ['observatory', 'metrics'],
          tasks: ['tasks', 'execution'], semantics: ['semantics'], gates: ['gates']}[name];
        const metadata = {...object(value[name]),
          ...(rows(value.domains).find(item => aliases.includes(object(item).id)) || object(object(value.domains)[name]))};
        const payload = name === 'evidence' ? value.results || value.evidence :
          name === 'observatory' ? value.metrics || value.observatory : value[name];
        if (Array.isArray(payload)) domain(name, {...metadata, records: payload}, stale);
        else domain(name, {...metadata, ...object(payload)}, stale);
      });
    }

    async function refresh() {
      if (client.busy) throw new Error('READ_ALREADY_ACTIVE');
      byId('refresh').disabled = true;
      try {
        const value = await client.read('snapshot'); snapshot(value);
        last = value; lastRead = new Date().toISOString(); render(last, false);
        byId('connection').textContent = 'Snapshot read. Domain evidence may independently be UNKNOWN, STALE or unverified.';
        byId('read-time').textContent = 'Browser read: ' + lastRead;
      } catch (error) {
        if (last) render(last, true);
        if (!byId('drilldown').hidden) {
          clear(byId('drilldown-content'));
          byId('drilldown-status').textContent = 'Snapshot refresh failed. Reopen the proof link for a new independently dated domain read.';
        }
        byId('connection').textContent = last ? 'Refresh unavailable. All retained observations below are LAST KNOWN / STALE.' :
          'Authenticated snapshot unavailable. No live-state or zero-count claim can be made.';
        byId('read-time').textContent = lastRead ? 'Last successful browser read: ' + lastRead : 'No successful snapshot read.';
        throw error;
      } finally {byId('refresh').disabled = false;}
    }

    async function drilldown() {
      const selected = route(window.location.hash);
      document.querySelectorAll('#navigation a').forEach(anchor => {
        if (anchor.getAttribute('href') === '#' + selected.section) anchor.setAttribute('aria-current', 'page');
        else anchor.removeAttribute('aria-current');
      });
      if (!selected.kind) {byId('drilldown').hidden = true; drillKey = undefined; return;}
      const key = selected.kind + ':' + selected.subject; drillKey = key;
      byId('drilldown').hidden = false;
      byId('drilldown-title').textContent = selected.kind === 'why' ? 'WHY · ' + selected.subject :
        selected.kind === 'proof' ? 'PROVE IT · ' + selected.subject : 'Dependencies · ' + selected.subject;
      byId('drilldown-status').textContent = 'Reading the owning domain…'; clear(byId('drilldown-content'));
      try {
        const value = drillValue(selected.kind, selected.subject, await client.read(selected.kind, selected.subject));
        if (drillKey !== key) return;
        const details = node('dl', undefined, 'details-list');
        const allowed = ['schema_version', 'subject', 'agent_id', 'task_id', 'result_id', 'record_id', 'status',
          'integrity', 'currentness', 'verification', 'independent_signature', 'source', 'source_revision',
          'version', 'environment', 'derivation_version', 'reason', 'explanation', 'dependency_kind', 'next_safe_action',
          'query_id', 'ontology_version', 'snapshot_sha256', 'authority', 'verified_capability_state',
          'certification', 'performance', 'proof_basis'];
        allowed.forEach(field => {if (Object.hasOwn(value, field)) pair(details, field.replaceAll('_', ' '), text(value[field]));});
        const proof = object(value.proof), observed = object(value.observed);
        ['producer', 'captured_at', 'completed_at', 'currentness_basis', 'time_freshness'].forEach(field => {
          if (Object.hasOwn(proof, field)) pair(details, field.replaceAll('_', ' '), text(proof[field]));
        });
        if (observed.result_digest) pair(details, 'Result SHA-256', object(observed.result_digest).value);
        rows(value.source_result_ids || value.result_ids).forEach((id, i) => pair(details, 'Source result ' + (i + 1), id));
        const links = node('div', undefined, 'links');
        rows(value.task_ids).forEach(id => {if (typeof id === 'string' && UUID.test(id)) link(links, 'PROVE IT ' + id, '#evidence?task_id=' + id);});
        byId('drilldown-content').append(details, links);
        function detailsTable(title, records, fields) {
          const entries = rows(records); if (!entries.length) return;
          const table = node('table'), wrap = node('div', undefined, 'table-wrap'), head = node('tr');
          fields.forEach(field => head.append(node('th', field.replaceAll('_', ' ')))); head.append(node('th', 'Proof links'));
          const thead = node('thead'); thead.append(head); const tbody = node('tbody');
          entries.forEach(raw => {
            const entry = object(raw), tr = node('tr');
            fields.forEach(field => tr.append(node('td', field === 'capability' ? text(entry.capability || entry.id) :
              field === 'value' ? metric(entry[field]) :
              field === 'result_ids' ? rows(entry[field]).map(id => text(id)).join(', ') || 'UNKNOWN' : text(entry[field]))));
            const actions = node('td');
            if (typeof entry.task_id === 'string' && UUID.test(entry.task_id)) link(actions, 'PROVE IT', '#evidence?task_id=' + entry.task_id);
            if (typeof entry.id === 'string' && SUBJECT.test(entry.id)) link(actions, 'Dependencies', '#gates?subject=' + encodeURIComponent(entry.id));
            tr.append(actions); tbody.append(tr);
          });
          table.append(thead, tbody); wrap.append(table);
          byId('drilldown-content').append(node('h3', title), wrap);
        }
        detailsTable('Declared capabilities · not verified by graph compatibility', value.declared_capabilities, ['capability']);
        detailsTable('Result evidence references', value.result_evidence, ['id', 'task_id', 'environment', 'verification', 'digest']);
        detailsTable('Metric derivation', value.metrics, ['metric_id', 'value', 'unit', 'scope', 'result_ids']);
        detailsTable('Dependency references', value.rows, ['metric_id', 'agent_id', 'id', 'task_id', 'verification']);
        byId('drilldown-status').textContent = 'Domain read: ' + new Date().toISOString() +
          '. Not a live stream. Unsigned or incomplete evidence is not certification.';
      } catch {
        if (drillKey === key) byId('drilldown-status').textContent = 'Details unavailable or another bounded read is active. No proof has been invented; use Refresh or reopen this link.';
      }
    }

    const poller = createPoller(refresh, {hidden: () => document.hidden});
    byId('refresh').addEventListener('click', () => {void poller.tick();});
    window.addEventListener('hashchange', () => {void drilldown();});
    window.addEventListener('pagehide', () => poller.stop());
    void poller.tick().then(() => drilldown());
    return {refresh, drilldown, poller};
  }

  const api = {SCHEMA, text, metric, state, certifiedCount, hfView, endpoint, route, snapshot, drillValue, createClient, createPoller, start};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else {root.GodsEye = api; if (root.document) start(root.document, root);}
})(typeof window !== 'undefined' ? window : globalThis);
