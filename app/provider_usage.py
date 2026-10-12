"""Read-only projection of existing local outcome records, never provider billing.

No credentials, network calls, wallet state or second usage ledger. Unknown input
or costs are not silently converted to zero. The bounded window is explicit.
"""
import json
import math
import re
import sqlite3
from pathlib import Path
from .agent_registry import registered_agent_ids,canonical_agent_id,RegistryError


def _group(identity):
    return {**identity, 'attempts': 0, 'tokens': None, 'estimated_cost_usd': None,
            'missing_usage_attempts': 0, 'missing_cost_attempts': 0,
            'provider_balance_usd': None, 'balance_state': 'UNKNOWN'}


def usage_projection(path, policy, *, limit=500, evidence_scope='LOCAL_RECORDED_ATTEMPTS'):
    if evidence_scope not in {'LOCAL_RECORDED_ATTEMPTS','MOCK_CONTRACT_FIXTURES'}:
        raise ValueError('Unsupported evidence scope')
    if type(limit) is not int or not 1<=limit<=500:raise ValueError('Invalid observation window')
    agents={agent:_group({'agent':agent}) for agent in sorted(registered_agent_ids(include_orchestrator=False))}
    providers={};rows=[];state='NO_RECORDS'
    path=Path(path)
    if path.exists():
        try:
            with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5) as db:
                # rowid is the existing insertion order, not a fabricated date.
                rows=db.execute('SELECT tokens,cost,details FROM reasoning_attempts ORDER BY rowid DESC LIMIT ?', (limit,)).fetchall()
            state='RECORDED' if rows else 'NO_RECORDS'
        except sqlite3.Error:state='UNAVAILABLE'
    unattributed=0
    for tokens,cost,raw in rows:
        try:details=json.loads(raw)
        except (ValueError,TypeError):unattributed+=1;continue
        if not isinstance(details,dict):unattributed+=1;continue
        try:agent=canonical_agent_id(details.get('agent_id',''))
        except (RegistryError,TypeError,AttributeError):unattributed+=1;continue
        if agent not in agents:unattributed+=1;continue
        provider=details.get('provider')
        # Identity is a bounded public catalog identifier, never endpoint, key or raw error.
        if not isinstance(provider,str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,100}',provider):
            unattributed+=1;continue
        target=providers.setdefault(provider,_group({'provider':provider}))
        for group in (agents[agent],target):
            group['attempts']+=1
            if type(tokens) is not int or tokens<0:group['missing_usage_attempts']+=1
            else:group['tokens']=(group['tokens'] or 0)+tokens
            if type(cost) not in (int,float) or not math.isfinite(cost) or cost<0:group['missing_cost_attempts']+=1
            else:group['estimated_cost_usd']=(group['estimated_cost_usd'] or 0)+cost
    for group in list(agents.values())+list(providers.values()):
        if group['missing_usage_attempts']:group['tokens']=None
        if group['missing_cost_attempts']:group['estimated_cost_usd']=None
        group['usage_state']='UNKNOWN' if group['tokens'] is None else 'RECORDED_WINDOW'
        group['cost_state']='UNKNOWN' if group['estimated_cost_usd'] is None else 'LOCAL_RATE_ESTIMATE_NOT_INVOICE'
    for agent in agents.values():
        agent['quota']={'per_agent_concurrency':policy.per_agent_concurrency,
                        'per_agent_cost_ceiling_usd':None,'allocation_state':'NOT_CONFIGURED',
                        'shared_daily_cost_ceiling_usd':policy.daily_cost_ceiling_usd,
                        'max_job_cost_usd':policy.max_job_cost_usd}
    return {'scope':evidence_scope,'state':state,'window':len(rows),'window_limit':limit,
            'ordering':'LATEST_LOCAL_INSERTIONS','provider_probe_performed':False,
            'billing_verified':False,'treasury_included':False,'unattributed_attempts':unattributed,
            'agents':list(agents.values()),'providers':list(providers.values())}
