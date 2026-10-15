# Fabric and gateway integration matrix

Pinned source main `25675aa35baf6e6b49a4682bd6e7666c796dc4de`; 15 October 2026. No fabric or registered identity was created, renamed or granted new authority.

| Path | Decision boundary | Enforcement boundary | Identity / scope | Audit / state | Current evidence and gaps |
| --- | --- | --- | --- | --- | --- |
| Existing direct application connector execution | Trusted registered sink consequence tags | `ConnectorRegistry.execute` + `SinkGuard.check`; protected tags default deny without trusted authorizer | Authenticated endpoint/task must bind agent; per-agent `execute_for_agent` checks version and registry eligibility | `DirectExecutor` writes bounded action records | Installed. Direct execution is deliberately not a universal signed-envelope harness. Logging failures become unavailable-ledger status rather than a universal execution gate. Cannot claim every action always durably logged. |
| Legacy deterministic PDP | `spine.classify_action`: AUTO/BOUNDED_AUTO/GATED/PROHIBITED; exact bounded sink restrictions | Signed `ActionHarness` validates key/envelope/lease/actor/action/budgets and executor revalidation | Actor/tenant/envelope and tool limits | Durable harness leases/events, Failsafe when constructed/wired | Source and installed files exist; direct production route does not universally mount this path. A legacy class name is not current live enforcement evidence. |
| Legacy host effects | `host_guard.classify_effect` examines action/nested arguments | `enforce_at_execution` requires owner approval ID + exact effect digest for host-high-risk+ | Bound action/executable/arguments/target | Caller/harness receipt | Used by HarnessedExecutor. Do not describe as automatically protecting unrelated standalone routes. |
| Bounded engineering WASM | Owner authentication + role allowlist + memory-capacity admission | No imports, Wasmtime fuel/memory/table/instance limits, two slots | A12Builder alias a17; A13TestEngineer alias a18 | Connector action observation | Source and installed path. No general native shell execution implied. Isolation is a working control, not a blocker to remove. |
| Compute/model gateway | Configured provider roles, allow_cloud, data class, trusted price/cost/concurrency policy | Queue leases/admission; model gateway inference-only checks | Canonical job actor, task ID, bounded model selection | SQLite compute queue/ledger | Live terminal jobs observed. Registry model unassigned is distinct from historical actual queue provider/model bindings. No fresh paid call made. |
| Hyper-Inference Fabric | Deterministic adaptive reasoning/router and explicit supplied permissions | Mock proxy registries check local permission/cost/time quota arguments | Advisory traces; permissions passed by caller | In-memory mock receipts and UIEF scorecard | Qualified metadata says advisory_only; real model/tool proxy adapter not installed or integrated. Router output grants no execution authority. |
| Skills/orchestration | Versioned manifest/dependencies/qualified metadata | Skill router chooses advisory pack; neither SKILLS nor PLAN grants permission | Declared owner agents; historical registry parked | Source manifests/version records | PLAN qualification and infrastructure tasks stale relative to latest owner scope. |
| Academy/UIEF | Room eligibility/unseen-assessment/budget validation | Library validation, separate in-memory lists | Source agent IDs and room assignments | Transient lists, export objects; existing coaching DB separate | New modules absent live. No new-room persistent schedule/controller connection found. No L7 issuance. |
| New intelligence UI/API | No authenticated caller or per-agent permission resolver | No auth dependencies on router; document retrieval uses fixed APPLICATION scope | Anonymous request accepted by source route shape | SQLite observations + JSON docs/alerts; no execution action-ledger integration | Standalone surface deliberately not mounted production. Ingestion performs external call and state writes. Production exposure blocked until bounded existing-authority integration/storage verification. |
| Event/cognitive/MLP fabric | Existing domain/schema/authority contracts | Legacy cognitive API handlers and MLPCapability authority check | Portfolio event contract; provenance and owning product remain separate | Inbox, graph/review projections, model candidates | Source not mounted production direct app. Retained recovery candidates must not be mistaken for activated routes. |
| Live collective workspace/tool bridge | Existing owner-authenticated branch-specific APIs | Endpoint auth, body bounds, broker/tool eligibility | Per-task original actor/identity metadata | Existing SQLite workspace/bridge + action ledger | Installed branch files exist but absent main. Preserve pending reconciliation; no new delegation attempted. |
| Emergency controls | Existing coaching.pause + source failsafe state machine + bounded worker stopping | Paused coaching readback; legacy failsafe hook where wired | Owner pause marker and actor | PAUSED DB state, preserved marker, historical receipts | Pause state observed. Global emergency-stop operation and full service restart were NOT TESTED; no claim of universal coverage. |

## Security qualification outcomes in this operation

| Control | Actual outcome | Boundary |
| --- | --- | --- |
| Host/source/runtime identity | PASS | Physical host name, OCI/env, installed hashes; no historical Dell substitution |
| Persistent data placement | PARTIAL | Existing /data external volume PASS; new ORQEVIA_DATA_DIR unset and intelligence fallback unsuitable |
| Secret preservation | PASS scoped | No Env dumps/secret values; config originals copied privately; hashes in reports |
| Auth/permissions | PARTIAL / production integration BLOCKED | Existing auth preserved; standalone intelligence router lacks auth integration |
| Tool allowlisting | NOT TESTED live | Source/installed checks reviewed; no real agent tool invocation performed |
| WASM isolation | NOT TESTED live | Source no-import/fuel/memory controls observed; root tests tracked separately |
| Prompt injection | NOT TESTED live | RAG returns content_is_authority false/instructions_may_execute false; flags alone are not attack qualification |
| Resource budgets | PARTIAL | Existing app bounded queue; coaching0.25CPU/256MiB/64PIDs networknone; backend/interface Docker0limits and writable rootfs. No isolated intelligence route rate/body/disk budget found |
| Audit | PARTIAL | Existing action-record file exists; new route is not linked to that ledger; no universal durable-audit claim |
| Failure containment | PASS scoped | Isolated controlled source outage preserves13observations; no production failure injected |
| Persistence | PASS scoped | Fresh subprocess reopened isolated obs/doc/alert data; no production service restart |
| Recovery/rollback | PARTIAL | Fresh13DB backup checks +686artifact hashes + config copies; retained rollback containers. No rollback drill |
| Suspension | PASS observed / NOT TESTED action | Existing marker/controllerPAUSED; no global failsafe transition invoked |
| Unauthorized operation denial | NOT TESTED comprehensive | Existing anonymous route/auth checks covered only by read-only receipts and root tests; no security bypass |

Critical integration gaps block the affected new production route only. They do not globally stop read-only recovery, isolated tests, existing healthy runtime or source reconciliation. No sandbox, auth boundary, failsafe or policy gate was removed.
