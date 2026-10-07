"""Narrow operator admission is an executable restriction, not a quality label."""
from copy import deepcopy
import hashlib
from types import SimpleNamespace

import pytest

from app import cloud_execution
from app.hf_admission import require_hf_admission
from app.provider_runtime import ProviderFailure


PROMPT = "SYNTHETIC: two observations, no restart authority."
PIN = hashlib.sha256(PROMPT.encode("utf-8")).hexdigest()
ENTRY = {
    "id": "hf-fixture", "provider_kind": "huggingface", "enabled": True,
    "qualification_status": "QUALIFIED", "location": "cloud", "tier": "MINI",
    "model": "Qwen/Qwen3-32B:deepinfra", "context_tokens": 4096,
    "output_tokens": 64, "input_usd_million": "0.08", "output_usd_million": "0.28",
    "allowed_task_classes": ["planning"],
    "allowed_prompt_bindings": [{"agent": "a19", "prompt_sha256": PIN}],
}
JOB = {
    "id": "scope-fixture", "agent": "a19", "prompt": PROMPT,
    "task_class": "planning", "preferred_provider": "hf-fixture", "allow_cloud": 1,
    "data_classification": "CLOUD_PERMITTED", "estimated_cost_usd": 0.001,
    "max_cost_usd": 0.001,
}


def denied(entry, job):
    with pytest.raises(ProviderFailure, match="PROVIDER_UNQUALIFIED") as error:
        require_hf_admission(entry, job, entry["id"])
    assert error.value.pre_execution is True
    assert PROMPT not in str(error.value)


def test_exact_actor_and_original_prompt_are_admitted():
    assert require_hf_admission(ENTRY, JOB, ENTRY["id"]) is None


@pytest.mark.parametrize("change", [
    {"agent": "a20"}, {"agent": None}, {"agent": 19},
    {"prompt": PROMPT + " "}, {"prompt": PROMPT.replace("no restart", "restart")},
    {"prompt": None}, {"prompt": PROMPT.encode()}, {"prompt": ""},
])
def test_unmeasured_actor_or_prompt_is_not_a_qualified_case(change):
    denied(ENTRY, {**JOB, **change})


@pytest.mark.parametrize("field", ["agent", "prompt"])
def test_missing_binding_field_fails_closed(field):
    job = {key: value for key, value in JOB.items() if key != field}
    denied(ENTRY, job)


@pytest.mark.parametrize("scope", [
    None, [], {}, "a19", [None], [True],
    [{"agent": "a19"}], [{"prompt_sha256": PIN}],
    [{"agent": "a19", "prompt_sha256": PIN, "extra": True}],
    [{"agent": "a19", "prompt_sha256": PIN.upper()}],
    [{"agent": "a19", "prompt_sha256": "0" * 63}],
    [{"agent": "a19", "prompt_sha256": True}],
    [{"agent": "prime", "prompt_sha256": PIN}],
    [{"agent": "a03", "prompt_sha256": PIN}],
    [{"agent": "a19", "prompt_sha256": PIN}] * 2,
    [{"agent": "a19", "prompt_sha256": PIN}] * 257,
])
def test_malformed_or_nonpermanent_scope_cannot_bypass_safety(scope):
    denied({**ENTRY, "allowed_prompt_bindings": scope}, JOB)


def test_legacy_catalog_without_narrow_scope_remains_unchanged():
    broad = {key: value for key, value in ENTRY.items() if key != "allowed_prompt_bindings"}
    assert require_hf_admission(broad, {**JOB, "agent": "a20"}, broad["id"]) is None


def test_scope_denial_precedes_adapter_and_credential_resolution(monkeypatch, tmp_path):
    monkeypatch.setattr(cloud_execution, "load_catalog", lambda: [deepcopy(ENTRY)])
    monkeypatch.setattr(cloud_execution, "adapter_for", lambda _: pytest.fail("No adapter/secret on scope denial"))
    with pytest.raises(ProviderFailure, match="PROVIDER_UNQUALIFIED"):
        cloud_execution.execute_cloud({**JOB, "agent": "a20"}, SimpleNamespace(name=ENTRY["id"]), tmp_path, lambda: False)


def test_fallback_primary_and_target_each_keep_their_scope():
    primary = {**ENTRY, "fallback_ids": ["hf-alternate"], "hf_fallback_policy": {
        "version": "hf-fallback.v1", "allowed_provider_ids": ["hf-alternate"], "allow_non_hf": False}}
    alternate = {**ENTRY, "id": "hf-alternate"}
    assert require_hf_admission(alternate, JOB, alternate["id"], primary=primary) is None
    for changed, other in (({**primary, "allowed_prompt_bindings": [{"agent": "a20", "prompt_sha256": PIN}]}, alternate),
                           (primary, {**alternate, "allowed_prompt_bindings": [{"agent": "a20", "prompt_sha256": PIN}]})):
        with pytest.raises(ProviderFailure, match="PROVIDER_UNQUALIFIED"):
            require_hf_admission(other, JOB, other["id"], primary=changed)


def test_prepared_fallback_binding_includes_an_independent_scope_copy():
    entry = deepcopy(ENTRY)
    prepared = cloud_execution._dispatch_binding(entry)
    assert prepared["allowed_prompt_bindings"] == entry["allowed_prompt_bindings"]
    entry["allowed_prompt_bindings"][0]["agent"] = "a20"
    assert prepared["allowed_prompt_bindings"][0]["agent"] == "a19"
    assert cloud_execution._dispatch_binding(entry) != prepared
