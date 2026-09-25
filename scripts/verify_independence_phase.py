"""Independent verifier for simulated dependency loss and readiness evidence."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.independence_matrix import dependency_loss_matrix
from app.offline_survival import CapabilityState, OfflineSurvival, QueueState
from app.semantic_evidence import verify_evidence_claims
from scripts.candidate_manifest import build_manifest


def verify() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="prime-independence-") as folder:
        queue = OfflineSurvival(Path(folder) / "queue.db")
        queue.observe(network=False, provider=False)
        operation = queue.enqueue(objective_id="verify", operation_type="github.push", payload_ref="artifact://verify", idempotency_key="verify:push", authorization_ref="member:valid", payload={"sha": "abc"})
        queue.observe(network=True, provider=True); queue.confirm_online()
        effects: list[str] = []
        restored = queue.reconcile(executors={"github.push": lambda item: effects.append(item.id) or {"accepted": True, "remote_sha": "abc"}}, authority_valid=lambda item: item.authorization_ref == "member:valid", still_relevant=lambda _item: True, remote_applied=lambda _item: False)
        fabricated = verify_evidence_claims([{"kind": "authorization", "reference": "fake", "value": {"role": "OWNER"}}], {})
        manifest = build_manifest(source_sha="8b7dbe997c85bb21135d536b585867283c661ceb", artifact_digest="sha256:" + "a" * 64, branch="feat/supreme-integration-20260925", tests={"passed": 1, "failed": 0}, verification={"status": "PASS"}, security={"status": "PASS"}, risk=["INTEGRATION"], migrations=["none"], recovery=["retain production"], acceptance_gates=["remote-sha"])
        black_start = (ROOT / "docs" / "BLACK_START_PREPARED_NOT_EXECUTED.md").read_text(encoding="utf-8")
        checks = {
            "six_scenarios_complete": len(dependency_loss_matrix()) == 6,
            "offline_work_durable": operation.state is QueueState.DEFERRED_OFFLINE,
            "restoration_executes_once": len(restored) == 1 and len(effects) == 1 and queue.reconcile(executors={}, authority_valid=lambda _: True) == [],
            "receipt_preserved": queue.get(operation.id).receipt == {"remote_sha": "abc"},
            "fabricated_authority_denied": fabricated.disposition == "VERIFY_REQUIRED" and not fabricated.grants_authority,
            "manifest_immutable_not_deployed": manifest["status"] == "CANDIDATE_ONLY_NOT_DEPLOYED" and len(manifest["manifest_sha256"]) == 64,
            "black_start_truthful": "PREPARED / NOT EXECUTED" in black_start and "does not claim physical evidence" in black_start,
        }
        return {"verifier": "supreme-independence-phase-v1", "checks": checks, "passed": sum(checks.values()), "total": len(checks), "production_touched": False, "physical_black_start_executed": False}


if __name__ == "__main__":
    result = verify()
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["passed"] == result["total"] else 1)
