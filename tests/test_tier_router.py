import pytest
from app.tier_router import Backend, Tier, select_route, required_tier

BACKENDS=(Backend('cpu','gemma3:1b',Tier.NANO,'local'),
          Backend('provider-neutral','simulated-mini',Tier.MINI,'cloud'))


def test_requirement_does_not_shrink_to_fit_local_capacity():
    assert required_tier('Reply OK')==Tier.NANO
    assert required_tier('Refactor this multi-file implementation')==Tier.MINI
    assert required_tier('Produce a formal proof for this cryptographic protocol')==Tier.FLAGSHIP
    assert required_tier('Summarize','x'*16001)==Tier.FLAGSHIP


def route(**kwargs):
    arguments=dict(minimum_tier=Tier.NANO,classification='CLOUD_PERMITTED',text='Public arithmetic question')
    arguments.update(kwargs)
    return select_route(BACKENDS,**arguments)


def test_smallest_sufficient_local_tier_and_queue_limit():
    assert route().backend.name == 'cpu'
    assert route(local_saturated=True).state == 'QUEUED'
    assert route(minimum_tier=Tier.MINI).state == 'UNAVAILABLE'
    assert route().grants_execution_authority is False


@pytest.mark.parametrize('classification',['LOCAL_ONLY','SENSITIVE','RESTRICTED','unknown'])
def test_restricted_data_never_routes_externally(classification):
    result=route(classification=classification,local_saturated=True,provider_authorized=True,
                 disclosure_authorized=True,cost_authorized=True)
    assert result.backend is None or result.backend.location != 'cloud'


@pytest.mark.parametrize('missing',['provider_authorized','disclosure_authorized','cost_authorized'])
def test_independent_cloud_authorizations_are_all_required(missing):
    args=dict(local_saturated=True,provider_authorized=True,disclosure_authorized=True,cost_authorized=True)
    args[missing]=False
    assert route(**args).state == 'QUEUED'


def test_simulated_cloud_eligibility_is_not_authority_and_failure_is_local():
    args=dict(local_saturated=True,provider_authorized=True,disclosure_authorized=True,cost_authorized=True)
    result=route(**args)
    assert result.backend.location == 'cloud' and not result.grants_execution_authority
    assert route(text='api_key=do-not-disclose',**args).state == 'QUEUED'
    assert select_route((BACKENDS[0],),minimum_tier=Tier.NANO,classification='CLOUD_PERMITTED',text='public',**args).state == 'QUEUED'
    assert route(minimum_tier=Tier.FLAGSHIP,**args).state == 'UNAVAILABLE'
