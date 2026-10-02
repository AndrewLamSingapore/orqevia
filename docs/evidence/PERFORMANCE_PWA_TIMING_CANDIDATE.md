# PWA timing candidate — 2026-10-02

`clients/pwa/app.mjs` now connects the existing `TaskTiming` recorder to an objective submitted in the PWA. The recorder is disabled by default. Open the PWA with `?pwa_timing=1` to opt in for that page load, submit an objective, and inspect `window.getJarvisPwaTiming()` in the browser console. Nothing is sent to a server or persisted. The next submission replaces the previous samples.

The snapshot contains only a fixed stage name and elapsed monotonic milliseconds from the submission request: `submit_start`, `submit_ack`, `events_start/end`, `status_start/end`, `first_contribution`, `render_end`, and `terminal`. Polling marks may repeat; first contribution and terminal occur at most once. A snapshot may be incomplete after an error, abort, or page close. The recorder receives no objective, task ID, identity, token, credential, header, or response body.

`submit_start` is marked immediately before the Interface request, after client digest and local pending-state preparation. `submit_ack` is marked when that request returns an authoritative task. `first_contribution` marks the first nonempty current result inserted into the DOM. `render_end` marks completion of `renderTask` including local history update, and `terminal` marks completion of a terminal task render. These DOM marks do not measure browser paint or the first model token. They do not establish an end-to-end Owner latency baseline by themselves.

Verification: `node --check clients/pwa/app.mjs` and `node --test clients/pwa/timing-tests.mjs clients/pwa/revision-tests.mjs` passed (19 tests). No production PWA trial or deployment was performed.
