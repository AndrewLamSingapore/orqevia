import http from 'node:http';
import { createHash, randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadConfig, publicConfig } from './lib/config.mjs';
import { InterfaceNode, sanitizeTask } from './lib/upstream.mjs';

const ROOT = fileURLToPath(new URL('./public/', import.meta.url));
const MIME = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.svg': 'image/svg+xml' };
const MAX_BODY = 32_768;
const MAX_ARTIFACT = 100 * 1024 * 1024;

function json(res, status, value) {
  const body = JSON.stringify(value);
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'content-length': Buffer.byteLength(body), 'cache-control': 'no-store' });
  res.end(body);
}

async function bodyJson(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > MAX_BODY) throw new Error('Request body is too large');
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}');
}

async function relayJson(response, res, sanitize = value => value) {
  const value = await response.json();
  if (!response.ok) return json(res, response.status, { error: String(value?.error || `ABEX request failed (${response.status})`) });
  return json(res, response.status, sanitize(value));
}

async function serveStatic(pathname, res) {
  const relative = pathname === '/' ? 'index.html' : pathname.slice(1);
  const safe = normalize(relative).replace(/^(\.\.[/\\])+/, '');
  const target = join(ROOT, safe);
  if (!target.startsWith(ROOT)) return json(res, 404, { error: 'Not found' });
  try {
    const bytes = await readFile(target);
    res.writeHead(200, { 'content-type': MIME[extname(target)] || 'application/octet-stream', 'content-length': bytes.length, 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' });
    res.end(bytes);
  } catch { json(res, 404, { error: 'Not found' }); }
}

export function createDellServer(config = loadConfig(), fetchImpl = fetch) {
  const upstream = new InterfaceNode(config, fetchImpl);
  return http.createServer(async (req, res) => {
    const requestId = randomUUID();
    res.setHeader('x-request-id', requestId);
    res.setHeader('content-security-policy', "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; base-uri 'none'; frame-ancestors 'none'");
    try {
      const url = new URL(req.url, 'http://localhost');
      if (url.pathname === '/api/local/status' && req.method === 'GET') return json(res, 200, publicConfig(config));
      if (!url.pathname.startsWith('/api/')) return serveStatic(url.pathname, res);
      if (!config.ready) return json(res, 503, { error: 'Dell client is locked until ABEX connection settings are complete', details: config.errors });

      if (url.pathname === '/api/health' && req.method === 'GET') return relayJson(await upstream.health(), res);
      if (url.pathname === '/api/objectives' && req.method === 'POST') {
        const body = await bodyJson(req);
        const key = req.headers['idempotency-key'];
        if (!key || !/^[A-Za-z0-9-]{8,128}$/.test(key)) throw new Error('A valid Idempotency-Key header is required');
        return relayJson(await upstream.submit(body.objective, key), res, sanitizeTask);
      }

      let match = url.pathname.match(/^\/api\/tasks\/([^/]+)$/);
      if (match && req.method === 'GET') return relayJson(await upstream.task(match[1]), res, sanitizeTask);
      match = url.pathname.match(/^\/api\/tasks\/([^/]+)\/artifacts$/);
      if (match && req.method === 'GET') return relayJson(await upstream.artifacts(match[1]), res);
      match = url.pathname.match(/^\/api\/tasks\/([^/]+)\/cancel$/);
      if (match && req.method === 'POST') return relayJson(await upstream.cancel(match[1]), res, sanitizeTask);
      match = url.pathname.match(/^\/api\/tasks\/([^/]+)\/events$/);
      if (match && req.method === 'GET') {
        const controller = new AbortController();
        req.on('close', () => controller.abort());
        const response = await upstream.events(match[1], controller.signal);
        if (!response.ok || !response.body) return relayJson(response, res);
        res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-store', connection: 'keep-alive' });
        for await (const chunk of response.body) res.write(chunk);
        return res.end();
      }
      match = url.pathname.match(/^\/api\/artifacts\/([^/]+)\/download$/);
      if (match && req.method === 'GET') {
        const response = await upstream.artifact(match[1]);
        if (!response.ok) return relayJson(response, res);
        const expected = response.headers.get('x-artifact-sha256')?.toUpperCase();
        if (!/^[A-F0-9]{64}$/.test(expected || '')) throw new Error('Artifact is missing a valid SHA-256 header');
        const bytes = Buffer.from(await response.arrayBuffer());
        if (bytes.length > MAX_ARTIFACT) throw new Error('Artifact exceeds the 100 MiB Dell retrieval limit');
        const observed = createHash('sha256').update(bytes).digest('hex').toUpperCase();
        if (observed !== expected) throw new Error('Artifact hash verification failed');
        const filename = (response.headers.get('x-artifact-name') || `artifact-${match[1]}`).replace(/[^A-Za-z0-9._ -]/g, '_');
        res.writeHead(200, { 'content-type': response.headers.get('content-type') || 'application/octet-stream', 'content-length': bytes.length, 'content-disposition': `attachment; filename="${filename}"`, 'x-artifact-sha256': observed, 'cache-control': 'no-store' });
        return res.end(bytes);
      }
      json(res, 404, { error: 'Not found' });
    } catch (error) {
      json(res, 502, { error: error instanceof Error ? error.message : 'Request failed', requestId });
    }
  });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const config = loadConfig();
  const server = createDellServer(config);
  server.listen(config.port, config.listenHost, () => {
    console.log(`JARVIS Dell thin client: http://${config.listenHost}:${config.port}`);
    console.log(config.ready ? `Locked to ${config.expectedHost}; authority remains ABEX_ONLY.` : `LOCKED: ${config.errors.join('; ')}`);
  });
}
