import copy,json
from scripts.verify_phase2_freeze import RECEIPT,validate

def test_exact_frozen_candidate_receipt_passes():
    assert validate(json.loads(RECEIPT.read_text(encoding='utf-8')))==[]

def test_freeze_rejects_self_promotion_and_digest_drift():
    value=json.loads(RECEIPT.read_text(encoding='utf-8')); changed=copy.deepcopy(value)
    changed['authority']['candidate_grants_production_authority']=True
    changed['bindings']['config/agent_registry.json']='0'*64
    assert {'self_promotion','digest:config/agent_registry.json'}<=set(validate(changed))
