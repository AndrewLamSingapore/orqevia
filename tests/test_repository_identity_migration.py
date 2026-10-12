"""Offline repository guards only; no dispatch, Azure access or signing."""
import os
import re
import base64
import json
from pathlib import Path

import pytest

from scripts import validate_initialization_protected_batch as old
from scripts import validate_fresh_initialization_20261011 as fresh
from scripts import azure_verifier_live_canary as canary

ROOT = Path(__file__).resolve().parents[1]
REPO = 'AndrewLamSingapore/orqevia'


@pytest.mark.parametrize('filename', ['prime-verifier-oidc.yml', 'prime-verifier-signer.yml'])
@pytest.mark.parametrize('change', [None, ('REPOSITORY', 'AndrewLamSingapore/prime'),
    ('REPOSITORY', 'attacker/orqevia'), ('REF', 'refs/heads/feature'),
    ('REF_PROTECTED', 'false'), ('EVENT_NAME', 'pull_request'),
    ('WORKFLOW_REF', REPO + '/.github/workflows/wrong.yml@refs/heads/main')])
def test_workflow_inline_guard_executes_current_identity_and_denies_untrusted(filename, change, monkeypatch, tmp_path):
    text = (ROOT / '.github/workflows' / filename).read_text()
    code = re.search(r"python - <<'PY'\n(.*?)\n          PY", text, re.S).group(1)
    code = '\n'.join(line[10:] for line in code.splitlines())
    env = {'REPOSITORY': REPO, 'REF': 'refs/heads/main', 'REF_PROTECTED': 'true',
           'EVENT_NAME': 'workflow_dispatch', 'WORKFLOW_REF': canary.CALLER,
           'GITHUB_OUTPUT': str(tmp_path / 'output')}
    if change:
        env[change[0]] = change[1]
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    if change:
        with pytest.raises(SystemExit):
            exec(compile(code, filename, 'exec'), {})
    else:
        exec(compile(code, filename, 'exec'), {})


@pytest.mark.parametrize('module', [old, fresh])
def test_initializer_rename_preserves_exact_batch_workflow_and_consumed_history(module):
    assert module.REPOSITORY == REPO
    sha = 'a' * 40
    env = {'GITHUB_REPOSITORY': REPO, 'GITHUB_REF': 'refs/heads/main',
           'GITHUB_REF_PROTECTED': 'true', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
           'GITHUB_WORKFLOW_REF': REPO + '/.github/workflows/' + module.WORKFLOW + '@refs/heads/main',
           'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_RUN_ID': '123', 'GITHUB_SHA': sha, 'GITHUB_WORKFLOW_SHA': sha}
    row = {'id': 123, 'head_sha': sha, 'head_branch': 'main', 'event': 'workflow_dispatch',
           'run_attempt': 1, 'status': 'in_progress', 'conclusion': None,
           'path': '.github/workflows/' + module.WORKFLOW, 'repository': {'full_name': REPO}}
    def read(path):
        return row if path == '/actions/runs/123' else {'total_count': 1, 'workflow_runs': [row]}
    assert module.guard(env, checkout_head=sha, github_read=read)['batch_sha256'] == module.BATCH
    for prior_status in ('completed', 'queued', 'in_progress'):
        def consumed(path):
            return row if path == '/actions/runs/123' else {'total_count': 2, 'workflow_runs':
                [row, dict(row, id=122, status=prior_status, conclusion='failure')]}
        with pytest.raises(ValueError, match='PREVIOUS_OR_CONCURRENT'):
            module.guard(env, checkout_head=sha, github_read=consumed)
    text = (ROOT / '.github/workflows' / module.WORKFLOW).read_text()
    assert "github.repository == '" + REPO + "'" in text
    assert 'github.run_attempt == 1' in text
    assert 'cancel-in-progress: false' in text


def test_oidc_numeric_subject_paths_and_reusable_reference_remain_exact():
    assert canary.SUBJECT == 'repo:AndrewLamSingapore@313231443/orqevia@1345668764:ref:refs/heads/main'
    assert canary.CALLER == REPO + '/.github/workflows/prime-verifier-oidc.yml@refs/heads/main'
    assert canary.SIGNER == REPO + '/.github/workflows/prime-verifier-signer.yml@refs/heads/main'
    text = (ROOT / '.github/workflows/prime-verifier-oidc.yml').read_text()
    assert 'uses: ' + REPO + '/.github/workflows/prime-verifier-signer.yml@main' in text
    assert old.WORKFLOW != fresh.WORKFLOW and old.BATCH != fresh.BATCH


@pytest.mark.parametrize('field,value', [('repository', 'AndrewLamSingapore/prime'),
    ('repository_id', '1'), ('repository_owner_id', '1'), ('sub', 'old-subject'),
    ('workflow_ref', 'wrong-caller'), ('job_workflow_ref', 'wrong-signer'),
    ('workflow_sha', 'b' * 40), ('job_workflow_sha', 'b' * 40),
    ('ref', 'refs/heads/feature'), ('ref_protected', 'false'), ('event_name', 'pull_request')])
def test_oidc_claim_mismatch_denied_with_only_offline_token_fixture(field, value, monkeypatch):
    sha = 'a' * 40
    claims = {'iss': 'https://token.actions.githubusercontent.com', 'aud': canary.AUDIENCE,
        'sub': canary.SUBJECT, 'repository': REPO, 'repository_id': '1345668764',
        'repository_owner_id': '313231443', 'ref': 'refs/heads/main', 'ref_protected': 'true',
        'workflow_ref': canary.CALLER, 'job_workflow_ref': canary.SIGNER,
        'workflow_sha': sha, 'job_workflow_sha': sha, 'event_name': 'workflow_dispatch'}
    monkeypatch.setenv('GITHUB_SHA', sha)
    monkeypatch.setenv('ACTIONS_ID_TOKEN_REQUEST_URL', 'https://offline.invalid/token')
    monkeypatch.setenv('ACTIONS_ID_TOKEN_REQUEST_TOKEN', 'fixture-only')
    def token():
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b'=').decode()
        return 'header.' + payload + '.signature'
    monkeypatch.setattr(canary, '_read_json', lambda operation: {'value': token()})
    assert canary._oidc() == token()
    claims[field] = value
    with pytest.raises(ValueError, match='OIDC claims not bound'):
        canary._oidc()
