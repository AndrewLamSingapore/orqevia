"""Local persistence/permission checks; not live agent certification."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import pytest
from app.collective_workspace import CollectiveWorkspace, BOARDS, Conflict


@pytest.fixture
def store(tmp_path):
    return CollectiveWorkspace(tmp_path/'workspace.db')


def test_22_principals_have_separate_durable_sketches(store):
    assert len(store.principals)==22 and 'prime' in store.principals
    for actor in sorted(store.principals):
        assert store.write_sketch(actor,actor,'checkpoint',{'summary':actor},checkpoint=True)==1
    reopened=CollectiveWorkspace(store.path)
    for actor in store.principals:
        assert reopened.read_sketch(actor,actor,'checkpoint')['note']=={'summary':actor}
    assert len(BOARDS)==10


@pytest.mark.parametrize('actor,owner',[('prime','a01'),('a01','prime'),('a01','a02'),('unregistered','a01')])
def test_private_cross_owner_denial(store,actor,owner):
    for operation in (lambda:store.read_sketch(actor,owner,'x'),lambda:store.search_sketch(actor,owner),lambda:store.write_sketch(actor,owner,'x',{'summary':'x'})):
        with pytest.raises(PermissionError):operation()


def test_revisions_checkpoint_search_archive_keep_history(store):
    store.write_sketch('a01','a01','x',{'summary':'original failure'})
    store.write_sketch('a01','a01','x',{'summary':'reassessment'},expected_revision=1,archived=True,checkpoint=True)
    assert store.search_sketch('a01','a01')==[]
    assert store.search_sketch('a01','a01','reassess',include_archived=True)[0]['revision']==2
    assert store.read_sketch('a01','a01','x',revision=1)['note']['summary']=='original failure'
    with pytest.raises(Conflict):store.write_sketch('a01','a01','x',{'summary':'stale'},expected_revision=1)


def test_concurrent_compare_and_swap_has_one_winner(store):
    store.write_sketch('a01','a01','x',{'summary':'base'})
    def update(i):
        try:return store.write_sketch('a01','a01','x',{'summary':str(i)},expected_revision=1)
        except Conflict:return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(update,range(2)))
    assert sorted(map(str,results))==['2','conflict']


@pytest.mark.parametrize('text',['password=not-real','API_KEY: fake','Bearer fake-not-a-token','hf_abcdefghijkl','sk-abcdefghijk','ghp_abcdefghijk','-----BEGIN RSA PRIVATE KEY-----','https://user:pass@example.test','eyJabc.def.ghi','chain of thought','raw user message','{"password":"fake"}','pass\u200bword=fake','ｐａｓｓｗｏｒｄ=fake'])
def test_secret_and_unstructured_payload_rejection(store,text):
    with pytest.raises(ValueError):store.write_sketch('prime','prime','x',{'summary':text})
    with pytest.raises(ValueError):store.post('prime','GLOBAL','x',{'summary':text})
    with store.connect() as db:assert db.execute('select count(*) from audit').fetchone()[0]==0


def test_schema_minimization_and_evidence_label_no_truth_promotion(store):
    for note in ({'raw_prompt':'x'},{'thoughts':'x'},{'summary':[]},{'evidence_level':'verified_fact'},{'evidence_refs':['https://example.test']}):
        with pytest.raises(ValueError):store.write_sketch('a01','a01','x',note)
    store.write_sketch('a01','a01','x',{'summary':'observed test','evidence_level':'verified_fact','evidence_refs':['receipt:123']})
    assert store.read_sketch('a01','a01','x')['note']['evidence_level']=='verified_fact'
    with pytest.raises(ValueError):store.write_sketch('a01','a01','hf_abcdefghijkl',{'summary':'safe'})


def test_board_idempotency_conflict_replay_ack_and_threads(store):
    store.subscribe('a02','ENGINEERING');store.subscribe('prime','ENGINEERING')
    note={'summary':'implementation result','task_refs':['task:1'],'evidence_refs':['receipt:1']}
    message=store.post('a01','ENGINEERING','key',note,thread='task:1')
    assert store.post('a01','ENGINEERING','key',note,thread='task:1')==message
    with pytest.raises(Conflict):store.post('a01','ENGINEERING','key',{'summary':'changed'},thread='task:1')
    reopened=CollectiveWorkspace(store.path)
    assert reopened.pending('a02')[0]['id']==message
    with pytest.raises(PermissionError):reopened.acknowledge('a03',message)
    reopened.acknowledge('a02',message);reopened.acknowledge('a02',message)
    assert reopened.pending('a02')==[] and len(reopened.pending('prime'))==1
    assert reopened.messages('a02','ENGINEERING',thread='other')==[]
    assert len(reopened.messages('a02','ENGINEERING',thread='task:1'))==1
    with pytest.raises(PermissionError):reopened.archive_message('prime',message)
    reopened.archive_message('a01',message)
    assert reopened.messages('a02','ENGINEERING')==[]
    assert len(reopened.messages('a02','ENGINEERING',include_archived=True))==1


def test_mid_transaction_exception_rolls_back_message_deliveries_and_audit(store,monkeypatch):
    store.subscribe('a02','GLOBAL')
    def broken(*args):raise RuntimeError('injected audit failure')
    monkeypatch.setattr(store,'log',broken)
    with pytest.raises(RuntimeError):store.post('a01','GLOBAL','key',{'summary':'bounded'})
    assert store.messages('a01','GLOBAL')==[] and store.pending('a02')==[]
    with store.connect() as db:assert db.execute('select count(*) from audit').fetchone()[0]==1


def test_task_lease_expiry_retry_backoff_three_attempts_restart(store):
    now=[100.0];store.clock=lambda:now[0]
    store.assign('prime','task:1','a17',{'summary':'implement bounded task'})
    with pytest.raises(PermissionError):store.claim('a18','task:1')
    token=store.claim('a17','task:1',lease_seconds=1)
    with pytest.raises(Conflict):store.claim('a17','task:1')
    now[0]+=2
    with pytest.raises(Conflict):store.transition('a17','task:1',token,'DONE',{'summary':'late'})
    token=store.claim('a17','task:1')
    store.transition('a17','task:1',token,'RETRY',{'failure':'original second failure'})
    reopened=CollectiveWorkspace(store.path,clock=lambda:now[0])
    with pytest.raises(Conflict):reopened.claim('a17','task:1')
    now[0]+=31;token=reopened.claim('a17','task:1')
    reopened.transition('a17','task:1',token,'RETRY',{'failure':'third failure'})
    assert reopened.task('a17','task:1')['state']=='BLOCKED'
    with pytest.raises(Conflict):reopened.claim('a17','task:1')
    assert [r['note'] for r in reopened.task_history('prime','task:1') if r['state']=='RETRY']==[{'failure':'original second failure'}]


def test_shutdown_handoff_invalidates_old_lease_and_does_not_complete(store):
    store.assign('prime','task:1','a17',{'summary':'work'})
    token=store.claim('a17','task:1');assert store.shutdown('a17')==['task:1']
    assert store.task('prime','task:1')['state']=='HANDOFF'
    with pytest.raises(Conflict):store.transition('a17','task:1',token,'DONE',{'summary':'wrong'})
    reopened=CollectiveWorkspace(store.path);token=reopened.claim('a17','task:1')
    reopened.transition('a17','task:1',token,'HANDOFF',{'summary':'verification needed'},handoff_to='a15')
    token=reopened.claim('a15','task:1')
    reopened.transition('a15','task:1',token,'DONE',{'summary':'verified','evidence_refs':['receipt:1']})
    assert reopened.task('prime','task:1')['state']=='DONE'
    assert reopened.shutdown('a15')==[]


def test_bounds_archive_not_delete_and_safe_audit(store):
    bounded=CollectiveWorkspace(store.path,max_records=1)
    bounded.write_sketch('a01','a01','x',{'summary':'safe'})
    with pytest.raises(ValueError):bounded.write_sketch('a01','a01','y',{'summary':'over budget'})
    assert bounded.read_sketch('a01','a01','y') is None
    assert 'content' not in bounded.audit('a01')[0]
    assert bounded.audit('prime')==[]
    with pytest.raises(ValueError):bounded.subscribe('a01','unknown')
    with pytest.raises(ValueError):bounded.post('a01','GLOBAL','bad\nkey',{'summary':'safe'})


def test_concurrent_duplicate_posts_deliver_once_and_database_integrity(store):
    store.subscribe('a02','GLOBAL')
    def publish(_):return store.post('prime','GLOBAL','same',{'summary':'bounded public work note'})
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(publish,range(2)))
    assert results[0]==results[1]
    assert len(store.pending('a02'))==1
    with store.connect() as db:
        assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
        assert db.execute('pragma foreign_key_check').fetchall()==[]


def test_explicit_owner_engineering_fields_roundtrip_and_bounded_types(store):
    note={'objective':'bounded change','decomposition':['inspect','implement'],
          'hypotheses':[{'claim':'parser mismatch','status':'unverified'}],
          'assumptions':['public fixture'],'plans':{'primary':['test']},
          'alternatives':['retain existing implementation'],'calculations':{'expected_count':21},
          'analysis':{'observed_count':15,'missing':None},'tool_results':[{'tool':'pytest','exit':0}],
          'experiments':[{'name':'replay','passed':True}], 'questions':['root cause?'],
          'dependencies':['task:1'],'next_actions':['retest'],'confidence':0.75,
          'uncertainty':0.25,'completion_criteria':['unchanged assertions pass']}
    store.write_sketch('prime','prime','plan',note)
    assert CollectiveWorkspace(store.path).read_sketch('prime','prime','plan')['note']==note


@pytest.mark.parametrize('note',[
    {'confidence':True},{'confidence':1.1},{'uncertainty':-0.1},
    {'uncertainty':float('nan')},{'calculations':float('inf')},
    {'analysis':{'a':{'b':{'c':{'d':{'e':1}}}}}},
    {'plans':['step']*33},{'analysis':{'value':'x'*4001}},
    {'analysis':{'raw_prompt':'user secret'}},{'tool_results':[{'hidden_reasoning':'x'}]},
    {'tool_results':[{'access_token':'fake-secret'}]},
    {'experiments':[{'output':'Bearer fake-token'}]},
    {'analysis':{'a':'x'*4000,'b':'x'*4000,'c':'x'*4000,'d':'x'*4000}}])
def test_engineering_bounds_hidden_input_and_nested_secrets_rejected(store,note):
    with pytest.raises(ValueError):store.write_sketch('a17','a17','analysis',note)
    assert store.read_sketch('a17','a17','analysis') is None


def test_assignment_edges_and_core_separate_coordination(store):
    store.assign('a15','implementation','a17',{'objective':'implement'})
    store.assign('a17','own-task','a17',{'objective':'self work'})
    for actor in store.principals:
        store.assign('prime','core-'+actor,actor,{'objective':'coordinate'})
    for actor,target in [('a17','a18'),('a01','a17'),('a15','a28'),('a17','prime')]:
        with pytest.raises(PermissionError):store.assign(actor,'illegal-'+actor+'-'+target,target,{'summary':'illegal'})
    assert store.task('prime','core-prime')['assigned']=='prime'


def test_handoff_denial_cycle_and_allowed_escalation_preserves_original(store):
    store.assign('a15','task:cycle','a15',{'objective':'implementation'})
    lead_token=store.claim('a15','task:cycle')
    store.transition('a15','task:cycle',lead_token,'HANDOFF',{'next_action':'implement'},handoff_to='a17')
    child_token=store.claim('a17','task:cycle')
    with pytest.raises(PermissionError):store.transition('a17','task:cycle',child_token,'HANDOFF',{'summary':'peer'},handoff_to='a18')
    with pytest.raises(Conflict):store.transition('a17','task:cycle',child_token,'HANDOFF',{'summary':'return'},handoff_to='a15')
    assert store.task('a17','task:cycle')['state']=='RUNNING'
    assert len(store.task_history('a15','task:cycle'))==4
    store.assign('prime','task:escalate','a17',{'objective':'bounded'})
    token=store.claim('a17','task:escalate')
    store.transition('a17','task:escalate',token,'HANDOFF',{'failure':'needs coordination'},handoff_to='prime')
    assert store.task('prime','task:escalate')['state']=='HANDOFF'
