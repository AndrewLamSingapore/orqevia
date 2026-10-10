"""Full final existing model selector; no queue, credentials or inference."""
from fastapi import HTTPException
from .tier_router import Backend,Tier,Route,select_direct_route,required_tier
from .compute_catalog import task_tier,choose


def select_final_model(request,*,configured,available,local_backends):
    selected=next((x for x in configured if x['id']==request.preferred_provider),None) if request.preferred_provider else None
    if request.preferred_provider and (selected is None or not selected.get('enabled') or selected['id'] not in available):
        raise HTTPException(422,'Selected provider is unavailable')
    if selected and selected.get('provider_kind')=='huggingface' and (
        request.data_classification!='CLOUD_PERMITTED' or request.max_cost_usd<=0
    ):
        raise HTTPException(422,'Hugging Face requires explicit disclosure and cost opt-in')
    tier=max(Tier[request.minimum_tier],task_tier(request.objective,request.task_class),required_tier(request.objective,request.context))
    backends=(local_backends() if callable(local_backends) else local_backends)+tuple(Backend(x['id'],x['model'],Tier[x['tier']],x['location']) for x in configured
        if x.get('enabled') and x['id'] in available and
        (x.get('provider_kind')!='huggingface' or x['id']==request.preferred_provider))
    if request.preferred_provider:
        backends=tuple(x for x in backends if x.name==request.preferred_provider)
    route = select_direct_route(backends,
                         minimum_tier=tier,classification=request.data_classification,
                         text=request.objective+'\n'+request.context)
    measured=choose([x for x in configured if x['id'] in available and x.get('measurement_evidence') and x.get('expected_seconds') is not None
        and (x.get('provider_kind')!='huggingface' or x['id']==request.preferred_provider)
        and (not request.preferred_provider or x['id']==request.preferred_provider)],tier,request.data_classification,request.objective+'\n'+request.context)
    # Use a measured alternative only when every eligible available backend is
    # measured. Unknown performance is never treated as slower by assumption.
    eligible={b.name for b in backends if b.tier>=tier and (b.location=='local' or request.data_classification=='CLOUD_PERMITTED')}
    if measured and eligible.issubset({x['id'] for x in measured}):
        item=measured[0]
        route=Route('READY','Fastest measured sufficient backend within data locality',Backend(item['id'],item['model'],Tier[item['tier']],item['location']))
    return route,tier
