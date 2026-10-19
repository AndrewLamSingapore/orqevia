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
        with patch.dict(os.environ, {"ORQEVIA_DATA_DIR": self.temp.name,
                                     "ORQEVIA_SPINE_TOKEN": "local-test-token"}):
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

    def test_canonical_orqevia_audit_remains_private_by_default(self):
        record_receipt(self.receipt("RECEIVED"), db_path=self.db)
        repository = "AndrewLamSingapore/orqevia"
        record_github_audit(self.audit(repository=repository), db_path=self.db)
        result = github_audit_digest(self.work_id, db_path=self.db)
        self.assertEqual(result["snapshots"][0]["repository"], repository)
        self.assertEqual(select_github_audits(self.work_id, "a18", (repository,), db_path=self.db)["citations"], [])
        explicit = select_github_audits(self.work_id, "a18", (repository,), db_path=self.db,
                                       allow_private_prime=True)
        self.assertEqual(explicit["citations"], result["snapshots"])
        self.assertEqual(explicit["authority"], "UNTRUSTED_CITED_DATA_ONLY")

    def test_renamed_repository_can_join_full_historical_audit_without_rewriting_rows(self):
        record_receipt(self.receipt("RECEIVED"), db_path=self.db)
        names = ["prime", "velyqua", "the-portal", "sky-tablet", "game-platform",
                 "authority-engine", "AndrewLamSingapore"]
        for name in names:
            record_github_audit(self.audit(repository="AndrewLamSingapore/" + name), db_path=self.db)
        before = github_audit_digest(self.work_id, db_path=self.db)["snapshots"]
        record_github_audit(self.audit(repository="AndrewLamSingapore/orqevia"), db_path=self.db)
        after = github_audit_digest(self.work_id, db_path=self.db)["snapshots"]
        self.assertEqual([row for row in after if row["repository"] != "AndrewLamSingapore/orqevia"], before)
        selected = select_github_audits(self.work_id, "a18", ("AndrewLamSingapore/orqevia",),
                                        db_path=self.db, allow_private_prime=True)
        self.assertEqual({row["repository"] for row in selected["citations"]},
                         {"AndrewLamSingapore/prime", "AndrewLamSingapore/orqevia"})
        self.assertEqual(select_github_audits(self.work_id, "a18", ("AndrewLamSingapore/prime",),
                                              db_path=self.db)["citations"], [])
        with self.assertRaises(ValueError):
            record_github_audit(self.audit(repository="AndrewLamSingapore/orqevia"), db_path=self.db)

    def test_alias_does_not_relax_exact_source_url_or_product_binding(self):
        record_receipt(self.receipt("RECEIVED"), db_path=self.db)
        for repository, source in [
            ("AndrewLamSingapore/orqevia", "AndrewLamSingapore/prime"),
            ("AndrewLamSingapore/prime", "AndrewLamSingapore/orqevia"),
            ("AndrewLamSingapore/orqevia", "AndrewLamSingapore/velyqua"),
            ("AndrewLamSingapore/velyqua", "AndrewLamSingapore/orqevia"),
            ("AndrewLamSingapore/orqevia-fork", "AndrewLamSingapore/orqevia-fork"),
        ]:
            with self.subTest(repository=repository, source=source), self.assertRaises(ValueError):
                record_github_audit(self.audit(repository=repository,
                    source_url=f"https://github.com/{source}/commit/{SHA}"), db_path=self.db)
        self.assertEqual(github_audit_digest(self.work_id, db_path=self.db)["snapshots"], [])

    def test_orqevia_alias_cannot_expand_other_product_citations(self):
        record_receipt(self.receipt("RECEIVED"), db_path=self.db)
        for name in ("orqevia", "prime", "velyqua", "the-portal", "sky-tablet", "game-platform", "authority-engine"):
            record_github_audit(self.audit(repository="AndrewLamSingapore/" + name), db_path=self.db)
        for name in ("velyqua", "the-portal", "sky-tablet", "game-platform", "authority-engine"):
            repository = "AndrewLamSingapore/" + name
            selected = select_github_audits(self.work_id, "a18", (repository,), db_path=self.db)
            self.assertEqual([row["repository"] for row in selected["citations"]], [repository])

    def test_http_canonical_audit_requires_existing_owner_gate(self):
        app = FastAPI(); app.include_router(router)
        with patch.dict(os.environ, {"ORQEVIA_DATA_DIR": self.temp.name,
                                     "ORQEVIA_SPINE_TOKEN": "local-test-token"}):
            with TestClient(app) as client:
                owner = {"Authorization": "Bearer local-test-token"}
                self.assertEqual(client.post("/api/external-work/receipts",
                    json=self.receipt("RECEIVED").model_dump(), headers=owner).status_code, 202)
                body = self.audit(repository="AndrewLamSingapore/orqevia").model_dump(mode="json")
                self.assertEqual(client.post("/api/external-work/github-audits", json=body).status_code, 401)
                self.assertEqual(client.post("/api/external-work/github-audits", json=body,
                    headers={"Authorization": "Bearer other-test-token"}).status_code, 401)
                self.assertEqual(client.post("/api/external-work/github-audits", json=body, headers=owner).status_code, 202)
                digest = client.get(f"/api/external-work/{self.work_id}/github-audits", headers=owner).json()
                self.assertEqual(digest["snapshots"][0]["repository"], "AndrewLamSingapore/orqevia")
                self.assertEqual(digest["authority"], "REPORTED_DATA_ONLY_NOT_ACCEPTED")

    def test_alias_history_stays_bounded_without_extra_product_or_scope(self):
        record_receipt(self.receipt("RECEIVED"), db_path=self.db)
        names = ["orqevia", "prime", "velyqua", "the-portal", "sky-tablet",
                 "game-platform", "authority-engine", "AndrewLamSingapore"]
        for name in names:
            for scope in ("SOURCE", "CI", "PR", "DEPLOYMENT"):
                record_github_audit(self.audit(repository="AndrewLamSingapore/" + name, scope=scope), db_path=self.db)
        snapshots = github_audit_digest(self.work_id, db_path=self.db)["snapshots"]
        self.assertEqual(len(snapshots), 32)
        selection = tuple("AndrewLamSingapore/" + name for name in names if name != "prime")
        selected = select_github_audits(self.work_id, "a18", selection, db_path=self.db)
        self.assertEqual(len(selected["citations"]), 4)
        self.assertEqual(selected["omitted"], 8)
        self.assertFalse(any(row["repository"] in {"AndrewLamSingapore/orqevia", "AndrewLamSingapore/prime"}
                             for row in selected["citations"]))
        self.assertTrue(all(row["scope"] in {"CI", "PR"} for row in selected["citations"]))


if __name__ == "__main__":
    unittest.main()
