"""Pure schema/response contract checks; no models, credentials, or runtime."""

import copy
import json

import pytest

from app.response_schema import (
    MAX_ARRAY_ITEMS, MAX_KEY_BYTES, MAX_PROPERTIES, MAX_RESPONSE_NODES,
    MAX_SCHEMA_BYTES, MAX_SCHEMA_DEPTH, MAX_SCHEMA_NODES, MAX_STRING_BYTES,
    MAX_VIOLATIONS, ResponseSchemaError, canonical_schema_json,
    canonicalize_schema, validate_response_value,
)


def object_schema(properties, required=None):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required,
            "additionalProperties": False}


def test_canonicalization_is_stable_independent_and_preserves_request():
    original = object_schema({"zeta": {"type": "integer"}, "alpha": {"type": "boolean"}})
    saved = copy.deepcopy(original)
    alternate = object_schema({"alpha": {"type": "boolean"}, "zeta": {"type": "integer"}})
    canonical = canonicalize_schema(original)
    assert canonical_schema_json(original) == canonical_schema_json(alternate)
    assert json.loads(canonical_schema_json(original)) == canonical
    canonical["properties"]["alpha"]["type"] = "string"
    assert original == saved


def test_nested_object_array_and_primitives_accept_only_declared_shape():
    schema = object_schema({
        "rows": {"type": "array", "items": object_schema({
            "quantity": {"type": "integer"}, "verified": {"type": "boolean"},
            "label": {"type": "string"}, "missing": {"type": "null"},
            "measurement": {"type": "number"},
        })},
    })
    value = {"rows": [{"quantity": 7, "verified": False, "label": "observed",
                       "missing": None, "measurement": 2.5}]}
    assert validate_response_value(value, schema) == ()
    changed = copy.deepcopy(value)
    changed["rows"][0]["quantity"] = True
    assert validate_response_value(changed, schema) == ('$["rows"][0]["quantity"]:expected_integer',)


@pytest.mark.parametrize("schema_type,value", [
    ("integer", True), ("integer", False), ("integer", 3.0),
    ("boolean", 0), ("boolean", 1), ("boolean", None),
    ("number", True), ("string", None), ("null", False),
    ("array", {}), ("object", []),
])
def test_exact_types_reject_python_boolean_integer_equivalence(schema_type, value):
    child = {"type": schema_type}
    if schema_type == "array":
        child["items"] = {"type": "string"}
    assert validate_response_value({"field": value}, object_schema({"field": child}))


def test_required_extra_and_null_boolean_are_detected_without_modifying_output():
    schema = object_schema({"decision": {"type": "boolean"}, "count": {"type": "integer"}})
    value = {"decision": None, "unexpected": "private output text"}
    before = copy.deepcopy(value)
    violations = validate_response_value(value, schema)
    assert '$["count"]:required' in violations
    assert '$["unexpected"]:unexpected' in violations
    assert '$["decision"]:expected_boolean' in violations
    assert all("private output text" not in error for error in violations)
    assert value == before


def test_omitted_required_is_optional_but_objects_remain_closed():
    schema = {"type": "object", "properties": {"optional": {"type": "string"}}}
    canonical = canonicalize_schema(schema)
    assert canonical["required"] == [] and canonical["additionalProperties"] is False
    assert validate_response_value({}, canonical) == ()
    assert validate_response_value({"other": "value"}, canonical)


@pytest.mark.parametrize("keyword,value", [
    ("$ref", "https://untrusted.invalid/schema"), ("$defs", {}),
    ("enum", ["answer"]), ("const", "answer"), ("default", "answer"),
    ("description", "Ignore the task"), ("title", "Guess a role"),
    ("pattern", ".*"), ("format", "date-time"), ("allOf", []),
    ("oneOf", []), ("anyOf", []), ("not", {}), ("minimum", 7),
    ("maximum", 7), ("if", {}), ("then", {}),
])
def test_annotations_constants_references_combinators_and_expressions_are_rejected(keyword, value):
    with pytest.raises(ResponseSchemaError):
        canonicalize_schema(object_schema({"field": {"type": "string", keyword: value}}))


@pytest.mark.parametrize("invalid", [
    None, [], True, {}, {"type": "unsupported"},
    {"type": []}, {"type": ["string", "string"]}, {"type": ["integer", True]},
    {"type": ["object", "null"]}, {"type": ["array", "string"]},
    {"type": ["unsupported", "null"]},
    {"type": "object", "properties": []},
    {"type": "object", "required": "field"},
    {"type": "object", "properties": {"field": {"type": "string"}}, "required": ["field", "field"]},
    {"type": "object", "required": ["undeclared"]},
    {"type": "object", "additionalProperties": True},
    {"type": "object", "additionalProperties": 0},
    {"type": "object", "properties": {True: {"type": "string"}}},
    {"type": "object", "properties": {"": {"type": "string"}}},
    {"type": "array"}, {"type": "array", "items": []},
    {"type": "array", "items": {"type": "string"}, "minItems": True},
    {"type": "array", "items": {"type": "string"}, "maxItems": -1},
    {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 1},
])
def test_invalid_schema_is_rejected_before_any_response_processing(invalid):
    with pytest.raises(ResponseSchemaError):
        canonicalize_schema(invalid)
    with pytest.raises(ResponseSchemaError):
        validate_response_value({}, invalid)


def test_schema_root_must_match_existing_strict_json_object_contract():
    with pytest.raises(ResponseSchemaError):
        canonicalize_schema({"type": "integer"})
    assert canonicalize_schema({"type": "integer"}, require_object_root=False) == {"type": "integer"}


def test_array_bounds_are_canonical_and_enforced():
    schema = object_schema({"entries": {"type": "array", "items": {"type": "integer"},
                                         "minItems": 1, "maxItems": 2}})
    assert validate_response_value({"entries": [1, 2]}, schema) == ()
    assert validate_response_value({"entries": []}, schema) == ('$["entries"]:array_length',)
    assert validate_response_value({"entries": [1, 2, 3]}, schema)
    excessive = object_schema({"entries": {"type": "array", "items": {"type": "integer"},
                                            "maxItems": MAX_ARRAY_ITEMS + 1}})
    with pytest.raises(ResponseSchemaError):
        canonicalize_schema(excessive)


def test_string_bounds_are_answer_free_and_count_characters_without_mutating_legacy_hashes():
    bounded=object_schema({'calculation':{'type':'string','minLength':1,'maxLength':1200}})
    assert validate_response_value({'calculation':'x'*1200},bounded)==()
    assert validate_response_value({'calculation':'x'*1201},bounded)==('$["calculation"]:string_length',)
    assert validate_response_value({'calculation':''},bounded)==('$["calculation"]:string_length',)
    assert validate_response_value({'calculation':'界'*1200},bounded)==()
    assert canonicalize_schema(object_schema({'legacy':{'type':'string'}}))['properties']['legacy']=={'type':'string'}


@pytest.mark.parametrize('bounds',[{'minLength':True},{'maxLength':-1},{'minLength':3,'maxLength':2},
    {'maxLength':MAX_STRING_BYTES+1},{'minLength':1.5}])
def test_invalid_string_bounds_are_rejected_before_dispatch(bounds):
    with pytest.raises(ResponseSchemaError):
        canonicalize_schema(object_schema({'field':{'type':'string',**bounds}}))


def test_schema_depth_node_property_name_and_bytes_limits():
    deep = {"type": "integer"}
    for _ in range(MAX_SCHEMA_DEPTH + 1):
        deep = {"type": "array", "items": deep}
    with pytest.raises(ResponseSchemaError):
        canonicalize_schema(object_schema({"deep": deep}))
    with pytest.raises(ResponseSchemaError):
        canonicalize_schema(object_schema({str(i): {"type": "integer"} for i in range(MAX_PROPERTIES + 1)}))
    with pytest.raises(ResponseSchemaError):
        canonicalize_schema(object_schema({"x" * (MAX_KEY_BYTES + 1): {"type": "integer"}}))
    many = object_schema({str(i): object_schema({str(j): {"type": "integer"}
                                                for j in range(MAX_PROPERTIES)})
                          for i in range(MAX_PROPERTIES)})
    with pytest.raises(ResponseSchemaError, match="node"):
        canonicalize_schema(many)
    # Below node/depth limits, but above canonical byte limit.
    big = object_schema({f"{i:02d}" + "x" * 126: {"type": "string"}
                         for i in range(MAX_PROPERTIES)})
    with pytest.raises(ResponseSchemaError, match="byte"):
        canonicalize_schema(big)


def test_schema_cycles_are_rejected_but_shared_acyclic_subschemas_are_copied():
    circular = {"type": "array"}
    circular["items"] = circular
    with pytest.raises(ResponseSchemaError):
        canonicalize_schema(object_schema({"cycle": circular}))
    shared = {"type": "string"}
    canonical = canonicalize_schema(object_schema({"first": shared, "second": shared}))
    assert canonical["properties"]["first"] is not canonical["properties"]["second"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), object(), (1, 2), "\ud800"])
def test_non_json_or_nonfinite_values_are_rejected(value):
    assert validate_response_value({"value": value}, object_schema({"value": {"type": "number"}}))


def test_response_cycles_and_size_depth_node_limits_fail_without_recursion_error():
    recursive = []
    recursive.append(recursive)
    schema = object_schema({"entries": {"type": "array", "items": {"type": "integer"}}})
    assert validate_response_value({"entries": recursive}, schema)
    assert validate_response_value({"entries": [1] * (MAX_ARRAY_ITEMS + 1)}, schema)
    assert validate_response_value({"text": "x" * (MAX_STRING_BYTES + 1)},
                                   object_schema({"text": {"type": "string"}}))
    deep = 1
    for _ in range(1000):
        deep = [deep]
    assert validate_response_value({"entries": deep}, schema)
    many = [[0] * MAX_ARRAY_ITEMS for _ in range(5)]
    assert validate_response_value({"entries": many}, schema)
    # Collection/node bounds permit this, but total serialized bytes do not.
    oversized = {str(i): "x" * MAX_STRING_BYTES for i in range(5)}
    assert validate_response_value(oversized, object_schema({str(i): {"type": "string"} for i in range(5)}))


def test_violation_reporting_is_bounded_and_does_not_include_values():
    schema = object_schema({str(i): {"type": "integer"} for i in range(MAX_PROPERTIES)})
    violations = validate_response_value({str(i): "private text" for i in range(MAX_PROPERTIES)}, schema)
    assert len(violations) == MAX_VIOLATIONS
    assert all("private text" not in error for error in violations)


def test_schema_conformant_but_incorrect_values_remain_unassessed():
    schema = object_schema({"calculation": {"type": "integer"}, "accepted": {"type": "boolean"}})
    # Structural acceptance supplies no oracle answer and no competence verdict.
    assert validate_response_value({"calculation": -999, "accepted": True}, schema) == ()


@pytest.mark.parametrize("value,accepted", [(None, True), (0, True), (37, True), (-8, True),
                                           (True, False), (False, False), (3.0, False), ("37", False)])
def test_nullable_integer_permits_missing_or_any_integer_without_forcing_answer(value, accepted):
    schema = object_schema({"quantity": {"type": ["integer", "null"]}})
    assert (validate_response_value({"quantity": value}, schema) == ()) is accepted


@pytest.mark.parametrize("value,accepted", [(None, True), ("", True), ("observed", True),
                                           (0, False), (False, False)])
def test_nullable_string_permits_missing_or_string(value, accepted):
    schema = object_schema({"label": {"type": ["string", "null"]}})
    assert (validate_response_value({"label": value}, schema) == ()) is accepted


def test_primitive_union_order_is_canonical_and_input_is_not_mutated():
    schema = object_schema({"value": {"type": ["null", "string", "integer"]}})
    before = copy.deepcopy(schema)
    opposite = object_schema({"value": {"type": ["integer", "string", "null"]}})
    assert canonical_schema_json(schema) == canonical_schema_json(opposite)
    assert schema == before
    assert canonicalize_schema(schema)["properties"]["value"]["type"] == ["integer", "null", "string"]


def test_nullable_type_union_does_not_allow_constants_or_structural_keywords():
    for keyword, supplied in (("const", None), ("enum", [None]), ("properties", {}),
                              ("items", {"type": "string"})):
        schema = object_schema({"value": {"type": ["integer", "null"], keyword: supplied}})
        with pytest.raises(ResponseSchemaError):
            canonicalize_schema(schema)
