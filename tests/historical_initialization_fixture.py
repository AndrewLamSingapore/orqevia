"""Original code/evidence fixture; never a current-source admission or live run."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
REVISION = 'd9a4e0bdd733a4908e9fa239f6b24bef3c2dce79'

CHILD = r'''
from datetime import datetime, timedelta, timezone
import json, socket, sys, threading
def denied(*args, **kwargs):
    raise AssertionError('HISTORICAL_SOURCE_FIXTURE_CANNOT_CONNECT_OR_START_WORKERS')
socket.socket.connect = denied
socket.create_connection = denied
original_thread_start = threading.Thread.start
def fixture_thread_start(thread, *args, **kwargs):
    # Windows subprocess uses reader threads for captured pipes with a timeout.
    # Permit only that standard-library I/O target; application workers stay denied.
    target = getattr(thread, '_target', None)
    if (getattr(target, '__module__', None) == 'subprocess'
            and getattr(target, '__name__', None) == '_readerthread'):
        return original_thread_start(thread, *args, **kwargs)
    return denied()
threading.Thread.start = fixture_thread_start
from scripts import audit_initialization_package as a
mode = sys.argv[1]
if mode == 'audit':
    plan = json.loads((a.ROOT / 'governance/agent-cert-initialization-proposed-fields-20261010.json').read_bytes())
    result = a.audit(plan, local_audit_at=datetime.now(timezone.utc))
else:
    if mode == 'fresh':
        from scripts import validate_fresh_initialization_20261011 as v
    else:
        from scripts import validate_initialization_protected_batch as v
    env = {'GITHUB_REPOSITORY': v.REPOSITORY, 'GITHUB_REF': 'refs/heads/main',
           'GITHUB_REF_PROTECTED': 'true', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
           'GITHUB_WORKFLOW_REF': v.REPOSITORY + '/.github/workflows/' + v.WORKFLOW + '@refs/heads/main',
           'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_RUN_ID': '123', 'GITHUB_SHA': v.MAIN, 'GITHUB_WORKFLOW_SHA': v.MAIN}
    run = {'id': 123, 'head_sha': v.MAIN, 'head_branch': 'main', 'event': 'workflow_dispatch',
           'run_attempt': 1, 'status': 'in_progress', 'conclusion': None,
           'path': '.github/workflows/' + v.WORKFLOW, 'repository': {'full_name': v.REPOSITORY}}
    def fake_history(path):
        return run if path == '/actions/runs/123' else {'total_count': 1, 'workflow_runs': [run]}
    started = datetime.now(timezone.utc)
    times = iter((started, started + timedelta(seconds=5)))
    plan = json.loads((v.ROOT / v.PLAN).read_bytes())
    result = v.protected_validation(plan, env=env, checkout_head=v.MAIN, github_read=fake_history, clock=lambda: next(times))
    assert datetime.fromisoformat(result['protected_validation_at']) == started + timedelta(seconds=5)
print(json.dumps(result))
'''


def historical_validation(tmp_path, mode):
    assert mode in {'audit', 'old', 'fresh'}
    target = tmp_path / 'historical-source'
    target.mkdir()
    archive = subprocess.check_output(['git', 'archive', '--format=tar', REVISION], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:') as source:
        source.extractall(target, filter='data')
    subprocess.run(['git', 'init', str(target)], check=True, capture_output=True)
    objects = subprocess.check_output(['git', 'rev-parse', '--path-format=absolute', '--git-path', 'objects'], cwd=ROOT, text=True).strip()
    (target / '.git/objects/info/alternates').write_text(Path(objects).as_posix() + '\n', encoding='ascii', newline='\n')
    subprocess.run(['git', 'update-ref', 'HEAD', REVISION], cwd=target, check=True, capture_output=True)
    # The public test orchestrators/plans were added after the verifier pin.
    # Overlay only those; all verifier/runtime/oracle closure files stay frozen.
    for name in ['scripts/audit_initialization_package.py', 'scripts/validate_initialization_protected_batch.py',
                 'scripts/validate_fresh_initialization_20261011.py',
                 'governance/agent-cert-initialization-proposed-fields-20261010.json',
                 'governance/agent-cert-initialization-proposed-fields-20261011.json']:
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    for plan_name in ['20261010', '20261011']:
        plan = json.loads((ROOT / ('governance/agent-cert-initialization-proposed-fields-' + plan_name + '.json')).read_bytes())
        for entry in plan['cases']:
            relative = Path(entry['evidence_directory']) / entry['record_established_fields']['agent_id']
            (target / relative).mkdir(parents=True, exist_ok=True)
            for name in ['execution.json', 'review.json']:
                shutil.copyfile(ROOT / relative / name, target / relative / name)
    env = {name: value for name, value in os.environ.items()
           if not name.startswith(('PRIME_', 'AZURE_', 'ACTIONS_', 'HF_', 'OPENAI_'))
           and name not in {'PYTHONPATH', 'PYTEST_ADDOPTS'}}
    env.update(PYTHONDONTWRITEBYTECODE='1', PRIME_DATA_DIR=str(tmp_path / 'fixture-data'),
               PRIME_COMPUTE_QUEUE_DB=str(tmp_path / 'fixture-data/compute-queue.db'))
    result = subprocess.run([sys.executable, '-B', '-c', CHILD, mode], cwd=target, env=env,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)
