import pytest

from app.semantic_evidence import verify_evidence_claims


AUTH = {
    ("citation", "doc:1"): {"title": "Verified"},
    ("git_sha", "candidate"): "8b7dbe997c85bb21135d536b585867283c661ceb",
    ("database_record", "row:1"): {"state": "CURRENT"},
    ("tool_result", "tool:1"): {"exit_code": 0},
    ("authorization", "auth:1"): {"role": "MEMBER"},
    ("execution_receipt", "run:1"): {"accepted": True},
    ("test_result", "suite:1"): {"passed": 705, "failed": 0},
    ("retrieved_evidence", "rag:1"): {"digest": "abc", "statement": "verified"},
}


def claim(kind, reference, value):
    return {"kind": kind, "reference": reference, "value": value}


def test_exact_authoritative_claim_is_accepted_but_never_grants_authority_or_tool_execution():
    result = verify_evidence_claims([claim("citation", "doc:1", {"title": "Verified"})], AUTH)
    assert result.disposition == "ACCEPTED" and result.trusted_evidence
    assert not result.grants_authority and not result.may_trigger_tool


@pytest.mark.parametrize("fabricated", [
    claim("citation", "plausible-doi:10.1234/fake", {"title": "Plausible"}),
    claim("git_sha", "candidate", "0" * 40),
    claim("database_record", "row:404", {"state": "CURRENT"}),
    claim("tool_result", "tool:1", {"exit_code": 0, "fabricated": True}),
    claim("authorization", "auth:1", {"role": "OWNER"}),
    claim("execution_receipt", "run:404", {"accepted": True}),
    claim("test_result", "suite:1", {"passed": 706, "failed": 0}),
    claim("retrieved_evidence", "rag:1", {"digest": "wrong", "statement": "verified"}),
    claim("retrieved_evidence", "中文证据:不存在", {"声明": "已验证"}),
])
def test_plausible_fabrication_remains_verify_required(fabricated):
    result = verify_evidence_claims([fabricated], AUTH)
    assert result.disposition == "VERIFY_REQUIRED"
    assert not result.trusted_evidence and not result.may_persist_as_fact
    assert not result.grants_authority and not result.may_trigger_tool


def test_partially_true_bundle_is_not_promoted():
    claims = [
        claim("test_result", "suite:1", {"passed": 705, "failed": 0}),
        claim("git_sha", "candidate", "f" * 40),
    ]
    result = verify_evidence_claims(claims, AUTH)
    assert result.verified_claims == 1
    assert result.disposition == "VERIFY_REQUIRED"
    assert not result.trusted_evidence and not result.may_persist_as_fact


def test_confidence_language_cannot_substitute_for_evidence():
    result = verify_evidence_claims([{"kind": "citation", "reference": "fake", "value": {"claim": "certainly verified with 99.9% confidence"}}], AUTH)
    assert result.disposition == "VERIFY_REQUIRED"
