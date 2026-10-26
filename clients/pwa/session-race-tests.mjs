// Deferred transport/storage fixtures exercising the actual app module.
// These are regression tests, not authenticated browser/device acceptance.
import test,{afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
const settle=()=>new Promise(resolve=>setTimeout(resolve,0));
let serial=0;
let activeFixture;
afterEach(async()=>{
  navigator.onLine=false;document.hidden=true;activeFixture?.listeners.get('offline')?.();
  for(const request of activeFixture?.requests||[]){request.resolve(new Response('{}',{status:401,headers:{'content-type':'application/json','X-ORQEVIA-Protocol':'orqevia.interface.v1'}}));}
  await settle();
});

async function fixture(){
  const nodes=new Map(),listeners=new Map(),documentListeners=new Map(),requests=[],intervals=[];
  function node(){return {textContent:'',value:'',children:[],dataset:{},classList:{toggle(){},add(){},remove(){}},listeners:new Map(),addEventListener(name,fn){this.listeners.set(name,fn);},setAttribute(){},removeAttribute(){},querySelector:node,replaceChildren(){this.children=[];},append(...items){this.children.push(...items);},scrollIntoView(){},focus(){},showModal(){this.open=true;},close(){this.open=false;}};}
  for(const match of readFileSync(new URL('./index.html',import.meta.url),'utf8').matchAll(/id="([^"]+)"/g))nodes.set(match[1],node());
  globalThis.document={hidden:false,documentElement:{dataset:{}},body:node(),getElementById(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);},querySelectorAll(){return [];},createElement:node,addEventListener(name,fn){documentListeners.set(name,fn);}};
  globalThis.window={addEventListener(name,fn){listeners.set(name,fn);},dispatchEvent(event){listeners.get(event.type)?.(event);}};
  globalThis.location={hash:''};globalThis.history={pushState(_state,_title,url){location.hash=url;}};
  globalThis.matchMedia=()=>({matches:false});
  Object.defineProperty(globalThis,'navigator',{value:{onLine:true},configurable:true});
  globalThis.setInterval=(fn,ms)=>{intervals.push({fn,ms});};
  globalThis.fetch=(url,options)=>new Promise((resolve,reject)=>{requests.push({url,options,resolve,reject});});
  const store={load:async()=>({pending:null,history:[]}),remember:async()=>{},clear:async()=>{}};
  globalThis.__sessionFixtureStore=store;
  const storeModule='data:text/javascript,'+encodeURIComponent('export class TaskStore {constructor(){return globalThis.__sessionFixtureStore;}}');
  const voiceModule='data:text/javascript,'+encodeURIComponent('export class Voice {stop(){} testOutput(){} speak(){} }');
  let source=readFileSync(process.env.PWA_APP_SOURCE||new URL('./app.mjs',import.meta.url),'utf8')
    .replace("'./core.mjs'",JSON.stringify(new URL('./core.mjs',import.meta.url).href))
    .replace("'./storage.mjs'",JSON.stringify(storeModule))
    .replace("'./voice.mjs'",JSON.stringify(voiceModule));
  await import('data:text/javascript;base64,'+Buffer.from(source+'\n// fixture '+(++serial)).toString('base64'));
  function response(index,value,status=200,mode='json'){
    const headers={'content-type':mode==='sse'?'text/event-stream':'application/json','X-ORQEVIA-Protocol':'orqevia.interface.v1'};
    requests[index].resolve(new Response(mode==='sse'?value:JSON.stringify(value),{status,headers}));
  }
  async function authenticated(clientId='member-a'){
    response(requests.length-1,{protocol:'orqevia.interface.v1',authenticated:true,clientId,role:'MEMBER',expiresAt:Date.now()/1000+3600});await settle();
  }
  function validate(){documentListeners.get('visibilitychange')();}
  function periodic(){intervals.find(item=>item.ms===60000).fn();}
  activeFixture={nodes,listeners,documentListeners,requests,store,response,authenticated,validate,periodic};
  return activeFixture;
}

test('startup restoration and network failure never advertise lost device trust',async()=>{
  const f=await fixture();assert.equal(document.documentElement.dataset.accessState,'restoring');
  f.requests[0].reject(new TypeError('fixture offline'));await settle();
  assert.equal(document.documentElement.dataset.accessState,'unavailable');
  assert.match(f.nodes.get('access-recovery-message').textContent,/trust has not been removed/);
});

test('only a completed server trust rejection shows enrollment recovery',async()=>{
  const f=await fixture();f.response(0,{protocol:'orqevia.interface.v1',authenticated:false,recovery:'DEVICE_EXPIRED'});await settle();
  assert.equal(document.documentElement.dataset.accessState,'untrusted');
});

test('logout invalidates an earlier session response before the logout request completes',async()=>{
  const f=await fixture();assert.equal(f.requests[0].url,'/pwa/api/session');
  const logout=f.nodes.get('logout-button').listeners.get('click')();
  assert.equal(f.requests[1].url,'/pwa/api/logout');
  f.response(0,{protocol:'orqevia.interface.v1',authenticated:true,clientId:'old-member',role:'MEMBER',expiresAt:Date.now()/1000+3600});await settle();
  assert.equal(f.nodes.get('connection-label').textContent,'Not connected');
  f.response(1,{});await logout;
  assert.equal(f.nodes.get('connection-label').textContent,'Not connected');
});

test('an earlier authorization failure cannot erase a newer validated session',async()=>{
  const f=await fixture();f.validate();assert.equal(f.requests.length,2);await f.authenticated('new-member');
  f.response(0,{},401);await settle();
  assert.equal(f.nodes.get('connection-label').textContent,'Connected to ORQEVIA');
  assert.match(f.nodes.get('session-detail').textContent,/new-member/);
});

test('successful logout of a trusted device immediately restores enrollment state',async()=>{
  const f=await fixture();await f.authenticated('signed-out-member');
  assert.equal(document.documentElement.dataset.accessState,'trusted');
  const logout=f.nodes.get('logout-button').listeners.get('click')();
  assert.equal(f.requests[1].url,'/pwa/api/logout');
  f.response(1,{});await logout;
  assert.equal(document.documentElement.dataset.accessState,'untrusted');
  assert.equal(f.nodes.get('connection-label').textContent,'Not connected');
  assert.equal(f.nodes.get('submit-button').disabled,true);
});

test('late account-A local history is not rendered or opened under account B',async()=>{
  const f=await fixture();let release;
  f.store.load=client=>client==='member-a'?new Promise(resolve=>{release=resolve;}):Promise.resolve({pending:null,history:[]});
  await f.authenticated('member-a');f.validate();await f.authenticated('member-b');
  release({pending:null,history:[{id:'old-private-task',state:'COMPLETED',updatedAt:1}]});await settle();
  assert.match(f.nodes.get('session-detail').textContent,/member-b/);
  assert.ok(f.requests.every(request=>!request.url.includes('old-private-task')));
  assert.doesNotMatch(f.nodes.get('history-list').textContent,/old-private-task/);
});

for(const failed of [false,true])test(`late account-A task ${failed?'401':'result'} cannot change account B`,async()=>{
  const f=await fixture();await f.authenticated('member-a');
  document.getElementById('resume-id').value='old-private-task';f.nodes.get('resume-form').listeners.get('submit')({preventDefault(){}});
  assert.match(f.requests[1].url,/old-private-task\/events$/);f.response(1,'',200,'sse');await settle();
  assert.match(f.requests[2].url,/old-private-task$/);
  f.periodic();await f.authenticated('member-b');
  f.response(2,failed?{}:{task_id:'old-private-task',revision:0,state:'COMPLETED',result:'PRIVATE ACCOUNT A'},failed?401:200);await settle();
  assert.match(f.nodes.get('session-detail').textContent,/member-b/);
  assert.equal(f.nodes.get('connection-label').textContent,'Connected to ORQEVIA');
  assert.equal(f.nodes.get('task-result').textContent,'');
});

test('ordinary same-member session refresh keeps the current task result',async()=>{
  const f=await fixture();await f.authenticated('member-a');
  document.getElementById('resume-id').value='owned-task';f.nodes.get('resume-form').listeners.get('submit')({preventDefault(){}});
  f.response(1,'',200,'sse');await settle();f.response(2,{task_id:'owned-task',revision:0,state:'COMPLETED',result:'OWNED RESULT'});await settle();
  assert.equal(f.nodes.get('task-result').textContent,'OWNED RESULT');
  const artifacts=f.requests.findIndex(request=>request.url.includes('/artifacts?'));f.response(artifacts,{artifacts:[],next_offset:null});await settle();
  f.validate();await f.authenticated('member-a');
  assert.equal(f.nodes.get('task-result').textContent,'OWNED RESULT');assert.match(f.nodes.get('session-detail').textContent,/member-a/);
});

test('late account-A local storage failure cannot disconnect account B',async()=>{
  const f=await fixture();let rejectOld;
  f.store.load=client=>client==='member-a'?new Promise((_resolve,reject)=>{rejectOld=reject;}):Promise.resolve({pending:null,history:[]});
  await f.authenticated('member-a');f.validate();await f.authenticated('member-b');rejectOld(new Error('fixture storage error'));await settle();
  assert.equal(f.nodes.get('connection-label').textContent,'Connected to ORQEVIA');assert.match(f.nodes.get('session-detail').textContent,/member-b/);
});

test('foreground renewal preserves an uploaded unsubmitted attachment for the same identity',async()=>{
  const f=await fixture();await f.authenticated('member-a');
  const file=new File(['controlled attachment fixture'],'note.txt',{type:'text/plain'}),input=f.nodes.get('file-input');input.files=[file];input.value='note.txt';
  const uploading=input.listeners.get('change')();await settle();
  const bytes=Buffer.from(await file.arrayBuffer());
  f.response(1,{artifactId:'owned-attachment',bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex')});await uploading;
  assert.equal(input.value,'');assert.equal(f.nodes.get('attachment-list').children.length,1);
  f.validate();await f.authenticated('member-a');
  assert.equal(f.nodes.get('attachment-list').children.length,1);
  assert.match(f.nodes.get('attachment-list').children[0].textContent,/note.txt/);
  const update=new Event('orqevia-before-shell-update',{cancelable:true});f.listeners.get(update.type)(update);assert.equal(update.defaultPrevented,true);
  f.validate();await f.authenticated('member-b');assert.equal(f.nodes.get('attachment-list').children.length,0);
});

test('failed upload preserves the selected file and defers a shell update',async()=>{
  const f=await fixture();await f.authenticated('member-a');
  const input=f.nodes.get('file-input');input.files=[new File(['fixture'],'note.txt')];input.value='note.txt';
  const uploading=input.listeners.get('change')();await settle();f.response(1,{},503);await uploading;
  assert.equal(input.value,'note.txt');assert.equal(f.nodes.get('attachment-list').children.length,0);
  const update=new Event('orqevia-before-shell-update',{cancelable:true});f.listeners.get(update.type)(update);assert.equal(update.defaultPrevented,true);
});
