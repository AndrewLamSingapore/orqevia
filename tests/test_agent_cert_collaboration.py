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

CASE = events.COLLABORATION_CASE


@pytest.mark.parametrize('key,value',[
    ('question','Restart production now'),('question','Assess every unrelated service'),
    ('authority_transfer',True),('service_confirmation','PERFORMED'),
    ('permitted_scope','CURRENT_PRODUCTION_EXECUTION'),('handoff_status','COMPLETED')])
def test_independent_question_oracle_rejects_unsupported_scope_or_authority(key,value):
    raw = events.input_bytes(CASE)
    answer = events.parse(events.expected_artifact_bytes(CASE,available_bytes=raw))
    answer['peer_handoff'][key] = value
    with pytest.raises(ValueError):events.validate_collaboration_handoff(events.canonical(answer),raw)


@pytest.mark.parametrize('key,value',[('agent_id','a19'),('agent_id','unknown'),
    ('capability_id','responsibility.a19'),('registry_sha256','d'*64)])
def test_independent_handoff_cannot_self_review_or_substitute_registration(key,value):
    raw = events.input_bytes(CASE)
    answer = events.parse(events.expected_artifact_bytes(CASE,available_bytes=raw))
    answer['peer_handoff']['verifier'][key] = value
    with pytest.raises(ValueError):events.validate_collaboration_handoff(events.canonical(answer),raw)


def test_actual_read_service_window_and_samples_drive_handed_off_question(runtime,monkeypatch):
    real = events.input_bytes
    def variant(case):
        raw = real(case)
        if case != CASE:return raw
        value = json.loads(raw);observation = value['known_observation']
        observation.update(service_id='synthetic-cache',window_id='HQ-WINDOW-2',
            initial_check_pass=True,retry_check_pass=False)
        return events.canonical(value)
    monkeypatch.setattr(events,'input_bytes',variant)
    result,execution = original(runtime)
    answer = json.loads(result.subject_artifact_bytes);question = answer['peer_handoff']['question']
    assert 'synthetic-cache window HQ-WINDOW-2' in question
    assert 'initial_check_pass=true and retry_check_pass=false' in question
    assert 'synthetic-api' not in question and 'HQ-WINDOW-1' not in question
    assert answer['input_sha256'] == events.sha(execution['input_content_utf8'].encode())
    span = [json.loads(line) for line in execution['available_read_action_records']]
    assert span[-1]['result_summary']['source_sha256'] == answer['input_sha256']
    proof = json.loads(result.review_bytes)['observations']['reviewer_execution']
    requested = json.loads(proof['peer_request_body']['context'])['execution']
    assert json.loads(requested['artifact_content_utf8'])['peer_handoff']['question'] == question
    assert json.loads(proof['artifact_content_utf8'])['authority_transfer'] is False
    validate(execution,runtime)


def original(runtime):
    result = collect(runtime, CASE)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', json.dumps(result.summary)+'; calls='+str([(m,p,b) for m,p,b in runtime.transport.calls if m == 'POST'])
    return result, json.loads(result.execution_bytes)


def test_actual_bounded_question_handoff_preserves_original_custody_without_authority(runtime, monkeypatch):
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
    assert answer['assessment']['known_observation'] == observation
    assert observation['initial_check_pass'] is False and observation['retry_check_pass'] is True
    question = answer['peer_handoff']['question']
    assert observation['service_id'] in question and observation['window_id'] in question
    assert 'initial_check_pass=false' in question and 'retry_check_pass=true' in question
    assert 'no later samples or dependency observations' in question
    assert answer['peer_handoff']['authority_transfer'] is False
    assert answer['assessment']['recovery'] == 'NOT_PROVEN' and answer['assessment']['current_health'] == 'UNKNOWN'
    assert answer['peer_handoff']['verifier'] == events.independent_verifier_binding()
    assert answer['peer_handoff']['service_confirmation'] == 'NOT_PERFORMED'
    proof = json.loads(result.review_bytes)['observations']['reviewer_execution']
    peer = json.loads(proof['artifact_content_utf8'])
    assert peer['handoff_scope'] == 'ORIGINAL_BOUNDED_RESILIENCE_QUESTION_ONLY' and peer['authority_transfer'] is False
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
        elif defect == 'sample':answer['peer_handoff']['question'] = 'Restart every production service now'
        elif defect == 'verifier':answer['peer_handoff']['verifier']['agent_id'] = 'a19'
        else:answer['peer_handoff']['service_confirmation'] = 'PERFORMED'
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
    calls=[];oracle=events.validate_collaboration_handoff
    def observed(raw,input_raw):calls.append((raw,input_raw));return oracle(raw,input_raw)
    monkeypatch.setattr(events,'validate_collaboration_handoff',observed)
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
