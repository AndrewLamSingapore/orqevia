'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const {configuration, ORIGINS, PATHS} = require('../scripts/fabric_browser_probe.cjs');

test('operator configuration admits only the two exact origins and a local module', () => {
  const module_path = path.resolve(__dirname, 'operator-playwright-module');
  for (const origin of ORIGINS) assert.equal(configuration({origin, module_path}).origin, origin);
  for (const origin of ['https://example.com', 'http://localhost:8443', 'https://localhost:8443/private', 'https://localhost:8443@evil.test']) {
    assert.throws(() => configuration({origin, module_path}), /INVALID_BROWSER_CONFIGURATION/);
  }
  assert.throws(() => configuration({origin: 'https://localhost:8443', module_path: './untrusted'}));
  assert.throws(() => configuration({origin: 'https://localhost:8443', module_path, command: 'anything'}));
});

test('probe paths are the three fixed public surfaces', () => {
  assert.deepEqual(PATHS, ['/', '/capabilities', '/pwa/']);
});
