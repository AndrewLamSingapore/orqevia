"""Canonical ORQEVIA agent registry and deny-by-default public projection."""
from __future__ import annotations

import json
import hashlib
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from .product_identity import CORE_DISPLAY_NAME

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "config" / "agent_registry.json"
MAX_DELEGATION_DEPTH = 2

# Backward-compatible role aliases are resolved to canonical registered agent IDs
# before work reaches the shared compute fabric. Unknown agent identities fail closed.
MIGRATION_PATH = REGISTRY_PATH.with_name("agent_registry_migration.json")
_migration_bytes = MIGRATION_PATH.read_bytes()
_expected_migration = os.getenv('PRIME_AGENT_MIGRATION_SHA256','').lower()
if _expected_migration and hashlib.sha256(_migration_bytes).hexdigest()!=_expected_migration:
    raise RuntimeError('Frozen Registry migration hash mismatch')
MIGRATION = json.loads(_migration_bytes)
LEGACY_IDS = MIGRATION['legacy_ids']
SUCCESSORS = MIGRATION['compatibility']
AGENT_ALIASES = {
    "prime": "prime", "strategy": "a01", "planner": "a02", "planning": "a02",
    "roadmap": "a03", "decision": "a04", "portfolio": "a05", "research": "a06",
    "evidence": "a07", "comparison": "a08", "knowledge": "a09", "data": "a10",
    "metrics": "a11", "analyst": "a12", "analysis": "a12", "forecast": "a13",
    "data-quality": "a14", "engineering": "a15", "architecture": "a16",
    "coding": "a17", "implementation": "a17", "test": "a18", "reliability": "a19",
    "economic": "a20", "cost": "a21", "value": "a22", "resource": "a23",
    "commercial": "a24", "quality": "a25", "critic": "a26", "review": "a26",
    "verification": "a27", "risk": "a28", "release": "a29",
}


class RegistryError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def load_agent_registry() -> dict[str, Any]:
    raw=REGISTRY_PATH.read_bytes()
    expected=os.getenv('PRIME_AGENT_REGISTRY_SHA256','').lower()
    if expected and hashlib.sha256(raw).hexdigest()!=expected:
        raise RegistryError('Frozen Registry hash mismatch')
    data = json.loads(raw)
    if data.get("schema_version") != "2.0" or data.get('registry_version') != '1.0.0':
        raise RegistryError("unsupported registry schema")
    leads = data.get("leads", [])
    aliases = {lead["id"]: lead["agent_id"] for lead in leads}
    if len(aliases) != 6 or len(set(aliases.values())) != 6:
        raise RegistryError("six unique lead aliases required")
    domains = {lead["agent_id"]: lead["domain"] for lead in data["leads"]}
    agents = data.get("agents", [])
    agent_statuses = {agent.get("agent_id"): agent.get("status") for agent in agents}
    if any(lead.get("status") != agent_statuses.get(lead.get("agent_id")) for lead in leads):
        raise RegistryError("lead projection status must match its canonical agent")
    for agent in agents:
        agent["id"] = agent["agent_id"]
        agent["reports_to"] = aliases.get(agent["reports_to"], agent["reports_to"])
        agent["division"] = domains.get(agent["id"], domains.get(agent["reports_to"], "")).title()
        if agent.get("can_delegate") != (agent["id"] in domains):
            raise RegistryError("only leads may delegate")
        if agent.get("authority") not in {"advisory", "restricted"}:
            raise RegistryError("unsupported agent authority")
        if agent.get("authority") == "restricted" and agent.get("human_approval") != "required_for_execution":
            raise RegistryError("restricted execution requires approval")
        if agent.get("status") != "registered" or agent.get("model") != "unassigned":
            raise RegistryError("runtime activation requires separately verified configuration")
        required={'immutable_id','purpose','responsibilities','non_responsibilities','allowed_delegation_targets','escalation_relationships','input_contract','output_contract','capability_requirements','tool_eligibility','model_tier_eligibility','compute_requirements','tap_relationship','failure_fallback','observability','version','lifecycle_status'}
        if not required.issubset(agent) or agent['immutable_id']!=agent['agent_id']:
            raise RegistryError('agent contract or immutable identity missing')
        if agent['tap_relationship'].get('delegation_transfers_authority') is not False:
            raise RegistryError('delegation cannot transfer authority')
    if len(agents) != 21:
        raise RegistryError(f"agent registry must contain exactly 21 agents; found {len(agents)}")
    ids = [a.get("id") for a in agents]
    if len(ids) != len(set(ids)) or any(not x for x in ids):
        raise RegistryError("agent IDs must be present and unique")
    prime = data.get("orchestrator", {}).get("id")
    if not prime:
        raise RegistryError("orchestrator ID is required")
    if set(ids) != set(SUCCESSORS.values()) or prime in ids:
        raise RegistryError("canonical identity set is invalid")
    if not set(domains).issubset(ids):
        raise RegistryError("lead aliases must resolve to registered agents")
    if any(a["reports_to"] != prime for a in agents if a["id"] in domains):
        raise RegistryError("leads must report to PRIME")
    known = set(ids) | {prime}
    for agent in agents:
        if agent.get("reports_to") not in known:
            raise RegistryError(f"unknown parent for {agent.get('id')}")
        children={a['id'] for a in agents if a['reports_to']==agent['id']}
        if set(agent['allowed_delegation_targets'])!=children or set(agent['escalation_relationships'])!={agent['reports_to']}:
            raise RegistryError('delegation/escalation contract does not match hierarchy')
    responsibilities=[r['id'] for a in agents for r in a['responsibilities']]
    if len(responsibilities)!=29 or set(responsibilities)!={'responsibility.'+key for key in SUCCESSORS}:
        raise RegistryError('responsibility coverage must be complete and uniquely owned')
    for agent in agents:
        if set(agent['capability_requirements'])!={r['id'] for r in agent['responsibilities']}:
            raise RegistryError('capability ownership does not match responsibilities')
        if set(agent.get('excluded_capabilities',[])) != set(responsibilities)-set(agent['capability_requirements']):
            raise RegistryError('explicit responsibility boundaries do not match ownership')
        if any(SUCCESSORS[r['id'].split('.')[-1]]!=agent['id'] for r in agent['responsibilities']):
            raise RegistryError('responsibility migration destination mismatch')
    coverage=data.get('responsibility_coverage',[])
    if len(coverage)!=29 or {item['responsibility_id'] for item in coverage}!=set(responsibilities):
        raise RegistryError('coverage matrix is incomplete')
    if any(SUCCESSORS.get(item['historical_agent'])!=item['owner'] for item in coverage):
        raise RegistryError('coverage matrix destination mismatch')
    if {key:value['canonical_id'] for key,value in data.get('named_operating_roles',{}).items()}!={'A12 Builder':'a17','A13 Test Engineer':'a18'}:
        raise RegistryError('named engineering roles are inconsistent')
    parent = {a["id"]: a["reports_to"] for a in agents}
    for start in ids:
        seen, node = set(), start
        while node != prime:
            if node in seen:
                raise RegistryError(f"hierarchy cycle at {start}")
            seen.add(node)
            node = parent.get(node)
            if node is None:
                raise RegistryError(f"orphan agent {start}")
    return data


def _index() -> dict[str, dict[str, Any]]:
    data = load_agent_registry()
    return {a["id"]: a for a in data["agents"]}


def orchestrator_id() -> str:
    return str(load_agent_registry()["orchestrator"]["id"])


def registered_agent_ids(*, include_orchestrator: bool = True) -> set[str]:
    ids = set(_index())
    if include_orchestrator:
        ids.add(orchestrator_id())
    return ids


def canonical_agent_id(value: str) -> str:
    """Resolve a canonical agent ID; reject unknown or invented identities."""
    raw = (value or "").strip()
    if not raw:
        raise RegistryError("agent identity is required")
    if raw in registered_agent_ids():
        return raw
    # Case distinguishes retired A10 from the new canonical Data Lead a10.
    alias = LEGACY_IDS.get(raw) or AGENT_ALIASES.get(raw.lower())
    alias = alias or next((x["agent_id"] for x in load_agent_registry()["leads"] if x["id"] == raw), None)
    alias = SUCCESSORS.get(alias or raw, alias)
    if alias and alias in registered_agent_ids():
        return alias
    raise RegistryError(f"unregistered agent identity: {raw}")


def agent_record(agent_id: str) -> dict[str, Any]:
    canonical = canonical_agent_id(agent_id)
    if canonical == orchestrator_id():
        return dict(load_agent_registry()["orchestrator"])
    return dict(_index()[canonical])


class AgentLibrary:
    """Versioned artifact adapter over this registry, never a second agent registry.

    Qualifications are read through the existing independent evidence projector.
    Published artifacts are immutable, tenant-owned and explicitly pinned by pockets.
    """
    def __init__(self, store, qualifications):
        self.store, self.qualifications = store, qualifications

    def manifest(self, agent_id, owner):
        from .activity_pockets.contracts import AgentManifest
        if agent_id not in registered_agent_ids(include_orchestrator=False):
            raise RegistryError("canonical specialist required")
        row = agent_record(agent_id)
        return AgentManifest(owner=owner, agent_id=agent_id, version=row["version"],
            capabilities=tuple(row["capability_requirements"]), tool_ids=tuple(row["tool_eligibility"]),
            provenance=self.store.provenance("library", "config/agent_registry.json"))

    def qualified(self, agent_id, owner, *, now):
        from .activity_pockets.contracts import QualificationEvidence
        manifest = self.manifest(agent_id, owner)
        capability = "responsibility." + agent_id
        projection = self.qualifications.project(agent_id, capability, now=now)
        if (projection["level"] not in {"L2", "L3", "L4", "L5", "L6", "L7"}
                or projection["trust_state"] in {"UNPROVEN", "REVALIDATION-REQUIRED"}
                or not {"baseline", "role"} <= set(projection["current_dimensions"])):
            raise PermissionError("current independent baseline and role qualification required")
        return manifest, QualificationEvidence(owner=owner, agent_id=agent_id,
            capability_id=capability, projection=projection,
            provenance=self.store.provenance("library", "app/agent_certification.py"))

    def skill(self, db, owner, version):
        from .activity_pockets.contracts import SkillManifest
        row = db.execute("SELECT id FROM pocket_records WHERE kind='library_skill' AND owner=? "
                         "AND json_extract(body,'$.version')=?", (owner, version)).fetchone()
        if row is None:
            raise KeyError("pinned skill version unavailable")
        return SkillManifest.model_validate(self.store.get(db, "library_skill", row[0], owner))

    def publish(self, db, skill):
        from .activity_pockets.store import digest
        try:
            previous = self.skill(db, skill.owner, skill.version)
        except KeyError:
            return self.store.put(db, "library_skill", skill)
        if (digest(previous.artifact) != digest(skill.artifact)
                or previous.tool_ids != skill.tool_ids or previous.agent_ids != skill.agent_ids):
            raise ValueError("published skill versions are immutable")
        return previous.model_dump(mode="json")

    def ensure_builtin(self, db, owner):
        from .activity_pockets.contracts import SkillManifest, ExtractionConfig
        from .academy import PersistentAcademy
        artifact = ExtractionConfig(title_fields=("title",), price_fields=("price",))
        from .activity_pockets.store import digest
        academy = PersistentAcademy(self.store)
        admission = db.execute("SELECT id FROM pocket_records WHERE kind='skill_validation' AND owner=? "
            "AND json_extract(body,'$.proposal_id')='bundled:1.0.0' AND json_extract(body,'$.candidate_sha256')=? "
            "AND json_extract(body,'$.provenance.source_revision')=? AND json_extract(body,'$.suite_sha256')=?",
            (owner, digest(artifact), self.store.revision, academy.suite_digest())).fetchone()
        if admission is None:
            PersistentAcademy(self.store).validate_builtin(db, owner, artifact)
        else:
            evidence = self.store.get(db, "skill_validation", admission[0], owner)
            if (not evidence["passed"] or evidence["candidate_sha256"] != digest(artifact)
                    or evidence["provenance"]["source_revision"] != self.store.revision):
                raise PermissionError("bundled skill requires current scoped admission")
        return self.publish(db, SkillManifest(owner=owner, version="1.0.0", agent_ids=("a07", "a14"),
            tool_ids=("provided_context.read",), artifact=artifact,
            permissions=("provided_context.read",),
            provenance=self.store.provenance("library", "skills/web.structured-extraction/SKILL.md")))


def responsibility_owner(capability: str) -> str:
    """Unique deterministic responsibility routing; never infer execution authority."""
    owners=[a['id'] for a in _index().values() if capability in a['capability_requirements']]
    if len(owners)!=1:raise RegistryError(f'unknown or ambiguous responsibility: {capability}')
    return owners[0]


def domain_lead(division: str) -> str:
    wanted = (division or "").strip().lower()
    for agent in _index().values():
        if agent.get("can_delegate") is True and str(agent.get("division", "")).lower() == wanted:
            return agent["id"]
    raise RegistryError(f"no registered lead for division: {division}")


def may_delegate(source: str, target: str, *, depth: int = 1) -> bool:
    """Only a direct orchestrator->lead or lead->child delegation is allowed."""
    if depth < 1 or depth > MAX_DELEGATION_DEPTH:
        return False
    try:
        src_id, dst_id = canonical_agent_id(source), canonical_agent_id(target)
    except RegistryError:
        return False
    agents = _index()
    dst = agents.get(dst_id)
    if not dst:
        return False
    prime = orchestrator_id()
    if src_id == prime:
        if depth != 1:
            return False
        return dst.get("can_delegate") is True and dst.get("reports_to") == prime
    src = agents.get(src_id)
    return bool(src and src.get("can_delegate") is True and dst.get("reports_to") == src_id)


def may_consult(source: str, target: str) -> bool:
    """Consultation is bounded to an agent's own lead or lead-to-lead peer review."""
    try:
        src_id, dst_id = canonical_agent_id(source), canonical_agent_id(target)
    except RegistryError:
        return False
    if src_id == dst_id or orchestrator_id() in {src_id, dst_id}:
        return False
    agents = _index()
    src, dst = agents.get(src_id), agents.get(dst_id)
    if not src or not dst:
        return False
    if src.get("reports_to") == dst_id and dst.get("can_delegate") is True:
        return True
    if src.get("can_delegate") is True and dst.get("can_delegate") is True:
        return True
    return False


def requires_owner_approval(*, consequential: bool) -> bool:
    """No agent relationship can bypass owner approval for consequential action."""
    return bool(consequential)


def public_relationships() -> list[dict[str, str]]:
    data = load_agent_registry()
    agents = data["agents"]
    prime = data["orchestrator"]["id"]
    edges: list[dict[str, str]] = []
    for agent in agents:
        edges.append({"source": agent["reports_to"], "target": agent["id"], "type": "reports_to"})
        if may_delegate(prime, agent["id"]):
            edges.append({"source": prime, "target": agent["id"], "type": "may_delegate"})
    for src in agents:
        for dst in agents:
            if may_delegate(src["id"], dst["id"]):
                edges.append({"source": src["id"], "target": dst["id"], "type": "may_delegate"})
            elif may_consult(src["id"], dst["id"]):
                edges.append({"source": src["id"], "target": dst["id"], "type": "may_consult"})
    return edges


def public_agent_registry() -> dict[str, Any]:
    data = load_agent_registry()
    allowed = set(data["publication_policy"]["allowed_fields"])
    # Explicit compatibility fields for the existing public network consumer.
    allowed |= {"id", "division", "reports_to"}
    allowed -= set(data["publication_policy"]["forbidden_fields"])
    return {
        "schema_version": data["schema_version"],
        "last_updated": data["last_updated"],
        "registry_id": data["registry_id"],
        "orchestrator": {
            "id": data["orchestrator"]["id"],
            "name": CORE_DISPLAY_NAME,
            "role": data["orchestrator"]["role"],
            "public_description": data["orchestrator"]["public_description"],
        },
        "agents": [{k: v for k, v in agent.items() if k in allowed} for agent in data["agents"]],
        "relationships": public_relationships(),
        "relationship_policy": {
            "max_delegation_depth": MAX_DELEGATION_DEPTH,
            "consequential_actions_require_owner_approval": True,
            "network_is_enforced": True,
            "runtime_activation_verified": False,
            "unknown_agent_policy": "deny",
        },
        "disclosure": "Public-safe projection. Operational prompts, credentials, endpoints and internal instructions are excluded by policy."
    }
