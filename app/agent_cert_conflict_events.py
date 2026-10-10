"""Fixed public source-quality conflict, not model votes or production advice.

Two existing registered peers preserve their original proposals/findings. A19
reconciles by inspectable underlying source data, and a distinct A26 reviews
original custody. Copied claims remain copied even when their file hash is valid.
"""
from __future__ import annotations
from datetime import datetime,timezone
from contextlib import closing
import json,math,re,sqlite3,threading,time

from .agent_cert_artifact_events import canonical,parse,sha,_utc,_uuid,_path,_registry,_bindings,_ledger_lines
from .agent_cert_recovery_events import retrieve_original_artifact

CASE='conflict_resolution:complete'
VERSION='a19.original-peer-source-quality.v1'
ORACLE=VERSION
INPUT_SCHEMA='prime.a19-conflict-input.v1'
RESULT_SCHEMA='prime.a19-conflict-result.v1'
EVENT_SCHEMA='prime.a19-conflict-event.v1'
REVIEW_SCHEMA='prime.a19-conflict-review.v1'
PROVENANCE='FIXED_PUBLIC_PEER_CONFLICT_NO_MODEL_OR_EXECUTION'
PHASES=('code_proposal','fixture_finding','reconciliation')
ORIENTATIONS=('standard','swapped')
ACTORS={'code_proposal':('a17','responsibility.a17'),
    'fixture_finding':('a18','responsibility.a18'),'reconciliation':('a19','responsibility.a19'),
    'review':('a26','responsibility.a26')}
REVIEW_ACTION='agent.certification.conflict.review'
_slot=threading.BoundedSemaphore(1)
OBJECTIVES={
    'code_proposal':'Read the fixed public design/assessment-source challenge and preserve an original proposed code behavior with its source limitations. This is an advisory literal proposal, not code execution, release, approval, health confirmation or model reasoning.',
    'fixture_finding':'Read the fixed public assessment-source fixture and preserve original reproducible findings or unresolved source gaps with an advisory recommendation. Do not execute proposed code, call models, claim production health or grant authority.',
    'reconciliation':'Read both distinct original registered peer recommendations and their underlying original source artifacts. Reconcile the conflicting assessment recommendations by source availability, exact underlying data and reproducibility; preserve both recommendations and unsupported claims. Do not vote by peer identity or status, execute code, confirm production health, sign or award L7.',
    'review':'Independently review the original A17/A18 source-quality conflict and actual A19 reconciliation. Reread all original Objective/input/result/action domains twice. Use the fixed independent source-quality oracle, never a producer builder or agent/status vote. No code execution, models, health confirmation, authority, signing or L7.'}


class ConflictEventError(ValueError):pass


def require(value,code):
    if value is not True:raise ConflictEventError(code) from None


def phase(value):
    require(type(value) is str and value in PHASES+('review',),'CONFLICT_PHASE_REQUIRED')
    return value


def orientation(value):
    require(type(value) is str and value in ORIENTATIONS,'CONFLICT_ORIENTATION_REQUIRED')
    return value


def public_sources():
    """Labels cannot supply missing observations or authenticate a copied claim."""
    observations=[dict(index=index,status='FAIL' if index==7 else 'PASS') for index in range(20)]
    return dict(legacy=dict(source_id='CF-LEGACY',source_scope='COPIED_PUBLIC_MEMO',
        copied_claim='HEALTHY',underlying_observations=None,original_observation_binding=None,
        recommendation='RETURN_HEALTHY',production_health='NOT_ESTABLISHED'),
        current=dict(source_id='CF-CURRENT',source_scope='SUPPLIED_PUBLIC_FIXTURE_ONLY',
            underlying_observations=observations,continuous_observation=False,
            recommendation='REPORT_WINDOW_KEEP_CONTINUOUS_HEALTH_UNKNOWN',production_health='NOT_ESTABLISHED'))


def challenge_bytes():
    return canonical(dict(schema_version=INPUT_SCHEMA,case=CASE,case_version=VERSION,
        source_quality_rule='AVAILABLE_EXACT_ORIGINAL_UNDERLYING_DATA_AND_REPRODUCIBLE_LIMITED_FINDING',
        orientations=list(ORIENTATIONS),sources=public_sources(),
        forbidden_basis=['peer_identity','peer_status','self_declared_quality','hash_alone'],
        scope='CONTROLLED_PUBLIC_SOURCE_CONFLICT_ONLY'))


def assigned_source(which,variant):
    phase(which);orientation(variant)
    require(which in PHASES[:2],'CONFLICT_PEER_PHASE_REQUIRED')
    key='legacy' if (which=='code_proposal')==(variant=='standard') else 'current'
    return public_sources()[key]


def canonical_phase_spec(which,variant='standard'):
    phase(which);orientation(variant);actor,capability=ACTORS[which]
    return dict(agent_id=actor,capability_id=capability,case=CASE,phase=which,orientation=variant,
        case_version=VERSION,oracle_id=ORACLE,case_input_sha256=sha(challenge_bytes()),
        request=dict(capability=capability,objective=OBJECTIVES[which],context=canonical(dict(
            fixed_challenge=parse(challenge_bytes()),orientation=variant)).decode(),classification='R0',
            data_classification='LOCAL_ONLY',minimum_tier='NANO',priority='low',task_class='classification',
            max_cost_usd=0.0,preferred_provider=None,response_format='strict_json',
            deterministic_operation='certification_conflict_'+which),
        evidence_scope='FOUR_DISTINCT_ORIGINAL_OBJECTIVES_SOURCE_QUALITY_NOT_VOTING',certification='UNVERIFIED')


def canonical_conflict_case():return canonical_phase_spec('reconciliation')


def phase_request(which,variant='standard',*,peer_executions=None,execution=None,nonce=None):
    request=dict(canonical_phase_spec(which,variant)['request'])
    body=dict(fixed_challenge=parse(challenge_bytes()),orientation=variant)
    if which=='reconciliation':
        require(type(peer_executions) is list and len(peer_executions)==2 and execution is None and nonce is None,
            'CONFLICT_TWO_ORIGINAL_PEERS_REQUIRED')
        body['peer_executions']=peer_executions
    elif which=='review':
        require(type(execution) is dict and peer_executions is None and _uuid(nonce),'CONFLICT_REVIEW_BINDING_REQUIRED')
        body.update(execution=execution,expected_execution_sha256=sha(canonical(execution)),review_nonce=nonce)
    else:require(peer_executions is None and execution is None and nonce is None,'CONFLICT_PEER_REQUEST_DRIFT')
    request['context']=canonical(body).decode()
    require(len(request['context'].encode())<=80000,'CONFLICT_CONTEXT_BOUND')
    return request


def _source_assessment(source):
    """Producer calculator: content availability, never an actor or status."""
    observations=source.get('underlying_observations')
    if observations is None:return dict(source_quality='UNVERIFIED_COPIED_CLAIM',checks=None,failures=None,
        failure_basis_points=None,recommendation='RETURN_HEALTHY',continuous_health='HEALTHY',
        supported=False,source_gap='NO_ORIGINAL_UNDERLYING_OBSERVATION_BINDING')
    require(type(observations) is list and len(observations)==20,'CONFLICT_ORIGINAL_OBSERVATIONS_REQUIRED')
    require(all(type(row) is dict and set(row)=={'index','status'} and type(row['index']) is int
        and row['index']==index and row['status'] in ('PASS','FAIL') for index,row in enumerate(observations)),
        'CONFLICT_OBSERVATION_SCHEMA')
    failures=sum(row['status']=='FAIL' for row in observations)
    return dict(source_quality='REPRODUCIBLE_LIMITED_PUBLIC_FIXTURE',checks=len(observations),failures=failures,
        failure_basis_points=failures*10000//len(observations),
        recommendation='REPORT_WINDOW_KEEP_CONTINUOUS_HEALTH_UNKNOWN',continuous_health='UNKNOWN',
        supported=True,source_gap=None)


def producer_result(which,*,task_id,input_raw,peer_results=None):
    phase(which);require(which in PHASES and _uuid(task_id),'CONFLICT_PRODUCER_REQUIRED')
    source=parse(input_raw);actor,capability=ACTORS[which]
    result=dict(schema_version=RESULT_SCHEMA,case=CASE,case_version=VERSION,phase=which,
        orientation=source['orientation'],task_id=task_id,agent_id=actor,capability_id=capability,
        input_sha256=sha(input_raw),status='completed',uncertainty='NO_PRODUCTION_OR_CONTINUOUS_HEALTH_PROOF',
        proposed_actions=[],model_calls=0,execution='NOT_PERFORMED',certification='UNVERIFIED')
    if which in PHASES[:2]:
        result.update(source_sha256=sha(canonical(source['source'])),source_id=source['source']['source_id'],
            result=_source_assessment(source['source']),source_scope=source['source']['source_scope'],
            contribution_kind='CODE_BEHAVIOR_PROPOSAL_ONLY' if which=='code_proposal' else 'PUBLIC_FIXTURE_FINDING_ONLY')
    else:
        require(type(peer_results) is list and len(peer_results)==2,'CONFLICT_ORIGINAL_RECOMMENDATIONS_REQUIRED')
        sources=[item['source'] for item in source['peer_sources']]
        assessments=[_source_assessment(item) for item in sources]
        winners=[index for index,item in enumerate(assessments) if item['supported'] is True]
        require(len(winners)==1,'CONFLICT_UNIQUE_SUPPORTED_SOURCE_REQUIRED')
        index=winners[0]
        result.update(result=dict(selected_source_id=sources[index]['source_id'],
            selected_peer_task_id=source['peer_sources'][index]['task_id'],
            selection_basis='AVAILABLE_EXACT_ORIGINAL_UNDERLYING_DATA_AND_REPRODUCIBLE_LIMITED_FINDING',
            failure_basis_points=assessments[index]['failure_basis_points'],continuous_health='UNKNOWN',
            production_health='NOT_ESTABLISHED',rejected_unsupported_claim='HEALTHY',
            preserved_recommendations=[dict(task_id=item['task_id'],sha256=sha(canonical(item)),
                original_result=item['result']) for item in peer_results]),source_scope='SUPPLIED_PUBLIC_FIXTURE_ONLY')
    return canonical(result)


def independent_result_check(which,*,task_id,input_raw,result_raw,peer_results=None):
    """Fixed independent oracle; no producer_result or source-assessment call."""
    phase(which);require(which in PHASES and _uuid(task_id),'CONFLICT_ORACLE_PHASE_REQUIRED')
    source,result=parse(input_raw),parse(result_raw);actor,capability=ACTORS[which]
    variant=orientation(source['orientation'])
    base=dict(schema_version=RESULT_SCHEMA,case=CASE,case_version=VERSION,phase=which,orientation=variant,
        task_id=task_id,agent_id=actor,capability_id=capability,input_sha256=sha(input_raw),status='completed',
        uncertainty='NO_PRODUCTION_OR_CONTINUOUS_HEALTH_PROOF',proposed_actions=[],model_calls=0,
        execution='NOT_PERFORMED',certification='UNVERIFIED')
    # Exact fixed public source body, not self-declared quality or a valid file
    # digest, determines which underlying observations can be checked.
    def fixed_assessment(item):
        facts=public_sources()
        if canonical(item)==canonical(facts['legacy']):
            return dict(source_quality='UNVERIFIED_COPIED_CLAIM',checks=None,failures=None,
                failure_basis_points=None,recommendation='RETURN_HEALTHY',continuous_health='HEALTHY',
                supported=False,source_gap='NO_ORIGINAL_UNDERLYING_OBSERVATION_BINDING')
        require(canonical(item)==canonical(facts['current']),'CONFLICT_FIXED_ORIGINAL_SOURCE_DRIFT')
        # Independent literal check and recomputation against twenty original
        # supplied records, no producer calculator and no preference for actor.
        observations=item['underlying_observations']
        failures=0
        for index,row in enumerate(observations):
            require(type(row['index']) is int and row['index']==index and row['status']==('FAIL' if index==7 else 'PASS'),
                'CONFLICT_FIXED_ORIGINAL_OBSERVATION_DRIFT')
            if row['status']=='FAIL':failures+=1
        require(len(observations)==20 and failures==1,'CONFLICT_INDEPENDENT_SAMPLE_DRIFT')
        return dict(source_quality='REPRODUCIBLE_LIMITED_PUBLIC_FIXTURE',checks=20,failures=1,
            failure_basis_points=500,recommendation='REPORT_WINDOW_KEEP_CONTINUOUS_HEALTH_UNKNOWN',
            continuous_health='UNKNOWN',supported=True,source_gap=None)
    if which in PHASES[:2]:
        require(canonical(source['source'])==canonical(assigned_source(which,variant)),
            'CONFLICT_SOURCE_ORIGIN_DRIFT')
        base.update(source_sha256=sha(canonical(source['source'])),source_id=source['source']['source_id'],
            result=fixed_assessment(source['source']),source_scope=source['source']['source_scope'],
            contribution_kind='CODE_BEHAVIOR_PROPOSAL_ONLY' if which=='code_proposal' else 'PUBLIC_FIXTURE_FINDING_ONLY')
    else:
        require(type(peer_results) is list and len(peer_results)==2,'CONFLICT_ORIGINAL_PEER_RESULTS_REQUIRED')
        items=source['peer_sources'];require(type(items) is list and len(items)==2,'CONFLICT_TWO_SOURCE_ORIGINS_REQUIRED')
        qualities=[fixed_assessment(item['source']) for item in items]
        winners=[i for i,item in enumerate(qualities) if item['supported'] is True]
        require(len(winners)==1,'CONFLICT_FIXED_UNIQUE_REPRODUCIBLE_SOURCE_REQUIRED')
        winner=winners[0]
        base.update(result=dict(selected_source_id=items[winner]['source']['source_id'],
            selected_peer_task_id=items[winner]['task_id'],
            selection_basis='AVAILABLE_EXACT_ORIGINAL_UNDERLYING_DATA_AND_REPRODUCIBLE_LIMITED_FINDING',
            failure_basis_points=500,continuous_health='UNKNOWN',production_health='NOT_ESTABLISHED',
            rejected_unsupported_claim='HEALTHY',preserved_recommendations=[dict(task_id=item['task_id'],
                sha256=sha(canonical(item)),original_result=item['result']) for item in peer_results]),
            source_scope='SUPPLIED_PUBLIC_FIXTURE_ONLY')
    require(result==base and result_raw==canonical(base),'CONFLICT_INDEPENDENT_RESULT_REJECTED')
    return base


def steps(which):
    phase(which)
    return ('setup','source','result') if which in PHASES[:2] else (
        'setup','peer0_input','peer0_result','peer1_input','peer1_result','result') if which=='reconciliation' else ('review',)


def action_type(which,step):
    require(step in steps(which)+('full',),'CONFLICT_STEP_REQUIRED')
    return REVIEW_ACTION if which=='review' and step=='review' else 'agent.certification.conflict.'+which+'.'+step


def _registered(registry_sha256):
    _registry(registry_sha256)
    from .agent_registry import agent_record,responsibility_owner
    for which,(actor,capability) in ACTORS.items():
        record=agent_record(actor)
        require(responsibility_owner(capability)==actor and record['immutable_id']==actor
            and record['authority']==('restricted' if actor=='a17' else 'advisory')
            and capability in record['capability_requirements']
            and 'provided_context.read' in record['tool_eligibility']
            and 'action.propose' in record['tool_eligibility']
            and record['tap_relationship']['delegation_transfers_authority'] is False,
            'CONFLICT_REGISTERED_OWNER_DRIFT')


def _preflight(root,task,which,runtime,now,deadline):
    """Four explicitly fixed existing owners; read-only native bounded SQLite."""
    actor,capability=ACTORS[which]
    path=_path(root/'objectives.db')
    require(path.is_file() and 0<path.stat().st_size<=8*1024*1024,'CONFLICT_ORIGINAL_OBJECTIVE_BOUND')
    for suffix in ('-wal','-shm'):
        side=_path(root/('objectives.db'+suffix))
        require(not side.exists() or (side.is_file() and side.stat().st_size<=8*1024*1024),
            'CONFLICT_OBJECTIVE_SIDECAR_BOUND')
    require(time.monotonic()<deadline,'CONFLICT_SHARED_BOUND_EXCEEDED')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,
            timeout=max(0,min(1,deadline-time.monotonic())))) as db:
        db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,65536);db.setlimit(sqlite3.SQLITE_LIMIT_COLUMN,32)
        db.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH,1024)
        db.set_progress_handler(lambda:int(time.monotonic()>=deadline),100)
        rows=db.execute('SELECT objective_hash,state,steps_json FROM objectives WHERE id=? LIMIT 2',(task,)).fetchall()
        turns=db.execute('SELECT revision FROM objective_turns WHERE task=? LIMIT 1',(task,)).fetchone()
        times=db.execute('SELECT revision,created_at,updated_at FROM objective_metadata WHERE task=? LIMIT 2',(task,)).fetchall()
        pins=db.execute('SELECT revision,host_id,source_revision,version,image_digest FROM objective_runtime WHERE task=? LIMIT 2',(task,)).fetchall()
    require(time.monotonic()<deadline and rows==[(sha(OBJECTIVES[which].encode()),'dispatching',json.dumps([capability]))]
        and turns is None and len(times)==1 and type(times[0][0]) is int and times[0][0]==0
        and times[0][1]==times[0][2] and 0<=(now-_utc(times[0][1])).total_seconds()<=300
        and pins==[(0,runtime['host_id'],runtime['source_revision'],runtime['version'],runtime['image_digest'])],
        'CONFLICT_ORIGINAL_OBJECTIVE_DRIFT')


def _metadata(metadata,raw,task,source,actor,*,began,ended):
    from .agent_cert_artifact_events import _metadata as established,PROVENANCE as BASE_PROVENANCE
    require(type(metadata) is dict and metadata.get('creator_agents')==[actor]
        and metadata.get('provenance')==PROVENANCE,'CONFLICT_ARTIFACT_ORIGINAL_OWNER_DRIFT')
    established(dict(metadata,creator_agents=['a19'],provenance=BASE_PROVENANCE),raw,task,source,began=began,ended=ended)


def read_action_span(root,task,which,*,step='full'):
    require(_uuid(task),'CONFLICT_TASK_REQUIRED');action_type(which,step)
    lines=_ledger_lines(_path(root))
    indices=[i for i,line in enumerate(lines) if (row:=parse(line.encode())).get('task_id')==task
        and (step=='full' or row.get('action_type')==action_type(which,step))]
    require(len(indices)==(2*len(steps(which)) if step=='full' else 2)
        and indices[-1]-indices[0]+1==len(indices),'CONFLICT_ORIGINAL_ACTION_COUNT')
    return lines[indices[0]:indices[-1]+1]


def validate_full_action_span(lines,task,which):
    from .agent_cert_event_api import _original_chain
    require(type(lines) is list and len(lines)==2*len(steps(which)),'CONFLICT_ORIGINAL_FULL_COUNT')
    rows=[parse(line.encode()) for line in lines];ids=[];actor,_=ACTORS[which]
    for index,step in enumerate(steps(which)):
        pair=rows[2*index:2*index+2]
        _original_chain(lines[2*index:2*index+2],task,action_type(which,step))
        require(all(row.get('agent_id')==actor for row in pair),'CONFLICT_ACTION_ORIGINAL_OWNER_DRIFT')
        ids.append(pair[0]['action_id'])
    require(len(set(ids))==len(ids) and all(left['sequence']+1==right['sequence']
        and left['sha256']==right['previous_sha256'] and _utc(left['timestamp'])<=_utc(right['timestamp'])
        for left,right in zip(rows,rows[1:])),'CONFLICT_ACTION_ORDER_DRIFT')
    return True


def _input(which,variant,task,arrived,peer_executions):
    base=dict(schema_version=INPUT_SCHEMA,case=CASE,case_version=VERSION,phase=which,
        orientation=variant,task_id=task,arrived_at=arrived,scope='CONTROLLED_PUBLIC_SOURCE_CONFLICT_ONLY')
    if which in PHASES[:2]:base['source']=assigned_source(which,variant)
    else:
        base['peer_sources']=[dict(task_id=item['dispatch']['task_id'],
            input_artifact_id=item['dispatch']['conflict_event']['input_artifact_metadata']['artifact_id'],
            input_sha256=sha(item['input_content_utf8'].encode()),
            result_artifact_id=item['artifact_metadata']['artifact_id'],result_sha256=sha(item['artifact_content_utf8'].encode()),
            source=parse(item['input_content_utf8'].encode())['source']) for item in peer_executions]
    return canonical(base)


def reread_original(root,execution,*,read_objective):
    require(callable(read_objective),'CONFLICT_ORIGINAL_OBJECTIVE_READER_REQUIRED')
    task=execution['dispatch']['task_id'];which=execution['dispatch']['conflict_event']['phase']
    require(canonical(read_objective(task))==canonical(execution['objective_read'][1]),'CONFLICT_ORIGINAL_OBJECTIVE_CHANGED')
    for metadata,raw in ((execution['artifact_metadata'],execution['artifact_content_utf8'].encode()),
            (execution['dispatch']['conflict_event']['input_artifact_metadata'],execution['input_content_utf8'].encode())):
        actual,content=retrieve_original_artifact(root,metadata['artifact_id'])
        require(canonical(actual)==canonical(metadata) and content==raw,'CONFLICT_ORIGINAL_ARTIFACT_CHANGED')
    require(read_action_span(root,task,which)==execution['original_action_records'],'CONFLICT_ORIGINAL_ACTIONS_CHANGED')
    return sha(canonical(execution))


def execute_phase(which,task_id,*,actor,submitted_request,data_root,ledger,runtime,read_runtime,
        source_revision,runtime_image_id,registry_sha256,read_objective):
    """Three fixed owning source tasks; no proposed-code or external execution."""
    phase(which);require(which in PHASES and actor==ACTORS[which][0],'CONFLICT_FIXED_PRODUCER_REQUIRED')
    require(_slot.acquire(blocking=False),'CONFLICT_PRODUCER_BUSY')
    try:
        from .action_records import ActionLedger,ActionRecord,DirectExecutor
        from .artifact_factory import ArtifactFactory
        from .deterministic_ops import DeterministicOps
        root=_path(data_root);_path(root/'artifacts')
        bound=_bindings(task_id,runtime,source_revision,runtime_image_id,registry_sha256)
        began=datetime.now(timezone.utc);deadline=time.monotonic()+5
        def remaining():
            left=min(deadline-time.monotonic(),5-(datetime.now(timezone.utc)-began).total_seconds())
            require(left>0,'CONFLICT_SHARED_BOUND_EXCEEDED');return left
        envelope=parse(submitted_request['context'].encode(),80000)
        variant=orientation(envelope.get('orientation'))
        peers=envelope.get('peer_executions')
        expected=phase_request(which,variant,peer_executions=peers)
        require(canonical(submitted_request)==canonical(expected),'CONFLICT_SUBMITTED_REQUEST_DRIFT')
        require(callable(read_runtime) and canonical(read_runtime())==canonical(bound),'CONFLICT_RUNTIME_UNBOUND')
        require(type(ledger) is ActionLedger and _path(ledger.path)==root/'action-records.jsonl'
            and not ledger.closed and ledger.worker.is_alive() and ledger.status()['healthy'] is True,
            'CONFLICT_ORIGINAL_LEDGER_REQUIRED')
        _registered(registry_sha256);_preflight(root,task_id,which,bound,began,deadline)
        with ledger.pending.all_tasks_done:require(ledger.pending.unfinished_tasks==0,'CONFLICT_PRIOR_ACTION_PENDING')
        require(not any(parse(line.encode()).get('task_id')==task_id for line in _ledger_lines(root)),
            'CONFLICT_TASK_ALREADY_ATTEMPTED')
        pins=dict(source_revision=source_revision,runtime_image_id=runtime_image_id,registry_sha256=registry_sha256)
        if peers is not None:
            require([item.get('dispatch',{}).get('conflict_event',{}).get('phase') for item in peers]==list(PHASES[:2]),
                'CONFLICT_ORIGINAL_PEER_PHASES_REQUIRED')
            require(len({item['dispatch']['task_id'] for item in peers}|{task_id})==3,'CONFLICT_DISTINCT_TASKS_REQUIRED')
            for item in peers:
                remaining();validate_execution(item,**pins,now=began)
                require(item['case_spec']['orientation']==variant,'CONFLICT_PEER_ORIENTATION_DRIFT')
                reread_original(root,item,read_objective=read_objective)
        remaining();executor=DirectExecutor(ledger);factory=ArtifactFactory(root/'artifacts')
        def create(raw):
            require(len(raw)<=65536,'CONFLICT_ARTIFACT_BOUND')
            metadata=factory.create(kind='json',content=raw.decode(),task_id=task_id,creator=actor,
                provenance=PROVENANCE,runtime_revision=source_revision)
            actual,content=retrieve_original_artifact(root,metadata['artifact_id'])
            require(canonical(actual)==canonical(metadata) and content==raw,'CONFLICT_ARTIFACT_READBACK_DRIFT')
            _metadata(metadata,raw,task_id,source_revision,actor,began=began,ended=datetime.now(timezone.utc))
            return metadata
        spec=canonical_phase_spec(which,variant);request_sha=sha(canonical(expected));ids={}
        def factory_record(step,schema):
            action=ActionRecord(task_id,actor,action_type(which,step),'artifact-factory',parameters_summary=dict(
                schema_version=schema,case_spec_sha256=sha(canonical(spec)),submitted_request_sha256=request_sha,
                read_only_observations=True));ids[step]=action.action_id;return action
        raw_input=_input(which,variant,task_id,datetime.now(timezone.utc).isoformat(),peers)
        setup=executor.execute(factory_record('setup',INPUT_SCHEMA),lambda:create(raw_input))
        reads=[];reader=DeterministicOps(source_version=source_revision)
        def consume(step,metadata):
            remaining()
            action=ActionRecord(task_id,actor,action_type(which,step),'provided_context.read',target='artifact.json',
                parameters_summary=dict(schema_version=INPUT_SCHEMA,source_artifact_id=metadata['artifact_id'],
                    relative_path='artifact.json',expected_sha256=metadata['sha256'],read_only_observations=True))
            ids[step]=action.action_id
            def read():
                raw,digest=reader.retrieve_file(_path(root/'artifacts'/metadata['artifact_id']),'artifact.json',
                    expected_sha256=metadata['sha256'])
                reads.append(raw);return dict(source_sha256=digest,result=raw.decode())
            executor.execute(action,read);remaining()
        if peers is None:consume('source',setup)
        else:
            for index,item in enumerate(peers):
                consume('peer'+str(index)+'_input',item['dispatch']['conflict_event']['input_artifact_metadata'])
                consume('peer'+str(index)+'_result',item['artifact_metadata'])
            for index,item in enumerate(peers):
                require(reads[2*index]==item['input_content_utf8'].encode()
                    and reads[2*index+1]==item['artifact_content_utf8'].encode(),'CONFLICT_CONSUMED_ORIGINAL_DRIFT')
                reread_original(root,item,read_objective=read_objective);remaining()
        peer_results=None if peers is None else [parse(reads[1]),parse(reads[3])]
        result=executor.execute(factory_record('result',RESULT_SCHEMA),lambda:create(producer_result(which,
            task_id=task_id,input_raw=reads[0] if peers is None else raw_input,peer_results=peer_results)))
        require(ledger.flush(timeout=remaining()) is True,'CONFLICT_DURABLE_ACTION_REQUIRED')
        require(canonical(read_runtime())==canonical(bound),'CONFLICT_RUNTIME_CHANGED')
        _registered(registry_sha256);remaining()
        event=dict(schema_version=EVENT_SCHEMA,case=CASE,phase=which,orientation=variant,case_version=VERSION,
            task_id=task_id,source_revision=source_revision,registry_sha256=registry_sha256,
            runtime_identity_sha256=sha(canonical(bound)),case_spec_sha256=sha(canonical(spec)),
            submitted_request_sha256=request_sha,input_artifact_metadata=setup,action_ids=ids,
            started_at=began.isoformat(),completed_at=datetime.now(timezone.utc).isoformat(),
            durable_action_delivery=True,certification='UNVERIFIED')
        return dict(task_id=task_id,state='COMPLETED',artifact=result,model_calls=0,execution_model='DETERMINISTIC',
            agent_id=actor,capability=ACTORS[which][1],runtime_source_revision=source_revision,conflict_event=event)
    except ConflictEventError:raise
    except Exception:raise ConflictEventError('CONFLICT_EXECUTION_FAILED') from None
    finally:_slot.release()


def validate_execution(execution,*,source_revision,runtime_image_id,registry_sha256,now):
    """Original ownership, source quality, native time and complete action joins."""
    try:
        from .agent_cert_event_api import _original_chain
        from .objective_api import inference_attempt_projection
        require(type(now) is datetime and now.tzinfo is not None,'CONFLICT_CURRENT_TIME_REQUIRED')
        value=parse(canonical(execution),262144)
        require(set(value)=={'case_spec','submitted_request_sha256','runtime','runtime_after','runtime_current',
            'submission','dispatch','artifact_metadata','artifact_content_utf8','input_content_utf8',
            'objective_read','original_action_records','observation','peer_executions'},'CONFLICT_EXECUTION_FIELDS')
        dispatch=value['dispatch'];event=dispatch['conflict_event'];which=phase(event['phase'])
        require(which in PHASES,'CONFLICT_PRODUCER_ORIGINAL_REQUIRED');variant=orientation(event['orientation'])
        actor,capability=ACTORS[which];task=dispatch['task_id'];spec=canonical_phase_spec(which,variant)
        require(canonical(value['case_spec'])==canonical(spec),'CONFLICT_CASE_SPEC_DRIFT')
        runtime=_bindings(task,value['runtime'],source_revision,runtime_image_id,registry_sha256)
        require(canonical(value['runtime_after'])==canonical(runtime) and canonical(value['runtime_current'])==canonical(runtime),
            'CONFLICT_RUNTIME_DRIFT')
        require(set(dispatch)=={'task_id','state','artifact','model_calls','execution_model','agent_id',
            'capability','runtime_source_revision','conflict_event'} and dispatch['state']=='COMPLETED'
            and dispatch['agent_id']==actor and dispatch['capability']==capability
            and dispatch['runtime_source_revision']==source_revision and dispatch['execution_model']=='DETERMINISTIC'
            and type(dispatch['model_calls']) is int and dispatch['model_calls']==0,'CONFLICT_DISPATCH_DRIFT')
        began,ended=_utc(event['started_at']),_utc(event['completed_at'])
        require(0<=(ended-began).total_seconds()<=5 and 0<=(now-ended).total_seconds()<=300,'CONFLICT_STALE_OR_UNBOUNDED')
        observation=value['observation'];obegan,oended=_utc(observation['started_at']),_utc(observation['completed_at'])
        require(set(observation)=={'started_at','completed_at'} and obegan<=began<=ended<=oended<=now
            and 0<=(oended-obegan).total_seconds()<=5,'CONFLICT_OBSERVATION_BOUND')
        peers=value['peer_executions'];joins=[];peer_results=None
        if which=='reconciliation':
            require(type(peers) is list and len(peers)==2
                and [item.get('dispatch',{}).get('conflict_event',{}).get('phase') for item in peers]==list(PHASES[:2]),
                'CONFLICT_EXACT_ORIGINAL_PEERS_REQUIRED')
            for item in peers:
                joined=validate_execution(item,source_revision=source_revision,runtime_image_id=runtime_image_id,
                    registry_sha256=registry_sha256,now=now)
                require(item['case_spec']['orientation']==variant,'CONFLICT_PEER_ORIENTATION_DRIFT');joins.append(joined)
            require(len({item['task_id'] for item in joins}|{task})==3,'CONFLICT_DISTINCT_PEER_TASKS_REQUIRED')
            peer_results=[parse(item['artifact_content_utf8'].encode()) for item in peers]
        else:require(peers is None,'CONFLICT_PEER_CANNOT_NEST_ORIGINALS')
        request=phase_request(which,variant,peer_executions=peers);request_sha=sha(canonical(request))
        require(value['submitted_request_sha256']==request_sha,'CONFLICT_REQUEST_ORIGINAL_HASH_DRIFT')
        raw=value['artifact_content_utf8'].encode();input_raw=value['input_content_utf8'].encode();source=parse(input_raw)
        require(began<=_utc(source['arrived_at'])<=ended
            and datetime.fromisoformat(source['arrived_at'].replace('Z','+00:00')).utcoffset().total_seconds()==0,
            'CONFLICT_SOURCE_ARRIVAL_REQUIRED')
        require(input_raw==_input(which,variant,task,source['arrived_at'],peers),'CONFLICT_ORIGINAL_SOURCE_ORIGIN_DRIFT')
        independent_result_check(which,task_id=task,input_raw=input_raw,result_raw=raw,peer_results=peer_results)
        metadata=value['artifact_metadata'];setup=event['input_artifact_metadata'];ids=event['action_ids']
        expected_event=dict(schema_version=EVENT_SCHEMA,case=CASE,phase=which,orientation=variant,case_version=VERSION,
            task_id=task,source_revision=source_revision,registry_sha256=registry_sha256,
            runtime_identity_sha256=sha(canonical(runtime)),case_spec_sha256=sha(canonical(spec)),
            submitted_request_sha256=request_sha,input_artifact_metadata=setup,action_ids=ids,
            started_at=event['started_at'],completed_at=event['completed_at'],durable_action_delivery=True,certification='UNVERIFIED')
        require(canonical(event)==canonical(expected_event) and set(ids)==set(steps(which))
            and all(_uuid(identifier) for identifier in ids.values()) and len(set(ids.values()))==len(ids),
            'CONFLICT_EVENT_ORIGINAL_ACTIONS_DRIFT')
        require(canonical(dispatch['artifact'])==canonical(metadata) and setup['artifact_id']!=metadata['artifact_id'],
            'CONFLICT_DISTINCT_ORIGINAL_ARTIFACTS')
        for meta,content in ((setup,input_raw),(metadata,raw)):
            _metadata(meta,content,task,source_revision,actor,began=began,ended=ended)
        lines=value['original_action_records'];validate_full_action_span(lines,task,which)
        rows=[parse(line.encode()) for line in lines]
        def check_pair(index,step,meta,content,*,factory):
            first,last=rows[index*2:index*2+2]
            params=dict(schema_version=INPUT_SCHEMA if step=='setup' or not factory else RESULT_SCHEMA,
                case_spec_sha256=sha(canonical(spec)),submitted_request_sha256=request_sha,read_only_observations=True) if factory else dict(
                schema_version=INPUT_SCHEMA,source_artifact_id=meta['artifact_id'],relative_path='artifact.json',
                expected_sha256=meta['sha256'],read_only_observations=True)
            base=dict(task_id=task,agent_id=actor,action_type=action_type(which,step),
                tool='artifact-factory' if factory else 'provided_context.read',target='' if factory else 'artifact.json',
                classification='R0',parameters_summary=params,model_backend='deterministic',execution_location='local',
                parent_agent=None,workflow_id=None,action_id=ids[step])
            common=set(base)|{'phase','timestamp','sequence','previous_sha256','sha256'}
            summary=dict(type='dict',artifact_id=meta['artifact_id'],sha256=meta['sha256'],location='artifact.json') if factory else dict(
                type='dict',source_sha256=sha(content),output_sha256=sha(content),output_length=len(content.decode()))
            require(set(first)==common and set(last)==common|{'success','duration_ms','result_summary'}
                and all(row.get(key)==expected for row in (first,last) for key,expected in base.items())
                and first['phase']=='started' and last['phase']=='completed' and last.get('success') is True
                and type(last['duration_ms']) in (int,float) and math.isfinite(last['duration_ms']) and 0<=last['duration_ms']<=5000
                and last['result_summary']==summary and began<=_utc(first['timestamp'])<=_utc(last['timestamp'])<=ended,
                'CONFLICT_ORIGINAL_ACTION_CUSTODY_DRIFT')
            if factory:require(_utc(first['timestamp'])<=_utc(meta['timestamp'])<=_utc(last['timestamp']),
                'CONFLICT_ORIGINAL_FACTORY_TIME_DRIFT')
            else:require(_utc(meta['timestamp'])<=_utc(first['timestamp']),'CONFLICT_READ_BEFORE_SOURCE')
        check_pair(0,'setup',setup,input_raw,factory=True)
        if peers is None:check_pair(1,'source',setup,input_raw,factory=False)
        else:
            for index,item in enumerate(peers):
                for offset,kind in enumerate(('input','result')):
                    meta=item['dispatch']['conflict_event']['input_artifact_metadata'] if kind=='input' else item['artifact_metadata']
                    content=item['input_content_utf8'].encode() if kind=='input' else item['artifact_content_utf8'].encode()
                    check_pair(1+index*2+offset,'peer'+str(index)+'_'+kind,meta,content,factory=False)
        check_pair(len(steps(which))-1,'result',metadata,raw,factory=True)
        require(_utc(source['arrived_at'])<=_utc(setup['timestamp']),'CONFLICT_SOURCE_ARRIVAL_ORDER')
        submission,read=value['submission'],value['objective_read']
        require(type(submission) is list and len(submission)==2 and type(submission[0]) is int and submission[0]==202
            and submission[1].get('id')==task and submission[1].get('steps')==[dict(capability=capability,dispatch=dispatch)],
            'CONFLICT_ORIGINAL_SUBMISSION_DRIFT')
        require(type(read) is list and len(read)==2 and type(read[0]) is int and read[0]==200,'CONFLICT_ORIGINAL_OBJECTIVE_REQUIRED')
        objective=read[1];immutable=objective.get('execution_metadata')
        require(objective.get('id')==task and type(objective.get('revision')) is int and objective['revision']==0
            and objective.get('state')=='COMPLETED'
            and objective.get('steps')==[dict(capability=capability,dispatch=dispatch,revision=0,state='completed')],
            'CONFLICT_ORIGINAL_OBJECTIVE_DRIFT')
        require(type(immutable) is dict and immutable.get('schema_version')=='jarvis.authoritative-execution.v1'
            and immutable.get('authoritative') is True and immutable.get('task_id')==task
            and type(immutable.get('revision')) is int and immutable['revision']==0 and immutable.get('state')=='COMPLETED'
            and immutable.get('runtime')==runtime and immutable.get('jobs')==[] and immutable.get('agent_execution')==[]
            and immutable.get('inference_attempts')==inference_attempt_projection([])
            and immutable.get('model_content_is_authoritative_metadata') is False
            and immutable.get('provenance',{}).get('runtime')=='IMMUTABLE_OBJECTIVE_RUNTIME'
            and obegan<=_utc(immutable['created_at'])<=began and _utc(rows[-1]['timestamp'])<=_utc(immutable['completed_at'])
            <=_utc(immutable['updated_at'])<=oended,'CONFLICT_IMMUTABLE_OBJECTIVE_DRIFT')
        if joins:require(all(_utc(item['completed_at'])<_utc(immutable['created_at'])
            and item['last_sequence']<rows[0]['sequence'] for item in joins),'CONFLICT_RESOLUTION_BEFORE_ORIGINAL_PEERS')
        return dict(task_id=task,case=CASE,phase=which,orientation=variant,agent_id=actor,capability_id=capability,
            case_spec_sha256=sha(canonical(spec)),runtime=runtime,registry_sha256=registry_sha256,
            input_artifact_id=setup['artifact_id'],input_sha256=sha(input_raw),artifact_id=metadata['artifact_id'],result_sha256=sha(raw),
            original_action_span_sha256=sha(''.join(lines).encode()),execution_metadata_sha256=sha(canonical(immutable)),
            first_sequence=rows[0]['sequence'],last_sequence=rows[-1]['sequence'],completed_at=immutable['completed_at'],
            peer_originals=joins,certification='UNVERIFIED')
    except ConflictEventError:raise
    except Exception:raise ConflictEventError('CONFLICT_EXECUTION_ORIGINAL_JOIN_REJECTED') from None


def _review_report(execution,joined,task,nonce,reviewed_at,source_revision,runtime_image_id):
    return dict(schema_version=REVIEW_SCHEMA,case=CASE,case_version=VERSION,subject_agent_id='a19',
        subject_capability_id='responsibility.a19',dimension='conflict_resolution',test_case='complete',
        reviewer_id='a26',reviewer_capability_id='responsibility.a26',task_id=task,source_revision=source_revision,
        runtime_image_id=runtime_image_id,execution_evidence_sha256=sha(canonical(execution)),
        case_spec_sha256=joined['case_spec_sha256'],result_sha256=joined['result_sha256'],review_nonce=nonce,
        reviewed_at=reviewed_at,oracle_id=ORACLE,test_result='PASS',review_errors=[],model_calls=0,
        execution_model='DETERMINISTIC',subject_execution_verification='THREE_DISTINCT_ORIGINAL_SOURCE_TASKS_JOINED',
        subject_domain_join=joined,certification='UNVERIFIED')


def execute_review(task_id,*,actor,submitted_request,data_root,ledger,runtime,read_runtime,
        source_revision,runtime_image_id,registry_sha256,read_objective):
    require(actor=='a26' and submitted_request.get('capability')=='responsibility.a26',
        'CONFLICT_FIXED_DISTINCT_REVIEWER_REQUIRED')
    require(_slot.acquire(blocking=False),'CONFLICT_REVIEW_BUSY')
    try:
        from .action_records import ActionLedger,ActionRecord,DirectExecutor
        from .artifact_factory import ArtifactFactory
        root=_path(data_root);bound=_bindings(task_id,runtime,source_revision,runtime_image_id,registry_sha256)
        began=datetime.now(timezone.utc);deadline=time.monotonic()+5
        def remaining():
            left=min(deadline-time.monotonic(),5-(datetime.now(timezone.utc)-began).total_seconds())
            require(left>0,'CONFLICT_REVIEW_SHARED_BOUND_EXCEEDED');return left
        envelope=parse(submitted_request['context'].encode(),80000)
        require(set(envelope)=={'fixed_challenge','orientation','execution','expected_execution_sha256','review_nonce'},
            'CONFLICT_REVIEW_FIELDS')
        execution=envelope['execution'];variant=orientation(envelope['orientation'])
        require(canonical(submitted_request)==canonical(phase_request('review',variant,
            execution=execution,nonce=envelope['review_nonce']))
            and envelope['expected_execution_sha256']==sha(canonical(execution)), 'CONFLICT_REVIEW_SUBMISSION_DRIFT')
        require(callable(read_runtime) and canonical(read_runtime())==canonical(bound),'CONFLICT_REVIEW_RUNTIME_DRIFT')
        require(type(ledger) is ActionLedger and _path(ledger.path)==root/'action-records.jsonl'
            and not ledger.closed and ledger.worker.is_alive() and ledger.status()['healthy'] is True,
            'CONFLICT_REVIEW_ORIGINAL_LEDGER_REQUIRED')
        _registered(registry_sha256);_preflight(root,task_id,'review',bound,began,deadline)
        with ledger.pending.all_tasks_done:require(ledger.pending.unfinished_tasks==0,'CONFLICT_REVIEW_PENDING_ACTION')
        require(not any(parse(line.encode()).get('task_id')==task_id for line in _ledger_lines(root)),
            'CONFLICT_REVIEW_TASK_ALREADY_ATTEMPTED')
        pins=dict(source_revision=source_revision,runtime_image_id=runtime_image_id,registry_sha256=registry_sha256)
        require(execution.get('dispatch',{}).get('conflict_event',{}).get('phase')=='reconciliation',
            'CONFLICT_ORIGINAL_RECONCILIATION_REQUIRED')
        joined=validate_execution(execution,**pins,now=began)
        originals=[*execution['peer_executions'],execution]
        require(execution['case_spec']['orientation']==variant
            and task_id not in [item['dispatch']['task_id'] for item in originals], 'CONFLICT_DISTINCT_REVIEW_TASK_REQUIRED')
        frozen=canonical(execution)
        for item in originals:remaining();reread_original(root,item,read_objective=read_objective)
        # The peer reaches a separate fixed oracle using original facts. It
        # never calls producer_result or the producer's source calculator.
        require(canonical(execution)==frozen and validate_execution(execution,**pins,
            now=datetime.now(timezone.utc))==joined,'CONFLICT_REVIEW_ORIGINAL_INPUT_CHANGED')
        for item in originals:remaining();reread_original(root,item,read_objective=read_objective)
        require(canonical(execution)==frozen and canonical(read_runtime())==canonical(bound),
            'CONFLICT_REVIEW_ORIGINAL_DOMAINS_CHANGED')
        _registered(registry_sha256);remaining()
        report=_review_report(execution,joined,task_id,envelope['review_nonce'],datetime.now(timezone.utc).isoformat(),
            source_revision,runtime_image_id)
        factory=ArtifactFactory(root/'artifacts')
        action=ActionRecord(task_id,'a26',REVIEW_ACTION,'artifact-factory',parameters_summary=dict(
            schema_version=REVIEW_SCHEMA,read_only_observations=True))
        artifact=DirectExecutor(ledger).execute(action,lambda:factory.create(kind='json',content=canonical(report).decode(),
            task_id=task_id,creator='a26',provenance=PROVENANCE,runtime_revision=source_revision))
        actual,raw=retrieve_original_artifact(root,artifact['artifact_id'])
        require(canonical(actual)==canonical(artifact) and raw==canonical(report),'CONFLICT_REVIEW_ARTIFACT_READBACK_DRIFT')
        require(ledger.flush(timeout=remaining()) is True,'CONFLICT_REVIEW_DURABLE_ACTION_REQUIRED')
        require(canonical(read_runtime())==canonical(bound),'CONFLICT_REVIEW_RUNTIME_CHANGED')
        _registered(registry_sha256);remaining()
        return dict(task_id=task_id,state='COMPLETED',artifact=artifact,model_calls=0,execution_model='DETERMINISTIC',
            agent_id='a26',capability='responsibility.a26',runtime_source_revision=source_revision,review_action_id=action.action_id)
    except ConflictEventError:raise
    except Exception:raise ConflictEventError('CONFLICT_ORIGINAL_REVIEW_REJECTED') from None
    finally:_slot.release()


def validate_reviewed_conflict(execution,peer,*,source_revision,runtime_image_id,registry_sha256,now):
    from .agent_cert_identity_review import action_span
    from .objective_api import inference_attempt_projection
    require(execution.get('dispatch',{}).get('conflict_event',{}).get('phase')=='reconciliation',
        'CONFLICT_PEER_CONTRIBUTION_IS_NOT_COMPLETED_CASE')
    joined=validate_execution(execution,source_revision=source_revision,runtime_image_id=runtime_image_id,
        registry_sha256=registry_sha256,now=now)
    require(type(peer) is dict and set(peer)=={'submitted_request_sha256','runtime','runtime_after','submission','dispatch',
        'artifact_metadata','artifact_content_utf8','objective_read','action_records','observation'},'CONFLICT_REVIEW_EVIDENCE_FIELDS')
    raw=peer['artifact_content_utf8'].encode();report=parse(raw)
    require(peer['submitted_request_sha256']==sha(canonical(phase_request('review',joined['orientation'],
        execution=execution,nonce=report['review_nonce']))),'CONFLICT_PEER_REQUEST_ORIGINAL_HASH_DRIFT')
    dispatch=peer['dispatch'];task=dispatch['task_id'];runtime=joined['runtime']
    require(_uuid(task) and task not in [joined['task_id'],*[item['task_id'] for item in joined['peer_originals']]]
        and canonical(peer['runtime'])==canonical(runtime) and canonical(peer['runtime_after'])==canonical(runtime),
        'CONFLICT_DISTINCT_REVIEWER_RUNTIME_REQUIRED')
    require(set(dispatch)=={'task_id','state','artifact','model_calls','execution_model','agent_id','capability',
        'runtime_source_revision','review_action_id'} and dispatch['state']=='COMPLETED' and dispatch['agent_id']=='a26'
        and dispatch['capability']=='responsibility.a26' and dispatch['runtime_source_revision']==source_revision
        and dispatch['execution_model']=='DETERMINISTIC' and type(dispatch['model_calls']) is int and dispatch['model_calls']==0,
        'CONFLICT_ORIGINAL_REVIEW_DISPATCH_DRIFT')
    # Fixed consumer envelope is independent of the producer report builder.
    expected_report=dict(schema_version=REVIEW_SCHEMA,case=CASE,case_version=VERSION,subject_agent_id='a19',
        subject_capability_id='responsibility.a19',dimension='conflict_resolution',test_case='complete',
        reviewer_id='a26',reviewer_capability_id='responsibility.a26',task_id=task,source_revision=source_revision,
        runtime_image_id=runtime_image_id,execution_evidence_sha256=sha(canonical(execution)),
        case_spec_sha256=joined['case_spec_sha256'],result_sha256=joined['result_sha256'],review_nonce=report['review_nonce'],
        reviewed_at=report['reviewed_at'],oracle_id=ORACLE,test_result='PASS',review_errors=[],model_calls=0,
        execution_model='DETERMINISTIC',subject_execution_verification='THREE_DISTINCT_ORIGINAL_SOURCE_TASKS_JOINED',
        subject_domain_join=joined,certification='UNVERIFIED')
    require(raw==canonical(expected_report),'CONFLICT_ORIGINAL_REVIEW_FIXED_ORACLE_DRIFT')
    observation=peer['observation'];began,ended=_utc(observation['started_at']),_utc(observation['completed_at'])
    require(set(observation)=={'started_at','completed_at'} and 0<=(ended-began).total_seconds()<=5
        and began<=_utc(report['reviewed_at'])<=ended<=now,'CONFLICT_REVIEW_OBSERVATION_BOUND')
    metadata=peer['artifact_metadata']
    require(canonical(metadata)==canonical(dispatch['artifact']),'CONFLICT_REVIEW_ARTIFACT_METADATA_DRIFT')
    _metadata(metadata,raw,task,source_revision,'a26',began=began,ended=ended)
    lines=peer['action_records'];require(type(lines) is list and len(lines)==2,'CONFLICT_EXACT_REVIEW_ACTIONS_REQUIRED')
    action_span(lines,task_id=task,agent_id='a26',action_type=REVIEW_ACTION,schema=REVIEW_SCHEMA,metadata=metadata,
        began=began,ended=ended,action_id=dispatch['review_action_id'])
    submission,read=peer['submission'],peer['objective_read']
    require(type(submission) is list and len(submission)==2 and type(submission[0]) is int and submission[0]==202
        and submission[1].get('id')==task and submission[1].get('steps')==[dict(capability='responsibility.a26',dispatch=dispatch)],
        'CONFLICT_ORIGINAL_REVIEW_SUBMISSION_DRIFT')
    require(type(read) is list and len(read)==2 and type(read[0]) is int and read[0]==200,'CONFLICT_ORIGINAL_REVIEW_OBJECTIVE_REQUIRED')
    objective=read[1];immutable=objective.get('execution_metadata')
    require(objective.get('id')==task and type(objective.get('revision')) is int and objective['revision']==0
        and objective.get('state')=='COMPLETED'
        and objective.get('steps')==[dict(capability='responsibility.a26',dispatch=dispatch,revision=0,state='completed')],
        'CONFLICT_ORIGINAL_REVIEW_OBJECTIVE_DRIFT')
    first,last=[parse(line.encode()) for line in lines]
    require(type(immutable) is dict and immutable.get('schema_version')=='jarvis.authoritative-execution.v1'
        and immutable.get('authoritative') is True and immutable.get('task_id')==task
        and type(immutable.get('revision')) is int and immutable['revision']==0 and immutable.get('state')=='COMPLETED'
        and immutable.get('runtime')==runtime and immutable.get('jobs')==[] and immutable.get('agent_execution')==[]
        and immutable.get('inference_attempts')==inference_attempt_projection([])
        and immutable.get('model_content_is_authoritative_metadata') is False
        and immutable.get('provenance',{}).get('runtime')=='IMMUTABLE_OBJECTIVE_RUNTIME'
        and began<=_utc(immutable['created_at'])<=_utc(report['reviewed_at'])<=_utc(first['timestamp'])
        <=_utc(last['timestamp'])<=_utc(immutable['completed_at'])<=_utc(immutable['updated_at'])<=ended
        and _utc(joined['completed_at'])<_utc(immutable['created_at']) and joined['last_sequence']<first['sequence'],
        'CONFLICT_ORIGINAL_REVIEW_IMMUTABLE_OBJECTIVE_DRIFT')
    return dict(subject_domain_join=joined,review_task_id=task,review_result_sha256=sha(raw),
        review_action_sha256=last['sha256'],review_objective_sha256=sha(canonical(immutable)),certification='UNVERIFIED')
