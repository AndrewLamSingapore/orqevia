# JARVIS PRIME FAILSAFE v0 — Execution Freeze

Status: **IMPLEMENTED AS STANDALONE NEGATIVE-CONTROL PRIMITIVE; PEP INTEGRATION PENDING**

FAILSAFE is deterministic containment below cognitive reasoning. It has negative authority only: freeze, contain, constrain, and require validated recovery. It cannot grant TAP authority, issue Action Envelopes, approve cloud execution, or invoke external executors.

## State machine

`NOMINAL -> DEGRADED -> EXECUTION_FREEZE -> CONTAINED -> RECOVERY_PENDING -> VALIDATION -> NOMINAL`

Exceptional state: `HARD_LOCK`.

A failed validation returns to `CONTAINED`. Restoration to `NOMINAL` requires explicit owner-approval evidence. Loss or corruption of FAILSAFE state is fail-closed for consequential execution.

## Frozen invariants

1. No consequential action may begin while execution is frozen.
2. PRIME/agents cannot clear a freeze by ordinary cognitive instruction.
3. A TAP authorization issued before a freeze does not override the freeze.
4. Freeze/recovery transitions are durably recorded.
5. FAILSAFE does not depend on an LLM.
6. Cloud/network loss does not disable local containment.
7. Recovery does not silently restore expired/revoked authority.
8. Failed recovery validation returns to containment.
9. FAILSAFE cannot grant positive authority.
10. Unprovable FAILSAFE state means consequential execution is denied.

## Required integration gate

Before this subsystem may be called operationally installed, every supported consequential executor path must call `Failsafe.assert_consequential_execution_allowed()` immediately after TAP/Harness revalidation and immediately before the external side effect. The acceptance suite must prove that a lease authorized before a freeze cannot execute after the freeze.

## Acceptance evidence required

- unit suite green;
- Harness/TAP integration test green;
- pre-authorized-then-freeze test green;
- process restart persistence test green;
- ledger unavailable test green;
- Dell/ABEX runtime acceptance green;
- retained evidence tied to exact commit/image SHA.
