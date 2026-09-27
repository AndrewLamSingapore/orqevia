#!/usr/bin/env python3
"""Offline Dell peer gate and evidence primitives; no candidate execution.

The CLI intentionally has no way to import a trusted execution context. JSON
claims and correctly hashed files are not independent verification. A future
trusted, isolated Dell runner must call the Python API with its own observations.
This module does not authenticate that runner or prove that it runs on Dell.

The evidence backend requires POSIX openat/O_NOFOLLOW semantics and fails closed
on unsupported platforms. Files are append-only *through this API*, not WORM.
SHA-256 checks detect changes against known digests; they are not signatures.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import os
import re
import stat
import sys
import uuid
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
GIT_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
BLOB_NAME = re.compile(r"[0-9a-f]{32}\.(?:blob|json)\Z")
PROOF_LABELS = (
    "PROVEN_BY_AUTOMATION", "PROVEN_BY_INDEPENDENT_DELL",
    "REQUIRES_PHYSICAL_DEVICE", "REQUIRES_LONGER_OBSERVATION", "UNPROVEN",
)
ADVERSARIAL_CATEGORIES = (
    "caller_controlled_authority", "fabricated_system_metadata",
    "model_content_system_metadata_separation", "owner_member_isolation",
    "authentication_session_expiry_recovery", "durable_identity",
    "duplicate_submission", "retries_timeouts", "stop_complete_races", "toctou",
    "concurrency", "restart_persistence", "corrupted_tampered_evidence",
    "stale_state", "prediction_integrity", "learning_evidence_qualification",
    "database_migrations", "backward_compatibility", "rollback",
    "pwa_cache_version_transitions", "offline_reconnect", "api_failure",
    "malformed_inputs", "bounded_resource_exhaustion", "dependency_service_outage",
    "task_lifecycle_correctness", "runtime_source_image_identity",
    "provenance_receipt_integrity",
)
BASE_CHECKS = (
    "frozen_remote_publication", "source_sha", "tree_content_integrity",
    "clean_worktree", "manifest", "candidate_image_identity",
    "provenance_evidence_bindings", "canonical_regression", "adversarial_regression",
    "migration_rehearsal", "rollback_rehearsal", "identity_boundary",
    "authority_boundary", "provenance_boundary",
)
READ_ALOUD_CHECKS = (
    "read_aloud_user_gesture", "read_aloud_speech_api_invocation",
    "read_aloud_voice_resolution", "read_aloud_utterance_creation",
    "read_aloud_start", "read_aloud_physical_boundary", "read_aloud_end_error_timeout",
)
REQUIRED_CHECKS = BASE_CHECKS + tuple("challenge:" + c for c in ADVERSARIAL_CATEGORIES) + READ_ALOUD_CHECKS
POST_CHECKS = (
    "production_health", "task_execution", "identity_session_integrity",
    "data_preservation", "runtime_receipts", "provenance", "no_unexpected_drift",
    "rollback_available",
)
IPHONE_AUDIBILITY = "Physical iPhone Read Aloud: Owner must observe audible speech on the exact approved candidate."
LONG_OBSERVATION = "Long-duration reliability and recovery remain unproven beyond the recorded test window."


class InvalidEvidence(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")


def _exact_fields(obj: dict, fields: set[str], label: str) -> None:
    if not isinstance(obj, dict) or set(obj) != fields:
        raise ValueError(f"{label}: expected exactly {sorted(fields)}")


def _json_load(path: str) -> Any:
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError(f"duplicate JSON key: {key}")
            obj[key] = value
        return obj
    with open(path, "rb") as source:
        raw = source.read(MAX_ARTIFACT_BYTES + 1)
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise ValueError("input exceeds size limit")
    return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(f"invalid JSON value {token}")))


@dataclasses.dataclass(frozen=True)
class EvidenceRef:
    name: str
    sha256: str
    size: int

    def validate(self) -> None:
        if not isinstance(self.name, str) or not BLOB_NAME.fullmatch(self.name):
            raise InvalidEvidence("invalid artifact name; flat opaque names only")
        if not isinstance(self.sha256, str) or not SHA256.fullmatch(self.sha256):
            raise InvalidEvidence("invalid evidence digest")
        if type(self.size) is not int or not 0 <= self.size <= MAX_ARTIFACT_BYTES:
            raise InvalidEvidence("invalid evidence size")

    @classmethod
    def from_dict(cls, value: dict) -> EvidenceRef:
        _exact_fields(value, {"name", "sha256", "size"}, "evidence reference")
        result = cls(**value)
        result.validate()
        return result


class EvidenceStore:
    """Flat, descriptor-anchored artifact storage. No delete/replace operation."""

    def __init__(self, root: str | Path):
        if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
            raise RuntimeError("Evidence backend unavailable: safe descriptor-relative, no-follow I/O required; use a supported POSIX host or add a reviewed native Windows backend.")
        given = Path(root)
        if ".." in given.parts:
            raise InvalidEvidence("parent traversal is not allowed")
        self.root = given.absolute()
        self._fd = None
        # Walk each path component using directory descriptors, so a symlink
        # swap between a check and an open cannot redirect artifact operations.
        directory_fd = os.open(self.root.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for component in self.root.parts[1:]:
                try:
                    child_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                except FileNotFoundError:
                    try:
                        os.mkdir(component, mode=0o700, dir_fd=directory_fd)
                    except FileExistsError:
                        pass
                    child_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = child_fd
            self._fd = directory_fd
        except BaseException:
            os.close(directory_fd)
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def put_bytes(self, value: bytes, *, json_artifact: bool = False) -> EvidenceRef:
        if not isinstance(value, bytes) or len(value) > MAX_ARTIFACT_BYTES:
            raise InvalidEvidence("artifact must be bytes within configured bound")
        if self._fd is None:
            raise InvalidEvidence("evidence store closed")
        name = uuid.uuid4().hex + (".json" if json_artifact else ".blob")
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400, dir_fd=self._fd)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(value)
                output.flush()
                os.fsync(output.fileno())
            os.fsync(self._fd)
        except BaseException:
            # Preserve even interrupted writes. They will not verify and cannot
            # accidentally be reused, because every write has a new identity.
            raise
        return EvidenceRef(name, hashlib.sha256(value).hexdigest(), len(value))

    def put_file(self, path: str | Path) -> EvidenceRef:
        source = Path(path)
        if ".." in source.parts:
            raise InvalidEvidence("parent traversal is not allowed")
        absolute = source.absolute()
        directory_fd = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for component in absolute.parts[1:-1]:
                next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = next_fd
            source_fd = os.open(absolute.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
            with os.fdopen(source_fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_ARTIFACT_BYTES:
                    raise InvalidEvidence("evidence must be a bounded regular file")
                data = stream.read(MAX_ARTIFACT_BYTES + 1)
            return self.put_bytes(data)
        finally:
            os.close(directory_fd)

    def read(self, ref: EvidenceRef) -> bytes:
        ref.validate()
        if self._fd is None:
            raise InvalidEvidence("evidence store closed")
        fd = os.open(ref.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._fd)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size != ref.size:
                raise InvalidEvidence("evidence size or file type differs")
            data = stream.read(MAX_ARTIFACT_BYTES + 1)
        if len(data) != ref.size or hashlib.sha256(data).hexdigest() != ref.sha256:
            raise InvalidEvidence("evidence digest differs")
        return data

    def seal(self, report: dict) -> EvidenceRef:
        return self.put_bytes(_canonical(report), json_artifact=True)


@dataclasses.dataclass(frozen=True)
class Binding:
    candidate_sha: str
    tree_sha: str
    image_digest: str
    runtime_revision: str

    def validate(self):
        if not isinstance(self.candidate_sha, str) or not GIT_SHA.fullmatch(self.candidate_sha):
            raise ValueError("candidate_sha must be a full lowercase Git object ID")
        if not isinstance(self.tree_sha, str) or not GIT_SHA.fullmatch(self.tree_sha) or len(self.tree_sha) != len(self.candidate_sha):
            raise ValueError("tree_sha must be a full Git object ID of the same format")
        if not isinstance(self.image_digest, str) or not IMAGE_DIGEST.fullmatch(self.image_digest):
            raise ValueError("image_digest must be immutable sha256:<64 hex>; tags are insufficient")
        if not isinstance(self.runtime_revision, str) or not GIT_SHA.fullmatch(self.runtime_revision):
            raise ValueError("runtime_revision must be a full lowercase Git object ID")
        if self.runtime_revision != self.candidate_sha:
            raise ValueError("runtime_revision must bind the exact candidate source SHA")

    @classmethod
    def from_manifest(cls, manifest: dict) -> Binding:
        if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION or type(manifest.get("schema_version")) is not int:
            raise ValueError("unsupported manifest schema")
        allowed = {"schema_version", "candidate_sha", "tree_sha", "image_digest", "runtime_revision", "claims"}
        _exact_fields(manifest, allowed, "candidate manifest")
        if not isinstance(manifest["claims"], list) or any(not isinstance(c, str) or not c.strip() or len(c) > 4000 for c in manifest["claims"]):
            raise ValueError("claims must be an array of bounded nonempty strings")
        result = cls(**{key: manifest[key] for key in ("candidate_sha", "tree_sha", "image_digest", "runtime_revision")})
        result.validate()
        return result


@dataclasses.dataclass(frozen=True)
class CheckObservation:
    """Trusted runner observation; never construct from candidate-supplied JSON.

    Evidence content must be interpreted by the trusted runner. A success-shaped
    log file or asserted JSON result is not sufficient to create an observation.
    """
    check_id: str
    binding: Binding
    outcome: str
    proof: str
    evidence: tuple[EvidenceRef, ...]
    run_id: str
    detail: str = ""


@dataclasses.dataclass(frozen=True)
class Finding:
    finding_id: str
    severity: str
    detail: str
    evidence: tuple[EvidenceRef, ...]
    resolved: bool = False


@dataclasses.dataclass(frozen=True)
class TrustedRunContext:
    """API trust boundary, not an authentication scheme.

    Only the trusted Dell runner supplies this object after independent work.
    The offline CLI cannot load one. This reference toolkit supplies no runner,
    host authentication, isolation, scheduler or production access adapter.
    """
    binding: Binding
    run_id: str
    verifier_peer: str
    independent_source: bool
    observations: tuple[CheckObservation, ...]
    findings: tuple[Finding, ...]
    # Complete claim accounting belongs to the independent verifier. Candidate
    # prose is never silently promoted to proof by being present in a manifest.
    unproven_claims: tuple[str, ...] = ()
    additional_physical_gates: tuple[str, ...] = ()
    longer_observation_gates: tuple[str, ...] = ()


def _empty_report(manifest: Any, phase: str = "PRE_PROMOTION") -> dict:
    candidate = manifest if isinstance(manifest, dict) else {}
    return {
        "SCHEMA VERSION": SCHEMA_VERSION, "PHASE": phase,
        "CANDIDATE SHA": candidate.get("candidate_sha", "UNAVAILABLE"),
        "IMAGE": candidate.get("image_digest", "UNAVAILABLE"),
        "SOURCE INTEGRITY": "BLOCKED", "CANONICAL REGRESSION": "BLOCKED",
        "DELL ADVERSARIAL REGRESSION": "BLOCKED", "P0": "NOT ASSESSED",
        "P1": "NOT ASSESSED", "P2": "NOT ASSESSED", "MIGRATION": "BLOCKED",
        "ROLLBACK": "BLOCKED", "IDENTITY": "BLOCKED", "AUTHORITY": "BLOCKED",
        "PROVENANCE": "BLOCKED", "SESSION/RECONNECT": "BLOCKED", "PWA/CACHE": "BLOCKED",
        "PHYSICAL GATES REMAINING": [IPHONE_AUDIBILITY],
        "UNPROVEN CLAIMS": list(candidate.get("claims", [])) if isinstance(candidate.get("claims"), list) else [],
        "LONGER OBSERVATION GATES": [LONG_OBSERVATION],
        "PROMOTION VERIFICATION": "BLOCKED", "PASS / FAIL / BLOCKED": "BLOCKED",
        "PROOF CLASSIFICATION": "UNPROVEN", "CHECKS": {}, "REASONS": [],
        "EVIDENCE ARTIFACT": "UNSEALED", "EVIDENCE SHA-256": "UNSEALED",
        "LIMITATIONS": [
            "Offline assessment is not proof that this process runs on Dell or reaches ABEX.",
            "Hashes are integrity checks, not evidence authenticity, signatures, or WORM storage.",
            "Software start/end events do not establish physical iPhone audibility.",
            "Independent verification PASS does not authorize deployment or replace Owner physical acceptance.",
        ],
    }


def _finish(report: dict, reasons: list[str], failures: list[str]) -> dict:
    report["REASONS"] = failures + reasons
    status = "FAIL" if failures else "BLOCKED" if reasons else "PASS"
    report["PASS / FAIL / BLOCKED"] = status
    report["PROMOTION VERIFICATION"] = "PROMOTION_VERIFICATION_PASS" if status == "PASS" else status
    report["PROOF CLASSIFICATION"] = "PROVEN_BY_INDEPENDENT_DELL" if status == "PASS" else "UNPROVEN"
    return report


def _check_context(binding: Binding, context: TrustedRunContext | None, store: EvidenceStore, required: tuple[str, ...]):
    reasons, failures, checks = [], [], {}
    if not isinstance(context, TrustedRunContext):
        return ["No trusted independent Dell execution context; candidate claims are not proof."], failures, checks
    shape_errors = _context_shape_errors(context)
    if shape_errors:
        return shape_errors, failures, checks
    try:
        context.binding.validate()
    except (ValueError, TypeError) as exc:
        return [f"Invalid trusted binding: {exc}"], failures, checks
    if context.binding != binding:
        failures.append("Trusted run identity differs from candidate source/tree/image/revision.")
    if context.verifier_peer != "DELL" or context.independent_source is not True:
        reasons.append("Independent Dell peer/source verification missing.")
    if not isinstance(context.run_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{8,128}", context.run_id):
        reasons.append("Invalid independent run identity.")
    seen = set()
    for observation in context.observations:
        if not isinstance(observation, CheckObservation):
            reasons.append("Malformed trusted check observation.")
            continue
        key = observation.check_id
        if not isinstance(key, str) or key not in required:
            reasons.append(f"Unexpected check identifier: {key!r}")
            continue
        if key in seen:
            failures.append(f"Duplicate check identity: {key}")
            continue
        seen.add(key)
        valid = True
        if observation.binding != binding or observation.run_id != context.run_id:
            failures.append(f"{key}: stale or differently bound observation.")
            valid = False
        if observation.proof != "PROVEN_BY_INDEPENDENT_DELL":
            reasons.append(f"{key}: not proven independently by Dell.")
            valid = False
        if observation.outcome not in ("PASS", "FAIL", "BLOCKED"):
            reasons.append(f"{key}: invalid outcome.")
            valid = False
        elif observation.outcome == "FAIL":
            failures.append(f"{key}: independent check failed.")
        elif observation.outcome != "PASS":
            reasons.append(f"{key}: incomplete independent check.")
        if not observation.evidence:
            reasons.append(f"{key}: no preserved evidence.")
            valid = False
        for ref in observation.evidence:
            try:
                if not isinstance(ref, EvidenceRef):
                    raise InvalidEvidence("reference not typed")
                store.read(ref)
            except (ValueError, OSError) as exc:
                failures.append(f"{key}: evidence integrity failure ({exc}).")
                valid = False
        checks[key] = {
            "outcome": observation.outcome if valid else "BLOCKED",
            "proof": observation.proof if valid else "UNPROVEN",
            "evidence": [dataclasses.asdict(ref) for ref in observation.evidence if isinstance(ref, EvidenceRef)],
            "detail": observation.detail,
        }
    reasons.extend(f"Missing independent check: {key}" for key in required if key not in seen)
    return reasons, failures, checks


def _context_shape_errors(context: TrustedRunContext) -> list[str]:
    errors = []
    if not isinstance(context.binding, Binding):
        errors.append("Trusted context binding must be a Binding object.")
    if not isinstance(context.run_id, str) or not isinstance(context.verifier_peer, str) or type(context.independent_source) is not bool:
        errors.append("Malformed trusted context identity.")
    for field in ("observations", "findings", "unproven_claims", "additional_physical_gates", "longer_observation_gates"):
        if not isinstance(getattr(context, field), tuple):
            errors.append(f"Trusted context {field} must be an immutable tuple.")
    if errors:
        return errors
    for field in ("unproven_claims", "additional_physical_gates", "longer_observation_gates"):
        if any(not isinstance(item, str) or not item.strip() or len(item) > 4000 for item in getattr(context, field)):
            errors.append(f"Malformed trusted context {field}.")
    for observation in context.observations:
        if not isinstance(observation, CheckObservation):
            errors.append("Malformed trusted check observation.")
            continue
        if not isinstance(observation.binding, Binding) or not all(isinstance(getattr(observation, name), str) for name in ("check_id", "outcome", "proof", "run_id", "detail")):
            errors.append("Malformed observation identity or outcome.")
        if not isinstance(observation.evidence, tuple) or any(not isinstance(ref, EvidenceRef) for ref in observation.evidence):
            errors.append("Malformed observation evidence references.")
    for finding in context.findings:
        if not isinstance(finding, Finding):
            errors.append("Malformed trusted finding.")
            continue
        if not all(isinstance(getattr(finding, name), str) for name in ("finding_id", "severity", "detail")) or type(finding.resolved) is not bool:
            errors.append("Malformed trusted finding identity or severity.")
        if not isinstance(finding.evidence, tuple) or any(not isinstance(ref, EvidenceRef) for ref in finding.evidence):
            errors.append("Malformed finding evidence references.")
    return errors


def _check_findings(context: TrustedRunContext, store: EvidenceStore):
    reasons, failures = [], []
    findings_by_level = {"P0": [], "P1": [], "P2": []}
    finding_ids = set()
    for finding in context.findings:
        if finding.severity not in ("P0", "P1", "P2", "P3"):
            reasons.append("Malformed independent finding severity.")
            continue
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", finding.finding_id) or finding.finding_id in finding_ids:
            failures.append("Missing, invalid, or duplicate finding identity.")
        finding_ids.add(finding.finding_id)
        # Frozen defects cannot be cleared by writing resolved=true.
        if finding.severity in findings_by_level:
            findings_by_level[finding.severity].append(finding.finding_id)
            failures.append(f"{finding.severity} in frozen candidate: {finding.finding_id}; successor candidate required.")
        if not finding.evidence:
            reasons.append(f"{finding.finding_id}: finding evidence not preserved.")
        for ref in finding.evidence:
            try:
                store.read(ref)
            except (ValueError, OSError) as exc:
                failures.append(f"{finding.finding_id}: finding evidence integrity failure ({exc}).")
    return reasons, failures, findings_by_level


def _group(checks: dict, keys: tuple[str, ...]) -> str:
    outcomes = [checks.get(key, {}).get("outcome", "BLOCKED") for key in keys]
    return "FAIL" if "FAIL" in outcomes else "PASS" if all(x == "PASS" for x in outcomes) else "BLOCKED"


def evaluate_candidate(manifest: dict, store: EvidenceStore, context: TrustedRunContext | None = None) -> dict:
    report = _empty_report(manifest)
    try:
        binding = Binding.from_manifest(manifest)
    except (ValueError, TypeError) as exc:
        return _finish(report, [f"Invalid or incomplete candidate manifest: {exc}"], [])
    reasons, failures, checks = _check_context(binding, context, store, REQUIRED_CHECKS)
    report["CHECKS"] = checks
    if isinstance(context, TrustedRunContext) and not _context_shape_errors(context):
        report["RUN ID"] = context.run_id
        report["BINDING"] = dataclasses.asdict(binding)
        report["PHYSICAL GATES REMAINING"].extend(context.additional_physical_gates)
        report["LONGER OBSERVATION GATES"].extend(context.longer_observation_gates)
        report["UNPROVEN CLAIMS"] = list(dict.fromkeys(report["UNPROVEN CLAIMS"] + list(context.unproven_claims)))
        finding_reasons, finding_failures, findings_by_level = _check_findings(context, store)
        reasons.extend(finding_reasons)
        failures.extend(finding_failures)
        for severity, items in findings_by_level.items():
            report[severity] = items if items else "NONE OBSERVED IN THIS RUN"
    report["SOURCE INTEGRITY"] = _group(checks, BASE_CHECKS[:5])
    for label, keys in {
        "CANONICAL REGRESSION": ("canonical_regression",),
        "DELL ADVERSARIAL REGRESSION": ("adversarial_regression",) + tuple("challenge:" + c for c in ADVERSARIAL_CATEGORIES) + READ_ALOUD_CHECKS,
        "MIGRATION": ("migration_rehearsal", "challenge:database_migrations"),
        "ROLLBACK": ("rollback_rehearsal", "challenge:rollback"),
        "IDENTITY": ("identity_boundary", "challenge:durable_identity", "challenge:owner_member_isolation"),
        "AUTHORITY": ("authority_boundary", "challenge:caller_controlled_authority", "challenge:fabricated_system_metadata", "challenge:model_content_system_metadata_separation"),
        "PROVENANCE": ("provenance_boundary", "provenance_evidence_bindings", "challenge:provenance_receipt_integrity"),
        "SESSION/RECONNECT": ("challenge:authentication_session_expiry_recovery", "challenge:offline_reconnect"),
        "PWA/CACHE": ("challenge:pwa_cache_version_transitions",),
    }.items():
        report[label] = _group(checks, keys)
    return _finish(report, reasons, failures)


def evaluate_postpromotion(manifest: dict, store: EvidenceStore, approved_context: TrustedRunContext | None = None, deployed_context: TrustedRunContext | None = None) -> dict:
    """Re-evaluate approval; never trust an imported 'PASS' report.

    The caller supplies independently measured production read-only observations.
    This function has no deployment, repair, rollback, or networking capability.
    """
    approval = evaluate_candidate(manifest, store, approved_context)
    report = _empty_report(manifest, "POST_PROMOTION")
    report["APPROVAL ASSESSMENT"] = approval
    report["APPROVED CANDIDATE VERIFICATION"] = approval["PROMOTION VERIFICATION"]
    for field in ("PHYSICAL GATES REMAINING", "UNPROVEN CLAIMS", "LONGER OBSERVATION GATES"):
        report[field] = list(approval[field])
    reasons, failures = [], []
    if approval["PASS / FAIL / BLOCKED"] != "PASS":
        reasons.append("Approved candidate has no currently valid independent Dell PASS.")
    try:
        binding = Binding.from_manifest(manifest)
    except (ValueError, TypeError) as exc:
        return _finish(report, [f"Invalid approved manifest: {exc}"], [])
    if not isinstance(deployed_context, TrustedRunContext):
        reasons.append("No trusted read-only deployed identity and health observations.")
        report["POST-PROMOTION VERIFICATION"] = "BLOCKED"
        return _finish(report, reasons, failures)
    shape_errors = _context_shape_errors(deployed_context)
    if shape_errors:
        report["POST-PROMOTION VERIFICATION"] = "BLOCKED"
        return _finish(report, reasons + shape_errors, failures)
    for label, additional in (
        ("PHYSICAL GATES REMAINING", deployed_context.additional_physical_gates),
        ("UNPROVEN CLAIMS", deployed_context.unproven_claims),
        ("LONGER OBSERVATION GATES", deployed_context.longer_observation_gates),
    ):
        report[label] = list(dict.fromkeys(report[label] + list(additional)))
    for field in ("candidate_sha", "tree_sha", "image_digest", "runtime_revision"):
        approved = getattr(binding, field)
        deployed = getattr(deployed_context.binding, field, None)
        if not deployed:
            reasons.append(f"Missing deployed {field}.")
        elif deployed != approved:
            failures.append(f"DEPLOYMENT DRIFT: {field}: approved={approved}; deployed={deployed}")
    post_reasons, post_failures, checks = _check_context(binding, deployed_context, store, POST_CHECKS)
    reasons.extend(post_reasons)
    failures.extend(post_failures)
    if isinstance(approved_context, TrustedRunContext) and deployed_context.run_id == approved_context.run_id:
        reasons.append("Post-promotion observations must be a separate run from candidate qualification.")
    finding_reasons, finding_failures, findings_by_level = _check_findings(deployed_context, store)
    reasons.extend(finding_reasons)
    failures.extend(finding_failures)
    for severity, items in findings_by_level.items():
        report[severity] = items if items else "NONE OBSERVED IN THIS RUN"
    report["CHECKS"] = checks
    report["APPROVED BINDING"] = dataclasses.asdict(binding)
    report["DEPLOYED BINDING"] = dataclasses.asdict(deployed_context.binding)
    result = _finish(report, reasons, failures)
    result["POST-PROMOTION VERIFICATION"] = "POST_PROMOTION_VERIFICATION_PASS" if result["PASS / FAIL / BLOCKED"] == "PASS" else result["PASS / FAIL / BLOCKED"]
    # Never expose an active PASS in the gate field when deployment has failed.
    # The historical approval remains explicitly separate above and nested.
    result["PROMOTION VERIFICATION"] = result["POST-PROMOTION VERIFICATION"]
    return result


def seal_assessment(store: EvidenceStore, report: dict) -> tuple[dict, EvidenceRef]:
    """Return external receipt; report cannot contain its own byte hash."""
    frozen = dict(report)
    frozen["EVIDENCE ARTIFACT"] = "See external evidence receipt for this sealed report"
    frozen["EVIDENCE SHA-256"] = "See external evidence receipt; a report cannot contain its own byte digest"
    frozen["SEALED AT UTC"] = dt.datetime.now(dt.timezone.utc).isoformat()
    ref = store.seal(frozen)
    receipt = dict(report)
    receipt["EVIDENCE ARTIFACT"] = str(store.root / ref.name)
    receipt["EVIDENCE SHA-256"] = ref.sha256
    receipt["EVIDENCE REFERENCE"] = dataclasses.asdict(ref)
    return receipt, ref


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    candidate = commands.add_parser("evaluate", help="Offline untrusted manifest assessment; cannot certify PASS")
    candidate.add_argument("manifest")
    candidate.add_argument("--store", required=True)
    post = commands.add_parser("postpromotion", help="Offline post-promotion assessment; requires future trusted read-only adapter for PASS")
    post.add_argument("manifest")
    post.add_argument("--store", required=True)
    add = commands.add_parser("preserve", help="Preserve one local evidence file under a fresh identity")
    add.add_argument("file")
    add.add_argument("--store", required=True)
    verify = commands.add_parser("verify-evidence", help="Compare stored bytes to an externally retained evidence receipt")
    verify.add_argument("reference", help="JSON file with name, sha256, size")
    verify.add_argument("--store", required=True)
    args = parser.parse_args(argv)
    try:
        with EvidenceStore(args.store) as store:
            if args.command == "preserve":
                print(json.dumps(dataclasses.asdict(store.put_file(args.file)), indent=2))
                return 0
            if args.command == "verify-evidence":
                ref = EvidenceRef.from_dict(_json_load(args.reference))
                store.read(ref)
                print(json.dumps({"INTEGRITY": "MATCHES_RETAINED_DIGEST", "AUTHENTICITY": "NOT ESTABLISHED", "reference": dataclasses.asdict(ref)}, indent=2))
                return 0
            manifest = _json_load(args.manifest)
            report = evaluate_candidate(manifest, store) if args.command == "evaluate" else evaluate_postpromotion(manifest, store)
            receipt, _ = seal_assessment(store, report)
            print(json.dumps(receipt, indent=2, ensure_ascii=False))
            return {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[report["PASS / FAIL / BLOCKED"]]
    except (ValueError, OSError, RuntimeError, TypeError) as exc:
        print(json.dumps({"PASS / FAIL / BLOCKED": "BLOCKED", "REASON": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
