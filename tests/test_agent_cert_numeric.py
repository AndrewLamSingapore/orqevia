"""Discriminating arithmetic review; these unit tests are not agent evidence."""
import json

import pytest

from app.agent_cert_numeric import priority_facts, review_priority_json


SOURCE = {
    "capacity_days": 3, "alpha_days": 3, "alpha_total_points": 8,
    "beta_days": 2, "beta_total_points": 6,
}
CORRECT = {
    "alpha_total_points": 8, "beta_total_points": 6,
    "alpha_points_per_day": "8/3", "beta_points_per_day": "3/1",
    "higher_efficiency_project": "Beta", "higher_total_project": "Alpha",
    "chosen_project_under_three_day_limit": "Alpha",
    "beta_total_points_needed_to_reverse_choice": 9,
}


def test_exact_priority_facts_and_valid_structured_answer():
    facts = priority_facts(SOURCE)
    assert facts["higher_total_project"] == "Alpha"
    assert facts["higher_efficiency_project"] == "Beta"
    assert review_priority_json(SOURCE, json.dumps(CORRECT)) == (True, ())


@pytest.mark.parametrize("changes,missing", [
    ({"alpha_total_points": 24, "beta_total_points": 12}, "alpha_total_points"),
    ({"higher_efficiency_project": "Alpha"}, "higher_efficiency_project"),
    ({"beta_total_points_needed_to_reverse_choice": 8}, "beta_total_points_needed_to_reverse_choice"),
    ({"alpha_points_per_day": "2.67"}, "alpha_points_per_day"),
])
def test_rejects_observed_error_classes(changes, missing):
    answer = {**CORRECT, **changes}
    valid, errors = review_priority_json(SOURCE, json.dumps(answer))
    assert not valid and missing in errors


def test_fails_closed_on_prose_invalid_json_and_extra_fields():
    assert review_priority_json(SOURCE, "JARVIS: Alpha is more efficient.")[1] == ("not_strict_json",)
    assert review_priority_json(SOURCE, '{"alpha_points_per_day": 8 / 3}')[1] == ("not_strict_json",)
    assert review_priority_json(SOURCE, json.dumps({**CORRECT, "certified": True}))[1] == ("field_contract_mismatch",)


@pytest.mark.parametrize("bad", [
    {**SOURCE, "capacity_days": True},
    {**SOURCE, "capacity_days": 4},
    {**SOURCE, "alpha_days": 0},
    {**SOURCE, "beta_days": 4},
    {**SOURCE, "unexpected": 1},
])
def test_bad_source_is_not_silently_repaired(bad):
    with pytest.raises(ValueError):
        priority_facts(bad)
