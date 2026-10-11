from contextlib import closing
"""SOURCE temporary-domain model assessment; no production or L7 admission."""
import os,uuid,json,time,sqlite3
from pathlib import Path
from datetime import datetime,timezone
from .agent_cert_resident_model import (ResidentAdmissionContract,ResidentCaseWindow,
    require,canonical,sha,run_source_assessment)
from .agent_cert_artifact_events import _path,_registry,_ledger_lines

CASE='model_substitution:complete'
INPUT_SCHEMA='prime.public-model-substitution-input.v1'
RESULT_SCHEMA='prime.public-model-substitution-result.v1'
EXECUTION_SCHEMA='prime.source-model-substitution-execution.v1'
PROVENANCE='SOURCE public synthetic model-substitution assessment; UNVERIFIED; no service execution'
PROMPT='Classify these public synthetic checks: true,false,true. Reply only DEGRADED if any is false, otherwise PASS.'
FAST_DIGEST='8648f39daa8fbf5b18c7b4e6a8fb4990c692751d49917417b8842ca5758e7ffc'
DEEP_DIGEST='a2af6cc3eb7fa8be8504abaf9b04e88f17a119ec3f04a3addf55f92841195f5a'
SUBJECT_OBJECTIVE='Preserve one public synthetic bounded assessment after an explicitly permitted pre-dispatch local residency refusal; do not claim service health or certification.'
REVIEW_OBJECTIVE='Independently grade original source model-substitution assessment custody twice; do not confirm service health or certify.'

def input_value():return dict(schema_version=INPUT_SCHEMA,case=CASE,service_id='PUBLIC_SYNTHETIC_ASSESSMENT',checks=[True,False,True])
def action_type(stage):
    require(stage in ('setup','input_read','result','review'),'MODEL_SUBSTITUTION_ACTION_STAGE_REQUIRED')
    return 'agent.certification.model_substitution.'+stage
def marker(root):
    path=_path(root/'source-qualification-domain.json')
    raw=bounded_file(path,4096)
    value=json.loads(raw)
    require(set(value)=={'schema','domain_id','source_revision','scope'} and value['schema']=='prime.source-qualification-domain.v1'
        and value['scope']=='SOURCE_TEMPORARY_DOMAIN_NOT_ACCEPTED_RUNTIME','MODEL_SOURCE_DOMAIN_REQUIRED')
    require(type(value['domain_id']) is str and str(uuid.UUID(value['domain_id']))==value['domain_id'],
        'MODEL_SOURCE_DOMAIN_UUID_REQUIRED')
    return value
def bounded_file(path,cap):
    path=_path(path);before=path.stat()
    def identity(info):return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)
    require(before.st_size<=cap,'MODEL_SOURCE_FILE_BOUND')
    with path.open('rb') as stream:
        require(identity(os.fstat(stream.fileno()))==identity(before),'MODEL_SOURCE_FILE_IDENTITY_DRIFT')
        raw=stream.read(cap+1)
        require(len(raw)<=cap and identity(os.fstat(stream.fileno()))==identity(before),'MODEL_SOURCE_FILE_BOUND_OR_DRIFT')
    require(identity(_path(path).stat())==identity(before),'MODEL_SOURCE_FILE_PATH_DRIFT');return raw
def original_artifact(root,metadata):
    folder=_path(root/'artifacts'/metadata['artifact_id'])
    native=json.loads(bounded_file(folder/'metadata.json',8192));raw=bounded_file(folder/'artifact.json',49152)
    require(canonical(native)==canonical(metadata) and sha(raw)==metadata['sha256'] and len(raw)==metadata['bytes'],
        'MODEL_SOURCE_ORIGINAL_ARTIFACT_DRIFT');return raw
def registry_pin():
    from .agent_registry import REGISTRY_PATH
    return sha(bounded_file(REGISTRY_PATH,1024*1024))
def qualification_settings(original_settings):
    from dataclasses import replace
    from .settings import PrimeSettings
    from .objective_api import runtime_snapshot
    from .compute_profile import generation_options
    require(type(original_settings) is PrimeSettings,'MODEL_SOURCE_ACTUAL_SETTINGS_REQUIRED')
    root=_path(Path(os.getenv('PRIME_DATA_DIR','/data')));domain=marker(root);runtime=runtime_snapshot()
    require(runtime['source_revision']==domain['source_revision']
        and runtime['host_id']=='SOURCE_DOMAIN_'+domain['domain_id'],'MODEL_SOURCE_PRIVATE_RUNTIME_REQUIRED')
    _registry(registry_pin())
    require(generation_options()=={},'MODEL_SOURCE_ORIGINAL_GENERATION_OPTIONS_REQUIRED')
    return replace(original_settings,context_tokens=512,max_output_tokens=16)
def canonical_request(stage,execution=None):
    require(stage in ('subject','review'),'MODEL_SOURCE_STAGE_REQUIRED')
    root=_path(Path(os.getenv('PRIME_DATA_DIR','/data')));domain=marker(root)
    context=dict(case=CASE,stage=stage,domain_id=domain['domain_id'],source_revision=domain['source_revision'],
        registry_sha256=registry_pin(),fast_digest=FAST_DIGEST,deep_digest=DEEP_DIGEST,input=input_value())
    if stage=='review':
        require(type(execution) is dict and len(canonical(execution))<=65536,'MODEL_SOURCE_EXECUTION_BOUND')
        context['execution']=execution
    return dict(classification='R0',capability='responsibility.a19' if stage=='subject' else 'responsibility.a26',
        objective=SUBJECT_OBJECTIVE if stage=='subject' else REVIEW_OBJECTIVE,context=canonical(context).decode(),
        data_classification='LOCAL_ONLY',minimum_tier='NANO',priority='low',task_class='classification',
        max_cost_usd=0.0,preferred_provider=None,response_format='strict_json',
        deterministic_operation='certification_model_substitution' if stage=='subject' else 'certification_model_substitution_review')

def execute_producer(body,*,actor,task_id,runtime,dispatch_window,ledger,settings,queue):
    from .artifact_factory import ArtifactFactory
    from .action_records import ActionRecord,DirectExecutor
    from .deterministic_ops import DeterministicOps
    request=body.model_dump();root=_path(Path(os.getenv('PRIME_DATA_DIR','/data')))
    require(actor=='a19' and canonical(request)==canonical(canonical_request('subject')),'MODEL_SOURCE_EXACT_REQUEST_REQUIRED')
    context=json.loads(request['context']);domain=marker(root)
    require(domain['source_revision']==runtime['source_revision'],'MODEL_SOURCE_RUNTIME_REQUIRED')
    _registry(context['registry_sha256'])
    from .agent_registry import agent_record
    require({'action.propose','provided_context.read'}<=set(agent_record(actor)['tool_eligibility']),
        'MODEL_SOURCE_EXISTING_TOOL_ELIGIBILITY_REQUIRED')
    window=ResidentCaseWindow.from_original_task(root=root,task_id=task_id,submitted_request=request,
        runtime=runtime,dispatch_window=dispatch_window)
    from dataclasses import asdict
    original_settings=settings;settings=qualification_settings(original_settings)
    generation=dict(original_public_settings=asdict(original_settings),effective_public_settings=asdict(settings),options={})
    contract=ResidentAdmissionContract(runtime['source_revision'],domain['domain_id'],root,sha(PROMPT.encode()),
        settings.fast_model,settings.deep_model,FAST_DIGEST,DEEP_DIGEST,context['registry_sha256'],window,canonical(generation).decode())
    contract.source_domain()
    require(not _path(root/'source-residency-assessment.claim').exists(),'MODEL_SOURCE_NATIVE_ASSESSMENT_ALREADY_CLAIMED')
    require(ledger.path.resolve()==root/'action-records.jsonl'
        and not any(json.loads(line).get('task_id')==task_id for line in _ledger_lines(root)),
        'MODEL_SOURCE_OWNING_LEDGER_OR_REPLAY')
    claim=_path(root/'source-model-substitution-producer.claim')
    try:
        with claim.open('xb') as stream:
            stream.write(canonical(dict(task_id=task_id,request_sha256=sha(canonical(request)),runtime=runtime,
                domain_id=domain['domain_id'])));stream.flush();os.fsync(stream.fileno())
    except FileExistsError:raise PermissionError('MODEL_SOURCE_PRODUCER_ALREADY_CLAIMED') from None
    window.remaining()
    executor=DirectExecutor(ledger);factory=ArtifactFactory(_path(root/'artifacts'))
    def record(stage,tool):return ActionRecord(task_id,actor,action_type(stage),tool,
        parameters_summary=dict(case=CASE,source_revision=runtime['source_revision'],registry_sha256=context['registry_sha256']))
    def create(raw):
        window.remaining()
        metadata=factory.create(kind='json',content=raw.decode(),task_id=task_id,creator=actor,
            provenance=PROVENANCE,runtime_revision=runtime['source_revision'])
        require(original_artifact(root,metadata)==raw,'MODEL_SOURCE_ARTIFACT_READBACK_DRIFT')
        window.remaining();return metadata
    setup_action=record('setup','artifact-factory');input_raw=canonical(input_value())
    setup=executor.execute(setup_action,lambda:create(input_raw))
    read_action=record('input_read','provided_context.read');read_action.target='artifact.json'
    read_action.parameters_summary.update(input_artifact_id=setup['artifact_id'],expected_sha256=setup['sha256'])
    reader=DeterministicOps(source_version=runtime['source_revision'])
    def read():
        raw,digest=reader.retrieve_file(_path(root/'artifacts'/setup['artifact_id']),'artifact.json',expected_sha256=setup['sha256'])
        require(raw==input_raw and digest==sha(raw),'MODEL_SOURCE_ACTUAL_INPUT_DRIFT')
        return dict(result=raw.decode(),source_sha256=digest)
    actual=executor.execute(read_action,read)
    require(actual['result'].encode()==input_raw and ledger.flush(timeout=window.remaining()) is True,
        'MODEL_SOURCE_INPUT_NOT_DURABLE')
    native=run_source_assessment(queue,settings=settings,contract=contract,prompt=PROMPT,ledger=ledger)
    require(native['fallback_exercised'] is True and native['assessment_result'].strip()=='DEGRADED',
        'MODEL_SOURCE_NATIVE_ASSESSMENT_NOT_PRESERVED')
    output=canonical(dict(schema_version=RESULT_SCHEMA,case=CASE,task_id=task_id,input_sha256=sha(input_raw),
        assessment='DEGRADED',actual_service_health='UNKNOWN',execution='NOT_PERFORMED',native_result=native,certification='UNVERIFIED'))
    require(len(output)<=49152,'MODEL_SOURCE_OUTPUT_BOUND')
    result_action=record('result','artifact-factory');result=executor.execute(result_action,lambda:create(output))
    require(ledger.flush(timeout=window.remaining()) is True and ledger.dropped==0,'MODEL_SOURCE_RESULT_NOT_DURABLE')
    window.remaining()
    return dict(task_id=task_id,state='COMPLETED',artifact=result,model_calls=1,execution_model='NATIVE_SOURCE_ASSESSMENT',
        agent_id=actor,capability='responsibility.a19',runtime_source_revision=runtime['source_revision'],certification='UNVERIFIED',
        model_substitution_event=dict(input_artifact_metadata=setup,case_action_ids=dict(setup=setup_action.action_id,
            input_read=read_action.action_id,result=result_action.action_id),native_job_ids=[item['job']['id'] for item in native['attempts']]))

def capture_original_execution(subject_id,submitted_request):
    """Read originals only; never create a task, artifact, queue or schema."""
    from .objective_api import runtime_snapshot
    root=_path(Path(os.getenv('PRIME_DATA_DIR','/data')));runtime=runtime_snapshot();deadline=time.monotonic()+1
    require(str(uuid.UUID(subject_id))==subject_id and canonical(submitted_request)==canonical(canonical_request('subject')),
        'MODEL_SOURCE_CAPTURE_REQUEST_REQUIRED')
    size=0
    for suffix in ('','-wal','-shm','-journal'):
        path=_path(root/('objectives.db'+suffix))
        if path.exists():
            require(path.is_file(),'MODEL_SOURCE_OBJECTIVE_STORE_INVALID');size+=path.stat().st_size
    require(size<=8*1024*1024,'MODEL_SOURCE_OBJECTIVE_STORE_BOUND')
    path=_path(root/'objectives.db');require(path.is_file(),'MODEL_SOURCE_OBJECTIVE_STORE_MISSING')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=0.1)) as connection:
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,1024*1024)
        connection.set_progress_handler(lambda:1 if time.monotonic()>=deadline else 0,100)
        connection.execute('BEGIN')
        row=connection.execute('SELECT objective_hash,state,steps_json FROM objectives WHERE id=?',(subject_id,)).fetchone()
        pins=connection.execute('SELECT revision,host_id,source_revision,version,image_digest FROM objective_runtime WHERE task=? LIMIT 2',(subject_id,)).fetchall()
        turns=connection.execute('SELECT revision FROM objective_turns WHERE task=? LIMIT 1',(subject_id,)).fetchall()
    require(time.monotonic()<deadline and row is not None and row[0]==sha(submitted_request['objective'].encode())
        and row[1]=='submitted' and not turns and pins==[(0,runtime['host_id'],runtime['source_revision'],runtime['version'],runtime['image_digest'])],
        'MODEL_SOURCE_ORIGINAL_OBJECTIVE_DRIFT')
    steps=json.loads(row[2]);require(type(steps) is list and len(steps)==1,'MODEL_SOURCE_ORIGINAL_STEP_REQUIRED')
    dispatch=steps[0]['dispatch'];event=dispatch['model_substitution_event']
    require(dispatch['task_id']==subject_id and dispatch['model_calls']==1 and dispatch['execution_model']=='NATIVE_SOURCE_ASSESSMENT',
        'MODEL_SOURCE_ACTUAL_DISPATCH_REQUIRED')
    input_metadata=event['input_artifact_metadata'];result_metadata=dispatch['artifact']
    input_raw=original_artifact(root,input_metadata);result_raw=original_artifact(root,result_metadata)
    output=json.loads(result_raw);context=json.loads(submitted_request['context'])
    execution=dict(schema_version=EXECUTION_SCHEMA,case=CASE,request=submitted_request,request_sha256=sha(canonical(submitted_request)),
        runtime=runtime,registry_sha256=context['registry_sha256'],task_id=subject_id,input_artifact_metadata=input_metadata,
        input_content_utf8=input_raw.decode(),input_read_action_id=event['case_action_ids']['input_read'],
        producer_artifact_metadata=result_metadata,producer_content_utf8=result_raw.decode(),case_action_ids=event['case_action_ids'],
        native_result=output['native_result'])
    require(len(canonical(execution))<=65536,'MODEL_SOURCE_EXECUTION_BOUND');return execution

def execute_review(body,*,actor,task_id,runtime,dispatch_window,ledger):
    from .agent_registry import responsibility_owner,REGISTRY_PATH
    from .agent_cert_model_substitution_review import validate_original_execution
    from .artifact_factory import ArtifactFactory
    from .action_records import ActionRecord,DirectExecutor
    root=_path(Path(os.getenv('PRIME_DATA_DIR','/data')));request=body.model_dump();context=json.loads(request['context'])
    require(type(context) is dict,'MODEL_SOURCE_REVIEW_CONTEXT_REQUIRED')
    execution=context.get('execution');require(type(execution) is dict,'MODEL_SOURCE_REVIEW_EXECUTION_REQUIRED')
    require(actor=='a26' and responsibility_owner('responsibility.a26')==actor
        and task_id!=execution.get('task_id') and canonical(request)==canonical(canonical_request('review',execution)),
        'MODEL_SOURCE_DISTINCT_CURRENT_PEER_REQUIRED')
    registry=registry_pin();_registry(registry)
    window=ResidentCaseWindow.from_original_task(root=root,task_id=task_id,submitted_request=request,
        runtime=runtime,dispatch_window=dispatch_window)
    require(not any(json.loads(line).get('task_id')==task_id for line in _ledger_lines(root)),
        'MODEL_SOURCE_PEER_TASK_REPLAY')
    report=validate_original_execution(execution,root=root,runtime=runtime,registry_sha256=registry,
        deadline=time.monotonic()+min(1,window.remaining()))
    require(registry_pin()==registry,'MODEL_SOURCE_REGISTRY_CHANGED_AFTER_REVIEW')
    factory=ArtifactFactory(_path(root/'artifacts'));record=ActionRecord(task_id,actor,action_type('review'),'artifact-factory',
        parameters_summary=dict(case=CASE,subject_task_id=execution['task_id'],execution_sha256=sha(canonical(execution)),
            registry_sha256=registry,source_revision=runtime['source_revision']))
    def create():
        window.remaining();raw=canonical(report);require(len(raw)<=49152,'MODEL_SOURCE_REVIEW_BOUND')
        metadata=factory.create(kind='json',content=raw.decode(),task_id=task_id,creator=actor,
            provenance=PROVENANCE,runtime_revision=runtime['source_revision'])
        require(original_artifact(root,metadata)==raw,'MODEL_SOURCE_PEER_READBACK_DRIFT');return metadata
    metadata=DirectExecutor(ledger).execute(record,create)
    require(ledger.flush(timeout=window.remaining()) is True and ledger.dropped==0,'MODEL_SOURCE_PEER_NOT_DURABLE')
    window.remaining()
    return dict(task_id=task_id,state='COMPLETED',artifact=metadata,model_calls=0,execution_model='DETERMINISTIC',
        agent_id=actor,capability='responsibility.a26',runtime_source_revision=runtime['source_revision'],
        review_action_id=record.action_id,review_action_durable=True,certification='UNVERIFIED')
