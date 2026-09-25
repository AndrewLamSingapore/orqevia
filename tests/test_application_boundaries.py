import unittest

from app.application_boundaries import evaluate_application_evidence, require_application_scope


def evidence(kind="SIMULATED", verification_ref=None):
    return {
        "application": "VELYQUA",
        "evidence_class": kind,
        "claim": "Tank temperature was 27 C.",
        "provenance": ["fixture:bounded-test"],
        "verification_ref": verification_ref,
    }


PHYSICAL_RECEIPT = {
    "receipt_sha256": "a" * 64,
    "device_id": "esp32-fixture",
    "firmware_sha256": "b" * 64,
    "sensor_id": "temperature-fixture",
    "observed_at": "2026-09-25T00:00:00Z",
    "transport_provenance": ["signed-lan-envelope:fixture"],
    "independent_verifier": "hardware-receipt-verifier-v1",
}


class ApplicationBoundaryTests(unittest.TestCase):
    def test_simulation_cannot_become_physical_or_authority(self):
        result = evaluate_application_evidence(evidence())
        self.assertFalse(result.may_claim_physical)
        self.assertFalse(result.grants_authority)
        self.assertFalse(result.may_mutate_other_application)

    def test_physical_label_without_receipt_fails_closed(self):
        result = evaluate_application_evidence(evidence("PHYSICAL_VERIFIED"))
        self.assertFalse(result.may_claim_physical)
        self.assertIn("physical_evidence_receipt_invalid", result.reasons)

    def test_verified_physical_receipt_is_still_not_authority(self):
        result = evaluate_application_evidence(evidence("PHYSICAL_VERIFIED", PHYSICAL_RECEIPT))
        self.assertTrue(result.may_claim_physical)
        self.assertFalse(result.grants_authority)

    def test_model_self_attestation_cannot_be_physical_receipt(self):
        result = evaluate_application_evidence(evidence("PHYSICAL_VERIFIED", "model:self-attested"))
        self.assertFalse(result.may_claim_physical)

    def test_model_named_verifier_is_denied_even_with_structured_receipt(self):
        receipt = dict(PHYSICAL_RECEIPT, independent_verifier="model-generated-verifier")
        result = evaluate_application_evidence(evidence("PHYSICAL_VERIFIED", receipt))
        self.assertFalse(result.may_claim_physical)
        self.assertIn("physical_verifier_not_independent", result.reasons)

    def test_unknown_classes_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "unknown"):
            evaluate_application_evidence(evidence("MODEL_SAYS_REAL"))

    def test_cross_application_scope_is_denied(self):
        require_application_scope(application="JARVIS", scope_id="JARVIS")
        with self.assertRaisesRegex(PermissionError, "cross-application"):
            require_application_scope(application="VELYQUA", scope_id="JARVIS")


if __name__ == "__main__":
    unittest.main()
