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
    class Connection:
        def __init__(self,*a):pass
        def request(self,*a,**k):pass
        def getresponse(self):return Response()
        def close(self):pass
        def abort(self):pass
    monkeypatch.setattr(public_http,'PinnedHTTPS',Connection)
    with pytest.raises(PermissionError):public_http.public_read('https://example.com')

def test_private_credentials_never_follow_redirect(monkeypatch):
    monkeypatch.setattr(public_http,'public_target',lambda url:(type('P',(),{'path':'/api'})(),'example.com',None))
    calls=[]
    class Connection:
        def __init__(self,*a):pass
        def request(self,*a,**k):calls.append(k)
        def getresponse(self):return type('R',(),{'status':302})()
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
    import os,threading,time
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
            self.guard_socket=socket.socket(fileno=os.dup(self.sock.fileno()))
    monkeypatch.setattr(public_http,'PinnedHTTPS',ControlledConnection)
    monkeypatch.setattr(public_http,'public_target',lambda url:(type('P',(),{'path':'/','query':''})(),'example.com',None))
    original_timer=public_http.deadline_timer
    monkeypatch.setattr(public_http,'deadline_timer',lambda connection,*args:original_timer(connection,.05))
    started=time.monotonic()
    with pytest.raises((TimeoutError,OSError,public_http.http.client.IncompleteRead)):
        public_http.public_read('https://example.com')
    assert time.monotonic()-started<.6
    worker.join(1)
