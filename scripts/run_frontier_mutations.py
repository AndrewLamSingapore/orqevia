"""Mutation campaign for consequential competence-frontier controls."""
from __future__ import annotations
import importlib.util,json,sys,tempfile
from pathlib import Path
M={
 "master_without_independence":('if independent and held_out and transfer>=5 and retained:','if held_out and transfer>=5 and retained:'),
 "ignore_staleness":('if record.last_verified is None or record.last_verified > now or (record.freshness_seconds is not None and now-record.last_verified > record.freshness_seconds):','if record.last_verified is None:'),
 "skip_transfer_failure":('if level!=expected or not ok:failed=expected;break','if level!=expected:failed=expected;break'),
 "disable_dependency_propagation":('if belief.belief_id not in affected and set(belief.dependencies)&affected:','if False and belief.belief_id not in affected and set(belief.dependencies)&affected:'),
 "allow_objective_drift":('if current.objective!=candidate.objective or candidate.changes_objective:reasons.append("objective_drift")','if False:reasons.append("objective_drift")'),
 "allow_evidence_weakening":('if candidate.weakens_evidence:reasons.append("evidence_weakened")','if False:reasons.append("evidence_weakened")'),
 "allow_missing_acquisition_evidence":('if not episode.evidence_ids:reasons.append("evidence_missing")','if False:reasons.append("evidence_missing")'),
 "compress_different_conditions":('groups.setdefault((lesson.invariant,lesson.conditions),[]).append(lesson.lesson_id)','groups.setdefault((lesson.invariant,()),[]).append(lesson.lesson_id)'),
}
def exposed(m,n):
 s='3'*40
 if n=='master_without_independence':return m.classify_capability(m.CapabilityRecord('x','x',m.CompetenceState.MASTERED,'L',evidence=(m.CapabilityEvidence('e',False,True,5,True,True,s),),last_verified=1),now=1)==m.CompetenceState.MASTERED
 if n=='ignore_staleness':return m.classify_capability(m.CapabilityRecord('x','x',m.CompetenceState.MASTERED,'L',evidence=(m.CapabilityEvidence('e',True,True,5,True,True,s),),last_verified=1,freshness_seconds=1),now=9)==m.CompetenceState.MASTERED
 if n=='skip_transfer_failure':return m.evaluate_transfer([(0,False)]).ceiling==0
 if n=='disable_dependency_propagation':return {x.belief_id:x.status for x in m.invalidate_dependents([m.BeliefNode('a'),m.BeliefNode('b',('a',))],{'a'})}['b']==m.KnowledgeStatus.ACTIVE
 cur=m.InstructionVersion('i','1','x','goal',('e',),True,True,4,'v')
 if n=='allow_objective_drift':return m.evaluate_instruction_rewrite(cur,m.replace(cur,version='2',objective='other',changes_objective=True)).disposition!='REJECT'
 if n=='allow_evidence_weakening':return m.evaluate_instruction_rewrite(cur,m.replace(cur,version='2',weakens_evidence=True)).disposition!='REJECT'
 if n=='allow_missing_acquisition_evidence':return m.verify_acquisition(m.AcquisitionEpisode('x',m.ACQUISITION_SEQUENCE,(),0,1))[0]
 if n=='compress_different_conditions':return bool(m.compress_lessons([m.Lesson('a','x',('a',),('e',)),m.Lesson('b','x',('b',),('e',))]))
def run(root):
 src=(root/'app/competence_frontier.py').read_text(encoding='utf-8');rows=[]
 with tempfile.TemporaryDirectory(prefix='frontier-mut-') as d:
  for n,(old,new) in M.items():
   if src.count(old)!=1:rows.append({'mutation':n,'detected':False,'error':'anchor'});continue
   p=Path(d)/(n+'.py');p.write_text(src.replace(old,new),encoding='utf-8');spec=importlib.util.spec_from_file_location('fm_'+n,p);mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod);rows.append({'mutation':n,'detected':bool(exposed(mod,n))})
 detected=sum(x['detected'] for x in rows);return {'introduced':len(rows),'detected':detected,'survived':len(rows)-detected,'rows':rows,'passed':detected==len(rows)}
if __name__=='__main__':
 r=run(Path(__file__).resolve().parents[1]);print(json.dumps(r,indent=2,sort_keys=True));raise SystemExit(0 if r['passed'] else 1)
