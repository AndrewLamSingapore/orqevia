"""Disposable actual original tasks; source custodian, never live unfamiliarity."""
import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app import agent_cert_fresh_input as fresh
from app.agent_cert_role_review import canonical_case_spec
from scripts.agent_cert_operator_io import AgentCertOperatorIO
from scripts.collect_agent_cert_event import collect_event_case
from tests.test_agent_cert_authority_chain import runtime
from tests.test_agent_cert_review_dispatch import configured, SOURCE, IMAGE, NONCE
from tests.test_agent_cert_operator_io import TOKEN, FakeTimer
from tests.test_agent_cert_tool_events import no_external_operations


def initialize(runtime):
    spec = canonical_case_spec('a19','responsibility.a19','baseline:initialization')
    operator = AgentCertOperatorIO(owner_token=TOKEN,spec=spec,
        expected_source_revision=SOURCE,expected_runtime_image=IMAGE,
        connection_factory=runtime.transport,timer_factory=FakeTimer,
        total_timeout_seconds=30,monotonic=lambda:0.0)
    result = collect_event_case(spec,io=operator.io(),read_subject_actions=operator.read_subject_actions,
        expected_source_revision=SOURCE,expected_runtime_image=IMAGE,
        expected_registry_sha256=runtime.registry_sha,reviewer_code_revision='f'*40,
        review_run_id='temporary-execution-input-initialization',timeout_seconds=30,
        nonce_factory=lambda:NONCE)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE',result.summary
    return json.loads(result.execution_bytes)


def supplied_after(initialization,case):
    # Called only after the actual initialization collector completed. This is
    # an explicit test custodian, not an external held-out challenge claim.
    assert initialization['dispatch']['state'] == 'COMPLETED'
    value = dict(case=case,challenge_id=str(uuid.uuid4()),label=fresh.LABEL,
        custodian_scope='SOURCE_TEST_CUSTODIAN',window_id='window-'+uuid.uuid4().hex)
    if case == fresh.CASES[0]:
        value.update(service_id='public-'+uuid.uuid4().hex,checks=7,failures=2)
    else:
        suffix = uuid.uuid4().hex
        nodes = ['front-'+suffix,'middle-'+suffix,'failed-'+suffix,'isolated-'+suffix]
        value.update(nodes=nodes,depends_on=[[nodes[0],nodes[1]],[nodes[1],nodes[2]]],
            failed_dependency=nodes[2],failure_observed=True)
    return value


def actual_stage(runtime,body):
    headers = {'Authorization':'Bearer '+TOKEN}
    response = runtime.client.post('/api/agents/objectives',json=body,headers=headers)
    assert response.status_code == 202,response.text
    view = response.json()
    dispatch = view['steps'][0]['dispatch']
    assert dispatch['state'] == 'COMPLETED',view
    metadata = dispatch['artifact'];task = dispatch['task_id']
    raw = runtime.client.get('/api/artifacts/'+metadata['artifact_id'],headers=headers)
    assert raw.status_code == 200,raw.text
    stage = json.loads(body['context'])['stage']
    def actions(action):
        reply = runtime.client.get('/api/agent-cert-events/actions/'+task,
            params={'action_type':action},headers=headers)
        assert reply.status_code == 200,reply.text
        return reply.json()['original_lines']
    objective = runtime.client.get('/api/agents/objectives/'+task,headers=headers)
    assert objective.status_code == 200,objective.text
    proof = dict(request=body,dispatch=dispatch,artifact_metadata=metadata,
        artifact_content_utf8=raw.content.decode(),action_records=actions(fresh.output_action(stage)),
        read_action_records=actions(fresh.read_action(stage)) if stage in ('source','audit') else [],
        objective_read=[objective.status_code,objective.json()])
    return proof


def input_chain(runtime,case):
    initialization = initialize(runtime)
    value = supplied_after(initialization,case)
    custody = actual_stage(runtime,fresh.custodian_request(case,initialization,value,runtime.registry_sha,str(uuid.uuid4())))
    return initialization,value,custody


@pytest.mark.parametrize('case',fresh.CASES)
def test_actual_supplied_after_initialization_distinct_blind_original_chain(runtime,case):
    initialization,value,custody = input_chain(runtime,case)
    source = actual_stage(runtime,fresh.stage_request('source',case,custody,runtime.registry_sha,str(uuid.uuid4())))
    audit = actual_stage(runtime,fresh.stage_request('audit',case,custody,runtime.registry_sha,str(uuid.uuid4())))
    comparison = actual_stage(runtime,fresh.stage_request('comparison',case,custody,runtime.registry_sha,
        str(uuid.uuid4()),source=source,audit=audit))
    data = fresh.validate_proof(comparison,initialization['runtime'],runtime.registry_sha,datetime.now(timezone.utc))
    assert data['result'] == 'PASS' and data['service_confirmation'] == 'NOT_PERFORMED'
    assert data['live_unfamiliarity'] == 'NOT_PROVEN'
    assert len({item['dispatch']['task_id'] for item in (custody,source,audit,comparison)}) == 4
    context = json.loads(comparison['request']['context'])
    assert len(comparison['request']['context']) <= 80000
    assert fresh.expand_original(context['source'],custody,'source') == source
    assert fresh.expand_original(context['audit'],custody,'audit') == audit
    assert source['dispatch']['artifact']['artifact_id'] not in audit['request']['context']
    assert source['artifact_content_utf8'] not in audit['request']['context']
    for defect in ('missing','hash','stage','foreign_task','original_artifact'):
        wrong = deepcopy(context['source'])
        nested = json.loads(wrong['request']['context'])
        if defect == 'missing':nested.pop('custodian')
        elif defect == 'hash':nested['custodian']['custodian_sha256'] = '0'*64
        elif defect == 'stage':nested['stage'] = 'audit'
        elif defect == 'foreign_task':wrong['dispatch']['task_id'] = str(uuid.uuid4())
        else:wrong['artifact_content_utf8'] += ' '
        wrong['request']['context'] = fresh.canonical(nested).decode()
        with pytest.raises(ValueError):
            expanded = fresh.expand_original(wrong,custody,'source')
            fresh.validate_proof(expanded,initialization['runtime'],runtime.registry_sha,datetime.now(timezone.utc))


@pytest.mark.parametrize('case',fresh.CASES)
@pytest.mark.parametrize('calculator',['producer_assessment','auditor_assessment'])
def test_genuine_wrong_original_answer_is_rejected_by_actual_distinct_comparison(runtime,monkeypatch,case,calculator):
    initialization,value,custody = input_chain(runtime,case)
    real = getattr(fresh,calculator)
    def faulty(payload):
        answer = real(payload)
        answer['current_health'] = 'HEALTHY'
        return answer
    monkeypatch.setattr(fresh,calculator,faulty)
    source = actual_stage(runtime,fresh.stage_request('source',case,custody,runtime.registry_sha,str(uuid.uuid4())))
    audit = actual_stage(runtime,fresh.stage_request('audit',case,custody,runtime.registry_sha,str(uuid.uuid4())))
    wrong = source if calculator == 'producer_assessment' else audit
    physical = runtime.root/'artifacts'/wrong['artifact_metadata']['artifact_id']/'artifact.json'
    assert physical.read_bytes() == wrong['artifact_content_utf8'].encode()
    assert json.loads(physical.read_bytes())['assessment']['current_health'] == 'HEALTHY'
    before = runtime.ledger.status()['persisted'],set((runtime.root/'artifacts').iterdir())
    body = fresh.stage_request('comparison',case,custody,runtime.registry_sha,str(uuid.uuid4()),source=source,audit=audit)
    reply = runtime.client.post('/api/agents/objectives',json=body,headers={'Authorization':'Bearer '+TOKEN})
    assert reply.status_code == 202 and reply.json()['steps'][0]['state'] == 'blocked'
    assert (runtime.ledger.status()['persisted'],set((runtime.root/'artifacts').iterdir())) == before


@pytest.mark.parametrize('case',fresh.CASES)
def test_input_only_original_auditor_never_reads_primary_answer(runtime,monkeypatch,case):
    initialization,value,custody = input_chain(runtime,case)
    source = actual_stage(runtime,fresh.stage_request('source',case,custody,runtime.registry_sha,str(uuid.uuid4())))
    from app.artifact_factory import ArtifactFactory
    from app.deterministic_ops import DeterministicOps
    retrieve,read = ArtifactFactory.retrieve,DeterministicOps.retrieve_file
    forbidden = source['artifact_metadata']['artifact_id'];reads = []
    def observed(self,artifact_id,*args,**kwargs):
        assert artifact_id != forbidden,'Prior primary answer disclosed to blind auditor'
        reads.append(artifact_id)
        return retrieve(self,artifact_id,*args,**kwargs)
    def actual_read(self,path,*args,**kwargs):
        assert forbidden not in str(path)
        return read(self,path,*args,**kwargs)
    monkeypatch.setattr(ArtifactFactory,'retrieve',observed)
    monkeypatch.setattr(DeterministicOps,'retrieve_file',actual_read)
    audit = actual_stage(runtime,fresh.stage_request('audit',case,custody,runtime.registry_sha,str(uuid.uuid4())))
    assert custody['artifact_metadata']['artifact_id'] in reads and forbidden not in reads
    def no_builder(*args,**kwargs):pytest.fail('Independent oracle borrowed calculator')
    monkeypatch.setattr(fresh,'producer_assessment',no_builder)
    monkeypatch.setattr(fresh,'auditor_assessment',no_builder)
    fresh.validate_proof(audit,initialization['runtime'],runtime.registry_sha,datetime.now(timezone.utc))


@pytest.mark.parametrize('case',fresh.CASES)
@pytest.mark.parametrize('defect',['prior_answer','answer','wrong_label','wrong_case','missing','no_failure','bool_count','oversize'])
def test_custodian_refuses_answer_bearing_or_unbound_input_before_any_artifact(runtime,case,defect):
    initialization = initialize(runtime);value = supplied_after(initialization,case)
    if defect in ('prior_answer','answer'):value[defect] = 'precomputed PASS'
    elif defect == 'wrong_label':value['label'] = 'PRIVATE'
    elif defect == 'wrong_case':value['case'] = fresh.CASES[1] if case == fresh.CASES[0] else fresh.CASES[0]
    elif defect == 'missing':value.pop('challenge_id')
    elif defect == 'no_failure':
        if case == fresh.CASES[0]:value['failures'] = 0
        else:value['failure_observed'] = False
    elif defect == 'bool_count':
        if case == fresh.CASES[0]:value['checks'] = True
        else:value['nodes'] = [True]
    else:value['window_id'] = 'x'*65537
    before = runtime.ledger.status()['persisted'],set((runtime.root/'artifacts').iterdir())
    with pytest.raises(ValueError):fresh.custodian_request(case,initialization,value,runtime.registry_sha,str(uuid.uuid4()))
    assert (runtime.ledger.status()['persisted'],set((runtime.root/'artifacts').iterdir())) == before


@pytest.mark.parametrize('case',fresh.CASES)
@pytest.mark.parametrize('stage',['custodian','source','audit'])
def test_actual_original_input_task_replay_is_rejected_without_new_observations(runtime,case,stage):
    initialization,value,custody = input_chain(runtime,case)
    if stage == 'custodian':body = fresh.custodian_request(case,initialization,value,runtime.registry_sha,str(uuid.uuid4()))
    else:
        actual_stage(runtime,fresh.stage_request(stage,case,custody,runtime.registry_sha,str(uuid.uuid4())))
        body = fresh.stage_request(stage,case,custody,runtime.registry_sha,str(uuid.uuid4()))
    before = runtime.ledger.status()['persisted'],set((runtime.root/'artifacts').iterdir())
    reply = runtime.client.post('/api/agents/objectives',json=body,headers={'Authorization':'Bearer '+TOKEN})
    assert reply.status_code == 202 and reply.json()['steps'][0]['state'] == 'blocked'
    assert (runtime.ledger.status()['persisted'],set((runtime.root/'artifacts').iterdir())) == before


def test_real_slow_fsync_both_audit_barriers_share_original_five_seconds(runtime,monkeypatch):
    import os,time,threading
    from app.action_records import ActionLedger
    initialization,value,custody = input_chain(runtime,fresh.CASES[0])
    execute,fsync,flush = fresh.execute,os.fsync,ActionLedger.flush
    phase = [None];delayed = [];budgets = []
    def tracked(body,*args,**kwargs):
        if body.objective != fresh.OBJECTIVES['audit']:return execute(body,*args,**kwargs)
        phase[0] = 'input'
        try:return execute(body,*args,**kwargs)
        finally:phase[0] = 'output'
    def slow(fd):
        current = phase[0]
        if current and current not in delayed and threading.current_thread().name == 'action-observability':
            delayed.append(current);time.sleep(1.2)
        return fsync(fd)
    def observed(self,timeout=5):
        if phase[0]:budgets.append((phase[0],timeout))
        return flush(self,timeout=timeout)
    monkeypatch.setattr(fresh,'execute',tracked)
    monkeypatch.setattr(os,'fsync',slow)
    monkeypatch.setattr(ActionLedger,'flush',observed)
    audit = actual_stage(runtime,fresh.stage_request('audit',fresh.CASES[0],custody,runtime.registry_sha,str(uuid.uuid4())))
    assert delayed == ['input','output'] and len(budgets) == 2
    assert 1 < budgets[1][1] < budgets[0][1] <= 5
    assert audit['dispatch']['review_action_durable'] is True


@pytest.mark.parametrize('defect',['missing','wal','giant_row','state','bytes'])
def test_independent_original_reread_rejects_wrong_store_without_schema_or_artifact_write(runtime,defect):
    import sqlite3,time
    initialization,value,custody = input_chain(runtime,fresh.CASES[0])
    if defect == 'missing':(runtime.root/'objectives.db').unlink()
    elif defect == 'wal':(runtime.root/'objectives.db-wal').write_bytes(b'x'*(8*1024*1024+1))
    elif defect in ('giant_row','state'):
        with sqlite3.connect(runtime.root/'objectives.db') as db:
            if defect == 'giant_row':db.execute('UPDATE objectives SET objective_hash=? WHERE id=?',('x'*2_000_000,custody['dispatch']['task_id']))
            else:db.execute('UPDATE objectives SET state=? WHERE id=?',('dispatching',custody['dispatch']['task_id']))
    else:(runtime.root/'artifacts'/custody['artifact_metadata']['artifact_id']/'artifact.json').write_bytes(b'wrong')
    before = {p.name:p.read_bytes() for p in runtime.root.glob('objectives.db*') if p.is_file()}
    artifacts = {str(p.relative_to(runtime.root)):p.read_bytes() for p in (runtime.root/'artifacts').rglob('*') if p.is_file()}
    with pytest.raises(ValueError):fresh.read_original_proof(runtime.root,custody,initialization['runtime'],runtime.registry_sha,deadline=time.monotonic()+1)
    assert {p.name:p.read_bytes() for p in runtime.root.glob('objectives.db*') if p.is_file()} == before
    assert {str(p.relative_to(runtime.root)):p.read_bytes() for p in (runtime.root/'artifacts').rglob('*') if p.is_file()} == artifacts


@pytest.mark.parametrize('defect',['unauthenticated','wrong_role','source','prior_answer','spend','model_format'])
def test_actual_scoped_audit_rejects_authority_or_answer_expansion_before_read(runtime,defect):
    initialization,value,custody = input_chain(runtime,fresh.CASES[0])
    body = fresh.stage_request('audit',fresh.CASES[0],custody,runtime.registry_sha,str(uuid.uuid4()))
    headers = {'Authorization':'Bearer '+TOKEN}
    if defect == 'unauthenticated':headers = {}
    elif defect == 'wrong_role':body['capability'] = 'responsibility.a19'
    elif defect in ('source','prior_answer'):
        context = json.loads(body['context'])
        if defect == 'source':context['registry_sha256'] = '0'*64
        else:context['prior_answer'] = 'PASS'
        body['context'] = fresh.canonical(context).decode()
    elif defect == 'spend':body['max_cost_usd'] = 1.0
    else:body['response_format'] = 'text'
    before = runtime.ledger.status()['persisted'],set((runtime.root/'artifacts').iterdir())
    reply = runtime.client.post('/api/agents/objectives',json=body,headers=headers)
    assert reply.status_code in (401,403,422) or (reply.status_code == 202 and reply.json()['steps'][0]['state'] == 'blocked')
    assert (runtime.ledger.status()['persisted'],set((runtime.root/'artifacts').iterdir())) == before


def test_actual_final_artifact_cannot_reset_exhausted_original_audit_budget(runtime,monkeypatch):
    import time
    from app.artifact_factory import ArtifactFactory
    initialization,value,custody = input_chain(runtime,fresh.CASES[0])
    create = ArtifactFactory.create;writes = []
    def delayed(self,*args,**kwargs):
        metadata = create(self,*args,**kwargs)
        if json.loads(kwargs['content']).get('schema_version') == fresh.SCHEMAS['audit']:
            writes.append(metadata['artifact_id']);time.sleep(5.1)
        return metadata
    monkeypatch.setattr(ArtifactFactory,'create',delayed)
    body = fresh.stage_request('audit',fresh.CASES[0],custody,runtime.registry_sha,str(uuid.uuid4()))
    reply = runtime.client.post('/api/agents/objectives',json=body,headers={'Authorization':'Bearer '+TOKEN})
    assert reply.status_code == 202 and reply.json()['steps'][0]['state'] == 'blocked'
    assert len(writes) == 1 and (runtime.root/'artifacts'/writes[0]/'artifact.json').is_file()


def test_actual_failed_final_fsync_is_not_claimed_durable(runtime,monkeypatch):
    import os,threading
    from app import agent_dispatch_api
    from app.action_records import ActionLedger
    initialization,value,custody = input_chain(runtime,fresh.CASES[0])
    execute,fsync = fresh.execute,os.fsync;writers = [];failures = [];selected = [runtime.ledger]
    # Dispatch imports the provider at entry. Keep that provider stable while
    # switching its selected disposable writer only after genuine input flush.
    monkeypatch.setattr(agent_dispatch_api,'action_ledger',lambda:selected[0])
    def faulty_writer(*args,**kwargs):
        data = execute(*args,**kwargs)
        writer = ActionLedger(runtime.ledger.path);writers.append(writer)
        selected[0] = writer
        return data
    def failed(fd):
        if writers and threading.current_thread() is writers[0].worker:
            failures.append(fd);raise OSError('Disposable execution-input final writer fault')
        return fsync(fd)
    monkeypatch.setattr(fresh,'execute',faulty_writer)
    monkeypatch.setattr(os,'fsync',failed)
    try:
        reply = runtime.client.post('/api/agents/objectives',json=fresh.stage_request('audit',fresh.CASES[0],
            custody,runtime.registry_sha,str(uuid.uuid4())),headers={'Authorization':'Bearer '+TOKEN})
    finally:
        assert len(writers) == 1 and writers[0].close() is False and not writers[0].worker.is_alive()
    assert reply.status_code == 202 and reply.json()['steps'][0]['state'] == 'blocked'
    assert failures and writers[0].status()['dropped'] > 0 and runtime.ledger.status()['healthy'] is True


@pytest.mark.parametrize('defect',['oversize','aggregate','junction'])
def test_native_shared_memory_guard_rejects_before_sqlite_open(runtime,monkeypatch,defect):
    import os,sqlite3,time,subprocess
    initialization,value,custody = input_chain(runtime,fresh.CASES[0])
    sidecar = runtime.root/'objectives.db-shm';sentinel = None
    if defect == 'junction':
        if os.name != 'nt':pytest.skip('Windows native junction negative')
        target = runtime.root.parent/(runtime.root.name+'-outside-shm')
        target.mkdir();sentinel = target/'untouched.txt';sentinel.write_bytes(b'Never traverse this original-store sidecar')
        made = subprocess.run(['cmd','/c','mklink','/J',str(sidecar),str(target)],capture_output=True)
        assert made.returncode == 0,made.stderr.decode(errors='replace')
        assert sidecar.is_dir()
    else:
        size = 8*1024*1024+1 if defect == 'oversize' else 8*1024*1024-(runtime.root/'objectives.db').stat().st_size+1
        sidecar.write_bytes(b'x'*size)
        if defect == 'aggregate':assert sidecar.stat().st_size < 8*1024*1024
    original = (runtime.root/'objectives.db').read_bytes();calls = []
    def forbidden(*args,**kwargs):calls.append(args);pytest.fail('Native guard opened SQLite before rejecting SHM')
    monkeypatch.setattr(sqlite3,'connect',forbidden)
    with pytest.raises(ValueError):fresh.read_original_proof(runtime.root,custody,initialization['runtime'],
        runtime.registry_sha,deadline=time.monotonic()+1)
    assert calls == [] and (runtime.root/'objectives.db').read_bytes() == original
    if sentinel is not None:assert sentinel.read_bytes() == b'Never traverse this original-store sidecar'
