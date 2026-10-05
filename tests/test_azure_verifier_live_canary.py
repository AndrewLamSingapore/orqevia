"""Offline boundary checks for the protected-main cryptographic canary."""
import base64
import hashlib
import json
import os
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from scripts import azure_verifier_live_canary as canary


class CanaryTests(unittest.TestCase):
    def setUp(self):
        self.private = ec.generate_private_key(ec.SECP256R1())
        numbers = self.private.public_key().public_numbers()
        encode = lambda number: base64.urlsafe_b64encode(number.to_bytes(32, "big")).rstrip(b"=").decode()
        self.pin = {"kty": "EC", "crv": "P-256", "x": encode(numbers.x), "y": encode(numbers.y)}

    def test_public_verify_and_tamper_rejection(self):
        message = b"bounded live canary"
        der = self.private.sign(message, ec.ECDSA(hashes.SHA256()))
        r, s = utils.decode_dss_signature(der)
        signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        public = canary._public(self.pin)
        self.assertTrue(canary.verify(public, message, signature))
        self.assertFalse(canary.verify(public, message + b"!", signature))
        self.assertFalse(canary.verify(public, message, signature[:-1]))

    def test_duplicate_public_fields_rejected(self):
        with self.assertRaises(ValueError):
            json.loads('{"kty":"EC","kty":"RSA"}', object_pairs_hook=canary._unique)

    def test_noncanonical_base64_rejected(self):
        for value in ("AA=", "AA!", "", "A"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canary._decode(value)

    def test_non_main_cannot_request_identity(self):
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "AndrewLamSingapore/prime",
                                  "GITHUB_REF": "refs/heads/feature",
                                  "GITHUB_REF_PROTECTED": "true",
                                  "GITHUB_EVENT_NAME": "workflow_dispatch"}):
            with patch.object(canary, "_oidc") as oidc, self.assertRaises(ValueError):
                canary.run({"key_id": canary.KEY_PREFIX + "0" * 32, "jwk": self.pin})
            oidc.assert_not_called()

    def test_azure_response_key_mismatch_rejected(self):
        with patch.object(canary, "_read_json", return_value={"kid": canary.KEY_PREFIX + "1" * 32,
                                                              "value": "A" * 86}):
            with self.assertRaisesRegex(ValueError, "key mismatch"):
                canary._sign(canary.KEY_PREFIX + "0" * 32, hashlib.sha256(b"x").digest(), "redacted")


if __name__ == "__main__":
    unittest.main()
