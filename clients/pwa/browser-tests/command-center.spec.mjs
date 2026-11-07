// Browser fixtures, not live deployment/financial/experiment receipts.
import {expect,test} from '@playwright/test';
import {mockSession,waitForSession,sessionBody,expectNoHorizontalOverflow} from './fixtures.mjs';
const catalog={schema:'orqevia.capability-depot.v1',capabilities:[{id:'local-knowledge',name:'Local knowledge',kind:'retrieval',status:'SOURCE_INSTALLED',available:null,offline:true,version:'1',dependencies:['local embedding model'],resources:{memory:'Measured by Resource Guardian'},operations:['retrieve']}],wallet:{status:'NOT_FOUND',spend_enabled:false,signing_available:false,scope:'Fixture audit: no live signing wallet; compute usage is not funds.'}};

test('official Command Center logo loads square and centered on desktop and mobile',async({page})=>{
 await mockSession(page);await page.goto('/pwa/');await waitForSession(page);
 const logo=page.locator('.command-banner img');await expect(logo).toHaveAttribute('src','/pwa/icons/orqevia-official-v1-192.png');await expect(logo).toHaveAttribute('alt','ORQEVIA official logo');await expect(logo).toHaveAttribute('srcset','/pwa/icons/orqevia-official-v1-192.png 192w, /pwa/icons/orqevia-official-v1-master.png 1254w');
 for(const width of [1440,390]){
  await page.setViewportSize({width,height:900});await expect(logo).toBeVisible();
  await expect.poll(()=>logo.evaluate(node=>node.complete&&node.naturalWidth>0&&node.naturalWidth===node.naturalHeight)).toBe(true);
  const box=await logo.evaluate(node=>{const image=node.getBoundingClientRect(),parent=node.parentElement.getBoundingClientRect();return{width:image.width,height:image.height,center:Math.abs(image.x+image.width/2-parent.x-parent.width/2),fit:getComputedStyle(node).objectFit,density:devicePixelRatio,currentSrc:node.currentSrc};});
  expect(box.width).toBe(width<640?108:132);expect(Math.abs(box.width-box.height)).toBeLessThan(1);expect(box.center).toBeLessThan(1);expect(box.fit).toBe('contain');if(box.width*box.density>192)expect(box.currentSrc).toContain('/pwa/icons/orqevia-official-v1-master.png');await expectNoHorizontalOverflow(page);
 }
});

test('live health separates verified core and critical facts from incomplete or stale monitoring',async({page})=>{
 await mockSession(page);let stale=false;
 await page.route('**/interface/v1/telemetry',route=>{
  const stamp=new Date().toISOString(),old=new Date(Date.now()-121000).toISOString(),last=new Date(Date.now()-3600000).toISOString();
  const check=(key,id,severity='CRITICAL')=>({check_key:key,check_id:id,severity,status:'PASS',fresh:true,observed_at:stamp});
  const services=['backend','interface','ollama','intelligence','coaching','otel-collector','integration-gateway','cloudflared','cloudflared-dual'].map(service_id=>({service_id,status:'HEALTHY',checks:[check('service:'+service_id+':fixture','fixture')]}));
  const collectors=['collector-source','host-identity','boot-identity'].map(id=>check('collector:'+id,id,'DEGRADED'));
  const names=['docker-engine','persistent-containers','backend-health','cloud-inference-configuration','interface-local','cloudflare-tunnel','auth-boundary','host-telemetry-freshness','model-runtime','fabrics-and-ai-scaffold-imports','agent-liveness-receipt','deployment-identity','queue-runtime-and-cost','workflow-and-notebook-persistence','rollback-readiness','permanent-supervision-tasks','disaster-recovery-backup'];
  const criticalCanaries=new Set(['docker-engine','persistent-containers','backend-health','interface-local','model-runtime']);const canaries=names.map(id=>check('canary:'+id,id,criticalCanaries.has(id)?'CRITICAL':'DEGRADED'));Object.assign(canaries.at(-1),{fresh:false,status:'UNKNOWN',state:'UNKNOWN',reason:'NO_QUALIFIED_OFF_DEVICE_DESTINATION_OR_CLEAN_HOST_RESTORE_EVIDENCE'});
  const value={schema_version:'orqevia.telemetry.v1',source:{instance:'browser-fixture',revision:'a'.repeat(40)},observed_at:stamp,freshness_seconds:60,audience:{client_id:'browser-owner'},metrics:[{metric_id:'registered_agents',collection_status:'OBSERVED',value:21},{metric_id:'active_job_records',collection_status:'OBSERVED',value:1}],agents:[],
   service_health:{schema_version:'orqevia.service-health.v1',status:'UNKNOWN',observed_at:stale?old:stamp,last_success_at:last,freshness_seconds:120,reason:stale?'COLLECTOR_RECEIPT_STALE':'MONITORING_COVERAGE_INCOMPLETE',functionality:{status:'HEALTHY',scope:'DECLARED_SERVICE_FUNCTIONAL_CHECKS_ONLY',reason:'REQUIRED_SERVICE_PROBES_PASSED'},services,collector_checks:collectors,canary_checks:canaries,coverage:{complete:false,critical_complete:true,inventory_complete:true,canary_freshness_seconds:1200,required_canary_checks:names,required_critical_checks:[...services.flatMap(row=>row.checks),...canaries].filter(row=>row.severity==='CRITICAL').map(row=>row.check_key)}},
   critical_issues:{schema_version:'orqevia.operational-incidents.v1',observed_at:stale?old:stamp,last_success_at:last,coverage_complete:true,store_status:'OBSERVED',critical_count:0,known_critical_count:stale?2:0,incidents:[],reason:stale?'COLLECTOR_RECEIPT_STALE':'CRITICAL_MONITORING_COMPLETE'}};
  return route.fulfill({status:200,contentType:'application/json',headers:{'X-ORQEVIA-Protocol':'orqevia.interface.v1','Cache-Control':'no-store'},body:JSON.stringify(value)});
 });
 await page.goto('/pwa/?view=live-systems');await waitForSession(page);await expect(page.locator('#core-services-count')).toHaveText('HEALTHY');await expect(page.locator('#critical-count')).toHaveText('0');await expect(page.locator('#service-health-list')).toContainText('Broader monitoring coverage: INCOMPLETE');await expect(page.locator('#service-health-list')).toContainText('NO_QUALIFIED_OFF_DEVICE_DESTINATION_OR_CLEAN_HOST_RESTORE_EVIDENCE');
 stale=true;await page.reload();await waitForSession(page);await expect(page.locator('#core-services-count')).toHaveText('STALE');await expect(page.locator('#core-services-count')).toHaveAttribute('data-collection-status','STALE');await expect(page.locator('#critical-count')).toHaveText('STALE');await expect(page.locator('#critical-count')).toHaveAttribute('data-collection-status','STALE');await expect(page.locator('#critical-detail')).toContainText('known critical records 2');await expect(page.locator('#critical-detail')).toContainText('COLLECTOR_RECEIPT_STALE');
});

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
