"""Shared audit receipts must survive Windows/Linux checkout without re-dating."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class SyncReceiptTests(unittest.TestCase):
    def test_every_original_receipt_has_identical_bytes(self):
        folder=ROOT/'docs/evidence/autonomy-20261013'
        index=json.loads((folder/'receipt-index.json').read_text(encoding='utf-8'))
        self.assertFalse(index['original_evidence_dates_rewritten'])
        self.assertFalse(index['production_readiness_claimed'])
        self.assertEqual(len(index['receipts']),14)
        for receipt in index['receipts']:
            with self.subTest(path=receipt['path']):
                content=(folder/receipt['path']).read_bytes()
                self.assertEqual(len(content),receipt['bytes'])
                self.assertEqual(hashlib.sha256(content).hexdigest(),receipt['sha256'])
                self.assertIn('original_file_modified_at_utc',receipt)

    def test_new_evidence_directory_is_byte_preserved(self):
        self.assertIn('docs/evidence/autonomy-20261013/** -text',
                      (ROOT/'.gitattributes').read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main()
