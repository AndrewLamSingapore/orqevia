"""Verify current source pointers without promoting historical runtime claims."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS_URL = "https://github.com/AndrewLamSingapore/orqevia/blob/main/STATUS.md"
SOURCE_URL = "https://github.com/AndrewLamSingapore/orqevia/blob/main/ORQEVIA-CURRENT-STATE.md"
OWNERSHIP = "Each product owns its source, configuration, contracts, and domain records in its repository."


def validate_status_authority(root: Path = ROOT) -> None:
    assert not (root / "SSOT.json").exists(), "retired SSOT.json must not be maintained"
    status = (root / "STATUS.md").read_text(encoding="utf8")
    assert status.startswith("# ORQEVIA status pointers"), "current status pointer heading required"
    assert "Source checks are not runtime verification." in status, "source/runtime evidence must stay separate"
    assert OWNERSHIP in status, "product data ownership contract required"
    for name in ("STATUS.md", "README.md", "AGENTS.md"):
        content = (root / name).read_text(encoding="utf8")
        assert "ORQEVIA-CURRENT-STATE.md" in content, name + " must identify the current source state"
        assert "replaces and supersedes every previous SSOT document" not in content, (
            "universal authority claim forbidden"
        )
    for name in ("ORQEVIA-CURRENT-STATE.md", "docs/ESTATE-SWEEP-20261106.md"):
        assert (root / name).is_file(), "current source pointer target missing"
    current = (root / "ORQEVIA-CURRENT-STATE.md").read_text(encoding="utf8")
    assert "Source validation" in current and "Current runtime revisions must be observed at the host." in current


if __name__ == "__main__":
    validate_status_authority()
    print("Current source pointers: PASS; actual deployment and runtime evidence remain separate")
