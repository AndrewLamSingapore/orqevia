import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
let serial=0;
const settle=()=>new Promise(r=>setTimeout(r,0));
async function fixture(view){
 const nodes=new Map(),events=new Map(),requests=[];
 const node=tag=>({tag,textContent:'',children:[],value:'',handlers:new Map(),append(...children){this.children.push(...children);},replaceChildren(...children){this.children=children;},setAttribute(){},addEventListener(name,fn){this.handlers.set(name,fn);}});
 for(const id of ['workflow-module','capability-description'])nodes.set(id,node('div'));
 globalThis.location={href:'https://workspace.test/pwa/?view='+view};
 globalThis.document={getElementById(id){if(id==='workflow-state')return nodes.get('workflow-module').children[0];return nodes.get(id);},createElement:node};
 globalThis.window={addEventListener(name,fn){events.set(name,fn);},dispatchEvent(e){events.get(e.type)?.(e);}};
 globalThis.fetch=async(path,options)=>{requests.push({path,options});const data=path.endsWith('/ideas')?{ideas:[{title:'Actual draft',body:'Preserved draft',created_at:'2026-10-15'}]}:path.endsWith('/scaffold')?{files:{'backend/app.py':'candidate'},execution_performed:false}:path.endsWith('/validate')?{status:'PASS',classification:'ISOLATED_FIXTURES'}:{release:{status:'UNAVAILABLE'}};return new Response(JSON.stringify(data));};
 await import('data:text/javascript;base64,'+Buffer.from(readFileSync(new URL('./workspace-tools.mjs',import.meta.url),'utf8')+'\n//'+(++serial)).toString('base64'));
 return {nodes,events,requests,async owner(){events.get('orqevia-session')({detail:{role:'OWNER',clientId:'test-owner'}});await settle();}};
}
test('workspace capabilities deny member access and clear private content on identity change',async()=>{
 const f=await fixture('ideas');assert.equal(f.requests.length,0);await f.owner();assert.ok(f.requests.length);f.events.get('orqevia-session')({detail:{role:'MEMBER',clientId:'member'}});assert.equal(f.nodes.get('workflow-module').children.length,1);assert.match(f.nodes.get('workflow-module').children[0].textContent,/bound owner/);assert.ok(f.requests.every(r=>r.options.credentials==='same-origin'&&!r.options.headers.Authorization));
});
test('Ideas persist through shared API and draft handoff does not execute an objective',async()=>{
 const f=await fixture('ideas');await f.owner();const form=f.nodes.get('workflow-module').children[1];form.children[0].value='Next idea';form.children[1].value='Real description';await form.handlers.get('submit')({preventDefault(){}});assert.equal(JSON.parse(f.requests.at(-1).options.body).title,'Next idea');assert.match(f.nodes.get('workflow-module').children[0].textContent,/saved/);
});
test('Build and Test use fixed backend operations and display measured results',async()=>{
 const f=await fixture('build');await f.owner();const root=f.nodes.get('workflow-module');root.children[1].value='Reviewable';await root.children[3].handlers.get('click')();assert.equal(JSON.parse(f.requests.at(-1).options.body).kind,'project');assert.match(root.children[0].textContent,/not executed or deployed/);
 f.events.get('orqevia-view')({detail:{name:'test'}});await settle();await root.children.at(-1).handlers.get('click')();assert.ok(f.requests.at(-1).path.endsWith('/validate'));assert.match(root.children[0].textContent,/Regression execution: PASS/);
 globalThis.fetch=async()=>new Response('{}',{status:503});f.events.get('orqevia-view')({detail:{name:'architecture'}});await settle();assert.match(root.children[0].textContent,/503/);
});
