import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const settle=()=>new Promise(r=>setTimeout(r,0));let serial=0;
async function fixture(){
 const nodes=new Map(),listeners=new Map(),requests=[];
 const node=(tag='div')=>({tag,textContent:'',value:'',checked:false,children:[],files:[],classList:{toggle(){}},listeners:new Map(),append(...v){this.children.push(...v);},replaceChildren(...v){this.children=[...v];},addEventListener(n,f){this.listeners.set(n,f);}});
 for(const match of readFileSync(new URL('./index.html',import.meta.url),'utf8').matchAll(/id="([^"]+)"/g))nodes.set(match[1],node());
 globalThis.document={getElementById(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);},createElement:node,querySelectorAll(){return [];}};
 globalThis.window={addEventListener(n,f){listeners.set(n,f);},dispatchEvent(e){listeners.get(e.type)?.(e);}};
 globalThis.fetch=async(path,options)=>{requests.push({path,options});let result=path.endsWith('/documents')?{documents:[{document_id:'a'.repeat(64),source:'fixture.txt',version:1,bytes:50,sha256:'a'.repeat(64)}]}:path.endsWith('/health')?{index:{status:'READY'}}:path.endsWith('/ingest')?{status:'INDEXED',added_chunks:1}:path.endsWith('/reindex')?{status:'REINDEXED',chunks:2}:{status:'CITED_MODEL_INTERPRETATION',answer:'Fixture answer [1]',model:'qwen2.5:7b',citations_valid:true,results:[{citation:'[1]',source:'fixture.txt',passage:'Fixture evidence',similarity:.8,sha256:'b'.repeat(64)}]};return new Response(JSON.stringify(result),{status:200,headers:{'content-type':'application/json'}});};
 await import('data:text/javascript;base64,'+Buffer.from(readFileSync(new URL('./knowledge.mjs',import.meta.url),'utf8')+'\n//'+(++serial)).toString('base64'));
 return {nodes,requests,listeners,session(role='OWNER',clientId='owner-fixture'){listeners.get('orqevia-session')({detail:role?{role,clientId}:null});}};
}
test('private knowledge is owner-scoped and does not send enrollment credentials',async()=>{
 const f=await fixture();assert.equal(f.requests.length,0);f.session('MEMBER');assert.equal(f.nodes.get('private-knowledge').hidden,true);assert.equal(f.requests.length,0);
 f.session();await settle();assert.equal(f.nodes.get('private-knowledge').hidden,false);assert.match(f.nodes.get('knowledge-state').textContent,/connected/);
 assert.ok(f.requests.every(r=>!r.options.headers.Authorization&&r.options.credentials==='same-origin'));
 f.session(null);assert.equal(f.nodes.get('private-knowledge').hidden,true);assert.equal(f.nodes.get('knowledge-documents').children.length,0);
});
test('document upload, retrieval and grounded local generation call shared APIs',async()=>{
 const f=await fixture();f.session();await settle();
 f.nodes.get('knowledge-file').files=[{name:'fixture.txt',size:4,arrayBuffer:async()=>new Uint8Array([116,101,115,116]).buffer}];
 await f.nodes.get('knowledge-upload').listeners.get('click')();assert.match(f.nodes.get('knowledge-state').textContent,/INDEXED/);
 f.nodes.get('knowledge-question').value='What does the fixture say?';
 await f.nodes.get('knowledge-retrieve').listeners.get('click')();
 f.nodes.get('knowledge-observations').checked=true;await f.nodes.get('knowledge-ask').listeners.get('click')();
 const request=f.requests.find(r=>r.path.endsWith('/answer'));assert.equal(JSON.parse(request.options.body).include_observations,true);
 assert.match(f.nodes.get('knowledge-answer').children[1].textContent,/Fixture answer \[1\]/);
});
test('unsupported documents and backend errors are explicit and recoverable',async()=>{
 const f=await fixture();f.session();await settle();f.nodes.get('knowledge-file').files=[{name:'bad.exe',size:4}];await f.nodes.get('knowledge-upload').listeners.get('click')();assert.match(f.nodes.get('knowledge-state').textContent,/Choose a PDF/);
 globalThis.fetch=async()=>new Response('{}',{status:503});await f.nodes.get('knowledge-refresh').listeners.get('click')();assert.match(f.nodes.get('knowledge-state').textContent,/unavailable/);assert.equal(f.nodes.get('knowledge-refresh').disabled,undefined);
});
