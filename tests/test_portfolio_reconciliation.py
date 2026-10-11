"""Documentation integrity, not runtime or market acceptance."""

import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest


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
    # Integration preserves canonical STATUS; source readiness does not authorize
    # inserting the candidate's historical restart claim into current status.
    assert "## Owner-directed restart and certification resumption — 10 October 2026" not in after
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
    # Admit exactly the dated observation, failure and non-certifying evidence
    # repair. Neither the later service failure nor the earlier finite pass may
    # overwrite history or become an unbounded/current acceptance claim.
    observation_title = "## Light-production observation and dated HF evidence repair — 8 October 2026"
    assert after.count(observation_title) == 1
    observation_start = after.index(observation_title)
    observation_end = after.index("## PR #210 source merge and copied-data rollback correction — 8 October 2026", observation_start)
    observation_update = after[observation_start:observation_end].encode("utf-8")
    assert len(observation_update) == 3517
    assert hashlib.sha256(observation_update).hexdigest() == "b2bc0b19fc66d0ed61dd4696b941306936b2a33b12b265fc9d1e07d3f2e31e2e"
    after = after[:observation_start] + after[observation_end:]
    # Admit this exact new correction/merge observation without rewriting the
    # earlier failed observation or any of its byte-pinned historical evidence.
    correction_title = "## PR #210 source merge and copied-data rollback correction — 8 October 2026"
    assert after.count(correction_title) == 1
    correction_start = after.index(correction_title)
    correction_end = after.index("## Authenticated certification feeds merged; further cases prepared — 8 October 2026", correction_start)
    correction_update = after[correction_start:correction_end].encode("utf-8")
    assert len(correction_update) == 2692
    assert hashlib.sha256(correction_update).hexdigest() == "449da24a577e56e43954e7e181bedbd2f0597dfb2040d2f1cbd56449f4842a7d"
    after = after[:correction_start] + after[correction_end:]
    # Admit only the exact new 8 October source/rehearsal observation. It is
    # distinct from all byte-pinned historical additions below; no arbitrary
    # current text, new PASS or deployment claim can bypass the history proof.
    current_title = "## Authenticated certification feeds merged; further cases prepared — 8 October 2026"
    assert after.count(current_title) == 1
    current_start = after.index(current_title)
    current_end = after.index("## Actual independent A19 signing and identity-event adapter — 7 October 2026", current_start)
    current_update = after[current_start:current_end].encode("utf-8")
    assert len(current_update) == 3620
    assert hashlib.sha256(current_update).hexdigest() == "c6df942a332489af2ea9abf5ac11f1f4b9bc9abbc213d236fe846887a8814944"
    after = after[:current_start] + after[current_end:]
    # Admit only this exact new, dated signing/candidate observation. Every
    # prior section and the original portfolio baseline remain byte-pinned.
    signing_title = "## Actual independent A19 signing and identity-event adapter — 7 October 2026"
    assert after.count(signing_title) == 1
    signing_start = after.index(signing_title)
    signing_end = after.index("## Scoped 5b deployment and unsigned A19 review — 7 October 2026", signing_start)
    signing_update = after[signing_start:signing_end].encode("utf-8")
    assert len(signing_update) == 2968
    assert hashlib.sha256(signing_update).hexdigest() == "c9d8a4cc56fa50433b29a05160e0cfc6c74419d0cb7cd63ff0c43f0cd9ea1266"
    after = after[:signing_start] + after[signing_end:]
    # Remove only this exact dated deployment/unsigned-review observation.
    # The frozen baseline and every earlier section pin stay unchanged; an
    # altered receipt, invented signature or expanded qualification still fails.
    live_title = "## Scoped 5b deployment and unsigned A19 review — 7 October 2026"
    assert after.count(live_title) == 1
    live_start = after.index(live_title)
    live_end = after.index("## Scoped certification runtime and success-error repair — 7 October 2026", live_start)
    live_update = after[live_start:live_end].encode("utf-8")
    assert len(live_update) == 2507
    assert hashlib.sha256(live_update).hexdigest() == "d74ec03cef04080982f3091d5daeeed1905e70ff7704d195c36f204434f5ca43"
    after = after[:live_start] + after[live_end:]
    # This separately dated runtime/failure observation is an exact addition,
    # not permission to erase or rewrite any previous status/evidence section.
    runtime_title = "## Scoped certification runtime and success-error repair — 7 October 2026"
    assert after.count(runtime_title) == 1
    runtime_start = after.index(runtime_title)
    runtime_end = after.index("## Agent certification execution repair — 7 October 2026", runtime_start)
    runtime_update = after[runtime_start:runtime_end].encode("utf-8")
    assert len(runtime_update) == 1715
    assert hashlib.sha256(runtime_update).hexdigest() == "e981b56286dba42533f6024d677a58334e2e35f247dc0dde67fdaa70bfa54ec9"
    after = after[:runtime_start] + after[runtime_end:]
    # Remove only the exact new, non-certifying 7 October observation; retain
    # the independently pinned historical bytes and reject altered claims.
    cert_title = "## Agent certification execution repair — 7 October 2026"
    assert after.count(cert_title) == 1
    cert_start = after.index(cert_title)
    cert_end = after.index("## HF runtime hardening — 7 October 2026", cert_start)
    cert_update = after[cert_start:cert_end].encode("utf-8")
    assert len(cert_update) == 1425
    assert hashlib.sha256(cert_update).hexdigest() == "a842b1e8ba6b6f0ec2c553e4f0433280157df5018c3c25d407089562e5d12fb1"
    after = after[:cert_start] + after[cert_end:]
    # The reviewed 7 October candidate observation is an addition, not a change
    # to frozen history. Remove only its exact recorded bytes; neither arbitrary
    # new text nor an altered acceptance claim may bypass the history proof.
    hf_title = "## HF runtime hardening — 7 October 2026"
    assert after.count(hf_title) == 1
    hf_start = after.index(hf_title)
    hf_end = after.index("## Status authority — 3 October 2026", hf_start)
    hf_update = after[hf_start:hf_end].encode("utf-8")
    assert len(hf_update) == 871
    assert hashlib.sha256(hf_update).hexdigest() == "5d8e92014422f868399bb5f05a3dc93d6ee5bfbc8d8c900589ee545df0e32f8a"
    after = after[:hf_start] + after[hf_end:]
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


@pytest.mark.parametrize("original,replacement", [
    ("QUALIFIED_FOR_OBSERVED_LIGHT_PRODUCTION", "PERMANENTLY_QUALIFIED_FOR_ALL_WORKLOADS"),
    ("not a continuously current sensor or heavy-load thermal qualification.",
     "a continuously current sensor and heavy-load thermal qualification."),
    ("Accepted backend remains `5b3dd3a`.", "Accepted backend is now `8b673e5`."),
    ("accepted PRIME exited with code 139 and Docker restarted it.",
     "accepted PRIME never exited and Docker never restarted it."),
    ("before any\n  stop, start, reader or copy operation.",
     "after every\n  stop, start, reader and copy operation passed."),
    ("without new inference,\n  fresh execution evidence, independent signature or certification.",
     "with new inference,\n  fresh execution evidence, independent signature and certification."),
    ("Full L7 remains **0/21**; no capability certification was awarded.",
     "Full L7 is **21/21**; every capability certification was awarded."),
], ids=["finite-not-permanent", "dated-not-heavy", "exact-accepted-runtime", "preserve-exit139",
        "no-fenced-copy", "projection-not-execution", "no-l7-award"])
def test_light_observation_and_failure_reject_inflated_claims(monkeypatch, original, replacement):
    status_path = ROOT / "STATUS.md"
    read_text = Path.read_text
    status = read_text(status_path, encoding="utf-8")
    assert status.count(original) == 1
    changed = status.replace(original, replacement, 1)
    def altered_read(path, *args, **kwargs):
        return changed if path == status_path else read_text(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", altered_read)
    with pytest.raises(AssertionError):
        test_status_insertion_preserves_all_existing_sections_and_history()


@pytest.mark.parametrize("original,replacement", [
    ("## Course study", "## Course study — unaccounted history edit"),
    ("Executed focused regression: 284 passed", "Executed focused regression: 285 passed"),
    ("Fully L7 certified remains **0/21**.", "Fully L7 certified remains **1/21**."),
    ("candidate has not changed Golden, Interface, Ollama", "candidate has deployed to Golden, Interface, Ollama"),
    ("d2793c00169cc6fca540e9c26c57790d143935d6", "d2793c00169cc6fca540e9c26c57790d143935d0"),
    ("bounded 69-second observation passed", "unbounded long-term soak passed"),
    ("before any A26\n  review or signing", "after verified A26\n  review and signing"),
    ("No signing was performed.", "Independent protected signing passed."),
    ("69.078 seconds", "69.078 hours"),
    ("0/21**.\n- Agent-reviewed evidence", "21/21**.\n- Agent-reviewed evidence"),
    ("bee1a7fc3253231dbde2a997aa3a4d02ac1bcf8457c4081941e8572cf1f22824",
     "bee1a7fc3253231dbde2a997aa3a4d02ac1bcf8457c4081941e8572cf1f22820"),
    ("thirteen tamper-denial checks passed", "thirteen tamper-denial checks failed"),
    ("its historical signature is not", "its historical signature is now"),
    ("2026-10-07T11:52:32Z", "2026-10-08T11:52:32Z"),
    ("No new cloud authority was added.", "New agent signing authority was added."),
])
def test_status_history_guard_rejects_unaccounted_edit(monkeypatch, original, replacement):
    status_path = ROOT / "STATUS.md"
    read_text = Path.read_text
    status = read_text(status_path, encoding="utf-8")
    expected_count = 4 if original == "Fully L7 certified remains **0/21**." else 1
    assert status.count(original) == expected_count
    # Independently falsify each repeated claim, including both the new and
    # historical 0/21 statement. Do not just mutate the first occurrence.
    offset = 0
    for _ in range(expected_count):
        position = status.index(original, offset)
        changed = status[:position] + replacement + status[position + len(original):]
        def altered_read(path, *args, **kwargs):
            return changed if path == status_path else read_text(path, *args, **kwargs)
        monkeypatch.setattr(Path, "read_text", altered_read)
        with pytest.raises(AssertionError):
            test_status_insertion_preserves_all_existing_sections_and_history()
        offset = position + len(original)


@pytest.mark.parametrize("original,replacement", [
    ("Full exact-head cloud tests for\n  this changed continuation remain separate from PR #209's completed CI.",
     "Full exact-head cloud tests for\n  this changed continuation passed all checks using PR #209's completed CI."),
    ("configuration matched the pinned archive; it has not been deployed.",
     "configuration matched the pinned archive; it has been deployed."),
    ("Source readiness is 98/2,146 paths, A19 42/74; these are not live case counts.",
     "Live certification is 98/2,146 paths, A19 42/74; these are live case counts."),
    ("receipts are preserved. Full L7 remains **0/21**;",
     "receipts are preserved. Full L7 is certified **21/21**;"),
    ("remain unwired. They are not counted as ready certification paths.",
     "are fully wired. They are counted as ready certification paths."),
    ("read failed closed on a relevant-code pin mismatch; restoration remains unproved.",
     "read passed despite a relevant-code pin mismatch; restoration is proved."),
    ("Windows PWA/image stages were skipped after that failure, not passed.",
     "Windows PWA/image stages passed despite that failure, not skipped."),
], ids=["new-cloud-pass", "new-deployment", "new-live-counts", "new-l7", "new-unwired-readiness",
        "new-rollback-pass", "new-skipped-pass"])
def test_current_case_observation_rejects_inflated_claims(monkeypatch, original, replacement):
    status_path = ROOT / "STATUS.md"
    read_text = Path.read_text
    status = read_text(status_path, encoding="utf-8")
    # Each full snippet belongs only to the new dated observation. Historical
    # claim counts and their independent mutation tests stay unchanged.
    assert status.count(original) == 1
    changed = status.replace(original, replacement, 1)
    def altered_read(path, *args, **kwargs):
        return changed if path == status_path else read_text(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", altered_read)
    with pytest.raises(AssertionError):
        test_status_insertion_preserves_all_existing_sections_and_history()


@pytest.mark.parametrize("original,replacement", [
    ("944755427c177d9ef661b24fdb37ea3f35f7ca99", "944755427c177d9ef661b24fdb37ea3f35f7ca90"),
    ("Agent L7 remains **0/21**.", "Agent L7 is complete **21/21**."),
    ("Public verifier\n  fixtures are not live Azure signing", "Public verifier\n  fixtures are live Azure signing"),
    ("prove a production cutover or preservation of arbitrary later production writes.",
     "prove a production cutover and preservation of arbitrary later production writes."),
    ("no production code or image was repaired.", "production code and image were repaired."),
    ("No PR #209 or #210 production deployment is established", "PR #209 and #210 production deployment is established"),
    ("Host stability remains unqualified.", "Host stability is qualified."),
    ("this observation awards no certification", "this observation awards all certifications"),
])
def test_current_rollback_correction_rejects_expanded_claims(monkeypatch, original, replacement):
    status_path = ROOT / "STATUS.md"
    read_text = Path.read_text
    status = read_text(status_path, encoding="utf-8")
    assert status.count(original) == 1
    changed = status.replace(original, replacement, 1)
    def altered_read(path, *args, **kwargs):
        return changed if path == status_path else read_text(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", altered_read)
    with pytest.raises(AssertionError):
        test_status_insertion_preserves_all_existing_sections_and_history()


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
