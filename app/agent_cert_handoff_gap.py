"""One supported missing-evidence peer denial and scoped continuation only."""
from datetime import datetime, timezone
from .agent_cert_artifact_events import canonical, parse, sha, _utc, _uuid

CASE = 'handoff_recovery:bounded_response'
FAILURE_CASE = 'handoff_recovery:agent_failure'
CASES=(CASE,FAILURE_CASE)
TRACE_SCHEMA = 'prime.a26-source-handoff-denial.v1'
FAILURE_REASON = 'Independent artifact review requires current joined event evidence'


def require(value, code):
    if value is not True:
        raise ValueError(code) from None


def case_remaining(budget):
    import time
    return max(0,min(5,budget['deadline']-time.monotonic(),
        5-(datetime.now(timezone.utc)-budget['started_at']).total_seconds()))


def failure_request(case=CASE):
    require(case in CASES,'HANDOFF_FIXED_CASE_REQUIRED')
    from .agent_cert_role_review import ARTIFACT_REVIEW_OBJECTIVE, ARTIFACT_REVIEW_OPERATION
    return dict(capability='responsibility.a26', objective=ARTIFACT_REVIEW_OBJECTIVE,
        context=canonical(dict(source_case=case, missing_original_peer_evidence=True,
            scope='PUBLIC_SOURCE_MISSING_EVIDENCE_HANDOFF_ONLY')).decode(),
        classification='R0', data_classification='LOCAL_ONLY', minimum_tier='NANO',
        priority='low', task_class='classification', max_cost_usd=0.0,
        preferred_provider=None, response_format='strict_json', deterministic_operation=ARTIFACT_REVIEW_OPERATION)


def is_failure_request(body):
    value = body.model_dump() if hasattr(body, 'model_dump') else body
    if type(value) is not dict or type(value.get('context')) is not str:return False
    try:case=parse(value['context'].encode()).get('source_case')
    except ValueError:return False
    return case in CASES and canonical(value)==canonical(failure_request(case))


def denial_detail(body, original_reason, *, actor, task_id, runtime, registry_sha256):
    """Called only after the unchanged supported validator actually denies."""
    require(is_failure_request(body) and actor == 'a26' and _uuid(task_id)
        and original_reason == FAILURE_REASON, 'HANDOFF_ORIGINAL_DENIAL_REQUIRED')
    actual = body.model_dump() if hasattr(body, 'model_dump') else body
    case=parse(actual['context'].encode())['source_case']
    return dict(reason=original_reason, source_handoff_trace=dict(schema_version=TRACE_SCHEMA,
        source_case=case, task_id=task_id, actor=actor, capability='responsibility.a26',
        objective_sha256=sha(failure_request()['objective'].encode()),
        dispatcher_request_sha256=sha(canonical(actual)), runtime=runtime,
        registry_sha256=registry_sha256, authentication='OWNER_AUTHENTICATED',
        outcome='MISSING_ORIGINAL_EVIDENCE_HANDOFF_DENIED', authority_transfer=False))


def validate_failed_original(original, *, runtime, registry_sha256, now, subject_task=None):
    from .objective_api import inference_attempt_projection
    require(type(original) is dict and _uuid(original.get('id'))
        and original['id'] != subject_task and type(original.get('revision')) is int
        and original['revision'] == 0 and original.get('state') == 'COMPLETED_WITH_FAILURES',
        'HANDOFF_ACTUAL_FAILED_OBJECTIVE_REQUIRED')
    task = original['id']
    case=original.get('steps',[{}])[0].get('source_handoff_trace',{}).get('source_case')
    require(case in CASES,'HANDOFF_ORIGINAL_FIXED_CASE_REQUIRED')
    detail = denial_detail(failure_request(case), FAILURE_REASON, actor='a26', task_id=task,
        runtime=runtime, registry_sha256=registry_sha256)
    require(original.get('steps') == [dict(capability='responsibility.a26',state='blocked',
        reason='STEP_DISPATCH_FAILED',source_handoff_trace=detail['source_handoff_trace'],revision=0)],
        'HANDOFF_ORIGINAL_DENIAL_TRACE_DRIFT')
    metadata = original.get('execution_metadata')
    require(type(metadata) is dict and metadata.get('schema_version') == 'jarvis.authoritative-execution.v1'
        and metadata.get('authoritative') is True and metadata.get('task_id') == task
        and type(metadata.get('revision')) is int and metadata['revision'] == 0
        and metadata.get('state') == 'COMPLETED_WITH_FAILURES' and canonical(metadata.get('runtime')) == canonical(runtime)
        and metadata.get('jobs') == [] and metadata.get('agent_execution') == []
        and metadata.get('inference_attempts') == inference_attempt_projection([])
        and metadata.get('model_content_is_authoritative_metadata') is False
        and metadata.get('provenance',{}).get('runtime') == 'IMMUTABLE_OBJECTIVE_RUNTIME'
        and metadata.get('started_at') is None and metadata.get('completed_at')==metadata.get('updated_at')
        and metadata.get('lifecycle',{}).get('started_at_reason')=='NO_EXECUTION_STARTED_DISPATCH_BLOCKED'
        and metadata.get('lifecycle',{}).get('completed_at_source')=='TERMINAL_STATE_OBSERVED_AT_OBJECTIVE_UPDATE'
        and _utc(metadata['created_at']) <= _utc(metadata['updated_at']) <= now
        and 0 <= (now-_utc(metadata['updated_at'])).total_seconds() <= 300,
        'HANDOFF_FAILED_RUNTIME_TIME_DRIFT')
    return dict(task_id=task, objective_sha256=detail['source_handoff_trace']['objective_sha256'],
        dispatcher_request_sha256=detail['source_handoff_trace']['dispatcher_request_sha256'],
        original_objective_sha256=sha(canonical(original)), reason=FAILURE_REASON,
        failure_scope='MISSING_REQUIRED_ORIGINAL_PEER_EVIDENCE_NOT_AGENT_CRASH',
        peer_conclusion='NOT_AVAILABLE', authority_transfer=False)


def continuation_request(original):
    from .agent_cert_tool_events import canonical_tool_case, input_bytes
    case=original['steps'][0]['source_handoff_trace']['source_case']
    require(case in CASES,'HANDOFF_ORIGINAL_FIXED_CASE_REQUIRED')
    request = dict(canonical_tool_case(case)['request'])
    request['context'] = canonical(dict(case=case, fixed_context=parse(input_bytes(case)),
        original_failed_peer=original)).decode()
    require(len(request['context'].encode()) <= 80000, 'HANDOFF_ORIGINAL_ENVELOPE_BOUND')
    return request


def reread_failed_original(original, *, reader, runtime, registry_sha256, now, subject_task):
    require(callable(reader), 'HANDOFF_ORIGINAL_READER_REQUIRED')
    joined = validate_failed_original(original, runtime=runtime,registry_sha256=registry_sha256,
        now=now,subject_task=subject_task)
    actual = reader(joined['task_id'])
    require(canonical(actual) == canonical(original), 'HANDOFF_OWNING_FAILED_OBJECTIVE_DRIFT')
    return joined


def read_failed_store(data_root, original, *, runtime,registry_sha256,now,subject_task,deadline):
    """Read retained private failure and trace in one existing-store transaction."""
    import json,sqlite3,time
    from contextlib import closing
    from .agent_cert_artifact_events import _path
    joined=validate_failed_original(original,runtime=runtime,registry_sha256=registry_sha256,
        now=now,subject_task=subject_task)
    root=_path(data_root);path=_path(root/'objectives.db');used=0
    require(path.is_file(),'HANDOFF_ORIGINAL_STORE_REQUIRED')
    for suffix in ('','-wal','-shm','-journal'):
        item=_path(root/('objectives.db'+suffix))
        if item.exists():
            require(item.is_file(),'HANDOFF_ORIGINAL_STORE_TYPE')
            used+=item.stat().st_size
    require(used<=8*1024*1024 and time.monotonic()<deadline,'HANDOFF_ORIGINAL_STORE_BOUND')
    try:
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=0.1)) as db:
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,1024*1024)
            db.set_progress_handler(lambda:1 if time.monotonic()>=deadline else 0,1000)
            db.execute('BEGIN')
            row=db.execute('SELECT objective_hash,state,steps_json FROM objectives WHERE id=?',
                (joined['task_id'],)).fetchone()
            turns=db.execute('SELECT revision FROM objective_turns WHERE task=? LIMIT 1',
                (joined['task_id'],)).fetchone()
            pins=db.execute('SELECT revision,host_id,source_revision,version,image_digest FROM objective_runtime WHERE task=? LIMIT 2',
                (joined['task_id'],)).fetchall()
            times=db.execute('SELECT revision,created_at,updated_at FROM objective_metadata WHERE task=? LIMIT 2',
                (joined['task_id'],)).fetchall()
    except sqlite3.Error:
        raise ValueError('HANDOFF_ORIGINAL_STORE_QUERY_REJECTED') from None
    require(time.monotonic()<deadline and row is not None and turns is None
        and row[0]==joined['objective_sha256'] and row[1]=='submitted'
        and pins==[(0,runtime['host_id'],runtime['source_revision'],runtime['version'],runtime['image_digest'])]
        and times==[(0,original['execution_metadata']['created_at'],original['updated_at'])],
        'HANDOFF_ORIGINAL_STORE_BINDING_DRIFT')
    stored=json.loads(row[2])
    expected=[dict(capability='responsibility.a26',state='blocked',reason=FAILURE_REASON,
        source_handoff_trace=original['steps'][0]['source_handoff_trace'])]
    require(stored==expected,'HANDOFF_ORIGINAL_PRIVATE_REASON_TRACE_DRIFT')
    return dict(task_id=joined['task_id'],stored_steps_sha256=sha(canonical(stored)),
        stored_objective_sha256=row[0],runtime=runtime,created_at=times[0][1],updated_at=times[0][2],
        certification='UNVERIFIED')


def produce_assessment(input_raw, original, *, runtime, registry_sha256, task_id):
    from .agent_cert_tool_events import input_bytes, case_version, RESULT_SCHEMA
    case=parse(input_raw)['case']
    require(case in CASES and input_raw==input_bytes(case) and original['steps'][0]['source_handoff_trace']['source_case']==case,
        'HANDOFF_ORIGINAL_OBSERVATION_REQUIRED')
    observation = parse(input_raw)['known_observation']
    joined = validate_failed_original(original,runtime=runtime,registry_sha256=registry_sha256,
        now=datetime.now(timezone.utc),subject_task=task_id)
    return canonical(dict(schema_version=RESULT_SCHEMA,case=case,case_version=case_version(case),
        input_sha256=sha(input_raw),known_observation=observation,
        failure_basis_points=observation['api_failures']*10000//observation['api_checks'],
        failed_peer=joined,peer_dependent_gap='ORIGINAL_PEER_EVIDENCE_UNAVAILABLE',
        **({'continuation_status':'ASSESSMENT_COMPLETED_AFTER_ORIGINAL_HANDOFF_REFUSAL'} if case==FAILURE_CASE
            else {'gap_status':'PEER_DEPENDENT_GAP_PRESERVED'}),
        peer_retry_count=0,peer_conclusion='NOT_AVAILABLE',recovery='NOT_PROVEN',
        current_health='UNKNOWN',authority_transfer=False,certification='UNVERIFIED'))


def validate_assessment(raw, input_raw, original, *, runtime,registry_sha256,task_id,now):
    """Separate original oracle, never the producer result constructor."""
    from .agent_cert_tool_events import input_bytes, case_version, RESULT_SCHEMA
    from fractions import Fraction
    case=parse(input_raw)['case']
    require(case in CASES and input_raw==input_bytes(case) and original['steps'][0]['source_handoff_trace']['source_case']==case,
        'HANDOFF_ORIGINAL_OBSERVATION_REQUIRED')
    source = parse(input_raw)['known_observation']
    require(type(source['api_checks']) is int and type(source['api_failures']) is int
        and source['api_checks']>0 and 0<=source['api_failures']<=source['api_checks'],
        'HANDOFF_ORIGINAL_COUNTS_REQUIRED')
    failed = validate_failed_original(original,runtime=runtime,registry_sha256=registry_sha256,
        now=now,subject_task=task_id)
    expected = dict(schema_version=RESULT_SCHEMA,case=case,case_version=case_version(case),
        input_sha256=sha(input_raw),known_observation=source,
        failure_basis_points=int(Fraction(source['api_failures'],source['api_checks'])*10000),
        failed_peer=failed,peer_dependent_gap='ORIGINAL_PEER_EVIDENCE_UNAVAILABLE',
        **({'continuation_status':'ASSESSMENT_COMPLETED_AFTER_ORIGINAL_HANDOFF_REFUSAL'} if case==FAILURE_CASE
            else {'gap_status':'PEER_DEPENDENT_GAP_PRESERVED'}),
        peer_retry_count=0,peer_conclusion='NOT_AVAILABLE',recovery='NOT_PROVEN',
        current_health='UNKNOWN',authority_transfer=False,certification='UNVERIFIED')
    require(raw == canonical(expected), 'HANDOFF_INDEPENDENT_ASSESSMENT_REJECTED')
    return True
