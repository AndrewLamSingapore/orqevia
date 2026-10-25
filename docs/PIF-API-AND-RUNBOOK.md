# PIF API, verification and rollback

Implementation is an additive optional package, not a new mandatory service.
Source discovery is in [PIF-ARCHITECTURE-20261025.md](PIF-ARCHITECTURE-20261025.md).
The package starts no worker, performs no network call and introduces no dependency.
The parent integration owns FastAPI/HTTPS bridge and established owner/tenant
authentication. Do not expose registry paths, tenant authority or event text as
caller-controlled gateway fields. Existing inference providers remain independent.

## Typed service contract

```python
from app.pif import History, Observation, PIFService
from app.pif.history import (
    QUEUE_STATES, QUEUE_ABSORBING, QUEUE_EDGES, read_compute_history,
)

service = PIFService(
    registry_path=None,       # existing ORQEVIA_MODEL_REGISTRY_DB / model-registry.db
    enabled=None,             # ORQEVIA_PIF_ENABLED == "1"; default disabled
    tenant_id="owner",       # supply from the existing authenticated principal
    min_transitions=30,       # statistical evidence sufficiency, not a queue limit
    min_source_transitions=5,
)
histories, diagnostics = read_compute_history(
    "/data/compute-queue.db", agent=None, since=None, until=None,
)
fit = service.fit_history(
    histories, states=QUEUE_STATES, absorbing_states=QUEUE_ABSORBING,
    allowed_edges=QUEUE_EDGES, alpha=0.5, source_revision="<40-character Git SHA>",
    model_id="queue-state", validation_cutoff=None,
    evidence_source="COMPUTE_EVENT_LEDGER_READ_ONLY",
)
transition = service.predict_transition("queued")
forecast = service.forecast_state("queued", steps=2)
risk = service.estimate_failure_risk("running", steps=2, failure_states=("failed",))
scenario = service.simulate_scenario("running", steps=2, samples=100, seed=42)
comparison = service.compare_scenarios({"new_job": "queued", "in_progress": "running"}, steps=2)
metadata = service.get_model_metadata(model_id="queue-state", version=None)
evidence = service.get_prediction_evidence(forecast["trace_id"])
```

Methods accept an initial state name or a mapping of known state names to
nonnegative probabilities summing to one. A horizon is a nonnegative integer
count of observed state-change events. `predict_transition` fixes it at one.
`estimate_failure_risk` requires absorbing failure states so occupancy equals
cumulative failure by the event horizon. A cancelled/budget-blocked outcome is
not silently called failure. Completion probabilities similarly appear in the
full forecast distribution; no seconds/deadline estimates are inferred.

Results use `orqevia.pif.result.v1`. They carry status, operation, reason, trace
ID, generated time, model ID/version, model provenance and evidence digest,
observation period, horizon/unit, reliability, assumptions, data and
`grants_execution_authority=false`. Probabilities are in `data.probabilities`.
Models are canonical-JSON, SHA-256-addressed artifacts. Forecasts and their
digest-checked evidence are persisted in tenant-scoped PIF tables in the
existing model-registry database. Existing LLM registry rows are unchanged.

| Status | Meaning |
| --- | --- |
| DISABLED | Independent PIF flag is off; no database initialization or core dependency. |
| INSUFFICIENT_DATA | No selected model, too few observations, or a reachable state lacks evidence. No invented probability result. |
| SHADOW | Mathematical conditional distribution/simulation is available from observed or explicitly labelled fixture data; production quality is unvalidated. |
| AVAILABLE | Requested artifact, metadata or prediction evidence was read. |
| UNAVAILABLE | Storage/integrity failure or unsupported hidden/causal inference. Core execution permissions remain unchanged. |

`infer_hidden_state(...)` explicitly returns unavailable until sufficient
emission-model evidence and independent validation exist. The pure offline
`app.pif.core.hidden_filter` supports scaled likelihoods/filtering and carries
no production validation. `evaluate_intervention(...)` returns unavailable
without action/reward/causal evidence. Scenario conditioning and comparing
separate scenario outputs do not establish causal intervention effects.
`compare_scenarios` pins one model version and returns each evidence-bearing
forecast plus probability differences from the first named initial condition.

Queue extraction reads no prompts/results and writes no queue rows. It maps
actual observed event semantics, preserves event insertion order for timestamp
ties, rejects missing initials, impossible transitions, unrecognized event
semantics, duplicate events and state mismatches. Retrying and lease recovery
are real running-to-queued transitions. Time windows select jobs created in the
window, preventing partial left-truncated histories from being invented.
Future outcomes are excluded. Aggregate exclusions are evidence, not successes.

## Validation and model quality

`tests/test_pif.py` covers exact matrices, probability conservation, multi-step
forecasts, sparse/absent observations, absorbing/periodic/reducible chains,
hand-calculated HMM filtering, likelihood underflow avoidance, deterministic
simulation, chronological entity disjointness, future-outcome nonleakage,
typed contracts, storage corruption, tenant isolation and independent rollback.
These fixtures are synthetic and are not production predictive evidence.

Fit reports include held-out multiclass Brier (sum over classes, range 0..2),
clipped log loss, global-frequency and persistence baselines, pooled class
calibration bins/error, train/test and chronological-half outcome-distribution
variation. Training histories end before cutoff; test histories start at/after
it; crossing entities are excluded. Both partitions must meet explicit evidence
minimums. The validation training artifact is separate from the final fit on
all supplied observations; the report records its digest, dates and split counts.
The package never declares a deployment-quality PASS from diagnostic scores.
Queue histories lack trusted workload-origin labels, so real runtime extraction
remains `observational_unclassified`; acceptance/coaching/fixture tasks must not
be promoted into representative production evidence by their appearance.

Run a local shadow report against an authorized actual ledger or its consistent
backup, with an explicit registry and a new output path:

```powershell
python -B scripts/pif_shadow_report.py --queue <compute-queue.db> `
  --registry <model-registry.db> --output <new-report.json> `
  --source-revision <exact-source-sha>
```

This invokes no inference provider and consumes no paid API tokens. Preserve
the original ledger/failed reports. The report discloses counts, digests and
diagnostics, not prompts/results. Production acceptance additionally requires
actual HTTPS adapter execution, authenticated scope/denial, current source/image
identity, persisted evidence readback and unaffected core operation with PIF
disabled, enabled, failing and independent from MEL.

## Monitoring and independent rollback

Monitor `service.health()` separately from MEL/core health: it reports disabled,
available shadow, or degraded storage. Monitor result status/reason, measured
gateway latency, evidence-window age, observed/excluded histories, insufficient
source states and calibration/drift diagnostics. An available service does not
mean a calibrated model. No new telemetry dependency is required.

To disable: set `ORQEVIA_PIF_ENABLED=0` in the existing deployment and recreate
the normal application services. No queue guard or deployment hold is used.
Preserve existing data, TLS, profiles and sessions. To select an earlier retained
shadow model, call `service.select_model_version("queue-state", "<version>")`.
The target must already exist in the same tenant; selection appends an audit
event and retains both models. No scheduler/model-provider route is modified.
Source rollback uses the existing immutable image procedure; additive PIF
tables can remain. Do not restore/delete the whole shared model registry to
roll back PIF, because that could destroy unrelated model history.

Current production forecasting quality, hidden-state inference, wall-time
completion/delay prediction, objective-state prediction and causal/MDP
estimation are **NOT VERIFIED / unavailable**, scoped to their missing evidence.
Do not describe engineering tests or successful shadow execution as those
milestones passing.
