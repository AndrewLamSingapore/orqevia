"""Non-destructive migration of retired database filenames."""

from __future__ import annotations

from pathlib import Path
import shutil


def migrate_legacy_database(path: str | Path, legacy_name: str) -> Path:
    """Copy a legacy SQLite database family to its current name when absent.

    The legacy bytes remain in place for rollback. An existing destination is
    never overwritten.
    """
    destination = Path(path)
    legacy_leaf = Path(legacy_name)
    if not legacy_leaf.name or legacy_leaf.name != legacy_name:
        raise ValueError("legacy_name must be a file name")
    legacy = destination.with_name(legacy_leaf.name)
    if destination.exists() or not legacy.is_file():
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy, destination)
    for suffix in ("-wal", "-shm"):
        source_sidecar = Path(str(legacy) + suffix)
        if source_sidecar.is_file():
            shutil.copy2(source_sidecar, Path(str(destination) + suffix))
    return destination
