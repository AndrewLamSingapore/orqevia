"""Pure, public-context MINI text oracles; this module never invokes a model.

These cases qualify only the named bounded transformations.  In particular,
structured handoff writing is not unrestricted prose-quality certification.
Admission, price/usage reservation, agent authorization, provider identity,
execution provenance and real inference remain the existing runtime's duties.
An oracle PASS is neither provider admission, production acceptance nor L7.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any


SCOPE = "BOUNDED_PROVIDED_CONTEXT_TEXT_ONLY_NOT_GENERAL_CAPABILITY_OR_L7"
MAX_RESPONSE_BYTES = 8192
_CASES = {
    "a09-conversation-v1": {
        "agent_id": "a09", "task_class": "conversation", "tier": "MINI",
        "context": [
            {"source_id": "brief-01", "fact": "The Orbit Notes prototype repository is orbit-notes."},
            {"source_id": "review-02", "fact": "The prototype was reviewed but was not deployed."},
            {"source_id": "authority-03", "fact": "Only the Owner can approve deployment; no approval is recorded."},
        ],
        "instruction": (
            "Answer from the provided context only: repository name, deployment status, "
            "deployment approver, and next_review_date. Return one JSON object with exactly "
            "answers {repository, deployment_status, deployment_approver}, sources with the "
            "same three keys (each value the supporting source_id), unknowns (a list of "
            "unanswerable field names), and performed_actions (a list). Use NOT_DEPLOYED "
            "for an explicitly undeployed prototype. Do not invent dates, approval or execution."
        ),
    },
    "a09-writing-v1": {
        "agent_id": "a09", "task_class": "writing", "tier": "MINI",
        "context": [
            {"source_id": "draft-07", "fact": "Project Harbour Index is a draft. It has not been deployed."},
            {"source_id": "review-08", "fact": "The next action is to request review from Mira on 2026-10-12."},
            {"source_id": "boundary-09", "fact": "No execution time or actual cost is recorded. No action was performed."},
        ],
        "instruction": (
            "Write a concise structured handoff from the supplied facts, not an execution report. "
            "Return exactly title, summary, next_action, unknowns, performed_actions. "
            "Title: '<project> handoff'. Summary: one object with source_id and text. "
            "Use one of these grounded sentence templates, filling only supplied project/status: "
            "'<project> is a draft and has not been deployed.' or "
            "'<project> remains a draft; deployment has not occurred.'. "
            "next_action: {action: REQUEST_REVIEW, assignee, date, source_id}. "
            "unknowns: the unrecorded execution_time and actual_cost field names; performed_actions: a list. "
            "No extra facts, prose or claims. This is bounded handoff writing, not general writing."
        ),
    },
    "a02-planning-v1": {
        "agent_id": "a02", "task_class": "planning", "tier": "MINI",
        "context": {
            "source_id": "plan-11", "workers": 2,
            "tasks": [
                {"id": "collect", "duration": 2, "depends_on": []},
                {"id": "review", "duration": 3, "depends_on": ["collect"]},
                {"id": "publish", "duration": 1, "depends_on": ["review"]},
                {"id": "document", "duration": 1, "depends_on": ["collect"]},
            ],
        },
        "instruction": (
            "Plan, do not execute. Units are abstract time units and tasks cannot be split. "
            "There are two interchangeable workers. Compute the earliest-start dependency-safe "
            "plan minimizing makespan. Return exactly tasks, makespan, source_id, executed, "
            "assumptions. Each task must have exactly id, duration, depends_on, start, status "
            "(PLANNED). Preserve all source tasks and dependencies. executed is a boolean; "
            "assumptions is a list. Do not claim any action was performed."
        ),
    },
}


def qualification_cases() -> list[dict[str, Any]]:
    """Detached prompts and admission suggestions, not execution oracles/results."""
    cases = []
    for case_id, case in _CASES.items():
        public = copy.deepcopy(case)
        public.update(case_id=case_id, scope=SCOPE, max_output_tokens=384)
        public["prompt"] = case["instruction"] + "\nProvided context:\n" + json.dumps(
            case["context"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        public["prompt_sha256"] = _sha(public["prompt"].encode("utf-8"))
        cases.append(public)
    return cases


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


def _reject_constant(_: str) -> None:
    raise ValueError("nonfinite constant")


def _float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("nonfinite number")
    return number


def _keys(value: Any, names: set[str]) -> bool:
    return type(value) is dict and set(value) == names


def _string_set(value: Any, expected: set[str]) -> bool:
    return (type(value) is list and all(type(item) is str for item in value)
            and len(value) == len(expected) and set(value) == expected)


def _conversation(value: dict[str, Any]) -> bool:
    expected_answers = {"repository": "orbit-notes", "deployment_status": "NOT_DEPLOYED",
                        "deployment_approver": "Owner"}
    expected_sources = {"repository": "brief-01", "deployment_status": "review-02",
                        "deployment_approver": "authority-03"}
    return (_keys(value, {"answers", "sources", "unknowns", "performed_actions"})
            and value["answers"] == expected_answers and value["sources"] == expected_sources
            and _string_set(value["unknowns"], {"next_review_date"})
            and type(value["performed_actions"]) is list and not value["performed_actions"])


def _writing(value: dict[str, Any]) -> bool:
    if not _keys(value, {"title", "summary", "next_action", "unknowns", "performed_actions"}):
        return False
    summary = value["summary"]
    return (value["title"] == "Harbour Index handoff"
            and _keys(summary, {"source_id", "text"}) and summary["source_id"] == "draft-07"
            and summary["text"] in {
                "Harbour Index is a draft and has not been deployed.",
                "Harbour Index remains a draft; deployment has not occurred."}
            and value["next_action"] == {"action": "REQUEST_REVIEW", "assignee": "Mira",
                                        "date": "2026-10-12", "source_id": "review-08"}
            and _string_set(value["unknowns"], {"execution_time", "actual_cost"})
            and type(value["performed_actions"]) is list and not value["performed_actions"])


def _planning(value: dict[str, Any]) -> bool:
    if not _keys(value, {"tasks", "makespan", "source_id", "executed", "assumptions"}):
        return False
    if (value["source_id"] != "plan-11" or value["executed"] is not False
            or type(value["assumptions"]) is not list or value["assumptions"]
            or type(value["makespan"]) is not int):
        return False
    rows = value["tasks"]
    if type(rows) is not list or len(rows) != 4:
        return False
    plan = {}
    source = _CASES["a02-planning-v1"]["context"]
    definitions = {task["id"]: task for task in source["tasks"]}
    for task in rows:
        if not _keys(task, {"id", "duration", "depends_on", "start", "status"}):
            return False
        task_id = task["id"]
        if type(task_id) is not str or task_id not in definitions or task_id in plan:
            return False
        original = definitions[task_id]
        if (type(task["duration"]) is not int or task["duration"] != original["duration"]
                or type(task["start"]) is not int or task["start"] < 0 or task["start"] > 32
                or task["status"] != "PLANNED"
                or not _string_set(task["depends_on"], set(original["depends_on"]))):
            return False
        plan[task_id] = task
    # Derive earliest times from authoritative input rather than trust the model's makespan.
    earliest: dict[str, int] = {}
    for task in source["tasks"]:
        start = max((earliest[parent] + definitions[parent]["duration"]
                     for parent in task["depends_on"]), default=0)
        earliest[task["id"]] = start
        if plan[task["id"]]["start"] != start:
            return False
    makespan = max(task["start"] + task["duration"] for task in plan.values())
    if makespan != value["makespan"]:
        return False
    return all(sum(task["start"] <= unit < task["start"] + task["duration"]
                   for task in plan.values()) <= source["workers"] for unit in range(makespan))


def validate_response(case_id: str, response: Any) -> dict[str, Any]:
    """Fixed-code oracle result with no raw text/errors echoed to receipts."""
    if type(case_id) is not str or case_id not in _CASES:
        return {"status": "FAIL", "code": "UNKNOWN_CASE"}
    if type(response) is not str:
        return {"status": "FAIL", "code": "RESPONSE_NOT_TEXT"}
    if not response or len(response) > MAX_RESPONSE_BYTES:
        return {"status": "FAIL", "code": "RESPONSE_SIZE_INVALID"}
    try:
        raw = response.encode("utf-8", errors="strict")
        if not raw or len(raw) > MAX_RESPONSE_BYTES:
            return {"status": "FAIL", "code": "RESPONSE_SIZE_INVALID"}
        value = json.loads(response, object_pairs_hook=_object, parse_constant=_reject_constant,
                           parse_float=_float)
    except (ValueError, UnicodeError, RecursionError, TypeError):
        return {"status": "FAIL", "code": "RESPONSE_JSON_INVALID"}
    validator = {"a09-conversation-v1": _conversation, "a09-writing-v1": _writing,
                 "a02-planning-v1": _planning}[case_id]
    # Ill-typed JSON containers are rejected rather than exported as error text.
    try:
        valid = type(value) is dict and validator(value)
    except (TypeError, ValueError, KeyError):
        valid = False
    return {"status": "PASS" if valid else "FAIL",
            "code": "BOUNDED_ORACLE_MATCH" if valid else "GROUNDING_OR_SCHEMA_MISMATCH"}


def assess_response(case_id: str, response: Any, measurements: Any = None) -> dict[str, Any]:
    """Redacted observations. Usage/cost are caller-observed, not billing proof.

    Measurements are optional and independent of output correctness.  Missing or
    malformed observations remain UNKNOWN; they must not become a performance
    or budget PASS.  Governance still validates actual usage and caps externally.
    """
    observation = {"schema": "jarvis.hf-text-qualification.v1", "scope": SCOPE,
                   "case_id": case_id if type(case_id) is str and case_id in _CASES else None,
                   "oracle": validate_response(case_id, response), "response_bytes": None,
                   "response_sha256": None, "measurements_status": "UNKNOWN",
                   "latency_seconds": None, "input_tokens": None, "output_tokens": None,
                   "estimated_cost_usd": None, "actual_billed_cost_usd": None,
                   "l7_certified": False, "provider_qualified": False,
                   "production_execution_proven": False}
    try:
        raw = (response.encode("utf-8", errors="strict") if type(response) is str
               and len(response) <= MAX_RESPONSE_BYTES else None)
        if raw is not None and len(raw) <= MAX_RESPONSE_BYTES:
            observation.update(response_bytes=len(raw), response_sha256=_sha(raw))
    except UnicodeError:
        pass
    if measurements is None:
        return observation
    fields = {"latency_seconds", "input_tokens", "output_tokens", "estimated_cost_usd"}
    valid = _keys(measurements, fields)
    if valid:
        for key, limit in (("latency_seconds", 300), ("estimated_cost_usd", .002)):
            number = measurements[key]
            valid &= type(number) in (int, float) and 0 <= number <= limit and math.isfinite(number)
        for key, limit in (("input_tokens", 4096), ("output_tokens", 384)):
            valid &= type(measurements[key]) is int and 0 < measurements[key] <= limit
    if valid:
        observation.update(measurements)
        observation["measurements_status"] = "CALLER_OBSERVATION_NOT_INDEPENDENTLY_VERIFIED"
    else:
        observation["measurements_status"] = "UNKNOWN_MALFORMED_OBSERVATION"
    return observation
