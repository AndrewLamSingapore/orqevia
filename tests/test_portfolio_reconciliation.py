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
    after = (ROOT / "STATUS.md").read_text(encoding="utf-8")
    # The 6 October interpretation changed only the opening date and scope
    # paragraphs. Require those exact bytes before restoring the 4 October
    # opening, so any unaccounted edit still fails the frozen history proof.
    title = "# STATUS.md — Portfolio status record\n\n"
    interpretation = (
        "Interpretation updated: 6 October 2026. Dated observations below retain their original dates.\n\n"
        "STATUS.md is the human-readable portfolio status index: it records dated claims, evidence, and open work. It is not a universal source of truth or a synchronization target. Each product owns its source, configuration, contracts, and domain records; runtime, deployment, identity, registries, and evidence each have their own scoped authority. Reconcile disagreements by domain ownership, version, and provenance. Runtime claims require observed deployment identity and evidence receipts; a source commit or CI result alone does not establish them. Historical SSOT mentions below describe the former arrangement and do not reinstate it.\n\n"
        "STATUS.md records current portfolio status claims and their evidence classification. Each product owns its source, configuration, contracts, and domain records in its repository.\n\n"
    )
    prior_scope = (
        "STATUS.md records current portfolio status claims and their evidence classification. It does not own implementation, runtime configuration, domain data, or product contracts. Each product owns its source, configuration, contracts, and domain records in its repository. Runtime claims require observed deployment identity and evidence receipts; a source commit or CI result alone does not establish them. Historical SSOT files remain dated evidence, not parallel current portfolio status records."
    )
    assert after.startswith(title + interpretation)
    after = title + "Last updated: 4 October 2026\n\n" + prior_scope + "\n\n" + after[len(title + interpretation):]
    # This dated, agent-reported update is new; preserve the original historical
    # byte proof by removing only this known addition before comparing it.
    authority_start = after.index("## Status authority — 3 October 2026")
    authority_end = after.index("## Portfolio current observation — 27 September 2026", authority_start)
    authority_update = after[authority_start:authority_end]
    assert "### Claimed, not independently checked" in authority_update
    assert "PRIME PR #149 merged" in authority_update
    after = after[:authority_start] + after[authority_end:]
    after = after.replace("Last updated: 4 October 2026", "Last updated: 27 September 2026", 1)
    # Reconstruct only the known 4 October status-scope correction before
    # comparing the frozen 27 September bytes; all other historical text must
    # still match the original digest exactly.
    after = after.replace("# STATUS.md — Portfolio status record", "# STATUS.md — Single source of truth", 1)
    after = after.replace(
        prior_scope,
        "**This file replaces and supersedes every previous SSOT document — technical, course-study, and job-search alike.** Any older SSOT file (on ABEX, in a repo, or elsewhere) is now historical only. Do not treat any prior SSOT document as current once this file exists. Archive or delete the old ones once this file is confirmed good — do not maintain both in parallel.",
        1,
    )
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
