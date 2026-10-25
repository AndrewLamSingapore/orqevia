"""Raw historical checkout for dated dry-run tests; never a live admission."""

import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

from scripts.sign_admitted_agent_cases import CODE_FILES


def pinned_batch_checkout(repository: Path, validator, plan: dict, destination: Path) -> Path:
    """Use actual pinned Git blobs while retaining the real closure checks.

    A temporary Git repository reads the existing object store through an
    alternate. It neither checks out nor modifies the shared repository. Archive
    bytes bypass platform line-ending conversion, and the original evidence is
    copied unchanged from the current, separately hash-checked batch package.
    """
    destination.mkdir()
    archive = subprocess.run(
        ["git", "archive", "--format=tar", validator.VERIFIER, "--", "app", "scripts", "config",
         "governance/agent-cert-verifier-azure-pins.json"],
        cwd=repository, capture_output=True, check=True, timeout=30,
    ).stdout
    names = set()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as stream:
        for member in stream.getmembers():
            if member.isdir():
                continue
            path = Path(member.name)
            if not member.isfile() or path.is_absolute() or ".." in path.parts:
                raise AssertionError("Unexpected member in fixed verifier archive")
            target = destination / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(stream.extractfile(member).read())
            names.add(member.name)
    assert set(CODE_FILES) <= names

    # The dated harness was authored after its code pin. It is the current code
    # under test; its domain/oracle dependencies must remain the pinned versions.
    paths = {validator.PLAN, "scripts/" + Path(validator.__file__).name, "scripts/audit_initialization_package.py"}
    for entry in plan["cases"]:
        folder = Path(entry["evidence_directory"]) / entry["record_established_fields"]["agent_id"]
        paths.update((str(folder / "execution.json"), str(folder / "review.json")))
    for name in paths:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((repository / name).read_bytes())

    objects = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-path", "objects"],
        cwd=repository, capture_output=True, check=True, timeout=10,
    ).stdout.decode().strip()
    subprocess.run(["git", "init", "--quiet", str(destination)], check=True, capture_output=True, timeout=10)
    (destination / ".git/objects/info/alternates").write_bytes(Path(objects).as_posix().encode("utf-8") + b"\n")
    return destination


DRY_RUN = """
import datetime as dt
import importlib
import json
import sys

validator = importlib.import_module(sys.argv[1])
fixture = json.load(sys.stdin)
run = fixture['run']
def github_read(path):
    if path == '/actions/runs/' + str(run['id']):
        return run
    return {'total_count': 1, 'workflow_runs': [run]}
started = dt.datetime.fromisoformat(fixture['started'])
times = iter((started, started + dt.timedelta(seconds=5)))
result = validator.protected_validation(
    fixture['plan'], env=fixture['env'], checkout_head=fixture['checkout_head'],
    github_read=github_read, clock=lambda: next(times),
)
print(json.dumps(result))
"""


def protected_validation_at_pin(snapshot: Path, validator, plan: dict, *, env: dict, checkout_head: str, run: dict, started):
    """Run the real historical domain/oracles without polluting current imports."""
    child_env = dict(os.environ)
    child_env["ORQEVIA_DATA_DIR"] = str(snapshot / "fixture-data")
    child_env["ORQEVIA_COMPUTE_QUEUE_DB"] = str(snapshot / "fixture-data/queue.db")
    payload = dict(plan=plan, env=env, checkout_head=checkout_head, run=run, started=started.isoformat())
    completed = subprocess.run(
        [sys.executable, "-B", "-c", DRY_RUN, validator.__name__],
        cwd=snapshot, env=child_env, input=json.dumps(payload).encode(), capture_output=True, timeout=120,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    return json.loads(completed.stdout)
