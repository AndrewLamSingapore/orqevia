"""Strict Ruff checks for changed Python without reformatting legacy files."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PREFIXES = (
    "clients/dell/build/",
    "node_modules/",
    ".venv/",
    "__pycache__/",
)


def git(*arguments: str) -> list[str]:
    result = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"git {' '.join(arguments)} failed: {result.stderr.strip()}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def python_files(rows: list[str]) -> list[str]:
    return [
        row for row in rows if row.endswith(".py") and not row.startswith(EXCLUDED_PREFIXES) and (ROOT / row).is_file()
    ]


def main() -> int:
    base = os.getenv("RUFF_BASE_REF", "origin/main").strip()
    try:
        merge_base = git("merge-base", "HEAD", base)[0]
        changed = python_files(git("diff", "--name-only", "--diff-filter=ACMR", merge_base, "--"))
        added = python_files(git("diff", "--name-only", "--diff-filter=A", merge_base, "--"))
    except (IndexError, RuntimeError) as error:
        print(f"RUFF_CHANGED_BASELINE_UNAVAILABLE: {error}", file=sys.stderr)
        return 2

    if not changed:
        print("Ruff changed-file lint: PASS (no Python changes)")
    else:
        lint = subprocess.run(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--isolated",
                "--no-cache",
                "--select",
                "E9,F",
                "--ignore",
                "F401,F403,F405,F811,F841",
                *changed,
            ],
            cwd=ROOT,
            check=False,
        )
        if lint.returncode:
            return lint.returncode
        print(f"Ruff changed-file lint: PASS ({len(changed)} files)")

    if not added:
        print("Ruff new-file format: PASS (no new Python files)")
        return 0
    added_lint = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--isolated",
            "--no-cache",
            "--select",
            "E9,F",
            "--ignore",
            "F403,F405",
            *added,
        ],
        cwd=ROOT,
        check=False,
    )
    if added_lint.returncode:
        return added_lint.returncode
    print(f"Ruff new-file strict lint: PASS ({len(added)} files)")
    formatting = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "format",
            "--config",
            "pyproject.toml",
            "--check",
            *added,
        ],
        cwd=ROOT,
        check=False,
    )
    if formatting.returncode:
        return formatting.returncode
    print(f"Ruff new-file format: PASS ({len(added)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
