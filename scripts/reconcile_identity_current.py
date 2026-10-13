"""Recheck latest identity replies read-only, preserving every prior failed wave."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess

CODE = r'''
import datetime,hashlib,json,os,pathlib,sqlite3
from decimal import Decimal
from app.jarvis_response_contract import validate_user_facing_answer
from app.settings import SETTINGS
from app.agent_registry import registered_agent_ids
revision='EXPECTED_REVISION'
assert os.getenv('PRIME_RUNTIME_REVISION')==revision
root=pathlib.Path(os.getenv('PRIME_DATA_DIR','/data'))/'identity-probes'/revision
plan=json.loads((root/'plan.json').read_text());submitted=json.loads((root/'submitted.json').read_text())
assert len(plan['jobs'])==len(submitted)==21
assert {row['agent'] for row in plan['jobs']}==set(submitted)==registered_agent_ids(include_orchestrator=False)
assert len(set(submitted.values()))==21
source_root=pathlib.Path('/app/app')
assert all(hashlib.sha256((source_root/name).read_bytes()).hexdigest()==wanted for name,wanted in plan['source_sha256'].items())
deep=json.loads((root/'a21-independent-local-deep.json').read_text())
fast=json.loads((root/'a21-independent-local.json').read_text())
assert deep['original_failed_cloud_job_id']==submitted['a21']
db=sqlite3.connect((root.parents[1]/'compute-queue.db').resolve().as_uri()+'?mode=ro',uri=True,timeout=.2);db.row_factory=sqlite3.Row
db.execute('BEGIN')
results=[];original_passed=0;selected_known=Decimal(0);selected_unknown=0;original_unknown=0
for expected in plan['jobs']:
 original=dict(db.execute('SELECT * FROM compute_jobs WHERE id=?',(submitted[expected['agent']],)).fetchone())
 original_passed+=original['status']=='completed' and not validate_user_facing_answer(plan['objective'],original['result'])
 original_unknown+=original['actual_cost_usd'] is None
 local=expected['agent']=='a21'
 actual=dict(db.execute('SELECT * FROM compute_jobs WHERE id=?',(deep['job_id'],)).fetchone()) if local else original
 terminal=json.loads((root/(actual['id']+('-local-terminal.json' if local else '-terminal.json'))).read_text())
 model=SETTINGS.deep_model if local else expected['model'];provider='ollama-deep' if local else expected['provider']
 bound=(actual['agent']==expected['agent'] and actual['prompt']==expected['prompt']
  and actual['model']==model and actual['provider']==actual['preferred_provider']==provider
  and actual['status']=='completed' and actual['max_retries']==0 and actual['attempts']==1
  and actual['external_execution']==0 and actual['response_format']=='text'
  and actual['allow_cloud']==(0 if local else 1)
  and actual['data_classification']==('LOCAL_ONLY' if local else 'CLOUD_PERMITTED')
  and actual['max_cost_usd']==(0 if local else .005)
  and hashlib.sha256((actual['result'] or '').encode()).hexdigest()==terminal['output_sha256']
  and actual['completed_at']==terminal['queue_receipt']['completed_at']
  and actual['prompt']==terminal['queue_receipt']['prompt'])
 errors=validate_user_facing_answer(plan['objective'],actual['result']) if bound else ['execution_binding_changed']
 results.append({'agent':expected['agent'],'job_id':actual['id'],'status':actual['status'],'model':actual['model'],
  'provider':actual['provider'],'execution_bound':bound,'passed':bound and not errors,'errors':errors,
  'started_at':actual['started_at'],'completed_at':actual['completed_at'],'actual_cost_usd':actual['actual_cost_usd'],
  'prompt_sha256':hashlib.sha256(actual['prompt'].encode()).hexdigest(),
  'output_sha256':hashlib.sha256((actual['result'] or '').encode()).hexdigest()})
 if actual['actual_cost_usd'] is None:selected_unknown+=1
 else:selected_known+=Decimal(str(actual['actual_cost_usd']))
retained=[]
for key in (submitted['a21'],fast['job_id']):
 job=dict(db.execute('SELECT * FROM compute_jobs WHERE id=?',(key,)).fetchone())
 retained.append({'agent':'a21','job_id':key,'status':job['status'],'execution_error':job['error'],
  'identity_errors':validate_user_facing_answer(plan['objective'],job['result']) if job['status']=='completed' else [],
  'model':job['model'],'provider':job['provider'],'actual_cost_usd':job['actual_cost_usd'],
  'output_sha256':hashlib.sha256((job['result'] or '').encode()).hexdigest()})
active=db.execute("SELECT COUNT(*) FROM compute_jobs WHERE status IN ('queued','running','held','awaiting_approval') OR cloud_inflight=1").fetchone()[0];db.close()
print(json.dumps({'scope':'LATEST_BOUND_PUBLIC_IDENTITY_REPLIES_NOT_NORMAL_ROLE_OR_FULL_ACCEPTANCE_OR_AZURE_L7',
 'observed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'runtime_source_revision':revision,
 'source_sha256':plan['source_sha256'],'identity_denominator':21,'identity_pass_count':sum(row['passed'] for row in results),
 'identity_fail_count':sum(not row['passed'] for row in results),'original_identity_wave':{'denominator':21,
 'passed':original_passed,'failed':21-original_passed,'unknown_cost_count':original_unknown},
 'retained_inference_attempts':23,'retained_failures':retained,'known_selected_cost_usd':str(selected_known),
 'unknown_selected_cost_count':selected_unknown,'normal_role_criteria_changed':False,'full_role_accepted_count':0,
 'independent_azure_status':'NOT_ESTABLISHED','model_calls_this_reconciliation':0,'active_queue_records':active,
 'results':results}))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-revision', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--container', default='prime-epoch-20260919-prime-1')
    args = parser.parse_args()
    if not re.fullmatch('[a-f0-9]{40}', args.expected_revision):
        parser.error('exact source revision required')
    docker = 'C:/Program Files/Docker/Docker/resources/bin/docker.exe'

    def identity():
        observed = subprocess.run([docker, 'inspect', args.container, '--format', '{{.Id}} {{.Image}}'],
                                  capture_output=True, text=True, check=True, timeout=15)
        instance, image = observed.stdout.strip().split()
        return {'container_id': instance, 'image_id': image}

    before = identity()
    result = subprocess.run([docker, 'exec', args.container, 'python', '-B', '-c',
        CODE.replace('EXPECTED_REVISION', args.expected_revision)], capture_output=True, text=True, encoding='utf-8', timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr[:2000])
    report = json.loads(result.stdout)
    report['runtime_container'] = identity()
    report['runtime_identity_stable'] = before == report['runtime_container']
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    path = args.output_dir/('IDENTITY-CURRENT-AGGREGATE-'+stamp+'.json')
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    if not report['runtime_identity_stable']:
        raise RuntimeError('runtime changed during reconciliation; original evidence retained')
    print(json.dumps({key: value for key, value in report.items() if key not in ('results', 'retained_failures', 'source_sha256')}))
    print(json.dumps({'receipt': str(path)}))


if __name__ == '__main__':
    main()
