"""Fixed input-only A26 source audit, never prior-answer or service access."""
from datetime import datetime, timezone
import time
import re

from .agent_cert_artifact_events import canonical, parse, sha, _path, _metadata, _utc, _uuid, _ledger_lines
from .agent_cert_tool_events import require, independent_verifier_binding, read_cross_peer_request

CASE = 'clean_room_audit:complete'
SCHEMA = 'prime.a26-clean-room-input-audit.v1'
INPUT_READ_ACTION = 'agent.certification.clean_room.input_read'
OBJECTIVE = ('Independently reproduce a bounded resilience conclusion from only the original labelled public '
    'input artifact. This fresh audit task receives no prior producer answer, answer artifact identifier, '
    'expected answer digest or primary execution envelope. Read only the fixed supplied input artifact, '
    'derive the API failure ratio and uncertainty independently, and commit this input-only audit before '
    'any separate comparison task sees the producer answer. Do not confirm current health, execute, certify, '
    'sign, transfer authority or use a model.')


def reproduce_input(raw):
    """Input-only independent arithmetic: no producer builder or answer argument."""
    from .agent_cert_tool_events import input_bytes
    require(type(raw) is bytes and raw == input_bytes(CASE),'BLIND_ORIGINAL_INPUT_REQUIRED')
    observation = parse(raw)['known_observation']
    checks,failed = observation['api_checks'],observation['api_failures']
    require(type(checks) is int and type(failed) is int and checks > 0 and 0 <= failed <= checks
        and observation['later_samples'] == [] and observation['dependencies_observed'] is False,
        'BLIND_ORIGINAL_COUNTS_INVALID')
    quotient,remainder = divmod(failed*10000,checks)
    return dict(service_id=observation['service_id'],window_id=observation['window_id'],
        api_checks=checks,api_failures=failed,api_failure_basis_points=quotient,
        ratio_remainder=remainder,assessment_scope='SUPPLIED_API_WINDOW_ONLY',
        recovery='NOT_PROVEN',current_health='UNKNOWN',dependencies='UNKNOWN')


def grade_original_input(raw):
    """Independent final oracle, never the A19 or blind-auditor producer."""
    from fractions import Fraction
    from .agent_cert_tool_events import input_bytes
    require(type(raw) is bytes and raw == input_bytes(CASE),'BLIND_ORIGINAL_INPUT_REQUIRED')
    observation = parse(raw)['known_observation']
    checks,failed = observation['api_checks'],observation['api_failures']
    require(type(checks) is int and type(failed) is int and checks > 0 and 0 <= failed <= checks
        and observation['later_samples'] == [] and observation['dependencies_observed'] is False,
        'BLIND_ORIGINAL_COUNTS_INVALID')
    scaled = int(Fraction(failed,checks)*10000)
    return dict(service_id=observation['service_id'],window_id=observation['window_id'],
        api_checks=checks,api_failures=failed,api_failure_basis_points=scaled,
        ratio_remainder=failed*10000-checks*scaled,assessment_scope='SUPPLIED_API_WINDOW_ONLY',
        recovery='NOT_PROVEN',current_health='UNKNOWN',dependencies='UNKNOWN')


def request_body(metadata,source,registry,nonce):
    return dict(classification='R0',capability='responsibility.a26',objective=OBJECTIVE,
        context=canonical(dict(case=CASE,input_artifact_metadata=metadata,expected_source_revision=source,
            expected_registry_sha256=registry,review_nonce=nonce)).decode(),data_classification='LOCAL_ONLY',
        minimum_tier='NANO',priority='low',task_class='classification',max_cost_usd=0.0,
        preferred_provider=None,response_format='strict_json',deterministic_operation='certification_tool_review')


def admit_request(body,*,runtime,registry,metadata=None):
    value = body.model_dump() if hasattr(body,'model_dump') else body
    require(type(value) is dict and type(value.get('context')) is str,'BLIND_INPUT_ONLY_REQUEST_REQUIRED')
    envelope = parse(value['context'].encode())
    require(set(envelope) == {'case','input_artifact_metadata','expected_source_revision',
        'expected_registry_sha256','review_nonce'} and envelope['case'] == CASE
        and envelope['expected_source_revision'] == runtime['source_revision']
        and envelope['expected_registry_sha256'] == registry and _uuid(envelope['review_nonce']),
        'BLIND_INPUT_ONLY_REQUEST_REQUIRED')
    original = envelope['input_artifact_metadata']
    require(type(original) is dict and _uuid(original.get('task_id'))
        and type(original.get('artifact_id')) is str and re.fullmatch('[0-9a-f]{32}',original['artifact_id']) is not None
        and type(original.get('bytes')) is int and 0 < original['bytes'] <= 1024*1024
        and type(original.get('sha256')) is str and re.fullmatch('[0-9a-f]{64}',original['sha256']) is not None
        and (metadata is None or canonical(original) == canonical(metadata))
        and canonical(value) == canonical(request_body(original,runtime['source_revision'],registry,
            envelope['review_nonce'])),'BLIND_INPUT_ONLY_REQUEST_REQUIRED')
    return envelope


def case_remaining(budget):
    """One existing five-second case window; neither clock can widen it."""
    remaining = min(5,budget['deadline']-time.monotonic(),
        5-(datetime.now(timezone.utc)-budget['started_at']).total_seconds())
    return max(0,remaining)


def execute_blind(body,authorization,*,actor,task_id,runtime,budget=None):
    """Actual separate registered owning A26 task; only fixed input read access."""
    from .agent_registry import agent_record, REGISTRY_PATH
    from .agent_dispatch_api import action_ledger
    from .objective_api import authenticate_owner, runtime_snapshot
    from .artifact_factory import ArtifactFactory
    from .action_records import ActionRecord, DirectExecutor
    from .deterministic_ops import DeterministicOps
    from .agent_cert_tool_events import check_setup
    import os
    authenticate_owner(authorization)
    binding = independent_verifier_binding();registry = sha(REGISTRY_PATH.read_bytes())
    require(actor == binding['agent_id'] and body.capability == binding['capability_id']
        and agent_record(actor)['authority'] == 'advisory'
        and {'provided_context.read','action.propose'} <= set(agent_record(actor)['tool_eligibility']),
        'BLIND_CURRENT_A26_REQUIRED')
    envelope = admit_request(body,runtime=runtime,registry=registry)
    metadata = envelope['input_artifact_metadata'];subject = metadata['task_id']
    if budget is None:budget = dict(deadline=time.monotonic()+5,started_at=datetime.now(timezone.utc))
    root = _path(os.getenv('PRIME_DATA_DIR','/data'));deadline = time.monotonic()+min(1,case_remaining(budget))
    require(case_remaining(budget) > 0,'BLIND_CASE_BUDGET_EXHAUSTED')
    original = read_cross_peer_request(root,task_id,body.model_dump(),runtime,subject,deadline=deadline)
    budget['started_at'] = min(budget['started_at'],_utc(original['created_at']))
    require(case_remaining(budget) > 0,'BLIND_CASE_BUDGET_EXHAUSTED')
    require(canonical(runtime_snapshot()) == canonical(runtime),'BLIND_RUNTIME_DRIFT')
    require(_path(root/'artifacts').is_dir(),'BLIND_ORIGINAL_ARTIFACT_STORE_REQUIRED')
    factory = ArtifactFactory(root/'artifacts')
    # This helper retrieves only the supplied original input folder. No answer
    # identifier, primary execution or expected answer exists in this task.
    folder = check_setup(factory,metadata,CASE,root)
    ledger = action_ledger()
    require(not any(parse(line.encode()).get('task_id') == task_id for line in _ledger_lines(root)),
        'BLIND_TASK_ALREADY_ATTEMPTED')
    action = ActionRecord(task_id,actor,INPUT_READ_ACTION,'provided_context.read',target='artifact.json',
        parameters_summary=dict(schema_version=SCHEMA,input_artifact_id=metadata['artifact_id'],
            expected_sha256=metadata['sha256'],read_only_observations=True))
    reader = DeterministicOps(source_version=runtime['source_revision'])
    private = {}
    def read_input():
        raw,digest = reader.retrieve_file(folder,'artifact.json',expected_sha256=metadata['sha256'])
        require(len(raw) <= 1024*1024 and digest == sha(raw),'BLIND_INPUT_READ_INVALID')
        private['raw'] = raw
        return dict(source_sha256=digest,result=raw.decode())
    read_result = DirectExecutor(ledger).execute(action,read_input)
    raw = private['raw']
    _metadata(metadata,raw,subject,runtime['source_revision'],
        began=_utc(metadata['timestamp']),ended=datetime.now(timezone.utc))
    conclusion = reproduce_input(raw)
    # No raw context in durable action summary: only its hash and byte length.
    remaining = case_remaining(budget)
    require(remaining > 0 and ledger.flush(timeout=remaining) is True
        and case_remaining(budget) > 0,'BLIND_INPUT_NOT_DURABLE')
    deadline = time.monotonic()+min(1,case_remaining(budget))
    require(canonical(read_cross_peer_request(root,task_id,body.model_dump(),runtime,subject,deadline=deadline))
        == canonical(original) and canonical(runtime_snapshot()) == canonical(runtime)
        and case_remaining(budget) > 0,'BLIND_REQUEST_DRIFT')
    return dict(schema_version=SCHEMA,case=CASE,auditor_id=actor,auditor_capability=body.capability,
        input_sha256=sha(raw),input_artifact_metadata=metadata,input_read_action_id=action.action_id,
        conclusion=conclusion,original_request=original,request_nonce=envelope['review_nonce'],
        answer_access='NOT_SUPPLIED_OR_READ',comparison='NOT_PERFORMED',model_calls=0,
        authority_transfer=False,certification='UNVERIFIED')


def input_action_span(root,task):
    require(_uuid(task),'BLIND_TASK_REQUIRED')
    lines = _ledger_lines(_path(root))
    selected = [i for i,line in enumerate(lines) if (value := parse(line.encode())).get('task_id') == task
        and value.get('action_type') == INPUT_READ_ACTION]
    require(len(selected) == 2 and 2 <= selected[-1]-selected[0]+1 <= 128,'BLIND_ORIGINAL_READ_PAIR_REQUIRED')
    return lines[selected[0]:selected[-1]+1]


def audit_metadata(metadata,raw,task,source,*,began,ended):
    expected = {'artifact_id','task_id','type','creator_agents','timestamp','version','provenance',
        'runtime_revision','validation_state','content_validation','location','sha256','bytes','delivery_state'}
    require(type(metadata) is dict and set(metadata) == expected
        and type(metadata['artifact_id']) is str and re.fullmatch('[0-9a-f]{32}',metadata['artifact_id']) is not None
        and metadata['task_id'] == task and metadata['type'] == 'json' and metadata['creator_agents'] == ['a26']
        and metadata['version'] == '1.0.0' and metadata['provenance'] == 'Deterministic computation; zero model calls'
        and metadata['runtime_revision'] == source and metadata['validation_state'] == 'STRUCTURE_VALIDATED'
        and metadata['content_validation'] == 'Not independently established by structural validation'
        and metadata['location'] == 'artifact.json' and metadata['sha256'] == sha(raw)
        and type(metadata['bytes']) is int and metadata['bytes'] == len(raw) <= 1024*1024
        and metadata['delivery_state'] == 'AVAILABLE' and began <= _utc(metadata['timestamp']) <= ended,
        'BLIND_ORIGINAL_METADATA_INVALID')


def validate_audit(proof,*,input_metadata,input_raw,runtime,registry,now):
    """Independent public original custody validator, never a blind self-PASS."""
    import math
    from .agent_cert_tool_events import _events,validate_cross_peer_receipt,validate_cross_peer_objective
    from .agent_cert_identity_review import action_span
    from .agent_cert_role_review import TOOL_REVIEW_ACTION
    require(type(proof) is dict and set(proof) == {'request','dispatch','artifact_metadata',
        'artifact_content_utf8','input_action_records','action_records','objective_read'},'BLIND_PROOF_FIELDS_INVALID')
    envelope = admit_request(proof['request'],runtime=runtime,registry=registry,metadata=input_metadata)
    dispatch = proof['dispatch'];metadata = proof['artifact_metadata']
    require(type(dispatch) is dict and set(dispatch) == {'task_id','state','artifact','model_calls','execution_model',
        'agent_id','capability','runtime_source_revision','review_action_id','review_action_durable','certification',
        'blind_input_read_action_id'} and _uuid(dispatch['task_id']) and dispatch['task_id'] != input_metadata['task_id']
        and dispatch['state'] == 'COMPLETED' and type(dispatch['model_calls']) is int and dispatch['model_calls'] == 0
        and dispatch['execution_model'] == 'DETERMINISTIC' and dispatch['agent_id'] == 'a26'
        and dispatch['capability'] == 'responsibility.a26' and dispatch['runtime_source_revision'] == runtime['source_revision']
        and dispatch['review_action_durable'] is True and dispatch['certification'] == 'UNVERIFIED',
        'BLIND_ACTUAL_DISTINCT_TASK_REQUIRED')
    raw = proof['artifact_content_utf8'].encode();data = parse(raw)
    require(type(metadata) is dict and metadata.get('creator_agents') == ['a26']
        and canonical(metadata) == canonical(dispatch['artifact']),'BLIND_ORIGINAL_ARTIFACT_REQUIRED')
    audit_metadata(metadata,raw,dispatch['task_id'],runtime['source_revision'],
        began=_utc(input_metadata['timestamp']),ended=now)
    receipt = data.get('original_request')
    validate_cross_peer_receipt(receipt,peer_task=dispatch['task_id'],subject_task=input_metadata['task_id'],
        request=proof['request'],runtime=runtime,now=_utc(metadata['timestamp']))
    expected = dict(schema_version=SCHEMA,case=CASE,auditor_id='a26',auditor_capability='responsibility.a26',
        input_sha256=sha(input_raw),input_artifact_metadata=input_metadata,
        input_read_action_id=dispatch['blind_input_read_action_id'],conclusion=grade_original_input(input_raw),
        original_request=receipt,request_nonce=envelope['review_nonce'],answer_access='NOT_SUPPLIED_OR_READ',
        comparison='NOT_PERFORMED',model_calls=0,authority_transfer=False,certification='UNVERIFIED')
    require(canonical(data) == canonical(expected),'BLIND_ORIGINAL_REPRODUCTION_INVALID')
    events = _events(proof['input_action_records'])
    require(len(events) == 2 and all(row.get('task_id') == dispatch['task_id'] for row in events),
        'BLIND_ORIGINAL_INPUT_READ_REQUIRED')
    first,last = events
    base = dict(task_id=dispatch['task_id'],agent_id='a26',action_type=INPUT_READ_ACTION,
        tool='provided_context.read',target='artifact.json',classification='R0',
        parameters_summary=dict(schema_version=SCHEMA,input_artifact_id=input_metadata['artifact_id'],
            expected_sha256=input_metadata['sha256'],read_only_observations=True),model_backend='deterministic',
        execution_location='local',parent_agent=None,workflow_id=None,action_id=dispatch['blind_input_read_action_id'])
    common = set(base)|{'phase','timestamp','sequence','previous_sha256','sha256'}
    require(_uuid(base['action_id']) and set(first) == common and set(last) == common|{'success','duration_ms','result_summary'}
        and all(canonical(row.get(key)) == canonical(value) for row in events for key,value in base.items())
        and first['phase'] == 'started' and last['phase'] == 'completed' and last['success'] is True
        and canonical(last['result_summary']) == canonical(dict(type='dict',source_sha256=sha(input_raw),
            output_sha256=sha(input_raw),output_length=len(input_raw.decode())))
        and type(last['duration_ms']) in (int,float) and math.isfinite(last['duration_ms']) and 0 <= last['duration_ms'] <= 5000
        and _utc(receipt['created_at']) <= _utc(first['timestamp']) <= _utc(last['timestamp']) <= _utc(metadata['timestamp'])
        and 0 <= (_utc(metadata['timestamp'])-_utc(receipt['created_at'])).total_seconds() <= 5,
        'BLIND_ORIGINAL_READ_BINDING_INVALID')
    action_span(proof['action_records'],task_id=dispatch['task_id'],agent_id='a26',action_type=TOOL_REVIEW_ACTION,
        schema=SCHEMA,metadata=metadata,began=_utc(last['timestamp']),ended=now,action_id=dispatch['review_action_id'])
    read = proof['objective_read']
    require(type(read) is list and len(read) == 2 and read[0] == 200,'BLIND_ORIGINAL_OBJECTIVE_REQUIRED')
    validate_cross_peer_objective(read[1],dispatch=dispatch,runtime=runtime,receipt=receipt,now=now)
    return data


def read_original_audit(root,proof,*,input_metadata,input_raw,runtime,registry,authorization,now):
    """Final grader rereads only already sealed original auditor evidence."""
    from contextlib import closing
    import sqlite3
    from .artifact_factory import ArtifactFactory
    from .agent_cert_role_review import read_tool_review_action_span
    from .objective_api import authenticate_owner
    import json
    authenticate_owner(authorization)
    data = validate_audit(proof,input_metadata=input_metadata,input_raw=input_raw,runtime=runtime,registry=registry,now=now)
    task = proof['dispatch']['task_id'];root = _path(root);path = _path(root/'objectives.db');size = 0
    deadline = time.monotonic()+1
    for suffix in ('','-wal','-journal'):
        item = _path(root/('objectives.db'+suffix))
        if item.exists():
            require(item.is_file(),'BLIND_ORIGINAL_STORE_INVALID');size += item.stat().st_size
    require(path.is_file() and size <= 8*1024*1024,'BLIND_ORIGINAL_STORE_BOUND')
    try:
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=0.1)) as db:
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,1024*1024)
            db.set_progress_handler(lambda:1 if time.monotonic() >= deadline else 0,1000)
            db.execute('BEGIN')
            row = db.execute('SELECT objective_hash,state,steps_json FROM objectives WHERE id=?',(task,)).fetchone()
            turns = db.execute('SELECT revision FROM objective_turns WHERE task=? LIMIT 1',(task,)).fetchone()
            timing = db.execute('SELECT revision,created_at,updated_at FROM objective_metadata WHERE task=? LIMIT 2',(task,)).fetchall()
            pins = db.execute('SELECT revision,host_id,source_revision,version,image_digest FROM objective_runtime WHERE task=? LIMIT 2',(task,)).fetchall()
            meta = proof['objective_read'][1]['execution_metadata']
            require(row is not None and row[0] == sha(OBJECTIVE.encode()) and row[1] == 'submitted'
                and canonical(json.loads(row[2])) == canonical([dict(capability='responsibility.a26',dispatch=proof['dispatch'])])
                and turns is None and timing == [(0,meta['created_at'],meta['updated_at'])]
                and pins == [(0,runtime['host_id'],runtime['source_revision'],runtime['version'],runtime['image_digest'])],
                'BLIND_ORIGINAL_TASK_DRIFT')
    except sqlite3.Error:
        raise ValueError('BLIND_ORIGINAL_STORE_QUERY_REJECTED') from None
    require(_path(root/'artifacts').is_dir(),'BLIND_ORIGINAL_ARTIFACT_STORE_REQUIRED')
    folder = _path(root/'artifacts'/proof['artifact_metadata']['artifact_id'])
    require(folder.is_dir() and {p.name for p in folder.iterdir()} == {'artifact.json','metadata.json'}
        and all(_path(folder/name).is_file() and (folder/name).stat().st_size <= 1024*1024
            for name in ('artifact.json','metadata.json')),'BLIND_ORIGINAL_ARTIFACT_BOUND')
    metadata,raw = ArtifactFactory(root/'artifacts').retrieve(proof['artifact_metadata']['artifact_id'])
    require(canonical(metadata) == canonical(proof['artifact_metadata']) and raw == proof['artifact_content_utf8'].encode()
        and canonical(input_action_span(root,task)) == canonical(proof['input_action_records'])
        and canonical(read_tool_review_action_span(root,task)) == canonical(proof['action_records'])
        and time.monotonic() < deadline,'BLIND_ORIGINAL_CUSTODY_DRIFT')
    return data
