"""Fail-closed portfolio application and evidence boundaries.

Application output is content, never identity, authority, or proof.  VELYQUA
physical claims additionally require an independently verifiable physical
receipt; simulated, replayed, and lab evidence remain useful but bounded.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import re
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
    if physical:
        required={"receipt_sha256","device_id","firmware_sha256","sensor_id","observed_at",
                  "transport_provenance","independent_verifier"}
        if not isinstance(verification_ref,dict) or set(verification_ref)!=required:
            physical=False;reasons.append("physical_evidence_receipt_invalid")
        else:
            for field in ("device_id","sensor_id","independent_verifier"):
                if not isinstance(verification_ref.get(field),str) or not verification_ref[field].strip():
                    physical=False;reasons.append(f"physical_{field}_missing")
            for field in ("receipt_sha256","firmware_sha256"):
                if not isinstance(verification_ref.get(field),str) or not re.fullmatch(r"[0-9a-f]{64}",verification_ref[field]):
                    physical=False;reasons.append(f"physical_{field}_invalid")
            transport=verification_ref.get("transport_provenance")
            if not isinstance(transport,list) or not transport or not all(isinstance(x,str) and x.strip() for x in transport):
                physical=False;reasons.append("physical_transport_provenance_missing")
            try:datetime.fromisoformat(str(verification_ref.get("observed_at")).replace("Z","+00:00"))
            except (TypeError,ValueError):physical=False;reasons.append("physical_observed_at_invalid")
            verifier=str(verification_ref.get("independent_verifier","")).lower()
            if any(label in verifier for label in ("model","inference","generated","self-attested")):
                physical=False;reasons.append("physical_verifier_not_independent")
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
