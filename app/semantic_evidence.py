"""Exact-match semantic evidence verification for consequential model claims."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


CONSEQUENTIAL_KINDS = frozenset({"citation", "git_sha", "database_record", "tool_result", "authorization", "execution_receipt", "test_result", "retrieved_evidence"})


@dataclass(frozen=True)
class SemanticEvidenceResult:
    disposition: str
    violations: tuple[str, ...]
    verified_claims: int
    trusted_evidence: bool
    may_persist_as_fact: bool
    grants_authority: bool
    may_trigger_tool: bool


def verify_evidence_claims(claims: list[dict[str, Any]], authoritative: dict[tuple[str, str], Any]) -> SemanticEvidenceResult:
    violations: list[str] = []
    verified = 0
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            violations.append(f"claim[{index}]:malformed")
            continue
        kind, reference = claim.get("kind"), claim.get("reference")
        if kind not in CONSEQUENTIAL_KINDS or not isinstance(reference, str) or not reference:
            violations.append(f"claim[{index}]:unsupported_identity")
            continue
        key = (kind, reference)
        if key not in authoritative:
            violations.append(f"claim[{index}]:unverified_reference")
            continue
        if claim.get("value") != authoritative[key]:
            violations.append(f"claim[{index}]:evidence_mismatch")
            continue
        verified += 1
    accepted = bool(claims) and not violations and verified == len(claims)
    return SemanticEvidenceResult(
        "ACCEPTED" if accepted else "VERIFY_REQUIRED",
        tuple(violations), verified,
        trusted_evidence=accepted,
        may_persist_as_fact=accepted,
        grants_authority=False,
        may_trigger_tool=False,
    )
