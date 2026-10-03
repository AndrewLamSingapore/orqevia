"""Optional measured machine envelope, independent of Registry and TAP."""
from functools import lru_cache
import hashlib,json,logging,os
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
    if profile.get('runtime_version'):
        if (not isinstance(profile['runtime_version'],str) or
                any(not isinstance(details.get('digest'),str) or not details['digest']
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


def validate_configuration(settings,queue_policy):
    profile=runtime_compute_profile()
    if not profile:return
    if queue_policy.global_concurrency>profile['normal_concurrency']:
        raise RuntimeError('Queue concurrency exceeds measured envelope')
    if settings.multi_specialist_workers>profile['normal_concurrency']:
        raise RuntimeError('Specialist concurrency exceeds measured envelope')
    if settings.context_tokens>profile['context_tokens'] or settings.max_output_tokens>profile['output_limit']:
        raise RuntimeError('Configured inference context/output exceeds measured envelope')
    if not set(settings.required_models).issubset(profile['models']):
        raise RuntimeError('Configured model is outside measured envelope')
    if profile.get('runtime_version'):
        import urllib.request
        with urllib.request.urlopen(settings.ollama_base_url+'/api/version',timeout=10) as r:
            if json.load(r).get('version')!=profile['runtime_version']:
                raise RuntimeError('Model runtime differs from measured envelope')
        with urllib.request.urlopen(settings.ollama_base_url+'/api/tags',timeout=10) as r:
            installed={m['name']:m['digest'] for m in json.load(r)['models']}
        if any(installed.get(name)!=details['digest'] for name,details in profile['models'].items()):
            raise RuntimeError('Model digest differs from measured envelope')


def generation_options():
    profile=runtime_compute_profile()
    return dict(profile.get('generation_options',{})) if profile else {}


def require_compute_capacity(model):
    profile=runtime_compute_profile()
    if not profile:return
    if model not in profile['models']:
        raise PermissionError('Model is outside measured Compute Profile')
    import psutil
    if psutil.virtual_memory().available < profile['minimum_available_mib']*1048576:
        raise PermissionError('Measured Compute Profile memory reserve reached; local inference held')
