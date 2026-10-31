"""Qualification contracts without generation or live services."""

import pytest
from app.response_schema import canonicalize_schema
from scripts.benchmark_eco_runtime import trial_spec


@pytest.mark.parametrize("role,model", [("fast", "gemma3:1b"), ("deep", "gemma3:12b")])
def test_trial_schema_is_supported_and_never_supplies_expected_answers(role, model):
    spec = trial_spec(model, 4, role)
    schema = canonicalize_schema(spec["response_schema"])
    assert schema["type"] == "object"
    assert set(schema["required"]) == set(spec["expected"])
    assert all(set(p) == {"type"} for p in schema["properties"].values())
    assert spec["context"] == 8192


def test_embedding_trial_uses_three_finite_semantic_inputs_without_generation_schema():
    spec = trial_spec("embeddinggemma:300m-qat-q4_0", 4, "embedding")
    assert len(spec["inputs"]) == 3
    assert spec["inputs"][0] == spec["inputs"][1]
    assert "response_schema" not in spec
