# SKILLS.md — ORQEVIA versioned agent-skills registry

Status authority for the skills system. This file is a human-readable index;
the machine-readable record is `skills/manifest.json`, and each skill carries
its own `skills/<skill-id>/SKILL.md` package.

Unless marked otherwise, every skill below is **DRAFT_CANDIDATE** and **not
qualified**. Instructions being present does not make a skill qualified.
Qualification requires a defined interface, passing tests, verified security
controls, demonstrated error handling, and preserved evidence (Gate A), plus
integration evidence (Gate B) before it may be considered operational.
`hyper-inference.fabric` is **QUALIFIED** by owner approval after CI, and its
activation remains `advisory_only`.

## Registry

| Skill id | Name | Version | Owner agents | Status |
| --- | --- | --- | --- | --- |
| reasoning.deductive | Deductive reasoning | 1.0.0 | a01, a02, a04 | DRAFT_CANDIDATE |
| reasoning.inductive | Inductive reasoning | 1.0.0 | a06, a07, a12, a13 | DRAFT_CANDIDATE |
| reasoning.abductive | Abductive reasoning | 1.0.0 | a02, a04, a19 | DRAFT_CANDIDATE |
| research.internet-gateway | Controlled internet research gateway | 1.0.0 | a06, a07, a09 | DRAFT_CANDIDATE |
| autonomy.bounded-proactive | Bounded proactive autonomy | 1.0.0 | a15, a16, a17, a19 | DRAFT_CANDIDATE |
| tools.discovery | Technical tool discovery and orchestration | 1.0.0 | a15, a16, a17 | DRAFT_CANDIDATE |
| matrix.multi-evidence | Multi-matrix evidence integration | 1.0.0 | a06, a07, a09, a10 | DRAFT_CANDIDATE |
| proxy.routing | Model and tool proxy routing | 1.0.0 | a15, a16 | DRAFT_CANDIDATE |
| academy.training | Intelligence Academy training-room interfaces | 1.0.0 | a26, a28 | DRAFT_CANDIDATE |
| uief.evaluation | Universal Intelligence Evaluation Framework | 1.0.0 | a18, a26, a28 | DRAFT_CANDIDATE |
| skills.governance | Skills registry governance and versioning | 1.0.0 | a26, a29 | DRAFT_CANDIDATE |
| orchestration.plan | Continuous skills-update orchestration | 1.0.0 | a01, a02, a15, a26 | DRAFT_CANDIDATE |
| hyper-inference.fabric | Hyper-Inference Fabric | 0.1.0 | a01, a02, a04, a15, a16, a18, a26 | QUALIFIED |

## Dependency graph

- reasoning.deductive → (none)
- reasoning.inductive → reasoning.deductive
- reasoning.abductive → reasoning.deductive, reasoning.inductive
- research.internet-gateway → (none)
- autonomy.bounded-proactive → research.internet-gateway
- tools.discovery → (none)
- matrix.multi-evidence → reasoning.inductive
- proxy.routing → tools.discovery
- academy.training → (none)
- uief.evaluation → academy.training
- skills.governance → (none)
- orchestration.plan → skills.governance, uief.evaluation
- hyper-inference.fabric → reasoning.deductive, reasoning.inductive, reasoning.abductive, matrix.multi-evidence, proxy.routing, uief.evaluation

## Hyper-Inference Fabric

`app/hyper_inference/` is the shared, advisory-only fabric for the reasoning
families and inference channels in Section 77. It exposes a versioned engine
registry (12 families), a channel registry (10 channels), mock model/tool proxy
registries, interoperable intelligence matrix structures, and the ten-step
adaptive inference router. The fabric never grants tools, spending, release or
execution authority, and it does not call external services. It is tested by
`tests/test_hyper_inference.py` and `tests/test_hyper_inference_integration.py`
(31 deterministic tests, passing), the 4-test fast 21-agent acceptance gate, and
the measured 15-dimension UIEF benchmark. It is `QUALIFIED` by owner approval
after the ORQEVIA v1 CI quality check passed for pull request #312; activation
remains `advisory_only`.

## Qualification workflow

1. Define the interface (inputs, outputs, error contract).
2. Implement the skill or instruction package.
3. Add deterministic tests including negative and security cases.
4. Run tests and preserve pass/fail receipts.
5. Record version, hash and owner agents in `skills/manifest.json`.
6. Gate A: interfaces defined, tests pass, security controls verified,
   error handling demonstrated, evidence recorded.
7. Gate B: dependencies work together, contracts compatible, failures
   contained, recovery demonstrated, no critical regression.
8. Only after Gates A and B may a skill move from DRAFT_CANDIDATE to QUALIFIED.

## Activation controls

- All skills are `advisory_only`: they never grant tools, spending, release,
  or execution authority by themselves.
- Activation requires a separate owner-approved change, and consequential
  actions still require the independent approval path in `app/routing_policy.py`
  and `app/host_guard.py`.

## Versioning and rollback

- `skills/manifest.json` is the versioned record; `schema_version` changes only
  with a breaking format change.
- Rollback references the prior manifest version and the prior `SKILL.md`; the
  record is additive and historical entries are preserved, never overwritten.
