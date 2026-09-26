import copy
import json
from pathlib import Path

from scripts.verify_abex_runtime_receipt import validate


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = json.loads((ROOT / "docs/evidence/ABEX_RUNTIME_RECEIPT_17FAD78_20260926.json").read_text())


def test_current_abex_observation_is_valid_but_not_independent_acceptance():
    assert validate(RECEIPT) == []
    assert RECEIPT["independent_verification"] is False
    assert RECEIPT["acceptance"]["prime_runtime_acceptance"] == "UNVERIFIED"


def test_self_attestation_and_runtime_identity_mutations_fail_closed():
    mutations = []
    self_verified = copy.deepcopy(RECEIPT)
    self_verified["independent_verification"] = True
    mutations.append(self_verified)
    wrong_host = copy.deepcopy(RECEIPT)
    wrong_host["runtime"]["host_id"] = "Dell"
    mutations.append(wrong_host)
    wrong_agent_count = copy.deepcopy(RECEIPT)
    wrong_agent_count["canonical_components"]["logical_agent_count"] = 29
    mutations.append(wrong_agent_count)
    model_authority = copy.deepcopy(RECEIPT)
    model_authority["task_evidence"]["model_content_authoritative"] = True
    mutations.append(model_authority)
    false_state = copy.deepcopy(RECEIPT)
    false_state["acceptance"]["prime_runtime_acceptance"] = "VERIFIED"
    mutations.append(false_state)
    duplicate_owner = copy.deepcopy(RECEIPT)
    duplicate_owner["physical_owner_iphone_acceptance"]["duplicate_owner_identity_created"] = True
    mutations.append(duplicate_owner)
    for value in mutations:
        assert validate(value), value


def test_wrong_task_artifact_and_timestamp_mutations_fail_closed():
    wrong_task = copy.deepcopy(RECEIPT)
    wrong_task["physical_owner_acceptance"]["task_id"] = "wrong-task"
    assert "physical_task_binding_mismatch" in validate(wrong_task)
    wrong_artifact = copy.deepcopy(RECEIPT)
    wrong_artifact["task_evidence"]["artifact_sha256"] = "not-a-digest"
    assert "artifact_digest_invalid" in validate(wrong_artifact)
    wrong_time = copy.deepcopy(RECEIPT)
    wrong_time["task_evidence"]["updated_at"] = wrong_time["task_evidence"]["created_at"]
    assert "task_lifecycle_order_invalid" in validate(wrong_time)
