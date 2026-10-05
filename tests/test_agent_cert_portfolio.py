"""A05's exact one-slot decision rejects false capacity and certainty claims."""
import json

import pytest

from app.agent_cert_portfolio import portfolio_facts, review_portfolio_json


SOURCE = {"available_slots": 1, "p_slots": 1, "q_slots": 1,
          "p_expected_value": 8, "q_expected_value": 5}


def test_expected_one_slot_decision_is_derived_from_source():
    expected = {**SOURCE, "selected_project": "P", "selected_slots": 1,
                "selected_expected_value": 8, "values_are_estimates": True,
                "both_feasible_together": False}
    assert portfolio_facts(SOURCE) == expected
    assert review_portfolio_json(SOURCE, json.dumps(expected)) == (True, ())
    for key, wrong in (("selected_project", "Q"), ("selected_slots", 2),
                       ("selected_expected_value", 13),
                       ("values_are_estimates", False),
                       ("both_feasible_together", True)):
        passed, errors = review_portfolio_json(SOURCE, json.dumps({**expected, key: wrong}))
        assert not passed and key in errors


def test_duplicate_keys_extra_claims_and_boolean_integer_fail_closed():
    expected = portfolio_facts(SOURCE)
    assert review_portfolio_json(SOURCE, '{"selected_project":"P","selected_project":"Q"}') == (
        False, ("not_strict_json",))
    assert review_portfolio_json(SOURCE, json.dumps({**expected, "guaranteed_outcome": True})) == (
        False, ("field_contract_mismatch",))
    assert review_portfolio_json(SOURCE, json.dumps({**expected, "available_slots": True})) == (
        False, ("available_slots",))


def test_source_variants_and_invalid_sources():
    q_leads = {**SOURCE, "q_expected_value": 9}
    assert portfolio_facts(q_leads)["selected_project"] == "Q"
    for invalid in ({**SOURCE, "available_slots": True},
                    {**SOURCE, "q_slots": 2},
                    {**SOURCE, "available_slots": 2},
                    {**SOURCE, "q_expected_value": 8},
                    {**SOURCE, "unknown": 1}):
        with pytest.raises(ValueError):
            portfolio_facts(invalid)
