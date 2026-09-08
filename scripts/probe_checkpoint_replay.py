"""Release-blocking checkpoint adversary; synthetic key and mock executor only.

Exit zero only when a copied pre-consumption checkpoint cannot repeat authority.
No model, production database, tunnel, network or operator pilot is used.
"""
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import Mock

from app.action_harness import ActionEnvelopeIssuer, ActionHarness, HarnessUnavailable
from app.job_queue import JobQueue, QueuePolicy
from app.spine import StableSpine, SpineStore
from tests.test_harness_execution import SECRET, queued, run


def make_rig(directory):
    return (ActionEnvelopeIssuer(SECRET), ActionHarness(directory / "h.db", {"authority-v0": SECRET}),
            StableSpine(SpineStore(str(directory / "s.db"))),
            JobQueue(directory / "q.db", QueuePolicy(global_concurrency=1)))


def main():
    with tempfile.TemporaryDirectory(prefix="harness-checkpoint-adversary-") as temporary:
        root = Path(temporary)
        original = root / "original"
        clone = root / "clone"
        clone.mkdir()
        rig = make_rig(original)
        job, _ = queued(rig)
        for name in ("h.db", "s.db", "q.db"):
            source = sqlite3.connect(original / name)
            destination = sqlite3.connect(clone / name)
            try:
                source.backup(destination)
            finally:
                source.close()
                destination.close()
        infer = Mock(return_value={"result": "synthetic result"})
        run(rig, job, infer)
        rig[3].finish(job["id"], result="synthetic result")
        copied = make_rig(clone)
        rejected = False
        try:
            run(copied, job, infer)
        except (PermissionError, HarnessUnavailable):
            rejected = True
        safe = rejected and infer.call_count == 1
        print(json.dumps({"probe": "pre-consumption checkpoint replay", "synthetic_only": True,
                          "mock_executor_calls": infer.call_count, "clone_rejected": rejected,
                          "gate": "PASS" if safe else "HOLD", "production_touched": False}))
        return 0 if safe else 1


if __name__ == "__main__":
    raise SystemExit(main())
