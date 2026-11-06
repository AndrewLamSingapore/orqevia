"""Storage location shared by the existing cross-product evidence adapters."""

import os
from pathlib import Path


def database_path() -> Path:
    root = Path(os.getenv("ORQEVIA_DATA_DIR", "/data"))
    root.mkdir(parents=True, exist_ok=True)
    # Existing records retain this historical filename. It imports no old
    # server, authority, scheduler or schema and creates no parallel user store.
    return root / "prime.db"
