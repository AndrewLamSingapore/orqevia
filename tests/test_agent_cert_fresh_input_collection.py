"""Exact bounded original HTTP collection and unsigned verifier bridge only."""
import json
import uuid
from copy import deepcopy
from datetime import datetime,timedelta,timezone

import pytest

from app import agent_cert_fresh_input as fresh
from app.agent_cert_role_review import canonical_case_spec,review_case_output
from scripts.collect_agent_cert_fresh_input import collect_fresh_input
from scripts.agent_cert_reviewed_signing import _review,CertificationReviewError
from tests.test_agent_cert_authority_chain import runtime
from tests.test_agent_cert_review_dispatch import configured,SOURCE,IMAGE
from tests.test_agent_cert_operator_io import TOKEN,FakeTimer
from tests.test_agent_cert_tool_events import no_external_operations
from tests.test_agent_cert_fresh_input import supplied_after

CODE = 'f'*40


def collect(runtime,case,**changes):
    options = dict(owner_token=TOKEN,expected_source_revision=SOURCE,expected_runtime_image=IMAGE,
        expected_registry_sha256=runtime.registry_sha,reviewer_code_revision=CODE,
        review_run_id='temporary-fresh-input-original-review',
        supply_after_initialization=lambda initialized:supplied_after(initialized,case),
        connection_factory=runtime.transport,timer_factory=FakeTimer,monotonic=lambda:0.0)
    options.update(changes)
    return collect_fresh_input(case,**options)


def row(case):
    now = datetime.now(timezone.utc);dimension,test_case = case.split(':')
    return dict(agent_id='a19',capability_id='responsibility.a19',dimension=dimension,test_case=test_case,
        certification_test='temporary-supplied-input',test_version=fresh.CASE_VERSION,test_result='PASS',
        verifier='a26',executor_identity='a19',source_revision=SOURCE,review_source_revision=SOURCE,
        reviewer_code_revision=CODE,authority_scope='advisory',review_test_version=fresh.ORACLE_ID,
        review_run_id='temporary-fresh-input-original-review',certified_at=now.isoformat(),
        last_revalidated=now.isoformat(),expires_at=(now+timedelta(hours=1)).isoformat())


def bridge(record,result,*,now=None,**changes):
    return _review(record,result.execution_bytes,result.review_bytes,source_revision=SOURCE,
        runtime_image_id=IMAGE,reviewer_code_revision=CODE,now=now or datetime.now(timezone.utc),**changes)


@pytest.mark.parametrize('case',fresh.CASES)
def test_original_bounded_collection_supplies_input_after_initialization_and_pure_bridge(runtime,case):
    arrivals = []
    def supply(initialized):
        arrivals.append((initialized['dispatch']['task_id'],len(runtime.requests)))
        assert len([p for m,p in runtime.requests if m == 'POST']) == 2
        return supplied_after(initialized,case)
    result = collect(runtime,case,supply_after_initialization=supply)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE',result.summary
    execution = json.loads(result.execution_bytes)
    assert len(arrivals) == 1 and len(result.original_replies) <= 60
    assert len([p for m,p in runtime.requests if m == 'POST']) == 6
    assert all(TOKEN.encode() not in reply.raw for reply in result.original_replies)
    bridge(row(case),result)
    fresh.validate_execution(execution,source_revision=SOURCE,runtime_image_id=IMAGE,
        registry_sha256=runtime.registry_sha,now=datetime.now(timezone.utc))
    assert canonical_case_spec('a19','responsibility.a19',case) == execution['case_spec']
    assert review_case_output('a19','responsibility.a19',case,'PASS')[0] is False
    with pytest.raises(ValueError):fresh.admit(execution['case_spec']['request'],runtime.registry_sha)


@pytest.mark.parametrize('defect',['owner','task','registry','model','false_health','oracle','reviewer','source','expired','cloud'])
def test_unsigned_bridge_rejects_original_binding_or_confirmation_corruption(runtime,defect):
    from dataclasses import replace
    case = fresh.CASES[0];result = collect(runtime,case)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE',result.summary
    record = row(case);execution = json.loads(result.execution_bytes);review = json.loads(result.review_bytes)
    if defect == 'owner':record['executor_identity'] = 'a26'
    elif defect == 'task':execution['source']['dispatch']['task_id'] = str(uuid.uuid4())
    elif defect == 'registry':review['registry_sha256'] = '0'*64
    elif defect == 'model':execution['audit']['dispatch']['model_calls'] = 1
    elif defect == 'false_health':review['service_confirmation'] = 'PROVEN'
    elif defect == 'oracle':review['oracle_pass'] = False
    elif defect == 'reviewer':review['reviewer_agent_id'] = 'a19'
    elif defect == 'source':record['review_source_revision'] = '0'*40
    elif defect == 'expired':record['expires_at'] = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    bad = replace(result,execution_bytes=fresh.canonical(execution),review_bytes=fresh.canonical(review))
    with pytest.raises((CertificationReviewError,ValueError)):
        bridge(record,bad,**({'cloud_binding':{}} if defect == 'cloud' else {}))


def test_collection_has_no_callback_fallback_or_replay_after_custodian_failure(runtime):
    calls = []
    def absent(initialized):calls.append(initialized['dispatch']['task_id']);return None
    result = collect(runtime,fresh.CASES[0],supply_after_initialization=absent)
    assert result.summary['state'] == 'INCOMPLETE' and len(calls) == 1
    assert len([p for m,p in runtime.requests if m == 'POST']) == 2
    assert result.original_replies and result.summary['signed'] is False
