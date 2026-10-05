"""Independent adversarial cases for the numeric reviewer, not agent evidence."""
import json

import pytest

from app.agent_cert_numeric import priority_facts, review_priority_json

SOURCE = {"capacity_days": 3, "alpha_days": 3, "alpha_total_points": 8,
          "beta_days": 2, "beta_total_points": 6}
ANSWER = {"alpha_total_points": 8, "beta_total_points": 6,
          "alpha_points_per_day": "8/3", "beta_points_per_day": "3/1",
          "higher_efficiency_project": "Beta", "higher_total_project": "Alpha",
          "chosen_project_under_three_day_limit": "Alpha",
          "beta_total_points_needed_to_reverse_choice": 9}


@pytest.mark.parametrize("first", ['"Alpha"', '"Beta"', 'NaN'])
def test_duplicate_comparison_is_rejected_even_if_last_value_is_correct(first):
    response = '{"higher_efficiency_project":' + first + ',' + json.dumps(ANSWER)[1:]
    assert review_priority_json(SOURCE, response) == (False, ("not_strict_json",))


def test_escaped_duplicate_name_cannot_hide_a_contradiction():
    response = '{"higher_efficiency_\\u0070roject":"Alpha",' + json.dumps(ANSWER)[1:]
    assert review_priority_json(SOURCE, response) == (False, ("not_strict_json",))


@pytest.mark.parametrize("days", [(1, 1), (1, 2), (2, 1)])
def test_oracle_rejects_sources_where_both_indivisible_projects_fit(days):
    # Both positive-value projects fit. A one-project answer cannot represent
    # the total-value optimum; reject this unsupported exercise instead.
    with pytest.raises(ValueError, match="one project"):
        priority_facts({**SOURCE, "alpha_days": days[0], "beta_days": days[1]})


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_json_constants_fail_closed(literal):
    response = json.dumps(ANSWER).replace('"alpha_total_points": 8',
                                        '"alpha_total_points": ' + literal)
    assert not review_priority_json(SOURCE, response)[0]


def test_bounded_deep_json_does_not_crash_the_reviewer():
    response = '[' * 1500 + '0' + ']' * 1500
    assert len(response) < 4096
    assert not review_priority_json(SOURCE, response)[0]
