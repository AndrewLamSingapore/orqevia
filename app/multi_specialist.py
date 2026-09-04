"""Bounded multi-specialist reasoning with one governed parent trace."""
from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .agent_runtime import AgentAuthorityRuntime
from .model_gateway import ModelGateway
from .settings import SETTINGS

SPECIALISTS = ("research", "data", "engineering", "strategy", "economic", "quality")
DEEP_SPECIALISTS = {"strategy", "economic", "quality"}


class MultiSpecialistRuntime:
    def __init__(self, gateway: ModelGateway | None = None, workers: int | None = None,
                 authority_runtime: AgentAuthorityRuntime | None = None):
        self.gateway = gateway or ModelGateway()
        self.workers = max(1, min(6, workers or SETTINGS.multi_specialist_workers))
        self.authority_runtime = authority_runtime or AgentAuthorityRuntime()

    def run(self, *, intent: str, context: str = "", evidence: str = "", deep: bool = False) -> dict[str, Any]:
        task_id = str(uuid.uuid4())
        base = f"Intent: {intent}\nContext: {context[:6000]}\nEvidence: {evidence[:12000]}\n"

        def one(role: str):
            path = self.authority_runtime.resolve_path(role, intent)
            self.authority_runtime.begin_path(path, trace_id=task_id, consequential=False)
            agent_id = path[-1]
            prompt = base + f"\nCanonical agent: {agent_id}. Act as the {role} specialist. Produce bounded analysis, assumptions, evidence gaps, risks and recommendations. Do not claim actions were executed."
            use_deep = deep or role in DEEP_SPECIALISTS
            started = time.perf_counter()
            self.authority_runtime.stage(trace_id=task_id, agent_id=agent_id, stage=f"specialist:{role}", status="started")
            try:
                result = self.gateway.local(prompt=prompt, deep=use_deep, task_id=task_id,
                                            stage=f"specialist:{role}").as_dict()
                self.authority_runtime.stage(trace_id=task_id, agent_id=agent_id, stage=f"specialist:{role}",
                                             status="completed", latency_ms=(time.perf_counter()-started)*1000)
                return role, result
            except Exception:
                self.authority_runtime.stage(trace_id=task_id, agent_id=agent_id, stage=f"specialist:{role}",
                                             status="failed", latency_ms=(time.perf_counter()-started)*1000)
                raise

        outputs, failures = {}, {}
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(one, role): role for role in SPECIALISTS}
            for future in as_completed(futures):
                role = futures[future]
                try:
                    name, result = future.result()
                    outputs[name] = result
                except Exception as exc:
                    failures[role] = {"error": type(exc).__name__, "message": str(exc)[:300]}
        if len(outputs) < 2:
            raise RuntimeError("multi-specialist quorum failed")

        joined = "\n\n".join(f"[{role}] {outputs[role].get('text', '')}" for role in SPECIALISTS if role in outputs)

        critique_path = self.authority_runtime.resolve_path("quality", "critic contradiction challenge risk")
        self.authority_runtime.begin_path(critique_path, trace_id=task_id)
        critic_id = critique_path[-1]
        critic_started = time.perf_counter()
        self.authority_runtime.stage(trace_id=task_id, agent_id=critic_id, stage="specialist_critique", status="started")
        critique = self.gateway.local(
            prompt=base + "\nSPECIALIST OUTPUTS:\n" + joined[:24000] + "\n\nAct as adversarial critic. Identify contradictions, unsupported claims, missing evidence and failure modes.",
            deep=True, task_id=task_id, stage="specialist_critique",
        ).as_dict()
        self.authority_runtime.stage(trace_id=task_id, agent_id=critic_id, stage="specialist_critique", status="completed",
                                     latency_ms=(time.perf_counter()-critic_started)*1000)

        synthesis_path = self.authority_runtime.resolve_path("strategy", "decision synthesis strongest answer")
        self.authority_runtime.begin_path(synthesis_path, trace_id=task_id)
        synthesis_id = synthesis_path[-1]
        synthesis_started = time.perf_counter()
        self.authority_runtime.stage(trace_id=task_id, agent_id=synthesis_id, stage="specialist_synthesis", status="started")
        synthesis = self.gateway.local(
            prompt=base + "\nSPECIALIST OUTPUTS:\n" + joined[:22000] + "\nCRITIQUE:\n" + critique.get("text", "")[:8000] + "\n\nSynthesize the strongest evidence-bounded answer. Preserve disagreement and uncertainty. External actions remain proposals only.",
            deep=True, task_id=task_id, stage="specialist_synthesis",
        ).as_dict()
        self.authority_runtime.stage(trace_id=task_id, agent_id=synthesis_id, stage="specialist_synthesis", status="completed",
                                     latency_ms=(time.perf_counter()-synthesis_started)*1000)
        return {"task_id": task_id, "authority_trace_id": task_id, "workers": self.workers,
                "specialists": outputs, "failures": failures, "critic": critique, "synthesis": synthesis,
                "executed_external_action": False}
