from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from tools.dell_node_sync import core


def git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={repo.resolve()}", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=check,
    )
    return result.stdout.strip()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def validated_commit(repo: Path, name: str, text: str, *, node: str) -> str:
    write(repo / name, text)
    git(repo, "add", name)
    git(
        repo,
        "commit",
        "-m",
        f"update {name}\n\nJARVIS-Origin-Node: {node}\nJARVIS-Work-Unit: test\nJARVIS-Validation: PASS",
    )
    return git(repo, "rev-parse", "HEAD")


def ordinary_commit(repo: Path, name: str, text: str) -> str:
    write(repo / name, text)
    git(repo, "add", name)
    git(repo, "commit", "-m", f"update {name}")
    return git(repo, "rev-parse", "HEAD")


def clone(remote: Path, target: Path) -> Path:
    subprocess.run(["git", "clone", "--branch", "main", str(remote), str(target)], check=True, capture_output=True)
    git(target, "config", "user.email", "sync@example.invalid")
    git(target, "config", "user.name", "Dell Sync Test")
    return target


def fixture(tmp_path: Path) -> tuple[Path, Path, Path, dict]:
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(seed)], check=True, capture_output=True)
    git(seed, "config", "user.email", "sync@example.invalid")
    git(seed, "config", "user.name", "Dell Sync Test")
    ordinary_commit(seed, "source.txt", "base\n")
    git(seed, "remote", "add", "origin", str(remote))
    git(seed, "push", "-u", "origin", "main")
    repo = clone(remote, tmp_path / "repo")
    config = {
        "schema_version": "1.0.0",
        "node": {"node_id": f"dell:{socket.gethostname()}", "expected_hostname": socket.gethostname()},
        "state_dir": str(tmp_path / "state"),
        "ssot": {"mode": "proposal_only"},
        "repositories": [{
            "repository_id": "velyqua",
            "canonical_local_path": str(repo),
            "canonical_github_remote": str(remote),
            "default_branch": "main",
            "allow_auto_ff": True,
            "allow_auto_push": True,
        }],
    }
    config_path = tmp_path / "config.json"
    write(config_path, json.dumps(config))
    return config_path, repo, remote, config


def test_01_clean_inventory_is_pass_and_idempotent(tmp_path):
    config_path, repo, _, _ = fixture(tmp_path)
    before = git(repo, "rev-parse", "HEAD")
    first = core.synchronize(config_path)
    second = core.synchronize(config_path)
    assert first["overall"] == second["overall"] == "PASS"
    assert git(repo, "rev-parse", "HEAD") == before


def test_02_remote_change_fast_forwards_to_dell(tmp_path):
    config_path, repo, remote, _ = fixture(tmp_path)
    other = clone(remote, tmp_path / "other")
    expected = ordinary_commit(other, "remote.txt", "remote\n")
    git(other, "push", "origin", "main")
    result = core.synchronize(config_path)
    assert result["overall"] == "PASS"
    assert git(repo, "rev-parse", "HEAD") == expected
    assert "fast_forwarded" in result["repositories"][0]["actions"]


def test_03_validated_local_change_pushes_and_verifies_remote(tmp_path):
    config_path, repo, remote, config = fixture(tmp_path)
    expected = validated_commit(repo, "local.txt", "local\n", node=config["node"]["node_id"])
    result = core.synchronize(config_path)
    assert result["overall"] == "PASS"
    assert git(remote, "rev-parse", "refs/heads/main") == expected
    assert result["repositories"][0]["remote_verified"] is True


def test_04_non_conflicting_concurrent_change_rebases_and_pushes(tmp_path):
    config_path, repo, remote, config = fixture(tmp_path)
    validated_commit(repo, "local.txt", "local\n", node=config["node"]["node_id"])
    other = clone(remote, tmp_path / "other")
    ordinary_commit(other, "remote.txt", "remote\n")
    git(other, "push", "origin", "main")
    result = core.synchronize(config_path)
    assert result["overall"] == "PASS"
    assert "rebased_non_conflicting" in result["repositories"][0]["actions"]
    assert (repo / "local.txt").read_text() == "local\n"
    assert (repo / "remote.txt").read_text() == "remote\n"


def test_05_conflicting_concurrent_change_preserves_both_histories(tmp_path):
    config_path, repo, remote, config = fixture(tmp_path)
    local = validated_commit(repo, "source.txt", "local\n", node=config["node"]["node_id"])
    other = clone(remote, tmp_path / "other")
    remote_sha = ordinary_commit(other, "source.txt", "remote\n")
    git(other, "push", "origin", "main")
    result = core.synchronize(config_path)
    item = result["repositories"][0]
    assert result["overall"] == "PENDING" and item["error"] == "semantic_conflict"
    assert git(repo, "rev-parse", "HEAD") == local
    assert git(repo, "rev-parse", "origin/main") == remote_sha
    assert not (repo / ".git" / "rebase-merge").exists()


def test_06_offline_commit_queues_then_recovers_push(tmp_path):
    config_path, repo, remote, config = fixture(tmp_path)
    expected = validated_commit(repo, "offline.txt", "offline\n", node=config["node"]["node_id"])
    hidden = tmp_path / "remote.offline"
    remote.rename(hidden)
    pending = core.synchronize(config_path)
    assert pending["overall"] == "PENDING"
    hidden.rename(remote)
    recovered = core.synchronize(config_path)
    assert recovered["overall"] == "PASS"
    assert git(remote, "rev-parse", "refs/heads/main") == expected


def test_07_unvalidated_ahead_commit_is_not_pushed(tmp_path):
    config_path, repo, remote, _ = fixture(tmp_path)
    remote_before = git(remote, "rev-parse", "refs/heads/main")
    ordinary_commit(repo, "unknown.txt", "unknown\n")
    result = core.synchronize(config_path)
    assert result["overall"] == "PENDING"
    assert result["repositories"][0]["error"] == "unvalidated_ahead_commits"
    assert git(remote, "rev-parse", "refs/heads/main") == remote_before


def test_08_dirty_tree_is_preserved_and_queued(tmp_path):
    config_path, repo, _, _ = fixture(tmp_path)
    write(repo / "source.txt", "dirty\n")
    result = core.synchronize(config_path)
    assert result["overall"] == "PENDING"
    assert (repo / "source.txt").read_text() == "dirty\n"
    assert result["repositories"][0]["error"] == "dirty_working_tree"


def test_09_explicit_work_unit_validates_commits_pushes_and_proposes_ssot(tmp_path):
    config_path, repo, remote, config = fixture(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    write(repo / "firmware.ino", "void setup() {}\nvoid loop() {}\n")
    unit = {
        "work_unit_id": "esp32-wifi-test",
        "repository_id": "velyqua",
        "base_revision": base,
        "paths": ["firmware.ino"],
        "validation_commands": [[sys.executable, "-c", "raise SystemExit(0)"]],
        "commit_message": "Add validated ESP32 firmware",
    }
    unit_path = tmp_path / "unit.json"
    write(unit_path, json.dumps(unit))
    result = core.commit_work_unit(config_path, unit_path)
    head = git(repo, "rev-parse", "HEAD")
    assert result["overall"] == "PASS"
    assert git(remote, "rev-parse", "refs/heads/main") == head
    assert result["work_unit"]["authority"] == "PROPOSAL_FOR_PRIME_RECONCILIATION"
    assert "JARVIS-Origin-Node" in git(repo, "log", "-1", "--format=%B")


def test_10_secret_path_is_rejected_without_staging(tmp_path):
    config_path, repo, _, _ = fixture(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    write(repo / ".env", "WIFI_PASSWORD=do-not-commit-this\n")
    unit = {"repository_id": "velyqua", "base_revision": base, "paths": [".env"], "validation_commands": []}
    unit_path = tmp_path / "secret-unit.json"
    write(unit_path, json.dumps(unit))
    with pytest.raises(ValueError, match="sensitive path"):
        core.commit_work_unit(config_path, unit_path)
    assert git(repo, "diff", "--cached", "--name-only") == ""


def test_11_validation_failure_does_not_commit(tmp_path):
    config_path, repo, _, _ = fixture(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    write(repo / "change.txt", "change\n")
    unit = {
        "repository_id": "velyqua",
        "base_revision": base,
        "paths": ["change.txt"],
        "validation_commands": [[sys.executable, "-c", "raise SystemExit(9)"]],
    }
    unit_path = tmp_path / "bad-unit.json"
    write(unit_path, json.dumps(unit))
    with pytest.raises(RuntimeError, match="validation failed"):
        core.commit_work_unit(config_path, unit_path)
    assert git(repo, "rev-parse", "HEAD") == base


def test_12_stale_lock_and_corrupt_status_recover_after_restart(tmp_path):
    config_path, _, _, _ = fixture(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    write(state / "sync.lock", json.dumps({"pid": 2147483647}))
    write(state / "status.json", "{interrupted")
    result = core.synchronize(config_path)
    assert result["overall"] == "PASS"
    assert json.loads((state / "status.json").read_text())["overall"] == "PASS"
    assert not (state / "sync.lock").exists()


def test_13_wrong_node_identity_fails_closed(tmp_path):
    config_path, _, _, config = fixture(tmp_path)
    config["node"]["expected_hostname"] = "NOT-THIS-HOST"
    write(config_path, json.dumps(config))
    with pytest.raises(RuntimeError, match="hostname mismatch"):
        core.synchronize(config_path)


def test_14_installer_uses_supported_repetition_parameters():
    script = (Path(__file__).parents[1] / "scripts" / "install_dell_node_sync.ps1").read_text(encoding="utf-8")
    assert "-RepetitionInterval (New-TimeSpan -Minutes 30)" in script
    assert "-RepetitionDuration (New-TimeSpan -Days 3650)" in script
    assert ".Repetition.Interval" not in script


def test_15_installed_runners_bind_pythonpath_to_install_root():
    root = Path(__file__).parents[1]
    for name in ("run_dell_node_sync.ps1", "run_dell_truth_reconciler.ps1"):
        script = (root / "scripts" / name).read_text(encoding="utf-8")
        assert '"$InstallRoot;$env:PYTHONPATH"' in script
        assert "else { $InstallRoot }" in script
