# Ruff quality report - 2026-10-19

## Status

**COMPLETE.**

## Installation

```text
Ruff 0.17.1
Installed via uv tool
Executable: C:\Users\Admin\.local\bin\ruff.exe
```

`C:\Users\Admin\.local\bin` was added to the user PATH for future shells.

## Existing tooling audit

No pre-existing Black, Flake8, isort, Pylint, Ruff, Tox or equivalent Python
quality configuration was found. There was no tool conflict to resolve.

## Configuration

`pyproject.toml` now defines:

- target Python 3.12;
- line length 120;
- excluded generated, temporary and dependency directories;
- selected rules `E9` and `F`;
- legacy ignores for `F401`, `F403`, `F405`, `F811` and `F841`;
- formatting settings for newly introduced Python files.

The legacy ignores are deliberate: the runtime contains compact one-line
statements, dynamic imports and compatibility re-exports. Reformatting thousands
of legacy lines would increase behavioral risk without a functional benefit.

## Enforcement

`scripts/check_ruff_changed.py` provides:

1. changed-file lint using the legacy-safe baseline;
2. strict `E9/F` lint for newly added Python files;
3. format check for newly added Python files using the repository's
   `pyproject.toml` policy.

The formatting check was corrected during final verification: an initial
`--isolated` invocation ignored the 120-character repository setting and used
Ruff's 88-character default. It now loads `pyproject.toml` explicitly.

CI runs:

```text
uv run ruff check .
uv run python scripts/check_ruff_changed.py
uv run python -m compileall -q app scripts tests
```

## Repairs made

- Initialized `feedback` before the orchestration retry loop in `app/main.py`,
  removing a real `F821` undefined-name finding.
- Removed a placeholder-free f-string in `app/offline_survival.py`.
- Formatted all newly introduced Python modules and tests.
- No behavior-sensitive bulk auto-fix was applied.

## Results

```text
ruff check .                         PASS
scripts/check_ruff_changed.py        PASS
ruff format --check <new Python>     PASS
python -m compileall                 PASS
full Python regression               6052 passed, 20 skipped, 3 deselected
```

The final full Python suite result is recorded in `REGRESSION_REPORT.md`.

## Policy for future changes

- Existing behavior-sensitive legacy formatting is not a condition for unrelated
  work.
- New Python files must pass strict `E9/F` lint and Ruff formatting.
- Changed files must not introduce undefined names or syntax failures.
- Any future expansion of rules must first produce a measured baseline and a
  reviewed remediation plan.
