"""Offline installed-package closure checks, not Linux CI or certification."""
import ast
from pathlib import Path
import os
import re
import subprocess
import sys
import textwrap


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/prime-verifier-signer.yml'
CHECK_NAME = 'Check owning initialization verification imports (no signing)'
SCRATCH_DATA = '${{ runner.temp }}/prime-verifier-domains'
EXPECTED_PINS = ('cryptography==50.0.2', 'httpx==0.28.1', 'fastapi==0.116.1')
IMPORT_CHECK = '''
from app.agent_dispatch_api import AgentRequest
from app.objective_api import inference_attempt_projection
from app.compute_queue_api import pool, queue
from app import agent_registry, agent_cert_initialization as initialization

assert AgentRequest.model_json_schema()['type'] == 'object'
projection = inference_attempt_projection([])
assert projection['status'] == 'NOT_APPLICABLE' and projection['attempts'] == []
assert projection['verification'] == 'UNVERIFIED'
registry_sha = initialization.sha(agent_registry.REGISTRY_PATH.read_bytes())
pairs = [(item['id'], capability)
         for item in agent_registry.load_agent_registry()['agents']
         for capability in item['capability_requirements']]
assert len(pairs) == 29 and len({agent for agent, _ in pairs}) == 21
for agent, capability in pairs:
    initialization._owned_domains(registry_sha, agent, capability)
assert pool.threads == []
with queue.connect() as connection:
    assert connection.execute('SELECT COUNT(*) FROM compute_jobs').fetchone()[0] == 0
print('Initialization verification imports ready; source check only, no signing')
'''


def step(name):
    source = WORKFLOW.read_text()
    match = re.search(r'^      - name: ' + re.escape(name) + r'\n(.*?)(?=^      - |\Z)',
                      source, re.M | re.S)
    assert match is not None, 'Required fixed workflow step missing'
    return match.group(1)


def declared_pins():
    source = WORKFLOW.read_text()
    command = re.search(r'run: python -m pip install --disable-pip-version-check ([^\n]+)', source)
    assert command is not None
    return tuple(command.group(1).split())


def inline_check():
    body = step(CHECK_NAME)
    match = re.search(r"          python - <<'PY'\n(.*?)          PY\n", body, re.S)
    assert match is not None
    return textwrap.dedent(match.group(1))


# Fresh child has no already-imported application modules. The finder permits
# only declared distributions plus their installed normal transitive closure;
# optional extras and unrelated locally installed packages cannot mask a hole.
PROBE = r'''
import http.client, importlib.abc, importlib.machinery, importlib.metadata
import json, os, pathlib, re, socket, subprocess, sys, threading, urllib.request
from packaging.requirements import Requirement
def forbidden(*args, **kwargs):
    raise AssertionError('OFFLINE_IMPORT_CANNOT_CONNECT_START_SIGN_OR_GENERATE_KEYS')
socket.socket.connect = forbidden
socket.create_connection = forbidden
urllib.request.urlopen = forbidden
http.client.HTTPConnection.connect = forbidden
subprocess.Popen.__init__ = forbidden
threading.Thread.start = forbidden
pins, check, mode = json.loads(sys.argv[1])
normalize = lambda name: re.sub(r'[-_.]+', '-', name).lower()
pending = [pin.split('==')[0] for pin in pins]
allowed = {}
while pending:
    name = normalize(pending.pop())
    if name in allowed:
        continue
    distribution = importlib.metadata.distribution(name)
    allowed[name] = distribution.version
    for requirement in distribution.requires or ():
        required = Requirement(requirement)
        if required.marker is None or required.marker.evaluate({'extra': ''}):
            pending.append(required.name)
# packaging is test-only marker parsing, never an extra application dependency.
for name in list(sys.modules):
    if name == 'packaging' or name.startswith('packaging.'):
        del sys.modules[name]
namespaces = {top for top, distributions in importlib.metadata.packages_distributions().items()
              if any(normalize(name) in allowed for name in distributions)}
class DeclaredOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is not None and spec.origin and 'site-packages' in spec.origin:
            if fullname.split('.')[0] not in namespaces:
                raise ModuleNotFoundError('UNDECLARED_DEPENDENCY:' + fullname, name=fullname)
sys.meta_path.insert(0, DeclaredOnly())
from cryptography.hazmat.primitives.asymmetric import ec
ec.generate_private_key = forbidden
import httpx
httpx.HTTPTransport.handle_request = forbidden
httpx.AsyncHTTPTransport.handle_async_request = forbidden
from scripts import agent_cert_reviewed_signing as bridge
bridge.ProtectedAzureES256Signer = forbidden
if mode == 'default-path-denied':
    original_mkdir = pathlib.Path.mkdir
    def denied_mkdir(path, *args, **kwargs):
        if path == pathlib.Path('/data'):
            raise PermissionError('SYNTHETIC_UNPRIVILEGED_ROOT_DATA_DENIAL')
        return original_mkdir(path, *args, **kwargs)
    pathlib.Path.mkdir = denied_mkdir
    try:
        from app.objective_api import inference_attempt_projection
    except PermissionError as error:
        assert str(error) == 'SYNTHETIC_UNPRIVILEGED_ROOT_DATA_DENIAL'
    else:
        raise AssertionError('Expected the actual objective import to require writable queue data')
else:
    exec(compile(check, '<fixed-workflow-import-check>', 'exec'))
    from app.compute_queue_api import queue
    assert pathlib.Path(queue.db_path).resolve() == pathlib.Path(os.environ['PRIME_COMPUTE_QUEUE_DB']).resolve()
    assert pathlib.Path(os.environ['PRIME_DATA_DIR']).resolve() in pathlib.Path(queue.db_path).resolve().parents
    assert threading.active_count() == 1
print(json.dumps({'scope': 'INSTALLED_CLOSURE_ONLY_NOT_LINUX_CI', 'distributions': allowed}, sort_keys=True))
'''


def probe(tmp_path, pins, check, mode='scratch'):
    environment = {name: value for name, value in os.environ.items()
                   if not name.startswith(('PRIME_', 'AZURE_', 'ACTIONS_', 'HF_', 'OPENAI_'))
                   and name not in ('PYTHONPATH', 'PYTEST_ADDOPTS')}
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    if mode == 'scratch':
        environment['PRIME_DATA_DIR'] = str(tmp_path / 'synthetic-runner-temp' / 'prime-verifier-domains')
        environment['PRIME_COMPUTE_QUEUE_DB'] = str(Path(environment['PRIME_DATA_DIR']) / 'compute-queue.db')
    import json
    result = subprocess.run([sys.executable, '-B', '-c', PROBE,
        json.dumps([pins, check, mode])], cwd=ROOT, env=environment,
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_declared_dependencies_import_actual_initialization_domains(tmp_path):
    # Before repair this uses the same exact import check and rejects FastAPI.
    assert 'INSTALLED_CLOSURE_ONLY_NOT_LINUX_CI' in probe(tmp_path, declared_pins(), IMPORT_CHECK)


def test_removed_fastapi_cannot_borrow_unrelated_installed_packages(tmp_path):
    import pytest
    with pytest.raises(AssertionError, match='UNDECLARED_DEPENDENCY:fastapi'):
        probe(tmp_path, EXPECTED_PINS[:2], IMPORT_CHECK)


def test_actual_objective_import_has_unprivileged_default_path_dependency(tmp_path):
    assert 'INSTALLED_CLOSURE_ONLY_NOT_LINUX_CI' in probe(tmp_path, EXPECTED_PINS, '', 'default-path-denied')


def test_workflow_uses_only_scratch_state_before_signing():
    assert declared_pins() == EXPECTED_PINS
    for name in (CHECK_NAME, 'Sign only fixed independently reviewed admitted cases'):
        body = step(name)
        assert 'PRIME_DATA_DIR: ' + SCRATCH_DATA in body
        assert 'PRIME_COMPUTE_QUEUE_DB: ' + SCRATCH_DATA + '/compute-queue.db' in body
    source = WORKFLOW.read_text()
    assert source.index(CHECK_NAME) < source.index('Protected Azure sign, public verification, tamper rejection')
    assert 'requirements.txt' not in source and '[standard]' not in source
    assert 'secrets: inherit' not in source and '\n  inputs:' not in source


def test_exact_inline_cloud_check_is_offline_and_owning_source(tmp_path):
    code = inline_check()
    assert ast.dump(ast.parse(code)) == ast.dump(ast.parse(IMPORT_CHECK))
    assert 'INSTALLED_CLOSURE_ONLY_NOT_LINUX_CI' in probe(tmp_path, declared_pins(), code)
