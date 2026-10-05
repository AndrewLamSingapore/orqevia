import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.agent_certification import (AgentCertificationRegistry, LEVEL_DIMENSIONS,
                                     REQUIRED_CASES, LOGIC_SIGNALS, MAX_EVIDENCE_BYTES)
from app.agent_registry import load_agent_registry


NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)
REVISION = "a" * 40


def fixture_rows(tmp_path, dimensions, *, agent_id="a17", capability_id="responsibility.a17"):
    agent_dir = tmp_path / agent_id
    agent_dir.mkdir(exist_ok=True)
    rows = []
    for dimension in dimensions:
        for test_case in REQUIRED_CASES.get(dimension, ("complete",)):
            evidence = f"{dimension}-{test_case}.txt"
            payload = f"fixture evidence for {dimension}/{test_case}".encode()
            (agent_dir / evidence).write_bytes(payload)
            rows.append({"agent_id": agent_id, "capability_id": capability_id,
                         "dimension": dimension, "test_case": test_case,
                         "certification_test": f"fixture.{dimension}.{test_case}",
                         "test_version": "1", "test_result": "PASS", "verifier": "a18",
                         "evidence": evidence, "evidence_sha256": hashlib.sha256(payload).hexdigest(),
                         "certified_at": (NOW - timedelta(days=1)).isoformat(),
                         "last_revalidated": NOW.isoformat(),
                         "expires_at": (NOW + timedelta(days=1)).isoformat(),
                         "source_revision": REVISION, "authority_scope": "restricted",
                         "health": "HEALTHY", "failure_count": 0, "recovery_result": "PASS",
                         "logic_signals": {LOGIC_SIGNALS[test_case]: "PASS"}
                         if dimension == "logic_quality" else {}})
    (agent_dir / "certification.json").write_text(json.dumps({"schema_version": "1.0", "records": rows}))
    return rows


def projection(tmp_path):
    return AgentCertificationRegistry(tmp_path, source_revision=REVISION,
                                      verify_record=lambda row: row.get("verifier") == "a18").project(
        "a17", "responsibility.a17", now=NOW)


def test_all_21_default_to_l0_without_domain_evidence(tmp_path):
    registry = AgentCertificationRegistry(tmp_path, source_revision=REVISION)
    agents = load_agent_registry()["agents"]
    assert len(agents) == 21
    for agent in agents:
        for capability in agent["capability_requirements"]:
            result = registry.project(agent["id"], capability, now=NOW)
            assert result["level"] == "L0"
            assert result["trust_state"] == "UNPROVEN"


def test_current_independent_artifacts_can_project_ladder_without_granting_authority(tmp_path):
    fixture_rows(tmp_path, LEVEL_DIMENSIONS[-1])
    assert AgentCertificationRegistry(tmp_path, source_revision=REVISION).project(
        "a17", "responsibility.a17", now=NOW)["level"] == "L0"
    result = projection(tmp_path)
    assert result["level"] == "L6"
    assert result["trust_state"] == "CERTIFIED-HEALTHY"
    assert result["authority_scope"] == "restricted"
    assert len(result["current_dimensions"]) == len(LEVEL_DIMENSIONS[-1])


def test_expiry_and_changed_source_require_revalidation(tmp_path):
    fixture_rows(tmp_path, ("baseline",))
    assert projection(tmp_path)["level"] == "L1"
    late = AgentCertificationRegistry(tmp_path, source_revision=REVISION,
                                      verify_record=lambda row: True).project(
        "a17", "responsibility.a17", now=NOW + timedelta(days=2))
    assert (late["level"], late["trust_state"]) == ("L0", "REVALIDATION-REQUIRED")
    changed = AgentCertificationRegistry(tmp_path, source_revision="b" * 40,
                                         verify_record=lambda row: True).project(
        "a17", "responsibility.a17", now=NOW)
    assert (changed["level"], changed["trust_state"]) == ("L0", "REVALIDATION-REQUIRED")


def test_latest_failed_check_downgrades_prior_pass(tmp_path):
    rows = fixture_rows(tmp_path, ("baseline", "role"))
    role_row = next(row for row in rows if row["dimension"] == "role")
    failed = dict(role_row, test_result="FAIL", certified_at=NOW.isoformat(),
                  last_revalidated=NOW.isoformat(), failure_count=1)
    (tmp_path / "a17" / "certification.json").write_text(
        json.dumps({"schema_version": "1.0", "records": rows + [failed]}))
    result = projection(tmp_path)
    assert (result["level"], result["trust_state"], result["failure_count"]) == (
        "L1", "REVALIDATION-REQUIRED", 1)


def test_later_revalidation_and_tied_fail_override_old_pass(tmp_path):
    rows = fixture_rows(tmp_path, ("baseline", "role"))
    role_row = next(row for row in rows if row["dimension"] == "role")
    later = dict(role_row, test_result="FAIL",
                 last_revalidated=(NOW + timedelta(hours=1)).isoformat())
    manifest = tmp_path / "a17" / "certification.json"
    manifest.write_text(json.dumps({"schema_version": "1.0", "records": rows + [later]}))
    assert AgentCertificationRegistry(tmp_path, source_revision=REVISION,
                                      verify_record=lambda row: True).project(
        "a17", "responsibility.a17", now=NOW + timedelta(hours=2))["level"] == "L1"
    tied = dict(role_row, test_result="FAIL")
    manifest.write_text(json.dumps({"schema_version": "1.0", "records": rows + [tied]}))
    assert projection(tmp_path)["level"] == "L1"


@pytest.mark.parametrize("defect", ["revoked_verifier", "bad_hash"])
@pytest.mark.parametrize("bad_first", [False, True])
def test_conflicting_tied_pass_rows_fail_closed_in_any_order(tmp_path, defect, bad_first):
    rows = fixture_rows(tmp_path, ("baseline", "role"))
    original = next(row for row in rows if row["dimension"] == "role")
    conflict = dict(original)
    if defect == "revoked_verifier":
        conflict["verifier"] = "a26"
    else:
        conflict["evidence_sha256"] = "0" * 64
    ordered = ([conflict] + rows) if bad_first else (rows + [conflict])
    (tmp_path / "a17" / "certification.json").write_text(
        json.dumps({"schema_version": "1.0", "records": ordered}))
    assert projection(tmp_path)["level"] == "L1"
    repaired = dict(original, certified_at=(NOW + timedelta(hours=1)).isoformat(),
                    last_revalidated=(NOW + timedelta(hours=1)).isoformat())
    (tmp_path / "a17" / "certification.json").write_text(
        json.dumps({"schema_version": "1.0", "records": ordered + [repaired]}))
    assert AgentCertificationRegistry(tmp_path, source_revision=REVISION,
                                      verify_record=lambda row: row.get("verifier") == "a18").project(
        "a17", "responsibility.a17", now=NOW + timedelta(hours=2))["level"] == "L2"


def test_self_verification_missing_artifact_and_wrong_capability_cannot_certify(tmp_path):
    rows = fixture_rows(tmp_path, ("baseline",))
    rows[0]["verifier"] = "a17"
    (tmp_path / "a17" / "certification.json").write_text(
        json.dumps({"schema_version": "1.0", "records": rows}))
    assert projection(tmp_path)["level"] == "L0"
    rows[0]["verifier"] = "a18"
    (tmp_path / "a17" / rows[0]["evidence"]).unlink()
    assert projection(tmp_path)["level"] == "L0"
    registry = AgentCertificationRegistry(tmp_path, source_revision=REVISION)
    assert registry.project("a17", "responsibility.a18", now=NOW)["level"] == "L0"


def test_revoked_verifier_and_degraded_health_prevent_l6(tmp_path):
    rows = fixture_rows(tmp_path, LEVEL_DIMENSIONS[-1])
    revoked = AgentCertificationRegistry(tmp_path, source_revision=REVISION,
                                         verify_record=lambda row: False).project(
        "a17", "responsibility.a17", now=NOW)
    assert (revoked["level"], revoked["trust_state"]) == ("L0", "REVALIDATION-REQUIRED")
    health = next(row for row in rows if row["dimension"] == "health")
    health["health"] = "DEGRADED"
    (tmp_path / "a17" / "certification.json").write_text(
        json.dumps({"schema_version": "1.0", "records": rows}))
    degraded = projection(tmp_path)
    assert (degraded["level"], degraded["trust_state"], degraded["health"]) == (
        "L5", "CERTIFIED-DEGRADED", "UNKNOWN")


@pytest.mark.parametrize("case,signal", LOGIC_SIGNALS.items())
def test_missing_or_failed_logic_signal_blocks_highest_projection(tmp_path, case, signal):
    rows = fixture_rows(tmp_path, LEVEL_DIMENSIONS[-1])
    target = next(row for row in rows if row["dimension"] == "logic_quality"
                  and row["test_case"] == case)
    manifest = tmp_path / "a17" / "certification.json"
    for value in (None, "FAIL", "UNVERIFIED", "NOT_APPLICABLE"):
        target["logic_signals"] = {} if value is None else {signal: value}
        manifest.write_text(json.dumps({"schema_version": "1.0", "records": rows}))
        result = projection(tmp_path)
        assert result["level"] == "L5"
        assert "logic_quality" not in result["current_dimensions"]


def test_latest_weak_logic_failure_requires_independent_revalidation(tmp_path):
    rows = fixture_rows(tmp_path, LEVEL_DIMENSIONS[-1])
    original = next(row for row in rows if row["dimension"] == "logic_quality"
                    and row["test_case"] == "counterevidence")
    failed = dict(original, test_result="FAIL", failure_count=1,
                  certified_at=(NOW + timedelta(hours=1)).isoformat(),
                  last_revalidated=(NOW + timedelta(hours=1)).isoformat(),
                  logic_signals={"counterexample_check": "FAIL"})
    manifest = tmp_path / "a17" / "certification.json"
    manifest.write_text(json.dumps({"schema_version": "1.0", "records": rows + [failed]}))
    current_time = NOW + timedelta(hours=2)
    registry = AgentCertificationRegistry(tmp_path, source_revision=REVISION,
                                          verify_record=lambda row: row.get("verifier") == "a18")
    result = registry.project("a17", "responsibility.a17", now=current_time)
    assert (result["level"], result["trust_state"], result["failure_count"]) == (
        "L5", "REVALIDATION-REQUIRED", 1)
    repaired_payload = b"independently reviewed counterevidence repair"
    (tmp_path / "a17" / "logic-quality-counterevidence-revalidated.txt").write_bytes(repaired_payload)
    repaired = dict(original, certified_at=(NOW + timedelta(hours=3)).isoformat(),
                    last_revalidated=(NOW + timedelta(hours=3)).isoformat(),
                    evidence="logic-quality-counterevidence-revalidated.txt",
                    evidence_sha256=hashlib.sha256(repaired_payload).hexdigest(),
                    logic_signals={"counterexample_check": "PASS"})
    manifest.write_text(json.dumps({"schema_version": "1.0", "records": rows + [failed, repaired]}))
    result = registry.project("a17", "responsibility.a17", now=NOW + timedelta(hours=4))
    assert result["level"] == "L6"


def test_one_role_or_general_case_cannot_promote_whole_dimension(tmp_path):
    rows = fixture_rows(tmp_path, ("baseline", "role", "general"))
    partial = [row for row in rows if row["dimension"] == "baseline" or row["test_case"] == "normal"]
    (tmp_path / "a17" / "certification.json").write_text(
        json.dumps({"schema_version": "1.0", "records": partial}))
    assert projection(tmp_path)["level"] == "L1"
    partial = [row for row in rows if row["dimension"] != "general" or row["test_case"] == "analysis"]
    (tmp_path / "a17" / "certification.json").write_text(
        json.dumps({"schema_version": "1.0", "records": partial}))
    assert projection(tmp_path)["level"] == "L2"


def test_oversized_artifact_cannot_promote(tmp_path):
    rows = fixture_rows(tmp_path, ("baseline",))
    target = tmp_path / "a17" / rows[0]["evidence"]
    target.write_bytes(b"x" * (MAX_EVIDENCE_BYTES + 1))
    rows[0]["evidence_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    (tmp_path / "a17" / "certification.json").write_text(
        json.dumps({"schema_version": "1.0", "records": rows}))
    assert projection(tmp_path)["level"] == "L0"


def test_reused_artifact_cannot_claim_distinct_role_cases(tmp_path):
    rows = fixture_rows(tmp_path, ("baseline", "role"))
    role_rows = [row for row in rows if row["dimension"] == "role"]
    for row in role_rows[1:]:
        row["evidence"] = role_rows[0]["evidence"]
        row["evidence_sha256"] = role_rows[0]["evidence_sha256"]
    (tmp_path / "a17" / "certification.json").write_text(
        json.dumps({"schema_version": "1.0", "records": rows}))
    assert projection(tmp_path)["level"] == "L1"


@pytest.mark.parametrize("shape", [[], "invalid", None])
def test_malformed_manifest_shape_fails_closed(tmp_path, shape):
    fixture_rows(tmp_path, ("baseline",))
    (tmp_path / "a17" / "certification.json").write_text(json.dumps(shape))
    assert projection(tmp_path)["level"] == "L0"


def test_agent_directory_and_manifest_symlinks_fail_closed(tmp_path):
    root = tmp_path / "root"
    external = tmp_path / "external"
    external.mkdir()
    fixture_rows(external, ("baseline",))
    root.mkdir()
    try:
        (root / "a17").symlink_to(external / "a17", target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable on this host")
    assert AgentCertificationRegistry(root, source_revision=REVISION,
                                      verify_record=lambda row: True).project(
        "a17", "responsibility.a17", now=NOW)["level"] == "L0"
    local = tmp_path / "local"
    local.mkdir()
    fixture_rows(local, ("baseline",))
    manifest = local / "a17" / "certification.json"
    manifest.unlink()
    manifest.symlink_to(external / "a17" / "certification.json")
    assert projection(local)["level"] == "L0"
