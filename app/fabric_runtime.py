"""Bounded fabric execution using reviewed operations and existing services.

The execution journal records actual calls, not successful verification. Only a
separate functional verifier can supply the registry's current evidence index.
No request selects a command, module, credential, filesystem root or network URL.
"""

from __future__ import annotations

import ast
import base64
import binascii
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SLOTS = threading.BoundedSemaphore(4)
MAX_RESULT = 1_500_000
MAX_RECORDS = 50_000


class FabricUnavailable(RuntimeError):
    """A supported optional runtime is not currently available."""


class FabricConflict(ValueError):
    """An execution identity cannot be rebound to other arguments."""


class OutputContractViolation(FabricUnavailable):
    """Sanitized output failure; unvalidated results never enter the journal."""


# Deliberately the fixed operation vocabulary, not an arbitrary-schema engine.
# Unknown assertions/formats fail closed, and catalog tests inventory this set.
OUTPUT_SCHEMA_KEYWORDS = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "oneOf",
        "anyOf",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "const",
        "enum",
        "pattern",
        "format",
        "propertyNames",
        "minLength",
        "maxLength",
        "minProperties",
        "maxProperties",
        "patternProperties",
        "contentEncoding",
        "description",
        "title",
        "default",
        "$schema",
    }
)
OUTPUT_SCHEMA_FORMATS = frozenset({"uuid", "date-time", "uri"})
OUTPUT_MAX_DEPTH = 64
OUTPUT_MAX_VISITS = 100_000


class _OutputMismatch(Exception):
    pass


def _output_schema_supported(schema, budget, depth=0):
    budget[0] -= 1
    if depth > OUTPUT_MAX_DEPTH or budget[0] < 0:
        raise OutputContractViolation("Output contract validation bound exceeded")
    if type(schema) is bool:
        return
    if not isinstance(schema, dict) or set(schema) - OUTPUT_SCHEMA_KEYWORDS:
        raise OutputContractViolation("Unsupported output contract vocabulary")
    if schema.get("format") is not None and schema["format"] not in OUTPUT_SCHEMA_FORMATS:
        raise OutputContractViolation("Unsupported output contract format")
    if schema.get("contentEncoding") is not None and schema["contentEncoding"] != "base64":
        raise OutputContractViolation("Unsupported output contract encoding")
    try:
        if "pattern" in schema:
            re.compile(schema["pattern"])
        for pattern in schema.get("patternProperties", {}):
            re.compile(pattern)
    except (TypeError, re.error):
        raise OutputContractViolation("Invalid output contract pattern") from None
    kinds = schema.get("type", [])
    kinds = [kinds] if isinstance(kinds, str) else kinds
    if not isinstance(kinds, list) or any(
        kind not in {"object", "array", "string", "number", "integer", "boolean", "null"} for kind in kinds
    ):
        raise OutputContractViolation("Unsupported output contract type")
    for keyword in ("properties", "patternProperties"):
        for child in schema.get(keyword, {}).values():
            _output_schema_supported(child, budget, depth + 1)
    for keyword in ("items", "additionalProperties", "propertyNames"):
        if keyword in schema:
            _output_schema_supported(schema[keyword], budget, depth + 1)
    for keyword in ("oneOf", "anyOf"):
        if keyword in schema:
            branches = schema[keyword]
            if not isinstance(branches, list) or not 1 <= len(branches) <= 32:
                raise OutputContractViolation("Output contract branch bound exceeded")
            for child in branches:
                _output_schema_supported(child, budget, depth + 1)


def _json_equal(left, right):
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_json_equal(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_json_equal(a, b) for a, b in zip(left, right))
    return left == right


def _output_kind(value, kind):
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "number": type(value) in (int, float),
        "integer": type(value) is int or (type(value) is float and value.is_integer()),
        "boolean": type(value) is bool,
        "null": value is None,
    }.get(kind, False)


def _output_format(value, format_):
    if format_ == "uuid":
        try:
            return str(uuid.UUID(value)) == value
        except (ValueError, AttributeError):
            return False
    if format_ == "date-time":
        if (
            re.fullmatch(
                r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})",
                value,
            )
            is None
        ):
            return False
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00")).utcoffset() is not None
        except ValueError:
            return False
    if format_ == "uri":
        if (
            not value.isascii()
            or any(ord(char) < 33 or ord(char) == 127 or char in '<>"{}|\\^`' for char in value)
            or re.search(r"%(?![0-9A-Fa-f]{2})", value)
        ):
            return False
        try:
            parsed = urlsplit(value)
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*", parsed.scheme or "") is None:
                return False
            if parsed.scheme.lower() in {"http", "https"}:
                return bool(parsed.hostname) and (parsed.port is None or 1 <= parsed.port <= 65535)
            return True
        except ValueError:
            return False
    return False


def _output_value(value, schema, budget, depth=0):
    budget[0] -= 1
    if depth > OUTPUT_MAX_DEPTH or budget[0] < 0:
        raise OutputContractViolation("Output contract validation bound exceeded")
    if schema is True:
        return
    if schema is False:
        raise _OutputMismatch()
    if "const" in schema and not _json_equal(value, schema["const"]):
        raise _OutputMismatch()
    if "enum" in schema and not any(_json_equal(value, choice) for choice in schema["enum"]):
        raise _OutputMismatch()
    for keyword in ("oneOf", "anyOf"):
        if keyword in schema:
            matches = 0
            for branch in schema[keyword]:
                try:
                    _output_value(value, branch, budget, depth + 1)
                    matches += 1
                except _OutputMismatch:
                    pass
                if keyword == "anyOf" and matches:
                    break
            if (keyword == "oneOf" and matches != 1) or (keyword == "anyOf" and not matches):
                raise _OutputMismatch()
    kinds = schema.get("type")
    if kinds is not None and not any(
        _output_kind(value, kind) for kind in ([kinds] if isinstance(kinds, str) else kinds)
    ):
        raise _OutputMismatch()
    if isinstance(value, dict):
        if (
            not schema.get("minProperties", 0) <= len(value) <= schema.get("maxProperties", MAX_RESULT)
            or set(schema.get("required", [])) - value.keys()
        ):
            raise _OutputMismatch()
        properties, patterns = schema.get("properties", {}), schema.get("patternProperties", {})
        for key, child in value.items():
            if not isinstance(key, str):
                raise _OutputMismatch()
            if "propertyNames" in schema:
                _output_value(key, schema["propertyNames"], budget, depth + 1)
            matched = False
            if key in properties:
                _output_value(child, properties[key], budget, depth + 1)
                matched = True
            for pattern, definition in patterns.items():
                if re.search(pattern, key) is not None:
                    _output_value(child, definition, budget, depth + 1)
                    matched = True
            if not matched and schema.get("additionalProperties", True) is not True:
                _output_value(child, schema["additionalProperties"], budget, depth + 1)
    elif isinstance(value, list):
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", MAX_RESULT):
            raise _OutputMismatch()
        if schema.get("items", True) is not True:
            for child in value:
                _output_value(child, schema["items"], budget, depth + 1)
    elif isinstance(value, str):
        if not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", MAX_RESULT):
            raise _OutputMismatch()
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise _OutputMismatch()
        if "format" in schema and not _output_format(value, schema["format"]):
            raise _OutputMismatch()
        if schema.get("contentEncoding") == "base64":
            try:
                base64.b64decode(value, validate=True)
            except (ValueError, binascii.Error):
                raise _OutputMismatch() from None
    elif type(value) in (int, float):
        if (
            not schema.get("minimum", -math.inf) <= value <= schema.get("maximum", math.inf)
            or ("exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"])
            or ("exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"])
        ):
            raise _OutputMismatch()


def _validate_output(value, schema):
    """Bounded guard for this catalog's explicit assertions, not full JSON Schema."""
    try:
        raw = _json(value)
        if len(raw.encode()) > MAX_RESULT:
            raise OutputContractViolation("Operation output exceeds bound")
        # Also reject lone surrogates hidden inside otherwise unconstrained data.
        json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        raise OutputContractViolation("Operation output is not bounded finite JSON") from None
    # Schema-free data is still bounded JSON: never let an unconstrained field
    # conceal a tuple, converted nonstring key, or a deeply nested result tree.
    pending, visits = [(value, 0)], 0
    while pending:
        child, depth = pending.pop()
        visits += 1
        if depth > OUTPUT_MAX_DEPTH or visits > OUTPUT_MAX_VISITS:
            raise OutputContractViolation("Output JSON validation bound exceeded")
        if type(child) is dict:
            if any(type(key) is not str for key in child):
                raise OutputContractViolation("Operation output contains non-JSON data")
            if visits + len(pending) + len(child) > OUTPUT_MAX_VISITS:
                raise OutputContractViolation("Output JSON validation bound exceeded")
            pending.extend((item, depth + 1) for item in child.values())
        elif type(child) is list:
            if visits + len(pending) + len(child) > OUTPUT_MAX_VISITS:
                raise OutputContractViolation("Output JSON validation bound exceeded")
            pending.extend((item, depth + 1) for item in child)
        elif type(child) not in (str, int, float, bool, type(None)):
            raise OutputContractViolation("Operation output contains non-JSON data")
    _output_schema_supported(schema, [10_000])
    try:
        _output_value(value, schema, [OUTPUT_MAX_VISITS])
    except _OutputMismatch:
        raise OutputContractViolation("Operation output violates its declared contract") from None
    return raw


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=True)


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _namespace(principal):
    return _hash([principal.tenant_id, principal.owner_id])


def _object(properties=None, required=()):
    return {"type": "object", "additionalProperties": False, "properties": properties or {}, "required": list(required)}


def _op(name, properties=None, required=(), *, scope):
    return {
        "operation": name,
        "input_schema": _object(properties, required),
        "output_schema": _BUILTIN_OUTPUTS[name],
        "scope": scope,
    }


TEXT = {"type": "string", "minLength": 1, "maxLength": 8000}
IDENTIFIER = {"type": "string", "minLength": 1, "maxLength": 100, "pattern": "^[A-Za-z0-9_.:-]+$"}
NUMBER = {"type": "number", "minimum": -1e12, "maximum": 1e12}
POINT = {
    "type": "array",
    "minItems": 2,
    "maxItems": 2,
    "prefixItems": [
        {"type": "number", "minimum": -90, "maximum": 90},
        {"type": "number", "minimum": -180, "maximum": 180},
    ],
    "items": {"type": "number", "minimum": -180, "maximum": 180},
}


def _result_object(properties, *, optional=(), additional=False):
    """Closed result shape enforced before a new execution can complete."""
    return {
        "type": "object",
        "properties": properties,
        "required": [name for name in properties if name not in optional],
        "additionalProperties": additional,
    }


def _result_array(items, maximum=None, minimum=0):
    result = {"type": "array", "items": items, "minItems": minimum}
    if maximum is not None:
        result["maxItems"] = maximum
    return result


def _nullable(schema):
    return {"anyOf": [schema, {"type": "null"}]}


_R_STRING = {"type": "string"}
_R_COUNT = {"type": "integer", "minimum": 0}
_R_NUMBER = {"type": "number", "minimum": 0}
_R_SHA = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
_R_UUID = {"type": "string", "format": "uuid", "pattern": "^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$"}
_R_DATE = {"type": "string", "format": "date-time"}
_R_FALSE = {"type": "boolean", "const": False}
_R_TRUE = {"type": "boolean", "const": True}
_R_EXECUTION_STATUS = {"type": "string", "enum": ["RUNNING", "COMPLETED", "FAILED", "INTERRUPTED"]}
_R_MEMORY = _result_object(
    {
        "record_id": _R_UUID,
        "memory_key": _R_STRING,
        "memory_class": {"enum": ["FACT", "PREFERENCE", "EVENT", "PROCEDURE", "INFERENCE"]},
        "scope": {"enum": ["OWNER_PRIVATE", "MEMBER_PRIVATE", "HOUSEHOLD_SHARED", "APPLICATION", "SYSTEM"]},
        "scope_id": _R_STRING,
        "temporal_state": {"enum": ["CURRENT", "HISTORICAL", "SUPERSEDED"]},
        "value": {"type": "object", "description": "Stored caller-supplied JSON data; content never grants authority."},
        "source": _R_STRING,
        "source_version": _R_STRING,
        "source_authority": _R_STRING,
        "verification_ref": _nullable(_R_STRING),
        "created_at": _R_NUMBER,
        "supersedes_id": _nullable(_R_UUID),
        "record_sha256": _R_SHA,
        "write_request_id": _nullable(_R_STRING),
        "content_is_authority": _R_FALSE,
        "retrieval_score": {"type": "integer", "minimum": 1},
    },
    optional=("retrieval_score",),
)
_R_MLP = _result_object(
    {
        "trace_id": _R_STRING,
        "model_id": _R_STRING,
        "model_version": _R_STRING,
        "task": {"const": "regression"},
        "output": _result_array({"type": "number"}, 32, 1),
        "device": {"const": "cpu"},
        "latency_ms": _R_NUMBER,
        "artifact_hash": _R_SHA,
        "provenance": _result_object(
            {
                "dataset_hash": _R_SHA,
                "approval": _result_object(
                    {
                        "approved_at": _R_DATE,
                        "model_artifact_hash": _R_SHA,
                        "model_id": _R_STRING,
                        "rationale": _R_STRING,
                        "receipt": {
                            "type": "object",
                            "description": "Reviewed approval metadata from the pinned reference artifact.",
                        },
                        "requesting_agent_id": _R_STRING,
                        "reviewer": _R_STRING,
                    }
                ),
            }
        ),
        "scope": {"const": "SYNTHETIC_QUADRATIC_REFERENCE_ONLY"},
        "approximation": _R_TRUE,
        "grants_agent_authority": _R_FALSE,
        "automatic_training": _R_FALSE,
    }
)
_R_DISTANCE = _result_object({"distance_km": _R_NUMBER, "method": {"const": "SPHERICAL_HAVERSINE"}})
_R_BROWSER_PAGE = _result_object(
    {
        "path": {"enum": ["/", "/capabilities", "/pwa/"]},
        "view": {"enum": ["desktop", "mobile"]},
        "response_status": {"type": "integer", "minimum": 0, "maximum": 599},
        "same_origin": {"type": "boolean"},
        "mobile_menu_exercised": {"type": "boolean"},
        **{
            name: _R_COUNT
            for name in (
                "h1_count",
                "visible_h1_count",
                "nav_count",
                "visible_navigation_controls",
                "document_width",
                "viewport_width",
                "page_error_count",
            )
        },
        "horizontal_overflow": {"type": "boolean"},
        "screenshot_sha256": _R_SHA,
        "page_error_sha256": _result_array(_R_SHA, 10),
        "http_error_status_counts": {
            "type": "object",
            "additionalProperties": _R_COUNT,
            "propertyNames": {"pattern": "^[45][0-9]{2}$"},
        },
        "passed": {"type": "boolean"},
    }
)
_R_TASK_ERROR = _result_object({"status": {"const": "FAILED"}, "error": _R_STRING, "seconds": _R_NUMBER})
_R_TASK_BLOCKED = _result_object({"status": {"const": "BLOCKED"}, "reason": _R_STRING})


def _workflow_task(result):
    return {
        "oneOf": [
            _result_object({"status": {"const": "COMPLETED"}, "result": result, "seconds": _R_NUMBER}),
            _R_TASK_ERROR,
            _R_TASK_BLOCKED,
        ]
    }


_BUILTIN_OUTPUTS = {
    "list_models": _result_object(
        {
            "models": _result_array(
                _result_object(
                    {"name": _nullable(_R_STRING), "digest": _nullable(_R_STRING), "size": _nullable(_R_COUNT)}
                ),
                50,
            ),
            "inference_executed": _R_FALSE,
        }
    ),
    "retrieve": _result_object(
        {
            "status": {"enum": ["RETRIEVED", "NO_EVIDENCE"]},
            "results": _result_array(
                _result_object(
                    {
                        "citation": _R_STRING,
                        "document_id": _R_SHA,
                        "source": _R_STRING,
                        "page": _nullable({"type": "integer", "minimum": 1}),
                        "document_version": {"type": "integer", "minimum": 1},
                        "passage": _R_STRING,
                        "sha256": _R_SHA,
                        "similarity": {"type": "number", "minimum": 0.2},
                        "content_is_authority": _R_FALSE,
                        "instructions_may_execute": _R_FALSE,
                    }
                ),
                5,
            ),
            "embedding_model": _R_STRING,
            "diagnostics": {
                "oneOf": [
                    _result_object(
                        {
                            "index_chunks": _R_COUNT,
                            "eligible_chunks": _R_COUNT,
                            "metric": {"const": "normalized inner product"},
                        }
                    ),
                    _result_object(
                        {
                            "backend": {"const": "pgvector"},
                            "metric": {"const": "exact cosine"},
                            "dimensions": {"const": 384},
                            "owner_filtered": _R_TRUE,
                        }
                    ),
                ]
            },
        },
        optional=("diagnostics",),
    ),
    "assess": _result_object(
        {
            "protocol": {"const": "orqevia.semantic.v1"},
            "relation": {"enum": ["contradiction", "entailment", "neutral"]},
            "assessment": {"enum": ["CONTRADICTION", "ENTAILMENT", "NEUTRAL", "UNCERTAIN"]},
            "uncalibrated_model_scores": _result_object(
                {
                    name: {"type": "number", "minimum": 0, "maximum": 1}
                    for name in ("contradiction", "entailment", "neutral")
                }
            ),
            "model": _R_STRING,
            "revision": _R_STRING,
            "model_sha256": _R_SHA,
            "elapsed_seconds": _R_NUMBER,
            "premise_sha256": _R_SHA,
            "claim_sha256": _R_SHA,
            "formal_proof": _R_FALSE,
            "source_authenticity_verified": _R_FALSE,
            "may_persist_as_verified_fact": _R_FALSE,
            "grants_execution_authority": _R_FALSE,
            "disclosure": _R_STRING,
        }
    ),
    "distance_km": _R_DISTANCE,
    "verify_latest_projection": _result_object(
        {
            "event_id": _R_STRING,
            "job_id": _R_STRING,
            "result_sha256": _R_SHA,
            "projectors_verified": {"const": 4},
            "persistence_integrity": {"const": "PASS"},
            "auto_promoted": _R_FALSE,
            "health_scope": {"const": "PERSISTED_EXECUTION_AND_FOUR_PROJECTOR_READBACK"},
        }
    ),
    "reference_infer": _R_MLP,
    "observe_governed_execution": _result_object(
        {
            "job_id": _R_STRING,
            "provider": _R_STRING,
            "model": _R_STRING,
            "result_sha256": _R_SHA,
            "completed_at": _R_DATE,
            "actual_cost_usd": _R_NUMBER,
            "max_cost_usd": {"type": "number", "exclusiveMinimum": 0},
            "input_tokens": _nullable(_R_COUNT),
            "output_tokens": _nullable(_R_COUNT),
            "execution_ledger_id": _R_STRING,
            "execution_ledger_sha256": _R_SHA,
            "billing_status": _R_STRING,
            "health_scope": {"const": "LAST_GOVERNED_INFERENCE_VALID_UNTIL_REPLACED_NOT_CONTINUOUS_PROVIDER_SLA"},
            "probe_spends_money": _R_FALSE,
        }
    ),
    "queue_metrics": _result_object(
        {
            "statuses": {"type": "object", "additionalProperties": _R_COUNT},
            "running": _result_array(
                _result_object(
                    {
                        "id": _R_STRING,
                        "agent": _R_STRING,
                        "provider": _nullable(_R_STRING),
                        "ram_mb": _R_COUNT,
                        "vram_mb": _R_COUNT,
                        "started_at": _nullable(_R_DATE),
                    }
                )
            ),
            "cloud_inflight": _result_array(
                _result_object(
                    {
                        "id": _R_STRING,
                        "agent": _R_STRING,
                        "provider": _nullable(_R_STRING),
                        "status": _R_STRING,
                        "lease_until": _nullable(_R_NUMBER),
                    }
                )
            ),
            "daily_spend_usd": _R_NUMBER,
            "policy": _result_object(
                {
                    **{
                        name: {"type": "integer", "minimum": 0}
                        for name in (
                            "global_concurrency",
                            "per_agent_concurrency",
                            "background_concurrency",
                            "local_ram_mb",
                            "local_vram_mb",
                            "cloud_wait_seconds",
                            "starvation_interval_seconds",
                            "starvation_boost_per_interval",
                            "starvation_boost_cap",
                            "cloud_concurrency",
                        )
                    },
                    "max_job_cost_usd": _R_NUMBER,
                    "daily_cost_ceiling_usd": _R_NUMBER,
                }
            ),
        }
    ),
    "invoke_tool": {
        "oneOf": [
            _result_object(
                {"tool": {"const": "geo.distance"}, "result": _R_DISTANCE, "credential_disclosed": _R_FALSE}
            ),
            _result_object({"tool": {"const": "mlp.reference"}, "result": _R_MLP, "credential_disclosed": _R_FALSE}),
        ]
    },
    "inspect_deployed_module": _result_object(
        {
            "module": _R_STRING,
            "source_sha256": _R_SHA,
            "bytes": {"type": "integer", "minimum": 0, "maximum": 2_000_000},
            "functions": _result_array(_R_STRING, 2000),
            "imports": _result_array(_R_STRING, 1000),
            "runtime_revision": _R_STRING,
        }
    ),
    "inspect_workbench": _result_object(
        {
            "protocol": {"const": "orqevia.fabric.browser-probe.v1"},
            "status": {"enum": ["PASS", "FAIL"]},
            "pages": _result_array(_R_BROWSER_PAGE, 6),
            "probe_script_sha256": _R_SHA,
            "observed_at": _R_DATE,
            "origin": _R_STRING,
            "execution_mode": {"const": "REAL_CHROMIUM"},
            "mocked": _R_FALSE,
            "tls_bypass": _R_FALSE,
            "scope": {"const": "PUBLIC_PAGES_DESKTOP_AND_EMULATED_MOBILE"},
            "physical_device_verified": _R_FALSE,
            "authenticated_workflow_verified": _R_FALSE,
            "execution_status": {"enum": ["FAILED", "COMPLETED"]},
            "browser_version": _R_STRING,
            "playwright_version": _R_STRING,
            "error": _R_STRING,
            "error_sha256": _R_SHA,
        },
        optional=(
            "observed_at",
            "origin",
            "execution_mode",
            "mocked",
            "tls_bypass",
            "scope",
            "physical_device_verified",
            "authenticated_workflow_verified",
            "execution_status",
            "browser_version",
            "playwright_version",
            "error",
            "error_sha256",
        ),
    ),
    "verify_execution_integrity": _result_object(
        {
            "execution_id": _R_UUID,
            "integrity_verified": {"type": "boolean"},
            "status": _R_EXECUTION_STATUS,
            "result_sha256": _nullable(_R_SHA),
            "runtime_revision": _R_STRING,
            "correctness_verified": _R_FALSE,
        }
    ),
    "store_context": _result_object({"record": _R_MEMORY, "automatically_verified_fact": _R_FALSE}),
    "search_context": _result_object({"records": _result_array(_R_MEMORY, 20)}),
    "execution_metrics": _result_object(
        {
            "execution_counts": _result_array(
                _result_object(
                    {"status": _R_EXECUTION_STATUS, "count": _R_COUNT, "average_duration_ms": _nullable(_R_NUMBER)}
                ),
                4,
            ),
            "source": {"const": "PERSISTED_EXECUTION_JOURNAL"},
            "total_operating_cost_usd": {"type": "null"},
            "cost_scope": {"const": "NOT_MEASURED"},
        }
    ),
    "release_identity": _result_object(
        {
            "runtime_revision": _R_STRING,
            "source_files": _result_object(
                {name: _R_SHA for name in ("fabric_runtime.py", "collective_api.py", "production_entry.py")}
            ),
            "deployment_executed": _R_FALSE,
        }
    ),
    "prepare_storyboard": _result_object(
        {
            "brief": TEXT,
            "scenes": _result_array(
                _result_object(
                    {
                        "description": TEXT,
                        "seconds": {"type": "integer", "minimum": 1, "maximum": 60},
                        "source_kind": {"enum": ["product_capture", "illustration", "attested_reference"]},
                        "start_seconds": {"type": "integer", "minimum": 0, "maximum": 179},
                        "end_seconds": {"type": "integer", "minimum": 1, "maximum": 180},
                        "requires_reconstruction_label": {"type": "boolean"},
                    }
                ),
                20,
                1,
            ),
            "duration_seconds": {"type": "integer", "minimum": 1, "maximum": 180},
            "review_state": {"const": "DRAFT"},
            "publication_authorized": _R_FALSE,
            "provider_called": _R_FALSE,
            "provider_cost_usd": {"const": 0},
        }
    ),
    "retrieve_observations": _result_object(
        {
            "count": {"type": "integer", "minimum": 0, "maximum": 5},
            "records": _result_array(
                _result_object(
                    {
                        "event_id": _R_STRING,
                        "kind": _R_STRING,
                        "ingested_at": _R_STRING,
                        "source": _R_STRING,
                        "source_url": _R_STRING,
                        "attribution": _R_STRING,
                        "observed_at": _nullable(_R_STRING),
                        "location": _nullable(
                            _result_object(
                                {
                                    "lat": {"type": "number", "minimum": -90, "maximum": 90},
                                    "lon": {"type": "number", "minimum": -180, "maximum": 180},
                                    "depth_km": {"type": "number"},
                                },
                                optional=("depth_km",),
                            )
                        ),
                    },
                    optional=("source", "source_url", "attribution", "observed_at", "location"),
                    additional={"description": "Unverified source-specific observation payload extension."},
                ),
                5,
            ),
        }
    ),
    "run_digest_workflow": _result_object(
        {
            "tasks": {
                "type": "object",
                "minProperties": 2,
                "maxProperties": 2,
                "additionalProperties": False,
                "patternProperties": {
                    "^[a-f0-9-]{36}:digest$": _workflow_task(_result_object({"sha256": _R_SHA})),
                    "^[a-f0-9-]{36}:summary$": _workflow_task(
                        _result_object({"characters": _R_COUNT, "words": _R_COUNT, "dependency_count": _R_COUNT})
                    ),
                },
            },
            "seconds": _R_NUMBER,
            "status": {"enum": ["COMPLETED", "COMPLETED_WITH_FAILURES"]},
        }
    ),
    "evaluate_tool_permission": _result_object(
        {
            "allowed": {"type": "boolean"},
            "policy": {"const": "FIXED_LOCAL_READ_AND_REFERENCE_TOOLS"},
            "grants_consequential_authority": _R_FALSE,
        }
    ),
    "bound_identity": _result_object(
        {
            "tenant": _R_STRING,
            "bound_owner": _R_STRING,
            "actor": _R_STRING,
            "credential_disclosed": _R_FALSE,
            "hardware_attested": _R_FALSE,
        }
    ),
    "synthesize_speech": _result_object(
        {
            "audio_base64": {"type": "string", "contentEncoding": "base64", "maxLength": 1_333_392},
            "audio_sha256": _R_SHA,
            "mime_type": {"const": "audio/wav"},
            "frames": {"type": "integer", "minimum": 1, "maximum": 500000},
            "sample_rate_hz": {"const": 16000},
            "channels": {"const": 1},
            "sample_width_bytes": {"const": 2},
            "duration_seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 31.25},
            "voice": {"enum": ["Microsoft David Desktop", "Microsoft Zira Desktop"]},
            "engine": {"const": "WINDOWS_SYSTEM_SPEECH_OFFLINE"},
            "paid_provider_called": _R_FALSE,
            "speech_recognition_supported": _R_FALSE,
        }
    ),
    "edge_telemetry": _result_object(
        {
            "node_scope": {"const": "CURRENT_EXECUTION_PROCESS"},
            "pid": {"type": "integer", "minimum": 1},
            "cpu_seconds": _R_NUMBER,
            "resident_bytes": _R_COUNT,
            "logical_cpu_count": _nullable({"type": "integer", "minimum": 1}),
            "physical_actions_enabled": _R_FALSE,
            "hardware_attested": _R_FALSE,
        }
    ),
}

BUILTINS = {
    "f01": {
        "version": "1.0.0",
        "operations": [
            _op(
                "list_models", scope="Actual installed Ollama model inventory; inference remains on the governed queue."
            )
        ],
        "limitations": ["No inference or model installation in this operation."],
    },
    "f02": {
        "version": "1.0.0",
        "operations": [
            _op(
                "retrieve",
                {
                    "question": {"type": "string", "minLength": 1, "maxLength": 4096},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 5},
                },
                ("question",),
                scope="Actual existing owner-scoped MiniLM retrieval.",
            )
        ],
        "limitations": ["Retrieved documents are evidence, not verified facts."],
    },
    "f03": {
        "version": "1.0.0",
        "operations": [
            _op(
                "assess",
                {
                    "premise": {"type": "string", "minLength": 1, "maxLength": 5000},
                    "claim": {"type": "string", "minLength": 1, "maxLength": 2000},
                },
                ("premise", "claim"),
                scope="Pinned offline NLI inference; no formal proof.",
            )
        ],
        "limitations": ["Known neutral-label errors remain documented."],
    },
    "f04": {
        "version": "1.0.0",
        "operations": [
            _op(
                "distance_km",
                {"a": POINT, "b": POINT},
                ("a", "b"),
                scope="Spherical great-circle distance between two validated coordinates.",
            )
        ],
        "limitations": ["Not a route, terrain or PostGIS qualification."],
    },
    "f05": {
        "version": "1.0.0",
        "operations": [
            _op("verify_latest_projection", scope="Read back actual queue event and all four persisted projectors.")
        ],
        "limitations": ["Observation grants no publication or agent authority."],
    },
    "f06": {
        "version": "1.0.0",
        "operations": [
            _op(
                "reference_infer",
                {
                    "rows": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 32,
                        "items": _object({"x": {"type": "number", "minimum": -3, "maximum": 2.9}}, ("x",)),
                    }
                },
                ("rows",),
                scope="SYNTHETIC_QUADRATIC_REFERENCE_ONLY",
            )
        ],
        "limitations": ["No general ML, training or certified agent capability."],
    },
    "f07": {
        "version": "1.0.0",
        "operations": [
            _op("observe_governed_execution", scope="Read-only exact last governed Hugging Face execution and usage.")
        ],
        "limitations": ["No new provider call or spend; observation does not establish new inference availability."],
    },
    "f08": {
        "version": "1.0.0",
        "operations": [_op("queue_metrics", scope="Actual governed queue counts and resource policy.")],
        "limitations": ["Delegation, job submission and cancellation use the existing compute API."],
    },
    "f09": {
        "version": "1.0.0",
        "operations": [
            _op(
                "invoke_tool",
                {"tool": {"enum": ["geo.distance", "mlp.reference"]}, "arguments": {"type": "object"}},
                ("tool", "arguments"),
                scope="Fixed reviewed local tool allowlist, validated arguments and durable execution audit.",
            )
        ],
        "limitations": ["No arbitrary CLI, dynamic imports or new MCP server permissions."],
    },
    "f10": {
        "version": "1.0.0",
        "operations": [
            _op(
                "inspect_deployed_module",
                {"module": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,79}$"}},
                ("module",),
                scope="Parse and hash actual deployed Python module; no execution or arbitrary paths.",
            )
        ],
        "limitations": ["Local repository check CLI remains separate; no automatic patch publication."],
    },
    "f11": {
        "version": "1.0.0",
        "operations": [
            _op(
                "inspect_workbench",
                scope="Real installed Chromium navigates fixed local workbench pages with normal TLS verification and measures responsive overflow.",
            )
        ],
        "limitations": [
            "Public navigation only; authenticated gameplay, accessibility audit and physical devices remain separate tests."
        ],
    },
    "f12": {
        "version": "1.0.0",
        "operations": [
            _op(
                "verify_execution_integrity",
                {"execution_id": {"type": "string", "format": "uuid"}},
                ("execution_id",),
                scope="Independent recomputation of persisted execution result hash, source and identity.",
            )
        ],
        "limitations": ["Integrity is not a correctness oracle or independent AI review."],
    },
    "f14": {
        "version": "1.0.0",
        "operations": [
            _op(
                "store_context",
                {"key": IDENTIFIER, "value": {"type": "object"}, "source": TEXT},
                ("key", "value", "source"),
                scope="Durable owner-private versioned INFERENCE memory with explicit provenance, never automatic FACT promotion.",
            ),
            _op(
                "search_context", {"query": TEXT}, ("query",), scope="Scoped, integrity-checked current memory search."
            ),
        ],
        "limitations": ["Submitted context is unverified inference; least-privilege owner scope is server-derived."],
    },
    "f15": {
        "version": "1.0.0",
        "operations": [
            _op("execution_metrics", scope="Actual persistent journal status counts, latency and execution source.")
        ],
        "limitations": ["Power, subscriptions and unmetered providers are not estimated as zero."],
    },
    "f16": {
        "version": "1.0.0",
        "operations": [
            _op("release_identity", scope="Observed runtime revision and hashes of deployed control-plane source.")
        ],
        "limitations": ["Build, promotion, backup and rollback remain explicit owner-operated CLI release operations."],
    },
    "f18": {
        "version": "1.0.0",
        "operations": [
            _op(
                "prepare_storyboard",
                {
                    "brief": TEXT,
                    "scenes": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 20,
                        "items": _object(
                            {
                                "description": TEXT,
                                "seconds": {"type": "integer", "minimum": 1, "maximum": 60},
                                "source_kind": {"enum": ["product_capture", "illustration", "attested_reference"]},
                            },
                            ("description", "seconds", "source_kind"),
                        ),
                    },
                },
                ("brief", "scenes"),
                scope="Actual deterministic edit timeline with provenance labels, draft review state and bounded durations.",
            )
        ],
        "limitations": ["No paid generation, encoding, rights approval or publication in this operation."],
    },
    "f19": {
        "version": "1.0.0",
        "operations": [
            _op("retrieve_observations", scope="Actual source-attributed geospatial observation service, bounded read.")
        ],
        "limitations": ["Live feed observations are not independent cross-source confirmation."],
    },
    "f23": {
        "version": "1.0.0",
        "operations": [
            _op(
                "run_digest_workflow",
                {"text": TEXT},
                ("text",),
                scope="Existing DAG engine executes bounded text digest and dependency validation; result journal is durable.",
            )
        ],
        "limitations": ["Long-running recovery, schedules and approvals use existing project workflow API."],
    },
    "f24": {
        "version": "1.0.0",
        "operations": [
            _op(
                "evaluate_tool_permission",
                {"tool": TEXT, "consequential": {"type": "boolean"}},
                ("tool", "consequential"),
                scope="Server-owned tool allowlist decision; client assertion cannot grant consequential execution authority.",
            )
        ],
        "limitations": ["This route cannot approve deployment, spending or physical actions."],
    },
    "f29": {
        "version": "1.0.0",
        "operations": [
            _op(
                "bound_identity",
                scope="Actual authenticated tenant, bound owner digest and actor; no bearer token disclosure.",
            )
        ],
        "limitations": ["No hardware attestation or new credentials issued."],
    },
    "f31": {
        "version": "1.0.0",
        "operations": [
            _op(
                "synthesize_speech",
                {
                    "text": {"type": "string", "minLength": 1, "maxLength": 120},
                    "voice": {"enum": ["Microsoft David Desktop", "Microsoft Zira Desktop"]},
                },
                ("text",),
                scope="Installed Windows System.Speech offline text-to-speech via the authenticated loopback knowledge service.",
            )
        ],
        "limitations": ["No speech recognition, voice cloning or physical speaker/microphone validation."],
    },
    "f33": {
        "version": "1.0.0",
        "operations": [
            _op("edge_telemetry", scope="Real resource telemetry from the current local execution node/process.")
        ],
        "limitations": ["Container/process scope only. No attached robot, physical action or hardware attestation."],
    },
}


# Conditional schemas describe the two real allowlisted tool signatures. The
# runtime already validates their nested arguments against those exact tools.
BUILTINS["f09"]["operations"][0]["input_schema"]["oneOf"] = [
    _result_object({"tool": {"const": tool}, "arguments": BUILTINS[fabric]["operations"][0]["input_schema"]})
    for tool, fabric in (("geo.distance", "f04"), ("mlp.reference", "f06"))
]


def execution_request_schema(contract):
    """Actual POST wrapper; empty parameters and the UUID are server defaults."""
    from copy import deepcopy

    variants = []
    for operation in contract["operations"]:
        required = ["operation"]
        if operation["input_schema"].get("required"):
            required.append("parameters")
        parameters = deepcopy(operation["input_schema"])
        if "parameters" not in required:
            parameters["default"] = {}
        variants.append(
            _object(
                {
                    "operation": {"type": "string", "const": operation["operation"]},
                    "parameters": parameters,
                    "execution_id": {
                        **_R_UUID,
                        "description": "Optional canonical UUID. Omission generates a new execution; reuse is bound to owner, tenant, operation and arguments.",
                    },
                },
                required,
            )
        )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Bounded fabric execution request",
        "oneOf": variants,
    }


def execution_receipt_schema(fabric_id, contract):
    """Current POST receipts; cross-version replay is 409, historical GET is separate."""
    from copy import deepcopy

    variants = []
    for operation in contract["operations"]:
        shared = {
            "execution_id": _R_UUID,
            "owner": _R_STRING,
            "tenant": _R_STRING,
            "fabric_id": {"const": fabric_id},
            "operation": {"const": operation["operation"]},
            "version": {"const": contract["version"]},
            "runtime_revision": _R_STRING,
            "input_sha256": _R_SHA,
            "started_at": _R_DATE,
        }
        variants.extend(
            [
                _result_object(
                    {
                        **shared,
                        "status": {"const": "COMPLETED"},
                        "result": deepcopy(operation["output_schema"]),
                        "result_sha256": _R_SHA,
                        "duration_ms": _R_NUMBER,
                        "error_code": {"type": "null"},
                    }
                ),
                _result_object(
                    {
                        **shared,
                        "status": {"enum": ["RUNNING", "FAILED", "INTERRUPTED"]},
                        "result": {"type": "null"},
                        # read_execution retains this storage field when its
                        # value is NULL; completed receipts pop the encoded JSON.
                        "result_json": {"type": "null"},
                        "result_sha256": {"type": "null"},
                        "duration_ms": _nullable(_R_NUMBER),
                        "error_code": _nullable(_R_STRING),
                    }
                ),
            ]
        )
    return deepcopy({"oneOf": variants})


def execution_response_schema(fabric_id, contract):
    """Real HTTP response envelope; completion is distinct from verification."""
    from copy import deepcopy

    return deepcopy(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            **_result_object(
                {
                    "protocol": {"const": "orqevia.collective.v1"},
                    "observed_at": _R_DATE,
                    # The HTTP handler accepts a 36-character correlation header which
                    # is intentionally broader than the canonical execution UUID.
                    "correlation_id": {"type": "string", "pattern": "^[a-f0-9-]{36}$"},
                    "data": execution_receipt_schema(fabric_id, contract),
                    "grants_execution_authority": _R_FALSE,
                }
            ),
        }
    )


def executable_contracts():
    """Imports are fixed source, never selected by user input."""
    from copy import deepcopy

    result = deepcopy(BUILTINS)
    for name in ("fabric_analytics", "fabric_foundations", "fabric_multimodal"):
        try:
            if name == "fabric_analytics":
                from .fabric_analytics import CONTRACTS
            elif name == "fabric_foundations":
                from .fabric_foundations import CONTRACTS
            else:
                from .fabric_multimodal import CONTRACTS
        except ImportError:
            continue
        # Optional empty descriptors do not override a real reviewed operation.
        for identifier, value in CONTRACTS.items():
            if value.get("operations"):
                result[identifier] = deepcopy(value)
    channel_output = result.get("f32", {}).get("operations", [])
    if channel_output:
        channel_output[0]["output_schema"]["properties"]["channel_statistics"]["items"] = _result_object(
            {
                "channel": {"enum": ["red", "green", "blue", "alpha"]},
                "minimum": {"type": "integer", "minimum": 0, "maximum": 255},
                "maximum": {"type": "integer", "minimum": 0, "maximum": 255},
                "mean": {"type": "number", "minimum": 0, "maximum": 255},
            }
        )
    from .fabric_research import CONTRACTS as research_contracts

    research = research_contracts["f19"]
    result["f19"]["version"] = research["version"]
    result["f19"]["operations"].extend(deepcopy(research["operations"]))
    result["f19"]["limitations"].extend(research["limitations"])
    return result


def _validate(value, schema, *, depth=0):
    """Validate only the explicit schema vocabulary used by our fixed contracts."""
    if depth > 20:
        raise ValueError("JSON nesting exceeds operation limit")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("Unsupported value")
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict):
            raise ValueError("Object required")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False and set(value) - props.keys():
            raise ValueError("Unknown operation fields")
        if set(schema.get("required", ())) - value.keys():
            raise ValueError("Missing operation fields")
        for key, content in value.items():
            if key in props:
                _validate(content, props[key], depth=depth + 1)
    elif kind == "array":
        if not isinstance(value, list) or not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 1000):
            raise ValueError("Array bound exceeded")
        for content in value:
            _validate(content, schema.get("items", {}), depth=depth + 1)
    elif kind in {"number", "integer"}:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or (isinstance(value, float) and not math.isfinite(value))
        ):
            raise ValueError("Finite number required")
        if kind == "integer" and type(value) is not int:
            raise ValueError("Integer required")
        if not schema.get("minimum", -math.inf) <= value <= schema.get("maximum", math.inf):
            raise ValueError("Numeric bound exceeded")
    elif kind == "string":
        if not isinstance(value, str) or not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 48000):
            raise ValueError("Text bound exceeded")
        if schema.get("pattern") and re.fullmatch(schema["pattern"], value) is None:
            raise ValueError("Invalid text format")
        if schema.get("format") == "uuid":
            if str(uuid.UUID(value)) != value:
                raise ValueError("Canonical UUID required")
    elif kind == "boolean" and type(value) is not bool:
        raise ValueError("Boolean required")


def _connect(data_root):
    root = Path(data_root) / "fabric-runtime"
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / "executions.db", timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=5000")
    db.execute("""CREATE TABLE IF NOT EXISTS executions (
        execution_id TEXT PRIMARY KEY, owner TEXT NOT NULL, tenant TEXT NOT NULL,
        fabric_id TEXT NOT NULL, operation TEXT NOT NULL, version TEXT NOT NULL,
        runtime_revision TEXT NOT NULL, input_sha256 TEXT NOT NULL,
        status TEXT NOT NULL, result_json TEXT, result_sha256 TEXT,
        started_at TEXT NOT NULL, duration_ms REAL, error_code TEXT)""")
    db.commit()
    return db


def read_execution(data_root, execution_id, principal):
    if str(uuid.UUID(execution_id)) != execution_id:
        raise ValueError("Canonical execution ID required")
    with closing(_connect(data_root)) as db:
        row = db.execute(
            "SELECT * FROM executions WHERE execution_id=? AND owner=? AND tenant=?",
            (execution_id, principal.owner_id, principal.tenant_id),
        ).fetchone()
    if row is None:
        raise KeyError("Execution not found")
    result = dict(row)
    result["result"] = json.loads(result.pop("result_json")) if result["result_json"] is not None else None
    if result["status"] == "COMPLETED" and _hash(result["result"]) != result["result_sha256"]:
        raise FabricUnavailable("Execution integrity failed")
    return result


def recover_interrupted(data_root):
    """Called once at backend startup before operation requests are accepted."""
    with closing(_connect(data_root)) as db, db:
        count = db.execute(
            "UPDATE executions SET status='INTERRUPTED',error_code='PROCESS_RESTARTED' WHERE status='RUNNING'"
        ).rowcount
    return count


def _service(path, payload, principal, *, knowledge=True):
    import httpx

    base = "http://host.docker.internal:8150" if knowledge else "http://intelligence:8100"
    headers = {
        "Authorization": "Bearer " + os.environ.get("ORQEVIA_SPINE_TOKEN", ""),
        "X-ORQEVIA-Owner": principal.owner_id,
    }
    try:
        with httpx.Client(timeout=httpx.Timeout(60, connect=3), trust_env=False, follow_redirects=False) as client:
            with client.stream(
                "GET" if payload is None else "POST", base + path, headers=headers, json=payload
            ) as response:
                if response.status_code != 200:
                    raise FabricUnavailable("Configured service rejected the operation")
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 2_000_000:
                        raise FabricUnavailable("Service response exceeds bound")
                    chunks.append(chunk)
                result = json.loads(b"".join(chunks))
                if not isinstance(result, dict):
                    raise FabricUnavailable("Service output contract failed")
                return result
    except (httpx.HTTPError, OSError, ValueError):
        raise FabricUnavailable("Configured fabric service unavailable") from None


def _builtin(identifier, operation, value, *, principal, data_root, execution_id):
    if identifier == "f01":
        from .settings import SETTINGS
        import httpx

        with httpx.Client(timeout=8, trust_env=False, follow_redirects=False) as client:
            response = client.get(SETTINGS.ollama_base_url.rstrip("/") + "/api/tags")
            response.raise_for_status()
        return {
            "models": [
                {key: model.get(key) for key in ("name", "digest", "size")}
                for model in response.json().get("models", [])
            ][:50],
            "inference_executed": False,
        }
    if identifier == "f02":
        return _service("/retrieve", {**value, "top_k": value.get("top_k", 3)}, principal)
    if identifier == "f03":
        return _service("/semantic/assess", value, principal)
    if identifier == "f04":
        from .geospatial import haversine_km, validate_coordinate

        for point in (value["a"], value["b"]):
            validate_coordinate(*point)
        return {"distance_km": haversine_km(*value["a"], *value["b"]), "method": "SPHERICAL_HAVERSINE"}
    if identifier in {"f05", "f06", "f07"}:
        from .fabric_adapters import event_observation, hf_observation, mlp_infer

        if identifier == "f05":
            return event_observation()
        if identifier == "f07":
            from .compute_catalog import load_catalog

            entry = next(
                (
                    entry
                    for entry in load_catalog()
                    if entry.get("provider_kind") == "huggingface" and entry.get("enabled")
                ),
                None,
            )
            if entry is None:
                raise FabricUnavailable("No enabled governed HF provider")
            return hf_observation(entry)
        return mlp_infer(value["rows"], execution_id)
    if identifier == "f08":
        from .compute_queue_api import queue

        return queue.metrics()
    if identifier == "f09":
        tool_id = {"geo.distance": ("f04", "distance_km"), "mlp.reference": ("f06", "reference_infer")}[value["tool"]]
        contract = next(op for op in BUILTINS[tool_id[0]]["operations"] if op["operation"] == tool_id[1])
        _validate(value["arguments"], contract["input_schema"])
        return {
            "tool": value["tool"],
            "result": _builtin(
                *tool_id, value["arguments"], principal=principal, data_root=data_root, execution_id=execution_id
            ),
            "credential_disclosed": False,
        }
    if identifier == "f10":
        path = ROOT / "app" / (value["module"] + ".py")
        if not path.is_file() or path.is_symlink():
            raise ValueError("Unavailable deployed module")
        raw = path.read_bytes()
        if len(raw) > 2_000_000:
            raise ValueError("Module exceeds analysis bound")
        tree = ast.parse(raw)
        return {
            "module": value["module"],
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "functions": sorted(
                {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
            )[:2000],
            "imports": sorted({node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)})[
                :1000
            ],
            "runtime_revision": os.getenv("ORQEVIA_RUNTIME_REVISION", "UNKNOWN"),
        }
    if identifier == "f12":
        record = read_execution(data_root, value["execution_id"], principal)
        return {
            "execution_id": record["execution_id"],
            "integrity_verified": record["status"] == "COMPLETED",
            "status": record["status"],
            "result_sha256": record["result_sha256"],
            "runtime_revision": record["runtime_revision"],
            "correctness_verified": False,
        }
    if identifier == "f11":
        return _service("/browser/inspect", {}, principal)
    if identifier == "f14":
        from .governed_knowledge import AccessContext, GovernedKnowledgeStore, MemoryClass, Scope

        store = GovernedKnowledgeStore(Path(data_root) / "fabric-runtime" / _namespace(principal) / "context.db")
        context = AccessContext("OWNER", principal.owner_id)
        if operation == "search_context":
            return {"records": store.search(value["query"], context=context, limit=20)}
        record = store.write(
            context=context,
            memory_key=value["key"],
            memory_class=MemoryClass.INFERENCE,
            scope=Scope.OWNER_PRIVATE,
            scope_id=principal.owner_id,
            value=value["value"],
            source=value["source"],
            source_version=os.getenv("ORQEVIA_RUNTIME_REVISION", "UNKNOWN"),
            source_authority="MODEL",
            write_request_id=execution_id,
        )
        return {"record": record, "automatically_verified_fact": False}
    if identifier == "f15":
        with closing(_connect(data_root)) as db:
            rows = db.execute(
                "SELECT status,COUNT(*) AS count,AVG(duration_ms) AS average_duration_ms FROM executions WHERE owner=? AND tenant=? GROUP BY status",
                (principal.owner_id, principal.tenant_id),
            ).fetchall()
        return {
            "execution_counts": [dict(row) for row in rows],
            "source": "PERSISTED_EXECUTION_JOURNAL",
            "total_operating_cost_usd": None,
            "cost_scope": "NOT_MEASURED",
        }
    if identifier == "f16":
        names = ("fabric_runtime.py", "collective_api.py", "production_entry.py")
        return {
            "runtime_revision": os.getenv("ORQEVIA_RUNTIME_REVISION", "UNKNOWN"),
            "source_files": {name: hashlib.sha256((ROOT / "app" / name).read_bytes()).hexdigest() for name in names},
            "deployment_executed": False,
        }
    if identifier == "f18":
        cursor, scenes = 0, []
        for scene in value["scenes"]:
            scenes.append(
                {
                    **scene,
                    "start_seconds": cursor,
                    "end_seconds": cursor + scene["seconds"],
                    "requires_reconstruction_label": scene["source_kind"] == "illustration",
                }
            )
            cursor += scene["seconds"]
        if cursor > 180:
            raise ValueError("Storyboard duration exceeds 180 seconds")
        return {
            "brief": value["brief"],
            "scenes": scenes,
            "duration_seconds": cursor,
            "review_state": "DRAFT",
            "publication_authorized": False,
            "provider_called": False,
            "provider_cost_usd": 0,
        }
    if identifier == "f19":
        if operation == "fetch_primary_source":
            from .fabric_research import execute

            return execute(identifier, operation, value)
        return _service("/api/orqevia/intelligence/geo/events?limit=5", None, principal, knowledge=False)
    if identifier == "f23":
        from .workflow_engine import Task, execute

        tasks = (
            Task(execution_id + ":digest", (), "a17", "digest"),
            Task(execution_id + ":summary", (execution_id + ":digest",), "a18", "summary"),
        )
        handlers = {
            "digest": lambda task, inputs, prior: {"sha256": hashlib.sha256(inputs["text"].encode()).hexdigest()},
            "summary": lambda task, inputs, prior: {
                "characters": len(inputs["text"]),
                "words": len(inputs["text"].split()),
                "dependency_count": len(prior),
            },
        }
        return execute(tasks, handlers, value, workers=1)
    if identifier == "f24":
        allowed = value["tool"] in {"geo.distance", "mlp.reference"} and not value["consequential"]
        return {
            "allowed": allowed,
            "policy": "FIXED_LOCAL_READ_AND_REFERENCE_TOOLS",
            "grants_consequential_authority": False,
        }
    if identifier == "f29":
        return {
            "tenant": principal.tenant_id,
            "bound_owner": principal.owner_id,
            "actor": principal.actor_id,
            "credential_disclosed": False,
            "hardware_attested": False,
        }
    if identifier == "f31":
        return _service("/speech/synthesize", value, principal)
    if identifier == "f33":
        import psutil

        process = psutil.Process()
        return {
            "node_scope": "CURRENT_EXECUTION_PROCESS",
            "pid": process.pid,
            "cpu_seconds": sum(process.cpu_times()[:2]),
            "resident_bytes": process.memory_info().rss,
            "logical_cpu_count": psutil.cpu_count(),
            "physical_actions_enabled": False,
            "hardware_attested": False,
        }
    raise ValueError("Unsupported fabric operation")


def execute_fabric(identifier, operation, parameters, *, principal, data_root, execution_id):
    """Run once; cross-version POST replay is 409, historical GET stays immutable."""
    if str(uuid.UUID(execution_id)) != execution_id:
        raise ValueError("Canonical execution ID required")
    contracts = executable_contracts()
    if identifier not in contracts:
        raise FabricUnavailable("No executable adapter is installed for this fabric")
    selected = next((op for op in contracts[identifier]["operations"] if op["operation"] == operation), None)
    if selected is None:
        raise ValueError("Unsupported operation")
    if len(_json(parameters).encode()) > 800_000:
        raise ValueError("Parameters exceed bound")
    _validate(parameters, selected["input_schema"])
    fingerprint = _hash({"fabric_id": identifier, "operation": operation, "parameters": parameters})
    with closing(_connect(data_root)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM executions WHERE execution_id=?", (execution_id,)).fetchone()
        if row is not None:
            if (
                row["owner"] != principal.owner_id
                or row["tenant"] != principal.tenant_id
                or row["input_sha256"] != fingerprint
                or row["version"] != contracts[identifier]["version"]
            ):
                raise FabricConflict("Execution identity is already bound")
            db.rollback()
            return read_execution(data_root, execution_id, principal)
        if db.execute("SELECT COUNT(*) FROM executions").fetchone()[0] >= MAX_RECORDS:
            raise FabricUnavailable("Execution journal retention limit reached")
        db.execute(
            "INSERT INTO executions (execution_id,owner,tenant,fabric_id,operation,version,runtime_revision,input_sha256,status,started_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                execution_id,
                principal.owner_id,
                principal.tenant_id,
                identifier,
                operation,
                contracts[identifier]["version"],
                os.getenv("ORQEVIA_RUNTIME_REVISION", "UNKNOWN"),
                fingerprint,
                "RUNNING",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    if not SLOTS.acquire(blocking=False):
        with closing(_connect(data_root)) as db, db:
            db.execute(
                "UPDATE executions SET status='FAILED',error_code='CAPACITY_EXCEEDED' WHERE execution_id=?",
                (execution_id,),
            )
        raise FabricUnavailable("Bounded fabric capacity exceeded")
    tick, result, error = time.monotonic(), None, "INTERRUPTED"
    try:
        from .observability import span

        with span(
            "fabric.execute", {"fabric.id": identifier, "fabric.operation": operation, "execution.id": execution_id}
        ):
            if identifier in BUILTINS:
                result = _builtin(
                    identifier,
                    operation,
                    parameters,
                    principal=principal,
                    data_root=data_root,
                    execution_id=execution_id,
                )
            elif identifier in {"f21", "f22", "f25", "f26", "f27", "f34", "f35"}:
                from .fabric_analytics import execute

                result = execute(identifier, operation, parameters)
            elif identifier in {"f13", "f20", "f28", "f30", "f36"}:
                from .fabric_foundations import execute

                # Per-tenant/owner path is server-derived, preventing cross-scope graph reads.
                result = execute(
                    identifier,
                    operation,
                    parameters,
                    data_root=Path(data_root) / "fabric-runtime" / _namespace(principal),
                )
            else:
                from .fabric_multimodal import execute

                result = execute(identifier, operation, parameters)
        if not isinstance(result, dict):
            raise OutputContractViolation("Operation must return an object")
        _validate_output(result, selected["output_schema"])
        error = None
    except Exception as exception:
        error = type(exception).__name__
        raise
    finally:
        SLOTS.release()
        with closing(_connect(data_root)) as db, db:
            db.execute(
                "UPDATE executions SET status=?,result_json=?,result_sha256=?,duration_ms=?,error_code=? WHERE execution_id=?",
                (
                    "FAILED" if error else "COMPLETED",
                    None if error else _json(result),
                    None if error else _hash(result),
                    round((time.monotonic() - tick) * 1000, 3),
                    error,
                    execution_id,
                ),
            )
    return read_execution(data_root, execution_id, principal)
