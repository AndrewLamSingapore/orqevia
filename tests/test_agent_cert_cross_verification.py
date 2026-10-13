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

CASE = events.CROSS_CASE


def original(runtime):
    result = collect(runtime, CASE)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', json.dumps(result.summary)+'; calls='+str([(m,p,b) for m,p,b in runtime.transport.calls if m == 'POST'])
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
    raw = execution['input_content_utf8'].encode()
    observation = json.loads(raw)['known_observation']
    assert answer['input_sha256'] == answer['evidence']['context_sha256'] == events.sha(raw)
    assert answer['assessment']['initial_sample_pass'] == observation['initial_check_pass'] is False
    assert answer['assessment']['latest_supplied_sample_pass'] == observation['retry_check_pass'] is True
    assert answer['assessment']['recovery'] == 'NOT_PROVEN' and answer['assessment']['current_health'] == 'UNKNOWN'
    assert answer['second_check_request']['verifier'] == events.independent_verifier_binding()
    assert answer['second_check_request']['service_confirmation'] == 'NOT_PERFORMED'
    proof = json.loads(result.review_bytes)['observations']['reviewer_execution']
    peer = json.loads(proof['artifact_content_utf8'])
    assert peer['cross_check_scope'] == 'ORIGINAL_SUPPLIED_RECOVERY_CLAIM_ONLY'
    assert peer['recovery'] == 'NOT_PROVEN' and peer['current_health'] == 'UNKNOWN'
    request = proof['peer_request_body'];receipt = peer['peer_request_receipt']
    assert receipt['objective_sha256'] == events.sha(request['objective'].encode())
    assert receipt['dispatcher_request_sha256'] == events.sha(events.canonical(request))
    assert receipt['task_id'] == proof['dispatch']['task_id'] != execution['dispatch']['task_id']
    assert proof['peer_objective_read'][1]['id'] == receipt['task_id']
    assert len([1 for method,path,body in runtime.transport.calls if method == 'GET' and path == '/api/agents/objectives/'+receipt['task_id']]) == 2
    assert len([1 for method,path,body in runtime.transport.calls if method == 'POST' and path == '/api/agents/objectives']) == 2
    assert not any(method == 'POST' and path == '/api/agents/dispatch' for method,path,body in runtime.transport.calls)
    import sqlite3
    with sqlite3.connect(runtime.root/'objectives.db') as db:
        assert db.execute('SELECT objective_hash FROM objectives WHERE id=?',(receipt['task_id'],)).fetchone() == (receipt['objective_sha256'],)
        assert db.execute('SELECT COUNT(*) FROM objectives WHERE id IN (?,?)',(receipt['task_id'],execution['dispatch']['task_id'])).fetchone()[0] == 2
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
    ('answer','confirmation','PERFORMED'),('answer','model_identity','a19'),
    ('assessment','recovery','PROVEN'),('assessment','current_health','HEALTHY'),
    ('assessment','recovery_claim_supported',True),('assessment','initial_sample_pass',True),
    ('assessment','latest_supplied_sample_pass',False),('assessment','scope','CURRENT_SERVICE'),
    ('request','authority_transfer',True),('request','service_confirmation','PERFORMED'),
    ('request','request_status','COMPLETED'),('request','required_original_context_sha256','d'*64),
    ('verifier','agent_id','a19'),('verifier','agent_id','unregistered'),
    ('verifier','registry_sha256','d'*64),('verifier','capability_id','responsibility.a19')])
def test_independent_oracle_rejects_false_recovery_health_or_peer_request(runtime,scope,key,value):
    _,execution = original(runtime)
    answer = json.loads(execution['artifact_content_utf8'])
    targets = dict(answer=answer,assessment=answer['assessment'],request=answer['second_check_request'],
        verifier=answer['second_check_request']['verifier'])
    targets[scope][key] = value
    execution['artifact_content_utf8'] = events.canonical(answer).decode()
    with pytest.raises(ValueError):validate(execution,runtime)


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
        if method == 'POST' and path == '/api/agents/objectives'))
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
    response = runtime.client.post('/api/agents/objectives',json=request,headers={'Authorization':'Bearer '+TOKEN})
    assert response.status_code == 202 and response.json()['steps'][0]['state'] == 'blocked' and len(reads) == 2
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
        if method == 'POST' and path == '/api/agents/objectives'))
    if defect == 'failed_read_objective':
        from app.agent_cert_role_review import TOOL_REVIEW_OBJECTIVE
        request['objective'] = TOOL_REVIEW_OBJECTIVE
    elif defect == 'self_reviewer':request['capability'] = 'responsibility.a19'
    else:request['minimum_tier'] = 'MINI'
    before = runtime.ledger.status()['persisted'],set((runtime.root/'artifacts').iterdir())
    reply = runtime.client.post('/api/agents/objectives',json=request,headers={'Authorization':'Bearer '+TOKEN})
    assert reply.status_code == 202 and reply.json()['steps'][0]['state'] == 'blocked'
    assert (runtime.ledger.status()['persisted'],set((runtime.root/'artifacts').iterdir())) == before


@pytest.mark.parametrize('defect',['objective_hash','runtime','steps','revision','state'])
def test_actual_peer_original_request_drift_on_second_read_fails_before_artifact(runtime,monkeypatch,defect):
    import sqlite3
    real,calls = events.read_cross_peer_request,[]
    def changed(root,task,request,pins,subject,**kwargs):
        calls.append(task)
        if len(calls) == 2:
            with sqlite3.connect(runtime.root/'objectives.db') as db:
                if defect == 'objective_hash':db.execute('UPDATE objectives SET objective_hash=? WHERE id=?',('d'*64,task))
                elif defect == 'runtime':db.execute('UPDATE objective_runtime SET image_digest=? WHERE task=?',('sha256:'+'d'*64,task))
                elif defect == 'steps':db.execute('UPDATE objectives SET steps_json=? WHERE id=?',('["responsibility.a19"]',task))
                elif defect == 'revision':db.execute('UPDATE objective_metadata SET revision=1 WHERE task=?',(task,))
                else:db.execute('UPDATE objectives SET state=? WHERE id=?',('submitted',task))
        return real(root,task,request,pins,subject,**kwargs)
    monkeypatch.setattr(events,'read_cross_peer_request',changed)
    result = collect(runtime,CASE)
    assert result.summary['state'] != 'UNSIGNED_EVENT_EVIDENCE'
    assert len(calls) == 2 and calls[0] == calls[1]
    assert len(list((runtime.root/'artifacts').iterdir())) == 2


@pytest.mark.parametrize('defect',['peer_id','objective_sha256','dispatcher_request_sha256','stored_state','runtime','service_confirmation'])
def test_original_peer_request_receipt_does_not_accept_laundered_fields(runtime,defect):
    result,execution = original(runtime)
    proof = json.loads(result.review_bytes)['observations']['reviewer_execution']
    peer = json.loads(proof['artifact_content_utf8']);receipt = deepcopy(peer['peer_request_receipt'])
    if defect == 'runtime':receipt['runtime']['source_revision'] = 'e'*40
    else:receipt[defect] = {'peer_id':'a19','objective_sha256':'d'*64,'dispatcher_request_sha256':'d'*64,
        'stored_state':'approved','service_confirmation':'PERFORMED'}[defect]
    from datetime import datetime,timezone
    with pytest.raises(ValueError):events.validate_cross_peer_receipt(receipt,
        peer_task=proof['dispatch']['task_id'],subject_task=execution['dispatch']['task_id'],
        request=proof['peer_request_body'],runtime=execution['runtime'],now=datetime.now(timezone.utc))


def test_direct_peer_dispatch_without_actual_objective_cannot_count_request(runtime):
    result,execution = original(runtime)
    from tests.test_agent_cert_review_dispatch import SOURCE
    import uuid
    request = events.cross_peer_request(execution,str(uuid.uuid4()),SOURCE)
    before = set((runtime.root/'artifacts').iterdir()),runtime.ledger.status()['persisted']
    reply = runtime.client.post('/api/agents/dispatch',json=request,headers={'Authorization':'Bearer '+TOKEN})
    assert reply.status_code == 422
    assert (set((runtime.root/'artifacts').iterdir()),runtime.ledger.status()['persisted']) == before


def test_independent_peer_uses_original_claim_oracle_not_producer_builder(runtime,monkeypatch):
    _,execution = original(runtime)
    monkeypatch.setattr(events,'expected_artifact_bytes',lambda *a,**k:pytest.fail('Borrowed producer builder'))
    validate(execution,runtime)


@pytest.mark.parametrize('defect',['claim','sample','verifier','confirmation'])
def test_actual_faulty_producer_original_is_rejected_by_a26_objective_check(runtime,monkeypatch,defect):
    real = events.expected_artifact_bytes
    def faulty(case,**kwargs):
        raw = real(case,**kwargs)
        if case != CASE:return raw
        answer = json.loads(raw)
        if defect == 'claim':answer['assessment']['recovery'] = 'PROVEN'
        elif defect == 'sample':answer['assessment']['initial_sample_pass'] = True
        elif defect == 'verifier':answer['second_check_request']['verifier']['agent_id'] = 'a19'
        else:answer['second_check_request']['service_confirmation'] = 'PERFORMED'
        return events.canonical(answer)
    monkeypatch.setattr(events,'expected_artifact_bytes',faulty)
    result = collect(runtime,CASE)
    assert result.summary['state'] != 'UNSIGNED_EVENT_EVIDENCE'
    execution = json.loads(result.execution_bytes)
    artifact_path = runtime.root/'artifacts'/execution['artifact_metadata']['artifact_id']/'artifact.json'
    assert artifact_path.read_bytes() == execution['artifact_content_utf8'].encode()
    assert len(execution['original_action_records']) == 6
    from tests.test_agent_cert_review_dispatch import SOURCE
    import uuid
    request = events.cross_peer_request(execution,str(uuid.uuid4()),SOURCE)
    calls=[];oracle=events.validate_cross_assessment
    def observed(raw,input_raw):calls.append((raw,input_raw));return oracle(raw,input_raw)
    monkeypatch.setattr(events,'validate_cross_assessment',observed)
    before = set((runtime.root/'artifacts').iterdir()),runtime.ledger.status()['persisted']
    reply = runtime.client.post('/api/agents/objectives',json=request,headers={'Authorization':'Bearer '+TOKEN})
    assert reply.status_code == 202 and reply.json()['steps'][0]['state'] == 'blocked'
    assert calls == [(artifact_path.read_bytes(),execution['input_content_utf8'].encode())]
    assert (set((runtime.root/'artifacts').iterdir()),runtime.ledger.status()['persisted']) == before


def test_exact_peer_objective_post_is_exclusive_without_automatic_replay(runtime):
    original(runtime)
    request = json.loads(next(body for method,path,body in reversed(runtime.transport.calls)
        if method == 'POST' and path == '/api/agents/objectives'))
    count = len(runtime.transport.calls)
    with pytest.raises(ValueError):runtime.operator.dispatch_reviewer(request)
    assert len(runtime.transport.calls) == count
    with pytest.raises(ValueError):runtime.operator.submit_objective(events.canonical_tool_case(CASE)['request'])
    # runtime preflight may read, but the original task is never submitted again.
    assert len([1 for method,path,body in runtime.transport.calls if method == 'POST']) == 2


@pytest.mark.parametrize('defect',['missing','giant_main','giant_wal','journal','giant_row','deadline'])
def test_original_peer_reader_bounds_real_stores_before_query_without_initialization(runtime,defect):
    import time
    result,execution = original(runtime)
    proof = json.loads(result.review_bytes)['observations']['reviewer_execution']
    task = proof['dispatch']['task_id'];request = proof['peer_request_body'];root=runtime.root
    deadline=time.monotonic()+1
    if defect == 'missing':(root/'objectives.db').unlink()
    elif defect == 'giant_main':(root/'objectives.db').write_bytes(b'x'*(8*1024*1024+1))
    elif defect == 'giant_wal':(root/'objectives.db-wal').write_bytes(b'x'*(8*1024*1024+1))
    elif defect == 'journal':(root/'objectives.db-journal').write_bytes(b'x'*(8*1024*1024+1))
    elif defect == 'giant_row':
        import sqlite3
        with sqlite3.connect(root/'objectives.db') as db:db.execute('UPDATE objectives SET objective_hash=? WHERE id=?',('x'*2_000_000,task))
    else:deadline=time.monotonic()-1
    before={p.name:p.read_bytes() for p in root.glob('objectives.db*') if p.is_file()}
    with pytest.raises(ValueError):events.read_cross_peer_request(root,task,request,execution['runtime'],
        execution['dispatch']['task_id'],deadline=deadline)
    assert {p.name:p.read_bytes() for p in root.glob('objectives.db*') if p.is_file()} == before


@pytest.mark.parametrize('defect',['runtime','steps','omitted_peer_objective','request','authoritative'])
def test_pure_protected_validator_rejects_original_peer_proof_drift(runtime,defect):
    from tests.test_agent_cert_tool_events import bridge,signer_row,CODE
    from tests.test_agent_cert_review_dispatch import SOURCE,IMAGE
    from datetime import datetime,timezone
    result,_ = original(runtime)
    review = json.loads(result.review_bytes);proof=review['observations']['reviewer_execution']
    if defect == 'runtime':proof['peer_objective_read'][1]['execution_metadata']['runtime']['image_digest']='sha256:'+'f'*64
    elif defect == 'steps':proof['peer_objective_read'][1]['steps'][0]['capability']='responsibility.a19'
    elif defect == 'omitted_peer_objective':proof.pop('peer_objective_read')
    elif defect == 'authoritative':proof['peer_objective_read'][1]['execution_metadata']['authoritative']=False
    else:proof['peer_request_body']['objective']='Verify current service health'
    with pytest.raises(ValueError):bridge._review(signer_row(result),result.execution_bytes,events.canonical(review),
        source_revision=SOURCE,runtime_image_id=IMAGE,reviewer_code_revision=CODE,now=datetime.now(timezone.utc))


def test_actual_supplied_sample_bytes_drive_both_scoped_assessments(runtime,monkeypatch):
    real = events.input_bytes
    def variant(case):
        raw = real(case)
        if case != CASE:return raw
        value=json.loads(raw);value['known_observation']['initial_check_pass']=True
        value['known_observation']['retry_check_pass']=False
        return events.canonical(value)
    monkeypatch.setattr(events,'input_bytes',variant)
    result,execution=original(runtime)
    answer=json.loads(result.subject_artifact_bytes)
    assert answer['assessment']['initial_sample_pass'] is True
    assert answer['assessment']['latest_supplied_sample_pass'] is False
    assert answer['assessment']['recovery_claim_supported'] is False
    assert answer['input_sha256']==events.sha(execution['input_content_utf8'].encode())
    proof=json.loads(result.review_bytes)['observations']['reviewer_execution']
    assert json.loads(proof['artifact_content_utf8'])['recovery']=='NOT_PROVEN'
    validate(execution,runtime)
