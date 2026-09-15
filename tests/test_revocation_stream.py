import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
import time

import pytest

from app.action_harness import ActionHarness,ActionEnvelopeIssuer,utcnow
from app import governed_stream


@pytest.mark.parametrize('change',['revoke','policy'])
def test_revocation_interrupts_stalled_stream_without_next_token(tmp_path,monkeypatch,change):
    key=b'isolated-stalled-stream-authority!'
    issuer=ActionEnvelopeIssuer(key)
    harness=ActionHarness(tmp_path/'harness.db',{issuer.key_id:key})
    envelope=issuer.issue(dict(tenant_id='personal',actor_id='a14',actor_type='reasoner',action='agent.infer',
        parameters={},context={},correlation_id='stall',idempotency_key='stall',schema_version='1.0.0',
        timestamp=utcnow().isoformat()),decision_id='stall',policy_version='harness-v0')
    assert harness.authorize(envelope).authorized
    assert harness.revalidate_for_execution(envelope).authorized
    closed=[]
    async def scenario():
        entered=asyncio.Event()
        class Response:
            def raise_for_status(self): pass
            async def aiter_lines(self):
                entered.set()
                await asyncio.Event().wait()
                yield ''
        class Client:
            def __init__(self,**kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            @asynccontextmanager
            async def stream(self,*args,**kwargs):
                try: yield Response()
                finally: closed.append(True)
        monkeypatch.setattr(governed_stream.httpx,'AsyncClient',Client)
        task=asyncio.create_task(governed_stream.infer(
            dict(harness_envelope=json.dumps(envelope),timeout_seconds=20,prompt='test'),SimpleNamespace(model='test'),
            settings=SimpleNamespace(ollama_base_url='http://unused',keep_alive='1m',context_tokens=32,max_output_tokens=8),
            harness=harness,validate=lambda job:None,capacity=lambda model:None,options=lambda:{}))
        await asyncio.wait_for(entered.wait(),1)
        start=time.perf_counter()
        if change=='revoke': harness.revoke(envelope['authorization']['lease_id'],reason='stop',revoked_by='test')
        else: harness.set_policy_version('changed')
        with pytest.raises(PermissionError): await asyncio.wait_for(task,1)
        assert time.perf_counter()-start<1
        assert closed==[True]
        assert not harness._revocation_listeners
    asyncio.run(scenario())
