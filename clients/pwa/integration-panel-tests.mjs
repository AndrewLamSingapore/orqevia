// Reproduce the real 30-second retry race without waiting or using a fake model.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mountIntegrationPanels} from './integration-panels.mjs';
const settle=()=>new Promise(resolve=>setTimeout(resolve,0));
function setup(){
 const intervals=[],elements=[],calls=[];
 const node=(tag,textContent='')=>{const e={tag,textContent,children:[],listeners:new Map(),value:'',isConnected:true,
  append(...children){this.children.push(...children);},prepend(...children){this.children.unshift(...children);},
  replaceChildren(...children){this.children=children;},addEventListener(name,fn){this.listeners.set(name,fn);},contains(){return false;}};elements.push(e);return e;};
 globalThis.document={hidden:false,activeElement:null};
 globalThis.window={addEventListener(){},removeEventListener(){}};
 globalThis.setInterval=fn=>{intervals.push(fn);return 1;};globalThis.clearInterval=()=>{};
 const section=node('section');
 const snapshot={providers:[{provider:'Declared fixture',status:'STALE',records:[{id:'retained-fixture'}]}],
  semantic_entailment:{status:'LOADED',qualification:{status:'BOUNDED_SYNTHETIC_PASS'}}};
 const record=(section,title)=>{const e=node('details',title);section.append(e);return e;};
 return {node,section,snapshot,record,elements,intervals,calls};
}
test('stale retained observations do not replace a semantic form or its pending result',async()=>{
 const f=setup();let finish;
 const request=async(path)=>{f.calls.push(path);if(path.endsWith('/assess'))return new Promise(resolve=>{finish=resolve;});return f.snapshot;};
 const stop=mountIntegrationPanels(f.section,{request,owner:true,readOnly:false,node:f.node,record:f.record,source(){},isCurrent:()=>true});
 await settle();const premise=f.elements.find(e=>e.id==='semantic-premise'),form=f.elements.find(e=>e.tag==='form');
 premise.value='The request has not been approved.';premise.listeners.get('input')();
 const pending=form.listeners.get('submit')({preventDefault(){}});
 f.intervals[0]();await settle();assert.ok(f.section.children.includes(form));assert.equal(f.calls.filter(p=>p.endsWith('/observations')).length,1);
 finish({assessment:'CONTRADICTION',disclosure:'Declared test response; not live inference.'});await pending;
 assert.ok(f.section.children.includes(form));assert.ok(f.section.children.some(e=>e.children.some(c=>c.textContent.startsWith('Semantic assessment: CONTRADICTION.'))));
 f.intervals[0]();await settle();assert.equal(f.calls.filter(p=>p.endsWith('/observations')).length,1);stop();
});
test('a failed projection request still retries and recovers while visible',async()=>{
 const f=setup();let attempt=0;
 const request=async()=>{if(++attempt===1)throw Error('Declared outage');return f.snapshot;};
 const stop=mountIntegrationPanels(f.section,{request,owner:true,readOnly:true,node:f.node,record:f.record,source(){},isCurrent:()=>true});
 await settle();assert.equal(attempt,1);f.intervals[0]();await settle();assert.equal(attempt,2);
 assert.ok(f.section.children.some(e=>e.textContent.includes('STALE')));stop();
});
