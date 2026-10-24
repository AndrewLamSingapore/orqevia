"""Versioned 36-fabric capability registry (mission deliverable A).

Contract-only catalog of the ORQEVIA fabric architecture. Lifecycle states are
honest: VERIFIED is reserved for fabrics with recorded functional evidence;
readiness observations alone do not verify a capability. This module is a
registry, not a runtime router, and performs no inference, no I/O beyond its
own report, and no side effects.

States: PROPOSED, IMPLEMENTED, VERIFIED, DEGRADED, FAILED, DISABLED, UNAVAILABLE.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import re
from datetime import datetime, timezone
from pathlib import Path

REGISTRY_VERSION = "1.4.1"
FABRIC_COUNT = 36
STATES = ("PROPOSED", "IMPLEMENTED", "VERIFIED", "DEGRADED", "FAILED", "DISABLED", "UNAVAILABLE")

# The 14 contract dimensions required by the MASTER-DIRECTIVE Part III.
CONTRACT_FIELDS = (
    "id",
    "name",
    "identifier",
    "version",
    "state",
    "purpose",
    "operations",
    "input_schema",
    "output_schema",
    "dependencies",
    "configuration",
    "auth",
    "health_check",
    "timeout_policy",
    "retry_policy",
    "resource_cost_limits",
    "observability_provenance",
    "failure_fallback",
    "tests_status",
    "lifecycle_owner",
    "evidence",
    "notes",
)

_VERSION_RE = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\Z")
_DEFAULT_SCHEMA = {"type": "object", "description": "Contract not yet specified"}

# Fresh live receipts from the 2026-10-24 post-reboot observation.
_STATUS_RECEIPT = {
    "path": "operations/orqevia2-20261023/collective-status-production-20261024T005605Z.json",
    "sha256": "ed6e080ae2a0abe887492a3c632743475d66e096fb9df15ae50b5969858a5c54",
}
_FABRIC_RECEIPT = {
    "path": "operations/orqevia2-20261023/fabric-production-20261024T005611Z.json",
    "sha256": "722dd9f8c394c8bf74301b4a4742329c6dde0dfe858efffbf088ec3325cc4285",
}


def _f(
    entry_id,
    name,
    identifier,
    state,
    purpose,
    *,
    version="0.1.0",
    operations=None,
    dependencies=None,
    configuration=None,
    auth="ORQEVIA_SPINE_TOKEN",
    health_check=None,
    timeout_policy="60s request timeout",
    retry_policy="bounded, idempotent retries only",
    resource_cost_limits="no paid provider by default",
    observability_provenance="OTEL loopback collector",
    failure_fallback="degrade to UNAVAILABLE and report",
    tests_status=None,
    lifecycle_owner="ORQEVIA control plane",
    evidence=None,
    notes="",
    input_schema=None,
    output_schema=None,
):
    return {
        "id": entry_id,
        "name": name,
        "identifier": identifier,
        "version": version,
        "state": state,
        "purpose": purpose,
        "operations": operations or [],
        "input_schema": deepcopy(input_schema or _DEFAULT_SCHEMA),
        "output_schema": deepcopy(output_schema or _DEFAULT_SCHEMA),
        "dependencies": dependencies or [],
        "configuration": configuration or {},
        "auth": auth,
        "health_check": health_check or "NONE",
        "timeout_policy": timeout_policy,
        "retry_policy": retry_policy,
        "resource_cost_limits": resource_cost_limits,
        "observability_provenance": observability_provenance,
        "failure_fallback": failure_fallback,
        "tests_status": tests_status or "not run",
        "lifecycle_owner": lifecycle_owner,
        "evidence": evidence or [],
        "notes": notes,
    }


_FABRICS = [
    _f(
        "f01",
        "Ollama Local",
        "ollama-local",
        "IMPLEMENTED",
        "Local inference via pinned Ollama runtime and deep-tier qualification.",
        version="1.0.0",
        operations=["list models", "bounded local completion"],
        dependencies=["orqevia-epoch-20261016-ollama-1"],
        health_check="/api/tags",
        tests_status="live readiness protocol 2026-10-24",
        evidence=[_STATUS_RECEIPT, _FABRIC_RECEIPT],
        notes="Readiness protocol observed; capability-level functional test remains for VERIFIED.",
    ),
    _f(
        "f02",
        "Knowledge MiniLM",
        "knowledge-minilm",
        "IMPLEMENTED",
        "Local retrieval and knowledge store backed by the pinned MiniLM service.",
        version="1.0.0",
        operations=["search", "store claim"],
        dependencies=["local-knowledge service"],
        health_check="/health",
        tests_status="live readiness protocol 2026-10-24",
        evidence=[_STATUS_RECEIPT, _FABRIC_RECEIPT],
        notes="59 knowledge claims, 0 verified facts, 0 unresolved contradictions at observation.",
    ),
    _f(
        "f03",
        "Semantic NLI",
        "semantic-nli",
        "IMPLEMENTED",
        "Pinned semantic entailment for claim checking and corrections.",
        version="1.0.0",
        operations=["entailment check"],
        dependencies=["local-knowledge service"],
        health_check="/semantic/health",
        tests_status="live readiness protocol 2026-10-24",
        evidence=[_STATUS_RECEIPT, _FABRIC_RECEIPT],
        notes="Readiness protocol observed.",
    ),
    _f(
        "f04",
        "Geospatial Intelligence",
        "geospatial-intelligence",
        "IMPLEMENTED",
        "Geospatial data service and vector capability.",
        version="1.0.0",
        operations=["geospatial query"],
        dependencies=["orqevia-geospatial-dev-database-1"],
        health_check="/api/orqevia/intelligence/health",
        tests_status="live readiness protocol 2026-10-24",
        evidence=[_STATUS_RECEIPT, _FABRIC_RECEIPT],
        notes="Readiness protocol observed.",
    ),
    _f(
        "f05",
        "Portfolio Event Fabric",
        "portfolio-event-fabric",
        "VERIFIED",
        "Durable portfolio event observation with projector readback.",
        version="1.0.0",
        operations=["observe event", "read projectors"],
        dependencies=["app/event_fabric.py"],
        health_check="collective lookup",
        tests_status="persisted execution and four-projector readback verified 2026-10-24",
        evidence=[_STATUS_RECEIPT, _FABRIC_RECEIPT],
        notes="VERIFIED on persisted execution evidence, not on a readiness observation alone.",
    ),
    _f(
        "f06",
        "MLP Fabric",
        "mlp-fabric",
        "VERIFIED",
        "Synthetic quadratic reference MLP for bounded inference demonstration.",
        version="1.0.0",
        operations=["bounded reference inference"],
        dependencies=["config/mlp/quadratic-reference-v1.json"],
        health_check="collective lookup",
        tests_status="actual bounded reference inference verified 2026-10-24",
        evidence=[_STATUS_RECEIPT, _FABRIC_RECEIPT],
        notes="SYNTHETIC_QUADRATIC_REFERENCE_ONLY; grants_agent_authority=false; automatic_training=false.",
    ),
    _f(
        "f07",
        "HF Gemma Nano",
        "hf-gemma-nano",
        "VERIFIED",
        "Governed Hugging Face cloud fallback under the daily cost cap.",
        version="1.0.0",
        operations=["governed cloud inference (bounded)"],
        dependencies=["ORQEVIA_HF_TOKEN_FILE"],
        health_check="collective lookup",
        tests_status="last governed inference within 24h at observation 2026-10-24",
        evidence=[_STATUS_RECEIPT, _FABRIC_RECEIPT],
        notes="Evidence expires 24 hours after the governed execution; not a continuous provider SLA.",
    ),
    _f(
        "f08",
        "Agent Orchestration Fabric",
        "agent-orchestration",
        "IMPLEMENTED",
        "Agent delegation, task planning, bounded execution and concurrency control.",
        version="0.2.0",
        operations=["plan", "delegate", "bounded execute"],
        dependencies=["app/compute_queue_api.py", "app/agent_registry.py"],
        tests_status="21/21 agents registered and liveness observed; cancellation and recovery gap audit pending",
        evidence=[_STATUS_RECEIPT],
        notes="Foundations reused from the collective runtime; vertical contract completion pending.",
    ),
    _f(
        "f09",
        "Tool & MCP Fabric",
        "tool-mcp",
        "IMPLEMENTED",
        "Governed interface to approved tools, APIs, CLI and MCP servers.",
        version="0.2.0",
        operations=["invoke approved tool"],
        dependencies=["app/agent_capability_*", "spine token auth"],
        tests_status="permission and argument validation gap audit pending",
        evidence=[_STATUS_RECEIPT],
        notes="Credential isolation enforced by secret references only; per-tool audit gaps remain.",
    ),
    _f(
        "f10",
        "Code Intelligence Fabric",
        "code-intelligence",
        "IMPLEMENTED",
        "Repository, dependency and test analysis with evidence-based patch support.",
        version="0.2.0",
        operations=["analyze repository", "review patch"],
        dependencies=["app/agent_cert_review_tool.py", "app/project_workflows.py"],
        tests_status="partial; vertical engineering pathway pending",
        evidence=[_STATUS_RECEIPT],
        notes="Component-level foundations exist; end-to-end repository workflow not yet vertically verified.",
    ),
    _f(
        "f11",
        "Browser Intelligence Fabric",
        "browser-intelligence",
        "IMPLEMENTED",
        "Browser end-to-end testing, screenshots and interaction checks.",
        version="0.2.0",
        operations=["browser run", "screenshot", "interaction check"],
        dependencies=["verify_operations_browser.cjs", "verify_fabric_browser.cjs"],
        tests_status="14/14 fabric browser and WebKit checks passed 2026-10-23",
        evidence=[{"path": "operations/orqevia2-20261023/fabric-browser-production-2026-10-23T10-59-06-831Z.json"}],
        notes="Vertical increments remain for accessibility and responsive validation coverage.",
    ),
    _f(
        "f12",
        "Verification & Evaluation Fabric",
        "verification-evaluation",
        "IMPLEMENTED",
        "Deterministic tests, evidence-based scoring and regression gates.",
        version="0.2.0",
        operations=["run acceptance", "score with evidence"],
        dependencies=["collective_live_acceptance.py", "staging_acceptance.cjs"],
        tests_status="16/16 live acceptance and 26 journey checks recorded",
        evidence=[_STATUS_RECEIPT, _FABRIC_RECEIPT],
        notes="Independent AI review remains partial; never a model's own assertion alone.",
    ),
    _f(
        "f13",
        "Security Intelligence Fabric",
        "security-intelligence",
        "IMPLEMENTED",
        "Dependency scanning, secret detection and remediation verification.",
        version="0.2.0",
        operations=["scan dependencies", "detect secrets", "verify remediation"],
        dependencies=["operations/orqevia-security-20261022"],
        tests_status="security closure receipts from 2026-10-22 retained; continuous scanning partial",
        evidence=[{"path": "operations/orqevia-security-20261022"}],
        notes="Host firewall status is an owner directive, recorded separately from this contract.",
    ),
    _f(
        "f14",
        "Memory & Context Fabric",
        "memory-context",
        "IMPLEMENTED",
        "Durable project context, decision records and versioned memory.",
        version="1.0.0",
        operations=["store memory", "retrieve provenance"],
        dependencies=["SQLite knowledge store"],
        health_check="collective lookup",
        tests_status="audit chain PASS, 6692 events, 59 claims",
        evidence=[_STATUS_RECEIPT],
        notes="Tamper-evident against partial edits; external anchor remains a limitation.",
    ),
    _f(
        "f15",
        "Observability Fabric",
        "observability",
        "IMPLEMENTED",
        "Traces, logs, metrics, latency and cost capture.",
        version="1.0.0",
        operations=["emit trace", "read metrics"],
        dependencies=["orqevia-epoch-20261016-otel-collector-1"],
        tests_status="OTEL telemetry gate PASS; exporter to /otel/otel-telemetry.json with rotation",
        evidence=[_STATUS_RECEIPT],
        notes="Telemetry never leaves the host.",
    ),
    _f(
        "f16",
        "Deployment & DevOps Fabric",
        "deployment-devops",
        "IMPLEMENTED",
        "Builds, CI/CD checks, release artifacts and rollback procedures.",
        version="1.0.0",
        operations=["prepare release", "verify rollback"],
        dependencies=["release-package/release_control.py", "release-package/prepare_release.py"],
        tests_status="rollback verification PASS gate retained",
        evidence=[_STATUS_RECEIPT],
        notes="Production promotion stays behind explicit approval gates.",
    ),
    _f(
        "f17",
        "Multimodal Intelligence Fabric",
        "multimodal-intelligence",
        "IMPLEMENTED",
        "Text, image and document analysis with verified supported models.",
        version="0.2.0",
        operations=["analyze image", "extract document"],
        dependencies=["app/vision_evidence.py", "app/local_document_extract.py", "app/media_api.py"],
        tests_status="vision candidate and adversarial tests pass; audio and video unverified",
        evidence=[],
        notes="Audio/video analysis not implemented; marked partial.",
    ),
    _f(
        "f18",
        "Creative Media Fabric",
        "creative-media",
        "IMPLEMENTED",
        "Governed Higgsfield video generation and asset production pipeline.",
        version="0.3.0",
        operations=["generate (paid, gated)", "compose review assets"],
        dependencies=["app/higgsfield_media.py", "app/media_generation.py"],
        tests_status="repository-ad batch complete under $0.03 cap; publication parked",
        evidence=[{"path": "operations/higgsfield-repository-ads-20261022"}],
        notes="Paid generation and publication require explicit approval; never auto-pays.",
    ),
    _f(
        "f19",
        "Research Intelligence Fabric",
        "research-intelligence",
        "IMPLEMENTED",
        "Source-grounded research, retrieval and cross-source verification.",
        version="0.2.0",
        operations=["observe provider", "synthesize evidence"],
        dependencies=["probe_observation_providers.py", "provider-* data"],
        tests_status="opensky, NDBC and EU council observations recorded; UN News/Press 404 parked",
        evidence=[],
        notes="Parked sources require an owner decision before reactivation.",
    ),
    _f(
        "f20",
        "Knowledge Graph Fabric",
        "knowledge-graph",
        "IMPLEMENTED",
        "Entities, relationships, claims and supporting evidence.",
        version="0.2.0",
        operations=["store claim", "query knowledge"],
        dependencies=["local-knowledge service"],
        tests_status="59 claims stored; entity/relationship modeling not yet built",
        evidence=[_STATUS_RECEIPT],
        notes="Claim store exists; graph modeling remains pending.",
    ),
    _f(
        "f21",
        "Simulation & Digital Twin Fabric",
        "simulation-digital-twin",
        "PROPOSED",
        "Bounded simulations, scenarios and state-based models.",
        version="0.1.0",
        operations=[],
        dependencies=[],
        tests_status="none",
        evidence=[],
        notes="No implementation yet.",
    ),
    _f(
        "f22",
        "Decision Intelligence Fabric",
        "decision-intelligence",
        "PROPOSED",
        "Alternatives, constraints, trade-offs, uncertainty and expected outcomes.",
        version="0.1.0",
        operations=[],
        dependencies=[],
        tests_status="none",
        evidence=[],
        notes="No implementation yet.",
    ),
    _f(
        "f23",
        "Workflow Automation Fabric",
        "workflow-automation",
        "IMPLEMENTED",
        "Event-driven workflows, schedules, durable queues, approvals and idempotency.",
        version="1.0.0",
        operations=["run workflow", "schedule job"],
        dependencies=["app/workflow_engine.py", "app/project_workflows.py", "app/operational_workflows.py"],
        tests_status="workflow engine and handoff unit tests pass",
        evidence=[{"path": "tests/test_workflow_engine.py"}],
        notes="Durable queue and approval integration reuse the collective queue.",
    ),
    _f(
        "f24",
        "Human Governance Fabric",
        "human-governance",
        "IMPLEMENTED",
        "Policy enforcement, human approvals, audit trails and least privilege.",
        version="1.0.0",
        operations=["enforce policy", "record approval", "audit"],
        dependencies=["collective governance", "audit chain"],
        tests_status="registry integrity PASS, audit chain PASS",
        evidence=[_STATUS_RECEIPT],
        notes="Emergency-stop coverage is documented as partial in doctrine PAUSE-COVERAGE.",
    ),
    _f(
        "f25",
        "Causal Reasoning Fabric",
        "causal-reasoning",
        "PROPOSED",
        "Causal models, hypothesis tests, counterfactuals and uncertainty.",
        version="0.1.0",
        operations=[],
        dependencies=[],
        tests_status="none",
        evidence=[],
        notes="No implementation yet.",
    ),
    _f(
        "f26",
        "Forecasting Fabric",
        "forecasting",
        "PROPOSED",
        "Time-series forecasting, backtesting, intervals and drift monitoring.",
        version="0.1.0",
        operations=[],
        dependencies=[],
        tests_status="none",
        evidence=[],
        notes="No implementation yet.",
    ),
    _f(
        "f27",
        "Optimization Fabric",
        "optimization",
        "PROPOSED",
        "Constrained scheduling, allocation and scenario comparison.",
        version="0.1.0",
        operations=[],
        dependencies=[],
        tests_status="none",
        evidence=[],
        notes="No implementation yet.",
    ),
    _f(
        "f28",
        "Privacy & Confidential Computing Fabric",
        "privacy-confidential-computing",
        "PROPOSED",
        "Data minimization, privacy controls and supported privacy-preserving methods.",
        version="0.1.0",
        operations=[],
        dependencies=[],
        tests_status="none",
        evidence=[],
        notes="No confidential-computing claim without compatible hardware and attestation.",
    ),
    _f(
        "f29",
        "Identity & Trust Fabric",
        "identity-trust",
        "IMPLEMENTED",
        "Authentication, authorization, service identity and trust policies.",
        version="1.0.0",
        operations=["issue pairing", "verify attestation"],
        dependencies=["TLS at interface", "golden runtime attestation", "ACL-restricted secrets"],
        tests_status="session boundary TRUST_REQUIRED and golden attestation VERIFIED",
        evidence=[{"path": "runtime/orqevia-epoch-20261016/runtime-attestation.json"}],
        notes="Device pairing one-tap flow is owner-parked; mint with an owner 'pairing code'.",
    ),
    _f(
        "f30",
        "Document Intelligence Fabric",
        "document-intelligence",
        "IMPLEMENTED",
        "Document extraction, classification, parsing, comparison and validation.",
        version="0.2.0",
        operations=["extract document"],
        dependencies=["app/local_document_extract.py"],
        tests_status="extraction module exists; classification and comparison pending",
        evidence=[],
        notes="Partial implementation only.",
    ),
    _f(
        "f31",
        "Voice & Speech Fabric",
        "voice-speech",
        "PROPOSED",
        "Speech recognition, synthesis, transcription and voice interaction.",
        version="0.1.0",
        operations=[],
        dependencies=[],
        tests_status="none",
        evidence=[],
        notes="No implementation yet; voice interaction requires authorization.",
    ),
    _f(
        "f32",
        "Computer Vision Fabric",
        "computer-vision",
        "IMPLEMENTED",
        "Image understanding, classification and visual measurements.",
        version="0.2.0",
        operations=["verify image evidence"],
        dependencies=["app/vision_evidence.py"],
        tests_status="vision candidate verifier and adversarial tests pass; object detection unverified",
        evidence=[{"path": "tests/test_vision_candidate_verifier.py"}],
        notes="Partial implementation only.",
    ),
    _f(
        "f33",
        "Robotics & Edge Fabric",
        "robotics-edge",
        "PROPOSED",
        "Authorized device integration, telemetry and bounded physical automation.",
        version="0.1.0",
        operations=[],
        dependencies=[],
        tests_status="none",
        evidence=[],
        notes="Physical actions require explicit authorization and safety interlocks.",
    ),
    _f(
        "f34",
        "Financial Intelligence Fabric",
        "financial-intelligence",
        "PROPOSED",
        "Financial modeling, budgeting, unit economics and sensitivity analysis.",
        version="0.1.0",
        operations=[],
        dependencies=[],
        tests_status="none",
        evidence=[],
        notes="The Portal lifetime ledger is a separate operational record, not this fabric.",
    ),
    _f(
        "f35",
        "Scientific Computing Fabric",
        "scientific-computing",
        "PROPOSED",
        "Numerical computing, statistics, reproducible experiments and validation.",
        version="0.1.0",
        operations=[],
        dependencies=[],
        tests_status="none",
        evidence=[],
        notes="No implementation yet.",
    ),
    _f(
        "f36",
        "Adversarial Testing Fabric",
        "adversarial-testing",
        "IMPLEMENTED",
        "Authorized red-team, prompt-injection and policy-resilience testing.",
        version="0.2.0",
        operations=["run adversarial case"],
        dependencies=["tests/test_vision_adversarial.py"],
        tests_status="vision adversarial suite passes; cross-fabric red teaming pending",
        evidence=[{"path": "tests/test_vision_adversarial.py"}],
        notes="Partial implementation only.",
    ),
]


def _existing_contracts(entries):
    """Describe bounded existing entrypoints without implying full fabric coverage."""
    by_id = {item["id"]: item for item in entries}
    by_id["f26"].update(
        state="IMPLEMENTED",
        operations=["chronological last-value holdout evaluation"],
        dependencies=["app/predictive_intelligence.py:evaluate_last_value_baseline"],
        tests_status="tests/test_historical_predictive.py; runtime verification requires fresh functional evidence",
        notes="Existing last-value baseline only. Confidence intervals and drift monitoring remain pending.",
    )
    by_id["f34"].update(
        state="IMPLEMENTED",
        operations=["bounded operating-cost and scenario calculations"],
        dependencies=["app/project_workflows.py:calculate_financials"],
        tests_status="tests/test_project_workflows.py; runtime verification requires fresh functional evidence",
        notes="Existing deterministic user-supplied business scenarios; not financial advice or market forecasting.",
    )
    path_schema = {"type": "string", "minLength": 1, "maxLength": 4096}
    by_id["f10"].update(
        operations=["inspect owning repository", "run selected existing check profile"],
        dependencies=["app/repository_evaluation.py", "scripts/evaluate_repository.py", "git"],
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["repository", "profile", "evidence_root"],
            "properties": {
                "repository": path_schema,
                "evidence_root": path_schema,
                "profile": {"enum": ["python", "node", "static-web"]},
            },
        },
        output_schema={
            "type": "object",
            "required": ["execution_id", "status", "directory", "receipt_sha256"],
            "properties": {
                "execution_id": {"type": "string", "format": "uuid"},
                "status": {"enum": ["PASS", "FAIL"]},
                "directory": path_schema,
                "checks": {"type": "integer", "minimum": 1, "maximum": 16},
                "receipt_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
            },
        },
        health_check="pytest tests/test_repository_evaluation.py",
        timeout_policy="300s default per explicit check, 1800s hard maximum; fixed profiles 600s; sequential execution",
        auth="Explicit local repository execution authorization; no remote arbitrary-command route",
        notes="Runs actual selected checks and rescans evidence. General patch generation and independent AI review remain separate capabilities.",
    )
    by_id["f12"].update(
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["receipt_directory"],
            "properties": {"receipt_directory": path_schema},
        },
        output_schema={
            "type": "object",
            "required": ["execution_id", "status", "errors", "execution_sha256"],
            "properties": {
                "execution_id": {"type": "string", "format": "uuid"},
                "status": {"enum": ["PASS", "FAIL"]},
                "errors": {"type": "array", "items": {"type": "string"}},
                "execution_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "publication_authorized": {"const": False},
            },
        },
        health_check="pytest tests/test_repository_evaluation.py tests/test_fabric_verification.py",
        notes="Deterministic independent file/JUnit rescan; no claim of independent AI review from deterministic evidence alone.",
    )
    return entries


def validate_registry(entries):
    """Fail loudly on structural or honesty violations."""
    if not isinstance(entries, list) or len(entries) != FABRIC_COUNT:
        raise ValueError("registry must contain exactly %d fabrics" % FABRIC_COUNT)
    seen = set()
    identifiers = set()
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            raise ValueError("fabric entry must be an object")
        for field in CONTRACT_FIELDS:
            if field not in item:
                raise ValueError("fabric %s missing contract field %s" % (item.get("id", index), field))
        if item["id"] in seen:
            raise ValueError("duplicate fabric id %s" % item["id"])
        if item["id"] != "f%02d" % (index + 1):
            raise ValueError("fabric ids must be the ordered f01-f36 set")
        seen.add(item["id"])
        if item["state"] not in STATES:
            raise ValueError("fabric %s has invalid state %s" % (item["id"], item["state"]))
        if not isinstance(item["version"], str) or not _VERSION_RE.fullmatch(item["version"]):
            raise ValueError("fabric %s has invalid version %s" % (item["id"], item["version"]))
        if item["state"] == "VERIFIED" and not item["evidence"]:
            raise ValueError("VERIFIED fabric %s has no recorded evidence" % item["id"])
        if item["state"] in ("IMPLEMENTED", "VERIFIED") and not item["identifier"]:
            raise ValueError("implemented fabric %s has no runtime identifier" % item["id"])
        if not isinstance(item["identifier"], str) or item["identifier"] in identifiers:
            raise ValueError("fabric identifiers must be unique strings")
        identifiers.add(item["identifier"])
        if not all(isinstance(item[field], dict) for field in ("input_schema", "output_schema")):
            raise ValueError("fabric schemas must be objects")
        runtime = item.get("runtime_contract")
        if runtime:
            actual = [operation["operation"] for operation in runtime["operations"]]
            if item["operations"] != actual or len(set(actual)) != len(actual):
                raise ValueError("top-level operations must match the executable contract")
            if item.get("contract_status") != "DEFINED_FOR_LISTED_OPERATIONS":
                raise ValueError("an executable contract must describe its listed operation schemas")
            variants = item["input_schema"].get("oneOf", [])
            declared = [variant.get("properties", {}).get("operation", {}).get("const") for variant in variants]
            if (
                declared != actual
                or item["output_schema"].get("properties", {}).get("data") != runtime["execution_receipt_schema"]
            ):
                raise ValueError("execution wrappers must bind the listed operations and receipt schema")
    return entries


_OPERATION_DEPENDENCIES = {
    "f01": ["app/settings.py", "httpx", "configured Ollama /api/tags"],
    "f02": ["app/local_knowledge_service.py:/retrieve", "pinned existing MiniLM index"],
    "f03": [
        "app/local_knowledge_service.py:/semantic/assess",
        "app/semantic_entailment.py",
        "pinned offline NLI artifacts",
    ],
    "f04": ["app/geospatial.py:haversine_km"],
    "f05": ["app/fabric_adapters.py:event_observation", "app/event_fabric.py", "actual governed compute queue stores"],
    "f06": ["app/fabric_adapters.py:mlp_infer", "app/mlp_fabric.py", "config/mlp/quadratic-reference-v1.json"],
    "f07": [
        "app/fabric_adapters.py:hf_observation",
        "app/compute_catalog.py",
        "actual queue and compute-ledger.db records no older than 24 hours",
    ],
    "f08": ["app/compute_queue_api.py:queue", "app/job_queue.py:JobQueue.metrics"],
    "f09": ["app/geospatial.py", "app/fabric_adapters.py:mlp_infer"],
    "f10": ["Python ast", "actual deployed app/*.py source"],
    "f11": [
        "app/local_knowledge_service.py:/browser/inspect",
        "app/fabric_browser.py",
        "scripts/fabric_browser_probe.cjs",
        "existing Chromium and Playwright",
    ],
    "f12": ["app/fabric_runtime.py:read_execution", "owner/tenant scoped execution journal"],
    "f14": ["app/governed_knowledge.py", "SQLite owner/tenant scoped context store"],
    "f15": ["SQLite owner/tenant scoped execution journal"],
    "f16": ["actual deployed fabric_runtime.py, collective_api.py and production_entry.py"],
    "f18": ["fixed deterministic edit-timeline calculation"],
    "f19": [
        "configured intelligence service /api/orqevia/intelligence/geo/events",
        "app/geo_ingest.py",
        "app/fabric_research.py:execute",
        "approved primary HTTPS hosts with normal CA and hostname verification",
    ],
    "f23": ["app/workflow_engine.py", "app/action_records.py", "fixed local digest/summary handlers"],
    "f24": ["fixed local tool policy in app/fabric_runtime.py"],
    "f29": ["authenticated CollectivePrincipal from app/collective_api.py"],
    "f31": [
        "app/local_knowledge_service.py:/speech/synthesize",
        "app/fabric_speech.py",
        "installed Windows System.Speech and allowlisted desktop voices",
    ],
    "f33": ["psutil", "current execution process resource counters"],
}


def _error_response_schema():
    """Exact direct-backend and interface error envelopes, not success results."""
    message = {"type": "string", "minLength": 1}
    error_properties = {
        "code": {"type": "string"},
        "message": message,
        "retryable": {"type": "boolean", "const": False},
    }

    def envelope(protocol, codes, *, correlation):
        properties = {
            "protocol": {"type": "string", "const": protocol},
            "error": {
                "type": "object",
                "required": ["code", "message", "retryable"],
                "properties": {**error_properties, "code": {"type": "string", "enum": codes}},
                "additionalProperties": False,
            },
        }
        if correlation:
            properties["correlation_id"] = {
                "type": "string",
                "format": "uuid",
                "pattern": "^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$",
            }
        return {"type": "object", "required": list(properties), "properties": properties, "additionalProperties": False}

    return {
        "oneOf": [
            {
                "type": "object",
                "required": ["detail"],
                "properties": {"detail": message},
                "additionalProperties": False,
            },
            envelope("orqevia.collective.v1", ["COLLECTIVE_REQUEST_FAILED"], correlation=True),
            envelope(
                "orqevia.interface.v1",
                [
                    "AUTHENTICATION_REQUIRED",
                    "CLIENT_SCOPE_DENIED",
                    "NOT_FOUND",
                    "METHOD_NOT_ALLOWED",
                    "STATE_CONFLICT",
                    "INVALID_REQUEST",
                    "HTTPS_REQUIRED",
                    "RATE_LIMITED",
                    "SERVICE_UNAVAILABLE",
                    "INTERNAL_ERROR",
                ],
                correlation=False,
            ),
        ]
    }


def _runtime_contract(item, runtime):
    """Publish the supported HTTP contract without promoting source into evidence."""
    from .fabric_runtime import execution_receipt_schema, execution_request_schema, execution_response_schema

    runtime = deepcopy(runtime)
    prior = {
        key: deepcopy(item[key])
        for key in (
            "purpose",
            "operations",
            "input_schema",
            "output_schema",
            "dependencies",
            "auth",
            "health_check",
            "timeout_policy",
            "retry_policy",
            "tests_status",
            "notes",
        )
    }
    if item["id"] in {"f10", "f12"}:
        item["local_entrypoint_contract"] = {
            "classification": "EXISTING_LOCAL_OPERATOR_CLI_SEPARATE_FROM_HTTP_EXECUTION",
            "entrypoint": "scripts/evaluate_repository.py"
            if item["id"] == "f10"
            else "app.repository_evaluation:verify_receipt",
            **prior,
        }
    item["historical_inventory"] = {
        "classification": "DATED_SOURCE_INVENTORY_NOT_CURRENT_RUNTIME_VERIFICATION",
        **prior,
    }
    identifier = item["id"]
    operations = runtime["operations"]
    item["version"] = runtime["version"]
    item["operations"] = [operation["operation"] for operation in operations]
    item["purpose"] = "Supported scope: " + " ".join(operation["scope"] for operation in operations)
    item["supported_scopes"] = [operation["scope"] for operation in operations]
    item["roadmap_purpose"] = prior["purpose"]
    item["limitations"] = deepcopy(runtime.get("limitations", []))
    item["contract_status"] = "DEFINED_FOR_LISTED_OPERATIONS"
    item["input_schema"] = deepcopy(execution_request_schema(runtime))
    item["output_schema"] = deepcopy(execution_response_schema(identifier, runtime))
    adapter = "app/fabric_runtime.py"
    if identifier in {"f21", "f22", "f25", "f26", "f27", "f34", "f35"}:
        adapter = "app/fabric_analytics.py"
    elif identifier in {"f13", "f20", "f28", "f30", "f36"}:
        adapter = "app/fabric_foundations.py"
    elif identifier in {"f17", "f32"}:
        adapter = "app/fabric_multimodal.py"
    item["dependencies"] = ["app/fabric_runtime.py:execute_fabric", *_OPERATION_DEPENDENCIES.get(identifier, [adapter])]
    if identifier == "f34":
        item["dependencies"].append("app/project_workflows.py:calculate_financials")
    item["configuration"] = {
        "data_directory": {"environment": "ORQEVIA_DATA_DIR", "default": "/data"},
        "runtime_revision_environment": "ORQEVIA_RUNTIME_REVISION",
        "activation_environment": {"ORQEVIA_COLLECTIVE_ENABLED": "1"},
        "credential_environment_names": ["ORQEVIA_SPINE_TOKEN", "ORQEVIA_PWA_OWNER_ACCOUNT_ID"],
        "tenant_environment": {"name": "ORQEVIA_TENANT_ID", "default": "personal"},
    }
    if identifier in {"f02", "f03", "f11", "f31"}:
        item["configuration"]["service_base"] = "http://host.docker.internal:8150"
    elif identifier == "f19":
        from .fabric_research import APPROVED_HOSTS, MAX_BODY, MAX_REDIRECTS, TOTAL_SECONDS

        item["configuration"]["service_base"] = "http://intelligence:8100"
        item["configuration"]["primary_source_retrieval"] = {
            "operation": "fetch_primary_source",
            "approved_hosts": sorted(APPROVED_HOSTS),
            "transport": "HTTPS_OS_TRUST_NO_CREDENTIALS_OR_HTTP_FALLBACK",
            "maximum_body_bytes": MAX_BODY,
            "maximum_redirects": MAX_REDIRECTS,
            "total_deadline_seconds": TOTAL_SECONDS,
        }
    elif identifier == "f01":
        item["configuration"]["ollama"] = {"environment": "OLLAMA_BASE_URL", "default": "http://ollama:11434"}
    item["auth"] = (
        "Backend requires the existing service bearer token, bound owner digest and validated actor. The interface uses its existing session boundary and server-held forwarding credentials. Client content never grants authority."
    )
    item["health_check"] = (
        "Authenticated registry discovery is not a functional health test. Execute a listed operation with a separately checked oracle and fresh source/version-bound evidence; contract regression: tests/test_fabric_registry.py."
    )
    item["timeout_policy"] = (
        "Schema/loop-bounded in-process work; no overall cancellation timer is asserted. Execution-journal SQLite busy timeout: 5s."
    )
    if identifier == "f01":
        item["timeout_policy"] = (
            "Configured Ollama HTTP I/O timeout 8s; this is not a whole-request execution deadline."
        )
    elif identifier in {"f02", "f03", "f11", "f19", "f31"}:
        item["timeout_policy"] = (
            "Configured service HTTP I/O timeout 60s, connect timeout 3s, response cap 2000000 bytes; not a global wall-clock deadline."
        )
        if identifier == "f11":
            item["timeout_policy"] += " Browser child has a 20s probe deadline and 25s process timeout."
        elif identifier == "f31":
            item["timeout_policy"] += " Windows synthesis child timeout: 30s."
        elif identifier == "f19":
            item["timeout_policy"] += (
                " These service bounds apply to retrieve_observations."
                " fetch_primary_source uses connect 3s/read 10s, a hard total 20s deadline,"
                " at most two revalidated redirects and 262144 response bytes."
            )
    item["retry_policy"] = (
        "No automatic retries. Reusing an execution UUID returns the persisted scoped receipt; RUNNING, FAILED and INTERRUPTED results never imply success or trigger replay."
    )
    limits = {
        "concurrency": 4,
        "input_canonical_json_bytes": 800000,
        "output_canonical_json_bytes": 1500000,
        "journal_records": 50000,
        "new_paid_provider_calls": 0,
    }
    item["resource_cost_limits"] = {
        **limits,
        "scope": "This adapter only. Electricity, subscriptions and separate governed provider workflows are not claimed free.",
    }
    item["observability_provenance"] = (
        "Persistent owner/tenant execution ID, source revision, contract version, input/result hashes and duration. OpenTelemetry fabric.execute span records fabric ID, operation and execution ID when telemetry is configured."
    )
    item["failure_fallback"] = (
        "Reject invalid contracts (422), missing resources (404), identity rebinding (409), timeout (408) or unavailable optional runtime/capacity (503). Journal failed/interrupted calls; do not silently substitute another capability or treat execution completion as verification."
    )
    item["tests_status"] = (
        "Source contract/runtime regression tests; current deployment capability requires independent fresh functional evidence. Schema validation alone is not operational verification."
    )
    item["notes"] = "Implemented for the listed operation scopes only. " + " ".join(item["limitations"])
    if identifier == "f06":
        item["notes"] += " grants_agent_authority=false; automatic_training=false."
    if identifier == "f07":
        item["notes"] += (
            " Fresh observation of an actual governed inference is required within 24 hours; a read-only observation initiates no new inference."
        )
    item["runtime_contract"] = {
        "version": runtime["version"],
        "endpoint": "/api/collective/v1/fabrics/" + identifier + "/execute",
        "interface_endpoint": "/interface/v1/collective/fabrics/" + identifier + "/execute",
        "method": "POST",
        "response_status": 200,
        "request_schema": deepcopy(item["input_schema"]),
        "response_schema": deepcopy(item["output_schema"]),
        "execution_receipt_schema": deepcopy(execution_receipt_schema(identifier, runtime)),
        "operations": operations,
        "limitations": deepcopy(item["limitations"]),
        "availability": "ADAPTER_INSTALLED_RUNTIME_PROBE_REQUIRED",
        "auth": item["auth"],
        "execution_id": "Optional in the POST request; required in persisted receipts. A supplied UUID is idempotent and bound to owner, tenant, operation and arguments.",
        "timeout_policy": item["timeout_policy"],
        "resource_limits": limits,
        "cost_policy": "No new paid provider calls from this execution adapter. Existing governed APIs separately enforce their explicit budgets.",
        "completion_semantics": "COMPLETED records successful execution only. It is not a capability verification or domain correctness verdict; a workflow result can independently report failures.",
        "error_statuses": [401, 403, 404, 405, 408, 409, 413, 422, 426, 429, 500, 503],
        "error_response_schema": _error_response_schema(),
    }


def load_fabric_registry():
    """Independent catalog snapshot; historical receipts never imply current health."""
    entries = _existing_contracts(deepcopy(_FABRICS))
    from .fabric_runtime import executable_contracts

    executable = executable_contracts()
    for item in entries:
        if item["state"] == "VERIFIED":
            item["recorded_historical_state"] = "VERIFIED"
            item["state"] = "IMPLEMENTED"
        item["verification"] = {"status": "UNVERIFIED", "reason": "CURRENT_FUNCTIONAL_RECEIPT_REQUIRED"}
        item["contract_status"] = "PARTIAL"
        runtime = executable.get(item["id"])
        if runtime:
            if item["state"] == "PROPOSED":
                item["state"] = "IMPLEMENTED"
            _runtime_contract(item, runtime)
    return {
        "registry_version": REGISTRY_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fabric_count": FABRIC_COUNT,
        "scope": "IMPLEMENTATION_CATALOG; attach recent source-bound functional receipts for runtime verification",
        "fabrics": validate_registry(entries),
    }


def registry_report(registry=None):
    """Compact summary suitable for dashboards and receipt hashing."""
    registry = registry or load_fabric_registry()
    counts = {state: 0 for state in STATES}
    for item in registry["fabrics"]:
        counts[item["state"]] += 1
    return {
        "registry_version": registry["registry_version"],
        "fabric_count": registry["fabric_count"],
        "state_counts": counts,
        "fabrics": [
            {
                "id": item["id"],
                "name": item["name"],
                "identifier": item["identifier"],
                "version": item["version"],
                "state": item["state"],
            }
            for item in registry["fabrics"]
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="ORQEVIA 36-fabric registry report")
    parser.add_argument("--json", metavar="PATH", help="write full registry JSON")
    parser.add_argument("--report", action="store_true", help="print summary report")
    args = parser.parse_args(argv)
    registry = load_fabric_registry()
    if args.json:
        Path(args.json).write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"registry": args.json, "fabric_count": registry["fabric_count"]}))
    if args.report:
        print(json.dumps(registry_report(registry), indent=2))
    if not args.json and not args.report:
        parser.error("pass --json PATH and/or --report")


if __name__ == "__main__":
    main()
