import asyncio
import pytest
from app.provider_circuit import ProviderCircuits
from app.provider_runtime import Chunk,Usage,ModelSpec,ProviderFailure,complete,complete_with_fallback


def spec(name='hf-primary'):
    return ModelSpec('model',name,'VERIFIED',1024,64)


class Provider:
    def __init__(self,chunks=None,error=None):
        self.chunks=chunks or []
        self.error=error
        self.calls=0

    async def stream(self,*args):
        self.calls+=1
        for chunk in self.chunks:yield chunk
        if self.error:raise self.error


def run(provider,circuits,**kwargs):
    return asyncio.run(complete(provider,spec(),[{'role':'user','content':'public synthetic'}],output_tokens=32,max_retries=0,circuits=circuits,**kwargs))


def test_open_circuit_blocks_transport_then_exactly_one_validated_recovery():
    now=[100.0]
    circuits=ProviderCircuits(failure_threshold=1,cooldown_seconds=10,clock=lambda:now[0])
    bad=Provider(error=ProviderFailure('RATE_LIMIT',pre_execution=True))
    with pytest.raises(ProviderFailure,match='RATE_LIMIT'):run(bad,circuits)
    good=Provider([Chunk(text='answer'),Chunk(complete=True)])
    with pytest.raises(ProviderFailure,match='PROVIDER_CIRCUIT_OPEN'):run(good,circuits)
    assert good.calls==0
    now[0]+=10
    assert run(good,circuits)['text']=='answer'
    assert circuits.snapshot('hf-primary')['circuit_state']=='CLOSED'
    assert circuits.snapshot('hf-primary')['active_permits']==0


@pytest.mark.parametrize('chunks,code',[
    ([Chunk(complete=True)],'EMPTY_OR_INCOMPLETE_RESPONSE'),
    ([Chunk(text='x'),Chunk(complete=True),Chunk(text='late')],'MALFORMED_STREAM'),
    ([Chunk(text='x'),Chunk(usage=Usage(1,-1)),Chunk(complete=True)],'INVALID_USAGE'),
])
def test_terminal_generator_is_not_validated_recovery(chunks,code):
    circuits=ProviderCircuits(failure_threshold=1)
    with pytest.raises(ProviderFailure,match=code):run(Provider(chunks),circuits)
    assert circuits.snapshot('hf-primary')['circuit_state']=='OPEN'
    assert circuits.snapshot('hf-primary')['active_permits']==0


def test_cancellation_releases_permit_without_provider_fault():
    class Slow:
        async def stream(self,*args):
            await asyncio.Event().wait()
            yield Chunk()
    circuits=ProviderCircuits(failure_threshold=1)
    with pytest.raises(ProviderFailure,match='TASK_TIMEOUT'):run(Slow(),circuits,timeout=.01)
    state=circuits.snapshot('hf-primary')
    assert state['active_permits']==0 and state['consecutive_provider_failures']==0


def test_explicit_authorized_fallback_can_skip_open_primary():
    circuits=ProviderCircuits(failure_threshold=1)
    circuits.fail(circuits.acquire('hf-primary'),'RATE_LIMIT',pre_execution=True)
    primary=Provider([Chunk(text='never'),Chunk(complete=True)])
    alternate=Provider([Chunk(text='answer'),Chunk(complete=True)])
    result=asyncio.run(complete_with_fallback([(primary,spec()),(alternate,spec('hf-alt'))],
        [{'role':'user','content':'public synthetic'}],authorize_candidate=lambda *args:True,
        output_tokens=32,max_retries=0,circuits=circuits))
    assert primary.calls==0 and alternate.calls==1
    assert result['fallback_failures']==[{'provider':'hf-primary','code':'PROVIDER_CIRCUIT_OPEN'}]


def test_ambiguous_primary_failure_never_replays_on_alternate():
    circuits=ProviderCircuits(failure_threshold=1)
    primary=Provider(error=ProviderFailure('PROVIDER_TIMEOUT'))
    alternate=Provider([Chunk(text='never'),Chunk(complete=True)])
    with pytest.raises(ProviderFailure,match='PROVIDER_TIMEOUT'):
        asyncio.run(complete_with_fallback([(primary,spec()),(alternate,spec('hf-alt'))],
            [{'role':'user','content':'public synthetic'}],authorize_candidate=lambda *args:True,
            output_tokens=32,max_retries=0,circuits=circuits))
    assert primary.calls==1 and alternate.calls==0


def test_visible_output_overrides_claimed_pre_execution_in_circuit_receipt():
    circuits=ProviderCircuits(failure_threshold=1)
    provider=Provider([Chunk(text='partial')],ProviderFailure('CAPACITY',pre_execution=True))
    with pytest.raises(ProviderFailure) as caught:run(provider,circuits)
    assert caught.value.pre_execution is False
    assert circuits.snapshot('hf-primary')['last_failure_pre_execution'] is False
