"""Temporary owned-domain events; source validation only, never L7 evidence."""
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import agent_dispatch_api as dispatch, agent_registry
from app.action_records import ActionLedger
from app.agent_cert_owned_context import canonical_owned_context_case
def challenge(case,*,agent_id,capability_id):
    assert case=='baseline:context'
    return canonical_owned_context_case(agent_id,capability_id)
from app.agent_cert_execution import observe_cert_case
from app.agent_cert_owned_context import (
    ACTION_TYPE, SCHEMA, MAX_AGE_SECONDS, context_reviewer,
    context_review_objective, validate_owned_context_execution,
    validate_context_report, OwnedContextError,
)
from app.agent_cert_initialization import canonical, sha
from app.agent_cert_identity_review import action_span, utc
from app.artifact_factory import ArtifactFactory
from tests.test_agent_cert_review_dispatch import configured, SOURCE, IMAGE, NONCE

PAIRS = [(a['id'], c) for a in agent_registry.load_agent_registry()['agents']
         for c in a['capability_requirements']]


@pytest.fixture
def events(configured, monkeypatch):
    from app import compute_queue_api, objective_api
    compute_queue_api.queue.policy = SimpleNamespace(global_concurrency=1)
    ledger = ActionLedger(configured.root / 'action-records.jsonl')
    monkeypatch.setattr(dispatch, 'action_ledger', lambda: ledger)

    def produce(pair):
        actor, capability = pair
        value = {'case_spec': challenge('baseline:context', agent_id=actor, capability_id=capability),
                 'runtime': objective_api.runtime_snapshot()}
        def submit(request):
            reply = objective_api.submit(objective_api.ObjectiveRequest(**request), 'fixture-owner')
            value['submission'] = [202, reply]
            value['dispatch'] = reply['steps'][0]['dispatch']
            return value['dispatch']
        def artifact(key):
            metadata, raw = ArtifactFactory(configured.root / 'artifacts').retrieve(key)
            value['artifact_metadata'] = metadata
            value['artifact_content_utf8'] = raw.decode()
            return metadata, raw
        value['observation'] = observe_cert_case(value['case_spec'], dispatch=submit,
            get_job=lambda _: pytest.fail('Zero-model contract check cannot read queue jobs'),
            get_artifact=artifact, get_runtime=objective_api.runtime_snapshot,
            expected_source_revision=SOURCE,
            expected_registry_sha256=sha(agent_registry.REGISTRY_PATH.read_bytes()), timeout_seconds=5)
        assert value['observation']['state'] == 'EXECUTED',value['observation']
        task = value['dispatch']['task_id']
        value['objective_read'] = [200, objective_api.get_read_only(task, 'fixture-owner')]
        assert ledger.flush(timeout=1)
        value['action_records'] = [line for line in ledger.path.read_text().splitlines(keepends=True) if json.loads(line)['action_type']==ACTION_TYPE and json.loads(line)['task_id']==task]
        value['action_chain_join'] = action_span(value['action_records'], task_id=task,
            agent_id=actor, action_type=ACTION_TYPE, schema=SCHEMA,
            metadata=value['artifact_metadata'], began=utc(value['observation']['started_at']),
            ended=utc(value['observation']['completed_at']))
        return json.loads(canonical(value))
    yield SimpleNamespace(produce=produce, root=configured.root, ledger=ledger)
    ledger.close()


def validate(value, now=None, **pins):
    pins.setdefault('agent_id', value['case_spec']['agent_id'])
    pins.setdefault('capability_id', value['case_spec']['capability_id'])
    return validate_owned_context_execution(value, source_revision=SOURCE, runtime_image_id=IMAGE,
        registry_sha256=sha(agent_registry.REGISTRY_PATH.read_bytes()),
        now=now or datetime.now(timezone.utc), **pins)


def review_request(value, **changes):
    actor, cap = context_reviewer(value['case_spec']['agent_id'], value['case_spec']['capability_id'])
    payload = dict(execution=value, expected_execution_sha256=sha(canonical(value)),
                   expected_source_revision=SOURCE, review_nonce=NONCE)
    request = dict(capability=cap, objective=context_review_objective(
        value['case_spec']['agent_id'], value['case_spec']['capability_id']),
        context=canonical(payload).decode(), priority='low', minimum_tier='NANO',
        task_class='classification', response_format='strict_json',
        deterministic_operation='certification_owned_context_review')
    return dispatch.AgentRequest(**{**request, **changes})


@pytest.mark.parametrize('pair', PAIRS)
def test_all_owned_pairs_join_original_domains_and_independent_peer(events, pair):
    assert len(PAIRS) == 29 and len(set(PAIRS)) == 29
    value = events.produce(pair)
    joined = validate(value)
    assert joined['task_id'] == value['dispatch']['task_id']
    report = json.loads(value['artifact_content_utf8'])
    assert (report['agent_id'], report['capability_id']) == pair
    assert report['execution']['model_calls'] == 0 and report['certification'] == 'UNVERIFIED'
    result = dispatch.dispatch_request(review_request(value), 'fixture-owner')
    assert (result['agent_id'], result['capability']) == context_reviewer(*pair)
    assert result['certification'] == 'UNVERIFIED' and result['review_action_durable'] is True
    _, raw = ArtifactFactory(events.root / 'artifacts').retrieve(result['artifact']['artifact_id'])
    review = json.loads(raw)
    assert review['test_result'] == 'PASS' and review['subject_agent_id'] == pair[0]
    assert review['subject_domain_join']['task_id'] == joined['task_id']


def test_authentication_denies_producer_and_reviewer(events):
    spec = challenge('baseline:context', agent_id='a02', capability_id='responsibility.a03')
    with pytest.raises(HTTPException) as exc:
        dispatch.dispatch_request(dispatch.AgentRequest(**spec['request']), 'unauthorized')
    assert exc.value.status_code == 401
    value = events.produce(('a02', 'responsibility.a03'))
    with pytest.raises(HTTPException) as exc:
        dispatch.dispatch_request(review_request(value), 'unauthorized')
    assert exc.value.status_code == 401


@pytest.mark.parametrize('mutation', ['artifact', 'objective', 'actions', 'runtime', 'pair'])
def test_custody_tamper_is_rejected(events, mutation):
    value = events.produce(('a02', 'responsibility.a03'))
    if mutation == 'artifact':
        value['artifact_content_utf8'] = value['artifact_content_utf8'].replace('UNVERIFIED', 'CERTIFIED')
    elif mutation == 'objective':
        value['objective_read'][1]['execution_metadata']['runtime']['source_revision'] = 'f' * 40
    elif mutation == 'actions':
        value['action_records'][-1] = value['action_records'][-1].replace('completed', 'failed')
    elif mutation == 'runtime':
        value['runtime']['source_revision'] = 'f' * 40
    else:
        value['case_spec']['capability_id'] = 'responsibility.a02'
    with pytest.raises(ValueError):
        validate(value)


def test_future_and_expired_report_rejected(events):
    value = events.produce(('a26', 'responsibility.a25'))
    assert context_reviewer('a26', 'responsibility.a25') == ('a18', 'responsibility.a27')
    report = json.loads(value['artifact_content_utf8'])
    captured = datetime.fromisoformat(report['captured_at'])
    pins = dict(task_id=report['task_id'], agent_id='a26', capability_id='responsibility.a25',
        runtime=value['runtime'], source_revision=SOURCE, runtime_image_id=IMAGE,
        registry_sha256=sha(agent_registry.REGISTRY_PATH.read_bytes()))
    for now in [captured - timedelta(seconds=1), captured + timedelta(seconds=MAX_AGE_SECONDS + 1)]:
        with pytest.raises(OwnedContextError, match='TIME_UNBOUND'):
            validate_context_report(value['artifact_content_utf8'], now=now, **pins)
    with pytest.raises(ValueError):
        validate(value, now=captured + timedelta(seconds=MAX_AGE_SECONDS + 1))


@pytest.mark.parametrize('pin', ['source_revision', 'runtime_image_id', 'registry_sha256'])
def test_wrong_protected_pin_rejected(events, pin):
    value = events.produce(('a02', 'responsibility.a03'))
    pins = dict(agent_id='a02', capability_id='responsibility.a03', source_revision=SOURCE,
        runtime_image_id=IMAGE, registry_sha256=sha(agent_registry.REGISTRY_PATH.read_bytes()),
        now=datetime.now(timezone.utc))
    pins[pin] = {'source_revision': 'f' * 40, 'runtime_image_id': 'sha256:' + 'f' * 64,
                 'registry_sha256': 'f' * 64}[pin]
    with pytest.raises(ValueError):
        validate_owned_context_execution(value, **pins)


def test_producer_task_replay_and_wrong_peer_rejected(events):
    value = events.produce(('a26', 'responsibility.a25'))
    with pytest.raises(HTTPException):
        dispatch.dispatch_request(review_request(value, capability='responsibility.a26'), 'fixture-owner')
    request = review_request(value)
    dispatch.dispatch_request(request, 'fixture-owner')
    from app.agent_cert_owned_context import execute_owned_context_case
    with pytest.raises((ValueError,HTTPException)):
        execute_owned_context_case(value['case_spec'], value['dispatch']['task_id'],
            submitted_request=value['case_spec']['request'], data_root=events.root,
            ledger=events.ledger, runtime=value['runtime'], read_runtime=lambda: value['runtime'],
            source_revision=SOURCE, runtime_image_id=IMAGE,
            registry_sha256=sha(agent_registry.REGISTRY_PATH.read_bytes()))


@pytest.mark.parametrize('original_domain',['objective','raw_objective_hash','artifact','input','ledger'])
def test_distinct_peer_final_reread_rejects_original_store_drift(events,monkeypatch,original_domain):
    from app import objective_api
    value=events.produce(('a26','responsibility.a26'))
    real=objective_api.get_read_only;reads=[]
    def changed(task,authorization):
        reads.append(task)
        if len(reads)==2:
            if original_domain=='input':
                metadata=json.loads(value['artifact_content_utf8'])['input_artifact_metadata']
                path=events.root/'artifacts'/metadata['artifact_id']/'artifact.json'
                path.write_bytes(path.read_bytes()+b' ')
            elif original_domain=='artifact':
                path=events.root/'artifacts'/value['artifact_metadata']['artifact_id']/'artifact.json'
                path.write_bytes(path.read_bytes()+b' ')
            elif original_domain=='ledger':
                path=events.ledger.path;path.write_bytes(path.read_bytes().replace(ACTION_TYPE.encode(),b'forged.contract'))
            else:
                import sqlite3
                with sqlite3.connect(events.root/'objectives.db') as db:
                    if original_domain=='raw_objective_hash':db.execute("UPDATE objectives SET objective_hash='forged' WHERE id=?",(task,))
                    else:db.execute("UPDATE objective_metadata SET updated_at='2000-01-01T00:00:00+00:00' WHERE task=?",(task,))
        return real(task,authorization)
    monkeypatch.setattr(objective_api,'get_read_only',changed)
    before=events.ledger.status()['persisted'],set((events.root/'artifacts').iterdir())
    with pytest.raises(HTTPException):dispatch.dispatch_request(review_request(value),'fixture-owner')
    assert len(reads)==2 and (events.ledger.status()['persisted'],set((events.root/'artifacts').iterdir()))==before

@pytest.mark.parametrize('fault',['boundary','health','unsupported'])
def test_corrupt_producer_independent_oracle_rejects(events,monkeypatch,fault):
 from app import agent_cert_owned_context as module
 original=module.select_context
 def changed(raw):
  result=original(raw)
  if fault=='boundary':result['sample_age_seconds']=[299]
  elif fault=='health':result['observed_sample_health']=['FAIL']
  else:result['continuous_health']='PASS'
  return result
 monkeypatch.setattr(module,'select_context',changed)
 with pytest.raises((ValueError,HTTPException,AssertionError)):
  events.produce(('a02','responsibility.a03'))


def test_healthy_writer_can_drain_within_shared_remaining_budget(events,monkeypatch):
 import time
 original=ActionLedger.flush;budgets=[]
 def delayed(self,timeout=5):
  budgets.append(timeout)
  if len(budgets)==1:time.sleep(1.05)
  return original(self,timeout=max(0.01,timeout-1.05) if len(budgets)==1 else timeout)
 monkeypatch.setattr(ActionLedger,'flush',delayed)
 value=events.produce(('a02','responsibility.a03'))
 validate(value)
 assert 1<budgets[0]<=5 and 0<budgets[1]<budgets[0]

@pytest.mark.parametrize('failure',['exhausted','writer'])
def test_shared_budget_exhaustion_and_failed_writer_fail_closed(events,monkeypatch,failure):
 from app import agent_cert_owned_context as module
 from types import SimpleNamespace
 if failure=='writer':monkeypatch.setattr(ActionLedger,'flush',lambda self,timeout=5:False)
 else:
  clock=[0.0];original=ActionLedger.flush
  def exhausted(self,timeout=5):
   result=original(self,timeout);clock[0]=6.0;return result
  monkeypatch.setattr(module,'time',SimpleNamespace(monotonic=lambda:clock[0]))
  monkeypatch.setattr(ActionLedger,'flush',exhausted)
 with pytest.raises((ValueError,HTTPException,AssertionError)):
  events.produce(('a02','responsibility.a03'))


@pytest.mark.parametrize('fault',['boundary','health','unsupported'])
def test_peer_oracle_rejects_wrong_assessment_from_intact_original_bytes(events,fault):
 value=events.produce(('a02','responsibility.a03'));report=json.loads(value['artifact_content_utf8'])
 if fault=='boundary':report['assessment']['sample_age_seconds']=[299]
 elif fault=='health':report['assessment']['observed_sample_health']=['FAIL']
 else:report['assessment']['root_cause']='known'
 pins=dict(task_id=report['task_id'],agent_id='a02',capability_id='responsibility.a03',
  runtime=value['runtime'],source_revision=SOURCE,runtime_image_id=IMAGE,
  registry_sha256=sha(agent_registry.REGISTRY_PATH.read_bytes()),now=datetime.now(timezone.utc))
 with pytest.raises(OwnedContextError,match='CONTEXT_REPORT_DRIFT'):
  validate_context_report(canonical(report),**pins)


@pytest.mark.parametrize('field',['actor','expected_digest','tool','result_digest'])
def test_original_read_bindings_are_mandatory(events,field):
 value=events.produce(('a02','responsibility.a03'));report=json.loads(value['artifact_content_utf8'])
 rows=[json.loads(line) for line in report['read_action_records']]
 if field=='actor':rows[0]['agent_id']='a03'
 elif field=='expected_digest':rows[0]['parameters_summary']['expected_sha256']='f'*64
 elif field=='tool':rows[0]['tool']='ambient.telemetry'
 else:rows[1]['result_summary']['source_sha256']='f'*64
 report['read_action_records']=[canonical(row).decode()+'\n' for row in rows]
 with pytest.raises(OwnedContextError,match='CONTEXT_READ_UNBOUND'):
  validate_context_report(canonical(report),task_id=report['task_id'],agent_id='a02',capability_id='responsibility.a03',
   runtime=value['runtime'],source_revision=SOURCE,runtime_image_id=IMAGE,
   registry_sha256=sha(agent_registry.REGISTRY_PATH.read_bytes()),now=datetime.now(timezone.utc))



def test_original_input_folder_with_extra_entries_rejected_before_review_artifact(events):
 value=events.produce(('a02','responsibility.a03'))
 metadata=json.loads(value['artifact_content_utf8'])['input_artifact_metadata']
 folder=events.root/'artifacts'/metadata['artifact_id']
 (folder/'unexpected.json').write_bytes(b'{}')
 before=set((events.root/'artifacts').iterdir())
 with pytest.raises(HTTPException):dispatch.dispatch_request(review_request(value),'fixture-owner')
 assert set((events.root/'artifacts').iterdir())==before
