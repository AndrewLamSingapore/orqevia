"""Original labelled context consumption; no domain reasoning or live health claim."""
from copy import deepcopy
from datetime import datetime, timezone
from contextlib import closing
import json
import math
import sqlite3
import threading
import time

from .agent_cert_initialization import _owned_pair, _owned_domains, canonical, sha, MAX_AGE_SECONDS

CASE = 'baseline:context'
SCHEMA = 'jarvis.owned-agent-context.v1'
INPUT_SCHEMA = 'prime.owned-agent-context-input.v1'
ORACLE_ID = 'registered.owned-context.v1'
ACTION_TYPE = 'agent.certification.owned_context.artifact'
SETUP_ACTION = 'agent.certification.owned_context.setup'
READ_ACTION = 'agent.certification.owned_context.read'
OPERATION = 'certification_owned_context'
REVIEW_ACTION = 'agent.certification.owned_context.review'
REVIEW_SCHEMA = 'prime.agent-cert-owned-context-review.v1'
REVIEW_OPERATION = 'certification_owned_context_review'
MAX_BYTES = 64 * 1024
_slot = threading.BoundedSemaphore(1)


class OwnedContextError(ValueError): pass


def require(value, code):
    if value is not True: raise OwnedContextError(code) from None


def context_bytes(agent_id, capability_id):
    _owned_pair(agent_id, capability_id)
    from .agent_cert_a19_baseline import _SCENARIOS
    return canonical({'schema_version': INPUT_SCHEMA, 'agent_id': agent_id,
        'capability_id': capability_id, 'case': CASE, 'data_scope': 'PUBLIC_SYNTHETIC_ONLY',
        'facts': deepcopy(_SCENARIOS[CASE][1])})


def select_context(raw):
    """Compute source-labelled selection from read bytes, never ambient telemetry."""
    from .agent_cert_initialization import _parse
    from .agent_cert_identity_review import utc
    value = _parse(raw, MAX_BYTES)
    facts = value['facts']
    require(type(facts) is dict and type(facts['target_service']) is str
        and type(facts['freshness_limit_seconds']) is int and 0 <= facts['freshness_limit_seconds'] <= 86400
        and type(facts['observations']) is list and len(facts['observations']) <= 32
        and type(facts['claims']) is list and len(facts['claims']) <= 32, 'CONTEXT_INPUT_INVALID')
    assessment = utc(facts['assessment_at'])
    selected, historical, ages = [], [], []
    seen = set()
    for item in facts['observations']:
        require(type(item) is dict and set(item) == {'source', 'service', 'observed_at', 'health'}
            and all(type(item[k]) is str and item[k] for k in item)
            and item['health'] in {'PASS', 'FAIL', 'UNKNOWN'} and item['source'] not in seen,
            'CONTEXT_OBSERVATION_INVALID')
        seen.add(item['source'])
        age = (assessment - utc(item['observed_at'])).total_seconds()
        require(math.isfinite(age) and age.is_integer(), 'CONTEXT_AGE_INVALID')
        if item['service'] == facts['target_service'] and 0 <= age <= facts['freshness_limit_seconds']:
            selected.append(deepcopy(item)); ages.append(int(age))
        else: historical.append(item['source'])
    unsupported = []
    for claim in facts['claims']:
        require(type(claim) is dict and set(claim) == {'source', 'claim', 'supporting_observation_refs'}
            and type(claim['source']) is str and type(claim['claim']) is str
            and type(claim['supporting_observation_refs']) is list
            and all(type(ref) is str and ref in seen for ref in claim['supporting_observation_refs']),
            'CONTEXT_CLAIM_INVALID')
        if not claim['supporting_observation_refs']: unsupported.append(claim['source'])
    return {'input_sha256': sha(raw), 'selected_observations': selected,
        'evidence_refs': [row['source'] for row in selected], 'historical_refs': historical,
        'sample_age_seconds': ages, 'observed_sample_health': [row['health'] for row in selected],
        'unsupported_claim_refs': unsupported, 'continuous_health': 'UNKNOWN', 'root_cause': 'UNKNOWN',
        'scope': 'LABELLED_PUBLIC_SYNTHETIC_CONTEXT_SELECTION_ONLY'}


def _review_assessment(raw):
    """Independent fixed BCTX oracle; never calls the producer calculator."""
    facts = json.loads(raw)['facts']
    first, old = facts['observations']
    require(first['source']=='BCTX1' and first['health']=='PASS' and old['source']=='BCTX2'
        and facts['freshness_limit_seconds']==300 and facts['claims'][0]['source']=='BCTX3'
        and facts['claims'][0]['supporting_observation_refs']==[], 'CONTEXT_FIXED_ORACLE_REQUIRED')
    return {'input_sha256':sha(raw),'selected_observations':[deepcopy(first)],
        'evidence_refs':['BCTX1'],'historical_refs':['BCTX2'],'sample_age_seconds':[300],
        'observed_sample_health':['PASS'],'unsupported_claim_refs':['BCTX3'],
        'continuous_health':'UNKNOWN','root_cause':'UNKNOWN',
        'scope':'LABELLED_PUBLIC_SYNTHETIC_CONTEXT_SELECTION_ONLY'}


def context_objective(agent_id, capability_id):
    _owned_pair(agent_id, capability_id)
    return (f'Read the original source-owned labelled context for {agent_id.upper()} {capability_id} once. '
        'Select only target-service observations within the declared freshness window; preserve old history '
        'and unsupported claims as unknown. Do not infer domain reasoning, continuous health or root cause.')


def context_reviewer(agent_id, capability_id):
    from .agent_cert_initialization import initialization_reviewer
    _owned_pair(agent_id, capability_id)
    return initialization_reviewer(agent_id, capability_id)


def context_review_objective(agent_id, capability_id):
    _owned_pair(agent_id, capability_id)
    return (f'Independently review one recorded {agent_id.upper()} original labelled-context consumption '
        f'for {capability_id} against its original Objective, context/result artifacts and setup/read/result '
        'action records twice. Verify declared freshness selection and unknown claims; do not certify or sign.')


def canonical_owned_context_case(agent_id, capability_id):
    raw = context_bytes(agent_id, capability_id)
    return {'agent_id': agent_id, 'capability_id': capability_id, 'case': CASE,
        'case_version': 'registered.owned-context-events.v1', 'oracle_id': ORACLE_ID,
        'case_input_sha256': sha(raw), 'request': {'capability': capability_id,
            'objective': context_objective(agent_id, capability_id), 'context': raw.decode(),
            'classification': 'R0', 'data_classification': 'LOCAL_ONLY', 'minimum_tier': 'NANO',
            'priority': 'low', 'task_class': 'classification', 'max_cost_usd': 0.0,
            'preferred_provider': None, 'response_format': 'strict_json', 'deterministic_operation': OPERATION},
        'certification': 'UNVERIFIED'}


def _read_span(lines, metadata, raw, task, agent, began, ended):
    from .agent_cert_identity_review import parse, utc, valid_uuid
    require(type(lines) is list and len(lines) == 2, 'CONTEXT_ORIGINAL_READ_REQUIRED')
    events = [parse(line.encode()) for line in lines]
    first, last = events
    aid = first['action_id']
    base = {'task_id': task, 'agent_id': agent, 'action_type': READ_ACTION,
        'tool': 'provided_context.read', 'target': 'artifact.json', 'classification': 'R0',
        'parameters_summary': {'schema_version': INPUT_SCHEMA, 'setup_artifact_id': metadata['artifact_id'],
            'expected_sha256': sha(raw), 'max_bytes': MAX_BYTES, 'read_only_observations': True},
        'model_backend': 'deterministic', 'execution_location': 'local', 'parent_agent': None,
        'workflow_id': None, 'action_id': aid}
    common = set(base) | {'phase', 'timestamp', 'sequence', 'previous_sha256', 'sha256'}
    require(valid_uuid(aid) and set(first) == common
        and set(last) == common | {'success', 'duration_ms', 'result_summary'}
        and all(canonical(e.get(k)) == canonical(v) for e in events for k,v in base.items())
        and first['phase'] == 'started' and last['phase'] == 'completed' and last['success'] is True
        and type(last['duration_ms']) in (int,float) and math.isfinite(last['duration_ms'])
        and 0 <= last['duration_ms'] <= 5000
        and last['result_summary'] == {'type': 'dict', 'sha256': sha(raw),
            'source_sha256': sha(raw), 'status': 'READ_ONCE_BOUNDED_BYTES'}
        and began <= utc(first['timestamp']) <= utc(last['timestamp']) <= ended,
        'CONTEXT_READ_UNBOUND')
    return aid


def _report_custody(report, pins, began, ended):
    from .agent_cert_identity_review import action_span, parse, utc
    raw = report['input_content_utf8'].encode()
    require(raw == context_bytes(pins['agent_id'], pins['capability_id']), 'CONTEXT_ORIGINAL_BYTES_REQUIRED')
    meta = report['input_artifact_metadata']
    require(type(meta) is dict and meta.get('task_id') == pins['task_id']
        and meta.get('creator_agents') == [pins['agent_id']] and meta.get('runtime_revision') == pins['source_revision']
        and meta.get('sha256') == sha(raw) and type(meta.get('bytes')) is int and meta['bytes'] == len(raw)
        and meta.get('location') == 'artifact.json' and meta.get('delivery_state') == 'AVAILABLE'
        and meta.get('validation_state') == 'STRUCTURE_VALIDATED' and meta.get('type') == 'json'
        and began <= utc(meta['timestamp']) <= ended, 'CONTEXT_INPUT_ARTIFACT_UNBOUND')
    lines = report['input_action_records']
    setup = action_span(lines, task_id=pins['task_id'], agent_id=pins['agent_id'], action_type=SETUP_ACTION,
        schema=INPUT_SCHEMA, metadata=meta, began=began, ended=ended)
    read = _read_span(report['read_action_records'], meta, raw, pins['task_id'], pins['agent_id'], began, ended)
    require(read != parse(lines[0].encode())['action_id'], 'CONTEXT_ACTION_DISTINCT_REQUIRED')
    return setup


def validate_context_report(raw, *, now, **pins):
    from .agent_cert_initialization import _parse, _instant, _bindings
    from .agent_cert_identity_review import utc
    report = _parse(raw, MAX_BYTES)
    captured = utc(report['captured_at']); began = utc(report['started_at'])
    require(0 <= (_instant(now)-captured).total_seconds() <= MAX_AGE_SECONDS
        and 0 <= (captured-began).total_seconds() <= 5, 'CONTEXT_TIME_UNBOUND')
    _report_custody(report, pins, began, captured)
    expected = {'schema_version': SCHEMA, 'case': CASE, 'oracle_id': ORACLE_ID,
        'task_id': pins['task_id'], 'agent_id': pins['agent_id'], 'capability_id': pins['capability_id'],
        'captured_at': captured.isoformat(), 'started_at': began.isoformat(),
        'runtime': _bindings(pins['task_id'],pins['runtime'],pins['source_revision'],pins['runtime_image_id'],pins['registry_sha256']),
        'owned_domains': _owned_domains(pins['registry_sha256'],pins['agent_id'],pins['capability_id']),
        'input_content_utf8': context_bytes(pins['agent_id'],pins['capability_id']).decode(),
        'input_artifact_metadata': report['input_artifact_metadata'],
        'input_action_records': report['input_action_records'], 'read_action_records': report['read_action_records'],
        'assessment': _review_assessment(report['input_content_utf8'].encode()),
        'observation': 'ACTUAL_ORIGINAL_CONTEXT_READ_AND_LABELLED_SELECTION',
        'execution': {'method':'DETERMINISTIC_READ_ONLY','model_calls':0,'input_tokens':0,'output_tokens':0,'fresh_inference_performed':False},
        'semantic_domain_answer_quality':'NOT_ASSESSED','consequential_execution':'NOT_PERFORMED',
        'independent_review':'NOT_PERFORMED','certification':'UNVERIFIED'}
    require(canonical(report) == canonical(expected), 'CONTEXT_REPORT_DRIFT')
    return report


def validate_owned_context_execution(execution, **pins):
    from .agent_cert_identity_review import _validate_event_execution, _OWNED_CONTEXT_ADAPTER, parse, utc
    joined = _validate_event_execution(execution, _adapter=_OWNED_CONTEXT_ADAPTER, **pins)
    report = parse(execution['artifact_content_utf8'].encode())
    lines = report['input_action_records'] + report['read_action_records'] + execution['action_records']
    require(len(lines) == 6, 'CONTEXT_SIX_ORIGINAL_RECORDS_REQUIRED')
    rows = [parse(line.encode()) for line in lines]
    require(len({row['action_id'] for row in rows}) == 3
        and all(row['task_id'] == joined['task_id'] and row['agent_id'] == pins['agent_id'] for row in rows),
        'CONTEXT_ORIGINAL_OWNER_REQUIRED')
    for index, row in enumerate(rows):
        require(type(row['sequence']) is int and row['sequence'] > 0
            and sha(canonical({k:v for k,v in row.items() if k!='sha256'})) == row['sha256'], 'CONTEXT_CHAIN_INVALID')
        if index:
            previous=rows[index-1]
            require(row['sequence']==previous['sequence']+1 and row['previous_sha256']==previous['sha256']
                and utc(previous['timestamp'])<=utc(row['timestamp']), 'CONTEXT_CHAIN_INVALID')
    require(utc(report['input_artifact_metadata']['timestamp']) <= utc(rows[2]['timestamp']), 'CONTEXT_READ_ORDER_INVALID')
    return {**joined, 'input_sha256': sha(report['input_content_utf8'].encode()),
        'original_context_action_span_sha256': sha(''.join(lines).encode())}


def read_original_context_objective(root, execution):
    from .agent_cert_artifact_events import _path
    spec=execution['case_spec'];task=execution['dispatch']['task_id'];runtime=execution['runtime']
    fixed=canonical_owned_context_case(spec['agent_id'],spec['capability_id'])
    path=_path(root/'objectives.db');require(path.is_file(),'CONTEXT_OBJECTIVE_REQUIRED')
    deadline=time.monotonic()+2
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=0.1)) as db:
        db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,1024*1024)
        db.set_progress_handler(lambda:int(time.monotonic()>=deadline),1000)
        db.execute('BEGIN')
        row=db.execute('SELECT objective_hash,state,steps_json FROM objectives WHERE id=?',(task,)).fetchone()
        turns=db.execute('SELECT revision FROM objective_turns WHERE task=? LIMIT 1',(task,)).fetchone()
        runtime_rows=db.execute('SELECT revision,host_id,source_revision,version,image_digest FROM objective_runtime WHERE task=? LIMIT 2',(task,)).fetchall()
    require(time.monotonic()<deadline and row is not None and row[0]==sha(fixed['request']['objective'].encode())
        and row[1]=='submitted' and turns is None
        and canonical(json.loads(row[2]))==canonical([{'capability':fixed['capability_id'],'dispatch':execution['dispatch']}])
        and runtime_rows==[(0,runtime['host_id'],runtime['source_revision'],runtime['version'],runtime['image_digest'])],
        'CONTEXT_ORIGINAL_OBJECTIVE_DRIFT')


def read_original_context_custody(root, execution):
    from .agent_cert_artifact_events import _path, _ledger_lines
    from .agent_cert_identity_review import parse
    report=parse(execution['artifact_content_utf8'].encode());metadata=report['input_artifact_metadata']
    folder=_path(root/'artifacts'/metadata['artifact_id'])
    names=set()
    for entry in folder.iterdir():
        require(len(names)<2,'CONTEXT_INPUT_FOLDER_DRIFT')
        names.add(entry.name)
    require(names=={'artifact.json','metadata.json'},'CONTEXT_INPUT_FOLDER_DRIFT')
    copies={}
    for name,limit in [('artifact.json',MAX_BYTES),('metadata.json',16384)]:
        path=_path(folder/name)
        require(path.is_file() and 0<path.stat().st_size<=limit,'CONTEXT_INPUT_BOUNDS')
        with path.open('rb') as stream: copies[name]=stream.read(limit+1)
        require(0<len(copies[name])<=limit,'CONTEXT_INPUT_BOUNDS')
    actual=parse(copies['metadata.json']);raw=copies['artifact.json']
    require(canonical(actual)==canonical(metadata) and raw==report['input_content_utf8'].encode()
        and actual['sha256']==sha(raw) and actual['bytes']==len(raw),'CONTEXT_INPUT_ORIGINAL_DRIFT')
    original=[line for line in _ledger_lines(root) if parse(line.encode()).get('task_id')==report['task_id']]
    require(canonical(original)==canonical(report['input_action_records']+report['read_action_records']+execution['action_records']),
        'CONTEXT_ORIGINAL_ACTIONS_DRIFT')


def execute_owned_context_case(spec, task_id, **arguments):
    require(_slot.acquire(blocking=False),'CONTEXT_PRODUCER_BUSY')
    try:
        return _execute(spec,task_id,**arguments)
    except OwnedContextError: raise
    except Exception: raise OwnedContextError('CONTEXT_EXECUTION_REJECTED') from None
    finally: _slot.release()


def _execute(spec,task_id,*,submitted_request,data_root,ledger,runtime,read_runtime,source_revision,runtime_image_id,registry_sha256):
    from .agent_cert_artifact_events import _path,_ledger_lines,parse,_utc
    from .agent_cert_initialization import _bindings
    from .action_records import ActionLedger,ActionRecord,DirectExecutor
    from .artifact_factory import ArtifactFactory
    from .deterministic_ops import DeterministicOps
    fixed=canonical_owned_context_case(spec.get('agent_id'),spec.get('capability_id'))
    require(canonical(spec)==canonical(fixed) and canonical(submitted_request)==canonical(fixed['request']),'CONTEXT_FIXED_REQUEST_REQUIRED')
    bound=_bindings(task_id,runtime,source_revision,runtime_image_id,registry_sha256)
    require(callable(read_runtime) and canonical(read_runtime())==canonical(bound),'CONTEXT_RUNTIME_UNBOUND')
    root=_path(data_root);began=datetime.now(timezone.utc);deadline=time.monotonic()+5
    def remaining():
        budget=min(deadline-time.monotonic(),5-(datetime.now(timezone.utc)-began).total_seconds())
        require(budget>0,"CONTEXT_SHARED_DEADLINE_EXHAUSTED")
        return budget
    require(type(ledger) is ActionLedger and _path(ledger.path)==root/'action-records.jsonl'
        and not ledger.closed and ledger.worker.is_alive() and ledger.status()['healthy'] is True,'CONTEXT_LEDGER_REQUIRED')
    path=_path(root/'objectives.db');require(path.is_file(),'CONTEXT_OBJECTIVE_REQUIRED')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=0.1)) as db:
        sql_deadline=min(deadline,time.monotonic()+2);db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,1024*1024)
        db.set_progress_handler(lambda:int(time.monotonic()>=sql_deadline),1000)
        row=db.execute('SELECT objective_hash,state,steps_json FROM objectives WHERE id=?',(task_id,)).fetchone()
        turns=db.execute('SELECT revision FROM objective_turns WHERE task=? LIMIT 1',(task_id,)).fetchone()
        times=db.execute('SELECT revision,created_at,updated_at FROM objective_metadata WHERE task=? LIMIT 2',(task_id,)).fetchall()
        pinned=db.execute('SELECT revision,host_id,source_revision,version,image_digest FROM objective_runtime WHERE task=? LIMIT 2',(task_id,)).fetchall()
    require(time.monotonic()<sql_deadline and row is not None and row[0]==sha(fixed['request']['objective'].encode())
        and row[1]=='dispatching' and row[2]==json.dumps([fixed['capability_id']]) and turns is None
        and len(times)==1 and times[0][0]==0 and times[0][1]==times[0][2]
        and 0<=(began-_utc(times[0][1])).total_seconds()<=MAX_AGE_SECONDS
        and pinned==[(0,bound['host_id'],bound['source_revision'],bound['version'],bound['image_digest'])],'CONTEXT_OBJECTIVE_DRIFT')
    domains=_owned_domains(registry_sha256,fixed['agent_id'],fixed['capability_id'])
    require('provided_context.read' in domains['definition']['tool_eligibility'],'CONTEXT_REGISTERED_READ_REQUIRED')
    with ledger.pending.all_tasks_done: require(ledger.pending.unfinished_tasks==0,'CONTEXT_PRIOR_ACTION_PENDING')
    require(all(parse(line.encode()).get('task_id')!=task_id for line in _ledger_lines(root)),'CONTEXT_ALREADY_ATTEMPTED')
    executor=DirectExecutor(ledger);factory=ArtifactFactory(root/'artifacts');raw=context_bytes(fixed['agent_id'],fixed['capability_id'])
    def create(content):
        metadata=factory.create(kind='json',content=content.decode(),task_id=task_id,creator=fixed['agent_id'],
            provenance='Deterministic computation; zero model calls',runtime_revision=source_revision)
        actual,data=factory.retrieve(metadata['artifact_id'])
        require(canonical(actual)==canonical(metadata) and data==content,'CONTEXT_ARTIFACT_READBACK_DRIFT')
        return metadata
    def artifact_action(action,schema):
        return ActionRecord(task_id,fixed['agent_id'],action,'artifact-factory',
            parameters_summary={'schema_version':schema,'read_only_observations':True})
    setup=executor.execute(artifact_action(SETUP_ACTION,INPUT_SCHEMA),lambda:create(raw))
    folder=_path(root/'artifacts'/setup['artifact_id']);read_raw=None
    read_action=ActionRecord(task_id,fixed['agent_id'],READ_ACTION,'provided_context.read',target='artifact.json',
        parameters_summary={'schema_version':INPUT_SCHEMA,'setup_artifact_id':setup['artifact_id'],
            'expected_sha256':sha(raw),'max_bytes':MAX_BYTES,'read_only_observations':True})
    def read():
        nonlocal read_raw
        remaining()
        path=_path(folder/'artifact.json');require(path.is_file() and 0<path.stat().st_size<=MAX_BYTES,'CONTEXT_READ_BOUNDS')
        read_raw,digest=DeterministicOps(source_version=source_revision).retrieve_file(folder,'artifact.json',expected_sha256=sha(raw))
        require(read_raw==raw and len(read_raw)<=MAX_BYTES,'CONTEXT_READ_DRIFT')
        return {'sha256':sha(read_raw),'source_sha256':digest,'status':'READ_ONCE_BOUNDED_BYTES'}
    executor.execute(read_action,read)
    require(ledger.flush(timeout=remaining()) is True,'CONTEXT_DURABLE_READ_REQUIRED')
    remaining()
    lines=[line for line in _ledger_lines(root) if parse(line.encode()).get('task_id')==task_id]
    require(len(lines)==4,'CONTEXT_SETUP_READ_REQUIRED')
    pins={'task_id':task_id,'agent_id':fixed['agent_id'],'capability_id':fixed['capability_id'],'runtime':bound,
        'source_revision':source_revision,'runtime_image_id':runtime_image_id,'registry_sha256':registry_sha256}
    def finish():
        remaining()
        report={'schema_version':SCHEMA,'case':CASE,'oracle_id':ORACLE_ID,**{k:pins[k] for k in ('task_id','agent_id','capability_id')},
            'captured_at':datetime.now(timezone.utc).isoformat(),'started_at':began.isoformat(),'runtime':bound,'owned_domains':domains,
            'input_content_utf8':read_raw.decode(),'input_artifact_metadata':setup,'input_action_records':lines[:2],
            'read_action_records':lines[2:],'assessment':select_context(read_raw),
            'observation':'ACTUAL_ORIGINAL_CONTEXT_READ_AND_LABELLED_SELECTION',
            'execution':{'method':'DETERMINISTIC_READ_ONLY','model_calls':0,'input_tokens':0,'output_tokens':0,'fresh_inference_performed':False},
            'semantic_domain_answer_quality':'NOT_ASSESSED','consequential_execution':'NOT_PERFORMED',
            'independent_review':'NOT_PERFORMED','certification':'UNVERIFIED'}
        output=canonical(report);require(len(output)<=MAX_BYTES,'CONTEXT_REPORT_BOUND')
        validate_context_report(output,now=datetime.now(timezone.utc),**pins)
        return create(output)
    artifact=executor.execute(artifact_action(ACTION_TYPE,SCHEMA),finish)
    require(ledger.flush(timeout=remaining()) is True and canonical(read_runtime())==canonical(bound)
        and time.monotonic()<deadline and 0<=(datetime.now(timezone.utc)-began).total_seconds()<=5,'CONTEXT_RUNTIME_TIME_OR_DURABILITY_DRIFT')
    _owned_domains(registry_sha256,fixed['agent_id'],fixed['capability_id'])
    return {'task_id':task_id,'state':'COMPLETED','artifact':artifact,'model_calls':0,'execution_model':'DETERMINISTIC',
        'agent_id':fixed['agent_id'],'capability':fixed['capability_id'],'runtime_source_revision':source_revision}
