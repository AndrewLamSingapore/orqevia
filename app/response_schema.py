"""Bounded, answer-free schema preflight and structural response validation.

This intentionally supports a small JSON Schema subset, not arbitrary JSON
Schema. Objects are closed, arrays have typed items, and every node declares a
type or bounded union of primitive types. Schemas describe shape only: no references, enums, const/default
values, annotations, expressions, regexes, or executable hooks are accepted.
No inference, repair, network, file, or database operations occur here.
"""

from __future__ import annotations

import json
import math
from typing import Any

MAX_SCHEMA_BYTES = 16_384
MAX_SCHEMA_DEPTH = 12
MAX_SCHEMA_NODES = 256
MAX_PROPERTIES = 64
MAX_KEY_BYTES = 128
MAX_ARRAY_ITEMS = 1_024
MAX_RESPONSE_BYTES = 65_536
MAX_RESPONSE_DEPTH = 32
MAX_RESPONSE_NODES = 4_096
MAX_STRING_BYTES = 16_384
MAX_VIOLATIONS = 32

_TYPES = frozenset({"object", "array", "integer", "number", "boolean", "string", "null"})
_PRIMITIVES = _TYPES - {"object", "array"}
_OBJECT_KEYS = frozenset({"type", "properties", "required", "additionalProperties"})
_ARRAY_KEYS = frozenset({"type", "items", "minItems", "maxItems"})
_STRING_KEYS = frozenset({"type", "minLength", "maxLength"})


class ResponseSchemaError(ValueError):
    """Invalid or unsupported request schema; fail before dispatch."""


def _bounded_key(key: Any) -> None:
    if type(key) is not str or not key:
        raise ResponseSchemaError("Schema property names must be nonempty strings")
    try:
        size = len(key.encode("utf-8"))
    except UnicodeError:
        raise ResponseSchemaError("Schema property name is not valid UTF-8") from None
    if size > MAX_KEY_BYTES:
        raise ResponseSchemaError("Schema property name exceeds limit")


def canonicalize_schema(schema: Any, *, require_object_root: bool = True,
                        preserve_field_order: bool = False) -> dict[str, Any]:
    """Validate the entire schema, return an independent deterministic copy.

    Closed objects default to additionalProperties:false. Omitted required is
    an empty list, so declared properties stay optional unless requested.
    Omitted array limits become 0..MAX_ARRAY_ITEMS. A root object is required
    for the application's existing strict_json contract; primitive schemas can
    be inspected independently by explicitly setting require_object_root=False.
    """
    count = 0
    active: set[int] = set()

    def visit(node: Any, depth: int) -> dict[str, Any]:
        nonlocal count
        count += 1
        if depth > MAX_SCHEMA_DEPTH or count > MAX_SCHEMA_NODES:
            raise ResponseSchemaError("Schema exceeds depth or node limit")
        if type(node) is not dict or id(node) in active:
            raise ResponseSchemaError("Schema nodes must be acyclic objects")
        if any(type(key) is not str for key in node):
            raise ResponseSchemaError("Schema keywords must be strings")
        kind = node.get("type")
        if type(kind) is list:
            if (not 1 <= len(kind) <= len(_PRIMITIVES) or
                    any(type(item) is not str or item not in _PRIMITIVES for item in kind) or
                    len(set(kind)) != len(kind)):
                raise ResponseSchemaError("Schema type union must contain distinct supported primitives")
            kind = sorted(kind)
        elif type(kind) is not str or kind not in _TYPES:
            raise ResponseSchemaError("Schema requires a supported explicit type")
        allowed = (_OBJECT_KEYS if kind == "object" else _ARRAY_KEYS if kind == "array"
                   else _STRING_KEYS if kind == "string" else {"type"})
        if set(node) - allowed:
            raise ResponseSchemaError("Unsupported schema keyword")
        active.add(id(node))
        try:
            result: dict[str, Any] = {"type": kind}
            if kind == "object":
                properties = node.get("properties", {})
                required = node.get("required", [])
                if type(properties) is not dict or len(properties) > MAX_PROPERTIES:
                    raise ResponseSchemaError("Schema properties are invalid or exceed limit")
                for name in properties:
                    _bounded_key(name)
                if type(required) is not list or len(required) > MAX_PROPERTIES:
                    raise ResponseSchemaError("Schema required keys are invalid or exceed limit")
                for name in required:
                    _bounded_key(name)
                if len(set(required)) != len(required) or not set(required).issubset(properties):
                    raise ResponseSchemaError("Required keys must be distinct declared properties")
                if node.get("additionalProperties", False) is not False:
                    raise ResponseSchemaError("Only closed object schemas are supported")
                # Canonical semantic hashes remain independent of field order.
                # At the generation boundary, required's declared array order
                # is also the recoverable wire order after JSON/DB round trips.
                # Input/calculation fields may then precede derived decisions.
                order = (required + [name for name in properties if name not in required]
                         if preserve_field_order else sorted(properties))
                result["properties"] = {name: visit(properties[name], depth + 1)
                                        for name in order}
                result["required"] = list(required) if preserve_field_order else sorted(required)
                result["additionalProperties"] = False
            elif kind == "array":
                if "items" not in node:
                    raise ResponseSchemaError("Arrays require one typed items schema")
                lower, upper = node.get("minItems", 0), node.get("maxItems", MAX_ARRAY_ITEMS)
                if (type(lower) is not int or type(upper) is not int or
                        not 0 <= lower <= upper <= MAX_ARRAY_ITEMS):
                    raise ResponseSchemaError("Invalid or excessive array bounds")
                result.update(items=visit(node["items"], depth + 1), minItems=lower, maxItems=upper)
            elif kind == "string" and ("minLength" in node or "maxLength" in node):
                lower, upper = node.get("minLength", 0), node.get("maxLength", MAX_STRING_BYTES)
                if (type(lower) is not int or type(upper) is not int or
                        not 0 <= lower <= upper <= MAX_STRING_BYTES):
                    raise ResponseSchemaError("Invalid or excessive string bounds")
                # Keep old schemas/hashes unchanged when no length is specified.
                for key in ("minLength", "maxLength"):
                    if key in node:
                        result[key] = node[key]
            return result
        finally:
            active.remove(id(node))

    result = visit(schema, 0)
    if require_object_root and result["type"] != "object":
        raise ResponseSchemaError("strict_json response schema must have an object root")
    if len(json.dumps(result, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")) > MAX_SCHEMA_BYTES:
        raise ResponseSchemaError("Schema exceeds byte limit")
    return result


def validated_wire_schema(schema: Any) -> dict[str, Any]:
    """Validate shape while retaining declared generation order; no answers."""
    return canonicalize_schema(schema, preserve_field_order=True)


def canonical_schema_json(schema: Any, *, require_object_root: bool = True) -> str:
    """Stable text for queue persistence, lease/hash binding, and format payload."""
    return json.dumps(canonicalize_schema(schema, require_object_root=require_object_root),
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _bounded_json_value(value: Any) -> bool:
    """Bound before serialization/recursive validation; reject non-JSON values."""
    stack = [(value, 0, False)]
    active: set[int] = set()
    count = 0
    try:
        while stack:
            item, depth, leaving = stack.pop()
            if leaving:
                active.remove(id(item))
                continue
            count += 1
            if depth > MAX_RESPONSE_DEPTH or count > MAX_RESPONSE_NODES:
                return False
            kind = type(item)
            if kind is dict or kind is list:
                if id(item) in active:
                    return False
                active.add(id(item))
                stack.append((item, depth, True))
                if kind is dict:
                    if len(item) > MAX_PROPERTIES:
                        return False
                    for key in item:
                        if type(key) is not str or len(key.encode("utf-8")) > MAX_KEY_BYTES:
                            return False
                    stack.extend((child, depth + 1, False) for child in item.values())
                else:
                    if len(item) > MAX_ARRAY_ITEMS:
                        return False
                    stack.extend((child, depth + 1, False) for child in item)
            elif kind is str:
                if len(item.encode("utf-8")) > MAX_STRING_BYTES:
                    return False
            elif kind is float:
                if not math.isfinite(item):
                    return False
            elif kind is int:
                if item.bit_length() > MAX_RESPONSE_BYTES * 3:
                    return False
            elif kind is not bool and item is not None:
                return False
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        return len(raw.encode("utf-8")) <= MAX_RESPONSE_BYTES
    except (UnicodeError, ValueError, OverflowError, RecursionError):
        return False


def validate_response_value(value: Any, schema: Any) -> tuple[str, ...]:
    """Return bounded structural violations; never alter or repair the output.

    An invalid request schema raises ResponseSchemaError. Returned response
    violations contain paths and expected types only, never response values.
    Shape acceptance does not prove correctness, role competence, or authority.
    """
    canonical = canonicalize_schema(schema)
    if not _bounded_json_value(value):
        return ("$:response_exceeds_limits_or_is_not_json",)
    violations: list[str] = []

    def visit(item: Any, node: dict[str, Any], path: str) -> None:
        if len(violations) >= MAX_VIOLATIONS:
            return
        expected = node["type"]
        actual = type(item)
        def matches(kind: str) -> bool:
            return (actual is dict if kind == "object" else
                    actual is list if kind == "array" else
                    actual is int if kind == "integer" else
                    actual in (int, float) if kind == "number" else
                    actual is bool if kind == "boolean" else
                    actual is str if kind == "string" else item is None)
        choices = [expected] if type(expected) is str else expected
        matched = any(matches(kind) for kind in choices)
        if not matched:
            violations.append(f"{path}:expected_{'_or_'.join(choices)}")
            return
        if expected == "object":
            properties = node["properties"]
            for name in node["required"]:
                if name not in item and len(violations) < MAX_VIOLATIONS:
                    violations.append(f"{path}[{json.dumps(name, ensure_ascii=True)}]:required")
            for name in item:
                if name not in properties and len(violations) < MAX_VIOLATIONS:
                    violations.append(f"{path}[{json.dumps(name, ensure_ascii=True)}]:unexpected")
            for name, child in properties.items():
                if name in item:
                    visit(item[name], child, f"{path}[{json.dumps(name, ensure_ascii=True)}]")
        elif expected == "array":
            if not node["minItems"] <= len(item) <= node["maxItems"]:
                violations.append(f"{path}:array_length")
                return
            for index, child in enumerate(item):
                visit(child, node["items"], f"{path}[{index}]")
        elif expected == "string":
            if not node.get("minLength", 0) <= len(item) <= node.get("maxLength", MAX_STRING_BYTES):
                violations.append(f"{path}:string_length")

    visit(value, canonical, "$")
    return tuple(violations)
