"""One finite a07 public-source specimen; never a role or Azure award.

Run inside the installed owner container after deployment confirmation. Prepare
and packet stages are also usable on the host. Original model output is retained
or rejected, never repaired by this driver. There is no automatic model retry.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request

SOURCE_URL = 'https://docs.python.org/robots.txt'
SCHEMA = 'orqevia.agent-tool-requests.v1'
AGENT = 'a07'
OBJECTIVE = (
    'Inspect the permitted official Python documentation robots.txt source. '
    'After actual retrieval, give a concise evidence note about what these bytes '
    'support and what they cannot establish. Preserve the observed source URL, '
    'byte count, source SHA-256 and retrieval time from system evidence. '
    'State whether source publication date, independent corroboration and '
    'denominator-based statistical claims are available; do not invent them. '
    'Distinguish retrieved source facts from your interpretation and missing '
    'evidence. Never claim tools ran, continuous health, role certification or '
    'Azure acceptance without the corresponding independent evidence.'
)


def now():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def response_schema():
    """Shape only; no const, enum, answer values or source-content hints."""
    strings = {name: {'type': 'string'} for name in ('id', 'kind', 'service')}
    strings['parameters'] = {'type': 'object', 'properties': {'url': {'type': 'string'}},
        'required': ['url'], 'additionalProperties': False}
    return {'type': 'object', 'properties': {'schema': {'type': 'string'},
        'requests': {'type': 'array', 'minItems': 1, 'maxItems': 1,
            'items': {'type': 'object', 'properties': strings,
                'required': ['id', 'kind', 'service', 'parameters'], 'additionalProperties': False}}},
        'required': ['schema', 'requests'], 'additionalProperties': False}


def prompt(attempt=1):
    original = (
        'You are the registered Evidence Agent a07. Do not supply task answers '
        'before retrieving evidence. The Owner permits exactly one public read '
        'of ' + SOURCE_URL + '. Return one JSON tool-request object only, using '
        'schema "' + SCHEMA + '" and requests with exactly id, kind, service and '
        'parameters. Choose a short lowercase step id; kind must be "service", '
        'service must be "internet.public.read", and parameters must contain '
        'only the approved URL. No actor, job, credential, provider, spending, '
        'workspace or delegation fields are allowed. This request is a proposal; '
        'the authenticated runtime will separately validate and execute it.\n'
        'Authorized objective:\n' + OBJECTIVE
    )
    if attempt == 1:
        return original
    # A diagnosed contract ambiguity, no source facts or task-answer values.
    return original + ('\nIdentifier contract clarification: id is a step label, '
        'not a numeric execution ID. It must start with a lowercase ASCII letter '
        'a-z. Remaining characters may only be lowercase ASCII letters, digits, '
        'underscore or hyphen. Total length must be one to forty-eight characters. '
        'Preserve the same task, source and all other output requirements.')


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.next')
    temporary.write_bytes(encoded(value))
    temporary.replace(path)


def retain(path, value):
    raw = encoded(value)
    if path.exists() and path.read_bytes() != raw:
        raise RuntimeError('Immutable specimen receipt changed: ' + path.name)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def rpc(method, path, body=None):
    if not path.startswith('/api/') or '..' in path:
        raise ValueError('Fixed owner API path required')
    token = os.environ.get('PRIME_SPINE_TOKEN', '').strip()
    if not token:
        raise RuntimeError('Existing owner credential unavailable')
    request = urllib.request.Request('http://127.0.0.1:8000' + path,
        data=encoded(body) if body is not None else None, method=method,
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    # No proxy, redirects or caller-selected origin can carry the credential.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=20) as response:
        raw = response.read(2097153)
        if len(raw) > 2097152:
            raise RuntimeError('Owner readback exceeds specimen bound')
        return json.loads(raw)


def guard(args):
    if not args.deployment_confirmed:
        raise PermissionError('Hold: root deployment confirmation required before submission or effect')
    if not re.fullmatch(r'[0-9a-f]{40}', args.expected_source or ''):
        raise ValueError('Exact deployed source revision required')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', args.expected_image or ''):
        raise ValueError('Externally observed exact Docker image pin required')
    source = os.environ.get('PRIME_RUNTIME_REVISION')
    image = os.environ.get('PRIME_RUNTIME_IMAGE_DIGEST')
    if source != args.expected_source or (image and image != args.expected_image):
        raise PermissionError('Installed runtime source/image differs from confirmed deployment')
    return {'observed_source_revision': source, 'observed_image_environment_pin': image,
        'externally_supplied_docker_image_pin': args.expected_image,
        'image_correspondence': 'MATCHING_ENVIRONMENT_PIN' if image else 'EXTERNAL_DOCKER_RECEIPT_REQUIRED',
        'host_id': os.environ.get('PRIME_INTERFACE_HOST_ID', 'UNKNOWN')}


def check_model_request(raw):
    # Delegate duplicate-key/nonfinite/depth validation to the installed bridge.
    from app.agent_tool_bridge import bounded_json
    value = bounded_json(raw)
    if type(value) is not dict or set(value) != {'schema', 'requests'} or value['schema'] != SCHEMA:
        raise ValueError('Actual model did not return the exact request envelope')
    requests = value['requests']
    if type(requests) is not list or len(requests) != 1:
        raise ValueError('Exactly one actual model request required')
    step = requests[0]
    if type(step) is not dict or set(step) != {'id', 'kind', 'service', 'parameters'}:
        raise ValueError('Actual model supplied unauthorized request fields')
    if step['kind'] != 'service' or step['service'] != 'internet.public.read' or step['parameters'] != {'url': SOURCE_URL}:
        raise PermissionError('Actual model requested an operation outside this specimen')
    if type(step['id']) is not str or not re.fullmatch(r'[a-z][a-z0-9_-]{0,47}', step['id']):
        raise ValueError('Actual model step identifier invalid')
    return step


def initial_job_bound(job, body):
    fields = ('agent', 'prompt', 'model', 'preferred_provider', 'data_classification',
              'response_format', 'max_retries', 'max_cost_usd')
    return (all(job.get(key) == body[key] for key in fields) and
        job.get('provider') == body['preferred_provider'] and job.get('attempts') == 1 and
        job.get('allow_cloud') == 0 and job.get('external_execution') == 0 and
        job.get('started_at') is not None and job.get('completed_at') is not None and
        json.loads(job.get('response_schema') or 'null') == body['response_schema'] and
        bool(job.get('inference_receipt')))


def inference_receipt_bound(job):
    """Reconstruct the actual local payload from fixed current runtime inputs."""
    from app.direct_stream import inference_request
    from app.settings import SETTINGS
    from app.compute_profile import generation_options
    from app.job_queue import Provider
    provider = Provider(job['provider'], 'local', job['model'], 1024, 0, 1)
    _, _, expected = inference_request(job, provider, settings=SETTINGS, options=generation_options)
    observed = json.loads(job.get('inference_receipt') or 'null')
    return encoded(observed) == encoded(expected)


def collect_actions(job_ids):
    path = Path(os.environ.get('PRIME_DATA_DIR', '/data')) / 'action-records.jsonl'
    if not path.exists() or path.stat().st_size > 67108864:
        return {'state': 'UNKNOWN_ACTION_READBACK_BOUND', 'records': []}
    records, previous, valid = [], '0' * 64, True
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            item = json.loads(line)
            observed = item.pop('sha256')
            valid = valid and item.get('previous_sha256') == previous and sha(encoded(item)) == observed
            previous = observed
            if item.get('task_id') in job_ids:
                records.append({**item, 'sha256': observed})
    return {'state': 'HASH_CHAIN_CHECKED' if valid else 'HASH_CHAIN_MISMATCH',
            'records': records, 'scope': 'OBSERVED_ACTION_FILE_ONLY_NOT_ALL_ROTATED_OR_OTHER_STORES'}


def run(args):
    root = args.output_dir
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / 'state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        'schema': 'orqevia.a07-bridge-specimen.v1', 'prepared_at_utc': now(),
        'maximum_initial_model_jobs': 1, 'maximum_feedback_model_jobs': 1,
        'automatic_model_retries': 0, 'full_role_acceptance': 'NOT_ESTABLISHED',
        'independent_review': 'PENDING', 'independent_azure_assessment': 'NOT_ESTABLISHED'}
    attempt = getattr(args, 'attempt', 1)
    if state.get('attempt', attempt) != attempt:
        raise ValueError('Separate attempt directory required; original case stays immutable')
    state['attempt'] = attempt
    def save():
        state['last_observed_at_utc'] = now()
        atomic(state_path, state)
        retain(root / 'history' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json'), state)
    if args.stage == 'prepare':
        retain(root / 'scenario.json', {'agent': AGENT, 'source_url': SOURCE_URL,
            'objective': OBJECTIVE, 'request_prompt': prompt(attempt), 'response_schema': response_schema(),
            'scope': 'ONE_PUBLIC_SOURCE_SPECIMEN_NOT_FULL_ROLE_OR_21_OR_AZURE',
            'answers_supplied': False, 'source_contents_supplied_before_retrieval': False})
        state['driver_sha256'] = sha(Path(__file__).read_bytes())
        save()
        return state
    if args.stage == 'packet':
        files = []
        for path in sorted(root.rglob('*')):
            if path.is_file() and not path.name.startswith('azure-assessment-packet') and '.next' not in path.name:
                files.append({'path': path.relative_to(root).as_posix(),
                              'sha256': sha(path.read_bytes()), 'bytes': path.stat().st_size})
        required = ['scenario.json', 'generation-job.json', 'public-tool-receipt.json',
                    'public-source.bin', 'feedback-job.json', 'action-readback.json',
                    'runtime-source-custody.json', 'deployment-identity-before.json',
                    'deployment-identity-after.json', 'independent-review.json']
        packet = {'schema': 'orqevia.azure-assessment-evidence-packet.v1', 'assembled_at_utc': now(),
            'agent': AGENT, 'subject': 'ONE_A07_PUBLIC_SOURCE_REQUEST_TOOL_FEEDBACK_SPECIMEN',
            'files': files, 'missing_evidence': [name for name in required if not (root / name).exists()],
            'observed_specimen_state': state, 'full_role_accepted_count': 0, 'full_role_denominator': 21,
            'independent_azure_assessment': 'NOT_ESTABLISHED', 'signed_cases': [],
            'azure_signing_or_credentials_used': False,
            'existing_owner_credentials_used_for_loopback_auth': bool(state.get('generation_job_id')),
            'independent_review_receipts': [item for item in files
                if 'independent-review' in Path(item['path']).name],
            'missing_assessment_scope_evidence': [
                'Passing independent semantic result-use review for this exact objective.',
                'Independent Azure verdict and attestation bound to the exact case, runtime source, authority and execution/review artifact digests.',
                'Remaining owned-capability exact-case evidence for all21 full agent roles.'],
            'assessment_decision': 'ASSIGNED_TO_INDEPENDENT_ASSESSOR',
            'limits': ['This packet supplies no Azure-issued results or attestation.',
                'A single specimen does not cover all a07 responsibilities or all21 agents.',
                'Request shape is supplied; actual source contents and task answers are not.',
                'The independent reviewer must inspect original model output and raw source bytes.',
                'Missing runtime or inference pins remain unknown; caller-provided image pin needs separate Docker evidence.']}
        # Keep each assembly immutable; a later review may add evidence without
        # erasing the earlier manifest or recursively hashing prior manifests.
        packet_sha = sha(encoded(packet))
        retain(root / ('azure-assessment-packet-' + packet_sha + '.json'), packet)
        atomic(root / 'azure-assessment-packet.json', packet)
        return {'packet_path': str(root / 'azure-assessment-packet.json'),
                'missing_evidence': packet['missing_evidence'], 'files': len(files)}
    pins = guard(args)
    state['runtime_pins'] = pins
    if args.stage == 'submit':
        if 'generation_job_id' in state:
            return {'state': 'ALREADY_SUBMITTED_NO_NEW_INFERENCE', 'job_id': state['generation_job_id']}
        from app.settings import SETTINGS
        from app import settings
        from app.agent_registry import agent_record
        assert agent_record(AGENT)['name'] == 'Evidence Agent'
        initial_model = SETTINGS.deep_model if attempt == 3 else SETTINGS.fast_model
        initial_provider = 'ollama-deep' if attempt == 3 else 'ollama-fast'
        body = {'agent': AGENT, 'prompt': prompt(attempt), 'response_schema': response_schema(),
            'response_format': 'strict_json', 'priority': 'low', 'model_role': 'deep' if attempt == 3 else 'fast',
            'model': initial_model, 'preferred_provider': initial_provider,
            'ram_mb': 1024, 'timeout_seconds': 60, 'max_retries': 0, 'max_cost_usd': 0,
            'allow_cloud': False, 'external_execution': False,
            'data_classification': 'CLOUD_PERMITTED', 'classification': 'R0',
            'task_class': 'classification', 'idempotency_key': 'a07-public-bridge-specimen-20261013:request'}
        if attempt != 1:
            body['idempotency_key'] += ':attempt' + str(attempt)
        from app.response_schema import canonicalize_schema
        body['response_schema'] = canonicalize_schema(body['response_schema'])
        package_root = Path(settings.__file__).resolve().parent.parent
        custody_paths = ['app/agent_tool_bridge.py', 'app/agent_tool_bridge_api.py',
            'app/capability_broker.py', 'app/public_http.py', 'app/compute_queue_api.py',
            'app/job_queue.py', 'app/direct_stream.py', 'app/action_records.py',
            'app/response_schema.py', 'app/settings.py', 'config/agent_registry.json']
        retain(root / 'runtime-source-custody.json', {'observed_at_utc': now(),
            'runtime_pins': pins, 'scope': 'ACTUAL_INSTALLED_FILE_BYTES; SOURCE_CORRESPONDENCE_REQUIRES_EXTERNAL_REVIEW',
            'files': [{'path': name, 'sha256': sha((package_root / name).read_bytes()),
                       'bytes': (package_root / name).stat().st_size} for name in custody_paths]})
        retain(root / 'initial-submission.json', body)
        state['submission_attempt_recorded'] = True
        state['feedback_model_expected'] = SETTINGS.fast_model
        save()  # Persist the deterministic key before an ambiguous HTTP result.
        job = rpc('POST', '/api/compute-queue/jobs', body)
        state['generation_job_id'] = job['id']
        retain(root / 'initial-submission-readback.json', job)
        save()
        return {'state': job['status'], 'job_id': job['id'], 'model': job['model'], 'cloud_budget_usd': job['max_cost_usd']}
    job_id = state['generation_job_id']
    prefix = '/api/agent-tool-bridge/sessions/' + job_id
    if args.stage == 'collect':
        job = rpc('GET', '/api/compute-queue/jobs/' + job_id)
        if job['status'] not in {'completed', 'failed', 'cancelled', 'budget_blocked'}:
            return {'state': job['status'], 'new_model_submissions': 0}
        retain(root / 'generation-job.json', job)
        if job['status'] != 'completed' or job.get('error'):
            state['failure'] = 'ORIGINAL_INFERENCE_FAILED_OR_BLOCKED'; save(); return state
        body = json.loads((root / 'initial-submission.json').read_text())
        if not initial_job_bound(job, body) or not inference_receipt_bound(job):
            state['failure'] = 'ORIGINAL_ACTOR_REQUEST_PROVIDER_OR_INFERENCE_RECEIPT_MISMATCH'; save(); return state
        try:
            step = check_model_request(job['result'])
        except (ValueError, PermissionError, TypeError) as exc:
            state['failure'] = 'ACTUAL_MODEL_REQUEST_REJECTED_' + type(exc).__name__; save(); return state
        scope = {'job_id': job_id, 'objective': OBJECTIVE, 'services': ['internet.public.read'],
                 'workspace_operations': [], 'delegation_targets': [], 'max_steps': 1, 'max_delegations': 0}
        rpc('POST', '/api/agent-tool-bridge/sessions', scope)
        observed = rpc('POST', prefix + '/execute', {})
        retain(root / 'public-tool-execution-readback.json', observed)
        receipt = rpc('GET', prefix + '/receipts/' + step['id'])
        retain(root / 'public-tool-receipt.json', receipt)
        value = receipt.get('receipt', {}).get('result', {}).get('result', {})
        if not value:
            state['failure'] = 'PUBLIC_TOOL_FAILED_OR_MISSING_RESULT'; save(); return state
        raw = base64.b64decode(value['content_base64'], validate=True)
        verified = (sha(raw) == value['source_sha256'] and len(raw) == value['bytes'] and
            value['source_url'] == SOURCE_URL and value['tls_verified'] is True and
            value['dns_socket_pinned'] is True and value['credentials_sent'] is False and
            value['executable_content_run'] is False)
        if not verified:
            state['failure'] = 'PUBLIC_RESULT_PROVENANCE_OR_BYTES_MISMATCH'; save(); return state
        source_path = root / 'public-source.bin'
        if source_path.exists() and source_path.read_bytes() != raw:
            raise RuntimeError('Original public source bytes changed')
        source_path.write_bytes(raw)
        state['tool_provenance_checked'] = True
        state['initial_inference_payload_receipt_checked'] = True
        state['source_sha256'] = sha(raw)
        state['source_bytes'] = len(raw)
        state['tool_step_id'] = step['id']
        save()
        return {'state': 'PUBLIC_TOOL_BYTES_RETAINED', 'source_sha256': sha(raw), 'bytes': len(raw), 'new_model_submissions': 0}
    if args.stage == 'feedback':
        if not state.get('tool_provenance_checked') or state.get('failure'):
            raise PermissionError('No feedback until actual tool/source provenance is retained')
        observed = rpc('POST', prefix + '/feedback', {})
        feedback = next(s for s in observed['steps'] if s['step_id'] == '_feedback')
        state['feedback_job_id'] = feedback['receipt']['result']['child_job_id']
        state['feedback_input_sha256'] = feedback['receipt']['result']['feedback_input_sha256']
        retain(root / 'feedback-submission-readback.json', observed)
        save()
        return {'state': feedback['state'], 'feedback_job_id': state['feedback_job_id'], 'maximum_additional_model_jobs': 1}
    if args.stage == 'finish':
        feedback_id = state['feedback_job_id']
        job = rpc('GET', '/api/compute-queue/jobs/' + feedback_id)
        if job['status'] not in {'completed', 'failed', 'cancelled', 'budget_blocked'}:
            return {'state': job['status'], 'new_model_submissions': 0}
        retain(root / 'feedback-job.json', job)
        state['feedback_job_binding_checked'] = (job.get('agent') == AGENT and
            job.get('provider') == 'ollama-fast' and job.get('model') == state['feedback_model_expected'] and
            job.get('attempts') == 1 and job.get('allow_cloud') == 0 and job.get('external_execution') == 0 and
            job.get('data_classification') == 'LOCAL_ONLY' and job.get('max_retries') == 0 and
            job.get('max_cost_usd') == 0 and sha(job['prompt'].encode()) == state['feedback_input_sha256'] and
            inference_receipt_bound(job))
        if not state['feedback_job_binding_checked']:
            state['failure'] = 'FEEDBACK_EXECUTION_OR_INPUT_BINDING_MISMATCH'
        observed = rpc('POST', prefix + '/observe', {})
        retain(root / 'final-bridge-readback.json', observed)
        actions = collect_actions({job_id, feedback_id})
        retain(root / 'action-readback.json', actions)
        state['synthesis_execution_state'] = job['status']
        state['actual_selected_queue_cost_usd'] = sum(j['actual_cost_usd'] for j in
            (json.loads((root / 'generation-job.json').read_text()), job)) if all(j.get('actual_cost_usd') is not None for j in
            (json.loads((root / 'generation-job.json').read_text()), job)) else None
        state['independent_review'] = 'PENDING_ORIGINAL_INPUT_OUTPUT_SOURCE_ACTION_REVIEW'
        save()
        return {'state': job['status'], 'action_readback': actions['state'],
                'selected_queue_cost_usd': state['actual_selected_queue_cost_usd'], 'full_role_acceptance': 'NOT_ESTABLISHED'}
    raise ValueError('Unknown specimen stage')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('prepare', 'submit', 'collect', 'feedback', 'finish', 'packet'), default='prepare')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--attempt', type=int, choices=(1, 2, 3), default=1,
                        help='Explicit separately authorized attempt; never an automatic retry loop')
    parser.add_argument('--deployment-confirmed', action='store_true')
    parser.add_argument('--expected-source')
    parser.add_argument('--expected-image')
    args = parser.parse_args()
    try:
        print(json.dumps(run(args), ensure_ascii=False))
    except Exception as exc:
        # Print no credential, traceback or request headers.
        print(json.dumps({'state': 'STOPPED_FOR_RECONCILIATION', 'error_type': type(exc).__name__,
                          'new_automatic_model_retries': 0}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
