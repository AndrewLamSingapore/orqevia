"""Independent regression of review findings. All contexts are synthetic fixtures.

These tests qualify gate semantics only; they do not establish a Dell host,
an ABEX candidate, a deployment, or physical iPhone speech.
"""
import dataclasses
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import dell_peer as peer


class ReviewFindings(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = peer.EvidenceStore(pathlib.Path(self.temp.name) / "evidence")
        self.addCleanup(self.store.close)
        self.binding = peer.Binding("a" * 40, "b" * 40, "sha256:" + "c" * 64, "a" * 40)
        self.manifest = {"schema_version": 1, **dataclasses.asdict(self.binding), "claims": []}
        self.evidence = self.store.put_bytes(b"Synthetic gate fixture; not production evidence.\n")
        self.approval = self.context("fixture-approval", peer.REQUIRED_CHECKS)
        self.deployed = self.context("fixture-deployed", peer.POST_CHECKS)

    def context(self, run_id, checks):
        return peer.TrustedRunContext(
            self.binding, run_id, "DELL", True,
            tuple(peer.CheckObservation(k, self.binding, "PASS", "PROVEN_BY_INDEPENDENT_DELL", (self.evidence,), run_id)
                  for k in checks), (),
        )

    def test_post_drift_never_exposes_current_promotion_pass(self):
        drift = dataclasses.replace(self.deployed, binding=dataclasses.replace(self.binding, image_digest="sha256:" + "d" * 64))
        report = peer.evaluate_postpromotion(self.manifest, self.store, self.approval, drift)
        self.assertEqual(report["PASS / FAIL / BLOCKED"], "FAIL")
        self.assertNotEqual(report["PROMOTION VERIFICATION"], "PROMOTION_VERIFICATION_PASS")

    def test_post_findings_and_gap_accounting_survive(self):
        finding = peer.Finding("review-P2", "P2", "Synthetic deployment finding", (self.evidence,))
        deployed = dataclasses.replace(self.deployed, findings=(finding,),
            unproven_claims=("Fixture unproven claim",),
            additional_physical_gates=("Fixture physical gate",),
            longer_observation_gates=("Fixture observation gate",))
        report = peer.evaluate_postpromotion(self.manifest, self.store, self.approval, deployed)
        self.assertEqual(report["P2"], ["review-P2"])
        self.assertIn("Fixture unproven claim", report["UNPROVEN CLAIMS"])
        self.assertIn("Fixture physical gate", report["PHYSICAL GATES REMAINING"])
        self.assertIn("Fixture observation gate", report["LONGER OBSERVATION GATES"])

    def test_missing_post_finding_evidence_cannot_pass(self):
        finding = peer.Finding("review-P3", "P3", "No preserved finding evidence", ())
        deployed = dataclasses.replace(self.deployed, findings=(finding,))
        report = peer.evaluate_postpromotion(self.manifest, self.store, self.approval, deployed)
        self.assertNotEqual(report["PASS / FAIL / BLOCKED"], "PASS")

    def test_candidate_json_claims_cannot_become_trusted_context(self):
        report = peer.evaluate_candidate(self.manifest, self.store, dataclasses.asdict(self.approval))
        self.assertEqual(report["PASS / FAIL / BLOCKED"], "BLOCKED")
        self.assertEqual(report["PROOF CLASSIFICATION"], "UNPROVEN")

    def test_software_pass_keeps_physical_iphone_gate_open(self):
        report = peer.evaluate_candidate(self.manifest, self.store, self.approval)
        self.assertEqual(report["PASS / FAIL / BLOCKED"], "PASS")
        self.assertIn(peer.IPHONE_AUDIBILITY, report["PHYSICAL GATES REMAINING"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
