# Permanent ORQEVIA interface access and UX standard

Owner-directed P0 standing order, 15 October 2026. Permanent until explicitly
superseded by the Owner. Applies to all existing and future ORQEVIA interfaces.

Open ORQEVIA → enter workspace → select any page → use its functionality.

## Trust and recovery

Previously enrolled devices restore their existing identity and server-assigned
role automatically. Eight-hour short sessions use Secure, HttpOnly, SameSite
host-only cookies; trusted device credentials last 90 days and are stored only
as hashes server-side. Active short sessions renew in the background within the
device trust lifetime. Refresh, page changes and normal service restarts must
not enroll again. Expiry and explicit revocation require clear recovery through
the existing local authenticated owner pairing flow. A new device establishes
trust once; opening a public shell never grants owner authority.

While checking trust, show restoration. Transport failure shows offline/retry,
never a spurious enrollment request or a false connected state. Do not destroy
device credentials on network errors. Do not publish secrets in frontend code,
URLs, logs or browser storage. Keep private records inaccessible without current
backend authorization; mutations retain owner-role and same-origin checks.

## Navigation and operational visibility

Intelligence opens useful public observation retrieval, provider provenance,
history, alerts and cited RAG on the first click. God's Eye is directly named in
navigation and exposes real service health, available operational metrics,
agent availability, task/evidence drill-down, map and event feed. Registration
is not agent liveness. Stored observations are not a claim of global live coverage.
No fabricated data or silent blank screens. Every data panel needs loading,
empty, offline, error and retry behavior. Partial service failure must not disable
unrelated working panels. Navigation, back and refresh preserve page identity.

ABEX owns implementation and execution. Dell independently reviews only.
Do not impose historical PRIME/SSOT/21-agent, DigitalOcean or Azure certification
as access or implementation dependencies. Retain compatible running services
and existing records without treating legacy names as current architecture.

## Required release evidence

Verify Home, first-click Intelligence and directly accessible God's Eye through
the deployed external TLS path. Exercise normal enrollment once, valid trusted
restoration, refresh and restart persistence, session expiry, revocation, member
and anonymous denial, same-origin mutation enforcement, actual retrieval and
provenance, offline/error recovery and owned-record isolation. Test existing
objective, task and artifact flows for regressions. Preserve preimages and data,
record source/image/container identities, and verify reversible rollout.

Actual owner-device acceptance is distinct from automated trusted test-device
evidence. Record limitations precisely. A screenshot, mockup, build or source
test alone cannot satisfy operational acceptance.
