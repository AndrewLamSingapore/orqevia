import json

from app.agent_cert_a17_boundary import review_a17_boundary_json, review_a17_cross_review_json
from scripts.a18_heldout_cloud_probe import EXPECTED_ERRORS, FLAWED


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
