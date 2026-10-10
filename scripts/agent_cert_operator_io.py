"""Prepared fixed-loopback Owner client for one zero-model event collection.

No CLI, environment/credential lookup, filesystem/ledger/Docker access, service
startup, signing or admission. The protected operator injects its EXISTING Owner
credential and independently observed source/image pins. Explicit invocation
alone performs HTTP; importing/constructing performs no transport/runtime I/O.
Canonical challenge metadata may read the existing public source Registry.

The source-owned runtime/action API feeds are not image attestation, Owner-device
qualification or L7. They must first be packaged, reviewed and deployed. Raw
bounded HTTP replies remain repr-hidden custody; persist them privately if an
attempt is interrupted. No mutation is retried, including after an uncertain
HTTP failure. The original owning validators remain the proof boundary.
"""
from dataclasses import dataclass, field
import hashlib
import http.client
import json
import math
import re
import socket
import threading
import time
import uuid

from app.agent_cert_role_review import canonical_case_spec
from scripts.collect_agent_cert_case import OperatorIO


HOST, PORT = '127.0.0.1', 8000
ORIGIN = 'http://127.0.0.1:8000'
RUNTIME_PATH = '/api/agent-cert-events/runtime'
MAX_JSON = 1024 * 1024
MAX_ARTIFACT = 65536
MAX_RESPONSE_CUSTODY = 8 * 1024 * 1024
_SOURCE = re.compile(r'[0-9a-f]{40}\Z')
_IMAGE = re.compile(r'sha256:[0-9a-f]{64}\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_ARTIFACT = re.compile(r'[0-9a-f]{32}\Z')
_IDENTITY = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z')
_POSTS = frozenset(('/api/agents/objectives', '/api/agents/dispatch'))


class OperatorBindingError(ValueError):
    """Fixed public code; never reflect response, credential or callback text."""


def _require(value, code):
    if value is not True:
        raise OperatorBindingError(code) from None


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def _uuid(value):
    try:
        return type(value) is str and str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    def nonfinite(_):
        raise ValueError()
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique,
                           parse_constant=nonfinite)
        _canonical(value)  # Overflowed JSON exponents also fail closed.
        _require(type(value) is dict, 'OWNED_JSON_OBJECT_REQUIRED')
        return value
    except Exception:
        raise OperatorBindingError('MALFORMED_BOUNDED_JSON') from None


def _response_framing(response, cap):
    # HTTPResponse.read1() silently closes on premature Content-Length EOF.
    # Require unambiguous wire framing and later prove the stated length ended.
    headers = response.getheaders()
    _require(type(headers) is list and all(type(pair) is tuple and len(pair) == 2
        and all(type(value) is str for value in pair) for pair in headers),
        'HTTP_FRAMING_INVALID')
    lengths = [value.strip() for key, value in headers if key.lower() == 'content-length']
    transfers = [value.strip().lower() for key, value in headers if key.lower() == 'transfer-encoding']
    _require(len(lengths) <= 1 and len(transfers) <= 1 and not (lengths and transfers),
        'HTTP_FRAMING_INVALID')
    _require(type(response.chunked) is bool, 'HTTP_FRAMING_INVALID')
    if transfers:
        _require(transfers == ['chunked'] and response.chunked is True
            and isinstance(response, http.client.HTTPResponse), 'HTTP_FRAMING_INVALID')
        def strict_trailer():
            # stdlib tolerates EOF after the final zero chunk. This fixed API
            # requires the actual trailer-terminating blank line, still bounded
            # by the same exact-socket timer and a small aggregate trailer cap.
            total = 0
            while True:
                line = response.fp.readline(65537)
                total += len(line)
                _require(type(line) is bytes and line.endswith(b'\r\n')
                    and total <= 65536, 'HTTP_FRAMING_INCOMPLETE')
                if line == b'\r\n':
                    return
        response._read_and_discard_trailer = strict_trailer
        return 'chunked', None
    _require(response.chunked is False, 'HTTP_FRAMING_INVALID')
    if lengths:
        value = lengths[0]
        _require(re.fullmatch(r'[0-9]{1,10}', value) is not None,
            'HTTP_FRAMING_INVALID')
        expected = int(value)
        _require(0 < expected <= cap and type(response.length) is int
            and response.length == expected, 'HTTP_FRAMING_INVALID')
        return 'length', expected
    _require(response.length is None and response.will_close is True,
        'HTTP_FRAMING_INVALID')
    return 'close', None


def _framing_complete(response, framing, size):
    kind, expected = framing
    _require(response.isclosed() is True, 'HTTP_FRAMING_INCOMPLETE')
    if kind == 'length':
        _require(size == expected and type(response.length) is int and response.length == 0,
            'HTTP_FRAMING_INCOMPLETE')
    elif kind == 'chunked':
        _require(response.chunk_left is None, 'HTTP_FRAMING_INCOMPLETE')


@dataclass(frozen=True)
class OriginalHTTPReply:
    method: str
    path: str
    status: int
    raw: bytes = field(repr=False)
    body_complete: bool = False


class AgentCertOperatorIO:
    """Single-use mutation paths, separately bounded total/request deadlines."""
    def __init__(self, *, owner_token, spec, expected_source_revision,
                 expected_runtime_image, total_timeout_seconds=10,
                 request_timeout_seconds=2, connection_factory=http.client.HTTPConnection,
                 timer_factory=threading.Timer, monotonic=time.monotonic):
        _require(type(owner_token) is str and 16 <= len(owner_token) <= 4096
            and all(33 <= ord(char) <= 126 for char in owner_token),
            'EXISTING_OWNER_CREDENTIAL_REQUIRED')
        _require(type(expected_source_revision) is str and _SOURCE.fullmatch(expected_source_revision) is not None
            and type(expected_runtime_image) is str and _IMAGE.fullmatch(expected_runtime_image) is not None,
            'EXTERNALLY_OBSERVED_RUNTIME_PINS_REQUIRED')
        _require(type(total_timeout_seconds) in (int, float) and math.isfinite(total_timeout_seconds)
            and 0 < total_timeout_seconds <= 30
            and type(request_timeout_seconds) in (int, float) and math.isfinite(request_timeout_seconds)
            and 0 < request_timeout_seconds <= 2
            and all(callable(v) for v in (connection_factory, timer_factory, monotonic)),
            'BOUNDED_OPERATOR_TRANSPORT_REQUIRED')
        try:
            _require(type(spec) is dict, 'CANONICAL_ZERO_MODEL_EVENT_REQUIRED')
            canonical = canonical_case_spec(spec.get('agent_id'), spec.get('capability_id'), spec.get('case'))
            _require(_canonical(spec) == _canonical(canonical), 'CANONICAL_ZERO_MODEL_EVENT_REQUIRED')
            agent, capability, case = canonical['agent_id'], canonical['capability_id'], canonical['case']
            if case == 'baseline:initialization':
                from app.agent_cert_initialization import (
                    ACTION_TYPE, initialization_reviewer, initialization_review_objective,
                )
                self._action_type = ACTION_TYPE
                self._reviewer, self._review_cap = initialization_reviewer(agent, capability)
                self._review_objective = initialization_review_objective(agent, capability)
                self._review_operation = 'certification_initialization_review'
                self._review_action_type = 'agent.certification.initialization.review'
            elif case == 'baseline:identity' and (agent, capability) != ('a19', 'responsibility.a19'):
                from app.agent_cert_owned_identity import (ACTION_TYPE, REVIEW_ACTION, REVIEW_OPERATION,
                    identity_reviewer, identity_review_objective)
                self._action_type = ACTION_TYPE
                self._reviewer, self._review_cap = identity_reviewer(agent, capability)
                self._review_objective = identity_review_objective(agent, capability)
                self._review_operation, self._review_action_type = REVIEW_OPERATION, REVIEW_ACTION
            elif case in {'tool_recovery:tool_failure', 'tool_recovery:bounded_response', 'graceful_degradation:complete', 'tools:complete', 'independent_verification:complete'}:
                from app.agent_cert_tool_events import tool_action_type
                from app.agent_cert_role_review import TOOL_REVIEW_ACTION, tool_review_objective, TOOL_REVIEW_OPERATION
                _require((agent, capability) == ('a19', 'responsibility.a19'), 'CANONICAL_ZERO_MODEL_EVENT_REQUIRED')
                self._action_type = tool_action_type(case)
                self._reviewer, self._review_cap = 'a26', 'responsibility.a26'
                self._review_objective, self._review_operation = tool_review_objective(case), TOOL_REVIEW_OPERATION
                self._review_action_type = TOOL_REVIEW_ACTION
            elif case in {'authority:complete', 'unauthorized_rejection:authorized', 'unauthorized_rejection:unauthorized'}:
                from app.agent_cert_authority_events import authority_action_type
                from app.agent_cert_role_review import (
                    AUTHORITY_REVIEW_ACTION, AUTHORITY_REVIEW_OBJECTIVE, AUTHORITY_REVIEW_OPERATION,
                )
                _require((agent, capability) == ('a19', 'responsibility.a19'),
                    'CANONICAL_ZERO_MODEL_EVENT_REQUIRED')
                self._action_type = authority_action_type(case)
                self._reviewer, self._review_cap = 'a26', 'responsibility.a26'
                self._review_objective = AUTHORITY_REVIEW_OBJECTIVE
                self._review_operation = AUTHORITY_REVIEW_OPERATION
                self._review_action_type = AUTHORITY_REVIEW_ACTION
            elif case in {'general:artifact_consume', 'general:artifact_produce', 'general:review', 'general:handoff', 'general:recovery', 'evidence_integrity:complete', 'context_integrity:complete'}:
                from app.agent_cert_artifact_events import artifact_action_type
                from app.agent_cert_role_review import (
                    ARTIFACT_REVIEW_ACTION, ARTIFACT_REVIEW_OBJECTIVE, ARTIFACT_REVIEW_OPERATION,
                )
                _require((agent, capability) == ('a19', 'responsibility.a19'),
                    'CANONICAL_ZERO_MODEL_EVENT_REQUIRED')
                self._action_type = artifact_action_type(case)
                self._reviewer, self._review_cap = 'a26', 'responsibility.a26'
                self._review_objective = ARTIFACT_REVIEW_OBJECTIVE
                self._review_operation = ARTIFACT_REVIEW_OPERATION
                self._review_action_type = ARTIFACT_REVIEW_ACTION
            else:
                _require((agent, capability, case) == ('a19', 'responsibility.a19', 'baseline:identity'),
                    'CANONICAL_ZERO_MODEL_EVENT_REQUIRED')
                # Fixed source-owned wording; do not import dispatcher/queue and
                # thereby construct runtime domain stores in an operator client.
                self._action_type = 'runtime.status.artifact'
                self._reviewer, self._review_cap = 'a26', 'responsibility.a26'
                self._review_objective = ('Independently review one recorded A19 zero-model identity event '
                    'against its original Objective, artifact and action records; do not certify or sign.')
                self._review_operation = 'certification_identity_review'
                self._review_action_type = 'agent.certification.identity.review'
            self._subject_action_types = {self._action_type}
            if case in {'tool_recovery:tool_failure', 'tool_recovery:bounded_response', 'graceful_degradation:complete', 'tools:complete', 'independent_verification:complete'}:
                from app.agent_cert_tool_events import tool_phases
                self._subject_action_types.update(tool_action_type(case, phase=phase) for phase in tool_phases(case) + ('full',))
            if case in {'general:artifact_consume', 'general:review', 'general:handoff', 'general:recovery', 'evidence_integrity:complete', 'context_integrity:complete'}:
                self._subject_action_types.add(artifact_action_type(case, setup=True))
            if case in {'general:recovery', 'evidence_integrity:complete', 'context_integrity:complete'}:
                self._subject_action_types.add(artifact_action_type(case, prior=True))
            self._spec = json.loads(_canonical(canonical))
            # Tool events retain two extra spans; recovery/integrity add
            # an original prior artifact and its action-pair GET. Existing
            # artifact/handoff cases retain their measured 24-reply cap.
            self._response_limit = 28 if case == 'graceful_degradation:complete' else 26 if case in {'tool_recovery:tool_failure', 'tool_recovery:bounded_response', 'tools:complete', 'independent_verification:complete', 'general:recovery', 'evidence_integrity:complete', 'context_integrity:complete'} else 24
        except Exception:
            raise OperatorBindingError('CANONICAL_ZERO_MODEL_EVENT_REQUIRED') from None
        self._token = owner_token
        self._source, self._image = expected_source_revision, expected_runtime_image
        self._total_seconds, self._request_seconds = total_timeout_seconds, request_timeout_seconds
        self._factory, self._timer_factory, self._clock = connection_factory, timer_factory, monotonic
        self._deadline = None
        self._authorized = False
        self._post_attempts = set()
        self._subject_task = self._review_task = self._review_action = None
        self._artifact_ids = set()
        self._responses = []
        self._response_bytes = 0
        self._lock = threading.Lock()

    def __repr__(self):
        return '<AgentCertOperatorIO credential=[REDACTED] PREPARED_NOT_LIVE>'

    def original_replies(self):
        """Bounded original response custody, never a public logging method."""
        return tuple(self._responses)

    def _now(self):
        try:
            value = self._clock()
            _require(type(value) in (int, float) and math.isfinite(value), 'CLOCK_INVALID')
            return value
        except Exception:
            raise OperatorBindingError('CLOCK_INVALID') from None

    def _remaining(self, request_deadline=None):
        now = self._now()
        if self._deadline is None:
            self._deadline = now + self._total_seconds
        remaining = min(self._deadline, request_deadline if request_deadline is not None else self._deadline) - now
        _require(math.isfinite(remaining) and remaining > 0, 'OPERATOR_DEADLINE_EXCEEDED')
        return remaining

    def _allowed_get(self, path, artifact):
        if artifact:
            return path in {'/api/artifacts/' + value for value in self._artifact_ids}
        paths = {RUNTIME_PATH}
        if self._subject_task:
            paths.add('/api/agents/objectives/' + self._subject_task)
            paths.update('/api/agent-cert-events/actions/' + self._subject_task + '?action_type=' + action
                for action in self._subject_action_types)
        if self._review_task:
            paths.add('/api/agent-cert-events/actions/' + self._review_task + '?action_type=' + self._review_action_type)
        return path in paths

    def _request(self, method, path, *, body=None, artifact=False):
        _require(type(method) is str and type(path) is str and type(artifact) is bool
            and ((method == 'GET' and body is None and self._allowed_get(path, artifact))
                 or (method == 'POST' and path in _POSTS and artifact is False and type(body) is dict)),
            'FIXED_OWNED_API_REQUIRED')
        self._remaining()
        _require(len(self._responses) < self._response_limit and self._response_bytes < MAX_RESPONSE_CUSTODY,
            'PRIVATE_RESPONSE_CUSTODY_BOUND_EXCEEDED')
        try:
            payload = _canonical(body) if body is not None else None
        except Exception:
            raise OperatorBindingError('BOUNDED_REQUEST_REQUIRED') from None
        _require(payload is None or len(payload) <= 128 * 1024, 'BOUNDED_REQUEST_REQUIRED')
        request_deadline = self._now() + min(self._request_seconds, self._remaining())
        if method == 'POST':
            with self._lock:
                _require(self._authorized and path not in self._post_attempts, 'MUTATION_UNAUTHORIZED_OR_REPLAY')
                self._remaining(request_deadline)
                self._post_attempts.add(path)
        headers = {'Host': '127.0.0.1:8000', 'Origin': ORIGIN,
            'Authorization': 'Bearer ' + self._token, 'Accept-Encoding': 'identity'}
        if payload is not None:
            headers['Content-Type'] = 'application/json'
        connection = response = timer = transport_socket = None
        status, raw, recorded = None, bytearray(), False
        try:
            connection = self._factory(HOST, PORT, timeout=self._remaining(request_deadline))
            connection.connect()
            transport_socket = connection.sock
            _require(transport_socket is not None, 'BOUNDED_SOCKET_REQUIRED')
            def expire():
                # Abort the exact fixed request socket; no generic process,
                # credential or service access. Stops slow-drip header/body I/O.
                try:
                    transport_socket.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
            timer = self._timer_factory(self._remaining(request_deadline), expire)
            timer.daemon = True
            timer.start()
            transport_socket.settimeout(self._remaining(request_deadline))
            connection.request(method, path, body=payload, headers=headers)
            transport_socket.settimeout(self._remaining(request_deadline))
            response = connection.getresponse()
            status = response.status
            _require(type(status) is int and 100 <= status <= 599, 'HTTP_STATUS_INVALID')
            _require(not 300 <= status <= 399, 'REDIRECT_FORBIDDEN')
            _require(response.getheader('Content-Encoding', 'identity') == 'identity', 'ENCODED_RESPONSE_FORBIDDEN')
            cap = MAX_ARTIFACT if artifact else MAX_JSON
            framing = _response_framing(response, cap)
            while len(raw) <= cap:
                transport_socket.settimeout(self._remaining(request_deadline))
                chunk = response.read1(min(65536, cap + 1 - len(raw)))
                _require(type(chunk) is bytes, 'HTTP_BODY_INVALID')
                if not chunk:
                    break
                raw.extend(chunk)
                if response.isclosed():
                    break  # Closed alone is not proof of complete framing.
            _require(0 < len(raw) <= cap, 'HTTP_RESPONSE_BOUND_EXCEEDED')
            _framing_complete(response, framing, len(raw))
            raw = bytes(raw)
            _require(len(self._responses) < self._response_limit and self._response_bytes + len(raw) <= MAX_RESPONSE_CUSTODY,
                'PRIVATE_RESPONSE_CUSTODY_BOUND_EXCEEDED')
            self._responses.append(OriginalHTTPReply(method, path, status, raw, True))
            recorded = True
            self._response_bytes += len(raw)
            self._remaining(request_deadline)  # Original bounded bytes retained first.
            if artifact:
                digest = response.getheader('X-Artifact-SHA256', '')
                _require(type(digest) is str and _SHA.fullmatch(digest) is not None
                    and hashlib.sha256(raw).hexdigest() == digest, 'ARTIFACT_DIGEST_INVALID')
                self._remaining(request_deadline)
                return status, raw, digest
            decoded = _decode(raw)
            self._remaining(request_deadline)
            return status, decoded
        except OperatorBindingError:
            raise
        except Exception:
            raise OperatorBindingError('FIXED_LOOPBACK_HTTP_FAILED_NO_RETRY') from None
        finally:
            # A returned bounded partial body is counterevidence, not a valid
            # response or proof. Preserve it if later deadline/shape checks fail.
            if not recorded and type(status) is int and raw and len(raw) <= MAX_JSON + 1:
                original = bytes(raw)
                if len(self._responses) < self._response_limit and self._response_bytes + len(original) <= MAX_RESPONSE_CUSTODY:
                    self._responses.append(OriginalHTTPReply(method, path, status, original, False))
                    self._response_bytes += len(original)
            for obj, name in ((timer, 'cancel'), (response, 'close'), (connection, 'close')):
                if obj is not None:
                    try:
                        getattr(obj, name)()
                    except Exception:
                        pass

    def runtime(self):
        status, value = self._request('GET', RUNTIME_PATH)
        _require(status == 200 and set(value) == {'host_id', 'source_revision', 'version', 'image_digest'}
            and value['source_revision'] == self._source and value['image_digest'] == self._image
            and all(type(value[key]) is str and _IDENTITY.fullmatch(value[key]) is not None
                    and value[key] != 'UNKNOWN' for key in ('host_id', 'version')),
            'AUTHENTICATED_RUNTIME_BINDING_REQUIRED')
        return value

    def authorize(self):
        self._authorized = False
        self.runtime()  # Original route must actually enforce existing Owner auth.
        self._authorized = True

    def submit_objective(self, body):
        try:
            _require(_canonical(body) == _canonical(self._spec['request']), 'CANONICAL_ZERO_MODEL_EVENT_REQUIRED')
        except Exception:
            raise OperatorBindingError('CANONICAL_ZERO_MODEL_EVENT_REQUIRED') from None
        self.runtime()
        status, value = self._request('POST', '/api/agents/objectives', body=body)
        if status == 202 and _uuid(value.get('id')):
            self._subject_task = value['id']
            steps = value.get('steps')
            metadata = steps[0].get('dispatch', {}).get('artifact') if type(steps) is list and len(steps) == 1 and type(steps[0]) is dict else None
            self._remember_artifact(metadata)
            if self._spec['case'] in {'general:artifact_consume', 'general:review', 'general:handoff', 'general:recovery',
                    'tool_recovery:tool_failure', 'tool_recovery:bounded_response', 'graceful_degradation:complete', 'tools:complete', 'independent_verification:complete', 'evidence_integrity:complete', 'context_integrity:complete'}:
                dispatch = steps[0].get('dispatch') if type(steps) is list and len(steps) == 1 and type(steps[0]) is dict else None
                event = dispatch.get('tool_event' if self._spec['case'] in {'tool_recovery:tool_failure','tool_recovery:bounded_response','graceful_degradation:complete', 'tools:complete', 'independent_verification:complete'} else 'artifact_event') if type(dispatch) is dict else None
                if type(event) is dict:
                    self._remember_artifact(event.get('input_artifact_metadata'))
                    if self._spec['case'] in {'general:recovery', 'evidence_integrity:complete', 'context_integrity:complete'}:
                        self._remember_artifact(event.get('prior_artifact_metadata'))
        return status, value

    def _remember_artifact(self, metadata):
        if type(metadata) is dict and type(metadata.get('artifact_id')) is str and _ARTIFACT.fullmatch(metadata['artifact_id']) is not None:
            self._artifact_ids.add(metadata['artifact_id'])

    def dispatch_reviewer(self, body):
        _require(_uuid(self._subject_task), 'OWNED_SUBJECT_TASK_REQUIRED')
        expected = dict(classification='R0', capability=self._review_cap, objective=self._review_objective,
            data_classification='LOCAL_ONLY', minimum_tier='NANO', priority='low', task_class='classification',
            max_cost_usd=0, response_format='strict_json', deterministic_operation=self._review_operation)
        try:
            _require(type(body) is dict and set(body) == set(expected) | {'context'}
                and all(_canonical(body[key]) == _canonical(value) for key, value in expected.items())
                and type(body['context']) is str and 0 < len(body['context'].encode('utf-8')) <= 80000,
                'FIXED_ZERO_MODEL_REVIEW_REQUIRED')
            context = _decode(body['context'].encode('utf-8'))
            _require(set(context) == {'execution', 'expected_execution_sha256', 'expected_source_revision', 'review_nonce'}
                and context['expected_source_revision'] == self._source and _uuid(context['review_nonce'])
                and type(context['execution']) is dict
                and _canonical(context['execution'].get('case_spec')) == _canonical(self._spec)
                and context['execution'].get('dispatch', {}).get('task_id') == self._subject_task
                and context['expected_execution_sha256'] == hashlib.sha256(_canonical(context['execution'])).hexdigest(),
                'FIXED_ZERO_MODEL_REVIEW_REQUIRED')
        except Exception:
            raise OperatorBindingError('FIXED_ZERO_MODEL_REVIEW_REQUIRED') from None
        self.runtime()
        status, value = self._request('POST', '/api/agents/dispatch', body=body)
        if status == 202 and _uuid(value.get('task_id')) and _uuid(value.get('review_action_id')):
            self._review_task, self._review_action = value['task_id'], value['review_action_id']
            self._remember_artifact(value.get('artifact'))
        return status, value

    def read_subject_actions(self, task_id, action_type):
        _require(_uuid(task_id) and task_id == self._subject_task and action_type in self._subject_action_types,
            'OWNED_ACTION_BINDING_REQUIRED')
        return self._actions(task_id, action_type)

    def _actions(self, task, action):
        status, value = self._request('GET', '/api/agent-cert-events/actions/' + task + '?action_type=' + action)
        _require(status == 200 and set(value) == {'schema', 'task_id', 'action_type', 'source_revision', 'original_lines'}
            and value['schema'] == 'prime.original-action-span.v1' and value['task_id'] == task
            and value['action_type'] == action and value['source_revision'] == self._source,
            'ORIGINAL_ACTION_FEED_BINDING_REQUIRED')
        lines = value['original_lines']
        _require(type(lines) is list and 2 <= len(lines) <= 128
            and all(type(line) is str and line.endswith('\n') and 0 < len(line) <= 65536
                    and len(line.encode('utf-8')) <= 65536 for line in lines)
            and sum(len(line.encode('utf-8')) for line in lines) <= MAX_JSON,
            'ORIGINAL_ACTION_FEED_BOUND_EXCEEDED')
        return lines  # Never truncate, rewrite, synthesize or certify the span.

    def read_review_actions(self, action_id):
        _require(_uuid(action_id) and action_id == self._review_action and _uuid(self._review_task),
            'OWNED_ACTION_BINDING_REQUIRED')
        return self._actions(self._review_task, self._review_action_type)

    def io(self):
        def objective(task):
            _require(_uuid(task) and task == self._subject_task, 'OWNED_OBJECTIVE_BINDING_REQUIRED')
            return self._request('GET', '/api/agents/objectives/' + task)
        def artifact(identifier):
            _require(type(identifier) is str and identifier in self._artifact_ids, 'OWNED_ARTIFACT_BINDING_REQUIRED')
            return self._request('GET', '/api/artifacts/' + identifier, artifact=True)
        def no_job(_):
            raise OperatorBindingError('ZERO_MODEL_EVENT_HAS_NO_QUEUE') from None
        return OperatorIO(self.authorize, self.runtime, self.submit_objective, objective,
            no_job, self.dispatch_reviewer, artifact, self.read_review_actions)
