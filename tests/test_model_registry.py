import hashlib
from dataclasses import replace

import pytest

from app.model_registry import ModelRegistryStore, ModelVersion


def version(number="1.0.0", *, context=8192, output=2048):
    return ModelVersion(
        model_id="local.deep",
        version=number,
        provider="ollama",
        model_name="qwen2.5:14b",
        location="local",
        context_tokens=context,
        output_tokens=output,
        capabilities=("text_generation",),
        artifact_sha256=hashlib.sha256(number.encode()).hexdigest(),
        source_url="https://example.invalid/model",
        metadata={"role": "deep"},
    )


def evaluation():
    return {
        "status": "PASS",
        "evidence_ref": "eval://local-deep-1",
        "checks": [{"name": "contract", "status": "PASS"}],
    }


def compatibility():
    return {
        "compatible": True,
        "evidence_ref": "compat://local-deep-1",
        "context_tokens": 8192,
        "output_tokens": 2048,
    }


def test_model_lifecycle_assignment_and_rollback(tmp_path):
    store = ModelRegistryStore(tmp_path / "models.db")
    store.register(version("1.0.0"), actor="owner")
    with pytest.raises(ValueError):
        store.activate("local.deep", "1.0.0", actor="owner", reason="premature")
    store.evaluate("local.deep", "1.0.0", evaluation(), actor="owner")
    with pytest.raises(ValueError):
        store.approve(
            "local.deep",
            "1.0.0",
            {"compatible": False, "evidence_ref": "compat://no"},
            actor="owner",
            reason="incompatible",
        )
    store.approve("local.deep", "1.0.0", compatibility(), actor="owner", reason="reviewed")
    store.activate("local.deep", "1.0.0", actor="owner", reason="promote")
    store.assign("a02", "local.deep", "1.0.0", actor="owner")
    store.register(version("2.0.0"), actor="owner")
    store.evaluate("local.deep", "2.0.0", evaluation(), actor="owner")
    store.approve("local.deep", "2.0.0", compatibility(), actor="owner", reason="reviewed")
    store.activate("local.deep", "2.0.0", actor="owner", reason="promote")
    assert store.get("local.deep", "1.0.0")["state"] == "deprecated"
    assert store.get("local.deep", "2.0.0")["state"] == "active"
    store.rollback("local.deep", "1.0.0", actor="owner", reason="regression")
    assert store.get("local.deep", "1.0.0")["state"] == "active"
    with store.connect() as db:
        assignment = db.execute("SELECT version FROM model_assignments WHERE agent_id='a02'").fetchone()
    assert assignment["version"] == "1.0.0"
    history = store.history("local.deep", "1.0.0")["events"]
    assert [item["event"] for item in history][-2:] == ["deprecated", "rolled_back"]


def test_duplicate_conflict_and_invalid_bounds_fail_closed(tmp_path):
    store = ModelRegistryStore(tmp_path / "models.db")
    store.register(version(), actor="owner")
    assert store.register(version(), actor="owner")["state"] == "registered"
    changed = replace(version(), model_name="different")
    with pytest.raises(ValueError):
        store.register(changed, actor="owner")
    with pytest.raises(ValueError):
        version("3.0.0", context=1024, output=2048)


def test_health_reports_lifecycle_counts(tmp_path):
    store = ModelRegistryStore(tmp_path / "models.db")
    store.register(version(), actor="owner")
    report = store.health()
    assert report["models"] == 1
    assert report["states"]["registered"] == 1
    assert report["events"] == 1
