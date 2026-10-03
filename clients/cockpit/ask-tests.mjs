import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {submitObjective} from './ask.mjs';
import {nextSubmission,acknowledge,ClientError} from '../pwa/core.mjs';

function fixture() {
  let pending=null;
  const calls=[];
  const store={
    async prepare(clientId,digest,uploads,action) {
      assert.equal(clientId,'client-1');
      assert.deepEqual(uploads,[]);
      assert.deepEqual(action,{kind:'new'});
      pending=nextSubmission(pending,digest,'generated-key');
      calls.push('prepare');
      return {pending};
    },
    async ack(clientId,key,task) {
      assert.equal(clientId,'client-1');
      pending=acknowledge(pending,key,task.taskId);
      calls.push('ack');
    }
  };
  return {store,calls,get pending(){return pending;}};
}

test('durable retry key is prepared before POST and acknowledged only after response',async()=>{
  const journal=fixture();
  const api={async submit(objective,key,uploads){journal.calls.push('submit');assert.equal(objective,'Plan safely');assert.equal(key,'generated-key');assert.deepEqual(uploads,[]);return {taskId:'task-1',state:'ROUTED'};}};
  const result=await submitObjective('  Plan safely  ','client-1',api,journal.store);
  assert.equal(result.id,'task-1');
  assert.deepEqual(journal.calls,['prepare','submit','ack']);
  assert.equal(journal.pending.taskId,'task-1');
});

test('uncertain network result preserves the same key for exact replay and blocks a changed objective',async()=>{
  const journal=fixture();
  const keys=[];
  let attempt=0;
  const api={async submit(_objective,key){keys.push(key);if(++attempt===1)throw new TypeError('network');return {taskId:'task-2',state:'ROUTED'};}};
  await assert.rejects(submitObjective('Same objective','client-1',api,journal.store),TypeError);
  await assert.rejects(submitObjective('Different objective','client-1',api,journal.store),error=>error instanceof ClientError&&error.code==='pending');
  const result=await submitObjective('Same objective','client-1',api,journal.store);
  assert.equal(result.id,'task-2');
  assert.deepEqual(keys,['generated-key','generated-key']);
});

test('failed durable preparation prevents POST',async()=>{
  let submitted=false;
  const store={async prepare(){throw new ClientError('storage');}};
  const api={async submit(){submitted=true;}};
  await assert.rejects(submitObjective('Plan safely','client-1',api,store),error=>error.code==='storage');
  assert.equal(submitted,false);
});

test('failed acknowledgement remains uncertain and replays only the original key',async()=>{
  const journal=fixture();
  const acknowledged=journal.store.ack;
  journal.store.ack=async()=>{throw new ClientError('storage');};
  const keys=[];
  const api={async submit(_objective,key){keys.push(key);return {taskId:'task-3',state:'ROUTED'};}};
  await assert.rejects(submitObjective('Same objective','client-1',api,journal.store),error=>error.code==='storage');
  assert.equal(journal.pending.taskId,null);
  journal.store.ack=acknowledged;
  const result=await submitObjective('Same objective','client-1',api,journal.store);
  assert.equal(result.id,'task-3');
  assert.deepEqual(keys,['generated-key','generated-key']);
});

test('cockpit Ask uses the durable helper and never ignores acknowledgement failure',()=>{
  const source=readFileSync(new URL('./app.mjs',import.meta.url),'utf8');
  assert.match(source,/await submitObjective\(/);
  assert.doesNotMatch(source,/api\.submit\(objective,\s*key/);
  assert.doesNotMatch(source,/store\.ack\([^\n]*\.catch\(/);
});
