"""Current source pointers do not confer portfolio or runtime authority."""

from pathlib import Path
import shutil

import pytest

from scripts.check_status_authority import OWNERSHIP, validate_status_authority

ROOT = Path(__file__).resolve().parents[1]
FILES = ("STATUS.md", "README.md", "AGENTS.md", "ORQEVIA-CURRENT-STATE.md", "docs/ESTATE-SWEEP-20261106.md")


@pytest.fixture
def source_copy(tmp_path):
    for name in FILES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    return tmp_path


def test_current_source_contract():
    validate_status_authority()


@pytest.mark.parametrize("name", ["STATUS.md", "README.md", "AGENTS.md"])
def test_stale_current_pointer_is_rejected(source_copy, name):
    path = source_copy / name
    path.write_text(
        path.read_text(encoding="utf8").replace("ORQEVIA-CURRENT-STATE.md", "retired-candidate.md"), encoding="utf8"
    )
    with pytest.raises(AssertionError, match="current source state"):
        validate_status_authority(source_copy)


@pytest.mark.parametrize("text", [OWNERSHIP, "Source checks are not runtime verification."])
def test_ownership_and_evidence_boundaries_are_required(source_copy, text):
    path = source_copy / "STATUS.md"
    path.write_text(path.read_text(encoding="utf8").replace(text, ""), encoding="utf8")
    with pytest.raises(AssertionError):
        validate_status_authority(source_copy)


def test_universal_status_authority_is_rejected(source_copy):
    with (source_copy / "STATUS.md").open("a", encoding="utf8") as stream:
        stream.write("This file replaces and supersedes every previous SSOT document.")
    with pytest.raises(AssertionError, match="universal authority"):
        validate_status_authority(source_copy)


def test_retired_master_pointer_is_rejected(source_copy):
    (source_copy / "SSOT.json").write_text("{}", encoding="utf8")
    with pytest.raises(AssertionError, match="retired SSOT"):
        validate_status_authority(source_copy)


@pytest.mark.parametrize("name", ["ORQEVIA-CURRENT-STATE.md", "docs/ESTATE-SWEEP-20261106.md"])
def test_missing_pointer_target_is_rejected(source_copy, name):
    (source_copy / name).unlink()
    with pytest.raises(AssertionError, match="target missing"):
        validate_status_authority(source_copy)
