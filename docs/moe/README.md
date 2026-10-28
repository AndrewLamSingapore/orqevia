# Selective-expert MoE assessment - 28 October 2026

Status: **UNDER IMPLEMENTATION - SOURCE CANDIDATE, NOT DEPLOYED**.

Owner: ABEX-ORQEVIA. Source baseline: `f37673b4ce618cc7cd672c987594f849d9985f02`.
The deployed product and resource names are ORQEVIA; ORZEVIA in the request
refers to the assessment target, not an instruction to rename resources.

The recommended direction is selective activation of the existing specialist
identities, deterministic work before generation, coordinated shared inference,
and optional measured cloud escalation. This is application routing, not neural
network MoE. Production already chooses one default specialist; do not claim
savings from replacing a nonexistent 21-agent default fan-out.

The first implementation extends the existing SQLite queue and WorkerPool with
an opt-in `home_eco` scheduling mode, explicit slot ownership, lifecycle timing,
bounded waiting count, priority aging, retry backoff, and patient coaching budgets.
The runtime compliance observer separately identifies actual deployed behavior.
No Docker restart, model installation, driver change, cloud call, or deployment
is included in this source milestone. Native MoE, cross-mission single-flight,
validated result caching, ULTRA_ECO defaults and model-quality acceptance remain
open implementation/experiment items. They must not be represented as delivered.

1. [Current-state architecture](01-CURRENT-STATE.md)
2. [MoE feasibility](02-MOE-FEASIBILITY.md)
3. [Proposed architecture](03-PROPOSED-ARCHITECTURE.md)
4. [Cost matrix](04-COST-MATRIX.md)
5. [Implementation and rollback](05-IMPLEMENTATION-ROADMAP.md)
6. [Proof of concept](06-PROOF-OF-CONCEPT.md)

Evidence levels are VERIFIED OBSERVATION, SOURCE IMPLEMENTED, ISOLATED TEST,
ESTIMATE, and NOT VERIFIED. An isolated executor test is not a real-model quality
test. Implementation status is not production acceptance.
