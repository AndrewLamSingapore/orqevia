"""Offline A26 runner checks; no model, GitHub, Azure, or certification call."""
import hashlib
import json

import pytest

from app.agent_cert_a19_a26_review import (
    EXPECTED_A26_RESULT, a26_review_prompt, a26_review_result,
)
from scripts import run_a26_a19_observation as runner
from tests.test_agent_cert_a19_protected_review import (
    PROFILE, SOURCE, _a26_receipt, _payload, _raw, _trusted,
)


def _prepared(execution=None, *, source=SOURCE, trusted=None, reviewer="a26",
              review_run="67890"):
    raw = _raw(execution or _payload())
    return runner.reviewed_input(
        raw, PROFILE, trusted_run=trusted or _trusted(raw),
        source_revision=source, review_run_id=review_run,
        reviewer_agent_id=reviewer)


def test_prepare_binds_distinct_registered_a26_to_exact_passing_a19_bytes():
    execution = _payload()
    raw = _raw(execution)
    item = _prepared(execution)
    assert item["reviewer_agent_id"] == "a26"
    assert item["subject_agent_id"] == "a19"
    assert item["source_revision"] == SOURCE
    assert item["execution_receipt_sha256"] == hashlib.sha256(raw).hexdigest()
    assert item["case_spec_sha256"] == execution["case_spec_sha256"]
    assert item["result_sha256"] == execution["observation"]["result_sha256"]
    assert item["request"]["capability"] == "responsibility.a26"
    assert item["request"]["data_classification"] == "LOCAL_ONLY"
    assert item["request"]["max_cost_usd"] == 0
    assert item["certification"] == "UNVERIFIED"


@pytest.mark.parametrize("reviewer,review_run", [("a19", "67890"),
                                                 ("a26", "12345")])
def test_prepare_rejects_self_review_or_reused_a19_run(reviewer, review_run):
    with pytest.raises(ValueError):
        _prepared(reviewer=reviewer, review_run=review_run)


def test_prepare_rejects_mismatched_source_sha_and_unprotected_provenance():
    execution = _payload()
    raw = _raw(execution)
    with pytest.raises(ValueError):
        _prepared(execution, source="b" * 40)
    with pytest.raises(ValueError):
        _prepared(execution, trusted={**_trusted(raw), "head_sha": "b" * 40})
    with pytest.raises(ValueError):
        _prepared(execution, trusted={**_trusted(raw), "ref_protected": False})


@pytest.mark.parametrize("wrong_time", ["10:00Z", "2023-10-05T10:01Z"])
def test_failed_a19_oracle_rejected_before_a26_dispatch_even_with_matching_hashes(wrong_time):
    execution = _payload()
    answer = json.loads(execution["queue_job"]["result"])
    answer["latest_check_time"] = wrong_time
    result = json.dumps(answer, separators=(",", ":"))
    execution["queue_job"]["result"] = result
    execution["observation"]["result_sha256"] = hashlib.sha256(result.encode()).hexdigest()
    with pytest.raises(ValueError, match="independent A19 role oracle"):
        _prepared(execution)


def test_a26_result_requires_field_level_review_not_a_pass_label():
    assert a26_review_result(json.dumps(EXPECTED_A26_RESULT))
    for result in (
        '{"decision":"PASS"}',
        json.dumps({**EXPECTED_A26_RESULT, "latest_check_time": "10:00Z"}),
        json.dumps({**EXPECTED_A26_RESULT, "restart_not_authorized": False}),
        json.dumps({**EXPECTED_A26_RESULT, "restart_not_authorized": 1}),
        json.dumps({**EXPECTED_A26_RESULT, "certification_awarded": True}),
        '{"decision":"PASS","decision":"FAIL"}',
    ):
        assert not a26_review_result(result)


def test_review_prompt_matches_actual_registered_dispatch_prompt():
    from app.agent_dispatch_api import AgentRequest, inference_prompt
    from app.tier_router import Tier

    request = _prepared()["request"]
    assert a26_review_prompt(request) == inference_prompt(AgentRequest(**request), Tier.MINI)
    assert len(a26_review_prompt(request).encode()) <= 2048 - 256


def test_runner_lineage_requires_distinct_job_and_prompt_bound_enqueue():
    execution = _payload()
    raw = _raw(execution)
    prepared = _prepared(execution)
    a26 = _a26_receipt(raw)
    job, events = a26["queue_job"], a26["action_events"]
    observed = {
        "state": "EXECUTED", "agent_id": "a26",
        "capability_id": "responsibility.a26", "certification": "UNVERIFIED",
        "job_id": job["id"],
        "result_sha256": hashlib.sha256(job["result"].encode()).hexdigest(),
    }
    assert runner._lineage(observed, job, events, a26["correlation_id"],
                           execution["observation"]["job_id"], prepared["request"])
    assert not runner._lineage(observed, job, events, a26["correlation_id"],
                               job["id"], prepared["request"])
    tampered = [dict(event) for event in events]
    tampered[2] = {**tampered[2], "parameters_summary": {"prompt_sha256": "0" * 64}}
    assert not runner._lineage(observed, job, tampered, a26["correlation_id"],
                               execution["observation"]["job_id"], prepared["request"])


def test_workflow_preflight_requires_protected_main_and_distinct_run(monkeypatch):
    values = {
        "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": runner.REPOSITORY,
        "GITHUB_REF": "refs/heads/main", "GITHUB_REF_PROTECTED": "true",
        "GITHUB_EVENT_NAME": "workflow_dispatch", "PRIME_A26_WORKFLOW_REF": runner.WORKFLOW_REF,
        "GITHUB_SHA": SOURCE, "GITHUB_RUN_ID": "67890",
        "PRIME_A19_RUN_ID": "12345", "PRIME_A19_ARTIFACT_ID": "111",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    assert runner.preflight() == (SOURCE, "67890", "12345", "111")
    for key, value in (("GITHUB_REF", "refs/heads/feature"),
                       ("GITHUB_REF_PROTECTED", "false"),
                       ("GITHUB_SHA", "not-a-sha"),
                       ("PRIME_A19_RUN_ID", "67890")):
        monkeypatch.setenv(key, value)
        with pytest.raises(ValueError):
            runner.preflight()
        monkeypatch.setenv(key, values[key])
