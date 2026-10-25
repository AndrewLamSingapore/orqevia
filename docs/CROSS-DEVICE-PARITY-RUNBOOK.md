# Shared desktop and iPhone workspace

The workspace remains `/pwa/` on the existing verified HTTPS gateway. Desktop,
iPhone Safari and the installed application's unchanged manifest identity use
the same route tree and authenticated telemetry API. The public `/` overview is
a separate page. Existing Cloudflare Access still applies at the public edge.

## Observation and authorization

`/interface/v1/telemetry` retains `health.read` authorization and now includes
`work_observation`, schema `orqevia.owned-work.v1`. The existing interface request
and account bindings identify tasks visible under the caller's current policy.
`task.read` is additionally required for task metadata. The read-only observer
uses the existing canonical objective calculation, never generated prose or a
device's selected-task history. No new database, service or queue is introduced.

Session metadata advertises the same durable client identity injected by cookie
middleware. The browser retains its strict audience check. In open mode,
execution policy is unchanged; PWA account metadata follows the actual active
server session. Expired-session ownership falls back to preserved bindings.
Other accounts are excluded before policy lookup, while caller and same-account
rebindings still fail closed. No historical account is reassigned or combined.

The schema contains status, scope, observation time, at most 50 recent tasks,
timestamped state observations, truncation information and provenance. Task
records contain original IDs, state, revision, agent IDs, stored timestamps and
execution provenance. Progress remains null unless actually observed. An
interrupted dispatch retains `reconciliation_required` with a null revision.
Prompts, names, uploaded documents, results, credentials and unrelated accounts'
tasks are excluded. Missing or inconsistent storage fails closed.

`operationalFacts()` interprets one response for every screen size. Dashboard
data attributes bind facts to `snapshot_id`, `observed_at` and runtime revision.
Different snapshots can contain changing values; equal snapshot IDs must render
equal facts. Local task notifications request another authenticated observation.
They never populate shared execution evidence. Unknown critical issue and core
service counts stay UNKNOWN. Empty observed work differs from unavailable work.

## Navigation and layout

Home exposes System Overview, Live System Health, Active Tasks and Live Activity
at every supported width. More links to those panels and every desktop module.
Operations is a direct mobile tab. Named PIF and MEL panels precede the existing
36-fabric catalog; their availability remains service-reported. Mobile task rows
retain every field with labels and an authorized task-details action.

## Cache and update behavior

Worker and page release `orqevia-shell-v41` share a generation handshake. Only
the complete current public shell is eligible for offline fallback. Auth, API,
task, result, upload and query requests are excluded. Foreground/resume triggers
an update check. Reload attempts are keyed to the target generation.

An active request, objective draft, attachment or modified input defers reload.
The app signals a safe handoff when busy controls settle. Existing session and
TaskStore reference data are preserved. Shell currency never implies live system
health. Offline data is marked unavailable instead of replayed as live evidence.

An already running v39 page needs an ordinary fresh navigation to acquire the
new update handlers. Reopen the existing HTTPS `/pwa/` link after saving work;
clearing device trust or reinstalling is unnecessary. Automated WebKit device
emulation is separate from physical Safari and installed-PWA acceptance.

## Release and rollback

Build the established HTTPS runtime image with the exact clean source revision.
Both current image recipes explicitly package the complete public shell and its
transitive imports, including `integration-panels.mjs`. The packaging contract
test checks this closure; actual HTTPS acceptance must additionally confirm
every resource is present and the worker installs successfully.
Retain the previous image, complete private configuration and verified SQLite
backups. Stage on the existing HTTPS staging profile, verify ownership, facts,
navigation, cache behavior and actual PIF/MEL/fabric requests. Promote through the
existing backend/interface deployment with PIF and MEL flags unchanged. No queue
guard is used. Restore the preceding image/configuration for rollback while
retaining current databases and all live writes. PIF and MEL keep independent
flags and their separate artifact/version rollback controls.

Production promotion and physical-device acceptance require their own dated
receipts. Unit tests or this runbook do not establish those milestones.
