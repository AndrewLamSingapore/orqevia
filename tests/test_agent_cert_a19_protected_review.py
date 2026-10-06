"""Synthetic offline checks only; these fixtures are not A19 certification."""
import hashlib
import json
from copy import deepcopy

import pytest

from app.agent_cert_a19_protected_review import review_a19_role_receipt
from app.agent_cert_a19_a26_review import (
    REVIEW_TEST_VERSION, build_a19_a26_review_artifact,
)
from app.agent_cert_role_group_two import role_case
from scripts import run_a19_protected_review_job as protected_job


SOURCE = "a" * 40
JOB = "11111111-1111-4111-8111-111111111111"
CORRELATION = "22222222-2222-4222-8222-222222222222"
RESULT = ('{"initial_check_pass":false,"retry_check_pass":true,'
          '"continuous_health_proven":false,"restart_authorized":false,'
          '"latest_check_time":"10:01Z","next_read_only_check":"sample_trend"}')
PROFILE = (json.dumps({"models": {"qwen3:1.7b": {"digest": "b" * 64}}},
                      sort_keys=True) + "\n").encode()


def _payload():
    spec = role_case("a19")
    case_digest = hashlib.sha256(json.dumps(spec, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()
    events = [{"task_id": task, "agent_id": "a19", "action_type": action,
               "phase": phase, "success": phase == "completed"}
              for task, action in ((JOB, "inference.run"),
                                   (CORRELATION, "inference.enqueue"))
              for phase in ("started", "completed")]
    return {
        "schema": "prime.a19.offhost-role-normal-observation.v1",
        "captured_at": "2026-10-06T05:00:02+00:00",
        "source_revision": SOURCE,
        "github_run_id": "12345", "github_run_attempt": "1",
        "model": "qwen3:1.7b", "model_digest": "b" * 64,
        "profile_sha256": hashlib.sha256(PROFILE).hexdigest(),
        "case": "role:normal", "challenge": spec,
        "case_spec_sha256": case_digest,
        "observation": {
            "agent_id": "a19", "capability_id": "responsibility.a19",
            "case": "role:normal", "state": "EXECUTED", "job_id": JOB,
            "certification": "UNVERIFIED", "oracle_id": "group_two_exact_role_oracle/v1",
            "case_spec_sha256": case_digest, "case_review": "ROLE_CHECK_PASS",
            "review_errors": [], "result_sha256": hashlib.sha256(RESULT.encode()).hexdigest(),
        },
        "correlation_id": CORRELATION,
        "queue_job": {
            "id": JOB, "agent": "a19", "status": "completed",
            "provider": "ollama-deep", "allow_cloud": False, "attempts": 1,
            "result": RESULT, "started_at": "2026-10-06T05:00:00+00:00",
            "completed_at": "2026-10-06T05:00:01+00:00",
        },
        "action_events": events, "lineage_pass": True, "lineage_errors": [],
        "role_review_pass": True, "certification": "UNVERIFIED",
        "scope": "off-host execution; not certification",
    }


def _raw(item):
    return (json.dumps(item, sort_keys=True, indent=2) + "\n").encode()


def _trusted(raw):
    return {
        "repository": "AndrewLamSingapore/prime", "repository_id": "1345668764",
        "workflow_ref": "AndrewLamSingapore/prime/.github/workflows/a19-offhost-role.yml@refs/heads/main",
        "ref": "refs/heads/main", "ref_protected": True,
        "event_name": "workflow_dispatch", "head_sha": SOURCE,
        "run_id": "12345", "run_attempt": "1", "conclusion": "success",
        "artifact_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _review(item, *, provenance=None):
    raw = _raw(item)
    return review_a19_role_receipt(raw, profile_raw=PROFILE, source_revision=SOURCE,
                                   trusted_run=provenance or _trusted(raw))


def test_exact_protected_main_receipt_recomputes_role_and_lineage():
    item = _payload()
    result = _review(item)
    assert result["execution_receipt_sha256"] == hashlib.sha256(_raw(item)).hexdigest()
    assert result["case_spec_sha256"] == item["case_spec_sha256"]
    assert result["result_sha256"] == item["observation"]["result_sha256"]
    assert result["oracle_id"] == "group_two_exact_role_oracle/v1"


@pytest.mark.parametrize("change", [
    {"ref": "refs/heads/feat/prime-a19-offhost-role-20261006"},
    {"ref_protected": False},
    {"event_name": "push"},
    {"head_sha": "d" * 40},
    {"workflow_ref": "AndrewLamSingapore/prime/.github/workflows/a19-offhost-role.yml@refs/heads/feature"},
    {"conclusion": "failure"},
    {"artifact_sha256": "0" * 64},
])
def test_feature_or_untrusted_run_cannot_reach_review(change):
    item = _payload()
    provenance = {**_trusted(_raw(item)), **change}
    with pytest.raises(ValueError, match="protected main run"):
        _review(item, provenance=provenance)


@pytest.mark.parametrize("mutate", [
    lambda item: item.update(source_revision="d" * 40),
    lambda item: item.update(certification="L7"),
    lambda item: item.update(role_review_pass=False),
    lambda item: item.update(model="qwen2.5:1.5b"),
    lambda item: item["observation"].update(case_review="ROLE_CHECK_FAIL"),
    lambda item: item["observation"].update(result_sha256="0" * 64),
    lambda item: item["queue_job"].update(result="forged"),
    lambda item: item["queue_job"].update(agent="a18"),
    lambda item: item["queue_job"].update(allow_cloud=True),
    lambda item: item["queue_job"].update(provider="ollama-fast"),
    lambda item: item["queue_job"].update(attempts=2),
    lambda item: item["queue_job"].update(completed_at="2026-10-06T05:00:03+00:00"),
    lambda item: item["observation"].update(oracle_id="self-asserted"),
    lambda item: item["action_events"].pop(),
    lambda item: item["action_events"][1].update(success=False),
    lambda item: item["challenge"]["request"].update(objective="different case"),
])
def test_claimed_pass_does_not_survive_independent_tamper_checks(mutate):
    item = deepcopy(_payload())
    mutate(item)
    with pytest.raises(ValueError):
        _review(item)


def test_duplicate_json_fields_and_oversize_are_rejected():
    raw = _raw(_payload()).replace(b'"schema": ', b'"schema": "forged", "schema": ', 1)
    with pytest.raises(ValueError, match="duplicate"):
        review_a19_role_receipt(raw, profile_raw=PROFILE, source_revision=SOURCE, trusted_run=_trusted(raw))
    with pytest.raises(ValueError, match="bounded"):
        review_a19_role_receipt(b"x" * (1024 * 1024 + 1), profile_raw=PROFILE, source_revision=SOURCE,
                                trusted_run=_trusted(b"x" * (1024 * 1024 + 1)))


def test_missing_or_tampered_measured_profile_is_rejected():
    item = _payload()
    raw = _raw(item)
    with pytest.raises(ValueError, match="measured model profile"):
        review_a19_role_receipt(raw, profile_raw=b"{}", source_revision=SOURCE,
                                trusted_run=_trusted(raw))
    wrong = PROFILE.replace(b"qwen3:1.7b", b"qwen2.5:1.5b")
    with pytest.raises(ValueError, match="measured model profile"):
        review_a19_role_receipt(raw, profile_raw=wrong, source_revision=SOURCE,
                                trusted_run=_trusted(raw))


def _a26_receipt(execution_raw):
    checked = review_a19_role_receipt(
        execution_raw, profile_raw=PROFILE, source_revision=SOURCE,
        trusted_run=_trusted(execution_raw))
    job_id = "33333333-3333-4333-8333-333333333333"
    correlation = "44444444-4444-4444-8444-444444444444"
    decision = {"decision": "PASS",
                "execution_receipt_sha256": checked["execution_receipt_sha256"],
                "case_spec_sha256": checked["case_spec_sha256"],
                "result_sha256": checked["result_sha256"]}
    events = [{"task_id": task, "agent_id": "a26", "action_type": action,
               "phase": phase, "success": phase == "completed"}
              for task, action in ((job_id, "inference.run"),
                                   (correlation, "inference.enqueue"))
              for phase in ("started", "completed")]
    return {"schema": "prime.a26.a19-role-review.v1",
            "source_revision": SOURCE, "github_run_id": "67890",
            "github_run_attempt": "1", "reviewed_at": "2026-10-06T05:02:02+00:00",
            "reviewer_agent_id": "a26", "subject_agent_id": "a19",
            "case": "role:normal", "certification": "UNVERIFIED",
            "execution_receipt_sha256": checked["execution_receipt_sha256"],
            "case_spec_sha256": checked["case_spec_sha256"],
            "result_sha256": checked["result_sha256"], "decision": "PASS",
            "queue_job": {"id": job_id, "agent": "a26", "status": "completed",
                          "provider": "ollama-deep", "allow_cloud": False,
                          "attempts": 1, "result": json.dumps(decision),
                          "started_at": "2026-10-06T05:02:00+00:00",
                          "completed_at": "2026-10-06T05:02:01+00:00"},
            "correlation_id": correlation, "action_events": events}


def _trusted_a26(raw):
    return {**_trusted(raw),
            "workflow_ref": "AndrewLamSingapore/prime/.github/workflows/a26-a19-observation.yml@refs/heads/main",
            "run_id": "67890", "artifact_sha256": hashlib.sha256(raw).hexdigest()}


def _build_review(execution, a26, *, a26_run=None):
    execution_raw, a26_raw = _raw(execution), _raw(a26)
    return build_a19_a26_review_artifact(
        execution_raw, PROFILE, a26_raw, source_revision=SOURCE,
        review_run_id="99999",
        trusted_execution_run=_trusted(execution_raw),
        trusted_a26_run=a26_run or _trusted_a26(a26_raw))


def test_distinct_protected_a26_execution_produces_unsigned_review_envelope():
    execution = _payload()
    a26 = _a26_receipt(_raw(execution))
    review = json.loads(_build_review(execution, a26))
    assert review["schema_version"] == "prime.agent-certification.review.v1"
    assert review["reviewer_identity"] == "a26"
    assert review["review_run_id"] == "99999"
    assert review["execution_evidence_sha256"] == hashlib.sha256(_raw(execution)).hexdigest()
    assert review["review_test_version"] == REVIEW_TEST_VERSION
    assert review["observations"]["a26_run_id"] == "67890"
    assert "attestation" not in review and "certification" not in review


@pytest.mark.parametrize("mutate", [
    lambda item: item.update(reviewer_agent_id="a19"),
    lambda item: item.update(decision="FAIL"),
    lambda item: item.update(execution_receipt_sha256="0" * 64),
    lambda item: item["queue_job"].update(agent="a19"),
    lambda item: item["queue_job"].update(status="LOCAL_EXECUTION_FAILED"),
    lambda item: item["queue_job"].update(result='{"decision":"PASS"}'),
    lambda item: item["action_events"].pop(),
    lambda item: item["action_events"][1].update(success=False),
])
def test_a26_label_or_claim_cannot_replace_independent_execution(mutate):
    execution = _payload()
    a26 = _a26_receipt(_raw(execution))
    mutate(a26)
    with pytest.raises(ValueError):
        _build_review(execution, a26)


@pytest.mark.parametrize("change", [
    {"ref": "refs/heads/feature"},
    {"ref_protected": False},
    {"workflow_ref": "AndrewLamSingapore/prime/.github/workflows/a19-offhost-role.yml@refs/heads/main"},
    {"run_id": "12345"},
    {"head_sha": "d" * 40},
    {"artifact_sha256": "0" * 64},
])
def test_a26_provenance_must_be_distinct_protected_main(change):
    execution = _payload()
    a26 = _a26_receipt(_raw(execution))
    raw = _raw(a26)
    with pytest.raises(ValueError, match="protected independent A26"):
        _build_review(execution, a26, a26_run={**_trusted_a26(raw), **change})


def test_failed_a19_oracle_cannot_be_laundered_by_a26_pass():
    execution = _payload()
    a26 = _a26_receipt(_raw(execution))
    execution["queue_job"]["result"] = "invented"
    with pytest.raises(ValueError):
        _build_review(execution, a26)


def _job_environment(monkeypatch, tmp_path):
    values = {
        "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "AndrewLamSingapore/prime",
        "GITHUB_REF": "refs/heads/main", "GITHUB_REF_PROTECTED": "true",
        "GITHUB_SHA": SOURCE, "GITHUB_RUN_ID": "99999",
        "PRIME_REVIEW_WORKFLOW_REF": protected_job.REVIEW_WORKFLOW,
        "PRIME_A19_RUN_ID": "12345", "PRIME_A19_ARTIFACT_ID": "111",
        "PRIME_A26_RUN_ID": "67890", "PRIME_A26_ARTIFACT_ID": "222",
        "RUNNER_TEMP": str(tmp_path), "GH_TOKEN": "synthetic-test-token",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def _github_metadata(path):
    if path == "branches/main":
        return {"protected": True}
    if path.startswith("actions/runs/"):
        run_id = int(path.rsplit("/", 1)[1])
        workflow = ("a19-offhost-role" if run_id == 12345
                    else "a26-a19-observation")
        return {"repository": {"full_name": "AndrewLamSingapore/prime",
                                "id": protected_job.REPOSITORY_ID},
                "head_repository": {"id": protected_job.REPOSITORY_ID},
                "id": run_id, "head_branch": "main", "head_sha": SOURCE,
                "event": "workflow_dispatch", "conclusion": "success",
                "path": f".github/workflows/{workflow}.yml", "run_attempt": 1}
    artifact_id = int(path.rsplit("/", 1)[1])
    run_id = 12345 if artifact_id == 111 else 67890
    name = (f"a19-offhost-observation-{run_id}" if artifact_id == 111
            else f"a26-a19-observation-{run_id}")
    return {"id": artifact_id, "name": name, "expired": False,
            "size_in_bytes": 1000, "digest": "sha256:" + "a" * 64,
            "workflow_run": {"id": run_id}}


def test_protected_job_emits_only_unsigned_review_after_authenticated_metadata(
        monkeypatch, tmp_path):
    _job_environment(monkeypatch, tmp_path)
    execution = _payload()
    a26 = _a26_receipt(_raw(execution))
    execution_root = tmp_path / "a19-execution"
    execution_root.mkdir()
    (execution_root / "a19-observation.json").write_bytes(_raw(execution))
    (execution_root / "profile.json").write_bytes(PROFILE)
    a26_root = tmp_path / "a26-observation"
    a26_root.mkdir()
    (a26_root / "a26-observation.json").write_bytes(_raw(a26))
    monkeypatch.setattr(protected_job, "_api_json", lambda path, token: _github_metadata(path))
    digest = protected_job.build()
    review = (tmp_path / "a19-review" / "a19-review.json").read_bytes()
    assert digest == hashlib.sha256(review).hexdigest()
    assert json.loads(review)["review_run_id"] == "99999"
    assert "attestation" not in json.loads(review)


def test_unprotected_main_cannot_emit_review(monkeypatch, tmp_path):
    _job_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(protected_job, "_api_json", lambda path, token: {"protected": False})
    with pytest.raises(ValueError, match="main protection"):
        protected_job.build()
    assert not (tmp_path / "a19-review" / "a19-review.json").exists()


@pytest.mark.parametrize("key,value", [
    ("GITHUB_REF", "refs/heads/feature"),
    ("GITHUB_REF_PROTECTED", "false"),
    ("PRIME_REVIEW_WORKFLOW_REF", "forged"),
    ("GITHUB_SHA", "not-a-sha"),
    ("PRIME_A26_RUN_ID", "12345"),
    ("PRIME_A19_ARTIFACT_ID", "not-an-id"),
])
def test_protected_job_refuses_untrusted_invocation(monkeypatch, tmp_path, key, value):
    _job_environment(monkeypatch, tmp_path)
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        protected_job.preflight()


@pytest.mark.parametrize("change", [
    {"head_branch": "feature"},
    {"head_sha": "0" * 40},
    {"conclusion": "failure"},
    {"path": ".github/workflows/other.yml"},
    {"head_repository": {"id": 1}},
])
def test_authenticated_run_metadata_must_match_exact_source(
        monkeypatch, change):
    def fake(path, token):
        item = _github_metadata(path)
        return {**item, **change} if path == "actions/runs/12345" else item
    monkeypatch.setattr(protected_job, "_api_json", fake)
    with pytest.raises(ValueError, match="provenance mismatch"):
        protected_job._trusted_run(
            "12345", "111", workflow="a19-offhost-role",
            artifact_name="a19-offhost-observation-12345", raw=b"receipt",
            source=SOURCE, protected=True, token="synthetic-test-token")


@pytest.mark.parametrize("change", [
    {"id": 999},
    {"name": "other-artifact"},
    {"expired": True},
    {"digest": "not-a-digest"},
    {"workflow_run": {"id": 67890}},
])
def test_authenticated_artifact_metadata_must_match_run(monkeypatch, change):
    def fake(path, token):
        item = _github_metadata(path)
        return {**item, **change} if path == "actions/artifacts/111" else item
    monkeypatch.setattr(protected_job, "_api_json", fake)
    with pytest.raises(ValueError, match="provenance mismatch"):
        protected_job._trusted_run(
            "12345", "111", workflow="a19-offhost-role",
            artifact_name="a19-offhost-observation-12345", raw=b"receipt",
            source=SOURCE, protected=True, token="synthetic-test-token")
