"""Explicit read-only adapters for compatible legacy definitions; no retired services."""

from .contracts import AgentManifest, SkillManifest, GuidanceConfig, Provenance


def adapt_agent(record, *, owner, source_revision):
    if record.get("status") != "registered" or record.get("immutable_id") != record.get("agent_id"):
        raise ValueError("registered immutable specialist definition required")
    agent_id = record["agent_id"]
    from ..agent_registry import registered_agent_ids

    if agent_id not in registered_agent_ids(include_orchestrator=False):
        raise ValueError("legacy orchestrators cannot become Factory dependencies")
    return AgentManifest(
        owner=owner,
        agent_id=agent_id,
        version=record["version"],
        capabilities=tuple(record["capability_requirements"]),
        tool_ids=tuple(record["tool_eligibility"]),
        audit_refs=("legacy-definition:" + record["immutable_id"],),
        provenance=Provenance(
            component="library",
            source_revision=source_revision,
            origin="legacy-adapter",
            reference="config/agent_registry.json:" + agent_id,
        ),
    )


def adapt_skill(record, *, owner, source_revision, agent_ids):
    if (
        record.get("implementation_kind") != "prompt_guidance"
        or record.get("required_tools") != []
        or record.get("authority_required") != "advisory_only"
    ):
        raise ValueError("only compatible advisory skill records may migrate")
    return SkillManifest(
        owner=owner,
        skill_id=record["skill_id"],
        version=record["version"],
        agent_ids=tuple(agent_ids),
        tool_ids=(),
        artifact=GuidanceConfig(instruction=record["instruction"]),
        audit_refs=("legacy-skill:" + record["skill_id"],),
        provenance=Provenance(
            component="library",
            source_revision=source_revision,
            origin="legacy-adapter",
            reference="app/skill_router.py",
        ),
    )
