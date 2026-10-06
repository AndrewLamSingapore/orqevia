"""Synthetic signing checks; no protected-main case or Azure key is used here."""
import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from app.agent_cert_azure_es256 import AzureES256CertificationVerifier
from app.agent_cert_azure_signer import ProtectedAzureES256Signer
from app.agent_certification import AgentCertificationRegistry
from scripts import run_a19_protected_attestation as attestation
from tests import test_agent_cert_a19_protected_review as case
from tests import test_agent_cert_azure_signer as signer_case


IDS = ("12345", "111", "67890", "222", "99999", "333")
NOW = datetime(2026, 10, 6, 7, 0, tzinfo=timezone.utc)


def _source():
    execution = case._raw(case._payload())
    a26 = case._raw(case._a26_receipt(execution))
    review = case.build_a19_a26_review_artifact(
        execution, case.PROFILE, a26, source_revision=case.SOURCE,
        review_run_id=IDS[4], trusted_execution_run=case._trusted(execution),
        trusted_a26_run=case._trusted_a26(a26))
    trusted_review = {
        **case._trusted(review), "workflow_ref": attestation.REVIEW_WORKFLOW,
        "run_id": IDS[4], "artifact_sha256": hashlib.sha256(review).hexdigest(),
    }
    return execution, case.PROFILE, a26, review, trusted_review


def _candidate(execution=None, profile=None, a26=None, review=None,
               trusted_review=None):
    originals = _source()
    execution = originals[0] if execution is None else execution
    profile = originals[1] if profile is None else profile
    a26 = originals[2] if a26 is None else a26
    review = originals[3] if review is None else review
    trusted_review = originals[4] if trusted_review is None else trusted_review
    return attestation.reviewed_case(
        execution, profile, a26, review, source=case.SOURCE,
        signing_run="55555", ids=IDS,
        execution_run=case._trusted(execution),
        a26_run=case._trusted_a26(a26), review_run=trusted_review,
        now=NOW)


def test_one_case_row_binds_exact_a19_a26_review_and_scope():
    execution, profile, a26, review, _ = _source()
    row = _candidate(execution, profile, a26, review)
    assert (row["agent_id"], row["dimension"], row["test_case"], row["test_result"]) == (
        "a19", "role", "normal", "PASS")
    assert row["verifier"] == "a26" and row["executor_identity"] == "a19"
    assert row["source_revision"] == case.SOURCE
    assert row["evidence_sha256"] == hashlib.sha256(execution).hexdigest()
    assert row["review_evidence_sha256"] == hashlib.sha256(review).hexdigest()
    assert row["a26_evidence_sha256"] == hashlib.sha256(a26).hexdigest()
    assert row["profile_sha256"] == hashlib.sha256(profile).hexdigest()
    assert row["review_run_id"] == IDS[4] and row["signing_run_id"] == "55555"
    assert row["attestation_scope"].endswith("no level claim")


@pytest.mark.parametrize("change", [
    {"ref_protected": False}, {"head_sha": "b" * 40},
    {"workflow_ref": "untrusted"}, {"conclusion": "failure"},
    {"run_id": IDS[0]}, {"artifact_sha256": "0" * 64},
])
def test_untrusted_review_run_never_builds_signing_row(change):
    *_, trusted = _source()
    with pytest.raises(ValueError, match="review provenance"):
        _candidate(trusted_review={**trusted, **change})


@pytest.mark.parametrize("mutation", [
    lambda row: row["queue_job"].update(result='{"latest_check_time":"10:00Z"}'),
    lambda row: row.update(role_review_pass=False),
    lambda row: row["observation"].update(case_review="ROLE_CHECK_FAIL"),
])
def test_failed_a19_answer_or_oracle_cannot_be_signed(mutation):
    execution = case._payload()
    mutation(execution)
    with pytest.raises(ValueError):
        _candidate(execution=case._raw(execution))


def test_a26_or_review_tamper_cannot_be_signed():
    execution, profile, a26, review, trusted = _source()
    a26_item = json.loads(a26)
    a26_item["decision"] = "FAIL"
    with pytest.raises(ValueError):
        _candidate(a26=case._raw(a26_item))
    forged_review = review.replace(b'"test_result":"PASS"', b'"test_result":"FAIL"')
    trusted = {**trusted, "artifact_sha256": hashlib.sha256(forged_review).hexdigest()}
    with pytest.raises(ValueError, match="review bytes"):
        _candidate(review=forged_review, trusted_review=trusted)


def _environment(monkeypatch, tmp_path):
    values = {
        "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": attestation.REPOSITORY,
        "GITHUB_REF": "refs/heads/main", "GITHUB_REF_PROTECTED": "true",
        "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_SHA": case.SOURCE,
        "GITHUB_RUN_ID": "55555", "PRIME_SIGNER_CALLER_REF": attestation.CALLER,
        "PRIME_A19_RUN_ID": IDS[0], "PRIME_A19_ARTIFACT_ID": IDS[1],
        "PRIME_A26_RUN_ID": IDS[2], "PRIME_A26_ARTIFACT_ID": IDS[3],
        "PRIME_REVIEW_RUN_ID": IDS[4], "PRIME_REVIEW_ARTIFACT_ID": IDS[5],
        "RUNNER_TEMP": str(tmp_path), "GH_TOKEN": "synthetic-gh-token",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize("key,value", [
    ("GITHUB_REF", "refs/heads/feature"),
    ("GITHUB_REF_PROTECTED", "false"),
    ("PRIME_SIGNER_CALLER_REF", "forged"),
    ("PRIME_A19_RUN_ID", "67890"),
    ("PRIME_REVIEW_ARTIFACT_ID", "111"),
    ("PRIME_A26_ARTIFACT_ID", ""),
])
def test_preflight_rejects_untrusted_or_partial_dispatch(monkeypatch, tmp_path, key, value):
    _environment(monkeypatch, tmp_path)
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        attestation.preflight()


def test_no_input_preserves_existing_canary_route(monkeypatch, tmp_path):
    _environment(monkeypatch, tmp_path)
    for name in attestation._IDS:
        monkeypatch.setenv(name, "")
    assert attestation.preflight() is None


@pytest.mark.parametrize("field,value", [
    ("review_run_id", "123/4"),
    ("review_run_id", "../123"),
    ("review_run_id", "123%2F4"),
    ("review_run_id", "123\n4"),
    ("review_test_version", "a19-role-exact+a26-independent/v1/../x"),
    ("review_test_version", "a19-role-exact%2Ba26-independent%2Fv1"),
    ("review_test_version", "a19-role-exact+a26-independent/v1\n"),
    ("review_test_version", "a19-role-exact+a26-independent/v1\x00"),
])
def test_review_provenance_separators_and_encoding_rejected_before_signing(
        tmp_path, field, value):
    synthetic, public, calls, root, row, _ = signer_case._fixture(tmp_path)
    review = signer_case._review_payload(row)
    (root / "a17" / "review.json").write_bytes(review)
    row.update({
        "review_evidence": "review.json",
        "review_evidence_sha256": hashlib.sha256(review).hexdigest(),
        "review_run_id": "protected-run-123",
        "review_source_revision": row["source_revision"],
        "review_test_version": "oracle.1",
    })
    row[field] = value
    oracle_calls = []
    signer = ProtectedAzureES256Signer(
        signer_case.SERVICE, signer_case.KEY_ID, public,
        synthetic._sign_digest,
        review_case=lambda *args: oracle_calls.append(args) or True)
    with pytest.raises(ValueError, match="review provenance required"):
        signer.sign_reviewed(row, evidence_root=root,
                             source_revision=row["source_revision"], now=signer_case.NOW)
    assert calls == [] and oracle_calls == []


def _files(tmp_path):
    execution, profile, a26, review, _ = _source()
    for directory, name, raw in (
        ("a19-execution", "a19-observation.json", execution),
        ("a19-execution", "profile.json", profile),
        ("a26-observation", "a26-observation.json", a26),
        ("a19-review", "a19-review.json", review),
    ):
        root = tmp_path / directory
        root.mkdir(exist_ok=True)
        (root / name).write_bytes(raw)
    return execution, profile, a26, review


def _trusted(workflow, raw):
    if workflow == "a19-offhost-role":
        return case._trusted(raw)
    if workflow == "a26-a19-observation":
        return case._trusted_a26(raw)
    return {**case._trusted(raw), "workflow_ref": attestation.REVIEW_WORKFLOW,
            "run_id": IDS[4]}


def test_tampered_review_blocks_oidc_and_key_vault(monkeypatch, tmp_path):
    _environment(monkeypatch, tmp_path)
    _files(tmp_path)
    review_path = tmp_path / "a19-review" / "a19-review.json"
    review_path.write_bytes(review_path.read_bytes().replace(b'"PASS"', b'"FAIL"'))
    monkeypatch.setattr(attestation, "_api_json", lambda path, token: {"protected": True})
    monkeypatch.setattr(attestation, "_trusted_run", lambda *args, workflow, raw, **kwargs:
                        _trusted(workflow, raw))
    monkeypatch.setattr(attestation, "_oidc", lambda: pytest.fail("OIDC requested before review"))
    with pytest.raises(ValueError):
        attestation.sign()
    assert not (tmp_path / "a19-attestation").exists()


def test_synthetic_reviewed_es256_sign_verify_and_tamper(monkeypatch, tmp_path):
    _environment(monkeypatch, tmp_path)
    _files(tmp_path)
    private = ec.generate_private_key(ec.SECP256R1())
    point = private.public_key().public_numbers()
    b64 = lambda n: base64.urlsafe_b64encode(n.to_bytes(32, "big")).rstrip(b"=").decode()
    pin = {"key_id": attestation.KEY_PREFIX + "a" * 32,
           "jwk": {"kty": "EC", "crv": "P-256", "x": b64(point.x), "y": b64(point.y)}}
    monkeypatch.setattr(attestation, "_api_json", lambda path, token: {"protected": True})
    monkeypatch.setattr(attestation, "_trusted_run", lambda *args, workflow, raw, **kwargs:
                        _trusted(workflow, raw))
    monkeypatch.setattr(attestation.json, "load", lambda stream, **kwargs: pin)
    monkeypatch.setattr(attestation, "_oidc", lambda: "synthetic-assertion")
    monkeypatch.setattr(attestation, "_azure_token", lambda assertion: "synthetic-bearer")
    calls = []

    def sign_digest(key_id, digest, *, access_token):
        calls.append((key_id, digest, access_token))
        der = private.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        r, s = utils.decode_dss_signature(der)
        return key_id, r.to_bytes(32, "big") + s.to_bytes(32, "big")

    monkeypatch.setattr(attestation, "key_vault_sign_digest", sign_digest)
    result = attestation.sign()
    assert result["result"] == "A19_ROLE_NORMAL_SIGNED_CASE_PASS"
    assert result["level_claim"] == "NONE" and len(calls) == 1
    record = json.loads((tmp_path / "a19-attestation" / "a19" / "certification.json").read_bytes())
    assert len(record["records"]) == 1
    signed = record["records"][0]
    verify = AzureES256CertificationVerifier({attestation.SERVICE: {pin["key_id"]: pin["jwk"]}})
    assert verify(signed)
    projection = AgentCertificationRegistry(
        tmp_path / "a19-attestation", source_revision=case.SOURCE,
        verify_record=verify).project("a19", "responsibility.a19",
                                      now=datetime.now(timezone.utc))
    assert projection["level"] == "L0"
    assert "role:normal" in projection["valid_cases"]
    for change in ({"test_result": "FAIL"}, {"agent_id": "a26"},
                   {"dimension": "baseline"}, {"review_evidence_sha256": "0" * 64}):
        assert not verify({**signed, **change})
