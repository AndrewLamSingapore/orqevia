import json

import pytest

from scripts.verify_capability_register import ROOT, validate


def test_canonical_register_validates():
    assert validate()["canonical"] is True


def test_register_rejects_unsupported_verified_status(tmp_path):
    value = validate()
    value["capabilities"][0]["status"] = "VERIFIED_BY_ASSERTION"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        validate(path)
