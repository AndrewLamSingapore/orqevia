"""Opt-in, bounded multi-invocation reasoning above governed model admission.

This module does not grant provider, tool, or agent authority. Callers supply an
already-authorized invocation function; each call must pass through the existing
model gateway. Novelty is a scheduling hint, never evidence of correctness.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
import time
import uuid
from typing import Callable


class Depth(str, Enum):
    FAST = "FAST"
    STANDARD = "STANDARD"
    DEEP = "DEEP"
    MAXIMUM = "MAXIMUM"


ROLES = (
    "primary_solver", "alternative_solver", "specialist", "counterexample_generator",
    "fact_checker", "weak_logic_critic", "numerical_verifier", "implementation_reviewer",
)


@dataclass(frozen=True)
class InvocationBudget:
    max_calls: int
    max_parallel: int = 1
    max_elapsed_seconds: float = 180.0
    max_prompt_chars: int = 12000
    max_result_chars: int = 8000

    def __post_init__(self) -> None:
        if not 1 <= self.max_calls <= 64 or not 1 <= self.max_parallel <= 16:
            raise ValueError("invocation count or parallelism outside configured safety bounds")
        if not 1 <= self.max_elapsed_seconds <= 3600:
            raise ValueError("invalid invocation time budget")
        if not 500 <= self.max_prompt_chars <= 100000 or not 500 <= self.max_result_chars <= 100000:
            raise ValueError("invalid context budget")


@dataclass(frozen=True)
class InvocationOutput:
    text: str
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    evidence_ref: str | None = None


Invoke = Callable[[str, str, str, float], InvocationOutput]
DeterministicCheck = Callable[[str], dict[str, object]]


def _features(text: str) -> set[str]:
    """Cheap marginal-diversity hint; cannot establish truth or independence."""
    return set(re.findall(r"[a-z0-9]{5,}", text.casefold()))


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class MultiInvocationRuntime:
    def __init__(self, invoke: Invoke, *, deterministic_check: DeterministicCheck | None = None):
        self.invoke = invoke
        self.deterministic_check = deterministic_check

    def run(self, *, objective: str, depth: Depth, budget: InvocationBudget,
            permitted_parallel: int = 1) -> dict[str, object]:
        if not isinstance(depth, Depth):
            raise ValueError("unknown invocation depth")
        if not objective.strip() or len(objective) > budget.max_prompt_chars:
            raise ValueError("objective missing or exceeds context budget")
        if not 1 <= permitted_parallel <= 16:
            raise ValueError("invalid provider concurrency admission")
        if depth is not Depth.FAST and budget.max_calls < 4:
            raise ValueError("budget cannot reserve critique, synthesis and verification")
        trace_id = str(uuid.uuid4())
        began = time.monotonic()
        ledger: list[dict[str, object]] = []
        outputs: list[tuple[str, str]] = []
        seen: set[str] = set()
        stop_reason = "budget_exhausted"

        def call(role: str, prompt: str) -> tuple[dict[str, object], InvocationOutput | None]:
            invocation_id = str(uuid.uuid4())
            started_at = _utc()
            started = time.monotonic()
            try:
                remaining = budget.max_elapsed_seconds - (started-began)
                if remaining <= 0:
                    raise TimeoutError("invocation time budget exhausted")
                result = self.invoke(role, prompt[:budget.max_prompt_chars], trace_id, remaining)
                if not isinstance(result, InvocationOutput) or not result.text.strip():
                    raise ValueError("empty or invalid invocation response")
                if result.cost_usd is not None and result.cost_usd < 0:
                    raise ValueError("invalid cost")
                record = {"invocation_id": invocation_id, "agent_id": None,
                          "capability": "reasoning.multi_invocation", "role": role, "started_at": started_at,
                          "ended_at": _utc(), "latency_ms": int((time.monotonic()-started)*1000),
                          "provider": result.provider, "model": result.model,
                          "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
                          "cost_usd": result.cost_usd, "evidence_ref": result.evidence_ref,
                          "success": True, "error": None}
                return record, result
            except Exception as exc:
                return {"invocation_id": invocation_id, "agent_id": None,
                        "capability": "reasoning.multi_invocation", "role": role, "started_at": started_at,
                        "ended_at": _utc(), "latency_ms": int((time.monotonic()-started)*1000),
                        "provider": None, "model": None, "input_tokens": None,
                        "output_tokens": None, "cost_usd": None, "evidence_ref": None,
                        "success": False, "error": type(exc).__name__}, None

        def wave(roles: list[str], context: str) -> int:
            nonlocal seen
            gained = 0
            with ThreadPoolExecutor(max_workers=min(budget.max_parallel, permitted_parallel, len(roles))) as pool:
                futures = {pool.submit(call, role, context + "\nRole: " + role.replace("_", " ")): role for role in roles}
                # Preserve role order in the evidence context despite completion order.
                completed = {futures[future]: future.result() for future in as_completed(futures)}
            for role in roles:
                record, result = completed[role]
                ledger.append(record)
                if result is not None:
                    compact = result.text[:budget.max_result_chars]
                    outputs.append((role, compact))
                    terms = _features(compact)
                    gained += len(terms - seen)
                    seen.update(terms)
            return gained

        base = "Objective: " + objective.strip() + "\nReason independently; label assumptions, counterevidence and uncertainty. Never claim an action was executed."
        if depth is Depth.FAST:
            wave(["primary_solver"], base)
            if not outputs:
                raise RuntimeError("single invocation failed")
            final = outputs[-1][1]
            stop_reason = "fast_mode"
        else:
            reserved = 3  # critic, synthesizer, final verifier are mandatory.
            exploratory = budget.max_calls - reserved
            initial = ["primary_solver"]
            if exploratory > 1:
                initial.append("alternative_solver")
            wave(initial, base)
            next_role = 2
            stagnant = 0
            while len(ledger) < exploratory and time.monotonic()-began < budget.max_elapsed_seconds:
                if depth is Depth.STANDARD:
                    stop_reason = "standard_depth"
                    break
                if depth is Depth.DEEP and next_role >= 4:
                    stop_reason = "deep_depth"
                    break
                remaining = exploratory-len(ledger)
                roles = [ROLES[(next_role+i) % len(ROLES)] for i in range(min(remaining, budget.max_parallel, permitted_parallel))]
                next_role += len(roles)
                context = base + "\nPrior distinct findings (not proof):\n" + "\n".join(
                    f"[{role}] {text}" for role, text in outputs[-4:])[:budget.max_prompt_chars//2]
                gained = wave(roles, context)
                stagnant = stagnant+1 if gained < 3 else 0
                if stagnant >= 2:
                    stop_reason = "marginal_diversity_low"
                    break
            if not outputs:
                raise RuntimeError("all exploratory invocations failed")
            compact = "\n".join(f"[{role}] {text}" for role, text in outputs)
            compact = compact[:budget.max_prompt_chars//2]
            critique_record, critique = call("weak_logic_critic", base + "\nFind shared false assumptions, contradictions, unsupported claims and counterexamples:\n" + compact)
            ledger.append(critique_record)
            if critique is None:
                raise RuntimeError("mandatory independent critique failed")
            critique_text = critique.text[:budget.max_result_chars]
            synthesis_record, synthesis = call("synthesizer", base + "\nFindings:\n" + compact + "\nCritique:\n" + critique_text + "\nPreserve dissent and uncertainty; do not majority-vote.")
            ledger.append(synthesis_record)
            if synthesis is None:
                raise RuntimeError("mandatory synthesis failed")
            final = synthesis.text[:budget.max_result_chars]
            verify_record, verification = call("final_verifier", base + "\nProposed answer:\n" + final + "\nCritique:\n" + critique_text + "\nIdentify remaining unsupported claims. Do not assert certification.")
            ledger.append(verify_record)
            if verification is None:
                raise RuntimeError("mandatory final verification failed")
        checked = self.deterministic_check(final) if self.deterministic_check else None
        # A model verifier is advisory; only a deterministic checker can establish a check.
        return {"trace_id": trace_id, "depth": depth.value, "answer": final,
                "critique": critique_text if depth is not Depth.FAST else None,
                "verification_comment": verification.text[:budget.max_result_chars] if depth is not Depth.FAST else None,
                "deterministic_check": checked, "verified": bool(checked and checked.get("passed") is True),
                "invocations": ledger, "stop_reason": stop_reason,
                "failed_invocations": sum(not record["success"] for record in ledger),
                "external_action_executed": False}


def local_gateway_invoker(gateway: object) -> Invoke:
    """Use only the governed local path; no paid/cloud authority is implied.

    ModelGateway.local performs compute and backend admission for *each* call.
    Production opt-in remains separately disabled in the cognitive API.
    """
    def invoke(role: str, prompt: str, trace_id: str, remaining: float) -> InvocationOutput:
        result = gateway.local(prompt=prompt, deep=role not in {"primary_solver", "alternative_solver"},
                               task_id=trace_id, stage=f"multi_invocation:{role}",
                               timeout=min(120.0, remaining))
        return InvocationOutput(text=result.text, provider=result.provider, model=result.model,
                                input_tokens=result.usage.get("prompt_eval_count"),
                                output_tokens=result.usage.get("eval_count"), cost_usd=0.0)
    return invoke
