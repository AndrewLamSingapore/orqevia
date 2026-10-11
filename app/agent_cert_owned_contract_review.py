"""Independent structural contract oracle and read-only original custody.
Never calls the producer checker/report builder; prose quality stays unknown.
"""
from datetime import datetime, timezone
import hashlib
import json
import time
from .agent_cert_artifact_events import canonical, parse, _path, _utc, _ledger_lines

CASE='baseline:contract'
VERSION='registered.owned-contract-structural.v1'
FIELDS=('agent_id','immutable_id','name','role','purpose','version','lifecycle_status','status',
        'authority','human_approval','can_delegate','reports_to','capability_requirements',
        'responsibilities','non_responsibilities','input_contract','output_contract',
        'tool_eligibility','model_tier_eligibility','tap_relationship','failure_fallback')

class OwnedContractReviewError(ValueError):pass

def require(value,code):
    if value is not True:raise OwnedContractReviewError(code) from None

def sha(raw):return hashlib.sha256(raw).hexdigest()

def independent_domains(raw,agent,capability):
    """Only exact original Registry bytes and actual request schema define fields."""
    from .agent_dispatch_api import AgentRequest
    source=parse(raw,1048576)
    require(source.get('schema_version')=='2.0' and len(source.get('agents',[]))==21,
            'CONTRACT_REVIEW_REGISTRY_INVALID')
    matches=[x for x in source['agents'] if x.get('agent_id')==agent]
    require(len(matches)==1 and agent!='a19','CONTRACT_REVIEW_OWNER_INVALID')
    record=matches[0]
    require(record['immutable_id']==agent and capability in record['capability_requirements']
        and sum(capability in x['capability_requirements'] for x in source['agents'])==1,
        'CONTRACT_REVIEW_CAPABILITY_INVALID')
    selected=[x for x in record['responsibilities'] if x['id']==capability]
    require(len(selected)==1,'CONTRACT_REVIEW_SELECTED_INVALID')
    definition={k:record[k] for k in FIELDS}
    aliases={x['id']:x['agent_id'] for x in source['leads']}
    definition['reports_to']=aliases.get(definition['reports_to'],definition['reports_to'])
    schema=AgentRequest.model_json_schema();properties=schema['properties']
    bounds={k:{n:properties[k][n] for n in ('minLength','maxLength') if n in properties[k]}
            for k in ('capability','objective','context')}
    return dict(registry=dict(source='config/agent_registry.json',source_sha256=sha(raw),
            schema_version=source['schema_version'],registry_version=source['registry_version'],agent_count=21),
        definition=definition,definition_sha256=sha(canonical(definition)),
        request_contract=dict(source='app.agent_dispatch_api.AgentRequest',schema=schema,
            schema_sha256=sha(canonical(schema)),input_bounds=bounds),
        selected_capability=selected[0],selected_capability_sha256=sha(canonical(selected[0])))

def independently_check(raw,domains):
    value=parse(raw,65536);definition=domains['definition'];selected=domains['selected_capability']
    require(set(value)=={'schema_version','agent_id','capability_id','source','samples'}
        and value['schema_version']=='prime.owned-contract-input.v1'
        and value['source']=='PUBLIC_SYNTHETIC_ONLY' and value['agent_id']==definition['immutable_id']
        and value['capability_id']==selected['id'],'CONTRACT_REVIEW_INPUT_INVALID')
    samples=value['samples'];require(type(samples) is list and 1<=len(samples)<=8,'CONTRACT_REVIEW_SAMPLES_BOUND')
    findings=[];seen=set()
    for sample in samples:
        require(type(sample) is dict and set(sample)=={'id','input_utf8','output_utf8'}
            and type(sample['id']) is str and 1<=len(sample['id'])<=100
            and sample['id'] not in seen,'CONTRACT_REVIEW_SAMPLE_INVALID')
        seen.add(sample['id'])
        require(type(sample['input_utf8']) is str and type(sample['output_utf8']) is str,
            'CONTRACT_REVIEW_RAW_INPUT_REQUIRED')
        supplied=parse(sample['input_utf8'].encode(),16384);proposed=parse(sample['output_utf8'].encode(),16384)
        missing_in=[name for name in definition['input_contract']['required'] if name not in supplied]
        missing_out=[name for name in definition['output_contract']['required'] if name not in proposed]
        invalid=[]
        for name in ('objective','context'):
            if name not in supplied:continue
            text=supplied[name];limits=domains['request_contract']['input_bounds'][name]
            if type(text) is not str or len(text)<limits.get('minLength',0) or len(text)>limits['maxLength']:
                invalid.append('input.'+name+'.bounds')
        if 'data_classification' in supplied and supplied['data_classification'] not in definition['input_contract']['data_classification']:
            invalid.append('input.data_classification.enum')
        if 'agent_id' in proposed and proposed['agent_id']!=definition['immutable_id']:
            invalid.append('output.agent_id.identity')
        if 'status' in proposed and proposed['status'] not in definition['output_contract']['status']:
            invalid.append('output.status.enum')
        actions=proposed.get('proposed_actions')
        if type(actions) is list and any(type(item) is dict and item.get('executed') is True for item in actions):
            invalid.append('output.proposed_actions.execution_claim')
        findings.append(dict(id=sample['id'],input_sha256=sha(sample['input_utf8'].encode()),
            output_sha256=sha(sample['output_utf8'].encode()),missing_input=missing_in,
            missing_output=missing_out,violations=invalid,
            structural_conformance=len(missing_in)+len(missing_out)+len(invalid)==0))
    return findings

def independent_report(raw,registry_raw,*,task_id,agent_id,capability_id):
    domains=independent_domains(registry_raw,agent_id,capability_id)
    return dict(schema_version='prime.owned-contract-result.v1',case=CASE,case_version=VERSION,
        task_id=task_id,agent_id=agent_id,capability_id=capability_id,input_sha256=sha(raw),
        registry_sha256=sha(registry_raw),owned_domains_sha256=sha(canonical(domains)),
        samples=independently_check(raw,domains),prose_semantics='NOT_ESTABLISHED',
        role_result_quality='NOT_ESTABLISHED',execution_authority='NOT_GRANTED',
        actual_service_health='UNKNOWN',certification='UNVERIFIED')

def _registry_original(expected):
    from .agent_registry import REGISTRY_PATH
    path=_path(REGISTRY_PATH);before=path.stat()
    require(path.is_file() and 0<before.st_size<=1048576,'CONTRACT_REVIEW_REGISTRY_BOUND')
    with path.open('rb') as stream:raw=stream.read(1048577)
    after=_path(path).stat()
    require(len(raw)==before.st_size and sha(raw)==expected
        and (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)==
            (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns),
        'CONTRACT_REVIEW_REGISTRY_CHANGED')
    return raw

def validate_original_execution(execution,*,root,runtime,registry_sha256,deadline):
    """Reopen native immutable task, both artifacts and six rows twice."""
    from .agent_cert_fresh_input import read_task
    from .agent_cert_recovery_events import retrieve_original_artifact
    require(type(execution) is dict and set(execution)=={'case_spec','submitted_request','runtime',
        'runtime_after','runtime_current','submission','dispatch','artifact_metadata',
        'artifact_content_utf8','input_content_utf8','objective_read','original_action_records','observation'},
        'CONTRACT_REVIEW_EXECUTION_FIELDS')
    validate_execution(execution,source_revision=runtime['source_revision'],runtime_image_id=runtime['image_digest'],
        registry_sha256=registry_sha256,now=datetime.now(timezone.utc))
    frozen=canonical(execution);require(len(frozen)<=262144,'CONTRACT_REVIEW_EXECUTION_BOUND')
    require(type(deadline) in (int,float) and time.monotonic()<deadline<=time.monotonic()+5,
        'CONTRACT_REVIEW_DEADLINE')
    require(all(canonical(execution[k])==canonical(runtime) for k in ('runtime','runtime_after','runtime_current')),
        'CONTRACT_REVIEW_RUNTIME_DRIFT')
    dispatch=execution['dispatch'];task=dispatch['task_id'];actor=dispatch['agent_id'];cap=dispatch['capability']
    require(actor!='a19' and dispatch['state']=='COMPLETED' and type(dispatch['model_calls']) is int
        and dispatch['model_calls']==0 and dispatch['execution_model']=='DETERMINISTIC'
        and dispatch['runtime_source_revision']==runtime['source_revision'],'CONTRACT_REVIEW_DISPATCH')
    spec=execution['case_spec'];body=execution['submitted_request'];event=dispatch['owned_contract_event']
    require(spec['case']==CASE and spec['case_version']==VERSION and spec['agent_id']==actor
        and spec['capability_id']==cap and canonical(spec['request'])==canonical(body)
        and body['capability']==cap and body['context']==execution['input_content_utf8']
        and event['submitted_request_sha256']==sha(canonical(body))
        and event['registry_sha256']==registry_sha256 and event['durable_action_delivery'] is True,
        'CONTRACT_REVIEW_REQUEST_DRIFT')
    require(canonical(execution['artifact_metadata'])==canonical(dispatch['artifact']),
        'CONTRACT_REVIEW_OUTPUT_METADATA')
    began=_utc(event['started_at']);ended=_utc(event['completed_at']);created=_utc(event['original_task_created_at'])
    require(created<=began<=ended and (ended-created).total_seconds()<=5
        and ended<=datetime.now(timezone.utc),'CONTRACT_REVIEW_ORIGINAL_TIME')
    input_raw=execution['input_content_utf8'].encode();result_raw=execution['artifact_content_utf8'].encode()
    require(0<len(input_raw)<=65536 and 0<len(result_raw)<=65536,'CONTRACT_REVIEW_ARTIFACT_BOUND')
    original_rows=execution['original_action_records'];require(type(original_rows) is list and len(original_rows)==6,
        'CONTRACT_REVIEW_SIX_ROWS_REQUIRED')
    for repeat in range(2):
        require(time.monotonic()<deadline and canonical(execution)==frozen,'CONTRACT_REVIEW_BUDGET_OR_DRIFT')
        registry_raw=_registry_original(registry_sha256)
        expected=independent_report(input_raw,registry_raw,task_id=task,agent_id=actor,capability_id=cap)
        require(canonical(expected)==result_raw,'CONTRACT_REVIEW_INDEPENDENT_ORACLE_REJECTED')
        receipt=read_task(_path(root),task,body,runtime,deadline=deadline,completed=dispatch,actor=actor)
        require(receipt['created_at']==event['original_task_created_at'],'CONTRACT_REVIEW_TASK_TIME')
        for metadata,raw in ((event['input_artifact_metadata'],input_raw),(dispatch['artifact'],result_raw)):
            require(metadata['task_id']==task and metadata['creator_agents']==[actor]
                and metadata['runtime_revision']==runtime['source_revision'] and metadata['type']=='json'
                and metadata['sha256']==sha(raw) and metadata['bytes']==len(raw),
                'CONTRACT_REVIEW_ARTIFACT_OWNER')
            actual,content=retrieve_original_artifact(_path(root),metadata['artifact_id'])
            require(canonical(actual)==canonical(metadata) and content==raw,'CONTRACT_REVIEW_ORIGINAL_ARTIFACT_CHANGED')
        lines=_ledger_lines(_path(root));selected=[line for line in lines if parse(line.encode()).get('task_id')==task]
        require(selected==original_rows,'CONTRACT_REVIEW_NATIVE_ACTION_DRIFT')
        rows=[parse(line.encode()) for line in original_rows]
        for step,tool in (('setup','action.propose'),('read','provided_context.read'),('result','action.propose')):
            pair=[row for row in rows if row['action_type']=='agent.certification.owned_contract.'+step]
            require(len(pair)==2 and [row['phase'] for row in pair]==['started','completed']
                and pair[1].get('success') is True and pair[1].get('error') is None
                and all(row['action_id']==event['action_ids'][step] and row['agent_id']==actor
                    and row['task_id']==task and row['tool']==tool for row in pair),
                'CONTRACT_REVIEW_ACTION_OWNER')
            common=dict(case=CASE,case_version=VERSION,capability_id=cap,registry_sha256=registry_sha256,
                submitted_request_sha256=sha(canonical(body)),read_only_observations=True)
            if step=='setup':common['content_sha256']=sha(input_raw)
            elif step=='read':common.update(setup_artifact_id=event['input_artifact_metadata']['artifact_id'],
                expected_sha256=sha(input_raw),relative_path='artifact.json')
            else:common['input_sha256']=sha(input_raw)
            require(all(row['target']=='artifact.json' and canonical(row['parameters_summary'])==canonical(common)
                and began<=_utc(row['timestamp'])<=ended for row in pair),'CONTRACT_REVIEW_ACTION_PARAMETERS')
            summary=pair[1]['result_summary']
            if step=='read':require(summary.get('source_sha256')==sha(input_raw),'CONTRACT_REVIEW_READ_HASH')
            else:
                metadata=event['input_artifact_metadata'] if step=='setup' else dispatch['artifact']
                require(summary.get('artifact_id')==metadata['artifact_id'] and summary.get('sha256')==metadata['sha256'],
                    'CONTRACT_REVIEW_ACTION_ARTIFACT_JOIN')
        for index,row in enumerate(rows):
            require(type(row['sequence']) is int and row['sequence']>0
                and sha(canonical({k:v for k,v in row.items() if k!='sha256'}))==row['sha256'],
                'CONTRACT_REVIEW_ACTION_HASH')
            if index:require(row['sequence']==rows[index-1]['sequence']+1
                and row['previous_sha256']==rows[index-1]['sha256'],'CONTRACT_REVIEW_ACTION_CHAIN')
        require(time.monotonic()<deadline,'CONTRACT_REVIEW_BUDGET_EXHAUSTED')
    return expected


def validate_execution(execution,*,source_revision,runtime_image_id,registry_sha256,now):
    """Host observer: independent original-byte oracle, not native-store proof."""
    require(type(now) is datetime and now.tzinfo is not None,'CONTRACT_REVIEW_CLOCK')
    require(type(execution) is dict and set(execution)=={'case_spec','submitted_request','runtime',
        'runtime_after','runtime_current','submission','dispatch','artifact_metadata',
        'artifact_content_utf8','input_content_utf8','objective_read','original_action_records','observation'},
        'CONTRACT_REVIEW_EXECUTION_FIELDS')
    require(len(canonical(execution))<=262144,'CONTRACT_REVIEW_EXECUTION_BOUND')
    runtime=execution['runtime']
    require(type(runtime) is dict and set(runtime)=={'host_id','source_revision','version','image_digest'}
        and runtime['source_revision']==source_revision and runtime['image_digest']==runtime_image_id
        and all(canonical(execution[k])==canonical(runtime) for k in ('runtime_after','runtime_current')),
        'CONTRACT_REVIEW_RUNTIME_DRIFT')
    dispatch=execution['dispatch'];actor=dispatch['agent_id'];cap=dispatch['capability'];task=dispatch['task_id']
    require(actor!='a19' and dispatch['state']=='COMPLETED' and type(dispatch['model_calls']) is int
        and dispatch['model_calls']==0 and dispatch['execution_model']=='DETERMINISTIC'
        and dispatch['runtime_source_revision']==source_revision,'CONTRACT_REVIEW_DISPATCH')
    body=execution['submitted_request'];spec=execution['case_spec'];event=dispatch['owned_contract_event']
    require(set(spec)=={'case','case_version','agent_id','capability_id','request','certification','scope'}
        and spec['case']==CASE and spec['case_version']==VERSION and spec['agent_id']==actor
        and spec['capability_id']==cap and spec['certification']=='UNVERIFIED' and spec['scope']=='STRUCTURAL_INSPECTION_ONLY'
        and canonical(spec['request'])==canonical(body) and body['capability']==cap
        and body['objective']=='Check the supplied input and proposed output against the registered contracts.'
        and body['data_classification']=='LOCAL_ONLY' and body['max_cost_usd']==0
        and body['deterministic_operation']=='certification_owned_contract'
        and body['context']==execution['input_content_utf8'],'CONTRACT_REVIEW_REQUEST_DRIFT')
    require(event['case']==CASE and event['case_version']==VERSION and event['registry_sha256']==registry_sha256
        and event['submitted_request_sha256']==sha(canonical(body)) and event['durable_action_delivery'] is True,
        'CONTRACT_REVIEW_EVENT_DRIFT')
    created=_utc(event['original_task_created_at']);began=_utc(event['started_at']);ended=_utc(event['completed_at'])
    require(created<=began<=ended<=now and (ended-created).total_seconds()<=5,'CONTRACT_REVIEW_ORIGINAL_TIME')
    observed=execution['observation']
    require(type(observed) is dict and set(observed)=={'started_at','completed_at'}
        and _utc(observed['started_at'])<=created and ended<=_utc(observed['completed_at'])<=now
        and 0<=(_utc(observed['completed_at'])-_utc(observed['started_at'])).total_seconds()<=5,
        'CONTRACT_REVIEW_OBSERVATION_TIME')
    require(type(execution['input_content_utf8']) is str and type(execution['artifact_content_utf8']) is str,
        'CONTRACT_REVIEW_ORIGINAL_BYTES')
    input_raw=execution['input_content_utf8'].encode();output_raw=execution['artifact_content_utf8'].encode()
    require(0<len(input_raw)<=65536 and 0<len(output_raw)<=65536,'CONTRACT_REVIEW_ARTIFACT_BOUND')
    expected=independent_report(input_raw,_registry_original(registry_sha256),task_id=task,
        agent_id=actor,capability_id=cap)
    require(canonical(expected)==output_raw,'CONTRACT_REVIEW_INDEPENDENT_ORACLE_REJECTED')
    require(canonical(execution['artifact_metadata'])==canonical(dispatch['artifact']),
        'CONTRACT_REVIEW_OUTPUT_METADATA')
    for metadata,raw in ((event['input_artifact_metadata'],input_raw),(dispatch['artifact'],output_raw)):
        require(metadata['task_id']==task and metadata['creator_agents']==[actor]
            and metadata['type']=='json' and metadata['runtime_revision']==source_revision
            and metadata['sha256']==sha(raw) and metadata['bytes']==len(raw)
            and metadata['provenance']=='Deterministic computation; zero model calls'
            and metadata['version']=='1.0.0' and metadata['location']=='artifact.json'
            and metadata['delivery_state']=='AVAILABLE' and began<=_utc(metadata['timestamp'])<=ended,
            'CONTRACT_REVIEW_ARTIFACT_OWNER')
    require(type(execution['objective_read']) in (tuple,list) and len(execution['objective_read'])==2
        and execution['objective_read'][0]==200,'CONTRACT_REVIEW_OBJECTIVE_REQUIRED')
    objective=execution['objective_read'][1];meta=objective['execution_metadata']
    require(objective['id']==task and objective['state']=='COMPLETED' and objective['revision']==0
        and canonical(objective['steps'])==canonical([dict(capability=cap,dispatch=dispatch,revision=0,state='completed')])
        and meta['authoritative'] is True and canonical(meta['runtime'])==canonical(runtime)
        and meta['task_id']==task and meta['created_at']==event['original_task_created_at']
        and _utc(meta['updated_at'])<=now and meta['jobs']==[] and meta['agent_execution']==[],
        'CONTRACT_REVIEW_ORIGINAL_OBJECTIVE_UNBOUND')
    submission=execution['submission']
    require(type(submission) in (list,tuple) and len(submission)==2 and submission[0]==202
        and submission[1]['id']==task and len(submission[1]['steps'])==1
        and canonical(submission[1]['steps'][0]['dispatch'])==canonical(dispatch),
        'CONTRACT_REVIEW_SUBMISSION_UNBOUND')
    lines=execution['original_action_records'];require(type(lines) is list and len(lines)==6,
        'CONTRACT_REVIEW_SIX_ROWS_REQUIRED')
    rows=[parse(line.encode()) for line in lines]
    for index,row in enumerate(rows):
        require(type(row['sequence']) is int and row['sequence']>0 and row['task_id']==task
            and row['agent_id']==actor and sha(canonical({k:v for k,v in row.items() if k!='sha256'}))==row['sha256'],
            'CONTRACT_REVIEW_ACTION_HASH')
        if index:require(row['sequence']==rows[index-1]['sequence']+1
            and row['previous_sha256']==rows[index-1]['sha256'],'CONTRACT_REVIEW_ACTION_CHAIN')
    for step,tool in (('setup','action.propose'),('read','provided_context.read'),('result','action.propose')):
        pair=[row for row in rows if row['action_type']=='agent.certification.owned_contract.'+step]
        require(len(pair)==2 and [r['phase'] for r in pair]==['started','completed']
            and pair[1].get('success') is True and pair[1].get('error') is None
            and all(row['action_id']==event['action_ids'][step] and row['tool']==tool
                and row['target']=='artifact.json' and began<=_utc(row['timestamp'])<=ended for row in pair),
            'CONTRACT_REVIEW_ACTION_OWNER')
        common=dict(case=CASE,case_version=VERSION,capability_id=cap,registry_sha256=registry_sha256,
            submitted_request_sha256=sha(canonical(body)),read_only_observations=True)
        if step=='setup':common['content_sha256']=sha(input_raw)
        elif step=='read':common.update(setup_artifact_id=event['input_artifact_metadata']['artifact_id'],
            expected_sha256=sha(input_raw),relative_path='artifact.json')
        else:common['input_sha256']=sha(input_raw)
        require(all(canonical(row['parameters_summary'])==canonical(common) for row in pair),
            'CONTRACT_REVIEW_ACTION_PARAMETERS')
        summary=pair[1]['result_summary']
        if step=='read':require(summary.get('source_sha256')==sha(input_raw),'CONTRACT_REVIEW_READ_HASH')
        else:
            metadata=event['input_artifact_metadata'] if step=='setup' else dispatch['artifact']
            require(summary.get('artifact_id')==metadata['artifact_id'] and summary.get('sha256')==metadata['sha256'],
                'CONTRACT_REVIEW_ACTION_ARTIFACT_JOIN')
    return expected


def validate_reviewed_execution(execution,peer,*,source_revision,runtime_image_id,registry_sha256,now):
    joined=validate_execution(execution,source_revision=source_revision,runtime_image_id=runtime_image_id,
        registry_sha256=registry_sha256,now=now)
    require(type(peer) is dict and set(peer)=={'submitted_request','runtime','runtime_after','runtime_current',
        'submission','dispatch','artifact_metadata','artifact_content_utf8','objective_read',
        'original_action_records','observation'},'CONTRACT_REVIEW_PEER_FIELDS')
    runtime=execution['runtime'];subject=execution['dispatch'];actor,cap=('a18','responsibility.a27') if subject['agent_id']=='a26' else ('a26','responsibility.a26')
    require(all(canonical(peer[key])==canonical(runtime) for key in ('runtime','runtime_after','runtime_current')),
        'CONTRACT_REVIEW_PEER_RUNTIME')
    dispatch=peer['dispatch'];task=dispatch['task_id'];event=dispatch['owned_contract_review']
    require(task!=subject['task_id'] and dispatch['state']=='COMPLETED' and dispatch['agent_id']==actor
        and dispatch['capability']==cap and dispatch['model_calls']==0 and type(dispatch['model_calls']) is int
        and dispatch['execution_model']=='DETERMINISTIC' and dispatch['runtime_source_revision']==source_revision,
        'CONTRACT_REVIEW_FIXED_DISTINCT_PEER')
    body=peer['submitted_request'];context=parse(body['context'].encode(),80000)
    require(set(context)=={'execution','execution_sha256','nonce'}
        and canonical(context['execution'])==canonical(execution)
        and context['execution_sha256']==sha(canonical(execution)),'CONTRACT_REVIEW_PEER_CONTEXT')
    from .agent_cert_artifact_events import _uuid
    require(_uuid(context['nonce']) and _uuid(task),'CONTRACT_REVIEW_PEER_UUID')
    expected_body=dict(capability=cap,objective='Independently inspect original registered-contract structural evidence for '+subject['agent_id']+'/'+subject['capability']+'. Do not certify or sign.',
        context=body['context'],classification='R0',data_classification='LOCAL_ONLY',minimum_tier='NANO',
        priority='low',task_class='classification',max_cost_usd=0.0,preferred_provider=None,
        response_format='strict_json',deterministic_operation='certification_owned_contract_review')
    require(canonical(body)==canonical(expected_body),'CONTRACT_REVIEW_PEER_REQUEST')
    expected=dict(schema_version='prime.owned-contract-review.v1',case=CASE,case_version=VERSION,
        task_id=task,agent_id=actor,capability_id=cap,subject_task_id=subject['task_id'],
        subject_agent_id=subject['agent_id'],subject_capability_id=subject['capability'],
        execution_sha256=sha(canonical(execution)),original_join=joined,
        grade_scope='STRUCTURAL_INSPECTION_ONLY',prose_semantics='NOT_ESTABLISHED',
        role_result_quality='NOT_ESTABLISHED',certification='UNVERIFIED')
    raw=peer['artifact_content_utf8'].encode();metadata=peer['artifact_metadata']
    require(0<len(raw)<=65536 and raw==canonical(expected)
        and canonical(metadata)==canonical(dispatch['artifact']) and metadata['task_id']==task
        and metadata['creator_agents']==[actor] and metadata['type']=='json'
        and metadata['runtime_revision']==source_revision and metadata['sha256']==sha(raw)
        and metadata['bytes']==len(raw),'CONTRACT_REVIEW_PEER_ARTIFACT')
    created=_utc(event['original_task_created_at']);began=_utc(event['started_at']);ended=_utc(event['completed_at'])
    require(created<=began<=_utc(metadata['timestamp'])<=ended<=now and (ended-created).total_seconds()<=5
        and event['durable_action_delivery'] is True and event['certification']=='UNVERIFIED'
        and _utc(execution['dispatch']['owned_contract_event']['completed_at'])<=created,
        'CONTRACT_REVIEW_PEER_TIME')
    view=peer['objective_read'];require(type(view) in (list,tuple) and len(view)==2 and view[0]==200,
        'CONTRACT_REVIEW_PEER_OBJECTIVE')
    objective=view[1];meta=objective['execution_metadata']
    require(objective['id']==task and objective['state']=='COMPLETED' and objective['revision']==0
        and canonical(objective['steps'])==canonical([dict(capability=cap,dispatch=dispatch,revision=0,state='completed')])
        and meta['authoritative'] is True and canonical(meta['runtime'])==canonical(runtime)
        and meta['created_at']==event['original_task_created_at'] and _utc(meta['updated_at'])<=now
        and meta['jobs']==[] and meta['agent_execution']==[],'CONTRACT_REVIEW_PEER_OBJECTIVE_UNBOUND')
    submission=peer['submission'];require(len(submission)==2 and submission[0]==202
        and submission[1]['id']==task and len(submission[1]['steps'])==1
        and canonical(submission[1]['steps'][0]['dispatch'])==canonical(dispatch),
        'CONTRACT_REVIEW_PEER_SUBMISSION')
    observation=peer['observation']
    require(_utc(observation['started_at'])<=created and ended<=_utc(observation['completed_at'])<=now
        and 0<=(_utc(observation['completed_at'])-_utc(observation['started_at'])).total_seconds()<=5,
        'CONTRACT_REVIEW_PEER_OBSERVATION')
    lines=peer['original_action_records'];require(type(lines) is list and len(lines)==2,'CONTRACT_REVIEW_PEER_ROWS')
    rows=[parse(line.encode()) for line in lines]
    require([row['phase'] for row in rows]==['started','completed'] and rows[1].get('success') is True
        and rows[1].get('error') is None,'CONTRACT_REVIEW_PEER_ACTION_STATE')
    parameters=dict(case=CASE,case_version=VERSION,subject_task_id=subject['task_id'],
        execution_sha256=sha(canonical(execution)),registry_sha256=registry_sha256,
        submitted_request_sha256=sha(canonical(body)),read_only_observations=True)
    for row in rows:
        require(row['task_id']==task and row['agent_id']==actor
            and row['action_type']=='agent.certification.owned_contract.review'
            and row['action_id']==event['action_id'] and row['tool']=='action.propose'
            and row['target']=='artifact.json' and canonical(row['parameters_summary'])==canonical(parameters)
            and began<=_utc(row['timestamp'])<=ended
            and sha(canonical({k:v for k,v in row.items() if k!='sha256'}))==row['sha256'],
            'CONTRACT_REVIEW_PEER_ACTION_BINDING')
    require(rows[1]['sequence']==rows[0]['sequence']+1 and rows[1]['previous_sha256']==rows[0]['sha256']
        and rows[1]['result_summary']['artifact_id']==metadata['artifact_id']
        and rows[1]['result_summary']['sha256']==metadata['sha256'],'CONTRACT_REVIEW_PEER_ACTION_CHAIN')
    return expected
