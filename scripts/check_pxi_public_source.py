"""One official public-source retrieval in an isolated ledger; no monitoring."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.evidence_product import EvidenceLedger
from app.exposure_intelligence import ExposureIntelligence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', required=True, type=Path)
    args = parser.parse_args()
    root = args.output_directory
    # Refuse overwriting any prior probe, and never take a production data path.
    if root.exists(): raise ValueError('PXI_FRESH_ISOLATED_DIRECTORY_REQUIRED')
    root.mkdir(parents=True)
    service = ExposureIntelligence(EvidenceLedger(root / 'synthetic-and-public-lens.db'))
    receipt = service.retrieve_kev()
    receipt.update(production_changed=False, monitoring_active=False,
                   private_assets_checked=False, credential_values_used=False)
    (root / 'PUBLIC-SOURCE-RECEIPT.json').open('x', encoding='utf-8').write(json.dumps(receipt, sort_keys=True))
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt['retrieval_verified'] else 2

if __name__ == '__main__': raise SystemExit(main())
