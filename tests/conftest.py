"""Configure disposable storage before application imports during collection.

Source tests must not depend on import order to avoid container /data paths.
Explicit caller-provided test directories remain supported.
"""
import os
import tempfile
from pathlib import Path

_test_data = tempfile.TemporaryDirectory(prefix="prime-pytest-", ignore_cleanup_errors=True)
os.environ.setdefault("PRIME_DATA_DIR", _test_data.name)
_data = Path(os.environ["PRIME_DATA_DIR"])
os.environ.setdefault("PRIME_SPINE_DB", str(_data / "spine.db"))
os.environ.setdefault("PRIME_COMPUTE_DB", str(_data / "compute-ledger.db"))


def pytest_unconfigure(config):
    _test_data.cleanup()

