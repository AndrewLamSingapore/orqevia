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


def test_supplementary_observation_does_not_renew_historical_manifest():
    manifest = json.loads((ROOT / "governance/operational-manifest.json").read_text(encoding="utf-8"))
    original = json.loads(
        subprocess.check_output(
            ["git", "show", "325c65323df03de1a1a7a12a50b76b3d20bf9bea:governance/operational-manifest.json"], cwd=ROOT
        )
    )
    reference = manifest.pop("latest_observation")
    # Account only for the two authority-prose corrections. All dates, runtime
    # identities and original acceptance evidence must still equal the snapshot.
    corrections = (
        (
            "supersession",
            "rule",
            "This manifest alone selects current architecture and operational state. Generated mirrors and public-safe source summaries are subordinate. Historical identities cannot populate current runtime fields. Superseded material remains recoverable from Git history.",
            "This manifest is a dated component and observation reference; it cannot select current architecture or operational state. STATUS.md is the sole portfolio status record. Each product repository owns its source, configuration, contracts and domain records. Runtime claims require observed runtime identity and evidence. Generated mirrors retain the same dated scope. Historical identities cannot populate current runtime fields. Superseded material remains recoverable from Git history.",
        ),
        (
            "truth_reconciliation",
            "authority_boundary",
            "STATUS.md alone owns current status; this manifest records component and observation references. Dell may independently verify; ABEX remains the PRIME runtime authority.",
            "STATUS.md records portfolio status claims and their evidence classification; this manifest records dated component and observation references. Each product owns its source, configuration, contracts and domain records in its repository. Runtime claims require observed runtime identity and evidence. Dell may independently verify; ABEX remains the PRIME runtime authority.",
        ),
    )
    for section, field, prior, corrected in corrections:
        assert original[section][field] == prior
        assert manifest[section][field] == corrected
        manifest[section][field] = prior

    # Account only for the dated /jarvis -> /orqevia entrypoint corrections
    # from the public-entrypoint reconciliation; every other field must still
    # equal the original snapshot byte-for-byte.
    def at(doc, path):
        node = doc
        for key in path:
            node = node[key]
        return node

    pointer_corrections = (
        (
            ("public_experience", "entrypoint"),
            "https://authority-engine-app.vercel.app/jarvis",
            "https://authority-engine-app.vercel.app/orqevia",
        ),
        (
            ("supersession", "current_public_entrypoint"),
            "https://authority-engine-app.vercel.app/jarvis",
            "https://authority-engine-app.vercel.app/orqevia",
        ),
        (
            ("systems", "authority", "jarvis_status_url"),
            "https://authority-engine-app.vercel.app/api/jarvis-status",
            "https://authority-engine-app.vercel.app/api/orqevia-status",
        ),
    )
    for keys, prior, corrected in pointer_corrections:
        assert at(original, keys) == prior
        assert at(manifest, keys) == corrected
        node = manifest
        for key in keys[:-1]:
            node = node[key]
        node[keys[-1]] = prior
    # Gen4 re-issue (owner order 2026-10-16): only the golden_architecture block
    # moves; assert each prior -> current pair explicitly, then restore the
    # snapshot values so every other pinned byte must still match exactly.
    golden = manifest["golden_architecture"]
    original_golden = original["golden_architecture"]
    golden_corrections = (
        ("active_generation", 2, 4),
        ("architecture_state", "FROZEN", "CURRENT"),
        ("manifest", "governance/golden-gen2-manifest.json", "governance/golden-gen4-manifest.json"),
        ("immutable_reference", "jarvis-prime-golden-gen2-20260927", "orqevia-golden-gen4-20261016"),
        ("runtime_source_sha", "b171253566e7c879283d2aacf699ae6c1ec8988e", "48648edd8d2640f12f8086b9910deec865519326"),
        ("runtime_image", "prime:phase2-audio-diagnostic-b171253", "orqevia:epoch-20261016-backend"),
        (
            "accepted_scope",
            "PHASE2_NON_AUDIO_ACCEPTED_READ_ALOUD_PARKED",
            "ORQEVIA_BRANDED_RUNTIME_NON_AUDIO_ACCEPTED_READ_ALOUD_PARKED",
        ),
        ("former_generation", "jarvis-prime-golden-gen1-20260926", "jarvis-prime-golden-gen2-20260927"),
        (
            "architecture",
            "docs/JARVIS-PRIME-PHASE2-UNIFIED-INTELLIGENCE-ARCHITECTURE.md",
            "docs/TOTAL-INTEGRATION-ARCHITECTURE.md",
        ),
        ("dell_post_promotion", "PROMOTION_VERIFICATION_PASS", "UNVERIFIED"),
    )
    for field, prior, corrected in golden_corrections:
        assert original_golden[field] == prior
        assert golden[field] == corrected
        golden[field] = prior
    # Dated manifest refresh: only the observation date moves; all prior
    # bytes and the STALE status remain pinned to the original snapshot.
    assert original["as_of_utc"] == "2026-09-26T07:48:05Z"
    assert manifest["as_of_utc"] == "2026-10-16T05:20:00Z"
    manifest["as_of_utc"] = original["as_of_utc"]
    assert manifest == original
    assert manifest["status"] == "STALE"
    assert reference["current_acceptance"] == "UNVERIFIED"
    assert reference["renews_existing_verification"] is False
    assert reference["role"] == "SUPPLEMENTARY_DATED_RECEIPT_INDEX_NOT_CURRENT_ACCEPTANCE"
    raw = (ROOT / reference["record"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == reference["record_sha256"]


def test_latest_receipt_index_preserves_role_and_client_evidence_limits():
    observation = json.loads((ROOT / "governance/observations/abex-post-restart-20261012.json").read_text())
    assert observation["classification"] == "CLAIMED_NOT_OWNER_VERIFIED"
    assert observation["candidate_promotion"] == "BLOCKED"
    assert observation["current_runtime_acceptance"] == "UNVERIFIED"
    assert observation["roles"]["latest_completed_run_source"] == "18ec93990eeccdbde60b85b32f5f5e0f0cb7849d"
    assert (observation["roles"]["pass"], observation["roles"]["fail"], observation["roles"]["tested"]) == (7, 14, 21)
    assert observation["roles"]["successor_live_acceptance"] == "NOT_TESTED"
    assert observation["dell"]["fresh_client_check"] == "PENDING_OWNER_CONFIRMED_UNAVAILABLE"
    assert observation["dell"]["abex_server_persistence"] == "PASS_DATED_SERVER_RECEIPT_ONLY"
    assert observation["codex"]["billing_policy"] == "OPENAI_ONLY"
    assert observation["windows_integrity"]["repair_performed"] is False
    assert observation["crash_context"]["causal_attribution"].startswith("UNESTABLISHED")


def test_candidate_closure_supplement_keeps_source_specific_totals_and_old_record():
    manifest = json.loads((ROOT / "governance/operational-manifest.json").read_text(encoding="utf-8"))
    reference = manifest["latest_observation"]
    assert reference["record"] == "governance/observations/abex-candidate-closure-66a5d90-20261012.json"
    raw = (ROOT / reference["record"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == reference["record_sha256"]
    observation = json.loads(raw)
    assert observation["candidate_source_sha"] == "66a5d9056ac13c69f73de8d8a986c91164bf8937"
    assert observation["candidate_source_frozen"] is True
    roles = observation["roles"]
    assert (roles["pass"], roles["fail"], roles["blocked"], roles["executed"]) == (8, 13, 0, 21)
    assert len(roles["rows"]) == len({row["role_id"] for row in roles["rows"]}) == 21
    assert sum(row["status"] == "PASS" for row in roles["rows"]) == 8
    assert sum(row["status"] == "FAIL" for row in roles["rows"]) == 13
    assert roles["role_competence_21_of_21"] is False
    assert roles["historical_18ec939"]["pooled"] is False
    previous = observation["supersedes_latest_observation_only"]
    assert previous["historical_record_preserved"] is True
    old_raw = (ROOT / previous["record"]).read_bytes()
    assert (
        hashlib.sha256(old_raw).hexdigest()
        == previous["record_sha256"]
        == "edf93502cbb88152e7bba1df26de627adc8f28dc56b2359378a2757681dd8ab1"
    )


def test_candidate_browser_and_ci_never_award_device_runtime_or_role_acceptance():
    observation = json.loads(
        (ROOT / "governance/observations/abex-candidate-closure-66a5d90-20261012.json").read_text(encoding="utf-8")
    )
    assert observation["classification"] == "CLAIMED_NOT_OWNER_VERIFIED"
    assert observation["upstream_ci"]["source_sha"] == observation["candidate_source_sha"]
    assert observation["upstream_ci"]["scope"] == "SOURCE_CHECKS_NOT_ROLE_OR_PRODUCTION_ACCEPTANCE"
    browser = observation["browser"]
    assert browser["scope"] == "ACTUAL_ISOLATED_BROWSER_NOT_DELL_OR_PHYSICAL_IPHONE"
    assert browser["pass"] == len(browser["checks"]) == 12
    assert browser["dell_acceptance"] is browser["physical_iphone_acceptance"] is False
    assert browser["task_result_and_restart_acceptance"] == "NOT_INCLUDED_PENDING_SEPARATE_RECEIPTS"
    assert observation["current_runtime_acceptance"] == "UNVERIFIED"
    assert observation["manifest_effective_status"] == "STALE"
    assert observation["existing_verification_timestamps_or_expiry_renewed"] is False
    assert observation["candidate_promotion"] == "BLOCKED"
    assert observation["l7_certification"] == "NOT_ESTABLISHED"


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
        "target_customer",
        "proposition",
        "pricing_hypothesis_sgd",
        "internal_readiness",
        "technical_evidence",
        "external_validation",
        "contradictions_and_missing_evidence",
        "next_gate",
        "owner_action",
        "evidence_refs",
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
    # Admit only this exact dated implementation/runtime distinction. All
    # earlier history and Owner-only Verified records retain their byte pins.
    eco_title='## Selective-expert MoE and patient inference - 28 October 2026'
    assert after.count(eco_title)==1
    eco_start=after.index(eco_title)
    eco_end=after.index('\n## ',eco_start+len(eco_title))+1
    eco_update=after[eco_start:eco_end].encode('utf-8')
    assert len(eco_update)==3501
    assert hashlib.sha256(eco_update).hexdigest()=='2087f7bacff6564ff93e85fbf7edbc66487e00347da52657213031cbb73dcec3'
    assert b'### Verified' not in eco_update
    after=after[:eco_start]+after[eco_end:]
    # Exact current preservation note; all prior historical pins remain.
    checkpoint_title = '## Live dashboard and generic Codex preservation checkpoint - 27 October 2026'
    assert after.count(checkpoint_title) == 1
    checkpoint_start = after.index(checkpoint_title)
    checkpoint_end = after.index("\n## ", checkpoint_start + len(checkpoint_title)) + 1
    checkpoint_update = after[checkpoint_start:checkpoint_end].encode("utf-8")
    assert len(checkpoint_update) == 1358
    assert hashlib.sha256(checkpoint_update).hexdigest() == "5b4729fdda7ac6f262260aef9242ea00c2cf19670dbed482f90b89a0995fe190"
    assert b"### Claimed, not independently checked" in checkpoint_update
    assert b"### Verified" not in checkpoint_update
    after = after[:checkpoint_start] + after[checkpoint_end:]
    # Exact continuation note; historical candidate notes remain pinned.
    integration_title = '## Live observability integration continuation - 27 October 2026'
    assert after.count(integration_title) == 1
    integration_start = after.index(integration_title)
    integration_end = after.index("\n## ", integration_start + len(integration_title)) + 1
    integration_update = after[integration_start:integration_end].encode("utf-8")
    assert len(integration_update) == 1740
    assert hashlib.sha256(integration_update).hexdigest() == "63be56865c343a1e7fe2d0f22ecf975d08e773dd230a5a68b73976f93406b5af"
    assert b"### Claimed, not independently checked" in integration_update
    assert b"### Verified" not in integration_update
    after = after[:integration_start] + after[integration_end:]
    # Admit only the exact source-only handover; prior claims stay pinned.
    handover_title = '## Observability recovery and DeepSeek handover - 27 October 2026'
    assert after.count(handover_title) == 1
    handover_start = after.index(handover_title)
    handover_end = after.index("\n## ", handover_start + len(handover_title)) + 1
    handover_update = after[handover_start:handover_end].encode("utf-8")
    assert len(handover_update) == 1191
    assert hashlib.sha256(handover_update).hexdigest() == "33012e8f0c803e44ddc87b92fa4842479cc86cfc08a69b165b07e95d35eaf1c1"
    assert b"### Claimed, not independently checked" in handover_update
    assert b"### Verified" not in handover_update
    after = after[:handover_start] + after[handover_end:]
    # Admit only this exact dated Academy candidate note; the complete prior
    # history and Owner-only Verified sections remain byte-pinned below.
    academy_title = "## Native coaching recovery and probability education - 27 October 2026"
    assert after.count(academy_title) == 1
    academy_start = after.index(academy_title)
    academy_end = after.index("\n## ", academy_start + len(academy_title)) + 1
    academy_update = after[academy_start:academy_end].encode("utf-8")
    assert len(academy_update) == 2270
    assert hashlib.sha256(academy_update).hexdigest() == "d128510386483f4bcd63ed97ebb7473ce2986e57c8ebf2f1b6def97947151550"
    assert b"### Claimed, not independently checked" in academy_update
    assert b"### Verified" not in academy_update
    after = after[:academy_start] + after[academy_end:]
    parity_title = "## Shared operational observations and shell coherence - 25 October 2026"
    assert after.count(parity_title) == 1
    parity_start = after.index(parity_title)
    parity_end = after.index("\n## ", parity_start + len(parity_title)) + 1
    parity_update = after[parity_start:parity_end].encode("utf-8")
    assert len(parity_update) == 1050
    assert hashlib.sha256(parity_update).hexdigest() == "056d28287b1e4119db16a56ea4716f32a5f3d5e672c75ba7eb0980ffa3100821"
    assert b"### Claimed, not independently checked" in parity_update
    assert b"### Verified" not in parity_update
    after = after[:parity_start] + after[parity_end:]
    discovery_title = "## Shared desktop and mobile interface discovery - 25 October 2026"
    assert after.count(discovery_title) == 1
    discovery_start = after.index(discovery_title)
    discovery_end = after.index("\n## ", discovery_start + len(discovery_title)) + 1
    discovery_update = after[discovery_start:discovery_end].encode("utf-8")
    assert len(discovery_update) == 1577
    assert hashlib.sha256(discovery_update).hexdigest() == "513a64480829fb00a1a845ee40555d923e0a5317d89fadd1ee1a4225a6429d03"
    assert b"### Claimed, not independently checked" in discovery_update
    assert b"### Verified" not in discovery_update
    after = after[:discovery_start] + after[discovery_end:]
    intelligence_title = "## Optional intelligence implementation and external exclusions - 25 October 2026"
    assert after.count(intelligence_title) == 1
    intelligence_start = after.index(intelligence_title)
    intelligence_end = after.index("\n## ", intelligence_start + len(intelligence_title)) + 1
    intelligence_update = after[intelligence_start:intelligence_end].encode("utf-8")
    assert len(intelligence_update) == 1879
    assert hashlib.sha256(intelligence_update).hexdigest() == "8c155f1962a1cd9de9c9b9b0d97348894eadc08c5ffe3fac332b06f5a4b9d6cc"
    assert b"### Claimed, not independently checked" in intelligence_update
    assert b"### Verified" not in intelligence_update
    after = after[:intelligence_start] + after[intelligence_end:]
    unrestricted_title = "## Owner HTTPS and unrestricted execution directive - 25 October 2026"
    assert after.count(unrestricted_title) == 1
    unrestricted_start = after.index(unrestricted_title)
    unrestricted_end = after.index("\n## ", unrestricted_start + len(unrestricted_title)) + 1
    unrestricted_update = after[unrestricted_start:unrestricted_end].encode("utf-8")
    assert len(unrestricted_update) == 1072
    assert hashlib.sha256(unrestricted_update).hexdigest() == "45f31c3c420988bf808ce3eb7befb9bc556cfef3a8f07a3e35d02896f2a5919a"
    assert b"### Claimed, not independently checked" in unrestricted_update
    assert b"### Verified" not in unrestricted_update
    after = after[:unrestricted_start] + after[unrestricted_end:]
    session_title = "## Current fabric HTTPS verification and session continuity - 25 October 2026"
    assert after.count(session_title) == 1
    session_start = after.index(session_title)
    session_end = after.index("\n## ", session_start + len(session_title)) + 1
    session_update = after[session_start:session_end].encode("utf-8")
    assert len(session_update) == 1141
    assert hashlib.sha256(session_update).hexdigest() == "f1c607dd3be7982fe7d051fa0aefcac70d99623803ae8d1bbe7909790f1ccf92"
    assert b"### Claimed, not independently checked" in session_update
    assert b"### Verified" not in session_update
    after = after[:session_start] + after[session_end:]
    # Admit the exact new non-Verified observation; retain every frozen check below.
    live_title = "## Scoped fabric production and workbench qualification - 24 October 2026"
    assert after.count(live_title) == 1
    live_start = after.index(live_title)
    live_end = after.index("\n## ", live_start + len(live_title)) + 1
    live_update = after[live_start:live_end].encode("utf-8")
    assert len(live_update) == 2832
    assert hashlib.sha256(live_update).hexdigest() == "fb11af6d5ef49e53b96dcfe11aaed675d279708faf5d9eb1c595b4c26cf0c665"
    assert b"### Claimed, not independently checked" in live_update
    assert b"### Verified" not in live_update
    after = after[:live_start] + after[live_end:]
    # Admit this exact candidate note while retaining the complete frozen proof.
    fabric_title = "## 36-fabric evidence contract candidate - 24 October 2026"
    assert after.count(fabric_title) == 1
    fabric_start = after.index(fabric_title)
    fabric_end = after.index("\n## ", fabric_start + len(fabric_title)) + 1
    fabric_update = after[fabric_start:fabric_end].encode("utf-8")
    assert len(fabric_update) == 880
    assert (
        hashlib.sha256(fabric_update).hexdigest() == "fc2c72d2abb8055055d2864ea12b091d1ec907c4d8a6804efc19620804275db5"
    )
    assert b"### Verified" not in fabric_update
    after = after[:fabric_start] + after[fabric_end:]
    # Admit only this exact dated OSIP candidate addition. All prior history
    # and Owner-only Verified sections retain their existing byte checks.
    osip_start = after.index("## ORQEVIA 2.0 candidate \u2014 23 October 2026")
    osip_end = after.index("## Live single-node release acceptance", osip_start)
    osip_update = after[osip_start:osip_end].encode("utf-8")
    assert len(osip_update) == 3362
    assert hashlib.sha256(osip_update).hexdigest() == "9d109632b868202dc41dc69761790b2e2ab8d002eeb30b1bca8d197fe8e26886"
    assert b"### Verified" not in osip_update
    after = after[:osip_start] + after[osip_end:]
    # Admit only the exact dated audit/release observations. All earlier bytes
    # and owner-only Verified records remain checked by the frozen proof below.
    audit_start = after.index("## Live single-node release acceptance — 23 October 2026")
    audit_end = after.index("Interpretation updated:", audit_start)
    audit_update = after[audit_start:audit_end].encode("utf-8")
    assert len(audit_update) == 5651
    assert (
        hashlib.sha256(audit_update).hexdigest() == "2ef87211a0d3df7f8e20baacd114cb0eb7e8424d7f5c5530cbe45a0c44e3694a"
    )
    assert audit_update.count(b"### Claimed, not independently checked") == 3
    assert b"### Verified" not in audit_update
    after = after[:audit_start] + after[audit_end:]
    # Admit only the exact final fast-model/God's Eye deployment record.
    final_title = "## Fast-model and God's Eye final deployment \u2014 20 October 2026"
    assert after.count(final_title) == 1
    final_start = after.index(final_title)
    final_end = after.index("\n## ", final_start + len(final_title)) + 1
    final_update = after[final_start:final_end].encode("utf-8")
    assert len(final_update) == 2969
    assert (
        hashlib.sha256(final_update).hexdigest() == "5a3735074a6bc2558b3742b0bf705ea8a9e4ba6c4690cba15cc14493a47560ae"
    )
    assert b"### Claimed, not independently checked" in final_update
    assert b"### Verified" not in final_update
    after = after[:final_start] + after[final_end:]
    # Admit only this exact source-only sweep record; preserve all frozen history.
    sweep_title = "## Portfolio public-audience sweep — 20 October 2026"
    assert after.count(sweep_title) == 1
    sweep_start = after.index(sweep_title)
    sweep_end = after.index("\n## ", sweep_start + len(sweep_title)) + 1
    sweep_update = after[sweep_start:sweep_end].encode("utf-8")
    assert len(sweep_update) == 1950
    assert (
        hashlib.sha256(sweep_update).hexdigest() == "3aef3535a51ab6345eeea978799597bc9575f929f9971e1cea5db4c0f99fb9e3"
    )
    assert b"### Claimed, not independently checked" in sweep_update
    assert b"### Verified" not in sweep_update
    after = after[:sweep_start] + after[sweep_end:]
    workflow_title = "## ORQEVIA durable workflow deployment - 20 October 2026"
    assert after.count(workflow_title) == 1
    workflow_start = after.index(workflow_title)
    workflow_end = after.index("\n## ", workflow_start + len(workflow_title)) + 1
    workflow_update = after[workflow_start:workflow_end].encode("utf-8")
    assert len(workflow_update) == 3848
    assert (
        hashlib.sha256(workflow_update).hexdigest()
        == "34a7d03e339de694487694d632d288282207a6cb751cd97c1bebffe6dc1ec787"
    )
    assert b"### Claimed, not independently checked" in workflow_update
    assert b"### Verified" not in workflow_update
    after = after[:workflow_start] + after[workflow_end:]
    iphone_title = "## ORQEVIA iPhone God's Eye recovery - candidate 20 October 2026"
    assert after.count(iphone_title) == 1
    iphone_start = after.index(iphone_title)
    iphone_end = after.index("\n## ", iphone_start + len(iphone_title)) + 1
    iphone_update = after[iphone_start:iphone_end].encode("utf-8")
    assert len(iphone_update) == 1667
    assert (
        hashlib.sha256(iphone_update).hexdigest() == "181b52694e635e1cea4fcd501334dadfbbd367ec4072da550323f93b2ed99eac"
    )
    assert b"### Claimed, not independently checked" in iphone_update
    assert b"### Verified" not in iphone_update
    after = after[:iphone_start] + after[iphone_end:]
    deployment_title = "## ORQEVIA signed naming candidate deployment - 19 October 2026"
    assert after.count(deployment_title) == 1
    deployment_start = after.index(deployment_title)
    deployment_end = after.index("\n## ", deployment_start + len(deployment_title)) + 1
    deployment_update = after[deployment_start:deployment_end].encode("utf-8")
    assert len(deployment_update) == 1819
    assert (
        hashlib.sha256(deployment_update).hexdigest()
        == "cfcaeee90c03fa952d792ca793d14f77ec6e29916364a14a85a69fd2bf00edd1"
    )
    assert b"### Claimed, not independently checked" in deployment_update
    assert b"### Verified" not in deployment_update
    after = after[:deployment_start] + after[deployment_end:]
    release_title = "## ORQEVIA release, role acceptance and naming migration - 19 October 2026"
    assert after.count(release_title) == 1
    release_start = after.index(release_title)
    release_end = after.index("\n## ", release_start + len(release_title)) + 1
    release_update = after[release_start:release_end].encode("utf-8")
    assert len(release_update) == 3421
    assert (
        hashlib.sha256(release_update).hexdigest() == "c9d4027d222fcf97eb832d53a7b302490a6e856b7942fcbae08299e7c5d7fe6e"
    )
    assert b"### Verified (Owner-authorized, 19 October 2026)" in release_update
    after = after[:release_start] + after[release_end:]
    sweep_title = "## ORQEVIA ABEX sweep and CodeQL closure - 19 October 2026"
    assert after.count(sweep_title) == 1
    sweep_start = after.index(sweep_title)
    sweep_end = after.index("\n## ", sweep_start + len(sweep_title)) + 1
    sweep_update = after[sweep_start:sweep_end].encode("utf-8")
    assert len(sweep_update) == 2132
    assert (
        hashlib.sha256(sweep_update).hexdigest() == "320b244e61bf04515e4ae9d18d9d16ba445917816cf9f5a5e49a4dc762db197b"
    )
    assert b"### Claimed, not independently checked" in sweep_update
    assert b"### Verified" not in sweep_update
    after = after[:sweep_start] + after[sweep_end:]
    security_title = "## ORQEVIA Starlette security remediation deployment - 19 October 2026"
    assert after.count(security_title) == 1
    security_start = after.index(security_title)
    security_end = after.index("\n## ", security_start + len(security_title)) + 1
    security_update = after[security_start:security_end].encode("utf-8")
    assert len(security_update) == 1629
    assert (
        hashlib.sha256(security_update).hexdigest()
        == "18794e6e2fada59285bee4b39492e963a2a34a140a57b905ce5256feab5171d0"
    )
    assert b"### Claimed, not independently checked" in security_update
    assert b"### Verified" not in security_update
    after = after[:security_start] + after[security_end:]
    # Admit the exact dated governed-tooling deployment record. Removing only
    # its pinned bytes preserves the historical proof below and rejects edits.
    deployment_title = "## ORQEVIA governed local tooling deployment - 19 October 2026"
    assert after.count(deployment_title) == 1
    deployment_start = after.index(deployment_title)
    deployment_end = after.index("\n## ", deployment_start + len(deployment_title)) + 1
    deployment_update = after[deployment_start:deployment_end].encode("utf-8")
    assert len(deployment_update) == 1455
    assert (
        hashlib.sha256(deployment_update).hexdigest()
        == "7fb3dae4445fae78b49f3416b6ad856f017504523d3bc3732eb1f93b1eb59dc5"
    )
    assert b"### Claimed, not independently checked" in deployment_update
    assert b"### Verified" not in deployment_update
    after = after[:deployment_start] + after[deployment_end:]
    # Admit only this dated full-sweep repair record; all prior bytes remain
    # pinned and no new claim may alter historical sections.
    repair_title = "## ORQEVIA full-sweep test isolation repair - 18 October 2026"
    assert after.count(repair_title) == 1
    repair_start = after.index(repair_title)
    repair_end = after.index("\n## ", repair_start + len(repair_title)) + 1
    repair_update = after[repair_start:repair_end].encode("utf-8")
    assert len(repair_update) == 1253
    assert (
        hashlib.sha256(repair_update).hexdigest() == "077c5fe7bd676d4e86ed9dc8b3da3a5575d9a3e6346410ec6f025fe18a7fe8b8"
    )
    after = after[:repair_start] + after[repair_end:]
    # Admit the dated 17 October health-audit/sweep section; all prior bytes stay pinned.
    audit_title = "## ORQEVIA repository health audit and GitHub sweep - 17 October 2026"
    assert after.count(audit_title) == 1
    audit_start = after.index(audit_title)
    audit_end = after.index("\n## ", audit_start + len(audit_title)) + 1
    audit = after[audit_start:audit_end]
    assert "### Claimed, not independently checked" in audit
    assert "### Verified" not in audit
    assert "374 remote branches" in audit
    after = after[:audit_start] + after[audit_end:]
    # Admit only this exact permanent-readiness and role-acceptance-start record;
    # all prior bytes remain pinned.
    readiness_title = "## Permanent readiness gate and full-role acceptance start - 17 October 2026"
    assert after.count(readiness_title) == 1
    readiness_start = after.index(readiness_title)
    readiness_end = after.index("\n## ", readiness_start + len(readiness_title)) + 1
    readiness_update = after[readiness_start:readiness_end].encode("utf-8")
    assert len(readiness_update) == 4614
    assert (
        hashlib.sha256(readiness_update).hexdigest()
        == "03bd39ea8a6a8c5229e2b1fe548cbde84209ac0b03ae281ebbc9f3104bcce3ac"
    )
    after = after[:readiness_start] + after[readiness_end:]
    # Admit only this exact estate reconciliation section; all prior bytes stay pinned.
    estate_title = "## Estate reconciliation - no blockers, no sandboxes - 16 October 2026 (night)"
    assert after.count(estate_title) == 1
    estate_start = after.index(estate_title)
    estate_end = after.index("\n## ", estate_start + len(estate_title)) + 1
    estate_update = after[estate_start:estate_end].encode("utf-8")
    assert len(estate_update) == 2077
    assert (
        hashlib.sha256(estate_update).hexdigest() == "0cc13853177b7150d0a2c4c521946c90199afd257123d0eec3c6d36312d47e5b"
    )
    after = after[:estate_start] + after[estate_end:]
    sweep_title = "## Dual-writer governance, sweep fixes and ABEX handoff - 16 October 2026"
    assert after.count(sweep_title) == 1
    sweep_start = after.index(sweep_title)
    sweep_end = after.index("\n## ", sweep_start + len(sweep_title)) + 1
    sweep = after[sweep_start:sweep_end]
    assert "### Claimed, not independently checked" in sweep
    assert "### Verified" not in sweep
    assert "docs/ABEX-RUNBOOK-20261016.md" in sweep
    after = after[:sweep_start] + after[sweep_end:]
    recovery_title = "## ABEX forensic recovery checkpoint - 15 October 2026"
    assert after.count(recovery_title) == 1
    recovery_start = after.index(recovery_title)
    recovery_end = after.index("\n## ", recovery_start + len(recovery_title)) + 1
    recovery = after[recovery_start:recovery_end]
    assert "### Claimed, not independently checked" in recovery
    assert "### Verified" not in recovery
    assert "docs/forensics/20261015/README.md" in recovery
    after = after[:recovery_start] + after[recovery_end:]
    # Admit only this exact public-entrypoint reconciliation; all prior bytes stay pinned.
    entry_title = "## Public entrypoint reconciliation and iPhone/website visibility - ORQEVIA - 15 October 2026"
    assert after.count(entry_title) == 1
    entry_start = after.index(entry_title)
    entry_end = after.index("\n## ", entry_start + len(entry_title)) + 1
    entry_update = after[entry_start:entry_end].encode("utf-8")
    assert len(entry_update) == 2017
    assert (
        hashlib.sha256(entry_update).hexdigest() == "f6ecf71876abaf8434cfc02dbef7048dea29690e258d0e5b2cf2ef1b959b0dfc"
    )
    after = after[:entry_start] + after[entry_end:]
    # Admit only this exact verifier re-pin resolution; all prior bytes stay pinned.
    repin_title = "## Verifier re-pin resolution — 16 October 2026"
    assert after.count(repin_title) == 1
    repin_start = after.index(repin_title)
    repin_end = after.index("\n## ", repin_start + len(repin_title)) + 1
    repin_update = after[repin_start:repin_end].encode("utf-8")
    assert len(repin_update) == 1237
    assert (
        hashlib.sha256(repin_update).hexdigest() == "cd958bf0143e5da81af6f436ec599c1c98ffc7be7951c58541d122371c92b80f"
    )
    after = after[:repin_start] + after[repin_end:]
    # Admit only this exact access-reconciliation / protected-batch / command-shell
    # consolidation section; all prior bytes stay pinned.
    recon_title = "## Access reconciliation, protected batch and command shell — 16 October 2026"
    assert after.count(recon_title) == 1
    recon_start = after.index(recon_title)
    recon_end = after.index("\n## ", recon_start + len(recon_title)) + 1
    recon_update = after[recon_start:recon_end].encode("utf-8")
    assert len(recon_update) == 6213
    assert (
        hashlib.sha256(recon_update).hexdigest() == "f760fa392da1c7ca86e95cf1294740b270973fe5fcd540ebe3ace05393268b96"
    )
    after = after[:recon_start] + after[recon_end:]
    # Admit this exact dated candidate report; all previous history remains pinned.
    geo_title = "## Geospatial/vector candidate — 16 October 2026"
    assert after.count(geo_title) == 1
    geo_start = after.index(geo_title)
    geo_end = after.index("\n## ", geo_start + len(geo_title)) + 1
    geo_update = after[geo_start:geo_end].encode("utf-8")
    assert len(geo_update) == 964
    assert hashlib.sha256(geo_update).hexdigest() == "e440b686ba8ca497429ff1eb1fef2769fc9d369043d552d995b311c97fed5e72"
    after = after[:geo_start] + after[geo_end:]
    # Admit only this exact signing-closure/identity/Singapore-origin section;
    # all prior bytes stay pinned.
    closing_title = "## Signing closure, command identity and Singapore origin — 16 October 2026"
    assert after.count(closing_title) == 1
    closing_start = after.index(closing_title)
    closing_end = after.index("\n## ", closing_start + len(closing_title)) + 1
    closing_update = after[closing_start:closing_end].encode("utf-8")
    assert len(closing_update) == 2921
    assert (
        hashlib.sha256(closing_update).hexdigest() == "ff170e7d4cdb49089932a2268acccffa35b021caf1d25b141e127415a564803b"
    )
    after = after[:closing_start] + after[closing_end:]
    # Admit only this exact installation-verification/brand-archive/readiness
    # section; all prior bytes stay pinned.
    install_title = "## Installation verification, brand archive and readiness — 16 October 2026"
    assert after.count(install_title) == 1
    install_start = after.index(install_title)
    install_end = after.index("\n## ", install_start + len(install_title)) + 1
    install_update = after[install_start:install_end].encode("utf-8")
    assert len(install_update) == 1920
    assert (
        hashlib.sha256(install_update).hexdigest() == "bf4b279e1ccfd6e1a23cc56e259ca593e9b39bbf38d3e73c6e6317f49124706e"
    )
    after = after[:install_start] + after[install_end:]
    # Admit only this exact ORQEVIA epoch supersession record; all prior bytes
    # stay pinned.
    epoch_title = "## ORQEVIA epoch supersession and worker execution — 16 October 2026 (night)"
    assert after.count(epoch_title) == 1
    epoch_start = after.index(epoch_title)
    epoch_end = after.index("\n## ", epoch_start + len(epoch_title)) + 1
    epoch_update = after[epoch_start:epoch_end].encode("utf-8")
    assert len(epoch_update) == 2452
    assert (
        hashlib.sha256(epoch_update).hexdigest() == "48a96cf60e632f1c522c99b5d58f2a2ab6c61cfb8d80038e59d86a30a2c06cf9"
    )
    after = after[:epoch_start] + after[epoch_end:]
    # Admit only this exact open-access / unsandboxed / gen-4 record; all prior
    # bytes stay pinned.
    open_title = "## Open access, unsandboxed runtime and the gen-4 baseline — 16 October 2026 (night)"
    assert after.count(open_title) == 1
    open_start = after.index(open_title)
    open_end = after.index("\n## ", open_start + len(open_title)) + 1
    open_update = after[open_start:open_end].encode("utf-8")
    assert len(open_update) == 2960
    assert hashlib.sha256(open_update).hexdigest() == "db016dcf6936144b5529c4ab6e9ef69829a4a0c1b07584b1648f659e3d457f29"
    after = after[:open_start] + after[open_end:]
    # The 6 October interpretation changed only the opening date and scope
    # paragraphs. Require those exact bytes before restoring the 4 October
    # opening, so any unaccounted edit still fails the frozen history proof.
    title = "# STATUS.md — Portfolio status record\n\n"
    interpretation = (
        "Interpretation updated: 6 October 2026. Dated observations below retain their original dates.\n\n"
        "STATUS.md is the human-readable portfolio status index: it records dated claims, evidence, and open work. It is not a universal source of truth or a synchronization target. Each product owns its source, configuration, contracts, and domain records; runtime, deployment, identity, registries, and evidence each have their own scoped authority. Reconcile disagreements by domain ownership, version, and provenance. Runtime claims require observed deployment identity and evidence receipts; a source commit or CI result alone does not establish them. Historical SSOT mentions below describe the former arrangement and do not reinstate it.\n\n"
        "STATUS.md records current portfolio status claims and their evidence classification. Each product owns its source, configuration, contracts, and domain records in its repository.\n\n"
    )
    prior_scope = "STATUS.md records current portfolio status claims and their evidence classification. It does not own implementation, runtime configuration, domain data, or product contracts. Each product owns its source, configuration, contracts, and domain records in its repository. Runtime claims require observed deployment identity and evidence receipts; a source commit or CI result alone does not establish them. Historical SSOT files remain dated evidence, not parallel current portfolio status records."
    assert after.startswith(title + interpretation)
    # Admit the current PR #314 dated additions without pinning their byte
    # lengths. The "How to use this file" section and every historical section
    # below remain byte-pinned, so this does not weaken the mutation guards.
    scaffold_start = after.index("## AI Scaffolding Engine - ORQEVIA - 15 October 2026")
    god_start = after.index("## GOD'S EYE + Geospatial Intelligence + RAG")
    handover_at = after.index("## Dell handover assessment and gap-closing - ORQEVIA - 14 October 2026")
    assert "Scaffolding Engine" in after[scaffold_start:god_start]
    top_block = after[god_start:handover_at]
    assert "There is no SSOT" in top_block
    after = after[:scaffold_start] + after[handover_at:]
    # Admit only this exact Dell handover-assessment addition; prior bytes stay pinned.
    handover_title = "## Dell handover assessment and gap-closing - ORQEVIA - 14 October 2026"
    assert after.count(handover_title) == 1
    handover_start = after.index(handover_title)
    handover_end = after.index("\n## ", handover_start + len(handover_title)) + 1
    handover_update = after[handover_start:handover_end].encode("utf-8")
    assert len(handover_update) == 1751
    assert (
        hashlib.sha256(handover_update).hexdigest()
        == "177ea1308e0a4ff0744de75ed40e5235c8d290be86c764e35fe0783c4f791171"
    )
    after = after[:handover_start] + after[handover_end:]
    # Admit only this exact public-profile observation; all prior bytes stay pinned.
    profile_title = "## Public GitHub profile refresh - 13 October 2026"
    assert after.count(profile_title) == 1
    profile_start = after.index(profile_title)
    profile_end = after.index("\n## ", profile_start + len(profile_title)) + 1
    profile_update = after[profile_start:profile_end].encode("utf-8")
    assert len(profile_update) == 2458
    assert (
        hashlib.sha256(profile_update).hexdigest() == "46c0bf06fde829fb81f6927e7f9975abb2fd66ba1187be1c84dd49ca77278efd"
    )
    after = after[:profile_start] + after[profile_end:]
    # Admit only this exact incremental observation; every earlier byte stays pinned.
    incremental_title = "## Incremental crash analysis and communication-path follow-up - 13 October 2026"
    assert after.count(incremental_title) == 1
    incremental_start = after.index(incremental_title)
    incremental_end = after.index("\n## ", incremental_start + len(incremental_title)) + 1
    incremental_update = after[incremental_start:incremental_end].encode("utf-8")
    assert len(incremental_update) == 4309
    assert (
        hashlib.sha256(incremental_update).hexdigest()
        == "626618b2ac3bcdc6bc38297b388e245fc8ff139585e76a413dfc79d2846cb610"
    )
    after = after[:incremental_start] + after[incremental_end:]
    # Admit only the exact dated telemetry/runtime follow-up; prior history is unchanged.
    runtime_title = "## Telemetry source and external runtime follow-up - 13 October 2026"
    assert after.count(runtime_title) == 1
    runtime_start = after.index(runtime_title)
    runtime_end = after.index("\n## ", runtime_start + len(runtime_title)) + 1
    runtime_update = after[runtime_start:runtime_end].encode("utf-8")
    assert len(runtime_update) == 3056
    assert (
        hashlib.sha256(runtime_update).hexdigest() == "04064e8c6e0e0d26904669f6e872d1e529ce03f748dd1fdf365135c5617477ee"
    )
    after = after[:runtime_start] + after[runtime_end:]
    # Admit only this exact dated sweep supplement; all prior bytes stay pinned.
    sweep_title = "## Portfolio bug sweep and STATUS reference reconciliation - 13 October 2026"
    assert after.count(sweep_title) == 1
    sweep_start = after.index(sweep_title)
    sweep_end = after.index("\n## ", sweep_start + len(sweep_title)) + 1
    sweep = after[sweep_start:sweep_end].encode("utf-8")
    assert len(sweep) == 3090
    assert hashlib.sha256(sweep).hexdigest() == "99b5d8085249869991190d2d0131741fa89e47777be20c7c5024012e8039dea1"
    after = after[:sweep_start] + after[sweep_end:]
    # Admit only this exact integration follow-up, preserving historical bytes.
    followup_title = "## Completed source integrations and remaining runtime work - 13 October 2026"
    assert after.count(followup_title) == 1
    followup_start = after.index(followup_title)
    followup_end = after.index("\n## ", followup_start + len(followup_title)) + 1
    followup = after[followup_start:followup_end].encode("utf-8")
    assert len(followup) == 3918
    assert hashlib.sha256(followup).hexdigest() == "e6814e6a7a9d5d8b1517ff4b3fca0c71a6c696621b2ed7b84a32e304691ceab9"
    after = after[:followup_start] + after[followup_end:]
    # Admit only this exact dated reconciliation; preserve every historical pin.
    reconciliation_title = "## ABEX\u2013DELL end-to-end reconciliation \u2014 13 October 2026"
    assert after.count(reconciliation_title) == 1
    reconciliation_start = after.index(reconciliation_title)
    reconciliation_end = after.index("\n## ", reconciliation_start + len(reconciliation_title)) + 1
    reconciliation_update = after[reconciliation_start:reconciliation_end].encode("utf-8")
    assert len(reconciliation_update) == 6743
    assert (
        hashlib.sha256(reconciliation_update).hexdigest()
        == "87e5825e0263e0a8f96e37ad96dc7a652d3c6e48f90691bd9c8bae0afee77a47"
    )
    after = after[:reconciliation_start] + after[reconciliation_end:]
    # Admit exactly this new 12 October Dell verification record; every prior
    # section pin stays unchanged.
    # This source-specific supplement leaves the first dated observation untouched.
    candidate_title = "## ABEX frozen candidate closure supplement — 12 October 2026"
    assert after.count(candidate_title) == 1
    candidate_start = after.index(candidate_title)
    candidate_end = after.index("## ABEX independent post-restart receipts — 12 October 2026", candidate_start)
    candidate_update = after[candidate_start:candidate_end].encode("utf-8")
    assert len(candidate_update) == 2498
    assert (
        hashlib.sha256(candidate_update).hexdigest()
        == "13467290dcac24592e4ab280d84bd94c403de21a85e99790d6fe85ab53921fb6"
    )
    after = after[:candidate_start] + after[candidate_end:]
    # Admit only this exact new dated receipt index; historical sections stay pinned.
    local_title = "## ABEX independent post-restart receipts — 12 October 2026"
    assert after.count(local_title) == 1
    local_start = after.index(local_title)
    local_end = after.index("## Dell independent verification - 12 October 2026", local_start)
    local_update = after[local_start:local_end].encode("utf-8")
    assert len(local_update) == 2436
    assert (
        hashlib.sha256(local_update).hexdigest() == "a58bd9753a6ded69cb24051fa14a998a0d39afecfbaaf12746b1e4a8380af0a3"
    )
    after = after[:local_start] + after[local_end:]
    dell_title = "## Dell independent verification - 12 October 2026"
    assert after.count(dell_title) == 1
    dell_start = after.index(dell_title)
    dell_end = after.index("## Repository and brand rename", dell_start)
    dell_update = after[dell_start:dell_end].encode("utf-8")
    assert len(dell_update) == 2743
    assert hashlib.sha256(dell_update).hexdigest() == "d87a085d906c5394419df35ba84476db395d0d3ec486467f5be1ac55aefb8316"
    after = after[:dell_start] + after[dell_end:]
    # Admit exactly this new dated rename/rebrand record before the byte-pinned
    # 8 October observation; every prior section pin stays unchanged.
    rebrand_start = after.index("## Repository and brand rename")
    assert after.count("## Repository and brand rename") == 1
    rebrand_end = after.index("## Light-production observation", rebrand_start)
    rebrand_update = after[rebrand_start:rebrand_end].encode("utf-8")
    assert len(rebrand_update) == 1797
    assert (
        hashlib.sha256(rebrand_update).hexdigest() == "792352335d2121cb4f6905eb4ca2094fc0b8af6526d44d59f32a4c2930277491"
    )
    after = after[:rebrand_start] + after[rebrand_end:]
    after = title + "Last updated: 4 October 2026\n\n" + prior_scope + "\n\n" + after[len(title + interpretation) :]
    # Admit exactly the dated observation, failure and non-certifying evidence
    # repair. Neither the later service failure nor the earlier finite pass may
    # overwrite history or become an unbounded/current acceptance claim.
    observation_title = "## Light-production observation and dated HF evidence repair — 8 October 2026"
    assert after.count(observation_title) == 1
    observation_start = after.index(observation_title)
    observation_end = after.index(
        "## PR #210 source merge and copied-data rollback correction — 8 October 2026", observation_start
    )
    observation_update = after[observation_start:observation_end].encode("utf-8")
    assert len(observation_update) == 3517
    assert (
        hashlib.sha256(observation_update).hexdigest()
        == "b2bc0b19fc66d0ed61dd4696b941306936b2a33b12b265fc9d1e07d3f2e31e2e"
    )
    after = after[:observation_start] + after[observation_end:]
    # Admit this exact new correction/merge observation without rewriting the
    # earlier failed observation or any of its byte-pinned historical evidence.
    correction_title = "## PR #210 source merge and copied-data rollback correction — 8 October 2026"
    assert after.count(correction_title) == 1
    correction_start = after.index(correction_title)
    correction_end = after.index(
        "## Authenticated certification feeds merged; further cases prepared — 8 October 2026", correction_start
    )
    correction_update = after[correction_start:correction_end].encode("utf-8")
    assert len(correction_update) == 2692
    assert (
        hashlib.sha256(correction_update).hexdigest()
        == "449da24a577e56e43954e7e181bedbd2f0597dfb2040d2f1cbd56449f4842a7d"
    )
    after = after[:correction_start] + after[correction_end:]
    # Admit only the exact new 8 October source/rehearsal observation. It is
    # distinct from all byte-pinned historical additions below; no arbitrary
    # current text, new PASS or deployment claim can bypass the history proof.
    current_title = "## Authenticated certification feeds merged; further cases prepared — 8 October 2026"
    assert after.count(current_title) == 1
    current_start = after.index(current_title)
    current_end = after.index(
        "## Actual independent A19 signing and identity-event adapter — 7 October 2026", current_start
    )
    current_update = after[current_start:current_end].encode("utf-8")
    assert len(current_update) == 3620
    assert (
        hashlib.sha256(current_update).hexdigest() == "c6df942a332489af2ea9abf5ac11f1f4b9bc9abbc213d236fe846887a8814944"
    )
    after = after[:current_start] + after[current_end:]
    # Admit only this exact new, dated signing/candidate observation. Every
    # prior section and the original portfolio baseline remain byte-pinned.
    signing_title = "## Actual independent A19 signing and identity-event adapter — 7 October 2026"
    assert after.count(signing_title) == 1
    signing_start = after.index(signing_title)
    signing_end = after.index("## Scoped 5b deployment and unsigned A19 review — 7 October 2026", signing_start)
    signing_update = after[signing_start:signing_end].encode("utf-8")
    assert len(signing_update) == 2968
    assert (
        hashlib.sha256(signing_update).hexdigest() == "c9d8a4cc56fa50433b29a05160e0cfc6c74419d0cb7cd63ff0c43f0cd9ea1266"
    )
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
    assert (
        hashlib.sha256(runtime_update).hexdigest() == "e981b56286dba42533f6024d677a58334e2e35f247dc0dde67fdaa70bfa54ec9"
    )
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


@pytest.mark.parametrize(
    "original,replacement",
    [
        ("QUALIFIED_FOR_OBSERVED_LIGHT_PRODUCTION", "PERMANENTLY_QUALIFIED_FOR_ALL_WORKLOADS"),
        (
            "not a continuously current sensor or heavy-load thermal qualification.",
            "a continuously current sensor and heavy-load thermal qualification.",
        ),
        ("Accepted backend remains `5b3dd3a`.", "Accepted backend is now `8b673e5`."),
        (
            "accepted PRIME exited with code 139 and Docker restarted it.",
            "accepted PRIME never exited and Docker never restarted it.",
        ),
        (
            "before any\n  stop, start, reader or copy operation.",
            "after every\n  stop, start, reader and copy operation passed.",
        ),
        (
            "without new inference,\n  fresh execution evidence, independent signature or certification.",
            "with new inference,\n  fresh execution evidence, independent signature and certification.",
        ),
        (
            "Full L7 remains **0/21**; no capability certification was awarded.",
            "Full L7 is **21/21**; every capability certification was awarded.",
        ),
    ],
    ids=[
        "finite-not-permanent",
        "dated-not-heavy",
        "exact-accepted-runtime",
        "preserve-exit139",
        "no-fenced-copy",
        "projection-not-execution",
        "no-l7-award",
    ],
)
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


@pytest.mark.parametrize(
    "original,replacement",
    [
        ("## Course study", "## Course study — unaccounted history edit"),
        ("The offending driver remains UNIDENTIFIED.", "The offending driver is NTFS."),
        ("Host reliability remains unresolved.", "Host reliability is certified."),
        (
            "PR #302 is an unmerged source candidate, distinct from the observed runtime.",
            "PR #302 is the installed and accepted runtime.",
        ),
        ("No hardware cause is established.", "The hardware cause is established."),
        ("Executed focused regression: 284 passed", "Executed focused regression: 285 passed"),
        ("Fully L7 certified remains **0/21**.", "Fully L7 certified remains **1/21**."),
        ("candidate has not changed Golden, Interface, Ollama", "candidate has deployed to Golden, Interface, Ollama"),
        ("d2793c00169cc6fca540e9c26c57790d143935d6", "d2793c00169cc6fca540e9c26c57790d143935d0"),
        ("bounded 69-second observation passed", "unbounded long-term soak passed"),
        ("before any A26\n  review or signing", "after verified A26\n  review and signing"),
        ("No signing was performed.", "Independent protected signing passed."),
        ("69.078 seconds", "69.078 hours"),
        ("0/21**.\n- Agent-reviewed evidence", "21/21**.\n- Agent-reviewed evidence"),
        (
            "bee1a7fc3253231dbde2a997aa3a4d02ac1bcf8457c4081941e8572cf1f22824",
            "bee1a7fc3253231dbde2a997aa3a4d02ac1bcf8457c4081941e8572cf1f22820",
        ),
        ("thirteen tamper-denial checks passed", "thirteen tamper-denial checks failed"),
        ("its historical signature is not", "its historical signature is now"),
        ("2026-10-07T11:52:32Z", "2026-10-08T11:52:32Z"),
        ("No new cloud authority was added.", "New agent signing authority was added."),
    ],
)
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
        changed = status[:position] + replacement + status[position + len(original) :]

        def altered_read(path, *args, **kwargs):
            return changed if path == status_path else read_text(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", altered_read)
        with pytest.raises(AssertionError):
            test_status_insertion_preserves_all_existing_sections_and_history()
        offset = position + len(original)


@pytest.mark.parametrize(
    "original,replacement",
    [
        (
            "Full exact-head cloud tests for\n  this changed continuation remain separate from PR #209's completed CI.",
            "Full exact-head cloud tests for\n  this changed continuation passed all checks using PR #209's completed CI.",
        ),
        (
            "configuration matched the pinned archive; it has not been deployed.",
            "configuration matched the pinned archive; it has been deployed.",
        ),
        (
            "Source readiness is 98/2,146 paths, A19 42/74; these are not live case counts.",
            "Live certification is 98/2,146 paths, A19 42/74; these are live case counts.",
        ),
        (
            "receipts are preserved. Full L7 remains **0/21**;",
            "receipts are preserved. Full L7 is certified **21/21**;",
        ),
        (
            "remain unwired. They are not counted as ready certification paths.",
            "are fully wired. They are counted as ready certification paths.",
        ),
        (
            "read failed closed on a relevant-code pin mismatch; restoration remains unproved.",
            "read passed despite a relevant-code pin mismatch; restoration is proved.",
        ),
        (
            "Windows PWA/image stages were skipped after that failure, not passed.",
            "Windows PWA/image stages passed despite that failure, not skipped.",
        ),
    ],
    ids=[
        "new-cloud-pass",
        "new-deployment",
        "new-live-counts",
        "new-l7",
        "new-unwired-readiness",
        "new-rollback-pass",
        "new-skipped-pass",
    ],
)
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


@pytest.mark.parametrize(
    "original,replacement",
    [
        ("944755427c177d9ef661b24fdb37ea3f35f7ca99", "944755427c177d9ef661b24fdb37ea3f35f7ca90"),
        ("Agent L7 remains **0/21**.", "Agent L7 is complete **21/21**."),
        (
            "Public verifier\n  fixtures are not live Azure signing",
            "Public verifier\n  fixtures are live Azure signing",
        ),
        (
            "prove a production cutover or preservation of arbitrary later production writes.",
            "prove a production cutover and preservation of arbitrary later production writes.",
        ),
        ("no production code or image was repaired.", "production code and image were repaired."),
        (
            "No PR #209 or #210 production deployment is established",
            "PR #209 and #210 production deployment is established",
        ),
        ("Host stability remains unqualified.", "Host stability is qualified."),
        ("this observation awards no certification", "this observation awards all certifications"),
    ],
)
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
    for boundary in (
        "Design is not an executed failure test",
        "W3-01 stays PARKED",
        "PARKED / NOT ACCEPTED",
        "MODEL_CONTENT",
    ):
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
