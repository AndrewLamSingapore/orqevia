"""Source-only receipt binding checks; no local inference or host load."""
import hashlib
import json

from app.agent_cert_role_group_two import role_case
from scripts.run_a19_offhost_observation import _case_digest, _verify_lineage


JOB_ID = "11111111-1111-4111-8111-111111111111"
CORRELATION_ID = "22222222-2222-4222-8222-222222222222"
RAW = ('{"initial_check_pass":false,"retry_check_pass":true,'
       '"continuous_health_proven":false,"restart_authorized":false,'
       '"latest_check_time":"10:01Z","next_read_only_check":"sample_trend"}')


def _sample():
    spec = role_case("a19")
    observation = {
        "agent_id": "a19", "capability_id": "responsibility.a19",
        "case": "role:normal", "job_id": JOB_ID, "state": "EXECUTED",
        "certification": "UNVERIFIED", "oracle_id": "group_two_exact_role_oracle/v1",
        "case_spec_sha256": _case_digest(spec),
        "case_review": "ROLE_CHECK_PASS",
        "result_sha256": hashlib.sha256(RAW.encode()).hexdigest(),
    }
    job = {"id": JOB_ID, "agent": "a19", "status": "completed",
           "attempts": 1, "allow_cloud": False, "provider": "ollama-deep",
           "result": RAW}
    events = [{"task_id": task_id, "agent_id": "a19",
               "action_type": action_type, "phase": phase,
               "success": True if phase == "completed" else None}
              for task_id, action_type in ((JOB_ID, "inference.run"),
                                           (CORRELATION_ID, "inference.enqueue"))
              for phase in ("started", "completed")]
    return spec, observation, job, events


def test_offhost_a19_role_case_binds_exact_spec_job_result_and_actions():
    spec, observed, job, events = _sample()
    assert _case_digest(spec) == hashlib.sha256(json.dumps(
        spec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert _verify_lineage(spec, observed, job, events, CORRELATION_ID) == (True, ())
    assert not _verify_lineage(spec, {**observed, "case_spec_sha256": "0" * 64},
                               job, events, CORRELATION_ID)[0]
    assert not _verify_lineage(spec, {**observed, "oracle_id": "unreviewed"},
                               job, events, CORRELATION_ID)[0]
    assert not _verify_lineage(spec, observed, {**job, "agent": "a18"},
                               events, CORRELATION_ID)[0]
    assert not _verify_lineage(spec, observed, {**job, "result": "forged"},
                               events, CORRELATION_ID)[0]
    assert not _verify_lineage(spec, observed, {**job, "allow_cloud": True},
                               events, CORRELATION_ID)[0]
    assert not _verify_lineage(spec, observed, {**job, "attempts": 2},
                               events, CORRELATION_ID)[0]
    assert not _verify_lineage(spec, observed, job, events[:-1],
                               CORRELATION_ID)[0]


def test_offhost_a19_lineage_does_not_infer_oracle_pass_or_certification():
    spec, observed, job, events = _sample()
    failed_role = {**observed, "case_review": "ROLE_CHECK_FAIL"}
    assert _verify_lineage(spec, failed_role, job, events, CORRELATION_ID) == (True, ())
    assert not _verify_lineage(spec, {**observed, "certification": "L7"},
                               job, events, CORRELATION_ID)[0]
    assert not _verify_lineage(spec, observed, job, events, None)[0]
    cross_job = [{**row, "task_id": "other"}
                 if row["action_type"] == "inference.run" else row for row in events]
    assert not _verify_lineage(spec, observed, job, cross_job, CORRELATION_ID)[0]
