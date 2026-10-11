"""Read-only, bounded preparation of missing certification cases.

This module makes no runtime calls, evidence records, grades, or attestations.
Model challenges require supplied discriminating context. Deterministic identity
and initialization events use only their fixed current owned source inputs.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Mapping

from .agent_cert_cases import challenge
from .agent_certification import AgentCertificationRegistry


CaseKey = tuple[str, str, str]


def plan_missing_cases(
    registry: AgentCertificationRegistry,
    *,
    max_jobs: int,
    case_contexts: Mapping[CaseKey, str] | None = None,
    now: datetime | None = None,
) -> list[dict]:
    """Select missing cases in dependency waves, fairly across agents.

    A planned case has no result. A dispatch request is prepared only when its
    exact agent/capability/case has a supplied, nonblank context, except fixed
    identity and initialization events whose inputs are the actual Registry and
    runtime. Preparation never dispatches or supplies certification evidence.
    """
    if not isinstance(max_jobs, int) or isinstance(max_jobs, bool) or max_jobs < 1:
        raise ValueError("max_jobs must be a positive integer")
    contexts = case_contexts or {}
    planned: list[dict] = []
    for wave_number, wave in enumerate(registry.pending_waves(now=now), start=1):
        by_agent: dict[str, deque[dict]] = {}
        for item in wave:
            by_agent.setdefault(item["agent_id"], deque()).append(item)
        while by_agent and len(planned) < max_jobs:
            for agent_id in tuple(by_agent):
                item = by_agent[agent_id].popleft()
                if not by_agent[agent_id]:
                    del by_agent[agent_id]
                key = (item["agent_id"], item["capability_id"], item["case"])
                context = contexts.get(key)
                fixed_event = item['case'] in {'baseline:identity', 'baseline:initialization'}
                if fixed_event and context:
                    raise ValueError('Fixed identity and initialization events reject supplied context')
                prepared = challenge(item["case"], agent_id=item["agent_id"],
                                     capability_id=item["capability_id"],
                                     context=None if fixed_event else context) if fixed_event or (
                                         isinstance(context, str) and context.strip()) else None
                planned.append({**item, "wave": wave_number,
                                "state": "READY_FOR_DISPATCH" if prepared else "NEEDS_CASE_CONTEXT",
                                "challenge": prepared})
                if len(planned) == max_jobs:
                    break
    return planned
