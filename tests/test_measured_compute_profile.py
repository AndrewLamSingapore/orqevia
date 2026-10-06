import hashlib,io,json,urllib.request
from types import SimpleNamespace
import pytest
from app import compute_profile as cp
from app.settings import SETTINGS
from tests.backend_receipt_fixture import install as install_backend_receipt


@pytest.fixture
def measured(tmp_path,monkeypatch):
    monkeypatch.setenv('PRIME_LOCAL_ADMISSION_MODE', 'measured')
    install_backend_receipt(monkeypatch,tmp_path,SETTINGS.ollama_base_url)
    raw=json.dumps({'schema':'abex.measured-compute.v1','normal_concurrency':1,
                    'minimum_available_mib':8192,'context_tokens':8192,'output_limit':512,
                    'runtime_version':'fixture-ollama',
                    'models':{'gemma3:1b':{'digest':'a'*64}}}).encode()
    path=tmp_path/'profile.json';path.write_bytes(raw)
    monkeypatch.setenv('PRIME_MEASURED_COMPUTE_PROFILE',str(path))
    monkeypatch.setenv('PRIME_MEASURED_COMPUTE_PROFILE_SHA256',hashlib.sha256(raw).hexdigest())
    cp.load_compute_profile.cache_clear()
    cp.runtime_compute_profile.cache_clear()
    def urlopen(url, timeout):
        assert timeout == 10
        if url.endswith('/api/version'):
            return io.BytesIO(b'{"version":"fixture-ollama"}')
        assert url.endswith('/api/tags')
        return io.BytesIO(json.dumps({'models':[{'name':'gemma3:1b','digest':'a'*64}]}).encode())
    monkeypatch.setattr(urllib.request, 'urlopen', urlopen)
    yield path
    cp.load_compute_profile.cache_clear()
    cp.runtime_compute_profile.cache_clear()


def test_changed_profile_fails_closed(measured):
    measured.write_text('{}')
    with pytest.raises(RuntimeError,match='integrity'):cp.load_compute_profile()


def test_malformed_requested_profile_blocks_measured_runtime(measured):
    measured.write_text('{}')
    assert cp.runtime_compute_profile() is None
    settings=SimpleNamespace(multi_specialist_workers=1,context_tokens=8192,
                             max_output_tokens=512,required_models=['gemma3:1b'])
    with pytest.raises(RuntimeError,match='requires a valid Compute Profile'):
        cp.validate_configuration(settings,SimpleNamespace(global_concurrency=1))
    assert cp.generation_options()=={}
    with pytest.raises(PermissionError,match='requires a valid Compute Profile'):
        cp.require_compute_capacity('gemma3:1b')


def test_missing_optional_profile_keeps_runtime_available_at_baseline(measured):
    measured.unlink()
    assert cp.runtime_compute_profile() is None


@pytest.mark.parametrize('missing', ['context_tokens','output_limit','models'])
def test_hash_pinned_incomplete_requested_profile_fails_closed(measured,monkeypatch,missing):
    profile=json.loads(measured.read_text())
    del profile[missing]
    raw=json.dumps(profile).encode()
    measured.write_bytes(raw)
    monkeypatch.setenv('PRIME_MEASURED_COMPUTE_PROFILE_SHA256',hashlib.sha256(raw).hexdigest())
    cp.load_compute_profile.cache_clear()
    cp.runtime_compute_profile.cache_clear()
    assert cp.runtime_compute_profile() is None
    settings=SimpleNamespace(multi_specialist_workers=1,context_tokens=8192,
                             max_output_tokens=512,required_models=['gemma3:1b'])
    with pytest.raises(RuntimeError,match='requires a valid Compute Profile'):
        cp.validate_configuration(settings,SimpleNamespace(global_concurrency=1))


def test_profile_cannot_expand_scheduler_or_models(measured):
    settings=SimpleNamespace(ollama_base_url='http://fixture',multi_specialist_workers=1,
                             context_tokens=8192,max_output_tokens=512,required_models=['gemma3:1b'])
    cp.validate_configuration(settings,SimpleNamespace(global_concurrency=1))
    with pytest.raises(RuntimeError,match='concurrency'):cp.validate_configuration(settings,SimpleNamespace(global_concurrency=2))
    with pytest.raises(PermissionError,match='Model'):cp.require_compute_capacity('unmeasured-model')


@pytest.mark.parametrize('mutation', [
    {'runtime_version': None},
    {'runtime_version': ''},
    {'models': {'gemma3:1b': {}}},
    {'models': {'gemma3:1b': {'digest': 'not-a-digest'}}},
])
def test_measured_profile_requires_pinned_runtime_and_model_bytes(measured, monkeypatch, mutation):
    profile = json.loads(measured.read_text())
    profile.update(mutation)
    raw = json.dumps(profile).encode()
    measured.write_bytes(raw)
    monkeypatch.setenv('PRIME_MEASURED_COMPUTE_PROFILE_SHA256', hashlib.sha256(raw).hexdigest())
    cp.load_compute_profile.cache_clear()
    cp.runtime_compute_profile.cache_clear()
    with pytest.raises(RuntimeError, match='runtime identity'):
        cp.load_compute_profile()
    assert cp.runtime_compute_profile() is None


def test_live_runtime_and_digest_mismatch_block_measured_start(measured, monkeypatch):
    settings=SimpleNamespace(ollama_base_url='http://fixture',multi_specialist_workers=1,
                             context_tokens=8192,max_output_tokens=512,
                             required_models=['gemma3:1b'])
    policy=SimpleNamespace(global_concurrency=1)
    cp.validate_configuration(settings,policy)
    def wrong_version(url, timeout):
        return io.BytesIO(b'{"version":"wrong"}' if url.endswith('/api/version') else
                          json.dumps({'models':[{'name':'gemma3:1b','digest':'a'*64}]}).encode())
    monkeypatch.setattr(urllib.request, 'urlopen', wrong_version)
    with pytest.raises(RuntimeError, match='runtime differs'):
        cp.validate_configuration(settings,policy)
    def wrong_digest(url, timeout):
        return io.BytesIO(b'{"version":"fixture-ollama"}' if url.endswith('/api/version') else
                          json.dumps({'models':[{'name':'gemma3:1b','digest':'b'*64}]}).encode())
    monkeypatch.setattr(urllib.request, 'urlopen', wrong_digest)
    with pytest.raises(RuntimeError, match='digest differs'):
        cp.validate_configuration(settings,policy)


def test_low_memory_holds_inference_without_authority_change(measured,monkeypatch):
    import psutil
    monkeypatch.setattr(psutil,'virtual_memory',lambda:SimpleNamespace(available=8192*1048576-1))
    with pytest.raises(PermissionError,match='reserve'):cp.require_compute_capacity('gemma3:1b')
    monkeypatch.setattr(psutil,'virtual_memory',lambda:SimpleNamespace(available=8192*1048576))
    cp.require_compute_capacity('gemma3:1b')


def test_bounded_work_respects_memory_reserve_without_model_requirement(measured,monkeypatch):
    import psutil
    monkeypatch.setattr(psutil,'virtual_memory',lambda:SimpleNamespace(available=8192*1048576))
    cp.require_bounded_work_capacity()
    with pytest.raises(PermissionError,match='Model'):
        cp.require_compute_capacity('unmeasured-model')
    monkeypatch.setattr(psutil,'virtual_memory',lambda:SimpleNamespace(available=8192*1048576-1))
    with pytest.raises(PermissionError,match='reserve'):
        cp.require_bounded_work_capacity()
