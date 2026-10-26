// Actual worker/release code in a VM; not physical installed-PWA acceptance.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

function worker({installFails=false}={}){
  const listeners=new Map(),deleted=[],assets=[],existing=new Set(['jarvis-shell-v14','unrelated-product-cache']);let skipped=0,claimed=0;
  const self={location:{origin:'https://candidate.invalid'},addEventListener(name,fn){listeners.set(name,fn);},skipWaiting(){skipped++;},clients:{claim(){claimed++;}}};
  const caches={async open(name){existing.add(name);return {async addAll(values){assets.push(...values);if(installFails)throw new Error('fixture shell download failed');},async match(path){return {cached:path,cache:name};}};},async keys(){return [...existing];},async delete(name){deleted.push(name);existing.delete(name);},async match(){throw new Error('Global cross-generation lookup is forbidden');}};
  vm.runInNewContext(readFileSync(new URL('./sw.js',import.meta.url),'utf8'),{self,caches,URL,Response,fetch:async()=>{throw new Error('fixture offline');}});
  async function lifecycle(name){let awaited;listeners.get(name)({waitUntil(p){awaited=p;}});await awaited;}
  return {listeners,deleted,assets,existing,lifecycle,get skipped(){return skipped;},get claimed(){return claimed;}};
}

test('successful update installs the full new shell before replacing only old app caches',async()=>{
  const w=worker();await w.lifecycle('install');
  assert.ok(w.assets.includes('/pwa/dashboard.mjs'));assert.ok(w.assets.includes('/pwa/dashboard.css'));
  assert.equal(w.skipped,1);assert.ok(w.existing.has('jarvis-shell-v14'));
  await w.lifecycle('activate');assert.deepEqual(w.deleted,['jarvis-shell-v14']);
  assert.ok(w.existing.has('unrelated-product-cache'));assert.equal(w.claimed,1);
});

test('failed shell download does not activate or delete the existing installed worker cache',async()=>{
  const w=worker({installFails:true});await assert.rejects(w.lifecycle('install'),/shell download failed/);
  assert.equal(w.skipped,0);assert.equal(w.claimed,0);assert.ok(w.existing.has('jarvis-shell-v14'));assert.equal(w.deleted.length,0);
});

test('worker never serves or caches auth, task, artifact, telemetry, query or other-origin requests',async()=>{
  const w=worker();
  for(const path of ['/pwa/api/session','/interface/v1/telemetry','/interface/v1/tasks/t','/interface/v1/artifacts/x','/pwa/app.mjs?private=1']){
    let intercepted=false;w.listeners.get('fetch')({request:{method:'GET',url:'https://candidate.invalid'+path},respondWith(){intercepted=true;}});assert.equal(intercepted,false,path);
  }
  let intercepted=false;w.listeners.get('fetch')({request:{method:'GET',url:'https://other-product.invalid/pwa/app.mjs'},respondWith(){intercepted=true;}});assert.equal(intercepted,false);
  let returned;w.listeners.get('fetch')({request:{method:'GET',url:'https://candidate.invalid/pwa/dashboard.mjs'},respondWith(p){returned=p;}});
  assert.equal((await returned).cached,'/pwa/dashboard.mjs');
});

test('offline fallback belongs only to the current complete generation',async()=>{
  const w=worker();w.existing.add('orqevia-shell-v999');
  let returned;w.listeners.get('fetch')({request:{method:'GET',url:'https://candidate.invalid/pwa/app.mjs'},respondWith(value){returned=value;}});
  const cache=readFileSync(new URL('./sw.js',import.meta.url),'utf8').match(/const CACHE='([^']+)'/)[1];
  assert.equal((await returned).cache,cache);
});

test('worker release handshake returns only this worker generation',()=>{
  const w=worker();let reply;
  w.listeners.get('message')({data:{type:'ORQEVIA_SHELL_RELEASE'},ports:[{postMessage(value){reply=value;},close(){}}]});
  const cache=readFileSync(new URL('./sw.js',import.meta.url),'utf8').match(/const CACHE='([^']+)'/)[1];
  assert.equal(reply.release,cache);assert.equal(reply.type,'ORQEVIA_SHELL_RELEASE');
});

const releaseSource=readFileSync(new URL('./release.mjs',import.meta.url),'utf8');
const currentRelease=releaseSource.match(/const RELEASE='([^']+)'/)[1];
const releaseNumber=Number(currentRelease.match(/v(\d+)$/)[1]);
const nextRelease=`orqevia-shell-v${releaseNumber+1}`,laterRelease=`orqevia-shell-v${releaseNumber+2}`;
const flush=async()=>{await new Promise(resolve=>setTimeout(resolve,0));await new Promise(resolve=>setTimeout(resolve,0));};

function release({pageRelease=currentRelease,activeRelease=pageRelease,values=new Map(),storageFails=false,updateFails=false}={}){
  const window=new EventTarget(),document=new EventTarget(),nodes=new Map(),sw=new EventTarget();
  let reloads=0,updates=0,busy=false;
  function node(tag){
    const value={tagName:tag.toUpperCase(),type:'',value:'',defaultValue:'',isConnected:true,children:[],events:new Map(),
      setAttribute(){},addEventListener(name,fn){this.events.set(name,fn);},append(...children){this.children.push(...children);},remove(){nodes.delete(this.id);this.isConnected=false;}};
    Object.defineProperty(value,'id',{get(){return this._id;},set(id){this._id=id;nodes.set(id,this);}});return value;
  }
  document.documentElement={dataset:{}};document.body=node('body');document.hidden=false;
  document.querySelector=()=>busy?{}:null;document.getElementById=id=>nodes.get(id)||null;document.createElement=node;
  class Channel{
    constructor(){this.port1={onmessage:null,start(){},close(){}};this.port2={postMessage:value=>queueMicrotask(()=>this.port1.onmessage?.({data:value})),close(){}};}
  }
  function controller(version){return {postMessage(data,ports){assert.equal(data.type,'ORQEVIA_SHELL_RELEASE');ports[0].postMessage({type:'ORQEVIA_SHELL_RELEASE',release:version});}};}
  sw.controller=controller(activeRelease);
  sw.register=async(path,options)=>{assert.equal(path,'/pwa/sw.js');assert.equal(options.scope,'/pwa/');assert.equal(options.updateViaCache,'none');return{async update(){updates++;if(updateFails)throw new Error('fixture update unavailable');}};};
  const navigator={serviceWorker:sw,onLine:true};
  const context={window,document,navigator,location:{protocol:'https:',reload(){reloads++;}},MessageChannel:Channel,CustomEvent,setTimeout,clearTimeout,Promise,
    sessionStorage:{getItem:key=>{if(storageFails)throw new Error('fixture storage unavailable');return values.get(key);},setItem:(key,value)=>{if(storageFails)throw new Error('fixture storage unavailable');values.set(key,value);}}};
  vm.runInNewContext(releaseSource.replace(`const RELEASE='${currentRelease}'`,`const RELEASE='${pageRelease}'`),context);
  return {window,document,navigator,values,node,nodes,context,get reloads(){return reloads;},get updates(){return updates;},set busy(value){busy=value;},
    changeController(version){sw.controller=controller(version);sw.dispatchEvent(new Event('controllerchange'));},
    edit(field,value){const focus=new Event('focusin');Object.defineProperty(focus,'target',{value:field});document.dispatchEvent(focus);field.value=value;const event=new Event('input');Object.defineProperty(event,'target',{value:field});document.dispatchEvent(event);},
    safe(){window.dispatchEvent(new Event('orqevia-shell-update-safe'));}};
}

test('coherent initial page registers and checks without an unnecessary reload',async()=>{
  const r=release();await flush();assert.equal(r.updates,1);assert.equal(r.reloads,0);
  assert.equal(r.context.__ORQEVIA_SHELL_STATE__.state,'current');
});

test('future controller releases reload once per TARGET generation and preserve unrelated storage',async()=>{
  const values=new Map([['enrollment-reference','retained'],[`${currentRelease}:controller-reload`,'1']]);
  const first=release({values});await flush();first.changeController(nextRelease);await flush();
  assert.equal(first.reloads,1);assert.equal(values.get(`${nextRelease}:controller-reload`),'1');
  const next=release({pageRelease:nextRelease,values});await flush();
  next.changeController(laterRelease);await flush();assert.equal(next.reloads,1);
  assert.equal(values.get(`${laterRelease}:controller-reload`),'1');assert.equal(values.get('enrollment-reference'),'retained');
});

test('repeated notifications cannot reload an already attempted target again',async()=>{
  const r=release({activeRelease:nextRelease,values:new Map([[`${nextRelease}:controller-reload`,'1']])});await flush();
  r.changeController(nextRelease);await flush();assert.equal(r.reloads,0);
  assert.equal(r.context.__ORQEVIA_SHELL_STATE__.reason,'reload_already_attempted');
});

test('unsaved objective or fabric text stays in memory until finished',async()=>{
  const r=release();await flush();const input=r.node('textarea');r.edit(input,'unsaved owner input');
  r.changeController(nextRelease);await flush();assert.equal(r.reloads,0);assert.equal(input.value,'unsaved owner input');
  assert.equal(r.context.__ORQEVIA_SHELL_STATE__.state,'update-ready');assert.equal(r.values.size,0);
  input.value='';r.safe();await flush();assert.equal(r.reloads,1);
});

test('application active-work cancellation defers until the safe-handoff event',async()=>{
  const r=release();await flush();const defer=event=>event.preventDefault();
  r.window.addEventListener('orqevia-before-shell-update',defer);r.changeController(nextRelease);await flush();assert.equal(r.reloads,0);
  r.window.removeEventListener('orqevia-before-shell-update',defer);r.safe();await flush();assert.equal(r.reloads,1);
});

test('handoff waits for the existing asynchronous reference transaction',async()=>{
  const r=release();await flush();let saved;const transaction=new Promise(resolve=>{saved=resolve;});
  r.window.addEventListener('orqevia-before-shell-update',event=>event.detail.waitUntil(transaction));
  r.changeController(nextRelease);await flush();assert.equal(r.reloads,0);saved();await flush();assert.equal(r.reloads,1);
});

test('offline and active busy states never trigger automatic reload',async()=>{
  const r=release();await flush();r.busy=true;r.changeController(nextRelease);await flush();assert.equal(r.reloads,0);
  r.busy=false;r.navigator.onLine=false;r.safe();await flush();assert.equal(r.reloads,0);assert.equal(r.context.__ORQEVIA_SHELL_STATE__.state,'offline');
  r.navigator.onLine=true;r.window.dispatchEvent(new Event('online'));await flush();assert.equal(r.reloads,1);
});

test('foreground, restored page and online events check updates without a continuous poller',async()=>{
  const r=release();await flush();assert.equal(r.updates,1);
  r.document.dispatchEvent(new Event('visibilitychange'));await flush();assert.equal(r.updates,2);
  const event=new Event('pageshow');Object.defineProperty(event,'persisted',{value:true});r.window.dispatchEvent(event);await flush();assert.equal(r.updates,3);
  r.window.dispatchEvent(new Event('online'));await flush();assert.equal(r.updates,4);
  assert.equal(releaseSource.includes('setInterval'),false);
});

test('unavailable session storage does not disable a safe coherent update',async()=>{
  const r=release({storageFails:true});await flush();r.changeController(nextRelease);await flush();assert.equal(r.reloads,1);
});

test('failed update lookup remains unknown even when loaded page and worker match',async()=>{
  const r=release({updateFails:true});await flush();assert.equal(r.reloads,0);
  assert.equal(r.context.__ORQEVIA_SHELL_STATE__.state,'unknown');
  assert.equal(r.context.__ORQEVIA_SHELL_STATE__.reason,'update_check_unavailable');
});

test('a changed file selection defers an update without persisting filenames',async()=>{
  const r=release();await flush();const field=r.node('input');field.type='file';field.files=[{name:'fixture.txt',size:20,lastModified:1}];
  const event=new Event('change');Object.defineProperty(event,'target',{value:field});r.document.dispatchEvent(event);
  r.changeController(nextRelease);await flush();assert.equal(r.reloads,0);assert.equal(r.values.size,0);
});
