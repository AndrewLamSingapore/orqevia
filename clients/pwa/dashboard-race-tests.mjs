// Intercepted source fixtures; not live/physical acceptance.
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const nodes=new Map();
const node=()=>({textContent:'',children:[],classList:{toggle(){}},setAttribute(){},replaceChildren(){this.children=[];},append(...v){this.children.push(...v);}});
const listeners=new Map();
globalThis.document={hidden:false,getElementById(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);},querySelectorAll(){return [];},createElement:node,addEventListener(){}};
globalThis.window={addEventListener(name,fn){listeners.set(name,fn);},scrollTo(){}};
Object.defineProperty(globalThis,'navigator',{value:{onLine:true},configurable:true});
globalThis.setInterval=()=>0;
let respond;
globalThis.fetch=()=>new Promise(resolve=>{respond=resolve;});
await import(new URL('./dashboard.mjs',import.meta.url));
listeners.get('orqevia-session')({detail:null});
console.log('after logout:',nodes.get('telemetry-state').textContent);
respond(new Response(JSON.stringify({schema_version:'orqevia.telemetry.v1',observed_at:new Date().toISOString(),freshness_seconds:60,
 metrics:[{metric_id:'registered_agents',collection_status:'OBSERVED',value:21}],source:{instance:'OLD-SESSION'},
 agents:Array.from({length:21},(_,i)=>({agent_id:`a${i}`,name:'fixture',registration:'REGISTERED',availability:'UNKNOWN'}))}),
 {status:200,headers:{'content-type':'application/json','X-PRIME-Protocol':'jarvis.interface.v1'}}));
await new Promise(resolve=>setTimeout(resolve,20));
console.log('after prior request resolves:',nodes.get('telemetry-state').textContent,nodes.get('telemetry-source').textContent);
console.log('agent list rows after logout:',nodes.get('agent-provenance-list').children.length);


assert.equal(nodes.get('telemetry-state').textContent,'UNAUTHORIZED');
assert.equal(nodes.get('agent-provenance-list').children.length,0);
assert.equal(nodes.get('telemetry-source').textContent,'No current authenticated measurement');
console.log('Late old-session response denied: 3 assertions PASS');

listeners.get('online')();
respond(new Response(JSON.stringify({schema_version:'orqevia.telemetry.v1',observed_at:new Date().toISOString(),freshness_seconds:60,metrics:[],source:{instance:'CURRENT'},agents:Array.from({length:21},(_,i)=>({agent_id:`a${i}`,name:'fixture',registration:'REGISTERED',availability:'UNKNOWN'}))}),{status:200,headers:{'content-type':'application/json','X-PRIME-Protocol':'jarvis.interface.v1'}}));
await new Promise(resolve=>setTimeout(resolve,20));
assert.equal(nodes.get('agent-provenance-list').children.length,21);
listeners.get('offline')();
assert.equal(nodes.get('agent-provenance-list').children.length,0);
assert.equal(nodes.get('telemetry-state').textContent,'OFFLINE');
console.log('Observed provenance cleared on offline: 3 assertions PASS');
