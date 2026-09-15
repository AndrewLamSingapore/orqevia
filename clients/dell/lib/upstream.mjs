import { createHash } from 'node:crypto';
import { assertSafeSegment } from './config.mjs';

const API_PREFIX = '/interface/v1';
const ALLOWED_STATES = new Set([
  'RECEIVED', 'ROUTED', 'RUNNING', 'WAITING', 'REPAIRING',
  'VALIDATING', 'COMPLETED', 'FAILED', 'RECOVERING'
]);

export class InterfaceNode {
  constructor(config, fetchImpl = fetch) {
    this.config = config;
    this.fetch = fetchImpl;
    this.identityVerifiedAt = 0;
  }

  headers(extra = {}) {
    return {
      authorization: `Bearer ${this.config.token}`,
      'x-jarvis-client-id': this.config.clientId,
      'x-jarvis-protocol-version': '1',
      ...extra
    };
  }

  url(path) {
    if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//') || path.includes('\\')) throw new Error('Invalid Interface Node path');
    const target = new URL(this.config.baseUrl.href);
    const prefix = target.pathname.replace(/\/+$/, '') + API_PREFIX;
    target.pathname = prefix + path;
    target.search = ''; target.hash = '';
    if (target.origin !== this.config.baseUrl.origin || !target.pathname.startsWith(prefix + '/')) throw new Error('Interface Node origin/path mismatch');
    return target;
  }

  async fetchInterface(path, init) {
    const target = this.url(path);
    const response = await this.fetch(target, { ...init, redirect: 'error' });
    if (response.redirected || (response.status >= 300 && response.status < 400) ||
        (response.url && new URL(response.url).origin !== target.origin)) throw new Error('Interface Node redirect rejected');
    return response;
  }

  async verifyIdentity(force = false) {
    if (!this.config.ready) throw new Error(`Client is not configured: ${this.config.errors.join('; ')}`);
    if (!force && Date.now() - this.identityVerifiedAt < 30_000) return;
    const response = await this.fetchInterface('/identity', { headers: this.headers(), signal: AbortSignal.timeout(8000) });
    if (!response.ok) throw new Error(`ABEX identity check failed (${response.status})`);
    const body = await response.json();
    const canonical = JSON.stringify({
      hostname: body.hostname,
      role: body.role,
      protocolVersion: body.protocolVersion,
      publicKey: body.publicKey
    });
    const observed = createHash('sha256').update(canonical, 'utf8').digest('hex').toUpperCase();
    if (body.hostname !== this.config.expectedHost) throw new Error('ABEX hostname mismatch');
    if (body.role !== 'AUTHORITATIVE_PRIME') throw new Error('Upstream does not claim authoritative PRIME role');
    if (String(body.protocolVersion) !== '1') throw new Error('Unsupported Interface Node protocol version');
    if (observed !== this.config.identitySha256) throw new Error('ABEX identity pin mismatch');
    this.identityVerifiedAt = Date.now();
  }

  async request(path, init = {}) {
    await this.verifyIdentity();
    const response = await this.fetchInterface(path, {
      ...init,
      headers: this.headers(init.headers),
      signal: init.signal || AbortSignal.timeout(30_000)
    });
    return response;
  }

  async health() { return this.request('/health'); }

  async submit(objective, idempotencyKey) {
    if (typeof objective !== 'string' || !objective.trim() || objective.length > 20_000) {
      throw new Error('Objective must contain 1 to 20,000 characters');
    }
    return this.request('/objectives', {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'idempotency-key': idempotencyKey },
      body: JSON.stringify({ objective: objective.trim() })
    });
  }

  task(id) { return this.request(`/tasks/${assertSafeSegment(id, 'task ID')}`); }
  artifacts(id) { return this.request(`/tasks/${assertSafeSegment(id, 'task ID')}/artifacts`); }
  events(id, signal) { return this.request(`/tasks/${assertSafeSegment(id, 'task ID')}/events`, { signal }); }
  cancel(id) { return this.request(`/tasks/${assertSafeSegment(id, 'task ID')}/cancel`, { method: 'POST' }); }
  artifact(id) { return this.request(`/artifacts/${assertSafeSegment(id, 'artifact ID')}`); }
}

export function sanitizeTask(value) {
  const task = value && typeof value === 'object' ? value : {};
  if (!ALLOWED_STATES.has(task.state)) throw new Error('Upstream returned an invalid task state');
  return {
    taskId: String(task.taskId || ''),
    state: task.state,
    message: String(task.message || ''),
    updatedAt: String(task.updatedAt || ''),
    result: task.result ?? null
  };
}
