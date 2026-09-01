"""Parallel multi-specialist reasoning with critique and synthesis."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from .model_gateway import ModelGateway

SPECIALISTS=("research","data","engineering","strategy","economic","quality")

class MultiSpecialistRuntime:
    def __init__(self,gateway:ModelGateway|None=None): self.gateway=gateway or ModelGateway()
    def run(self,*,intent:str,context:str="",evidence:str="",deep:bool=False)->dict[str,Any]:
        base=f"Intent: {intent}\nContext: {context[:6000]}\nEvidence: {evidence[:12000]}\n"
        def one(role:str):
            p=base+f"\nAct as the {role} specialist. Produce bounded analysis, assumptions, evidence gaps, risks and recommendations. Do not claim actions were executed."
            return role,self.gateway.local(prompt=p,deep=deep).as_dict()
        outputs={}
        with ThreadPoolExecutor(max_workers=len(SPECIALISTS)) as pool:
            futures=[pool.submit(one,r) for r in SPECIALISTS]
            for f in as_completed(futures):
                role,result=f.result(); outputs[role]=result
        joined="\n\n".join(f"[{r}] {outputs[r].get('text','')}" for r in SPECIALISTS if r in outputs)
        critique=self.gateway.local(prompt=base+"\nSPECIALIST OUTPUTS:\n"+joined[:24000]+"\n\nAct as adversarial critic. Identify contradictions, unsupported claims, missing evidence and failure modes.",deep=True).as_dict()
        synthesis=self.gateway.local(prompt=base+"\nSPECIALIST OUTPUTS:\n"+joined[:22000]+"\nCRITIQUE:\n"+critique.get('text','')[:8000]+"\n\nSynthesize the strongest evidence-bounded answer. Preserve disagreement and uncertainty. External actions remain proposals only.",deep=True).as_dict()
        return {"specialists":outputs,"critic":critique,"synthesis":synthesis,"executed_external_action":False}
