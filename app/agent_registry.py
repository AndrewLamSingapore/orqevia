"""Owned ORQEVIA capabilities; identity and collaboration grant no tool authority."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .product_identity import CORE_DISPLAY_NAME

REGISTRY_PATH = Path(__file__).resolve().parent.parent / 'config/agent_registry.json'
# Historical identity aliases are data readers, never delegation permissions.
MIGRATION_PATH = REGISTRY_PATH.with_name('agent_registry_migration.json')
_migration_bytes = MIGRATION_PATH.read_bytes()
_expected_migration = os.getenv('ORQEVIA_AGENT_MIGRATION_SHA256', '').lower()
if _expected_migration and hashlib.sha256(_migration_bytes).hexdigest() != _expected_migration:
    raise RuntimeError('Registry identity migration hash mismatch')
MIGRATION = json.loads(_migration_bytes)
LEGACY_IDS = MIGRATION['legacy_ids']
SUCCESSORS = MIGRATION['compatibility']
AGENT_ALIASES = {
    'strategy': 'a01', 'planner': 'a02', 'planning': 'a02',
    'roadmap': 'a03', 'decision': 'a04', 'portfolio': 'a05', 'research': 'a06',
    'evidence': 'a07', 'comparison': 'a08', 'knowledge': 'a09', 'data': 'a10',
    'metrics': 'a11', 'analyst': 'a12', 'analysis': 'a12', 'forecast': 'a13',
    'data-quality': 'a14', 'engineering': 'a15', 'architecture': 'a16',
    'coding': 'a17', 'implementation': 'a17', 'test': 'a18', 'reliability': 'a19',
    'economic': 'a20', 'cost': 'a21', 'value': 'a22', 'resource': 'a23',
    'commercial': 'a24', 'quality': 'a25', 'critic': 'a26', 'review': 'a26',
    'verification': 'a27', 'risk': 'a28', 'release': 'a29',
}


class RegistryError(RuntimeError):
    pass


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RegistryError('duplicate capability inventory field')
        result[key] = value
    return result


def normalize_registry(source: dict[str, Any]) -> dict[str, Any]:
    """Validate supplied source without a cached or historical reporting tree."""
    data = deepcopy(source)
    if data.get('schema_version') != '3.0' or data.get('registry_version') != '2.0.0':
        raise RegistryError('unsupported capability inventory schema')
    if 'leads' in data or data.get('coordination', {}).get('delegation_transfers_authority') is not False:
        raise RegistryError('capability coordination cannot inherit authority')
    coordinator = data.get('orchestrator', {}).get('id')
    if coordinator != 'orqevia':
        raise RegistryError('ORQEVIA coordination identity is required')
    agents = data.get('agents')
    if not isinstance(agents, list) or not agents:
        raise RegistryError('capability inventory cannot be empty')
    required = {'agent_id', 'immutable_id', 'name', 'role', 'purpose', 'responsibilities',
                'non_responsibilities', 'input_contract', 'output_contract',
                'capability_requirements', 'tool_eligibility', 'model_tier_eligibility',
                'compute_requirements', 'tap_relationship', 'failure_fallback',
                'observability', 'version', 'lifecycle_status', 'division'}
    identities = []
    owners = {}
    for agent in agents:
        if not isinstance(agent, dict) or not required.issubset(agent):
            raise RegistryError('capability definition is incomplete')
        identity = agent['agent_id']
        if not isinstance(identity, str) or not identity or agent['immutable_id'] != identity:
            raise RegistryError('capability identity is invalid')
        if any(key in agent for key in ('reports_to', 'can_delegate', 'allowed_delegation_targets', 'escalation_relationships')):
            raise RegistryError('reporting hierarchy is retired')
        if agent.get('authority') not in {'advisory', 'restricted'}:
            raise RegistryError('unsupported capability authority')
        if agent['authority'] == 'restricted' and agent.get('human_approval') != 'required_for_execution':
            raise RegistryError('restricted execution requires scoped approval')
        if agent.get('status') != 'registered' or agent.get('model') != 'unassigned':
            raise RegistryError('model activation requires separately verified configuration')
        if agent['tap_relationship'].get('delegation_transfers_authority') is not False:
            raise RegistryError('capability selection cannot transfer authority')
        for field in ('tool_eligibility', 'model_tier_eligibility', 'capability_requirements'):
            values = agent[field]
            if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values) or len(values) != len(set(values)):
                raise RegistryError('invalid capability eligibility contract')
        responsibilities = agent['responsibilities']
        if not isinstance(responsibilities, list) or not responsibilities:
            raise RegistryError('owned responsibilities are required')
        responsibility_ids = [item['id'] for item in responsibilities]
        if set(responsibility_ids) != set(agent['capability_requirements']) or len(responsibility_ids) != len(set(responsibility_ids)):
            raise RegistryError('capability ownership does not match responsibilities')
        for capability in responsibility_ids:
            if capability in owners:
                raise RegistryError('capability ownership must be unambiguous')
            owners[capability] = identity
        agent['id'] = identity
        identities.append(identity)
    if len(identities) != len(set(identities)) or coordinator in identities:
        raise RegistryError('capability identities must be unique')
    coverage = data.get('responsibility_coverage', [])
    if (len(coverage) != len(owners) or {row['responsibility_id'] for row in coverage} != set(owners)
            or any(owners[row['responsibility_id']] != row['owner'] for row in coverage)):
        raise RegistryError('responsibility coverage does not match owned capabilities')
    if any(value['canonical_id'] not in identities for value in data.get('named_operating_roles', {}).values()):
        raise RegistryError('named operating role is inconsistent')
    return data


@lru_cache(maxsize=1)
def load_agent_registry() -> dict[str, Any]:
    raw = REGISTRY_PATH.read_bytes()
    expected = os.getenv('ORQEVIA_AGENT_REGISTRY_SHA256', '').lower()
    if expected and hashlib.sha256(raw).hexdigest() != expected:
        raise RegistryError('capability inventory hash mismatch')
    return normalize_registry(json.loads(raw, object_pairs_hook=_unique_object))


def _index() -> dict[str, dict[str, Any]]:
    return {agent['id']: agent for agent in load_agent_registry()['agents']}


def orchestrator_id() -> str:
    return str(load_agent_registry()['orchestrator']['id'])


def registered_agent_ids(*, include_orchestrator: bool = True) -> set[str]:
    ids = set(_index())
    if include_orchestrator:
        ids.add(orchestrator_id())
    return ids


def canonical_agent_id(value: str) -> str:
    """Resolve owned identities, including historical record aliases."""
    raw = (value or '').strip()
    if raw in registered_agent_ids():
        return raw
    # This retired spelling reads saved identities; it cannot create a separate
    # coordinator or grant execution permission to a task or tool.
    if raw.lower() == 'prime':
        return orchestrator_id()
    # Case distinguishes old uppercase identities from current lowercase IDs.
    alias = LEGACY_IDS.get(raw) or AGENT_ALIASES.get(raw.lower())
    if raw.startswith('lead_'):
        alias = AGENT_ALIASES.get(raw.removeprefix('lead_'))
    alias = SUCCESSORS.get(alias or raw, alias)
    if alias and alias in registered_agent_ids():
        return alias
    raise RegistryError(f'unregistered agent identity: {raw}')


def agent_record(agent_id: str) -> dict[str, Any]:
    identity = canonical_agent_id(agent_id)
    return deepcopy(load_agent_registry()['orchestrator'] if identity == orchestrator_id() else _index()[identity])


def responsibility_owner(capability: str) -> str:
    owners = [agent['id'] for agent in _index().values() if capability in agent['capability_requirements']]
    if len(owners) != 1:
        raise RegistryError(f'unknown or ambiguous responsibility: {capability}')
    return owners[0]


def domain_lead(division: str) -> str:
    """Historical caller adapter: resolve a domain capability, not a supervisor."""
    wanted = (division or '').strip().lower()
    alias = AGENT_ALIASES.get(wanted)
    if alias:
        return canonical_agent_id(alias)
    raise RegistryError(f'unknown capability domain: {division}')


def may_delegate(source: str, target: str, *, depth: int = 1) -> bool:
    """Distinct owned capabilities may hand off without role escalation."""
    if not isinstance(depth, int) or isinstance(depth, bool) or depth < 1:
        return False
    try:
        src, dst = canonical_agent_id(source), canonical_agent_id(target)
    except RegistryError:
        return False
    return src != dst and dst != orchestrator_id()


def may_consult(source: str, target: str) -> bool:
    try:
        return canonical_agent_id(source) != canonical_agent_id(target)
    except RegistryError:
        return False


def requires_owner_approval(*, consequential: bool) -> bool:
    """Collaboration does not authorize consequential external actions."""
    return bool(consequential)


def public_relationships() -> list[dict[str, str]]:
    # Actual task handoffs are execution records, not a permanent reporting tree.
    return []


def public_agent_registry() -> dict[str, Any]:
    data = load_agent_registry()
    allowed = set(data['publication_policy']['allowed_fields']) | {'id'}
    allowed -= set(data['publication_policy']['forbidden_fields'])
    return {
        'schema_version': data['schema_version'], 'last_updated': data['last_updated'],
        'registry_id': data['registry_id'],
        'orchestrator': {key: value for key, value in {**data['orchestrator'], 'name': CORE_DISPLAY_NAME}.items()
                         if key in {'id', 'name', 'role', 'public_description'}},
        'agents': [{key: value for key, value in agent.items() if key in allowed} for agent in data['agents']],
        'relationships': public_relationships(),
        'relationship_policy': {'execution_model': 'DIRECT_CAPABILITY_HANDOFF',
                                'consequential_actions_require_owner_approval': True,
                                'delegation_transfers_authority': False,
                                'runtime_activation_verified': False, 'unknown_agent_policy': 'deny'},
        'disclosure': 'Declared capabilities are not competence proof. Private prompts, credentials and endpoints are excluded.',
    }


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

    def assignment_evidence(self, agent_id, owner, *, now):
        """Observe role evidence without authorizing this fixed native adapter.

        The Factory executes server-owned retrieval/parser functions, not an
        agent-selected model or executable. Source scope, tested skill artifacts
        and fixed tool handlers authorize that bounded path independently.
        """
        from .activity_pockets.contracts import QualificationEvidence
        manifest = self.manifest(agent_id, owner)
        capability = "responsibility." + agent_id
        projection = self.qualifications.project(agent_id, capability, now=now)
        projection = {**projection, "execution_basis": "TESTED_NATIVE_SCOPED_ADAPTER",
                      "role_evidence_grants_execution_permission": False,
                      "agent_model_executed": False}
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
