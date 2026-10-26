"""Run real-component controlled HTTPS acceptance and export reproducible evidence."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import uuid4
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, default=ROOT / ".artifacts" / "activity-pockets")
    args = parser.parse_args()
    destination = args.evidence_dir.resolve()
    if not destination.is_relative_to(ROOT):
        raise SystemExit("Use a repository-local evidence directory for this controlled verifier")
    destination.mkdir(parents=True, exist_ok=True)
    run = destination / ("run-" + uuid4().hex)
    run.mkdir()
    junit = run / "acceptance.xml"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/test_activity_pockets.py",
        "--basetemp=" + str(run / "pytest"),
        "--junitxml=" + str(junit),
    ]
    started = datetime.now(timezone.utc).isoformat()
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    (run / "test-output.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
    suites = ET.parse(junit).getroot().iter("testsuite") if junit.exists() else []
    totals = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
    for suite in suites:
        for key in totals:
            totals[key] += int(suite.attrib.get(key, 0))
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    diff = subprocess.check_output(["git", "diff", "HEAD", "--", "app", "tests", "scripts", "contracts"], cwd=ROOT)
    names = subprocess.check_output(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            "app",
            "tests",
            "scripts",
            "contracts",
            "config",
            "skills",
            "governance",
        ],
        cwd=ROOT,
        text=True,
    ).splitlines()
    files = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in sorted(set(names))
        if (ROOT / name).is_file()
    }
    file_manifest = json.dumps(files, sort_keys=True, separators=(",", ":"))
    (run / "source-files.json").write_text(file_manifest + "\n", encoding="utf-8")
    for database in (run / "pytest").glob("test_complete_twenty*/pockets.db"):
        with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
            outputs = [json.loads(row[0]) for row in db.execute("SELECT body FROM pocket_records WHERE kind='output'")]
            events = [json.loads(row[0]) for row in db.execute("SELECT body FROM pocket_events ORDER BY sequence")]
        (run / "reference-outputs.json").write_text(json.dumps(outputs, indent=2), encoding="utf-8")
        (run / "reference-events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")
    report = {
        "schema_version": "1.0",
        "scope": "controlled-fixture-real-component-integration",
        "started_at": started,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "source_revision": revision,
        "working_diff_sha256": hashlib.sha256(diff).hexdigest(),
        "tested_file_manifest_sha256": hashlib.sha256(file_manifest.encode()).hexdigest(),
        "python": sys.version.split()[0],
        "command": command,
        "exit_code": result.returncode,
        "result": "VERIFIED" if result.returncode == 0 else "FAILED",
        **totals,
        "fixture_qualification_is_production_certification": False,
        "production_deployed": False,
        "live_fleet_qualification": "PARKED_BY_OWNER",
        "artifacts": sorted(path.name for path in run.iterdir() if path.is_file()),
    }
    (run / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (destination / "LATEST.json").write_text(
        json.dumps({"run": run.name, "report": report}, indent=2), encoding="utf-8"
    )
    print(json.dumps({"result": report["result"], **totals, "evidence": str(run)}, indent=2))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
