# PR59 development witness implementation

Status: DEVELOPMENT_ONLY; PR remains draft/HOLD for production. SSOT remains
STALE. No production provider, environment switch, startup hook or network
service is installed. The production requirements file and Docker image
dependencies are unchanged. Development dependencies are installed using
`python -m pip install -r requirements-witness-dev.txt`.

`app/development_witness.py` implements a synthetic protected Harness capsule:

- Actual StableSpine remains the sole evaluator. A protected development signing
  facade verifies the existing envelope before signing an Ed25519 commitment to
  its full contents, durable decision, epoch, session and policy content.
- The frontend has status only. Its signatures/requests cannot enroll, approve,
  complete, activate or replace state. Root transitions independently reject
  decreasing rights, substituted bindings, unproven slot release and unsigned
  or stale policy/epoch changes.
- An explicit Anchor retained by the test supervisor models the surviving root.
  The SQLite journal is checked against that anchor, not trusted merely because
  it has a high sequence. Consumption and occupancy commit in one record.
- AVAILABLE can become DENIED or CONSUMED; neither can become AVAILABLE again.
  Epoch and session tombstones persist. Reopening cannot revive old approvals.
- The final start guard rechecks policy, revocation, signature, current epoch,
  input, time and exact consumed slot immediately before the finite fake
  provider starts. No HTTP adapter, generic callback or production provider is
  accepted. The existing worker calls it only through explicit dependency
  injection, which application startup never supplies.
- A separately keyed fake provider supervisor supplies terminal/quiescence
  evidence. Terminal result/audit and slot release share a commit. Unknown
  outcomes retain occupancy. Recovery returns bookkeeping/evidence, never a
  callable permit or retry.
- Rotation requires exact predecessor, current Spine signature, owner recovery
  signature, frozen/empty state, no active provider, fresh session and pinned
  replacement identities. Old capsules cannot continue under the new epoch.

## Evidence scope and limitations

The root is an **explicit development assumption**, not non-restorable hardware.
Python private members, type checks and PID checks are not OS isolation. Same
process privileged code can compromise the model; total root/enforcer compromise
is not a claimed solved threat. Hardware/lifecycle boundary cases assert refusal
and preserve `production_valid=False`; they do not attest a real Dell/ABEX.

The original production path without the injected capsule is not promoted to
rollback-safe. The retained Docker governed smoke exercises that existing path
with a fake Ollama. Its green result is a regression gate, not a witness/provider
isolation claim. Native/Docker Ollama and production PRIME remain untouched.

`tests/test_development_witness.py` names all A01-A45 acceptance families. The
T01-T13 parameterized transition suite tests normal, duplicate, root-loss and
before-prepare/after-prepare/after-head outcomes; T14 tests journal reopening,
missing/corrupted state, cloned paths and lost anchors. Additional tests cover
fabricated increasing roots and signed key rotation. Real process tests keep
the capsule in a separate synthetic supervisor and kill/clone only test workers.

The matrix is a development executable model, not an exhaustive formal proof.
A05/A15/A19/A23/A25/A37 production-boundary claims remain unproved. No assertion
that a live native socket, TPM, all-root compromise or actual GPU quiescence is
safe is inferred from their development-denial checks. Continuous platform
isolation and every R qualification row still require separate target evidence.

The checkpoint probe still copies all three pre-consumption h/s/q databases,
executes the original once and requires rejection of the clone with total mock
calls exactly one. Its only new fixture dependency is the surviving synthetic
capsule outside the copied ledgers. Its exit remains nonzero on failure. Both
Windows and Ubuntu run it as a mandatory step.

## Validation and production prerequisites

Local implementation validation: 395 tests passed with nine existing deprecation
warnings; compile, STALE manifest and generated checkpoint consistency passed.
Hosted exact-head results are reported separately after branch publication.

Production remains HOLD for a qualified surviving root and independent custody;
protected signing and trusted time; real memory/VM/host clone fencing; exclusive
Harness/provider-start and termination hooks; native/Docker/cloud/other ingress
exclusion and estate-wide one-slot proof; historical data continuity and runtime
provenance. ABEX, AgentScope/Hermes, VELYQUA hardware/predictive ML and hardware
acceptance stay pending. No merge, deployment or three-agent pilot is authorized.
