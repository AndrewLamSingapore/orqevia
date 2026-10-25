"""Independent, tenant-scoped optimization experiments in the existing registry DB.

Recording or recommending an experiment grants no model-promotion authority.
Disabled construction and health checks do not touch storage or model artifacts.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterator, Mapping
import uuid

from .inventory import runtime_inventory

IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"{name} must be a stable identifier")
    return value


def _number(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{name} must be finite")
    try:
        finite = math.isfinite(value)
    except OverflowError as error:
        raise ValueError(f"{name} must be finite") from error
    if not finite:
        raise ValueError(f"{name} must be finite")
    if value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be {'positive' if positive else 'nonnegative'}")
    return float(value)


def _digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True)
class ExperimentEvidence:
    schema_version: str
    model_id: str
    technique: str
    baseline_sha256: str
    candidate_sha256: str
    measured_at: str
    source_revision: str
    workload: dict
    hardware: dict
    measurements: dict
    quality: dict
    compatible: bool
    preparation: dict

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> "ExperimentEvidence":
        if not isinstance(value, Mapping):
            raise ValueError("experiment evidence must be an object")
        if set(value) != set(cls.__dataclass_fields__):
            raise ValueError("experiment fields must match the MEL evidence contract")
        # A JSON round trip prevents mutable caller aliases and rejects NaN/Infinity.
        try:
            data = json.loads(json.dumps(dict(value), allow_nan=False))
            result = cls(**data)
        except (TypeError, ValueError) as error:
            raise ValueError("experiment must contain finite JSON data") from error
        if result.schema_version != "1.0" or result.technique != "onnx_dynamic_int8":
            raise ValueError("unsupported experiment schema or technique")
        _identifier(result.model_id, "model_id")
        _digest(result.baseline_sha256, "baseline_sha256")
        _digest(result.candidate_sha256, "candidate_sha256")
        if result.baseline_sha256 == result.candidate_sha256:
            raise ValueError("baseline and candidate must be distinct artifacts")
        if not isinstance(result.source_revision, str) or not re.fullmatch(r"[0-9a-f]{40}", result.source_revision):
            raise ValueError("source_revision must be a Git SHA")
        try:
            timestamp = datetime.fromisoformat(result.measured_at.replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError) as error:
            raise ValueError("measured_at must be an ISO timestamp") from error
        if timestamp.tzinfo is None:
            raise ValueError("measured_at must include a timezone")
        if type(result.compatible) is not bool:
            raise ValueError("compatible must be a boolean")
        for name in ("workload", "hardware", "measurements", "quality", "preparation"):
            if not isinstance(getattr(result, name), dict):
                raise ValueError(f"{name} must be an object")
        workload = result.workload
        if set(workload) != {"sha256", "sample_count", "kind", "representative", "labeled_sample_count"}:
            raise ValueError("workload fields must match the MEL evidence contract")
        _digest(workload["sha256"], "workload.sha256")
        if workload["kind"] not in {"controlled_fixture", "local_corpus", "production_corpus"}:
            raise ValueError("unsupported workload kind")
        if type(workload["sample_count"]) is not int or workload["sample_count"] <= 0:
            raise ValueError("sample_count must be positive")
        if type(workload["labeled_sample_count"]) is not int or workload["labeled_sample_count"] < 0:
            raise ValueError("labeled_sample_count must be nonnegative")
        if type(workload["representative"]) is not bool:
            raise ValueError("representative must be boolean")
        if workload["kind"] == "controlled_fixture" and workload["representative"]:
            raise ValueError("controlled fixtures cannot establish production representativeness")
        if set(result.measurements) != {"baseline", "candidate"}:
            raise ValueError("baseline and candidate measurements are required")
        for label, measurement in result.measurements.items():
            cls._validate_measurement(measurement, label)
        quality = result.quality
        if set(quality) != {"mean_cosine", "min_cosine", "max_absolute_error", "top1_agreement", "critical_task_quality_validated", "task_quality_loss", "task_quality_evidence_sha256"}:
            raise ValueError("quality fields must match the MEL evidence contract")
        for name in ("mean_cosine", "min_cosine"):
            value = quality[name]
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not -1 <= value <= 1:
                raise ValueError(f"{name} must be between -1 and 1")
        if not 0 <= _number(quality["top1_agreement"], "top1_agreement") <= 1:
            raise ValueError("top1_agreement must be between 0 and 1")
        _number(quality["max_absolute_error"], "max_absolute_error")
        if type(quality["critical_task_quality_validated"]) is not bool:
            raise ValueError("critical_task_quality_validated must be boolean")
        if quality["critical_task_quality_validated"]:
            _number(quality["task_quality_loss"], "task_quality_loss")
            _digest(quality["task_quality_evidence_sha256"], "task_quality_evidence_sha256")
            if not workload["representative"] or not workload["labeled_sample_count"]:
                raise ValueError("critical quality needs representative labeled evidence")
        elif quality["task_quality_loss"] is not None or quality["task_quality_evidence_sha256"] is not None:
            raise ValueError("unvalidated task quality must remain unavailable")
        return result

    @staticmethod
    def _validate_measurement(data: Any, label: str) -> None:
        expected = {"load_ms", "cold_first_batch_ms", "peak_process_memory_bytes", "startup_peak_memory_bytes", "artifact_bytes", "cpu_seconds", "wall_seconds", "batch_1", "batch_8"}
        if not isinstance(data, dict) or set(data) != expected:
            raise ValueError(f"{label} measurement fields do not match the contract")
        for name in expected - {"batch_1", "batch_8"}:
            _number(data[name], f"{label}.{name}", positive=name == "artifact_bytes")
            if name.endswith("bytes") and type(data[name]) is not int:
                raise ValueError("memory and artifact byte counts must be integers")
        if data["peak_process_memory_bytes"] < data["startup_peak_memory_bytes"]:
            raise ValueError("process peak cannot decrease below its startup peak")
        for name in ("batch_1", "batch_8"):
            timing = data[name]
            if not isinstance(timing, dict) or set(timing) != {"mean_ms", "p50_ms", "p95_ms", "stdev_ms", "min_ms", "max_ms", "samples", "throughput_items_per_second"}:
                raise ValueError("timing fields do not match the contract")
            if type(timing["samples"]) is not int or timing["samples"] < 2:
                raise ValueError("repeated measurements are required")
            for key in set(timing) - {"samples"}:
                _number(timing[key], f"{label}.{name}.{key}", positive=key != "stdev_ms")
            if not timing["min_ms"] <= timing["p50_ms"] <= timing["p95_ms"] <= timing["max_ms"]:
                raise ValueError("timing quantiles must be ordered")
            if not timing["min_ms"] <= timing["mean_ms"] <= timing["max_ms"]:
                raise ValueError("timing mean must be within observed range")
            batch_size = 1 if name == "batch_1" else 8
            expected_throughput = 1000 * batch_size / timing["mean_ms"]
            if not math.isclose(timing["throughput_items_per_second"], expected_throughput, rel_tol=1e-6):
                raise ValueError("throughput must agree with measured batch size and mean latency")


class MELService:
    """Advisory-only efficiency evidence, independent of PIF and core inference."""

    def __init__(self, path: str | Path | None = None, *, enabled: bool | None = None) -> None:
        if enabled is not None and type(enabled) is not bool:
            raise ValueError("enabled must be boolean")
        self.enabled = enabled if enabled is not None else os.getenv("ORQEVIA_MEL_ENABLED", "0").lower() in {"1", "true", "yes"}
        default = Path(os.getenv("ORQEVIA_DATA_DIR", "/data")) / "model-registry.db"
        self.path = Path(path or os.getenv("ORQEVIA_MODEL_REGISTRY_DB") or default)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=20)
        try:
            db.row_factory = sqlite3.Row
            with db:
                db.execute("CREATE TABLE IF NOT EXISTS mel_experiments (experiment_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, actor TEXT NOT NULL, recorded_at TEXT NOT NULL, evidence_sha256 TEXT NOT NULL, evidence_json TEXT NOT NULL)")
                db.execute("CREATE INDEX IF NOT EXISTS mel_experiments_tenant ON mel_experiments(tenant_id,recorded_at)")
                yield db
        finally:
            db.close()

    def health(self) -> dict:
        result = {"capability": "mel", "enabled": self.enabled, "status": "disabled", "independent_of_pif": True, "automatic_promotion": False}
        if self.enabled:
            try:
                with self._connect() as db:
                    db.execute("SELECT 1").fetchone()
                result["status"] = "available"
            except (OSError, sqlite3.Error):
                result["status"] = "degraded"
                result["reason"] = "experiment_storage_unavailable"
        return result

    def inventory(self) -> dict:
        if not self.enabled:
            return self.health()
        return {**self.health(), "inventory": runtime_inventory(), "model_routing_changed": False}

    def experiments(self, tenant_id: str, limit: int = 50) -> dict:
        _identifier(tenant_id, "tenant_id")
        if type(limit) is not int or limit <= 0:
            raise ValueError("limit must be positive")
        if not self.enabled:
            return {**self.health(), "experiments": []}
        with self._connect() as db:
            rows = db.execute("SELECT * FROM mel_experiments WHERE tenant_id=? ORDER BY recorded_at DESC,experiment_id DESC LIMIT ?", (tenant_id, limit)).fetchall()
        return {"status": "available", "experiments": [self._record(row) for row in rows]}

    @staticmethod
    def _record(row: sqlite3.Row) -> dict:
        item = dict(row)
        encoded = item.pop("evidence_json")
        item["integrity"] = "PASS" if hashlib.sha256(encoded.encode()).hexdigest() == item["evidence_sha256"] else "FAIL"
        item["evidence"] = json.loads(encoded)
        return item

    def record_experiment(self, evidence: Mapping[str, Any], *, tenant_id: str, actor: str) -> dict:
        _identifier(tenant_id, "tenant_id")
        _identifier(actor, "actor")
        if not self.enabled:
            return self.health()
        parsed = ExperimentEvidence.parse(evidence)
        encoded = json.dumps(asdict(parsed), sort_keys=True, separators=(",", ":"), allow_nan=False)
        experiment_id = str(uuid.uuid4())
        values = (experiment_id, tenant_id, actor, datetime.now(timezone.utc).isoformat(), hashlib.sha256(encoded.encode()).hexdigest(), encoded)
        with self._connect() as db:
            db.execute("INSERT INTO mel_experiments VALUES(?,?,?,?,?,?)", values)
            row = db.execute("SELECT * FROM mel_experiments WHERE experiment_id=? AND tenant_id=?", (experiment_id, tenant_id)).fetchone()
        return {"status": "recorded", "experiment": self._record(row), "model_routing_changed": False}

    def recommend(self, model_id: str, *, tenant_id: str, max_quality_loss: float = 0.01) -> dict:
        _identifier(model_id, "model_id")
        _number(max_quality_loss, "max_quality_loss")
        if not self.enabled:
            return self.health()
        result = {"status": "retain_baseline", "model_id": model_id, "model_routing_changed": False, "automatic_promotion": False, "reasons": ["no_qualified_experiment"]}
        with self._connect() as db:
            rows = db.execute("SELECT * FROM mel_experiments WHERE tenant_id=? ORDER BY recorded_at DESC", (tenant_id,)).fetchall()
        reasons = set()
        for row in rows:
            if hashlib.sha256(row["evidence_json"].encode()).hexdigest() != row["evidence_sha256"]:
                reasons.add("stored_evidence_integrity_failed")
                continue
            try:
                evidence = ExperimentEvidence.parse(json.loads(row["evidence_json"]))
            except ValueError:
                reasons.add("stored_evidence_invalid")
                continue
            if evidence.model_id != model_id:
                continue
            if not evidence.compatible:
                reasons.add("runtime_compatibility_not_validated")
                continue
            if not evidence.quality["critical_task_quality_validated"]:
                reasons.add("operational_task_quality_not_validated")
                continue
            if evidence.quality["task_quality_loss"] > max_quality_loss:
                reasons.add("task_quality_loss_exceeds_threshold")
                continue
            if not self._performance_supported(evidence):
                reasons.add("latency_improvement_not_supported")
                continue
            return {**result, "status": "eligible_candidate", "experiment_id": row["experiment_id"], "candidate_sha256": evidence.candidate_sha256, "reasons": ["representative_quality_and_repeated_latency_evidence"], "caveat": "Advisory evidence only; existing model activation and rollback contracts remain authoritative."}
        if reasons:
            result["reasons"] = sorted(reasons)
        return result

    @staticmethod
    def _performance_supported(evidence: ExperimentEvidence) -> bool:
        # Conservative normal-approximation comparison, disclosed in the runbook.
        for batch in ("batch_1", "batch_8"):
            baseline = evidence.measurements["baseline"][batch]
            candidate = evidence.measurements["candidate"][batch]
            radius = 1.96 * math.sqrt(baseline["stdev_ms"] ** 2 / baseline["samples"] + candidate["stdev_ms"] ** 2 / candidate["samples"])
            if candidate["p95_ms"] > baseline["p95_ms"] or candidate["mean_ms"] + radius >= baseline["mean_ms"]:
                return False
        return True
