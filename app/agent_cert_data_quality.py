"""Exact, non-certifying review of the synthetic a14 data-quality case."""
from __future__ import annotations

import json


_FIELDS = frozenset({"duplicate_ids", "negative_amount_ids",
                     "duplicate_row_indices", "negative_amount_row_indices",
                     "source_mutated", "validation"})


def _unique(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON field")
        value[key] = item
    return value


def data_quality_facts(rows: list[dict]) -> dict:
    """Derive defects from bounded source rows, never from the worker's claims."""
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ValueError("bounded rows required")
    seen = set()
    duplicate_ids = []
    negative_ids = []
    duplicate_indices = []
    negative_indices = []
    for index, row in enumerate(rows):
        if (not isinstance(row, dict) or set(row) != {"id", "amount"}
                or type(row["id"]) is not int or not 0 <= row["id"] <= 1_000_000
                or type(row["amount"]) is not int or abs(row["amount"]) > 1_000_000):
            raise ValueError("invalid source row")
        if row["id"] in seen:
            duplicate_indices.append(index)
            if row["id"] not in duplicate_ids:
                duplicate_ids.append(row["id"])
        seen.add(row["id"])
        if row["amount"] < 0:
            negative_indices.append(index)
            if row["id"] not in negative_ids:
                negative_ids.append(row["id"])
    return {"duplicate_ids": duplicate_ids, "negative_amount_ids": negative_ids,
            "duplicate_row_indices": duplicate_indices,
            "negative_amount_row_indices": negative_indices,
            "source_mutated": False,
            "validation": "FAIL" if duplicate_indices or negative_indices else "PASS"}


def review_data_quality_json(rows: list[dict], response: str) -> tuple[bool, tuple[str, ...]]:
    """Require exact findings and strict JSON; this never awards certification."""
    expected = data_quality_facts(rows)
    if not isinstance(response, str) or len(response) > 4096:
        return False, ("response_not_bounded_text",)
    try:
        answer = json.loads(response, object_pairs_hook=_unique)
    except (json.JSONDecodeError, ValueError):
        return False, ("not_strict_json",)
    if not isinstance(answer, dict) or set(answer) != _FIELDS:
        return False, ("field_contract_mismatch",)
    errors = []
    for key in sorted(_FIELDS):
        actual = answer[key]
        valid_type = type(actual) is type(expected[key])
        if isinstance(expected[key], list):
            valid_type = valid_type and all(type(item) is int for item in actual)
        if not valid_type or actual != expected[key]:
            errors.append(key)
    return not errors, tuple(errors)
