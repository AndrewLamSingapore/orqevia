"""Current-source, offline trust guards; no OIDC/Azure exchange or redispatch."""
from pathlib import Path
import base64
import json
import os
import subprocess
import sys

import pytest

from scripts import azure_verifier_live_canary as canary
from scripts import validate_initialization_protected_batch as old_batch
from scripts import validate_fresh_initialization_20261011 as fresh_batch

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'AndrewLamSingapore/orqevia'
CALLER = REPOSITORY + '/.github/workflows/orqevia-verifier-oidc.yml@refs/heads/main'
SIGNER = REPOSITORY + '/.github/workflows/orqevia-verifier-signer.yml@refs/heads/main'


def test_reusable_workflow_and_claim_bindings_agree():
    caller = (ROOT/'.github/workflows/orqevia-verifier-oidc.yml').read_text()
    signer = (ROOT/'.github/workflows/orqevia-verifier-signer.yml').read_text()
    assert 'uses: ' + SIGNER.removesuffix('refs/heads/main') + 'main' in caller
    assert CALLER in caller and CALLER in signer
    assert canary.CALLER == CALLER and canary.SIGNER == SIGNER
    assert canary.SUBJECT == 'repo:AndrewLamSingapore@313231443/orqevia@1345668764:ref:refs/heads/main'
    assert 'secrets: inherit' not in caller + signer


@pytest.mark.parametrize('workflow', ['orqevia-verifier-oidc.yml', 'orqevia-verifier-signer.yml'])
@pytest.mark.parametrize('repository,protected,event,expected_pass', [
    (REPOSITORY, 'true', 'workflow_dispatch', True),
    ('AndrewLamSingapore/prime', 'true', 'workflow_dispatch', False),
    ('attacker/orqevia', 'true', 'workflow_dispatch', False),
    (REPOSITORY, 'false', 'workflow_dispatch', False),
    (REPOSITORY, 'true', 'pull_request', False),
])
def test_actual_workflow_guard_fails_closed(workflow, repository, protected, event, expected_pass, tmp_path):
    value = (ROOT/'.github/workflows'/workflow).read_text()
    code = value.split("python - <<'PY'\n", 1)[1].split('\n          PY', 1)[0]
    code = '\n'.join(line.removeprefix('          ') for line in code.splitlines())
    env = dict(os.environ, REPOSITORY=repository, REF='refs/heads/main',
               REF_PROTECTED=protected, EVENT_NAME=event, WORKFLOW_REF=CALLER,
               GITHUB_OUTPUT=str(tmp_path/'output'))
    result = subprocess.run([sys.executable, '-B', '-c', code], env=env,
                            capture_output=True, text=True)
    assert (result.returncode == 0) is expected_pass


@pytest.mark.parametrize('validator', [old_batch, fresh_batch])
def test_retired_repository_denied_before_github_history_read(validator):
    env = {'GITHUB_REPOSITORY': 'AndrewLamSingapore/prime'}
    with pytest.raises(ValueError, match='GUARD'):
        validator.guard(env, checkout_head=validator.MAIN,
                        github_read=lambda _: pytest.fail('must not query GitHub'))


def test_distinct_consumed_batches_and_workflow_history_paths_preserved():
    assert old_batch.WORKFLOW == 'prime-initialization-validation.yml'
    assert fresh_batch.WORKFLOW == 'orqevia-fresh-initialization-validation-20261011.yml'
    assert old_batch.BATCH == '9792f8d3ef5f9a72ca4d9ef0501ed74ce7a7363d5555e39151d59eb9b26d98d5'
    assert fresh_batch.BATCH == 'ccf4a0137006aac948d83b2f7791629ff62092791f2401b2fe9b157d309cec9e'
    for validator in (old_batch, fresh_batch):
        assert validator.REPOSITORY == REPOSITORY
        source = (ROOT/'scripts'/Path(validator.__file__).name).read_text()
        assert "'/actions/workflows/'+WORKFLOW+'/runs?event=workflow_dispatch&per_page=100'" in source
    # The superseded fixed29 workflow file is retired by this PR; its identity
    # stays pinned in the validator constants and dated history. Only the live
    # fresh29 workflow must still carry the protected-run guards.
    assert not (ROOT/'.github/workflows'/old_batch.WORKFLOW).exists()
    workflow = (ROOT/'.github/workflows'/fresh_batch.WORKFLOW).read_text()
    assert 'github.run_attempt == 1' in workflow and 'github.ref_protected' in workflow


@pytest.mark.parametrize('field,value', [
    ('repository', 'AndrewLamSingapore/prime'),
    ('repository_id', '999'), ('repository_owner_id', '999'),
    ('sub', 'repo:AndrewLamSingapore@313231443/prime@1345668764:ref:refs/heads/main'),
    ('workflow_ref', 'AndrewLamSingapore/prime/.github/workflows/prime-verifier-oidc.yml@refs/heads/main'),
    ('job_workflow_ref', 'AndrewLamSingapore/prime/.github/workflows/prime-verifier-signer.yml@refs/heads/main'),
])
def test_oidc_rejects_retired_identity_and_numeric_identity_mismatch(field, value, monkeypatch):
    head = 'b'*40
    claims = {'iss': 'https://token.actions.githubusercontent.com', 'aud': canary.AUDIENCE,
              'sub': canary.SUBJECT, 'repository': REPOSITORY, 'repository_id': '1345668764',
              'repository_owner_id': '313231443', 'ref': 'refs/heads/main', 'ref_protected': 'true',
              'workflow_ref': CALLER, 'job_workflow_ref': SIGNER,
              'workflow_sha': head, 'job_workflow_sha': head, 'event_name': 'workflow_dispatch'}
    claims[field] = value
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b'=').decode()
    monkeypatch.setenv('GITHUB_SHA', head)
    monkeypatch.setenv('ACTIONS_ID_TOKEN_REQUEST_URL', 'https://oidc.example.test/token')
    monkeypatch.setenv('ACTIONS_ID_TOKEN_REQUEST_TOKEN', 'synthetic-test-only')
    monkeypatch.setattr(canary, '_read_json', lambda _: {'value': 'header.'+payload+'.signature'})
    with pytest.raises(ValueError, match='OIDC claims not bound'):
        canary._oidc()
