// Deterministic failure/recovery contract fixtures; never live health evidence.
import assert from 'node:assert/strict';
import test from 'node:test';
import {healthFacts,operationalFacts,sampleFreshness} from './dashboard.mjs';

const now=Date.parse('2026-10-27T05:00:00Z'),iso=delta=>new Date(now+delta*1000).toISOString();
const canaryNames=['docker-engine','persistent-containers','backend-health','cloud-inference-configuration','interface-local','cloudflare-tunnel','auth-boundary','host-telemetry-freshness','model-runtime','fabrics-and-ai-scaffold-imports','agent-liveness-receipt','deployment-identity','queue-runtime-and-cost','workflow-and-notebook-persistence','rollback-readiness','permanent-supervision-tasks','disaster-recovery-backup'];
function snapshot(){
  const check=(check_key,check_id,severity='CRITICAL')=>({check_key,check_id,severity,status:'PASS',fresh:true,observed_at:iso(0)});
  const services=['backend','interface','ollama','intelligence','coaching','otel-collector','integration-gateway','cloudflared','cloudflared-dual'].map(service_id=>({service_id,status:'HEALTHY',checks:[check('service:'+service_id+':fixture','fixture')]}));
  const collectors=['collector-source','host-identity','boot-identity'].map(name=>check('collector:'+name,name,'DEGRADED'));
  const criticalCanaries=new Set(['docker-engine','persistent-containers','backend-health','interface-local','model-runtime']);
  const canaries=canaryNames.map(name=>check('canary:'+name,name,criticalCanaries.has(name)?'CRITICAL':'DEGRADED'));
  const requiredCritical=[...services.flatMap(row=>row.checks),...canaries].filter(row=>row.severity==='CRITICAL').map(row=>row.check_key);
  return {schema_version:'orqevia.telemetry.v1',source:{instance:'fixture-host',revision:'a'.repeat(40)},observed_at:iso(0),freshness_seconds:60,agents:[],
    metrics:[{metric_id:'cpu',value:0,collection_status:'OBSERVED',producer:'host-collector',event_timestamp:iso(-30)}],
    host:{captured_at:now/1000-30,max_age_seconds:150,source:{host_id:'fixture-host'},field_status:{cpu_percent:{collection_status:'OBSERVED',captured_at:now/1000-30,source:'native-fixture'}}},
    service_health:{schema_version:'orqevia.service-health.v1',observed_at:iso(0),freshness_seconds:120,status:'HEALTHY',services,
      functionality:{status:'HEALTHY',scope:'DECLARED_SERVICE_FUNCTIONAL_CHECKS_ONLY',reason:'REQUIRED_SERVICE_PROBES_PASSED'},
      collector_checks:collectors,canary_checks:canaries,coverage:{complete:true,critical_complete:true,inventory_complete:true,canary_freshness_seconds:1200,required_canary_checks:canaryNames,required_critical_checks:requiredCritical}},
    critical_issues:{schema_version:'orqevia.operational-incidents.v1',observed_at:iso(0),coverage_complete:true,store_status:'OBSERVED',critical_count:0,known_critical_count:0,incidents:[]}};
}
test('measured zero retains original native timestamp and provenance',()=>{
  const value=snapshot(),health=healthFacts(value,now);assert.equal(health.metrics.cpu.value,0);assert.equal(health.metrics.cpu.capturedAt,now/1000-30);assert.equal(health.metrics.cpu.source,'native-fixture');assert.equal(operationalFacts(value,now).host.cpu,0);
});
test('fresh API cannot renew an expired or malformed child host sample',()=>{
  for(const stamp of [now/1000-151,now/1000+6,'2026-10-27 05:00:00',null]){const value=snapshot();value.host.field_status.cpu_percent.captured_at=stamp;value.metrics[0].event_timestamp=stamp;assert.equal(healthFacts(value,now).metrics.cpu.value,null);assert.equal(operationalFacts(value,now).host.cpu,null);}
});
test('an authoritative zero needs every declared critical sample and the observed incident store',()=>{
  assert.equal(healthFacts(snapshot(),now).critical.count,0);
  for(const corrupt of [v=>v.service_health.services.pop(),v=>v.service_health.services[0].checks=[],v=>v.service_health.services[0].checks[0].observed_at=iso(-121),v=>v.service_health.collector_checks[0].observed_at=iso(-121),v=>v.service_health.canary_checks[0].observed_at=iso(-1201),v=>v.critical_issues.store_status='UNAVAILABLE',v=>v.critical_issues.coverage_complete=false,v=>v.critical_issues.critical_count=null,v=>v.service_health.services[0]=v.service_health.services[1]]){
    const value=snapshot();corrupt(value);assert.equal(healthFacts(value,now).critical.count,null);
  }
});
test('missing and disconnected snapshots immediately clear healthy facts',()=>{
  assert.equal(healthFacts(null,now).critical.count,null);assert.equal(healthFacts(null,now).core.status,'UNKNOWN');assert.equal(healthFacts(snapshot(),now+61000).core.status,'STALE');assert.equal(healthFacts(snapshot(),now+61000).metrics.cpu.value,null);
});
test('fresh failure reports real critical count and a later valid recovery restores zero',()=>{
  const value=snapshot();value.service_health.status='CRITICAL';value.service_health.functionality.status='UNHEALTHY';value.service_health.services[0].status='CRITICAL';value.service_health.services[0].checks[0].status='FAIL';value.critical_issues.critical_count=1;assert.equal(healthFacts(value,now).critical.count,1);assert.equal(healthFacts(value,now).core.status,'CRITICAL');assert.equal(healthFacts(snapshot(),now).critical.count,0);
});
test('partial monitoring keeps known records separate from authoritative count',()=>{
  const value=snapshot();value.critical_issues.coverage_complete=false;value.critical_issues.known_critical_count=2;const health=healthFacts(value,now);assert.equal(health.critical.count,null);assert.equal(health.critical.knownCount,2);
});
test('original timestamps require timezone and bounded future tolerance',()=>{
  assert.equal(sampleFreshness(iso(6),150,now),'UNKNOWN');assert.equal(sampleFreshness('2026-10-27T05:00:00',150,now),'UNKNOWN');assert.equal(sampleFreshness(iso(-151),150,now),'STALE');
});

test('stale collector is explicit while original samples and known incidents stay historical',()=>{
  const value=snapshot();value.service_health.observed_at=iso(-121);value.service_health.reason='COLLECTOR_RECEIPT_STALE';value.service_health.last_success_at=iso(-3600);
  value.critical_issues.observed_at=iso(-121);value.critical_issues.last_success_at=iso(-3600);value.critical_issues.reason='COLLECTOR_RECEIPT_STALE';value.critical_issues.known_critical_count=2;
  const health=healthFacts(value,now);assert.equal(health.core.status,'STALE');assert.equal(health.critical.status,'STALE');assert.equal(health.critical.count,null);assert.equal(health.critical.knownCount,2);assert.equal(health.core.observedAt,iso(-121));assert.equal(health.critical.lastSuccessAt,iso(-3600));assert.equal(health.monitoring.status,'STALE');
});

test('noncritical unknown verification does not hide checked core services or verified critical coverage',()=>{
  const value=snapshot();value.service_health.status='UNKNOWN';value.service_health.coverage.complete=false;
  const backup=value.service_health.canary_checks.find(check=>check.check_id==='disaster-recovery-backup');backup.status='UNKNOWN';backup.fresh=false;backup.reason='NO_QUALIFIED_OFF_DEVICE_DESTINATION_OR_CLEAN_HOST_RESTORE_EVIDENCE';
  const health=healthFacts(value,now);assert.equal(health.core.status,'HEALTHY');assert.equal(health.critical.count,0);assert.equal(health.monitoring.status,'INCOMPLETE');assert.equal(health.monitoring.complete,false);assert.equal(health.canaryChecks.at(-1).reason,backup.reason);
});

test('canary coverage follows source-owned identities rather than a fixed sixteen or seventeen count',()=>{
  const value=snapshot();assert.equal(value.service_health.canary_checks.length,17);assert.equal(healthFacts(value,now).critical.count,0);
  const extra={check_id:'future-noncritical-check',check_key:'canary:future-noncritical-check',severity:'DEGRADED',fresh:true,status:'PASS',observed_at:iso(0)};
  value.service_health.canary_checks.push(extra);value.service_health.coverage.required_canary_checks=[...canaryNames,extra.check_id];assert.equal(healthFacts(value,now).critical.count,0);
  for(const corrupt of [v=>delete v.service_health.coverage.required_canary_checks,v=>v.service_health.coverage.required_canary_checks=[...canaryNames,'docker-engine'],v=>v.service_health.canary_checks.pop(),v=>v.service_health.canary_checks[1]=v.service_health.canary_checks[0]]){
    const invalid=snapshot();corrupt(invalid);const health=healthFacts(invalid,now);assert.equal(health.critical.count,null);assert.equal(health.monitoring.complete,false);assert.equal(health.monitoring.status,'UNKNOWN');
  }
});

test('missing critical declarations, stale critical samples and stale store never become zero',()=>{
  for(const corrupt of [v=>delete v.service_health.coverage.required_critical_checks,v=>v.service_health.coverage.required_critical_checks.pop(),v=>v.service_health.coverage.critical_complete=false,v=>v.service_health.services[0].checks=[],v=>v.service_health.canary_checks[0].fresh=false,v=>v.critical_issues.observed_at=iso(-121),v=>v.critical_issues.schema_version='unrecognized',v=>v.service_health.schema_version='unrecognized']){
    const value=snapshot();corrupt(value);assert.equal(healthFacts(value,now).critical.count,null);
  }
  const stale=snapshot();stale.critical_issues.observed_at=iso(-121);assert.equal(healthFacts(stale,now).critical.status,'STALE');
});

test('unconfigured collection remains distinct and missing provenance cannot prove core health',()=>{
  const value=snapshot();value.service_health.status='NOT_CONFIGURED';assert.equal(healthFacts(value,now).core.status,'NOT_CONFIGURED');assert.equal(healthFacts(value,now).critical.status,'NOT_CONFIGURED');assert.equal(healthFacts(value,now).critical.count,null);
  for(const corrupt of [v=>delete v.service_health.functionality,v=>delete v.service_health.collector_checks,v=>v.service_health.collector_checks[0].status='FAIL',v=>v.service_health.services.pop()]){const missing=snapshot();corrupt(missing);assert.notEqual(healthFacts(missing,now).core.status,'HEALTHY');}
});

test('invalid or missing source inventory cannot prove health while confirmed failures remain visible',()=>{
  for(const corrupt of [v=>delete v.service_health.coverage.inventory_complete,v=>v.service_health.coverage.inventory_complete=false,v=>v.service_health.services.push(v.service_health.services[0]),v=>v.service_health.services.pop(),v=>v.service_health.services[0]=v.service_health.services[1]]){
    const value=snapshot();corrupt(value);const health=healthFacts(value,now);assert.equal(health.core.status,'UNKNOWN');assert.equal(health.critical.count,null);
  }
  const value=snapshot();value.service_health.coverage.inventory_complete=false;value.service_health.functionality.status='UNHEALTHY';value.service_health.services[0].status='CRITICAL';value.service_health.services[0].checks[0].status='FAIL';assert.equal(healthFacts(value,now).core.status,'CRITICAL');assert.equal(healthFacts(value,now).critical.count,null);
});

test('malformed service checks remain unavailable without hiding a separately confirmed failure',()=>{
  for(const malformed of [null,false,0,'invalid',[],{}]){
    const value=snapshot();value.service_health.services[0].checks.push(malformed);const health=healthFacts(value,now);assert.equal(health.core.status,'UNKNOWN');assert.equal(health.critical.count,null);assert.equal(health.services[0].status,'UNKNOWN');assert.equal(health.services[0].reason,'MALFORMED_SERVICE_CHECKS');assert.equal(health.services[0].checks.at(-1).status,'UNKNOWN');
    value.service_health.functionality.status='UNHEALTHY';value.service_health.services[1].status='CRITICAL';value.service_health.services[1].checks[0].status='FAIL';assert.equal(healthFacts(value,now).core.status,'CRITICAL');
  }
  for(const checks of [null,{},'invalid']){const value=snapshot();value.service_health.services[0].checks=checks;const health=healthFacts(value,now);assert.equal(health.core.status,'UNKNOWN');assert.equal(health.services[0].reason,'MALFORMED_SERVICE_CHECKS');assert.deepEqual(health.services[0].checks,[]);}
  const oversized=snapshot();for(let index=0;index<16;index++)oversized.service_health.services[0].checks.push({check_id:'extra-'+index,check_key:'service:backend:extra-'+index,severity:'DEGRADED',status:'PASS',fresh:true,observed_at:iso(0)});assert.equal(healthFacts(oversized,now).core.status,'UNKNOWN');assert.equal(healthFacts(oversized,now).critical.count,null);
});

test('validated execution growth retains its conservative clock and unavailable growth stays unknown',()=>{
  const value=snapshot(),backend=value.service_health.services[0],check=backend.checks[0],oldKey=check.check_key;
  Object.assign(check,{check_id:'backend-readiness',check_key:'service:backend:backend-readiness',scope:'PERSISTENCE_AND_RECENT_WORKER_EXECUTION',reason:'PERSISTENCE_AND_RECENT_EXECUTION_PROGRESS_OBSERVED',observed_at:iso(-60)});
  value.service_health.coverage.required_critical_checks=value.service_health.coverage.required_critical_checks.map(key=>key===oldKey?check.check_key:key);
  let facts=healthFacts(value,now);assert.equal(facts.core.status,'HEALTHY');assert.equal(facts.services[0].checks[0].observed_at,iso(-60));assert.equal(facts.services[0].checks[0].reason,check.reason);
  check.observed_at=iso(-121);facts=healthFacts(value,now);assert.equal(facts.core.status,'UNKNOWN');assert.equal(facts.critical.count,null);
  Object.assign(check,{status:'UNKNOWN',fresh:false,reason:'WORKER_EXECUTION_PROGRESS_NOT_CONFIRMED',observed_at:iso(0)});backend.status='UNKNOWN';value.service_health.functionality.status='UNKNOWN';
  facts=healthFacts(value,now);assert.equal(facts.core.status,'UNKNOWN');assert.equal(facts.critical.count,null);assert.equal(facts.services[0].checks[0].reason,check.reason);
  Object.assign(check,{status:'PASS',fresh:true,scope:'PERSISTENCE_AND_NATIVE_WORKER_HEARTBEAT',reason:'PERSISTENCE_AND_NATIVE_WORKER_HEARTBEAT_OBSERVED',observed_at:iso(-60)});backend.status='HEALTHY';value.service_health.functionality.status='HEALTHY';
  facts=healthFacts(value,now);assert.equal(facts.core.status,'HEALTHY');assert.equal(facts.services[0].checks[0].reason,'PERSISTENCE_AND_NATIVE_WORKER_HEARTBEAT_OBSERVED');
});
