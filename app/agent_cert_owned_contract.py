"""Prospective registered-contract structural inspection, not role quality or L7.

Original supplied request/output bytes remain immutable evidence. Prose contract
requirements are reported as unestablished, never inferred from field presence.
The original A19 baseline contract exercise is deliberately outside this route.
"""
from datetime import datetime, timezone
import time
import threading

from .agent_cert_initialization import _owned_domains, _bindings, initialization_reviewer
from .agent_cert_artifact_events import canonical, parse, sha, _path, _utc, _ledger_lines
from .agent_cert_owned_identity import owned_pair

CASE = 'baseline:contract'
VERSION = 'registered.owned-contract-structural.v1'
SCHEMA = 'prime.owned-contract-input.v1'
RESULT_SCHEMA = 'prime.owned-contract-result.v1'
OPERATION = 'certification_owned_contract'
REVIEW_OPERATION = 'certification_owned_contract_review'
REVIEW_ACTION = 'agent.certification.owned_contract.review'
MAX_BYTES = 65536
PROVENANCE = 'Deterministic computation; zero model calls'
_slot = threading.BoundedSemaphore(1)


class OwnedContractError(ValueError):
    pass


def require(value, code):
    if value is not True:
        raise OwnedContractError(code) from None


def registry_digest():
    from . import agent_registry
    path = _path(agent_registry.REGISTRY_PATH)
    require(path.is_file(), 'OWNED_CONTRACT_REGISTRY_REQUIRED')
    before = path.stat()
    require(0 < before.st_size <= 1048576, 'OWNED_CONTRACT_REGISTRY_BOUNDS')
    with path.open('rb') as stream:
        original = stream.read(1048577)
    after = _path(path).stat()
    require(0 < len(original) <= 1048576 and
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
        'OWNED_CONTRACT_REGISTRY_CHANGED')
    return sha(original)


def supplied_bytes(agent_id, capability_id):
    """Explicit public source exercise; each pair binds its actual responsibility."""
    owned_pair(agent_id, capability_id)
    owned = _owned_domains(registry_digest(), agent_id, capability_id)
    selected = owned['selected_capability']
    request = dict(objective='Inspect supplied evidence for '+capability_id,
        context='PUBLIC_SYNTHETIC_ONLY: '+selected['input'], data_classification='LOCAL_ONLY')
    output = dict(agent_id=agent_id, status='needs_evidence',
        result='PUBLIC_SYNTHETIC_ONLY: proposed '+selected['output'],
        uncertainty=['ROLE_RESULT_QUALITY_NOT_ESTABLISHED'], proposed_actions=[])
    invalid_request = dict(request); del invalid_request['data_classification']
    invalid_output = dict(output, status='outside_registered_vocabulary',
        proposed_actions=[dict(operation='production.restart',executed=True)]); del invalid_output['uncertainty']
    return canonical(dict(schema_version=SCHEMA, agent_id=agent_id, capability_id=capability_id,
        source='PUBLIC_SYNTHETIC_ONLY', samples=[
            dict(id='structural-complete', input_utf8=canonical(request).decode(), output_utf8=canonical(output).decode()),
            dict(id='structural-incomplete', input_utf8=canonical(invalid_request).decode(),
                output_utf8=canonical(invalid_output).decode())]))


def canonical_case(agent_id, capability_id):
    raw = supplied_bytes(agent_id, capability_id)
    return dict(case=CASE, case_version=VERSION, agent_id=agent_id, capability_id=capability_id,
        request=dict(capability=capability_id,
            objective='Check the supplied input and proposed output against the registered contracts.',
            context=raw.decode(), classification='R0', data_classification='LOCAL_ONLY',
            minimum_tier='NANO', priority='low', task_class='classification', max_cost_usd=0.0,
            preferred_provider=None, response_format='strict_json', deterministic_operation=OPERATION),
        certification='UNVERIFIED', scope='STRUCTURAL_INSPECTION_ONLY')


def reviewer(agent_id, capability_id):
    owned_pair(agent_id, capability_id)
    return initialization_reviewer(agent_id, capability_id)


def action_type(step):
    require(step in ('setup', 'read', 'result'), 'OWNED_CONTRACT_ACTION_REQUIRED')
    return 'agent.certification.owned_contract.'+step


def read_action_span(root,task,kind):
    from .agent_cert_artifact_events import _uuid
    require(_uuid(task) and kind in {action_type(step) for step in ('setup','read','result')} | {REVIEW_ACTION},
        'OWNED_CONTRACT_FIXED_ACTION_REQUIRED')
    lines=_ledger_lines(_path(root))
    owned=[index for index,line in enumerate(lines)
        if (row:=parse(line.encode())).get('task_id')==task and row.get('action_type')==kind]
    require(len(owned)==2 and owned[-1]==owned[0]+1,'OWNED_CONTRACT_EXACT_ORIGINAL_PAIR_REQUIRED')
    return lines[owned[0]:owned[-1]+1]


def review_request(execution, nonce):
    from .agent_cert_artifact_events import _uuid
    require(type(execution) is dict and _uuid(nonce), 'OWNED_CONTRACT_REVIEW_CONTEXT_REQUIRED')
    spec = execution.get('case_spec', {})
    require(type(spec) is dict, 'OWNED_CONTRACT_REVIEW_SPEC_REQUIRED')
    agent, capability = spec.get('agent_id'), spec.get('capability_id')
    _, peer_capability = reviewer(agent, capability)
    envelope = dict(execution=execution, execution_sha256=sha(canonical(execution)), nonce=nonce)
    context = canonical(envelope)
    require(len(context) <= 80000, 'OWNED_CONTRACT_REVIEW_CONTEXT_BOUNDS')
    return dict(capability=peer_capability,
        objective='Independently inspect original registered-contract structural evidence for '+agent+'/'+capability+'. Do not certify or sign.',
        context=context.decode(), classification='R0', data_classification='LOCAL_ONLY',
        minimum_tier='NANO', priority='low', task_class='classification', max_cost_usd=0.0,
        preferred_provider=None, response_format='strict_json', deterministic_operation=REVIEW_OPERATION)


def inspect_supplied(raw, owned):
    """Producer checker. Independent review implements its own checker."""
    value = parse(raw, MAX_BYTES)
    require(type(value) is dict and set(value) ==
        {'schema_version', 'agent_id', 'capability_id', 'source', 'samples'}, 'OWNED_CONTRACT_INPUT_FIELDS')
    definition = owned['definition']; selected = owned['selected_capability']
    require(value['schema_version'] == SCHEMA and value['source'] == 'PUBLIC_SYNTHETIC_ONLY'
        and value['agent_id'] == definition['immutable_id'] and value['capability_id'] == selected['id'],
        'OWNED_CONTRACT_INPUT_BINDING')
    require(type(value['samples']) is list and 0 < len(value['samples']) <= 8, 'OWNED_CONTRACT_SAMPLE_BOUNDS')
    identifiers = set(); results = []
    for sample in value['samples']:
        require(type(sample) is dict and set(sample) == {'id','input_utf8','output_utf8'}
            and type(sample['id']) is str and 0 < len(sample['id']) <= 100
            and sample['id'] not in identifiers, 'OWNED_CONTRACT_SAMPLE_INVALID')
        identifiers.add(sample['id'])
        require(type(sample['input_utf8']) is str and type(sample['output_utf8']) is str,
            'OWNED_CONTRACT_SAMPLE_BYTES_REQUIRED')
        request = parse(sample['input_utf8'].encode(), 16384)
        output = parse(sample['output_utf8'].encode(), 16384)
        require(type(request) is dict and type(output) is dict, 'OWNED_CONTRACT_OBJECTS_REQUIRED')
        missing_input = [key for key in definition['input_contract']['required'] if key not in request]
        missing_output = [key for key in definition['output_contract']['required'] if key not in output]
        violations = []
        for field in ('objective','context'):
            if field in request:
                bounds = owned['request_contract']['input_bounds'][field]
                if type(request[field]) is not str or not bounds.get('minLength',0) <= len(request[field]) <= bounds['maxLength']:
                    violations.append('input.'+field+'.bounds')
        if 'data_classification' in request and request['data_classification'] not in definition['input_contract']['data_classification']:
            violations.append('input.data_classification.enum')
        if 'agent_id' in output and output['agent_id'] != definition['immutable_id']:
            violations.append('output.agent_id.identity')
        if 'status' in output and output['status'] not in definition['output_contract']['status']:
            violations.append('output.status.enum')
        if type(output.get('proposed_actions')) is list and any(type(action) is dict
                and action.get('executed') is True for action in output['proposed_actions']):
            violations.append('output.proposed_actions.execution_claim')
        results.append(dict(id=sample['id'], input_sha256=sha(sample['input_utf8'].encode()),
            output_sha256=sha(sample['output_utf8'].encode()), missing_input=missing_input,
            missing_output=missing_output, violations=violations,
            structural_conformance=not (missing_input or missing_output or violations)))
    return results


def build_report(raw, *, task_id, agent_id, capability_id, registry_sha256):
    owned = _owned_domains(registry_sha256, agent_id, capability_id)
    return dict(schema_version=RESULT_SCHEMA, case=CASE, case_version=VERSION,
        task_id=task_id, agent_id=agent_id, capability_id=capability_id,
        input_sha256=sha(raw), registry_sha256=registry_sha256,
        owned_domains_sha256=sha(canonical(owned)), samples=inspect_supplied(raw, owned),
        prose_semantics='NOT_ESTABLISHED', role_result_quality='NOT_ESTABLISHED',
        execution_authority='NOT_GRANTED', actual_service_health='UNKNOWN', certification='UNVERIFIED')


def execute_producer(task_id, *, actor, submitted_request, data_root, ledger,
        runtime, read_runtime, source_revision, runtime_image_id, registry_sha256):
    require(_slot.acquire(blocking=False), 'OWNED_CONTRACT_BUSY')
    try:
        from .agent_cert_fresh_input import read_task
        from .agent_cert_recovery_events import retrieve_original_artifact
        from .action_records import ActionRecord, DirectExecutor
        from .artifact_factory import ArtifactFactory
        start = time.monotonic(); began = datetime.now(timezone.utc)
        root = _path(data_root); bound = _bindings(task_id, runtime, source_revision, runtime_image_id, registry_sha256)
        capability = submitted_request['capability']; fixed = canonical_case(actor, capability)
        require(canonical(submitted_request) == canonical(fixed['request']), 'OWNED_CONTRACT_REQUEST_DRIFT')
        original = read_task(root, task_id, submitted_request, bound, deadline=start+5)
        created = _utc(original['created_at'])
        def remaining():
            left = min(5, start+5-time.monotonic(), 5-(datetime.now(timezone.utc)-created).total_seconds())
            require(left > 0, 'OWNED_CONTRACT_TASK_BUDGET_EXHAUSTED')
            return left
        remaining()
        require(canonical(read_runtime()) == canonical(bound) and registry_digest() == registry_sha256,
            'OWNED_CONTRACT_RUNTIME_DRIFT')
        require(not any(parse(line.encode()).get('task_id') == task_id for line in _ledger_lines(root)),
            'OWNED_CONTRACT_ALREADY_ATTEMPTED')
        with ledger.pending.all_tasks_done:
            require(ledger.pending.unfinished_tasks == 0, 'OWNED_CONTRACT_PRIOR_ACTION_PENDING')
        factory = ArtifactFactory(_path(root/'artifacts')); executor = DirectExecutor(ledger)
        def create(raw):
            remaining()
            metadata = factory.create(kind='json', content=raw.decode(), task_id=task_id,
                creator=actor, provenance=PROVENANCE, runtime_revision=source_revision)
            original_metadata, original_raw = retrieve_original_artifact(root, metadata['artifact_id'])
            require(canonical(original_metadata) == canonical(metadata) and original_raw == raw,
                'OWNED_CONTRACT_ARTIFACT_READBACK')
            return metadata
        def record(step, tool, **parameters):
            return ActionRecord(task_id, actor, action_type(step), tool, target='artifact.json',
                parameters_summary=dict(case=CASE, case_version=VERSION, capability_id=capability,
                    registry_sha256=registry_sha256, submitted_request_sha256=sha(canonical(submitted_request)),
                    read_only_observations=True, **parameters))
        raw = submitted_request['context'].encode()
        setup_record = record('setup','action.propose',content_sha256=sha(raw))
        setup = executor.execute(setup_record, lambda: create(raw))
        read_record = record('read','provided_context.read', setup_artifact_id=setup['artifact_id'],
            expected_sha256=sha(raw), relative_path='artifact.json')
        def read():
            remaining()
            metadata, content = retrieve_original_artifact(root, setup['artifact_id'])
            require(canonical(metadata) == canonical(setup) and content == raw, 'OWNED_CONTRACT_INPUT_DRIFT')
            return dict(source_sha256=sha(content), result=content.decode())
        actual = executor.execute(read_record, read)
        result_record = record('result','action.propose', input_sha256=sha(raw))
        output = executor.execute(result_record, lambda: create(canonical(build_report(actual['result'].encode(),
            task_id=task_id, agent_id=actor, capability_id=capability, registry_sha256=registry_sha256))))
        require(ledger.flush(timeout=remaining()) is True, 'OWNED_CONTRACT_DURABILITY_REQUIRED')
        require(registry_digest() == registry_sha256 and canonical(read_runtime()) == canonical(bound),
            'OWNED_CONTRACT_RUNTIME_DRIFT')
        remaining()
        event = dict(case=CASE, case_version=VERSION, input_artifact_metadata=setup,
            action_ids=dict(setup=setup_record.action_id,read=read_record.action_id,result=result_record.action_id),
            started_at=began.isoformat(), completed_at=datetime.now(timezone.utc).isoformat(),
            original_task_created_at=original['created_at'], submitted_request_sha256=sha(canonical(submitted_request)),
            registry_sha256=registry_sha256, durable_action_delivery=True)
        return dict(task_id=task_id,state='COMPLETED',artifact=output,model_calls=0,
            execution_model='DETERMINISTIC',agent_id=actor,capability=capability,
            runtime_source_revision=source_revision,owned_contract_event=event)
    except OwnedContractError:
        raise
    except Exception:
        raise OwnedContractError('OWNED_CONTRACT_EXECUTION_REJECTED') from None
    finally:
        _slot.release()


def execute_review(task_id, *, actor, submitted_request, data_root, ledger,
        runtime, read_runtime, source_revision, runtime_image_id, registry_sha256):
    """Persist a separate authenticated peer's structural grade, not role approval."""
    require(_slot.acquire(blocking=False), 'OWNED_CONTRACT_BUSY')
    try:
        from .agent_cert_fresh_input import read_task
        from .agent_cert_owned_contract_review import validate_original_execution
        from .agent_cert_recovery_events import retrieve_original_artifact
        from .action_records import ActionRecord, DirectExecutor
        from .artifact_factory import ArtifactFactory
        start = time.monotonic(); began = datetime.now(timezone.utc)
        root = _path(data_root); bound = _bindings(task_id,runtime,source_revision,runtime_image_id,registry_sha256)
        envelope = parse(submitted_request['context'].encode(),80000)
        require(type(envelope) is dict and set(envelope) == {'execution','execution_sha256','nonce'},
            'OWNED_CONTRACT_REVIEW_FIELDS')
        execution = envelope['execution']
        expected = review_request(execution,envelope['nonce'])
        require(canonical(expected) == canonical(submitted_request)
            and envelope['execution_sha256'] == sha(canonical(execution)), 'OWNED_CONTRACT_REVIEW_REQUEST_DRIFT')
        subject = execution['case_spec']['agent_id']; cap = execution['case_spec']['capability_id']
        peer, peer_capability = reviewer(subject,cap)
        require(actor == peer and actor != subject and submitted_request['capability'] == peer_capability,
            'OWNED_CONTRACT_DISTINCT_REVIEWER_REQUIRED')
        original = read_task(root,task_id,submitted_request,bound,deadline=start+5)
        created = _utc(original['created_at'])
        def remaining():
            left = min(5,start+5-time.monotonic(),5-(datetime.now(timezone.utc)-created).total_seconds())
            require(left > 0,'OWNED_CONTRACT_REVIEW_TASK_BUDGET_EXHAUSTED')
            return left
        require(registry_digest() == registry_sha256 and canonical(read_runtime()) == canonical(bound),
            'OWNED_CONTRACT_RUNTIME_DRIFT')
        require(not any(parse(line.encode()).get('task_id') == task_id for line in _ledger_lines(root)),
            'OWNED_CONTRACT_ALREADY_ATTEMPTED')
        with ledger.pending.all_tasks_done:
            require(ledger.pending.unfinished_tasks == 0,'OWNED_CONTRACT_PRIOR_ACTION_PENDING')
        joined = validate_original_execution(execution,root=root,runtime=bound,
            registry_sha256=registry_sha256,deadline=time.monotonic()+remaining())
        raw = canonical(dict(schema_version='prime.owned-contract-review.v1',case=CASE,case_version=VERSION,
            task_id=task_id,agent_id=actor,capability_id=peer_capability,subject_task_id=execution['dispatch']['task_id'],
            subject_agent_id=subject,subject_capability_id=cap,execution_sha256=envelope['execution_sha256'],
            original_join=joined,grade_scope='STRUCTURAL_INSPECTION_ONLY',prose_semantics='NOT_ESTABLISHED',
            role_result_quality='NOT_ESTABLISHED',certification='UNVERIFIED'))
        factory = ArtifactFactory(_path(root/'artifacts'))
        record = ActionRecord(task_id,actor,REVIEW_ACTION,'action.propose',target='artifact.json',
            parameters_summary=dict(case=CASE,case_version=VERSION,subject_task_id=execution['dispatch']['task_id'],
                execution_sha256=envelope['execution_sha256'],registry_sha256=registry_sha256,
                submitted_request_sha256=sha(canonical(submitted_request)),read_only_observations=True))
        def create():
            remaining()
            metadata = factory.create(kind='json',content=raw.decode(),task_id=task_id,creator=actor,
                provenance=PROVENANCE,runtime_revision=source_revision)
            actual, content = retrieve_original_artifact(root,metadata['artifact_id'])
            require(canonical(actual) == canonical(metadata) and content == raw,'OWNED_CONTRACT_REVIEW_READBACK')
            return metadata
        artifact = DirectExecutor(ledger).execute(record,create)
        require(ledger.flush(timeout=remaining()) is True,'OWNED_CONTRACT_DURABILITY_REQUIRED')
        require(registry_digest() == registry_sha256 and canonical(read_runtime()) == canonical(bound),
            'OWNED_CONTRACT_RUNTIME_DRIFT')
        remaining()
        return dict(task_id=task_id,state='COMPLETED',artifact=artifact,model_calls=0,execution_model='DETERMINISTIC',
            agent_id=actor,capability=peer_capability,runtime_source_revision=source_revision,
            owned_contract_review=dict(action_id=record.action_id,started_at=began.isoformat(),
                completed_at=datetime.now(timezone.utc).isoformat(),durable_action_delivery=True,
                original_task_created_at=original['created_at'],certification='UNVERIFIED'))
    except OwnedContractError:
        raise
    except Exception:
        raise OwnedContractError('OWNED_CONTRACT_REVIEW_REJECTED') from None
    finally:
        _slot.release()
