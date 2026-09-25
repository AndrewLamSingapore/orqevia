"""Independent deterministic verifier for portfolio application boundaries."""
from app.application_boundaries import evaluate_application_evidence, require_application_scope


def main() -> int:
    checks = 0
    for evidence_class in ("SIMULATED", "REPLAYED", "LAB", "PHYSICAL_UNVERIFIED"):
        result = evaluate_application_evidence({
            "application": "VELYQUA", "evidence_class": evidence_class,
            "claim": "bounded claim", "provenance": ["verifier:fixture"],
            "verification_ref": None,
        })
        assert not result.may_claim_physical and not result.grants_authority
        checks += 1
    verified = evaluate_application_evidence({
        "application": "VELYQUA", "evidence_class": "PHYSICAL_VERIFIED",
        "claim": "bounded claim", "provenance": ["physical:fixture"],
        "verification_ref": "receipt:fixture",
    })
    assert verified.may_claim_physical and not verified.grants_authority
    checks += 1
    try:
        require_application_scope(application="VELYQUA", scope_id="JARVIS")
        raise AssertionError("cross-application scope was accepted")
    except PermissionError:
        checks += 1
    print({"status": "PASS", "checks": checks, "production_touched": False})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
