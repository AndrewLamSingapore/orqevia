# Agent Harness v0

Status: **source implementation under review; runtime activation is prohibited**.

This is the policy-enforcement boundary between the 29 lightweight specialist
identities and every executor. PRIME and specialist models may propose actions.
Stable Spine is the sole policy-decision point. The Trusted Authority Plane
attests that decision by issuing a signed, versioned, short-lived lease. The
Harness verifies and consumes that lease immediately before execution.

## Pilot

Only these registered agents are admitted in v0:

- `a14` Data Quality Agent
- `a16` Architecture Agent
- `a21` Cost Agent

The registry remains PRIME plus 29 specialists (`a01`–`a29`). Registration is
not runtime activity and does not imply 29 concurrent model processes.

## Enforced invariants

- HMAC-SHA256 covers the complete v2 Action Envelope.
- Signing material belongs only in the single Trusted Authority Plane.
- Nonces and leases are single-use and durably recorded.
- Authorization and lease TTL are capped at five minutes.
- Current policy version is rechecked immediately before execution.
- Operator revocation is effective before execution.
- Privileged execution requires an owner approval reference.
- Privileged ledger failure raises `HarnessUnavailable` and never calls an executor.
- Advisory ledger failure is closed by default; a future explicit policy tier may
  enable degraded advisory work.
- `HarnessedExecutor` is the supported executor adapter. Direct executor wiring
  is prohibited.
- Local inference concurrency starts at one. Any increase to two requires
  monitored acceptance evidence and an explicit operator configuration change.
- Cloud routing remains approval-gated and cost-capped.

## Acceptance gates

| Gate | Automated evidence | Runtime evidence required |
|---|---|---|
| Valid signed lease accepted | `test_three_pilot_agents_receive_signed_leases` | Pending |
| Unknown/forged rejected | `test_unknown_agent_and_forged_envelope_fail_closed` | Pending |
| Expired/replayed rejected | `test_expiry_nonce_replay_and_execution_replay_are_rejected` | Pending |
| Revocation effective | `test_revocation_and_policy_change_are_checked_at_execution_time` | Pending |
| Policy-change revalidation | same test | Pending |
| Owner approval for privilege | `test_privileged_actions_require_owner_approval` | Pending |
| Ledger outage fail-closed | `test_privileged_ledger_failure_halts_before_executor` | Pending |
| Executor side channel blocked | `test_executor_is_unreachable_when_lease_is_invalid` | Pending |
| Audit reconstruction | `test_audit_reconstruction_is_ordered_and_complete` | Pending |
| Queue priority/fairness | existing queue tests plus Harness v0 follow-up | Pending |
| Recovery under worker loss | existing lease-expiry queue test | Pending |

No agent migration, cloud overflow activation, production signing key, or ABEX
authority commissioning is authorized by merging this source change. Graduation
requires every runtime-evidence cell to pass reproducibly and receive human sign-off.
