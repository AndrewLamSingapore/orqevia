"""Original-domain review of one distinct zero-model A19 initialization event.

The report's owned definition/input-bounds oracle is necessary, not sufficient.
The reused fixed event adapter additionally joins its original authenticated
Objective, artifact bytes/metadata and durable action span to the same runtime.
No signature, deployment, health or L7 authority is supplied here.
"""
from .agent_cert_initialization import CASE, ORACLE_ID
from .agent_cert_identity_review import (
    IdentityReviewError, _INITIALIZATION_ADAPTER, _validate_event_execution,
)


SCHEMA = 'prime.agent-cert-initialization-review.v1'


class InitializationReviewError(ValueError):
    """Fixed public-safe event failure, without retained content disclosure."""


def validate_initialization_execution(execution, *, source_revision, runtime_image_id,
                                      registry_sha256, now):
    """Validate only the dedicated source-owned baseline:initialization event."""
    try:
        return _validate_event_execution(execution, source_revision=source_revision,
            runtime_image_id=runtime_image_id, registry_sha256=registry_sha256,
            now=now, _adapter=_INITIALIZATION_ADAPTER)
    except IdentityReviewError as exc:
        raise InitializationReviewError(str(exc)) from None
