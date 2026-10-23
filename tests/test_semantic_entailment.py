"""Contract/security fixtures; actual NLI accuracy has separate pinned-model receipts."""

import math

import pytest

from app.semantic_entailment import EntailmentEngine, verdict


def test_semantic_scores_are_bounded_and_uncertainty_is_explicit():
    assert verdict([0, 0, 0])["assessment"] == "UNCERTAIN"
    confident = verdict([10, 0, 0])
    assert confident["assessment"] == "CONTRADICTION"
    assert sum(confident["uncalibrated_model_scores"].values()) == pytest.approx(1, abs=0.000002)
    for invalid in ([math.nan, 0, 0], [0, math.inf, 0], [1, 2]):
        with pytest.raises(RuntimeError):
            verdict(invalid)


def test_unconfigured_semantic_service_never_claims_loaded_or_grants_authority(monkeypatch):
    monkeypatch.delenv("ORQEVIA_NLI_MODEL_DIR", raising=False)
    engine = EntailmentEngine()
    assert engine.health()["status"] == "NOT_CONFIGURED"
    assert engine.health()["formal_proof"] is False
    assert engine.health()["grants_execution_authority"] is False
    with pytest.raises(RuntimeError):
        engine.assess("A bounded premise", "A bounded claim")
    with pytest.raises(ValueError):
        engine.assess("", "claim")


def test_semantic_artifacts_are_verified_before_optional_runtime_loading(tmp_path, monkeypatch):
    monkeypatch.setenv("ORQEVIA_NLI_MODEL_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text("This is not the pinned model configuration")
    with pytest.raises(RuntimeError, match="integrity"):
        EntailmentEngine().load()
