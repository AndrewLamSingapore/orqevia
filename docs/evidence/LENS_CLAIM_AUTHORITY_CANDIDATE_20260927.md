# Deterministic claim-authority projection — isolated candidate

Date: 27 September 2026. Scope: result projection only, not production promotion
or complete Evidence Lens qualification.

Base: `1e77ae10834465f579452b9086014f0c2ab3a62b`.
Branch: `fix/lens-claim-authority-20260927`.

## Preserved failure

The root investigator observed production task
`df319f44-4832-45a3-8602-e786bda257ca` on accepted source
`b171253566e7c879283d2aacf699ae6c1ec8988e`: the stored architecture
assessment was `UNVERIFIED` because canonical governance evidence was unavailable,
but the returned result wrapper asserted `authoritative: true` and replaced its
governance provenance with `CANONICAL_REGISTRY_AND_RUNTIME`.

Production's unavailable answer is preserved as a fail-closed lookup, not a
fabricated or stale answer. The image omits the governance directory; historical
Gen1 answers observed in a source checkout are a separate source-selection issue.

Before changing `app/objective_api.py`, the new regression file ran against the
base implementation: **15 failed in 1.86 seconds**. Both missing-directory cases
failed on `assert True is False`. Other failures exposed absent verification
status or the same overbroad authority flag.

## Narrow correction

The existing `SYSTEM_FACT` type and text remain compatible. Result projection now
preserves the nested verification state and source category. Claim authority is
true only when every included current-turn system assessment is `VERIFIED`, with
nonempty valid metadata bound to the exact returned text. Missing/malformed or
text-mismatched assessment metadata defaults to `UNVERIFIED`.

Mixed assessments retain individual source/status entries. Historical turns cannot
promote the current turn. Every system result explicitly has
`may_update_truth_plane: false`: returning a verified fact is not permission to
write acceptance state or durable truth. Task completion and authoritative
execution metadata are unchanged.

## Executed verification

Using the existing canonical Python environment, fresh temporary test data and
queue directories, bytecode disabled, and pytest cache disabled:

```text
pytest tests/test_system_fact_authority.py tests/test_system_architecture.py
       tests/test_authoritative_result_metadata.py tests/test_evidence_product.py
       tests/test_prime_evidence_adapter.py tests/test_phase2_evidence_adapter.py
       -q -p no:cacheprovider --tb=short
68 passed in 5.97s
```

Coverage includes the production-shaped missing governance directory, valid
registered facts, unverified/unavailable/partial/stale/contradicted states,
missing/unbound metadata, current-turn selection and mixed evidence.

The existing canonical CI allowlist now includes `system_fact_authority`, so the
new regression is enforced by normal CI rather than only this focused run.
Final sequential canonical execution passed **531 tests in 74.81 seconds**,
with one existing AnyIO `BlockingPortal` deprecation warning. Canonical source
and generated mirror validation reported `CONSISTENT`; the existing operational
record remained `STALE` (not changed by this candidate).

The five existing PWA suites also passed: `tests.mjs` 11, `followup-tests.mjs` 6,
`revision-tests.mjs` 15, `candidate-tests.mjs` 9, and `voice-tests.mjs` 14:
**55 passed, zero failures**. Simulated voice lifecycle tests do not establish
physical audible output or reopen the parked audio gate.

Canonical CI ran with one pytest worker, not a stress workload. One-second
sampling of the actual interpreter child (not the Windows venv launcher)
observed peak working set 94,597,120 bytes and last-observed CPU 11.109375
seconds. These are process observations, not a whole-host benchmark. Raw logs
and JUnit evidence were retained at
`C:\Users\Admin\AppData\Local\Temp\lens-claim-canonical-final-374c0dea99244426b247abe12735e00d`.

## Remaining boundary

This repair does not package or retrieve current governance evidence, implement
live Evidence Lens/SSOT integration, repair unsupported model claims, change
production, or establish physical acceptance. It is an isolated candidate;
production remains on accepted Golden Gen 2. Complete Evidence Lens qualification
remains unresolved and cannot be claimed from these tests.
