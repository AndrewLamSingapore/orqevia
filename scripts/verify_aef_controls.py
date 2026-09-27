"""Independent deterministic verifier for high-assurance engineering controls."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.application_boundaries import evaluate_application_evidence
from app.engineering_loop import _govern_verification


def main() -> int:
    digest=hashlib.sha256(b'candidate').hexdigest();checks={}
    checks['assertion_only_rejected']=not _govern_verification({'passed':True},digest)['passed']
    good={'passed':True,'verdict':'ACCEPT','verifier':'a18','independent':True,
          'candidate_sha256':digest,'checks':[{'name':'fixture','status':'PASS','evidence_ref':'fixture:executed'}]}
    checks['bound_receipt_accepted']=_govern_verification(good,digest)['passed']
    checks['wrong_digest_rejected']=not _govern_verification({**good,'candidate_sha256':'0'*64},digest)['passed']
    base={'application':'VELYQUA','evidence_class':'PHYSICAL_VERIFIED','claim':'physical reading',
          'provenance':['fixture:bounded']}
    checks['model_physical_claim_rejected']=not evaluate_application_evidence({**base,'verification_ref':'model:self-attested'}).may_claim_physical
    receipt={'receipt_sha256':'a'*64,'device_id':'device-fixture','firmware_sha256':'b'*64,
             'sensor_id':'sensor-fixture','observed_at':'2026-09-25T00:00:00Z',
             'transport_provenance':['signed-envelope:fixture'],'independent_verifier':'hardware-receipt-verifier-v1'}
    checks['structured_physical_receipt_bounded']=evaluate_application_evidence({**base,'verification_ref':receipt}).may_claim_physical
    result={'verifier':'aef-controls-v1','status':'PASS' if all(checks.values()) else 'FAIL',
            'checks':checks,'passed':sum(checks.values()),'total':len(checks),'production_touched':False}
    print(json.dumps(result,sort_keys=True))
    return 0 if result['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
