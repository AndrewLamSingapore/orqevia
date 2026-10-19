# Python environment and uv report - 2026-10-19

## Status

**COMPLETE.**

## Installed tool

| Item | Value |
|---|---|
| Package | `astral-sh.uv` |
| Version | 0.13.1 |
| Installation | WinGet |
| Installer verification | WinGet hash verification PASS |
| Host executable | `C:\Users\Admin\AppData\Local\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe` |

## Lock ownership

| Environment | Python | Lock |
|---|---:|---|
| ORQEVIA development/CI | 3.12.15 | `uv.lock` |
| ORQEVIA production container | 3.12.14 | Existing pinned `requirements.txt` |
| Local AI/RAG service | 3.13.15 | `requirements-local-intelligence.lock` |

The environments remain separate by design. The backend does not inherit local
AI packages, and the local AI service is not installed into the backend image.

## Reproducible ORQEVIA environment

`pyproject.toml` records:

- Python constraint `>=3.12,<3.13`;
- the existing runtime package versions;
- OpenTelemetry API, SDK and OTLP HTTP exporter 1.45.1;
- development group `pytest 9.1.1` and `ruff 0.17.1`;
- `package = false` because this is a verification environment, not a new
  distributable application package.

Commands executed:

```powershell
uv lock --python 3.12
uv sync --frozen --python 3.12 --all-groups
uv lock --check
uv sync --frozen --python 3.12 --all-groups
```

Observed result:

```text
Using CPython 3.12.15
Creating virtual environment at: .venv
Resolved 58 packages
Checked 56 packages
```

No application package was installed into site-packages; `uv` only created the
isolated project environment.

## Local AI/RAG environment

Existing environment:

```text
C:\Users\Admin\orqevia-ai\.venv
Python 3.13.15
```

OpenTelemetry 1.45.1 packages were installed using uv into that existing
environment without replacing the FAISS/Ollama dependency set.

Verification:

```powershell
uv pip check --python C:\Users\Admin\orqevia-ai\.venv\Scripts\python.exe
```

Result:

```text
Checked 91 packages
All installed packages are compatible
```

The local AI transitive lock is:

```text
requirements-local-intelligence.lock
```

It was generated for Windows/Python 3.13 with:

```powershell
uv pip compile requirements-local-intelligence.txt `
  --python-version 3.13 `
  --python-platform windows `
  --output-file requirements-local-intelligence.lock
```

## CI integration

The `tooling-governance` job:

1. installs uv 0.13.1 from PyPI;
2. runs `uv sync --frozen --python 3.12 --all-groups`;
3. verifies uv, Python, Ruff and pytest versions;
4. runs canonical state checks;
5. runs observability/media-provider tests;
6. runs loopback OTLP verification;
7. runs Ruff baseline and changed-file gates;
8. compiles all Python sources.

## Preservation decisions

- The production Docker base image remains `python:3.12-slim`.
- Existing `requirements.txt` constraints remain authoritative for the runtime.
- No Poisson/Poetry/conda environment was introduced.
- No existing local AI environment was deleted or merged.
- `pip` remains in CI only to bootstrap uv.

## Recovery

To rebuild the development environment:

```powershell
uv sync --frozen --python 3.12 --all-groups
uv run python --version
uv run pytest --version
uv run ruff --version
```

To restore the local AI dependency set:

```powershell
uv pip sync requirements-local-intelligence.lock `
  --python C:\Users\Admin\orqevia-ai\.venv\Scripts\python.exe
```

Do not install the backend and local AI dependencies into the same environment.
