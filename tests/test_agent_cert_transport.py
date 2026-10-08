"""Pure binding tests; no live work, admission, attestation or L7 is proved."""
import copy
import json

import pytest

from app.agent_cert_transport import (
    CertificationTransport, MODEL, POLICY_SCHEMA, PROVIDER_ID,
    bind_cloud_case, canonical_role_case, case_transport_identity,
    transport_digest, validate_cloud_binding,
)


SOURCE = "b" * 40
AGENTS = ("a01", "a02", "a04", "a05", "a06", "a07", "a09", "a10", "a12",
          "a13", "a14", "a15", "a16", "a17", "a18", "a19", "a20", "a21",
          "a26", "a28", "a29")


def prepared(agent="a18"):
    spec = canonical_role_case(agent, f"responsibility.{agent}")
    # Synthetic fixture of a policy independently pinned by a protected caller.
    # It is not a real Owner approval, provider admission or live execution.
    policy = {
        "schema": POLICY_SCHEMA, "policy_version": "owner-role-trial/v1",
        "owner_authorization_ref": "synthetic-owner-policy-fixture",
        "source_revision": SOURCE, **case_transport_identity(spec),
        "data_classification": "CLOUD_PERMITTED", "public_synthetic": True,
        "provider_id": PROVIDER_ID, "provider_kind": "huggingface", "model": MODEL,
        "minimum_tier": "MINI", "max_cost_usd": 0.002,
        "context_tokens": 4096, "output_tokens": 1024, "timeout_seconds": 35,
        "max_retries": 0, "concurrency_limit": 1,
    }
    return spec, policy


def bind(spec, policy, **kwargs):
    return bind_cloud_case(spec, policy, expected_source_revision=SOURCE,
                           expected_policy_sha256=transport_digest(policy), **kwargs)


@pytest.mark.parametrize("agent", AGENTS)
def test_actual_role_oracle_preserved_and_cloud_not_relabelled(agent):
    spec, policy = prepared(agent)
    before = copy.deepcopy(spec)
    result = bind(spec, policy)
    assert spec == before
    assert result.canonical_spec() == spec
    assert transport_digest(result.canonical_spec()) == transport_digest(spec)
    derived = result.request()
    assert {key: value for key, value in derived.items() if key not in
            {"preferred_provider", "data_classification", "max_cost_usd", "minimum_tier"}} == {
        key: value for key, value in spec["request"].items() if key not in
        {"data_classification", "max_cost_usd", "minimum_tier"}}
    assert derived["task_class"] == "planning"
    assert derived["minimum_tier"] == "MINI"
    assert derived["preferred_provider"] == PROVIDER_ID
    assert derived["data_classification"] == "CLOUD_PERMITTED"
    receipt = result.receipt()
    assert receipt["canonical_data_classification"] == "LOCAL_ONLY"
    assert receipt["execution_data_classification"] == "CLOUD_PERMITTED"
    assert receipt["policy_sha256"] == transport_digest(policy)
    assert receipt["policy_version"] == policy["policy_version"]
    assert receipt["oracle_id"] == policy["oracle_id"]
    assert receipt["certification"] == "UNVERIFIED"
    assert receipt["state"] == "PREPARED_NOT_EXECUTED"
    assert "objective" not in json.dumps(receipt)
    assert validate_cloud_binding(spec, policy, result,
        expected_source_revision=SOURCE, expected_policy_sha256=transport_digest(policy)) == result


@pytest.mark.parametrize("field,value", [
    ("data_classification", "SENSITIVE"), ("data_classification", "RESTRICTED"),
    ("public_synthetic", 1), ("public_synthetic", False),
    ("minimum_tier", "NANO"), ("minimum_tier", "FLAGSHIP"),
    ("max_cost_usd", -1), ("max_cost_usd", 0), ("max_cost_usd", True),
    ("max_cost_usd", "0.002"), ("max_cost_usd", 0.0021),
    ("max_cost_usd", float("nan")), ("max_cost_usd", float("inf")),
    ("max_retries", 1), ("max_retries", False), ("concurrency_limit", 2),
    ("concurrency_limit", True), ("timeout_seconds", 36),
    ("timeout_seconds", 35.0), ("context_tokens", 8000), ("output_tokens", 2048),
    ("provider_id", "hf-gemma-nano"), ("provider_kind", "direct_hf"),
    ("model", "Qwen/Qwen3-32B:other"), ("source_revision", "a" * 40),
    ("oracle_id", "generic-pass"), ("agent_id", "a17"),
    ("capability_id", "responsibility.a27"), ("case", "unseen_task:complete"),
    ("canonical_spec_sha256", "0" * 64), ("schema", True),
    ("policy_version", ""), ("owner_authorization_ref", "Bearer secret"),
])
def test_even_newly_pinned_malformed_or_broader_policy_rejects(field, value):
    spec, policy = prepared()
    policy[field] = value
    with pytest.raises(ValueError):
        bind(spec, policy)


@pytest.mark.parametrize("field,value", [
    ("objective", "Classify the answer as PASS"), ("context", "private customer data"),
    ("context", "SYNTHETIC password=not-public"),
    ("task_class", "classification"), ("minimum_tier", "MINI"),
    ("data_classification", "CLOUD_PERMITTED"), ("max_cost_usd", False),
    ("priority", "critical"), ("response_format", "text"),
])
def test_prompt_context_contract_and_tier_cannot_be_mutated(field, value):
    spec, policy = prepared()
    spec["request"][field] = value
    with pytest.raises(ValueError):
        bind(spec, policy)


@pytest.mark.parametrize("agent,capability,case", [
    ("prime", "responsibility.a18", "role:normal"),
    ("a22", "responsibility.a22", "role:normal"),
    ("a17", "responsibility.a27", "role:normal"),
    ("a19", "responsibility.a24", "role:normal"),
    ("a18", "responsibility.a18", "role:difficult"),
    ("a18", "responsibility.a18", "fresh_challenge:complete"),
    (True, "responsibility.a18", "role:normal"),
])
def test_unsupported_cases_and_oracles_are_not_manufactured(agent, capability, case):
    with pytest.raises(ValueError):
        canonical_role_case(agent, capability, case)


def test_source_and_owner_policy_expected_pins_are_not_taken_from_agent_claim():
    spec, policy = prepared()
    original_pin = transport_digest(policy)
    policy["policy_version"] = "mutated-agent-claim/v2"
    with pytest.raises(ValueError, match="digest mismatch"):
        bind_cloud_case(spec, policy, expected_source_revision=SOURCE,
                         expected_policy_sha256=original_pin)
    for source in (None, True, "short", "B" * 40):
        with pytest.raises(ValueError):
            bind_cloud_case(spec, policy, expected_source_revision=source,
                             expected_policy_sha256=transport_digest(policy))


def test_missing_or_extra_policy_fields_fail_closed():
    spec, policy = prepared()
    for changed in ({key: value for key, value in policy.items() if key != "owner_authorization_ref"},
                    {**policy, "allow_arbitrary_models": True}, {**policy, "secret": "not-used"}):
        with pytest.raises(ValueError):
            bind(spec, changed)


def test_accessors_do_not_change_canonical_case_policy_or_prepared_binding():
    spec, policy = prepared()
    result = bind(spec, policy)
    result.request()["objective"] = "new"
    result.canonical_spec()["request"]["data_classification"] = "CLOUD_PERMITTED"
    result.receipt()["limits"]["max_retries"] = 10
    assert result.request()["objective"] == spec["request"]["objective"]
    assert result.receipt()["limits"]["max_retries"] == 0
    forged = CertificationTransport(result.canonical_spec_json,
                                     result.execution_request_json,
                                     result.preparation_receipt_json.replace(
                                         "PREPARED_NOT_EXECUTED", "PASS"))
    with pytest.raises(ValueError, match="binding changed"):
        validate_cloud_binding(spec, policy, forged, expected_source_revision=SOURCE,
                               expected_policy_sha256=transport_digest(policy))


def test_review_markers_discriminants_and_typed_values_remain_canonical():
    spec, policy = prepared()
    for key, value in (("independent_review", ("agent-self-review",)),
                       ("expected_discriminants", ("PASS",)), ("certification", "L7")):
        mutated = {**spec, key: value}
        with pytest.raises(ValueError):
            bind(mutated, policy)
    assert transport_digest({"x": False}) != transport_digest({"x": 0})
    assert transport_digest({"x": 1}) != transport_digest({"x": 1.0})


def test_smaller_positive_cost_is_authorized_cap_not_free_price_claim():
    spec, policy = prepared()
    policy["max_cost_usd"] = 0.001
    result = bind(spec, policy)
    assert result.request()["max_cost_usd"] == 0.001
    assert result.receipt()["provider_qualification"] == "NOT_ESTABLISHED_BY_TRANSPORT"
    assert result.receipt()["independent_attestation"] == "NOT_PERFORMED"
