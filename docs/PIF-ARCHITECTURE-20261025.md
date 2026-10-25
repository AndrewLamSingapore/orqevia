# Optional Probabilistic Intelligence Fabric

Discovery baseline: canonical `AndrewLamSingapore/orqevia` main
`4d415d8528c48e9f795e5758d33f244d782cb53f`, inspected 25 October 2026.
This inventory preceded PIF implementation. It establishes source architecture,
not production deployment or forecasting accuracy.

| Component | Classification | Verified source and implication |
| --- | --- | --- |
| Shared inference scheduler | EXISTING AND VERIFIED | `app/job_queue.py` owns SQLite `compute_jobs` and append-only `compute_events`; reuse read-only observations, never schedule or authorize from forecasts. |
| State history | EXISTING BUT INCOMPLETE | Events carry state changes through submitted, cloud_reserved, claimed, completion, retries, expiry and cancellation. Metadata events are not transitions. Current job rows cannot substitute for missing events. Fixture/acceptance jobs are not reliably labelled as production; observational fits must remain shadow-only. |
| Job state definitions | EXISTING AND VERIFIED | Current `TERMINAL` is completed, failed, cancelled, budget_blocked. Ordinary submission is queued; cloud reservation is held. Legacy awaiting_approval is distinct. `registry_denied` results in failed; it is not a state named denied. |
| Objective lifecycle | EXISTING BUT INCOMPLETE | `app/objective_api.py` stores objectives and revision snapshots, without an append-only timestamped objective-state history. Job completion is not objective completion. Objective forecasts are unavailable until suitable histories exist. |
| Existing forecasting | EXISTING BUT INCOMPLETE | `app/predictive_intelligence.py` implements chronological last-value/MAE; hyper-inference's probabilistic engine is a deterministic score. Neither supplies learned Markov transition forecasts. Preserve both interfaces. |
| Generic probabilistic models | MISSING | No Markov/HMM model, calibrated queue-state forecasting, or simulation-provenance registry was found in `app` and tests. |
| Model registry | EXISTING AND VERIFIED | `app/model_registry.py` stores versioned neural/LLM registrations, evaluations, assignments, events and rollback in model-registry.db. Its required positive context/output-token contract does not describe Markov models. PIF adds namespaced tables to this same database, without fabricated LLM fields or modifying existing tables. |
| API and authorization | EXISTING AND VERIFIED | FastAPI routers are registered by `direct_entry.py`; authenticated collective principal/HTTPS bridge already exists. Parent integration owns route wiring. PIF supplies a service, never an alternative authority. |
| Persistence and deployment | EXISTING AND VERIFIED | Existing ORQEVIA data directory, SQLite, packaged Python application and deployment are reused. No service, cloud subscription, broker, GPU, dependency installation or migration of core tables is required. |
| Hidden-state production evidence | NOT VERIFIED | No labelled emission histories or accepted hidden-state validation were found. A tested scaled forward filter can be used offline; production hidden inference returns unavailable. |
| Causal/action/reward evidence | NOT VERIFIED | Queue events do not identify causal interventions or reward functions. No production intervention/MDP estimate is supported. |
| Runtime forecast quality | NOT VERIFIED | Source inspection and mathematical fixtures cannot establish prospective predictive accuracy, representative sampling, stationarity, calibration or production deployment. |

## Interfaces and independence

`app.pif` is an optional pure-standard-library package. Importing it opens no
database, starts no thread and performs no network calls. `PIFService` checks
`ORQEVIA_PIF_ENABLED` (default `0`) independently of MEL or external simulation
providers. Disabled calls return `DISABLED`; storage faults return `UNAVAILABLE`.
Core queue/agent execution does not import or depend on PIF.

The eight service operations are `predict_transition`, `forecast_state`,
`estimate_failure_risk`, `infer_hidden_state`, `simulate_scenario`,
`evaluate_intervention`, `get_prediction_evidence`, and `get_model_metadata`.
Each JSON-safe response includes a trace ID, timestamp, model version/digest,
observation period, evidence digest, horizon unit, reliability/assumptions and
`grants_execution_authority=false`. Queue horizons are **observed state-change
events**, never seconds or an implied completion deadline. Separate elapsed-time
or semi-Markov models are appropriate where dwell time determines outcomes.

Training uses explicitly supplied timestamped, entity-separated histories.
Chronological evaluation uses a cutoff: training observations must precede it;
test entities must begin at or after it. Histories crossing it are excluded,
preventing future leakage and the same entity appearing in both partitions.
Reports compare Brier score/log loss, empirical-frequency and persistence
baselines, calibration bins, and first/second-half outcome shift. These are
descriptive diagnostics, not automatic promotion. Fit artifacts record fixture,
simulation, observational-unclassified, or observed-production provenance.
Only the latter could be eligible for future independently validated promotion;
this release has no automatic promotion or execution-authorization operation.

Transition matrices use additive smoothing only over permitted edges. Terminal
states remain exact absorbing rows; smoothing never invents recovery from a
terminal state. Missing/unobserved rows remain unsupported for prediction even
if a normalized prior exists. Multi-step forecasts, seeded Monte Carlo and
scenario comparisons report their first-order, time-homogeneous assumptions.
Scenario comparison is predictive conditioning, not causal intervention.

Models/evidence use canonical JSON and SHA-256, not pickle or executable model
artifacts. Store lookup is tenant-scoped. Retained version references allow
independent rollback; setting PIF's flag to zero immediately disables service
calls while existing artifacts and core execution remain intact.

Mathematical reference: [Cambridge Markov chain course notes](https://www.statslab.cam.ac.uk/~rrw1/markov/M.pdf),
chapters 1-3 and 7-9. Validation diagnostics follow the distinctions in the
[scikit-learn calibration documentation](https://scikit-learn.org/stable/modules/calibration.html):
Brier/log loss assess more than calibration alone, so the release reports bins
and scores separately. These references do not establish ORQEVIA model quality.
