"""Rate-review unit fixtures are not agent certification evidence."""
import json

import pytest

from app.agent_cert_rates import rate_facts, review_rate_json


SOURCE = {"week1_failures": 10, "week1_requests": 100,
          "week2_failures": 15, "week2_requests": 300}
CORRECT = {**SOURCE, "week1_rate": "1/10", "week2_rate": "1/20",
           "failure_count_change": "UP", "failure_rate_change": "DOWN",
           "cause": "UNKNOWN"}


def test_exact_counts_rates_directions_and_unknown_cause():
    assert rate_facts(SOURCE) == CORRECT
    assert review_rate_json(SOURCE, json.dumps(CORRECT)) == (True, ())


def test_held_out_periods_are_computed_not_copied_from_fixture():
    held_out = {"week1_failures": 1, "week1_requests": 4,
                "week2_failures": 2, "week2_requests": 8}
    expected = {**held_out, "week1_rate": "1/4", "week2_rate": "1/4",
                "failure_count_change": "UP", "failure_rate_change": "UNCHANGED",
                "cause": "UNKNOWN"}
    assert rate_facts(held_out) == expected
    assert review_rate_json(held_out, json.dumps(expected)) == (True, ())
    assert not review_rate_json(held_out, json.dumps(CORRECT))[0]


@pytest.mark.parametrize("change,field", [
    ({"week1_rate": "10/100"}, "week1_rate"),
    ({"week2_rate": "15/300"}, "week2_rate"),
    ({"failure_count_change": "DOWN"}, "failure_count_change"),
    ({"failure_rate_change": "UP"}, "failure_rate_change"),
    ({"cause": "Higher volume caused the change"}, "cause"),
    ({"week2_failures": True}, "week2_failures"),
])
def test_rejects_wrong_or_unsupported_claims(change, field):
    valid, errors = review_rate_json(SOURCE, json.dumps({**CORRECT, **change}))
    assert not valid and field in errors


def test_rejects_prose_extra_fields_and_duplicate_decoded_keys():
    assert review_rate_json(SOURCE, "JARVIS: 10% fell to 5%.")[1] == ("not_strict_json",)
    observed_fenced = '```json\n' + json.dumps({**CORRECT, "week1_rate": "10%", "week2_rate": "5%"}) + '\n```'
    assert review_rate_json(SOURCE, observed_fenced)[1] == ("not_strict_json",)
    assert review_rate_json(SOURCE, json.dumps({**CORRECT, "date": "2024-02-29"}))[1] == (
        "field_contract_mismatch",)
    duplicate = json.dumps(CORRECT)[:-1] + ',"cause":"KNOWN"}'
    assert review_rate_json(SOURCE, duplicate)[1] == ("not_strict_json",)


@pytest.mark.parametrize("source", [
    {**SOURCE, "week1_requests": 0},
    {**SOURCE, "week2_failures": 301},
    {**SOURCE, "week1_failures": True},
    {**SOURCE, "unexpected": 1},
])
def test_invalid_source_fails_closed(source):
    with pytest.raises(ValueError):
        rate_facts(source)
