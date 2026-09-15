from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.dell_truth_reconciler import core


def git(path: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def commit(repo: Path, name: str, text: str) -> str:
    write(repo / name, text)
    git(repo, "add", name)
    git(repo, "commit", "-m", f"update {name}")
    return git(repo, "rev-parse", "HEAD")


def fixture(tmp_path: Path) -> tuple[Path, Path, Path, dict]:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    git(repo, "config", "user.email", "truth@example.invalid")
    git(repo, "config", "user.name", "Truth Test")
    head = commit(repo, "source.txt", "canonical\n")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-u", "origin", "main")
    observation = tmp_path / "abex.json"
    write(observation, json.dumps({"identity": "DESKTOP-BGD97NB"}))
    ssot = tmp_path / "ssot.json"
    ssot_value = {
        "as_of_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "systems": {"prime": {"source_head_sha": head}},
    }
    write(ssot, json.dumps(ssot_value))
    config = {
        "schema_version": "1.0.0",
        "ssot_path": str(ssot),
        "ssot_max_age_hours": 24,
        "abex": {"observation_path": str(observation)},
        "repositories": [{
            "repository_id": "prime",
            "component_name": "PRIME",
            "canonical_local_path": str(repo),
            "canonical_github_remote": str(remote),
            "default_branch": "main",
            "ssot_system_id": "prime",
            "classification": "CANONICAL",
        }],
    }
    config_path = tmp_path / "config.json"
    write(config_path, json.dumps(config))
    return config_path, repo, remote, config


def run(config_path: Path, **kwargs):
    return core.reconcile(config_path, **kwargs)


def codes(result: dict) -> set[str]:
    return {item["code"] for item in result["contradictions"] + result["unresolved_findings"]}


def test_01_local_remote_ssot_equal_is_green(tmp_path):
    config_path, *_ = fixture(tmp_path)
    assert run(config_path)["overall_health"] == "GREEN"


def test_02_local_ahead_of_remote(tmp_path):
    config_path, repo, *_ = fixture(tmp_path)
    commit(repo, "ahead.txt", "ahead\n")
    assert "local_ahead" in codes(run(config_path))


def test_03_remote_ahead_of_local(tmp_path):
    config_path, repo, remote, _ = fixture(tmp_path)
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "--branch", "main", str(remote), str(other)], check=True, capture_output=True)
    git(other, "config", "user.email", "truth@example.invalid")
    git(other, "config", "user.name", "Truth Test")
    commit(other, "remote.txt", "remote\n")
    git(other, "push", "origin", "main")
    git(repo, "fetch", "origin")
    assert "remote_ahead" in codes(run(config_path))


def test_04_genuine_divergence(tmp_path):
    config_path, repo, remote, _ = fixture(tmp_path)
    commit(repo, "local.txt", "local\n")
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "--branch", "main", str(remote), str(other)], check=True, capture_output=True)
    git(other, "config", "user.email", "truth@example.invalid")
    git(other, "config", "user.name", "Truth Test")
    commit(other, "remote.txt", "remote\n")
    git(other, "push", "origin", "main")
    git(repo, "fetch", "origin")
    result = run(config_path)
    assert "branch_diverged" in codes(result) and result["overall_health"] == "RED"


def test_05_dirty_working_tree(tmp_path):
    config_path, repo, *_ = fixture(tmp_path)
    write(repo / "source.txt", "dirty\n")
    assert "dirty_working_tree" in codes(run(config_path))


def test_06_untracked_source_file(tmp_path):
    config_path, repo, *_ = fixture(tmp_path)
    write(repo / "new.py", "pass\n")
    result = run(config_path)
    assert "untracked_files" in codes(result)


def test_07_wrong_remote(tmp_path):
    config_path, _, _, config = fixture(tmp_path)
    config["repositories"][0]["canonical_github_remote"] = "https://github.com/wrong/repo.git"
    write(config_path, json.dumps(config))
    assert "wrong_remote" in codes(run(config_path))


def test_08_missing_evidence(tmp_path):
    config_path, _, _, config = fixture(tmp_path)
    config["evidence"] = [{"evidence_id": "missing", "path": str(tmp_path / "missing.bin"), "sha256": "0" * 64}]
    write(config_path, json.dumps(config))
    assert "missing_evidence" in codes(run(config_path))


def test_09_corrupt_evidence_hash(tmp_path):
    config_path, _, _, config = fixture(tmp_path)
    evidence = tmp_path / "evidence.bin"
    write(evidence, "real")
    config["evidence"] = [{"evidence_id": "e1", "path": str(evidence), "sha256": "0" * 64}]
    write(config_path, json.dumps(config))
    assert "evidence_hash_mismatch" in codes(run(config_path))


def test_10_ssot_wrong_result_sha(tmp_path):
    config_path, _, _, config = fixture(tmp_path)
    ssot = Path(config["ssot_path"])
    value = json.loads(ssot.read_text())
    value["systems"]["prime"]["source_head_sha"] = "f" * 40
    write(ssot, json.dumps(value))
    assert "ssot_result_sha_mismatch" in codes(run(config_path))


def test_11_unsupported_pass_claim(tmp_path):
    config_path, _, _, config = fixture(tmp_path)
    config["claims"] = [{"claim_id": "pass", "verification_state": "VERIFIED", "evidence_ids": ["absent"]}]
    write(config_path, json.dumps(config))
    assert "unsupported_pass_claim" in codes(run(config_path))


def test_12_duplicate_repository(tmp_path):
    config_path, repo, remote, config = fixture(tmp_path)
    duplicate = dict(config["repositories"][0])
    duplicate.update({"repository_id": "prime-copy", "canonical_local_path": str(repo), "canonical_github_remote": str(remote)})
    config["repositories"].append(duplicate)
    write(config_path, json.dumps(config))
    assert "duplicate_repository" in codes(run(config_path))


def test_13_abex_unavailable(tmp_path):
    config_path, _, _, config = fixture(tmp_path)
    config["abex"] = {"observation_path": str(tmp_path / "gone.json")}
    write(config_path, json.dumps(config))
    assert "abex_unavailable" in codes(run(config_path))


def test_14_github_unavailable(tmp_path, monkeypatch):
    config_path, *_ = fixture(tmp_path)
    original = core._run_git
    def failed(path, *args, **kwargs):
        return (1, "", "offline") if args and args[0] == "fetch" else original(path, *args, **kwargs)
    monkeypatch.setattr(core, "_run_git", failed)
    assert "github_fetch_failed" in codes(run(config_path, fetch=True))


def test_15_stale_ssot(tmp_path):
    config_path, _, _, config = fixture(tmp_path)
    ssot = Path(config["ssot_path"])
    value = json.loads(ssot.read_text())
    value["as_of_utc"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    value["status"] = "STALE"
    value["verification"] = {"stale_reasons": ["verification_expired:manifest"]}
    write(ssot, json.dumps(value))
    result_codes = codes(run(config_path))
    assert {"stale_ssot", "ssot_declared_stale"}.issubset(result_codes)


def test_16_interrupted_reconciliation_preserves_source(tmp_path, monkeypatch):
    config_path, repo, *_ = fixture(tmp_path)
    before = git(repo, "rev-parse", "HEAD")
    original = core._sha256
    monkeypatch.setattr(core, "_sha256", lambda path: (_ for _ in ()).throw(KeyboardInterrupt()))
    config = json.loads(config_path.read_text())
    evidence = tmp_path / "evidence"
    write(evidence, "x")
    config["evidence"] = [{"evidence_id": "x", "path": str(evidence), "sha256": hashlib.sha256(b"x").hexdigest()}]
    write(config_path, json.dumps(config))
    try:
        run(config_path)
    except KeyboardInterrupt:
        pass
    finally:
        monkeypatch.setattr(core, "_sha256", original)
    assert git(repo, "rev-parse", "HEAD") == before


def test_17_restart_recovers_over_corrupt_derived_status(tmp_path):
    config_path, _, _, config = fixture(tmp_path)
    status = tmp_path / "state" / "status.json"
    write(status, "{interrupted")
    config["derived_status_path"] = str(status)
    write(config_path, json.dumps(config))
    result = run(config_path, repair=True)
    repaired = json.loads(status.read_text())
    assert repaired["reconciliation_id"] == result["reconciliation_id"]


def test_18_safe_repair_refreshes_refs_and_cache(tmp_path):
    config_path, _, _, config = fixture(tmp_path)
    status = tmp_path / "status.json"
    config["derived_status_path"] = str(status)
    write(config_path, json.dumps(config))
    result = run(config_path, fetch=True, repair=True)
    kinds = {item["kind"] for item in result["automatic_repairs_performed"]}
    assert {"remote_refs_refreshed", "derived_status_rebuilt"}.issubset(kinds)
