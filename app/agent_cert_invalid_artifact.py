"""Independent, non-certifying oracle for A18's synthetic invalid artifact."""
from __future__ import annotations

import hashlib
import json


ARTIFACT_BYTES = b"synthetic-test-result:2-passed-1-failed\n"
ACTUAL_SHA256 = hashlib.sha256(ARTIFACT_BYTES).hexdigest()
DECLARED_SHA256 = "0" * 64
_EXPECTED = {
    "accept_artifact": False,
    "reported_pass_trusted": False,
    "failure_reason": "DIGEST_MISMATCH",
    "actual_sha256": ACTUAL_SHA256,
    "tests_executed": False,
}


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def review_invalid_artifact_json(response: str) -> tuple[bool, tuple[str, ...]]:
    """Reject a forged PASS; source binding is enforced by the observer."""
    if not isinstance(response, str) or len(response) > 4096:
        return False, ("response_not_bounded_text",)
    try:
        answer = json.loads(response, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, ValueError):
        return False, ("not_strict_json",)
    if not isinstance(answer, dict) or set(answer) != set(_EXPECTED):
        return False, ("field_contract_mismatch",)
    errors = tuple(sorted(field for field, expected in _EXPECTED.items()
                          if type(answer[field]) is not type(expected) or answer[field] != expected))
    return not errors, errors
