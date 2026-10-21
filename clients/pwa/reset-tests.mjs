import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const html = readFileSync(new URL('./reset.html', import.meta.url), 'utf8');
const source = readFileSync(new URL('./reset.mjs', import.meta.url), 'utf8');

test('repair route loads a same-origin module without inline script', () => {
  assert.match(html, /<script type="module" src="\/pwa\/reset\.mjs"><\/script>/);
  assert.doesNotMatch(html, /<script(?![^>]*\bsrc=)[^>]*>/);
});

test('repair clears only ORQEVIA workers and shell caches', () => {
  assert.ok(source.includes('registration.scope'));
  assert.ok(source.includes("startsWith('/pwa/')"));
  assert.ok(source.includes("['jarvis-shell-', 'orqevia-shell-']"));
  assert.ok(source.includes('registration.unregister()'));
  assert.ok(source.includes('caches.delete(name)'));
  assert.ok(!source.includes('localStorage.clear'));
  assert.ok(!source.includes('document.cookie'));
});

test('repair returns to the current workspace without a reload loop', () => {
  assert.ok(source.includes('location.replace(`/pwa/?recovered=${Date.now()}`)'));
  assert.ok(!source.includes('location.reload'));
});
