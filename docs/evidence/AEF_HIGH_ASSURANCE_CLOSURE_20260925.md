# Autonomous Engineering Fabric high-assurance closure — 2026-09-25

## Objective contract

- **OBJECTIVE_ID:** `AEF-HA-20260925-01`
- **PROBLEM:** Candidate acceptance relied on verifier assertions and did not
  independently bind source, artifact, executed tests, security receipts, or
  remote durability.
- **DESIRED_OUTCOME:** Assertion-only success fails closed; accepted candidates
  have evidence-bound verifier and provenance receipts.
- **IN_SCOPE:** Engineering verification, candidate provenance, VELYQUA
  physical-evidence firewall, capability register, deterministic tests.
- **OUT_OF_SCOPE:** Production deployment, production data, phones, physical
  Black Start, drivers, firmware, disks, and Windows configuration.
- **AUTHORITY/PRODUCTION BOUNDARY:** Candidate-only; no deployment authority.
- **SECURITY INVARIANTS:** Builder cannot self-certify; model content is not
  physical evidence; unknown/incomplete evidence is rejected.
- **ROLLBACK:** Revert the candidate commits; protected production remains at
  `0ecb5803470bef2a941da31332d87702268648d6`.
- **STOP CONDITIONS:** Production impact, host instability, destructive action,
  or a need for new authority.

## Baseline

- Base SHA: `1ae52ff38fd2d9826a93312e718536025d89e8e5`.
- Branch: `feat/supreme-integration-20260925`.
- Worktree: clean before mutation.
- Reproduction: a verifier returning only `{"passed": true}` produced
  `VERIFIED_CANDIDATE` in one attempt.
- Second reproduction: a VELYQUA `PHYSICAL_VERIFIED` claim with
  `verification_ref="model:self-attested"` set `may_claim_physical=true`.

## Repairs

1. Engineering verification now requires an `a18` independent-verifier
   identity, an exact candidate digest, an explicit `ACCEPT`, and nonempty
   executed checks with evidence references. Assertion-only success is
   normalized to `REJECT` with violations.
2. Candidate provenance now verifies the source commit, immutable artifact
   digest, hashed test/verifier/security receipts, zero failures/skips, source
   ancestry, and the actual remote branch SHA.
3. VELYQUA physical evidence now requires a structured receipt binding device,
   firmware, sensor, observation time, transport provenance, receipt digest,
   and a non-model independent verifier. It still grants no authority.
4. The capability register is schema 2.0 and records purpose, component,
   maturity, evidence, security, offline behavior, recovery, portability, and
   reuse potential without conflating LAB/CANDIDATE/production.

## Adversarial and mutation evidence

- Engineering verifier mutations: 5 assertion/incomplete/wrong-digest cases.
- Candidate provenance mutations: 8 wrong-source, stale-remote, changed
  artifact, fabricated-receipt, hidden-skip, biased-verifier, secret-finding,
  and changed-manifest cases.
- Mutations introduced: 13.
- Mutations detected: 13.
- Mutations survived: 0.
- Independent AEF controls verifier: 5/5.
- Production touched: no.

An initial red-team test implementation failed eight cases because it passed a
mutated package dictionary where the helper expected the full fixture tuple.
That test-harness defect was preserved in command evidence, corrected without
weakening assertions, and the suite reran cleanly.

## Maturity assessment

**Achieved: LEVEL 4 — Autonomous Engineering.**

Evidence supports autonomous specification, reproduction, candidate repair,
independent verification, adversarial rejection, risk-selected regression,
and durable provenance. Level 5 is not claimed because program-wide production
promotion and physical gates remain governed external events. Level 6 is not
claimed because self-improvement cannot self-promote and has not been proven
across a sustained independent program lifecycle.

## Final closure evidence

- Source SHA: `f8790a8cd9feda2bf9f63ad2f24ae9a289926efa`.
- Stable remote candidate ref: `candidate/aef-high-assurance-20260925` at the
  exact source SHA.
- Immutable source archive SHA-256:
  `9acfa789abda8f7fc23890a4289f1a45ed343d47c4457522d428d44c9a24fdc2`.
- Risk-selected domain regression: 215 passed, 0 failed, 0 skipped.
- Canonical regression: 422 passed, 0 failed, 0 skipped, 1 warning.
- Full regression: 796 passed, 0 failed, 0 skipped, 5 warnings.
- Strict package provenance verifier: `ACCEPT`, zero violations, three test
  receipts verified.
- Secret-pattern findings: zero. Dependency changes: zero.
- Production deployment: not performed.
