"""Candidate-only, no-model proof of the external-work evidence boundary."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.external_work_receipts import (
    ExternalReceipt, GithubAuditSnapshot, owner_digest, record_receipt,
    record_github_audit, github_audit_digest, select_github_audits, router,
)


HASH = "a" * 64
SHA = "b" * 40


class ExternalWorkReceiptsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "receipts.db"
        self.work_id = "portfolio-audit-20261003"

    def tearDown(self):
        self.temp.cleanup()

    def receipt(self, state, executor="NONE", **changes):
        data = dict(work_id=self.work_id, objective_sha256=HASH, agent_id="a07",
                    state=state, source="CODEX_TASK", evidence_sha256=HASH, executor=executor)
        data.update(changes)
        return ExternalReceipt(**data)

    def audit(self, repository="AndrewLamSingapore/game-platform", scope="CI", **changes):
        data = dict(work_id=self.work_id, repository=repository,
                    source_url=f"https://github.com/{repository}/commit/{SHA}",
                    commit_sha=SHA, observed_at="2026-10-03T12:00:00+08:00",
                    confidence="OBSERVED", scope=scope, check_state="PASS",
                    evidence_sha256=HASH)
        data.update(changes)
        return GithubAuditSnapshot(**data)

    def test_bounded_transition_and_owner_digest_cannot_accept_or_publish(self):
        record_receipt(self.receipt("RECEIVED"), db_path=self.db)
        with self.assertRaises(ValueError):
            record_receipt(self.receipt("RETURNED", "CODEX"), db_path=self.db)
        record_receipt(self.receipt("DELEGATED", "CODEX"), db_path=self.db)
        record_receipt(self.receipt("RETURNED", "CODEX"), db_path=self.db)
        with self.assertRaises(ValueError):
            record_receipt(self.receipt("DELEGATED", "CODEX"), db_path=self.db)
        result = owner_digest(self.work_id, db_path=self.db)
        self.assertEqual([r["state"] for r in result["evidence"]],
                         ["RECEIVED", "DELEGATED", "RETURNED"])
        self.assertEqual(result["authority"], "REPORTED_DATA_ONLY_NOT_ACCEPTED")
        with self.assertRaises(Exception):
            self.receipt("ACCEPT")
        with self.assertRaises(ValueError):
            record_receipt(self.receipt("FAILED", "CODEX", objective_sha256="c" * 64), db_path=self.db)

    def test_credential_urls_and_unknown_repositories_fail_closed(self):
        record_receipt(self.receipt("RECEIVED"), db_path=self.db)
        bad = [
            self.audit(source_url=f"https://github.com/AndrewLamSingapore/game-platform/commit/{SHA}?token=secret"),
            self.audit(source_url=f"https://github.com.evil/AndrewLamSingapore/game-platform/commit/{SHA}"),
            self.audit(repository="OtherOrg/game-platform"),
        ]
        for item in bad:
            with self.assertRaises(ValueError):
                record_github_audit(item, db_path=self.db)
        self.assertEqual(github_audit_digest(self.work_id, db_path=self.db)["snapshots"], [])

    def test_seven_distinct_source_identities_and_role_specific_selection(self):
        record_receipt(self.receipt("RECEIVED"), db_path=self.db)
        repos = ["prime", "velyqua", "the-portal", "sky-tablet", "game-platform",
                 "authority-engine", "AndrewLamSingapore"]
        for name in repos:
            record_github_audit(self.audit(repository="AndrewLamSingapore/" + name), db_path=self.db)
        with self.assertRaises(ValueError):
            record_github_audit(self.audit(repository="AndrewLamSingapore/game-platform"), db_path=self.db)
        result = github_audit_digest(self.work_id, db_path=self.db)
        self.assertEqual(len(result["snapshots"]), 7)
        selected = select_github_audits(self.work_id, "a18", tuple("AndrewLamSingapore/" + x for x in repos),
                                        db_path=self.db)
        self.assertEqual(len(selected["citations"]), 4)
        self.assertEqual(selected["omitted"], 2)
        self.assertNotIn("AndrewLamSingapore/prime", [x["repository"] for x in selected["citations"]])
        self.assertEqual(select_github_audits(self.work_id, "a17", ("AndrewLamSingapore/velyqua",),
                                              db_path=self.db)["citations"], [])  # CI isn't builder scope.
        private = select_github_audits(self.work_id, "a18", ("AndrewLamSingapore/prime",),
                                       db_path=self.db, allow_private_prime=True)
        self.assertEqual(private["citations"][0]["repository"], "AndrewLamSingapore/prime")

    def test_router_requires_owner_auth_and_is_not_mounted_automatically(self):
        app = FastAPI()
        app.include_router(router)
        with patch.dict(os.environ, {"PRIME_DATA_DIR": self.temp.name,
                                     "PRIME_SPINE_TOKEN": "local-test-token"}):
            with TestClient(app) as client:
                data = self.receipt("RECEIVED").model_dump()
                self.assertEqual(client.post("/api/external-work/receipts", json=data).status_code, 401)
                self.assertEqual(client.post("/api/external-work/receipts", json=data,
                                             headers={"Authorization": "Bearer local-test-token"}).status_code, 202)
                self.assertEqual(client.get(f"/api/external-work/{self.work_id}",
                                            headers={"Authorization": "Bearer local-test-token"}).json()["state"],
                                 "RECEIVED")
                self.assertEqual(client.post("/api/external-work/receipts", json={**data, "secret": "x"},
                                             headers={"Authorization": "Bearer local-test-token"}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
