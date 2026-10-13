import test from 'node:test';
import assert from 'node:assert/strict';
import {normalLatestLines} from './dashboard.mjs';
const now=Date.parse('2026-10-13T11:00:00Z');
const fixture=()=>({status:'OBSERVED',normal_denominator:21,reassessed_count:21,normal_pass_count:21,normal_fail_count:0,
  full_role_accepted_count:0,certification_awarded:false,reconciled_at:new Date(now).toISOString(),last_execution_at:new Date(now-300000).toISOString(),
  assessment_runtime_revision:'a'.repeat(40),observer_runtime_revision:'b'.repeat(40),
  agents:Array.from({length:21},(_,i)=>({agent_id:'agent-'+i,execution_bound:true,latest_pass:true}))});
test('latest normal replay remains distinct from readiness and full acceptance',()=>{
  const lines=normalLatestLines(fixture(),now);assert.match(lines[0],/21 \/ 21 pass/);assert.match(lines[1],/0 \/ 21 established/);assert.match(lines[2],/Historical waves and failures remain retained/);
});
test('latest normal counts fail closed on tamper missing pins stale future and duplicate rows',()=>{
  for(const edit of [value=>value.normal_pass_count=20,value=>value.agents[0]=value.agents[1],value=>value.agents[0].execution_bound=false,
    value=>value.agents[0].latest_pass='true',value=>value.full_role_accepted_count=21,value=>value.certification_awarded=true,
    value=>value.reconciled_at=new Date(now+6000).toISOString(),value=>value.reconciled_at=new Date(now-60001).toISOString(),
    value=>value.last_execution_at='invalid',value=>value.observer_runtime_revision='UNKNOWN']){
    const value=fixture();edit(value);assert.equal(normalLatestLines(value,now),null);
  }
});
