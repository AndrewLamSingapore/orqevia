"""A14's source-bound row oracle rejects plausible but false answers."""
import json

import pytest

from app.agent_cert_data_quality import data_quality_facts, review_data_quality_json


ROWS = [{"id": 1, "amount": 5}, {"id": 1, "amount": 5},
        {"id": 2, "amount": -3}]


def test_duplicate_and_negative_findings_are_derived_from_source():
    answer = {"duplicate_ids": [1], "negative_amount_ids": [2],
              "duplicate_row_indices": [1], "negative_amount_row_indices": [2],
              "source_mutated": False, "validation": "FAIL"}
    assert data_quality_facts(ROWS) == answer
    assert review_data_quality_json(ROWS, json.dumps(answer)) == (True, ())
    for key, wrong in (("duplicate_ids", []), ("negative_amount_ids", []),
                       ("duplicate_row_indices", [0]),
                       ("negative_amount_row_indices", [1]),
                       ("source_mutated", True), ("validation", "PASS")):
        passed, errors = review_data_quality_json(ROWS, json.dumps({**answer, key: wrong}))
        assert not passed and key in errors


def test_duplicate_json_keys_extra_claims_and_bool_ids_fail_closed():
    assert review_data_quality_json(ROWS, '{"validation":"FAIL","validation":"PASS"}') == (
        False, ("not_strict_json",))
    assert review_data_quality_json(ROWS, json.dumps({**data_quality_facts(ROWS),
                                                     "auto_repaired": True})) == (
        False, ("field_contract_mismatch",))
    wrong = {**data_quality_facts(ROWS), "duplicate_ids": [True]}
    assert review_data_quality_json(ROWS, json.dumps(wrong)) == (
        False, ("duplicate_ids",))


def test_clean_source_passes_and_invalid_source_is_rejected():
    clean = [{"id": 1, "amount": 0}, {"id": 2, "amount": 5}]
    assert data_quality_facts(clean)["validation"] == "PASS"
    for invalid in ([], [{"id": True, "amount": 5}], [{"id": 1, "amount": False}],
                    [{"id": 1, "amount": 5, "unexpected": 1}]):
        with pytest.raises(ValueError):
            data_quality_facts(invalid)
