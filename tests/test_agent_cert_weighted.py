"""The a04 role oracle checks arithmetic and ties without certifying a worker."""

import json

import pytest

from app.agent_cert_weighted import review_weighted_json, weighted_facts


SOURCE = {"reliability_weight": 2, "speed_weight": 1,
          "a_reliability": 4, "a_speed": 1,
          "b_reliability": 2, "b_speed": 5}


def test_equal_weighted_scores_require_unresolved_tie():
    expected = {**SOURCE, "a_score": 9, "b_score": 9,
                "decision": "TIE", "missing_tie_breaker": True}
    assert weighted_facts(SOURCE) == expected
    assert review_weighted_json(SOURCE, json.dumps(expected)) == (True, ())
    for wrong in ({**expected, "decision": "A"},
                  {**expected, "missing_tie_breaker": False},
                  {**expected, "b_score": 8}):
        passed, errors = review_weighted_json(SOURCE, json.dumps(wrong))
        assert not passed and errors


def test_duplicate_key_and_extra_claim_fail_closed():
    assert review_weighted_json(SOURCE, '{"decision":"TIE","decision":"A"}') == (
        False, ("not_strict_json",))
    assert review_weighted_json(SOURCE, json.dumps({**weighted_facts(SOURCE),
                                                    "winner_reason": "invented"})) == (
        False, ("field_contract_mismatch",))


@pytest.mark.parametrize("changed", [{**SOURCE, "reliability_weight": True},
                                      {**SOURCE, "speed_weight": 0, "reliability_weight": 0},
                                      {**SOURCE, "a_speed": -1}])
def test_invalid_source_is_not_reviewed(changed):
    with pytest.raises(ValueError):
        weighted_facts(changed)
