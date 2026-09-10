# Implementation mandate: verified development candidate

This is an implementation inventory, not a new frozen specification, replacement
operational SSOT, authority grant or production qualification. Canonical STALE
and the Independent Authority Witness production boundary remain in effect.

## Provenance

The Dell checkout at `C:/Users/User/OneDrive/Documents/prime` is clean at
`c449dd1c8e22976c97507733201807d4d73bf92e`. A separate September 8 remediation
checkout contains uncommitted PR59 work; it was inspected and left untouched.
GitHub inspected September 10 reports PR59 open/draft, production HOLD, head
`17126125e0fad398f5603ce3c76754abe2bcb880`, main
`b999caabbe3371b0e1c333721bf59ea0f669f666`, mergeable=false. Main's changes from
the Dell checkout are governance records only. The candidate imports all 53
changed files at the exact PR59 head through the GitHub connector, verifies
their Git blob hashes, and retains the unchanged source files from c449dd1.
Its local import commit has a different history; it is not the remote commit.

## Implementation inventory and scope

| Area | Evidence and status |
| --- | --- |
| Stable Spine | Existing deterministic PDP, durable decision records and trust tightening; preserved |
| Harness | Existing signed v2 envelopes, nonce/expiry/revocation checks, durable consumption, execution-time revalidation; baseline tests pass |
| Scheduling | Existing global single-slot pilot, priority/fairness, queue claims and bounded unsigned retries; signed consumed work never automatically retries |
| Authority witness | Existing development capsule and clone/replay adversaries; synthetic root/provider only, production qualification absent |
| Deterministic feasibility | Bounded arithmetic, exact UTF-8 SHA256, existing schema validation and canonical agent lookup; matching requests complete without inference, malformed matching requests reject, provider boundary rechecks |
| Intent orchestration | New authenticated `/api/harness/intent` selects one of a14/a16/a21 then uses existing dispatch and signed queue; a bounded pilot interface, not general autonomous planning |
| Inference routing | Existing local-only pilot preserved; controlled feasibility reason codes added; cloud executor remains disabled |
| Accounting | Missing provider token usage stays null through queue and summaries; known partial sums labeled incomplete; attempts, confirmed model calls and agent calls distinguished for new worker events; historical events remain explicitly unclassified |
| Recovery | Queue faults back off 1/2/4/8 seconds, exhaust after five consecutive failures and expose attention status; bounded recovery transitions use the existing event ledger; finish failures never repeat inference; stop/start preserves live-worker exclusion |
| Operator UI | Evidence-based four-state overview and plain-language CLI status; diagnostic details separated; frozen read-only Control Surface preserved with no execution UI |
| ABEX | Owner confirms device has not arrived; commissioning/deployment cannot run |
| Deployment package | Existing September 8 Day-0 command pack and commissioning specification found; review planner/tests exist, production root/provider adapters still unavailable; not represented as an executable production bootstrap |
| Current runtime | Docker backend and native Ollama processes observed; Docker executable denied by Windows account permissions; immutable container provenance not freshly established |
| Offline Companion | Four external frozen design artifacts not yet materialized in this checkout, confirmed by owner; dependent implementation held |
| Web3 | Policy artifact not yet materialized/location unresolved, confirmed by owner; no numeric model-tier floor invented; no wallet/deploy/admin/transfer executor added |
| VELYQUA | Existing observation integration preserved; no new sensor evidence, Gate 1/2/3 qualification or predictive ML claimed |
| AgentScope/Hermes | Existing dependency gate remains parked |
| Other projects | Portal, Game/Living Worlds and Sky left untouched; execution priorities are Work, Web3, VELYQUA per owner mandate |
| Attention integrations | No WhatsApp, iMessage or separate notification subsystem added |

## New request contracts

Owner-authenticated `POST /api/harness/intent` accepts `intent`, optional
`correlation_id` and `idempotency_key`. The owner need not choose a pilot agent.
Cost/pricing/budget words select a21; dataset/duplicate/quality words select a14;
remaining pilot analysis selects a16. This is deliberately selective and does
not activate all 29 registry entries. Inference retains the existing 202 queued
response and poll endpoint. A completed deterministic request returns 200,
zero model/token use and `action_authority=false`. Exact-contract failure
returns 422 with `resolution_path=reject`; ledger failure returns 503.

Examples: `calculate (12 + 4) / 2`, `0.1 + 0.2`, `sha256 text: abc`,
`validate schema policy-state-v1: "AUTO"`, `lookup agent a14`.
Arithmetic returns exact rational strings (`3/10`, not rounded `0.3`). Only
addition, subtraction, multiplication, division, parentheses and unary signs
are supported. Length, syntax-tree size and integer size are bounded. No eval,
file I/O, network lookup or caller-registered plugin participates. Pure
computation creates no action authorization. Existing pilot dispatch also
applies this gate, so choosing a deep model cannot override a matching contract.
Unknown general tasks remain eligible only for the existing local pilot.

This is a finite capability registry, not a claim of universal deterministic
feasibility detection. Future capabilities need explicit bounded contracts and
tests. No cloud model-tier or Web3 floor is inferred from these examples.

## Dependent phase gates

The owner identified these exact external artifacts, without supplying contents:

1. `companion-node.v1.yaml`, identifier `jarvis.companion.node.v1.0.0`.
2. `offline-export-policy.v1.yaml`.
3. `offline-reconciliation-protocol.v1.yaml`, identifier
   `jarvis.companion.reconciliation-protocol.v1.0.0`.
4. `offline-companion-verification.v1.yaml`.

Status: EXTERNAL DESIGN ARTIFACTS / NOT YET MATERIALIZED IN THIS CHECKOUT.
Identity → Export → Reconciliation → Verification remains the dependency order.
No file contents are reconstructed from filenames. Companion proposes only;
PRIME independently revalidates. Web3 policy status is NOT YET MATERIALIZED /
LOCATION UNRESOLVED. W3-01 remains one repository, one test wallet, one testnet,
one simple contract, zero real funds and PRIME approval/receipt evidence.

Production promotion requires the existing protected surviving root, trusted
time/signing custody, real provider start/termination, OS/host clone exclusion,
exclusive ingress and estate-wide one-slot evidence. Development tests cannot
replace those gates. ABEX has not arrived, so there is no commissioned target,
host identity or target evidence. The Dell remains a development/operator host;
this work starts no authority service or model and copies no production secret.

## Reproduction

Using Python 3.12 and the existing `requirements-witness-dev.txt` dependencies,
set `PRIME_DATA_DIR`, `PRIME_SPINE_DB`, and `PRIME_COMPUTE_DB` to disposable test
paths, then run:

```
python -m pytest -q
python -m scripts.probe_checkpoint_replay
python -m compileall -q app scripts
python scripts/verify_operational_manifest.py --allow-stale
python scripts/generate_resume_checkpoint.py --check
```

Baseline: 395 tests passed on this Dell. Candidate results are retained in the
delivery report alongside machine-readable JUnit evidence. Tests use temporary
databases, synthetic providers and test credentials only. Hosted Ubuntu and
container acceptance are development evidence; real-provider, deployment and
physical-host acceptance are not claimed. See `docs/OPERATIONS_RECOVERY.md` and
`docs/LAM_OPERATOR_GUIDE.md` for observation/recovery semantics and limitations.

The dedicated Compute Profile Benchmark Protocol, addenda and full ABEX Workload
Corpus were not identified. Existing benchmark fixtures are not replacements.
Dependency scans cover only the isolated test environment, not the live estate.
