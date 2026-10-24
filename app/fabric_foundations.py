"""Bounded foundation operations; submitted data never grants execution authority.

These operations are deliberately smaller than the full fabric roadmaps. They do
not contact providers, validate credentials, execute instructions in documents,
scan a host, or claim hardware confidentiality or model adversarial robustness.
The caller supplies an already authorized, owner-scoped data root for the graph.
"""

from __future__ import annotations

from contextlib import contextmanager
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from .agent_notebooks import SENSITIVE_PATTERNS
from .exposure_intelligence import PATTERNS

MAX_TEXT = 65_536
MAX_JSON_BYTES = 262_144
MAX_NODES = 10_000
MAX_GRAPH_ENTITIES = 10_000
MAX_GRAPH_VERSIONS = 20_000
MAX_GRAPH_EDGES = 20_000
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_EMAIL = re.compile(r"(?i)\b[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9.-]*[A-Z0-9])?\.[A-Z]{2,63}\b")
_SENSITIVE_KEY = re.compile(r"(?i)(?:password|passwd|secret|token|api[_-]?key|authorization|private[_-]?key)")
_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----.*?(?:-----END (?:[A-Z0-9]+ )?PRIVATE KEY-----|\Z)",
    re.S,
)


def _object(properties, required=None):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else required,
        "additionalProperties": False,
    }


def _array(items, maximum, minimum=0):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


_TEXT = {"type": "string", "maxLength": MAX_TEXT}
_IDENTIFIER = {"type": "string", "pattern": _ID.pattern, "maxLength": 128}
_PROVENANCE = _array(
    _object(
        {
            "source": {"type": "string", "minLength": 1, "maxLength": 256},
            "sha256": {"type": "string", "pattern": _SHA.pattern},
        }
    ),
    8,
    1,
)
_ENTITY = _object(
    {
        "id": _IDENTIFIER,
        "kind": _IDENTIFIER,
        "label": {"type": "string", "minLength": 1, "maxLength": 256},
        "provenance": _PROVENANCE,
    }
)
_EDGE = _object({"source": _IDENTIFIER, "predicate": _IDENTIFIER, "target": _IDENTIFIER, "provenance": _PROVENANCE})
_FORMAT = {"type": "string", "enum": ["text", "json", "csv"]}
_JSON_VALUE = {"type": ["object", "array", "string", "number", "boolean", "null"]}
_COUNT = {"type": "integer", "minimum": 0}
_HASH = {"type": "string", "pattern": _SHA.pattern}
_SUMMARY = _object(
    {
        "kind": {"type": "string"},
        "items": _COUNT,
        "lines": _COUNT,
    }
)


def _operation(name, input_schema, output_schema, scope):
    return {"operation": name, "input_schema": input_schema, "output_schema": output_schema, "scope": scope}


CONTRACTS = {
    "f13": {
        "version": "1.0.0",
        "operations": [
            _operation(
                "scan-text",
                _object({"text": _TEXT}),
                _object(
                    {
                        "input_sha256": _HASH,
                        "finding_count": _COUNT,
                        "findings": _array(
                            _object({"detector": {"type": "string"}, "line": {"type": "integer", "minimum": 1}}),
                            512,
                        ),
                        "truncated": {"type": "boolean"},
                        "text_retained": {"const": False},
                        "credential_validity": {"const": "NOT_TESTED"},
                        "scope": {"const": "SUBMITTED_TEXT_PATTERN_MATCHES_ONLY"},
                    }
                ),
                "Recognized secret-pattern locations only; no submitted text or matched value is returned.",
            )
        ],
        "limitations": ["No host, repository dependency, credential-validity or full vulnerability audit."],
    },
    "f20": {
        "version": "1.0.0",
        "operations": [
            _operation(
                "upsert-entities",
                _object({"entities": _array(_ENTITY, 64, 1)}),
                _object(
                    {
                        "entities": _array(
                            _object(
                                {
                                    "id": _IDENTIFIER,
                                    "version": {"type": "integer", "minimum": 1},
                                    "content_sha256": _HASH,
                                }
                            ),
                            64,
                        ),
                        "provenance_status": {"const": "USER_SUPPLIED_UNVERIFIED"},
                    }
                ),
                "Owner-scoped durable SQLite entities, immutable versions and source-digest references.",
            ),
            _operation(
                "add-relationships",
                _object({"relationships": _array(_EDGE, 64, 1)}),
                _object(
                    {
                        "relationship_ids": _array(_IDENTIFIER, 64),
                        "provenance_status": {"const": "USER_SUPPLIED_UNVERIFIED"},
                    }
                ),
                "Idempotent relationships between stored entities, retaining supplied evidence references.",
            ),
            _operation(
                "query",
                _object({"entity_id": _IDENTIFIER, "limit": {"type": "integer", "minimum": 1, "maximum": 200}}, []),
                _object(
                    {
                        "entities": _array(
                            _object(
                                {
                                    **_ENTITY["properties"],
                                    "version": {"type": "integer", "minimum": 1},
                                    "content_sha256": _HASH,
                                }
                            ),
                            200,
                        ),
                        "relationships": _array(_object({"id": _IDENTIFIER, **_EDGE["properties"]}), 200),
                        "truncated": {"type": "boolean"},
                        "provenance_status": {"const": "USER_SUPPLIED_UNVERIFIED"},
                    }
                ),
                "Bounded current-entity and adjacent-relationship retrieval from actual persistent storage.",
            ),
        ],
        "limitations": [
            "Evidence digests and assertions are supplied by the caller, not independently verified facts.",
            "No inference, automatic entity resolution, remote graph service or cross-owner retrieval.",
        ],
    },
    "f28": {
        "version": "1.0.0",
        "operations": [
            _operation(
                "redact-text",
                _object({"text": _TEXT}),
                _object(
                    {
                        "text": {"type": "string", "maxLength": MAX_JSON_BYTES},
                        "redaction_applied": {"type": "boolean"},
                        "confidential_computing": {"const": False},
                        "scope": {"const": "RECOGNIZED_SECRET_PATTERNS_AND_EMAIL_ADDRESSES"},
                    }
                ),
                "In-memory pattern redaction; input is not persisted.",
            ),
            _operation(
                "minimize-record",
                _object(
                    {
                        "record": {"type": "object", "maxProperties": 64},
                        "allow_fields": _array({"type": "string", "minLength": 1, "maxLength": 128}, 64),
                    }
                ),
                _object(
                    {
                        "record": {"type": "object", "maxProperties": 64},
                        "dropped_field_count": _COUNT,
                        "redaction_applied": {"type": "boolean"},
                        "confidential_computing": {"const": False},
                        "scope": {"const": "TOP_LEVEL_ALLOWLIST_RECURSIVE_SENSITIVE_KEY_AND_PATTERN_REDACTION"},
                    }
                ),
                "Allowlisted fields only, recursively removing recognized sensitive keys and redacting text values.",
            ),
        ],
        "limitations": [
            "Pattern coverage is finite; this is not guaranteed anonymization or detection of every personal datum.",
            "No hardware attestation, secure enclave, differential privacy or confidential-computing guarantee.",
        ],
    },
    "f30": {
        "version": "1.0.0",
        "operations": [
            _operation(
                "parse-document",
                _object({"format": _FORMAT, "text": _TEXT}),
                _object({"format": _FORMAT, "document": _JSON_VALUE, "summary": _SUMMARY, "input_sha256": _HASH}),
                "Strict submitted UTF-8 text, JSON or rectangular CSV parsing; structured output is data.",
            ),
            _operation(
                "compare-documents",
                _object({"format": _FORMAT, "left": _TEXT, "right": _TEXT}),
                _object(
                    {
                        "format": _FORMAT,
                        "byte_equal": {"type": "boolean"},
                        "semantic_equal": {"type": "boolean"},
                        "left_sha256": _HASH,
                        "right_sha256": _HASH,
                        "left_summary": _SUMMARY,
                        "right_summary": _SUMMARY,
                    }
                ),
                "Exact text comparison or canonical parsed JSON/CSV comparison, retaining both source digests.",
            ),
        ],
        "limitations": [
            "No OCR, encrypted PDF, office-file extraction, document execution or semantic AI interpretation."
        ],
    },
    "f36": {
        "version": "1.0.0",
        "operations": [
            _operation(
                "evaluate-policy-cases",
                _object(
                    {
                        "authorized": {"const": True},
                        "policy": _object(
                            {
                                "tools": _array(
                                    _object(
                                        {
                                            "name": _IDENTIFIER,
                                            "allowed_arguments": _array(_IDENTIFIER, 32),
                                            "required_arguments": _array(_IDENTIFIER, 32),
                                        }
                                    ),
                                    32,
                                )
                            }
                        ),
                        "cases": _array(
                            _object(
                                {
                                    "id": _IDENTIFIER,
                                    "tool": _IDENTIFIER,
                                    "arguments": {"type": "object", "maxProperties": 32},
                                    "source_text": {"type": "string", "maxLength": 4096},
                                    "expected": {"enum": ["ALLOW", "DENY"]},
                                },
                                ["id", "tool", "arguments", "expected"],
                            ),
                            64,
                            1,
                        ),
                    }
                ),
                _object(
                    {
                        "cases": _array(
                            _object(
                                {
                                    "id": _IDENTIFIER,
                                    "decision": {"enum": ["ALLOW", "DENY"]},
                                    "reason": {"type": "string"},
                                    "matches_expected": {"type": "boolean"},
                                    "source_text_sha256": _HASH,
                                }
                            ),
                            64,
                        ),
                        "passed": _COUNT,
                        "failed": _COUNT,
                        "tools_executed": {"const": 0},
                        "model_invoked": {"const": False},
                        "scope": {"const": "DETERMINISTIC_TOOL_POLICY_CHALLENGE_ONLY"},
                    }
                ),
                "Tests supplied structured tool-policy challenges; source instructions never become policy.",
            )
        ],
        "limitations": [
            "A caller-supplied test policy does not change production authorization or execute tools.",
            "This tests deterministic allowlist/argument checks, not a model's general prompt-injection robustness.",
        ],
    },
}


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise ValueError("FOUNDATION_JSON_INVALID") from None


def _bounded_json(value: Any) -> None:
    """Bound the already decoded object too, including nesting and non-finite numbers."""
    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > 12 or nodes > MAX_NODES:
            raise ValueError("FOUNDATION_JSON_COMPLEXITY_LIMIT")
        if isinstance(item, dict):
            if any(not isinstance(key, str) or len(key) > 256 for key in item):
                raise ValueError("FOUNDATION_JSON_KEY_INVALID")
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif not (item is None or isinstance(item, (str, bool, int, float))):
            raise ValueError("FOUNDATION_JSON_TYPE_INVALID")
    try:
        size = len(_canonical(value).encode("utf-8"))
    except (UnicodeError, ValueError):
        raise ValueError("FOUNDATION_JSON_ENCODING_INVALID") from None
    if size > MAX_JSON_BYTES:
        raise ValueError("FOUNDATION_JSON_SIZE_LIMIT")


def _validate(value: Any, schema: dict) -> None:
    """Validate the small schema vocabulary used in the public contracts."""
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        raise ValueError("FOUNDATION_CONSTANT_INVALID")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("FOUNDATION_ENUM_INVALID")
    expected = schema.get("type")
    kinds = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": type(value) is int,
        "number": type(value) in (int, float),
        "boolean": type(value) is bool,
        "null": value is None,
    }
    if expected is not None and not any(
        kinds.get(kind, False) for kind in ([expected] if isinstance(expected, str) else expected)
    ):
        raise ValueError("FOUNDATION_TYPE_INVALID")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        if any(key not in value for key in schema.get("required", [])):
            raise ValueError("FOUNDATION_REQUIRED_FIELD_MISSING")
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            raise ValueError("FOUNDATION_UNKNOWN_FIELD")
        if len(value) > schema.get("maxProperties", MAX_NODES):
            raise ValueError("FOUNDATION_OBJECT_SIZE_LIMIT")
        for key, child in value.items():
            if key in properties:
                _validate(child, properties[key])
    elif isinstance(value, list):
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", MAX_NODES):
            raise ValueError("FOUNDATION_ARRAY_SIZE_LIMIT")
        if "items" in schema:
            for child in value:
                _validate(child, schema["items"])
    elif isinstance(value, str):
        if not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", MAX_JSON_BYTES):
            raise ValueError("FOUNDATION_TEXT_SIZE_LIMIT")
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            raise ValueError("FOUNDATION_PATTERN_INVALID")
    elif type(value) in (int, float):
        if not schema.get("minimum", float("-inf")) <= value <= schema.get("maximum", float("inf")):
            raise ValueError("FOUNDATION_NUMBER_RANGE_INVALID")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _scan(text: str) -> dict:
    findings = []
    truncated = False
    for detector, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            if len(findings) == 512:
                truncated = True
                break
            findings.append({"detector": detector, "line": text.count("\n", 0, match.start()) + 1})
    return {
        "input_sha256": _hash(text),
        "finding_count": len(findings),
        "findings": findings,
        "truncated": truncated,
        "text_retained": False,
        "credential_validity": "NOT_TESTED",
        "scope": "SUBMITTED_TEXT_PATTERN_MATCHES_ONLY",
    }


def _redact_text(text: str) -> str:
    text = _PRIVATE_KEY.sub("[REDACTED PRIVATE KEY]", text)
    for pattern, replacement in SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    for pattern in PATTERNS.values():
        text = pattern.sub("[REDACTED]", text)
    return _EMAIL.sub("[REDACTED EMAIL]", text)


def _minimize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _minimize(child) for key, child in value.items() if not _SENSITIVE_KEY.search(key)}
    if isinstance(value, list):
        return [_minimize(child) for child in value]
    return _redact_text(value) if isinstance(value, str) else value


@contextmanager
def _graph(data_root: Path):
    root = Path(data_root).resolve()
    directory = root / "fabric-foundations"
    database = directory / "knowledge-graph.sqlite3"
    if not directory.resolve().is_relative_to(root) or not database.resolve().is_relative_to(root):
        raise ValueError("GRAPH_STORAGE_BOUNDARY_INVALID")
    directory.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS foundation_entity_versions (
                entity_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                kind TEXT NOT NULL,
                label TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                PRIMARY KEY (entity_id, version)
            );
            CREATE TABLE IF NOT EXISTS foundation_entity_heads (
                entity_id TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                FOREIGN KEY (entity_id, version) REFERENCES foundation_entity_versions(entity_id, version)
            );
            CREATE TABLE IF NOT EXISTS foundation_relationships (
                relationship_id TEXT PRIMARY KEY,
                source TEXT NOT NULL REFERENCES foundation_entity_heads(entity_id),
                predicate TEXT NOT NULL,
                target TEXT NOT NULL REFERENCES foundation_entity_heads(entity_id),
                provenance_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS foundation_edges_source ON foundation_relationships(source);
            CREATE INDEX IF NOT EXISTS foundation_edges_target ON foundation_relationships(target);
            """
        )
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _graph_execute(operation: str, payload: dict, data_root: Path) -> dict:
    with _graph(data_root) as db:
        if operation == "upsert-entities":
            entities = payload["entities"]
            if len({item["id"] for item in entities}) != len(entities):
                raise ValueError("GRAPH_DUPLICATE_ENTITY")
            db.execute("BEGIN IMMEDIATE")
            total = db.execute("SELECT COUNT(*) FROM foundation_entity_heads").fetchone()[0]
            versions = db.execute("SELECT COUNT(*) FROM foundation_entity_versions").fetchone()[0]
            output = []
            for item in entities:
                content = _hash(_canonical(item))
                current = db.execute(
                    "SELECT v.version,v.content_sha256 FROM foundation_entity_versions v "
                    "JOIN foundation_entity_heads h ON h.entity_id=v.entity_id AND h.version=v.version WHERE v.entity_id=?",
                    (item["id"],),
                ).fetchone()
                version = current["version"] if current else 0
                if current is None or current["content_sha256"] != content:
                    if versions >= MAX_GRAPH_VERSIONS or (current is None and total >= MAX_GRAPH_ENTITIES):
                        raise ValueError("GRAPH_RESOURCE_LIMIT")
                    version += 1
                    db.execute(
                        "INSERT INTO foundation_entity_versions VALUES(?,?,?,?,?,?)",
                        (item["id"], version, item["kind"], item["label"], _canonical(item["provenance"]), content),
                    )
                    db.execute(
                        "INSERT INTO foundation_entity_heads VALUES(?,?) "
                        "ON CONFLICT(entity_id) DO UPDATE SET version=excluded.version",
                        (item["id"], version),
                    )
                    versions += 1
                    total += current is None
                output.append({"id": item["id"], "version": version, "content_sha256": content})
            return {"entities": output, "provenance_status": "USER_SUPPLIED_UNVERIFIED"}
        if operation == "add-relationships":
            db.execute("BEGIN IMMEDIATE")
            total = db.execute("SELECT COUNT(*) FROM foundation_relationships").fetchone()[0]
            output = []
            for item in payload["relationships"]:
                relationship_id = "rel:" + _hash(_canonical(item))
                for endpoint in (item["source"], item["target"]):
                    if (
                        db.execute("SELECT 1 FROM foundation_entity_heads WHERE entity_id=?", (endpoint,)).fetchone()
                        is None
                    ):
                        raise ValueError("GRAPH_ENDPOINT_NOT_FOUND")
                if (
                    db.execute(
                        "SELECT 1 FROM foundation_relationships WHERE relationship_id=?", (relationship_id,)
                    ).fetchone()
                    is None
                ):
                    if total >= MAX_GRAPH_EDGES:
                        raise ValueError("GRAPH_RESOURCE_LIMIT")
                    db.execute(
                        "INSERT INTO foundation_relationships VALUES(?,?,?,?,?)",
                        (
                            relationship_id,
                            item["source"],
                            item["predicate"],
                            item["target"],
                            _canonical(item["provenance"]),
                        ),
                    )
                    total += 1
                output.append(relationship_id)
            return {"relationship_ids": output, "provenance_status": "USER_SUPPLIED_UNVERIFIED"}
        entity_id = payload.get("entity_id")
        limit = payload.get("limit", 100)
        entities = db.execute(
            "SELECT v.* FROM foundation_entity_versions v JOIN foundation_entity_heads h "
            "ON h.entity_id=v.entity_id AND h.version=v.version "
            + ("WHERE v.entity_id=? " if entity_id else "")
            + "ORDER BY v.entity_id LIMIT ?",
            (entity_id, limit + 1) if entity_id else (limit + 1,),
        ).fetchall()
        relationships = db.execute(
            "SELECT * FROM foundation_relationships "
            + ("WHERE source=? OR target=? " if entity_id else "")
            + "ORDER BY relationship_id LIMIT ?",
            (entity_id, entity_id, limit + 1) if entity_id else (limit + 1,),
        ).fetchall()
        result = {
            "entities": [
                {
                    "id": row["entity_id"],
                    "version": row["version"],
                    "kind": row["kind"],
                    "label": row["label"],
                    "provenance": json.loads(row["provenance_json"]),
                    "content_sha256": row["content_sha256"],
                }
                for row in entities[:limit]
            ],
            "relationships": [
                {
                    "id": row["relationship_id"],
                    "source": row["source"],
                    "predicate": row["predicate"],
                    "target": row["target"],
                    "provenance": json.loads(row["provenance_json"]),
                }
                for row in relationships[:limit]
            ],
            "truncated": len(entities) > limit or len(relationships) > limit,
            "provenance_status": "USER_SUPPLIED_UNVERIFIED",
        }
        # A graph may grow across many individually bounded writes. Reads must
        # stay bounded too; retain deterministic prefixes rather than returning
        # an unbounded response or treating a large stored graph as a failure.
        while True:
            try:
                _bounded_json(result)
                return result
            except ValueError:
                key = "entities" if len(result["entities"]) >= len(result["relationships"]) else "relationships"
                if not result[key]:
                    raise
                result[key].pop()
                result["truncated"] = True


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _parse_document(format_: str, text: str) -> tuple[Any, dict]:
    if format_ == "text":
        return text, {"kind": "text", "items": len(text), "lines": len(text.splitlines())}
    if format_ == "json":
        try:
            document = json.loads(
                text, object_pairs_hook=_pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError())
            )
            _bounded_json(document)
        except (ValueError, RecursionError, TypeError, OverflowError):
            raise ValueError("JSON_DOCUMENT_INVALID") from None
        return document, {
            "kind": "object" if isinstance(document, dict) else "array" if isinstance(document, list) else "scalar",
            "items": len(document) if isinstance(document, (dict, list)) else 1,
            "lines": len(text.splitlines()),
        }
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        headers = next(reader)
        if (
            not 1 <= len(headers) <= 64
            or any(not key or len(key) > 128 for key in headers)
            or len(set(headers)) != len(headers)
        ):
            raise ValueError("CSV_HEADER_INVALID")
        rows = []
        for row in reader:
            if len(rows) == 256 or len(row) != len(headers) or any(len(cell) > 2048 for cell in row):
                raise ValueError("CSV_ROW_INVALID")
            rows.append(dict(zip(headers, row)))
        document = {"headers": headers, "rows": rows}
        _bounded_json(document)
    except (csv.Error, ValueError, StopIteration):
        raise ValueError("CSV_DOCUMENT_INVALID") from None
    return document, {"kind": "table", "items": len(rows), "lines": len(text.splitlines())}


def _policy_cases(payload: dict) -> dict:
    tools = {}
    for item in payload["policy"]["tools"]:
        name = item["name"]
        allowed = set(item["allowed_arguments"])
        required = set(item["required_arguments"])
        if (
            name in tools
            or len(allowed) != len(item["allowed_arguments"])
            or len(required) != len(item["required_arguments"])
            or not required <= allowed
        ):
            raise ValueError("POLICY_DEFINITION_INVALID")
        tools[name] = (allowed, required)
    if len({case["id"] for case in payload["cases"]}) != len(payload["cases"]):
        raise ValueError("POLICY_DUPLICATE_CASE")
    results = []
    for case in payload["cases"]:
        tool = tools.get(case["tool"])
        arguments = case["arguments"]
        if tool is None:
            decision, reason = "DENY", "TOOL_NOT_ALLOWED"
        elif len(_canonical(arguments).encode("utf-8")) > 4096:
            decision, reason = "DENY", "ARGUMENT_SIZE_LIMIT"
        elif set(arguments) - tool[0]:
            decision, reason = "DENY", "ARGUMENT_NOT_ALLOWED"
        elif not tool[1] <= set(arguments):
            decision, reason = "DENY", "REQUIRED_ARGUMENT_MISSING"
        else:
            decision, reason = "ALLOW", "STRUCTURED_POLICY_MATCH"
        results.append(
            {
                "id": case["id"],
                "decision": decision,
                "reason": reason,
                "matches_expected": decision == case["expected"],
                "source_text_sha256": _hash(case.get("source_text", "")),
            }
        )
    passed = sum(item["matches_expected"] for item in results)
    return {
        "cases": results,
        "passed": passed,
        "failed": len(results) - passed,
        "tools_executed": 0,
        "model_invoked": False,
        "scope": "DETERMINISTIC_TOOL_POLICY_CHALLENGE_ONLY",
    }


def execute(fabric_id: str, operation: str, payload: dict, *, data_root: Path) -> dict:
    """Execute one listed operation after local schema and resource validation."""
    contract = CONTRACTS.get(fabric_id)
    definition = (
        next((item for item in contract["operations"] if item["operation"] == operation), None) if contract else None
    )
    if definition is None:
        raise ValueError("FOUNDATION_OPERATION_UNSUPPORTED")
    _bounded_json(payload)
    _validate(payload, definition["input_schema"])
    if fabric_id == "f13":
        result = _scan(payload["text"])
    elif fabric_id == "f20":
        result = _graph_execute(operation, payload, data_root)
    elif fabric_id == "f28" and operation == "redact-text":
        redacted = _redact_text(payload["text"])
        result = {
            "text": redacted,
            "redaction_applied": redacted != payload["text"],
            "confidential_computing": False,
            "scope": "RECOGNIZED_SECRET_PATTERNS_AND_EMAIL_ADDRESSES",
        }
    elif fabric_id == "f28":
        allowed = payload["allow_fields"]
        if len(set(allowed)) != len(allowed):
            raise ValueError("PRIVACY_DUPLICATE_ALLOWED_FIELD")
        selected = {key: value for key, value in payload["record"].items() if key in allowed}
        record = _minimize(selected)
        result = {
            "record": record,
            "dropped_field_count": len(payload["record"]) - len(record),
            "redaction_applied": selected != record,
            "confidential_computing": False,
            "scope": "TOP_LEVEL_ALLOWLIST_RECURSIVE_SENSITIVE_KEY_AND_PATTERN_REDACTION",
        }
    elif fabric_id == "f30" and operation == "parse-document":
        document, summary = _parse_document(payload["format"], payload["text"])
        result = {
            "format": payload["format"],
            "document": document,
            "summary": summary,
            "input_sha256": _hash(payload["text"]),
        }
    elif fabric_id == "f30":
        left, left_summary = _parse_document(payload["format"], payload["left"])
        right, right_summary = _parse_document(payload["format"], payload["right"])
        result = {
            "format": payload["format"],
            "byte_equal": payload["left"] == payload["right"],
            "semantic_equal": _canonical(left) == _canonical(right),
            "left_sha256": _hash(payload["left"]),
            "right_sha256": _hash(payload["right"]),
            "left_summary": left_summary,
            "right_summary": right_summary,
        }
    else:
        result = _policy_cases(payload)
    _bounded_json(result)
    _validate(result, definition["output_schema"])
    return result
