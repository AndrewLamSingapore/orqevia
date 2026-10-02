"""Documentation integrity, not runtime or market acceptance."""

import hashlib
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = ROOT / "docs" / "portfolio"
INDEX = json.loads((PORTFOLIO / "source-index-20260927.json").read_text(encoding="utf-8"))
EXPECTED_IDS = {"prime", "velyqua", "the-portal", "sky-tablet", "game-platform", "authority-engine"}


def test_exactly_six_products_and_lens_is_a_capability():
    assert len(INDEX["products"]) == 6
    assert {p["id"] for p in INDEX["products"]} == EXPECTED_IDS
    assert INDEX["evidence_lens_role"] == "CROSS_PRODUCT_CAPABILITY_NOT_SEVENTH_PRODUCT"


def test_dated_evidence_does_not_become_current_status_authority():
    assert INDEX["status_authority"] == "../../STATUS.md"
    assert INDEX["record_role"] == "SUBORDINATE_DATED_EVIDENCE_NOT_CURRENT_STATUS"
    assert INDEX["archive_role"] == "BYTE_IDENTICAL_HISTORICAL_PREPARATION_NOT_CURRENT_STATUS"
    status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
    assert status.count("## Portfolio current observation — 27 September 2026") == 1
    assert "Evidence Lens is a cross-product capability, not a seventh" in status
    assert "PRODUCTION_QUALIFICATION_FAIL" in status


def test_product_records_have_evidence_and_unproven_commercial_limits():
    required = {
        "target_customer", "proposition", "pricing_hypothesis_sgd", "internal_readiness",
        "technical_evidence", "external_validation", "contradictions_and_missing_evidence",
        "next_gate", "owner_action", "evidence_refs",
    }
    for product in INDEX["products"]:
        assert required <= product.keys()
        assert all(product[key] for key in required)
        assert re.fullmatch(r"[0-9a-f]{40}", product["source_sha"])
        assert product["commercial_level"] == "L0"
        assert "UNTESTED" in product["pricing_hypothesis_sgd"]
        assert product["external_validation"] == "NO_QUALIFYING_EXTERNAL_RECEIPT_IN_REVIEWED_REGISTER"


def test_historical_commercial_originals_have_exact_original_bytes():
    archive = PORTFOLIO / INDEX["archive_directory"]
    records = INDEX["archive"]
    assert len(records) == 9
    assert {p.name for p in archive.iterdir()} == {r["filename"] for r in records}
    for record in records:
        data = (archive / record["filename"]).read_bytes()
        assert len(data) == record["bytes"], record["filename"]
        assert hashlib.sha256(data).hexdigest() == record["sha256"], record["filename"]
    assert "archive/** -text" in (PORTFOLIO / ".gitattributes").read_text(encoding="utf-8")


def test_frozen_receipts_remain_separate_from_new_reconciliation():
    prime = next(p for p in INDEX["products"] if p["id"] == "prime")
    assert prime["source_sha"] != prime["runtime_source_sha"]
    assert prime["runtime_source_sha"] == "b171253566e7c879283d2aacf699ae6c1ec8988e"
    assert prime["rollback_image_tag"] == "prime:sha-17fad78"
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", prime["runtime_image_id"])
    assert len(INDEX["canonical_git_evidence"]) == 4
    for record in INDEX["canonical_git_evidence"]:
        assert re.fullmatch(r"[0-9a-f]{64}", record["sha256"])
        # These were recorded from raw Git blobs; CRLF working-tree conversion
        # must never be mistaken for a changed frozen receipt.
        data = subprocess.check_output(
            ["git", "cat-file", "blob", f"HEAD:{record['path']}"],
            cwd=ROOT,
        )
        assert len(data) == record["bytes"]
        assert hashlib.sha256(data).hexdigest() == record["sha256"]


def test_status_insertion_preserves_all_existing_sections_and_history():
    # Verify the insertion at its historical commit. Later legitimate status
    # entries must not change the original preservation claim.
    after = subprocess.check_output(
        ["git", "show", "f945f6019cdb4742359cdb714cc523b5fe8fe63c:STATUS.md"],
        cwd=ROOT,
    ).decode("utf-8")
    start = after.index("## Portfolio current observation — 27 September 2026")
    end = after.index("## PRIME / VELYQUA / ABEX", start)
    preserved = (after[:start] + after[end:]).encode("utf-8")
    baseline = INDEX["status_before_insertion"]
    assert len(preserved) == baseline["bytes"]
    assert hashlib.sha256(preserved).hexdigest() == baseline["sha256"]


def test_public_deployment_identity_is_not_physical_or_commercial_proof():
    public = [p for p in INDEX["products"] if p["id"] != "prime"]
    assert len(public) == 5
    assert len({p["deployment_id"] for p in public}) == 5
    assert all(p["production_alias"].startswith("https://") for p in public)
    assert "No functional browser/customer validation is implied" in INDEX["deployment_observation_note"]
    reconciliation = (PORTFOLIO / "PORTFOLIO_RECONCILIATION_20260927.md").read_text(encoding="utf-8")
    for boundary in ("Design is not an executed failure test", "W3-01 stays PARKED", "PARKED / NOT ACCEPTED", "MODEL_CONTENT"):
        assert boundary in reconciliation


def test_public_source_bindings_match_the_observed_deployment_receipt():
    receipt_path = PORTFOLIO / INDEX["deployment_receipt"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    deployments = {d["source_repository"]: d for d in receipt["deployments"]}
    for product in INDEX["products"]:
        if product["id"] == "prime":
            continue
        observed = deployments[product["repository"]]
        assert observed["source_sha"] == product["source_sha"]
        assert observed["id"] == product["deployment_id"]
        assert observed["state"] == "READY"
        assert observed["target"] == "production"
        host = product["production_alias"].removeprefix("https://").rstrip("/")
        assert host in observed["aliases"]
