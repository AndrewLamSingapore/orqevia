import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('../app/control_surface.html', import.meta.url), 'utf8');
const line = prefix => source.split(/\r?\n/).find(value => value.startsWith(prefix));
const approvalCard = new Function(`${line('const $=')} ${line('function approvalCard(x)')}; return approvalCard;`)();

test('approval keys with quotes and markup remain inert data and reach the delegated handler intact', () => {
  const key = `case'\");globalThis.injected=true;//<svg onload=alert(1)>&quot;`;
  const markup = approvalCard({
    status: 'PENDING', idempotency_key: key, title: 'Review', risk: 'low',
    source: 'test', reversibility: 'yes', evidence: [], expected_effect: {},
  });
  assert.equal((markup.match(/data-approval-key=/g) || []).length, 3);
  assert.doesNotMatch(markup, /\sonclick=/);
  assert.match(markup, /&#39;/);
  assert.match(markup, /&quot;/);
  assert.match(markup, /&lt;svg/);
  assert.match(markup, /&amp;quot;/);

  let clickHandler;
  const button = {dataset: {approvalKey: key, decision: 'approve'}};
  const approvalList = {
    addEventListener: (name, handler) => { assert.equal(name, 'click'); clickHandler = handler; },
    contains: node => node === button,
  };
  const calls = [];
  new Function('$', 'decideApproval', line("$('approvalList').addEventListener('click'"))(
    () => approvalList, (id, decision) => calls.push({id, decision}),
  );
  clickHandler({target: {closest: () => button}});
  assert.deepEqual(calls, [{id: key, decision: 'approve'}]);
  assert.equal(globalThis.injected, undefined);
});
