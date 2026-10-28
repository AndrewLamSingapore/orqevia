"""Read-only runtime compliance evidence. Never starts inference or changes Docker.

The desired profile is an observation target, not proof of enforcement.
Environment values are selected from an explicit non-secret allowlist in memory.
"""
from __future__ import annotations
import argparse
import datetime
import json
from pathlib import Path
import ssl
import subprocess
import urllib.error
import urllib.request


SAFE_SETTINGS = frozenset({
    'ORQEVIA_OUTPUT_QUEUE_MODE', 'ORQEVIA_COMPUTE_PROFILE', 'ORQEVIA_FAST_MODEL',
    'ORQEVIA_DEEP_MODEL', 'ORQEVIA_EVALUATOR_MODEL', 'ORQEVIA_EMBED_MODEL',
    'ORQEVIA_MODEL_KEEP_ALIVE', 'ORQEVIA_CONTEXT_TOKENS', 'ORQEVIA_MAX_OUTPUT_TOKENS',
    'OLLAMA_NUM_PARALLEL', 'OLLAMA_MAX_LOADED_MODELS', 'OLLAMA_MAX_QUEUE',
    'OLLAMA_KEEP_ALIVE', 'OLLAMA_CONTEXT_LENGTH',
})


def safe_settings(environment):
    return {key: value for item in environment for key, sep, value in [item.partition('=')]
            if sep and key in SAFE_SETTINGS}


def command(args, *, stdin=None):
    result = subprocess.run(args, input=stdin, text=True, capture_output=True,
                            encoding='utf-8', errors='replace', timeout=30)
    if result.returncode:
        raise RuntimeError('Runtime observation command failed')
    return result.stdout


def enforcement_matrix(requested, settings, journal):
    mode = settings.get('ORQEVIA_OUTPUT_QUEUE_MODE', 'direct')
    coordinated = mode == 'home_eco' and journal.get('lifecycle_columns_present', False)
    return {
        'requested_profile': requested,
        'actual_scheduling_mode': mode,
        'actual_compute_profile': settings.get('ORQEVIA_COMPUTE_PROFILE', 'UNKNOWN'),
        'profile_matches': coordinated and requested == 'HOME_ECO',
        'shared_admission': 'DEPLOYED_NOT_FUNCTIONALLY_VERIFIED' if coordinated else 'NOT_ENFORCED',
        'patient_deadlines': 'NOT_VERIFIED',
        'duplicate_requests_prevented': None,
        'duplicate_counter_state': 'NOT_INSTRUMENTED',
        'actual_inference_requests': None,
        'actual_inference_request_state': 'NOT_MEASURED_BY_MODEL_RESIDENCY_OR_JOB_STATUS',
        'scheduler_bypass': 'DIRECT_DISPATCH_BYPASSES_SHARED_ADMISSION' if mode == 'direct' else 'ALL_PRODUCERS_NOT_VERIFIED',
        'all_21_agents_functional': 'NOT_ESTABLISHED_BY_REGISTRATION_OR_CONTAINER_HEALTH',
        'ultra_eco': 'NOT_DEPLOYED' if requested == 'ULTRA_ECO' else 'NOT_REQUESTED',
    }


JOURNAL_PROBE = r'''
import datetime,json,pathlib,sqlite3
agents=json.loads(pathlib.Path('/app/config/agent_registry.json').read_text())['agents']
now=datetime.datetime.now(datetime.timezone.utc)
with sqlite3.connect('file:/data/compute-queue.db?mode=ro',uri=True,timeout=3) as db:
 db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON')
 columns={r[1] for r in db.execute('PRAGMA table_info(compute_jobs)')}
 statuses=dict(db.execute('SELECT status,count(*) FROM compute_jobs GROUP BY status'))
 active=[dict(r) for r in db.execute("SELECT id,agent,model,provider,priority,status,created_at,started_at,timeout_seconds FROM compute_jobs WHERE status IN ('running','queued')")]
 history=[]
 for a in agents:
  aid=a['agent_id']
  row=db.execute("SELECT id,completed_at,input_tokens,output_tokens,length(result) result_bytes FROM compute_jobs WHERE agent=? AND status='completed' AND model='gemma3:12b' AND length(result)>0 ORDER BY completed_at DESC LIMIT 1",(aid,)).fetchone()
  history.append({'agent':aid,'registered':True,'historical_persisted_deep_success':dict(row) if row else None,'current_end_to_end_status':'NOT_VERIFIED'})
 result={'canonical_agent_count':len(agents),'status_counts':statuses,'application_active_jobs':active,'application_queue_depth':statuses.get('queued',0),'lifecycle_columns_present':{'local_inflight','lifecycle_state','timings_json'}<=columns,'agents':history,'idempotency_bindings':db.execute('SELECT count(*) FROM compute_submission_keys').fetchone()[0]}
 if 'local_inflight' in columns:result['journal_slot_owners']=db.execute('SELECT count(*) FROM compute_jobs WHERE local_inflight=1').fetchone()[0]
mem={}
for line in pathlib.Path('/proc/meminfo').read_text().splitlines():
 k,_,v=line.partition(':')
 if k in ('MemTotal','MemAvailable','SwapTotal','SwapFree','SwapCached'):mem[k]=v.strip()
result['linux_memory']=mem
print(json.dumps(result))
'''


def observe(requested, ca_file=None):
    ids = command(['docker','ps','-aq','--no-trunc']).split()
    raw = json.loads(command(['docker','inspect',*ids]))
    containers = []
    backend_settings = {}
    for c in raw:
        name = c['Name'].lstrip('/')
        settings = safe_settings(c['Config'].get('Env') or [])
        if name == 'orqevia-epoch-20261016-backend-1':
            backend_settings = settings
        labels = c['Config'].get('Labels') or {}
        containers.append({'name':name,'id':c['Id'],'state':c['State']['Status'],
            'health':(c['State'].get('Health') or {}).get('Status'),
            'started_at':c['State']['StartedAt'],'image_id':c['Image'],
            'source_revision':labels.get('org.opencontainers.image.revision'),
            'safe_settings':settings})
    journal = json.loads(command(['docker','exec','-i','orqevia-epoch-20261016-backend-1',
                                 'python','-B','-'], stdin=JOURNAL_PROBE))
    stats = [json.loads(x) for x in command(['docker','stats','--no-stream','--format','{{json .}}']).splitlines() if x]
    residency = command(['docker','exec','orqevia-epoch-20261016-ollama-1','ollama','ps'])
    endpoints = []
    if ca_file:
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=ca_file)
        for path in ('/pwa/','/interface/v1/health'):
            try:
                with urllib.request.urlopen('https://localhost:8443'+path,context=context,timeout=10) as response:
                    endpoints.append({'path':path,'status':response.status,'certificate_verified':True})
            except urllib.error.HTTPError as exc:
                endpoints.append({'path':path,'status':exc.code,'certificate_verified':True})
            except (OSError,ValueError) as exc:
                endpoints.append({'path':path,'status':'NOT_VERIFIED','error_class':type(exc).__name__})
    return {'schema':'orqevia.runtime-compliance.v1',
        'observed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'execution_mode':'READ_ONLY_NO_INFERENCE','compliance':enforcement_matrix(requested,backend_settings,journal),
        'containers':containers,'journal':journal,'docker_stats':stats,
        'model_residency':residency,'https_endpoints':endpoints,
        'requesting_mission_binding':'Application candidates recorded; Ollama request-to-mission binding NOT VERIFIED',
        'thermal_power_fan':'NOT_COLLECTED','mutations_performed':False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--requested-profile', choices=['HOME_ECO','ULTRA_ECO','BALANCED'], required=True)
    parser.add_argument('--ca-file')
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    report = observe(args.requested_profile,args.ca_file)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'observed_at_utc':report['observed_at_utc'],'compliance':report['compliance'],
                      'running_containers':sum(c['state']=='running' for c in report['containers']),
                      'canonical_agent_count':report['journal']['canonical_agent_count'],
                      'output':str(args.output) if args.output else None}))


if __name__ == '__main__':
    main()
