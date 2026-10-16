// Execute the actual UI module against deferred service responses; not device acceptance.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const settle=()=>new Promise(r=>setTimeout(r,0));let serial=0;
async function fixture({empty=false,fail=false}={}){
 const nodes=new Map(),listeners=new Map(),requests=[],intervals=[];
 const element=(tag='div')=>({tag,textContent:'',dataset:{},children:[],listeners:new Map(),classList:{toggle(){}},append(...n){this.children.push(...n);},replaceChildren(...n){this.children=[...n];},addEventListener(n,f){this.listeners.set(n,f);},setAttribute(){},getContext(){return {beginPath(){},moveTo(){},lineTo(){},stroke(){},arc(){},fill(){}};}});
 globalThis.document={hidden:false,documentElement:{dataset:{}},getElementById(id){if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);},createElement:element};
 globalThis.location={href:'https://abex.test/pwa/?view=intelligence'};
 Object.defineProperty(globalThis,'navigator',{value:{onLine:true},configurable:true});
 globalThis.window={addEventListener(n,f){listeners.set(n,f);},dispatchEvent(e){listeners.get(e.type)?.(e);}};
 globalThis.setInterval=f=>{intervals.push(f);};
 globalThis.fetch=async(path,options)=>{requests.push({path,options});const payload=path.endsWith('session')?{authenticated:true}:path.includes('/geo/events')?{records:empty?[]:[{event_id:'usgs-real-shaped-fixture',magnitude:5,place:'Fixture only',location:{lat:1,lon:2},source_url:'https://earthquake.usgs.gov/example',ingested_at:new Date().toISOString()}]}:path.includes('rag/retrieve')?{status:'GROUNDED',results:[{source:'https://earthquake.usgs.gov/example'}]}:path.includes('telemetry')?{observed_at:new Date().toISOString(),freshness_seconds:60,agents:[],metrics:[]}:path.endsWith('/alerts')?{alerts:[]}:path.endsWith('/health')?{ok:true}:{};return new Response(JSON.stringify(payload),{status:fail&&path.endsWith('/health')?503:200,headers:{'content-type':'application/json'}});};
 await import(new URL('./intelligence.mjs?test='+(++serial),import.meta.url));
 return {nodes,listeners,requests,intervals,session(value={clientId:'fixture',role:'OWNER'}){listeners.get('orqevia-session')({detail:value});},text(){const all=[];function walk(n){all.push(n.textContent);for(const c of n.children||[])walk(c);}walk(nodes.get('intelligence-content'));return all.join('\n');}};
}
test('first Intelligence session loads real service panels with variable agent list and cited RAG',async()=>{
 const f=await fixture();assert.equal(f.requests.length,0);f.session();await settle();await settle();
 assert.equal(f.nodes.get('intelligence-state').dataset.state,'ready');assert.match(f.text(),/Fixture only/);assert.match(f.text(),/No alerts have fired/);
 const root=f.nodes.get('intelligence-content'),rag=root.children.find(p=>p.children[0]?.textContent.startsWith('Knowledge retrieval'));
 const form=rag.children.find(n=>n.tag==='form');form.children[1].value='earthquake';await form.listeners.get('submit')({preventDefault(){}});
 assert.match(f.text(),/GROUNDED/);assert.ok(f.requests.some(r=>r.path.endsWith('rag/retrieve')&&r.options.method==='POST'));
});
test('empty observations and partial failure are explicit and Refresh recovers',async()=>{
 const f=await fixture({empty:true,fail:true});f.session();await settle();await settle();assert.equal(f.nodes.get('intelligence-state').dataset.state,'error');assert.match(f.text(),/No observations stored/);assert.match(f.text(),/Service returned 503/);
 globalThis.fetch=async()=>new Response(JSON.stringify({records:[],agents:[],metrics:[],alerts:[],ok:true}),{status:200});f.nodes.get('intelligence-refresh').listeners.get('click')();await settle();await settle();assert.equal(f.nodes.get('intelligence-state').dataset.state,'ready');
});
test('offline and logout clear data; direct God’s Eye selection reloads without enrollment',async()=>{
 const f=await fixture();f.session();await settle();await settle();navigator.onLine=false;f.listeners.get('offline')();assert.equal(f.nodes.get('intelligence-content').children.length,0);assert.equal(f.nodes.get('intelligence-state').dataset.state,'offline');
 navigator.onLine=true;f.listeners.get('orqevia-view')({detail:{name:'gods-eye'}});await settle();await settle();assert.equal(f.nodes.get('intelligence-title').textContent,"God's Eye");assert.equal(f.nodes.get('intelligence-state').dataset.state,'ready');f.session(null);assert.equal(f.nodes.get('intelligence-content').children.length,0);
});

test('source synchronization is owner-only and sends an authorized mutation request',async()=>{
 const f=await fixture();f.session({clientId:'fixture',role:'MEMBER'});await settle();assert.equal(f.nodes.get('intelligence-ingest').hidden,true);
 await f.nodes.get('intelligence-ingest').listeners.get('click')();assert.ok(!f.requests.some(r=>r.path.endsWith('/ingest/run')));
 f.session({clientId:'fixture',role:'OWNER'});await settle();assert.equal(f.nodes.get('intelligence-ingest').hidden,false);
 await f.nodes.get('intelligence-ingest').listeners.get('click')();assert.ok(f.requests.some(r=>r.path.endsWith('/ingest/run')&&r.options.method==='POST'));
});

test('geographic filters validate coordinates and request the real radius API',async()=>{
 const f=await fixture();f.session();await settle();await settle();
 const filter=f.nodes.get('intelligence-content').children.find(p=>p.children[0]?.textContent==='Geographic filter');
 const form=filter.children.find(n=>n.tag==='form'),fields=form.children.slice(0,3).map(l=>l.children[0]);
 fields[0].value=91;fields[1].value=0;fields[2].value=100;
 form.listeners.get('submit')({preventDefault(){}});assert.match(f.nodes.get('intelligence-state').textContent,/valid latitude/);
 fields[0].value=1.35;fields[1].value=103.8;
 form.listeners.get('submit')({preventDefault(){}});await settle();await settle();
 assert.ok(f.requests.some(r=>r.path.includes('/geo/radius?lat=1.35&lon=103.8&radius_km=100')));
});
