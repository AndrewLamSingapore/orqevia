# Playwright and PWA test report - 2026-10-19

## Status

**COMPLETE for automated desktop/browser assurance.**

Physical iPhone/Safari installation, microphone and audible-output acceptance
remain a separate physical-device gate.

## Toolchain

| Item | Version |
|---|---:|
| Node.js local | 24.20.0 |
| Node.js project pin | 22 |
| pnpm | 12.14.0 |
| Playwright | 1.63.0 |
| Chromium | 153.0.8010.12 |
| Firefox | 155.0 |
| WebKit | 26.6 |

## Test topology

- `clients/pwa/playwright.config.mjs` defines Chromium, Firefox and WebKit.
- `clients/pwa/browser-test-server.mjs` serves only `/pwa/` content on
  `127.0.0.1`; API paths are not silently redirected.
- Sessions and task responses are mocked with existing protocol headers.
- Service workers are allowed only in the PWA-specific test file and blocked in
  workflow tests to avoid engine-specific interception ambiguity.
- CI retries are bounded; Playwright is configured to mark flaky retries as
  failures in CI.

## Coverage

### Shell and responsive layout

- ORQEVIA title and dashboard load.
- Desktop primary navigation opens Agents with updated URL and capability view.
- Mobile layout exposes the mobile navigation while hiding desktop navigation.
- No horizontal document/body overflow at 1440px desktop or 390px mobile.
- Duplicate DOM IDs: none.
- Unlabeled buttons: none in the checked initial shell.

### PWA

- Manifest is served as `application/manifest+json`.
- Manifest identity/scope/start URL and standalone display mode are correct.
- 192px, 512px and maskable icons are present.
- Service worker installs and controls the page.
- `orqevia-shell-v28` cache is present.
- Cached shell is readable offline.
- Chromium performs a controlled offline reload successfully.
- Firefox exposes an engine-level `NS_ERROR_OFFLINE` during automated offline
  navigation on Windows; its service-worker cache was fetched and validated
  directly.
- WebKit exposes an internal Playwright offline-reload error on Windows; manifest,
  service-worker control and cache were verified, but offline navigation is not
  claimed for that engine.

### Critical workflow

- Session is established through the existing `/pwa/api/session` shape.
- New Objective opens the actual composer.
- Objective submission sends the expected JSON body.
- `X-ORQEVIA-PWA: 1` and idempotency headers are present.
- No browser `Authorization` header or bearer credential is sent.
- Terminal task result and task ID render in the active workspace.

## Executed command

```powershell
cd clients/pwa
corepack pnpm install --frozen-lockfile
corepack pnpm exec playwright install chromium firefox webkit
corepack pnpm test:browser
```

Final result:

```text
15 passed
```

Five tests per browser engine.

Additional JavaScript tests:

```powershell
corepack pnpm test:unit
```

Result:

```text
81 passed, 0 failed
```

## Regression found and repaired

The browser suite exposed a real routing defect:

```text
New Objective -> view("objective") -> unknown view fallback -> Home
```

`dashboard.mjs` now explicitly registers `objective` as a valid view:

```javascript
known.add("objective")
```

The Playwright workflow test and a source-level dashboard assertion both guard
the repair.

## Evidence

- JSON: `clients/pwa/browser-results/results.json`
- HTML: `clients/pwa/browser-results/html/`
- Failure-only screenshots/videos/traces: `clients/pwa/browser-results/artifacts/`
- CI artifact: `orqevia-browser-assurance`

Generated browser evidence is excluded from Git by `.gitignore`.

## Deployed live endpoint

After promotion, Chromium, Firefox and WebKit loaded
`https://192.168.1.23:8443/pwa/` with HTTP 200 and title `ORQEVIA`. Each
reported a visible dashboard, manifest and no horizontal overflow. Chromium
also verified the mobile viewport and the deployed `view=objective` route.
