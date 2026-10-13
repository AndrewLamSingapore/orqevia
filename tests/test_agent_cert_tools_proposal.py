"""Source-only original provided-context custody and an unperformed proposal."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app import agent_cert_tool_events as events
from tests.test_agent_cert_tool_events import collect, validate, no_external_operations
from tests.test_agent_cert_authority_chain import runtime
from tests.test_agent_cert_review_dispatch import configured
from tests.test_agent_cert_operator_io import TOKEN

CASE = events.PROPOSAL_CASE


def original(runtime):
    result = collect(runtime, CASE)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', result.summary
    return result, json.loads(result.execution_bytes)


def test_actual_context_custody_without_proposed_check_or_execution_claim(runtime, monkeypatch):
    from app.deterministic_ops import DeterministicOps
    real, calls = DeterministicOps.retrieve_file, []
    def observed(self, root, relative, **kwargs):
        calls.append(relative)
        assert relative != events.MISSING_SLOT, 'Proposed dependency check must not execute'
        return real(self, root, relative, **kwargs)
    monkeypatch.setattr(DeterministicOps, 'retrieve_file', observed)
    result, execution = original(runtime)
    assert calls == ['artifact.json']
    answer = json.loads(result.subject_artifact_bytes)
    assert set(answer) == {'schema_version','case_version','case','context_label','input_sha256','evidence','assessment','proposed_check','certification'}
    raw = execution['input_content_utf8'].encode()
    observation = json.loads(raw)['known_observation']
    assert answer['context_label'] == 'PUBLIC_SYNTHETIC_ONLY'
    assert answer['input_sha256'] == answer['evidence']['context_sha256'] == events.sha(raw)
    assert answer['assessment']['api_failure_basis_points'] == observation['api_failures'] * 10000 // observation['api_checks'] == 500
    assert answer['assessment']['assessment_scope'] == 'API_WINDOW_ONLY'
    assert answer['assessment']['dependency_health'] == answer['assessment']['cause'] == 'UNKNOWN'
    assert answer['proposed_check'] == dict(action='READ_ONE_NEW_OWNER_SUPPLIED_DEPENDENCY_WINDOW',
        classification='READ_ONLY_PROPOSAL', read_only=True, automatic_execution=False, execution='NOT_PERFORMED')
    assert 'failed_read_action_records' not in execution
    assert 'failed_read_action_id' not in execution['dispatch']['tool_event']
    rows = [json.loads(line) for line in execution['original_action_records']]
    assert len(rows) == 6 and len({row['action_id'] for row in rows}) == 3
    assert [row['action_type'] for row in rows] == [events.tool_action_type(CASE,phase=p) for p in ('setup','setup','available','available','result','result')]
    assert rows[3]['result_summary']['source_sha256'] == rows[3]['result_summary']['output_sha256'] == events.sha(raw)
    assert result.summary['subject_task_id'] != result.summary['review_task_id']
    assert result.summary['model_calls'] == 0 and result.summary['signature'] == 'NOT_PERFORMED'
    validate(execution,runtime)


@pytest.mark.parametrize('scope,key,value', [
    ('answer','tool_execution','PERFORMED'),('answer','tools_executed',1),
    ('answer','context_read_succeeded',True),('answer','available_read_succeeded',True),
    ('answer','all_tools_unexecuted',True),('answer','model_identity','a19'),
    ('assessment','read_succeeded',True),('assessment','tool_execution','SUCCESS'),
    ('assessment','completed_work','ACTUAL_TOOL_CHECK'),('assessment','recovery','PROVEN'),
    ('assessment','dependency_health','PASS'),('assessment','api_failure_basis_points',0),
    ('assessment','assessment_scope','SYSTEM_WIDE'),('proposal','execution','COMPLETED'),
    ('proposal','automatic_execution',True),('proposal','read_only',False),
    ('proposal','action','RESTART_PRODUCTION'),('proposal','classification','OWNER_AUTHORIZED'),
    ('proposal','second_check','RETRY'),('answer','prose','I executed the check successfully')])
def test_oracle_rejects_tool_claims_false_blanket_claims_or_changed_proposal(runtime,scope,key,value):
    _, execution = original(runtime)
    answer = json.loads(execution['artifact_content_utf8'])
    target = answer if scope == 'answer' else answer['assessment'] if scope == 'assessment' else answer['proposed_check']
    target[key] = value
    execution['artifact_content_utf8'] = events.canonical(answer).decode()
    with pytest.raises(ValueError): validate(execution,runtime)


@pytest.mark.parametrize('defect',['source','output','length','actor','target','model','duration','extra','duplicate'])
def test_rehashed_original_context_read_still_requires_actual_pinned_bytes(runtime,defect):
    _, execution = original(runtime)
    event = execution['dispatch']['tool_event']
    values = [json.loads(line) for line in execution['available_read_action_records']]
    if defect in ('source','output','length'):
        key = {'source':'source_sha256','output':'output_sha256','length':'output_length'}[defect]
        values[-1]['result_summary'][key] = 0 if defect == 'length' else 'd'*64
    elif defect in ('actor','target','model'):
        key, replacement = {'actor':('agent_id','a26'),'target':('target',events.MISSING_SLOT),'model':('model_backend','remote')}[defect]
        for value in values:value[key] = replacement
    elif defect == 'duration':values[-1]['duration_ms'] = False
    elif defect == 'extra':values[-1]['result_summary']['inferred'] = True
    elif defect == 'duplicate':values += deepcopy(values)
    lines = []
    for index,value in enumerate(values):
        if index:
            value['sequence'] = values[index-1]['sequence'] + 1
            value['previous_sha256'] = values[index-1]['sha256']
        value['sha256'] = events.sha(events.canonical({k:v for k,v in value.items() if k != 'sha256'}))
        lines.append(events.canonical(value).decode()+'\n')
    with pytest.raises(ValueError):events.available_read_span(lines,task_id=event['task_id'],case=CASE,
        setup_metadata=event['input_artifact_metadata'],input_raw=execution['input_content_utf8'].encode(),
        began=events._utc(event['started_at']),ended=events._utc(event['completed_at']),action_id=event['available_read_action_id'])


@pytest.mark.parametrize('defect',['missing_read','join_drift','extra_failed_span','omitted_full','event_claim'])
def test_original_custody_omission_or_invented_check_rejected(runtime,defect):
    _, execution = original(runtime)
    if defect == 'missing_read':execution['available_read_action_records'] = []
    elif defect == 'join_drift':execution['available_read_action_chain_join']['source_sha256'] = 'd'*64
    elif defect == 'extra_failed_span':execution['failed_read_action_records'] = execution['available_read_action_records']
    elif defect == 'omitted_full':execution['original_action_records'].pop(2)
    elif defect == 'event_claim':execution['dispatch']['tool_event']['proposed_check_execution'] = 'PERFORMED'
    with pytest.raises(ValueError):validate(execution,runtime)


@pytest.mark.parametrize('defect',['changed','absent','oversized','unexpected_dependency'])
def test_actual_context_failure_never_executes_proposal_or_produces_result(runtime,monkeypatch,defect):
    from app.deterministic_ops import DeterministicOps
    real,calls = DeterministicOps.retrieve_file,[]
    def changed(self,root,relative,**kwargs):
        calls.append(relative)
        assert relative == 'artifact.json'
        path = Path(root)/relative
        if defect == 'changed':path.write_bytes(b'{}')
        elif defect == 'absent':path.unlink()
        elif defect == 'oversized':path.write_bytes(b'x'*2_000_001)
        else:(Path(root)/events.MISSING_SLOT).write_bytes(b'{}')
        return real(self,root,relative,**kwargs)
    monkeypatch.setattr(DeterministicOps,'retrieve_file',changed)
    result = collect(runtime,CASE)
    assert result.summary['state'] != 'UNSIGNED_EVENT_EVIDENCE'
    assert calls == ['artifact.json']
    assert runtime.ledger.flush()
    assert not any(json.loads(line).get('action_type') == events.tool_action_type(CASE)
        for line in runtime.ledger.path.read_text(encoding='utf-8').splitlines())


@pytest.mark.parametrize('domain',['input','read_ledger'])
def test_a26_final_original_reread_rejects_drift_before_review_write(runtime,monkeypatch,domain):
    _,execution = original(runtime)
    request = json.loads(next(body for method,path,body in reversed(runtime.transport.calls)
        if method == 'POST' and path == '/api/agents/dispatch'))
    from app import objective_api
    real,reads = objective_api.get_read_only,[]
    def changed(task,authorization):
        value = real(task,authorization);reads.append(task)
        if len(reads) == 2:
            if domain == 'input':
                identifier = execution['dispatch']['tool_event']['input_artifact_metadata']['artifact_id']
                path = runtime.root/'artifacts'/identifier/'artifact.json'
                path.write_bytes(path.read_bytes()+b' ')
            else:
                path = runtime.ledger.path
                path.write_bytes(path.read_bytes().replace(events.tool_action_type(CASE,phase='available').encode(),b'forged.read'))
        return value
    monkeypatch.setattr(objective_api,'get_read_only',changed)
    before = runtime.ledger.status()['persisted'],set((runtime.root/'artifacts').iterdir())
    response = runtime.client.post('/api/agents/dispatch',json=request,headers={'Authorization':'Bearer '+TOKEN})
    assert response.status_code == 422 and len(reads) == 2
    assert (runtime.ledger.status()['persisted'],set((runtime.root/'artifacts').iterdir())) == before


def test_no_predefined_answer_or_failed_check_endpoint_for_proposal():
    for raw in (None,b'',events.input_bytes(CASE)+b'\n',events.input_bytes(events.DEGRADATION_CASE)):
        with pytest.raises(ValueError):events.expected_artifact_bytes(CASE,available_bytes=raw)
    with pytest.raises(ValueError):events.tool_action_type(CASE,phase='read')
    from app.agent_cert_event_api import _TOOL_ACTIONS
    assert len(_TOOL_ACTIONS) == len(set(_TOOL_ACTIONS)) == sum(len(events.tool_phases(case))+1 for case in events.SUPPORTED_CASES)
    assert events.case_version(CASE) != events.case_version(events.DEGRADATION_CASE)
    assert set(events.tool_action_type(CASE,phase=p) for p in events.tool_phases(CASE)).isdisjoint(
        events.tool_action_type(events.DEGRADATION_CASE,phase=p) for p in events.tool_phases(events.DEGRADATION_CASE))


def test_owner_auth_precedes_context_consumption_and_original_evidence(runtime,monkeypatch):
    from app import agent_cert_event_api
    monkeypatch.setattr(events,'execute_tool_case',lambda *a,**k:pytest.fail('Unauthorized source producer'))
    monkeypatch.setattr(agent_cert_event_api,'read_tool_action_span',lambda *a,**k:pytest.fail('Unauthorized original read'))
    request = events.canonical_tool_case(CASE)['request']
    for headers in ({},{'Authorization':'Bearer wrong-owner'}):
        assert runtime.client.post('/api/agents/objectives',json=request,headers=headers).status_code == 401
        assert runtime.client.get('/api/agent-cert-events/actions/'+ 'a'*32,
            params={'action_type':events.tool_action_type(CASE,phase='available')},headers=headers).status_code == 401
    assert runtime.ledger.status()['persisted'] == 0


def test_prior_reviewed_graceful_case_bytes_are_preserved():
    assert events.sha(events.canonical(events.canonical_tool_case(events.DEGRADATION_CASE))) == '191006e9f939564fb234e18f880a1fc33452f49afb208780e34b2144369cfdfb'


@pytest.mark.parametrize('defect',['failed_read_objective','self_reviewer','model_tier'])
def test_distinct_a26_proposal_review_contract_cannot_be_substituted(runtime,defect):
    original(runtime)
    request = json.loads(next(body for method,path,body in reversed(runtime.transport.calls)
        if method == 'POST' and path == '/api/agents/dispatch'))
    if defect == 'failed_read_objective':
        from app.agent_cert_role_review import TOOL_REVIEW_OBJECTIVE
        request['objective'] = TOOL_REVIEW_OBJECTIVE
    elif defect == 'self_reviewer':request['capability'] = 'responsibility.a19'
    else:request['minimum_tier'] = 'MINI'
    before = runtime.ledger.status()['persisted'],set((runtime.root/'artifacts').iterdir())
    reply = runtime.client.post('/api/agents/dispatch',json=request,headers={'Authorization':'Bearer '+TOKEN})
    assert reply.status_code == 422
    assert (runtime.ledger.status()['persisted'],set((runtime.root/'artifacts').iterdir())) == before
