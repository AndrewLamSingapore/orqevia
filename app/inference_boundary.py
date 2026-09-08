"""Trusted worker call scope; no HTTP/client-supplied execution capability."""
from contextlib import contextmanager
from contextvars import ContextVar


class InferenceBoundaryError(RuntimeError):
    pass


_active_job = ContextVar("harness_active_job", default=None)


def deny_legacy_inference():
    raise InferenceBoundaryError("Inference requires a consumed signed Harness job")


@contextmanager
def worker_call(job):
    # Used only after durable execution-time PEP consumption, in the same thread.
    if _active_job.get() is not None:
        raise InferenceBoundaryError("nested inference is prohibited")
    token = _active_job.set(job)
    try:
        yield
    finally:
        _active_job.reset(token)


def require_worker_call(job):
    if _active_job.get() is not job:
        deny_legacy_inference()
    # One model call per consumed authorization, including within this scope.
    _active_job.set(None)
