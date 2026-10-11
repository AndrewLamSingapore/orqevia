"""Original configured model selection, never installed-model health/inference."""
from __future__ import annotations
import os,time
from pathlib import Path
from .agent_cert_artifact_events import canonical,parse,sha,_path
from .tier_router import Tier,Backend,classify_for_cloud,required_tier
from .compute_catalog import task_tier

CASE='models:complete'
VERSION='a19.original-full-final-model-selection.v1'
FIELDS=('id','model','tier','location','enabled','provider_kind','expected_seconds','expected_cost_usd')


class ModelSelectionError(ValueError):pass


def require(value,code):
    if value is not True:raise ModelSelectionError(code)


def routing_request():
    return dict(capability='responsibility.a19',objective='Classify this fixed public routing report as selection only.',
        context='PUBLIC_SYNTHETIC: Report selected tier and limitations; model identity is not agent identity. No inference is requested.',
        classification='R0',data_classification='LOCAL_ONLY',minimum_tier='NANO',priority='low',
        task_class='classification',max_cost_usd=0.0,preferred_provider=None,response_format='strict_json')


def capture_native_snapshot(*,deadline):
    """Read actual existing configuration/provider metadata without resolving secrets."""
    from .compute_catalog import load_catalog
    from .compute_queue_api import providers
    from .agent_dispatch_api import local_model_backends
    name=os.getenv('PRIME_PROVIDER_CATALOG','')
    def original_bytes():
        if not name:return b'{"models":[]}'
        path=_path(Path(name));before=path.stat()
        require(path.is_file() and 0<before.st_size<=131072,'MODEL_ORIGINAL_CATALOG_BOUND')
        identity=lambda stat:(stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns)
        with path.open('rb') as stream:
            opened=os.fstat(stream.fileno())
            require(identity(opened)==identity(before),'MODEL_ORIGINAL_CATALOG_CHANGED')
            raw=stream.read(131072+1)
            require(0<len(raw)<=131072,'MODEL_ORIGINAL_CATALOG_BOUND')
            require(identity(os.fstat(stream.fileno()))==identity(before),'MODEL_ORIGINAL_CATALOG_CHANGED')
        after=_path(Path(name)).stat()
        require(identity(after)==identity(before) and time.monotonic()<deadline,'MODEL_ORIGINAL_CATALOG_CHANGED')
        return raw
    require(time.monotonic()<deadline,'MODEL_NATIVE_SNAPSHOT_BOUND')
    raw=original_bytes();before=sha(raw);configured=load_catalog(raw_bytes=raw)
    require(raw==original_bytes(),'MODEL_CATALOG_CHANGED_DURING_READ')
    available=sorted({p.name for p in providers(validated_catalog=configured)});locals=local_model_backends()
    require(raw==original_bytes() and time.monotonic()<deadline,'MODEL_CATALOG_CHANGED_DURING_READ')
    sanitized=[]
    for entry in configured:
        item={f:entry[f] for f in FIELDS if f in entry}
        item['measurement_evidence']=bool(entry.get('measurement_evidence'))
        item['measurement_evidence_sha256']=sha(canonical(entry.get('measurement_evidence')))
        sanitized.append(item)
    snapshot=dict(schema_version='prime.original-model-routing-inputs.v1',catalog_original_sha256=before,
        catalog=sanitized,available_provider_names=available,
        local_backends=[dict(name=b.name,model=b.model,tier=b.tier.name,location=b.location,
            available=b.available) for b in locals],
        availability_scope='ORIGINAL_CONFIGURED_NATIVE_PROVIDER_METADATA_NOT_INSTALLED_MODEL_HEALTH',
        credentials='NOT_RESOLVED',model_calls=0)
    require(len(canonical(snapshot))<=65536,'MODEL_NATIVE_SNAPSHOT_BYTES')
    return snapshot,configured,set(available),locals


def owning_request(input_raw):
    from .agent_cert_tool_events import canonical_tool_case,input_bytes
    require(input_raw==input_bytes(CASE),'MODEL_ORIGINAL_INPUT_REQUIRED')
    return canonical_tool_case(CASE)['request']


def produce_report(snapshot,*,configured,available,locals,input_raw):
    from .agent_dispatch_api import AgentRequest
    from .model_selection import select_final_model
    request=owning_request(input_raw)
    route,effective=select_final_model(AgentRequest(**request),configured=configured,
        available=available,local_backends=locals)
    require(route.state in ('READY','QUEUED') and route.backend is not None,
        'MODEL_ACTUAL_SUFFICIENT_SELECTION_UNAVAILABLE')
    return canonical(dict(schema_version='prime.a19-original-model-selection-result.v1',case=CASE,
        case_version=VERSION,input_sha256=sha(input_raw),routing_request=request,
        original_snapshot_sha256=sha(canonical(snapshot)),requested_minimum_tier=request['minimum_tier'],
        effective_required_tier=effective.name,selected_tier=route.backend.tier.name,
        selected_backend=route.backend.name,selected_model=route.backend.model,
        selected_location=route.backend.location,selection_state=route.state,selection_reason=route.reason,
        agent_id='a19',agent_capability='responsibility.a19',agent_is_model=False,
        inference='NOT_PERFORMED',model_health='NOT_OBSERVED',availability_scope=snapshot['availability_scope'],
        reasoning_scope='FIXED_PUBLIC_CLASSIFICATION_SELECTION_REPORT_NOT_GENERAL_COMPLEX_REASONING',
        authority='NONE',model_calls=0,certification='UNVERIFIED'))


def independently_validate_report(raw,input_raw,snapshot):
    """Independent raw final-route oracle, never shared selector/producer report."""
    result=parse(raw);request=owning_request(input_raw)
    # This fixed original classification contract has no elevated triage trigger.
    # Do not borrow the producer's task/required-tier classifiers.
    require(request['minimum_tier']=='NANO' and request['task_class']=='classification'
        and len(request['context'])<=4000 and not any(term in request['objective'].lower()
        for term in ('formal proof','threat model','cryptographic protocol','novel research',
                     'multi-file','refactor','concurrency','architecture','debug')),
        'MODEL_FIXED_CLASSIFICATION_REQUIREMENT_CHANGED')
    minimum=Tier.NANO
    catalog=snapshot['catalog'];available=set(snapshot['available_provider_names'])
    candidates=[dict(id=x['name'],model=x['model'],tier=x['tier'],location=x['location'],
        available=x['available']) for x in snapshot['local_backends']]
    candidates += [dict(x,available=True) for x in catalog if x.get('enabled') and x['id'] in available
        and x.get('provider_kind')!='huggingface']
    ordered=sorted([x for x in candidates if x['available'] and Tier[x['tier']]>=minimum],
        key=lambda x:(Tier[x['tier']],x['location']!='local',x['id']))
    local=[x for x in ordered if x['location']=='local']
    require(bool(local),'MODEL_INDEPENDENT_SUFFICIENT_LOCAL_SELECTION_REQUIRED')
    expected=local[0];reason='Lowest sufficient local tier'
    measured=[x for x in catalog if x.get('enabled') and x['id'] in available
        and x.get('measurement_evidence') and x.get('expected_seconds') is not None
        and x.get('provider_kind')!='huggingface' and Tier[x['tier']]>=minimum and x['location']=='local']
    measured.sort(key=lambda x:(float(x['expected_seconds']),float(x.get('expected_cost_usd',float('inf'))),
        Tier[x['tier']],x['id']))
    coverage={x['id'] for x in candidates if Tier[x['tier']]>=minimum and x['location']=='local'}
    if measured and coverage.issubset({x['id'] for x in measured}):
        expected=measured[0];reason='Fastest measured sufficient backend within data locality'
    literal=dict(schema_version='prime.a19-original-model-selection-result.v1',case='models:complete',
        case_version='a19.original-full-final-model-selection.v1',input_sha256=sha(input_raw),
        routing_request=request,original_snapshot_sha256=sha(canonical(snapshot)),
        requested_minimum_tier=request['minimum_tier'],effective_required_tier=minimum.name,
        selected_tier=expected['tier'],selected_backend=expected['id'],selected_model=expected['model'],
        selected_location='local',selection_state='READY',selection_reason=reason,
        agent_id='a19',agent_capability='responsibility.a19',agent_is_model=False,inference='NOT_PERFORMED',
        model_health='NOT_OBSERVED',availability_scope='ORIGINAL_CONFIGURED_NATIVE_PROVIDER_METADATA_NOT_INSTALLED_MODEL_HEALTH',
        reasoning_scope='FIXED_PUBLIC_CLASSIFICATION_SELECTION_REPORT_NOT_GENERAL_COMPLEX_REASONING',
        authority='NONE',model_calls=0,certification='UNVERIFIED')
    require(result==literal and raw==canonical(literal),'MODEL_ORIGINAL_INDEPENDENT_REPORT_REJECTED')
    return literal


def reread_native_snapshot(snapshot,*,deadline):
    fresh,*_=capture_native_snapshot(deadline=deadline)
    require(canonical(fresh)==canonical(snapshot),'MODEL_ORIGINAL_NATIVE_CONFIGURATION_CHANGED')
    return sha(canonical(snapshot))


def case_remaining(budget):
    from datetime import datetime,timezone
    return max(0,min(5,budget['deadline']-time.monotonic(),
        5-(datetime.now(timezone.utc)-budget['started_at']).total_seconds()))
