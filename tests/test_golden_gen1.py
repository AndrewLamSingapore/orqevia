import copy
import json
from pathlib import Path

from scripts.verify_golden_gen1 import MANIFEST, validate


def test_golden_gen1_manifest_binds_authoritative_evidence():
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert validate(value) == []


def test_golden_gen1_rejects_authority_and_generation_drift():
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    changed = copy.deepcopy(value)
    changed["authority"]["member_inherits_owner"] = True
    changed["phase2_boundary"]["state"] = "PRODUCTION"
    errors = validate(changed)
    assert "member_authority" in errors
    assert "phase2_boundary" in errors
