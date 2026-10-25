"""Meaningful MEL evidence, tenant isolation, fallback and dependency boundaries."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from app.mel import MELService
from app.mel.benchmark import aggregate, load_corpus, summarize_times
from app.mel.service import ExperimentEvidence


def evidence(*, qualified=False):
    def measurement(mean):
        timing = {"mean_ms": mean, "p50_ms": mean, "p95_ms": mean + 1, "stdev_ms": 0.5, "min_ms": mean - 1, "max_ms": mean + 2, "samples": 20, "throughput_items_per_second": 1000 / mean}
        return {"load_ms": 5, "cold_first_batch_ms": 10, "peak_process_memory_bytes": 1000, "startup_peak_memory_bytes": 500, "artifact_bytes": 1000, "cpu_seconds": 1, "wall_seconds": 2, "batch_1": dict(timing), "batch_8": {**timing, "throughput_items_per_second": 8000 / mean}}
    return {
        "schema_version": "1.0", "model_id": "embedding-model", "technique": "onnx_dynamic_int8",
        "baseline_sha256": "a" * 64, "candidate_sha256": "b" * 64,
        "measured_at": "2026-10-25T00:00:00+00:00", "source_revision": "c" * 40,
        "workload": {"sha256": "d" * 64, "sample_count": 40, "kind": "production_corpus" if qualified else "controlled_fixture", "representative": qualified, "labeled_sample_count": 40 if qualified else 0},
        "hardware": {"provider": "CPUExecutionProvider"},
        "measurements": {"baseline": measurement(20), "candidate": measurement(10)},
        "quality": {"mean_cosine": 0.999, "min_cosine": 0.998, "max_absolute_error": 0.001, "top1_agreement": 1.0, "critical_task_quality_validated": qualified, "task_quality_loss": 0.005 if qualified else None, "task_quality_evidence_sha256": "e" * 64 if qualified else None},
        "compatible": True, "preparation": {"method": "test fixture, not actual benchmark evidence"},
    }


def test_disabled_creates_no_storage_and_is_independent(tmp_path, monkeypatch):
    monkeypatch.setenv("ORQEVIA_PIF_ENABLED", "1")
    service = MELService(tmp_path / "absent" / "model-registry.db", enabled=False)
    assert service.health()["status"] == "disabled"
    assert service.inventory()["independent_of_pif"]
    assert service.experiments("tenant")["experiments"] == []
    assert service.record_experiment(evidence(), tenant_id="tenant", actor="owner")["status"] == "disabled"
    assert service.recommend("embedding-model", tenant_id="tenant")["status"] == "disabled"
    assert not (tmp_path / "absent").exists()


def test_explicit_flags_are_independent(tmp_path, monkeypatch):
    monkeypatch.setenv("ORQEVIA_PIF_ENABLED", "0")
    monkeypatch.setenv("ORQEVIA_MEL_ENABLED", "true")
    assert MELService(tmp_path / "registry.db").health()["status"] == "available"
    monkeypatch.setenv("ORQEVIA_MEL_ENABLED", "false")
    monkeypatch.setenv("ORQEVIA_PIF_ENABLED", "true")
    assert MELService(tmp_path / "second.db").health()["status"] == "disabled"


def test_tenant_isolation_immutable_records_and_no_llm_schema(tmp_path):
    path = tmp_path / "model-registry.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE unrelated_existing_models (id TEXT PRIMARY KEY)")
        db.execute("INSERT INTO unrelated_existing_models VALUES('preserved')")
    service = MELService(path, enabled=True)
    original = evidence()
    first = service.record_experiment(original, tenant_id="one", actor="owner")
    original["quality"]["mean_cosine"] = 0
    stored = service.experiments("one")["experiments"][0]
    assert stored["evidence"]["quality"]["mean_cosine"] == 0.999
    encoded = json.dumps(stored["evidence"], sort_keys=True, separators=(",", ":"))
    assert stored["evidence_sha256"] == hashlib.sha256(encoded.encode()).hexdigest()
    assert service.experiments("two")["experiments"] == []
    assert service.recommend("embedding-model", tenant_id="two")["reasons"] == ["no_qualified_experiment"]
    second = service.record_experiment(evidence(), tenant_id="one", actor="owner")
    assert first["experiment"]["experiment_id"] != second["experiment"]["experiment_id"]
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT id FROM unrelated_existing_models").fetchone()[0] == "preserved"
        assert db.execute("SELECT count(*) FROM mel_experiments").fetchone()[0] == 2
        assert "context_tokens" not in {row[1] for row in db.execute("PRAGMA table_info(mel_experiments)")}


def test_synthetic_quality_cannot_promote(tmp_path):
    service = MELService(tmp_path / "registry.db", enabled=True)
    service.record_experiment(evidence(), tenant_id="tenant", actor="owner")
    result = service.recommend("embedding-model", tenant_id="tenant")
    assert result["status"] == "retain_baseline"
    assert result["reasons"] == ["operational_task_quality_not_validated"]
    assert result["model_routing_changed"] is False


def test_qualified_recommendation_is_still_advisory(tmp_path):
    service = MELService(tmp_path / "registry.db", enabled=True)
    service.record_experiment(evidence(qualified=True), tenant_id="tenant", actor="owner")
    result = service.recommend("embedding-model", tenant_id="tenant")
    assert result["status"] == "eligible_candidate"
    assert result["candidate_sha256"] == "b" * 64
    assert result["model_routing_changed"] is False
    assert result["automatic_promotion"] is False
    assert service.recommend("embedding-model", tenant_id="tenant", max_quality_loss=0.001)["reasons"] == ["task_quality_loss_exceeds_threshold"]


def test_noisy_or_slower_candidate_retains_baseline(tmp_path):
    service = MELService(tmp_path / "registry.db", enabled=True)
    item = evidence(qualified=True)
    item["measurements"]["candidate"]["batch_1"]["stdev_ms"] = 100
    service.record_experiment(item, tenant_id="tenant", actor="owner")
    assert service.recommend("embedding-model", tenant_id="tenant")["reasons"] == ["latency_improvement_not_supported"]


def test_unsupported_runtime_retains_baseline(tmp_path):
    item = evidence(qualified=True)
    item["compatible"] = False
    service = MELService(tmp_path / "registry.db", enabled=True)
    service.record_experiment(item, tenant_id="tenant", actor="owner")
    assert service.recommend("embedding-model", tenant_id="tenant")["reasons"] == ["runtime_compatibility_not_validated"]


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(candidate_sha256="a" * 64),
    lambda d: d.update(baseline_sha256="not-a-hash"),
    lambda d: d.update(source_revision="branch-name"),
    lambda d: d.update(measured_at="2026-10-25"),
    lambda d: d.update(compatible="true"),
    lambda d: d.update(technique="remote_weight_pruning"),
    lambda d: d["quality"].update(mean_cosine=float("nan")),
    lambda d: d["quality"].update(top1_agreement=1.01),
    lambda d: d["quality"].update(critical_task_quality_validated=True, task_quality_loss=0.0, task_quality_evidence_sha256="e" * 64),
    lambda d: d["workload"].update(representative=True),
    lambda d: d["workload"].update(sample_count=True),
    lambda d: d["measurements"]["baseline"]["batch_1"].update(samples=1),
    lambda d: d["measurements"]["baseline"]["batch_1"].update(mean_ms=float("inf")),
    lambda d: d["measurements"]["baseline"]["batch_1"].update(p95_ms=0.5),
])
def test_invalid_evidence_is_rejected_without_insert(tmp_path, mutate):
    service = MELService(tmp_path / "registry.db", enabled=True)
    item = deepcopy(evidence())
    mutate(item)
    with pytest.raises(ValueError):
        service.record_experiment(item, tenant_id="tenant", actor="owner")
    assert service.experiments("tenant")["experiments"] == []


def test_storage_failure_is_separate_health(tmp_path):
    path = tmp_path / "corrupt.db"
    path.write_bytes(b"not a SQLite database")
    service = MELService(path, enabled=True)
    assert service.health()["status"] == "degraded"
    assert service.health()["reason"] == "experiment_storage_unavailable"


def test_inventory_does_not_infer_gpu_support(tmp_path, monkeypatch):
    monkeypatch.delenv("ORQEVIA_MEL_MODEL_DIR", raising=False)
    service = MELService(tmp_path / "registry.db", enabled=True)
    inventory = service.inventory()["inventory"]
    assert inventory["local_onnx_artifact"]["available"] is False
    assert inventory["acceleration"]["nvidia_2_4"] == "NOT_VERIFIED"


def test_import_has_no_heavy_framework_or_pif_dependency():
    code = "import sys; import app.mel; assert not ({'torch','transformers','numpy','onnxruntime','onnx','app.pif'} & set(sys.modules))"
    subprocess.run([sys.executable, "-B", "-c", code], cwd=Path(__file__).resolve().parents[1], check=True)


def test_timing_and_aggregation_preserve_real_repetitions():
    summary = summarize_times([1, 2, 3, 4], 8)
    assert summary["p50_ms"] == 2.5
    assert summary["p95_ms"] == 4
    assert summary["throughput_items_per_second"] == 3200
    observation = {"load_ms": 5, "cold_first_batch_ms": 9, "cpu_seconds": 1, "wall_seconds": 2, "peak_process_memory_bytes": 100, "startup_peak_memory_bytes": 50, "artifact_bytes": 30, "batch_1": [1, 2], "batch_8": [3, 4]}
    merged = aggregate([observation, {**observation, "peak_process_memory_bytes": 110}])
    assert merged["batch_1"]["samples"] == 4
    assert merged["peak_process_memory_bytes"] == 110


def test_corpus_loading_uses_actual_text_but_does_not_infer_quality(tmp_path):
    path = tmp_path / "chunks.json"
    path.write_text(json.dumps([{"text": "one", "source": "fixture"}, {"text": "two"}]))
    assert load_corpus(path) == ["one", "two"]
    path.write_text(json.dumps([{"text": ""}]))
    with pytest.raises(ValueError):
        load_corpus(path)


def test_quality_comparison_is_only_baseline_agreement():
    np = pytest.importorskip("numpy")
    from app.mel.benchmark import quality_summary

    base = np.zeros((4, 384))
    base[0, 0] = base[2, 0] = base[1, 1] = base[3, 1] = 1
    result = quality_summary(base, base.copy(), 2)
    assert result["top1_agreement"] == 1
    assert result["mean_cosine"] == 1
    assert result["critical_task_quality_validated"] is False
    assert result["task_quality_loss"] is None
    with pytest.raises(ValueError):
        quality_summary(base, np.zeros_like(base), 2)


def test_experiment_contract_does_not_accept_unexpected_payload():
    item = evidence()
    item["prompt"] = "unrecognized payload"
    with pytest.raises(ValueError):
        ExperimentEvidence.parse(item)
