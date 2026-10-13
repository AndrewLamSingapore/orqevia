import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {coachingStatus} from './dashboard.mjs';

const time = Date.parse('2026-10-12T01:00:00Z');
const observed = {status: 'OBSERVED', last_event_at: new Date(time).toISOString(), cohort_id: 'c', cohort_source_revision: 'a'.repeat(40), baseline_pass_count: 0, acceptance_pass_count: 0, completed_count: 0, agents: []};

assert.equal(coachingStatus(observed, time), 'OBSERVED');
assert.equal(coachingStatus(observed, time + 60001), 'STALE');
assert.equal(coachingStatus({...observed, status: 'UNAVAILABLE', last_event_at: null}, time), 'UNAVAILABLE');
assert.equal(coachingStatus({...observed, last_event_at: 'not a timestamp'}, time), 'UNKNOWN');
assert.equal(coachingStatus({...observed, last_event_at: new Date(time + 6000).toISOString()}, time), 'UNKNOWN');
assert.equal(coachingStatus(null, time), 'UNKNOWN');
assert.equal(coachingStatus({status: 'OBSERVED'}, time), 'UNKNOWN');

const html = readFileSync(new URL('./index.html', import.meta.url), 'utf8');
assert.ok(html.includes('id="coaching-view"'));
assert.ok(html.includes('data-view="coaching"'));
assert.ok(html.includes('id="coaching-summary"') && html.includes('id="coaching-roles"'));
assert.ok(!html.includes('21/21 agents ready'));

const css = readFileSync(new URL('./dashboard.css', import.meta.url), 'utf8');
assert.ok(css.includes('.coaching-roles'));

console.log('Coaching dashboard: status transitions, malformed/future rejection, DOM and style wiring PASS');
