# Actual architecture and preserved roles

Sources pinned at f37673b4. Current deployment observed separately; source
checkout and the October27 handover are not proof of production identity.

- app/pif/core.py: deterministic Markov, stationary/absorbing, hidden-state and
  Monte Carlo. history.py's queue model has8states. service.py loads tenant
  registry models and writes prediction receipts via store.py SQLite. Forecasts
  remain advisory/shadow; no execution authority.
- app/mel/service.py and inventory.py: tenant experiment registry, evidence and
  advisory efficiency recommendations. Independent control from PIF. ONNX
  preparation/inference uses mature native libraries; no new weight/quantization
  artifacts were prepared, selected or promoted during this mission.
- app/onnx_embedding.py: native ONNX/tokenizer/NumPy wrapper; pooling/normalization
  already included in the model graph. No evidence to rewrite those kernels.
- app/job_queue.py and agent_registry.py: Python control plane/shared durable
  SQLite journal and21logical identities. No21local inference processes created.
- app/interface_telemetry.py: read-only CTE metadata ranking; currently live
  function returns21roles from6965records. Existing idx_compute_agent/claim
  indexes; no live schema or historical-record changes.
- HTTPS gateway/interface, backend, coaching, intelligence, Ollama and telemetry
  remain separate existing service containers. GitHub standard hosted runners
  perform CI remotely; no local self-hosted runner was found. Database and model
  volumes/bind mounts remain unchanged. No release or production configuration
  change is part of this branch.

The table is registry identity/contract evidence, not agent competence or
permission to resume background work. Existing compute requirements, input/output
contracts, fallback, TAP relationship and model eligibility remain in the exact
unchanged config/agent_registry.json. Actual producer/queue/resource dependencies
and task memory matrix are also documented by the separate Guardian candidate.

| Identity | Registered role/name | Reports to | Execution dependencies |
|---|---|---|---|
| a01 | Strategy Lead | prime | Existing shared Python dispatch + durable compute journal; model task-qualified at runtime |
| a02 | Planning and Roadmap Agent | lead_strategy | Existing shared Python dispatch + durable compute journal; model task-qualified at runtime |
| a04 | Decision and Comparison Agent | lead_strategy | Existing shared Python dispatch + durable compute journal; model task-qualified at runtime |
| a05 | Portfolio and Capacity Agent | lead_strategy | Existing shared Python dispatch + durable compute journal; model task-qualified at runtime |
| a06 | Research Lead | prime | Existing shared Python dispatch + durable compute journal; model task-qualified at runtime |
| a07 | Evidence Agent | lead_research | Existing shared Python dispatch + durable compute journal; model task-qualified at runtime |
| a09 | Knowledge Agent | lead_research | Existing shared Python dispatch + durable compute journal; model task-qualified at runtime |
| a10 | Data Lead | prime | Existing shared Python dispatch + durable compute journal; model task-qualified at runtime |
| a12 | Metrics and Analysis Agent | lead_data | Existing shared Python dispatch + durable compute journal; model task-qualified at runtime |
| a13 | Forecast Agent | lead_data | Existing shared Python dispatch + durable compute journal; model task-qualified at runtime |
| a14 | Data Quality Agent | lead_data | Existing shared Python dispatch + durable compute journal; model task-qualified at runtime |
| a15 | Engineering Lead | prime | Existing shared Python dispatch + durable compute journal; model task-qualified at runtime |
| a16 | Architecture Agent | lead_engineering | Existing shared Python dispatch + durable compute journal; model task-qualified at runtime |
| a17 | Implementation Agent | lead_engineering | Existing shared Python dispatch + durable compute journal; model task-qualified at runtime |
| a18 | Test and Verification Agent | lead_engineering | Existing shared Python dispatch + durable compute journal; model task-qualified at runtime |
| a19 | Reliability Agent | lead_engineering | Existing shared Python dispatch + durable compute journal; model task-qualified at runtime |
| a20 | Commercial and Economic Lead | prime | Existing shared Python dispatch + durable compute journal; model task-qualified at runtime |
| a21 | Cost and Value Agent | lead_economic | Existing shared Python dispatch + durable compute journal; model task-qualified at runtime |
| a26 | Independent Quality Lead | prime | Existing shared Python dispatch + durable compute journal; model task-qualified at runtime |
| a28 | Risk Agent | lead_quality | Existing shared Python dispatch + durable compute journal; model task-qualified at runtime |
| a29 | Release Agent | lead_quality | Existing shared Python dispatch + durable compute journal; model task-qualified at runtime |
