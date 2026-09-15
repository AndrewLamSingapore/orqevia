"""Deterministic model selection. A route is never execution authority."""
from dataclasses import dataclass
from enum import IntEnum
import re


class Tier(IntEnum):
    NANO = 0
    MINI = 1
    FLAGSHIP = 2


@dataclass(frozen=True)
class Backend:
    name: str
    model: str
    tier: Tier
    location: str
    available: bool = True


@dataclass(frozen=True)
class Route:
    state: str
    reason: str
    backend: Backend | None = None
    grants_execution_authority: bool = False


CLASSIFICATIONS = frozenset({'LOCAL_ONLY','CLOUD_PERMITTED','SENSITIVE','RESTRICTED'})
SECRET = re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:api[_-]?key|password|secret|access[_-]?token)\s*[:=]\s*\S+|\bBearer\s+\S+', re.I)


def classify_for_cloud(classification: str, text: str) -> bool:
    """Explicit metadata is necessary but insufficient for external disclosure."""
    return classification == 'CLOUD_PERMITTED' and not SECRET.search(text)


def required_tier(objective: str, context: str = '') -> Tier:
    """Conservative deterministic triage; availability never lowers requirement."""
    text=objective.lower()
    if len(context)>16000 or any(term in text for term in ('formal proof','threat model','cryptographic protocol','novel research')):
        return Tier.FLAGSHIP
    if len(context)>4000 or any(term in text for term in ('multi-file','refactor','concurrency','architecture','debug')):
        return Tier.MINI
    return Tier.NANO


def select_route(backends: tuple[Backend,...], *, minimum_tier: Tier,
                 classification: str, text: str, local_saturated: bool = False,
                 provider_authorized: bool = False, disclosure_authorized: bool = False,
                 cost_authorized: bool = False) -> Route:
    if classification not in CLASSIFICATIONS:
        return Route('DENIED','Unknown data classification')
    if not isinstance(minimum_tier,Tier):
        return Route('DENIED','Unknown model tier')
    eligible = sorted((b for b in backends if b.available and b.tier >= minimum_tier),
                      key=lambda b:(b.tier,b.location != 'local',b.name))
    local = [b for b in eligible if b.location == 'local']
    cloud_allowed = (provider_authorized and disclosure_authorized and cost_authorized
                     and classify_for_cloud(classification,text))
    if local and not local_saturated:
        return Route('READY','Lowest sufficient available local tier',local[0])
    if cloud_allowed:
        cloud = [b for b in eligible if b.location == 'cloud']
        if cloud:
            return Route('READY','Governed cloud candidate; independent TAP lease still required',cloud[0])
    if local:
        return Route('QUEUED','Local capacity is occupied; preserve measured slot limit',local[0])
    return Route('UNAVAILABLE','No authorized available backend satisfies the required tier')


def select_direct_route(backends: tuple[Backend,...], *, minimum_tier: Tier,
                        classification: str,text: str,local_saturated: bool=False) -> Route:
    """Select available compute; data residency/secret handling are not action approvals."""
    if classification not in CLASSIFICATIONS or not isinstance(minimum_tier,Tier):
        return Route('UNAVAILABLE','Invalid routing metadata')
    eligible=sorted((b for b in backends if b.available and b.tier>=minimum_tier),
                    key=lambda b:(b.tier,b.location!='local',b.name))
    local=[b for b in eligible if b.location=='local']
    if local and not local_saturated:return Route('READY','Lowest sufficient local tier',local[0])
    cloud=[b for b in eligible if b.location=='cloud' and classify_for_cloud(classification,text)]
    if cloud:return Route('READY','Available cloud tier within data-residency constraints',cloud[0])
    if local:return Route('QUEUED','Local slots occupied',local[0])
    return Route('UNAVAILABLE','No available backend satisfies tier and data residency')
