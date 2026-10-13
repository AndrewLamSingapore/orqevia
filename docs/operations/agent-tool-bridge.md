# Recorded agent tool fulfillment

`app/agent_tool_bridge_api.py` provides owner-authenticated routes under
`/api/agent-tool-bridge`. Mount its router through the existing direct application
and include that prefix in the existing authenticated body-limit middleware.
The bridge consumes the original completed compute-queue output; HTTP callers
cannot replace that output or choose its actor, model, provider or credentials.

An Owner creates `/sessions` with the completed `job_id`, authorized `objective`,
explicit `services`, `workspace_operations` and registry-valid
`delegation_targets`. The maximum is four requests, two delegated child jobs,
and one subsequent feedback job. Unsupported or unauthorized operations remain
denied by the existing broker/workspace boundaries. Public reads additionally
require the original task's `CLOUD_PERMITTED` classification. Workspace list
requests require an explicit integer `limit` between one and four.

The model output contract is an exact JSON object:

```json
{"schema":"orqevia.agent-tool-requests.v1","requests":[{"id":"source","kind":"service","service":"private.task.metadata.read","parameters":{}}]}
```

Workspace requests replace `service` with `operation`. Delegated requests contain
only `id`, `kind: "delegate"`, `target` and a bounded `objective`. Text grants no
additional authority. Every child uses the configured local fast provider,
`LOCAL_ONLY`, zero cloud budget and no retry; queue admission and capacity remain
in force. No paid provider is selected by this bridge.

`POST /sessions/{job_id}/execute` reserves each step durably before its effect.
Completed replay returns its retained receipt. An interrupted or overlapping
`IN_PROGRESS` step returns a conflict and requires independent reconciliation.
Queue submission and bridge storage are separate transactions; a crash across
them is explicitly ambiguous, never replayed automatically. Source, queue
attempt/provider evidence and the observed bridge runtime retain separate scope;
missing original runtime pins remain unknown.

`POST /observe` joins actual delegated queue results. `POST /feedback` queues one
local continuation bound to the retained result hashes. Full receipts remain
available through owner-only `GET /sessions/{job_id}/receipts/{step_id}`.
Oversized receipts use explicitly labelled partial excerpts in the model input,
with complete original byte counts, hashes and references; they are never
represented as complete model evidence. Observing a completed continuation
records its actual input/output and provider, but does not prove semantic
consumption, correctness or acceptance.

`POST /stop` durably prevents further dispatch and cancels known child jobs,
including provisional bindings whose audit is still settling. In-flight tool
completion remains observable; STOP does not invent a rollback of an action
that already happened. Original jobs, outputs, failed actions and receipts are
retained. Local source/fixture checks, installed behavior, full role acceptance
and independent Azure assessment remain separate.
