// Deterministic failure/recovery contract fixtures; never live health evidence.
import assert from 'node:assert/strict';
import test from 'node:test';
import {healthFacts,operationalFacts,sampleFreshness} from './dashboard.mjs';

const now=Date.parse('2026-10-27T05:00:00Z'),iso=delta=>new Date(now+delta*1000).toISOString();
function snapshot(){
  const check=()=>({status:'PASS',fresh:true,observed_at:iso(0)});
  const services=['backend','interface','ollama','intelligence','coaching','otel-collector','integration-gateway','cloudflared','cloudflared-dual'].map(service_id=>({service_id,status:'HEALTHY',checks:[check()]}));
  return {schema_version:'orqevia.telemetry.v1',source:{instance:'fixture-host',revision:'a'.repeat(40)},observed_at:iso(0),freshness_seconds:60,agents:[],
    metrics:[{metric_id:'cpu',value:0,collection_status:'OBSERVED',producer:'host-collector',event_timestamp:iso(-30)}],
    host:{captured_at:now/1000-30,max_age_seconds:150,source:{host_id:'fixture-host'},field_status:{cpu_percent:{collection_status:'OBSERVED',captured_at:now/1000-30,source:'native-fixture'}}},
    service_health:{schema_version:'orqevia.service-health.v1',observed_at:iso(0),freshness_seconds:120,status:'HEALTHY',services,
      collector_checks:Array.from({length:3},check),canary_checks:Array.from({length:16},check),coverage:{complete:true,canary_freshness_seconds:1200}},
    critical_issues:{schema_version:'orqevia.operational-incidents.v1',observed_at:iso(0),coverage_complete:true,store_status:'OBSERVED',critical_count:0,known_critical_count:0,incidents:[]}};
}
test('measured zero retains original native timestamp and provenance',()=>{
  const value=snapshot(),health=healthFacts(value,now);assert.equal(health.metrics.cpu.value,0);assert.equal(health.metrics.cpu.capturedAt,now/1000-30);assert.equal(health.metrics.cpu.source,'native-fixture');assert.equal(operationalFacts(value,now).host.cpu,0);
});
test('fresh API cannot renew an expired or malformed child host sample',()=>{
  for(const stamp of [now/1000-151,now/1000+6,'2026-10-27 05:00:00',null]){const value=snapshot();value.host.field_status.cpu_percent.captured_at=stamp;value.metrics[0].event_timestamp=stamp;assert.equal(healthFacts(value,now).metrics.cpu.value,null);assert.equal(operationalFacts(value,now).host.cpu,null);}
});
test('an authoritative zero needs complete fresh service collector and canary coverage',()=>{
  assert.equal(healthFacts(snapshot(),now).critical.count,0);
  for(const corrupt of [v=>v.service_health.services.pop(),v=>v.service_health.services[0].checks=[],v=>v.service_health.services[0].checks[0].observed_at=iso(-121),v=>v.service_health.collector_checks[0].observed_at=iso(-121),v=>v.service_health.canary_checks[0].observed_at=iso(-1201),v=>v.critical_issues.store_status='UNAVAILABLE',v=>v.critical_issues.coverage_complete=false,v=>v.critical_issues.critical_count=null,v=>v.service_health.services[0]=v.service_health.services[1]]){
    const value=snapshot();corrupt(value);const health=healthFacts(value,now);assert.equal(health.critical.count,null);assert.notEqual(health.core.status,'HEALTHY');
  }
});
test('missing and disconnected snapshots immediately clear healthy facts',()=>{
  assert.equal(healthFacts(null,now).critical.count,null);assert.equal(healthFacts(snapshot(),now+61000).core.status,'UNKNOWN');assert.equal(healthFacts(snapshot(),now+61000).metrics.cpu.value,null);
});
test('fresh failure reports real critical count and a later valid recovery restores zero',()=>{
  const value=snapshot();value.service_health.status='CRITICAL';value.service_health.services[0].status='CRITICAL';value.service_health.services[0].checks[0].status='FAIL';value.critical_issues.critical_count=1;assert.equal(healthFacts(value,now).critical.count,1);assert.equal(healthFacts(value,now).core.status,'CRITICAL');assert.equal(healthFacts(snapshot(),now).critical.count,0);
});
test('partial monitoring keeps known records separate from authoritative count',()=>{
  const value=snapshot();value.critical_issues.coverage_complete=false;value.critical_issues.known_critical_count=2;const health=healthFacts(value,now);assert.equal(health.critical.count,null);assert.equal(health.critical.knownCount,2);
});
test('original timestamps require timezone and bounded future tolerance',()=>{
  assert.equal(sampleFreshness(iso(6),150,now),'UNKNOWN');assert.equal(sampleFreshness('2026-10-27T05:00:00',150,now),'UNKNOWN');assert.equal(sampleFreshness(iso(-151),150,now),'STALE');
});
