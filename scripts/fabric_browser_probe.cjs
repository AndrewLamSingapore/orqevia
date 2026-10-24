'use strict';

// Operator-launched real browser probe. No routing, mocked responses, credentials,
// persistent profiles, TLS bypass, arbitrary URLs or publication are supported.
const crypto = require('node:crypto');
const path = require('node:path');

const ORIGINS = new Set(['https://localhost:8443', 'https://192.168.1.23:9443']);
const PATHS = ['/', '/capabilities', '/pwa/'];
const DEADLINE_MS = 20_000;
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
let activeBrowser;

function configuration(value) {
  if (!value || Array.isArray(value) || typeof value !== 'object' ||
      Object.keys(value).sort().join(',') !== 'module_path,origin' ||
      !ORIGINS.has(value.origin) || typeof value.module_path !== 'string' ||
      !path.isAbsolute(value.module_path) || value.module_path.length > 2048) {
    throw new Error('INVALID_BROWSER_CONFIGURATION');
  }
  return value;
}

async function inspect(config) {
  configuration(config);
  const {chromium} = require(config.module_path);
  const receipt = {
    protocol: 'orqevia.fabric.browser-probe.v1',
    observed_at: new Date().toISOString(),
    status: 'FAIL', origin: config.origin,
    execution_mode: 'REAL_CHROMIUM', mocked: false, tls_bypass: false,
    scope: 'PUBLIC_PAGES_DESKTOP_AND_EMULATED_MOBILE',
    physical_device_verified: false, authenticated_workflow_verified: false,
    execution_status: 'FAILED', pages: [],
  };
  let browser;
  try {
    browser = await chromium.launch({headless: true, timeout: 8000});
    activeBrowser = browser;
    receipt.browser_version = browser.version();
    receipt.playwright_version = require(path.join(config.module_path, 'package.json')).version;
    for (const [view, viewport] of [['desktop', {width: 1440, height: 1000}], ['mobile', {width: 390, height: 844}]]) {
      const context = await browser.newContext({viewport, ignoreHTTPSErrors: false});
      try {
        const page = await context.newPage();
        page.setDefaultTimeout(5000);
        page.setDefaultNavigationTimeout(5000);
        let errors = [];
        let httpErrors = {};
        page.on('pageerror', error => { if (errors.length < 10) errors.push(sha(String(error?.message || 'pageerror'))); });
        page.on('response', response => {
          if (response.status() >= 400) httpErrors[String(response.status())] = (httpErrors[String(response.status())] || 0) + 1;
        });
        for (const target of PATHS) {
          errors = [];
          httpErrors = {};
          const response = await page.goto(config.origin + target, {waitUntil: 'domcontentloaded'});
          const sameOrigin = new URL(page.url()).origin === config.origin;
          if (!sameOrigin) throw new Error('UNEXPECTED_BROWSER_NAVIGATION');
          let mobileMenuExercised = false;
          if (view === 'mobile' && target !== '/pwa/') {
            const menu = page.locator('button.menu-toggle[aria-controls="public-navigation"]');
            if (await menu.isVisible()) {
              await menu.click();
              await page.locator('#public-navigation a:visible').first().waitFor({state: 'visible', timeout: 2000});
              mobileMenuExercised = await menu.getAttribute('aria-expanded') === 'true';
            }
          }
          // Geometry and visible semantics are observed from the real page.
          const geometry = await page.evaluate(() => {
            const visible = element => {
              const box = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return box.width > 0 && box.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const headings = [...document.querySelectorAll('h1')];
            const navigation = [...document.querySelectorAll('nav,[role="navigation"]')];
            return {
              h1_count: headings.length,
              visible_h1_count: headings.filter(visible).length,
              nav_count: navigation.length,
              visible_navigation_controls: navigation.flatMap(element => [...element.querySelectorAll('a,button')]).filter(visible).length,
              document_width: Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0),
              viewport_width: document.documentElement.clientWidth,
            };
          });
          const screenshot = await page.screenshot({type: 'png', fullPage: false, timeout: 3000});
          const row = {
            path: target, view, response_status: response?.status() || 0, same_origin: sameOrigin,
            mobile_menu_exercised: mobileMenuExercised,
            ...geometry,
            horizontal_overflow: geometry.document_width > geometry.viewport_width + 1,
            screenshot_sha256: sha(screenshot),
            page_error_count: errors.length, page_error_sha256: [...errors],
            http_error_status_counts: {...httpErrors},
          };
          row.passed = row.response_status === 200 && row.visible_h1_count > 0 &&
            row.nav_count > 0 && row.visible_navigation_controls > 0 &&
            !row.horizontal_overflow && row.page_error_count === 0 && Object.keys(httpErrors).length === 0;
          receipt.pages.push(row);
        }
      } finally {
        await context.close();
      }
    }
    receipt.execution_status = 'COMPLETED';
    receipt.status = receipt.pages.length === 6 && receipt.pages.every(row => row.passed) ? 'PASS' : 'FAIL';
  } catch (error) {
    receipt.error = 'BROWSER_PROBE_FAILED';
    receipt.error_sha256 = sha(String(error?.message || 'browser failure'));
  } finally {
    if (browser) await browser.close().catch(() => {});
    activeBrowser = undefined;
  }
  return receipt;
}

async function main() {
  let emitted = false;
  let timedOut = false;
  const emit = value => {
    if (!emitted) {
      emitted = true;
      process.stdout.write(JSON.stringify(value) + '\n');
    }
  };
  const deadline = setTimeout(() => {
    timedOut = true;
    emit({protocol: 'orqevia.fabric.browser-probe.v1', status: 'FAIL', error: 'BROWSER_DEADLINE_EXCEEDED', pages: []});
    // Let Playwright terminate its own browser tree. A hung close leaves this
    // process alive so the outer worker can kill the whole tree at 25 seconds.
    process.exitCode = 1;
    if (activeBrowser) void activeBrowser.close().catch(() => {});
  }, DEADLINE_MS);
  try {
    let raw = '';
    for await (const block of process.stdin) {
      raw += block.toString('utf8');
      if (Buffer.byteLength(raw, 'utf8') > 4096) throw new Error('INVALID_BROWSER_CONFIGURATION');
    }
    const result = await inspect(configuration(JSON.parse(raw)));
    emit(result);
    process.exitCode = !timedOut && result.status === 'PASS' ? 0 : 1;
  } catch {
    emit({protocol: 'orqevia.fabric.browser-probe.v1', status: 'FAIL', error: 'INVALID_BROWSER_CONFIGURATION', pages: []});
    process.exitCode = 1;
  } finally {
    clearTimeout(deadline);
  }
}

module.exports = {configuration, inspect, ORIGINS, PATHS};
if (require.main === module) void main();
