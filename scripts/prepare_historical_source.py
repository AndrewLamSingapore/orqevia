"""Prepare the exact historical source object needed by offline provenance tests.

The pinned source is not reachable from main, so a full branch checkout can omit
it. This helper fetches that object without changing refs or the worktree. It
does not change the dated signer, source closure, or expected tree contracts.
"""

import argparse
import base64
import json
import os
from pathlib import Path
import subprocess


SOURCE = "891e3adfdd6defac00d7faef34bec06a10de4a4e"
EXPECTED_TREE = "39e90331a979b6c88e156a53559b590560954e4e"
REMOTE = "https://github.com/AndrewLamSingapore/orqevia.git"
TOKEN_ENV = "ORQEVIA_CI_READ_TOKEN"


class PreparationError(RuntimeError):
    """A fixed, non-sensitive failure code suitable for CI output."""


def _git_environment():
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("GIT_TRACE", "GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))
        and key
        not in {
            TOKEN_ENV,
            "GIT_CONFIG_COUNT",
            "GIT_CONFIG_PARAMETERS",
            "GIT_CURL_VERBOSE",
            "GIT_SSL_NO_VERIFY",
            "GIT_ASKPASS",
            "SSH_ASKPASS",
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_COMMON_DIR",
            "GIT_OBJECT_DIRECTORY",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        }
    }
    environment.update(GIT_NO_REPLACE_OBJECTS="1", GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    settings = [
        ("http.sslVerify", "true"),
        ("http.followRedirects", "false"),
        ("credential.helper", ""),
        ("credential.interactive", "false"),
        ("http.extraHeader", ""),
        (f"http.{REMOTE}.extraHeader", ""),
        ("protocol.allow", "never"),
        ("protocol.https.allow", "always"),
    ]
    token = os.environ.get(TOKEN_ENV, "")
    if token:
        authorization = base64.b64encode(("x-access-token:" + token).encode()).decode("ascii")
        settings.append((f"http.{REMOTE}.extraHeader", "AUTHORIZATION: basic " + authorization))
    for index, (key, value) in enumerate(settings):
        environment[f"GIT_CONFIG_KEY_{index}"] = key
        environment[f"GIT_CONFIG_VALUE_{index}"] = value
    environment["GIT_CONFIG_COUNT"] = str(len(settings))
    return environment


def _git(repository, arguments, environment, *, timeout=30):
    try:
        return subprocess.run(
            ["git", "-C", str(repository), *arguments],
            env=environment,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PreparationError("historical_source_git_unavailable_or_timed_out") from error


def prepare(repository):
    environment = _git_environment()
    if _git(repository, ["rev-parse", "--git-dir"], environment).returncode:
        raise PreparationError("historical_source_repository_unavailable")
    fetched = _git(repository, ["cat-file", "-e", SOURCE + "^{commit}"], environment).returncode != 0
    if fetched:
        result = _git(
            repository,
            [
                "fetch",
                "--depth=1",
                "--no-tags",
                "--no-write-fetch-head",
                "--no-auto-maintenance",
                "--no-recurse-submodules",
                REMOTE,
                SOURCE,
            ],
            environment,
            timeout=180,
        )
        if result.returncode:
            # Captured transport output can contain authentication diagnostics.
            raise PreparationError("historical_source_fetch_failed")
    result = _git(repository, ["rev-parse", "--verify", SOURCE + "^{tree}"], environment)
    tree = result.stdout.decode("ascii", errors="replace").strip()
    if result.returncode or tree != EXPECTED_TREE:
        raise PreparationError("historical_source_tree_mismatch")
    return {"status": "VERIFIED", "source_revision": SOURCE, "source_tree": tree, "fetched": fetched}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
    arguments = parser.parse_args(argv)
    try:
        receipt = prepare(arguments.repository)
    except PreparationError as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
