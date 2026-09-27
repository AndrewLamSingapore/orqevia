"""Synthetic unit tests of gate logic; no Dell/ABEX/device certification."""

import contextlib
import dataclasses
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import dell_peer as peer


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = peer.EvidenceStore(self.root / "evidence")
        self.binding = peer.Binding("a" * 40, "b" * 40, "sha256:" + "c" * 64, "a" * 40)
        self.manifest = {"schema_version": 1, **dataclasses.asdict(self.binding), "claims": ["Audible iPhone speech"]}
        self.ref = self.store.put_bytes(b"SYNTHETIC UNIT TEST ONLY: trusted adapter fixture, not ABEX or Dell execution\n")
        self.context = self.make_context(peer.REQUIRED_CHECKS, "synthetic-pre-123")
        self.post = self.make_context(peer.POST_CHECKS, "synthetic-post-123")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def make_context(self, checks, run_id, binding=None):
        binding = binding or self.binding
        observations = tuple(peer.CheckObservation(key, binding, "PASS", "PROVEN_BY_INDEPENDENT_DELL", (self.ref,), run_id, "Synthetic fixture only") for key in checks)
        return peer.TrustedRunContext(binding, run_id, "DELL", True, observations, ())

    def assess(self, context=None):
        return peer.evaluate_candidate(self.manifest, self.store, context)

    def test_claims_and_hashes_alone_never_certify(self):
        report = self.assess()
        self.assertEqual(report["PASS / FAIL / BLOCKED"], "BLOCKED")
        self.assertEqual(report["PROOF CLASSIFICATION"], "UNPROVEN")

    def test_complete_trusted_synthetic_context_exercises_pass_without_physical_claim(self):
        report = self.assess(self.context)
        self.assertEqual(report["PASS / FAIL / BLOCKED"], "PASS", report["REASONS"])
        self.assertIn(peer.IPHONE_AUDIBILITY, report["PHYSICAL GATES REMAINING"])
        self.assertIn("Audible iPhone speech", report["UNPROVEN CLAIMS"])
        self.assertTrue(report["LONGER OBSERVATION GATES"])

    def test_every_required_check_is_mandatory(self):
        for key in peer.REQUIRED_CHECKS:
            with self.subTest(check=key):
                changed = dataclasses.replace(self.context, observations=tuple(o for o in self.context.observations if o.check_id != key))
                self.assertEqual(self.assess(changed)["PASS / FAIL / BLOCKED"], "BLOCKED")

    def test_duplicate_check_cannot_mask_failure(self):
        failed = dataclasses.replace(self.context.observations[0], outcome="FAIL")
        for observations in ((failed,) + self.context.observations, self.context.observations + (failed,)):
            self.assertEqual(self.assess(dataclasses.replace(self.context, observations=observations))["PASS / FAIL / BLOCKED"], "FAIL")

    def test_non_dell_or_nonindependent_context_cannot_certify(self):
        for changed in (dataclasses.replace(self.context, verifier_peer="ABEX"), dataclasses.replace(self.context, independent_source=False), dataclasses.replace(self.context, independent_source=1)):
            self.assertEqual(self.assess(changed)["PASS / FAIL / BLOCKED"], "BLOCKED")

    def test_automation_is_not_independent_dell_proof(self):
        for label in peer.PROOF_LABELS:
            if label == "PROVEN_BY_INDEPENDENT_DELL":
                continue
            with self.subTest(proof=label):
                obs = dataclasses.replace(self.context.observations[0], proof=label)
                changed = dataclasses.replace(self.context, observations=(obs,) + self.context.observations[1:])
                self.assertEqual(self.assess(changed)["PASS / FAIL / BLOCKED"], "BLOCKED")

    def test_stale_receipt_and_other_candidate_receipt_fail(self):
        changed_binding = dataclasses.replace(self.binding, image_digest="sha256:" + "d" * 64)
        for obs in (dataclasses.replace(self.context.observations[0], run_id="previous-run-123"), dataclasses.replace(self.context.observations[0], binding=changed_binding)):
            changed = dataclasses.replace(self.context, observations=(obs,) + self.context.observations[1:])
            self.assertEqual(self.assess(changed)["PASS / FAIL / BLOCKED"], "FAIL")

    def test_context_source_image_tree_drift_fails(self):
        for field, value in (("candidate_sha", "d" * 40), ("tree_sha", "d" * 40), ("image_digest", "sha256:" + "d" * 64)):
            with self.subTest(field=field):
                binding = dataclasses.replace(self.binding, **{field: value})
                if field == "candidate_sha":
                    binding = dataclasses.replace(binding, runtime_revision=value)
                changed = dataclasses.replace(self.context, binding=binding)
                self.assertEqual(self.assess(changed)["PASS / FAIL / BLOCKED"], "FAIL")

    def test_missing_evidence_is_blocked(self):
        obs = dataclasses.replace(self.context.observations[0], evidence=())
        changed = dataclasses.replace(self.context, observations=(obs,) + self.context.observations[1:])
        self.assertEqual(self.assess(changed)["PASS / FAIL / BLOCKED"], "BLOCKED")

    def test_corrupted_evidence_fails_and_existing_failure_is_preserved(self):
        failed = dataclasses.replace(self.context.observations[0], outcome="FAIL")
        report = self.assess(dataclasses.replace(self.context, observations=(failed,) + self.context.observations[1:]))
        receipt, seal = peer.seal_assessment(self.store, report)
        before = self.store.read(seal)
        path = self.store.root / self.ref.name
        path.chmod(0o600)
        path.write_bytes(b"tampered")
        self.assertEqual(self.assess(self.context)["PASS / FAIL / BLOCKED"], "FAIL")
        self.assertEqual(self.store.read(seal), before)
        self.assertEqual(hashlib.sha256(before).hexdigest(), receipt["EVIDENCE SHA-256"])

    def test_critical_finding_cannot_be_cleared_on_frozen_candidate(self):
        for severity in ("P0", "P1", "P2"):
            for resolved in (False, True):
                finding = peer.Finding("defect-001", severity, "deterministic fixture", (self.ref,), resolved)
                report = self.assess(dataclasses.replace(self.context, findings=(finding,)))
                self.assertEqual(report["PASS / FAIL / BLOCKED"], "FAIL")
                self.assertEqual(report[severity], ["defect-001"])

    def test_unexpected_observation_is_not_silently_ignored(self):
        extra = dataclasses.replace(self.context.observations[0], check_id="audible_iphone_speech")
        changed = dataclasses.replace(self.context, observations=self.context.observations + (extra,))
        self.assertEqual(self.assess(changed)["PASS / FAIL / BLOCKED"], "BLOCKED")

    def test_malformed_trusted_api_context_fails_closed(self):
        variants = (
            dataclasses.replace(self.context, binding=None),
            dataclasses.replace(self.context, observations=None),
            dataclasses.replace(self.context, findings=None),
            dataclasses.replace(self.context, unproven_claims=(None,)),
            dataclasses.replace(self.context, run_id=[]),
            dataclasses.replace(self.context, observations=(dataclasses.replace(self.context.observations[0], evidence=None),)),
        )
        for changed in variants:
            with self.subTest(context=changed):
                self.assertEqual(self.assess(changed)["PASS / FAIL / BLOCKED"], "BLOCKED")

    def test_manifest_cannot_add_trust_or_weaken_requirements(self):
        for key, value in (("trusted_context", dataclasses.asdict(self.context)), ("PROMOTION VERIFICATION", "PROMOTION_VERIFICATION_PASS"), ("required_checks", [])):
            manifest = dict(self.manifest, **{key: value})
            self.assertEqual(peer.evaluate_candidate(manifest, self.store, self.context)["PASS / FAIL / BLOCKED"], "BLOCKED")

    def test_image_tag_short_sha_or_wrong_revision_blocked(self):
        for key, value in (("image_digest", "jarvis:latest"), ("candidate_sha", "abc123"), ("runtime_revision", "f" * 40), ("schema_version", True)):
            self.assertEqual(peer.evaluate_candidate(dict(self.manifest, **{key: value}), self.store, self.context)["PASS / FAIL / BLOCKED"], "BLOCKED")

    def test_postpromotion_revalidates_approval_not_claimed_pass(self):
        imported_pass = {"PROMOTION VERIFICATION": "PROMOTION_VERIFICATION_PASS"}
        result = peer.evaluate_postpromotion(self.manifest, self.store, imported_pass, self.post)
        self.assertEqual(result["PASS / FAIL / BLOCKED"], "BLOCKED")

    def test_postpromotion_exact_binding_and_all_readonly_checks_required(self):
        result = peer.evaluate_postpromotion(self.manifest, self.store, self.context, self.post)
        self.assertEqual(result["POST-PROMOTION VERIFICATION"], "POST_PROMOTION_VERIFICATION_PASS", result["REASONS"])
        for key in peer.POST_CHECKS:
            changed = dataclasses.replace(self.post, observations=tuple(o for o in self.post.observations if o.check_id != key))
            self.assertEqual(peer.evaluate_postpromotion(self.manifest, self.store, self.context, changed)["PASS / FAIL / BLOCKED"], "BLOCKED")

    def test_postpromotion_missing_identity_is_blocked_mismatch_is_fail(self):
        changed_binding = dataclasses.replace(self.binding, image_digest="")
        post = self.make_context(peer.POST_CHECKS, "synthetic-post-123", changed_binding)
        self.assertEqual(peer.evaluate_postpromotion(self.manifest, self.store, self.context, post)["PASS / FAIL / BLOCKED"], "BLOCKED")
        changed_binding = dataclasses.replace(self.binding, image_digest="sha256:" + "d" * 64)
        post = self.make_context(peer.POST_CHECKS, "synthetic-post-123", changed_binding)
        result = peer.evaluate_postpromotion(self.manifest, self.store, self.context, post)
        self.assertEqual(result["PASS / FAIL / BLOCKED"], "FAIL")
        self.assertTrue(any("DEPLOYMENT DRIFT: image_digest" in x for x in result["REASONS"]))

    def test_postpromotion_reusing_pre_run_is_blocked(self):
        post = self.make_context(peer.POST_CHECKS, self.context.run_id)
        self.assertEqual(peer.evaluate_postpromotion(self.manifest, self.store, self.context, post)["PASS / FAIL / BLOCKED"], "BLOCKED")

    def test_postpromotion_retains_gaps_and_findings(self):
        finding = peer.Finding("deploy-001", "P1", "synthetic drift finding", (self.ref,))
        post = dataclasses.replace(self.post, findings=(finding,), additional_physical_gates=("Owner reconnect check",), unproven_claims=("No battery drain",), longer_observation_gates=("48 hour restart recovery",))
        result = peer.evaluate_postpromotion(self.manifest, self.store, self.context, post)
        self.assertEqual(result["PASS / FAIL / BLOCKED"], "FAIL")
        self.assertEqual(result["P1"], ["deploy-001"])
        self.assertIn("Owner reconnect check", result["PHYSICAL GATES REMAINING"])
        self.assertIn("No battery drain", result["UNPROVEN CLAIMS"])

    def test_postpromotion_p3_finding_still_requires_evidence(self):
        finding = peer.Finding("deploy-003", "P3", "low severity finding", ())
        result = peer.evaluate_postpromotion(self.manifest, self.store, self.context, dataclasses.replace(self.post, findings=(finding,)))
        self.assertEqual(result["PASS / FAIL / BLOCKED"], "BLOCKED")

    def test_cli_does_not_load_trusted_context_or_execute_candidate(self):
        path = self.root / "manifest.json"
        path.write_text(json.dumps(self.manifest))
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = peer.main(["evaluate", str(path), "--store", str(self.store.root)])
        result = json.loads(stdout.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(result["PASS / FAIL / BLOCKED"], "BLOCKED")
        ref = peer.EvidenceRef.from_dict(result["EVIDENCE REFERENCE"])
        self.store.read(ref)

    def test_duplicate_json_key_rejected(self):
        path = self.root / "manifest.json"
        path.write_text('{"schema_version":1,"schema_version":2}')
        with self.assertRaises(ValueError):
            peer._json_load(str(path))


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = peer.EvidenceStore(self.root / "evidence")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_unique_report_seals_never_overwrite_historical_fail(self):
        fail = self.store.seal({"status": "FAIL"})
        before = self.store.read(fail)
        passed = self.store.seal({"status": "PASS"})
        repeat = self.store.seal({"status": "FAIL"})
        self.assertEqual(len({fail.name, passed.name, repeat.name}), 3)
        self.assertEqual(self.store.read(fail), before)

    def test_uuid_collision_cannot_overwrite(self):
        fixed_uuid = mock.Mock(hex="f" * 32)
        with mock.patch.object(peer.uuid, "uuid4", return_value=fixed_uuid):
            ref = self.store.put_bytes(b"FAIL")
            with self.assertRaises(FileExistsError):
                self.store.put_bytes(b"PASS")
        self.assertEqual(self.store.read(ref), b"FAIL")

    def test_traversal_and_absolute_reference_rejected(self):
        for name in ("../victim", "/etc/passwd", "a/b.blob", "x" * 32 + ".blob"):
            ref = peer.EvidenceRef(name, "a" * 64, 0)
            with self.assertRaises(peer.InvalidEvidence):
                self.store.read(ref)
        with self.assertRaises(peer.InvalidEvidence):
            peer.EvidenceStore(self.root / "evidence" / ".." / "elsewhere")

    def test_symlink_artifact_and_store_parent_rejected(self):
        victim = self.root / "victim"
        victim.write_bytes(b"known bytes")
        name = "a" * 32 + ".blob"
        (self.store.root / name).symlink_to(victim)
        ref = peer.EvidenceRef(name, hashlib.sha256(b"known bytes").hexdigest(), 11)
        with self.assertRaises(OSError):
            self.store.read(ref)
        link = self.root / "linked"
        link.symlink_to(self.store.root, target_is_directory=True)
        with self.assertRaises(OSError):
            peer.EvidenceStore(link / "child")

    def test_symlink_source_and_ancestor_rejected(self):
        actual = self.root / "actual"
        actual.mkdir()
        (actual / "source.txt").write_bytes(b"source")
        link = self.root / "link"
        link.symlink_to(actual, target_is_directory=True)
        with self.assertRaises(OSError):
            self.store.put_file(link / "source.txt")
        direct = self.root / "source-link"
        direct.symlink_to(actual / "source.txt")
        with self.assertRaises(OSError):
            self.store.put_file(direct)

    def test_fifo_evidence_cannot_hang_reader(self):
        name = "b" * 32 + ".blob"
        os.mkfifo(self.store.root / name)
        with self.assertRaises(peer.InvalidEvidence):
            self.store.read(peer.EvidenceRef(name, hashlib.sha256(b"").hexdigest(), 0))

    def test_digest_size_and_type_are_checked(self):
        ref = self.store.put_bytes(b"abc")
        for changed in (dataclasses.replace(ref, sha256="0" * 64), dataclasses.replace(ref, size=2), dataclasses.replace(ref, size=True)):
            with self.assertRaises(peer.InvalidEvidence):
                self.store.read(changed)

    def test_store_directory_swap_cannot_redirect_descriptor(self):
        original = self.store.root
        moved = self.root / "moved"
        original.rename(moved)
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        original.symlink_to(elsewhere, target_is_directory=True)
        ref = self.store.put_bytes(b"descriptor anchored")
        self.assertTrue((moved / ref.name).is_file())
        self.assertFalse((elsewhere / ref.name).exists())
        self.assertEqual(self.store.read(ref), b"descriptor anchored")


if __name__ == "__main__":
    unittest.main(verbosity=2)
