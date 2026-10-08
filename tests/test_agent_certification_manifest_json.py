"""Disposable manifest counterexamples; trusted fixture verifier, never live L7."""
import json

import pytest

from app.agent_certification import AgentCertificationRegistry
from tests.test_agent_certification import NOW, REVISION, fixture_rows


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def project(tmp_path, raw):
    (tmp_path / "a17" / "certification.json").write_bytes(raw.encode("utf-8"))
    return AgentCertificationRegistry(
        tmp_path, source_revision=REVISION,
        verify_record=lambda row: row.get("verifier") == "a18",
    ).project("a17", "responsibility.a17", now=NOW)


def denied(result):
    assert result["level"] == "L0"
    assert result["valid_cases"] == []
    assert result["current_cases"] == []


def test_control_valid_bounded_baseline_is_not_blanket_rejected(tmp_path):
    rows = fixture_rows(tmp_path, ("baseline",))
    result = project(tmp_path, encode({"schema_version": "1.0", "records": rows}))
    assert result["level"] == "L1"
    assert "baseline:identity" in result["current_cases"]


@pytest.mark.parametrize("second_key", ['"records"', '"\\u0072ecords"'])
def test_duplicate_top_level_rows_cannot_hide_actual_later_failure(tmp_path, second_key):
    rows = fixture_rows(tmp_path, ("baseline",))
    failed = dict(rows[0], test_result="FAIL", certified_at=NOW.isoformat(),
                  last_revalidated=NOW.isoformat(), failure_count=1)
    genuine = encode({"schema_version": "1.0", "records": rows + [failed]})
    assert project(tmp_path, genuine)["level"] == "L0"
    malformed = ('{"schema_version":"1.0","records":' + encode(rows + [failed])
                 + ',' + second_key + ':' + encode(rows) + '}')
    denied(project(tmp_path, malformed))


@pytest.mark.parametrize("second_key", ['"test_result"', '"test_\\u0072esult"'])
def test_duplicate_row_result_cannot_mask_its_failure(tmp_path, second_key):
    rows = fixture_rows(tmp_path, ("baseline",))
    failed = [dict(rows[0], test_result="FAIL"), *rows[1:]]
    assert project(tmp_path, encode({"schema_version": "1.0", "records": failed}))["level"] == "L0"
    first = encode(rows[0]).replace('"test_result":"PASS"',
        '"test_result":"FAIL",' + second_key + ':"PASS"')
    malformed = '{"schema_version":"1.0","records":[' + first + ',' + ','.join(
        encode(row) for row in rows[1:]) + ']}'
    denied(project(tmp_path, malformed))


def test_nested_duplicate_logic_signal_cannot_hide_counterevidence(tmp_path):
    rows = fixture_rows(tmp_path, ("logic_quality",))
    rows[0]["logic_signals"] = {"evidence_support": "FAIL"}
    ordinary = project(tmp_path, encode({"schema_version": "1.0", "records": rows}))
    assert "logic_quality:unsupported_assumption" not in ordinary["valid_cases"]
    raw = encode({"schema_version": "1.0", "records": rows}).replace(
        '"evidence_support":"FAIL"',
        '"evidence_support":"FAIL","evidence_\\u0073upport":"PASS"')
    denied(project(tmp_path, raw))


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "1e309"])
def test_nonfinite_manifest_is_not_normalized_into_current_cases(tmp_path, literal):
    rows = fixture_rows(tmp_path, ("baseline",))
    raw = '{"schema_version":"1.0","observation_cost":' + literal + ',"records":' + encode(rows) + '}'
    denied(project(tmp_path, raw))


@pytest.mark.parametrize("literal", ["-Infinity", "-1e309"])
def test_negative_nonfinite_values_are_also_rejected(tmp_path, literal):
    rows = fixture_rows(tmp_path, ("baseline",))
    raw = '{"schema_version":"1.0","measurement":' + literal + ',"records":' + encode(rows) + '}'
    denied(project(tmp_path, raw))


@pytest.mark.parametrize("literal", ["0", "-1", "1.5", "1e308"])
def test_finite_metadata_does_not_invalidate_valid_evidence(tmp_path, literal):
    rows = fixture_rows(tmp_path, ("baseline",))
    raw = '{"schema_version":"1.0","measurement":' + literal + ',"records":' + encode(rows) + '}'
    assert project(tmp_path, raw)["level"] == "L1"


def test_deep_malformed_manifest_is_unknown_not_an_unhandled_error(tmp_path):
    fixture_rows(tmp_path, ("baseline",))
    denied(project(tmp_path, '{"schema_version":"1.0","records":' + '[' * 2000 + '}' ))


@pytest.mark.parametrize("field", ["last_revalidated", "certified_at", "expires_at"])
@pytest.mark.parametrize("value", [None, {}, [], 1, True])
def test_non_string_timestamp_rejects_case_without_crashing_projection(tmp_path, field, value):
    rows = fixture_rows(tmp_path, ("baseline",))
    rejected_case = "baseline:" + rows[0]["test_case"]
    rows[0][field] = value
    result = project(tmp_path, encode({"schema_version": "1.0", "records": rows}))
    assert result["level"] == "L0"
    assert result["current_cases"] == []
    assert rejected_case not in result["valid_cases"]
    # Retain distinct unaffected records; bad time is not a blanket rewrite.
    assert len(result["valid_cases"]) == len(rows) - 1
