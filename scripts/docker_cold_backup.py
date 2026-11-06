"""Plan/verify a two-disk backup; copying requires an approved offline window.

Default action is plan. This program never stops Docker, WSL or any process,
never compacts disks, never restores/overwrites a disk and never prunes Docker.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from docker_storage_monitor import atomic_json, command, vhdx_metadata


def sources():
    root = Path(os.environ.get("LOCALAPPDATA", "C:/Users/Admin/AppData/Local")) / "Docker/wsl"
    return {"data": root / "disk/docker_data.vhdx", "boot": root / "main/ext4.vhdx"}


def digest_file(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def plan(destination):
    disks = {name: vhdx_metadata(path) for name, path in sources().items()}
    destination = Path(destination).resolve()
    ancestor = destination
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    required = sum(disk["logical_bytes"] or 0 for disk in disks.values())
    capacity = shutil.disk_usage(ancestor)
    return {
        "status": "PLAN_ONLY_NO_BACKUP_CREATED",
        "virtual_disks": disks,
        "destination": str(destination),
        "required_copy_bytes": required,
        "required_free_with_10_percent_margin": (required * 110 + 99) // 100,
        "destination_free_bytes": capacity.free,
        "all_sources_exist": all(d["exists"] for d in disks.values()),
        "capacity_sufficient": capacity.free >= (required * 110 + 99) // 100,
        "consistency": "UNVERIFIED_UNTIL_OFFLINE_EXCLUSIVE_COPY_AND_HASH_VERIFICATION",
        "restore_qualification": "NOT_TESTED",
        "background_pause_must_remain": True,
    }


def require_offline():
    if os.name != "nt":
        raise RuntimeError("This procedure is specifically qualified for the ABEX Windows paths")
    # All checks are read-only. Any uncertainty refuses a consistent-backup claim.
    processes = command(
        [
            "powershell",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -in @('Docker Desktop','com.docker.backend','com.docker.build') } | Select-Object -ExpandProperty ProcessName",
        ]
    )
    running = command(["wsl", "--list", "--running", "--quiet"])
    if processes or "docker-desktop" in running:
        raise RuntimeError("Docker Desktop/WSL is active; no copy attempted")
    result = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, timeout=15)
    if result.returncode == 0:
        raise RuntimeError("Docker daemon is available; no copy attempted")


def exclusive_read(path):
    """Hold a Windows share-none read handle for the complete two-disk copy."""
    import ctypes
    from ctypes import wintypes
    import msvcrt

    library = ctypes.WinDLL("kernel32", use_last_error=True)
    create = library.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    library.CloseHandle.argtypes = [wintypes.HANDLE]
    library.CloseHandle.restype = wintypes.BOOL
    handle = create(str(Path(path).resolve()), 0x80000000, 0, None, 3, 0x08000000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), "Exclusive offline disk handle unavailable")
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        library.CloseHandle(handle)
        raise
    return os.fdopen(descriptor, "rb", buffering=1024 * 1024)


def copy_stream_verified(stream, target):
    """Never overwrite; the caller retains its source handle throughout."""
    hasher = hashlib.sha256()
    size = 0
    with Path(target).open("xb") as output:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
            output.write(block)
            size += len(block)
        output.flush()
        os.fsync(output.fileno())
    expected = hasher.hexdigest()
    if digest_file(target) != expected:
        raise RuntimeError("Backup readback SHA256 mismatch; preserve partial evidence and investigate")
    return {"file": Path(target).name, "bytes": size, "sha256": expected}


def copy_offline(destination, approved):
    if not approved:
        raise ValueError("The Owner must explicitly authorize the offline maintenance window before copying")
    proposal = plan(destination)
    if not proposal["all_sources_exist"] or not proposal["capacity_sufficient"]:
        raise ValueError("Missing source or insufficient capacity")
    require_offline()
    with ExitStack() as stack:
        handles = {name: stack.enter_context(exclusive_read(path)) for name, path in sources().items()}
        # Both share-none handles must be held before any output disk is created.
        destination = Path(destination).resolve()
        for path in sources().values():
            if destination == path.resolve() or destination.is_relative_to(path.parent.parent.resolve()):
                raise ValueError("Backup destination overlaps the live Docker disk tree")
        destination.mkdir(parents=True, exist_ok=False)
        manifest = {
            "schema": "abex.docker.cold-backup.v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "copy_status": "IN_PROGRESS",
            "consistency": "OFFLINE_EXCLUSIVE_HANDLES",
            "restore_qualification": "NOT_TESTED",
            "disks": {},
        }
        atomic_json(destination / "manifest.json", manifest)
        for name, stream in handles.items():
            filename = "docker_data.vhdx" if name == "data" else "ext4.vhdx"
            manifest["disks"][name] = copy_stream_verified(stream, destination / filename)
            manifest["disks"][name]["original_path"] = str(sources()[name])
        manifest["copy_status"] = "HASH_VERIFIED_BOTH_DISKS_NOT_RESTORE_QUALIFIED"
        atomic_json(destination / "manifest.json", manifest)
    return manifest


def verify(folder):
    folder = Path(folder).resolve()
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8-sig"))
    if manifest.get("copy_status") != "HASH_VERIFIED_BOTH_DISKS_NOT_RESTORE_QUALIFIED" or set(
        manifest.get("disks", {})
    ) != {"data", "boot"}:
        raise ValueError("Incomplete or unsupported backup manifest")
    for name, entry in manifest["disks"].items():
        expected_name = "docker_data.vhdx" if name == "data" else "ext4.vhdx"
        if entry["file"] != expected_name:
            raise ValueError("Unexpected backup filename")
        path = folder / expected_name
        if path.stat().st_size != entry["bytes"] or digest_file(path) != entry["sha256"]:
            raise ValueError("Backup integrity verification failed")
    return {"status": "HASH_VERIFIED_BOTH_DISKS", "restore_qualification": "NOT_TESTED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "verify", "copy-offline"), nargs="?", default="plan")
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--approved-maintenance-window", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.action == "plan":
        result = plan(args.destination)
    elif args.action == "verify":
        result = verify(args.destination)
    else:
        result = copy_offline(args.destination, args.approved_maintenance_window)
    if args.output:
        atomic_json(args.output, result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
