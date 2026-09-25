import json

import pytest

from app.capability_router import CapabilityBackend, load_capability_profiles, select_capability_route


def profiles():
    return load_capability_profiles()


@pytest.mark.parametrize("capability", ["reasoning", "coding", "chinese", "english", "retrieval", "verification"])
def test_fastest_verified_local_model_handles_routine_capabilities(capability):
    route = select_capability_route(profiles(), capability=capability, classification="LOCAL_ONLY")
    assert route.state == "READY"
    assert route.backend.model == "gemma3:1b"
    assert route.grants_execution_authority is False


def test_tool_selection_uses_only_model_that_passed_measured_gate():
    route = select_capability_route(profiles(), capability="tool_selection", classification="LOCAL_ONLY")
    assert route.state == "READY"
    assert route.backend.model == "gemma3:4b"


def test_strict_json_fails_into_deterministic_verification_instead_of_guessing():
    route = select_capability_route(profiles(), capability="structured_output", classification="LOCAL_ONLY")
    assert route.state == "VERIFY_REQUIRED"
    assert route.backend is None
    assert route.grants_execution_authority is False


def test_preferred_model_loss_falls_back_only_to_another_verified_model():
    current = profiles()
    unavailable_fast = tuple(
        CapabilityBackend(item.name, item.model, item.location, item.median_latency_seconds, item.verified_capabilities, available=item.model != "gemma3:1b")
        for item in current
    )
    route = select_capability_route(unavailable_fast, capability="chinese", classification="LOCAL_ONLY")
    assert route.state == "READY"
    assert route.backend.model == "gemma3:4b"


def test_pressure_queues_verified_local_work_without_cloud_fallback():
    route = select_capability_route(profiles(), capability="coding", classification="CLOUD_PERMITTED", local_saturated=True)
    assert route.state == "QUEUED"
    assert route.backend.location == "local"


def test_unverified_capability_and_unknown_classification_fail_closed():
    assert select_capability_route(profiles(), capability="vision", classification="SENSITIVE").state == "UNAVAILABLE"
    assert select_capability_route(profiles(), capability="reasoning", classification="UNKNOWN").state == "DENIED"


def test_profile_loader_rejects_cloud_overlap_and_unmeasured_latency(tmp_path):
    base = {
        "schema_version": "1.0",
        "privacy": "LOCAL_ONLY",
        "profiles": [{"name": "bad", "model": "bad", "location": "cloud", "median_latency_seconds": 0, "verified_capabilities": ["reasoning"], "failed_capabilities": ["reasoning"]}],
    }
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    with pytest.raises(ValueError):
        load_capability_profiles(path)
