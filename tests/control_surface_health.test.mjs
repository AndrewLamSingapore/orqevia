import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('../app/control_surface.html', import.meta.url), 'utf8');
const healthSource = source.slice(source.indexOf('async function health(){'), source.indexOf('async function loadOverview(){'));
const overviewSource = source.slice(source.indexOf('async function loadOverview(){'), source.indexOf('async function loadSystem(){'));

test('a reachable 503 health response is degraded, while transport failure is unknown', async () => {
  for (const [response, expected, label] of [
    [{ok:true, status:200, json:async()=>({ok:true,integrity:'ok',models:{ready:true}})}, 'healthy', '● PRIME healthy'],
    [{ok:false, status:503, json:async()=>({ok:false,integrity:'ok',models:{ready:false}})}, 'degraded', '● PRIME degraded'],
  ]) {
    const node = {};
    const health = new Function('fetch', '$', `${healthSource}; return health;`)(async()=>response,()=>node);
    const observed = await health();
    assert.equal(observed.state, expected);
    assert.equal(node.textContent, label);
  }
  const node = {};
  const health = new Function('fetch', '$', `${healthSource}; return health;`)(async()=>{throw new TypeError('offline')},()=>node);
  assert.deepEqual(await health(), {state:'unknown',integrity:'UNKNOWN',modelsReady:null});
  assert.equal(node.textContent, '● PRIME unavailable');
});

test('contradictory health status and payload cannot render healthy', async () => {
  for (const response of [
    {status:503, json:async()=>({ok:true,integrity:'ok',models:{ready:true}})},
    {status:200, json:async()=>({ok:false,integrity:'ok',models:{ready:false}})},
  ]) {
    const node = {};
    const health = new Function('fetch', '$', `${healthSource}; return health;`)(async()=>response,()=>node);
    assert.deepEqual(await health(), {state:'unknown',integrity:'UNKNOWN',modelsReady:null});
    assert.equal(node.textContent, '● PRIME unavailable');
  }
});

test('overview uses observed health instead of defaulting a missing status field to healthy', async () => {
  const nodes = Object.fromEntries(['overviewMetrics','guidance','priorities'].map(id=>[id,{innerHTML:''}]));
  const api = async path => path==='/api/status'?{agent_jobs:0}:[];
  const observed = {state:'degraded',integrity:'ok',modelsReady:false};
  const loadOverview = new Function('api','health','$','esc','items',`${overviewSource}; return loadOverview;`)(
    api, async()=>observed, id=>nodes[id], value=>String(value), (id,rows)=>{nodes[id].innerHTML=String(rows.length)},
  );
  await loadOverview();
  assert.match(nodes.overviewMetrics.innerHTML, /degraded/);
  assert.match(nodes.guidance.innerHTML, /Model readiness: not ready/);
  assert.doesNotMatch(nodes.guidance.innerHTML, /PRIME integrity.*healthy/);
});
