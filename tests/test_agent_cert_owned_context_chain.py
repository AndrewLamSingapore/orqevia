"""Original temporary HTTP domains and pure protected oracle, never signing."""
from datetime import datetime,timedelta,timezone
import json
import pytest
from app.agent_cert_owned_context import canonical_owned_context_case,context_reviewer,ORACLE_ID
from app.agent_registry import agent_record
from tests.test_agent_cert_owned_context_events import PAIRS
from tests.test_agent_cert_authority_chain import runtime,CODE
from tests.test_agent_cert_review_dispatch import configured,SOURCE,IMAGE,NONCE
from tests.test_agent_cert_operator_io import TOKEN,FakeTimer
from scripts.agent_cert_operator_io import AgentCertOperatorIO
from scripts.collect_agent_cert_event import collect_event_case
from scripts.agent_cert_reviewed_signing import _review


@pytest.mark.parametrize('pair',PAIRS)
def test_all29_actual_http_operator_original_custody_and_pure_oracle(runtime,pair,monkeypatch):
    from app import agent_cert_owned_context as module
    original=module.validate_owned_context_execution;errors=[]
    def joined(value,**pins):
        try:return original(value,**pins)
        except Exception as exc:
            errors.append(type(exc).__name__+':'+str(exc));raise
    monkeypatch.setattr(module,'validate_owned_context_execution',joined)
    agent,capability=pair;spec=canonical_owned_context_case(*pair)
    operator=AgentCertOperatorIO(owner_token=TOKEN,spec=spec,expected_source_revision=SOURCE,
        expected_runtime_image=IMAGE,connection_factory=runtime.transport,timer_factory=FakeTimer,
        total_timeout_seconds=30,monotonic=lambda:0.0)
    result=collect_event_case(spec,io=operator.io(),read_subject_actions=operator.read_subject_actions,
        expected_source_revision=SOURCE,expected_runtime_image=IMAGE,expected_registry_sha256=runtime.registry_sha,
        reviewer_code_revision=CODE,review_run_id='temporary-owned-context-original-review',timeout_seconds=30,
        nonce_factory=lambda:NONCE)
    assert result.summary['state']=='UNSIGNED_EVENT_EVIDENCE',json.dumps({'summary':result.summary,'original_join_errors':errors})
    assert result.summary['subject_task_id']!=result.summary['review_task_id']
    assert len(result.subject_actions)==len(result.reviewer_actions)==2
    assert [method for method,_ in runtime.requests].count('POST')==2
    review=json.loads(result.review_bytes);now=datetime.now(timezone.utc)
    reviewer,reviewcap=context_reviewer(*pair)
    assert json.loads(result.reviewer_artifact_bytes)['reviewer_id']==reviewer
    row={'agent_id':agent,'capability_id':capability,'dimension':'baseline','test_case':'context',
        'certification_test':'owned-context-source-chain','test_version':'registered.owned-context-events.v1',
        'test_result':'PASS','verifier':reviewer,'executor_identity':agent,'source_revision':SOURCE,
        'review_source_revision':SOURCE,'reviewer_code_revision':CODE,'authority_scope':agent_record(agent)['authority'],
        'review_test_version':ORACLE_ID,'review_run_id':review['review_run_id'],'certified_at':now.isoformat(),
        'last_revalidated':now.isoformat(),'expires_at':(now+timedelta(hours=1)).isoformat()}
    assert _review(row,result.execution_bytes,result.review_bytes,source_revision=SOURCE,
        runtime_image_id=IMAGE,reviewer_code_revision=CODE,now=now) is True
    assert result.summary['signature']=='NOT_PERFORMED'
