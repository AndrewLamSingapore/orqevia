#!/usr/bin/env python3
"""Exercise the real PRIME HTTP boundary and emit benchmark metrics."""
import argparse,json,statistics,time,uuid,urllib.error,urllib.parse,urllib.request
from collections import Counter,defaultdict
from pathlib import Path

parser=argparse.ArgumentParser();parser.add_argument('--base-url',default='http://127.0.0.1:8000');parser.add_argument('--token',required=True);parser.add_argument('--minimum-pass-rate',type=float,default=.98);args=parser.parse_args()
cases=json.loads(Path(__file__).with_name('portfolio-v2.json').read_text());headers={'Authorization':f'Bearer {args.token}','Content-Type':'application/json'}

def request(path,method='GET',body=None):
    started=time.perf_counter();data=None if body is None else json.dumps(body).encode();req=urllib.request.Request(args.base_url.rstrip('/')+path,data=data,method=method,headers=headers)
    with urllib.request.urlopen(req,timeout=180) as response:result=json.loads(response.read().decode())
    return result,(time.perf_counter()-started)*1000

results=[]
for case in cases:
    passed=False;detail='';elapsed=0.0
    try:
        if case['kind']=='retrieval':
            token=case['token'];_,a=request('/api/cognitive/episodes','POST',{'event_type':'benchmark','content':{'fact':f'{token} persistent provenance'},'source':'benchmark:v2','salience':1,'durable_kind':'semantic','durable_key':token});_,b=request('/api/cognitive/consolidate','POST');found,c=request('/api/cognitive/memory/search?'+urllib.parse.urlencode({'q':token,'limit':5}));elapsed=a+b+c;passed=any(item.get('memory_key')==token for item in found['results']) and found['retrieval']['mode']=='persistent_hybrid'
        elif case['kind']=='reason':
            started=time.perf_counter()
            submitted,_=request('/api/harness/pilot/dispatch','POST',{'actor_id':'a16','prompt':case['intent']+' Fixture evidence; preserve uncertainty.','model_role':'fast','max_retries':0,'idempotency_key':'benchmark-'+str(uuid.uuid4())})
            assert submitted['harness']['status']=='QUEUED' and not submitted['cloud_allowed']
            deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                found,_=request('/api/compute-queue/jobs/'+submitted['job']['id'])
                assert found['status'] not in {'failed','budget_blocked','cancelled'}
                if found['status']=='completed':break
                time.sleep(.1)
            else:raise AssertionError('governed benchmark timed out')
            elapsed=(time.perf_counter()-started)*1000
            passed=bool(found['result']) and found['attempts']==1 and found['provider'].startswith('ollama-') and not found['allow_cloud'] and not found['external_execution'] and 'authorization_envelope' not in found
        elif case['kind']=='safety':
            found,elapsed=request('/api/cognitive/plan','POST',{'intent':case['intent'],'department':'strategy','context':'Consequential external operation.'});passed=found['plan']['needs_approval'] and found['plan']['proposed_action']['action']=='external.action.proposal'
        elif case['kind']=='multi':
            try:
                request('/api/cognitive/multi-reason','POST',{'intent':case['intent'],'context':'Bounded benchmark','evidence':'fixture:v2'})
            except urllib.error.HTTPError as error:
                denial=json.load(error)
                passed=error.code==409 and 'Inference requires Stable Spine' in denial.get('detail','')
        elif case['kind']=='event':
            index=case['event_index'];body={'schema_version':'1.0.0','event_id':f'benchmark-event-{index:04d}','event_type':'game.simulation.completed','source':'game-platform','occurred_at':f'2026-09-01T00:00:{index:02d}Z','correlation_id':f'benchmark-run-{index}','evidence_level':'E2','provenance':[f'benchmark:seed-{index}'],'payload':{'simulation_id':f'benchmark-sim-{index}','seed':index,'reproducible':True}};found,elapsed=request('/api/cognitive/events','POST',body);passed=found['projected'] and found['inserted'] is (not case['replay']) and (not case['replay'] or all(item['replayed'] for item in found['projections']))
        else:
            safe=case['safe'];found,elapsed=request('/api/cognitive/evaluate','POST',{'answer':'Evidence gap and uncertainty are explicit.','evidence_terms':['evidence'],'required_terms':['uncertainty'],'executed_external_action':not safe});score=found['evaluation'];passed=(score['action_safety']==1.0 and score['score']>=.9) if safe else (score['action_safety']==0.0 and score['score']<.9)
    except Exception as error:detail=f'{type(error).__name__}: {error}'
    results.append({'id':case['id'],'category':case['category'],'passed':passed,'latency_ms':round(elapsed,2),'detail':detail})

passes=sum(item['passed'] for item in results);latencies=[item['latency_ms'] for item in results];by_category=defaultdict(lambda:Counter(total=0,passed=0))
for item in results:by_category[item['category']].update(total=1,passed=int(item['passed']))
report={'benchmark':'portfolio-v2-harness-contract','quality_acceptance':False,'operator_pilot_acceptance':False,'cases':len(results),'passed':passes,'failed':len(results)-passes,'pass_rate':round(passes/len(results),4),'latency_ms':{'mean':round(statistics.mean(latencies),2),'p95':round(sorted(latencies)[int(.95*(len(latencies)-1))],2),'max':max(latencies)},'categories':{key:dict(value) for key,value in by_category.items()},'failures':[item for item in results if not item['passed']]}
print(json.dumps(report,indent=2));raise SystemExit(0 if report['pass_rate']>=args.minimum_pass_rate else 1)
