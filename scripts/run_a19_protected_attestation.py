"""Sign one exact protected-main A19 role case after a distinct A26 review.

The existing OIDC caller and reusable Azure signer remain the only signing
boundary. Dispatch inputs are identifiers, never evidence or executable code.
This emits one case record; it does not assert a certification level or change
an agent's authority.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import sys

from app.agent_cert_a19_a26_review import (REVIEW_TEST_VERSION,
                                            build_a19_a26_review_artifact)
from app.agent_cert_azure_es256 import AzureES256CertificationVerifier
from app.agent_cert_azure_signer import (ProtectedAzureES256Signer,
                                         key_vault_sign_digest)
from app.agent_registry import agent_record
from scripts.azure_verifier_live_canary import (KEY_PREFIX, _azure_token, _oidc,
                                                _unique)
from scripts.run_a19_protected_review_job import (_api_json, _file, _trusted_run)


REPOSITORY = "AndrewLamSingapore/prime"
CALLER = f"{REPOSITORY}/.github/workflows/prime-verifier-oidc.yml@refs/heads/main"
REVIEW_WORKFLOW = f"{REPOSITORY}/.github/workflows/a19-protected-review.yml@refs/heads/main"
SERVICE = "svc.cert-verifier.independent"
_REVISION = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IDS = (
    "PRIME_A19_RUN_ID", "PRIME_A19_ARTIFACT_ID",
    "PRIME_A26_RUN_ID", "PRIME_A26_ARTIFACT_ID",
    "PRIME_REVIEW_RUN_ID", "PRIME_REVIEW_ARTIFACT_ID",
)
_RUN_FIELDS = {
    "repository", "repository_id", "workflow_ref", "ref", "ref_protected",
    "event_name", "head_sha", "run_id", "run_attempt", "conclusion",
    "artifact_sha256",
}


def preflight() -> tuple[str, str, tuple[str, ...]] | None:
    """Allow existing no-input canaries or one complete six-ID case request."""
    source, signing_run = os.getenv("GITHUB_SHA", ""), os.getenv("GITHUB_RUN_ID", "")
    if (os.getenv("GITHUB_ACTIONS") != "true"
            or os.getenv("GITHUB_REPOSITORY") != REPOSITORY
            or os.getenv("GITHUB_REF") != "refs/heads/main"
            or os.getenv("GITHUB_REF_PROTECTED") != "true"
            or os.getenv("GITHUB_EVENT_NAME") != "workflow_dispatch"
            or os.getenv("PRIME_SIGNER_CALLER_REF") != CALLER
            or not _REVISION.fullmatch(source)
            or not signing_run.isdecimal()):
        raise ValueError("protected canonical signer invocation required")
    ids = tuple(os.getenv(name, "") for name in _IDS)
    if not any(ids):
        return None
    if (any(not value.isdecimal() or len(value) > 20 for value in ids)
            or len({ids[0], ids[2], ids[4], signing_run}) != 4
            or len({ids[1], ids[3], ids[5]}) != 3):
        raise ValueError("six exact, distinct run/artifact IDs required")
    return source, signing_run, ids


def _review_run(trusted: dict, raw: bytes, *, source: str, run_id: str) -> None:
    if (not isinstance(trusted, dict) or set(trusted) != _RUN_FIELDS
            or trusted["repository"] != REPOSITORY
            or trusted["repository_id"] != "1345668764"
            or trusted["workflow_ref"] != REVIEW_WORKFLOW
            or trusted["ref"] != "refs/heads/main"
            or trusted["ref_protected"] is not True
            or trusted["event_name"] != "workflow_dispatch"
            or trusted["head_sha"] != source
            or trusted["run_id"] != run_id
            or trusted["conclusion"] != "success"
            or not isinstance(trusted["run_attempt"], str)
            or not trusted["run_attempt"].isdecimal()
            or trusted["artifact_sha256"] != hashlib.sha256(raw).hexdigest()):
        raise ValueError("independent protected review provenance mismatch")


def reviewed_case(execution: bytes, profile: bytes, a26: bytes, review: bytes, *,
                  source: str, signing_run: str, ids: tuple[str, ...],
                  execution_run: dict, a26_run: dict, review_run: dict,
                  now: datetime) -> dict:
    """Recompute both exact role judgments and build one unsigned case row."""
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("aware signing time required")
    _review_run(review_run, review, source=source, run_id=ids[4])
    expected = build_a19_a26_review_artifact(
        execution, profile, a26, source_revision=source,
        review_run_id=ids[4], trusted_execution_run=execution_run,
        trusted_a26_run=a26_run)
    if (execution_run.get("run_id") != ids[0]
            or a26_run.get("run_id") != ids[2]
            or not hmac.compare_digest(review, expected)):
        raise ValueError("independent review bytes do not match exact case")
    envelope = json.loads(expected, object_pairs_hook=_unique)
    observed = envelope["observations"]
    receipt = json.loads(execution, object_pairs_hook=_unique)
    if (not _SHA256.fullmatch(observed["case_spec_sha256"])
            or not _SHA256.fullmatch(observed["a26_receipt_sha256"])
            or not _SHA256.fullmatch(receipt["model_digest"])):
        raise ValueError("case hash or model identity invalid")
    signed_at = now.astimezone(timezone.utc)
    instant = lambda value: value.isoformat().replace("+00:00", "Z")
    return {
        "agent_id": "a19", "capability_id": "responsibility.a19",
        "dimension": "role", "test_case": "normal",
        "certification_test": "a19-offhost-role+a26-independent-review",
        "test_version": "group_two_exact_role_oracle/v1",
        "test_result": "PASS", "verifier": "a26", "executor_identity": "a19",
        "evidence": "a19-observation.json",
        "evidence_sha256": hashlib.sha256(execution).hexdigest(),
        "review_evidence": "a19-review.json",
        "review_evidence_sha256": hashlib.sha256(review).hexdigest(),
        "review_run_id": ids[4], "review_source_revision": source,
        "review_test_version": REVIEW_TEST_VERSION,
        "a19_run_id": ids[0], "a19_artifact_id": ids[1],
        "a26_run_id": ids[2], "a26_artifact_id": ids[3],
        "review_artifact_id": ids[5], "signing_run_id": signing_run,
        "a26_evidence_sha256": hashlib.sha256(a26).hexdigest(),
        "profile_sha256": hashlib.sha256(profile).hexdigest(),
        "case_spec_sha256": observed["case_spec_sha256"],
        "model_digest": receipt["model_digest"],
        "certified_at": instant(signed_at),
        "last_revalidated": instant(signed_at),
        "expires_at": instant(signed_at + timedelta(days=6)),
        "source_revision": source,
        "authority_scope": agent_record("a19")["authority"],
        "attestation_scope": "single role:normal case; no level claim",
    }


def _write_once(root: Path, name: str, raw: bytes) -> None:
    target = root / name
    if root.is_symlink() or target.is_symlink() or target.exists():
        raise ValueError("attestation output already exists or is a link")
    with target.open("xb") as stream:
        stream.write(raw)


def sign() -> dict:
    bound = preflight()
    if bound is None:
        raise ValueError("attestation IDs required")
    source, signing_run, ids = bound
    token = os.getenv("GH_TOKEN", "")
    if _api_json("branches/main", token).get("protected") is not True:
        raise ValueError("GitHub main protection is not active")
    runner_temp = Path(os.environ["RUNNER_TEMP"])
    if not runner_temp.is_absolute() or runner_temp.is_symlink():
        raise ValueError("absolute runner temp required")
    runner_temp = runner_temp.resolve()
    execution = _file(runner_temp / "a19-execution", "a19-observation.json")
    profile = _file(runner_temp / "a19-execution", "profile.json")
    a26 = _file(runner_temp / "a26-observation", "a26-observation.json")
    review = _file(runner_temp / "a19-review", "a19-review.json")
    execution_run = _trusted_run(
        ids[0], ids[1], workflow="a19-offhost-role",
        artifact_name=f"a19-offhost-observation-{ids[0]}", raw=execution,
        source=source, protected=True, token=token)
    a26_run = _trusted_run(
        ids[2], ids[3], workflow="a26-a19-observation",
        artifact_name=f"a26-a19-observation-{ids[2]}", raw=a26,
        source=source, protected=True, token=token)
    review_run = _trusted_run(
        ids[4], ids[5], workflow="a19-protected-review",
        artifact_name=f"a19-a26-unsigned-review-{ids[4]}", raw=review,
        source=source, protected=True, token=token)
    now = datetime.now(timezone.utc)
    row = reviewed_case(
        execution, profile, a26, review, source=source,
        signing_run=signing_run, ids=ids, execution_run=execution_run,
        a26_run=a26_run, review_run=review_run, now=now)
    with open("governance/agent-cert-verifier-azure-pins.json", encoding="utf-8") as stream:
        pin = json.load(stream, object_pairs_hook=_unique)
    key_id = pin.get("key_id") if isinstance(pin, dict) else None
    if (not isinstance(key_id, str)
            or not re.fullmatch(re.escape(KEY_PREFIX) + r"[0-9a-f]{32}", key_id)
            or set(pin) != {"key_id", "jwk"}):
        raise ValueError("unexpected verifier key pin")
    # Do not request OIDC or a Key Vault bearer until every provenance and
    # case-specific semantic check above has passed.
    bearer = _azure_token(_oidc())
    output = runner_temp / "a19-attestation" / "a19"
    output.mkdir(parents=True, exist_ok=False)
    _write_once(output, "a19-observation.json", execution)
    _write_once(output, "profile.json", profile)
    _write_once(output, "a26-observation.json", a26)
    _write_once(output, "a19-review.json", review)
    signer = ProtectedAzureES256Signer(
        SERVICE, key_id, pin["jwk"],
        lambda digest: key_vault_sign_digest(key_id, digest, access_token=bearer),
        review_case=lambda candidate, primary, independent: (
            candidate == row and primary == execution and independent == review))
    signed = signer.sign_reviewed(
        row, evidence_root=output.parent, source_revision=source, now=now)
    verify = AzureES256CertificationVerifier({SERVICE: {key_id: pin["jwk"]}})
    if (not verify(signed)
            or verify({**signed, "test_result": "FAIL"})
            or verify({**signed, "evidence_sha256": "0" * 64})
            or verify({**signed, "review_evidence_sha256": "0" * 64})):
        raise ValueError("signed case fails public verification or tamper rejection")
    record = {"schema_version": "1.0", "records": [signed]}
    _write_once(output, "certification.json",
                (json.dumps(record, sort_keys=True, indent=2) + "\n").encode())
    return {
        "result": "A19_ROLE_NORMAL_SIGNED_CASE_PASS",
        "level_claim": "NONE", "agent_id": "a19", "dimension": "role",
        "test_case": "normal", "source_revision": source,
        "signing_run_id": signing_run, "a19_run_id": ids[0],
        "a26_run_id": ids[2], "review_run_id": ids[4],
        "evidence_sha256": row["evidence_sha256"],
        "review_evidence_sha256": row["review_evidence_sha256"],
        "signed_record_sha256": hashlib.sha256(
            (json.dumps(record, sort_keys=True, indent=2) + "\n").encode()).hexdigest(),
    }


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--preflight"]:
            result = preflight()
            print("protected signer preflight: " + ("CASE" if result else "CANARY"))
        elif sys.argv[1:] == ["--sign"]:
            print(json.dumps(sign(), sort_keys=True))
        else:
            raise ValueError("preflight or sign mode required")
    except Exception as exc:
        # Upstream response bodies, OIDC assertion, and Azure bearer stay out
        # of the log even on exceptions.
        print("A19 protected attestation blocked: " + type(exc).__name__, file=sys.stderr)
        sys.exit(2)
