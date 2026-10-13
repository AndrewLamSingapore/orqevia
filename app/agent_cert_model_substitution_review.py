"""Independent original native assessment grader; no inference or store writes.

Recorded lease snapshots are historical observations, not surviving lease rows
or an atomic no-cold-load guarantee. Simulated transport never qualifies a case.
"""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import hashlib,json,math,os,re,sqlite3,time,uuid

CASE='model_substitution:complete'
PROVENANCE='SOURCE public synthetic model-substitution assessment; UNVERIFIED; no service execution'
MAX_BYTES=65536
EXECUTION_FIELDS={'schema_version','case','request','request_sha256','runtime','registry_sha256','task_id',
    'input_artifact_metadata','input_content_utf8','input_read_action_id','producer_artifact_metadata',
    'producer_content_utf8','case_action_ids','native_result'}
LEASE_FIELDS={'endpoint','job_id','instance','boot_id','state','demand_mib','refresh_after','dispatched_at','max_leases'}

class SubstitutionReviewError(ValueError):pass
def require(value,code):
    if value is not True:raise SubstitutionReviewError(code) from None
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def sha(raw):return hashlib.sha256(raw).hexdigest()
def exact_uuid(value):
    try:return type(value) is str and str(uuid.UUID(value))==value
    except (ValueError,AttributeError,TypeError):return False
def utc(value):
    require(type(value) is str and len(value)<=64,'SUBSTITUTION_ORIGINAL_UTC_REQUIRED')
    try:value=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:raise SubstitutionReviewError('SUBSTITUTION_ORIGINAL_UTC_REQUIRED') from None
    require(value.tzinfo is not None,'SUBSTITUTION_ORIGINAL_UTC_REQUIRED');return value.astimezone(timezone.utc)
def parse(raw,limit=MAX_BYTES):
    require(type(raw) is bytes and 0<len(raw)<=limit,'SUBSTITUTION_ORIGINAL_BYTES_BOUND')
    def pairs(values):
        result={}
        for key,value in values:
            require(key not in result,'SUBSTITUTION_DUPLICATE_JSON');result[key]=value
        return result
    try:return json.loads(raw.decode(),object_pairs_hook=pairs,parse_constant=lambda _:require(False,'SUBSTITUTION_NONFINITE_JSON'))
    except SubstitutionReviewError:raise
    except Exception:raise SubstitutionReviewError('SUBSTITUTION_ORIGINAL_JSON_REQUIRED') from None
def tick(deadline):require(type(deadline) in (int,float) and math.isfinite(deadline) and time.monotonic()<deadline,'SUBSTITUTION_REVIEW_SHARED_DEADLINE')
def guarded(path):
    path=Path(path)
    require(path.is_absolute() and '..' not in path.parts,'SUBSTITUTION_ORIGINAL_ABSOLUTE_PATH')
    for part in (path,*path.parents):
        require(not part.is_symlink() and not part.is_junction(),'SUBSTITUTION_ORIGINAL_REPARSE')
    return path
def original_bytes(path,limit,deadline):
    tick(deadline);path=guarded(path);before=path.stat()
    identity=lambda x:(x.st_dev,x.st_ino,x.st_size,x.st_mtime_ns,x.st_mode)
    require(path.is_file() and 0<before.st_size<=limit,'SUBSTITUTION_ORIGINAL_FILE_BOUND')
    with path.open('rb') as stream:
        require(identity(os.fstat(stream.fileno()))==identity(before),'SUBSTITUTION_ORIGINAL_FILE_CHANGED')
        raw=stream.read(limit+1)
        require(0<len(raw)<=limit and identity(os.fstat(stream.fileno()))==identity(before),'SUBSTITUTION_ORIGINAL_FILE_CHANGED')
    require(identity(guarded(path).stat())==identity(before),'SUBSTITUTION_ORIGINAL_FILE_CHANGED');tick(deadline)
    return raw
def database(root,name,deadline):
    root=guarded(root);used=0
    for suffix in ('','-wal','-shm','-journal'):
        path=guarded(root/(name+suffix))
        if path.exists():require(path.is_file(),'SUBSTITUTION_ORIGINAL_DB_FILE');used+=path.stat().st_size
    require(used<=8*1024*1024 and (root/name).is_file(),'SUBSTITUTION_ORIGINAL_DB_BOUND');tick(deadline)
    return root/name
def connection(path,deadline):
    tick(deadline);db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=min(.1,deadline-time.monotonic()))
    try:
        db.row_factory=sqlite3.Row
        db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,MAX_BYTES);db.setlimit(sqlite3.SQLITE_LIMIT_COLUMN,128)
        db.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH,4096)
        db.set_progress_handler(lambda:1 if time.monotonic()>=deadline else 0,100);db.execute('BEGIN')
    except BaseException:
        db.close();raise
    return db

def original_artifact(root,metadata,text,task,runtime,deadline):
    require(type(text) is str,'SUBSTITUTION_ORIGINAL_ARTIFACT_TEXT');raw=text.encode()
    fields={'artifact_id','task_id','type','creator_agents','timestamp','version','provenance','runtime_revision',
        'validation_state','content_validation','location','sha256','bytes','delivery_state'}
    require(type(metadata) is dict and set(metadata)==fields and re.fullmatch('[0-9a-f]{32}',metadata['artifact_id']) is not None
        and metadata['task_id']==task and metadata['creator_agents']==['a19'] and metadata['type']=='json'
        and metadata['location']=='artifact.json' and metadata['provenance']==PROVENANCE
        and metadata['runtime_revision']==runtime['source_revision'] and metadata['version']=='1.0.0'
        and metadata['validation_state']=='STRUCTURE_VALIDATED' and metadata['delivery_state']=='AVAILABLE'
        and metadata['content_validation']=='Not independently established by structural validation'
        and type(metadata['bytes']) is int and 0<metadata['bytes']==len(raw)<=MAX_BYTES
        and metadata['sha256']==sha(raw),'SUBSTITUTION_ORIGINAL_ARTIFACT_METADATA')
    folder=guarded(root/'artifacts'/metadata['artifact_id'])
    stored_meta=original_bytes(folder/'metadata.json',8192,deadline)
    stored_raw=original_bytes(folder/'artifact.json',MAX_BYTES,deadline)
    require(parse(stored_meta)==metadata and stored_raw==raw,'SUBSTITUTION_ORIGINAL_ARTIFACT_CHANGED')
    return parse(raw),sha(stored_meta)

def original_task(root,execution,runtime,deadline):
    task=execution['task_id'];request=execution['request']
    require(exact_uuid(task),'SUBSTITUTION_ORIGINAL_TASK_ID')
    with closing(connection(database(root,'objectives.db',deadline),deadline)) as db:
        row=db.execute('SELECT objective_hash,state,steps_json FROM objectives WHERE id=?',(task,)).fetchone()
        times=db.execute('SELECT revision,created_at,updated_at FROM objective_metadata WHERE task=? LIMIT 2',(task,)).fetchall()
        pins=db.execute('SELECT revision,host_id,source_revision,version,image_digest FROM objective_runtime WHERE task=? LIMIT 2',(task,)).fetchall()
        turns=db.execute('SELECT revision FROM objective_turns WHERE task=? LIMIT 1',(task,)).fetchone()
    tick(deadline)
    require(row is not None and row['objective_hash']==sha(request['objective'].encode()) and row['state']=='submitted'
        and turns is None and len(times)==1 and times[0]['revision']==0 and len(pins)==1
        and tuple(pins[0])==(0,runtime['host_id'],runtime['source_revision'],runtime['version'],runtime['image_digest']),
        'SUBSTITUTION_ORIGINAL_TASK_CHANGED')
    steps=parse(row['steps_json'].encode());require(type(steps) is list and len(steps)==1
        and set(steps[0])=={'capability','dispatch'} and steps[0]['capability']=='responsibility.a19','SUBSTITUTION_ORIGINAL_TASK_STEPS')
    dispatch=steps[0]['dispatch']
    require(dispatch['task_id']==task and dispatch['agent_id']=='a19' and dispatch['capability']=='responsibility.a19'
        and dispatch['execution_model']=='NATIVE_SOURCE_ASSESSMENT' and type(dispatch['model_calls']) is int
        and dispatch['model_calls']==1 and dispatch['artifact']==execution['producer_artifact_metadata']
        and dispatch['runtime_source_revision']==runtime['source_revision'],'SUBSTITUTION_ORIGINAL_DISPATCH_CHANGED')
    event=dispatch['model_substitution_event']
    require(type(event) is dict and set(event)=={'input_artifact_metadata','case_action_ids','native_job_ids'}
        and event['input_artifact_metadata']==execution['input_artifact_metadata']
        and event['case_action_ids']==execution['case_action_ids']
        and event['native_job_ids']==[item['job']['id'] for item in execution['native_result']['attempts']],
        'SUBSTITUTION_ORIGINAL_DISPATCH_EVENT_CHANGED')
    return dict(created_at=times[0]['created_at'],updated_at=times[0]['updated_at'],dispatch_sha256=sha(canonical(dispatch)))

def ledger(root,deadline):
    raw=original_bytes(root/'action-records.jsonl',8*1024*1024,deadline)
    require(raw.endswith(b'\n'),'SUBSTITUTION_ORIGINAL_LEDGER_FRAMING');events=[];previous='0'*64
    for number,line in enumerate(raw.splitlines(),1):
        tick(deadline);event=parse(line);digest=event.pop('sha256')
        require(event['sequence']==number and event['previous_sha256']==previous and sha(canonical(event))==digest,
            'SUBSTITUTION_ORIGINAL_LEDGER_CHAIN');previous=digest;event['sha256']=digest;events.append(event)
    return events
def action_pair(events,identifier,task,action,tool,completed,deadline):
    tick(deadline);rows=[x for x in events if x.get('action_id')==identifier]
    require(len(rows)==2 and all(x['task_id']==task and x['agent_id']=='a19' and x['action_type']==action
        and x['tool']==tool and x['classification']=='R0' and x['execution_location']=='local' for x in rows)
        and rows[0]['phase']=='started' and rows[1]['phase']==completed,'SUBSTITUTION_ORIGINAL_ACTION_PAIR')
    require(utc(rows[0]['timestamp'])<=utc(rows[1]['timestamp']),'SUBSTITUTION_ORIGINAL_ACTION_TIME')
    return rows

def native_ps(receipt,job,contract,phase,decision,deadline):
    tick(deadline);require(type(receipt) is dict and receipt.get('phase')==phase and receipt.get('decision')==decision
        and receipt.get('job_id')==job['id'] and receipt.get('model')==job['model']
        and receipt.get('source_revision')==contract['source_revision'] and receipt.get('domain_id')==contract['domain_id']
        and receipt.get('contract_sha256')==sha(canonical(contract)) and receipt.get('qualification')=='SOURCE_UNREADY'
        and receipt.get('atomic_no_cold_load_guarantee') is False,'SUBSTITUTION_ORIGINAL_PS_BINDING')
    raw=receipt['raw_ps_utf8'].encode();require(sha(raw)==receipt['raw_ps_sha256'],'SUBSTITUTION_ORIGINAL_PS_HASH')
    body=parse(raw);require(type(body) is dict and set(body)=={'models'} and type(body['models']) is list
        and len(body['models'])<=8,'SUBSTITUTION_ORIGINAL_PS_MODELS')
    observed=utc(receipt['observed_at']);require(utc(contract['started_at'])<=observed<=utc(contract['deadline']),
        'SUBSTITUTION_ORIGINAL_PS_TIME')
    entries={}
    for item in body['models']:
        require(type(item) is dict and item.get('name')==item.get('model') and item['name'] not in entries
            and type(item.get('digest')) is str and re.fullmatch('[0-9a-f]{64}',item['digest']) is not None,
            'SUBSTITUTION_ORIGINAL_PS_ENTRY');entries[item['name']]=item;utc(item['expires_at'])
    selected=entries.get(job['model']);alternative=next(x for x in contract['alternatives'] if x['model']==job['model'])
    if selected is not None:require(selected['digest']==alternative['digest'],'SUBSTITUTION_ORIGINAL_MODEL_DIGEST')
    available=selected is not None and utc(selected['expires_at'])>=utc(contract['deadline'])
    require(available==(decision=='RESIDENT_ADMITTED') and receipt['expires_at']==(None if selected is None else selected['expires_at'])
        and receipt['reason']==(None if available else 'NOT_RESIDENT' if selected is None else 'EXPIRY_BEFORE_SHARED_DEADLINE'),
        'SUBSTITUTION_ORIGINAL_RESIDENCY_DECISION')
    snapshot=receipt['original_lease_snapshot']
    require(type(snapshot) is dict and set(snapshot)==LEASE_FIELDS,'SUBSTITUTION_RECORDED_ORIGINAL_LEASE_SNAPSHOT')
    from urllib.parse import urlsplit
    endpoint=urlsplit(snapshot['endpoint'])
    require(endpoint.scheme=='http' and endpoint.hostname=='127.0.0.1' and endpoint.port is not None
        and 1<=endpoint.port<=65535 and endpoint.username is None and endpoint.password is None
        and not endpoint.path and not endpoint.query and not endpoint.fragment,'SUBSTITUTION_ORIGINAL_LEASE_ENDPOINT')
    require(snapshot['endpoint']==contract['generation']['effective_public_settings']['ollama_base_url'],
        'SUBSTITUTION_ORIGINAL_GENERATION_ENDPOINT')
    require(type(snapshot) is dict and set(snapshot)==LEASE_FIELDS and snapshot['job_id']==job['id']
        and snapshot['state']==('pending' if phase=='PRE_DISPATCH' else 'running')
        and snapshot['instance']=='' and snapshot['boot_id']==''
        and type(snapshot['demand_mib']) is int and snapshot['demand_mib']>0
        and type(snapshot['max_leases']) is int and snapshot['max_leases']==1
        and all(type(snapshot[k]) in (int,float) and math.isfinite(snapshot[k]) for k in ('refresh_after','dispatched_at'))
        and (snapshot['dispatched_at']==0 if phase=='PRE_DISPATCH' else snapshot['dispatched_at']>0),
        'SUBSTITUTION_RECORDED_ORIGINAL_LEASE_SNAPSHOT')
    return sha(raw)

def original_native(root,value,input_raw,events,deadline):
    require(type(value) is dict and set(value)=={'state','case','contract','attempts','fallback_exercised','assessment_result',
        'actual_service_health','atomic_no_cold_load_guarantee','reload_consistency','certification'}
        and value['state']=='SOURCE_UNREADY' and value['case']==CASE and value['fallback_exercised'] is True
        and value['actual_service_health']=='UNKNOWN' and value['atomic_no_cold_load_guarantee'] is False
        and value['reload_consistency']=='NOT_VERIFIED_NATIVE_METRIC_RETAINED' and value['certification']=='UNVERIFIED',
        'SUBSTITUTION_NATIVE_RESULT_SCOPE')
    contract=value['contract'];attempts=value['attempts']
    require(type(contract) is dict and set(contract)=={'schema','case','source_revision','domain_id','registry_sha256',
        'identity_scope','prompt_sha256','alternatives','minimum_tier','data_classification','max_cost_usd','max_retries',
        'residency_policy','requested_cold_loads','started_at','deadline','qualification','generation'},'SUBSTITUTION_NATIVE_CONTRACT_FIELDS')
    generation=contract['generation']
    require(type(generation) is dict and set(generation)=={'original_public_settings','effective_public_settings','options'}
        and generation['options']=={},'SUBSTITUTION_ORIGINAL_GENERATION_FIELDS')
    original=generation['original_public_settings'];effective=generation['effective_public_settings']
    setting_fields={'ollama_base_url','fast_model','deep_model','embedding_model','multi_specialist_workers',
        'evaluator_model','compute_profile','context_tokens','max_output_tokens','keep_alive'}
    require(type(original) is dict and set(original)==setting_fields and type(effective) is dict
        and effective==dict(original,context_tokens=512,max_output_tokens=16)
        and original['fast_model']=='gemma3:1b' and original['deep_model']=='gemma3:4b',
        'SUBSTITUTION_ORIGINAL_PRIVATE_GENERATION_LIMITS')
    raw_receipts={name:original_bytes(root/name,4096 if name=='source-qualification-domain.json' else MAX_BYTES,deadline)
        for name in ('source-qualification-domain.json','source-residency-assessment.claim',
            'source-residency-result.json','source-residency-fast-failure.json')}
    require(parse(raw_receipts['source-qualification-domain.json'])==dict(
        schema='prime.source-qualification-domain.v1',domain_id=contract['domain_id'],source_revision=contract['source_revision'],
        scope='SOURCE_TEMPORARY_DOMAIN_NOT_ACCEPTED_RUNTIME'),'SUBSTITUTION_ORIGINAL_SOURCE_DOMAIN')
    require(parse(raw_receipts['source-residency-assessment.claim'])==contract,
        'SUBSTITUTION_ORIGINAL_NATIVE_CLAIM')
    require(parse(raw_receipts['source-residency-result.json'])==value,
        'SUBSTITUTION_ORIGINAL_NATIVE_RESULT_RECEIPT')
    require(parse(raw_receipts['source-residency-fast-failure.json'])==dict(
        state='SOURCE_UNREADY',case=CASE,contract=contract,attempt=attempts[0],error_type='ResidencyUnavailable',native_chat_utf8=''),
        'SUBSTITUTION_ORIGINAL_NATIVE_DENIAL_RECEIPT')
    require(type(attempts) is list and len(attempts)==2 and len({x['job']['id'] for x in attempts})==2
        and contract['case']==CASE and contract['data_classification']=='LOCAL_ONLY'
        and contract['max_retries']==0 and contract['max_cost_usd']==0 and contract['requested_cold_loads']==0
        and contract['qualification']=='SOURCE_UNREADY' and contract['identity_scope']=='SOURCE_TEMPORARY_DOMAIN_NOT_ACCEPTED_RUNTIME'
        and contract['minimum_tier']=='NANO' and contract['residency_policy']=='resident_admission_observation',
        'SUBSTITUTION_NATIVE_ALTERNATIVES_POLICY')
    alternatives=contract['alternatives'];require(type(alternatives) is list and len(alternatives)==2
        and [(x['role'],x['model'],x['tier']) for x in alternatives]==[('fast','gemma3:1b','NANO'),('deep','gemma3:4b','MINI')]
        and all(type(x['digest']) is str and re.fullmatch('[0-9a-f]{64}',x['digest']) is not None for x in alternatives),
        'SUBSTITUTION_ORIGINAL_ORDERED_ALTERNATIVES')
    with closing(connection(database(root,'compute-queue.db',deadline),deadline)) as db:
        originals=[];histories=[]
        for attempt in attempts:
            row=db.execute('SELECT * FROM compute_jobs WHERE id=?',(attempt['job']['id'],)).fetchone()
            require(row is not None and dict(row)==attempt['job'],'SUBSTITUTION_ORIGINAL_NATIVE_JOB_CHANGED');originals.append(dict(row))
            history=[dict(item) for item in db.execute('SELECT event_type,details_json,created_at FROM compute_events WHERE job_id=? ORDER BY rowid LIMIT 4',
                (attempt['job']['id'],)).fetchall()]
            require(len(history)==3,'SUBSTITUTION_ORIGINAL_NATIVE_EVENTS');histories.append(history)
        extra=db.execute('SELECT id FROM compute_jobs WHERE created_at>=? AND created_at<=? LIMIT 4',
            (contract['started_at'],contract['deadline'])).fetchall()
        require({x['id'] for x in extra}=={x['id'] for x in originals},'SUBSTITUTION_HIDDEN_NATIVE_JOB')
    tick(deadline);require(originals[0]['prompt']==originals[1]['prompt']==
        'Classify these public synthetic checks: true,false,true. Reply only DEGRADED if any is false, otherwise PASS.'
        and sha(originals[0]['prompt'].encode())==contract['prompt_sha256'],'SUBSTITUTION_SAME_ORIGINAL_ASSESSMENT_PROMPT')
    for index,(attempt,job,alternative) in enumerate(zip(attempts,originals,alternatives)):
        require(set(attempt)=={'job','residency','action_id'} and job['agent']=='a19' and job['model_role']==alternative['role']
            and job['model']==alternative['model'] and job['provider']=='ollama-'+alternative['role']
            and job['preferred_provider']==job['provider'] and job['attempts']==1 and job['max_retries']==0
            and job['allow_cloud']==job['external_execution']==0 and job['data_classification']=='LOCAL_ONLY'
            and job['classification']=='R0' and job['timeout_seconds']==5 and job['actual_cost_usd']==0
            and job['max_cost_usd']==0,'SUBSTITUTION_ORIGINAL_NATIVE_JOB_POLICY')
        history=histories[index];terminal='failed' if index==0 else 'completed'
        require([x['event_type'] for x in history]==['submitted','claimed',terminal]
            and utc(job['created_at'])<=utc(history[0]['created_at'])<=utc(job['started_at'])
            and utc(job['started_at'])<=utc(history[1]['created_at'])<=utc(job['completed_at'])
            and utc(job['completed_at'])<=utc(history[2]['created_at'])<=utc(contract['deadline']),
            'SUBSTITUTION_ORIGINAL_NATIVE_EVENT_ORDER')
        terminal_details=parse(history[2]['details_json'].encode())
        require(set(terminal_details)=={'error','cost_usd','attempt','model_load_ns','inference_ns'}
            and terminal_details['error']==job['error'] and terminal_details['cost_usd']==0
            and terminal_details['attempt']==1,'SUBSTITUTION_ORIGINAL_NATIVE_COMPLETION_EVENT')
        native_pair=action_pair(events,attempt['action_id'],job['id'],'inference.run','ollama','completed',deadline)
        require(native_pair[1]['success'] is (index==1)
            and native_pair[1].get('error')==('ResidencyUnavailable' if index==0 else None),
            'SUBSTITUTION_ORIGINAL_NATIVE_ACTION_OUTCOME')
        require(all(row['parameters_summary']==dict(contract_sha256=sha(canonical(contract)),domain_id=contract['domain_id'])
            and row['model_backend']==job['model'] for row in native_pair)
            and len([x for x in events if x['task_id']==job['id']])==2,'SUBSTITUTION_NATIVE_ORIGINAL_ACTION_SCOPE')
        require(utc(contract['started_at'])<=utc(job['created_at'])<=utc(job['started_at'])<=utc(job['completed_at'])<=utc(contract['deadline']),
            'SUBSTITUTION_ORIGINAL_NATIVE_JOB_TIME')
        if index==0:
            require(job['status']=='failed' and job['error']=='RESIDENCY_UNAVAILABLE' and not job['result'],
                'SUBSTITUTION_ORIGINAL_PERMITTED_DENIAL')
            native_ps(attempt['residency'],job,contract,'PRE_DISPATCH','RESIDENCY_UNAVAILABLE',deadline)
        else:
            require(native_pair[1]['result_summary']==dict(type='dict',output_sha256=sha(job['result'].encode()),
                output_length=len(job['result'])),'SUBSTITUTION_ORIGINAL_NATIVE_ACTION_OUTPUT')
            require(job['status']=='completed' and job['error']=='' and job['result'].strip()=='DEGRADED'
                and value['assessment_result']==job['result'],'SUBSTITUTION_ACTUAL_DEEP_ASSESSMENT_OUTPUT')
            observation=attempt['residency'];require(set(observation)=={'before','after','completion','native_chat_utf8','native_chat_request_utf8'},'SUBSTITUTION_NATIVE_CHAT_CUSTODY')
            outgoing=observation['native_chat_request_utf8'].encode()
            require(outgoing==canonical(dict(model=job['model'],messages=[dict(role='user',content=job['prompt'])],
                stream=True,keep_alive=effective['keep_alive'],options=dict(num_ctx=512,num_predict=16))),
                'SUBSTITUTION_ORIGINAL_OUTGOING_NATIVE_PAYLOAD')
            native_ps(observation['before'],job,contract,'PRE_DISPATCH','RESIDENT_ADMITTED',deadline)
            native_ps(observation['after'],job,contract,'POST_DISPATCH','RESIDENT_ADMITTED',deadline)
            lines=observation['native_chat_utf8'].encode();require(0<len(lines)<=MAX_BYTES,'SUBSTITUTION_NATIVE_CHAT_BOUND')
            messages=[parse(line) for line in lines.splitlines() if line]
            require(messages and messages[-1].get('done') is True and messages[-1].get('model')==job['model']
                and sum(x.get('done') is True for x in messages)==1
                and ''.join(x.get('message',{}).get('content','') for x in messages)==job['result'],
                'SUBSTITUTION_NATIVE_ORIGINAL_CHAT_OUTPUT')
            final=messages[-1];completion=observation['completion']
            require(type(final.get('load_duration')) is int and final['load_duration']>=0
                and completion==dict(load_duration=final['load_duration'],atomic_no_cold_load_guarantee=False,qualification='SOURCE_UNREADY'),
                'SUBSTITUTION_NATIVE_ORIGINAL_LOAD_METRIC')
            require(terminal_details['model_load_ns']==final['load_duration']
                and terminal_details['inference_ns']==final.get('eval_duration',0)
                and job['input_tokens']==int(final.get('prompt_eval_count',0)) and job['output_tokens']==int(final.get('eval_count',0)),
                'SUBSTITUTION_NATIVE_ORIGINAL_METRIC_EVENT')
    require(utc(originals[0]['completed_at'])<=utc(originals[1]['created_at']),'SUBSTITUTION_NATIVE_FALLBACK_ORDER')
    return {'job_ids':[x['id'] for x in originals],'native_result_sha256':sha(canonical(value)),
        'native_event_history_sha256':sha(canonical(histories)),
        'original_receipt_sha256':{name:sha(raw) for name,raw in raw_receipts.items()}}

def validate_original_execution(execution,*,root,runtime,registry_sha256,deadline):
    """Twice read the actual original domains before any peer output is created."""
    tick(deadline);root=guarded(root)
    require(type(execution) is dict and set(execution)==EXECUTION_FIELDS and len(canonical(execution))<=MAX_BYTES
        and execution['schema_version']=='prime.source-model-substitution-execution.v1'
        and execution['case']==CASE and execution['runtime']==runtime and execution['registry_sha256']==registry_sha256
        and execution['request_sha256']==sha(canonical(execution['request'])),'SUBSTITUTION_ORIGINAL_EXECUTION_ENVELOPE')
    from .agent_cert_model_substitution_events import canonical_request
    require(execution['request']==canonical_request('subject'),'SUBSTITUTION_ORIGINAL_CANONICAL_REQUEST')
    from .agent_cert_artifact_events import _registry
    _registry(registry_sha256)
    original_input=parse(execution['input_content_utf8'].encode())
    require(original_input==dict(schema_version='prime.public-model-substitution-input.v1',case=CASE,
        service_id='PUBLIC_SYNTHETIC_ASSESSMENT',checks=[True,False,True])
        and all(type(x) is bool for x in original_input['checks']),'SUBSTITUTION_ORIGINAL_PUBLIC_INPUT')
    # Independently derive from the original supplied facts, never a producer helper.
    expected='DEGRADED' if any(x is False for x in original_input['checks']) else 'PASS'
    require(expected=='DEGRADED','SUBSTITUTION_INDEPENDENT_ASSESSMENT')
    previous=None
    for _ in range(2):
        tick(deadline);task=original_task(root,execution,runtime,deadline)
        input_value,input_meta_sha=original_artifact(root,execution['input_artifact_metadata'],execution['input_content_utf8'],execution['task_id'],runtime,deadline)
        output,output_meta_sha=original_artifact(root,execution['producer_artifact_metadata'],execution['producer_content_utf8'],execution['task_id'],runtime,deadline)
        input_sha=sha(execution['input_content_utf8'].encode())
        require(input_value==original_input and output==dict(schema_version='prime.public-model-substitution-result.v1',case=CASE,
            task_id=execution['task_id'],input_sha256=input_sha,assessment=expected,actual_service_health='UNKNOWN',
            execution='NOT_PERFORMED',native_result=execution['native_result'],certification='UNVERIFIED'),
            'SUBSTITUTION_INDEPENDENT_ORIGINAL_RESULT')
        events=ledger(root,deadline);ids=execution['case_action_ids']
        require(type(ids) is dict and set(ids)=={'setup','input_read','result'} and len(set(ids.values()))==3
            and execution['input_read_action_id']==ids['input_read'],'SUBSTITUTION_ORIGINAL_CASE_ACTION_IDS')
        pairs=[action_pair(events,ids[name],execution['task_id'],'agent.certification.model_substitution.'+name,
            'provided_context.read' if name=='input_read' else 'artifact-factory','completed',deadline) for name in ('setup','input_read','result')]
        for name,pair in zip(('setup','input_read','result'),pairs):
            parameters=dict(case=CASE,source_revision=runtime['source_revision'],registry_sha256=registry_sha256)
            if name=='input_read':parameters.update(input_artifact_id=execution['input_artifact_metadata']['artifact_id'],expected_sha256=input_sha)
            require(all(row['parameters_summary']==parameters and row['target']==('artifact.json' if name=='input_read' else '')
                and row['model_backend']=='deterministic' for row in pair),'SUBSTITUTION_ORIGINAL_CASE_ACTION_BOUNDING')
            require(pair[1]['success'] is True and pair[1].get('error') is None,
                'SUBSTITUTION_ORIGINAL_CASE_ACTION_SUCCESS')
            if name=='input_read':
                summary=dict(type='dict',source_sha256=input_sha,output_sha256=input_sha,
                    output_length=len(execution['input_content_utf8']))
            else:
                meta=execution['input_artifact_metadata' if name=='setup' else 'producer_artifact_metadata']
                summary=dict(type='dict',artifact_id=meta['artifact_id'],sha256=meta['sha256'],location=meta['location'])
                require(utc(pair[0]['timestamp'])<=utc(meta['timestamp'])<=utc(pair[1]['timestamp']),
                    'SUBSTITUTION_ORIGINAL_ARTIFACT_ACTION_TIME')
            require(pair[1]['result_summary']==summary,'SUBSTITUTION_ORIGINAL_CASE_ACTION_OUTPUT')
        require(len([x for x in events if x['task_id']==execution['task_id']])==6,'SUBSTITUTION_EXACT_OWNING_CASE_ROWS')
        contract=execution['native_result']['contract']
        request_context=parse(execution['request']['context'].encode())
        require(contract['source_revision']==runtime['source_revision'] and contract['registry_sha256']==registry_sha256
            and contract['domain_id']==request_context['domain_id']
            and exact_uuid(contract['domain_id']) and runtime['host_id']=='SOURCE_DOMAIN_'+contract['domain_id']
            and [x['digest'] for x in contract['alternatives']]==[request_context['fast_digest'],request_context['deep_digest']]
            and utc(contract['started_at'])==utc(task['created_at']) and (utc(contract['deadline'])-utc(task['created_at'])).total_seconds()==5
            and utc(task['created_at'])<=utc(execution['input_artifact_metadata']['timestamp'])<=utc(pairs[1][0]['timestamp'])
            and utc(pairs[1][1]['timestamp'])<=utc(execution['producer_artifact_metadata']['timestamp'])<=utc(task['updated_at'])<=utc(contract['deadline']),
            'SUBSTITUTION_ORIGINAL_TASK_ANCHORED_BUDGET')
        native=original_native(root,execution['native_result'],execution['input_content_utf8'].encode(),events,deadline)
        snapshot=dict(task=task,input_metadata_sha256=input_meta_sha,output_metadata_sha256=output_meta_sha,native=native,
            selected_original_rows_sha256=sha(canonical([x for x in events if x['task_id'] in [execution['task_id'],*native['job_ids']]])))
        require(previous is None or snapshot==previous,'SUBSTITUTION_ORIGINAL_CHANGED_BETWEEN_READS');previous=snapshot
    tick(deadline)
    return dict(schema_version='prime.independent-model-substitution-review.v1',case=CASE,subject_task_id=execution['task_id'],
        original_execution_sha256=sha(canonical(execution)),input_sha256=input_sha,assessment=expected,assessment_preserved=True,
        native_job_ids=previous['native']['job_ids'],original_custody=previous,original_domain_reads=2,
        actual_service_health='UNKNOWN',execution='NOT_PERFORMED',certification='UNVERIFIED',
        source_qualification='SOURCE_UNREADY_UNTIL_ACTUAL_BACKEND_QUALIFICATION',atomic_no_cold_load_guarantee=False,
        backend_identity_observed=False,
        lease_scope='SEALED_RECORDED_UNDER_LEASE_OBSERVATIONS_NOT_CURRENT_LEASE_HISTORY')
