# Existing God's Eye and access audit — 15 October 2026

Candidate base 6bad0b54; canonical main resolved to 25675aa35baf6e6b49a4682bd6e7666c796dc4de.

- Existing `app/orqevia/static/gods-eye/map.*` renders the real stored USGS
  observations and freshness; reuse the same geospatial API and mapping math.
- Existing formal `gods-eye/index.html` and `gods-eye.js` expect the semantic
  projection schema. Archived branch `feat/prime-gods-eye-semantic-20261007`,
  commit `8a53df1f8bf4f673a6e58da9dc65d4862db32c45`, was recovered and inspected.
  Its `app/gods_eye_api.py` requires exactly 21 registry agents, exposes a separate
  owner-bearer domain-store boundary, and optionally invokes semantic_fabric.
  Requiring this stack would contradict the new standing order. Preserve it as
  historical work; do not grant PWA users its privileged global-store access.
- Existing `app/interface_telemetry.py` exposes authorized aggregate metrics and
  explicit unknown liveness. Reuse the installed `/interface/v1/telemetry`
  contract; new panels accept variable agent lists and fail independently.
- Existing PWA task/artifact routes enforce account ownership. Link drill-down
  to these routes instead of duplicating or exposing global task records.
- The deployed Intelligence button previously selected only a capability
  description. It had no ingestion/retrieval/map controls. New content belongs
  in the existing primary PWA rather than another enrollment surface.
- Existing durable-device backend already supported 90-day persistence and
  restoration. The frontend showed enrollment before restoration completed
  and discarded visible state after transport failures. Repair that lifecycle;
  renew active sessions without rotating credentials or escalating roles.
- Selected installed PWA modules contained later task/branding/coaching fixes
  absent from main. Reconcile those exact preserved installed files before
  repair. Deploy only selected files additively on the retained Interface base.

Provider-blocked aviation, maritime and geopolitical integrations and optional
formal semantic inference remain explicitly unavailable. This does not prevent
real geospatial, evidence, retrieval, historical or operational observations.
