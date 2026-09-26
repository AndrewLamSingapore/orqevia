import copy
import json

from scripts.verify_phase2_candidate import MANIFEST, validate


def test_phase2_candidate_manifest_is_fail_closed():
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert validate(value) == []


def test_phase2_manifest_rejects_production_or_authority_drift():
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    changed = copy.deepcopy(value)
    changed["feature_flags"]["production_enabled"] = True
    changed["authority"]["member_inherits_owner"] = True
    changed["promotion"]["authorized_by_this_manifest"] = True
    errors = validate(changed)
    assert {"production_flag", "authority:member_inherits_owner", "promotion_boundary"} <= set(errors)
