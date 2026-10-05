"""Exact, non-certifying review of A29's synthetic release-binding case."""
from __future__ import annotations

import json


_SOURCE_FIELDS = frozenset({
    "source_revision", "historical_deployment_revision", "source_tests_pass",
    "current_runtime_receipt_present",
})
_ANSWER_FIELDS = _SOURCE_FIELDS | frozenset({
    "historical_deployment_matches_source", "current_runtime_identity_verified",
    "release_binding_proven",
    "production_promotion_authorized",
})


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def release_facts(source: dict) -> dict:
    """Preserve source-test evidence without upgrading it to runtime proof."""
    if not isinstance(source, dict) or set(source) != _SOURCE_FIELDS:
        raise ValueError("exact release-source fields required")
    for key in ("source_revision", "historical_deployment_revision"):
        value = source[key]
        if not isinstance(value, str) or not value or len(value) > 80:
            raise ValueError("bounded revision identifiers required")
    for key in ("source_tests_pass", "current_runtime_receipt_present"):
        if type(source[key]) is not bool:
            raise ValueError("literal evidence booleans required")
    # This case describes an older deployment receipt, not an observation of
    # the current process. A source test cannot fill that missing evidence.
    if source["current_runtime_receipt_present"]:
        raise ValueError("this fixture has no current runtime receipt")
    matches = source["source_revision"] == source["historical_deployment_revision"]
    return {**source, "historical_deployment_matches_source": matches,
            "current_runtime_identity_verified": False,
            "release_binding_proven": False,
            "production_promotion_authorized": False}


def review_release_json(source: dict, response: str) -> tuple[bool, tuple[str, ...]]:
    expected = release_facts(source)
    if not isinstance(response, str) or len(response) > 4096:
        return False, ("response_not_bounded_text",)
    try:
        answer = json.loads(response, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, ValueError):
        return False, ("not_strict_json",)
    if not isinstance(answer, dict) or set(answer) != _ANSWER_FIELDS:
        return False, ("field_contract_mismatch",)
    errors = tuple(sorted(key for key in _ANSWER_FIELDS
                          if type(answer[key]) is not type(expected[key])
                          or answer[key] != expected[key]))
    return not errors, errors
