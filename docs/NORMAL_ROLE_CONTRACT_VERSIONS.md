# Normal-role contract versions

Historical `challenge()` and `role_case()` bytes remain unchanged. Existing
cloud policies, signed admissions and their original hash pins continue to bind
those exact cases, including `a19-role-normal-operation-id.v2`.

Use `app.agent_cert_structured_roles.structured_role_case(agent_id)` to prepare
the explicitly versioned `prime.normal-role-structured.v1` local task. It adds
an answer-free shape schema and clarification, while retaining the supplied
facts, independent semantic oracle, LOCAL_ONLY scope and zero spending limit.
It is a new task contract and requires a fresh actual execution receipt.

The legacy cloud transport rejects the changed structured case. No historical
policy, signed receipt or completed execution may be rebound to it. Future
protected transport support requires a separately reviewed version-aware
binding. Source tests and schema-valid output do not prove role competence,
physical-device acceptance, L7 or production readiness.
