import datetime as dt
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

from scripts import validate_fresh_initialization_20261016 as v


def test_batch_plan_matches_pinned_digest_and_evidence():
    plan=json.loads((ROOT/v.PLAN).read_bytes())
    assert plan['case_count']==29 and len(plan['cases'])==29
    tuples=sorted((e['record_established_fields']['agent_id'],e['record_established_fields']['capability_id'],
                   e['execution_sha256'],e['review_sha256']) for e in plan['cases'])
    assert hashlib.sha256(json.dumps(tuples,separators=(',',':')).encode()).hexdigest()==v.BATCH
    for e in plan['cases']:
        d=ROOT/e['evidence_directory']/e['record_established_fields']['agent_id']
        assert hashlib.sha256(d.joinpath('execution.json').read_bytes()).hexdigest()==e['execution_sha256']
        assert hashlib.sha256(d.joinpath('review.json').read_bytes()).hexdigest()==e['review_sha256']
        assert e['execution_source_revision']==v.SOURCE and e['reviewer_code_revision']==v.SOURCE
        assert e['verifier_code_revision']==v.VERIFIER and e['runtime_image_id']==v.IMAGE


def test_protected_validation_dry_run_with_fake_guard():
    plan=json.loads((ROOT/v.PLAN).read_bytes())
    sha=v.VERIFIER
    env={'GITHUB_REPOSITORY':v.REPOSITORY,'GITHUB_REF':'refs/heads/main','GITHUB_REF_PROTECTED':'true',
         'GITHUB_EVENT_NAME':'workflow_dispatch',
         'GITHUB_WORKFLOW_REF':v.REPOSITORY+'/.github/workflows/'+v.WORKFLOW+'@refs/heads/main',
         'GITHUB_RUN_ATTEMPT':'1','GITHUB_RUN_ID':'555','GITHUB_SHA':sha,'GITHUB_WORKFLOW_SHA':sha}
    run={'id':555,'head_sha':sha,'head_branch':'main','event':'workflow_dispatch','run_attempt':1,
         'status':'in_progress','conclusion':None,'path':'.github/workflows/'+v.WORKFLOW,
         'repository':{'full_name':v.REPOSITORY}}
    def fake(path):
        return run if path=='/actions/runs/555' else {'total_count':1,'workflow_runs':[run]}
    t0=dt.datetime.now(dt.timezone.utc)
    times=iter((t0,t0+dt.timedelta(seconds=5)))
    result=v.protected_validation(plan,env=env,checkout_head=sha,github_read=fake,clock=lambda: next(times))
    assert result['original_case_count']==29 and result['all_original_oracles']=='PASS'
    assert result['signature']=='NOT_PERFORMED' and result['l7_awarded'] is False and result['installed'] is False
