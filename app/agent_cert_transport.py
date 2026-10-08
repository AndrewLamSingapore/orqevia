"""Pure, caller-authorized cloud transport for explicit synthetic case oracles.

The protected caller must independently obtain/pin the Owner policy digest and
the actual runtime source revision. An agent-supplied policy or digest is NOT
authorization. This module neither authenticates callers nor qualifies models,
loads catalogs, executes work, signs evidence, or grants certification.

The original local challenge is retained exactly. Only an explicitly authorized
transport variant is derived; the existing role/oracle and task class are never
relabelled as classification. Runtime admission, price/reservation, capability
authority, authenticated dispatch and independent review remain mandatory.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass

from .agent_cert_cases import challenge
from .agent_registry import agent_record, responsibility_owner
from .compute_catalog import task_tier
from .tier_router import Tier, classify_for_cloud, required_tier


POLICY_SCHEMA = "prime.agent-cert-cloud-policy.v1"
BINDING_SCHEMA = "prime.agent-cert-cloud-binding.v1"
PROVIDER_ID = "hf-qwen-certification"
MODEL = "Qwen/Qwen3-32B:deepinfra"
SUPPORTED_MODELS = frozenset({MODEL, "Qwen/Qwen3-235B-A22B-Instruct-2507:novita"})
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}\Z")
_GROUP_TWO = frozenset({"a15", "a16", "a19", "a20", "a26"})
_ORACLES = {
    "a01": "exact_numeric_oracle", "a04": "exact_weighted_oracle",
    "a05": "exact_portfolio_oracle", "a12": "exact_rate_oracle",
    "a14": "exact_data_quality_oracle", "a17": "exact_a17_boundary_oracle",
    "a18": "exact_zero_boundary_oracle", "a21": "exact_cost_oracle",
    "a28": "exact_risk_oracle", "a29": "exact_release_oracle",
    **{agent: "exact_role_g1_oracle" for agent in
       ("a02", "a06", "a07", "a09", "a10", "a13")},
    **{agent: "group_two_exact_role_oracle/v1" for agent in _GROUP_TWO},
}
_POLICY_KEYS = frozenset({
    "schema", "policy_version", "owner_authorization_ref", "source_revision",
    "agent_id", "capability_id", "case", "oracle_id", "canonical_spec_sha256",
    "data_classification", "public_synthetic", "provider_id", "provider_kind",
    "model", "minimum_tier", "max_cost_usd", "context_tokens", "output_tokens",
    "timeout_seconds", "max_retries", "concurrency_limit",
})


def _json(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("transport data must be finite JSON") from None


def transport_digest(value: object) -> str:
    """Canonical typed JSON digest; hashing a policy does not authorize it."""
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def canonical_role_case(agent_id: str, capability_id: str,
                        case_id: str = "role:normal") -> dict:
    """Return a fresh current-source role challenge, not an execution/PASS record.

    Only existing source-owned primary or explicit secondary role:normal
    oracles are supported. Generic/unseen cases never acquire a borrowed
    oracle. Source support grants neither Owner consent nor provider admission.
    """
    if (type(agent_id) is not str or agent_id not in _ORACLES
            or type(capability_id) is not str
            or type(case_id) is not str or case_id != "role:normal"
            or responsibility_owner(capability_id) != agent_id
            or capability_id not in agent_record(agent_id)["capability_requirements"]):
        raise ValueError("unsupported registered case/oracle")
    secondary = capability_id != f"responsibility.{agent_id}"
    if secondary:
        from .agent_cert_secondary_roles import (
            CASE_VERSION, ORACLE_ID, SUPPORTED_CAPABILITIES, canonical_secondary_spec,
        )
        if SUPPORTED_CAPABILITIES.get(capability_id) != agent_id:
            raise ValueError("unsupported registered case/oracle")
        spec = canonical_secondary_spec(agent_id, capability_id)
        if spec.get('case_version') != CASE_VERSION or spec.get('oracle_id') != ORACLE_ID:
            raise ValueError("canonical public synthetic oracle unavailable")
        marker = 'exact_secondary_role_oracle'
        public_prefix = f'PUBLIC SYNTHETIC source={CASE_VERSION}; facts='
    elif agent_id in _GROUP_TWO:
        # Lazy import avoids a cycle when the existing observer uses this module.
        from .agent_cert_role_group_two import role_case
        spec = role_case(agent_id)
        marker = "group_two_exact_role_oracle"
        public_prefix = 'SYNTHETIC'
    else:
        spec = challenge(case_id, agent_id=agent_id, capability_id=capability_id)
        marker = _ORACLES[agent_id]
        public_prefix = 'SYNTHETIC'
    request = spec["request"]
    if (marker not in spec["independent_review"]
            or spec["certification"] != "UNVERIFIED"
            or request.get("response_format") != "strict_json"
            or request.get("task_class") != "planning"
            or request.get("classification") != "R0"
            or request.get("data_classification") != "LOCAL_ONLY"
            or type(request.get("max_cost_usd")) is not int
            or request["max_cost_usd"] != 0
            or (secondary and request.get('minimum_tier') != 'MINI')
            or not request["context"].startswith(public_prefix)
            or not classify_for_cloud("CLOUD_PERMITTED",
                                      request["objective"] + "\n" + request["context"])):
        raise ValueError("canonical public synthetic oracle unavailable")
    return spec


def case_transport_identity(spec: dict) -> dict:
    """Public binding fields for an independently authorized policy."""
    if type(spec) is not dict:
        raise ValueError("canonical case required")
    canonical = canonical_cert_case(spec.get("agent_id"), spec.get("capability_id"),
                                    spec.get("case"))
    if _json(spec) != _json(canonical):
        raise ValueError("canonical case was modified")
    oracle = _ORACLES[canonical["agent_id"]]
    if canonical['capability_id'] != f"responsibility.{canonical['agent_id']}":
        from .agent_cert_secondary_roles import ORACLE_ID
        oracle = ORACLE_ID
    elif canonical["case"] != "role:normal":
        # Each source-owned family retains its own grader identity. Never
        # lend an older quality oracle to a new/general/event challenge.
        oracle = canonical['oracle_id']
    return {"agent_id": canonical["agent_id"],
            "capability_id": canonical["capability_id"],
            "case": canonical["case"], "oracle_id": oracle,
            "canonical_spec_sha256": transport_digest(canonical)}


def canonical_cert_case(agent_id: str, capability_id: str,
                        case_id: str = "role:normal") -> dict:
    """Existing role or one explicit source-owned public A19 quality adapter.

    No generic challenge acquires an oracle. Advisory case descriptions do not
    prove actual tool, recovery or audit events. Higher task tiers stay intact.
    """
    if type(case_id) is str and case_id == "role:normal":
        return canonical_role_case(agent_id, capability_id, case_id)
    from .agent_cert_a19_cases import CASE_VERSION, ORACLE_ID, SUPPORTED_CASES
    from .agent_cert_a19_general import (CASE_VERSION as GENERAL_VERSION,
        ORACLE_ID as GENERAL_ORACLE, SUPPORTED_CASES as GENERAL_CASES)
    from .agent_cert_a19_baseline import (CASE_VERSION as BASELINE_VERSION,
        ORACLE_ID as BASELINE_ORACLE, SUPPORTED_CASES as BASELINE_CASES)
    schema = 'prime.a19-public-quality-input.v1'
    if type(case_id) is str and case_id in GENERAL_CASES:
        CASE_VERSION, ORACLE_ID = GENERAL_VERSION, GENERAL_ORACLE
        schema = 'prime.a19-general-quality-input.v1'
    if type(case_id) is str and case_id in BASELINE_CASES:
        CASE_VERSION, ORACLE_ID = BASELINE_VERSION, BASELINE_ORACLE
        schema = 'prime.a19-baseline-quality-input.v1'
    supported = (*SUPPORTED_CASES, *GENERAL_CASES, *BASELINE_CASES)
    if (type(agent_id) is not str or agent_id != "a19" or
            type(capability_id) is not str or capability_id != "responsibility.a19" or
            type(case_id) is not str or case_id not in supported or
            responsibility_owner(capability_id) != agent_id or
            capability_id not in agent_record(agent_id)["capability_requirements"]):
        raise ValueError("unsupported registered case/oracle")
    from .agent_cert_role_review import canonical_case_spec
    canonical = canonical_case_spec(agent_id, capability_id, case_id)
    request = canonical["request"]
    expected_request = challenge(case_id, agent_id=agent_id, capability_id=capability_id)["request"]
    try:
        context = json.loads(request["context"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("canonical public synthetic oracle unavailable") from None
    if (canonical.get("oracle_id") != ORACLE_ID or canonical.get("case_version") != CASE_VERSION
            or ORACLE_ID not in canonical["independent_review"]
            or canonical["certification"] != "UNVERIFIED"
            or request.get("response_format") != "strict_json"
            or request.get("task_class") != expected_request["task_class"]
            or request.get("minimum_tier") != expected_request["minimum_tier"]
            or request.get("classification") != "R0"
            or request.get("data_classification") != "LOCAL_ONLY"
            or type(request.get("max_cost_usd")) is not int or request["max_cost_usd"] != 0
            or type(context) is not dict
            or context.get("schema") != schema
            or context.get("data_scope") != "PUBLIC_SYNTHETIC_ONLY"
            or context.get("case_id") != case_id or context.get("case_version") != CASE_VERSION
            or not classify_for_cloud("CLOUD_PERMITTED", request["objective"] + "\n" + request["context"])):
        raise ValueError("canonical public synthetic oracle unavailable")
    return canonical


@dataclass(frozen=True)
class CertificationTransport:
    """Immutable JSON bytes; accessors return copies, not mutable authority."""
    canonical_spec_json: str
    execution_request_json: str
    preparation_receipt_json: str

    def canonical_spec(self) -> dict:
        stored = json.loads(self.canonical_spec_json)
        canonical = canonical_cert_case(stored.get("agent_id"), stored.get("capability_id"),
                                        stored.get("case"))
        if _json(canonical) != self.canonical_spec_json:
            raise ValueError("current canonical challenge changed")
        # Preserve the existing tuple-valued review/discriminant contract too,
        # so an unmodified existing observer sees the exact canonical spec.
        return canonical

    def request(self) -> dict:
        return json.loads(self.execution_request_json)

    def receipt(self) -> dict:
        return json.loads(self.preparation_receipt_json)


def bind_cloud_case(spec: dict, policy: dict, *, expected_source_revision: str,
                    expected_policy_sha256: str) -> CertificationTransport:
    """Bind one exact source-owned challenge to protected Owner consent.

    ``expected_*`` MUST come from the authenticated operator/caller boundary,
    never from agent request fields. Limits are a required execution contract,
    not new dispatch kwargs or proof that a runtime has applied them.
    """
    if (type(expected_source_revision) is not str
            or not _HEX40.fullmatch(expected_source_revision)
            or type(expected_policy_sha256) is not str
            or not _HEX64.fullmatch(expected_policy_sha256)
            or type(policy) is not dict or set(policy) != _POLICY_KEYS):
        raise ValueError("protected source/policy binding required")
    # Typed canonicalization rejects bool/int equality tricks and nonfinite data.
    if transport_digest(policy) != expected_policy_sha256:
        raise ValueError("Owner policy digest mismatch")
    identity = case_transport_identity(spec)
    if (policy.get("schema") != POLICY_SCHEMA
            or policy.get("source_revision") != expected_source_revision
            or any(type(policy.get(key)) is not str or not _REFERENCE.fullmatch(policy[key])
                   for key in ("policy_version", "owner_authorization_ref"))
            or any(type(policy.get(key)) is not str or policy[key] != value
                   for key, value in identity.items())
            or policy.get("data_classification") != "CLOUD_PERMITTED"
            or type(policy.get("public_synthetic")) is not bool
            or policy["public_synthetic"] is not True
            or policy.get("provider_id") != PROVIDER_ID
            or policy.get("provider_kind") != "huggingface"
            or type(policy.get("model")) is not str or policy["model"] not in SUPPORTED_MODELS):
        raise ValueError("Owner policy scope mismatch")
    fixed_limits = {"context_tokens": 4096, "output_tokens": 1024,
                    "timeout_seconds": 35, "max_retries": 0, "concurrency_limit": 1}
    if any(type(policy.get(key)) is not int or policy[key] != value
           for key, value in fixed_limits.items()):
        raise ValueError("bounded transport limits required")
    cost = policy.get("max_cost_usd")
    if (type(cost) not in (int, float) or not math.isfinite(cost)
            or not 0 < cost <= 0.002):
        raise ValueError("bounded explicit cloud cost required")
    base = spec["request"]
    tier = max(Tier[base["minimum_tier"]],
               task_tier(base["objective"], base["task_class"]),
               required_tier(base["objective"], base["context"]))
    if type(policy.get("minimum_tier")) is not str or policy["minimum_tier"] != tier.name:
        raise ValueError("canonical required tier must be preserved")
    request = {**base, "data_classification": "CLOUD_PERMITTED",
               "max_cost_usd": cost, "preferred_provider": PROVIDER_ID,
               "minimum_tier": tier.name}
    request_sha = transport_digest(request)
    binding = {**identity, "source_revision": expected_source_revision,
               "policy_sha256": expected_policy_sha256,
               "execution_request_sha256": request_sha}
    receipt = {"schema": BINDING_SCHEMA, **binding,
               "request_binding_sha256": transport_digest(binding),
               "policy_version": policy["policy_version"],
               "owner_authorization_ref": policy["owner_authorization_ref"],
               "canonical_data_classification": "LOCAL_ONLY",
               "execution_data_classification": "CLOUD_PERMITTED",
               "provider_id": PROVIDER_ID, "provider_kind": "huggingface", "model": policy["model"],
               "minimum_tier": tier.name, "task_class": base["task_class"],
               "limits": {**fixed_limits, "max_cost_usd": cost},
               "state": "PREPARED_NOT_EXECUTED", "certification": "UNVERIFIED",
               "provider_qualification": "NOT_ESTABLISHED_BY_TRANSPORT",
               "independent_attestation": "NOT_PERFORMED"}
    return CertificationTransport(_json(spec), _json(request), _json(receipt))


def validate_cloud_binding(spec: dict, policy: dict, binding: CertificationTransport,
                           *, expected_source_revision: str,
                           expected_policy_sha256: str) -> CertificationTransport:
    """Rebuild from current contracts before a protected caller dispatches."""
    expected = bind_cloud_case(spec, policy,
                               expected_source_revision=expected_source_revision,
                               expected_policy_sha256=expected_policy_sha256)
    if type(binding) is not CertificationTransport or binding != expected:
        raise ValueError("prepared cloud binding changed")
    return expected
