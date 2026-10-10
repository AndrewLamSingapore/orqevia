"""Two bounded supplied-at-execution cases; no scenario or answer fallback.

Source custodian exercises are explicitly synthetic. Original task/artifact
custody does not prove a live challenge was previously unknown to an agent.
"""
from datetime import datetime, timezone
from contextlib import closing
import json
import re
import sqlite3
import time
import math
import threading

from .agent_cert_artifact_events import canonical, parse, sha, _path, _utc, _uuid, _ledger_lines
from .agent_cert_tool_events import require, independent_verifier_binding, _events
from .agent_cert_clean_room import case_remaining

CASES = ('fresh_challenge:complete','unseen_task:complete')
STAGES = ('custodian','source','audit','comparison')
SCHEMAS = {stage:'prime.execution-input.'+stage+'.v1' for stage in STAGES}
OPERATION = 'certification_tool_review'
MAX_INPUT = 65536
LABEL = 'PUBLIC_SYNTHETIC_EXECUTION_INPUT'
CASE_VERSION = 'a19.supplied-execution-input.v1'
ORACLE_ID = 'a26.original-supplied-input-blind-comparison.v1'
REVIEW_SCHEMA = 'prime.supplied-execution-input.original-review.v1'
OBJECTIVES = {
    'custodian':'Materialize only the newly supplied labelled synthetic execution input after the original A19 initialization completes. Supply no prior assessment or expected answer. This is an input custodian task, not case grading, service observation, authority, model execution, signing or certification.',
    'source':'Assess only the newly supplied synthetic service or held-out dependency failure received after original initialization. Read the original execution input once, derive observations and uncertainty, and propose one bounded read-only check. Do not rely on prior answer text, claim current service health, execute a proposed action, use a model or certify.',
    'audit':'Independently calculate a conclusion from only the original newly supplied execution input. Receive no prior A19 assessment, answer artifact identifier or expected answer digest. Seal this separate input-only calculation before any comparison. Do not execute, confirm current health, use a model, transfer authority, sign or certify.',
    'comparison':'Independently compare the original supplied-at-execution input, original A19 assessment and already sealed input-only A26 calculation. Reopen original tasks, artifacts and actions twice. Grade only original bounded synthetic custody and arithmetic/topology; no current health confirmation, model, authority, signing or certification.',
}
_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z')
_slot = threading.BoundedSemaphore(1)


def canonical_case(case):
    require(case in CASES,'EXECUTION_INPUT_CASE_UNSUPPORTED')
    # This is a non-executable input requirement, never a baked challenge.
    return dict(agent_id='a19',capability_id='responsibility.a19',case=case,
        case_version=CASE_VERSION,oracle_id=ORACLE_ID,
        request=request('source',case,dict(case=case,stage='source',
            execution_input_required=True,input_policy='AFTER_ORIGINAL_INITIALIZATION_NO_ANSWER_NO_FALLBACK')),
        evidence_scope='ORIGINAL_POST_INITIALIZATION_INPUT_AND_DISTINCT_SEALED_BLIND_COMPARISON_ONLY')


def validate_execution(execution,*,source_revision,runtime_image_id,registry_sha256,now):
    require(type(execution) is dict and set(execution) == {
        'case_spec','runtime','initialization','custodian','source','audit','comparison'},
        'EXECUTION_INPUT_EXECUTION_FIELDS_INVALID')
    spec = execution['case_spec'];runtime = execution['runtime']
    require(independent_verifier_binding()['registry_sha256'] == registry_sha256,
        'EXECUTION_INPUT_CURRENT_REGISTERED_VERIFIER_REQUIRED')
    require(type(spec) is dict and canonical(spec) == canonical(canonical_case(spec.get('case')))
        and type(runtime) is dict and set(runtime) == {'host_id','source_revision','version','image_digest'}
        and runtime['source_revision'] == source_revision and runtime['image_digest'] == runtime_image_id,
        'EXECUTION_INPUT_EXECUTION_BINDING_INVALID')
    custody,source,audit,comparison = (execution[key] for key in ('custodian','source','audit','comparison'))
    data = validate_proof(comparison,runtime,registry_sha256,now)
    context = parse(comparison['request']['context'].encode())
    require(data['case'] == spec['case'] and data['stage'] == 'comparison'
        and canonical(context['custodian']) == canonical(custody)
        and canonical(expand_original(context['source'],custody,'source')) == canonical(source)
        and canonical(expand_original(context['audit'],custody,'audit')) == canonical(audit)
        and canonical(parse(custody['request']['context'].encode())['initialization']) == canonical(execution['initialization']),
        'EXECUTION_INPUT_COMPLETE_ORIGINAL_DAG_REQUIRED')
    return dict(case=spec['case'],task_id=source['dispatch']['task_id'],
        case_spec_sha256=sha(canonical(spec)),result_sha256=source['artifact_metadata']['sha256'],
        comparison_task_id=comparison['dispatch']['task_id'],comparison_sha256=comparison['artifact_metadata']['sha256'],
        completed_at=comparison['artifact_metadata']['timestamp'],oracle_id=ORACLE_ID,oracle_pass=True,
        service_confirmation='NOT_PERFORMED',live_unfamiliarity='NOT_PROVEN')


def payload(case,value):
    require(case in CASES and type(value) is dict and len(canonical(value)) <= MAX_INPUT,
        'EXECUTION_INPUT_REQUIRED')
    common = {'case','challenge_id','label','custodian_scope','window_id'}
    require(value.get('case') == case and _uuid(value.get('challenge_id'))
        and value.get('label') == LABEL and value.get('custodian_scope') == 'SOURCE_TEST_CUSTODIAN'
        and type(value.get('window_id')) is str and _NAME.fullmatch(value['window_id']) is not None,
        'EXECUTION_INPUT_LABEL_OR_ID_INVALID')
    if case == CASES[0]:
        require(set(value) == common|{'service_id','checks','failures'}
            and type(value['service_id']) is str and _NAME.fullmatch(value['service_id']) is not None
            and type(value['checks']) is int and type(value['failures']) is int
            and 1 <= value['failures'] <= value['checks'] <= 100000,
            'NEW_SYNTHETIC_FAILURE_REQUIRED')
    else:
        require(set(value) == common|{'nodes','depends_on','failed_dependency','failure_observed'}
            and type(value['nodes']) is list and 1 <= len(value['nodes']) <= 32
            and all(type(n) is str and _NAME.fullmatch(n) is not None for n in value['nodes'])
            and len(set(value['nodes'])) == len(value['nodes'])
            and type(value['depends_on']) is list and len(value['depends_on']) <= 64
            and all(type(edge) is list and len(edge) == 2 and all(type(n) is str and n in value['nodes'] for n in edge)
                and edge[0] != edge[1] for edge in value['depends_on'])
            and len({tuple(e) for e in value['depends_on']}) == len(value['depends_on'])
            and value['failed_dependency'] in value['nodes'] and value['failure_observed'] is True,
            'HELD_OUT_DEPENDENCY_FAILURE_REQUIRED')
    return value


def producer_assessment(value):
    """Only input arriving at execution drives this producer."""
    case = value['case'];payload(case,value)
    if case == CASES[0]:
        quotient = value['failures']*10000 // value['checks']
        evidence = dict(service_id=value['service_id'],checks=value['checks'],failures=value['failures'],
            failure_basis_points=quotient,ratio_remainder=value['failures']*10000-quotient*value['checks'])
    else:
        seen = {value['failed_dependency']};frontier = [value['failed_dependency']]
        while frontier:
            dependency = frontier.pop(0)
            for node,target in value['depends_on']:
                if target == dependency and node not in seen:seen.add(node);frontier.append(node)
        evidence = dict(failed_dependency=value['failed_dependency'],potentially_affected_nodes=sorted(seen))
    return dict(window_id=value['window_id'],evidence=evidence,scope='SUPPLIED_SYNTHETIC_EXECUTION_INPUT_ONLY',
        current_health='UNKNOWN',recovery='NOT_PROVEN',live_unfamiliarity='NOT_PROVEN',
        proposed_check=dict(action='READ_ONE_NEW_OWNER_SUPPLIED_DISCRIMINATING_WINDOW',execution='NOT_PERFORMED',
            automatic_execution=False,read_only=True),authority_transfer=False)


def auditor_assessment(value):
    """Independent input-only calculator, not the A19 producer."""
    case = value['case'];payload(case,value)
    if case == CASES[0]:
        quotient,remainder = divmod(10000*value['failures'],value['checks'])
        evidence = dict(service_id=value['service_id'],checks=value['checks'],failures=value['failures'],
            failure_basis_points=quotient,ratio_remainder=remainder)
    else:
        reverse = {n:[] for n in value['nodes']}
        for service,dependency in value['depends_on']:reverse[dependency].append(service)
        found = set();stack = [value['failed_dependency']]
        while stack:
            node = stack.pop()
            if node in found:continue
            found.add(node);stack.extend(reverse[node])
        evidence = dict(failed_dependency=value['failed_dependency'],potentially_affected_nodes=sorted(found))
    return dict(window_id=value['window_id'],evidence=evidence,scope='SUPPLIED_SYNTHETIC_EXECUTION_INPUT_ONLY',
        current_health='UNKNOWN',recovery='NOT_PROVEN',live_unfamiliarity='NOT_PROVEN',
        proposed_check=dict(action='READ_ONE_NEW_OWNER_SUPPLIED_DISCRIMINATING_WINDOW',execution='NOT_PERFORMED',
            automatic_execution=False,read_only=True),authority_transfer=False)


def oracle_assessment(value):
    """Separate final grader: Fraction and transitive closure, no producer call."""
    from fractions import Fraction
    case = value['case'];payload(case,value)
    if case == CASES[0]:
        quotient = int(Fraction(value['failures'],value['checks'])*10000)
        evidence = dict(service_id=value['service_id'],checks=value['checks'],failures=value['failures'],
            failure_basis_points=quotient,ratio_remainder=10000*value['failures']-value['checks']*quotient)
    else:
        nodes = value['nodes'];size = len(nodes);index = {node:i for i,node in enumerate(nodes)}
        reach = [[i == j for j in range(size)] for i in range(size)]
        for node,dependency in value['depends_on']:reach[index[node]][index[dependency]] = True
        for k in range(size):
            for i in range(size):
                for j in range(size):reach[i][j] = reach[i][j] or (reach[i][k] and reach[k][j])
        affected = sorted(node for i,node in enumerate(nodes) if reach[i][index[value['failed_dependency']]])
        evidence = dict(failed_dependency=value['failed_dependency'],potentially_affected_nodes=affected)
    return dict(window_id=value['window_id'],evidence=evidence,scope='SUPPLIED_SYNTHETIC_EXECUTION_INPUT_ONLY',
        current_health='UNKNOWN',recovery='NOT_PROVEN',live_unfamiliarity='NOT_PROVEN',
        proposed_check=dict(action='READ_ONE_NEW_OWNER_SUPPLIED_DISCRIMINATING_WINDOW',execution='NOT_PERFORMED',
            automatic_execution=False,read_only=True),authority_transfer=False)


def request(stage,case,context):
    require(stage in STAGES and case in CASES,'EXECUTION_INPUT_STAGE_UNSUPPORTED')
    return dict(classification='R0',capability='responsibility.a19' if stage == 'source' else 'responsibility.a26',
        objective=OBJECTIVES[stage],context=canonical(context).decode(),data_classification='LOCAL_ONLY',
        minimum_tier='NANO',priority='low',task_class='classification',max_cost_usd=0.0,
        preferred_provider=None,response_format='strict_json',deterministic_operation=OPERATION)


def custodian_request(case,initialization,value,registry,nonce):
    payload(case,value)
    return request('custodian',case,dict(case=case,stage='custodian',initialization=initialization,
        supplied_payload=value,registry_sha256=registry,review_nonce=nonce))


def stage_request(stage,case,custodian,registry,nonce,*,source=None,audit=None):
    require(stage in ('source','audit','comparison'),'EXECUTION_INPUT_STAGE_UNSUPPORTED')
    context = dict(case=case,stage=stage,custodian=custodian,registry_sha256=registry,review_nonce=nonce)
    if stage == 'comparison':context.update(source=compact_original(source,custodian),audit=compact_original(audit,custodian))
    return request(stage,case,context)


def compact_original(proof,custodian):
    """Share one custody DAG node; never replace original artifact/action bytes."""
    value = parse(canonical(proof));context = parse(value['request']['context'].encode())
    require(context.get('stage') in ('source','audit')
        and canonical(context.get('custodian')) == canonical(custodian),'EXECUTION_INPUT_SHARED_CUSTODY_MISMATCH')
    context['custodian'] = {'custodian_sha256':sha(canonical(custodian))}
    value['request']['context'] = canonical(context).decode()
    return value


def expand_original(proof,custodian,stage):
    value = parse(canonical(proof));context = parse(value['request']['context'].encode())
    require(context.get('stage') == stage and context.get('custodian') == {
        'custodian_sha256':sha(canonical(custodian))},'EXECUTION_INPUT_SHARED_CUSTODY_REFERENCE_INVALID')
    context['custodian'] = custodian
    value['request']['context'] = canonical(context).decode()
    return value


def admit(body,registry):
    value = body.model_dump() if hasattr(body,'model_dump') else body
    require(type(value) is dict and type(value.get('context')) is str,'EXECUTION_INPUT_REQUEST_REQUIRED')
    context = parse(value['context'].encode());stage,case = context.get('stage'),context.get('case')
    fields = {'case','stage','registry_sha256','review_nonce'}|({'initialization','supplied_payload'}
        if stage == 'custodian' else {'custodian'}|({'source','audit'} if stage == 'comparison' else set()))
    require(stage in STAGES and case in CASES and set(context) == fields
        and context['registry_sha256'] == registry and _uuid(context['review_nonce'])
        and canonical(value) == canonical(request(stage,case,context)),'EXECUTION_INPUT_REQUEST_UNBOUND')
    if stage == 'custodian':payload(case,context['supplied_payload'])
    return context


def read_task(root,task,body,runtime,*,deadline,completed=None,actor=None):
    """Bounded read-only original store; no migration, initialization or COUNT."""
    root = _path(root);path = _path(root/'objectives.db');used = 0
    require(_uuid(task) and path.is_file(),'EXECUTION_INPUT_ORIGINAL_STORE_REQUIRED')
    for suffix in ('','-wal','-shm','-journal'):
        candidate = _path(root/('objectives.db'+suffix))
        if candidate.exists():
            require(candidate.is_file(),'EXECUTION_INPUT_STORE_INVALID');used += candidate.stat().st_size
    require(used <= 8*1024*1024 and time.monotonic() < deadline,'EXECUTION_INPUT_STORE_BOUND')
    try:
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=0.1)) as db:
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,1024*1024)
            db.set_progress_handler(lambda:1 if time.monotonic() >= deadline else 0,1000);db.execute('BEGIN')
            row = db.execute('SELECT objective_hash,state,steps_json FROM objectives WHERE id=?',(task,)).fetchone()
            turns = db.execute('SELECT revision FROM objective_turns WHERE task=? LIMIT 1',(task,)).fetchone()
            times = db.execute('SELECT revision,created_at,updated_at FROM objective_metadata WHERE task=? LIMIT 2',(task,)).fetchall()
            pins = db.execute('SELECT revision,host_id,source_revision,version,image_digest FROM objective_runtime WHERE task=? LIMIT 2',(task,)).fetchall()
    except sqlite3.Error:raise ValueError('EXECUTION_INPUT_STORE_QUERY_REJECTED') from None
    cap = body['capability']
    require(time.monotonic() < deadline and row is not None and row[0] == sha(body['objective'].encode())
        and turns is None and len(times) == 1 and times[0][0] == 0
        and pins == [(0,runtime['host_id'],runtime['source_revision'],runtime['version'],runtime['image_digest'])],
        'EXECUTION_INPUT_ORIGINAL_TASK_DRIFT')
    if completed is None:
        require(row[1] == 'dispatching' and json.loads(row[2]) == [cap] and times[0][1] == times[0][2]
            and 0 <= (datetime.now(timezone.utc)-_utc(times[0][1])).total_seconds() <= 5,
            'EXECUTION_INPUT_ORIGINAL_REQUEST_REQUIRED')
    else:
        require(row[1] == 'submitted' and canonical(json.loads(row[2])) == canonical([dict(capability=cap,dispatch=completed)])
            and completed['task_id'] == task and completed['agent_id'] == actor
            and completed['capability'] == cap and completed['model_calls'] == 0
            and completed['execution_model'] == 'DETERMINISTIC','EXECUTION_INPUT_COMPLETED_TASK_REQUIRED')
    return dict(task_id=task,objective_sha256=row[0],request_sha256=sha(canonical(body)),
        capability=cap,revision=0,created_at=times[0][1],updated_at=times[0][2],runtime=runtime,
        state=row[1],scope='ORIGINAL_TASK_AND_AUTHENTICATED_REQUEST_ONLY')


def read_original_artifact(root,metadata,raw,actor,task,runtime):
    from .artifact_factory import ArtifactFactory
    validate_metadata(metadata,raw,actor,task,runtime,datetime.now(timezone.utc))
    folder = _path(_path(root)/'artifacts'/metadata.get('artifact_id',''))
    require(folder.is_dir() and {p.name for p in folder.iterdir()} == {'artifact.json','metadata.json'}
        and all(_path(folder/name).is_file() and (folder/name).stat().st_size <= MAX_INPUT
            for name in ('artifact.json','metadata.json')),'EXECUTION_INPUT_ARTIFACT_BOUND')
    actual,stored = ArtifactFactory(folder.parent).retrieve(metadata['artifact_id'])
    require(canonical(actual) == canonical(metadata) and stored == raw,'EXECUTION_INPUT_ORIGINAL_ARTIFACT_DRIFT')
    return parse(stored)


def validate_metadata(metadata,raw,actor,task,runtime,now):
    fields = {'artifact_id','task_id','type','creator_agents','timestamp','version','provenance',
        'runtime_revision','validation_state','content_validation','location','sha256','bytes','delivery_state'}
    require(type(metadata) is dict and set(metadata) == fields
        and type(metadata['artifact_id']) is str and re.fullmatch('[0-9a-f]{32}',metadata['artifact_id']) is not None
        and _uuid(task) and metadata['task_id'] == task and metadata['creator_agents'] == [actor]
        and metadata['type'] == 'json' and metadata['version'] == '1.0.0'
        and metadata['provenance'] == 'Deterministic computation; zero model calls'
        and metadata['runtime_revision'] == runtime['source_revision']
        and metadata['validation_state'] == 'STRUCTURE_VALIDATED'
        and metadata['content_validation'] == 'Not independently established by structural validation'
        and metadata['location'] == 'artifact.json' and metadata['delivery_state'] == 'AVAILABLE'
        and metadata['sha256'] == sha(raw) and type(metadata['bytes']) is int
        and 0 < metadata['bytes'] == len(raw) <= MAX_INPUT and _utc(metadata['timestamp']) <= now,
        'EXECUTION_INPUT_ORIGINAL_METADATA_INVALID')


def read_span(root,task,action):
    require(_uuid(task) and action in {read_action(s) for s in ('source','audit')}|
        {output_action(s) for s in STAGES},'EXECUTION_INPUT_ACTION_INVALID')
    lines = _ledger_lines(_path(root));positions = [i for i,line in enumerate(lines)
        if (event := parse(line.encode())).get('task_id') == task and event.get('action_type') == action]
    require(len(positions) == 2 and 2 <= positions[-1]-positions[0]+1 <= 128,'EXECUTION_INPUT_ORIGINAL_ACTION_PAIR_REQUIRED')
    return lines[positions[0]:positions[-1]+1]


def read_action(stage):
    require(stage in ('source','audit'),'EXECUTION_INPUT_READ_STAGE_INVALID')
    return 'agent.certification.execution_input.'+stage+'.read'


def output_action(stage):
    require(stage in STAGES,'EXECUTION_INPUT_OUTPUT_STAGE_INVALID')
    return 'agent.certification.execution_input.'+stage+'.artifact'


def initialization_original(root,execution,runtime,registry,*,deadline):
    from .agent_cert_initialization_review import validate_initialization_execution
    from .agent_cert_initialization import ACTION_TYPE
    from .agent_cert_role_review import canonical_case_spec
    validate_initialization_execution(execution,agent_id='a19',capability_id='responsibility.a19',
        source_revision=runtime['source_revision'],runtime_image_id=runtime['image_digest'],
        registry_sha256=registry,now=datetime.now(timezone.utc))
    dispatch = execution['dispatch'];task = dispatch['task_id']
    body = canonical_case_spec('a19','responsibility.a19','baseline:initialization')['request']
    # Pydantic normalizes omitted preferred_provider to None in the dispatcher.
    body = dict(body,preferred_provider=None)
    receipt = read_task(root,task,body,runtime,deadline=deadline,completed=dispatch,actor='a19')
    require(execution['objective_read'][1]['execution_metadata']['updated_at'] == receipt['updated_at'],
        'EXECUTION_INPUT_INITIALIZATION_TIME_DRIFT')
    metadata = execution['artifact_metadata'];raw = execution['artifact_content_utf8'].encode()
    read_original_artifact(root,metadata,raw,'a19',task,runtime)
    lines = _ledger_lines(_path(root));indexes = [i for i,line in enumerate(lines)
        if (e := parse(line.encode())).get('task_id') == task and e.get('action_type') == ACTION_TYPE]
    require(len(indexes) == 2 and lines[indexes[0]:indexes[-1]+1] == execution['action_records'],
        'EXECUTION_INPUT_INITIALIZATION_ACTION_DRIFT')
    require(time.monotonic() < deadline,'EXECUTION_INPUT_INITIALIZATION_READ_BOUND')
    return receipt


def execute(body,authorization,*,actor,task_id,runtime,budget):
    """Only the exact authenticated owning dispatcher invokes this protocol."""
    from .objective_api import authenticate_owner,runtime_snapshot
    from .agent_registry import agent_record
    from .agent_dispatch_api import action_ledger
    from .action_records import ActionRecord,DirectExecutor
    from .deterministic_ops import DeterministicOps
    import os
    authenticate_owner(authorization);binding = independent_verifier_binding();registry = binding['registry_sha256']
    context = admit(body,registry);stage,case = context['stage'],context['case']
    require(actor == ('a19' if stage == 'source' else 'a26')
        and agent_record(actor)['authority'] == 'advisory'
        and {'provided_context.read','action.propose'} <= set(agent_record(actor)['tool_eligibility']),
        'EXECUTION_INPUT_CURRENT_OWNER_REQUIRED')
    root = _path(os.getenv('PRIME_DATA_DIR','/data'))
    require(_path(root/'artifacts').is_dir() and case_remaining(budget) > 0,'EXECUTION_INPUT_STORE_OR_BUDGET_REQUIRED')
    body_value = body.model_dump();deadline = time.monotonic()+min(1,case_remaining(budget))
    original = read_task(root,task_id,body_value,runtime,deadline=deadline)
    budget['started_at'] = min(budget['started_at'],_utc(original['created_at']))
    require(canonical(runtime_snapshot()) == canonical(runtime),'EXECUTION_INPUT_RUNTIME_DRIFT')
    ledger = action_ledger()
    require(ledger.status()['healthy'] and not any(parse(line.encode()).get('task_id') == task_id
        for line in _ledger_lines(root)),'EXECUTION_INPUT_TASK_ALREADY_ATTEMPTED')
    data = dict(schema_version=SCHEMAS[stage],case=case,stage=stage,original_request=original,
        review_nonce=context['review_nonce'],model_calls=0,certification='UNVERIFIED',
        authority_transfer=False,live_unfamiliarity='NOT_PROVEN')
    if stage == 'custodian':
        initialized = initialization_original(root,context['initialization'],runtime,registry,
            deadline=time.monotonic()+min(1,case_remaining(budget)))
        require(_utc(initialized['updated_at']) <= _utc(original['created_at']) and initialized['task_id'] != task_id,
            'EXECUTION_INPUT_MUST_ARRIVE_AFTER_INITIALIZATION')
        challenge_id = context['supplied_payload']['challenge_id']
        require(not any((event := parse(line.encode())).get('action_type') == output_action('custodian')
            and event.get('parameters_summary',{}).get('challenge_id') == challenge_id
            for line in _ledger_lines(root)),'EXECUTION_INPUT_CUSTODIAN_REPLAY_DENIED')
        data.update(initialization_task_id=initialized['task_id'],initialization_updated_at=initialized['updated_at'],
            supplied_payload=payload(case,context['supplied_payload']),custodian_scope='SOURCE_TEST_CUSTODIAN',
            input_handling='SUPPLIED_AFTER_ORIGINAL_INITIALIZATION',assessment_supplied=False,challenge_id=challenge_id)
    else:
        custodian = context['custodian']
        require(stage_of(custodian) == 'custodian','EXECUTION_INPUT_CUSTODIAN_STAGE_REQUIRED')
        custody = read_original_proof(root,custodian,runtime,registry,
            deadline=time.monotonic()+min(1,case_remaining(budget)))
        require(custody['stage'] == 'custodian' and custody['case'] == case
            and _utc(custodian['artifact_metadata']['timestamp']) <= _utc(original['created_at']),
            'EXECUTION_INPUT_ORIGINAL_HANDOFF_REQUIRED')
        data['challenge_id'] = custody['challenge_id']
        if stage in ('source','audit'):
            metadata = custodian['artifact_metadata'];folder = _path(root/'artifacts'/metadata['artifact_id'])
            require(not any((event := parse(line.encode())).get('action_type') == read_action(stage)
                and event.get('parameters_summary',{}).get('input_artifact_id') == metadata['artifact_id']
                for line in _ledger_lines(root)),'EXECUTION_INPUT_HANDOFF_REPLAY_DENIED')
            action = ActionRecord(task_id,actor,read_action(stage),'provided_context.read',target='artifact.json',
                parameters_summary=dict(schema_version=SCHEMAS[stage],case=case,input_artifact_id=metadata['artifact_id'],
                    expected_sha256=metadata['sha256'],read_only_observations=True))
            reader = DeterministicOps(source_version=runtime['source_revision'])
            def read():
                raw,digest = reader.retrieve_file(folder,'artifact.json',expected_sha256=metadata['sha256'])
                require(raw == custodian['artifact_content_utf8'].encode() and digest == sha(raw),
                    'EXECUTION_INPUT_READ_DRIFT')
                return dict(source_sha256=digest,result=raw.decode())
            raw = DirectExecutor(ledger).execute(action,read)['result'].encode();observed = parse(raw)
            supplied = payload(case,observed['supplied_payload'])
            assessment = producer_assessment(supplied) if stage == 'source' else auditor_assessment(supplied)
            remaining = case_remaining(budget)
            require(remaining > 0 and ledger.flush(timeout=remaining) is True and case_remaining(budget) > 0,
                'EXECUTION_INPUT_READ_NOT_DURABLE')
            data.update(input_artifact_metadata=metadata,input_sha256=sha(raw),payload_sha256=sha(canonical(supplied)),
                input_read_action_id=action.action_id,assessment=assessment,prior_answer_access='NOT_SUPPLIED_OR_READ')
        else:
            require(not any((event := parse(line.encode())).get('action_type') == output_action('comparison')
                and event.get('parameters_summary',{}).get('challenge_id') == custody['challenge_id']
                for line in _ledger_lines(root)),'EXECUTION_INPUT_COMPARISON_REPLAY_DENIED')
            source = expand_original(context['source'],custodian,'source')
            audit = expand_original(context['audit'],custodian,'audit')
            source_data = read_original_proof(root,source,runtime,registry,deadline=time.monotonic()+min(1,case_remaining(budget)))
            audit_data = read_original_proof(root,audit,runtime,registry,deadline=time.monotonic()+min(1,case_remaining(budget)))
            require(source_data['stage'] == 'source' and audit_data['stage'] == 'audit'
                and source_data['case'] == audit_data['case'] == case
                and len({task_id,source['dispatch']['task_id'],audit['dispatch']['task_id'],custodian['dispatch']['task_id']}) == 4
                and source_data['input_sha256'] == audit_data['input_sha256'] == custodian['artifact_metadata']['sha256']
                and _utc(audit['artifact_metadata']['timestamp']) <= _utc(original['created_at'])
                and source_data['assessment'] == audit_data['assessment'] == oracle_assessment(custody['supplied_payload']),
                'EXECUTION_INPUT_INDEPENDENT_COMPARISON_REJECTED')
            # Independent original rereads after calculation, with one case budget.
            require(read_original_proof(root,source,runtime,registry,deadline=time.monotonic()+min(1,case_remaining(budget))) == source_data
                and read_original_proof(root,audit,runtime,registry,deadline=time.monotonic()+min(1,case_remaining(budget))) == audit_data,
                'EXECUTION_INPUT_CHANGED_DURING_COMPARISON')
            data.update(source_task_id=source['dispatch']['task_id'],audit_task_id=audit['dispatch']['task_id'],
                custodian_task_id=custodian['dispatch']['task_id'],input_sha256=custodian['artifact_metadata']['sha256'],
                result='PASS',review_scope='ORIGINAL_SUPPLIED_INPUT_AND_SEALED_BLIND_COMPARISON_ONLY',
                service_confirmation='NOT_PERFORMED')
    require(case_remaining(budget) > 0 and canonical(runtime_snapshot()) == canonical(runtime),
        'EXECUTION_INPUT_BUDGET_OR_RUNTIME_DRIFT')
    return data


def dispatch(body,authorization,*,actor,task_id,runtime,budget):
    """One serialized exact stage, including both original durability barriers."""
    from .objective_api import authenticate_owner,runtime_snapshot
    from .agent_dispatch_api import action_ledger
    from .action_records import ActionRecord,DirectExecutor
    from .artifact_factory import ArtifactFactory
    import os
    authenticate_owner(authorization)
    require(_slot.acquire(blocking=False),'EXECUTION_INPUT_DISPATCH_BUSY')
    try:
        data = execute(body,authorization,actor=actor,task_id=task_id,runtime=runtime,budget=budget)
        stage = data['stage'];root = _path(os.getenv('PRIME_DATA_DIR','/data'))
        require(case_remaining(budget) > 0,'EXECUTION_INPUT_CASE_BUDGET_EXHAUSTED')
        ledger = action_ledger();factory = ArtifactFactory(_path(root/'artifacts'))
        record = ActionRecord(task_id,actor,output_action(stage),'artifact-factory',parameters_summary=dict(
            schema_version=SCHEMAS[stage],case=data['case'],challenge_id=data['challenge_id'],read_only_observations=True))
        def create():
            metadata = factory.create(kind='json',content=canonical(data).decode(),task_id=task_id,creator=actor,
                provenance='Deterministic computation; zero model calls',runtime_revision=runtime['source_revision'])
            actual,raw = factory.retrieve(metadata['artifact_id'])
            require(actual == metadata and raw == canonical(data),'EXECUTION_INPUT_OUTPUT_READBACK_DRIFT')
            return metadata
        metadata = DirectExecutor(ledger).execute(record,create)
        remaining = case_remaining(budget)
        require(remaining > 0 and ledger.flush(timeout=remaining) is True and case_remaining(budget) > 0
            and canonical(runtime_snapshot()) == canonical(runtime),'EXECUTION_INPUT_OUTPUT_NOT_DURABLE')
        result = dict(task_id=task_id,state='COMPLETED',artifact=metadata,model_calls=0,execution_model='DETERMINISTIC',
            agent_id=actor,capability=body.capability,runtime_source_revision=runtime['source_revision'],
            review_action_id=record.action_id,review_action_durable=True,certification='UNVERIFIED')
        if stage in ('source','audit'):result['execution_input_read_action_id'] = data['input_read_action_id']
        return result
    finally:_slot.release()


def output_span(proof,data):
    rows = _events(proof['action_records']);dispatch = proof['dispatch'];metadata = proof['artifact_metadata']
    require(len(rows) == 2,'EXECUTION_INPUT_ORIGINAL_OUTPUT_PAIR_REQUIRED')
    base = dict(task_id=dispatch['task_id'],agent_id=dispatch['agent_id'],action_type=output_action(data['stage']),
        tool='artifact-factory',target='',classification='R0',model_backend='deterministic',execution_location='local',
        parent_agent=None,workflow_id=None,action_id=dispatch['review_action_id'],parameters_summary=dict(
            schema_version=SCHEMAS[data['stage']],case=data['case'],challenge_id=data['challenge_id'],read_only_observations=True))
    fields = set(base)|{'phase','timestamp','sequence','previous_sha256','sha256'}
    require(_uuid(base['action_id']) and set(rows[0]) == fields
        and set(rows[1]) == fields|{'success','duration_ms','result_summary'}
        and all(canonical(row.get(k)) == canonical(v) for row in rows for k,v in base.items())
        and rows[0]['phase'] == 'started' and rows[1]['phase'] == 'completed' and rows[1]['success'] is True
        and type(rows[1]['duration_ms']) in (int,float) and math.isfinite(rows[1]['duration_ms'])
        and 0 <= rows[1]['duration_ms'] <= 5000
        and rows[1]['result_summary'] == dict(type='dict',artifact_id=metadata['artifact_id'],sha256=metadata['sha256'],location='artifact.json')
        and _utc(data['original_request']['created_at']) <= _utc(rows[0]['timestamp']) <= _utc(metadata['timestamp']) <= _utc(rows[1]['timestamp']),
        'EXECUTION_INPUT_OUTPUT_BINDING_INVALID')


def validate_proof(proof,runtime,registry,now):
    """Portable original evidence semantics; never calls a producer calculator."""
    require(type(proof) is dict and set(proof) == {'request','dispatch','artifact_metadata','artifact_content_utf8',
        'read_action_records','action_records','objective_read'},'EXECUTION_INPUT_PROOF_FIELDS_INVALID')
    context = admit(proof['request'],registry);stage,case = context['stage'],context['case']
    dispatch,metadata = proof['dispatch'],proof['artifact_metadata'];actor = 'a19' if stage == 'source' else 'a26'
    fields = {'task_id','state','artifact','model_calls','execution_model','agent_id','capability',
        'runtime_source_revision','review_action_id','review_action_durable','certification'}|(
        {'execution_input_read_action_id'} if stage in ('source','audit') else set())
    require(type(dispatch) is dict and set(dispatch) == fields and _uuid(dispatch.get('task_id')) and dispatch.get('state') == 'COMPLETED'
        and dispatch.get('agent_id') == actor and dispatch.get('capability') == proof['request']['capability']
        and type(dispatch.get('model_calls')) is int and dispatch['model_calls'] == 0
        and dispatch.get('execution_model') == 'DETERMINISTIC'
        and dispatch.get('runtime_source_revision') == runtime['source_revision']
        and dispatch.get('review_action_durable') is True and dispatch.get('certification') == 'UNVERIFIED'
        and canonical(dispatch.get('artifact')) == canonical(metadata),'EXECUTION_INPUT_ACTUAL_TASK_REQUIRED')
    raw = proof['artifact_content_utf8'].encode();data = parse(raw);receipt = data.get('original_request')
    require(type(receipt) is dict and set(receipt) == {'task_id','objective_sha256','request_sha256',
        'capability','revision','created_at','updated_at','runtime','state','scope'}
        and receipt.get('task_id') == dispatch['task_id']
        and receipt.get('request_sha256') == sha(canonical(proof['request']))
        and receipt.get('objective_sha256') == sha(proof['request']['objective'].encode())
        and receipt.get('capability') == proof['request']['capability']
        and type(receipt.get('revision')) is int and receipt['revision'] == 0
        and receipt.get('state') == 'dispatching' and receipt.get('created_at') == receipt.get('updated_at')
        and canonical(receipt.get('runtime')) == canonical(runtime)
        and receipt.get('scope') == 'ORIGINAL_TASK_AND_AUTHENTICATED_REQUEST_ONLY'
        and 0 <= (_utc(metadata['timestamp'])-_utc(receipt['created_at'])).total_seconds() <= 5,
        'EXECUTION_INPUT_ORIGINAL_REQUEST_UNBOUND')
    validate_metadata(metadata,raw,actor,dispatch['task_id'],runtime,now)
    expected = dict(schema_version=SCHEMAS[stage],case=case,stage=stage,original_request=receipt,
        review_nonce=context['review_nonce'],model_calls=0,certification='UNVERIFIED',
        authority_transfer=False,live_unfamiliarity='NOT_PROVEN')
    if stage == 'custodian':
        init = context['initialization'];initialized = init['objective_read'][1]['execution_metadata']
        from .agent_cert_initialization_review import validate_initialization_execution
        validate_initialization_execution(init,agent_id='a19',capability_id='responsibility.a19',
            source_revision=runtime['source_revision'],runtime_image_id=runtime['image_digest'],
            registry_sha256=registry,now=now)
        require(_utc(initialized['updated_at']) <= _utc(receipt['created_at']),'EXECUTION_INPUT_CHRONOLOGY_INVALID')
        expected.update(initialization_task_id=init['dispatch']['task_id'],initialization_updated_at=initialized['updated_at'],
            supplied_payload=payload(case,context['supplied_payload']),custodian_scope='SOURCE_TEST_CUSTODIAN',
            input_handling='SUPPLIED_AFTER_ORIGINAL_INITIALIZATION',assessment_supplied=False,
            challenge_id=context['supplied_payload']['challenge_id'])
    else:
        require(stage_of(context['custodian']) == 'custodian','EXECUTION_INPUT_CUSTODIAN_STAGE_REQUIRED')
        custody = validate_proof(context['custodian'],runtime,registry,now)
        require(custody['stage'] == 'custodian' and custody['case'] == case
            and _utc(context['custodian']['artifact_metadata']['timestamp']) <= _utc(receipt['created_at']),
            'EXECUTION_INPUT_CUSTODIAN_CHRONOLOGY_INVALID')
        expected['challenge_id'] = custody['challenge_id']
        if stage in ('source','audit'):
            original = context['custodian'];input_raw = original['artifact_content_utf8'].encode()
            expected.update(input_artifact_metadata=original['artifact_metadata'],input_sha256=sha(input_raw),
                payload_sha256=sha(canonical(custody['supplied_payload'])),input_read_action_id=dispatch.get('execution_input_read_action_id'),
                assessment=oracle_assessment(custody['supplied_payload']),prior_answer_access='NOT_SUPPLIED_OR_READ')
            rows = _events(proof['read_action_records']);require(len(rows) == 2,'EXECUTION_INPUT_ORIGINAL_READ_REQUIRED')
            base = dict(task_id=dispatch['task_id'],agent_id=actor,action_type=read_action(stage),tool='provided_context.read',
                target='artifact.json',classification='R0',model_backend='deterministic',execution_location='local',
                parent_agent=None,workflow_id=None,action_id=expected['input_read_action_id'],
                parameters_summary=dict(schema_version=SCHEMAS[stage],case=case,input_artifact_id=original['artifact_metadata']['artifact_id'],
                    expected_sha256=sha(input_raw),read_only_observations=True))
            require(_uuid(base['action_id']) and all(canonical(row.get(k)) == canonical(v) for row in rows for k,v in base.items())
                and set(rows[0]) == set(base)|{'timestamp','phase','sequence','previous_sha256','sha256'}
                and set(rows[1]) == set(base)|{'timestamp','phase','sequence','previous_sha256','sha256',
                    'success','duration_ms','result_summary'}
                and rows[0]['phase'] == 'started' and rows[1]['phase'] == 'completed' and rows[1].get('success') is True
                and type(rows[1].get('duration_ms')) in (int,float)
                and math.isfinite(rows[1]['duration_ms']) and 0 <= rows[1]['duration_ms'] <= 5000
                and rows[1].get('result_summary') == dict(type='dict',source_sha256=sha(input_raw),
                    output_sha256=sha(input_raw),output_length=len(input_raw.decode()))
                and _utc(receipt['created_at']) <= _utc(rows[0]['timestamp']) <= _utc(rows[1]['timestamp']) <= _utc(metadata['timestamp']),
                'EXECUTION_INPUT_READ_BINDING_INVALID')
        else:
            source = expand_original(context['source'],context['custodian'],'source')
            audit = expand_original(context['audit'],context['custodian'],'audit')
            require(stage_of(source) == 'source' and stage_of(audit) == 'audit','EXECUTION_INPUT_COMPARISON_STAGES_REQUIRED')
            s = validate_proof(source,runtime,registry,now);a = validate_proof(audit,runtime,registry,now)
            require(s['stage'] == 'source' and a['stage'] == 'audit' and s['case'] == a['case'] == case
                and s['input_sha256'] == a['input_sha256'] == context['custodian']['artifact_metadata']['sha256']
                and len({dispatch['task_id'],source['dispatch']['task_id'],audit['dispatch']['task_id'],context['custodian']['dispatch']['task_id']}) == 4
                and _utc(audit['artifact_metadata']['timestamp']) <= _utc(receipt['created_at']),
                'EXECUTION_INPUT_SEALED_DISTINCT_AUDIT_REQUIRED')
            expected.update(source_task_id=source['dispatch']['task_id'],audit_task_id=audit['dispatch']['task_id'],
                custodian_task_id=context['custodian']['dispatch']['task_id'],input_sha256=s['input_sha256'],result='PASS',
                review_scope='ORIGINAL_SUPPLIED_INPUT_AND_SEALED_BLIND_COMPARISON_ONLY',service_confirmation='NOT_PERFORMED')
    require(canonical(data) == canonical(expected),'EXECUTION_INPUT_INDEPENDENT_ORACLE_REJECTED')
    if stage not in ('source','audit'):require(proof['read_action_records'] == [],'EXECUTION_INPUT_UNEXPECTED_READ')
    output_span(proof,data)
    require(type(proof['objective_read']) in (list,tuple) and len(proof['objective_read']) == 2
        and type(proof['objective_read'][1]) is dict,'EXECUTION_INPUT_ORIGINAL_OBJECTIVE_REQUIRED')
    status,view = proof['objective_read'];meta = view.get('execution_metadata',{})
    require(status == 200 and view.get('id') == dispatch['task_id'] and view.get('state') == 'COMPLETED'
        and type(view.get('revision')) is int and view['revision'] == 0 and len(view.get('steps',[])) == 1
        and canonical(view['steps'][0].get('dispatch')) == canonical(dispatch)
        and view['steps'][0].get('capability') == proof['request']['capability']
        and meta.get('authoritative') is True and meta.get('runtime') == runtime
        and meta.get('created_at') == receipt['created_at'] and meta.get('jobs') == []
        and meta.get('agent_execution') == [] and _utc(meta['updated_at']) <= now,
        'EXECUTION_INPUT_ORIGINAL_OBJECTIVE_UNBOUND')
    return data


def stage_of(proof):
    require(type(proof) is dict and type(proof.get('request')) is dict
        and type(proof['request'].get('context')) is str,'EXECUTION_INPUT_STAGE_PROOF_REQUIRED')
    return parse(proof['request']['context'].encode()).get('stage')


def read_original_proof(root,proof,runtime,registry,*,deadline):
    data = validate_proof(proof,runtime,registry,datetime.now(timezone.utc));stage = data['stage']
    actor = 'a19' if stage == 'source' else 'a26';dispatch = proof['dispatch']
    receipt = read_task(root,dispatch['task_id'],proof['request'],runtime,deadline=deadline,completed=dispatch,actor=actor)
    view = proof['objective_read'][1]['execution_metadata']
    require(receipt['created_at'] == view['created_at'] and receipt['updated_at'] == view['updated_at'],
        'EXECUTION_INPUT_ORIGINAL_TIMING_DRIFT')
    actual = read_original_artifact(root,proof['artifact_metadata'],proof['artifact_content_utf8'].encode(),actor,dispatch['task_id'],runtime)
    if stage == 'custodian':
        context = parse(proof['request']['context'].encode())
        initialization_original(root,context['initialization'],runtime,registry,deadline=deadline)
    require(actual == data and read_span(root,dispatch['task_id'],output_action(stage)) == proof['action_records']
        and (stage not in ('source','audit') or read_span(root,dispatch['task_id'],read_action(stage)) == proof['read_action_records'])
        and time.monotonic() < deadline,'EXECUTION_INPUT_ORIGINAL_CUSTODY_DRIFT')
    return actual
