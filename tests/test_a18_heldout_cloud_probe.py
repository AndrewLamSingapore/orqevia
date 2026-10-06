import json

from app.agent_cert_a17_boundary import review_a17_boundary_json, review_a17_cross_review_json
from scripts.a18_heldout_cloud_probe import EXPECTED_ERRORS, FLAWED, ledger_bound


def test_heldout_defects_are_distinct_and_discriminating():
    flawed = json.dumps(FLAWED, sort_keys=True, separators=(",", ":"))
    valid, errors = review_a17_boundary_json(flawed)
    assert not valid
    assert errors == EXPECTED_ERRORS
    assert errors == ("float_error", "ten_error", "zero_result")
    correct_review = json.dumps({"verdict": "FAIL", "failed_fields": list(errors),
                                 "tests_executed": False})
    assert review_a17_cross_review_json(flawed, correct_review) == (True, ())
    stale_review = json.dumps({"verdict": "FAIL",
                               "failed_fields": ["negative_one_error", "string_error", "type_guard"],
                               "tests_executed": False})
    assert review_a17_cross_review_json(flawed, stale_review)[0] is False


def test_ledger_binding_requires_exact_job_id_and_rejects_reused_attempt():
    good = [("job-1", {"agent_id": "a18", "success": True, "retries": 0})]
    assert ledger_bound(good, "job-1")
    assert not ledger_bound(good, "job-2")
    assert not ledger_bound(good + good, "job-1")
    assert not ledger_bound([("job-1", {**good[0][1], "agent_id": "a19"})], "job-1")
    assert not ledger_bound([("job-1", {**good[0][1], "success": False})], "job-1")
    assert not ledger_bound([("job-1", {**good[0][1], "retries": True})], "job-1")
