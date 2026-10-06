"""No Azure credentials or network: a fake BlobClient is the entire transport."""

import hashlib
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.offhost_blob_transport import (
    ACCOUNT_URL, CONTAINER, MAGIC, TransportError, _blob_client, canary, encrypted_file,
    validate_sas,
)


NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


def sas(**overrides):
    fields = {
        "sv": "2024-11-04", "sr": "c", "sp": "rcw", "spr": "https",
        "se": "2026-10-06T12:30:00Z", "sig": "fake%2Bsignature",
    }
    fields.update(overrides)
    return "&".join(f"{key}={value}" for key, value in fields.items())


class FakeBlob:
    def __init__(self, *, tamper=False, exists=False):
        self.data = b"existing" if exists else None
        self.tamper = tamper
        self.upload_kwargs = None

    def upload_blob(self, source, **kwargs):
        self.upload_kwargs = kwargs
        if self.data is not None:
            raise RuntimeError("exists; secret URL must not escape")
        self.data = source.read() if hasattr(source, "read") else source

    def download_blob(self):
        return self

    def chunks(self):
        data = self.data + b"x" if self.tamper else self.data
        yield data[:7]
        yield data[7:]


class BlobTransportTests(unittest.TestCase):
    def test_sas_contract(self):
        self.assertEqual(validate_sas("?" + sas(), now=NOW), sas())
        for value in (
            sas(sr="b"), sas(sp="rcwl"), sas(sp="rcwd"), sas(spr="https%2Chttp"),
            sas(se="2026-10-06T14:00:00Z"), sas(se="2026-10-06T12:01:00Z"),
            sas(st="2026-10-06T12:10:00Z"), sas(ss="b", srt="co"),
            sas(si="policy"), sas(sig=""), sas() + "&sp=rcw", "https://x.blob.core.windows.net/?" + sas(),
            sas() + "\n&sp=rcw", sas(sig="fake%0Asignature"),
        ):
            with self.subTest(value=value[:20]), self.assertRaises(TransportError):
                validate_sas(value, now=NOW)

    def test_canary_readback_and_no_overwrite(self):
        fake = FakeBlob()
        seen = {}

        def factory(token, name):
            seen.update(token=token, name=name)
            return fake

        # No real SAS can be used in tests; patch the clock at the validation seam.
        from unittest.mock import patch
        with patch("scripts.offhost_blob_transport.validate_sas", side_effect=lambda token: validate_sas(token, now=NOW)):
            result = canary(sas(), client_factory=factory, payload=b"synthetic-only")
        self.assertTrue(seen["name"].startswith("canary/"))
        self.assertEqual(fake.upload_kwargs, {"blob_type": "BlockBlob", "length": 14, "overwrite": False})
        self.assertEqual(result["sha256"], hashlib.sha256(b"synthetic-only").hexdigest())
        self.assertEqual(result["verification"], "DOWNLOAD_SHA256_MATCH")
        self.assertNotIn("sig", str(result))
        self.assertEqual(ACCOUNT_URL, "https://abexrecovery20261006.blob.core.windows.net")
        self.assertEqual(CONTAINER, "abex-recovery")

    def test_readback_tamper_and_existing_blob_fail_closed(self):
        from unittest.mock import patch
        with patch("scripts.offhost_blob_transport.validate_sas", side_effect=lambda token: validate_sas(token, now=NOW)):
            for fake in (FakeBlob(tamper=True), FakeBlob(exists=True)):
                with self.assertRaises(TransportError) as failure:
                    canary(sas(), client_factory=lambda _token, _name: fake, payload=b"synthetic")
                self.assertNotIn("secret", str(failure.exception))
                self.assertNotIn("sig", str(failure.exception))

    def test_encrypted_file_magic_and_readback(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "ciphertext.bin"
            source.write_bytes(MAGIC + b"synthetic-ciphertext-bytes")
            expected = hashlib.sha256(source.read_bytes()).hexdigest()
            fake = FakeBlob()
            with patch("scripts.offhost_blob_transport.validate_sas", side_effect=lambda token: validate_sas(token, now=NOW)):
                result = encrypted_file(sas(), source, expected, client_factory=lambda _token, _name: fake)
                self.assertTrue(result["blob"].startswith("encrypted/"))
                self.assertEqual(result["bytes"], source.stat().st_size)
                source.write_bytes(b"plaintext")
                with self.assertRaises(TransportError):
                    encrypted_file(sas(), source, expected, client_factory=lambda _token, _name: FakeBlob())
                source.write_bytes(MAGIC + b"different")
                with self.assertRaises(TransportError):
                    encrypted_file(sas(), source, expected, client_factory=lambda _token, _name: FakeBlob())

    def test_constructor_exception_cannot_leak_sas(self):
        from unittest.mock import patch
        with patch("scripts.offhost_blob_transport.validate_sas", side_effect=lambda token: validate_sas(token, now=NOW)):
            def fail(_token, _name):
                raise RuntimeError("fake%2Bsignature")

            with self.assertRaises(TransportError) as failure:
                canary(sas(), client_factory=fail, payload=b"synthetic")
            self.assertNotIn("fake%2Bsignature", str(failure.exception))

    def test_official_sdk_seam_uses_fixed_endpoint_and_separate_credential(self):
        from unittest.mock import patch
        recorded = {}

        def constructor(**kwargs):
            recorded.update(kwargs)
            return object()

        azure = types.ModuleType("azure")
        storage = types.ModuleType("azure.storage")
        blob = types.ModuleType("azure.storage.blob")
        blob.BlobClient = constructor
        with patch.dict(sys.modules, {"azure": azure, "azure.storage": storage, "azure.storage.blob": blob}):
            _blob_client(sas(), "canary/fixed.bin")
        self.assertEqual(recorded["account_url"], ACCOUNT_URL)
        self.assertEqual(recorded["container_name"], CONTAINER)
        self.assertEqual(recorded["blob_name"], "canary/fixed.bin")
        self.assertEqual(recorded["credential"], sas())
        self.assertNotIn("sig", recorded["account_url"])


if __name__ == "__main__":
    unittest.main()
