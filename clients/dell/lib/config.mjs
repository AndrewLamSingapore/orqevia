import { isIP } from 'node:net';

const LOOPBACK_NAMES = new Set(['127.0.0.1', '::1', 'localhost']);
const SHA256 = /^[a-f0-9]{64}$/i;

export function loadConfig(env = process.env) {
  const conflicts = [];
  const setting = suffix => {
    const current = env['ORQEVIA_' + suffix]?.trim();
    const historical = env['JARVIS_' + suffix]?.trim();
    if (current && historical && current !== historical) conflicts.push('Conflicting current and historical ' + suffix + ' settings');
    return current || historical || '';
  };
  const rawUrl = setting('ABEX_BASE_URL') || '';
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

  const expectedHost = setting('ABEX_EXPECTED_HOST') || '';
  const identitySha256 = setting('ABEX_IDENTITY_SHA256') || '';
  const clientId = setting('CLIENT_ID') || '';
  const token = setting('CLIENT_TOKEN') || '';
  const listenHost = setting('DELL_LISTEN_HOST') || '127.0.0.1';
  const port = Number(setting('DELL_LISTEN_PORT') || 4317);

  const errors = [...conflicts];
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
