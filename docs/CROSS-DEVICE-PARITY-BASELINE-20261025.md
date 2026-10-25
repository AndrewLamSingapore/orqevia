# Cross-device parity baseline

Inspected before implementation on 25 October 2026. Live source was
`d747b4685ec13419ad001e124b365eaef88b88d5`; integration starts from the reviewed
UI branch `0e51859b6e0788ad6bd805ef1481acb80c1c1620`.

Verified causes:

- `dashboard.css` explicitly hid `.dashboard-top`, `.dashboard-tasks` and
  `.dashboard-bottom` below700px. Mobile Home substituted a welcome, shortcut
  grid and separate readiness summary for the desktop operational panels.
- Navigation styles used different700px/760px breakpoints. Operations was
  nested in More; several desktop routes were missing from that menu.
- The existing telemetry request was shared, but task/activity rows came from
  device-local selected-task events. A second device could legitimately have
  no selected event while the first displayed one. This is not an authoritative
  cross-device task inventory.
- A missing active-job metric selected the IDLE badge through a falsey branch,
  even though the adjacent text said activity was unavailable.
- The v39 update reload key represented the loaded page rather than the target
  worker. A later controller change in the same tab could be ignored. Offline
  fallback used a global cache lookup instead of the current generation.
- An actual verified-HTTPS sweep of all39 shell resources found
  `integration-panels.mjs` returned404 while the other38 returned200. Its source
  exists and Intelligence imports it, but the image recipes omitted it. The
  worker's atomic shell installation therefore failed. The release now copies
  the complete explicit public asset set from source; CI checks shell and
  transitive module coverage in both current image recipes.
- Actual browser testing confirmed a second data-path defect: session metadata
  advertised the generic open-mode identity while cookie middleware retained the
  durable PWA client identity. The strict audience check correctly rejected the
  mismatch despite a valid fresh telemetry200 response. Session metadata must
  match the identity injected by the existing middleware; the check is retained.
- Open-mode account metadata also replaced durable PWA account bindings with a
  generic account, causing ownership conflicts. The correction preserves active
  server session accounts and expired-session ownership fallback, excluding
  other accounts before reading their current policy. No accounts are rewritten.
- Real light-theme overview labels had1.6595:1 contrast on white. Shared labels
  now use the existing theme's muted text token for both color schemes.

The desktop shortcut targets `https://localhost:8443/pwa/`. The public hostname's
configured origin routes to the same HTTPS interface with CA validation. Direct
origin requests with the public Host header and local requests returned identical
workspace HTML. Anonymous public requests reach existing Cloudflare Access;
authenticated edge readback and the actual phone's cached state are not verified
by that origin check. `/` is a separate static public overview; `/pwa/` is the
application and its unchanged manifest identity/start URL.

Reuse: the existing telemetry contract, canonical objective state calculation,
interface request/account ownership tables, TaskStore retry references, shared
dashboard DOM and established HTTPS gateway. No new database, executor, service,
framework, queue guard or mandatory integration is needed.

Implementation contract: one authenticated telemetry snapshot drives shared
overview, readiness, gauges, owner-authorized work observations and activity.
Missing observations stay UNKNOWN/UNAVAILABLE. Browser task events trigger a
server refresh instead of inventing shared execution facts. Snapshot UUID,
observation time and runtime revision bind rendered values to the actual API
response. Responsive layout reflows those same panels rather than selecting a
different fact source. Worker/page generation is separately observable and never
presented as system health; updates preserve existing trust and unsaved input.
