"""Pure HTTP fakes and one temporary-domain chain; no sockets/live services."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import http.client
import io
import json
import traceback

import pytest

from app.agent_cert_role_review import canonical_case_spec
from scripts import agent_cert_operator_io as binding
from tests.test_agent_cert_review_dispatch import configured, SOURCE, IMAGE
from tests.test_collect_agent_cert_event import operator, collect
from tests.test_agent_cert_identity_fleet import PAIRS as IDENTITY_PAIRS


TOKEN = 'fixture-existing-owner-token-not-real'
TASK = '11111111-1111-4111-8111-111111111111'
REVIEW = '22222222-2222-4222-8222-222222222222'
ACTION = '33333333-3333-4333-8333-333333333333'
ARTIFACT = 'a'*32
RUNTIME = dict(host_id='ABEX', source_revision=SOURCE, version='fixture-current', image_digest=IMAGE)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


class FakeSocket:
    def __init__(self):
        self.timeouts, self.shutdowns = [], []
    def settimeout(self, value):
        self.timeouts.append(value)
    def shutdown(self, mode):
        self.shutdowns.append(mode)


class FakeTimer:
    all = []
    def __init__(self, seconds, callback):
        self.seconds, self.callback = seconds, callback
        self.started = self.cancelled = False
        self.all.append(self)
    def start(self):
        self.started = True
    def cancel(self):
        self.cancelled = True


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None, after_read=None, chunk_size=65536):
        self.status = status
        self.stream = io.BytesIO(raw(RUNTIME) if body is None else body)
        self.headers = headers or {}
        self.closed = False
        self.after_read = after_read
        self.chunk_size = chunk_size
        self.chunked, self.length, self.will_close = False, None, True
    def getheader(self, key, default=None):
        return self.headers.get(key, default)
    def getheaders(self):
        return list(self.headers.items())
    def read1(self, count):
        value = self.stream.read(min(count, self.chunk_size))
        if self.after_read:
            self.after_read()
        return value
    def isclosed(self):
        return self.stream.tell() == len(self.stream.getvalue())
    def close(self):
        self.closed = True


class FakeTransport:
    def __init__(self, handler=None):
        self.handler = handler or (lambda method, path, body: FakeResponse())
        self.connections, self.calls = [], []
    def __call__(self, host, port, timeout):
        assert (host, port) == ('127.0.0.1', 8000)
        parent = self
        class Connection:
            def __init__(self):
                self.sock, self.closed = FakeSocket(), False
            def connect(self):
                pass
            def request(self, method, path, *, body, headers):
                assert headers['Authorization'] == 'Bearer '+TOKEN
                assert headers['Host'] == '127.0.0.1:8000'
                assert headers['Origin'] == 'http://127.0.0.1:8000'
                assert headers['Accept-Encoding'] == 'identity'
                assert not any(key.lower().startswith(('x-forwarded', 'forwarded')) for key in headers)
                self.args = method, path, body
                parent.calls.append((method, path, body))
            def getresponse(self):
                self.response = parent.handler(*self.args)
                return self.response
            def close(self):
                self.closed = True
        connection = Connection()
        self.connections.append(connection)
        return connection


def client(transport=None, **changes):
    values = dict(owner_token=TOKEN, spec=canonical_case_spec('a19', 'responsibility.a19', 'baseline:initialization'),
        expected_source_revision=SOURCE, expected_runtime_image=IMAGE,
        connection_factory=transport or FakeTransport(), timer_factory=FakeTimer,
        monotonic=lambda: 0.0)
    values.update(changes)
    return binding.AgentCertOperatorIO(**values)


def test_prepared_client_never_connects_or_discloses_existing_credential():
    transport = FakeTransport()
    item = client(transport)
    assert transport.connections == []
    assert TOKEN not in repr(item) and 'PREPARED_NOT_LIVE' in repr(item)
    assert item.original_replies() == ()
    assert item.io().read_provider_entry is None


def test_bearer_runtime_endpoint_not_public_health_is_authentication():
    transport = FakeTransport()
    item = client(transport)
    assert item.authorize() is None
    assert transport.calls[0][:2] == ('GET', '/api/agent-cert-events/runtime')
    assert item.runtime() == RUNTIME
    assert all(c.closed and c.response.closed for c in transport.connections)
    assert TOKEN not in repr(item.original_replies())
    assert all(r.body_complete is True for r in item.original_replies())


@pytest.mark.parametrize('change', [
    {'owner_token': 'x\r\nInjected: value'}, {'owner_token': 'short'},
    {'owner_token': 'x'*16+'\u00e9'}, {'expected_source_revision': 'UNKNOWN'},
    {'expected_runtime_image': None}, {'total_timeout_seconds': True},
    {'total_timeout_seconds': 31}, {'total_timeout_seconds': float('nan')},
    {'request_timeout_seconds': 3}, {'request_timeout_seconds': float('inf')},
])
def test_invalid_credential_pins_or_budgets_never_connect(change):
    transport = FakeTransport()
    with pytest.raises(binding.OperatorBindingError):
        client(transport, **change)
    assert transport.connections == []


@pytest.mark.parametrize('method,path', [
    ('GET', '/health'), ('GET', '/control/api/jobs'),
    ('GET', 'https://example.com/anything'), ('GET', '//example.com'),
    ('GET', '/api/agents/objectives/'+TASK), ('GET', '/api/artifacts/'+ARTIFACT),
    ('GET', '/api/agent-cert-events/runtime?token=x'), ('POST', '/api/observability/flush'),
])
def test_unowned_arbitrary_external_or_ambient_route_denied(method, path):
    transport = FakeTransport()
    item = client(transport)
    with pytest.raises(binding.OperatorBindingError):
        item._request(method, path, body={} if method == 'POST' else None)
    assert transport.connections == []


@pytest.mark.parametrize('status', [401, 403, 503, True, '200'])
def test_unauthenticated_or_untyped_runtime_never_grants_mutation(status):
    transport = FakeTransport(lambda *args: FakeResponse(status=status))
    item = client(transport)
    with pytest.raises(binding.OperatorBindingError):
        item.authorize()
    assert item._authorized is False
    assert not any(method == 'POST' for method, _, _ in transport.calls)


@pytest.mark.parametrize('body', [
    b'{"source_revision":"wrong","source_revision":"'+SOURCE.encode()+b'"}',
    b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e309}', b'[]', b'not JSON',
    raw({**RUNTIME, 'source_revision': 'a'*40}), raw({**RUNTIME, 'image_digest': 'sha256:'+'0'*64}),
])
def test_decoded_duplicate_nonfinite_or_changed_runtime_denied_and_original_kept(body):
    transport = FakeTransport(lambda *args: FakeResponse(body=body))
    item = client(transport)
    with pytest.raises(binding.OperatorBindingError):
        item.authorize()
    assert item.original_replies()[0].raw == body
    assert TOKEN not in repr(item.original_replies())


@pytest.mark.parametrize('response', [
    FakeResponse(status=302), FakeResponse(headers={'Content-Encoding': 'gzip'}),
    FakeResponse(body=b'x'*(binding.MAX_JSON+1)),
])
def test_redirect_compression_and_body_bound_rejected(response):
    transport = FakeTransport(lambda *args: response)
    item = client(transport)
    with pytest.raises(binding.OperatorBindingError):
        item.authorize()
    assert len(transport.connections) == 1 and transport.connections[0].closed


def test_request_deadline_has_original_partial_custody_and_exact_socket_abort():
    clock = [0.0]
    response = FakeResponse(after_read=lambda: clock.__setitem__(0, 2.1), chunk_size=32)
    transport = FakeTransport(lambda *args: response)
    item = client(transport, monotonic=lambda: clock[0], total_timeout_seconds=10, request_timeout_seconds=2)
    with pytest.raises(binding.OperatorBindingError, match='DEADLINE'):
        item.authorize()
    original = item.original_replies()[0]
    assert original.raw == raw(RUNTIME)[:32] and original.body_complete is False
    assert transport.connections[0].closed
    timer = FakeTimer.all[-1]
    assert timer.started and timer.cancelled and timer.seconds == 2
    timer.callback()
    assert transport.connections[0].sock.shutdowns == [binding.socket.SHUT_RDWR]


def test_total_deadline_is_not_reset_between_requests():
    clock = [0.0]
    transport = FakeTransport()
    item = client(transport, monotonic=lambda: clock[0], total_timeout_seconds=1)
    item.authorize()
    clock[0] = 1.1
    with pytest.raises(binding.OperatorBindingError, match='DEADLINE'):
        item.runtime()
    assert len(transport.connections) == 1


def test_decode_work_cannot_escape_request_deadline(monkeypatch):
    # Deliberately inject time advancement, never burn CPU to test a deadline.
    clock = [0.0]
    original = binding._decode
    def slow(raw_reply):
        value = original(raw_reply)
        clock[0] = 2.1
        return value
    monkeypatch.setattr(binding, '_decode', slow)
    transport = FakeTransport()
    item = client(transport, monotonic=lambda: clock[0], total_timeout_seconds=10)
    with pytest.raises(binding.OperatorBindingError, match='DEADLINE'):
        item.authorize()
    assert item._authorized is False
    assert item.original_replies()[0].body_complete is True
    assert item.original_replies()[0].raw == raw(RUNTIME)


def wire_response(header, body):
    # Actual stdlib framing, backed only by BytesIO: no socket or server.
    class WireSocket:
        def makefile(self, mode):
            return io.BytesIO(b'HTTP/1.1 200 OK\r\n' + header + b'\r\n' + body)
    response = http.client.HTTPResponse(WireSocket())
    response.begin()
    return response


@pytest.mark.parametrize('kind', ['length-one', 'length-ten', 'missing-final-chunk',
    'incomplete-chunk', 'missing-trailer-terminator', 'duplicate-length', 'invalid-length'])
def test_real_http_framing_incomplete_or_ambiguous_never_authorizes(kind):
    original = raw(RUNTIME)
    length = str(len(original)).encode()
    chunk = format(len(original), 'x').encode() + b'\r\n' + original + b'\r\n'
    if kind.startswith('length-'):
        extra = 1 if kind == 'length-one' else 10
        header, body = b'Content-Length: ' + str(len(original)+extra).encode() + b'\r\n', original
    elif kind == 'missing-final-chunk':
        header, body = b'Transfer-Encoding: chunked\r\n', chunk
    elif kind == 'incomplete-chunk':
        header, body = b'Transfer-Encoding: chunked\r\n', format(len(original)+10, 'x').encode()+b'\r\n'+original
    elif kind == 'missing-trailer-terminator':
        header, body = b'Transfer-Encoding: chunked\r\n', chunk+b'0\r\n'
    elif kind == 'duplicate-length':
        header, body = b'Content-Length: '+length+b'\r\nContent-Length: '+length+b'\r\n', original
    else:
        header, body = b'Content-Length: malformed\r\n', original
    response = wire_response(header, body)
    transport = FakeTransport(lambda *args: response)
    item = client(transport)
    with pytest.raises(binding.OperatorBindingError):
        item.authorize()
    assert item._authorized is False
    if kind not in ('duplicate-length', 'invalid-length'):
        assert item.original_replies()[0].raw == original
        assert item.original_replies()[0].body_complete is False
    assert transport.connections[0].closed


@pytest.mark.parametrize('kind', ['length', 'chunked', 'close'])
def test_real_http_complete_framing_remains_supported(kind):
    original = raw(RUNTIME)
    if kind == 'length':
        header, body = b'Content-Length: '+str(len(original)).encode()+b'\r\n', original
    elif kind == 'chunked':
        header = b'Transfer-Encoding: chunked\r\n'
        body = format(len(original), 'x').encode()+b'\r\n'+original+b'\r\n0\r\n\r\n'
    else:
        header, body = b'Connection: close\r\n', original
    item = client(FakeTransport(lambda *args: wire_response(header, body)))
    assert item.authorize() is None
    assert item._authorized is True
    assert item.original_replies()[0].raw == original
    assert item.original_replies()[0].body_complete is True


def test_interrupted_post_is_consumed_and_secret_error_suppressed():
    def handler(method, path, body):
        if method == 'POST':
            raise RuntimeError('DO_NOT_EXPOSE '+TOKEN)
        return FakeResponse()
    transport = FakeTransport(handler)
    item = client(transport)
    item.authorize()
    for _ in range(2):
        with pytest.raises(binding.OperatorBindingError) as error:
            item.submit_objective(item._spec['request'])
        rendered = ''.join(traceback.format_exception(error.value))
        assert TOKEN not in rendered and 'DO_NOT_EXPOSE' not in rendered
    assert sum(method == 'POST' for method, _, _ in transport.calls) == 1
    assert all(c.closed for c in transport.connections)


@pytest.mark.parametrize('change', [
    {'deterministic_operation': None}, {'capability': 'responsibility.a26'},
    {'context': 'untrusted replacement'}, {'max_cost_usd': 0.002},
    {'data_classification': 'CLOUD_PERMITTED'},
])
def test_subject_scope_not_arbitrary_inference(change):
    transport = FakeTransport()
    item = client(transport)
    with pytest.raises(binding.OperatorBindingError):
        item.submit_objective({**item._spec['request'], **change})
    assert transport.connections == []


def test_reviewer_and_action_binding_cannot_read_unrelated_evidence():
    item = client()
    for callback, args in ((item.read_subject_actions, (TASK, 'runtime.status.artifact')),
                           (item.read_review_actions, (ACTION,)), (item.io().read_job, (TASK,))):
        with pytest.raises(binding.OperatorBindingError):
            callback(*args)
    with pytest.raises(binding.OperatorBindingError):
        item.dispatch_reviewer({'capability': 'responsibility.a19', 'context': '{}'})


def test_reviewer_cannot_post_when_no_original_subject_task_was_captured():
    transport = FakeTransport()
    item = client(transport)
    item.authorize()
    # Both missing task values compare equal; that is not an owned UUID.
    execution = {'case_spec': item._spec, 'dispatch': {'task_id': None}}
    context = dict(execution=execution, expected_execution_sha256=hashlib.sha256(raw(execution)).hexdigest(),
        expected_source_revision=SOURCE, review_nonce=ACTION)
    body = dict(classification='R0', capability=item._review_cap, objective=item._review_objective,
        context=raw(context).decode(), data_classification='LOCAL_ONLY', minimum_tier='NANO',
        priority='low', task_class='classification', max_cost_usd=0, response_format='strict_json',
        deterministic_operation=item._review_operation)
    with pytest.raises(binding.OperatorBindingError, match='OWNED_SUBJECT_TASK_REQUIRED'):
        item.dispatch_reviewer(body)
    assert not any(method == 'POST' for method, _, _ in transport.calls)


@pytest.mark.parametrize('case', ['baseline:initialization', 'baseline:identity'])
def test_complete_zero_model_collection_through_fake_http_and_actual_temporary_domains(operator, monkeypatch, case):
    # Root's new server feeds are represented as wire fakes here. They are
    # not deployed routes or live authenticated transport in this source test.
    subject_task = [None]
    def handler(method, path, body):
        if path == binding.RUNTIME_PATH:
            return FakeResponse(body=raw(operator.runtime()))
        if path == '/api/agents/objectives':
            status, reply = operator.submit(json.loads(body))
            subject_task[0] = reply['id']
            return FakeResponse(status, raw(reply))
        if path == '/api/agents/dispatch':
            status, reply = operator.reviewer(json.loads(body))
            return FakeResponse(status, raw(reply))
        if path.startswith('/api/agents/objectives/'):
            status, reply = operator.objective(path.rsplit('/', 1)[1])
            return FakeResponse(status, raw(reply))
        if path.startswith('/api/artifacts/'):
            status, original, digest = operator.artifact(path.rsplit('/', 1)[1])
            return FakeResponse(status, original, {'X-Artifact-SHA256': digest})
        task = path.split('/actions/')[1].split('?')[0]
        action = path.split('?action_type=')[1]
        if case == 'baseline:identity':
            from fastapi import Response
            from app import agent_cert_event_api, agent_dispatch_api
            monkeypatch.setattr(agent_cert_event_api, 'authenticate_owner', agent_dispatch_api.authenticate_owner)
            lines = agent_cert_event_api.actions(task, Response(), action, 'fixture-owner')['original_lines']
            if task == subject_task[0]:
                operator.subject_lines = lines
            else:
                operator.review_lines = lines
        else:
            lines = operator.subject_actions(task, action) if task == subject_task[0] else operator.reviewer_actions(operator.review['review_action_id'])
        return FakeResponse(body=raw(dict(schema='prime.original-action-span.v1', task_id=task,
            action_type=action, source_revision=SOURCE, original_lines=lines)))
    transport = FakeTransport(handler)
    item = client(transport, spec=canonical_case_spec('a26', 'responsibility.a25', case))
    result = collect(operator, agent='a26', cap='responsibility.a25', case=case, io=item.io(), actions=item.read_subject_actions)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', result.summary
    assert result.summary['reviewer_identity'] == 'a18'
    assert result.summary['model_calls'] == 0 and result.summary['signature'] == 'NOT_PERFORMED'
    assert sum(method == 'POST' for method, _, _ in transport.calls) == 2
    assert operator.calls.count('submit') == operator.calls.count('review') == 1
    assert result.subject_actions == tuple(operator.subject_lines)
    assert result.reviewer_actions == tuple(operator.review_lines)
    assert all(c.closed and c.response.closed for c in transport.connections)
    assert all(timer.cancelled for timer in FakeTimer.all)
    assert TOKEN not in repr(item.original_replies())
    assert not any(path == '/health' or path.startswith('/control') for _, path, _ in transport.calls)


@pytest.mark.parametrize('agent,cap', IDENTITY_PAIRS)
def test_owned_identity_transport_constructor_has_exact_source_contract_without_connecting(agent, cap):
    from app import agent_cert_identity_fleet as identity
    transport = FakeTransport()
    item = client(transport, spec=canonical_case_spec(agent, cap, identity.CASE))
    assert transport.connections == [] and item.original_replies() == ()
    assert item._subject_action_types == {identity.ACTION_TYPE}
    assert (item._reviewer, item._review_cap) == identity.identity_reviewer(agent, cap)
    assert item._reviewer != agent and item._review_objective == identity.identity_review_objective(agent, cap)
    assert item._review_action_type == identity.REVIEW_ACTION
    assert item._review_operation == 'certification_identity_review'


def test_source_interface_has_no_credential_or_ledger_file_reader():
    from pathlib import Path
    source = Path(binding.__file__).read_text(encoding='utf-8')
    for forbidden in ('os.getenv', 'os.environ', 'subprocess', 'read_bytes(', 'write_bytes(',
                      'read_action_span(', 'if __name__', 'sign_digest(', 'requests.', 'httpx.'):
        assert forbidden not in source
