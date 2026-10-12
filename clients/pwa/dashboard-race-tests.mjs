// Pure deferred-response regression fixtures, not live browser acceptance.
// Usage: node dashboard-race-regressions.mjs ABSOLUTE_PATH_TO_dashboard.mjs
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
import test, {afterEach} from 'node:test';

const target=new URL('./dashboard.mjs',import.meta.url);
assert.ok(target,'Supply source or proposed dashboard path.');
const core=new URL('./core.mjs',import.meta.url).href;
const source=readFileSync(target,'utf8').replace("'./core.mjs'",JSON.stringify(core));
const settle=()=>new Promise(resolve=>setTimeout(resolve,0));
let fixtureSerial=0;
let activeRequests=[];
afterEach(async()=>{for(const request of activeRequests){if(!request.settled)request.resolve(new Response('{}',{status:401,headers:{'content-type':'application/json','X-PRIME-Protocol':'jarvis.interface.v1'}}));}await settle();});

async function fixture(){
  const nodes=new Map(), listeners=new Map(), documentListeners=new Map(), intervals=[];
  const node=()=>({textContent:'',children:[],classList:{toggle(){}},setAttribute(){},replaceChildren(){this.children=[];},append(...v){this.children.push(...v);}});
  globalThis.document={hidden:false,getElementById(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);},querySelectorAll(){return [];},createElement:node,addEventListener(name,fn){documentListeners.set(name,fn);}};
  globalThis.window={addEventListener(name,fn){listeners.set(name,fn);},dispatchEvent(event){listeners.get(event.type)?.(event);},scrollTo(){}};
  Object.defineProperty(globalThis,'navigator',{value:{onLine:true},configurable:true});
  globalThis.setInterval=(fn,ms)=>{intervals.push({fn,ms});return intervals.length;};
  const requests=[];
  activeRequests=requests;
  // Deliberately ignores abort: verifies caller guards even after response raced cancellation.
  globalThis.fetch=(url,options)=>new Promise((resolve,reject)=>{const request={url,options,settled:false,resolve(value){this.settled=true;resolve(value);},reject(value){this.settled=true;reject(value);}};requests.push(request);});
  const encoded=Buffer.from(source+'\n// fixture '+(++fixtureSerial)).toString('base64');
  await import('data:text/javascript;base64,'+encoded);
  return {nodes,listeners,documentListeners,intervals,requests,
    session(value){listeners.get('orqevia-session')({detail:value?{...value,clientId:'fixture-client',generation:1}:null});},
    respond(i,instance='CURRENT',observed=Date.now(),audience='fixture-client'){
      requests[i].resolve(new Response(JSON.stringify({schema_version:'orqevia.telemetry.v1',observed_at:new Date(observed).toISOString(),freshness_seconds:60,
        audience:{client_id:audience},metrics:[{metric_id:'registered_agents',collection_status:'OBSERVED',value:21}],source:{instance,revision:'a'.repeat(40)},
        agents:Array.from({length:21},(_,n)=>({agent_id:`fixture-${n}`,name:'fixture',registration:'REGISTERED',availability:'UNKNOWN'}))}),
        {status:200,headers:{'content-type':'application/json','X-PRIME-Protocol':'jarvis.interface.v1'}}));
    }
  };
}

test('No telemetry request until authenticated session is confirmed',async()=>{
  const f=await fixture();assert.equal(f.requests.length,0);
  f.session({role:'MEMBER'});assert.equal(f.requests.length,1);
  f.respond(0);await settle();assert.equal(f.nodes.get('telemetry-state').textContent,'OBSERVED');
});

test('a valid-looking measurement addressed to a different client is rejected',async()=>{
  const f=await fixture();f.session({role:'MEMBER'});f.respond(0,'OTHER',Date.now(),'other-client');await settle();
  assert.equal(f.nodes.get('telemetry-state').textContent,'UNKNOWN');assert.equal(f.nodes.get('agent-provenance-list').children.length,0);
});

test('task events require the current client and ownership generation',async()=>{
  const f=await fixture();f.session({role:'MEMBER'});
  const task={id:'owned-task',agents:['a02'],state:'COMPLETED',revision:1,clientId:'fixture-client',generation:1};
  f.listeners.get('orqevia-task')({detail:task});assert.equal(f.nodes.get('activity-state').textContent,'OWNED TASK OBSERVATIONS');
  const before=f.nodes.get('dashboard-task-rows').children[0];
  for(const wrong of [{clientId:'other-client'},{generation:0}])f.listeners.get('orqevia-task')({detail:{...task,id:'other-task',...wrong}});
  assert.equal(f.nodes.get('dashboard-task-rows').children[0],before);
  f.session({role:'MEMBER'});assert.equal(f.nodes.get('activity-state').textContent,'OWNED TASK OBSERVATIONS');
  f.session(null);assert.equal(f.nodes.get('activity-state').textContent,'UNAVAILABLE');
});

test('A delayed prior-session success cannot repopulate telemetry after logout',async()=>{
  const f=await fixture();f.session({role:'OWNER'});assert.equal(f.requests.length,1);
  f.session(null);assert.equal(f.nodes.get('telemetry-state').textContent,'UNAUTHORIZED');
  f.respond(0,'OLD-SESSION');await settle();
  assert.equal(f.nodes.get('telemetry-state').textContent,'UNAUTHORIZED');
  assert.equal(f.nodes.get('agent-provenance-list').children.length,0);
  assert.doesNotMatch(f.nodes.get('telemetry-source').textContent,/OLD-SESSION/);
});

test('A delayed old authorization failure cannot erase a newer session measurement',async()=>{
  const f=await fixture();f.session({role:'OWNER'});f.session(null);f.session({role:'MEMBER'});
  assert.equal(f.requests.length,2);f.respond(1,'NEW-SESSION');await settle();
  f.requests[0].resolve(new Response('{}',{status:401,headers:{'content-type':'application/json','X-PRIME-Protocol':'jarvis.interface.v1'}}));await settle();
  assert.equal(f.nodes.get('telemetry-state').textContent,'OBSERVED');
  assert.match(f.nodes.get('telemetry-source').textContent,/NEW-SESSION/);
  assert.equal(f.nodes.get('agent-provenance-list').children.length,21);
});

test('Offline invalidation rejects late success and clears provenance rows',async()=>{
  const f=await fixture();f.session({role:'MEMBER'});
  navigator.onLine=false;f.listeners.get('offline')();f.respond(0);await settle();
  assert.equal(f.nodes.get('telemetry-state').textContent,'OFFLINE');
  assert.equal(f.nodes.get('agent-provenance-list').children.length,0);
});

test('Expired observed data becomes stale with empty agent rows',async()=>{
  const f=await fixture();f.session({role:'MEMBER'});f.respond(0,'CURRENT',Date.now()-59000);await settle();
  assert.equal(f.nodes.get('agent-provenance-list').children.length,21);
  const originalNow=Date.now;
  try{Date.now=()=>originalNow()+2000;f.intervals.find(x=>x.ms===5000).fn();}
  finally{Date.now=originalNow;}
  assert.equal(f.nodes.get('telemetry-state').textContent,'STALE');
  assert.equal(f.nodes.get('registered-count').textContent,'—');
  assert.equal(f.nodes.get('agent-provenance-list').children.length,0);
});

test('Visibility suspension releases a pending slot without accepting the old response',async()=>{
  const f=await fixture();f.session({role:'MEMBER'});
  document.hidden=true;f.documentListeners.get('visibilitychange')();
  document.hidden=false;f.documentListeners.get('visibilitychange')();
  assert.equal(f.requests.length,2);f.respond(1,'FOREGROUND');await settle();f.respond(0,'BACKGROUND');await settle();
  assert.match(f.nodes.get('telemetry-source').textContent,/FOREGROUND/);
  assert.doesNotMatch(f.nodes.get('telemetry-source').textContent,/BACKGROUND/);
});
