"""Fail-closed integration contracts across router, model, memory and tools.

This module is deliberately transport-neutral.  It proves that identity and
authority are carried by a trusted request envelope, never inferred from model
or retrieved content, and that ambiguous downstream failures cannot become a
successful or consequential operation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app.capability_router import CapabilityBackend, select_capability_route
from app.structured_output import StructuredResult, evaluate_structured_output


ROLES = frozenset({"OWNER", "MEMBER", "APPLICATION", "SYSTEM"})
FAILURE_DISPOSITIONS = {
    "schema_mismatch": "VERIFY_REQUIRED",
    "version_mismatch": "FAIL_CLOSED",
    "malformed_output": "VERIFY_REQUIRED",
    "timeout": "DEFERRED",
    "duplicate_request": "IDEMPOTENT_REPLAY",
    "stale_request": "DENIED",
    "provider_unavailable": "DEFERRED",
    "model_unavailable": "DEFERRED",
    "retrieval_unavailable": "DEFERRED",
    "database_unavailable": "FAIL_CLOSED",
    "tool_unavailable": "DEFERRED",
    "network_unavailable": "DEFERRED",
    "expired_session": "DENIED",
    "unauthorized_operation": "DENIED",
}


@dataclass(frozen=True)
class IntegrationEnvelope:
    trace_id: str
    request_id: str
    actor_id: str
    role: str
    scope: str
    schema_version: str
    created_at: float
    expires_at: float
    idempotency_key: str
    permissions: frozenset[str] = field(default_factory=frozenset)

    def validate(self, *, now: float | None = None, expected_version: str = "1.0") -> None:
        current = time.time() if now is None else now
        if not all((self.trace_id, self.request_id, self.actor_id, self.scope, self.idempotency_key)):
            raise ValueError("identity, trace, scope and idempotency fields are required")
        if self.role not in ROLES:
            raise PermissionError("unknown role")
        if self.schema_version != expected_version:
            raise ValueError("version_mismatch")
        if self.created_at > current + 30 or self.expires_at <= current:
            raise PermissionError("stale_or_expired_request")


@dataclass(frozen=True)
class IntegrationResult:
    disposition: str
    trace_id: str
    request_id: str
    route_model: str | None = None
    value: Any | None = None
    evidence: tuple[str, ...] = ()
    tool_executed: bool = False
    authority_changed: bool = False


class IdempotencyLedger:
    def __init__(self) -> None:
        self._results: dict[str, IntegrationResult] = {}

    def get(self, key: str) -> IntegrationResult | None:
        return self._results.get(key)

    def put(self, key: str, result: IntegrationResult) -> None:
        self._results.setdefault(key, result)


def failure_disposition(kind: str) -> str:
    try:
        return FAILURE_DISPOSITIONS[kind]
    except KeyError as error:
        raise ValueError("unknown failure must not be guessed") from error


def run_model_hop(
    envelope: IntegrationEnvelope,
    *,
    backends: tuple[CapabilityBackend, ...],
    capability: str,
    classification: str,
    raw_model_output: str,
    schema: dict[str, Any],
    semantic_verify: Callable[[Any], list[str]] | None = None,
    ledger: IdempotencyLedger | None = None,
    now: float | None = None,
) -> IntegrationResult:
    try:
        envelope.validate(now=now)
    except PermissionError as error:
        return IntegrationResult("DENIED", envelope.trace_id, envelope.request_id, evidence=(str(error),))
    except ValueError as error:
        return IntegrationResult("FAIL_CLOSED", envelope.trace_id, envelope.request_id, evidence=(str(error),))
    if ledger:
        prior = ledger.get(envelope.idempotency_key)
        if prior:
            return prior
    route = select_capability_route(backends, capability=capability, classification=classification)
    if route.state not in {"READY", "VERIFY_REQUIRED"}:
        return IntegrationResult(route.state, envelope.trace_id, envelope.request_id, evidence=(route.reason,))
    structured: StructuredResult = evaluate_structured_output(
        raw_model_output, schema, semantic_verify=semantic_verify, max_repair_attempts=0
    )
    result = IntegrationResult(
        "ACCEPTED" if structured.accepted else "VERIFY_REQUIRED",
        envelope.trace_id,
        envelope.request_id,
        route.backend.model if route.backend else None,
        structured.value,
        structured.violations,
        tool_executed=False,
        authority_changed=False,
    )
    if ledger:
        ledger.put(envelope.idempotency_key, result)
    return result


def authorize_tool(envelope: IntegrationEnvelope, *, permission: str, model_claimed_role: str | None = None) -> bool:
    """Authorize only from the trusted envelope; model claims are inert data."""
    envelope.validate()
    del model_claimed_role
    return permission in envelope.permissions


def retrieved_content_can_grant_authority(content: Any) -> bool:
    del content
    return False

