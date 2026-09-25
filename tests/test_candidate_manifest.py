import pytest

from scripts.candidate_manifest import build_manifest


BASE = dict(
    source_sha="8b7dbe997c85bb21135d536b585867283c661ceb",
    artifact_digest="sha256:" + "a" * 64,
    branch="feat/supreme-integration-20260925",
    tests={"passed": 705, "failed": 0},
    verification={"status": "PASS", "checks": 4},
    security={"status": "PASS", "secret_findings": 0},
    risk=["INTEGRATION", "MEMORY", "AUTHORITY", "SECURITY"],
    migrations=["candidate governed-memory schema only; production migration not authorized"],
    recovery=["retain commissioned production image and data", "forward-repair candidate in isolation"],
    acceptance_gates=["canonical", "full", "independent-verifier", "remote-sha"],
)


def test_manifest_is_deterministic_immutable_and_non_deploying():
    first = build_manifest(**BASE)
    second = build_manifest(**BASE)
    assert first == second
    assert first["status"] == "CANDIDATE_ONLY_NOT_DEPLOYED"
    assert len(first["manifest_sha256"]) == 64


@pytest.mark.parametrize("field,value", [
    ("source_sha", "short"),
    ("artifact_digest", "prime:latest"),
    ("tests", {"passed": 1, "failed": 1}),
    ("verification", {"status": "UNKNOWN"}),
    ("security", {"status": "UNKNOWN"}),
    ("risk", []),
    ("recovery", []),
    ("acceptance_gates", []),
])
def test_incomplete_or_floating_manifest_fails_closed(field, value):
    candidate = dict(BASE); candidate[field] = value
    with pytest.raises(ValueError):
        build_manifest(**candidate)
