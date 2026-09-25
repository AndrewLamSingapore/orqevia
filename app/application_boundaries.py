"""Fail-closed portfolio application and evidence boundaries.

Application output is content, never identity, authority, or proof.  VELYQUA
physical claims additionally require an independently verifiable physical
receipt; simulated, replayed, and lab evidence remain useful but bounded.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Application(str, Enum):
    JARVIS = "JARVIS"
    VELYQUA = "VELYQUA"


class EvidenceClass(str, Enum):
    SIMULATED = "SIMULATED"
    REPLAYED = "REPLAYED"
    LAB = "LAB"
    PHYSICAL_UNVERIFIED = "PHYSICAL_UNVERIFIED"
    PHYSICAL_VERIFIED = "PHYSICAL_VERIFIED"


@dataclass(frozen=True)
class BoundaryDecision:
    disposition: str
    application: str
    evidence_class: str
    may_claim_physical: bool
    grants_authority: bool
    may_mutate_other_application: bool
    reasons: tuple[str, ...]


def evaluate_application_evidence(envelope: Any) -> BoundaryDecision:
    """Classify an application claim without executing or persisting it."""
    if not isinstance(envelope, dict):
        raise ValueError("application evidence envelope must be an object")
    allowed = {"application", "evidence_class", "claim", "provenance", "verification_ref"}
    if set(envelope) != allowed:
        raise ValueError("application evidence fields do not match the version 1 contract")
    try:
        application = Application(envelope["application"])
        evidence_class = EvidenceClass(envelope["evidence_class"])
    except (KeyError, ValueError) as error:
        raise ValueError("unknown application or evidence class") from error
    claim = envelope.get("claim")
    provenance = envelope.get("provenance")
    if not isinstance(claim, str) or not claim.strip():
        raise ValueError("claim must be a non-empty string")
    if not isinstance(provenance, list) or not provenance or not all(
        isinstance(item, str) and item.strip() for item in provenance
    ):
        raise ValueError("attributed provenance is required")
    verification_ref = envelope.get("verification_ref")
    physical = evidence_class is EvidenceClass.PHYSICAL_VERIFIED
    reasons: list[str] = []
    if physical and (not isinstance(verification_ref, str) or not verification_ref.strip()):
        physical = False
        reasons.append("physical_evidence_missing_independent_verification")
    if evidence_class is not EvidenceClass.PHYSICAL_VERIFIED:
        reasons.append("evidence_class_does_not_prove_physical_reality")
    disposition = "ACCEPTED_BOUNDED" if physical or evidence_class in {
        EvidenceClass.SIMULATED, EvidenceClass.REPLAYED, EvidenceClass.LAB,
        EvidenceClass.PHYSICAL_UNVERIFIED,
    } else "VERIFY_REQUIRED"
    return BoundaryDecision(
        disposition=disposition,
        application=application.value,
        evidence_class=evidence_class.value,
        may_claim_physical=physical,
        grants_authority=False,
        may_mutate_other_application=False,
        reasons=tuple(reasons),
    )


def require_application_scope(*, application: str, scope_id: str) -> None:
    """Reject cross-application memory/data writes before they reach storage."""
    try:
        expected = Application(application).value
    except ValueError as error:
        raise ValueError("unknown application") from error
    if scope_id != expected:
        raise PermissionError("cross-application scope mutation denied")
