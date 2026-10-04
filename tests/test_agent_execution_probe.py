"""No network, model, production state, or certification authority in these tests."""
from app.agent_execution_probe import baseline_plan, observe_baseline_execution

JOB_ID = "11111111-1111-4111-8111-111111111111"


def test_plan_is_one_owned_case_per_registered_specialist():
    plan = baseline_plan()
    assert len(plan) == 21
    assert len({item["agent_id"] for item in plan}) == 21
    assert all(item["case"] == "baseline:identity" for item in plan)


def test_completed_worker_observation_is_redacted_and_not_certification():
    captured = {}

    def dispatch(request):
        captured.update(request)
        return {"capability": request["capability"], "job": {"id": JOB_ID, "agent": "a17"}}

    def get_job(_job_id):
        marker = captured["objective"].rsplit(" ", 1)[1]
        return {"id": JOB_ID, "agent": "a17", "status": "completed",
                "prompt": captured["objective"],
                "started_at": "2026-10-04T00:00:00Z", "completed_at": "2026-10-04T00:00:01Z",
                "provider": "ollama-fast", "attempts": 1, "result": marker, "error": None}

    observed = observe_baseline_execution("a17", "responsibility.a17",
                                          dispatch=dispatch, get_job=get_job)
    assert observed["state"] == "EXECUTED"
    assert observed["challenge_returned"] is True
    assert observed["certification"] == "UNVERIFIED"
    assert captured["data_classification"] == "LOCAL_ONLY"
    assert captured["max_cost_usd"] == 0
    assert "result" not in observed and "objective" not in observed
    assert captured["objective"].rsplit(" ", 1)[1] not in str(observed)


def test_queued_job_does_not_claim_execution_or_certification():
    captured = {}
    clock = iter([0, 0, 0.2, 0.6, 1.1])

    def dispatch(request):
        captured.update(request)
        return {"capability": request["capability"], "job": {"id": JOB_ID, "agent": "a17"}}

    observed = observe_baseline_execution(
        "a17", "responsibility.a17", timeout_seconds=1,
        dispatch=dispatch,
        get_job=lambda _job_id: {"id": JOB_ID, "agent": "a17", "status": "queued",
                                 "prompt": captured["objective"]},
        monotonic=lambda: next(clock), pause=lambda _: None)
    assert observed["state"] == "INCOMPLETE"
    assert observed["certification"] == "UNVERIFIED"


def test_forged_route_and_workerless_completion_fail_closed():
    wrong = observe_baseline_execution(
        "a17", "responsibility.a17",
        dispatch=lambda request: {"capability": request["capability"],
                                  "job": {"id": JOB_ID, "agent": "a18"}},
        get_job=lambda _: {})
    assert wrong["state"] == "REJECTED"
    captured = {}

    def dispatch(request):
        captured.update(request)
        return {"capability": request["capability"], "job": {"id": JOB_ID, "agent": "a17"}}

    no_worker = observe_baseline_execution(
        "a17", "responsibility.a17",
        dispatch=dispatch,
        get_job=lambda _: {"id": JOB_ID, "agent": "a17", "status": "completed",
                           "prompt": captured["objective"],
                           "result": "fixture answer"})
    assert no_worker["state"] == "REJECTED"
    assert no_worker["certification"] == "UNVERIFIED"


def test_unrelated_job_or_untrusted_provider_cannot_be_execution_evidence():
    captured = {}

    def dispatch(request):
        captured.update(request)
        return {"capability": request["capability"], "job": {"id": JOB_ID, "agent": "a17"}}

    unrelated = observe_baseline_execution(
        "a17", "responsibility.a17", dispatch=dispatch,
        get_job=lambda _: {"id": JOB_ID, "agent": "a17", "status": "completed",
                           "prompt": "a different job"})
    assert (unrelated["state"], unrelated["reason"]) == ("REJECTED", "job_prompt_mismatch")

    malformed_provider = observe_baseline_execution(
        "a17", "responsibility.a17", dispatch=dispatch,
        get_job=lambda _: {"id": JOB_ID, "agent": "a17", "status": "completed",
                           "prompt": captured["objective"], "result": "canary",
                           "started_at": "2026-10-04T00:00:00Z",
                           "completed_at": "2026-10-04T00:00:01Z", "attempts": 1,
                           "provider": "Bearer secret raw provider"})
    assert malformed_provider["state"] == "REJECTED"
    assert "secret" not in str(malformed_provider)


def test_failure_and_dependency_errors_do_not_leak_raw_text():
    def leaked_error(_):
        raise RuntimeError("Bearer secret raw provider response")

    observed = observe_baseline_execution(
        "a17", "responsibility.a17", dispatch=leaked_error, get_job=lambda _: {})
    assert observed["state"] == "INCOMPLETE"
    assert "secret" not in str(observed)
    captured = {}

    def dispatch(request):
        captured.update(request)
        return {"capability": request["capability"], "job": {"id": JOB_ID, "agent": "a17"}}

    failed = observe_baseline_execution(
        "a17", "responsibility.a17",
        dispatch=dispatch,
        get_job=lambda _: {"id": JOB_ID, "agent": "a17", "status": "failed",
                           "prompt": captured["objective"],
                           "error": "secret raw model output"})
    assert failed["state"] == "FAILED"
    assert "secret" not in str(failed)


def test_unowned_capability_rejected_before_dispatch():
    invoked = []
    try:
        observe_baseline_execution("a17", "responsibility.a18",
                                   dispatch=lambda _: invoked.append(1), get_job=lambda _: {})
    except ValueError:
        pass
    else:
        assert False, "unowned capability was accepted"
    assert invoked == []
