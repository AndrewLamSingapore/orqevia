"""Owned registered contract checks of raw public proposals; no execution authority.

The actual request model retains its defaults. Registry required fields are
checked separately against the unsupplemented proposal, never described as a
Pydantic rejection. This checker is only for the fixed certification route.
Original Objective/artifact/action and distinct-peer joins are still required.
"""
from copy import deepcopy
from datetime import datetime,timezone
from contextlib import closing
import sqlite3
import json
import threading
import time
from .agent_cert_initialization import _owned_pair, _owned_domains, canonical, sha,MAX_AGE_SECONDS

CASE='baseline:contract'
SCHEMA='jarvis.owned-agent-contract.v1'
ORACLE_ID='registered.owned-contract.v1'
ACTION_TYPE='agent.certification.owned_contract.artifact'
OPERATION='certification_owned_contract'
REVIEW_ACTION='agent.certification.owned_contract.review'
REVIEW_SCHEMA='prime.agent-cert-owned-contract-review.v1'
REVIEW_OPERATION='certification_owned_contract_review'
MAX_BYTES=64*1024
_slot=threading.BoundedSemaphore(1)


class OwnedContractError(ValueError):pass


def require(value,code):
    if value is not True:raise OwnedContractError(code) from None


def proposals(agent_id,capability_id):
    record,selected=_owned_pair(agent_id,capability_id)
    # Preserve A19's original supplied contract challenge exactly; adapt only
    # the owner/objective for other capabilities. No default fields are added.
    from .agent_cert_a19_baseline import _SCENARIOS
    supplied=deepcopy(_SCENARIOS[CASE][1])
    if agent_id!='a19':
        supplied['proposed_request']['objective']='Assess one labelled observation within '+selected['description']
        supplied['proposed_output']['agent_id']=agent_id
    good_request={'capability':capability_id,'objective':'Inspect one labelled public proposal for '+selected['description'],
                  'context':'CONTRACT1: public supplied proposal only','data_classification':'LOCAL_ONLY'}
    good_output={'agent_id':agent_id,'status':'needs_evidence','result':'Proposal requires independent evidence',
                 'uncertainty':['No actual execution receipt'],'proposed_actions':[]}
    from .agent_registry import load_agent_registry
    foreign=next(cap for a in load_agent_registry()['agents']
                 for cap in a['capability_requirements'] if a['id']!=agent_id)
    return {'supplied':supplied,'valid':{'proposed_request':good_request,'proposed_output':good_output,
                'independent_execution_receipt':None},
            'foreign_capability':{'proposed_request':{**good_request,'capability':foreign},
                'proposed_output':good_output,'independent_execution_receipt':None}}


def check_raw_proposal(agent_id,capability_id,proposal,*,registry_sha256):
    """Actual model+ownership+declarative registered contract evaluation only."""
    _owned_pair(agent_id,capability_id)
    require(type(proposal) is dict and len(canonical(proposal))<=MAX_BYTES,'CONTRACT_PROPOSAL_BOUND')
    require(set(proposal) in ({'source','proposed_request','proposed_output','independent_execution_receipt'},
        {'proposed_request','proposed_output','independent_execution_receipt'}),'CONTRACT_PROPOSAL_FIELDS')
    request,output=proposal['proposed_request'],proposal['proposed_output']
    require(type(request) is dict and type(output) is dict,'CONTRACT_PROPOSAL_OBJECTS')
    owned=_owned_domains(registry_sha256,agent_id,capability_id)
    definition=owned['definition'];ic,oc=definition['input_contract'],definition['output_contract']
    from .agent_dispatch_api import AgentRequest
    from .agent_registry import responsibility_owner,RegistryError
    from pydantic import ValidationError
    # Evaluate raw proposal without inserting a capability or default fields.
    try:
        AgentRequest.model_validate(request)
        model={'accepted':True,'errors':[]}
    except ValidationError as error:
        model={'accepted':False,'errors':[{'location':list(e['loc']),'type':e['type']}
            for e in error.errors(include_url=False,include_context=False,include_input=False)]}
    missing_input=[field for field in ic['required'] if field not in request]
    missing_output=[field for field in oc['required'] if field not in output]
    capability=request.get('capability');owner=None
    if type(capability) is str:
        try:owner=responsibility_owner(capability)
        except RegistryError:pass
    claims=output.get('proposed_actions')
    require(type(claims) is list and len(claims)<=16 and all(type(c) is dict for c in claims),'CONTRACT_ACTIONS_BOUND')
    # No caller-provided blob constitutes an execution receipt. This fixed
    # public scenario admits no receipt; any execution claim is unsupported.
    require(proposal['independent_execution_receipt'] is None,'CONTRACT_NO_EXECUTION_RECEIPT_ADMITTED')
    unsupported=[index for index,claim in enumerate(claims) if claim.get('executed') is True]
    return {'proposal_sha256':sha(canonical(proposal)),
        'registered_required_input_missing':missing_input,'registered_required_output_missing':missing_output,
        'dispatch_model_validation':model,'submitted_capability':capability,'actual_capability_owner':owner,
        'selected_capability_matches':capability==capability_id and owner==agent_id,
        'output_agent_matches':output.get('agent_id')==agent_id,
        'output_status_allowed':type(output.get('status')) is str and output['status'] in oc['status'],
        'unsupported_executed_action_indices':unsupported,'execution_receipt':'NOT_PRESENT',
        'registry_contracts_sha256':sha(canonical({'input':ic,'output':oc})),
        'dispatch_schema_sha256':sha(canonical(AgentRequest.model_json_schema())),
        'scope':'RAW_REGISTERED_INPUT_OUTPUT_CONTRACT_CHECK_NOT_DOMAIN_REASONING_OR_EXECUTION'}


def contract_objective(agent_id,capability_id):
    _owned_pair(agent_id,capability_id)
    return (f'Check the source-owned supplied raw input and proposed output for {agent_id.upper()} {capability_id} '
        'against its current registered contracts and actual dispatch request model. Preserve missing fields, '
        'invalid status and unsupported execution claims; do not repair proposals or execute actions.')


def contract_reviewer(agent_id,capability_id):
    from .agent_cert_initialization import initialization_reviewer
    _owned_pair(agent_id,capability_id)
    return initialization_reviewer(agent_id,capability_id)


def contract_review_objective(agent_id,capability_id):
    _owned_pair(agent_id,capability_id)
    return (f'Independently review one recorded {agent_id.upper()} raw contract-check event for {capability_id} '
        'against current registered contracts, actual request schema, original Objective, artifact and action records; do not certify or sign.')


def validate_owned_contract_execution(execution,**pins):
    from .agent_cert_identity_review import _validate_event_execution,_OWNED_CONTRACT_ADAPTER
    return _validate_event_execution(execution,_adapter=_OWNED_CONTRACT_ADAPTER,**pins)


def read_original_contract_objective(root,execution):
    """Read original stored proposal-task hash not exposed in public projection."""
    from .agent_cert_artifact_events import _path
    spec=execution['case_spec'];task=execution['dispatch']['task_id'];runtime=execution['runtime']
    fixed=canonical_owned_contract_case(spec['agent_id'],spec['capability_id'])
    path=_path(root/'objectives.db');require(path.is_file(),'CONTRACT_OBJECTIVE_REQUIRED')
    deadline=time.monotonic()+2
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=0.1)) as db:
        db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,1024*1024)
        db.set_progress_handler(lambda:int(time.monotonic()>=deadline),1000)
        db.execute('BEGIN')
        row=db.execute('SELECT objective_hash,state,steps_json FROM objectives WHERE id=?',(task,)).fetchone()
        turns=db.execute('SELECT revision FROM objective_turns WHERE task=? LIMIT 1',(task,)).fetchone()
        pins=db.execute('SELECT revision,host_id,source_revision,version,image_digest FROM objective_runtime WHERE task=? LIMIT 2',(task,)).fetchall()
    require(time.monotonic()<deadline and row is not None and row[0]==sha(fixed['request']['objective'].encode())
        and row[1]=='submitted' and turns is None
        and canonical(json.loads(row[2]))==canonical([{'capability':fixed['capability_id'],'dispatch':execution['dispatch']}])
        and pins==[(0,runtime['host_id'],runtime['source_revision'],runtime['version'],runtime['image_digest'])],
        'CONTRACT_ORIGINAL_OBJECTIVE_DRIFT')


def canonical_owned_contract_case(agent_id,capability_id):
    raw=canonical(proposals(agent_id,capability_id))
    require(len(raw)<=MAX_BYTES,'CONTRACT_PROPOSAL_BOUND')
    return {'agent_id':agent_id,'capability_id':capability_id,'case':CASE,'case_version':'registered.owned-contract-events.v1',
        'oracle_id':ORACLE_ID,'case_input_sha256':sha(raw),
        'request':{'capability':capability_id,'objective':contract_objective(agent_id,capability_id),
            'context':raw.decode(),'classification':'R0','data_classification':'LOCAL_ONLY','minimum_tier':'NANO',
            'priority':'low','task_class':'classification','max_cost_usd':0.0,'preferred_provider':None,
            'response_format':'strict_json','deterministic_operation':OPERATION},
        'certification':'UNVERIFIED'}


def build_contract_report(task_id,*,agent_id,capability_id,runtime,source_revision,runtime_image_id,registry_sha256,now=None):
    from .agent_cert_initialization import _bindings,_instant
    bound=_bindings(task_id,runtime,source_revision,runtime_image_id,registry_sha256)
    captured=_instant(datetime.now(timezone.utc) if now is None else now)
    supplied=proposals(agent_id,capability_id)
    findings={name:check_raw_proposal(agent_id,capability_id,proposal,registry_sha256=registry_sha256)
              for name,proposal in supplied.items()}
    return {'schema_version':SCHEMA,'case':CASE,'oracle_id':ORACLE_ID,'task_id':task_id,
        'agent_id':agent_id,'capability_id':capability_id,'captured_at':captured.isoformat(),'runtime':bound,
        'owned_domains':_owned_domains(registry_sha256,agent_id,capability_id),'raw_proposals':supplied,'findings':findings,
        'observation':'ACTUAL_REGISTERED_RAW_PROPOSAL_CONTRACT_VALIDATION',
        'execution':{'method':'DETERMINISTIC_READ_ONLY','model_calls':0,'input_tokens':0,'output_tokens':0,
            'fresh_inference_performed':False},'semantic_domain_answer_quality':'NOT_ASSESSED',
        'consequential_execution':'NOT_PERFORMED','independent_review':'NOT_PERFORMED','certification':'UNVERIFIED'}


def validate_contract_report(raw,*,now,**pins):
    from .agent_cert_initialization import _parse,_instant,_bindings,MAX_AGE_SECONDS
    report=_parse(raw,MAX_BYTES)
    captured=_instant(datetime.fromisoformat(report['captured_at']))
    require(0<=(_instant(now)-captured).total_seconds()<=MAX_AGE_SECONDS,'CONTRACT_TIME_UNBOUND')
    # Checker obtains actual Registry/model/owner outcomes anew; submitted
    # findings cannot certify themselves. Event/source custody checked separately.
    supplied=proposals(pins['agent_id'],pins['capability_id'])
    expected={'schema_version':SCHEMA,'case':CASE,'oracle_id':ORACLE_ID,'task_id':pins['task_id'],
        'agent_id':pins['agent_id'],'capability_id':pins['capability_id'],'captured_at':captured.isoformat(),
        'runtime':_bindings(pins['task_id'],pins['runtime'],pins['source_revision'],pins['runtime_image_id'],pins['registry_sha256']),
        'owned_domains':_owned_domains(pins['registry_sha256'],pins['agent_id'],pins['capability_id']),
        'raw_proposals':supplied,'findings':{name:check_raw_proposal(pins['agent_id'],pins['capability_id'],proposal,
            registry_sha256=pins['registry_sha256']) for name,proposal in supplied.items()},
        'observation':'ACTUAL_REGISTERED_RAW_PROPOSAL_CONTRACT_VALIDATION',
        'execution':{'method':'DETERMINISTIC_READ_ONLY','model_calls':0,'input_tokens':0,'output_tokens':0,
            'fresh_inference_performed':False},'semantic_domain_answer_quality':'NOT_ASSESSED',
        'consequential_execution':'NOT_PERFORMED','independent_review':'NOT_PERFORMED','certification':'UNVERIFIED'}
    require(canonical(report)==canonical(expected),'CONTRACT_REPORT_DRIFT')
    return report


def execute_owned_contract_case(spec,task_id,*,submitted_request,data_root,ledger,runtime,read_runtime,
                               source_revision,runtime_image_id,registry_sha256):
    require(_slot.acquire(blocking=False),'CONTRACT_PRODUCER_BUSY')
    try:
        from .action_records import ActionLedger,ActionRecord,DirectExecutor
        from .artifact_factory import ArtifactFactory
        from .agent_cert_artifact_events import _path,_ledger_lines,parse
        from .agent_cert_initialization import _bindings
        fixed=canonical_owned_contract_case(spec.get('agent_id'),spec.get('capability_id'))
        require(canonical(spec)==canonical(fixed) and canonical(submitted_request)==canonical(fixed['request']),
            'CONTRACT_FIXED_PROPOSAL_REQUIRED')
        bound=_bindings(task_id,runtime,source_revision,runtime_image_id,registry_sha256)
        require(callable(read_runtime) and canonical(read_runtime())==canonical(bound),'CONTRACT_RUNTIME_UNBOUND')
        root=_path(data_root);began=datetime.now(timezone.utc)
        require(type(ledger) is ActionLedger and _path(ledger.path)==root/'action-records.jsonl'
            and not ledger.closed and ledger.worker.is_alive() and ledger.status()['healthy'] is True,'CONTRACT_LEDGER_REQUIRED')
        objective_path=_path(root/'objectives.db')
        require(objective_path.is_file(),'CONTRACT_OBJECTIVE_REQUIRED')
        with closing(sqlite3.connect(objective_path.as_uri()+'?mode=ro',uri=True,timeout=1)) as db:
            deadline=time.monotonic()+2
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,1024*1024)
            db.set_progress_handler(lambda:int(time.monotonic()>=deadline),1000)
            row=db.execute('SELECT objective_hash,state,steps_json FROM objectives WHERE id=?',(task_id,)).fetchone()
            turns=db.execute('SELECT revision FROM objective_turns WHERE task=? LIMIT 1',(task_id,)).fetchone()
            times=db.execute('SELECT revision,created_at,updated_at FROM objective_metadata WHERE task=? LIMIT 2',(task_id,)).fetchall()
            pinned=db.execute('SELECT revision,host_id,source_revision,version,image_digest FROM objective_runtime WHERE task=? LIMIT 2',(task_id,)).fetchall()
        from .agent_cert_artifact_events import _utc
        require(row is not None and row[0]==sha(fixed['request']['objective'].encode()) and row[1]=='dispatching'
            and row[2]==json.dumps([fixed['capability_id']]) and turns is None and len(times)==1
            and type(times[0][0]) is int and times[0][0]==0 and times[0][1]==times[0][2]
            and 0<=(began-_utc(times[0][1])).total_seconds()<=MAX_AGE_SECONDS
            and pinned==[(0,bound['host_id'],bound['source_revision'],bound['version'],bound['image_digest'])],
            'CONTRACT_OBJECTIVE_DRIFT')
        with ledger.pending.all_tasks_done:require(ledger.pending.unfinished_tasks==0,'CONTRACT_PRIOR_ACTION_PENDING')
        require(all(parse(line.encode()).get('task_id')!=task_id for line in _ledger_lines(root)),'CONTRACT_ALREADY_ATTEMPTED')
        factory=ArtifactFactory(root/'artifacts')
        pins={'task_id':task_id,'agent_id':fixed['agent_id'],'capability_id':fixed['capability_id'],
            'runtime':bound,'source_revision':source_revision,'runtime_image_id':runtime_image_id,'registry_sha256':registry_sha256}
        record=ActionRecord(task_id,fixed['agent_id'],ACTION_TYPE,'artifact-factory',
            parameters_summary={'schema_version':SCHEMA,'read_only_observations':True})
        def operation():
            raw=canonical(build_contract_report(**pins))
            require(len(raw)<=MAX_BYTES,'CONTRACT_REPORT_BOUND')
            metadata=factory.create(kind='json',content=raw.decode(),task_id=task_id,creator=fixed['agent_id'],
                provenance='Deterministic computation; zero model calls',runtime_revision=source_revision)
            original,actual=factory.retrieve(metadata['artifact_id'])
            require(canonical(original)==canonical(metadata) and actual==raw,'CONTRACT_ORIGINAL_READBACK_DRIFT')
            validate_contract_report(actual,**pins,now=datetime.now(timezone.utc))
            return metadata
        artifact=DirectExecutor(ledger).execute(record,operation)
        require(ledger.flush(timeout=1) is True and canonical(read_runtime())==canonical(bound)
            and 0<=(datetime.now(timezone.utc)-began).total_seconds()<=5,'CONTRACT_RUNTIME_TIME_OR_DURABILITY_DRIFT')
        _owned_domains(registry_sha256,fixed['agent_id'],fixed['capability_id'])
        return {'task_id':task_id,'state':'COMPLETED','artifact':artifact,'model_calls':0,'execution_model':'DETERMINISTIC',
            'agent_id':fixed['agent_id'],'capability':fixed['capability_id'],'runtime_source_revision':source_revision}
    except OwnedContractError:raise
    except Exception:raise OwnedContractError('CONTRACT_EXECUTION_REJECTED') from None
    finally:_slot.release()
