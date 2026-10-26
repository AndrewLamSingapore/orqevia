"""Versioned contracts shared by Academy, Library, Tools and the Factory."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Version = Annotated[str, Field(pattern=r"^\d{1,4}\.\d{1,4}\.\d{1,4}$")]


def utcnow():
    return datetime.now(timezone.utc)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True, allow_inf_nan=False)


class Provenance(Contract):
    component: Literal["academy", "library", "tools", "factory", "orqevia"]
    source_revision: Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
    origin: Literal["runtime", "controlled-fixture", "legacy-adapter"] = "runtime"
    reference: Annotated[str, Field(min_length=1, max_length=512)]


class Envelope(Contract):
    schema_version: Literal["1.0"] = "1.0"
    id: Identifier = Field(default_factory=lambda: uuid4().hex)
    owner: Identifier
    created_at: AwareDatetime = Field(default_factory=utcnow)
    provenance: Provenance
    permissions: tuple[Identifier, ...] = ()
    compatibility: tuple[str, ...] = ("activity-pockets/1",)
    audit_refs: tuple[str, ...] = ()


class AgentManifest(Envelope):
    agent_id: Identifier
    version: Version
    capabilities: tuple[Identifier, ...]
    tool_ids: tuple[Identifier, ...]


class ExtractionConfig(Contract):
    title_fields: tuple[Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,31}$")], ...]
    price_fields: tuple[Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,31}$")], ...]

    @field_validator("title_fields", "price_fields")
    @classmethod
    def bounded_fields(cls, value):
        if not 1 <= len(value) <= 4 or len(set(value)) != len(value):
            raise ValueError("one to four unique declarative field names required")
        return value


class GuidanceConfig(Contract):
    instruction: Annotated[str, Field(min_length=1, max_length=240)]
    authority: Literal["advisory_only"] = "advisory_only"


class SkillManifest(Envelope):
    skill_id: Identifier = "web.structured-extraction"
    version: Version
    agent_ids: tuple[Identifier, ...]
    tool_ids: tuple[Identifier, ...]
    artifact: ExtractionConfig | GuidanceConfig


class ToolManifest(Envelope):
    tool_id: Identifier
    version: Version
    input_contract: dict
    output_contract: dict
    side_effects: Literal["authorized-source-read", "local-read", "local-write", "external-consequential"] = (
        "authorized-source-read"
    )


class ResourceBudget(Contract):
    max_attempts: Annotated[int, Field(strict=True, ge=1, le=10000)] = 20
    max_bytes: Annotated[int, Field(strict=True, ge=1, le=100_000_000)] = 2_000_000
    max_records: Annotated[int, Field(strict=True, ge=1, le=10000)] = 1000
    max_wall_seconds: Annotated[float, Field(gt=0, le=86400)] = 300
    max_cost_usd: Annotated[float, Field(ge=0, le=100)] = 0
    max_retries: Annotated[int, Field(strict=True, ge=0, le=5)] = 2


class PocketManifest(Envelope):
    objective: Annotated[str, Field(min_length=10, max_length=4000)]
    agent_ids: tuple[Identifier, ...] = ("a07",)
    skill_id: Literal["web.structured-extraction"] = "web.structured-extraction"
    skill_version: Version = "1.0.0"
    source_ids: tuple[Identifier, ...]
    permitted_operations: tuple[Literal["provided_context.read"], ...] = ("provided_context.read",)
    budget: ResourceBudget = Field(default_factory=ResourceBudget)
    success_criteria: Annotated[str, Field(min_length=5, max_length=1000)]
    stop_conditions: tuple[str, ...] = ("budget_exhausted", "quality_failure", "owner_cancelled")
    retention_days: Annotated[int, Field(strict=True, ge=1, le=3650)] = 30
    not_before: AwareDatetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def complete_scope(self):
        for values in (self.agent_ids, self.source_ids, self.permitted_operations, self.stop_conditions):
            if not values or len(values) > 32 or len(set(values)) != len(values):
                raise ValueError("nonempty, unique and bounded pocket scope required")
        if set(self.permissions) != set(self.permitted_operations):
            raise ValueError("permission envelope must equal permitted operations")
        if not {"budget_exhausted", "quality_failure", "owner_cancelled"} <= set(self.stop_conditions):
            raise ValueError("mandatory execution stop conditions missing")
        return self


class ExecutionEvent(Envelope):
    pocket_id: Identifier
    event_type: Identifier
    actor: Identifier
    details: dict = Field(default_factory=dict)


class EvaluationRecord(Envelope):
    proposal_id: Identifier
    evaluator: Identifier
    candidate_sha256: Digest
    suite_sha256: Digest
    passed: bool
    regression_results: tuple[dict, ...]
    safety_passed: bool
    correctness_passed: bool
    traceability_passed: bool
    generalization_passed: bool


class CoachingProposal(Envelope):
    pocket_id: Identifier
    proposer: Identifier
    observed_deficiency: str
    supporting_evidence: tuple[Identifier, ...]
    proposed_change: ExtractionConfig
    expected_benefit: str
    evaluation_methodology: str
    regression_results: tuple[dict, ...] = ()
    risk_assessment: str
    rollback_procedure: str
    from_version: Version
    to_version: Version


class QualificationEvidence(Envelope):
    agent_id: Identifier
    capability_id: Identifier
    projection: dict
    scope: Literal["existing-certification-projection"] = "existing-certification-projection"


class PromotionDecision(Envelope):
    pocket_id: Identifier
    proposal_id: Identifier
    evaluation_id: Identifier
    approver: Identifier
    approved: bool
    candidate_sha256: Digest
    reason: Annotated[str, Field(min_length=5, max_length=1000)]
    previous_version: Version
    promoted_version: Version


class RecoveryRecord(Envelope):
    pocket_id: Identifier
    operation: Literal["lease-recovery", "rollback", "retention-purge"]
    previous_state: str
    restored_state: str
    reason: str
    evidence_refs: tuple[str, ...]


SCHEMAS = (
    AgentManifest,
    SkillManifest,
    ToolManifest,
    PocketManifest,
    ExecutionEvent,
    EvaluationRecord,
    CoachingProposal,
    QualificationEvidence,
    PromotionDecision,
    RecoveryRecord,
)
