'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ui = require('../app/gods_eye.js');
const registry = require('../config/agent_registry.json');
const TASK = '687845ae-6032-4355-a5e2-f124c8b22e07';
const fixture = () => ({schema_version: ui.SCHEMA, observed_at: '2026-10-07T04:00:00Z', status: 'OBSERVED',
  registry: {agent_ids: registry.agents.map(row => row.agent_id), registry_version: registry.registry_version},
  runtime: {status: 'HEALTHY', source_revision: 'a'.repeat(40), environment: 'ISOLATED', verification: 'UNVERIFIED'},
  agents: registry.agents.map(row => ({agent_id: row.agent_id, name: row.name, role: row.role,
    runtime_activation: 'UNVERIFIED', proven: {level: 'L0', trust_state: 'UNPROVEN'}, quality: null, latency_ms: null, cost_usd: null}))});
const response = value => ({ok: true, headers: {get: () => null}, text: async () => JSON.stringify(value)});

test('unknown, nullable and unsupported metric data cannot become zero', () => {
  for (const value of [undefined, null, false, true, NaN, Infinity, {}, {value: 0, status: 'UNKNOWN'}]) {
    assert.equal(ui.metric(value), 'UNKNOWN');
  }
  assert.equal(ui.metric(0), '0');
  assert.equal(ui.metric({value: 0, status: 'OBSERVED', unit: 'ms'}), '0 ms');
});

test('HF view cannot turn missing metadata or credential readiness into live health', () => {
  assert.equal(ui.hfView({schema_version: 'future', registration_status: 'CONFIGURED'}).registration, 'UNKNOWN');
  const result = ui.hfView({schema_version: 'jarvis.hf-operational-profile.v1',
    observation_status: 'OBSERVED_DOMAIN_METADATA_UNVERIFIED', registration_status: 'CONFIGURED',
    providers: [{provider_id: 'hf-one', readiness: 'READY', provider_health: 'UNMEASURED', qualification_verification: 'UNVERIFIED'}],
    agents: [{agent_id: 'a20', applicability: 'OPTIONAL', last_dated_success: null, l7_count: 21, token: 'DO_NOT_RENDER_PRIVATE'}]});
  assert.equal(result.providers[0].readiness, 'READY');
  assert.equal(result.providers[0].health, 'UNMEASURED');
  assert.equal(result.agents[0].execution, 'UNKNOWN');
  assert.doesNotMatch(JSON.stringify(result), /DO_NOT_RENDER_PRIVATE|l7_count/);
});

test('actual HF renderer preserves optionality, dated evidence and verification boundaries', async () => {
  const value = fixture();
  value.hugging_face = {schema_version: 'jarvis.hf-operational-profile.v1',
    registration_status: 'CONFIGURED', observation_status: 'OBSERVED_DOMAIN_METADATA_UNVERIFIED',
    providers: [{provider_id: 'hf-one', model: 'fixture/model:provider', readiness: 'READY',
      provider_health: 'UNMEASURED', qualification_verification: 'UNVERIFIED', circuit_state: 'CLOSED'}],
    agents: [{agent_id: 'a20', applicability: 'OPTIONAL', role_quality: 'UNKNOWN', failover_observation: 'UNKNOWN',
      last_dated_success: {status: 'OBSERVED_DATED_EXECUTION_NOT_QUALITY_OR_HEALTH', objective_id: TASK,
        job_completed_at: '2026-10-07T04:00:00Z'}, token: 'DO_NOT_RENDER_PRIVATE'}]};
  const result = await browserFixture(value), rendered = result.nodes.get('inference-content').textContent;
  assert.match(rendered, /OPTIONAL/); assert.match(rendered, /UNMEASURED/);
  assert.match(rendered, /UNVERIFIED/); assert.match(rendered, /PROVE IT/);
  assert.doesNotMatch(rendered, /DO_NOT_RENDER_PRIVATE/);
  assert.deepEqual(result.urls, ['/control/api/gods-eye']);
});

test('L7 count requires scoped certification status and literal bounded integer, never a signing or task-completion flag', () => {
  for (const value of [{status: 'SIGNED', l7_count: 21}, {status: 'COMPLETED', l7_count: 21},
    {status: 'UNAVAILABLE', l7_count: 0}, {status: 'OBSERVED', l7_count: false},
    {status: 'OBSERVED', l7_count: '21'}, {status: 'OBSERVED', l7_count: 22},
    {status: 'OBSERVED', l7_count: -1}, {}]) assert.equal(ui.certifiedCount(value), 'UNKNOWN');
  assert.equal(ui.certifiedCount({status: 'OBSERVED', l7_count: 0}), '0');
});

test('real noncontiguous 21 identities are preserved without manufacturing A01-A21', () => {
  const result = ui.snapshot(fixture());
  assert.equal(result.validPopulation, true);
  assert.equal(result.agents.length, 21);
  for (const id of ['a26', 'a28', 'a29']) assert.ok(result.agents.some(row => row.agent_id === id));
  assert.equal(result.agents.some(row => row.agent_id === 'a03'), false);
  assert.match(result.populationNote, /shorthand/);
});

test('missing agent rows do not get filled with fictitious identities', () => {
  const value = fixture(); value.agents.pop(); value.registry.agent_ids.pop();
  assert.equal(ui.snapshot(value).validPopulation, false);
  assert.equal(ui.snapshot(value).agents.length, 20);
});

test('duplicates, malformed identity and registry divergence cannot appear as 21 healthy agents', () => {
  for (const mutate of [value => {value.agents[20].agent_id = value.agents[0].agent_id;},
    value => {value.agents[0].agent_id = '../a01';}, value => {value.registry.agent_ids[0] = 'a03';}]) {
    const value = fixture(); mutate(value); const result = ui.snapshot(value);
    assert.equal(result.validPopulation, false); assert.equal(result.agents.length, 0);
  }
});

test('missing or malformed registry bindings and extra identities are not accepted', () => {
  for (const mutate of [value => {delete value.registry;}, value => {value.registry.agent_ids = 'a01';},
    value => {value.registry.count = '21';}, value => {
      value.agents.push({agent_id: 'a30'}); value.registry.agent_ids.push('a30');
    }]) {
    const value = fixture(); mutate(value); assert.equal(ui.snapshot(value).validPopulation, false);
  }
});

test('missing domains remain admissible, unsupported snapshot version fails explicitly', () => {
  assert.equal(ui.snapshot(fixture()).validPopulation, true);
  for (const value of [null, [], {}, {schema_version: 'future.v2'}]) assert.throws(() => ui.snapshot(value), /INCOMPATIBLE/);
});

test('fixed read-only routes preserve actual IDs and safely encoded subjects', () => {
  assert.equal(ui.endpoint('snapshot'), '/control/api/gods-eye');
  assert.equal(ui.endpoint('why', 'a26'), '/control/api/gods-eye/why?agent_id=a26');
  assert.equal(ui.endpoint('dependencies', 'objective:123'), '/control/api/gods-eye/dependencies?subject=objective%3A123');
  assert.equal(ui.endpoint('proof', TASK), '/control/api/evidence/from-objective/' + TASK);
});

test('arbitrary URLs, mutation names and unsafe subjects have no request path', () => {
  for (const [kind, subject] of [['https://evil.example', 'a26'], ['submit', TASK], ['why', '../../token'],
    ['proof', 'https://evil.example'], ['dependencies', 'a01?token=abc'], ['dependencies', '<script>']]) {
    assert.throws(() => ui.endpoint(kind, subject), /INVALID_READ_SUBJECT/);
  }
});

test('stable deep links map to explicit GET handlers only', () => {
  assert.deepEqual(ui.route('#observatory?agent_id=a26'), {section: 'observatory', kind: 'why', subject: 'a26'});
  assert.deepEqual(ui.route('#evidence?task_id=' + TASK), {section: 'evidence', kind: 'proof', subject: TASK});
  assert.deepEqual(ui.route('#gates?subject=a29'), {section: 'gates', kind: 'dependencies', subject: 'a29'});
  assert.deepEqual(ui.route('#observatory?agent_id=https://evil.example'), {section: 'observatory'});
  assert.deepEqual(ui.route('#execute?subject=a01'), {section: 'overview'});
});

test('proof drilldown binds the exact task and cannot upgrade unsigned Lens evidence', () => {
  const value = {record_id: 'objective:' + TASK + ':r1', task_id: TASK, verification: 'UNVERIFIED'};
  assert.equal(ui.drillValue('proof', TASK, value), value);
  assert.equal(ui.drillValue('proof', TASK, {record_id: value.record_id, verification: 'UNVERIFIED', integrity: 'INVALID'}).integrity, 'INVALID');
  for (const changed of [{...value, task_id: 'another-task'}, {...value, record_id: 'objective:wrong:r1'},
    {...value, verification: 'VERIFIED'}, {...value, observed: {task_id: 'another-task'}}]) {
    assert.throws(() => ui.drillValue('proof', TASK, changed), /WRONG_PROOF_BINDING/);
  }
});

test('WHY and dependency drilldowns bind query version, type and requested subject', () => {
  assert.equal(ui.drillValue('why', 'a26', {schema_version: 'prime.semantic.query.v1', query_id: 'why', agent_id: 'a26'}).agent_id, 'a26');
  assert.equal(ui.drillValue('dependencies', 'result-1', {schema_version: 'prime.semantic.query.v1', query_id: 'depends_on', result_id: 'result-1', status: 'UNKNOWN'}).status, 'UNKNOWN');
  for (const value of [{schema_version: 'future.v2', query_id: 'why', agent_id: 'a26'},
    {schema_version: 'prime.semantic.query.v1', query_id: 'why', agent_id: 'a01'},
    {schema_version: 'prime.semantic.query.v1', query_id: 'prove_it', agent_id: 'a26'}]) {
    assert.throws(() => ui.drillValue('why', 'a26', value), /WRONG_SEMANTIC_BINDING/);
  }
});

test('client sends GET with same-origin browser auth and no token or redirect forwarding', async () => {
  let observed;
  const client = ui.createClient(async (url, options) => {observed = {url, options}; return response(fixture());});
  assert.equal((await client.read('snapshot')).schema_version, ui.SCHEMA);
  assert.equal(observed.options.method, 'GET'); assert.equal(observed.options.credentials, 'same-origin');
  assert.equal(observed.options.cache, 'no-store'); assert.equal(observed.options.redirect, 'error');
  assert.deepEqual(observed.options.headers, {Accept: 'application/json'});
  assert.equal(Object.hasOwn(observed.options, 'body'), false);
});

test('overlapping reads are denied and the reservation is released after completion', async () => {
  let release, calls = 0;
  const client = ui.createClient(() => {calls++; return new Promise(resolve => {release = resolve;});});
  const first = client.read('snapshot'); assert.equal(client.busy, true);
  await assert.rejects(client.read('why', 'a26'), /READ_ALREADY_ACTIVE/); assert.equal(calls, 1);
  release(response(fixture())); await first; assert.equal(client.busy, false);
});

test('transport failure does not automatically retry and releases the read gate', async () => {
  let calls = 0;
  const client = ui.createClient(async () => {calls++; throw new Error('offline');});
  await assert.rejects(client.read('snapshot')); assert.equal(calls, 1); assert.equal(client.busy, false);
});

test('HTTP auth failure is not interpreted as an empty healthy snapshot', async () => {
  const client = ui.createClient(async () => ({ok: false, status: 401}));
  await assert.rejects(client.read('snapshot'), /READ_UNAVAILABLE/);
});

test('oversized and malformed response bodies fail without rendering or retry', async () => {
  for (const raw of ['x'.repeat(262145), '"' + '€'.repeat(90000) + '"', '{malformed']) {
    const client = ui.createClient(async () => ({ok: true, text: async () => raw}));
    await assert.rejects(client.read('snapshot')); assert.equal(client.busy, false);
  }
  const client = ui.createClient(async () => ({ok: true, headers: {get: () => '262145'}, text: async () => '{}'}));
  await assert.rejects(client.read('snapshot'), /READ_TOO_LARGE/);
});

test('timeout abort applies to the whole response read and cannot accept late data', async () => {
  let abort, options;
  const client = ui.createClient(async (_, opts) => {options = opts; return {ok: true, text: async () => {abort(); return '{}';}};},
    {setTimeout: callback => {abort = callback; return 1;}, clearTimeout: () => {}});
  await assert.rejects(client.read('snapshot'), /READ_TIMEOUT/);
  assert.equal(options.signal.aborted, true); assert.equal(client.busy, false);
});

test('poller has no overlapping refresh and hidden pages back off', async () => {
  let release, calls = 0, scheduled;
  const poller = ui.createPoller(() => {calls++; return new Promise(resolve => {release = resolve;});},
    {hidden: () => true, setTimeout: (_, delay) => {scheduled = delay; return 1;}, clearTimeout: () => {}});
  const first = poller.tick(); assert.equal(poller.running, true);
  assert.equal(await poller.tick(), false); assert.equal(calls, 1);
  release(); await first; assert.equal(scheduled, 30000); poller.stop(); assert.equal(await poller.tick(), false);
});

test('poll failures back off rather than rapidly retrying', async () => {
  let delay;
  const poller = ui.createPoller(async () => {throw new Error('offline');},
    {setTimeout: (_, value) => {delay = value; return 1;}, clearTimeout: () => {}});
  await poller.tick(); assert.equal(delay, 10000);
  await poller.tick(); assert.equal(delay, 15000); poller.stop();
});

test('stale presentation never leaves the previous runtime health looking current', () => {
  assert.equal(ui.state('HEALTHY', true), 'STALE · HEALTHY');
  assert.equal(ui.state(null, true), 'STALE · UNKNOWN');
});

class Element {
  constructor(tag) {this.tagName = tag; this.children = []; this.attributes = {}; this._text = ''; this.listeners = {};}
  set textContent(value) {this._text = String(value); this.children = [];}
  get textContent() {return this._text + this.children.map(row => row.textContent).join(' ');}
  append(...children) {this.children.push(...children);}
  replaceChildren(...children) {this._text = ''; this.children = children;}
  setAttribute(key, value) {this.attributes[key] = value;}
  getAttribute(key) {return this.attributes[key];}
  removeAttribute(key) {delete this.attributes[key];}
  addEventListener(key, value) {this.listeners[key] = value;}
}
async function browserFixture(value, extraResponses) {
  const nodes = new Map(), events = {}, urls = [];
  const doc = {hidden: false, getElementById(id) {if (!nodes.has(id)) nodes.set(id, new Element('div')); return nodes.get(id);},
    createElement(tag) {return new Element(tag);}, querySelectorAll() {return [];}};
  const win = {location: {hash: '#overview'}, async fetch(url) {
    urls.push(url); return response(extraResponses && Object.hasOwn(extraResponses, url) ? extraResponses[url] : value);
  },
    addEventListener(key, callback) {events[key] = callback;}};
  const controller = ui.start(doc, win);
  await new Promise(resolve => setImmediate(resolve)); events.pagehide();
  return {nodes, urls, events, win, controller, doc};
}

test('actual renderer creates 21 cards and uses inert text for adversarial content', async () => {
  const value = fixture(); value.agents[0].name = '<img src=x onerror=alert(1)>';
  value.secret = 'DO_NOT_RENDER_SECRET'; value.agents[0].token = 'DO_NOT_RENDER_SECRET';
  const result = await browserFixture(value);
  assert.equal(result.nodes.get('agent-cards').children.length, 21);
  assert.match(result.nodes.get('agent-cards').textContent, /<img src=x onerror=alert\(1\)>/);
  assert.doesNotMatch([...result.nodes.values()].map(node => node.textContent).join(' '), /DO_NOT_RENDER_SECRET/);
  assert.deepEqual(result.urls, ['/control/api/gods-eye']);
});

test('actual renderer preserves signed-not-L7 distinction and unknown metrics', async () => {
  const value = fixture(); value.agents[0].trust_state = 'SIGNED';
  const result = await browserFixture(value), rendered = result.nodes.get('agent-cards').textContent;
  assert.match(rendered, /SIGNED/); assert.match(rendered, /L0/); assert.match(rendered, /UNKNOWN/);
  assert.equal(result.nodes.get('overview-cards').children[2].children[1].textContent, 'UNKNOWN');
});

test('actual renderer displays every missing domain as unknown without inventing observations', async () => {
  const result = await browserFixture(fixture());
  for (const id of ['tasks', 'evidence', 'observatory', 'semantics', 'gates']) {
    assert.match(result.nodes.get(id + '-content').textContent, /UNKNOWN/);
    assert.match(result.nodes.get(id + '-content').textContent, /No attributable observations/);
  }
});

test('exact backend array contract renders tasks, semantic results, metrics and gates', async () => {
  const value = fixture();
  value.registry = {count: 21, authoritative_ids: registry.agents.map(row => row.agent_id)};
  value.runtime = {status: 'HEALTHY', reported_source_revision: 'b'.repeat(40), reported_image: 'sha256:' + 'c'.repeat(64),
    identity_verification: 'UNVERIFIED', source: 'RUNTIME', currentness: 'CURRENT_READ'};
  value.agents[0].live_state = 'IDLE'; value.agents[0].current_task_id = TASK;
  value.domains = ['tasks', 'evidence', 'observatory', 'semantics', 'gates'].map(id =>
    ({id, status: 'OBSERVED', source: 'OWNING_' + id, currentness: 'CURRENT_READ'}));
  value.tasks = [{id: TASK, state: 'COMPLETED', agent_id: 'a20', evidence_status: 'UNVERIFIED'}];
  value.results = [{id: 'result-1', task_id: TASK, agent_id: 'a20', integrity: 'VALID', currentness: 'CURRENT', verification: 'UNVERIFIED'}];
  value.metrics = [{metric_id: 'completed_tasks', agent_id: 'a20', result_ids: ['result-1'], value: 1,
    unit: 'tasks', scope: 'BOUNDED_OBSERVED_RESULTS', currentness: 'CURRENT_READ'}];
  value.gates = [{id: 'owner_path', status: 'DEFERRED', reason: 'Owner enrollment parked', source: 'GATE_CONTRACT'}];
  value.evidence = {status: 'OBSERVED', source: 'EVIDENCE_LENS', currentness: 'OBJECTIVE_SCOPED', records: value.results};
  value.observatory = {status: 'PARTIAL', source: 'BOUNDED_DOMAIN_DERIVATION', metrics: value.metrics};
  const result = await browserFixture(value);
  assert.match(result.nodes.get('tasks-content').textContent, /COMPLETED/);
  assert.match(result.nodes.get('evidence-content').textContent, /result-1/);
  assert.match(result.nodes.get('observatory-content').textContent, /1 tasks/);
  assert.match(result.nodes.get('observatory-content').textContent, /BOUNDED_OBSERVED_RESULTS/);
  assert.match(result.nodes.get('gates-content').textContent, /owner_path/);
  assert.match(result.nodes.get('agent-cards').textContent, /IDLE/);
  assert.match(result.nodes.get('snapshot-binding').textContent, /Reported runtime image/);
});

test('semantic summary reports actual formal scope and never promotes compatibility to certification', async () => {
  const value = fixture(); value.semantics = {schema_version: 'prime.semantic.v1', status: 'READY',
    ontology_version: '0.1.0', accepted_results: 1, accepted_metrics: 1, asserted_triples: 43, inferred_triples: 11,
    production_acceptance: 'UNVERIFIED', authority: 'READ_ONLY_REBUILDABLE_DOMAIN_PROJECTION', l7_awarded: false};
  const result = await browserFixture(value), rendered = result.nodes.get('semantics-content').textContent;
  assert.match(rendered, /READ_ONLY_REBUILDABLE_DOMAIN_PROJECTION/);
  assert.match(rendered, /UNVERIFIED/); assert.match(rendered, /43/);
  assert.equal(result.nodes.get('overview-cards').children[2].children[1].textContent, 'UNKNOWN');
});

test('WHY renderer exposes typed source evidence and metric derivation without arbitrary JSON or false certification', async () => {
  const why = {schema_version: 'prime.semantic.query.v1', query_id: 'why', agent_id: 'a26',
    status: 'READY', source_revision: 'a'.repeat(40), authority: 'READ_ONLY_PROJECTION',
    declared_capabilities: [{id: 'responsibility.a26'}],
    result_evidence: [{id: 'result-1', task_id: TASK, environment: 'ISOLATED', verification: 'UNVERIFIED', digest: 'b'.repeat(64)}],
    verified_capability_state: 'NOT_ESTABLISHED_BY_SEMANTICS',
    metrics: [{metric_id: 'observed-task-count:a26', value: 1, unit: 'count', scope: 'BOUNDED_OBSERVED_RESULTS', result_ids: ['result-1']}],
    forbidden_payload: 'DO_NOT_RENDER_PRIVATE'};
  const result = await browserFixture(fixture(), {'/control/api/gods-eye/why?agent_id=a26': why});
  result.win.location.hash = '#observatory?agent_id=a26'; await result.controller.drilldown();
  const rendered = result.nodes.get('drilldown-content').textContent;
  assert.match(rendered, /responsibility\.a26/); assert.match(rendered, /result-1/);
  assert.match(rendered, /Metric derivation/); assert.match(rendered, /BOUNDED_OBSERVED_RESULTS/);
  assert.match(rendered, /UNVERIFIED/); assert.match(rendered, /NOT_ESTABLISHED_BY_SEMANTICS/);
  assert.doesNotMatch(rendered, /DO_NOT_RENDER_PRIVATE/);
  assert.deepEqual(result.urls, ['/control/api/gods-eye', '/control/api/gods-eye/why?agent_id=a26']);
});

test('result dependency deep link renders actual edges, whereas unsupported subjects remain unknown', async () => {
  const dependencies = {schema_version: 'prime.semantic.query.v1', query_id: 'depends_on', result_id: 'result-1',
    status: 'READY', rows: [{metric_id: 'observed-task-count:a26', agent_id: 'a26'}]};
  const result = await browserFixture(fixture(), {'/control/api/gods-eye/dependencies?subject=result-1': dependencies});
  result.win.location.hash = '#gates?subject=result-1'; await result.controller.drilldown();
  assert.match(result.nodes.get('drilldown-content').textContent, /observed-task-count:a26/);
  assert.match(result.nodes.get('drilldown-content').textContent, /a26/);
});

test('legacy Workbench receives only a read-only discovery link and remains a separate experience', () => {
  const source = fs.readFileSync(path.join(__dirname, '../app/production_control.html'), 'utf8');
  assert.match(source, /href="\/control\/gods-eye"/); assert.match(source, /<form id="submit">/);
});

test('refresh failure marks the actual retained display stale and removes old drilldown claims', async () => {
  const value = fixture(); const evolving = await browserFixture(value);
  evolving.doc.getElementById('drilldown').hidden = false;
  evolving.doc.getElementById('drilldown-content').textContent = 'CURRENT proof from earlier read';
  value.schema_version = 'unsupported.v2';
  await assert.rejects(evolving.controller.refresh());
  assert.match(evolving.nodes.get('connection').textContent, /LAST KNOWN \/ STALE/);
  assert.match(evolving.nodes.get('overview-cards').textContent, /STALE/);
  assert.equal(evolving.nodes.get('drilldown-content').textContent, '');
  assert.doesNotMatch(evolving.nodes.get('agent-cards').textContent, /\bHEALTHY\b/);
});

test('frontend does not use unsafe HTML insertion, credentials, persistent browser storage or mutation requests', () => {
  const source = fs.readFileSync(path.join(__dirname, '../app/gods_eye.js'), 'utf8');
  assert.doesNotMatch(source, /innerHTML|outerHTML|insertAdjacentHTML|document\.write|localStorage|sessionStorage|eval\(/);
  assert.doesNotMatch(source, /method:\s*['"](?:POST|PUT|PATCH|DELETE)['"]|Authorization|HF_TOKEN|PRIME_SPINE_TOKEN/);
});
