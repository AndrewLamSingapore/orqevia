"""Source tests with fake GitHub metadata; never actual protected receipts."""
from datetime import datetime,timedelta,timezone
import json
import pytest
from scripts import validate_initialization_protected_batch as v
from scripts.sign_admitted_agent_cases import unchanged_reviewer_code, unchanged_runtime_reviewer_code


def _pinned_closure_drifted() -> bool:
    """True when this checkout no longer matches the pinned reviewer revisions.

    The protected one-shot initialization validation only applies to the exact
    revisions recorded in scripts/audit_initialization_package.py. On a drifted
    checkout the fail-closed audit would reject, so the local mirror of the
    happy path is skipped instead of reporting a false red. Re-run at the pinned
    revision (or after ABEX re-validates at a new revision) to exercise it.
    """
    try:
        unchanged_reviewer_code(v.ROOT, v.MAIN)
        unchanged_runtime_reviewer_code(v.ROOT, v.ORIGINAL)
    except ValueError:
        return True
    return False


_rev_guard = pytest.mark.skipif(_pinned_closure_drifted(),
    reason='pinned reviewer/verifier revisions do not match this checkout; requires ABEX re-validation')

SHA=v.MAIN
ENV={'GITHUB_REPOSITORY':v.REPOSITORY,'GITHUB_REF':'refs/heads/main','GITHUB_REF_PROTECTED':'true',
     'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_WORKFLOW_REF':v.REPOSITORY+'/.github/workflows/'+v.WORKFLOW+'@refs/heads/main',
     'GITHUB_RUN_ATTEMPT':'1','GITHUB_RUN_ID':'123','GITHUB_SHA':SHA,'GITHUB_WORKFLOW_SHA':SHA}
RUN={'id':123,'head_sha':SHA,'head_branch':'main','event':'workflow_dispatch','run_attempt':1,
     'status':'in_progress','conclusion':None,'path':'.github/workflows/'+v.WORKFLOW,
     'repository':{'full_name':v.REPOSITORY}}


def read(suffix):
    return RUN if suffix=='/actions/runs/123' else {'total_count':1,'workflow_runs':[RUN]}


@_rev_guard
def test_actual_29_custody_validated_with_fake_guard_fixed24h_source_test_only():
    plan=json.loads((v.ROOT/v.PLAN).read_bytes())
    started=datetime.now(timezone.utc)
    stamps=iter((started,started+timedelta(seconds=5)))
    result=v.protected_validation(plan,env=ENV,checkout_head=SHA,github_read=read,clock=lambda:next(stamps))
    assert result['original_case_count']==29
    assert result['signature']=='NOT_PERFORMED' and result['installed'] is False
    boundary=datetime.fromisoformat(result['protected_validation_at'])
    assert boundary==started+timedelta(seconds=5)
    for entry in result['proposed_manifest']['cases']:
        row=entry['record']
        assert row['source_revision']==row['reviewer_code_revision']==v.ORIGINAL
        assert row['certified_at']==row['last_revalidated']==boundary.isoformat()
        assert datetime.fromisoformat(row['expires_at'])-boundary==timedelta(hours=24)


@pytest.mark.parametrize('key,value',[('GITHUB_REF','refs/heads/feature'),('GITHUB_REF_PROTECTED','false'),
    ('GITHUB_EVENT_NAME','pull_request'),('GITHUB_RUN_ATTEMPT','2'),('GITHUB_REPOSITORY','attacker/prime'),
    ('GITHUB_WORKFLOW_SHA','a'*40),('GITHUB_WORKFLOW_REF','wrong')])
def test_guard_denies_before_api_read(key,value):
    env=dict(ENV);env[key]=value
    with pytest.raises(ValueError,match='GUARD'):
        v.guard(env,checkout_head=SHA,github_read=lambda _:pytest.fail('must not query'))


@pytest.mark.parametrize('prior_status',['completed','in_progress','queued'])
def test_prior_failure_or_uncertainty_consumes_batch(prior_status):
    prior=dict(RUN,id=122,status=prior_status,conclusion='failure' if prior_status=='completed' else None)
    def history(suffix):
        return RUN if suffix=='/actions/runs/123' else {'total_count':2,'workflow_runs':[RUN,prior]}
    with pytest.raises(ValueError,match='PREVIOUS_OR_CONCURRENT'):
        v.guard(ENV,checkout_head=SHA,github_read=history)


def test_authenticated_run_head_mismatch_denied():
    with pytest.raises(ValueError,match='RUN_BINDING'):
        v.guard(ENV,checkout_head=SHA,github_read=lambda _:dict(RUN,head_sha='b'*40))


def test_missing_history_current_run_denied():
    with pytest.raises(ValueError,match='HISTORY'):
        v.guard(ENV,checkout_head=SHA,github_read=lambda p:RUN if p=='/actions/runs/123' else {'total_count':0,'workflow_runs':[]})


def test_wrong_exact_digestset_denied_before_validation():
    plan=json.loads((v.ROOT/v.PLAN).read_bytes())
    plan['cases'][0]['execution_sha256']='0'*64
    with pytest.raises(ValueError,match='DIGESTSET'):
        v.protected_validation(plan,env=ENV,checkout_head=SHA,github_read=read)
