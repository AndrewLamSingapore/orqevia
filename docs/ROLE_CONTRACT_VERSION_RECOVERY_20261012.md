# Explicit normal-role task version and input fidelity repair

Baseline: `18ec93990eeccdbde60b85b32f5f5e0f0cb7849d` has a closed
source-specific local model cohort of 7 PASS and 14 FAIL. It silently appended
clarifications and schemas to the historical `role:normal` contract. That changed
A19's canonical digest while leaving its legacy v2 version and policy pins in
place. Historical acceptance/admission checks then rejected the changed bytes.

This candidate restores `agent_cert_cases.py` and `agent_cert_role_group_two.py`
from `bb99929c9e3fddd6d88a97662297dac94546978a` exactly. A19's historical digest
is again `d4ecfa3e97d0ec7b842dffac2b64fd431c40b45f98c9951d18b09ee3a724e929`.
Historical assertions, admission records, registry and semantic oracles stay
unchanged.

New executions must explicitly select `role:normal_structured`, version
`normal-role-structured-input.v1`. This task derives from the same registered
primary responsibility and semantic oracle. It carries the original source
context verbatim plus reviewed typed raw facts, and the answer-free schema and
clarification. It grants no cloud authority, new role, execution permission,
spending consent or certification. The historical cloud transport rejects it.

Response schemas previously alphabetized generation fields. That erased the
declared order, placing comparison/output fields before their inputs in several
roles. Validated wire schemas retain `required` array order through API, queue
storage and payload construction. Required's order reconstructs property order
even when stored JSON sorts object keys. Canonical semantic schema serialization
continues to ignore order, while actual payload receipts bind the ordered array.
The same bounds and strict type/shape checks apply. Field order can help causal
generation, but cannot guarantee mathematical or role competence.

Actual baseline failures include incorrect arithmetic/comparisons, source row
indices, boundary booleans, objective identifier placement, latest-sample
selection, and stale/current uncertainty. These remain failed historical
receipts. Typed source inputs and declared field order are a repair hypothesis;
only a fresh complete model cohort can establish effectiveness. No correct
answers are supplied to the runtime by this repair.

Run local canonical quality in new fixture data, using the existing environment:

```powershell
$env:ORQEVIA_DATA_DIR = '<fresh isolated fixture directory>'
$env:ORQEVIA_COMPUTE_QUEUE_DB = "$env:ORQEVIA_DATA_DIR/queue.db"
python -B scripts/run_canonical_ci.py
```

The tests added here cover the original pin, all 21 explicit mappings,
source-context binding, unchanged semantic rejection, ordered payload persistence
and mutation denial, and registered native peer reconstruction. Those fixture
passes are source regression evidence, never actual agent competence.

Fresh execution must run on one clean pinned candidate, with actual local model
jobs, original task/job/result bytes, immutable request receipts and independent
queue/objective/peer custody joins. Preserve the previous 7/14 and all original
3/18 evidence. Candidate promotion, 21/21 acceptance, L7 and production readiness
remain unverified and blocked until their separate required evidence exists.
