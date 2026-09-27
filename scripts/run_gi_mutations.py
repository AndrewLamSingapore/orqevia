"""Bounded consequential mutations for general/context reasoning controls."""
from __future__ import annotations
import importlib.util,json,sys,tempfile
from pathlib import Path

MUTATIONS={
 "allow_fact_without_evidence":('if self.kind == ClaimKind.FACT and not self.evidence_ids:','if False and self.kind == ClaimKind.FACT and not self.evidence_ids:'),
 "allow_reasoning_authority":('if self.grants_authority:','if False and self.grants_authority:'),
 "cross_scope_context":('if c.scope in {scope, "GLOBAL"}','if True'),
 "prediction_as_current":('if state.temporal != TemporalState.CURRENT or not state.evidence_ids: continue','if not state.evidence_ids: continue'),
 "correlation_as_cause":('required={"temporal_order","mechanism","intervention","confounders_addressed"}','required={"temporal_order"}'),
 "ignore_stale_assumption":('if missing or stale: return PlanResult','if missing: return PlanResult'),
 "store_one_shot_lesson":('if len(rows)<3: reasons.append("insufficient_repetition")','if False and len(rows)<3: reasons.append("insufficient_repetition")'),
 "accept_affirming_consequent":('if requested_rule in invalid:\n        return DeductionResult(None, False, premise_evidence, requested_rule, (invalid[requested_rule],))','if requested_rule in invalid:\n        return DeductionResult(consequent, True, premise_evidence, requested_rule)'),
}

def caught(m,name):
 try:
  if name=="allow_fact_without_evidence":m.Claim("x","x",m.ClaimKind.FACT,"x");return True
  if name=="allow_reasoning_authority":m.Claim("x","x",m.ClaimKind.OBSERVATION,"x",grants_authority=True);return True
 except ValueError:return False
 if name=="cross_scope_context":return bool(m.reconstruct_context("x","B",[m.Claim("x","x",m.ClaimKind.OBSERVATION,"x",scope="A")],now=1).selected)
 if name=="prediction_as_current":return bool(m.current_world([m.WorldState("x","x",1,m.TemporalState.PREDICTED,1,("e",))]))
 if name=="correlation_as_cause":return m.assess_causality(temporal_order=True,correlation=True).status!="CAUSAL_UNKNOWN"
 if name=="ignore_stale_assumption":return m.plan_steps([m.PlanStep("x",assumptions=("fresh",))],set()).disposition!="VERIFY_REQUIRED"
 if name=="store_one_shot_lesson":return m.evaluate_lesson("x",[True],provenance=("e",),counterexample_checked=True).disposition!="HYPOTHESIS_ONLY"
 if name=="accept_affirming_consequent":return m.deduce(antecedent="a",consequent="b",requested_rule="affirming_consequent").valid
 return False

def run(root):
 source=(root/'app/general_intelligence.py').read_text(encoding='utf-8');rows=[]
 with tempfile.TemporaryDirectory(prefix='prime-gi-mutations-') as d:
  for name,(old,new) in MUTATIONS.items():
   if source.count(old)!=1:rows.append({'mutation':name,'detected':False,'error':'anchor'});continue
   path=Path(d)/f'{name}.py';path.write_text(source.replace(old,new),encoding='utf-8')
   spec=importlib.util.spec_from_file_location(f'gi_mutation_{name}',path);module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
   rows.append({'mutation':name,'detected':caught(module,name)})
 detected=sum(r['detected'] for r in rows);return {'introduced':len(rows),'detected':detected,'survived':len(rows)-detected,'rows':rows,'passed':detected==len(rows)}

if __name__=='__main__':
 r=run(Path(__file__).resolve().parents[1]);print(json.dumps(r,indent=2,sort_keys=True));raise SystemExit(0 if r['passed'] else 1)
