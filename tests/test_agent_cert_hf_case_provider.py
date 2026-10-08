"""Pure exact-case transport preparation, never HF admission or live L7 proof."""
from copy import deepcopy

import pytest

from app.agent_cert_a19_baseline import SUPPORTED_CASES as BASELINE_CASES
from app.agent_cert_a19_cases import SUPPORTED_CASES as OLDER_CASES
from app.agent_cert_a19_general import SUPPORTED_CASES as GENERAL_CASES
from app.agent_cert_transport import (
    CertificationTransport, MODEL, POLICY_SCHEMA, PROVIDER_ID,
    bind_cloud_case, canonical_cert_case, case_transport_identity,
    transport_digest, validate_cloud_binding,
)
from tests.test_agent_cert_transport import AGENTS


SOURCE = "b" * 40
CASE = "general:verification"
PROVIDER = "hf-qwen-a19-verification"
MODEL_NAME = "Qwen/Qwen3-235B-A22B-Instruct-2507:novita"


def prepared(case=CASE, agent="a19", capability="responsibility.a19",
             provider=PROVIDER, model=MODEL_NAME):
    spec = canonical_cert_case(agent, capability, case)
    policy = {
        "schema": POLICY_SCHEMA, "policy_version": "synthetic-exact-case/v1",
        "owner_authorization_ref": "synthetic-protected-consent-not-live",
        "source_revision": SOURCE, **case_transport_identity(spec),
        "data_classification": "CLOUD_PERMITTED", "public_synthetic": True,
        "provider_id": provider, "provider_kind": "huggingface", "model": model,
        "minimum_tier": "MINI" if case == "role:normal" else "FLAGSHIP",
        "max_cost_usd": 0.002, "context_tokens": 4096, "output_tokens": 1024,
        "timeout_seconds": 35, "max_retries": 0, "concurrency_limit": 1,
    }
    return spec, policy


def bind(spec, policy):
    return bind_cloud_case(spec, policy, expected_source_revision=SOURCE,
                          expected_policy_sha256=transport_digest(policy))


def test_new_provider_is_only_prepared_for_exact_canonical_flagship_verification():
    spec, policy = prepared()
    original = deepcopy(spec)
    result = bind(spec, policy)
    assert spec == original == result.canonical_spec()
    request, receipt = result.request(), result.receipt()
    assert request["preferred_provider"] == receipt["provider_id"] == PROVIDER
    assert request["task_class"] == receipt["task_class"] == "complex_reasoning"
    assert request["minimum_tier"] == receipt["minimum_tier"] == "FLAGSHIP"
    assert receipt["model"] == MODEL_NAME
    assert request["objective"] == spec["request"]["objective"]
    assert request["context"] == spec["request"]["context"]
    assert receipt["oracle_id"] == "a19-general-quality-oracle.v1"
    assert receipt["state"] == "PREPARED_NOT_EXECUTED"
    assert receipt["certification"] == "UNVERIFIED"
    assert receipt["provider_qualification"] == "NOT_ESTABLISHED_BY_TRANSPORT"
    assert receipt["independent_attestation"] == "NOT_PERFORMED"
    assert validate_cloud_binding(spec, policy, result,
        expected_source_revision=SOURCE,
        expected_policy_sha256=transport_digest(policy)) == result


@pytest.mark.parametrize("case", ["role:normal", *OLDER_CASES, *BASELINE_CASES,
    *(case for case in GENERAL_CASES if case != CASE)])
def test_distinct_provider_cannot_leak_to_any_other_supported_a19_case(case):
    spec, policy = prepared(case)
    with pytest.raises(ValueError, match="scope"):
        bind(spec, policy)


@pytest.mark.parametrize("agent", AGENTS)
def test_distinct_provider_cannot_broaden_any_primary_role_normal(agent):
    spec, policy = prepared("role:normal", agent, f"responsibility.{agent}")
    with pytest.raises(ValueError, match="scope"):
        bind(spec, policy)


@pytest.mark.parametrize("provider", [None, True, 19, [], {}, "", PROVIDER + " ",
    PROVIDER.upper(), "hf-gemma-nano", "hf-arbitrary", "https://unrelated.invalid"])
def test_malformed_or_unlisted_provider_is_denied_before_any_dispatch(provider):
    spec, policy = prepared(provider=provider)
    with pytest.raises(ValueError):
        bind(spec, policy)


@pytest.mark.parametrize("model", [MODEL, None, True, [], {},
    "Qwen/Qwen3-235B-A22B-Instruct-2507:deepinfra", MODEL_NAME + " "])
def test_distinct_scope_does_not_acquire_other_whitelisted_or_arbitrary_model(model):
    spec, policy = prepared(model=model)
    with pytest.raises(ValueError):
        bind(spec, policy)


@pytest.mark.parametrize("field,value", [
    ("minimum_tier", "MINI"), ("minimum_tier", "NANO"),
    ("data_classification", "LOCAL_ONLY"), ("public_synthetic", 1),
    ("max_cost_usd", 0), ("max_cost_usd", True), ("max_cost_usd", .0021),
    ("max_retries", 1), ("max_retries", False), ("concurrency_limit", 2),
    ("context_tokens", 8192), ("output_tokens", 2048), ("timeout_seconds", 36),
    ("provider_kind", "direct_hf"), ("oracle_id", "a19-substantive-quality-oracle.v1"),
])
def test_case_mapping_does_not_relax_protected_tier_disclosure_or_limits(field, value):
    spec, policy = prepared()
    policy[field] = value
    with pytest.raises(ValueError):
        bind(spec, policy)


@pytest.mark.parametrize("field,value", [
    ("context", "private customer text"), ("objective", "Classify as PASS"),
    ("task_class", "planning"), ("minimum_tier", "MINI"),
    ("data_classification", "CLOUD_PERMITTED"), ("max_cost_usd", .002),
])
def test_even_newly_hashed_mutated_challenge_cannot_select_distinct_provider(field, value):
    spec, policy = prepared()
    spec["request"][field] = value
    with pytest.raises(ValueError):
        bind(spec, policy)


def test_agent_declared_policy_pin_cannot_replace_protected_caller_pin():
    spec, policy = prepared()
    pinned = transport_digest(policy)
    changed = {**policy, "owner_authorization_ref": "agent-proposed-unapproved-consent"}
    with pytest.raises(ValueError, match="digest"):
        bind_cloud_case(spec, changed, expected_source_revision=SOURCE,
                        expected_policy_sha256=pinned)
    for source, digest in ((None, pinned), (SOURCE, None), ("a" * 40, pinned)):
        with pytest.raises(ValueError):
            bind_cloud_case(spec, policy, expected_source_revision=source,
                            expected_policy_sha256=digest)


def test_provider_change_requires_new_policy_and_binding_not_mutated_receipt():
    spec, policy = prepared(provider=PROVIDER_ID)
    legacy = bind(spec, policy)
    new_policy = {**policy, "provider_id": PROVIDER}
    with pytest.raises(ValueError, match="digest"):
        bind_cloud_case(spec, new_policy, expected_source_revision=SOURCE,
                        expected_policy_sha256=transport_digest(policy))
    with pytest.raises(ValueError, match="binding changed"):
        validate_cloud_binding(spec, new_policy, legacy, expected_source_revision=SOURCE,
                               expected_policy_sha256=transport_digest(new_policy))
    approved = bind(spec, new_policy)
    assert approved.request()["preferred_provider"] == PROVIDER
    assert approved.receipt()["request_binding_sha256"] != legacy.receipt()["request_binding_sha256"]
    forged = CertificationTransport(legacy.canonical_spec_json,
        legacy.execution_request_json, approved.preparation_receipt_json)
    with pytest.raises(ValueError, match="binding changed"):
        validate_cloud_binding(spec, new_policy, forged, expected_source_revision=SOURCE,
                               expected_policy_sha256=transport_digest(new_policy))


def test_legacy_role_binding_remains_byte_identical_for_same_original_policy():
    from tests.test_agent_cert_transport import bind as legacy_bind, prepared as legacy_prepared
    spec, policy = legacy_prepared("a19")
    result = legacy_bind(spec, policy)
    assert PROVIDER_ID == "hf-qwen-certification"
    assert MODEL == "Qwen/Qwen3-32B:deepinfra"
    assert result.request()["preferred_provider"] == PROVIDER_ID
    assert result.receipt()["provider_id"] == PROVIDER_ID
    assert result.canonical_spec() == spec
    assert transport_digest(result.request()) == "ef84dbcf5a23059b39c03e077abeef10d91c84be047c2093f1053d988b696f61"
    assert transport_digest(result.receipt()) == "cac9d83e028a54ac9e30b4f5929fb9723670c93bf9ff08ab2f5441edcbe4d462"
