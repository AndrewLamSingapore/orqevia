"""Read-only, fail-closed projection of domain-owned agent certification evidence.

Evidence belongs under each agent's directory. This module grants no execution
authority and does not write a central certification flag or mutate the registry.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .agent_registry import agent_record, canonical_agent_id, orchestrator_id


LEVEL_DIMENSIONS = (
    (),
    ("baseline",),
    ("baseline", "role"),
    ("baseline", "role", "general"),
    ("baseline", "role", "general", "collaboration"),
    ("baseline", "role", "general", "collaboration", "recovery"),
    ("baseline", "role", "general", "collaboration", "recovery",
     "authority", "tools", "models", "cross_verification", "fresh_challenge",
     "logic_quality", "health"),
    ("baseline", "role", "general", "collaboration", "recovery",
     "authority", "tools", "models", "cross_verification", "fresh_challenge", "health",
     "logic_quality",
     "broad_transfer", "unseen_task", "adversarial", "context_integrity",
     "conflict_resolution", "injection_resistance", "unauthorized_rejection",
     "model_substitution", "tool_recovery", "handoff_recovery",
     "evidence_integrity", "cross_agent_conflict", "graceful_degradation",
     "independent_verification", "clean_room_audit", "continuous_revalidation"),
)
REQUIRED_CASES = {
    "baseline": ("identity", "initialization", "authorization", "objective", "instruction",
                 "context", "structured_output", "contract", "error", "timeout", "evidence",
                 "result", "completion", "prime_validation"),
    "role": ("normal", "difficult", "edge", "invalid_input", "failure"),
    "general": ("analysis", "planning", "reasoning", "communication", "evidence",
                "decomposition", "artifact_consume", "artifact_produce", "review",
                "verification", "error_recognition", "handoff", "recovery"),
    "logic_quality": ("unsupported_assumption", "contradiction", "counterevidence",
                      "edge_case", "false_pass", "fact_vs_inference"),
    "adversarial": ("ambiguous_instruction", "contradictory_evidence", "stale_information",
                    "invalid_artifact", "malformed_input", "missing_dependency",
                    "false_completion", "unauthorized_action", "injection_attempt"),
    "unauthorized_rejection": ("authorized", "unauthorized", "owner_only"),
    "tool_recovery": ("tool_failure", "bounded_response"),
    "handoff_recovery": ("agent_failure", "bounded_response"),
}
LOGIC_SIGNALS = {
    "unsupported_assumption": "evidence_support",
    "contradiction": "logic_check",
    "counterevidence": "counterexample_check",
    "edge_case": "boundary_check",
    "false_pass": "independent_review",
    "fact_vs_inference": "conflict_status",
}
CERTIFICATION_WAVES = (
    ("baseline",),
    ("role", "general", "tools", "models", "broad_transfer"),
    ("collaboration", "cross_verification", "cross_agent_conflict"),
    ("recovery", "tool_recovery", "handoff_recovery", "graceful_degradation"),
    ("authority", "logic_quality", "adversarial", "context_integrity", "conflict_resolution",
     "injection_resistance", "unauthorized_rejection", "evidence_integrity"),
    ("fresh_challenge", "unseen_task", "model_substitution"),
    ("independent_verification", "clean_room_audit", "continuous_revalidation", "health"),
)
MAX_EVIDENCE_BYTES = 1024 * 1024


def _unique_manifest_fields(pairs):
    """Reject contradictory decoded fields rather than hiding counterevidence."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate certification manifest field")
        result[key] = value
    return result


def _finite_manifest_number(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("nonfinite certification manifest number")
    return parsed


def _invalid_manifest_constant(_):
    raise ValueError("nonfinite certification manifest constant")


def _artifact_digest_ok(agent_dir: Path, name: object, expected: object) -> bool:
    if not isinstance(name, str) or not name or "\\" in name:
        return False
    if not isinstance(expected, str) or len(expected) != 64:
        return False
    evidence = Path(name)
    if evidence.is_absolute() or ".." in evidence.parts:
        return False
    cursor = agent_dir
    for part in evidence.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return False
    artifact = cursor.resolve()
    if not artifact.is_relative_to(agent_dir.resolve()) or not artifact.is_file():
        return False
    if artifact.stat().st_size > MAX_EVIDENCE_BYTES:
        return False
    return hashlib.sha256(artifact.read_bytes()).hexdigest() == expected


def _utc(value: str) -> datetime:
    if type(value) is not str:
        raise ValueError("certification timestamps require strings")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("certification timestamps require timezone")
    return parsed.astimezone(timezone.utc)


class AgentCertificationRegistry:
    """Project current evidence; never promote from registration or task invocation."""

    def __init__(self, evidence_root: Path, *, source_revision: str,
                 verify_record: Callable[[dict], bool] | None = None):
        self.root = Path(evidence_root)
        self.source_revision = source_revision
        self.verify_record = verify_record

    def _valid(self, row: dict, agent_dir: Path, agent_id: str, capability_id: str,
               now: datetime) -> bool:
        try:
            # A name in a JSON record is not independent verification. The
            # domain evidence owner must supply an authenticated verifier.
            if self.verify_record is None or not self.verify_record(row):
                return False
            if row["agent_id"] != agent_id or row["capability_id"] != capability_id:
                return False
            if row["test_result"] != "PASS" or not row["test_version"] or not row["certification_test"]:
                return False
            if canonical_agent_id(row["verifier"]) in {agent_id}:
                return False
            if row["source_revision"] != self.source_revision:
                return False
            if row["authority_scope"] != agent_record(agent_id)["authority"]:
                return False
            # The protected Azure signer retains a legacy digest-only canary
            # path. Its signature proves key custody, not independent case
            # review, so it must never promote a certification projection.
            attestation = row.get("attestation")
            if isinstance(attestation, dict) and attestation.get("algorithm") == "ES256":
                if (not all(isinstance(row.get(field), str) and row[field]
                            for field in ("review_evidence", "review_evidence_sha256",
                                          "review_run_id", "review_test_version",
                                          "review_source_revision"))
                        or row["review_source_revision"] != row["source_revision"]):
                    return False
            if row["dimension"] == "recovery" and row.get("recovery_result") != "PASS":
                return False
            if row["dimension"] == "logic_quality":
                signal = LOGIC_SIGNALS.get(row.get("test_case"))
                signals = row.get("logic_signals")
                if signal is None or not isinstance(signals, dict) or signals.get(signal) != "PASS":
                    return False
            if _utc(row["certified_at"]) > _utc(row["last_revalidated"]) or _utc(row["last_revalidated"]) > now:
                return False
            if _utc(row["expires_at"]) <= now:
                return False
            if not _artifact_digest_ok(agent_dir, row["evidence"], row["evidence_sha256"]):
                return False
            if any(field in row for field in ("review_evidence", "review_evidence_sha256")):
                if (row.get("review_evidence") == row["evidence"]
                        or not _artifact_digest_ok(agent_dir, row.get("review_evidence"),
                                                   row.get("review_evidence_sha256"))):
                    return False
            return True
        except Exception:
            return False

    def _manifest_rows(self, agent_id: str) -> list[dict]:
        """Read one bounded manifest snapshot; never cache across projections."""
        agent_dir = self.root / agent_id
        try:
            if self.root.is_symlink() or agent_dir.is_symlink():
                raise ValueError("certification root or agent directory is a symlink")
            if not agent_dir.resolve().is_relative_to(self.root.resolve()):
                raise ValueError("agent directory escapes certification root")
            manifest = agent_dir / "certification.json"
            if manifest.is_symlink():
                raise ValueError("certification manifest is a symlink")
            with manifest.open("rb") as stream:
                raw = stream.read(MAX_EVIDENCE_BYTES + 1)
            if len(raw) > MAX_EVIDENCE_BYTES:
                raise ValueError("certification manifest exceeds size limit")
            # The manifest is evidence, not a last-key-wins projection. A
            # duplicate at any depth can otherwise conceal a recorded FAIL.
            data = json.loads(raw.decode("utf-8"),
                              object_pairs_hook=_unique_manifest_fields,
                              parse_float=_finite_manifest_number,
                              parse_constant=_invalid_manifest_constant)
            if not isinstance(data, dict):
                raise ValueError("certification manifest must be an object")
            rows = data["records"] if data.get("schema_version") == "1.0" else []
            if not isinstance(rows, list):
                return []
            return rows
        except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError):
            return []

    def project(self, agent_id: str, capability_id: str, *, now: datetime | None = None) -> dict:
        agent_id = canonical_agent_id(agent_id)
        if agent_id == orchestrator_id():
            raise ValueError("orchestrator is not a permanent specialist agent")
        record = agent_record(agent_id)
        if capability_id not in record["capability_requirements"]:
            return {"agent_id": agent_id, "capability_id": capability_id,
                    "level": "L0", "trust_state": "UNPROVEN", "health": "UNKNOWN",
                    "authority_scope": "NOT_AUTHORIZED", "current_dimensions": [],
                    "current_cases": [], "missing_cases": []}
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("projection time requires timezone")
        return self._project_from_rows(agent_id, capability_id, now,
                                       self._manifest_rows(agent_id), record)

    def _project_from_rows(self, agent_id: str, capability_id: str, now: datetime,
                           rows: list[dict], record: dict) -> dict:
        agent_dir = self.root / agent_id
        matching = [row for row in rows if isinstance(row, dict)
                    and row.get("agent_id") == agent_id and row.get("capability_id") == capability_id]
        latest = {}
        malformed = set()
        ambiguous = set()
        for row in matching:
            dimension = row.get("dimension")
            if dimension not in LEVEL_DIMENSIONS[-1]:
                continue
            test_case = row.get("test_case")
            if not isinstance(test_case, str) or not test_case:
                continue
            key = (dimension, test_case)
            try:
                timestamp = (_utc(row["last_revalidated"]), _utc(row["certified_at"]),
                             row.get("test_result") != "PASS")
            except (KeyError, TypeError, ValueError):
                malformed.add(key)
                continue
            if key in latest:
                if timestamp[:2] == latest[key][0][:2]:
                    ambiguous.add(key)
                elif timestamp > latest[key][0]:
                    ambiguous.discard(key)
            if key not in latest or timestamp > latest[key][0]:
                latest[key] = (timestamp, row)
        valid = {key for key, (_, row) in latest.items() if key not in malformed and key not in ambiguous
                 if self._valid(row, agent_dir, agent_id, capability_id, now)}
        current = set()
        duplicate_artifact_cases = set()
        for dimension in LEVEL_DIMENSIONS[-1]:
            required = REQUIRED_CASES.get(dimension, ("complete",))
            if all((dimension, case) in valid for case in required):
                artifacts = [latest[(dimension, case)][1]["evidence"] for case in required]
                if len(artifacts) == len(set(artifacts)):
                    current.add(dimension)
                else:
                    duplicate_artifact_cases.update(
                        (dimension, case) for case in required
                        if artifacts.count(latest[(dimension, case)][1]["evidence"]) > 1)
        latest_rows = [row for _, row in latest.values()]
        health_row = latest.get(("health", "complete"))
        health = "HEALTHY" if "health" in current and health_row and health_row[1].get("health") == "HEALTHY" else "UNKNOWN"
        if health != "HEALTHY":
            current.discard("health")
        level = max(index for index, required in enumerate(LEVEL_DIMENSIONS)
                    if set(required).issubset(current))
        stale = bool(matching) and (len(valid) < len(latest) or not current)
        missing = [(dimension, case) for dimension in LEVEL_DIMENSIONS[-1]
                   for case in REQUIRED_CASES.get(dimension, ("complete",))
                   if ((dimension, case) not in valid
                       or (dimension, case) in duplicate_artifact_cases
                       or (dimension == "health" and "health" not in current))]
        return {"agent_id": agent_id, "capability_id": capability_id,
                "level": f"L{level}",
                "trust_state": ("REVALIDATION-REQUIRED" if stale else
                                "L7-CURRENT" if level == 7 else
                                "CERTIFIED-HEALTHY" if level == 6 else
                                "UNPROVEN" if level == 0 else "CERTIFIED-DEGRADED"),
                "health": health, "authority_scope": record["authority"],
                "current_dimensions": sorted(current),
                "current_cases": [f"{dimension}:{case}" for dimension, case in sorted(valid)
                                  if dimension in current],
                "valid_cases": [f"{dimension}:{case}" for dimension, case in sorted(valid)],
                "missing_cases": [f"{dimension}:{case}" for dimension, case in missing],
                "failure_count": max((row.get("failure_count", 0) for row in latest_rows
                                      if isinstance(row.get("failure_count", 0), int)
                                      and row.get("failure_count", 0) >= 0), default=0)}

    def matrix(self, *, now: datetime | None = None) -> list[dict]:
        """Return one fail-closed certification row per registered specialist.

        A row is L7 only when every owned capability projects to L7. This is
        a read-only work/evidence projection, not a runtime agent test runner.
        """
        from .agent_registry import load_agent_registry

        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("projection time requires timezone")
        rows = []
        for agent in load_agent_registry()["agents"]:
            # A single request sees one bounded, internally consistent manifest
            # snapshot per agent. A later request rereads it, so revocations are
            # not hidden behind a process-wide cache.
            manifest_rows = self._manifest_rows(agent["id"])
            capabilities = [self._project_from_rows(agent["id"], capability, now,
                                                    manifest_rows, agent)
                            for capability in agent["capability_requirements"]]
            level = min(int(item["level"][1:]) for item in capabilities)
            missing = {item["capability_id"]: item["missing_cases"] for item in capabilities
                       if item["missing_cases"]}
            rows.append({"agent_id": agent["id"], "role": agent["role"],
                         "capabilities": capabilities, "level": f"L{level}",
                         "trust_state": ("REVALIDATION-REQUIRED" if any(
                                             item["trust_state"] == "REVALIDATION-REQUIRED"
                                             for item in capabilities) else
                                         "L7-CURRENT" if level == 7 else
                                         "CERTIFIED-HEALTHY" if level == 6 else
                                         "UNPROVEN" if level == 0 else "CERTIFIED-DEGRADED"),
                         "health": "HEALTHY" if all(item["health"] == "HEALTHY"
                                                  for item in capabilities) else "UNKNOWN",
                         "missing": missing})
        return rows

    def pending_waves(self, *, now: datetime | None = None) -> list[list[dict]]:
        """Batch only missing cases; waves encode dependencies, not PASS claims."""
        matrix = self.matrix(now=now)
        waves = []
        for dimensions in CERTIFICATION_WAVES:
            wave = []
            for agent in matrix:
                for capability, missing in agent["missing"].items():
                    for case in missing:
                        if case.partition(":")[0] in dimensions:
                            wave.append({"agent_id": agent["agent_id"],
                                         "capability_id": capability, "case": case})
            waves.append(wave)
        return waves
