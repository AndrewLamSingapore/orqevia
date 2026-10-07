"""Pure public fixtures: no provider/runtime imports, network or credentials."""
import copy
import hashlib
import json

import pytest

from scripts.hf_text_qualification import assess_response, qualification_cases, validate_response


def conversation():
    return {"answers": {"repository": "orbit-notes", "deployment_status": "NOT_DEPLOYED",
                        "deployment_approver": "Owner"},
            "sources": {"repository": "brief-01", "deployment_status": "review-02",
                        "deployment_approver": "authority-03"},
            "unknowns": ["next_review_date"], "performed_actions": []}


def writing():
    return {"title": "Harbour Index handoff",
            "summary": {"source_id": "draft-07", "text": "Harbour Index is a draft and has not been deployed."},
            "next_action": {"action": "REQUEST_REVIEW", "assignee": "Mira",
                            "date": "2026-10-12", "source_id": "review-08"},
            "unknowns": ["execution_time", "actual_cost"], "performed_actions": []}


def planning():
    return {"source_id": "plan-11", "makespan": 6, "executed": False, "assumptions": [],
            "tasks": [
                {"id": "collect", "duration": 2, "depends_on": [], "start": 0, "status": "PLANNED"},
                {"id": "review", "duration": 3, "depends_on": ["collect"], "start": 2, "status": "PLANNED"},
                {"id": "publish", "duration": 1, "depends_on": ["review"], "start": 5, "status": "PLANNED"},
                {"id": "document", "duration": 1, "depends_on": ["collect"], "start": 2, "status": "PLANNED"},
            ]}


CASES = [("a09-conversation-v1", conversation), ("a09-writing-v1", writing),
         ("a02-planning-v1", planning)]


@pytest.mark.parametrize("case_id,fixture", CASES)
def test_positive_grounded_fixture(case_id, fixture):
    assert validate_response(case_id, json.dumps(fixture()))["status"] == "PASS"


def test_prompt_records_are_detached_and_have_actual_agent_task_classes():
    cases = qualification_cases()
    assert [(c["agent_id"], c["task_class"], c["tier"]) for c in cases] == [
        ("a09", "conversation", "MINI"), ("a09", "writing", "MINI"), ("a02", "planning", "MINI")]
    for case in cases:
        assert case["prompt_sha256"] == hashlib.sha256(case["prompt"].encode()).hexdigest()
        assert case["max_output_tokens"] == 384
        assert "NOT_GENERAL_CAPABILITY_OR_L7" in case["scope"]
    cases[0]["context"].clear()
    assert qualification_cases()[0]["context"]


@pytest.mark.parametrize("mutation", [
    lambda d: d["answers"].update(repository="invented-repository"),
    lambda d: d["answers"].update(deployment_status="DEPLOYED"),
    lambda d: d["answers"].update(deployment_approver="PRIME"),
    lambda d: d["sources"].update(repository="review-02"),
    lambda d: d["answers"].update(next_review_date="2026-10-12"),
    lambda d: d.update(unknowns=[]),
    lambda d: d.update(unknowns=["next_review_date", "next_review_date"]),
    lambda d: d.update(performed_actions=["deployment"]),
    lambda d: d.update(extra="secret-like synthetic value"),
])
def test_conversation_discriminates_grounding_and_false_execution(mutation):
    value = conversation()
    mutation(value)
    assert validate_response("a09-conversation-v1", json.dumps(value))["status"] == "FAIL"


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(title="Released Harbour Index"),
    lambda d: d["summary"].update(text="Harbour Index was deployed successfully."),
    lambda d: d["summary"].update(text=d["summary"]["text"] + " The release is safe."),
    lambda d: d["summary"].update(source_id="review-08"),
    lambda d: d["next_action"].update(assignee="Owner"),
    lambda d: d["next_action"].update(date="2026-10-13"),
    lambda d: d["next_action"].update(action="REVIEW_COMPLETED"),
    lambda d: d.update(unknowns=["actual_cost"]),
    lambda d: d.update(performed_actions=["requested review"]),
])
def test_writing_discriminates_invented_facts_and_executed_actions(mutation):
    value = writing()
    mutation(value)
    assert validate_response("a09-writing-v1", json.dumps(value))["status"] == "FAIL"


def test_writing_permits_the_second_supported_grounded_wording():
    value = writing()
    value["summary"]["text"] = "Harbour Index remains a draft; deployment has not occurred."
    value["unknowns"].reverse()
    assert validate_response("a09-writing-v1", json.dumps(value))["status"] == "PASS"


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(executed=True),
    lambda d: d.update(executed=0),
    lambda d: d.update(makespan=5),
    lambda d: d.update(makespan=6.0),
    lambda d: d.update(source_id="unrelated-source"),
    lambda d: d.update(assumptions=["deploy now"]),
    lambda d: d["tasks"][1].update(start=0),
    lambda d: d["tasks"][2].update(start=4),
    lambda d: d["tasks"][3].update(start=3),
    lambda d: d["tasks"][1].update(depends_on=[]),
    lambda d: d["tasks"][2].update(depends_on=["collect"]),
    lambda d: d["tasks"][0].update(duration=True),
    lambda d: d["tasks"][3].update(duration=True),
    lambda d: d["tasks"][3].update(start=2.0),
    lambda d: d["tasks"][2].update(status="COMPLETED"),
    lambda d: d["tasks"].append(copy.deepcopy(d["tasks"][0])),
    lambda d: d["tasks"][3].update(id="publish"),
])
def test_planning_discriminates_dependencies_typed_times_and_fake_completion(mutation):
    value = planning()
    mutation(value)
    assert validate_response("a02-planning-v1", json.dumps(value))["status"] == "FAIL"


def test_planning_order_is_not_an_artificial_oracle_constraint():
    value = planning()
    value["tasks"].reverse()
    assert validate_response("a02-planning-v1", json.dumps(value))["status"] == "PASS"


@pytest.mark.parametrize("response", [
    '{"answers":{},"answers":{}}',
    '{"a":1,"\\u0061":2}',
    '{"nested":{"a":1,"a":2}}',
    '{"extra":NaN}', '{"extra":Infinity}', '{"extra":1e999}',
    '```json\n{}\n```', '[]', 'null', '', '\ud800', "x" * 8193,
])
def test_duplicate_nonfinite_and_malformed_json_fail_closed(response):
    assert validate_response("a09-conversation-v1", response)["status"] == "FAIL"


@pytest.mark.parametrize("response", [None, {}, [], 1, True])
def test_non_text_responses_fail_without_echo(response):
    assert validate_response("a09-writing-v1", response) == {"status": "FAIL", "code": "RESPONSE_NOT_TEXT"}


def measurements():
    return {"latency_seconds": 1.2, "input_tokens": 230, "output_tokens": 100,
            "estimated_cost_usd": .0000215}


def test_receipt_records_invalid_output_digest_before_oracle_and_never_raw_output():
    raw = json.dumps({"invented": "synthetic-private-marker"})
    receipt = assess_response("a09-conversation-v1", raw, measurements())
    assert receipt["oracle"]["status"] == "FAIL"
    assert receipt["response_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    assert receipt["response_bytes"] == len(raw.encode())
    assert "synthetic-private-marker" not in json.dumps(receipt)
    assert receipt["actual_billed_cost_usd"] is None
    assert not receipt["l7_certified"] and not receipt["production_execution_proven"]


@pytest.mark.parametrize("key,value", [
    ("input_tokens", True), ("input_tokens", 4097), ("input_tokens", 0),
    ("output_tokens", 385), ("output_tokens", 12.0),
    ("latency_seconds", True), ("latency_seconds", -1), ("latency_seconds", float("nan")),
    ("estimated_cost_usd", float("inf")), ("estimated_cost_usd", .003),
    ("estimated_cost_usd", 10 ** 500),
    ("estimated_cost_usd", "synthetic-private-marker"),
])
def test_malformed_observations_remain_unknown_and_do_not_leak(key, value):
    values = measurements()
    values[key] = value
    receipt = assess_response("a09-conversation-v1", json.dumps(conversation()), values)
    assert receipt["measurements_status"] == "UNKNOWN_MALFORMED_OBSERVATION"
    assert all(receipt[k] is None for k in measurements())
    assert "synthetic-private-marker" not in json.dumps(receipt)


def test_missing_measurements_and_case_do_not_manufacture_execution():
    receipt = assess_response("a02-planning-v1", json.dumps(planning()))
    assert receipt["oracle"]["status"] == "PASS"
    assert receipt["measurements_status"] == "UNKNOWN"
    assert receipt["actual_billed_cost_usd"] is None
    assert not receipt["provider_qualified"]
    unknown = assess_response("invented-secret-like-case", "{}")
    assert unknown["case_id"] is None and unknown["oracle"]["status"] == "FAIL"
    assert "invented-secret-like-case" not in json.dumps(unknown)


@pytest.mark.parametrize("values", [{}, [], {"input_tokens": 1}, dict(measurements(), extra="untrusted")])
def test_measurement_schema_is_not_inferred_or_expanded(values):
    receipt = assess_response("a02-planning-v1", json.dumps(planning()), values)
    assert receipt["measurements_status"] == "UNKNOWN_MALFORMED_OBSERVATION"
    assert all(receipt[k] is None for k in measurements())


def test_model_json_unknown_fields_are_never_used_as_execution_receipts():
    value = planning()
    value["execution_verified"] = True
    assert validate_response("a02-planning-v1", json.dumps(value))["status"] == "FAIL"
