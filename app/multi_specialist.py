"""Bounded multi-specialist reasoning with one parent trace."""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .model_gateway import ModelGateway
from .settings import SETTINGS

SPECIALISTS = ("research", "data", "engineering", "strategy", "economic", "quality")
DEEP_SPECIALISTS = {"strategy", "economic", "quality"}


class MultiSpecialistRuntime:
    def __init__(self, gateway: ModelGateway | None = None, workers: int | None = None):
        self.gateway = gateway or ModelGateway()
        self.workers = max(1, min(6, workers or SETTINGS.multi_specialist_workers))

    def run(self, *, intent: str, context: str = "", evidence: str = "", deep: bool = False) -> dict[str, Any]:
        task_id = str(uuid.uuid4())
        base = f"Intent: {intent}\nContext: {context[:6000]}\nEvidence: {evidence[:12000]}\n"

        def one(role: str):
            prompt = base + f"\nAct as the {role} specialist. Produce bounded analysis, assumptions, evidence gaps, risks and recommendations. Do not claim actions were executed."
            use_deep = deep or role in DEEP_SPECIALISTS
            return role, self.gateway.local(prompt=prompt, deep=use_deep, task_id=task_id, stage=f"specialist:{role}").as_dict()

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
        critique = self.gateway.local(prompt=base + "\nSPECIALIST OUTPUTS:\n" + joined[:24000] + "\n\nAct as adversarial critic. Identify contradictions, unsupported claims, missing evidence and failure modes.", deep=True, task_id=task_id, stage="specialist_critique").as_dict()
        synthesis = self.gateway.local(prompt=base + "\nSPECIALIST OUTPUTS:\n" + joined[:22000] + "\nCRITIQUE:\n" + critique.get("text", "")[:8000] + "\n\nSynthesize the strongest evidence-bounded answer. Preserve disagreement and uncertainty. External actions remain proposals only.", deep=True, task_id=task_id, stage="specialist_synthesis").as_dict()
        return {"task_id": task_id, "workers": self.workers, "specialists": outputs, "failures": failures, "critic": critique, "synthesis": synthesis, "executed_external_action": False}
