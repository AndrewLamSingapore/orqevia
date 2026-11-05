"""Historical fixture preparation preserves byte checks and CI credential isolation."""

import base64
import json
import subprocess

import pytest

from scripts import prepare_historical_source as preparation


@pytest.fixture
def pinned_repository(tmp_path, monkeypatch):
    repository = tmp_path / "historical.git"
    subprocess.run(["git", "init", "--bare", str(repository)], capture_output=True, check=True)

    def write_object(kind, value):
        result = subprocess.run(
            ["git", "-C", str(repository), "hash-object", "-w", "-t", kind, "--stdin"],
            input=value,
            capture_output=True,
            check=True,
        )
        return result.stdout.decode("ascii").strip()

    tree = write_object("tree", b"")
    commit = write_object(
        "commit",
        (
            f"tree {tree}\nauthor Fixture <fixture@example.invalid> 1 +0000\n"
            "committer Fixture <fixture@example.invalid> 1 +0000\n\nHistorical source fixture\n"
        ).encode(),
    )
    monkeypatch.setattr(preparation, "SOURCE", commit)
    monkeypatch.setattr(preparation, "EXPECTED_TREE", tree)
    return repository, commit, tree


def test_existing_exact_object_needs_no_network_or_ref_changes(pinned_repository):
    repository, commit, tree = pinned_repository
    assert preparation.prepare(repository) == {
        "status": "VERIFIED",
        "source_revision": commit,
        "source_tree": tree,
        "fetched": False,
    }
    refs = subprocess.run(["git", "-C", str(repository), "for-each-ref"], capture_output=True, check=True).stdout
    assert not refs
    assert not (repository / "FETCH_HEAD").exists()


def test_wrong_historical_tree_still_fails_closed(pinned_repository, monkeypatch):
    repository, _, _ = pinned_repository
    monkeypatch.setattr(preparation, "EXPECTED_TREE", "0" * 40)
    with pytest.raises(preparation.PreparationError, match="historical_source_tree_mismatch"):
        preparation.prepare(repository)


def test_fetch_failure_never_logs_credentials_or_transport_output(tmp_path, monkeypatch, capsys):
    token = "synthetic-read-token"
    monkeypatch.setenv(preparation.TOKEN_ENV, token)
    monkeypatch.setenv("GIT_TRACE_CURL", "1")
    calls = []

    def run(arguments, *, env, **kwargs):
        calls.append((arguments, env))
        if "rev-parse" in arguments:
            return subprocess.CompletedProcess(arguments, 0, b".git", b"")
        return subprocess.CompletedProcess(arguments, 1, b"", token.encode())

    monkeypatch.setattr(preparation.subprocess, "run", run)
    assert preparation.main(["--repository", str(tmp_path)]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out) == {"status": "FAIL", "error": "historical_source_fetch_failed"}
    assert not output.err and token not in output.out
    arguments, environment = calls[-1]
    assert "--depth=1" in arguments and preparation.SOURCE in arguments
    assert token not in " ".join(arguments)
    assert preparation.TOKEN_ENV not in environment and "GIT_TRACE_CURL" not in environment
    entries = {
        environment[f"GIT_CONFIG_KEY_{index}"]: environment[f"GIT_CONFIG_VALUE_{index}"]
        for index in range(int(environment["GIT_CONFIG_COUNT"]))
    }
    authorization = base64.b64encode(("x-access-token:" + token).encode()).decode("ascii")
    assert entries[f"http.{preparation.REMOTE}.extraHeader"] == "AUTHORIZATION: basic " + authorization
    assert entries["http.sslVerify"] == "true"
    assert entries["http.followRedirects"] == "false"
