"""Authenticate and connect bounded agent probes to the existing live dispatcher.

This is an in-process adapter, not a new service or an authority grant. The
caller supplies an Owner bearer credential to the existing authentication
boundary. Queue completion is observed, never turned into L7 certification.
"""
from __future__ import annotations

from .agent_execution_probe import observe_baseline_execution


def observe_live_baseline(agent_id: str, capability_id: str, *, authorization: str,
                          timeout_seconds: float = 30) -> dict:
    """Run one local-only registered-agent canary through existing dispatch.

    Must execute in the PRIME service process (or an equally configured
    authenticated runtime) so it shares the governed queue. The credential is
    never included in the returned evidence or passed to an agent prompt.
    """
    from .client_auth import authenticate_owner
    from .agent_dispatch_api import AgentRequest, dispatch_request
    from .compute_queue_api import queue

    authenticate_owner(authorization)

    def dispatch(request: dict) -> dict:
        return dispatch_request(AgentRequest(**request), authorization)

    return observe_baseline_execution(agent_id, capability_id, dispatch=dispatch,
                                      get_job=queue.get, timeout_seconds=timeout_seconds)
