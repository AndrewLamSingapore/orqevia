"""Optional measured machine envelope, independent of Registry and TAP."""
from functools import lru_cache
import hashlib,json,logging,os,re
from pathlib import Path


@lru_cache(maxsize=1)
def load_compute_profile():
    filename=os.getenv('PRIME_MEASURED_COMPUTE_PROFILE','').strip()
    if not filename:return None
    expected=os.getenv('PRIME_MEASURED_COMPUTE_PROFILE_SHA256','').lower()
    raw=Path(filename).read_bytes()
    if not expected or hashlib.sha256(raw).hexdigest()!=expected:
        raise RuntimeError('Measured Compute Profile integrity mismatch')
    profile=json.loads(raw)
    if not isinstance(profile,dict) or profile.get('schema')!='abex.measured-compute.v1':
        raise RuntimeError('Unsupported measured Compute Profile schema')
    bounds=('normal_concurrency','minimum_available_mib','context_tokens','output_limit')
    if any(type(profile.get(key)) is not int or profile[key]<1 for key in bounds):
        raise RuntimeError('Invalid measured Compute Profile bounds')
    models=profile.get('models')
    if (not isinstance(models,dict) or not models or
            any(not isinstance(name,str) or not name or not isinstance(details,dict)
                for name,details in models.items())):
        raise RuntimeError('Invalid measured Compute Profile models')
    if not isinstance(profile.get('generation_options',{}),dict):
        raise RuntimeError('Invalid measured Compute Profile generation options')
    if (not isinstance(profile.get('runtime_version'),str) or
            not profile['runtime_version'].strip() or
            any(not isinstance(details.get('digest'),str) or
                re.fullmatch(r'[0-9a-fA-F]{64}', details['digest']) is None
                for details in models.values())):
        raise RuntimeError('Invalid measured Compute Profile runtime identity')
    return profile


@lru_cache(maxsize=1)
def runtime_compute_profile():
    """Treat a malformed optional envelope as absent, retaining baseline N=1.

    The strict loader remains available to diagnostics/tests. Runtime callers
    must not make PRIME unavailable because an optional profile is malformed.
    """
    try:
        return load_compute_profile()
    except (OSError, RuntimeError, ValueError, TypeError, KeyError):
        logging.getLogger(__name__).warning(
            'Invalid measured Compute Profile; using baseline inference policy'
        )
        return None


def verify_runtime_identity(profile, endpoint, *, timeout=10):
    """Bind a measured admission to the live Ollama version and model bytes."""
    import urllib.request
    try:
        with urllib.request.urlopen(endpoint.rstrip('/')+'/api/version',timeout=timeout) as r:
            version=json.load(r)['version']
        with urllib.request.urlopen(endpoint.rstrip('/')+'/api/tags',timeout=timeout) as r:
            installed={m['name']:m['digest'] for m in json.load(r)['models']}
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise RuntimeError('Model runtime identity unavailable') from exc
    if version!=profile['runtime_version']:
        raise RuntimeError('Model runtime differs from measured envelope')
    if any(installed.get(name)!=details['digest'] for name,details in profile['models'].items()):
        raise RuntimeError('Model digest differs from measured envelope')


def validate_configuration(settings,queue_policy):
    from .backend_admission import admission_mode
    mode=admission_mode()
    profile=runtime_compute_profile()
    if mode=='measured' and not profile:
        raise RuntimeError('Measured local inference admission requires a valid Compute Profile')
    if not profile:return
    if queue_policy.global_concurrency>profile['normal_concurrency']:
        raise RuntimeError('Queue concurrency exceeds measured envelope')
    if settings.multi_specialist_workers>profile['normal_concurrency']:
        raise RuntimeError('Specialist concurrency exceeds measured envelope')
    if settings.context_tokens>profile['context_tokens'] or settings.max_output_tokens>profile['output_limit']:
        raise RuntimeError('Configured inference context/output exceeds measured envelope')
    if not set(settings.required_models).issubset(profile['models']):
        raise RuntimeError('Configured model is outside measured envelope')
    verify_runtime_identity(profile,settings.ollama_base_url)


def generation_options():
    profile=runtime_compute_profile()
    return dict(profile.get('generation_options',{})) if profile else {}


def require_compute_capacity(model, endpoint=None):
    from .backend_admission import admission_mode
    mode=admission_mode()
    profile=runtime_compute_profile()
    if mode=='golden_n1':return
    if not profile:
        raise PermissionError('Measured local inference admission requires a valid Compute Profile')
    if profile and model not in profile['models']:
        raise PermissionError('Model is outside measured Compute Profile')
    # Optional performance profiles cannot waive the mandatory backend scope.
    from .backend_admission import observation, RESERVE_MIB
    from .settings import SETTINGS
    sample=observation(endpoint or SETTINGS.ollama_base_url)
    if sample['available_mib'] < RESERVE_MIB:
        raise PermissionError('Backend memory reserve reached; local inference held')
    if profile:
        try:require_bounded_work_capacity()
        except PermissionError:
            raise PermissionError('Measured Compute Profile memory reserve reached; local inference held') from None


def require_bounded_work_capacity():
    """Admit bounded local work by RAM reserve, independent of model slots.

    The WebAssembly executor has its own fuel, memory, and concurrency limits;
    a measured model's presence is irrelevant to that non-inference work.
    """
    profile=runtime_compute_profile()
    if not profile:return
    import psutil
    if psutil.virtual_memory().available < profile['minimum_available_mib']*1048576:
        raise PermissionError('Measured Compute Profile memory reserve reached; bounded work held')
