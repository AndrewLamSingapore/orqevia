// Actual worker/release code in a VM; not physical installed-PWA acceptance.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

function worker({installFails=false}={}){
  const listeners=new Map(),deleted=[],assets=[],existing=new Set(['jarvis-shell-v14','unrelated-product-cache']);let skipped=0,claimed=0;
  const self={location:{origin:'https://candidate.invalid'},addEventListener(name,fn){listeners.set(name,fn);},skipWaiting(){skipped++;},clients:{claim(){claimed++;}}};
  const caches={async open(name){existing.add(name);return {async addAll(values){assets.push(...values);if(installFails)throw new Error('fixture shell download failed');}};},async keys(){return [...existing];},async delete(name){deleted.push(name);existing.delete(name);},async match(path){return {cached:path};}};
  vm.runInNewContext(readFileSync(new URL('./sw.js',import.meta.url),'utf8'),{self,caches,URL,fetch:async()=>{throw new Error('fixture offline');}});
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

test('release checks for update and reloads at most once per generation without touching enrollment storage',async()=>{
  const listeners=new Map(),values=new Map();let reloads=0,updates=0;
  const navigator={serviceWorker:{addEventListener(name,fn){listeners.set(name,fn);},async register(path,options){assert.equal(path,'/pwa/sw.js');assert.equal(options.scope,'/pwa/');return{async update(){updates++;}};}}};
  vm.runInNewContext(readFileSync(new URL('./release.mjs',import.meta.url),'utf8'),{navigator,location:{protocol:'https:',reload(){reloads++;}},sessionStorage:{getItem:key=>values.get(key),setItem:(key,value)=>values.set(key,value)}});
  await new Promise(resolve=>setTimeout(resolve,0));listeners.get('controllerchange')();listeners.get('controllerchange')();
  assert.equal(updates,1);assert.equal(reloads,1);assert.deepEqual([...values.keys()],['orqevia-shell-v24:controller-reload']);
});
