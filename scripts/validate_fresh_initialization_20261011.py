"""Fixed29 public-only protected validation. No signer, renewal or installation.

One workflow invocation consumes this exact evidence batch, including failure.
Subsequent runs/attempts are denied. Local audit never emits protected rows.
"""
from datetime import datetime,timedelta,timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib import request

from scripts.audit_initialization_package import audit,MAIN,ORIGINAL,ROOT
from scripts.sign_admitted_agent_cases import parse

REPOSITORY='AndrewLamSingapore/orqevia'
WORKFLOW='orqevia-fresh-initialization-validation-20261011.yml'
BATCH='ccf4a0137006aac948d83b2f7791629ff62092791f2401b2fe9b157d309cec9e'
PLAN='governance/agent-cert-initialization-proposed-fields-20261011.json'
IMAGE='sha256:1554813d96cef71e9c649b820690cdd897e2f44ab9bd0f80a9314ddd76978f68'


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def guard(env, *, checkout_head, github_read):
    expected=REPOSITORY+'/.github/workflows/'+WORKFLOW+'@refs/heads/main'
    if (env.get('GITHUB_REPOSITORY')!=REPOSITORY or env.get('GITHUB_REF')!='refs/heads/main'
            or env.get('GITHUB_REF_PROTECTED')!='true'
            or env.get('GITHUB_EVENT_NAME')!='workflow_dispatch'
            or env.get('GITHUB_WORKFLOW_REF')!=expected
            or env.get('GITHUB_RUN_ATTEMPT')!='1'
            or checkout_head!=env.get('GITHUB_SHA')
            or env.get('GITHUB_WORKFLOW_SHA')!=checkout_head
            or len(checkout_head)!=40 or any(c not in '0123456789abcdef' for c in checkout_head)):
        raise ValueError('PROTECTED_FIXED_BATCH_GUARD_DENIED')
    run_id=env.get('GITHUB_RUN_ID','')
    if not run_id.isdecimal():raise ValueError('EXACT_RUN_ID_REQUIRED')
    current=github_read('/actions/runs/'+run_id)
    if (type(current) is not dict or current.get('id')!=int(run_id)
            or current.get('head_sha')!=checkout_head or current.get('head_branch')!='main'
            or current.get('event')!='workflow_dispatch' or current.get('run_attempt')!=1
            or current.get('status')!='in_progress' or current.get('conclusion') is not None
            or current.get('path')!='.github/workflows/'+WORKFLOW
            or current.get('repository',{}).get('full_name')!=REPOSITORY):
        raise ValueError('AUTHENTICATED_RUN_BINDING_DENIED')
    runs=github_read('/actions/workflows/'+WORKFLOW+'/runs?event=workflow_dispatch&per_page=100')
    if (type(runs) is not dict or type(runs.get('total_count')) is not int
            or not 1<=runs['total_count']<=100 or type(runs.get('workflow_runs')) is not list
            or len(runs['workflow_runs'])!=runs['total_count']):
        raise ValueError('COMPLETE_BOUNDED_INVOCATION_HISTORY_REQUIRED')
    # The workflow has no inputs and binds one source batch. Any other invocation
    # consumes/rejects this batch regardless of success, failure or uncertainty.
    if len(runs['workflow_runs'])!=1 or runs['workflow_runs'][0].get('id')!=int(run_id):
        raise ValueError('BATCH_PREVIOUS_OR_CONCURRENT_INVOCATION_DENIED')
    return {'run_id':int(run_id),'run_attempt':1,'source_revision':checkout_head,
            'workflow_ref':expected,'batch_sha256':BATCH}


def protected_validation(plan, *, env, checkout_head, github_read, clock=lambda:datetime.now(timezone.utc)):
    provenance=guard(env,checkout_head=checkout_head,github_read=github_read)
    pairs=sorted((e['record_established_fields']['agent_id'],e['record_established_fields']['capability_id'],
                  e['execution_sha256'],e['review_sha256']) for e in plan['cases'])
    # Original digest uses JSON's default ensure_ascii and list order exactly.
    digest=hashlib.sha256(json.dumps(pairs,separators=(',',':')).encode()).hexdigest()
    if digest!=BATCH:raise ValueError('EXACT_ORIGINAL_29_DIGESTSET_REQUIRED')
    if any(e['execution_source_revision']!=ORIGINAL or e['reviewer_code_revision']!=ORIGINAL
           or e['verifier_code_revision']!=MAIN or e['runtime_image_id']!=IMAGE for e in plan['cases']):
        raise ValueError('FIXED_SOURCE_IMAGE_CLOSURE_REQUIRED')
    started=clock()
    result=audit(plan,local_audit_at=started)
    boundary=clock()
    if (boundary.tzinfo is None or started.tzinfo is None or not started<=boundary
            or (boundary-started).total_seconds()>120):
        raise ValueError('PROTECTED_VALIDATION_CLOCK_BOUND_DENIED')
    boundary=boundary.astimezone(timezone.utc)
    expires=boundary+timedelta(hours=24)
    entries=[]
    for e in plan['cases']:
        row=dict(e['record_established_fields'])
        row.update(certification_test='baseline-initialization',test_version=row['review_test_version'],
                   certified_at=boundary.isoformat(),last_revalidated=boundary.isoformat(),
                   expires_at=expires.isoformat())
        entries.append({k:e[k] for k in ('evidence_directory','execution_sha256','review_sha256',
            'execution_source_revision','runtime_image_id','reviewer_code_revision','verifier_code_revision',
            'cloud_policy','owner_policy_sha256')} | {'record':row})
    proposed={'schema_version':'prime.protected-reviewed-cases.v1','cases':entries}
    parse(canonical(proposed)) # unchanged parser, not active manifest installation
    return {'schema':'prime.protected-initialization-validation.v1','provenance':provenance,
        'protected_validation_at':boundary.isoformat(),'fixed_expires_at':expires.isoformat(),
        'original_case_count':len(result['cases']),'all_original_oracles':'PASS',
        'proposed_manifest':proposed,'proposed_manifest_sha256':hashlib.sha256(canonical(proposed)).hexdigest(),
        'signature':'NOT_PERFORMED','l7_awarded':False,'installed':False,'rolling_renewal':False}


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def github_reader(token):
    opener=request.build_opener(NoRedirect)
    calls=[]
    def read(suffix):
        if suffix not in {'/actions/runs/'+os.environ['GITHUB_RUN_ID'],
                         '/actions/workflows/'+WORKFLOW+'/runs?event=workflow_dispatch&per_page=100'} or suffix in calls:
            raise ValueError('FIXED_SINGLE_READ_REQUIRED')
        calls.append(suffix)
        req=request.Request('https://api.github.com/repos/'+REPOSITORY+suffix,
            headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
                     'X-GitHub-Api-Version':'2022-11-28','User-Agent':'PRIME-fixed29-public-validation'})
        with opener.open(req,timeout=10) as response:
            if response.status!=200:raise ValueError('READONLY_GITHUB_RESPONSE_DENIED')
            raw=response.read(1024*1024+1)
        if len(raw)>1024*1024:raise ValueError('GITHUB_RESPONSE_BOUND')
        return json.loads(raw)
    return read


def main():
    # Only workflow entry point; no local-mode capability to emit protected rows.
    out=ROOT/'fresh-initialization-validation-output'
    out.mkdir(exist_ok=False)
    try:
        head=subprocess.run(['git','rev-parse','HEAD'],capture_output=True,check=True,timeout=5).stdout.decode().strip()
        token=os.environ.get('GH_READ_TOKEN')
        if not isinstance(token,str) or not token:raise ValueError('READONLY_WORKFLOW_TOKEN_REQUIRED')
        result=protected_validation(json.loads((ROOT/PLAN).read_bytes()),env=os.environ,
            checkout_head=head,github_read=github_reader(token))
        with (out/'protected-validation.json').open('xb') as stream:stream.write(canonical(result))
        print('FIXED_29_VALIDATED_PROPOSED_ROWS_ONLY_NO_SIGNATURE_NO_INSTALL')
    except Exception:
        with (out/'failure.json').open('xb') as stream:
            stream.write(canonical({'state':'REJECTED_OR_UNCERTAIN_BATCH_CONSUMED_NO_RETRY',
                'batch_sha256':BATCH,'run_id':os.environ.get('GITHUB_RUN_ID'),'run_attempt':os.environ.get('GITHUB_RUN_ATTEMPT'),
                'signature':'NOT_PERFORMED','l7_awarded':False}))
        raise SystemExit('Fixed batch validation rejected; original failure preserved, no automatic retry') from None


if __name__=='__main__':main()
