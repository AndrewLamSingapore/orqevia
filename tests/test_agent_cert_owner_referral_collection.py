"""Disposable HTTPS ASGI source lab; no real TLS endpoint or Owner identity claim."""
import json,ssl
import pytest
from fastapi.testclient import TestClient
from app import pwa_sessions as pwa,owner_referrals as referrals
from scripts.agent_cert_operator_io import OwnerPhaseOperatorIO,OperatorBindingError
from scripts.collect_agent_cert_event import collect_owner_referral_case
from tests.test_agent_cert_authority_chain import runtime
from tests.test_agent_cert_review_dispatch import configured,SOURCE,IMAGE
from tests.test_agent_cert_operator_io import TOKEN,FakeTransport,FakeTimer,FakeResponse,FakeSocket
from tests.test_agent_cert_owner_referral_events import ORIGIN,LOCAL,HEADERS

COOKIE='__Host-JARVIS-PWA=source_lab_existing_token_123456'

@pytest.fixture(autouse=True)
def configured_lab_pwa_origin(monkeypatch):
    monkeypatch.setenv('PRIME_PWA_ORIGIN',ORIGIN)
    monkeypatch.delenv('PRIME_PWA_ADDITIONAL_ORIGINS',raising=False)

def prepared(**changes):
    values=dict(owner_token=TOKEN,which='proposal',expected_source_revision=SOURCE,
        expected_runtime_image=IMAGE,approved_pwa_origin=ORIGIN,owner_session_cookie=COOKIE,
        connection_factory=FakeTransport(),timer_factory=FakeTimer)
    values.update(changes);return OwnerPhaseOperatorIO(**values)

@pytest.mark.parametrize('origin',[None,'http://127.0.0.1:8000','https://user:pass@local.invalid',
    'https://local.invalid/','https://local.invalid/path','https://local.invalid?q=1',
    'https://local.invalid#x','https://local.invalid:0','https://local.invalid:99999','https://local.invalid\r\nHeader:x'])
def test_explicit_https_origin_required_without_transport(origin):
    with pytest.raises(OperatorBindingError):prepared(approved_pwa_origin=origin)

@pytest.mark.parametrize('cookie',[None,'','other=abc','__Host-JARVIS-PWA=short',COOKIE+'; extra=1',COOKIE+'\r\nX:1'])
def test_cookie_must_be_explicit_single_existing_host_cookie(cookie):
    with pytest.raises(OperatorBindingError):prepared(owner_session_cookie=cookie)

def test_construct_does_not_connect_or_disclose_cookie():
    transport=FakeTransport();value=prepared(connection_factory=transport)
    assert not transport.calls and not transport.connections
    assert TOKEN not in repr(value) and COOKIE not in repr(value)
    with pytest.raises(OperatorBindingError):value.acknowledge_owner_referral()
    assert not transport.calls

def test_owner_transport_cannot_activate_or_submit_fresh_input_protocol():
    transport=FakeTransport();value=prepared(connection_factory=transport)
    assert value._execution_input is None and value._execution_input_body is None
    assert value._execution_input_tasks=={}
    with pytest.raises(OperatorBindingError,match='ORIGINAL_CLIENT_INITIALIZATION_REQUIRED'):
        value.activate_execution_input('fresh_challenge:complete',{})
    with pytest.raises(OperatorBindingError,match='EXECUTION_INPUT_STAGE_OR_REPLAY_DENIED'):
        value.execution_input_stage(nonce='00000000-0000-4000-8000-000000000001')
    assert not transport.calls and not transport.connections

class FramedASGIResponse(FakeResponse):
    def __init__(self,**kwargs):
        super().__init__(**kwargs);self.length=len(self.stream.getvalue())
    def getheader(self,key,default=None):
        return next((v for k,v in self.headers.items() if k.lower()==key.lower()),default)
    def read1(self,count):
        value=super().read1(count);self.length-=len(value);return value

class ASGISourceTransport:
    def __init__(self,client,*,pwa_surface=False):self.client=client;self.pwa_surface=pwa_surface;self.calls=[];self.tls_contexts=[]
    def __call__(self,host,port,timeout,context=None):
        if self.pwa_surface:
            assert (host,port)==('192.168.1.23',8443)
            assert context.verify_mode==ssl.CERT_REQUIRED and context.check_hostname
            self.tls_contexts.append(context)
        else:assert (host,port)==('127.0.0.1',8000) and context is None
        parent=self
        class Connection:
            def __init__(self):self.sock=FakeSocket()
            def connect(self):pass
            def request(self,method,path,*,body,headers):
                if parent.pwa_surface:
                    assert 'Authorization' not in headers and headers['Origin']==ORIGIN
                    assert headers['Host']=='192.168.1.23:8443'
                    assert not any(k.lower().startswith(('forwarded','x-forwarded')) for k in headers)
                    if method=='POST':assert body is None and headers['X-JARVIS-PWA']=='1'
                else:assert 'Cookie' not in headers and headers['Authorization']=='Bearer '+TOKEN
                # Never preserve secret headers in source evidence.
                parent.calls.append((method,path,body))
                response=parent.client.request(method,path,content=body,headers=headers)
                self.response=FramedASGIResponse(status=response.status_code,body=response.content,
                    headers={k.title():v for k,v in response.headers.items()})
            def getresponse(self):return self.response
            def close(self):pass
        return Connection()

def test_actual_collector_https_advisory_and_distinct_original_peer(runtime,monkeypatch):
    monkeypatch.setenv('PRIME_PWA_ORIGIN',ORIGIN);monkeypatch.setenv('PRIME_PWA_OWNER_ORIGIN',LOCAL)
    monkeypatch.setenv('PRIME_PWA_OWNER_ACCOUNT_ID','public-source-fixture-owner')
    app=runtime.client.app
    for router in (pwa.router,pwa.owner_router,referrals.router):app.include_router(router)
    app.add_middleware(pwa.PWASessionMiddleware)
    # Disposable fixture enrollment only. The production collector never enrolls or discovers a cookie.
    with TestClient(app,base_url=LOCAL,client=('127.0.0.1',50000)) as local:
        issued=local.post('/pwa/owner/pairing',headers=dict(HEADERS,Origin=LOCAL,**{'X-Jarvis-PWA':'1'}),json={'role':'OWNER'})
        assert issued.status_code==200
    with TestClient(app,base_url=ORIGIN) as owner:
        enrolled=owner.post('/pwa/api/enroll',headers={'Origin':ORIGIN,'X-Jarvis-PWA':'1'},json={'code':issued.json()['code']})
        assert enrolled.status_code==200
        cookie='__Host-JARVIS-PWA='+owner.cookies.get('__Host-JARVIS-PWA')
        spine=ASGISourceTransport(runtime.client);surface=ASGISourceTransport(owner,pwa_surface=True);operators=[]
        def factory(**kwargs):
            operator=OwnerPhaseOperatorIO(owner_token=TOKEN,expected_source_revision=SOURCE,expected_runtime_image=IMAGE,
                approved_pwa_origin=ORIGIN,owner_session_cookie=cookie,connection_factory=spine,
                pwa_connection_factory=surface,timer_factory=FakeTimer,**kwargs)
            operators.append(operator);return operator
        result=collect_owner_referral_case(operator_factory=factory,expected_source_revision=SOURCE,
            expected_runtime_image=IMAGE,expected_registry_sha256=runtime.registry_sha)
        assert result.summary['state']=='UNSIGNED_EVENT_EVIDENCE',json.dumps(result.summary,sort_keys=True)
        assert result.summary['submission_attempts']==2
        assert result.summary['owner_acknowledgment']=='NOT_APPROVED'
        assert len(surface.calls)==3 and [c[0] for c in surface.calls]==['GET','POST','GET']
        assert len(surface.tls_contexts)==3
        execution=json.loads(result.execution_bytes);peer=json.loads(result.peer_execution_bytes)
        assert len(execution['original_action_records'])==8 and len(peer['action_records'])==2
        assert execution['dispatch']['task_id']!=peer['dispatch']['task_id']
        assert cookie not in repr(result) and cookie not in result.execution_bytes.decode()+result.peer_execution_bytes.decode()
        before=len(surface.calls)
        with pytest.raises(OperatorBindingError):operators[0].acknowledge_owner_referral()
        assert len(surface.calls)==before+1 # Original immutable reread allowed; acknowledgment POST never replayed.


@pytest.mark.parametrize('fault',['redirect','forbidden','approval','performed','wrong_proposal','uncertain_post'])
def test_owner_surface_failure_preserves_originals_never_replays_or_dispatches_peer(fault):
    # Transport contract fake only, never represented as authentic Owner proof.
    import uuid
    identifier=str(uuid.uuid4());task=str(uuid.uuid4())
    proposal=dict(proposal=dict(referral_id=identifier,task_id=task),proposal_sha256='a'*64,
        state='PENDING_OWNER_ACK',acknowledgment=None,execution_authority='NONE',execution_performed=False)
    ack=dict(proposal, state='ACKNOWLEDGED_NOT_APPROVED',acknowledgment={'decision':'ACKNOWLEDGED_NOT_APPROVED'})
    if fault=='approval':ack['state']='APPROVED'
    if fault=='performed':ack['execution_performed']=True
    if fault=='wrong_proposal':ack['proposal']={'referral_id':str(uuid.uuid4())}
    calls=[]
    def tls_factory(host,port,timeout,context):
        assert context.verify_mode==ssl.CERT_REQUIRED and context.check_hostname
        class Connection:
            def __init__(self):self.sock=FakeSocket()
            def connect(self):pass
            def request(self,method,path,*,body,headers):
                assert 'Authorization' not in headers and headers['Cookie']==COOKIE
                calls.append((method,path,body));self.method=method
                if fault=='uncertain_post' and method=='POST':raise OSError('disposable uncertain transport')
            def getresponse(self):
                status=302 if fault=='redirect' else 403 if fault=='forbidden' else 200
                return FakeResponse(status=status,body=json.dumps(proposal if self.method=='GET' else ack).encode())
            def close(self):pass
        return Connection()
    operator=prepared(pwa_connection_factory=tls_factory)
    operator._authorized=True;operator._subject_task=task;operator._owner_referral_id=identifier;operator._owner_proposal=proposal
    with pytest.raises(OperatorBindingError):operator.acknowledge_owner_referral()
    posts=sum(c[0]=='POST' for c in calls)
    with pytest.raises(OperatorBindingError):operator.acknowledge_owner_referral()
    assert sum(c[0]=='POST' for c in calls)==posts<=1
    assert all(c[2] is None for c in calls)
    assert COOKIE not in repr(operator.original_replies())
    assert not any('/api/agents/' in c[1] for c in calls)


@pytest.mark.parametrize('mode',['unconfigured','foreign','changed_after_constructor'])
def test_existing_owner_origin_admission_before_secret_transport(monkeypatch,mode):
    calls=[]
    def forbidden(*args,**kwargs):calls.append(True);raise AssertionError('No network before owning origin admission')
    if mode=='unconfigured':
        monkeypatch.delenv('PRIME_PWA_ORIGIN',raising=False)
        with pytest.raises(OperatorBindingError):prepared(pwa_connection_factory=forbidden)
    elif mode=='foreign':
        with pytest.raises(OperatorBindingError):prepared(approved_pwa_origin='https://valid-tls-foreign.invalid',pwa_connection_factory=forbidden)
    else:
        import uuid
        operator=prepared(pwa_connection_factory=forbidden);operator._authorized=True
        operator._subject_task=str(uuid.uuid4());operator._owner_referral_id=str(uuid.uuid4())
        operator._owner_proposal={};monkeypatch.setenv('PRIME_PWA_ORIGIN','https://other-owner.invalid')
        with pytest.raises(OperatorBindingError):operator.acknowledge_owner_referral()
    assert calls==[]
