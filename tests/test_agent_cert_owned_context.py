import json
import pytest
from app.agent_cert_owned_context import context_bytes,select_context,_review_assessment
from app.agent_cert_initialization import canonical
from app import agent_registry
PAIRS=[(a['id'],c) for a in agent_registry.load_agent_registry()['agents'] for c in a['capability_requirements']]
@pytest.mark.parametrize('pair',PAIRS)
def test_actual_context_and_independent_boundary(pair):
 from app.agent_cert_a19_baseline import _SCENARIOS
 raw=context_bytes(*pair)
 assert json.loads(raw)['facts']==_SCENARIOS['baseline:context'][1]
 result=select_context(raw)
 assert result==_review_assessment(raw)
 assert result['sample_age_seconds']==[300] and result['observed_sample_health']==['PASS']
 assert result['evidence_refs']==['BCTX1'] and result['historical_refs']==['BCTX2']
 assert result['continuous_health']==result['root_cause']=='UNKNOWN'
@pytest.mark.parametrize('change',['future','stale','other_service'])
def test_selection_uses_supplied_bytes(change):
 value=json.loads(context_bytes('a19','responsibility.a19'));row=value['facts']['observations'][0]
 if change=='future':row['observed_at']='2026-10-08T04:10:01Z'
 elif change=='stale':row['observed_at']='2026-10-08T04:04:59Z'
 else:row['service']='other-service'
 result=select_context(canonical(value))
 assert result['selected_observations']==[] and result['historical_refs']==['BCTX1','BCTX2']
def test_a19_original_quality_case_unchanged():
 from app.agent_cert_role_review import canonical_case_spec
 from app.agent_cert_a19_baseline import canonical_a19_baseline_case
 assert canonical_case_spec('a19','responsibility.a19','baseline:context')==canonical_a19_baseline_case('baseline:context')
