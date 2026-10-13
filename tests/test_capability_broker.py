"""Isolated permissions/security checks, not live internet or certification."""
import json
import socket
import pytest
from app import public_http
from app.capability_broker import ServiceRequest,execute_request,permissions,INFRA_READ
from app.agent_registry import registered_agent_ids
from app.action_records import ActionLedger

AGENTS=sorted(registered_agent_ids(include_orchestrator=False))
JOB='11111111-1111-4111-8111-111111111111'
class Queue:
    def __init__(self,agent):self.agent=agent
    def get(self,key):return {'id':key,'agent':self.agent,'prompt':'OWNER_TASK_CONTEXT','data_classification':'CLOUD_PERMITTED'}
    def metrics(self):return {'statuses':{'completed':1},'policy':{'local':1}}

@pytest.mark.parametrize('agent',AGENTS)
def test_every_actor_has_common_read_path_and_own_private_scope(agent,tmp_path):
    ledger=ActionLedger(tmp_path/'audit.jsonl');queue=Queue(agent)
    try:
        public=execute_request(ServiceRequest(agent=agent,job_id=JOB,service='internet.public.read',parameters={'url':'https://example.com'}),
             job_queue=queue,reader=lambda url:{'status':200,'content':'UNTRUSTED DATA'},ledger=ledger)
        private=execute_request(ServiceRequest(agent=agent,job_id=JOB,service='private.task.metadata.read'),job_queue=queue,ledger=ledger)
        assert public['audit_persisted'] and private['result']['prompt_or_credential_content_returned'] is False
        with pytest.raises(PermissionError):execute_request(ServiceRequest(agent=agent,job_id=JOB,service='infrastructure.apply'),job_queue=queue,ledger=ledger)
        assert not public['full_role_acceptance_awarded']
        events=[json.loads(line) for line in (tmp_path/'audit.jsonl').read_text().splitlines()]
        assert len(events)==6 and events[-1]['success'] is False
        assert 'OWNER_TASK_CONTEXT' not in (tmp_path/'audit.jsonl').read_text()
    finally:ledger.close()

@pytest.mark.parametrize('agent',AGENTS)
def test_infrastructure_read_and_sandbox_follow_role_policy(agent):
    policy=permissions(agent)
    assert policy['infrastructure.status.read']==(agent in INFRA_READ)
    assert policy['sandbox.wasm.execute']==(agent in {'a17','a18'})
    assert not policy['infrastructure.apply'] and not policy['secrets.request']

def test_spoofed_actor_never_calls_reader(tmp_path):
    ledger=ActionLedger(tmp_path/'audit.jsonl');calls=[]
    try:
        with pytest.raises(PermissionError):execute_request(ServiceRequest(agent='a01',job_id=JOB,service='internet.public.read',parameters={'url':'https://example.com'}),
           job_queue=Queue('a02'),reader=lambda url:calls.append(url),ledger=ledger)
        assert not calls
        events=[json.loads(line) for line in (tmp_path/'audit.jsonl').read_text().splitlines()]
        assert events[-1]['agent_id']=='boundary' and events[-1]['success'] is False
    finally:ledger.close()

@pytest.mark.parametrize('url',['http://example.com','file:///etc/passwd','https://name:secret@example.com','https://example.com:8443',
                              'https://example.com/#fragment','https://example.com/?access_token=hidden'])
def test_unsafe_urls_denied_before_dns(url,monkeypatch):
    monkeypatch.setattr(public_http,'resolve_addresses',lambda *a,**k:pytest.fail('unsafe URL must not resolve'))
    with pytest.raises((ValueError,PermissionError)):public_http.public_target(url)

@pytest.mark.parametrize('address',['127.0.0.1','192.168.1.23','169.254.169.254','10.0.0.1','::1','::ffff:127.0.0.1','224.0.0.1'])
def test_private_metadata_loopback_and_multicast_denied(address,monkeypatch):
    monkeypatch.setattr(public_http,'resolve_addresses',lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',(address,443))])
    with pytest.raises(PermissionError):public_http.public_target('https://example.com')

def test_dns_mixed_public_private_answer_denied(monkeypatch):
    monkeypatch.setattr(public_http,'resolve_addresses',lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443)),
                                                        (socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))])
    with pytest.raises(PermissionError):public_http.public_target('https://example.com')

def test_public_redirect_cannot_reach_private_network(monkeypatch):
    monkeypatch.setattr(public_http,'resolve_addresses',lambda host,*a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1' if host=='internal' else '8.8.8.8',443))])
    class Response:
        status=302
        def getheader(self,key):return 'https://internal/'
        def close(self):pass
    class Connection:
        def __init__(self,*a):pass
        def request(self,*a,**k):pass
        def getresponse(self):return Response()
        def close(self):pass
        def abort(self):pass
    monkeypatch.setattr(public_http,'PinnedHTTPS',Connection)
    with pytest.raises(PermissionError):public_http.public_read('https://example.com')

def test_private_credentials_never_follow_redirect(monkeypatch):
    monkeypatch.setattr(public_http,'public_target',lambda url,*args:(type('P',(),{'path':'/api'})(),'example.com',None))
    calls=[]
    class Connection:
        def __init__(self,*a):pass
        def request(self,*a,**k):calls.append(k)
        def getresponse(self):return type('R',(),{'status':302,'close':lambda self:None})()
        def close(self):pass
        def abort(self):pass
    monkeypatch.setattr(public_http,'PinnedHTTPS',Connection)
    with pytest.raises(RuntimeError):public_http.fixed_private_json('https://example.com/api',{'Authorization':'Bearer PRIVATE'})
    assert len(calls)==1


def test_shared_admission_bounds_core_agents_and_same_actor():
    from app.capability_broker import service_admission,ServiceBusy
    with service_admission('a01'):
        with pytest.raises(ServiceBusy):
            with service_admission('a01'):pass
        with service_admission('a02'):
            with pytest.raises(ServiceBusy):
                with service_admission('prime'):pass
    with service_admission('prime'):pass


def test_connection_close_slow_body_is_interrupted_by_owned_transport(monkeypatch):
    """Actual disposable local socket; production DNS/TLS is not bypassed."""
    import threading,time
    server=socket.socket();server.bind(('127.0.0.1',0));server.listen(1)
    address=server.getsockname()
    def serve():
        try:
            client,_=server.accept()
            with client:
                client.recv(4096)
                client.sendall(b'HTTP/1.0 200 OK\r\nConnection: close\r\nContent-Length: 10\r\n\r\na')
                for _ in range(9):time.sleep(.1);client.sendall(b'a')
        except OSError:pass
        finally:server.close()
    worker=threading.Thread(target=serve,daemon=True);worker.start()
    class ControlledConnection(public_http.PinnedHTTPS):
        def connect(self):
            self.sock=socket.create_connection(address,timeout=1)
            self.guard_socket=self.sock.dup()
    monkeypatch.setattr(public_http,'PinnedHTTPS',ControlledConnection)
    monkeypatch.setattr(public_http,'public_target',lambda url,*args:(type('P',(),{'path':'/','query':''})(),'example.com',None))
    original_timer=public_http.deadline_timer
    monkeypatch.setattr(public_http,'deadline_timer',lambda connection,*args:original_timer(connection,.05))
    started=time.monotonic()
    with pytest.raises((TimeoutError,OSError,public_http.http.client.IncompleteRead)):
        public_http.public_read('https://example.com')
    assert time.monotonic()-started<.6
    worker.join(1)


def test_unknown_actor_denial_is_durable_and_sanitized(tmp_path):
    ledger=ActionLedger(tmp_path/'audit.jsonl');calls=[]
    try:
        with pytest.raises(PermissionError):execute_request(ServiceRequest(agent='x01',job_id=JOB,service='internet.public.read',parameters={'url':'https://example.com'}),
            job_queue=Queue('x01'),reader=lambda url:calls.append(url),ledger=ledger)
        events=[json.loads(line) for line in (tmp_path/'audit.jsonl').read_text().splitlines()]
        assert not calls and events[-1]['success'] is False
        assert events[-1]['agent_id']=='boundary'
        assert 'https://example.com' not in (tmp_path/'audit.jsonl').read_text()
    finally:ledger.close()


def test_job_id_is_canonical_uuid():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):ServiceRequest(agent='a01',job_id='x'*36,service='internet.public.read')


def test_core_parameters_obey_agent_resource_bounds(tmp_path):
    from app.capability_broker import CoreRequest,execute_core_request
    ledger=ActionLedger(tmp_path/'audit.jsonl');calls=[]
    try:
        for parameters in ({'url':'https://example.com/'+'x'*262144},{'url':float('nan')}):
            with pytest.raises(ValueError):execute_core_request(CoreRequest(request_id='bounded',service='internet.public.read',parameters=parameters),
                reader=lambda url:calls.append(url),ledger=ledger)
        assert not calls
    finally:ledger.close()


@pytest.mark.parametrize('raw',[b'\xff\x00\x80',b'x'*public_http.MAX_BYTES,b'x'*(public_http.MAX_BYTES+1)])
def test_public_byte_limit_and_binary_integrity(raw,monkeypatch):
    import base64,hashlib
    address=(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))
    monkeypatch.setattr(public_http,'public_target',lambda url,*args:(type('P',(),{'path':'/','query':''})(),'example.com',address))
    class Response:
        status=200
        def getheader(self,key,default=None):return default
        def read(self,limit):return raw
        def close(self):pass
    class Connection:
        def __init__(self,*args):pass
        def request(self,*args,**kwargs):pass
        def getresponse(self):return Response()
        def close(self):pass
        def abort(self):pass
    monkeypatch.setattr(public_http,'PinnedHTTPS',Connection)
    if len(raw)>public_http.MAX_BYTES:
        with pytest.raises(ValueError,match='byte limit'):public_http.public_read('https://example.com')
        return
    result=public_http.public_read('https://example.com')
    if raw.startswith(b'\xff'):assert result['content'] is None
    assert hashlib.sha256(base64.b64decode(result['content_base64'])).hexdigest()==result['source_sha256']
    assert result['destination_ip']=='8.8.8.8' and result['observed_at']


def test_dns_timeout_uses_remaining_operation_budget(monkeypatch):
    calls=[]
    def resolve(host,timeout=3):
        calls.append(timeout)
        raise public_http.subprocess.TimeoutExpired('fixture-resolver',timeout)
    monkeypatch.setattr(public_http,'resolve_addresses',resolve)
    monkeypatch.setattr(public_http.time,'monotonic',lambda:10)
    with pytest.raises(public_http.subprocess.TimeoutExpired):public_http.public_target('https://example.com',10.25)
    assert calls==[.25]


def test_redirects_share_dns_and_http_deadline(monkeypatch):
    times=iter([0,1,2,3,4,5,6,7,8,9,10])
    monkeypatch.setattr(public_http.time,'monotonic',lambda:next(times))
    monkeypatch.setattr(public_http,'TOTAL_SECONDS',6)
    deadlines=[]
    def target(url,deadline):
        deadlines.append(deadline)
        public_http.remaining_time(deadline)
        return type('P',(),{'path':'/','query':''})(),'example.com',None
    monkeypatch.setattr(public_http,'public_target',target)
    class Response:
        status=302
        def getheader(self,key):return '/next'
        def close(self):pass
    class Connection:
        def __init__(self,*args):pass
        def request(self,*args,**kwargs):pass
        def getresponse(self):return Response()
        def close(self):pass
        def abort(self):pass
    monkeypatch.setattr(public_http,'PinnedHTTPS',Connection)
    with pytest.raises(TimeoutError):public_http.public_read('https://example.com')
    assert len(deadlines)>=2 and set(deadlines)=={6}


def test_tls_hostname_failure_on_pinned_socket_cleans_up(tmp_path,monkeypatch):
    """A real local TLS peer; production URL admission is not changed."""
    import ssl,threading
    from datetime import datetime,timedelta,timezone
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')])
    now=datetime.now(timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
          .not_valid_after(now+timedelta(minutes=5))
          .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),critical=False).sign(key,hashes.SHA256()))
    cert_path=tmp_path/'tls.crt';key_path=tmp_path/'tls.key'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    server=socket.socket();server.bind(('127.0.0.1',0));server.listen(1);server.settimeout(2)
    address=server.getsockname()
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert_path,key_path)
    def serve():
        try:
            client,_=server.accept()
            with client:
                with context.wrap_socket(client,server_side=True):pass
        except (OSError,ssl.SSLError):pass
        finally:server.close()
    worker=threading.Thread(target=serve,daemon=True);worker.start()
    connection=public_http.PinnedHTTPS('wrong.example',(socket.AF_INET,socket.SOCK_STREAM,6,'',address))
    connection._context.load_verify_locations(cert_path)
    monkeypatch.setattr(socket,'getaddrinfo',lambda *args,**kwargs:pytest.fail('Pinned connect must not resolve again'))
    try:
        with pytest.raises(ssl.SSLCertVerificationError):connection.connect()
        assert connection.sock is None and connection.guard_socket is None
    finally:connection.dispose();worker.join(2)


def test_tls_handshake_without_server_response_is_interrupted():
    import threading,time
    server=socket.socket();server.bind(('127.0.0.1',0));server.listen(1);server.settimeout(1)
    address=server.getsockname()
    release=threading.Event()
    def serve():
        try:
            client,_=server.accept()
            with client:release.wait(.5)
        except OSError:pass
        finally:server.close()
    worker=threading.Thread(target=serve,daemon=True);worker.start()
    connection=public_http.PinnedHTTPS('example.com',(socket.AF_INET,socket.SOCK_STREAM,6,'',address))
    watchdog=public_http.deadline_timer(connection,.05)
    started=time.monotonic()
    try:
        with pytest.raises((OSError,TimeoutError)):connection.connect()
        assert watchdog.expired.is_set() and time.monotonic()-started<.4
        assert connection.sock is None and connection.guard_socket is None
    finally:
        watchdog.cancel();watchdog.join();connection.dispose();release.set();worker.join(1)
