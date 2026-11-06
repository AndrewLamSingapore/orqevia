import test from 'node:test';
import assert from 'node:assert/strict';
import { loadConfig, publicConfig, assertSafeSegment } from '../lib/config.mjs';
import { once } from 'node:events';
import { createDellServer } from '../server.mjs';
import { InterfaceNode, sanitizeTask } from '../lib/upstream.mjs';
import { createHash } from 'node:crypto';

const PIN_BODY = { hostname: 'DESKTOP-BGD97NB', role: 'AUTHORITATIVE_ORQEVIA', protocolVersion: '1', publicKey: 'test-key' };
const PIN = createHash('sha256').update(JSON.stringify(PIN_BODY)).digest('hex').toUpperCase();
const goodEnv = {
  JARVIS_ABEX_BASE_URL: 'https://abex.invalid', JARVIS_ABEX_EXPECTED_HOST: 'DESKTOP-BGD97NB',
  JARVIS_ABEX_IDENTITY_SHA256: PIN, JARVIS_CLIENT_ID: 'dell:DESKTOP-IPV4PH9', JARVIS_CLIENT_TOKEN: 'secret',
  JARVIS_DELL_LISTEN_HOST: '127.0.0.1', JARVIS_DELL_LISTEN_PORT: '4317'
};

test('configuration is fail-closed when authority settings are absent', () => {
  const config = loadConfig({});
  assert.equal(config.ready, false);
  assert.equal(publicConfig(config).authority, 'ABEX_ONLY');
  assert.equal(publicConfig(config).localRole, 'THIN_CLIENT');
});

test('plain HTTP and non-loopback listener are rejected', () => {
  const config = loadConfig({ ...goodEnv, JARVIS_ABEX_BASE_URL: 'http://192.168.1.23', JARVIS_DELL_LISTEN_HOST: '0.0.0.0' });
  assert.equal(config.ready, false);
  assert.match(config.errors.join(' '), /HTTPS/);
  assert.match(config.errors.join(' '), /loopback-only/);
});

test('verified identity unlocks an upstream request', async () => {
  const calls = [];
  const fakeFetch = async (url) => {
    calls.push(String(url));
    if (String(url).endsWith('/identity')) return Response.json(PIN_BODY);
    return Response.json({ ok: true });
  };
  const node = new InterfaceNode(loadConfig(goodEnv), fakeFetch);
  const response = await node.health();
  assert.equal(response.status, 200);
  assert.equal(calls.length, 2);
});

test('identity mismatch blocks all task traffic', async () => {
  const fakeFetch = async () => Response.json({ ...PIN_BODY, hostname: 'WRONG-HOST' });
  const node = new InterfaceNode(loadConfig(goodEnv), fakeFetch);
  await assert.rejects(node.health(), /hostname mismatch/);
});

test('task states and path identifiers are bounded', () => {
  assert.equal(sanitizeTask({ taskId: 't1', state: 'RUNNING' }).state, 'RUNNING');
  assert.throws(() => sanitizeTask({ taskId: 't1', state: 'MADE_UP' }), /invalid task state/);
  assert.throws(() => assertSafeSegment('../secrets'), /Invalid identifier/);
});

test('current settings work and conflicting historical aliases fail closed', () => {
  const current = Object.fromEntries(Object.entries(goodEnv).map(([key, value]) => [key.replace(/^JARVIS_/, 'ORQEVIA_'), value]));
  assert.equal(loadConfig(current).ready, true);
  assert.equal(loadConfig({...current, JARVIS_CLIENT_TOKEN: 'different-private-value'}).ready, false);
});

test('desktop opens the HTTPS workspace without weakening API credential checks', async () => {
  const config = loadConfig({...goodEnv, JARVIS_CLIENT_TOKEN: ''});
  const server = createDellServer(config, () => { throw new Error('Redirect must not send an upstream API credential'); });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const origin = `http://127.0.0.1:${server.address().port}`;
  try {
    const response = await fetch(origin + '/', {redirect: 'manual'});
    assert.equal(response.status, 307);
    assert.equal(response.headers.get('location'), new URL('/pwa/', config.baseUrl).href);
    assert.equal(response.headers.get('cache-control'), 'no-store');
    assert.equal((await fetch(origin + '/app.js')).status, 410);
    assert.equal((await fetch(origin + '/api/health')).status, 503);
  } finally {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
});

test('the retired renderer cannot redirect to plaintext or credential-bearing origins', async () => {
  const config = loadConfig({...goodEnv, JARVIS_ABEX_BASE_URL: 'http://untrusted.invalid/'});
  const server = createDellServer(config);
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  try {
    const response = await fetch(`http://127.0.0.1:${server.address().port}/`, {redirect: 'manual'});
    assert.equal(response.status, 503);
    assert.equal(response.headers.get('location'), null);
  } finally {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
});
