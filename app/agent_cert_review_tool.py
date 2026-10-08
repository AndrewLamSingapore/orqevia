"""Bounded registered semantic review; no authentication, signing or L7 grant.

The authenticated dispatcher owns actual queue/runtime reconciliation and must
invoke this operation under the chosen registered reviewer. A submitted hash or
LIVE_RUNTIME label alone never proves subject execution. The dispatcher owns
the immutable review artifact and durable action record produced afterwards.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import re
import uuid

from .agent_registry import agent_record, canonical_agent_id
from .agent_cert_role_review import (
    canonical_case_spec, canonical_role_spec, review_case_output, review_role_output,
)


_EXECUTION_FIELDS = {
    "schema_version", "agent_id", "capability_id", "dimension", "test_case",
    "source_revision", "runtime_image_id", "environment", "executor_identity",
    "case_spec", "dispatch", "job", "transport",
}
_JOB_FIELDS = {"id", "agent", "status", "result", "result_sha256", "provider",
               "attempts", "started_at", "completed_at", "error"}
_TRANSPORT_FIELDS = {"authentication", "dispatch_http_status", "job_http_status",
                     "provider_locality", "runtime_source_revision", "actual_runtime_image"}
_CLOUD_ROUTE_FIELDS = {"preferred_provider", "model", "allow_cloud", "data_classification",
                       "task_class", "classification", "max_retries", "max_cost_usd",
                       "prompt_sha256", "input_tokens", "output_tokens", "actual_cost_usd"}


class RoleReviewError(ValueError):
    """Fixed public error codes only, never caller context or credential text."""


def _deny(code):
    raise RoleReviewError(code) from None


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            _deny("DUPLICATE_FIELD")
        value[key] = item
    return value


def _finite(text):
    value = float(text)
    if not math.isfinite(value):
        _deny("NONFINITE_NUMBER")
    return value


def _json(text):
    value = json.loads(text, object_pairs_hook=_unique, parse_float=_finite,
                       parse_constant=lambda _: _deny("NONFINITE_NUMBER"))
    if type(value) is not dict:
        _deny("OBJECT_REQUIRED")
    return value


def _uuid(value):
    try:
        return type(value) is str and str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _time(value):
    if type(value) is not str or not 1 <= len(value) <= 40:
        _deny("EXECUTION_TIME_INVALID")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _deny("EXECUTION_TIME_INVALID")
    return parsed


def _cloud_execution(execution, canonical, source_revision):
    """Check the declared bounded variant, never grant Owner/cloud authority.

    The dispatcher must join every route value to the actual queue. The protected
    signer must separately rebuild this binding from its pinned Owner policy.
    PREPARED_NOT_EXECUTED remains preparation metadata, not execution evidence.
    """
    from .agent_cert_transport import (BINDING_SCHEMA, SUPPORTED_MODELS, PROVIDER_ID,
                                     case_transport_identity)
    extension = execution.get("cloud_transport")
    if type(extension) is not dict or set(extension) != {"binding", "queue_route"}:
        _deny("CLOUD_EXECUTION_INVALID")
    binding, route = extension["binding"], extension["queue_route"]
    identity = case_transport_identity(canonical)
    binding_fields = set(identity) | {
        "schema", "source_revision", "policy_sha256", "execution_request_sha256",
        "request_binding_sha256", "policy_version", "owner_authorization_ref",
        "canonical_data_classification", "execution_data_classification", "provider_id",
        "provider_kind", "model", "minimum_tier", "task_class", "limits", "state",
        "certification", "provider_qualification", "independent_attestation"}
    if (type(binding) is not dict or set(binding) != binding_fields
            or any(_canonical(binding.get(key)) != _canonical(value)
                   for key, value in identity.items())
            or binding.get("schema") != BINDING_SCHEMA
            or binding.get("source_revision") != source_revision
            or binding.get("canonical_data_classification") != "LOCAL_ONLY"
            or binding.get("execution_data_classification") != "CLOUD_PERMITTED"
            or binding.get("provider_id") != PROVIDER_ID
            or binding.get("provider_kind") != "huggingface"
            or type(binding.get("model")) is not str or binding["model"] not in SUPPORTED_MODELS
            or binding.get("task_class") != canonical["request"]["task_class"]
            or binding.get("state") != "PREPARED_NOT_EXECUTED"
            or binding.get("certification") != "UNVERIFIED"
            or binding.get("provider_qualification") != "NOT_ESTABLISHED_BY_TRANSPORT"
            or binding.get("independent_attestation") != "NOT_PERFORMED"
            or any(type(binding.get(key)) is not str
                   or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}", binding[key])
                   for key in ("policy_version", "owner_authorization_ref"))
            or any(type(binding.get(key)) is not str
                   or not re.fullmatch(r"[0-9a-f]{64}", binding[key])
                   for key in ("policy_sha256", "execution_request_sha256", "request_binding_sha256"))):
        _deny("CLOUD_BINDING_INVALID")
    limits = binding.get("limits")
    fixed = {"context_tokens": 4096, "output_tokens": 1024,
             "timeout_seconds": 35, "max_retries": 0, "concurrency_limit": 1}
    if (type(limits) is not dict or set(limits) != set(fixed) | {"max_cost_usd"}
            or any(type(limits.get(key)) is not int or limits[key] != value
                   for key, value in fixed.items())
            or type(limits.get("max_cost_usd")) not in (int, float)
            or not math.isfinite(limits["max_cost_usd"])
            or not 0 < limits["max_cost_usd"] <= 0.002):
        _deny("CLOUD_LIMITS_INVALID")
    from .compute_catalog import task_tier
    from .tier_router import Tier, required_tier
    original = canonical["request"]
    tier = max(Tier[original["minimum_tier"]], task_tier(original["objective"], original["task_class"]),
               required_tier(original["objective"], original["context"]))
    derived = {**original, "data_classification": "CLOUD_PERMITTED",
               "max_cost_usd": limits["max_cost_usd"], "preferred_provider": PROVIDER_ID,
               "minimum_tier": tier.name}
    digest_binding = {**identity, "source_revision": source_revision,
                      "policy_sha256": binding["policy_sha256"],
                      "execution_request_sha256": _sha(_canonical(derived))}
    if (binding.get("minimum_tier") != tier.name
            or binding["execution_request_sha256"] != digest_binding["execution_request_sha256"]
            or binding["request_binding_sha256"] != _sha(_canonical(digest_binding))):
        _deny("CLOUD_REQUEST_BINDING_INVALID")
    expected = {"preferred_provider": PROVIDER_ID, "model": binding["model"], "allow_cloud": 1,
                "data_classification": "CLOUD_PERMITTED", "task_class": original["task_class"],
                "classification": "R0", "max_retries": 0, "max_cost_usd": limits["max_cost_usd"]}
    if (type(route) is not dict or set(route) != _CLOUD_ROUTE_FIELDS
            or any(_canonical(route.get(key)) != _canonical(value) for key, value in expected.items())
            or type(route.get("prompt_sha256")) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", route["prompt_sha256"])
            or type(route.get("input_tokens")) is not int or not 0 <= route["input_tokens"] <= 4096
            or type(route.get("output_tokens")) is not int or not 0 <= route["output_tokens"] <= 1024
            or type(route.get("actual_cost_usd")) not in (int, float)
            or not math.isfinite(route["actual_cost_usd"])
            or not 0 <= route["actual_cost_usd"] <= limits["max_cost_usd"]
            or execution["job"].get("provider") != PROVIDER_ID
            or type(execution["job"].get("attempts")) is not int or execution["job"]["attempts"] != 1):
        _deny("CLOUD_ROUTE_INVALID")


def execute_role_review(context: str, *, reviewer_id: str, capability_id: str,
                        source_revision: str, task_id: str) -> dict:
    """Review exact public case facts under a separate registered actor.

    Only case quality is judged here. Caller-supplied execution metadata must
    separately match the owning queue/runtime and protected signing inputs.
    The raw answer/context never enters this returned review record.
    """
    try:
        if (type(context) is not str or not 1 <= len(context.encode("utf-8")) <= 65_536
                or type(source_revision) is not str
                or not re.fullmatch(r"[0-9a-f]{40}", source_revision) or not _uuid(task_id)):
            _deny("REVIEW_INPUT_INVALID")
        payload = _json(context)
        if set(payload) != {"execution", "expected_execution_sha256",
                            "expected_source_revision", "review_nonce"}:
            _deny("REVIEW_INPUT_FIELDS_INVALID")
        execution = payload["execution"]
        if (type(execution) is not dict
                or set(execution) not in (_EXECUTION_FIELDS, _EXECUTION_FIELDS | {"cloud_transport"})
                or payload["expected_source_revision"] != source_revision
                or execution.get("source_revision") != source_revision
                or type(payload["expected_execution_sha256"]) is not str
                or not re.fullmatch(r"[0-9a-f]{64}", payload["expected_execution_sha256"])
                or payload["expected_execution_sha256"] != _sha(_canonical(execution))
                or not _uuid(payload["review_nonce"])):
            _deny("EXECUTION_SOURCE_OR_DIGEST_INVALID")
        subject, subject_cap = execution.get("agent_id"), execution.get("capability_id")
        if (type(subject) is not str or canonical_agent_id(subject) != subject
                or type(subject_cap) is not str
                or subject_cap not in agent_record(subject)["capability_requirements"]):
            _deny("SUBJECT_IDENTITY_INVALID")
        actor = "a18" if subject == "a26" else "a26"
        actor_cap = "responsibility.a27" if subject == "a26" else "responsibility.a26"
        if (reviewer_id != actor or capability_id != actor_cap or reviewer_id == subject
                or canonical_agent_id(reviewer_id) != reviewer_id
                or capability_id not in agent_record(reviewer_id)["capability_requirements"]
                or agent_record(reviewer_id)["authority"] != "advisory"):
            _deny("INDEPENDENT_REVIEWER_REQUIRED")
        dimension, test_case = execution.get("dimension"), execution.get("test_case")
        if (type(dimension) is not str or type(test_case) is not str
                or not re.fullmatch(r"[a-z_]{1,40}", dimension)
                or not re.fullmatch(r"[a-z_]{1,40}", test_case)):
            _deny("CASE_BINDING_INVALID")
        case_id = dimension + ":" + test_case
        # Preserve the exact legacy role-normal path as well as its API.
        canonical = (canonical_role_spec(subject, subject_cap) if case_id == "role:normal"
                     else canonical_case_spec(subject, subject_cap, case_id))
        image = execution.get("runtime_image_id")
        if (execution.get("schema_version") != "prime.agent-certification.execution.v1"
                or canonical.get("case") != case_id
                or execution.get("executor_identity") != subject
                or execution.get("environment") != "LIVE_RUNTIME"
                or _canonical(execution.get("case_spec")) != _canonical(canonical)
                or type(image) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", image)):
            _deny("CASE_BINDING_INVALID")
        job = execution["job"]
        if (type(job) is not dict or set(job) != _JOB_FIELDS or not _uuid(job.get("id"))
                or job["id"] == task_id or job.get("agent") != subject
                or job.get("status") != "completed"
                or not (job["error"] is None or (type(job["error"]) is str and job["error"] == ""))
                or type(job.get("attempts")) is not int or not 1 <= job["attempts"] <= 3
                or type(job.get("provider")) is not str
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", job["provider"])
                or type(job.get("result")) is not str
                or not 1 <= len(job["result"].encode("utf-8")) <= 16_384
                or job.get("result_sha256") != _sha(job["result"].encode("utf-8"))):
            _deny("SUBJECT_JOB_INVALID")
        dispatch = {"capability": subject_cap, "job": {"id": job["id"], "agent": subject}}
        if _canonical(execution["dispatch"]) != _canonical(dispatch):
            _deny("DISPATCH_BINDING_INVALID")
        transport = execution["transport"]
        if (type(transport) is not dict or set(transport) != _TRANSPORT_FIELDS
                or transport.get("authentication") != "OWNER_AUTHENTICATED"
                or type(transport.get("dispatch_http_status")) is not int
                or transport["dispatch_http_status"] != 202
                or type(transport.get("job_http_status")) is not int or transport["job_http_status"] != 200
                or transport.get("provider_locality") not in {"LOCAL", "CLOUD"}
                or transport.get("runtime_source_revision") != source_revision
                or transport.get("actual_runtime_image") != image):
            _deny("TRANSPORT_BINDING_INVALID")
        if "cloud_transport" in execution:
            if transport["provider_locality"] != "CLOUD":
                _deny("CLOUD_TRANSPORT_REQUIRED")
            _cloud_execution(execution, canonical, source_revision)
        elif transport["provider_locality"] != "LOCAL":
            _deny("CLOUD_BINDING_REQUIRED")
        now = datetime.now(timezone.utc)
        if not _time(job["started_at"]) <= _time(job["completed_at"]) <= now:
            _deny("EXECUTION_TIME_INVALID")
        _json(job["result"])
        passed, errors = (review_role_output(subject, subject_cap, job["result"])
                          if case_id == "role:normal" else
                          review_case_output(subject, subject_cap, case_id, job["result"]))
        if (type(passed) is not bool or type(errors) is not tuple or len(errors) > 32
                or any(type(code) is not str or not re.fullmatch(r"[A-Za-z0-9_]{1,80}", code)
                       for code in errors) or (passed and errors)):
            _deny("ORACLE_CONTRACT_INVALID")
        from .agent_cert_secondary_roles import SUPPORTED_CAPABILITIES, ORACLE_ID as SECONDARY_ORACLE
        oracle_id = (SECONDARY_ORACLE if subject_cap in SUPPORTED_CAPABILITIES else
                     canonical["oracle_id"] if case_id != "role:normal" else
                     "group_two_exact_role_oracle/v1" if "group_two_exact_role_oracle" in
                     canonical["independent_review"] else "existing.role-normal.v1")
        return {
            "schema_version": "prime.agent-cert-role-review.v1", "task_id": task_id,
            "reviewer_id": reviewer_id, "reviewer_capability_id": capability_id,
            "subject_agent_id": subject, "subject_capability_id": subject_cap,
            "dimension": dimension, "test_case": test_case, "source_revision": source_revision,
            "runtime_image_id": image, "subject_job_id": job["id"],
            "review_nonce": payload["review_nonce"], "reviewed_at": now.isoformat(),
            "execution_evidence_sha256": payload["expected_execution_sha256"],
            "case_spec_sha256": _sha(_canonical(canonical)), "result_sha256": job["result_sha256"],
            "oracle_id": oracle_id, "test_result": "PASS" if passed else "FAIL",
            "review_errors": errors, "model_calls": 0, "execution_model": "DETERMINISTIC",
            "subject_execution_verification": "DOMAIN_JOIN_REQUIRED", "certification": "UNVERIFIED",
        }
    except RoleReviewError:
        raise
    except Exception:
        # Exceptions may include caller result text, paths or credentials.
        _deny("ROLE_REVIEW_REJECTED")
