import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {ClientError,sessionActive,retryable} from './core.mjs';

const read=name=>readFileSync(new URL(name,import.meta.url),'utf8');
const app=read('./app.mjs'),html=read('./index.html'),css=read('./style.css');
const section=(start,end)=>{const a=app.indexOf(start),b=app.indexOf(end,a);assert.ok(a>=0&&b>a);return app.slice(a,b);};
const stateFunction=section('function workspaceConnectionState(','\nfunction connectionFailure(');
const failureFunction=section('function connectionFailure(','\nconst show=');
const revalidateFunction=section('async function revalidateSession(','\nasync function connectSession(');
const state=vm.runInNewContext(`${stateFunction};workspaceConnectionState`);

test('all eight connection states are explicit and only observed ONLINE enables work',()=>{
  for(const name of ['ONLINE','CONNECTING','RECONNECTING','OFFLINE','AUTH_REQUIRED','SESSION_EXPIRED','SERVICE_UNAVAILABLE','ERROR']){
    const value=state({online:true,sessionValid:true,state:name});
    assert.equal(value.state,name);assert.equal(value.ready,name==='ONLINE');assert.equal(typeof value.label,'string');
  }
  assert.equal(state({online:true,sessionValid:false,state:'ONLINE'}).state,'SESSION_EXPIRED');
  assert.equal(state({online:false,sessionValid:true,state:'ONLINE'}).state,'OFFLINE');
  for(const unsafe of [null,'UNKNOWN','PASS',1,true,'__proto__'])assert.equal(state({online:true,sessionValid:true,state:unsafe}).state,'ERROR');
  assert.equal(state({online:'true',sessionValid:true,state:'ONLINE'}).ready,false);
  assert.equal(state({online:true,sessionValid:'true',state:'ONLINE'}).ready,false);
});

function sessionHarness({value,health={state:'READY'},failure,hasConnected=false}={}){
  const calls=[],detail={textContent:''};
  const context=vm.createContext({session:null,hasConnected,connectionState:'CONNECTING',
    navigator:{onLine:true},monitor:{abort(){}},sessionActive,ClientError,retryable,
    controls(){},$(id){assert.equal(id,'session-detail');return detail;},
    api:{async session(){calls.push('session');return value;},async request(path,options){calls.push({path,options});if(failure)throw failure;return health;}}});
  vm.runInContext(`${stateFunction};${failureFunction};${revalidateFunction}`,context);
  return {context,calls,detail,run:()=>vm.runInContext('revalidateSession()',context)};
}
const authenticated=()=>({protocol:'jarvis.interface.v1',authenticated:true,expiresAt:Date.now()/1000+600,role:'MEMBER',clientId:'fixture-only'});

test('current session plus one authenticated bounded health READY is required for Online',async()=>{
  const h=sessionHarness({value:authenticated()});await h.run();
  assert.equal(h.context.connectionState,'ONLINE');assert.equal(h.context.hasConnected,true);
  assert.equal(h.calls.length,2);assert.equal(h.calls[1].path,'/interface/v1/health');
  assert.equal(h.calls[1].options.timeout,5000);assert.equal(h.calls[1].options.retry,undefined);
  assert.ok(!h.detail.textContent.includes('fixture-only'));
});
test('missing auth never probes health and keeps genuine recovery enrollment possible',async()=>{
  for(const previous of [false,true]){
    const h=sessionHarness({value:{protocol:'jarvis.interface.v1',authenticated:false},hasConnected:previous});
    await h.run();assert.deepEqual(h.calls,['session']);assert.equal(h.context.session,null);
    assert.equal(h.context.connectionState,previous?'SESSION_EXPIRED':'AUTH_REQUIRED');
  }
});
test('malformed protocol, literal-auth and expired session cannot become Online',async()=>{
  for(const delta of [{protocol:'old'},{authenticated:'true'},{expiresAt:1}]){
    const h=sessionHarness({value:{...authenticated(),...delta}});
    await assert.rejects(h.run(),e=>e.code==='protocol');assert.deepEqual(h.calls,['session']);
    assert.equal(h.context.connectionState,'ERROR');
  }
});
test('session alone or unready/ambiguous service response does not claim runtime health',async()=>{
  for(const health of [{state:'UNKNOWN'},null,{state:true},{}]){
    const h=sessionHarness({value:authenticated(),health});await assert.rejects(h.run());
    assert.equal(h.context.connectionState,'SERVICE_UNAVAILABLE');assert.equal(h.calls.length,2);
  }
  const h=sessionHarness({value:authenticated(),failure:new TypeError('sensitive network detail')});
  await assert.rejects(h.run());assert.equal(h.context.connectionState,'ERROR');assert.equal(h.calls.length,2);
});
test('health auth expiry is distinct from server capacity and does not automatically replay',async()=>{
  for(const status of [401,429,503]){
    const h=sessionHarness({value:authenticated(),failure:new ClientError('http',status),hasConnected:true});
    await assert.rejects(h.run());assert.equal(h.calls.length,2);
    assert.equal(h.context.connectionState,status===401?'SESSION_EXPIRED':'SERVICE_UNAVAILABLE');
  }
});
test('workspace preserves real recovery, task evidence, file and voice paths without fake login features',()=>{
  for(const id of ['enrollment-form','enrollment-code','objective-form','attachment-list','record-button','previous-result','artifact-list','copy-task','execution-metadata','connection-retry'])assert.ok(html.includes(`id="${id}"`));
  assert.ok(html.includes('DEVICE SETUP &amp; RECOVERY'));assert.ok(html.includes('A new sign-in method is not available yet'));
  assert.ok(!html.includes('<style>'));assert.ok(!html.includes('onclick='));
  assert.ok(!/Sign in with Google|Sign in with Apple|Use a passkey/.test(html));
  assert.ok(app.includes("button.dataset.taskId=item.id"));assert.ok(app.includes("element('strong','Saved task')"));
  assert.ok(app.includes("api.request('/interface/v1/health',{timeout:5000})"));
  assert.ok(!app.includes("ready?'Connected to PRIME'"));
  assert.ok(app.includes("show('control-center-link',sessionActive(session)&&session.role==='OWNER')"));
  assert.ok(html.includes('href="/pwa/control-center"'));assert.ok(!html.includes('href="/control"'));
});
test('mobile/Desktop layout and CSP-compatible CSS preserve focus, safe areas and reduced motion',()=>{
  assert.ok(css.indexOf('/* Product boundary')>css.indexOf(':root{color-scheme:dark'));
  for(const token of ['100svh','100dvh','safe-area-inset-top','safe-area-inset-bottom','@media(min-width:900px)','@media(max-width:600px)','focus-visible','prefers-reduced-motion','min-height:54px','min-height:44px'])assert.ok(css.includes(token),token);
  assert.ok(html.includes('viewport-fit=cover'));assert.ok(html.includes('role="status" aria-live="polite"'));
});
test('shell generation is coherent and protected Control Center never enters offline cache',()=>{
  const sw=read('./sw.js'),release=read('./release.mjs');
  assert.equal(sw.match(/const CACHE='([^']+)'/)[1],release.match(/const RELEASE='([^']+)'/)[1]);
  assert.equal(sw.match(/const CACHE='([^']+)'/)[1],'jarvis-shell-v15');
  assert.ok(!sw.includes('/pwa/control-center'));assert.ok(!sw.includes('/pwa/api/control-center'));
  assert.ok(sw.includes('url.search||!SHELL.includes(url.pathname)'));
  assert.ok(sw.includes("event.request.method!=='GET'"));
});
