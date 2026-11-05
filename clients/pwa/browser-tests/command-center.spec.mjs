// Browser fixtures, not live deployment/financial/experiment receipts.
import {expect,test} from '@playwright/test';
import {mockSession,waitForSession,sessionBody,expectNoHorizontalOverflow} from './fixtures.mjs';
const catalog={schema:'orqevia.capability-depot.v1',capabilities:[{id:'local-knowledge',name:'Local knowledge',kind:'retrieval',status:'SOURCE_INSTALLED',available:null,offline:true,version:'1',dependencies:['local embedding model'],resources:{memory:'Measured by Resource Guardian'},operations:['retrieve']}],wallet:{status:'NOT_FOUND',spend_enabled:false,signing_available:false,scope:'Fixture audit: no live signing wallet; compute usage is not funds.'}};

test('depot and wallets disclose actual metadata without invented funds or installation authority',async({page})=>{
 await mockSession(page);const requests=[];
 await page.route('**/api/orqevia/depot',async route=>{requests.push({method:route.request().method(),headers:await route.request().allHeaders()});await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(catalog)});});
 await page.goto('/pwa/?view=assets');await waitForSession(page);await expect(page.locator('#depot-capabilities')).toContainText('Local knowledge');await expect(page.locator('#depot-capabilities')).toContainText('Not reported');await expect(page.locator('#depot-state')).toContainText('unavailable operations are not simulated');
 await expect(page.locator('#depot-capabilities button')).toHaveText('Open capability');
 expect(requests.length).toBeGreaterThan(0);expect(requests.every(r=>r.method==='GET'&&r.headers['x-orqevia-pwa']==='1'&&!r.headers.authorization)).toBe(true);
 await page.locator('.desktop-navigation [data-view="wallets"]').click();await expect(page.locator('#wallets-content')).toContainText('NOT_FOUND');await expect(page.locator('#wallets-content')).toContainText('Not available');await expect(page.locator('#wallets-content')).toContainText('Disabled');await expect(page.locator('#wallets-view button')).toHaveCount(0);await expectNoHorizontalOverflow(page);
});

test('member inventory makes no owner-scoped catalog request',async({page})=>{
 await mockSession(page);await page.route('**/pwa/api/session',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({...sessionBody(),role:'MEMBER'})}));let requests=0;await page.route('**/api/orqevia/depot',route=>{requests++;return route.fulfill({status:200,body:JSON.stringify(catalog)});});
 await page.goto('/pwa/?view=assets');await waitForSession(page);await expect(page.locator('#depot-state')).toContainText('bound owner');expect(requests).toBe(0);await expect(page.locator('#evolution-run')).toBeDisabled();
});

test('fixed evolution comparison is explicit and cannot supply code or evaluation criteria',async({page})=>{
 await mockSession(page);const requests=[];await page.route('**/api/orqevia/evolution/experiment',async route=>{requests.push({body:route.request().postDataJSON(),headers:await route.request().allHeaders()});return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({schema:'orqevia.experiment.v1',scope:'HELD_OUT_SYNTHETIC',held_out:{baseline:2,candidate:4},production_changed:false})});});
 await page.route('**/api/orqevia/evolution/experiments',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({experiments:[{run_id:'saved-fixture-run',observed_at_utc:'2026-11-05T00:00:00Z',evidence_scope:'HELD_OUT_SYNTHETIC'}],read_only:true})}));
 await page.goto('/pwa/?view=evolution');await waitForSession(page);await expect(page.locator('#evolution-history')).toContainText('saved-fixture-run');expect(requests).toHaveLength(0);await page.locator('#evolution-run').click();await expect(page.locator('#evolution-result')).toContainText('HELD_OUT_SYNTHETIC');await expect(page.locator('#evolution-state')).toContainText('does not change production');expect(requests).toHaveLength(1);expect(requests[0].body).toEqual({});expect(requests[0].headers['x-orqevia-pwa']).toBe('1');expect(requests[0].headers.authorization).toBeUndefined();
});

test('evidence capture is explicit, uses existing task identity, and clears on logout',async({page})=>{
 await mockSession(page);const requests=[];await page.route('**/interface/v1/lens/**',async route=>{requests.push({path:new URL(route.request().url()).pathname,method:route.request().method(),body:route.request().postData()});return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({scope:'FIXTURE',objective_id:'11111111-1111-4111-8111-111111111111',integrity:true,currentness:'CURRENT'})});});
 await page.goto('/pwa/?view=console');await waitForSession(page);expect(requests).toHaveLength(0);await page.locator('#lens-task').fill('11111111-1111-4111-8111-111111111111');await page.locator('#lens-read').click();await expect(page.locator('#lens-state')).toContainText('stored source record');expect(requests.at(-1).method).toBe('GET');expect(requests.at(-1).path).toContain('/objectives/');
 await page.locator('#lens-record').click();await expect(page.locator('#lens-state')).toContainText('Evidence recording returned');expect(requests.at(-1).method).toBe('POST');expect(requests.at(-1).body).toBe('{}');await page.locator('#lens-inspect').click();await expect(page.locator('#lens-result')).toContainText('CURRENT');expect(requests.at(-1).method).toBe('GET');
 await page.evaluate(()=>window.dispatchEvent(new CustomEvent('orqevia-session',{detail:null})));await expect(page.locator('#lens-result')).toBeEmpty();await expect(page.locator('#lens-task')).toHaveValue('');await expect(page.locator('#lens-record')).toBeDisabled();
});

test('late catalog reply cannot repopulate a logged-out private inventory',async({page})=>{
 await mockSession(page);let release;await page.route('**/api/orqevia/depot',async route=>{await new Promise(resolve=>release=resolve);await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({...catalog,capabilities:[{...catalog.capabilities[0],name:'PRIVATE_OLD_SESSION'}]})}).catch(()=>{});});
 await page.goto('/pwa/?view=assets');await waitForSession(page);await expect.poll(()=>Boolean(release)).toBe(true);await page.evaluate(()=>window.dispatchEvent(new CustomEvent('orqevia-session',{detail:null})));release();await expect(page.locator('#depot-capabilities')).toBeEmpty();await expect(page.locator('#depot-capabilities')).not.toContainText('PRIVATE_OLD_SESSION');
});

test('Intelligence loads model and memory observations and hands a plan to the mission composer',async({page})=>{
 await mockSession(page);const plans=[];
 await page.route('**/interface/v1/osip/status',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({protocol:'orqevia.osip.v1',observed_at:'2026-11-05T00:00:00Z',correlation_id:'fixture',models:{entries:[{model:'configured-local-fixture',enabled:true,location:'LOCAL',tier:'FAST'}],runtime:{status:'OBSERVED',ready:true}},memory:{documents:{status:'OBSERVED'}},agents:[]})}));
 await page.route('**/interface/v1/osip/plans',route=>{plans.push(route.request().postDataJSON());return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({protocol:'orqevia.osip.v1',steps:[{purpose:'Inspect existing notes',capabilities:['knowledge']}],disclosure:'Fixture plan only',correlation_id:'fixture-plan'})});});
 await page.goto('/pwa/?view=intelligence');await waitForSession(page);await expect(page.locator('#osip-content')).toContainText('configured-local-fixture');await expect(page.locator('#osip-content')).toContainText('Memory & continuity');
 await page.locator('#osip-objective').fill('Analyze my research notes');await page.locator('#osip-plan-submit').click();await expect(page.locator('#osip-plan-result')).toContainText('Inspect existing notes');expect(plans).toEqual([{objective:'Analyze my research notes'}]);
 await page.locator('#osip-plan-result button').click();await expect(page).toHaveURL(/view=missions/);await expect(page.locator('#objective')).toHaveValue('Analyze my research notes');
});

test('mobile metric status labels fit their own cards without hidden clipping',async({page})=>{
 await mockSession(page);await page.route('**/interface/v1/collective/**',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({protocol:'orqevia.collective.v1',data:{metrics:{registry_health:'UNAVAILABLE'},records:[],fabrics:[]}})}));
 await page.goto('/pwa/?view=console');await waitForSession(page);await expect(page.locator('.operations-metric strong').filter({hasText:'UNAVAILABLE'})).toHaveCount(1);
 for(const width of [320,390]){await page.setViewportSize({width,height:844});await expectNoHorizontalOverflow(page);const clipped=await page.locator('.operations-metric strong').evaluateAll(nodes=>nodes.filter(node=>node.scrollWidth>node.clientWidth+1).map(node=>({text:node.textContent,scroll:node.scrollWidth,client:node.clientWidth})));expect(clipped).toEqual([]);}
});

test('saved experiment summaries wrap complete 64-character identifiers on compact screens',async({page})=>{
 const runID='0123456789abcdef'.repeat(4);
 await mockSession(page);
 await page.route('**/api/orqevia/evolution/experiments',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({experiments:[{run_id:runID,observed_at_utc:'2026-11-05T03:00:00Z',evidence_scope:'HELD_OUT_SYNTHETIC'}],read_only:true})}));
 await page.goto('/pwa/?view=evolution');await waitForSession(page);
 const summary=page.locator('#evolution-history summary');await expect(summary).toContainText(runID);
 for(const width of [320,390]){
  await page.setViewportSize({width,height:844});
  await expectNoHorizontalOverflow(page);
  const measured=await summary.evaluate((node,id)=>({complete:node.textContent.includes(id),client:node.clientWidth,scroll:node.scrollWidth,wrap:getComputedStyle(node).overflowWrap,ellipsis:getComputedStyle(node).textOverflow==='ellipsis'}),runID);
  expect(measured.complete).toBe(true);expect(measured.ellipsis).toBe(false);expect(measured.wrap).toBe('anywhere');expect(measured.scroll).toBeLessThanOrEqual(measured.client+1);
 }
 await summary.click();await expect(page.locator('#evolution-history pre')).toBeVisible();await expect(page.locator('#evolution-history pre')).toContainText(runID);await expectNoHorizontalOverflow(page);
});
