import { isIP } from 'node:net';

const LOOPBACK_NAMES = new Set(['127.0.0.1', '::1', 'localhost']);
const SHA256 = /^[a-f0-9]{64}$/i;

export function loadConfig(env = process.env) {
  const rawUrl = env.JARVIS_ABEX_BASE_URL?.trim() || '';
  let baseUrl;
  let urlError = '';
  try {
    baseUrl = new URL(rawUrl);
    if (baseUrl.protocol !== 'https:') urlError = 'ABEX URL must use HTTPS';
    if (baseUrl.username || baseUrl.password) urlError = 'ABEX URL must not contain credentials';
    baseUrl.pathname = baseUrl.pathname.replace(/\/$/, '');
    baseUrl.search = '';
    baseUrl.hash = '';
  } catch {
    urlError = 'ABEX URL is missing or invalid';
  }

  const expectedHost = env.JARVIS_ABEX_EXPECTED_HOST?.trim() || '';
  const identitySha256 = env.JARVIS_ABEX_IDENTITY_SHA256?.trim() || '';
  const clientId = env.JARVIS_CLIENT_ID?.trim() || '';
  const token = env.JARVIS_CLIENT_TOKEN?.trim() || '';
  const listenHost = env.JARVIS_DELL_LISTEN_HOST?.trim() || '127.0.0.1';
  const port = Number(env.JARVIS_DELL_LISTEN_PORT || 4317);

  const errors = [];
  if (urlError) errors.push(urlError);
  if (!expectedHost) errors.push('Expected ABEX hostname is missing');
  if (!SHA256.test(identitySha256)) errors.push('ABEX identity pin must be a SHA-256 hex value');
  if (!clientId) errors.push('Dell client ID is missing');
  if (!token) errors.push('Client token is missing');
  if (!LOOPBACK_NAMES.has(listenHost)) errors.push('Dell UI listener must be loopback-only');
  if (!Number.isInteger(port) || port < 1024 || port > 65535) errors.push('Dell UI port is invalid');

  return {
    baseUrl,
    expectedHost,
    identitySha256: identitySha256.toUpperCase(),
    clientId,
    token,
    listenHost,
    port,
    ready: errors.length === 0,
    errors,
    authority: 'ABEX_ONLY',
    localRole: 'THIN_CLIENT'
  };
}

export function publicConfig(config) {
  return {
    configured: config.ready,
    errors: config.errors,
    expectedHost: config.expectedHost || null,
    upstream: config.baseUrl?.origin || null,
    clientId: config.clientId || null,
    authority: config.authority,
    localRole: config.localRole
  };
}

export function assertSafeSegment(value, label = 'identifier') {
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value || '')) {
    throw new Error(`Invalid ${label}`);
  }
  return encodeURIComponent(value);
}
