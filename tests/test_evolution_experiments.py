"""Independent acceptance for fixed bounded experiment execution and evidence."""

from dataclasses import replace
import json

import pytest

from app import evolution_experiments as experiments


def test_frozen_oracle_and_disjoint_withheld_inputs():
    hashes = experiments._validate_suite()
    assert len(hashes["development"]) == 6
    assert len(hashes["held_out"]) == 8
    assert not hashes["development"] & hashes["held_out"]
    # This hand-calculated held-out example catches prioritizing a future job
    # before an already-ready background job, without invoking either solver.
    case = next(case for case in experiments._CASES if case.name == "future_priority_cannot_idle")
    expected = case.answer()
    assert (expected["La_start"], expected["Lc_start"], expected["Lb_start"]) == (0, 5, 8)


def test_candidate_cannot_receive_or_modify_expected_outputs():
    case = experiments._CASES[0]
    inputs = case.inputs()
    assert set(inputs[0]) == {"name", "arrival", "duration", "priority_class"}
    inputs[0]["arrival"] = 99999
    assert case.inputs()[0]["arrival"] == 0
    assert case.answer()["Da_start"] == 0


def test_changed_evaluator_is_rejected_before_candidates(monkeypatch):
    modified = replace(experiments._CASES[0], expected=(("Da", 0, 999, 0),))
    monkeypatch.setattr(experiments, "_CASES", (modified, *experiments._CASES[1:]))
    with pytest.raises(ValueError, match="integrity"):
        experiments.run_experiment()


def test_judge_rejects_floats_booleans_and_missing_fields():
    expected = {"a_start": 0, "waiting_consumes_execution_budget": False}
    assert experiments._judge(dict(expected), expected)
    assert not experiments._judge({"a_start": False, "waiting_consumes_execution_budget": False}, expected)
    assert not experiments._judge({"a_start": 0.0, "waiting_consumes_execution_budget": False}, expected)
    assert not experiments._judge({"a_start": 0}, expected)


def test_execution_validator_rejects_overlap_early_start_and_wait_budget():
    inputs = [
        {"name": "a", "arrival": 0, "duration": 3, "priority_class": "background"},
        {"name": "b", "arrival": 1, "duration": 2, "priority_class": "interactive"},
    ]
    overlapping = {
        "a_start": 0,
        "a_finish": 3,
        "a_wait": 0,
        "b_start": 1,
        "b_finish": 3,
        "b_wait": 0,
        "waiting_consumes_execution_budget": False,
    }
    assert not experiments._valid_execution(overlapping, inputs)
    early = {**overlapping, "b_start": 0, "b_finish": 2, "b_wait": -1}
    assert not experiments._valid_execution(early, inputs)
    budget = {**overlapping, "waiting_consumes_execution_budget": True}
    assert not experiments._valid_execution(budget, inputs)


def test_fixed_comparison_retains_only_confirmed_synthetic_improvement(tmp_path):
    result = experiments.run_experiment(tmp_path)
    assert result["production_policy_changed"] is False
    assert result["network_calls"] == result["model_calls"] == result["financial_actions"] == 0
    assert result["selection"]["status"] == "RETAIN_EXPERIMENTAL_METHOD"
    assert result["selection"]["candidate"] == "existing_exact_tool"
    assert result["selection"]["additional_correct_held_out_cases_vs_fifo"] > 0
    held = {item["candidate"]: item for item in result["held_out"]}
    assert held["existing_exact_tool"]["correct_cases"] == 8
    assert held["release_aware_priority_heap"]["correct_cases"] == 8
    assert held["arrival_fifo"]["correct_cases"] < 8
    for item in result["development"] + result["held_out"]:
        assert len(item["candidate_cpu_ns_samples"]) == 3
        assert all(sample >= 0 for sample in item["candidate_cpu_ns_samples"])
        assert item["coordination"]["candidate_calls_per_workload"] == 1
        assert item["useful_completed_jobs"] <= item["attempted_jobs"]
    stored = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert experiments._digest({key: value for key, value in stored.items() if key != "run_id"}) == stored["run_id"]
    assert stored["records"][-1]["parents"] == [stored["records"][-2]["record_id"]]
    for record in stored["records"]:
        assert (
            experiments._digest({key: value for key, value in record.items() if key != "record_id"})
            == record["record_id"]
        )
    before = next(tmp_path.glob("*.json")).read_bytes()
    with pytest.raises(FileExistsError):
        experiments._persist(tmp_path, stored)
    assert next(tmp_path.glob("*.json")).read_bytes() == before


def test_heldout_failure_cannot_be_reselected_to_another_winner(monkeypatch):
    original = experiments._exact_tool
    held_names = {case.jobs[0][0] for case in experiments._CASES if case.split == "held_out"}

    def overfitting_candidate(jobs):
        answer = original(jobs)
        if jobs[0]["name"] in held_names:
            answer["waiting_consumes_execution_budget"] = True
        return answer

    monkeypatch.setattr(
        experiments,
        "_CANDIDATES",
        (
            experiments._CANDIDATES[0],
            experiments._CANDIDATES[1],
            ("existing_exact_tool", overfitting_candidate, 0, "Controlled held-out regression"),
        ),
    )
    result = experiments.run_experiment()
    assert result["selection"]["status"] == "REJECT_NO_VERIFIED_GAIN"
    assert result["selection"]["candidate"] is None
