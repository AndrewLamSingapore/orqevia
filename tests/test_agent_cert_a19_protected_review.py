"""Synthetic offline checks only; these fixtures are not A19 certification."""
import hashlib
import json
from copy import deepcopy

import pytest

from app.agent_cert_a19_protected_review import review_a19_role_receipt
from app.agent_cert_role_group_two import role_case


SOURCE = "a" * 40
JOB = "11111111-1111-4111-8111-111111111111"
CORRELATION = "22222222-2222-4222-8222-222222222222"
RESULT = ('{"initial_check_pass":false,"retry_check_pass":true,'
          '"continuous_health_proven":false,"restart_authorized":false,'
          '"latest_check_time":"10:01Z","next_read_only_check":"sample_trend"}')


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
        "profile_sha256": "c" * 64,
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
    return review_a19_role_receipt(raw, source_revision=SOURCE,
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
        review_a19_role_receipt(raw, source_revision=SOURCE, trusted_run=_trusted(raw))
    with pytest.raises(ValueError, match="bounded"):
        review_a19_role_receipt(b"x" * (1024 * 1024 + 1), source_revision=SOURCE,
                                trusted_run=_trusted(b"x" * (1024 * 1024 + 1)))
