"""Rehearse a byte-exact delta between two *quiesced* PRIME data trees.

This deliberately does not read live production or certify candidate-schema
compatibility. Both input trees must have been captured behind a write fence.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path


class DeltaError(ValueError):
    pass


def _is_reparse(path: Path) -> bool:
    # Windows junctions are not symlinks, but can escape the fenced tree.
    if path.is_symlink() or path.is_junction():
        return True
    return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inventory(root: Path) -> dict[str, str]:
    if not root.is_dir() or _is_reparse(root):
        raise DeltaError("input must be a real directory")
    files: dict[str, str] = {}
    for path in root.rglob("*"):
        if _is_reparse(path):
            raise DeltaError("links or reparse points are not allowed in a rollback tree")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = _digest(path)
        elif not path.is_dir():
            raise DeltaError("unsupported rollback tree entry")
    return dict(sorted(files.items()))


def _directories(root: Path) -> list[str]:
    """Include empty directories, whose shape a file-only inventory cannot prove."""
    if not root.is_dir() or _is_reparse(root):
        raise DeltaError("input must be a real directory")
    directories = []
    for path in root.rglob("*"):
        if _is_reparse(path):
            raise DeltaError("links or reparse points are not allowed in a rollback tree")
        if path.is_dir():
            directories.append(path.relative_to(root).as_posix())
    return sorted(directories)


def _safe_name(name: str) -> Path:
    path = Path(name)
    if not name or path.is_absolute() or "\\" in name or ":" in name or any(part in ("", ".", "..") for part in name.split("/")):
        raise DeltaError("invalid delta path")
    return path


def manifest_digest(package: Path) -> str:
    """Pin this digest outside the mutable package before accepting a replay."""
    return _digest(Path(package) / "manifest.json")


def capture_delta(snapshot: Path, final: Path, package: Path) -> dict:
    """Package changed bytes and tombstones without modifying either input."""
    snapshot, final, package = Path(snapshot), Path(final), Path(package)
    if package.exists():
        raise DeltaError("delta package already exists")
    before, after = _inventory(snapshot), _inventory(final)
    before_dirs, after_dirs = _directories(snapshot), _directories(final)
    if package.resolve().is_relative_to(snapshot.resolve()) or package.resolve().is_relative_to(final.resolve()):
        raise DeltaError("delta package must be outside both inputs")
    changed = {name: digest for name, digest in after.items() if before.get(name) != digest}
    deleted = sorted(set(before) - set(after))
    package.mkdir(parents=True)
    try:
        for name, digest in changed.items():
            target = package / "payload" / _safe_name(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(final / name, target)
            if _digest(target) != digest:
                raise DeltaError("source changed while capturing delta; discard package")
        manifest = {"schema": 2, "before": before, "after": after,
                    "before_dirs": before_dirs, "after_dirs": after_dirs,
                    "changed": changed, "deleted": deleted}
        (package / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        if _inventory(final) != after or _directories(final) != after_dirs:
            raise DeltaError("final tree changed during capture; discard package")
        return manifest
    except Exception:
        shutil.rmtree(package)
        raise


def replay_delta(snapshot: Path, package: Path, restored: Path, expected_manifest_sha256: str) -> None:
    """Verify inputs, then materialize a new tree; never mutate a snapshot."""
    snapshot, package, restored = Path(snapshot), Path(package), Path(restored)
    if restored.exists():
        raise DeltaError("restore destination already exists")
    if restored.resolve().is_relative_to(snapshot.resolve()) or restored.resolve().is_relative_to(package.resolve()):
        raise DeltaError("restore destination must be outside inputs")
    if len(expected_manifest_sha256) != 64 or manifest_digest(package) != expected_manifest_sha256:
        raise DeltaError("delta manifest does not match independent pinned digest")
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema") != 2:
        raise DeltaError("unsupported delta manifest")
    before, after, changed, deleted = (manifest.get(key) for key in ("before", "after", "changed", "deleted"))
    before_dirs, after_dirs = (manifest.get(key) for key in ("before_dirs", "after_dirs"))
    if (not all(isinstance(x, dict) for x in (before, after, changed))
            or not all(isinstance(x, list) and all(isinstance(name, str) for name in x)
                       and x == sorted(set(x)) for x in (deleted, before_dirs, after_dirs))):
        raise DeltaError("malformed delta manifest")
    for name in set(before) | set(after) | set(changed) | set(deleted) | set(before_dirs) | set(after_dirs):
        _safe_name(name)
    if _inventory(snapshot) != before or _directories(snapshot) != before_dirs:
        raise DeltaError("snapshot differs from delta base")
    if set(changed) != {name for name, digest in after.items() if before.get(name) != digest}:
        raise DeltaError("changed-file set is inconsistent")
    if sorted(set(before) - set(after)) != deleted:
        raise DeltaError("deleted-file set is inconsistent")
    payload = package / "payload"
    if changed:
        if _inventory(payload) != changed:
            raise DeltaError("delta payload differs from manifest")
    elif payload.exists():
        raise DeltaError("unexpected delta payload")
    restored.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rollback-delta-", dir=restored.parent) as temporary:
        staging = Path(temporary) / "data"
        shutil.copytree(snapshot, staging)
        for name in deleted:
            (staging / _safe_name(name)).unlink()
        for name in sorted(set(before_dirs) - set(after_dirs), key=lambda item: (item.count("/"), item), reverse=True):
            (staging / _safe_name(name)).rmdir()
        for name in after_dirs:
            (staging / _safe_name(name)).mkdir(parents=True, exist_ok=True)
        for name in changed:
            target = staging / _safe_name(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(package / "payload" / name, target)
        if _inventory(staging) != after or _directories(staging) != after_dirs:
            raise DeltaError("replayed tree differs from fenced final state")
        os.rename(staging, restored)
