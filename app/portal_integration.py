"""Cross-project Portal -> PRIME experiment ingestion.

Pure, deterministic contract validation and specialist routing live here so the
integration can be tested without starting Ollama or PRIME's full runtime.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from .orchestration import choose_specialist

CANDIDATE_STATUSES = {"proposed", "accepted", "rejected", "superseded"}
SPEC_STATES = {"draft", "verified", "approved", "rejected", "completed"}


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def validate_experiment_candidate(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("candidate must be an object")
    allowed = {"schema_version", "candidate_id", "source", "title", "question", "hypothesis", "node_ids", "concepts", "provenance", "evidence_boundary", "status", "created_at"}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unknown candidate fields: {', '.join(sorted(unknown))}")
    if payload.get("schema_version") != "1.0":
        raise ValueError("schema_version must be 1.0")
    candidate_id = _nonempty(payload.get("candidate_id"), "candidate_id")
    if not re.fullmatch(r"PTL-EXP-[A-Z0-9-]+", candidate_id):
        raise ValueError("candidate_id must match PTL-EXP-[A-Z0-9-]+")
    if payload.get("source") != "the-portal":
        raise ValueError("source must be the-portal")
    status = payload.get("status")
    if status not in CANDIDATE_STATUSES:
        raise ValueError("invalid candidate status")
    result = dict(payload)
    result["title"] = _nonempty(payload.get("title"), "title")
    result["question"] = _nonempty(payload.get("question"), "question")
    result["evidence_boundary"] = _nonempty(payload.get("evidence_boundary"), "evidence_boundary")
    for field in ("node_ids", "concepts", "provenance"):
        value = payload.get(field, [])
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise ValueError(f"{field} must be an array of strings")
        result[field] = list(dict.fromkeys(x.strip() for x in value if x.strip()))
    hypothesis = payload.get("hypothesis")
    if hypothesis is not None and not isinstance(hypothesis, str):
        raise ValueError("hypothesis must be a string or null")
    return result


def route_candidate(candidate: dict[str, Any]) -> dict[str, str]:
    text = " ".join([candidate["title"], candidate["question"], candidate.get("hypothesis") or "", " ".join(candidate.get("concepts", []))])
    decision = choose_specialist("research", candidate["title"], text)
    return {"specialist": decision.specialist, "reason": decision.reason}


def build_experiment_spec(candidate: dict[str, Any]) -> dict[str, Any]:
    """Create a bounded draft spec from a validated candidate.

    PRIME does not manufacture empirical evidence here. A spec is marked
    verified only when provenance exists; otherwise it remains draft and asks
    for evidence explicitly.
    """
    candidate = validate_experiment_candidate(candidate)
    route = route_candidate(candidate)
    digest = hashlib.sha256(candidate["candidate_id"].encode()).hexdigest()[:12].upper()
    provenance = candidate.get("provenance", [])
    has_evidence = bool(provenance)
    hypothesis = (candidate.get("hypothesis") or candidate["question"]).strip()
    requirements = [
        f"Preserve Portal evidence boundary: {candidate['evidence_boundary']}",
        "Collect observations that can falsify as well as support the hypothesis.",
        "Identify every empirical input by source before drawing a quantitative conclusion.",
    ]
    if not has_evidence:
        requirements.insert(0, "EVIDENCE_REQUIRED: attach source-supported provenance before treating the hypothesis as verified.")
    return {
        "schema_version": "1.0",
        "experiment_id": f"PRM-EXP-{digest}",
        "candidate_id": candidate["candidate_id"],
        "source": "prime",
        "objective": f"Test the Portal candidate without assuming it is true: {hypothesis}",
        "method": "Define a bounded observable test, collect only attributable evidence, compare outcomes with the stated hypothesis, and record contradictory or null results.",
        "evidence_requirements": requirements,
        "success_criteria": ["Required observations are attributable to named sources.", "The result can distinguish support, contradiction, or insufficient evidence."],
        "safety_constraints": ["No consequential external or physical action is authorized by this specification.", "Human approval is required before execution outside PRIME."],
        "target_system": "velyqua" if any(x.lower() in {"aquarium", "water", "ecology", "sensor", "velyqua"} for x in candidate.get("concepts", [])) else None,
        "verification": {"specialist": route["specialist"], "verdict": "pass" if has_evidence else "not_run", "score": 1.0 if has_evidence else None, "notes": route["reason"]},
        "approval_state": "verified" if has_evidence else "draft",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def validate_experiment_spec(spec: dict[str, Any]) -> dict[str, Any]:
    required = {"schema_version", "experiment_id", "candidate_id", "source", "objective", "method", "evidence_requirements", "approval_state"}
    missing = required - set(spec)
    if missing:
        raise ValueError(f"missing spec fields: {', '.join(sorted(missing))}")
    if spec["schema_version"] != "1.0" or spec["source"] != "prime":
        raise ValueError("invalid spec identity")
    if not re.fullmatch(r"PRM-EXP-[A-Z0-9-]+", _nonempty(spec["experiment_id"], "experiment_id")):
        raise ValueError("invalid experiment_id")
    _nonempty(spec["candidate_id"], "candidate_id")
    _nonempty(spec["objective"], "objective")
    _nonempty(spec["method"], "method")
    if spec["approval_state"] not in SPEC_STATES:
        raise ValueError("invalid approval_state")
    if not isinstance(spec["evidence_requirements"], list) or not spec["evidence_requirements"]:
        raise ValueError("evidence_requirements must be a non-empty array")
    return spec


def serialize_record(candidate: dict[str, Any], spec: dict[str, Any]) -> str:
    return json.dumps({"candidate": candidate, "spec": spec}, ensure_ascii=False, sort_keys=True)
