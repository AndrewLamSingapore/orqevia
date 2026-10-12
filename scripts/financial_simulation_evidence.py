"""Local public-synthetic evidence; leaves private authority key in isolated work."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    parser.add_argument('--runtime',required=True)
    parser.add_argument('--junit',required=True)
    args=parser.parse_args()
    output=Path(args.output).resolve();runtime=Path(args.runtime).resolve()
    output.mkdir(parents=True,exist_ok=True)
    if runtime.exists() and any(runtime.iterdir()):
        raise SystemExit('Evidence runtime must be new/empty; do not overwrite an existing treasury')
    runtime.mkdir(parents=True,exist_ok=True)
    os.environ.update(PRIME_DATA_DIR=str(runtime),PRIME_SPINE_TOKEN='public-synthetic-evidence-owner',
                      PRIME_REGISTRY_V1_ENABLED='1',PRIME_FINANCIAL_SIMULATION_ENABLED='1')
    from fastapi.testclient import TestClient
    from app.direct_entry import app
    from app.agent_registry import load_agent_registry,REGISTRY_PATH
    from app.action_records import close_ledgers
    from app.financial_simulation import authority
    api=TestClient(app)
    headers={'Authorization':'Bearer public-synthetic-evidence-owner'}
    junit=ET.parse(args.junit)
    cases=list(junit.iter('testcase'))
    records=load_agent_registry()['agents']
    matrix=[];events=[]
    for record in records:
        agent=record['immutable_id'];capability=record['responsibilities'][0]['id']
        response=api.get('/api/financial-simulation/services',params={'capability':capability},headers=headers)
        assert response.status_code==200
        quote=api.post('/api/financial-simulation/quote',json={'capability':capability,'service':'simulation.lookup'},headers=headers)
        assert quote.status_code==200
        objective='Owner objective: purchase a public synthetic lookup and return its receipt for '+agent
        request=dict(quote=quote.json(),idempotency_key='public-synthetic:'+agent,objective=objective)
        response=api.post('/api/agents/objectives',headers=headers,json=dict(capability=capability,
            objective=objective,context=json.dumps(request),deterministic_operation='financial_simulation',
            classification='R0',data_classification='LOCAL_ONLY',max_cost_usd=0))
        assert response.status_code==202,response.text
        objective_receipt=response.json()
        dispatch=objective_receipt['steps'][0]['dispatch']
        artifact=json.loads((runtime/'artifacts'/dispatch['artifact']['artifact_id']/'artifact.json').read_text())
        assert artifact['receipt']['state']=='SETTLED' and artifact['receipt']['amount']==100
        read=api.get('/api/agents/objectives/'+objective_receipt['id'],headers=headers)
        assert read.status_code==200 and read.json()['state']=='COMPLETED'
        finance=authority(runtime)
        restarted=finance.recover(artifact['receipt']['id'],agent)
        assert restarted['state']=='SETTLED'
        matching=[case for case in cases if ('test_all_registered_agents' in case.attrib.get('name','') and
                   case.attrib.get('name','').endswith('-'+agent+']')) or
                  case.attrib.get('name','')=='test_actual_objective_paid_service_artifact['+agent+']']
        failing=[case for case in matching if any(child.tag in {'failure','error','skipped'} for child in case)]
        # 28 mandatory per-agent scenario cases plus one existing-interface integration case.
        passed=len(matching)==29 and not failing
        matrix.append(dict(agent=agent,name=record['name'],capability=capability,identity='PASS',
            policy='PASS' if passed else 'FAIL',simulated_payment='PASS',recovery='PASS' if passed else 'FAIL',
            audit='PASS' if passed else 'FAIL',scenarios_passed=len(matching)-len(failing),
            scenarios_expected=29,verdict='PASS' if passed else 'FAIL',model_calls=0,
            runtime_admission='DETERMINISTIC_SIMULATION_ONLY',live_payment='DISABLED',l7='UNVERIFIED'))
        events.append(dict(agent=agent,interface='actual_existing_in_process_HTTP_routes',
                           objective_submission=objective_receipt,objective_read=read.json(),
                           artifact=artifact,recovery=restarted))
    assert api.post('/api/observability/flush',headers=headers).json()['flushed']
    ledger=api.get('/api/financial-simulation/report',headers=headers)
    assert ledger.status_code==200
    report=ledger.json()
    assert report['balances']['settled']==2100 and report['balances']['reserved']==0
    # Owner controls and original-transaction restart evidence, using synthetic money only.
    finance=authority(runtime)
    freeze=finance.owner_control('freeze',value=True)
    blocked=finance.request(records[0]['immutable_id'],dict(quote=finance.quote(records[0]['immutable_id'],'simulation.lookup'),
                            idempotency_key='frozen-attempt',objective='Synthetic frozen request'),'freeze-evidence')
    assert blocked['reason']=='TREASURY_FROZEN'
    finance.owner_control('freeze',value=False)
    tx=finance.request(records[0]['immutable_id'],dict(quote=finance.quote(records[0]['immutable_id'],'simulation.lookup'),
                       idempotency_key='uncertain-attempt',objective='Synthetic ambiguous result'),'recovery-evidence')
    finance.reserve(tx['id'],records[0]['immutable_id'])
    uncertain=finance.execute(tx['id'],records[0]['immutable_id'],scenario='ambiguous_after')
    recovered=authority(runtime).recover(tx['id'],records[0]['immutable_id'])
    assert uncertain['state']=='INDETERMINATE' and recovered['state']=='SETTLED'
    revoke=finance.owner_control('revoke',agent=records[-1]['immutable_id'])
    revoked=finance.request(records[-1]['immutable_id'],dict(quote=finance.quote(records[-1]['immutable_id'],'simulation.lookup'),
                        idempotency_key='revoked-attempt',objective='Synthetic revoked request'),'revocation-evidence')
    assert revoked['reason']=='AGENT_REVOKED'
    report=finance.report()
    assert report['balances']['settled']==2200 and report['balances']['available']==7800
    for filename,value in [('matrix.json',matrix),('objective-receipts.json',events),('ledger.json',report),
                           ('recovery-controls.json',dict(freeze=freeze,denied=blocked,uncertain=uncertain,recovered=recovered,
                                                         revocation=revoke,revoked_request=revoked))]:
        (output/filename).write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding='utf-8')
    (output/'action-records.jsonl').write_bytes((runtime/'action-records.jsonl').read_bytes())
    (output/'matrix.md').write_text('| Agent | Registered name | Identity | Policy | Payment | Recovery | Audit | Verdict |\n|---|---|---|---|---|---|---|---|\n'+
        '\n'.join('| '+ ' | '.join(str(row[key]) for key in ('agent','name','identity','policy','simulated_payment','recovery','audit','verdict'))+' |' for row in matrix),encoding='utf-8')
    summary=dict(mode='PUBLIC_SYNTHETIC_SIMULATION',registry_path=str(REGISTRY_PATH),
        registry_sha256=hashlib.sha256(REGISTRY_PATH.read_bytes()).hexdigest(),agent_count=len(records),
        agent_ids=[record['immutable_id'] for record in records],matrix_passed=sum(row['verdict']=='PASS' for row in matrix),
        tests=sum(1 for _ in cases),failed=sum(1 for case in cases if case.find('failure') is not None or case.find('error') is not None),
        skipped=sum(1 for case in cases if case.find('skipped') is not None),balances=report['balances'],
        git_revision=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        live_spending='DISABLED',live_providers='UNAVAILABLE_UNIMPLEMENTED',certification='UNVERIFIED',
        limits='No production promotion, model admission, Windows ACL isolation, external audit anchor or L7 qualification established')
    (output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    close_ledgers()
    print(json.dumps(summary,indent=2))
    if any(row['verdict']!='PASS' for row in matrix): raise SystemExit(1)


if __name__=='__main__': main()
