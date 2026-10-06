"""Source-only checks for off-host receipt binding; no model or host load."""
import hashlib

from scripts.run_a18_offhost_observation import _verify_lineage


JOB_ID = "11111111-1111-4111-8111-111111111111"
CORRELATION_ID = "22222222-2222-4222-8222-222222222222"
RAW = '{"accept_control":true,"accept_mutated":false}'


def _sample():
    observation = {"job_id": JOB_ID, "state": "EXECUTED",
                   "case_review": "ARTIFACT_CHECK_PASS",
                   "result_sha256": hashlib.sha256(RAW.encode()).hexdigest()}
    job = {"id": JOB_ID, "agent": "a18", "status": "completed",
           "attempts": 1, "allow_cloud": False, "provider": "ollama-fast",
           "result": RAW}
    events = [{"task_id": task_id, "agent_id": "a18",
               "action_type": action_type, "phase": phase,
               "success": True if phase == "completed" else None}
              for task_id, action_type in ((JOB_ID, "inference.run"),
                                           (CORRELATION_ID, "inference.enqueue"))
              for phase in ("started", "completed")]
    return observation, job, events


def test_a18_offhost_lineage_requires_same_job_queue_result_and_both_ledger_actions():
    observation, job, events = _sample()
    assert _verify_lineage(observation, job, events, CORRELATION_ID) == (True, ())
    assert not _verify_lineage(observation, {**job, "id": "other"}, events,
                               CORRELATION_ID)[0]
    assert not _verify_lineage(observation, {**job, "result": "forged"}, events,
                               CORRELATION_ID)[0]
    assert not _verify_lineage(observation, {**job, "allow_cloud": True}, events,
                               CORRELATION_ID)[0]
    assert not _verify_lineage(observation, {**job, "attempts": 2}, events,
                               CORRELATION_ID)[0]
    assert not _verify_lineage(observation, job, events[:-1], CORRELATION_ID)[0]
    assert not _verify_lineage({**observation, "case_review": "ARTIFACT_CHECK_FAIL"},
                               job, events, CORRELATION_ID)[0]


def test_a18_offhost_lineage_rejects_cross_job_ledger_and_missing_correlation():
    observation, job, events = _sample()
    substituted = [{**row, "task_id": "different-job"}
                   if row["action_type"] == "inference.run" else row for row in events]
    assert not _verify_lineage(observation, job, substituted, CORRELATION_ID)[0]
    assert not _verify_lineage(observation, job, events, None)[0]
