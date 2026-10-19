import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {loadConfig} from '../lib/config.mjs';
import {InterfaceNode} from '../lib/upstream.mjs';

const identity={hostname:'DESKTOP-BGD97NB',role:'AUTHORITATIVE_ORQEVIA',protocolVersion:'1',publicKey:'fixture-public-key'};
const pin=createHash('sha256').update(JSON.stringify(identity)).digest('hex');
function config(base='https://abex.example:8443'){
 return loadConfig({JARVIS_ABEX_BASE_URL:base,JARVIS_ABEX_EXPECTED_HOST:identity.hostname,JARVIS_ABEX_IDENTITY_SHA256:pin,
  JARVIS_CLIENT_ID:'dell:fixture',JARVIS_CLIENT_TOKEN:'fixture-nonproduction-token'});
}

test('root URLs preserve configured origin despite URL root pathname slash',()=>{
 for(const base of ['https://abex.example:8443','https://abex.example:8443/']){
  const client=new InterfaceNode(config(base));
  assert.equal(client.url('/health').href,'https://abex.example:8443/interface/v1/health');
  assert.equal(client.url('/identity').origin,'https://abex.example:8443');
 }
});

test('configured prefix and trailing slashes join within origin',()=>{
 for(const base of ['https://abex.example:8443/prime','https://abex.example:8443/prime/','https://abex.example:8443/prime///']){
  const client=new InterfaceNode(config(base));
  assert.equal(client.url('/tasks/task-1').href,'https://abex.example:8443/prime/interface/v1/tasks/task-1');
 }
});

test('actual canonical identity and health request emit credentials only at ABEX origin',async()=>{
 const calls=[];
 const client=new InterfaceNode(config(),async(url,init)=>{
  calls.push({url:new URL(url),init});
  assert.equal(url.origin,'https://abex.example:8443');
  assert.equal(init.redirect,'error');
  return new Response(JSON.stringify(url.pathname.endsWith('/identity')?identity:{state:'READY'}),{status:200});
 });
 const response=await client.health();assert.equal((await response.json()).state,'READY');
 assert.equal(calls.length,2);assert.equal(calls[0].url.pathname,'/interface/v1/identity');
 assert.equal(calls[1].url.pathname,'/interface/v1/health');
 assert.ok(calls.every(call=>call.init.headers.authorization==='Bearer fixture-nonproduction-token'));
});

test('off-origin/network-path/traversal targets rejected before credential transport',async()=>{
 const calls=[];const client=new InterfaceNode(config(),async(...args)=>{calls.push(args);return new Response('{}')});
 for(const path of ['//evil.example/steal','https://evil.example/steal','/../../owner','/\\evil.example']){
  await assert.rejects(client.fetchInterface(path,{headers:client.headers()}));
 }
 assert.equal(calls.length,0);
});

test('redirect attempt cannot opt into following or send auth to redirected origin',async()=>{
 let offOriginRequests=0,primaryRequests=0;
 const client=new InterfaceNode(config(),async(url,init)=>{
  assert.equal(url.origin,'https://abex.example:8443');primaryRequests++;
  if(init.redirect!=='error'){offOriginRequests++;throw new Error('Unsafe redirect would execute')}
  return new Response('',{status:302,headers:{location:'https://evil.example/steal'}});
 });
 await assert.rejects(client.fetchInterface('/health',{headers:client.headers(),redirect:'follow'}),/redirect rejected/);
 assert.equal(primaryRequests,1);assert.equal(offOriginRequests,0);
});

test('already redirected or wrong-origin response is not accepted',async()=>{
 for(const value of [{redirected:true,status:200,url:'https://abex.example:8443/interface/v1/identity'},
                    {redirected:false,status:200,url:'https://evil.example/identity'}]){
  const client=new InterfaceNode(config(),async()=>value);
  await assert.rejects(client.fetchInterface('/identity',{}),/redirect rejected/);
 }
});
