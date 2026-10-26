// Controlled contract fixtures, never production forecasting evidence.
import assert from 'node:assert/strict';
import test from 'node:test';
import {operationalFacts} from './dashboard.mjs';

const now=Date.parse('2026-10-25T10:00:00Z');
function snapshot(){return {schema_version:'orqevia.telemetry.v1',snapshot_id:'fixture-observation',observed_at:new Date(now).toISOString(),freshness_seconds:60,
  source:{instance:'fixture',revision:'a'.repeat(40)},agents:[],metrics:[
    {metric_id:'registered_agents',collection_status:'OBSERVED',value:21},
    {metric_id:'active_job_records',collection_status:'OBSERVED',value:0},
    {metric_id:'cpu',collection_status:'OBSERVED',value:0}],
  observed_agent_count:21,fresh_agent_count:12,ready_agent_count:8,model_runtime:{ready:true,required_models:['fixture'],missing_models:[]},
  work_observation:{schema_version:'orqevia.owned-work.v1',status:'OBSERVED',scope:'OWNER_ACCOUNT',observed_at:new Date(now).toISOString(),tasks:[],activity:[],has_more:false}};}
function task(){return {id:'owned-task',state:'RUNNING',revision:1,agents:['a02'],progress:null,updated_at:new Date(now).toISOString()};}

test('one authenticated observation produces identical facts without device-local history',()=>{
  const value=snapshot(),desktop=operationalFacts(value,now),phone=operationalFacts(structuredClone(value),now);
  assert.deepEqual(desktop,phone);assert.equal(desktop.snapshotId,value.snapshot_id);assert.equal(desktop.sourceRevision,value.source.revision);
  assert.equal(desktop.registered,21);assert.equal(desktop.ready,8);assert.equal(desktop.activeJobs,0);assert.equal(desktop.host.cpu,0);
});
test('missing measurements and invalid values are unknown while observed zero is preserved',()=>{
  const value=snapshot();value.metrics.push({metric_id:'memory',collection_status:'OBSERVED',value:101},
    {metric_id:'disk',collection_status:'OBSERVED',value:NaN},{metric_id:'network_latency',collection_status:'OBSERVED',value:Infinity});
  let facts=operationalFacts(value,now);assert.deepEqual(facts.host,{cpu:0,memory:null,disk:null,network_latency:null});
  value.metrics.find(row=>row.metric_id==='active_job_records').collection_status='UNAVAILABLE';value.ready_agent_count=99;
  facts=operationalFacts(value,now);assert.equal(facts.activeJobs,null);assert.equal(facts.ready,null);
});
test('expired or future telemetry cannot retain healthy or idle facts',()=>{
  const value=snapshot();let facts=operationalFacts(value,now+61000);assert.equal(facts.status,'STALE');assert.equal(facts.activeJobs,null);assert.equal(facts.work.status,'UNAVAILABLE');
  value.observed_at=new Date(now+6000).toISOString();facts=operationalFacts(value,now);assert.equal(facts.status,'UNKNOWN');assert.equal(facts.registered,null);
});
test('missing, stale or unauthorized canonical work is explicit',()=>{
  const value=snapshot();delete value.work_observation;assert.equal(operationalFacts(value,now).work.status,'UNAVAILABLE');
  value.work_observation=snapshot().work_observation;value.work_observation.observed_at=new Date(now-61000).toISOString();assert.equal(operationalFacts(value,now).work.status,'UNAVAILABLE');
  value.work_observation.status='UNAUTHORIZED';assert.equal(operationalFacts(value,now).work.status,'UNAUTHORIZED');
});
test('duplicate tasks, malformed revisions and future activity fail closed',()=>{
  for(const corrupt of [work=>work.tasks.push(task(),task()),work=>work.tasks.push({...task(),revision:null}),
    work=>work.activity.push({event:'TASK_STATE_OBSERVATION',task_id:'owned-task',state:'RUNNING',timestamp:new Date(now+6000).toISOString()})]){
    const value=snapshot();corrupt(value.work_observation);assert.equal(operationalFacts(value,now).work.status,'UNAVAILABLE');
  }
});
test('canonical reconciliation_required retains an unknown revision instead of hiding all work',()=>{
  const value=snapshot();value.work_observation.tasks.push({...task(),state:'reconciliation_required',revision:null});
  const facts=operationalFacts(value,now);assert.equal(facts.work.status,'OBSERVED');assert.equal(facts.work.tasks[0].revision,null);
});
test('ordinary canonical tasks and timestamped observations preserve their original evidence',()=>{
  const value=snapshot(),work=value.work_observation;work.tasks.push(task());work.activity.push({event:'TASK_STATE_OBSERVATION',task_id:'owned-task',state:'RUNNING',timestamp:new Date(now-1000).toISOString()});
  const facts=operationalFacts(value,now);assert.equal(facts.work,work);assert.equal(facts.work.tasks[0].progress,null);
});
