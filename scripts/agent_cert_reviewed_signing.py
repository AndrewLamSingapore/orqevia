"""One protected, artifact-bound role case; never an L7 award or Azure login.

The protected caller owns the independently reviewed artifact hashes, exact
runtime identity and public key pin. None may be obtained from an executing
agent's submission. Only that caller may inject the existing Key Vault signing
operation. This module performs no network, credential loading or file writes.
Execution source and original reviewer code remain distinct from later protected
verifier code. A newly verified record does not change original event/review time.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import uuid

from app.agent_cert_azure_es256 import AzureES256CertificationVerifier
from app.agent_cert_azure_signer import ProtectedAzureES256Signer, _read_subject_artifact
from app.agent_cert_ed25519 import _REQUIRED_RECORD_FIELDS
from app.agent_cert_role_group_two import _CASES as GROUP_TWO_CASES
from app.agent_cert_role_review import (
    canonical_case_spec, canonical_role_spec, review_case_output, review_role_output,
)
from app.agent_certification import LOGIC_SIGNALS
from app.agent_registry import agent_record, canonical_agent_id, responsibility_owner


SERVICE = 'svc.cert-verifier.independent'
_REV = re.compile(r'[0-9a-f]{40}\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_IMAGE = re.compile(r'sha256:[0-9a-f]{64}\Z')
_PROVIDER = re.compile(r'[A-Za-z0-9_-]{1,80}\Z')
_EXECUTION_FIELDS = {'schema_version', 'agent_id', 'capability_id', 'dimension',
                     'test_case', 'source_revision', 'runtime_image_id',
                     'environment', 'executor_identity', 'case_spec', 'dispatch',
                     'job', 'transport'}
_JOB_FIELDS = {'id', 'agent', 'status', 'result', 'result_sha256', 'provider',
               'attempts', 'started_at', 'completed_at', 'error'}
_RECORD_FIELDS = set(_REQUIRED_RECORD_FIELDS) | {
    'review_evidence', 'review_evidence_sha256', 'review_run_id',
    'review_test_version', 'review_source_revision', 'reviewer_code_revision',
}


class CertificationReviewError(ValueError):
    """A fixed public code; never interpolate model, credential or error text."""


def _deny(code):
    raise CertificationReviewError(code) from None


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _deny('DUPLICATE_FIELD')
        result[key] = value
    return result


def _finite(value):
    result = float(value)
    if not math.isfinite(result):
        _deny('NONFINITE_NUMBER')
    return result


def _json(raw):
    if type(raw) is not bytes or not 1 <= len(raw) <= 1024 * 1024:
        _deny('ARTIFACT_SIZE_INVALID')
    try:
        result = json.loads(raw, object_pairs_hook=_unique, parse_float=_finite,
                            parse_constant=lambda _: _deny('NONFINITE_NUMBER'))
        if type(result) is not dict:
            _deny('ARTIFACT_OBJECT_REQUIRED')
        return result
    except CertificationReviewError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        _deny('ARTIFACT_JSON_INVALID')


def _utc(value):
    if type(value) is not str or not 1 <= len(value) <= 40:
        _deny('EXECUTION_TIME_INVALID')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
        return parsed
    except ValueError:
        _deny('EXECUTION_TIME_INVALID')


def _role_oracle(agent, result):
    # Reuse the actual domain oracles and their exact supplied facts. No
    # generic pass fixture, fence stripping or model self-assessment is allowed.
    valid, errors = review_role_output(agent, f'responsibility.{agent}', result)
    if valid is not True or errors:
        _deny('CASE_ORACLE_FAILED')


def _role_spec(agent):
    # Group two defines a distinct strict-json request. It is not interchangeable
    # with challenge()'s older generic prompt for the same registered role.
    return canonical_role_spec(agent, f'responsibility.{agent}')


def _case_fields(spec):
    case_id = spec.get('case') if type(spec) is dict else None
    if type(case_id) is not str or case_id.count(':') != 1:
        _deny('CASE_ORACLE_UNSUPPORTED')
    return tuple(case_id.split(':'))


def _case_spec(row):
    dimension, test_case = row.get('dimension'), row.get('test_case')
    if type(dimension) is not str or type(test_case) is not str:
        _deny('CASE_ORACLE_UNSUPPORTED')
    try:
        return canonical_case_spec(row['agent_id'], row['capability_id'], dimension + ':' + test_case)
    except (ValueError, TypeError, KeyError):
        _deny('CASE_ORACLE_UNSUPPORTED')


def _oracle_id(agent, spec=None):
    if agent == 'a19' and spec is not None and spec.get('case') == 'cross_agent_conflict:complete':
        from app.agent_cert_cross_conflict_events import ORACLE
        return ORACLE
    if agent == 'a19' and spec is not None and spec.get('case') == 'unauthorized_rejection:owner_only':
        from app.agent_cert_owner_referral_events import ORACLE
        return ORACLE
    if agent == 'a19' and spec is not None and spec.get('case') == 'conflict_resolution:complete':
        from app.agent_cert_conflict_events import ORACLE
        return ORACLE
    if agent == 'a19' and spec is not None and spec.get('case') == 'recovery:complete':
        from app.agent_cert_recovery_events import ORACLE
        return ORACLE
    if spec is not None and spec.get('case') == 'baseline:initialization':
        from app.agent_cert_initialization import initialization_oracle_id
        return initialization_oracle_id(agent, spec['capability_id'])
    if agent == 'a19' and spec is not None and spec.get('case') == 'baseline:identity':
        from app.agent_cert_identity_review import ORACLE_ID
        return ORACLE_ID
    if spec is not None and spec.get('case') == 'baseline:identity':
        from app.agent_cert_owned_identity import ORACLE_ID
        return ORACLE_ID
    if spec is not None:
        from app.agent_cert_fresh_input import CASES as FRESH_CASES, ORACLE_ID as FRESH_ORACLE
        if spec.get('case') in FRESH_CASES:
            return FRESH_ORACLE
        from app.agent_cert_tool_events import SUPPORTED_CASES as TOOL_CASES, oracle_id
        if spec.get('case') in TOOL_CASES:
            return oracle_id(spec['case'])
        from app.agent_cert_authority_events import SUPPORTED_CASES as AUTHORITY_CASES, ORACLE_ID as AUTHORITY_ORACLE
        if spec.get('case') in AUTHORITY_CASES:
            return AUTHORITY_ORACLE
        from app.agent_cert_artifact_events import SUPPORTED_CASES, oracle_id
        if spec.get('case') in SUPPORTED_CASES:
            return oracle_id(spec['case'])
    if spec is not None and spec.get('case') != 'role:normal':
        from app.agent_cert_a19_baseline import SUPPORTED_CASES as BASELINE_CASES, ORACLE_ID as BASELINE_ORACLE
        if spec.get('case') in BASELINE_CASES:
            return BASELINE_ORACLE
        from app.agent_cert_a19_general import SUPPORTED_CASES, ORACLE_ID as GENERAL_ORACLE
        if spec.get('case') in SUPPORTED_CASES:
            return GENERAL_ORACLE
        from app.agent_cert_a19_cases import ORACLE_ID
        return ORACLE_ID
    if spec is not None:
        from app.agent_cert_secondary_roles import SUPPORTED_CAPABILITIES, ORACLE_ID
        if spec.get('capability_id') in SUPPORTED_CAPABILITIES:
            return ORACLE_ID
    return 'group_two_exact_role_oracle/v1' if agent in GROUP_TWO_CASES else 'existing.role-normal.v1'


def _review_version(agent, spec=None):
    # Official oracle IDs may contain '/'; the protected signer's provenance
    # grammar deliberately does not. Keep the domain oracle identity intact in
    # observations and bind a separate, fixed signing-provenance version.
    if spec is not None and spec.get('case') != 'role:normal':
        return _oracle_id(agent, spec)
    if spec is not None:
        from app.agent_cert_secondary_roles import SUPPORTED_CAPABILITIES, ORACLE_ID
        if spec.get('capability_id') in SUPPORTED_CAPABILITIES:
            return ORACLE_ID
    return 'group_two_exact_role_oracle.v1' if agent in GROUP_TWO_CASES else None


def _uuid(value):
    try:
        return type(value) is str and str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _review_action_chain(raw_events, *, dispatch, metadata, reviewed_at, certified_at):
    if type(raw_events) is not list or not 2 <= len(raw_events) <= 128:
        _deny('REVIEW_ACTION_CHAIN_REQUIRED')
    events = []
    previous = None
    for raw in raw_events:
        if type(raw) is not str or not 1 <= len(raw.encode('utf-8')) <= 64 * 1024:
            _deny('REVIEW_ACTION_CHAIN_INVALID')
        event = _json(raw.encode('utf-8'))
        if (type(event.get('sequence')) is not int or not 1 <= event['sequence'] < 2 ** 63 or
                type(event.get('sha256')) is not str or not _SHA.fullmatch(event['sha256']) or
                type(event.get('previous_sha256')) is not str or not _SHA.fullmatch(event['previous_sha256']) or
                _sha(_canonical({key: value for key, value in event.items() if key != 'sha256'})) != event['sha256']):
            _deny('REVIEW_ACTION_CHAIN_INVALID')
        if previous is not None and (event['sequence'] != previous['sequence'] + 1 or
                                     event['previous_sha256'] != previous['sha256']):
            _deny('REVIEW_ACTION_CHAIN_INVALID')
        events.append(event)
        previous = event
    action_id = dispatch['review_action_id']
    owned = [event for event in events if event.get('action_id') == action_id]
    if len(owned) != 2 or owned[0] is not events[0] or owned[1] is not events[-1]:
        _deny('REVIEW_ACTION_CHAIN_INVALID')
    base = {
        'task_id': dispatch['task_id'], 'agent_id': dispatch['agent_id'],
        'action_type': 'agent.certification.role.review', 'tool': 'artifact-factory',
        'target': '', 'classification': 'R0',
        'parameters_summary': {'schema_version': 'prime.agent-cert-role-review.v1',
                               'read_only_observations': True},
        'model_backend': 'deterministic', 'execution_location': 'local',
        'parent_agent': None, 'workflow_id': None, 'action_id': action_id,
    }
    common = set(base) | {'phase', 'timestamp', 'sequence', 'previous_sha256', 'sha256'}
    start, completed = owned
    if (set(start) != common or set(completed) != common | {'success', 'duration_ms', 'result_summary'} or
            any(_canonical(event.get(key)) != _canonical(value)
                for event in owned for key, value in base.items()) or
            start['phase'] != 'started' or completed['phase'] != 'completed' or
            completed['success'] is not True or
            type(completed['duration_ms']) not in {int, float} or
            not math.isfinite(completed['duration_ms']) or not 0 <= completed['duration_ms'] <= 120_000 or
            _canonical(completed['result_summary']) != _canonical({
                'type': 'dict', 'artifact_id': metadata['artifact_id'],
                'sha256': metadata['sha256'], 'location': 'artifact.json'}) or
            not reviewed_at <= _utc(start['timestamp']) <= _utc(metadata['timestamp']) <=
                _utc(completed['timestamp']) <= certified_at):
        _deny('REVIEW_ACTION_BINDING_INVALID')


def _cloud_execution(execution, *, spec, cloud_binding, cloud_policy,
                     expected_owner_policy_sha256, source_revision):
    from app.agent_cert_transport import validate_cloud_binding
    try:
        checked = validate_cloud_binding(spec, cloud_policy, cloud_binding,
            expected_source_revision=source_revision,
            expected_policy_sha256=expected_owner_policy_sha256)
    except (ValueError, TypeError, KeyError, AttributeError):
        _deny('PROTECTED_CLOUD_POLICY_REQUIRED')
    prepared = checked.receipt()
    proof = execution.get('cloud_transport')
    if (type(proof) is not dict or set(proof) != {'binding', 'queue_route'} or
            _canonical(proof['binding']) != _canonical(prepared)):
        _deny('CLOUD_TRANSPORT_BINDING_INVALID')
    route = proof['queue_route']
    if type(route) is not dict or set(route) != {
            'preferred_provider', 'model', 'allow_cloud', 'data_classification', 'task_class',
            'classification', 'max_retries', 'max_cost_usd', 'prompt_sha256',
            'input_tokens', 'output_tokens', 'actual_cost_usd'}:
        _deny('CLOUD_QUEUE_BINDING_INVALID')
    fixed = {'preferred_provider': prepared['provider_id'], 'model': prepared['model'],
             'allow_cloud': 1, 'data_classification': 'CLOUD_PERMITTED',
             'task_class': prepared['task_class'], 'classification': 'R0', 'max_retries': 0,
             'max_cost_usd': checked.request()['max_cost_usd']}
    if (any(_canonical(route.get(key)) != _canonical(value) for key, value in fixed.items()) or
            type(route['prompt_sha256']) is not str or not _SHA.fullmatch(route['prompt_sha256']) or
            type(route['input_tokens']) is not int or not 0 <= route['input_tokens'] <= prepared['limits']['context_tokens'] or
            type(route['output_tokens']) is not int or not 0 <= route['output_tokens'] <= prepared['limits']['output_tokens'] or
            type(route['actual_cost_usd']) not in {int, float} or not math.isfinite(route['actual_cost_usd']) or
            not 0 <= route['actual_cost_usd'] <= prepared['limits']['max_cost_usd'] or
            execution['job']['provider'] != prepared['provider_id'] or execution['job']['attempts'] != 1):
        _deny('CLOUD_QUEUE_BINDING_INVALID')
    return route['prompt_sha256']


def _reviewer_execution(proof, *, row, job, spec, execution_sha256,
                        source_revision, runtime_image_id, now, queue_prompt_sha256=None):
    """Bind a real registered review artifact; a reviewer label is not execution."""
    if type(proof) is not dict or set(proof) != {
            'dispatch', 'artifact_content_utf8', 'transport', 'action_records'}:
        _deny('REGISTERED_REVIEW_EXECUTION_REQUIRED')
    subject = row['agent_id']
    dimension, test_case = _case_fields(spec)
    if (row.get('dimension', dimension) != dimension or
            row.get('test_case', test_case) != test_case):
        _deny('REGISTERED_REVIEW_CONTENT_INVALID')
    actor = 'a18' if subject == 'a26' else 'a26'
    capability = 'responsibility.a27' if subject == 'a26' else 'responsibility.a26'
    dispatch = proof['dispatch']
    if (type(dispatch) is not dict or set(dispatch) != {
            'task_id', 'state', 'artifact', 'model_calls', 'execution_model', 'agent_id',
            'capability', 'runtime_source_revision', 'review_action_id',
            'review_action_durable', 'certification'} or
            row['verifier'] != actor or dispatch['agent_id'] != actor or
            dispatch['capability'] != capability or not _uuid(dispatch['task_id']) or
            dispatch['task_id'] == job['id'] or not _uuid(dispatch['review_action_id']) or
            dispatch['state'] != 'COMPLETED' or type(dispatch['model_calls']) is not int or
            dispatch['model_calls'] != 0 or dispatch['execution_model'] != 'DETERMINISTIC' or
            dispatch['runtime_source_revision'] != source_revision or
            dispatch['review_action_durable'] is not True or dispatch['certification'] != 'UNVERIFIED'):
        _deny('REGISTERED_REVIEW_DISPATCH_INVALID')
    transport = {'authentication': 'OWNER_AUTHENTICATED', 'dispatch_http_status': 202,
                 'artifact_http_status': 200, 'runtime_source_revision': source_revision,
                 'actual_runtime_image': runtime_image_id}
    if _canonical(proof['transport']) != _canonical(transport):
        _deny('REGISTERED_REVIEW_TRANSPORT_INVALID')
    raw = proof['artifact_content_utf8']
    if type(raw) is not str or not 1 <= len(raw.encode('utf-8')) <= 64 * 1024:
        _deny('REGISTERED_REVIEW_ARTIFACT_INVALID')
    content = _json(raw.encode('utf-8'))
    metadata = dispatch['artifact']
    if (type(metadata) is not dict or set(metadata) != {
            'artifact_id', 'task_id', 'type', 'creator_agents', 'timestamp', 'version',
            'provenance', 'runtime_revision', 'validation_state', 'content_validation',
            'location', 'sha256', 'bytes', 'delivery_state'} or
            type(metadata['artifact_id']) is not str or not re.fullmatch(r'[0-9a-f]{32}', metadata['artifact_id']) or
            metadata['task_id'] != dispatch['task_id'] or metadata['creator_agents'] != [actor] or
            metadata['type'] != 'json' or metadata['version'] != '1.0.0' or
            metadata['provenance'] != 'Deterministic computation; zero model calls' or
            metadata['runtime_revision'] != source_revision or metadata['validation_state'] != 'STRUCTURE_VALIDATED' or
            metadata['content_validation'] != 'Not independently established by structural validation' or
            metadata['location'] != 'artifact.json' or metadata['sha256'] != _sha(raw.encode('utf-8')) or
            type(metadata['bytes']) is not int or metadata['bytes'] != len(raw.encode('utf-8')) or
            metadata['delivery_state'] != 'AVAILABLE'):
        _deny('REGISTERED_REVIEW_ARTIFACT_INVALID')
    expected = {
        'schema_version': 'prime.agent-cert-role-review.v1', 'task_id': dispatch['task_id'],
        'reviewer_id': actor, 'reviewer_capability_id': capability,
        'subject_agent_id': subject, 'subject_capability_id': row['capability_id'],
        'dimension': dimension, 'test_case': test_case, 'source_revision': source_revision,
        'runtime_image_id': runtime_image_id, 'subject_job_id': job['id'],
        'execution_evidence_sha256': execution_sha256, 'case_spec_sha256': _sha(_canonical(spec)),
        'result_sha256': job['result_sha256'], 'oracle_id': _oracle_id(subject, spec),
        'test_result': 'PASS', 'review_errors': [], 'model_calls': 0,
        'execution_model': 'DETERMINISTIC', 'subject_execution_verification': 'QUEUE_AND_OBJECTIVE_JOINED',
        'certification': 'UNVERIFIED',
    }
    if (set(content) != set(expected) | {'review_nonce', 'reviewed_at', 'subject_domain_join'} or
            any(_canonical(content.get(key)) != _canonical(value) for key, value in expected.items()) or
            not _uuid(content['review_nonce'])):
        _deny('REGISTERED_REVIEW_CONTENT_INVALID')
    join = content['subject_domain_join']
    if (type(join) is not dict or set(join) != {
            'objective_id', 'objective_revision', 'job_id', 'runtime', 'observed_at',
            'execution_metadata_sha256', 'prompt_sha256', 'case_spec_sha256'} or not _uuid(join['objective_id']) or
            join['objective_id'] in {job['id'], dispatch['task_id']} or join['job_id'] != job['id'] or
            type(join['objective_revision']) is not int or not 0 <= join['objective_revision'] <= 10_000 or
            type(join['execution_metadata_sha256']) is not str or not _SHA.fullmatch(join['execution_metadata_sha256']) or
            type(join['prompt_sha256']) is not str or not _SHA.fullmatch(join['prompt_sha256']) or
            (queue_prompt_sha256 is not None and join['prompt_sha256'] != queue_prompt_sha256) or
            join['case_spec_sha256'] != _sha(_canonical(spec))):
        _deny('REGISTERED_REVIEW_DOMAIN_JOIN_INVALID')
    runtime = join['runtime']
    if (type(runtime) is not dict or set(runtime) != {'host_id', 'source_revision', 'version', 'image_digest'} or
            runtime['source_revision'] != source_revision or runtime['image_digest'] != runtime_image_id or
            any(type(runtime[key]) is not str or runtime[key] == 'UNKNOWN' or
                not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,95}', runtime[key])
                for key in ('host_id', 'version'))):
        _deny('REGISTERED_REVIEW_DOMAIN_JOIN_INVALID')
    reviewed_at, observed_at = _utc(content['reviewed_at']), _utc(join['observed_at'])
    certified_at = _utc(row['certified_at'])
    if not (_utc(job['completed_at']) <= reviewed_at <= observed_at <= _utc(metadata['timestamp']) <= certified_at <= now):
        _deny('REGISTERED_REVIEW_TIME_INVALID')
    _review_action_chain(proof['action_records'], dispatch=dispatch, metadata=metadata,
                         reviewed_at=reviewed_at, certified_at=certified_at)


def _fresh_input_review(row,primary,review,*,source_revision,runtime_image_id,reviewer_code_revision,now):
    from app import agent_cert_fresh_input as fresh
    from app.agent_registry import REGISTRY_PATH
    case = str(row.get('dimension'))+':'+str(row.get('test_case'))
    if (case not in fresh.CASES or row.get('agent_id') != 'a19'
        or row.get('capability_id') != 'responsibility.a19' or row.get('verifier') != 'a26'
        or row.get('executor_identity') != 'a19' or row.get('authority_scope') != agent_record('a19')['authority']
        or row.get('test_result') != 'PASS' or row.get('test_version') != fresh.CASE_VERSION
        or row.get('review_test_version') != fresh.ORACLE_ID or row.get('source_revision') != source_revision
        or row.get('review_source_revision') != source_revision or row.get('reviewer_code_revision') != reviewer_code_revision
        or any(type(row.get(k)) is not str or not 1 <= len(row[k]) <= 100
            for k in ('certification_test','review_run_id'))):
        _deny('EXECUTION_INPUT_RECORD_BINDING_INVALID')
    execution,envelope = _json(primary),_json(review)
    registry = _sha(REGISTRY_PATH.read_bytes())
    try:
        comparison = execution['comparison']
        reviewed_at = _utc(comparison['objective_read'][1]['execution_metadata']['updated_at'])
        if reviewed_at > now:_deny('EXECUTION_INPUT_REVIEW_TIME_INVALID')
        join = fresh.validate_execution(execution,source_revision=source_revision,
            runtime_image_id=runtime_image_id,registry_sha256=registry,now=reviewed_at)
        if execution['case_spec']['case'] != case:_deny('EXECUTION_INPUT_CASE_MISMATCH')
        expected = dict(schema_version=fresh.REVIEW_SCHEMA,execution_sha256=_sha(primary),case=case,
            registry_sha256=registry,reviewer_code_revision=reviewer_code_revision,review_run_id=row['review_run_id'],
            oracle_id=fresh.ORACLE_ID,oracle_pass=True,subject_agent_id='a19',subject_capability_id='responsibility.a19',
            reviewer_agent_id='a26',reviewer_capability_id='responsibility.a26',subject_domain_join=join,
            reviewer_execution=comparison,model_calls=0,certification='UNVERIFIED',
            service_confirmation='NOT_PERFORMED',live_unfamiliarity='NOT_PROVEN')
        if _canonical(envelope) != _canonical(expected):_deny('EXECUTION_INPUT_ORIGINAL_REVIEW_UNBOUND')
        if not (_utc(join['completed_at']) <= reviewed_at <= _utc(row['certified_at'])
            <= _utc(row['last_revalidated']) <= now < _utc(row['expires_at'])):
            _deny('EXECUTION_INPUT_RECORD_TIME_INVALID')
    except (KeyError,TypeError,ValueError,UnicodeError):
        _deny('EXECUTION_INPUT_ORIGINAL_REVIEW_INVALID')


def _review(row, primary, review, *, source_revision, runtime_image_id,
            reviewer_code_revision, now, cloud_binding=None, cloud_policy=None,
            expected_owner_policy_sha256=None):
    if (row.get('dimension'),row.get('test_case'))==('cross_agent_conflict','complete'):
        if any(value is not None for value in (cloud_binding,cloud_policy,expected_owner_policy_sha256)):
            _deny('CROSS_CONFLICT_CLOUD_TRANSPORT_FORBIDDEN')
        return _cross_conflict_review(row,primary,review,source_revision=source_revision,runtime_image_id=runtime_image_id,
            reviewer_code_revision=reviewer_code_revision,now=now)
    if (row.get('dimension'),row.get('test_case'))==('unauthorized_rejection','owner_only'):
        if any(value is not None for value in (cloud_binding,cloud_policy,expected_owner_policy_sha256)):
            _deny('OWNER_REFERRAL_CLOUD_OR_POLICY_FORBIDDEN')
        return _owner_referral_review(row,primary,review,source_revision=source_revision,
            runtime_image_id=runtime_image_id,reviewer_code_revision=reviewer_code_revision,now=now)
    if (row.get('dimension'),row.get('test_case'))==('conflict_resolution','complete'):
        if any(value is not None for value in (cloud_binding,cloud_policy,expected_owner_policy_sha256)):
            _deny('CONFLICT_CLOUD_TRANSPORT_FORBIDDEN')
        return _conflict_review(row,primary,review,source_revision=source_revision,runtime_image_id=runtime_image_id,
            reviewer_code_revision=reviewer_code_revision,now=now)
    if (row.get('dimension'), row.get('test_case')) == ('recovery', 'complete'):
        if any(value is not None for value in (cloud_binding, cloud_policy, expected_owner_policy_sha256)):
            _deny('RECOVERY_CLOUD_TRANSPORT_FORBIDDEN')
        return _recovery_review(row, primary, review, source_revision=source_revision,
            runtime_image_id=runtime_image_id, reviewer_code_revision=reviewer_code_revision, now=now)
    from app.agent_cert_fresh_input import CASES as FRESH_CASES
    if str(row.get('dimension'))+':'+str(row.get('test_case')) in FRESH_CASES:
        if any(value is not None for value in (cloud_binding,cloud_policy,expected_owner_policy_sha256)):
            _deny('EXECUTION_INPUT_CLOUD_TRANSPORT_FORBIDDEN')
        return _fresh_input_review(row,primary,review,source_revision=source_revision,
            runtime_image_id=runtime_image_id,reviewer_code_revision=reviewer_code_revision,now=now)
    from app.agent_cert_tool_events import SUPPORTED_CASES as TOOL_CASES
    if str(row.get('dimension')) + ':' + str(row.get('test_case')) in TOOL_CASES:
        if any(value is not None for value in (cloud_binding, cloud_policy, expected_owner_policy_sha256)):
            _deny('TOOL_CLOUD_TRANSPORT_FORBIDDEN')
        return _contract_event_review(row, primary, review, source_revision=source_revision,
            runtime_image_id=runtime_image_id, reviewer_code_revision=reviewer_code_revision,
            now=now, initialization=False, tool=True)
    from app.agent_cert_authority_events import SUPPORTED_CASES as AUTHORITY_CASES
    if str(row.get('dimension')) + ':' + str(row.get('test_case')) in AUTHORITY_CASES:
        if any(value is not None for value in (cloud_binding, cloud_policy, expected_owner_policy_sha256)):
            _deny('AUTHORITY_CLOUD_TRANSPORT_FORBIDDEN')
        return _contract_event_review(row, primary, review, source_revision=source_revision,
            runtime_image_id=runtime_image_id, reviewer_code_revision=reviewer_code_revision,
            now=now, initialization=False, authority=True)
    if row.get('dimension') == 'baseline' and row.get('test_case') in {'identity', 'initialization'}:
        if any(value is not None for value in (cloud_binding, cloud_policy, expected_owner_policy_sha256)):
            _deny('IDENTITY_CLOUD_TRANSPORT_FORBIDDEN')
        return _contract_event_review(row, primary, review, source_revision=source_revision,
            runtime_image_id=runtime_image_id, reviewer_code_revision=reviewer_code_revision,
            now=now, initialization=row['test_case'] == 'initialization')
    from app.agent_cert_artifact_events import SUPPORTED_CASES as ARTIFACT_CASES
    if str(row.get('dimension')) + ':' + str(row.get('test_case')) in ARTIFACT_CASES:
        if any(value is not None for value in (cloud_binding, cloud_policy, expected_owner_policy_sha256)):
            _deny('ARTIFACT_CLOUD_TRANSPORT_FORBIDDEN')
        return _contract_event_review(row, primary, review, source_revision=source_revision,
            runtime_image_id=runtime_image_id, reviewer_code_revision=reviewer_code_revision,
            now=now, initialization=False, artifact=True)
    execution = _json(primary)
    envelope = _json(review)
    cloud_requested = any(value is not None for value in (
        cloud_binding, cloud_policy, expected_owner_policy_sha256))
    if set(execution) != _EXECUTION_FIELDS | ({'cloud_transport'} if cloud_requested else set()):
        _deny('EXECUTION_FIELDS_INVALID')
    agent = row.get('agent_id')
    reviewer = row.get('verifier')
    if (type(agent) is not str or canonical_agent_id(agent) != agent or
            type(reviewer) is not str or canonical_agent_id(reviewer) != reviewer or
            reviewer == agent or row.get('executor_identity') != agent or
            row.get('capability_id') not in agent_record(agent)['capability_requirements'] or
            responsibility_owner(row.get('capability_id')) != agent or
            row.get('test_result') != 'PASS' or
            row.get('source_revision') != source_revision or
            row.get('review_source_revision') != source_revision or
            row.get('reviewer_code_revision') != reviewer_code_revision or
            row.get('authority_scope') != agent_record(agent)['authority'] or
            any(type(row.get(key)) is not str or not 1 <= len(row[key]) <= 100 for key in
                ('certification_test', 'test_version', 'review_run_id', 'review_test_version'))):
        _deny('RECORD_BINDING_INVALID')
    spec = _case_spec(row)
    version = _review_version(agent, spec)
    if version is not None and row['review_test_version'] != version:
        _deny('REVIEW_ORACLE_VERSION_INVALID')
    dimension, test_case = _case_fields(spec)
    if dimension == 'logic_quality':
        if _canonical(row.get('logic_signals')) != _canonical({LOGIC_SIGNALS[test_case]: 'PASS'}):
            _deny('LOGIC_SIGNALS_BINDING_INVALID')
    expected = {'schema_version': 'prime.agent-certification.execution.v1',
                'agent_id': agent, 'capability_id': row['capability_id'],
                'dimension': dimension, 'test_case': test_case,
                'source_revision': source_revision, 'runtime_image_id': runtime_image_id,
                'environment': 'LIVE_RUNTIME', 'executor_identity': row.get('executor_identity'),
                'case_spec': spec}
    if any(_canonical(execution.get(key)) != _canonical(value) for key, value in expected.items()):
        _deny('EXECUTION_BINDING_INVALID')
    # The official challenge is LOCAL_ONLY. Cloud trial evidence cannot be
    # silently promoted into this case by changing a label or its prompt.
    transport = {'authentication': 'OWNER_AUTHENTICATED', 'dispatch_http_status': 202,
                 'job_http_status': 200, 'provider_locality': 'CLOUD' if cloud_requested else 'LOCAL',
                 'runtime_source_revision': source_revision,
                 'actual_runtime_image': runtime_image_id}
    if _canonical(execution['transport']) != _canonical(transport):
        _deny('LIVE_AUTHORIZED_TRANSPORT_REQUIRED')
    job = execution['job']
    if (type(job) is not dict or set(job) != _JOB_FIELDS or
            type(job['id']) is not str or str(uuid.UUID(job['id'])) != job['id'] or
            job['agent'] != agent or job['status'] != 'completed' or
            not (job['error'] is None or (type(job['error']) is str and job['error'] == '')) or
            type(job['attempts']) is not int or not 1 <= job['attempts'] <= 3 or
            type(job['provider']) is not str or not _PROVIDER.fullmatch(job['provider']) or
            type(job['result']) is not str or not 1 <= len(job['result'].encode('utf-8')) <= 64 * 1024 or
            job['result_sha256'] != _sha(job['result'].encode('utf-8'))):
        _deny('COMPLETED_EXECUTION_INVALID')
    dispatch = {'capability': row['capability_id'], 'job': {'id': job['id'], 'agent': agent}}
    if _canonical(execution['dispatch']) != _canonical(dispatch):
        _deny('DISPATCH_JOB_MISMATCH')
    if not (_utc(job['started_at']) <= _utc(job['completed_at']) <=
            _utc(row.get('certified_at')) <= _utc(row.get('last_revalidated')) <= now <
            _utc(row.get('expires_at'))):
        _deny('EXECUTION_TIME_INVALID')
    observations = {
        'execution_job_id': job['id'], 'result_sha256': job['result_sha256'],
        'case_spec_sha256': _sha(_canonical(spec)), 'runtime_image_id': runtime_image_id,
        'reviewer_code_revision': reviewer_code_revision,
        'oracle_id': _oracle_id(agent, spec), 'oracle_pass': True,
    }
    supplied = envelope.get('observations')
    if (type(supplied) is not dict or set(supplied) != set(observations) | {'reviewer_execution'} or
            any(_canonical(supplied.get(key)) != _canonical(value) for key, value in observations.items())):
        _deny('REVIEW_OBSERVATIONS_INVALID')
    queue_prompt = _cloud_execution(execution, spec=spec, cloud_binding=cloud_binding,
        cloud_policy=cloud_policy, expected_owner_policy_sha256=expected_owner_policy_sha256,
        source_revision=source_revision) if cloud_requested else None
    _reviewer_execution(supplied['reviewer_execution'], row=row, job=job, spec=spec,
                        execution_sha256=_sha(primary), source_revision=source_revision,
                        runtime_image_id=runtime_image_id, now=now,
                        queue_prompt_sha256=queue_prompt)
    valid, errors = review_case_output(agent, row['capability_id'], spec['case'], job['result'])
    if valid is not True or errors:
        _deny('CASE_ORACLE_FAILED')
    return True


def _identity_review(row, primary, reviewed, *, source_revision, runtime_image_id,
                     reviewer_code_revision, now):
    return _contract_event_review(row, primary, reviewed, source_revision=source_revision,
        runtime_image_id=runtime_image_id, reviewer_code_revision=reviewer_code_revision,
        now=now, initialization=False)


def _contract_event_review(row, primary, reviewed, *, source_revision, runtime_image_id,
                           reviewer_code_revision, now, initialization, artifact=False, authority=False, tool=False):
    """Review a genuine artifact event; never manufacture a model queue job."""
    from app.agent_cert_identity_review import (
        ORACLE_ID, SCHEMA, action_span, validate_identity_execution,
    )
    from app.agent_registry import REGISTRY_PATH
    subject, capability = 'a19', 'responsibility.a19'
    reviewer, reviewer_capability = 'a26', 'responsibility.a26'
    dimension = 'baseline'
    owned_identity = (not (tool or authority or artifact or initialization)
        and (row.get('agent_id'), row.get('capability_id')) != ('a19', 'responsibility.a19'))
    if tool:
        from app.agent_cert_tool_events import oracle_id
        from app.agent_cert_role_review import (TOOL_REVIEW_SCHEMA as SCHEMA,
            TOOL_REVIEW_ACTION as review_action_type, tool_event_review_join as validate_event)
        event_case, dimension = row.get('test_case'), row.get('dimension')
        ORACLE_ID = oracle_id(str(dimension) + ':' + str(event_case))
    elif authority:
        from app.agent_cert_authority_events import ORACLE_ID
        from app.agent_cert_role_review import (AUTHORITY_REVIEW_SCHEMA as SCHEMA,
            AUTHORITY_REVIEW_ACTION as review_action_type, authority_event_review_join as validate_event)
        event_case, dimension = row.get('test_case'), row.get('dimension')
    elif artifact:
        from app.agent_cert_artifact_events import oracle_id
        from app.agent_cert_role_review import (ARTIFACT_REVIEW_SCHEMA as SCHEMA,
            ARTIFACT_REVIEW_ACTION as review_action_type, artifact_event_review_join as validate_event)
        event_case, dimension = row.get('test_case'), row.get('dimension')
        ORACLE_ID = oracle_id(str(dimension) + ':' + str(event_case))
    elif initialization:
        from app.agent_cert_initialization_review import (SCHEMA,
            validate_initialization_execution as validate_event)
        from app.agent_cert_initialization import initialization_reviewer, initialization_oracle_id
        subject, capability = row.get('agent_id'), row.get('capability_id')
        reviewer, reviewer_capability = initialization_reviewer(subject, capability)
        ORACLE_ID = initialization_oracle_id(subject, capability)
        event_case = 'initialization'
        review_action_type = 'agent.certification.initialization.review'
    elif owned_identity:
        from app.agent_cert_owned_identity import (REVIEW_SCHEMA as SCHEMA, ORACLE_ID,
            REVIEW_ACTION as review_action_type, identity_reviewer,
            validate_owned_identity_execution as validate_event)
        subject, capability = row.get('agent_id'), row.get('capability_id')
        reviewer, reviewer_capability = identity_reviewer(subject, capability)
        event_case = 'identity'
    else:
        validate_event = validate_identity_execution
        event_case = 'identity'
        review_action_type = 'agent.certification.identity.review'
    if (row.get('agent_id') != subject or row.get('capability_id') != capability
            or row.get('verifier') != reviewer or row.get('executor_identity') != subject
            or row.get('source_revision') != source_revision
            or row.get('review_source_revision') != source_revision
            or row.get('reviewer_code_revision') != reviewer_code_revision
            or row.get('authority_scope') != agent_record(subject)['authority']
            or row.get('test_result') != 'PASS' or row.get('review_test_version') != ORACLE_ID
            or any(type(row.get(key)) is not str or not 1 <= len(row[key]) <= 100
                   for key in ('certification_test', 'test_version', 'review_run_id'))):
        _deny('IDENTITY_RECORD_BINDING_INVALID')
    execution, envelope = _json(primary), _json(reviewed)
    # Off-host Linux images use the tracked LF registry bytes. This derived
    # build pin is compared with the original report's RAW-file digest; the
    # report is never normalized or rewritten to manufacture a match.
    # Initialization recomputes the complete owned contracts from their actual
    # raw build bytes. Do not normalize its original report/pin into a match.
    registry_raw = REGISTRY_PATH.read_bytes()
    registry_sha = _sha(registry_raw if initialization or owned_identity or artifact or authority or tool else registry_raw.replace(b'\r\n', b'\n'))
    event_review_time = now
    if artifact or initialization or owned_identity or authority or tool:
        # The runtime's 300-second consumption bound applies when the actual
        # registered peer reviewer read the original event/report. Later protected verification
        # must preserve that time, not claim a new execution or rereview. The
        # timestamp is provisional until the complete original reviewer
        # artifact, metadata, action span and joins below bind it. The real
        # current clock still governs the certification record's validity.
        preliminary = envelope.get('observations')
        proof = preliminary.get('reviewer_execution') if type(preliminary) is dict else None
        raw = proof.get('artifact_content_utf8') if type(proof) is dict else None
        if type(raw) is not str or not 1 <= len(raw.encode('utf-8')) <= 65536:
            _deny('REGISTERED_IDENTITY_REVIEW_ARTIFACT_INVALID')
        event_review_time = _utc(_json(raw.encode('utf-8')).get('reviewed_at'))
        if event_review_time > now:
            _deny('IDENTITY_REVIEW_TIME_INVALID')
    join = validate_event(execution, source_revision=source_revision,
        runtime_image_id=runtime_image_id, registry_sha256=registry_sha, now=event_review_time,
        **({'agent_id': subject, 'capability_id': capability} if initialization or owned_identity else {}))
    spec = _case_spec(row)
    if (artifact or authority or tool) and (join.get('case') != spec['case'] or
            join.get('case_spec_sha256') != _sha(_canonical(spec))):
        _deny('ARTIFACT_REVIEW_CASE_MISMATCH')
    expected_observations = dict(execution_task_id=join['task_id'], result_sha256=join['result_sha256'],
        case_spec_sha256=join['case_spec_sha256'], runtime_image_id=runtime_image_id,
        registry_sha256=registry_sha, reviewer_code_revision=reviewer_code_revision,
        oracle_id=ORACLE_ID, oracle_pass=True)
    observations = envelope.get('observations')
    if (type(observations) is not dict or set(observations) != set(expected_observations) | {'reviewer_execution'}
            or any(_canonical(observations.get(k)) != _canonical(v) for k, v in expected_observations.items())):
        _deny('IDENTITY_REVIEW_OBSERVATIONS_INVALID')
    proof = observations['reviewer_execution']
    if type(proof) is not dict or set(proof) != ({'dispatch', 'artifact_content_utf8', 'transport', 'action_records'} |
            ({'peer_objective_read','peer_request_body'} if tool and str(dimension)+':'+str(event_case) in {'models:complete','cross_verification:complete','collaboration:complete','handoff_recovery:bounded_response','handoff_recovery:agent_failure', 'clean_room_audit:complete'} else set())):
        _deny('REGISTERED_IDENTITY_REVIEW_REQUIRED')
    dispatch = proof['dispatch']
    if (type(dispatch) is not dict or set(dispatch) != {'task_id', 'state', 'artifact', 'model_calls',
            'execution_model', 'agent_id', 'capability', 'runtime_source_revision', 'review_action_id',
            'review_action_durable', 'certification'} or not _uuid(dispatch.get('task_id'))
            or dispatch['task_id'] == join['task_id'] or dispatch.get('state') != 'COMPLETED'
            or dispatch.get('agent_id') != reviewer or dispatch.get('capability') != reviewer_capability
            or type(dispatch.get('model_calls')) is not int or dispatch['model_calls'] != 0
            or dispatch.get('execution_model') != 'DETERMINISTIC'
            or dispatch.get('runtime_source_revision') != source_revision
            or not _uuid(dispatch.get('review_action_id')) or dispatch.get('review_action_durable') is not True
            or dispatch.get('certification') != 'UNVERIFIED'):
        _deny('REGISTERED_IDENTITY_REVIEW_DISPATCH_INVALID')
    transport = dict(authentication='OWNER_AUTHENTICATED', dispatch_http_status=202,
        artifact_http_status=200, runtime_source_revision=source_revision, actual_runtime_image=runtime_image_id)
    if _canonical(proof['transport']) != _canonical(transport):
        _deny('REGISTERED_IDENTITY_REVIEW_TRANSPORT_INVALID')
    raw = proof['artifact_content_utf8']
    if type(raw) is not str or not 1 <= len(raw.encode('utf-8')) <= 65536:
        _deny('REGISTERED_IDENTITY_REVIEW_ARTIFACT_INVALID')
    content = _json(raw.encode('utf-8'))
    metadata = dispatch['artifact']
    if (type(metadata) is not dict or set(metadata) != {'artifact_id', 'task_id', 'type', 'creator_agents',
            'timestamp', 'version', 'provenance', 'runtime_revision', 'validation_state', 'content_validation',
            'location', 'sha256', 'bytes', 'delivery_state'}
            or type(metadata.get('artifact_id')) is not str or not re.fullmatch('[0-9a-f]{32}', metadata['artifact_id'])
            or metadata.get('task_id') != dispatch['task_id'] or metadata.get('creator_agents') != [reviewer]
            or metadata.get('type') != 'json' or metadata.get('version') != '1.0.0'
            or metadata.get('provenance') != 'Deterministic computation; zero model calls'
            or metadata.get('runtime_revision') != source_revision
            or metadata.get('validation_state') != 'STRUCTURE_VALIDATED'
            or metadata.get('content_validation') != 'Not independently established by structural validation'
            or metadata.get('location') != 'artifact.json' or metadata.get('sha256') != _sha(raw.encode('utf-8'))
            or type(metadata.get('bytes')) is not int or metadata['bytes'] != len(raw.encode('utf-8'))
            or metadata.get('delivery_state') != 'AVAILABLE'):
        _deny('REGISTERED_IDENTITY_REVIEW_ARTIFACT_INVALID')
    expected = dict(schema_version=SCHEMA, task_id=dispatch['task_id'], reviewer_id=reviewer,
        reviewer_capability_id=reviewer_capability, subject_agent_id=subject, subject_capability_id=capability,
        dimension=dimension, test_case=event_case, source_revision=source_revision, runtime_image_id=runtime_image_id,
        execution_evidence_sha256=_sha(primary), case_spec_sha256=_sha(_canonical(spec)), result_sha256=join['result_sha256'],
        oracle_id=ORACLE_ID, test_result='PASS', review_errors=[], model_calls=0, execution_model='DETERMINISTIC',
        subject_execution_verification='ARTIFACT_OBJECTIVE_ACTION_JOINED', subject_domain_join=join,
        certification='UNVERIFIED')
    if tool and str(dimension)+':'+str(event_case) in {'models:complete','cross_verification:complete','collaboration:complete','handoff_recovery:bounded_response','handoff_recovery:agent_failure', 'clean_room_audit:complete'}:
        from app.agent_cert_tool_events import cross_peer_request,validate_cross_peer_receipt,validate_cross_peer_objective,peer_review_fields
        peer_request = cross_peer_request(execution,content.get('review_nonce'),source_revision)
        receipt = content.get('peer_request_receipt')
        validate_cross_peer_receipt(receipt,peer_task=dispatch['task_id'],subject_task=join['task_id'],
            request=peer_request,runtime=execution['runtime'],now=_utc(content.get('reviewed_at')))
        peer_read = proof.get('peer_objective_read')
        if (_canonical(proof.get('peer_request_body')) != _canonical(peer_request)
                or type(peer_read) is not list or len(peer_read) != 2 or peer_read[0] != 200):
            _deny('CROSS_ORIGINAL_PEER_REQUEST_REQUIRED')
        validate_cross_peer_objective(peer_read[1],dispatch=dispatch,runtime=execution['runtime'],receipt=receipt,
            now=_utc(row['certified_at']))
        if str(dimension)+':'+str(event_case) == 'clean_room_audit:complete':
            from app.agent_cert_clean_room import validate_audit
            blind = execution.get('blind_audit')
            validate_audit(blind,input_metadata=execution['dispatch']['tool_event']['input_artifact_metadata'],
                input_raw=execution['input_content_utf8'].encode(),runtime=execution['runtime'],
                registry=registry_sha,now=_utc(content.get('reviewed_at')))
            if (blind['dispatch']['task_id'] in {dispatch['task_id'],join['task_id']}
                or _utc(blind['artifact_metadata']['timestamp']) > _utc(receipt['created_at'])):
                _deny('BLIND_AUDIT_MUST_PRECEDE_COMPARISON')
        expected.update(peer_review_fields(str(dimension)+':'+str(event_case),receipt))
    if (set(content) != set(expected) | {'review_nonce', 'reviewed_at'} or not _uuid(content.get('review_nonce'))
            or any(_canonical(content.get(k)) != _canonical(v) for k, v in expected.items())):
        _deny('REGISTERED_IDENTITY_REVIEW_CONTENT_INVALID')
    certified = _utc(row['certified_at'])
    if not (_utc(join['completed_at']) <= _utc(content['reviewed_at']) <= _utc(metadata['timestamp']) <= certified
            <= _utc(row['last_revalidated']) <= now < _utc(row['expires_at'])):
        _deny('IDENTITY_REVIEW_TIME_INVALID')
    action_span(proof['action_records'], task_id=dispatch['task_id'], agent_id=reviewer,
        action_type=review_action_type, schema=SCHEMA, metadata=metadata,
        began=_utc(content['reviewed_at']), ended=certified,
        action_id=dispatch['review_action_id'], duration_limit_ms=120000)
    return True


def _conflict_review(row,primary,reviewed,*,source_revision,runtime_image_id,reviewer_code_revision,now):
    """Original four-task proof; current record interval cannot renew its event."""
    from app.agent_cert_conflict_events import VERSION,ORACLE,validate_reviewed_conflict
    from app.agent_registry import REGISTRY_PATH
    if (row.get('agent_id')!='a19' or row.get('capability_id')!='responsibility.a19'
            or row.get('executor_identity')!='a19' or row.get('verifier')!='a26'
            or row.get('authority_scope')!=agent_record('a19')['authority']
            or row.get('source_revision')!=source_revision or row.get('review_source_revision')!=source_revision
            or row.get('reviewer_code_revision')!=reviewer_code_revision or row.get('test_result')!='PASS'
            or row.get('test_version')!=VERSION or row.get('review_test_version')!=ORACLE
            or any(type(row.get(key)) is not str or not 1<=len(row[key])<=100
                for key in ('certification_test','review_run_id'))):
        _deny('CONFLICT_RECORD_BINDING_INVALID')
    execution,peer=_json(primary),_json(reviewed);raw=peer.get('artifact_content_utf8')
    if type(raw) is not str or not 1<=len(raw.encode())<=65536:_deny('CONFLICT_ORIGINAL_PEER_REQUIRED')
    reviewed_at=_utc(_json(raw.encode()).get('reviewed_at'))
    completed=_utc(peer.get('observation',{}).get('completed_at'))
    if not (reviewed_at<=completed<=_utc(row.get('certified_at'))<=_utc(row.get('last_revalidated'))
            <=now<_utc(row.get('expires_at'))):_deny('CONFLICT_RECORD_TIME_INVALID')
    validate_reviewed_conflict(execution,peer,source_revision=source_revision,runtime_image_id=runtime_image_id,
        registry_sha256=_sha(REGISTRY_PATH.read_bytes()),now=completed)
    return True


def _cross_conflict_review(row,primary,reviewed,*,source_revision,runtime_image_id,reviewer_code_revision,now):
    """Original four-task proof; current record interval cannot renew its event."""
    from app.agent_cert_cross_conflict_events import VERSION,ORACLE,validate_reviewed_conflict
    from app.agent_registry import REGISTRY_PATH
    if (row.get('agent_id')!='a19' or row.get('capability_id')!='responsibility.a19'
            or row.get('executor_identity')!='a19' or row.get('verifier')!='a26'
            or row.get('authority_scope')!=agent_record('a19')['authority']
            or row.get('source_revision')!=source_revision or row.get('review_source_revision')!=source_revision
            or row.get('reviewer_code_revision')!=reviewer_code_revision or row.get('test_result')!='PASS'
            or row.get('test_version')!=VERSION or row.get('review_test_version')!=ORACLE
            or any(type(row.get(key)) is not str or not 1<=len(row[key])<=100
                for key in ('certification_test','review_run_id'))):
        _deny('CROSS_CONFLICT_RECORD_BINDING_INVALID')
    execution,peer=_json(primary),_json(reviewed);raw=peer.get('artifact_content_utf8')
    if type(raw) is not str or not 1<=len(raw.encode())<=65536:_deny('CROSS_CONFLICT_ORIGINAL_PEER_REQUIRED')
    reviewed_at=_utc(_json(raw.encode()).get('reviewed_at'))
    completed=_utc(peer.get('observation',{}).get('completed_at'))
    if not (reviewed_at<=completed<=_utc(row.get('certified_at'))<=_utc(row.get('last_revalidated'))
            <=now<_utc(row.get('expires_at'))):_deny('CROSS_CONFLICT_RECORD_TIME_INVALID')
    validate_reviewed_conflict(execution,peer,source_revision=source_revision,runtime_image_id=runtime_image_id,
        registry_sha256=_sha(REGISTRY_PATH.read_bytes()),now=completed)
    return True


def _recovery_review(row, primary, reviewed, *, source_revision, runtime_image_id,
                     reviewer_code_revision, now):
    """Consume the original two tasks and persisted peer, never renew their time."""
    from app.agent_cert_recovery_events import VERSION, ORACLE, validate_reviewed_recovery
    from app.agent_registry import REGISTRY_PATH
    if (row.get('agent_id') != 'a19' or row.get('capability_id') != 'responsibility.a19'
            or row.get('executor_identity') != 'a19' or row.get('verifier') != 'a26'
            or row.get('authority_scope') != agent_record('a19')['authority']
            or row.get('source_revision') != source_revision
            or row.get('review_source_revision') != source_revision
            or row.get('reviewer_code_revision') != reviewer_code_revision
            or row.get('test_result') != 'PASS' or row.get('test_version') != VERSION
            or row.get('review_test_version') != ORACLE
            or any(type(row.get(key)) is not str or not 1 <= len(row[key]) <= 100
                   for key in ('certification_test', 'review_run_id'))):
        _deny('RECOVERY_RECORD_BINDING_INVALID')
    execution, peer = _json(primary), _json(reviewed)
    raw = peer.get('artifact_content_utf8')
    if type(raw) is not str or not 1 <= len(raw.encode('utf-8')) <= 65536:
        _deny('RECOVERY_ORIGINAL_PEER_REQUIRED')
    original_review_time = _utc(_json(raw.encode('utf-8')).get('reviewed_at'))
    peer_completed = _utc(peer.get('observation', {}).get('completed_at'))
    if not (original_review_time <= peer_completed <= _utc(row.get('certified_at'))
            <= _utc(row.get('last_revalidated')) <= now < _utc(row.get('expires_at'))):
        _deny('RECOVERY_RECORD_TIME_INVALID')
    # The peer's actual completed observation binds the historical consumption
    # check; current time governs only the record interval above.
    validate_reviewed_recovery(execution, peer, source_revision=source_revision,
        runtime_image_id=runtime_image_id, registry_sha256=_sha(REGISTRY_PATH.read_bytes()),
        now=peer_completed)
    return True


def sign_reviewed_case(row, *, evidence_root: Path, execution_sha256: str,
                       review_sha256: str, execution_source_revision: str,
                       runtime_image_id: str, reviewer_code_revision: str,
                       public_pin: dict, sign_digest, now: datetime,
                       verifier_code_revision: str | None = None,
                       cloud_binding=None, cloud_policy=None,
                       expected_owner_policy_sha256: str | None = None) -> dict:
    """Validate and sign ONE approved case using the existing protected signer.

    Hash bindings and revisions are trusted caller inputs from protected reviewed
    source, not portable approvals or request parameters. A cryptographic PASS
    authenticates this case only; the registry still owns full L7 projection.
    """
    try:
        required_fields = _RECORD_FIELDS | ({'logic_signals'} if type(row) is dict and
            row.get('dimension') == 'logic_quality' else set())
        if (type(row) is not dict or set(row) != required_fields or not callable(sign_digest) or
                type(execution_sha256) is not str or not _SHA.fullmatch(execution_sha256) or
                type(review_sha256) is not str or not _SHA.fullmatch(review_sha256) or
                execution_sha256 == review_sha256 or
                type(execution_source_revision) is not str or not _REV.fullmatch(execution_source_revision) or
                type(reviewer_code_revision) is not str or not _REV.fullmatch(reviewer_code_revision) or
                (verifier_code_revision is not None and (type(verifier_code_revision) is not str or
                    not _REV.fullmatch(verifier_code_revision))) or
                type(runtime_image_id) is not str or not _IMAGE.fullmatch(runtime_image_id) or
                type(now) is not datetime or now.tzinfo is None or
                type(public_pin) is not dict or set(public_pin) != {'key_id', 'jwk'}):
            _deny('PROTECTED_BINDINGS_REQUIRED')
        candidate = _json(_canonical(row))
        if (candidate.get('evidence_sha256') != execution_sha256 or
                candidate.get('review_evidence_sha256') != review_sha256 or
                'attestation' in candidate):
            _deny('APPROVED_ARTIFACT_MISMATCH')
        if verifier_code_revision is not None:
            # Protected caller pins the complete current verifier closure.
            # Keep the immutable runtime reviewer provenance distinct; all
            # fields, including this new protected binding, are signed.
            candidate['verifier_code_revision'] = verifier_code_revision
        root = Path(evidence_root)
        if not root.is_absolute() or any(path.is_symlink() for path in (root, *root.parents)):
            _deny('PROTECTED_EVIDENCE_ROOT_REQUIRED')
        subject = candidate.get('agent_id')
        if type(subject) is not str or canonical_agent_id(subject) != subject:
            _deny('REGISTERED_SUBJECT_REQUIRED')
        primary = _read_subject_artifact(root / subject, candidate.get('evidence'))
        review = _read_subject_artifact(root / subject, candidate.get('review_evidence'))
        if _sha(primary) != execution_sha256 or _sha(review) != review_sha256:
            _deny('APPROVED_ARTIFACT_MISMATCH')
        callback = lambda record, execution, reviewed: _review(record, execution, reviewed,
            source_revision=execution_source_revision, runtime_image_id=runtime_image_id,
            reviewer_code_revision=reviewer_code_revision, now=now,
            cloud_binding=cloud_binding, cloud_policy=cloud_policy,
            expected_owner_policy_sha256=expected_owner_policy_sha256)
        # Review once before constructing any signing operation. sign_reviewed
        # separately repeats review and artifact binding immediately before sign.
        callback(candidate, primary, review)
        signer = ProtectedAzureES256Signer(SERVICE, public_pin['key_id'], public_pin['jwk'],
                                           sign_digest, review_case=callback)
        signed = signer.sign_reviewed(candidate, evidence_root=root,
                                       source_revision=execution_source_revision, now=now)
        verifier = AzureES256CertificationVerifier({SERVICE: {public_pin['key_id']: public_pin['jwk']}})
        changed = dict(signed, test_case='different-case')
        if verifier(signed) is not True or verifier(changed) is not False:
            _deny('SIGNATURE_VERIFICATION_FAILED')
        return signed
    except CertificationReviewError:
        raise
    except Exception:
        # Never forward result text, path, provider exception or injected bearer.
        _deny('REVIEWED_CASE_SIGNING_REJECTED')

def _owner_referral_review(row,primary,reviewed,*,source_revision,runtime_image_id,reviewer_code_revision,now):
    """Original referral, separate Owner acknowledgment and persisted peer only."""
    from app.agent_cert_owner_referral_events import VERSION,ORACLE,validate_reviewed_owner_case
    from app.agent_registry import REGISTRY_PATH
    if (row.get('agent_id')!='a19' or row.get('capability_id')!='responsibility.a19'
            or row.get('executor_identity')!='a19' or row.get('verifier')!='a26'
            or row.get('authority_scope')!=agent_record('a19')['authority']
            or row.get('source_revision')!=source_revision or row.get('review_source_revision')!=source_revision
            or row.get('reviewer_code_revision')!=reviewer_code_revision or row.get('test_result')!='PASS'
            or row.get('test_version')!=VERSION or row.get('review_test_version')!=ORACLE
            or any(type(row.get(key)) is not str or not 1<=len(row[key])<=100
                for key in ('certification_test','review_run_id'))):
        _deny('OWNER_REFERRAL_RECORD_BINDING_INVALID')
    execution,peer=_json(primary),_json(reviewed);raw=peer.get('artifact_content_utf8')
    if type(raw) is not str or not 1<=len(raw.encode())<=65536:_deny('OWNER_REFERRAL_ORIGINAL_PEER_REQUIRED')
    reviewed_at=_utc(_json(raw.encode()).get('reviewed_at'))
    completed=_utc(peer.get('observation',{}).get('completed_at'))
    if not (reviewed_at<=completed<=_utc(row.get('certified_at'))<=_utc(row.get('last_revalidated'))
            <=now<_utc(row.get('expires_at'))):_deny('OWNER_REFERRAL_RECORD_TIME_INVALID')
    validate_reviewed_owner_case(execution,peer,source_revision=source_revision,runtime_image_id=runtime_image_id,
        registry_sha256=_sha(REGISTRY_PATH.read_bytes()),now=completed)
    return True
