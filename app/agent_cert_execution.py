"""Bounded live case observation without grading or certification authority.

The caller injects authenticated dispatch and job-read functions from the
existing runtime. Raw model output stays within this process and is never
returned by this observer. Case-specific oracles may reject an output, but
cannot sign evidence or grant L1-L7 status.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from .agent_cert_numeric import review_priority_json
from .agent_cert_rates import review_rate_json
from .agent_cert_weighted import review_weighted_json
from .agent_cert_boundary import review_zero_boundary_json
from .agent_cert_a17_boundary import review_a17_boundary_json
from .agent_cert_data_quality import review_data_quality_json
from .agent_cert_portfolio import review_portfolio_json
from .agent_cert_cost import review_cost_json
from .agent_cert_risk import review_risk_json
from .agent_cert_release import review_release_json
from .agent_cert_role_g1 import SOURCES as ROLE_G1_SOURCES, review_role_json
from .agent_cert_cases import challenge
from .agent_registry import agent_record, responsibility_owner
from .agent_cert_transport import CertificationTransport, validate_cloud_binding


_PROVIDER = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_TERMINAL = frozenset({"completed", "failed", "cancelled", "budget_blocked"})
_A01_SOURCE = {
    "capacity_days": 3, "alpha_days": 3, "alpha_total_points": 8,
    "beta_days": 2, "beta_total_points": 6,
}
_A12_SOURCE = {"week1_failures": 10, "week1_requests": 100,
               "week2_failures": 15, "week2_requests": 300}
_A04_SOURCE = {"reliability_weight": 2, "speed_weight": 1,
               "a_reliability": 4, "a_speed": 1,
               "b_reliability": 2, "b_speed": 5}
_A14_SOURCE = [{"id": 1, "amount": 5}, {"id": 1, "amount": 5},
               {"id": 2, "amount": -3}]
_A05_SOURCE = {"available_slots": 1, "p_slots": 1, "q_slots": 1,
               "p_expected_value": 8, "q_expected_value": 5}
_A21_SOURCE = {"fixed_cost": 100, "variable_cost_per_unit": 3, "volume": 20}
_A28_SOURCE = {"a_likelihood": 2, "a_impact": 5,
               "b_likelihood": 4, "b_impact": 2}
_A29_SOURCE = {"source_revision": "abc123", "historical_deployment_revision": "def456",
               "source_tests_pass": True, "current_runtime_receipt_present": False}


def _time(value: object) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate report key")
        value[key] = item
    return value


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _runtime_identity(value, source_revision):
    if not isinstance(value, dict):
        return None
    identity = {key: value.get(key) for key in
                ("host_id", "source_revision", "version", "image_digest")}
    if (identity["source_revision"] != source_revision
            or not isinstance(identity["host_id"], str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", identity["host_id"])
            or identity["host_id"] == "UNKNOWN"
            or not isinstance(identity["version"], str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", identity["version"])
            or identity["version"] == "UNKNOWN"
            or not isinstance(identity["image_digest"], str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", identity["image_digest"])):
        return None
    return identity


def _cloud_job_binding(row, receipt, *, completed=False):
    """Bind authenticated queue observations, never manufacture admission.

    The outer queue timeout can exceed the catalog's 35-second execution cap;
    it is not evidence of the provider's effective deadline. Catalog limits and
    current price/reservation admission remain the protected caller's contract.
    """
    if not isinstance(row, dict):
        return None
    cost = row.get("max_cost_usd")
    prompt = row.get("prompt")
    if (row.get("preferred_provider") != receipt["provider_id"]
            or row.get("model") != receipt["model"]
            or type(row.get("allow_cloud")) is not int or row["allow_cloud"] != 1
            or row.get("data_classification") != "CLOUD_PERMITTED"
            or row.get("task_class") != receipt["task_class"]
            or row.get("classification") != "R0"
            or type(row.get("max_retries")) is not int or row["max_retries"] != 0
            or type(cost) not in (int, float) or not math.isfinite(cost)
            or not 0 < cost <= receipt["limits"]["max_cost_usd"]
            or type(prompt) is not str or not prompt or len(prompt) > 80_000):
        return None
    if row.get("status") in {"running", "completed"} and row.get("provider") != receipt["provider_id"]:
        return None
    if completed:
        if row.get("provider") != receipt["provider_id"] or type(row.get("attempts")) is not int or row["attempts"] != 1:
            return None
        for field in ("input_tokens", "output_tokens"):
            value = row.get(field)
            if value is not None and (type(value) is not int or value < 0):
                return None
        output = row.get("output_tokens")
        if output is not None and output > receipt["limits"]["output_tokens"]:
            return None
        actual = row.get("actual_cost_usd")
        if actual is not None and (type(actual) not in (int, float)
                or not math.isfinite(actual) or not 0 <= actual <= cost):
            return None
    return {"preferred_provider": row["preferred_provider"], "model": row["model"],
            "allow_cloud": row["allow_cloud"],
            "data_classification": row["data_classification"],
            "task_class": row["task_class"], "classification": row["classification"],
            "max_retries": row["max_retries"], "max_cost_usd": cost,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()}


def _observe_runtime_artifact(spec, base, *, dispatch, get_artifact, get_runtime,
                              expected_source_revision, expected_registry_sha256,
                              started, timeout_seconds, monotonic, wall_clock):
    """Join the existing zero-model artifact path, not a manufactured queue row.

    Dependencies must be authenticated domain reads supplied by the caller.
    The source is an observed runtime binding, not independent deployment or
    certification attestation. Raw artifact sections never leave this observer.
    """
    if spec != challenge("baseline:identity", agent_id="a19",
                         capability_id="responsibility.a19"):
        return {**base, "state": "REJECTED", "reason": "runtime_case_source_mismatch"}
    if (not callable(get_artifact) or not callable(get_runtime)
            or not isinstance(expected_source_revision, str)
            or not re.fullmatch(r"[0-9a-f]{40}", expected_source_revision)
            or not isinstance(expected_registry_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_registry_sha256)):
        return {**base, "state": "REJECTED", "reason": "runtime_evidence_reader_missing"}
    began = wall_clock()
    if not isinstance(began, datetime) or began.tzinfo is None:
        return {**base, "state": "REJECTED", "reason": "observation_time_missing"}
    before = _runtime_identity(get_runtime(), expected_source_revision)
    if before is None:
        return {**base, "state": "REJECTED", "reason": "runtime_identity_missing"}
    reply = dispatch(spec["request"])
    if (not isinstance(reply, dict) or set(reply) != {
            "task_id", "state", "artifact", "model_calls", "execution_model",
            "agent_id", "capability", "runtime_source_revision"}
            or reply.get("state") != "COMPLETED"
            or reply.get("execution_model") != "DETERMINISTIC"
            or reply.get("agent_id") != "a19"
            or reply.get("capability") != "responsibility.a19"
            or reply.get("runtime_source_revision") != expected_source_revision
            or type(reply.get("model_calls")) is not int or reply["model_calls"] != 0):
        return {**base, "state": "REJECTED", "reason": "deterministic_dispatch_invalid"}
    task_id, declared = reply.get("task_id"), reply.get("artifact")
    if (not isinstance(task_id, str)
            or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", task_id)
            or not isinstance(declared, dict)):
        return {**base, "state": "REJECTED", "reason": "artifact_identity_mismatch"}
    artifact_id = declared.get("artifact_id")
    if not isinstance(artifact_id, str) or not re.fullmatch(r"[0-9a-f]{32}", artifact_id):
        return {**base, "state": "REJECTED", "reason": "artifact_identity_mismatch"}
    if monotonic() - started >= timeout_seconds:
        return {**base, "state": "INCOMPLETE", "reason": "bounded_timeout"}
    retrieved = get_artifact(artifact_id)
    if (not isinstance(retrieved, tuple) or len(retrieved) != 2
            or not isinstance(retrieved[0], dict) or type(retrieved[1]) is not bytes):
        return {**base, "state": "REJECTED", "reason": "artifact_read_invalid"}
    metadata, raw = retrieved
    if (len(raw) == 0 or len(raw) > 200_000
            or len(_canonical(metadata)) > 16_384
            or _canonical(metadata) != _canonical(declared)
            or metadata.get("artifact_id") != artifact_id
            or metadata.get("task_id") != task_id
            or metadata.get("creator_agents") != ["a19"]
            or metadata.get("type") != "json"
            or metadata.get("runtime_revision") != expected_source_revision
            or metadata.get("validation_state") != "STRUCTURE_VALIDATED"
            or metadata.get("delivery_state") != "AVAILABLE"
            or metadata.get("location") != "artifact.json"
            or type(metadata.get("bytes")) is not int or metadata["bytes"] != len(raw)
            or metadata.get("sha256") != hashlib.sha256(raw).hexdigest()):
        return {**base, "state": "REJECTED", "reason": "artifact_binding_mismatch"}
    report = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite report")))
    from .runtime_status import validate_report
    validate_report(report)
    captured, artifact_time = _time(report.get("captured_at")), _time(metadata.get("timestamp"))
    registry = report.get("registry", {})
    if (report.get("task_id") != task_id
            or captured is None or artifact_time is None or captured < began
            or artifact_time < captured
            or registry.get("status") != "OBSERVED"
            or type(registry.get("agent_count")) is not int or registry["agent_count"] != 21
            or registry.get("source_sha256") != expected_registry_sha256
            or report.get("execution") != {
                "model_calls": 0, "input_tokens": 0, "output_tokens": 0,
                "method": "DETERMINISTIC_READ_ONLY", "fresh_inference_performed": False}
            or any(type(report["execution"].get(key)) is not int
                   for key in ("model_calls", "input_tokens", "output_tokens"))
            or type(report["execution"].get("fresh_inference_performed")) is not bool):
        return {**base, "state": "REJECTED", "reason": "runtime_report_binding_mismatch"}
    after = _runtime_identity(get_runtime(), expected_source_revision)
    ended = wall_clock()
    if after is None or _canonical(before) != _canonical(after):
        return {**base, "state": "REJECTED", "reason": "runtime_identity_changed"}
    if not isinstance(ended, datetime) or ended.tzinfo is None or artifact_time > ended:
        return {**base, "state": "REJECTED", "reason": "observation_time_invalid"}
    if monotonic() - started >= timeout_seconds:
        return {**base, "state": "INCOMPLETE", "reason": "bounded_timeout"}
    return {**base, "state": "EXECUTED", "execution_model": "DETERMINISTIC",
            "task_id": task_id, "artifact_id": artifact_id, "model_calls": 0,
            "source_revision": expected_source_revision,
            "registry_sha256": expected_registry_sha256,
            "runtime_identity_sha256": hashlib.sha256(_canonical(before)).hexdigest(),
            "result_sha256": metadata["sha256"], "artifact_metadata_sha256":
            hashlib.sha256(_canonical(metadata)).hexdigest(),
            "started_at": began.isoformat(), "completed_at": ended.isoformat(),
            "captured_at": captured.isoformat(),
            "case_review": "RUNTIME_STATUS_ARTIFACT_CHECK_PASS", "review_errors": ()}


def _observe_initialization_artifact(spec, base, *, dispatch, get_artifact, get_runtime,
                                     expected_source_revision, expected_registry_sha256,
                                     started, timeout_seconds, monotonic, wall_clock):
    """Observe the distinct owned-contract inspection, never an identity clone."""
    from .agent_cert_initialization import MAX_BYTES, validate_initialization_report
    agent, capability = spec.get('agent_id'), spec.get('capability_id')
    if _canonical(spec) != _canonical(challenge('baseline:initialization', agent_id=agent,
                                                capability_id=capability)):
        return {**base, 'state': 'REJECTED', 'reason': 'initialization_case_source_mismatch'}
    if (not callable(get_artifact) or not callable(get_runtime)
            or type(expected_source_revision) is not str
            or re.fullmatch('[0-9a-f]{40}', expected_source_revision) is None
            or type(expected_registry_sha256) is not str
            or re.fullmatch('[0-9a-f]{64}', expected_registry_sha256) is None):
        return {**base, 'state': 'REJECTED', 'reason': 'initialization_evidence_reader_missing'}
    began = wall_clock()
    if type(began) is not datetime or began.tzinfo is None or began.utcoffset() is None:
        return {**base, 'state': 'REJECTED', 'reason': 'observation_time_missing'}
    before = _runtime_identity(get_runtime(), expected_source_revision)
    if before is None:
        return {**base, 'state': 'REJECTED', 'reason': 'runtime_identity_missing'}
    if monotonic() - started >= timeout_seconds:
        return {**base, 'state': 'INCOMPLETE', 'reason': 'bounded_timeout'}
    reply = dispatch(spec['request'])
    if (type(reply) is not dict or set(reply) != {'task_id', 'state', 'artifact', 'model_calls',
            'execution_model', 'agent_id', 'capability', 'runtime_source_revision'}
            or reply.get('state') != 'COMPLETED' or reply.get('execution_model') != 'DETERMINISTIC'
            or reply.get('agent_id') != agent or reply.get('capability') != capability
            or reply.get('runtime_source_revision') != expected_source_revision
            or type(reply.get('model_calls')) is not int or reply['model_calls'] != 0):
        return {**base, 'state': 'REJECTED', 'reason': 'deterministic_dispatch_invalid'}
    task, declared = reply.get('task_id'), reply.get('artifact')
    if (type(task) is not str
            or re.fullmatch('[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', task) is None
            or type(declared) is not dict):
        return {**base, 'state': 'REJECTED', 'reason': 'artifact_identity_mismatch'}
    artifact_id = declared.get('artifact_id')
    if type(artifact_id) is not str or re.fullmatch('[0-9a-f]{32}', artifact_id) is None:
        return {**base, 'state': 'REJECTED', 'reason': 'artifact_identity_mismatch'}
    if monotonic() - started >= timeout_seconds:
        return {**base, 'state': 'INCOMPLETE', 'reason': 'bounded_timeout'}
    retrieved = get_artifact(artifact_id)
    if (type(retrieved) is not tuple or len(retrieved) != 2
            or type(retrieved[0]) is not dict or type(retrieved[1]) is not bytes):
        return {**base, 'state': 'REJECTED', 'reason': 'artifact_read_invalid'}
    metadata, raw = retrieved
    if monotonic() - started >= timeout_seconds:
        return {**base, 'task_id': task, 'artifact_id': artifact_id,
                'state': 'INCOMPLETE', 'reason': 'bounded_timeout'}
    if (not 0 < len(raw) <= MAX_BYTES or len(_canonical(metadata)) > 16384
            or _canonical(metadata) != _canonical(declared)
            or metadata.get('artifact_id') != artifact_id or metadata.get('task_id') != task
            or metadata.get('creator_agents') != [agent] or metadata.get('type') != 'json'
            or metadata.get('runtime_revision') != expected_source_revision
            or metadata.get('validation_state') != 'STRUCTURE_VALIDATED'
            or metadata.get('delivery_state') != 'AVAILABLE' or metadata.get('location') != 'artifact.json'
            or type(metadata.get('bytes')) is not int or metadata['bytes'] != len(raw)
            or metadata.get('sha256') != hashlib.sha256(raw).hexdigest()):
        return {**base, 'state': 'REJECTED', 'reason': 'artifact_binding_mismatch'}
    after = _runtime_identity(get_runtime(), expected_source_revision)
    ended = wall_clock()
    if after is None or _canonical(before) != _canonical(after):
        return {**base, 'state': 'REJECTED', 'reason': 'runtime_identity_changed'}
    if type(ended) is not datetime or ended.tzinfo is None or ended.utcoffset() is None:
        return {**base, 'state': 'REJECTED', 'reason': 'observation_time_invalid'}
    if monotonic() - started >= timeout_seconds:
        return {**base, 'task_id': task, 'artifact_id': artifact_id,
                'state': 'INCOMPLETE', 'reason': 'bounded_timeout'}
    joined = validate_initialization_report(raw, task_id=task, runtime=before,
        source_revision=expected_source_revision, runtime_image_id=before['image_digest'],
        registry_sha256=expected_registry_sha256, now=ended, agent_id=agent, capability_id=capability)
    captured, artifact_time = _time(joined['captured_at']), _time(metadata.get('timestamp'))
    if captured is None or artifact_time is None or not began <= captured <= artifact_time <= ended:
        return {**base, 'state': 'REJECTED', 'reason': 'initialization_report_time_unbound'}
    if monotonic() - started >= timeout_seconds:
        return {**base, 'state': 'INCOMPLETE', 'reason': 'bounded_timeout'}
    return {**base, 'state': 'EXECUTED', 'execution_model': 'DETERMINISTIC',
            'task_id': task, 'artifact_id': artifact_id, 'model_calls': 0,
            'source_revision': expected_source_revision, 'registry_sha256': expected_registry_sha256,
            'runtime_identity_sha256': hashlib.sha256(_canonical(before)).hexdigest(),
            'result_sha256': metadata['sha256'],
            'artifact_metadata_sha256': hashlib.sha256(_canonical(metadata)).hexdigest(),
            'started_at': began.isoformat(), 'completed_at': ended.isoformat(),
            'captured_at': captured.isoformat(), 'case_review': 'INITIALIZATION_ARTIFACT_CHECK_PASS',
            'review_errors': ()}


def _observe_artifact_event(spec, base, *, dispatch, get_artifact, get_runtime,
                            expected_source_revision, expected_registry_sha256,
                            started, timeout_seconds, monotonic, wall_clock, authority=False, tool=False):
    """Observe fixed actual artifact work, not a model answer or complete review."""
    if tool:
        from . import agent_cert_tool_events as events
        fixed = events.canonical_tool_case(spec.get('case'))
    elif authority:
        from . import agent_cert_authority_events as events
        fixed = events.canonical_authority_case(spec.get('case'))
    else:
        from . import agent_cert_artifact_events as events
        fixed = events.canonical_artifact_case(spec.get('case'))
    event_key = 'tool_event' if tool else 'authority_event' if authority else 'artifact_event'
    if _canonical(spec) != _canonical(fixed):
        return {**base, 'state': 'REJECTED', 'reason': 'artifact_case_source_mismatch'}
    if (not callable(get_artifact) or not callable(get_runtime)
            or type(expected_source_revision) is not str
            or re.fullmatch('[0-9a-f]{40}', expected_source_revision) is None
            or type(expected_registry_sha256) is not str
            or re.fullmatch('[0-9a-f]{64}', expected_registry_sha256) is None):
        return {**base, 'state': 'REJECTED', 'reason': 'artifact_evidence_reader_missing'}
    began = wall_clock()
    if type(began) is not datetime or began.tzinfo is None or began.utcoffset() is None:
        return {**base, 'state': 'REJECTED', 'reason': 'observation_time_missing'}
    before = _runtime_identity(get_runtime(), expected_source_revision)
    if before is None:
        return {**base, 'state': 'REJECTED', 'reason': 'runtime_identity_missing'}
    if monotonic() - started >= timeout_seconds:
        return {**base, 'state': 'INCOMPLETE', 'reason': 'bounded_timeout'}
    reply = dispatch(fixed['request'])
    if (type(reply) is not dict or set(reply) != {'task_id', 'state', 'artifact', 'model_calls',
            'execution_model', 'agent_id', 'capability', 'runtime_source_revision', event_key}
            or reply.get('state') != 'COMPLETED' or reply.get('execution_model') != 'DETERMINISTIC'
            or reply.get('agent_id') != 'a19' or reply.get('capability') != 'responsibility.a19'
            or reply.get('runtime_source_revision') != expected_source_revision
            or type(reply.get('model_calls')) is not int or reply['model_calls'] != 0):
        return {**base, 'state': 'REJECTED', 'reason': 'artifact_dispatch_invalid'}
    task, declared, event = reply['task_id'], reply['artifact'], reply[event_key]
    if (not events._uuid(task) or type(declared) is not dict or type(event) is not dict
            or type(declared.get('artifact_id')) is not str
            or re.fullmatch('[0-9a-f]{32}', declared['artifact_id']) is None):
        return {**base, 'state': 'REJECTED', 'reason': 'artifact_identity_mismatch'}
    event_began, event_ended = _time(event.get('started_at')), _time(event.get('completed_at'))
    if (event.get('schema_version') != events.EVENT_SCHEMA or event.get('case') != fixed['case']
            or event.get('case_version') != events.CASE_VERSION or event.get('task_id') != task
            or event.get('source_revision') != expected_source_revision
            or event.get('registry_sha256') != expected_registry_sha256
            or event.get('case_spec_sha256') != events.sha(events.canonical(fixed))
            or event.get('input_sha256') != fixed['case_input_sha256']
            or event.get('runtime_identity_sha256') != events.sha(events.canonical(before))
            or event.get('durable_action_delivery') is not True or event.get('certification') != 'UNVERIFIED'
            or not events._uuid(event.get('subject_action_id')) or event_began is None or event_ended is None
            or not began <= event_began <= event_ended
            or (event_ended - event_began).total_seconds() > 5):
        return {**base, 'state': 'REJECTED', 'reason': 'artifact_event_binding_mismatch'}
    if monotonic() - started >= timeout_seconds:
        return {**base, 'state': 'INCOMPLETE', 'reason': 'bounded_timeout'}
    retrieved = get_artifact(declared['artifact_id'])
    if (type(retrieved) is not tuple or len(retrieved) != 2
            or type(retrieved[0]) is not dict or type(retrieved[1]) is not bytes):
        return {**base, 'state': 'REJECTED', 'reason': 'artifact_read_invalid'}
    metadata, raw = retrieved
    expected_raw = (events.expected_result_bytes(fixed['case'],
        events.current_authority_policy(expected_registry_sha256),
        events.sha(events.canonical(events._snapshot(event.get('read_domains_before'))))) if authority
        else events.expected_artifact_bytes(fixed['case'], **(
            {'registry_sha256': expected_registry_sha256}
            if fixed['case'] == 'context_integrity:complete' else {}), **(
            {'task_id': task, 'input_artifact': event.get('input_artifact_metadata'),
             **({'prior_artifact': event.get('prior_artifact_metadata')}
                if fixed['case'] in {'general:recovery', 'evidence_integrity:complete', 'context_integrity:complete'} else {})}
            if fixed['case'] in {'general:handoff', 'general:recovery', 'evidence_integrity:complete', 'context_integrity:complete'} else {})))
    if events.canonical(metadata) != events.canonical(declared) or raw != expected_raw:
        return {**base, 'state': 'REJECTED', 'reason': 'artifact_binding_mismatch'}
    events._metadata(metadata, raw, task, expected_source_revision, began=event_began, ended=event_ended)
    after = _runtime_identity(get_runtime(), expected_source_revision)
    ended = wall_clock()
    if after is None or _canonical(before) != _canonical(after):
        return {**base, 'state': 'REJECTED', 'reason': 'runtime_identity_changed'}
    if type(ended) is not datetime or ended.tzinfo is None or ended.utcoffset() is None or event_ended > ended:
        return {**base, 'state': 'REJECTED', 'reason': 'observation_time_invalid'}
    if monotonic() - started >= timeout_seconds:
        return {**base, 'state': 'INCOMPLETE', 'reason': 'bounded_timeout'}
    return {**base, 'state': 'EXECUTED', 'execution_model': 'DETERMINISTIC',
        'task_id': task, 'artifact_id': metadata['artifact_id'], 'model_calls': 0,
        'source_revision': expected_source_revision, 'registry_sha256': expected_registry_sha256,
        'runtime_identity_sha256': events.sha(events.canonical(before)), 'result_sha256': events.sha(raw),
        'artifact_metadata_sha256': events.sha(events.canonical(metadata)),
        'started_at': began.isoformat(), 'captured_at': event_began.isoformat(), 'completed_at': ended.isoformat(),
        'case_review': ('TOOL_EVENT_RESULT_CHECK_PASS_ORIGINAL_JOINS_REQUIRED' if tool else
            'AUTHORITY_EVENT_RESULT_CHECK_PASS_ORIGINAL_JOINS_REQUIRED' if authority else
            'ARTIFACT_EVENT_RESULT_CHECK_PASS_ORIGINAL_JOINS_REQUIRED'), 'review_errors': ()}


def observe_cert_case(spec: dict, *, dispatch: Callable[[dict], dict],
                      get_job: Callable[[str], dict], timeout_seconds: float = 60,
                      monotonic: Callable[[], float] = time.monotonic,
                      pause: Callable[[float], None] = time.sleep,
                      get_artifact: Callable[[str], tuple[dict, bytes]] | None = None,
                      get_runtime: Callable[[], dict] | None = None,
                      expected_source_revision: str | None = None,
                      expected_registry_sha256: str | None = None,
                      cloud_binding: CertificationTransport | None = None,
                      cloud_policy: dict | None = None,
                      expected_owner_policy_sha256: str | None = None,
                      wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict:
    """Observe one prepared case through the existing authenticated queue.

    Execution evidence and a local numeric verdict are deliberately distinct
    from authenticated independent review and a signed certification record.
    """
    if not isinstance(spec, dict) or spec.get("certification") != "UNVERIFIED":
        raise ValueError("prepared unverified challenge required")
    agent = spec.get("agent_id")
    capability = spec.get("capability_id")
    request = spec.get("request")
    if (not isinstance(agent, str) or not isinstance(capability, str)
            or not isinstance(request, dict) or request.get("capability") != capability
            or responsibility_owner(capability) != agent
            or capability not in agent_record(agent)["capability_requirements"]
            or request.get("data_classification") != "LOCAL_ONLY"
            or request.get("max_cost_usd") != 0
            or request.get("priority") != "low"
            or not isinstance(request.get("objective"), str)
            or not isinstance(request.get("context"), str)):
        raise ValueError("case violates bounded registered route")
    if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or not 0 < timeout_seconds <= 120:
        raise ValueError("timeout must be bounded to 120 seconds")
    base = {"agent_id": agent, "capability_id": capability, "case": spec.get("case"),
            "certification": "UNVERIFIED"}
    execution_request = request
    cloud_receipt = None
    if any(value is not None for value in (cloud_binding, cloud_policy, expected_owner_policy_sha256)):
        try:
            binding = validate_cloud_binding(
                spec, cloud_policy, cloud_binding,
                expected_source_revision=expected_source_revision,
                expected_policy_sha256=expected_owner_policy_sha256)
            cloud_receipt = binding.receipt()
            execution_request = binding.request()
        except (ValueError, TypeError, KeyError, AttributeError):
            return {**base, "state": "REJECTED", "reason": "cloud_binding_invalid"}
        if not callable(get_runtime):
            return {**base, "state": "REJECTED", "reason": "cloud_runtime_reader_missing"}
        # Only bounded metadata is returned; neither prompt nor policy body is
        # disclosed to the executing agent or included in the observation.
        base = {**base, "cloud_transport": cloud_receipt,
                "source_revision": expected_source_revision,
                "case_spec_sha256": cloud_receipt["canonical_spec_sha256"],
                "execution_request_sha256": cloud_receipt["execution_request_sha256"],
                "execution_data_classification": "CLOUD_PERMITTED"}
        timeout_seconds = min(timeout_seconds, cloud_receipt["limits"]["timeout_seconds"])
    secondary_role = spec.get('case') == 'role:normal' and capability != f'responsibility.{agent}'
    if secondary_role:
        from .agent_cert_secondary_roles import canonical_secondary_spec
        try:
            expected = canonical_secondary_spec(agent, capability)
            if _canonical(spec) != _canonical(expected):
                return {**base, 'state': 'REJECTED', 'reason': 'secondary_role_oracle_source_mismatch'}
        except (ValueError, TypeError, KeyError, UnicodeError):
            return {**base, 'state': 'REJECTED', 'reason': 'secondary_role_oracle_scope_mismatch'}
    if (agent in ROLE_G1_SOURCES and capability == f'responsibility.{agent}'
            and spec.get("case") == "role:normal"):
        canonical = challenge("role:normal", agent_id=agent, capability_id=capability)
        if ("exact_role_g1_oracle" in spec.get("independent_review", ())
                or request.get("context") == canonical["request"]["context"]) and spec != canonical:
            return {**base, "state": "REJECTED", "reason": "role_g1_oracle_source_mismatch"}
    started = monotonic()
    try:
        cloud_runtime = None
        if cloud_receipt is not None:
            cloud_runtime = _runtime_identity(get_runtime(), expected_source_revision)
            if cloud_runtime is None:
                return {**base, "state": "REJECTED", "reason": "cloud_runtime_identity_missing"}
            if monotonic() - started >= timeout_seconds:
                return {**base, "state": "INCOMPLETE", "reason": "bounded_timeout"}
            # Revalidate pinned mutable policy immediately before dispatch; no
            # consent change may widen the already prepared transport.
            validate_cloud_binding(spec, cloud_policy, cloud_binding,
                expected_source_revision=expected_source_revision,
                expected_policy_sha256=expected_owner_policy_sha256)
        if (agent, capability, spec.get("case")) == (
                "a19", "responsibility.a19", "baseline:identity"):
            return _observe_runtime_artifact(
                spec, base, dispatch=dispatch, get_artifact=get_artifact,
                get_runtime=get_runtime, expected_source_revision=expected_source_revision,
                expected_registry_sha256=expected_registry_sha256, started=started,
                timeout_seconds=timeout_seconds, monotonic=monotonic, wall_clock=wall_clock)
        if spec.get('case') == 'baseline:initialization':
            if cloud_receipt is not None:
                return {**base, 'state': 'REJECTED', 'reason': 'initialization_cloud_transport_forbidden'}
            return _observe_initialization_artifact(
                spec, base, dispatch=dispatch, get_artifact=get_artifact,
                get_runtime=get_runtime, expected_source_revision=expected_source_revision,
                expected_registry_sha256=expected_registry_sha256, started=started,
                timeout_seconds=timeout_seconds, monotonic=monotonic, wall_clock=wall_clock)
        from .agent_cert_tool_events import SUPPORTED_CASES as TOOL_CASES
        if spec.get('case') in TOOL_CASES:
            if cloud_receipt is not None:
                return {**base, 'state': 'REJECTED', 'reason': 'tool_cloud_transport_forbidden'}
            return _observe_artifact_event(spec, base, dispatch=dispatch, get_artifact=get_artifact,
                get_runtime=get_runtime, expected_source_revision=expected_source_revision,
                expected_registry_sha256=expected_registry_sha256, started=started,
                timeout_seconds=timeout_seconds, monotonic=monotonic, wall_clock=wall_clock, tool=True)
        from .agent_cert_artifact_events import SUPPORTED_CASES as ARTIFACT_CASES
        if spec.get('case') in ARTIFACT_CASES:
            if cloud_receipt is not None:
                return {**base, 'state': 'REJECTED', 'reason': 'artifact_cloud_transport_forbidden'}
            return _observe_artifact_event(spec, base, dispatch=dispatch, get_artifact=get_artifact,
                get_runtime=get_runtime, expected_source_revision=expected_source_revision,
                expected_registry_sha256=expected_registry_sha256, started=started,
                timeout_seconds=timeout_seconds, monotonic=monotonic, wall_clock=wall_clock)
        from .agent_cert_authority_events import SUPPORTED_CASES as AUTHORITY_CASES
        if spec.get('case') in AUTHORITY_CASES:
            if cloud_receipt is not None:
                return {**base, 'state': 'REJECTED', 'reason': 'authority_cloud_transport_forbidden'}
            return _observe_artifact_event(spec, base, dispatch=dispatch, get_artifact=get_artifact,
                get_runtime=get_runtime, expected_source_revision=expected_source_revision,
                expected_registry_sha256=expected_registry_sha256, started=started,
                timeout_seconds=timeout_seconds, monotonic=monotonic, wall_clock=wall_clock, authority=True)
        reply = dispatch(execution_request)
        job = reply.get("job") if isinstance(reply, dict) else None
        if (not isinstance(job, dict) or reply.get("capability") != capability
                or job.get("agent") != agent):
            return {**base, "state": "REJECTED", "reason": "dispatch_identity_mismatch"}
        job_id = job.get("id")
        try:
            valid_job_id = isinstance(job_id, str) and str(uuid.UUID(job_id)) == job_id
        except ValueError:
            valid_job_id = False
        if not valid_job_id:
            return {**base, "state": "REJECTED", "reason": "job_id_missing"}
        cloud_job = None
        if cloud_receipt is not None:
            cloud_job = _cloud_job_binding(job, cloud_receipt)
            if cloud_job is None or reply.get("tier") != cloud_receipt["minimum_tier"]:
                return {**base, "job_id": job_id, "state": "REJECTED",
                        "reason": "cloud_dispatch_binding_mismatch"}
            base = {**base, "queue_prompt_sha256": cloud_job["prompt_sha256"],
                    "queue_route_binding_sha256": hashlib.sha256(_canonical(cloud_job)).hexdigest(),
                    "runtime_identity_sha256": hashlib.sha256(_canonical(cloud_runtime)).hexdigest()}
        while monotonic() - started < timeout_seconds:
            row = get_job(job_id)
            if (not isinstance(row, dict) or row.get("id") != job_id
                    or row.get("agent") != agent):
                return {**base, "job_id": job_id, "state": "REJECTED",
                        "reason": "job_identity_mismatch"}
            status = row.get("status")
            if cloud_receipt is not None:
                observed_binding = _cloud_job_binding(row, cloud_receipt,
                                                      completed=status == "completed")
                if observed_binding is None or _canonical(observed_binding) != _canonical(cloud_job):
                    return {**base, "job_id": job_id, "state": "REJECTED",
                            "reason": "cloud_job_binding_mismatch"}
            if status == "completed":
                result = row.get("result")
                began = _time(row.get("started_at"))
                ended = _time(row.get("completed_at"))
                provider = row.get("provider")
                if (not isinstance(result, str) or not result.strip() or len(result) > 200_000
                        or began is None or ended is None or began > ended
                        or not isinstance(provider, str) or not _PROVIDER.fullmatch(provider)
                        or type(row.get("attempts")) is not int or row["attempts"] < 1
                        or row.get("error")):
                    return {**base, "job_id": job_id, "state": "REJECTED",
                            "reason": "worker_evidence_missing"}
                if cloud_receipt is not None:
                    after = _runtime_identity(get_runtime(), expected_source_revision)
                    if after is None or _canonical(after) != _canonical(cloud_runtime):
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "cloud_runtime_identity_changed"}
                    validate_cloud_binding(spec, cloud_policy, cloud_binding,
                        expected_source_revision=expected_source_revision,
                        expected_policy_sha256=expected_owner_policy_sha256)
                    if monotonic() - started >= timeout_seconds:
                        return {**base, "job_id": job_id, "state": "INCOMPLETE",
                                "reason": "bounded_timeout"}
                review = "UNREVIEWED"
                review_errors: tuple[str, ...] = ()
                if secondary_role:
                    from .agent_cert_role_review import review_case_output
                    valid, review_errors = review_case_output(agent, capability, 'role:normal', result)
                    review = 'SECONDARY_ROLE_CHECK_PASS' if valid is True else 'SECONDARY_ROLE_CHECK_FAIL'
                    # Legacy challenge metadata may contain the owner's
                    # primary oracle flag. A secondary capability is reviewed
                    # only by its own fixed source, never that primary oracle.
                    return {**base, 'job_id': job_id, 'state': 'EXECUTED',
                            'provider': provider, 'attempts': row['attempts'],
                            'started_at': began.isoformat(), 'completed_at': ended.isoformat(),
                            'result_sha256': hashlib.sha256(result.encode()).hexdigest(),
                            'case_review': review, 'review_errors': review_errors}
                if "exact_numeric_oracle" in spec.get("independent_review", ()):
                    if agent != "a01" or capability != "responsibility.a01" or spec.get("case") != "role:normal":
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "numeric_oracle_scope_mismatch"}
                    if request != challenge("role:normal", agent_id="a01",
                                            capability_id="responsibility.a01")["request"]:
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "numeric_oracle_source_mismatch"}
                    valid, review_errors = review_priority_json(_A01_SOURCE, result)
                    review = "NUMERIC_CHECK_PASS" if valid else "NUMERIC_CHECK_FAIL"
                if "exact_rate_oracle" in spec.get("independent_review", ()):
                    if agent != "a12" or capability != "responsibility.a12" or spec.get("case") != "role:normal":
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "rate_oracle_scope_mismatch"}
                    if request != challenge("role:normal", agent_id="a12",
                                            capability_id="responsibility.a12")["request"]:
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "rate_oracle_source_mismatch"}
                    valid, review_errors = review_rate_json(_A12_SOURCE, result)
                    review = "RATE_CHECK_PASS" if valid else "RATE_CHECK_FAIL"
                if "exact_weighted_oracle" in spec.get("independent_review", ()):
                    if agent != "a04" or capability != "responsibility.a04" or spec.get("case") != "role:normal":
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "weighted_oracle_scope_mismatch"}
                    if request != challenge("role:normal", agent_id="a04",
                                            capability_id="responsibility.a04")["request"]:
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "weighted_oracle_source_mismatch"}
                    valid, review_errors = review_weighted_json(_A04_SOURCE, result)
                    review = "WEIGHTED_CHECK_PASS" if valid else "WEIGHTED_CHECK_FAIL"
                if "exact_zero_boundary_oracle" in spec.get("independent_review", ()):
                    if agent != "a18" or capability != "responsibility.a18" or spec.get("case") != "role:normal":
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "boundary_oracle_scope_mismatch"}
                    if request != challenge("role:normal", agent_id="a18",
                                            capability_id="responsibility.a18")["request"]:
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "boundary_oracle_source_mismatch"}
                    valid, review_errors = review_zero_boundary_json(result)
                    review = "BOUNDARY_CHECK_PASS" if valid else "BOUNDARY_CHECK_FAIL"
                if "exact_a17_boundary_oracle" in spec.get("independent_review", ()):
                    if agent != "a17" or capability != "responsibility.a17" or spec.get("case") != "role:normal":
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "a17_boundary_oracle_scope_mismatch"}
                    if request != challenge("role:normal", agent_id="a17",
                                            capability_id="responsibility.a17")["request"]:
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "a17_boundary_oracle_source_mismatch"}
                    valid, review_errors = review_a17_boundary_json(result)
                    review = "A17_BOUNDARY_CHECK_PASS" if valid else "A17_BOUNDARY_CHECK_FAIL"
                if "exact_data_quality_oracle" in spec.get("independent_review", ()):
                    if agent != "a14" or capability != "responsibility.a14" or spec.get("case") != "role:normal":
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "data_quality_oracle_scope_mismatch"}
                    if request != challenge("role:normal", agent_id="a14",
                                            capability_id="responsibility.a14")["request"]:
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "data_quality_oracle_source_mismatch"}
                    valid, review_errors = review_data_quality_json(_A14_SOURCE, result)
                    review = "DATA_QUALITY_CHECK_PASS" if valid else "DATA_QUALITY_CHECK_FAIL"
                if "exact_portfolio_oracle" in spec.get("independent_review", ()):
                    if agent != "a05" or capability != "responsibility.a05" or spec.get("case") != "role:normal":
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "portfolio_oracle_scope_mismatch"}
                    if request != challenge("role:normal", agent_id="a05",
                                            capability_id="responsibility.a05")["request"]:
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "portfolio_oracle_source_mismatch"}
                    valid, review_errors = review_portfolio_json(_A05_SOURCE, result)
                    review = "PORTFOLIO_CHECK_PASS" if valid else "PORTFOLIO_CHECK_FAIL"
                if "exact_cost_oracle" in spec.get("independent_review", ()):
                    if agent != "a21" or capability != "responsibility.a21" or spec.get("case") != "role:normal":
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "cost_oracle_scope_mismatch"}
                    if spec != challenge("role:normal", agent_id="a21",
                                         capability_id="responsibility.a21"):
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "cost_oracle_source_mismatch"}
                    valid, review_errors = review_cost_json(_A21_SOURCE, result)
                    review = "COST_CHECK_PASS" if valid else "COST_CHECK_FAIL"
                if "exact_risk_oracle" in spec.get("independent_review", ()):
                    if agent != "a28" or capability != "responsibility.a28" or spec.get("case") != "role:normal":
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "risk_oracle_scope_mismatch"}
                    if spec != challenge("role:normal", agent_id="a28",
                                         capability_id="responsibility.a28"):
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "risk_oracle_source_mismatch"}
                    valid, review_errors = review_risk_json(_A28_SOURCE, result)
                    review = "RISK_CHECK_PASS" if valid else "RISK_CHECK_FAIL"
                if "exact_release_oracle" in spec.get("independent_review", ()):
                    if agent != "a29" or capability != "responsibility.a29" or spec.get("case") != "role:normal":
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "release_oracle_scope_mismatch"}
                    if spec != challenge("role:normal", agent_id="a29",
                                         capability_id="responsibility.a29"):
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "release_oracle_source_mismatch"}
                    valid, review_errors = review_release_json(_A29_SOURCE, result)
                    review = "RELEASE_CHECK_PASS" if valid else "RELEASE_CHECK_FAIL"
                if "exact_role_g1_oracle" in spec.get("independent_review", ()):
                    if agent not in ROLE_G1_SOURCES or capability != f"responsibility.{agent}" or spec.get("case") != "role:normal":
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "role_g1_oracle_scope_mismatch"}
                    if spec != challenge("role:normal", agent_id=agent, capability_id=capability):
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "role_g1_oracle_source_mismatch"}
                    valid, review_errors = review_role_json(agent, ROLE_G1_SOURCES[agent], result)
                    review = "ROLE_G1_CHECK_PASS" if valid else "ROLE_G1_CHECK_FAIL"
                return {**base, "job_id": job_id, "state": "EXECUTED",
                        "provider": provider, "attempts": row["attempts"],
                        "started_at": began.isoformat(), "completed_at": ended.isoformat(),
                        "result_sha256": hashlib.sha256(result.encode()).hexdigest(),
                        "case_review": review, "review_errors": review_errors}
            if status in _TERMINAL:
                return {**base, "job_id": job_id, "state": "FAILED",
                        "reason": "terminal_job_failure"}
            if status not in {"queued", "running", "approval_required"}:
                return {**base, "job_id": job_id, "state": "REJECTED",
                        "reason": "unknown_job_state"}
            pause(min(0.25, max(0.0, timeout_seconds - (monotonic() - started))))
        return {**base, "job_id": job_id, "state": "INCOMPLETE",
                "reason": "bounded_timeout"}
    except Exception:
        # Dependency exceptions may embed bearer credentials or model text.
        return {**base, "state": "INCOMPLETE", "reason": "dependency_failed"}
