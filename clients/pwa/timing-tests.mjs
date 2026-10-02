import test from 'node:test';
import assert from 'node:assert/strict';
import {TaskTiming} from './timing.mjs';

test('timing is disabled by default and emits no samples', () => {
  const timing = new TaskTiming({clock: () => {throw Error('clock must not be read');}});
  assert.equal(timing.start(), false);
  assert.equal(timing.mark('terminal'), false);
  assert.deepEqual(timing.snapshot(), {schema:'jarvis.pwa.timing.v1',enabled:false,samples:[]});
});

test('opt-in timing records monotonic elapsed stages without content or identity', () => {
  let now = 100;
  const timing = new TaskTiming({enabled:true,clock:() => now});
  assert.equal(timing.start(), true);
  now += 23.25; timing.mark('submit_ack');
  now += 10; timing.mark('events_start');
  now += 5; timing.mark('events_end');
  now += 2; timing.mark('status_start');
  now += 7; timing.mark('status_end');
  now += 1; timing.mark('first_contribution');
  now += 3; timing.mark('render_end');
  now += 1; timing.mark('terminal');
  assert.deepEqual(timing.snapshot().samples.map(s => s.stage),[
    'submit_start','submit_ack','events_start','events_end','status_start',
    'status_end','first_contribution','render_end','terminal'
  ]);
  assert.equal(timing.snapshot().samples[1].elapsed_ms,23.25);
  assert.equal(timing.mark('terminal'),false);
  assert.deepEqual(Object.keys(timing.snapshot()),['schema','enabled','samples']);
});

test('invalid stages, backward clock, and mutation of snapshots are rejected or isolated', () => {
  let now = 5;
  const timing = new TaskTiming({enabled:true,clock:() => now});
  timing.start();
  assert.throws(() => timing.mark('objective text'),TypeError);
  now = 4;
  assert.throws(() => timing.mark('status_start'),RangeError);
  const copy=timing.snapshot();copy.samples[0].stage='tampered';
  assert.equal(timing.snapshot().samples[0].stage,'submit_start');
});

test('recorder is bounded and restart clears prior task samples', () => {
  let now = 1;
  const timing = new TaskTiming({enabled:true,clock:() => now});
  timing.start();
  for(let i=0;i<200;i++){now += 1;timing.mark('events_start');}
  assert.equal(timing.snapshot().samples.length,128);
  timing.start();
  assert.deepEqual(timing.snapshot().samples,[{stage:'submit_start',elapsed_ms:0}]);
});
