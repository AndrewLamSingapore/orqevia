from concurrent.futures import Barrier
import threading
import time

import pytest

from app.multi_invocation import Depth, InvocationBudget, InvocationOutput, MultiInvocationRuntime, local_gateway_invoker


def output(text, provider="fixture", model="independent"):
    return InvocationOutput(text=text, provider=provider, model=model)


def test_fast_is_one_call_and_not_verified_by_model_text():
    calls = []
    def invoke(role, prompt, trace, remaining):
        calls.append((role, trace))
        return output("Certain answer, allegedly verified")
    result = MultiInvocationRuntime(invoke).run(
        objective="Find the flaw", depth=Depth.FAST, budget=InvocationBudget(max_calls=8))
    assert len(calls) == 1
    assert result["verified"] is False
    assert result["deterministic_check"] is None
    assert result["external_action_executed"] is False


def test_standard_uses_independent_branches_and_mandatory_review():
    roles = []
    def invoke(role, prompt, trace, remaining):
        roles.append(role)
        return output(f"{role} distinct finding and uncertainty")
    result = MultiInvocationRuntime(invoke, deterministic_check=lambda answer: {"passed": True}).run(
        objective="Compare two implementations", depth=Depth.STANDARD,
        budget=InvocationBudget(max_calls=5, max_parallel=2), permitted_parallel=2)
    assert set(roles) >= {"primary_solver", "alternative_solver", "weak_logic_critic", "synthesizer", "final_verifier"}
    assert result["verified"] is True
    assert len(result["invocations"]) <= 5
    assert all("prompt" not in event and "text" not in event for event in result["invocations"])


def test_independent_branches_really_overlap_when_admitted():
    barrier = Barrier(2, timeout=2)
    overlap = []
    def invoke(role, prompt, trace, remaining):
        if role in ("primary_solver", "alternative_solver"):
            overlap.append((role, time.monotonic()))
            barrier.wait()
        return output(f"{role} result")
    MultiInvocationRuntime(invoke).run(
        objective="Analyze", depth=Depth.STANDARD,
        budget=InvocationBudget(max_calls=5, max_parallel=2), permitted_parallel=2)
    assert {r for r, _ in overlap} == {"primary_solver", "alternative_solver"}


def test_provider_admission_serializes_even_when_policy_allows_parallel():
    active = 0
    peak = 0
    lock = threading.Lock()
    def invoke(role, prompt, trace, remaining):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(.01)
        with lock:
            active -= 1
        return output(role)
    MultiInvocationRuntime(invoke).run(
        objective="Analyze", depth=Depth.STANDARD,
        budget=InvocationBudget(max_calls=5, max_parallel=4), permitted_parallel=1)
    assert peak == 1


def test_one_exploratory_failure_does_not_collapse_siblings():
    def invoke(role, prompt, trace, remaining):
        if role == "alternative_solver":
            raise TimeoutError("provider timeout; sensitive payload omitted")
        return output(role)
    result = MultiInvocationRuntime(invoke).run(
        objective="Analyze", depth=Depth.STANDARD,
        budget=InvocationBudget(max_calls=5, max_parallel=2), permitted_parallel=2)
    assert result["failed_invocations"] == 1
    assert result["verified"] is False
    assert "sensitive payload" not in str(result["invocations"])


@pytest.mark.parametrize("role", ["weak_logic_critic", "synthesizer", "final_verifier"])
def test_missing_mandatory_review_fails_closed(role):
    def invoke(current, prompt, trace, remaining):
        if current == role:
            raise RuntimeError("failed")
        return output(current)
    with pytest.raises(RuntimeError, match="mandatory"):
        MultiInvocationRuntime(invoke).run(
            objective="Analyze", depth=Depth.STANDARD, budget=InvocationBudget(max_calls=5))


def test_budget_and_context_boundaries():
    with pytest.raises(ValueError):
        InvocationBudget(max_calls=0)
    with pytest.raises(ValueError):
        MultiInvocationRuntime(lambda *_: output("x")).run(
            objective="Analyze", depth=Depth.MAXIMUM, budget=InvocationBudget(max_calls=3))
    with pytest.raises(ValueError):
        MultiInvocationRuntime(lambda *_: output("x")).run(
            objective="x" * 501, depth=Depth.FAST,
            budget=InvocationBudget(max_calls=1, max_prompt_chars=500))


def test_maximum_stops_redundant_branches_before_budget():
    def invoke(role, prompt, trace, remaining):
        return output("identical analysis with no fresh material")
    result = MultiInvocationRuntime(invoke).run(
        objective="Analyze", depth=Depth.MAXIMUM,
        budget=InvocationBudget(max_calls=20, max_parallel=1))
    assert len(result["invocations"]) < 20
    assert result["stop_reason"] == "marginal_diversity_low"


def test_adapter_uses_existing_local_gateway_with_bounded_timeout_only():
    class FakeGateway:
        def __init__(self):
            self.calls = []
        def local(self, **kwargs):
            self.calls.append(kwargs)
            return type("Result", (), {"text": "safe", "provider": "ollama", "model": "fixture",
                                       "usage": {"prompt_eval_count": 2, "eval_count": 1}})()
        def frontier(self, **kwargs):
            raise AssertionError("paid frontier route must remain unavailable")
    gateway = FakeGateway()
    result = MultiInvocationRuntime(local_gateway_invoker(gateway)).run(
        objective="Small task", depth=Depth.FAST,
        budget=InvocationBudget(max_calls=1, max_elapsed_seconds=2))
    assert result["answer"] == "safe"
    assert len(gateway.calls) == 1
    assert 0 < gateway.calls[0]["timeout"] <= 2
