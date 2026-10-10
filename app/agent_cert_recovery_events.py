"""Fixed public two-Objective correction protocol, never production recovery.

The precursor deliberately records a wrong inference as CONTROLLED_FAILURE.
Its original bytes remain part of the corrective case. Source constructors and
pure checks alone establish no original execution, authentication or L7 award.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
import math
import threading
import time

from .agent_cert_artifact_events import canonical, parse, sha, _utc, _uuid

CASE = 'recovery:complete'
PRIOR_PHASE = 'controlled_prior'
CORRECTION_PHASE = 'correction'
VERSION = 'a19.original-two-task-correction.v1'
INPUT_SCHEMA = 'prime.a19-recovery-input.v1'
RESULT_SCHEMA = 'prime.a19-recovery-result.v1'
EVENT_SCHEMA = 'prime.a19-recovery-event.v1'
ORACLE = 'a19.original-two-task-correction.v1'
AGENT = 'a19'
CAPABILITY = 'responsibility.a19'
PROVENANCE = 'PUBLIC_SYNTHETIC_CONTROLLED_FAILURE_EXERCISE_ZERO_MODELS'
REVIEW_SCHEMA = 'prime.a19-recovery-review.v1'
REVIEW_ACTION = 'agent.certification.recovery.review'
REVIEW_OBJECTIVE = ('Independently review the two actual distinct original A19 tasks: retained documented CONTROLLED_FAILURE '
    'followed by an actual newer source sample and correction. Reread both original Objectives, immutable input/result '
    'artifacts and complete original action chains twice; independently reject unsupported health, wrong arithmetic, '
    'borrowed source, reversed arrival or a repaired predecessor. This fixed public exercise is not production recovery, '
    'model reasoning or L7. Do not restart, change policy, renew, certify or sign.')
_OBJECTIVES = {
    PRIOR_PHASE: 'Create the documented public controlled failure: actually read RC1, then deliberately record the unsupported inference continuous_health=HEALTHY as CONTROLLED_FAILURE. Preserve this wrong original conclusion unchanged for a separate later corrective task. This is an intentional deterministic challenge, not a prior real model or production incident; do not certify, sign or execute recovery.',
    CORRECTION_PHASE: 'After a distinct completed original controlled-failure task, actually read its retained wrong conclusion and the newer original RC2 sample. Correct the prior inference: derive500 failure basis points for the supplied newer window and withdraw continuous_health=HEALTHY to UNKNOWN, preserving and citing the original controlled failure. Do not claim production recovery, cause, model reasoning, continuous health, authority, certification or L7.',
}
_slot = threading.BoundedSemaphore(1)


class RecoveryEventError(ValueError):
    """Fixed safe error codes, never retained context or local path text."""


def require(condition, code):
    if condition is not True:
        raise RecoveryEventError(code) from None


def phase(value):
    require(type(value) is str and value in _OBJECTIVES, 'RECOVERY_PHASE_REQUIRED')
    return value


def challenge_bytes():
    return canonical(dict(schema_version=INPUT_SCHEMA, case_version=VERSION, case=CASE,
        scope='FIXED_PUBLIC_CONTROLLED_FAILURE_ONLY',
        prior=dict(source_id='RC1', service_id='synthetic-api', window_id='RC-WINDOW-1',
            checks=20, failures=0, continuous_observation=False),
        newer=dict(source_id='RC2', supersedes_source_id='RC1', service_id='synthetic-api',
            window_id='RC-WINDOW-2', checks=20, failures=1, continuous_observation=False)))


def canonical_phase_spec(which):
    which = phase(which)
    return dict(agent_id=AGENT, capability_id=CAPABILITY, case=CASE, phase=which,
        case_version=VERSION, oracle_id=ORACLE, case_input_sha256=sha(challenge_bytes()),
        request=dict(capability=CAPABILITY, objective=_OBJECTIVES[which],
            context=challenge_bytes().decode(), classification='R0', data_classification='LOCAL_ONLY',
            minimum_tier='NANO', priority='low', task_class='classification', max_cost_usd=0.0,
            preferred_provider=None, response_format='strict_json',
            deterministic_operation='certification_recovery_'+which),
        evidence_scope='ACTUAL_TWO_DISTINCT_ORIGINAL_TASKS_WITH_RETAINED_CONTROLLED_FAILURE',
        precursor_is_certification_case=False, certification='UNVERIFIED')


def canonical_recovery_case():
    return canonical_phase_spec(CORRECTION_PHASE)


def correction_request(prior_execution):
    """Source-owned dynamic binding wrapper; original joining is mandatory."""
    require(type(prior_execution) is dict, 'RECOVERY_ORIGINAL_PRIOR_REQUIRED')
    # This constructor only retains bytes; it cannot attest their origin.
    request = dict(canonical_recovery_case()['request'])
    request['context'] = canonical(dict(fixed_challenge=parse(challenge_bytes()),
        original_prior_execution=prior_execution)).decode()
    require(len(request['context'].encode()) <= 80000, 'RECOVERY_PRIOR_ENVELOPE_TOO_LARGE')
    return request


def sample_bytes(which, *, arrived_at, prior=None):
    which = phase(which)
    _utc(arrived_at)
    require(datetime.fromisoformat(arrived_at.replace('Z', '+00:00')).utcoffset().total_seconds() == 0,
        'RECOVERY_SAMPLE_UTC_REQUIRED')
    facts = parse(challenge_bytes())['prior' if which == PRIOR_PHASE else 'newer']
    if which == CORRECTION_PHASE:
        require(type(prior) is dict and _uuid(prior.get('task_id')),
            'RECOVERY_ORIGINAL_PRIOR_REQUIRED')
    else:
        require(prior is None, 'RECOVERY_PRIOR_PHASE_BINDING_INVALID')
    return canonical(dict(schema_version=INPUT_SCHEMA, case_version=VERSION, case=CASE,
        phase=which, arrived_at=arrived_at, observation=facts,
        prior_original=prior, scope='PUBLIC_SYNTHETIC_ONLY'))


def producer_result(which, *, task_id, input_raw, prior_result_raw=None):
    """Actual producer calculator; the peer must never call this function."""
    which = phase(which)
    require(_uuid(task_id), 'RECOVERY_TASK_REQUIRED')
    source = parse(input_raw)
    require(source.get('phase') == which, 'RECOVERY_INPUT_PHASE_DRIFT')
    observation = source['observation']
    result = dict(schema_version=RESULT_SCHEMA, case_version=VERSION, case=CASE,
        phase=which, task_id=task_id, input_sha256=sha(input_raw),
        source_id=observation['source_id'], source_arrived_at=source['arrived_at'],
        failure_basis_points=observation['failures']*10000//observation['checks'],
        continuous_health='HEALTHY' if which == PRIOR_PHASE else 'UNKNOWN',
        failure_classification='CONTROLLED_FAILURE' if which == PRIOR_PHASE else 'ORIGINAL_FAILURE_RETAINED',
        scope='SUPPLIED_SYNTHETIC_WINDOW_ONLY', cause='UNKNOWN', production_recovery='NOT_ESTABLISHED',
        owner_authority='NOT_GRANTED', model_calls=0, certification='UNVERIFIED')
    if which == PRIOR_PHASE:
        result['wrong_inference'] = 'UNSUPPORTED_CONTINUOUS_HEALTH_FROM_SINGLE_WINDOW'
        result['prior_original'] = None
        result['withdrawn_inference'] = None
    else:
        require(type(prior_result_raw) is bytes, 'RECOVERY_WRONG_ORIGINAL_BYTES_REQUIRED')
        original = parse(prior_result_raw)
        result['prior_original'] = source['prior_original']
        result['retained_wrong_result_sha256'] = sha(prior_result_raw)
        result['withdrawn_inference'] = dict(prior_value=original['continuous_health'],
            corrected_value='UNKNOWN', reason='NEWER_SAMPLE_AND_SINGLE_WINDOW_DO_NOT_PROVE_CONTINUOUS_HEALTH')
    return canonical(result)


def independent_result_check(which, *, task_id, input_raw, result_raw, prior_result_raw=None):
    """Separate fixed oracle, independent of the producer assessment function."""
    which = phase(which)
    require(_uuid(task_id), 'RECOVERY_TASK_REQUIRED')
    source, result = parse(input_raw), parse(result_raw)
    fixed = parse(challenge_bytes())
    facts = fixed['prior' if which == PRIOR_PHASE else 'newer']
    require(set(source)=={'schema_version','case_version','case','phase','arrived_at','observation','prior_original','scope'}
        and source['schema_version']==INPUT_SCHEMA and source['case_version']==VERSION
        and source['case']==CASE and source['phase']==which and canonical(source['observation'])==canonical(facts)
        and source['scope']=='PUBLIC_SYNTHETIC_ONLY'
        and (source['prior_original'] is None if which==PRIOR_PHASE else type(source['prior_original']) is dict),
        'RECOVERY_FIXED_SAMPLE_DRIFT')
    _utc(source['arrived_at'])
    require(datetime.fromisoformat(source['arrived_at'].replace('Z','+00:00')).utcoffset().total_seconds()==0,
        'RECOVERY_SAMPLE_UTC_REQUIRED')
    expected = dict(schema_version=RESULT_SCHEMA, case_version=VERSION, case=CASE,
        phase=which, task_id=task_id, input_sha256=sha(input_raw), source_id=facts['source_id'],
        source_arrived_at=source['arrived_at'], failure_basis_points=0 if which == PRIOR_PHASE else 500,
        continuous_health='HEALTHY' if which == PRIOR_PHASE else 'UNKNOWN',
        failure_classification='CONTROLLED_FAILURE' if which == PRIOR_PHASE else 'ORIGINAL_FAILURE_RETAINED',
        scope='SUPPLIED_SYNTHETIC_WINDOW_ONLY', cause='UNKNOWN', production_recovery='NOT_ESTABLISHED',
        owner_authority='NOT_GRANTED', model_calls=0, certification='UNVERIFIED')
    if which == PRIOR_PHASE:
        require(prior_result_raw is None, 'RECOVERY_PRECURSOR_CANNOT_HAVE_PRIOR')
        expected.update(wrong_inference='UNSUPPORTED_CONTINUOUS_HEALTH_FROM_SINGLE_WINDOW',
            prior_original=None, withdrawn_inference=None)
    else:
        require(type(prior_result_raw) is bytes, 'RECOVERY_WRONG_ORIGINAL_BYTES_REQUIRED')
        original = parse(prior_result_raw)
        require(original.get('phase') == PRIOR_PHASE and original.get('task_id') != task_id
            and original.get('failure_classification') == 'CONTROLLED_FAILURE'
            and original.get('continuous_health') == 'HEALTHY', 'RECOVERY_ORIGINAL_WRONG_INFERENCE_REQUIRED')
        expected.update(prior_original=source['prior_original'],
            retained_wrong_result_sha256=sha(prior_result_raw),
            withdrawn_inference=dict(prior_value='HEALTHY', corrected_value='UNKNOWN',
                reason='NEWER_SAMPLE_AND_SINGLE_WINDOW_DO_NOT_PROVE_CONTINUOUS_HEALTH'))
    require(result == expected and result_raw == canonical(expected), 'RECOVERY_INDEPENDENT_RESULT_REJECTED')
    return expected


def action_type(which, step):
    phase(which)
    require(step in ('setup','read','result','full'), 'RECOVERY_ACTION_REQUIRED')
    return 'agent.certification.recovery.'+which+'.'+step


def retrieve_original_artifact(root, identifier):
    """Bound every source read before allocating, preserving owning byte pins."""
    from .agent_cert_artifact_events import _path
    require(type(identifier) is str and re.fullmatch('[0-9a-f]{32}',identifier) is not None,
        'RECOVERY_ARTIFACT_ID_REQUIRED')
    folder = _path(root/'artifacts'/identifier)
    require(folder.is_dir(), 'RECOVERY_ORIGINAL_ARTIFACT_REQUIRED')
    inventory=[]
    for item in folder.iterdir():
        inventory.append(item.name)
        require(len(inventory)<=2, 'RECOVERY_ARTIFACT_INVENTORY_INVALID')
    require(set(inventory)=={'metadata.json','artifact.json'}, 'RECOVERY_ARTIFACT_INVENTORY_INVALID')
    values=[]
    for name,cap in (('metadata.json',16384),('artifact.json',65536)):
        path=_path(folder/name)
        require(path.is_file() and 0<path.stat().st_size<=cap, 'RECOVERY_ORIGINAL_ARTIFACT_BOUNDS')
        with path.open('rb') as handle:
            raw=handle.read(cap+1)
        require(0<len(raw)<=cap,'RECOVERY_ORIGINAL_ARTIFACT_BOUNDS')
        values.append(raw)
    metadata=parse(values[0],16384)
    require(metadata.get('artifact_id')==identifier and metadata.get('sha256')==sha(values[1])
        and type(metadata.get('bytes')) is int and metadata['bytes']==len(values[1]),
        'RECOVERY_ORIGINAL_ARTIFACT_DIGEST')
    return metadata,values[1]


def validate_metadata(metadata, raw, task, source, *, began, ended):
    from .agent_cert_artifact_events import _metadata, PROVENANCE as BASE_PROVENANCE
    require(type(metadata) is dict and metadata.get('provenance')==PROVENANCE,
        'RECOVERY_SOURCE_PROVENANCE_REQUIRED')
    # Preserve all established Factory metadata checks; this source owns its
    # explicit controlled-challenge provenance, checked above independently.
    _metadata(dict(metadata,provenance=BASE_PROVENANCE),raw,task,source,began=began,ended=ended)


def read_action_span(root, task, which, *, step='full'):
    from .agent_cert_artifact_events import _ledger_lines, _path
    require(_uuid(task),'RECOVERY_TASK_REQUIRED')
    action_type(which,step)
    lines=_ledger_lines(_path(root))
    indices=[i for i,line in enumerate(lines) if (row:=parse(line.encode())).get('task_id')==task
        and (step=='full' or row.get('action_type')==action_type(which,step))]
    require(len(indices)==(6 if step=='full' else 2) and indices[-1]-indices[0]+1==len(indices),
        'RECOVERY_EXACT_ORIGINAL_ACTIONS_REQUIRED')
    return lines[indices[0]:indices[-1]+1]


def validate_full_action_span(lines,task,which):
    from .agent_cert_event_api import _original_chain
    require(type(lines) is list and len(lines)==6,'RECOVERY_EXACT_SIX_ROWS_REQUIRED')
    rows=[parse(line.encode()) for line in lines]
    ids=[]
    for index,step in enumerate(('setup','read','result')):
        _original_chain(lines[index*2:index*2+2],task,action_type(which,step))
        require(all(row.get('agent_id')==AGENT for row in rows[index*2:index*2+2]),
            'RECOVERY_ACTION_IDENTITY_DRIFT')
        ids.append(rows[index*2]['action_id'])
    require(len(set(ids))==3 and all(left['sequence']+1==right['sequence'] and left['sha256']==right['previous_sha256']
        and _utc(left['timestamp'])<=_utc(right['timestamp']) for left,right in zip(rows,rows[1:])),
        'RECOVERY_ORIGINAL_ACTION_ORDER_DRIFT')
    return True


def read_review_action_span(root,task):
    from .agent_cert_artifact_events import _ledger_lines,_path
    require(_uuid(task),'RECOVERY_REVIEW_TASK_REQUIRED')
    lines=_ledger_lines(_path(root))
    indices=[i for i,line in enumerate(lines) if (row:=parse(line.encode())).get('task_id')==task
        and row.get('action_type')==REVIEW_ACTION]
    require(len(indices)==2 and indices[-1]==indices[0]+1,'RECOVERY_EXACT_REVIEW_ACTIONS_REQUIRED')
    return lines[indices[0]:indices[-1]+1]


def execute_phase(which, task_id, *, submitted_request, data_root, ledger, runtime, read_runtime,
        source_revision, runtime_image_id, registry_sha256, read_objective):
    """Explicit owning dispatcher only; each phase retains its own five seconds."""
    phase(which)
    require(_slot.acquire(blocking=False),'RECOVERY_PRODUCER_BUSY')
    try:
        from .agent_cert_artifact_events import _bindings,_path,_registry,_objective_preflight,_ledger_lines
        from .action_records import ActionLedger,ActionRecord,DirectExecutor
        from .artifact_factory import ArtifactFactory
        from .deterministic_ops import DeterministicOps
        root=_path(data_root)
        _path(root/'artifacts')
        bound=_bindings(task_id,runtime,source_revision,runtime_image_id,registry_sha256)
        began=datetime.now(timezone.utc);deadline=time.monotonic()+5
        def remaining():
            left=min(deadline-time.monotonic(),5-(datetime.now(timezone.utc)-began).total_seconds())
            require(left>0,'RECOVERY_SHARED_BOUND_EXCEEDED')
            return left
        require(callable(read_runtime) and canonical(read_runtime())==canonical(bound),
            'RECOVERY_RUNTIME_UNBOUND')
        fixed=canonical_phase_spec(which)
        prior_execution=prior_join=prior_raw=None
        if which==CORRECTION_PHASE:
            envelope=parse(submitted_request['context'].encode(),262144)
            require(set(envelope)=={'fixed_challenge','original_prior_execution'}
                and canonical(envelope['fixed_challenge'])==challenge_bytes(),'RECOVERY_REQUEST_CHALLENGE_DRIFT')
            prior_execution=envelope['original_prior_execution']
            require(type(prior_execution) is dict and prior_execution.get('dispatch',{}).get('recovery_event',{}).get('phase')==PRIOR_PHASE,
                'RECOVERY_SINGLE_ORIGINAL_PRECURSOR_REQUIRED')
            expected=correction_request(prior_execution)
            # This mandatory owning reread is not satisfied by caller hashes.
            prior_join=validate_phase_execution(prior_execution,source_revision=source_revision,
                runtime_image_id=runtime_image_id,registry_sha256=registry_sha256,now=began)
            require(prior_join['phase']==PRIOR_PHASE and prior_join['task_id']!=task_id,
                'RECOVERY_DISTINCT_PRIOR_TASK_REQUIRED')
            reread_phase_original(root,prior_execution,read_objective=read_objective)
            prior_raw=prior_execution['artifact_content_utf8'].encode()
        else:
            expected=fixed['request']
        require(canonical(submitted_request)==canonical(expected),'RECOVERY_SUBMITTED_REQUEST_DRIFT')
        require(type(ledger) is ActionLedger and _path(ledger.path)==root/'action-records.jsonl'
            and not ledger.closed and ledger.worker.is_alive() and ledger.status()['healthy'] is True,
            'RECOVERY_OWNING_LEDGER_REQUIRED')
        _registry(registry_sha256)
        _objective_preflight(root,task_id,fixed,bound,began)
        with ledger.pending.all_tasks_done:
            require(ledger.pending.unfinished_tasks==0,'RECOVERY_PRIOR_ACTION_PENDING')
        require(not any(parse(line.encode()).get('task_id')==task_id for line in _ledger_lines(root)),
            'RECOVERY_TASK_ALREADY_ATTEMPTED')
        remaining()
        executor,factory=DirectExecutor(ledger),ArtifactFactory(root/'artifacts')
        def create(raw):
            metadata=factory.create(kind='json',content=raw.decode(),task_id=task_id,creator=AGENT,
                provenance=PROVENANCE,runtime_revision=source_revision)
            actual_metadata,actual_raw=retrieve_original_artifact(root,metadata['artifact_id'])
            require(canonical(actual_metadata)==canonical(metadata) and actual_raw==raw,
                'RECOVERY_ARTIFACT_READBACK_DRIFT')
            validate_metadata(metadata,raw,task_id,source_revision,began=began,ended=datetime.now(timezone.utc))
            return metadata
        def record(step):
            return ActionRecord(task_id,AGENT,action_type(which,step),'artifact-factory',
                parameters_summary=dict(schema_version=INPUT_SCHEMA if step=='setup' else RESULT_SCHEMA,
                    case_spec_sha256=sha(canonical(fixed)),submitted_request_sha256=sha(canonical(expected)),
                    read_only_observations=True))
        arrived=datetime.now(timezone.utc).isoformat()
        if prior_join is not None:
            require(_utc(prior_join['completed_at'])<_utc(arrived),'RECOVERY_NEWER_ARRIVAL_REQUIRED')
        source=sample_bytes(which,arrived_at=arrived,prior=prior_join)
        setup_action=record('setup')
        setup=executor.execute(setup_action,lambda:create(source))
        reader=DeterministicOps(source_version=source_revision)
        read_action=ActionRecord(task_id,AGENT,action_type(which,'read'),'provided_context.read',target='artifact.json',
            parameters_summary=dict(schema_version=INPUT_SCHEMA,setup_artifact_id=setup['artifact_id'],
                relative_path='artifact.json',expected_sha256=setup['sha256'],read_only_observations=True))
        def read_source():
            raw,digest=reader.retrieve_file(root/'artifacts'/setup['artifact_id'],'artifact.json',expected_sha256=setup['sha256'])
            require(raw==source,'RECOVERY_ACTUAL_SOURCE_DRIFT')
            return dict(source_sha256=digest,result=raw.decode())
        actual=executor.execute(read_action,read_source)
        result_action=record('result')
        result=executor.execute(result_action,lambda:create(producer_result(which,task_id=task_id,
            input_raw=actual['result'].encode(),prior_result_raw=prior_raw)))
        require(ledger.flush(timeout=remaining()) is True,'RECOVERY_DURABLE_ACTION_REQUIRED')
        require(canonical(read_runtime())==canonical(bound),'RECOVERY_RUNTIME_CHANGED')
        _registry(registry_sha256);remaining()
        ended=datetime.now(timezone.utc)
        event=dict(schema_version=EVENT_SCHEMA,case=CASE,phase=which,case_version=VERSION,task_id=task_id,
            source_revision=source_revision,registry_sha256=registry_sha256,runtime_identity_sha256=sha(canonical(bound)),
            case_spec_sha256=sha(canonical(fixed)),submitted_request_sha256=sha(canonical(expected)),
            input_artifact_metadata=setup,setup_action_id=setup_action.action_id,
            read_action_id=read_action.action_id,subject_action_id=result_action.action_id,
            started_at=began.isoformat(),completed_at=ended.isoformat(),durable_action_delivery=True,certification='UNVERIFIED')
        return dict(task_id=task_id,state='COMPLETED',artifact=result,model_calls=0,execution_model='DETERMINISTIC',
            agent_id=AGENT,capability=CAPABILITY,runtime_source_revision=source_revision,recovery_event=event)
    except RecoveryEventError:
        raise
    except Exception:
        raise RecoveryEventError('RECOVERY_EXECUTION_FAILED') from None
    finally:
        _slot.release()


def validate_phase_execution(execution, *, source_revision,runtime_image_id,registry_sha256,now):
    """Exact original phase join; caller bytes still require owning rereads."""
    try:
        from .agent_cert_artifact_events import _bindings
        from .agent_cert_event_api import _original_chain
        from .objective_api import inference_attempt_projection
        require(type(now) is datetime and now.tzinfo is not None,'RECOVERY_TIME_REQUIRED')
        value=parse(canonical(execution),524288)
        require(set(value)=={'case_spec','submitted_request','runtime','runtime_after','runtime_current',
            'submission','dispatch','artifact_metadata','artifact_content_utf8','input_content_utf8',
            'objective_read','original_action_records','observation','prior_execution'},
            'RECOVERY_EXECUTION_FIELDS_INVALID')
        dispatch=value['dispatch'];event=dispatch['recovery_event'];which=phase(event['phase'])
        fixed=canonical_phase_spec(which);task=dispatch['task_id']
        require(canonical(value['case_spec'])==canonical(fixed),'RECOVERY_CASE_SPEC_DRIFT')
        runtime=_bindings(task,value['runtime'],source_revision,runtime_image_id,registry_sha256)
        require(canonical(value['runtime_after'])==canonical(runtime)
            and canonical(value['runtime_current'])==canonical(runtime),'RECOVERY_RUNTIME_DRIFT')
        require(set(dispatch)=={'task_id','state','artifact','model_calls','execution_model','agent_id',
            'capability','runtime_source_revision','recovery_event'} and dispatch['state']=='COMPLETED'
            and dispatch['agent_id']==AGENT and dispatch['capability']==CAPABILITY
            and dispatch['runtime_source_revision']==source_revision and dispatch['execution_model']=='DETERMINISTIC'
            and type(dispatch['model_calls']) is int and dispatch['model_calls']==0,'RECOVERY_DISPATCH_UNBOUND')
        began,ended=_utc(event['started_at']),_utc(event['completed_at'])
        require(0<=(ended-began).total_seconds()<=5 and 0<=(now-ended).total_seconds()<=300,
            'RECOVERY_EVENT_STALE_OR_UNBOUNDED')
        observation=value['observation']
        require(type(observation) is dict and set(observation)=={'started_at','completed_at'}
            and _utc(observation['started_at'])<=began<=ended<=_utc(observation['completed_at'])<=now
            and 0<=(_utc(observation['completed_at'])-_utc(observation['started_at'])).total_seconds()<=5,
            'RECOVERY_OBSERVATION_UNBOUND')
        prior=value['prior_execution'];prior_join=prior_raw=None
        if which==CORRECTION_PHASE:
            require(type(prior) is dict,'RECOVERY_ORIGINAL_PRIOR_REQUIRED')
            require(prior.get('dispatch',{}).get('recovery_event',{}).get('phase')==PRIOR_PHASE,
                'RECOVERY_SINGLE_ORIGINAL_PRECURSOR_REQUIRED')
            prior_join=validate_phase_execution(prior,source_revision=source_revision,runtime_image_id=runtime_image_id,
                registry_sha256=registry_sha256,now=now)
            require(prior_join['phase']==PRIOR_PHASE and prior_join['task_id']!=task,
                'RECOVERY_DISTINCT_PRIOR_TASK_REQUIRED')
            request=correction_request(prior)
            prior_raw=prior['artifact_content_utf8'].encode()
        else:
            require(prior is None,'RECOVERY_PRECURSOR_CANNOT_HAVE_PRIOR')
            request=fixed['request']
        require(canonical(value['submitted_request'])==canonical(request),'RECOVERY_SUBMITTED_REQUEST_DRIFT')
        expected_event=dict(schema_version=EVENT_SCHEMA,case=CASE,phase=which,case_version=VERSION,task_id=task,
            source_revision=source_revision,registry_sha256=registry_sha256,runtime_identity_sha256=sha(canonical(runtime)),
            case_spec_sha256=sha(canonical(fixed)),submitted_request_sha256=sha(canonical(request)),
            input_artifact_metadata=event['input_artifact_metadata'],setup_action_id=event['setup_action_id'],
            read_action_id=event['read_action_id'],subject_action_id=event['subject_action_id'],
            started_at=event['started_at'],completed_at=event['completed_at'],durable_action_delivery=True,certification='UNVERIFIED')
        require(canonical(event)==canonical(expected_event),'RECOVERY_EVENT_BINDING_DRIFT')
        raw=value['artifact_content_utf8'].encode();input_raw=value['input_content_utf8'].encode()
        source=parse(input_raw)
        require(canonical(source.get('prior_original'))==canonical(prior_join) and began<=_utc(source['arrived_at'])<=ended,
            'RECOVERY_SAMPLE_ORIGINAL_BINDING')
        if prior_join is not None:
            require(_utc(prior_join['completed_at'])<_utc(source['arrived_at']),
                'RECOVERY_NEWER_ARRIVAL_REQUIRED')
        independent_result_check(which,task_id=task,input_raw=input_raw,result_raw=raw,prior_result_raw=prior_raw)
        metadata=value['artifact_metadata'];setup=event['input_artifact_metadata']
        require(canonical(dispatch['artifact'])==canonical(metadata),'RECOVERY_RESULT_METADATA_DRIFT')
        validate_metadata(metadata,raw,task,source_revision,began=began,ended=ended)
        validate_metadata(setup,input_raw,task,source_revision,began=began,ended=ended)
        require(setup['artifact_id']!=metadata['artifact_id'],'RECOVERY_DISTINCT_ARTIFACTS_REQUIRED')
        lines=value['original_action_records']
        require(type(lines) is list and len(lines)==6,'RECOVERY_EXACT_SIX_ROWS_REQUIRED')
        rows=[parse(line.encode()) for line in lines]
        ids=[event['setup_action_id'],event['read_action_id'],event['subject_action_id']]
        require(all(_uuid(x) for x in ids) and len(set(ids))==3,'RECOVERY_DISTINCT_ACTIONS_REQUIRED')
        for i,step in enumerate(('setup','read','result')):
            pair=rows[2*i:2*i+2]
            _original_chain(lines[2*i:2*i+2],task,action_type(which,step))
            require(all(row.get('agent_id')==AGENT and row['action_id']==ids[i] for row in pair),
                'RECOVERY_ACTION_IDENTITY_DRIFT')
        require(all(left['sequence']+1==right['sequence'] and left['sha256']==right['previous_sha256']
            and _utc(left['timestamp'])<=_utc(right['timestamp']) for left,right in zip(rows,rows[1:])),
            'RECOVERY_ORIGINAL_ACTION_ORDER_DRIFT')
        # A precursor must precede the later task physically as well as in UTC.
        if prior_join is not None:
            require(prior_join['last_sequence']<rows[0]['sequence'],'RECOVERY_PRIOR_LEDGER_ORDER_DRIFT')
        for i,step,meta,schema in ((0,'setup',setup,INPUT_SCHEMA),(2,'result',metadata,RESULT_SCHEMA)):
            expected_parameters=dict(schema_version=schema,case_spec_sha256=sha(canonical(fixed)),
                submitted_request_sha256=sha(canonical(request)),read_only_observations=True)
            base=dict(task_id=task,agent_id=AGENT,action_type=action_type(which,step),tool='artifact-factory',
                target='',classification='R0',parameters_summary=expected_parameters,model_backend='deterministic',
                execution_location='local',parent_agent=None,workflow_id=None,action_id=ids[i])
            common=set(base)|{'phase','timestamp','sequence','previous_sha256','sha256'}
            first,last=rows[2*i:2*i+2]
            require(set(first)==common and set(last)==common|{'success','duration_ms','result_summary'}
                and all(row.get(key)==expected for row in (first,last) for key,expected in base.items())
                and last.get('success') is True and type(last.get('duration_ms')) in (int,float)
                and math.isfinite(last['duration_ms']) and 0<=last['duration_ms']<=5000
                and last.get('result_summary')==dict(type='dict',artifact_id=meta['artifact_id'],
                    sha256=meta['sha256'],location='artifact.json')
                and began<=_utc(first['timestamp'])<=_utc(meta['timestamp'])<=_utc(last['timestamp'])<=ended,
                'RECOVERY_ORIGINAL_REQUEST_ACTION_DRIFT')
        read_first,read_last=rows[2:4]
        require(all(row.get('tool')=='provided_context.read' and row.get('target')=='artifact.json'
            and row.get('classification')=='R0' and row.get('model_backend')=='deterministic'
            and row.get('execution_location')=='local' and row.get('parent_agent') is None
            and row.get('workflow_id') is None and row.get('parameters_summary')==dict(schema_version=INPUT_SCHEMA,
                setup_artifact_id=setup['artifact_id'],relative_path='artifact.json',expected_sha256=setup['sha256'],
                read_only_observations=True) for row in (read_first,read_last))
            and read_last.get('success') is True and type(read_last.get('duration_ms')) in (int,float)
            and math.isfinite(read_last['duration_ms']) and 0<=read_last['duration_ms']<=5000
            and read_last.get('result_summary')==dict(type='dict',source_sha256=sha(input_raw),
                output_sha256=sha(input_raw),output_length=len(input_raw.decode()))
            and _utc(setup['timestamp'])<=_utc(read_first['timestamp'])<=_utc(read_last['timestamp'])<=_utc(metadata['timestamp']),
            'RECOVERY_ACTUAL_READ_CUSTODY_DRIFT')
        require(_utc(source['arrived_at'])<=_utc(setup['timestamp']),'RECOVERY_SAMPLE_ARRIVAL_ORDER_DRIFT')
        submission,read=value['submission'],value['objective_read']
        require(type(submission) is list and len(submission)==2 and type(submission[0]) is int and submission[0]==202
            and submission[1].get('id')==task
            and submission[1].get('steps')==[dict(capability=CAPABILITY,dispatch=dispatch)],'RECOVERY_ORIGINAL_SUBMISSION_DRIFT')
        require(type(read) is list and len(read)==2 and type(read[0]) is int and read[0]==200,
            'RECOVERY_ORIGINAL_OBJECTIVE_REQUIRED')
        objective=read[1];immutable=objective.get('execution_metadata')
        require(objective.get('id')==task and type(objective.get('revision')) is int and objective['revision']==0
            and objective.get('state')=='COMPLETED'
            and objective.get('steps')==[dict(capability=CAPABILITY,dispatch=dispatch,revision=0,state='completed')],
            'RECOVERY_ORIGINAL_OBJECTIVE_DRIFT')
        require(type(immutable) is dict and immutable.get('schema_version')=='jarvis.authoritative-execution.v1'
            and immutable.get('authoritative') is True and immutable.get('task_id')==task
            and type(immutable.get('revision')) is int and immutable['revision']==0 and immutable.get('state')=='COMPLETED'
            and immutable.get('runtime')==runtime and immutable.get('jobs')==[] and immutable.get('agent_execution')==[]
            and immutable.get('inference_attempts')==inference_attempt_projection([])
            and immutable.get('model_content_is_authoritative_metadata') is False
            and immutable.get('provenance',{}).get('runtime')=='IMMUTABLE_OBJECTIVE_RUNTIME'
            and _utc(observation['started_at'])<=_utc(immutable.get('created_at'))<=began
            and _utc(rows[-1]['timestamp'])<=_utc(immutable.get('completed_at'))<=_utc(immutable.get('updated_at'))
            <=_utc(observation['completed_at']), 'RECOVERY_IMMUTABLE_OBJECTIVE_DRIFT')
        if prior_join is not None:
            require(_utc(prior_join['completed_at'])<_utc(immutable['created_at']),
                'RECOVERY_SECOND_TASK_AFTER_PRIOR_REQUIRED')
        return dict(task_id=task,case=CASE,phase=which,artifact_id=metadata['artifact_id'],result_sha256=sha(raw),
            case_spec_sha256=sha(canonical(fixed)),runtime=runtime,registry_sha256=registry_sha256,
            input_artifact_id=setup['artifact_id'],input_sha256=sha(input_raw),
            first_sequence=rows[0]['sequence'],last_sequence=rows[-1]['sequence'],
            original_action_span_sha256=sha(''.join(lines).encode()),
            execution_metadata_sha256=sha(canonical(immutable)),completed_at=immutable['completed_at'],
            prior_original=prior_join,certification='UNVERIFIED')
    except RecoveryEventError:
        raise
    except Exception:
        raise RecoveryEventError('RECOVERY_ORIGINAL_PHASE_REJECTED') from None


def reread_phase_original(root, execution, *, read_objective):
    """Mandatory owning-domain equality; immutable submissions alone are unsafe."""
    require(callable(read_objective),'RECOVERY_OWNING_OBJECTIVE_READER_REQUIRED')
    task=execution['dispatch']['task_id'];which=execution['dispatch']['recovery_event']['phase']
    objective=read_objective(task)
    require(canonical(objective)==canonical(execution['objective_read'][1]),'RECOVERY_OWNING_OBJECTIVE_DRIFT')
    for metadata,raw in ((execution['artifact_metadata'],execution['artifact_content_utf8'].encode()),
            (execution['dispatch']['recovery_event']['input_artifact_metadata'],execution['input_content_utf8'].encode())):
        original,content=retrieve_original_artifact(root,metadata['artifact_id'])
        require(canonical(original)==canonical(metadata) and content==raw,'RECOVERY_OWNING_ARTIFACT_DRIFT')
    require(read_action_span(root,task,which)==execution['original_action_records'],'RECOVERY_OWNING_LEDGER_DRIFT')
    return sha(canonical(execution))


def validate_recovery_execution(execution, **pins):
    require(type(execution) is dict and execution.get('dispatch',{}).get('recovery_event',{}).get('phase')==CORRECTION_PHASE,
        'RECOVERY_PRECURSOR_IS_NOT_COMPLETED_CASE')
    return validate_phase_execution(execution,**pins)


def canonical_review_request(execution, *, nonce):
    require(_uuid(nonce),'RECOVERY_REVIEW_NONCE_REQUIRED')
    request=dict(canonical_recovery_case()['request'])
    request.update(capability='responsibility.a26',objective=REVIEW_OBJECTIVE,
        deterministic_operation='certification_recovery_review',
        context=canonical(dict(execution=execution,expected_execution_sha256=sha(canonical(execution)),
            expected_source_revision=execution['runtime']['source_revision'],review_nonce=nonce)).decode())
    require(len(request['context'].encode())<=80000,'RECOVERY_REVIEW_CONTEXT_BOUND')
    return request


def _review_objective_preflight(root,task,runtime,now,deadline):
    from contextlib import closing
    import sqlite3
    import json
    from .agent_cert_artifact_events import _path
    path=_path(root/'objectives.db')
    require(path.is_file() and 0<path.stat().st_size<=8*1024*1024,'RECOVERY_REVIEW_OBJECTIVE_BOUND')
    for suffix in ('-wal','-shm'):
        side=_path(root/('objectives.db'+suffix))
        require(not side.exists() or (side.is_file() and side.stat().st_size<=8*1024*1024),
            'RECOVERY_REVIEW_OBJECTIVE_SIDECAR_BOUND')
    require(time.monotonic()<deadline,'RECOVERY_REVIEW_SHARED_BOUND_EXCEEDED')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,
            timeout=max(0,min(1,deadline-time.monotonic())))) as db:
        db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,65536)
        db.setlimit(sqlite3.SQLITE_LIMIT_COLUMN,32)
        db.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH,1024)
        db.set_progress_handler(lambda:int(time.monotonic()>=deadline),100)
        rows=db.execute('SELECT objective_hash,state,steps_json FROM objectives WHERE id=? LIMIT 2',(task,)).fetchall()
        turns=db.execute('SELECT revision FROM objective_turns WHERE task=? LIMIT 1',(task,)).fetchone()
        times=db.execute('SELECT revision,created_at,updated_at FROM objective_metadata WHERE task=? LIMIT 2',(task,)).fetchall()
        pins=db.execute('SELECT revision,host_id,source_revision,version,image_digest FROM objective_runtime WHERE task=? LIMIT 2',(task,)).fetchall()
    require(time.monotonic()<deadline and len(rows)==1 and rows[0]==(sha(REVIEW_OBJECTIVE.encode()),'dispatching',
        json.dumps(['responsibility.a26'])) and turns is None and len(times)==1
        and type(times[0][0]) is int and times[0][0]==0 and times[0][1]==times[0][2]
        and 0<=(now-_utc(times[0][1])).total_seconds()<=300
        and pins==[(0,runtime['host_id'],runtime['source_revision'],runtime['version'],runtime['image_digest'])],
        'RECOVERY_REVIEW_ORIGINAL_OBJECTIVE_DRIFT')


def execute_review(task_id, *, actor, submitted_request,data_root,ledger,runtime,read_runtime,
        source_revision,runtime_image_id,registry_sha256,read_objective):
    """One fixed distinct original peer, actual custody read twice before write."""
    require(actor=='a26' and submitted_request.get('capability')=='responsibility.a26',
        'RECOVERY_FIXED_DISTINCT_REVIEWER_REQUIRED')
    require(_slot.acquire(blocking=False),'RECOVERY_REVIEW_BUSY')
    try:
        from .agent_cert_artifact_events import _path,_registry,_ledger_lines
        from .action_records import ActionLedger,ActionRecord,DirectExecutor
        from .artifact_factory import ArtifactFactory
        root=_path(data_root);began=datetime.now(timezone.utc);deadline=time.monotonic()+5
        def remaining():
            left=min(deadline-time.monotonic(),5-(datetime.now(timezone.utc)-began).total_seconds())
            require(left>0,'RECOVERY_REVIEW_SHARED_BOUND_EXCEEDED')
            return left
        require(_uuid(task_id) and callable(read_runtime) and canonical(read_runtime())==canonical(runtime),
            'RECOVERY_REVIEW_RUNTIME_REQUIRED')
        require(runtime.get('source_revision')==source_revision and runtime.get('image_digest')==runtime_image_id,
            'RECOVERY_REVIEW_RUNTIME_PINS')
        envelope=parse(submitted_request['context'].encode(),80000)
        require(set(envelope)=={'execution','expected_execution_sha256','expected_source_revision','review_nonce'},
            'RECOVERY_REVIEW_FIELDS_INVALID')
        execution=envelope['execution']
        require(envelope['expected_source_revision']==source_revision
            and envelope['expected_execution_sha256']==sha(canonical(execution))
            and canonical(submitted_request)==canonical(canonical_review_request(execution,nonce=envelope['review_nonce'])),
            'RECOVERY_REVIEW_REQUEST_DRIFT')
        _registry(registry_sha256)
        _review_objective_preflight(root,task_id,runtime,began,deadline)
        require(type(ledger) is ActionLedger and _path(ledger.path)==root/'action-records.jsonl'
            and not ledger.closed and ledger.worker.is_alive() and ledger.status()['healthy'] is True,
            'RECOVERY_REVIEW_OWNING_LEDGER_REQUIRED')
        with ledger.pending.all_tasks_done:
            require(ledger.pending.unfinished_tasks==0,'RECOVERY_REVIEW_PRIOR_ACTION_PENDING')
        require(not any(parse(line.encode()).get('task_id')==task_id for line in _ledger_lines(root)),
            'RECOVERY_REVIEW_TASK_ALREADY_ATTEMPTED')
        pins=dict(source_revision=source_revision,runtime_image_id=runtime_image_id,registry_sha256=registry_sha256)
        joined=validate_recovery_execution(execution,**pins,now=datetime.now(timezone.utc))
        require(task_id not in (joined['task_id'],joined['prior_original']['task_id']),
            'RECOVERY_DISTINCT_REVIEW_TASK_REQUIRED')
        originals=(execution['prior_execution'],execution)
        frozen=canonical(execution)
        for original in originals:
            remaining();reread_phase_original(root,original,read_objective=read_objective)
        # Recompute using the independent fixed oracle, never producer_result.
        require(canonical(execution)==frozen and validate_recovery_execution(execution,**pins,
            now=datetime.now(timezone.utc))==joined,'RECOVERY_REVIEW_INPUT_CHANGED')
        for original in originals:
            remaining();reread_phase_original(root,original,read_objective=read_objective)
        require(canonical(execution)==frozen and canonical(read_runtime())==canonical(runtime),
            'RECOVERY_REVIEW_DOMAINS_CHANGED')
        _registry(registry_sha256);remaining()
        report=dict(schema_version=REVIEW_SCHEMA,subject_agent_id=AGENT,subject_capability_id=CAPABILITY,
            dimension='recovery',test_case='complete',reviewer_id='a26',reviewer_capability_id='responsibility.a26',
            task_id=task_id,source_revision=source_revision,runtime_image_id=runtime_image_id,
            execution_evidence_sha256=sha(frozen),case_spec_sha256=joined['case_spec_sha256'],
            result_sha256=joined['result_sha256'],review_nonce=envelope['review_nonce'],
            reviewed_at=datetime.now(timezone.utc).isoformat(),oracle_id=ORACLE,test_result='PASS',review_errors=[],
            model_calls=0,execution_model='DETERMINISTIC',subject_execution_verification='TWO_ORIGINAL_OBJECTIVE_ARTIFACT_ACTION_CHAINS_JOINED',
            subject_domain_join=joined,certification='UNVERIFIED')
        factory=ArtifactFactory(root/'artifacts')
        action=ActionRecord(task_id,'a26',REVIEW_ACTION,'artifact-factory',parameters_summary=dict(
            schema_version=REVIEW_SCHEMA,read_only_observations=True))
        artifact=DirectExecutor(ledger).execute(action,lambda:factory.create(kind='json',content=canonical(report).decode(),
            task_id=task_id,creator='a26',provenance='Deterministic computation; zero model calls',runtime_revision=source_revision))
        actual,raw=retrieve_original_artifact(root,artifact['artifact_id'])
        require(canonical(actual)==canonical(artifact) and raw==canonical(report),'RECOVERY_REVIEW_ARTIFACT_DRIFT')
        require(ledger.flush(timeout=remaining()) is True,'RECOVERY_REVIEW_DURABLE_REQUIRED')
        require(canonical(read_runtime())==canonical(runtime),'RECOVERY_REVIEW_RUNTIME_CHANGED')
        _registry(registry_sha256);remaining()
        return dict(task_id=task_id,state='COMPLETED',artifact=artifact,model_calls=0,execution_model='DETERMINISTIC',
            agent_id='a26',capability='responsibility.a26',runtime_source_revision=source_revision,
            review_action_id=action.action_id)
    except RecoveryEventError:
        raise
    except Exception:
        raise RecoveryEventError('RECOVERY_REVIEW_REJECTED') from None
    finally:
        _slot.release()


def validate_reviewed_recovery(execution,peer,*,source_revision,runtime_image_id,registry_sha256,now):
    """Pure admission bridge: both originals plus actual persisted peer custody."""
    from .agent_cert_identity_review import action_span
    from .agent_cert_artifact_events import _metadata,PROVENANCE as BASE_PROVENANCE
    from .objective_api import inference_attempt_projection
    joined=validate_recovery_execution(execution,source_revision=source_revision,runtime_image_id=runtime_image_id,
        registry_sha256=registry_sha256,now=now)
    require(type(peer) is dict and set(peer)=={'submitted_request','runtime','runtime_after','submission','dispatch',
        'artifact_metadata','artifact_content_utf8','objective_read','action_records','observation'},
        'RECOVERY_PEER_FIELDS_REQUIRED')
    raw=peer['artifact_content_utf8'].encode();report=parse(raw)
    require(canonical(peer['submitted_request'])==canonical(canonical_review_request(execution,nonce=report['review_nonce'])),
        'RECOVERY_PEER_REQUEST_DRIFT')
    dispatch=peer['dispatch'];task=dispatch['task_id'];runtime=joined['runtime']
    require(_uuid(task) and task not in (joined['task_id'],joined['prior_original']['task_id'])
        and canonical(peer['runtime'])==canonical(runtime) and canonical(peer['runtime_after'])==canonical(runtime),
        'RECOVERY_DISTINCT_PEER_IDENTITY_REQUIRED')
    require(set(dispatch)=={'task_id','state','artifact','model_calls','execution_model','agent_id','capability',
        'runtime_source_revision','review_action_id'} and dispatch['state']=='COMPLETED'
        and dispatch['agent_id']=='a26' and dispatch['capability']=='responsibility.a26'
        and dispatch['runtime_source_revision']==source_revision and dispatch['execution_model']=='DETERMINISTIC'
        and type(dispatch['model_calls']) is int and dispatch['model_calls']==0,
        'RECOVERY_PEER_DISPATCH_DRIFT')
    expected=dict(schema_version=REVIEW_SCHEMA,subject_agent_id=AGENT,subject_capability_id=CAPABILITY,
        dimension='recovery',test_case='complete',reviewer_id='a26',reviewer_capability_id='responsibility.a26',
        task_id=task,source_revision=source_revision,runtime_image_id=runtime_image_id,
        execution_evidence_sha256=sha(canonical(execution)),case_spec_sha256=joined['case_spec_sha256'],
        result_sha256=joined['result_sha256'],review_nonce=report['review_nonce'],reviewed_at=report['reviewed_at'],
        oracle_id=ORACLE,test_result='PASS',review_errors=[],model_calls=0,execution_model='DETERMINISTIC',
        subject_execution_verification='TWO_ORIGINAL_OBJECTIVE_ARTIFACT_ACTION_CHAINS_JOINED',
        subject_domain_join=joined,certification='UNVERIFIED')
    require(raw==canonical(expected),'RECOVERY_PEER_FIXED_ORACLE_DRIFT')
    observation=peer['observation'];began,ended=_utc(observation['started_at']),_utc(observation['completed_at'])
    require(set(observation)=={'started_at','completed_at'} and 0<=(ended-began).total_seconds()<=5
        and ended<=now and began<=_utc(report['reviewed_at'])<=ended,'RECOVERY_PEER_OBSERVATION_DRIFT')
    metadata=peer['artifact_metadata']
    require(metadata.get('creator_agents')==['a26'] and metadata.get('provenance')=='Deterministic computation; zero model calls'
        and canonical(dispatch['artifact'])==canonical(metadata),'RECOVERY_PEER_ARTIFACT_IDENTITY_DRIFT')
    # Keep the established exact Factory metadata shape, while independently
    # enforcing the distinct source-owned A26 creator/provenance above.
    _metadata(dict(metadata,creator_agents=[AGENT],provenance=BASE_PROVENANCE),raw,task,source_revision,began=began,ended=ended)
    lines=peer['action_records']
    require(type(lines) is list and len(lines)==2,'RECOVERY_EXACT_PEER_ACTIONS_REQUIRED')
    action_span(lines,task_id=task,agent_id='a26',action_type=REVIEW_ACTION,schema=REVIEW_SCHEMA,
        metadata=metadata,began=began,ended=ended,action_id=dispatch['review_action_id'])
    submission,read=peer['submission'],peer['objective_read']
    require(type(submission) is list and len(submission)==2 and type(submission[0]) is int and submission[0]==202
        and submission[1].get('id')==task and submission[1].get('steps')==[dict(capability='responsibility.a26',dispatch=dispatch)],
        'RECOVERY_PEER_ORIGINAL_SUBMISSION_DRIFT')
    require(type(read) is list and len(read)==2 and type(read[0]) is int and read[0]==200,
        'RECOVERY_PEER_ORIGINAL_OBJECTIVE_REQUIRED')
    objective=read[1];immutable=objective.get('execution_metadata')
    require(objective.get('id')==task and type(objective.get('revision')) is int and objective['revision']==0
        and objective.get('state')=='COMPLETED'
        and objective.get('steps')==[dict(capability='responsibility.a26',dispatch=dispatch,revision=0,state='completed')],
        'RECOVERY_PEER_OBJECTIVE_DRIFT')
    first,last=[parse(line.encode()) for line in lines]
    require(type(immutable) is dict and immutable.get('schema_version')=='jarvis.authoritative-execution.v1'
        and immutable.get('authoritative') is True and immutable.get('task_id')==task
        and type(immutable.get('revision')) is int and immutable['revision']==0 and immutable.get('state')=='COMPLETED'
        and immutable.get('runtime')==runtime and immutable.get('jobs')==[] and immutable.get('agent_execution')==[]
        and immutable.get('inference_attempts')==inference_attempt_projection([])
        and immutable.get('model_content_is_authoritative_metadata') is False
        and immutable.get('provenance',{}).get('runtime')=='IMMUTABLE_OBJECTIVE_RUNTIME'
        and began<=_utc(immutable.get('created_at'))<=_utc(report['reviewed_at'])<=_utc(first['timestamp'])
        <=_utc(last['timestamp'])<=_utc(immutable.get('completed_at'))<=_utc(immutable.get('updated_at'))<=ended,
        'RECOVERY_PEER_IMMUTABLE_OBJECTIVE_DRIFT')
    require(_utc(joined['completed_at'])<_utc(immutable['created_at'])
        and joined['last_sequence']<first['sequence'],'RECOVERY_PEER_AFTER_ORIGINAL_REQUIRED')
    return dict(subject_domain_join=joined,review_task_id=task,review_result_sha256=sha(raw),
        review_action_sha256=last['sha256'],review_objective_sha256=sha(canonical(immutable)),certification='UNVERIFIED')
