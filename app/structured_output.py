"""Fail-closed structured output validation with bounded, explicit repair."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Callable


MAX_PAYLOAD_BYTES = 65_536
SUPPORTED_SCHEMA_KEYS = frozenset({
    "type", "properties", "required", "additionalProperties", "enum", "minimum", "maximum",
    "minLength", "maxLength", "items", "minItems", "maxItems", "description", "title",
})
FENCE = re.compile(r"\A\s*```(?:json)?\s*\n(?P<body>.*)\n```\s*\Z", re.I | re.S)


class StructuredOutputError(ValueError):
    pass


@dataclass(frozen=True)
class StructuredResult:
    disposition: str
    accepted: bool
    value: Any | None
    violations: tuple[str, ...]
    attempts: int
    repair_used: bool
    raw_sha256: str
    raw_chars: int
    grants_tool_authority: bool = False


def _reject_constant(value: str) -> None:
    raise StructuredOutputError(f"non-standard JSON constant: {value}")


def _object_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StructuredOutputError(f"duplicate key: {key}")
        result[key] = value
    return result


def parse_json(raw: str, *, allow_fence_normalization: bool = True) -> tuple[Any, bool]:
    candidate = raw
    normalized = False
    if allow_fence_normalization:
        fenced = FENCE.match(raw)
        if fenced:
            candidate = fenced.group("body")
            normalized = True
    try:
        return json.loads(candidate, object_pairs_hook=_object_no_duplicates, parse_constant=_reject_constant), normalized
    except (json.JSONDecodeError, StructuredOutputError) as error:
        raise StructuredOutputError(str(error)) from error


def _schema_type_matches(value: Any, expected: str) -> bool:
    if expected == "object": return isinstance(value, dict)
    if expected == "array": return isinstance(value, list)
    if expected == "string": return isinstance(value, str)
    if expected == "boolean": return isinstance(value, bool)
    if expected == "integer": return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number": return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "null": return value is None
    raise StructuredOutputError(f"unsupported schema type: {expected}")


def validate_schema(value: Any, schema: dict[str, Any], *, path: str = "$") -> list[str]:
    if not isinstance(schema, dict):
        raise StructuredOutputError("schema must be an object")
    unsupported = set(schema) - SUPPORTED_SCHEMA_KEYS
    if unsupported:
        raise StructuredOutputError("unsupported schema keywords: " + ",".join(sorted(unsupported)))
    expected = schema.get("type")
    if not isinstance(expected, str):
        raise StructuredOutputError("schema requires one explicit type")
    if not _schema_type_matches(value, expected):
        return [f"{path}:expected_{expected}"]
    violations: list[str] = []
    if "enum" in schema and value not in schema["enum"]:
        violations.append(f"{path}:invalid_enum")
    if expected == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict) or not isinstance(required, list) or any(not isinstance(key, str) for key in required):
            raise StructuredOutputError("object schema properties/required are malformed")
        for key in required:
            if key not in value:
                violations.append(f"{path}.{key}:required")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    violations.append(f"{path}.{key}:unexpected")
        for key, child in properties.items():
            if key in value:
                violations.extend(validate_schema(value[key], child, path=f"{path}.{key}"))
    elif expected == "array":
        minimum, maximum = schema.get("minItems"), schema.get("maxItems")
        if minimum is not None and len(value) < int(minimum): violations.append(f"{path}:too_few_items")
        if maximum is not None and len(value) > int(maximum): violations.append(f"{path}:too_many_items")
        if "items" in schema:
            for index, item in enumerate(value):
                violations.extend(validate_schema(item, schema["items"], path=f"{path}[{index}]"))
    elif expected == "string":
        minimum, maximum = schema.get("minLength"), schema.get("maxLength")
        if minimum is not None and len(value) < int(minimum): violations.append(f"{path}:too_short")
        if maximum is not None and len(value) > int(maximum): violations.append(f"{path}:too_long")
    elif expected in {"integer", "number"}:
        minimum, maximum = schema.get("minimum"), schema.get("maximum")
        if minimum is not None and value < minimum: violations.append(f"{path}:below_minimum")
        if maximum is not None and value > maximum: violations.append(f"{path}:above_maximum")
    return violations


def evaluate_structured_output(
    raw: str,
    schema: dict[str, Any],
    *,
    repair: Callable[[str, tuple[str, ...]], str] | None = None,
    semantic_verify: Callable[[Any], list[str]] | None = None,
    max_repair_attempts: int = 1,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
) -> StructuredResult:
    if max_repair_attempts not in {0, 1}:
        raise ValueError("repair attempts must be bounded to zero or one")
    original_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    if len(raw.encode("utf-8")) > max_payload_bytes:
        return StructuredResult("VERIFY_REQUIRED", False, None, ("$:payload_too_large",), 1, False, original_hash, len(raw))
    candidate, repaired, attempts = raw, False, 0
    while True:
        attempts += 1
        try:
            value, normalized = parse_json(candidate)
            violations = tuple(validate_schema(value, schema))
            if not violations and semantic_verify is not None:
                try:
                    semantic_violations = semantic_verify(value)
                except Exception as error:  # verifier failure cannot become acceptance
                    semantic_violations = [f"semantic_verifier_error:{type(error).__name__}"]
                if not isinstance(semantic_violations, list) or any(not isinstance(item, str) for item in semantic_violations):
                    semantic_violations = ["semantic_verifier_invalid_result"]
                violations = tuple(f"$:semantic:{item}" for item in semantic_violations)
        except StructuredOutputError as error:
            value, normalized, violations = None, False, (f"$:parse:{error}",)
        if not violations:
            return StructuredResult("ACCEPTED", True, value, (), attempts, repaired or normalized, original_hash, len(raw))
        if repair is None or repaired or max_repair_attempts == 0:
            return StructuredResult("VERIFY_REQUIRED", False, None, violations, attempts, repaired, original_hash, len(raw))
        candidate = repair(candidate, violations)
        if not isinstance(candidate, str) or candidate == raw:
            return StructuredResult("VERIFY_REQUIRED", False, None, violations, attempts, False, original_hash, len(raw))
        if len(candidate.encode("utf-8")) > max_payload_bytes:
            return StructuredResult("VERIFY_REQUIRED", False, None, ("$:repair_payload_too_large",), attempts + 1, True, original_hash, len(raw))
        repaired = True
