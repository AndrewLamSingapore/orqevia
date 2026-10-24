// Explicit browser fixtures for the operator UI. These are not live fabric receipts.
import { expect, test } from '@playwright/test';
import { mockSession, mockTaskApi, waitForSession, sessionBody, expectNoHorizontalOverflow } from './fixtures.mjs';

const prefix='/interface/v1/collective/';
const envelope=data=>({protocol:'orqevia.collective.v1',data});
const point={type:'array',minItems:2,maxItems:2,items:{type:'number'}};
const catalog=()=>({verification_context:{observed_at:'2026-10-24T06:00:00Z'},fabrics:Array.from({length:36},(_,index)=>{
 const id='f'+String(index+1).padStart(2,'0');
 return {id,name:id==='f04'?'Geospatial Intelligence':'Fixture fabric '+(index+1),version:'1.0.0',state:'VERIFIED',purpose:'Bounded browser fixture capability.',verification:{status:'PASS',scope:'Fixture verification scope only',observed_at:'2026-10-24T06:00:00Z',expires_at:'2099-10-24T06:00:00Z'},runtime_contract:{version:'1.0.0',limitations:['Fixture scope; no broad certification.'],operations:[{operation:id==='f04'?'distance_km':'inspect',input_schema:id==='f04'?{type:'object',required:['a','b'],properties:{a:point,b:point},additionalProperties:false}:{type:'object',properties:{},additionalProperties:false},output_schema:{type:'object'},scope:id==='f04'?'Spherical distance only; no route planning.':'Fixture inspection only.'}]}};
})});

async function fixture(page,{role='OWNER',catalogError=false,holdExecution=false,loseExecutionResponse=false,catalogResponse=null}={}){
 const observed={posts:[],reads:[],registries:0,record:null,release:null};
 await mockSession(page);await mockTaskApi(page);
 if(role!=='OWNER')await page.route(/\/pwa\/api\/session(?:\?.*)?$/,route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({...sessionBody(),role})}));
 await page.route('**/interface/v1/collective/**',async route=>{
  const request=route.request(),path=new URL(request.url()).pathname.slice(prefix.length);
  const reply=(data,status=200)=>route.fulfill({status,contentType:'application/json',headers:{'Cache-Control':'no-store'},body:JSON.stringify(envelope(data))});
  if(path==='status')return reply({observed_at:'2026-10-24T06:00:00Z',metrics:{},gaps:{items:[]}});
  if(path==='fabrics/registry'){
   observed.registries++;
   if(catalogError&&observed.registries===1)return reply({},503);
   return reply(catalogResponse||catalog());
  }
  const run=path.match(/^fabrics\/(f\d{2})\/execute$/);
  if(run&&request.method()==='POST'){
   const body=JSON.parse(request.postData());observed.posts.push({body,headers:await request.allHeaders(),path});
   observed.record={execution_id:body.execution_id,fabric_id:run[1],operation:body.operation,version:'1.0.0',runtime_revision:'a'.repeat(40),status:'COMPLETED',input_sha256:'b'.repeat(64),result_sha256:'c'.repeat(64),duration_ms:1.5,started_at:'2026-10-24T06:00:00Z',error_code:null,result:{distance_km:111.195,untrusted:'<img src=x onerror="globalThis.fabricInjection=true">'}};
   if(holdExecution)await new Promise(resolve=>observed.release=resolve);
   if(loseExecutionResponse)return route.abort('failed');
   return reply(observed.record).catch(()=>{});
  }
  if(path.startsWith('fabrics/executions/')){observed.reads.push(path.split('/').at(-1));return reply(observed.record||{},observed.record?200:404);}
  return reply({},404);
 });
 await page.goto('/pwa/');await waitForSession(page);
 if((await page.viewportSize()).width<760){await page.locator('#mobile-more-open').click();await page.locator('#mobile-more-dialog [data-view="operations"]').click();}
 else await page.locator('.desktop-navigation [data-view="operations"]').click();
 return observed;
}

test('the registry exposes all 36 scoped contracts without executing on discovery or selection',async({page})=>{
 const seen=await fixture(page);
 await expect(page.locator('#fabric-select option')).toHaveCount(36);
 await expect(page.locator('#fabric-summary')).toContainText('36 defined');
 await page.locator('#fabric-select').selectOption('f04');
 await expect(page.locator('#fabric-operation')).toHaveValue('distance_km');
 await expect(page.locator('#fabric-contract')).toContainText('Spherical distance only');
 await expect(page.locator('#fabric-contract')).toContainText('Fixture verification scope only');
 await expect(page.locator('#fabric-input-schema')).toContainText('"required"');
 await expect(page.locator('#fabric-output-schema')).toContainText('"object"');
 await page.locator('#fabric-select').selectOption('f18');
 expect(seen.posts).toHaveLength(0);
 await expect(page.locator('.workspace-title')).toBeVisible();
});

test('an explicit operation uses CSRF/session transport and shows actual persisted result identifiers and hashes',async({page})=>{
 const seen=await fixture(page);await expect(page.locator('#fabric-select option')).toHaveCount(36);
 await page.locator('#fabric-select').selectOption('f04');await page.locator('#fabric-parameters').fill('{"a":[0,0],"b":[0,1]}');await page.locator('#fabric-run').click();
 await expect(page.locator('#fabric-state')).toContainText('persisted receipt was read back');
 await expect(page.locator('#fabric-result')).toContainText('111.195');
 await expect(page.locator('#fabric-result')).toContainText('c'.repeat(64));
 expect(seen.posts).toHaveLength(1);expect(seen.posts[0].body.parameters).toEqual({a:[0,0],b:[0,1]});expect(seen.posts[0].headers['x-orqevia-pwa']).toBe('1');expect(seen.posts[0].headers.authorization).toBeUndefined();
 expect(seen.posts[0].body.execution_id).toMatch(/^[a-f0-9-]{36}$/);expect(seen.reads).toEqual([seen.posts[0].body.execution_id]);
 await expect(page.locator('#fabric-result img')).toHaveCount(0);expect(await page.evaluate(()=>globalThis.fabricInjection)).toBeUndefined();
 await page.locator('#fabric-read').click();await expect.poll(()=>seen.reads.length).toBe(2);expect(seen.posts).toHaveLength(1);
 await expect(page.locator('#operations-observation-form')).toBeAttached();await expect(page.locator('#operations-challenge-form')).toBeAttached();
});

test('malformed, array and nonfinite JSON are rejected before any operation request',async({page})=>{
 const seen=await fixture(page);await expect(page.locator('#fabric-select option')).toHaveCount(36);
 for(const [input,message] of [['{bad','Enter valid JSON'],['[]','must be one object'],['{"value":1e400}','must be finite']]){
  await page.locator('#fabric-parameters').fill(input);await page.locator('#fabric-run').click();await expect(page.locator('#fabric-state')).toContainText(message);
 }
 expect(seen.posts).toHaveLength(0);
});

test('a lost POST response recovers by execution ID without automatically repeating the operation',async({page})=>{
 const seen=await fixture(page,{loseExecutionResponse:true});await expect(page.locator('#fabric-select option')).toHaveCount(36);
 await page.locator('#fabric-run').click();await expect(page.locator('#fabric-state')).toContainText('did not return a confirmed outcome');
 await expect(page.locator('#fabric-execution-id')).toHaveValue(seen.record.execution_id);await page.locator('#fabric-read').click();
 await expect(page.locator('#fabric-state')).toContainText('Recorded execution COMPLETED');expect(seen.posts).toHaveLength(1);expect(seen.reads).toEqual([seen.record.execution_id]);
});

test('logout clears inputs and rejects a late prior-session execution response',async({page})=>{
 const seen=await fixture(page,{holdExecution:true});await expect(page.locator('#fabric-select option')).toHaveCount(36);
 await page.locator('#fabric-run').click();await expect.poll(()=>seen.posts.length).toBe(1);
 await page.evaluate(()=>window.dispatchEvent(new CustomEvent('orqevia-session',{detail:null})));seen.release();
 await expect(page.locator('#fabric-select option')).toHaveCount(0);await expect(page.locator('#fabric-result')).toBeEmpty();await expect(page.locator('#fabric-execution-id')).toHaveValue('');await expect(page.locator('#fabric-parameters')).toHaveValue('{}');await expect(page.locator('#fabric-run')).toBeDisabled();await expect(page.locator('#fabric-select')).toBeDisabled();
 expect(seen.reads).toHaveLength(0);
});

test('catalog errors recover by refresh and offline mode clears private execution state',async({page,context})=>{
 const seen=await fixture(page,{catalogError:true});await expect(page.locator('#fabric-state')).toHaveAttribute('data-state','error');
 await page.locator('#fabric-refresh').click();await expect(page.locator('#fabric-select option')).toHaveCount(36);
 await page.locator('#fabric-parameters').fill('{"private":"local fixture"}');await context.setOffline(true);
 await expect(page.locator('#fabric-select option')).toHaveCount(0);await expect(page.locator('#fabric-parameters')).toHaveValue('{}');await expect(page.locator('#fabric-result')).toBeEmpty();await expect(page.locator('#fabric-run')).toBeDisabled();await expect(page.locator('#fabric-select')).toBeDisabled();
 await context.setOffline(false);await expect(page.locator('#fabric-select option')).toHaveCount(36);expect(seen.posts).toHaveLength(0);
});

test('member sessions do not request owner-scoped fabric contracts',async({page})=>{
 const seen=await fixture(page,{role:'MEMBER'});await expect(page.locator('#fabric-state')).toContainText('bound owner');await expect(page.locator('#fabric-run')).toBeDisabled();await expect(page.locator('#fabric-select')).toBeDisabled();expect(seen.registries).toBe(0);expect(seen.posts).toHaveLength(0);
});

test('the mobile catalog and long receipt hashes remain within the viewport',async({page})=>{
 await page.setViewportSize({width:390,height:844});await fixture(page);await expect(page.locator('#fabric-select option')).toHaveCount(36);
 await page.locator('#fabric-run').click();await expect(page.locator('#fabric-result')).toContainText('c'.repeat(64));
 await expectNoHorizontalOverflow(page);await expect(page.locator('#fabric-read')).toBeVisible();
});

test('an empty catalog has an explicit recovery state and cannot submit an operation',async({page})=>{
 const seen=await fixture(page,{catalogResponse:{fabrics:[]}});await expect(page.locator('#fabric-state')).toContainText('no fabric contracts');await expect(page.locator('#fabric-select option')).toHaveCount(0);await expect(page.locator('#fabric-run')).toBeDisabled();await expect(page.locator('#fabric-input-schema')).toContainText('No executable input schema');expect(seen.posts).toHaveLength(0);
});

test('an unavailable capability remains visible without preventing selection of another fabric',async({page})=>{
 const value=catalog();value.fabrics[30].state='UNAVAILABLE';value.fabrics[30].runtime_contract.operations=[];
 await fixture(page,{catalogResponse:value});await expect(page.locator('#fabric-select option')).toHaveCount(36);await page.locator('#fabric-select').selectOption('f31');await expect(page.locator('#fabric-contract')).toContainText('UNAVAILABLE');await expect(page.locator('#fabric-contract')).toContainText('No executable operation');await expect(page.locator('#fabric-run')).toBeDisabled();await expect(page.locator('#fabric-select')).toBeEnabled();await page.locator('#fabric-select').selectOption('f04');await expect(page.locator('#fabric-run')).toBeEnabled();
});
