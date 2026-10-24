"""Bounded fabric execution using reviewed operations and existing services.

The execution journal records actual calls, not successful verification. Only a
separate functional verifier can supply the registry's current evidence index.
No request selects a command, module, credential, filesystem root or network URL.
"""

from __future__ import annotations

import ast
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

ROOT = Path(__file__).resolve().parents[1]
SLOTS = threading.BoundedSemaphore(4)
MAX_RESULT = 1_500_000
MAX_RECORDS = 50_000


class FabricUnavailable(RuntimeError):
    """A supported optional runtime is not currently available."""


class FabricConflict(ValueError):
    """An execution identity cannot be rebound to other arguments."""


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
        "output_schema": {"type": "object"},
        "scope": scope,
    }


TEXT = {"type": "string", "minLength": 1, "maxLength": 8000}
IDENTIFIER = {"type": "string", "minLength": 1, "maxLength": 100, "pattern": "^[A-Za-z0-9_.:-]+$"}
NUMBER = {"type": "number", "minimum": -1e12, "maximum": 1e12}
POINT = {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "number", "minimum": -180, "maximum": 180}}

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
                {"question": TEXT, "top_k": {"type": "integer", "minimum": 1, "maximum": 10}},
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
    """Run an explicit operation once; failed/interrupted calls never replay as PASS."""
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
            raise ValueError("Operation must return an object")
        raw = _json(result)
        if len(raw.encode()) > MAX_RESULT:
            raise ValueError("Operation output exceeds bound")
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
