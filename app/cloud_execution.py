"""Execute catalog-selected reasoning through the existing queue and action ledger."""
import asyncio
from copy import deepcopy
import time
import uuid
from decimal import Decimal,InvalidOperation
from .compute_catalog import load_catalog,model_spec
from .provider_runtime import ChatCompletionProvider,HuggingFaceProvider,ProviderFailure,complete,complete_with_fallback
from .secret_refs import resolve_secret,SecretUnavailable
from .tier_router import classify_for_cloud
from .tier_router import Tier
from .outcome_metrics import OutcomeMetrics
from .action_records import ActionRecord,DirectExecutor,action_ledger
from .reasoning_budgets import select_budget,verify_reserved_cost
from .hf_admission import require_hf_admission,require_hf_fallback_policy
from .provider_circuit import ProviderCircuits

PROVIDER_CIRCUITS=ProviderCircuits()


def _dispatch_binding(entry):
    """Bind prepared disclosure, consent and caps; not changing observations."""
    fields=('id','provider_kind','location','tier','model','endpoint','secret_ref',
        'enabled','qualification_status','context_tokens','output_tokens',
        'input_usd_million','output_usd_million','cached_usd_million',
        'task_budgets','allowed_task_classes','fallback_ids','hf_fallback_policy','max_retries')
    return deepcopy({field:entry.get(field) for field in fields})


def adapter_for(entry):
    if entry.get('provider_kind')=='huggingface':
        return HuggingFaceProvider(entry['secret_ref'],secret_resolver=resolve_secret)
    # A HF credential must never reach an unrelated host, even if a malformed
    # catalog bypassed load_catalog or used the environment-reference variant.
    if entry.get('secret_ref') in {'env:HF_TOKEN','file:HF_TOKEN'}:
        raise ProviderFailure('HF_CREDENTIAL_SCOPE_DENIED',pre_execution=True)
    return ChatCompletionProvider(entry['endpoint'],entry['secret_ref'],secret_resolver=resolve_secret)


def require_fallback_admission(primary,target,job):
    """Revalidate every alternate before credential resolution or disclosure."""
    if not target.get('enabled') or target.get('qualification_status')!='QUALIFIED':
        raise ProviderFailure('FALLBACK_UNQUALIFIED',pre_execution=True)
    if target.get('location')!='cloud':
        raise ProviderFailure('FALLBACK_POLICY_DENIED',pre_execution=True)
    if primary.get('provider_kind')=='huggingface':
        require_hf_fallback_policy(primary,job,target)
        require_hf_admission(target,job,target['id'],primary=primary)
    else:
        # Preserve the prohibition on generic cloud -> implicit HF disclosure.
        require_hf_admission(target,job,target['id'])
    if target.get('provider_kind')!='huggingface' and target.get('secret_ref') in {'env:HF_TOKEN','file:HF_TOKEN'}:
        raise ProviderFailure('HF_CREDENTIAL_SCOPE_DENIED',pre_execution=True)


def configured_provider_health():
    """Readiness inventory, with no health inference or network side effects.

    Endpoint and credential reference/value are deliberately absent from reports.
    External activation and selection remain explicit configuration decisions.
    """
    result=[]
    for entry in load_catalog():
        if entry.get('location')!='cloud':continue
        status={'readiness':'DISABLED','provider_health':'UNMEASURED','network_probe_performed':False}
        if entry.get('enabled'):
            try:
                status=adapter_for(entry).health()
            except Exception:
                status={'readiness':'CONFIGURATION_INVALID','provider_health':'UNMEASURED','network_probe_performed':False}
        result.append({'provider_id':entry['id'],**status,'circuit':PROVIDER_CIRCUITS.snapshot(entry['id'])})
    return result


def execute_cloud(job,provider,data,cancelled):
    if not classify_for_cloud(job.get('data_classification','LOCAL_ONLY'),job['prompt']):raise ProviderFailure('DATA_LOCALITY')
    catalog=load_catalog()
    entries=[x for x in catalog if x['id']==provider.name and x.get('enabled')]
    if not entries:raise ProviderFailure('PROVIDER_UNAVAILABLE')
    entry=entries[0]
    require_hf_admission(entry,job,provider.name)
    spec=model_spec(entry);metrics=OutcomeMetrics(data/'compute-ledger.db')
    started=time.monotonic();answer=None;failure=None;selected=entry;failure_retries=0;failure_routes=[]
    def operation():
        nonlocal selected
        messages=[{'role':'user','content':job['prompt']}]
        budget=select_budget(entry,job,spec)
        verify_reserved_cost(budget,job,messages)
        action.parameters_summary['reasoning_budget']=budget.receipt()
        action.parameters_summary['requested_output_tokens']=budget.output_tokens
        fallback_ids=entry.get('fallback_ids',[])
        if fallback_ids:
            if not isinstance(fallback_ids,list) or len(fallback_ids)>3 or any(not isinstance(x,str) for x in fallback_ids) or len(set(fallback_ids))!=len(fallback_ids) or entry['id'] in fallback_ids:
                raise ProviderFailure('FALLBACK_CONFIGURATION_INVALID',pre_execution=True)
            candidates=[entry]
            if entry.get('provider_kind')=='huggingface':
                action.parameters_summary['hf_fallback_policy']=require_hf_fallback_policy(entry,job)
            for name in fallback_ids:
                matches=[x for x in catalog if x['id']==name and x.get('enabled') and x.get('location')=='cloud']
                if len(matches)!=1:raise ProviderFailure('FALLBACK_CONFIGURATION_INVALID',pre_execution=True)
                require_fallback_admission(entry,matches[0],job)
                candidates.append(matches[0])
            budgets={x['id']:select_budget(x,job,model_spec(x)) for x in candidates}
            specs={key:value.model for key,value in budgets.items()}
            bindings={x['id']:_dispatch_binding(x) for x in candidates}
            def approve(candidate,messages,output_tokens):
                nonlocal selected
                try:
                    # Read domain-owned configuration again immediately before
                    # each route. Old dicts cannot prove current consent/prices.
                    # A changed binding denies the prepared route: never hot-swap
                    # its adapter, resolve a new credential, or enlarge its caps.
                    fresh=load_catalog()
                    primaries=[x for x in fresh if x['id']==entry['id']]
                    targets=[x for x in fresh if x['id']==candidate.provider]
                    if len(primaries)!=1 or len(targets)!=1:return False
                    primary,target=primaries[0],targets[0]
                    if _dispatch_binding(primary)!=bindings[entry['id']] or _dispatch_binding(target)!=bindings[candidate.provider]:return False
                    if target['id']==primary['id']:
                        require_hf_admission(target,job,target['id'])
                        if not target.get('enabled') or target.get('qualification_status')!='QUALIFIED':return False
                    else:require_fallback_admission(primary,target,job)
                    # Do not dispatch a prebuilt adapter/spec after its catalog
                    # model, rates or limits changed while a prior route ran.
                    if select_budget(target,job,model_spec(target))!=budgets[candidate.provider]:return False
                    verify_reserved_cost(budgets[candidate.provider],job,messages)
                except (ProviderFailure,OSError,ValueError,TypeError,KeyError,AttributeError,InvalidOperation):return False
                if Tier[target['tier']]<Tier[primary['tier']] or not job.get('allow_cloud') or not classify_for_cloud(job.get('data_classification','LOCAL_ONLY'),job['prompt']):return False
                if candidate.input_usd_million is None or candidate.output_usd_million is None:return False
                # A bounded byte upper estimate is deliberately more conservative
                # than a tokenizer guess. Keep within the already-reserved budget.
                upper=sum(len(m['content'].encode())+16 for m in messages)
                if upper+output_tokens>candidate.context_tokens or output_tokens>candidate.output_tokens:return False
                input_rate=max(candidate.input_usd_million,candidate.cached_usd_million or candidate.input_usd_million)
                estimate=(Decimal(upper)*input_rate+Decimal(output_tokens)*candidate.output_usd_million)/Decimal(1_000_000)
                try:
                    reserved=Decimal(str(job.get('estimated_cost_usd',0)));ceiling=Decimal(str(job.get('max_cost_usd',0)))
                    if not reserved.is_finite() or not ceiling.is_finite() or min(reserved,ceiling)<estimate:return False
                except (InvalidOperation,ValueError):return False
                selected=target
                action.parameters_summary['selected_provider']=target['id']
                action.parameters_summary['selected_model']=target['model']
                action.parameters_summary['reasoning_budget']=budgets[candidate.provider].receipt()
                return True
            adapters=[(adapter_for(x),specs[x['id']]) for x in candidates]
            result=asyncio.run(complete_with_fallback(adapters,[{'role':'user','content':job['prompt']}],authorize_candidate=approve,
                output_tokens=budget.output_tokens,timeout=min(x.timeout_seconds for x in budgets.values()),cancelled=cancelled,max_retries=min(1,int(entry.get('max_retries',1))),circuits=PROVIDER_CIRCUITS))
            action.parameters_summary['fallback_failures']=result['fallback_failures']
            return result
        adapter=adapter_for(entry)
        return asyncio.run(complete(adapter,budget.model,messages,output_tokens=budget.output_tokens,timeout=budget.timeout_seconds,cancelled=cancelled,max_retries=min(1,int(entry.get('max_retries',1))),circuits=PROVIDER_CIRCUITS))
    try:
        action=ActionRecord(job['id'],job['agent'],'inference.run',provider.name,classification=job.get('classification','R0'),model_backend=spec.name,execution_location='cloud')
        answer=DirectExecutor(action_ledger()).execute(action,operation)
        usage=answer['usage']
        return {'result':answer['text'],'input_tokens':usage.input_tokens,'output_tokens':usage.output_tokens,'actual_cost_usd':None if answer['cost_usd'] is None else float(answer['cost_usd'])}
    except SecretUnavailable:failure='CREDENTIAL_UNAVAILABLE';raise ProviderFailure(failure) from None
    except ProviderFailure as exc:
        failure=exc.code;failure_retries=getattr(exc,'retry_count',0);failure_routes=getattr(exc,'fallback_failures',[]);raise
    finally:
        usage=answer['usage'] if answer else None
        metrics.record(attempt_id=uuid.uuid4().hex,task_id=job['id'],task_class=job.get('task_class','auto'),tier=entry['tier'],seconds=time.monotonic()-started,
            input_tokens=usage.input_tokens if usage else None,output_tokens=usage.output_tokens if usage else None,cost=answer['cost_usd'] if answer else None,
            agent_id=job['agent'],provider=selected['id'],model=selected['model'],retries=answer['retries'] if answer else failure_retries,
            requested_tier=entry['tier'],requested_provider=entry['id'],requested_model=entry['model'],
            fallback_route=answer.get('fallback_failures',[]) if answer else failure_routes,
            error_classifications=sorted(set(([x['code'] for x in answer.get('fallback_failures',[])]+answer.get('retry_errors',[])) if answer else ([x['code'] for x in failure_routes]+([failure] if failure else [])))),
            cached_tokens=usage.cached_tokens if usage else None,success=answer is not None,failure_kind=failure)
