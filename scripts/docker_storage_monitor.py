"""On-demand, read-only Docker/WSL storage inventory. No scheduler or cleanup."""

from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

WSL_ROOT = "/mnt/docker-desktop-disk/data/docker"
EXPECTED = {
    "orqevia-epoch-20261016-backend-1",
    "orqevia-epoch-20261016-interface-1",
    "orqevia-epoch-20261016-ollama-1",
    "orqevia-epoch-20261016-otel-collector-1",
    "orqevia-epoch-20261016-integration-gateway-1",
    "orqevia-epoch-20261016-cloudflared-1",
    "orqevia-epoch-20261016-cloudflared-dual-1",
    "orqevia-coaching-coaching-1",
    "orqevia-intelligence-1",
}
LOG_POLICY = {"Type": "json-file", "Config": {"max-size": "10m", "max-file": "3"}}
HISTORICAL_ROLLBACK_TAGS = {"orqevia:open-access-7275620-20261021", "orqevia:orq002-workflow-20261020"}


def command(arguments, timeout=30):
    result = subprocess.run(arguments, capture_output=True, timeout=timeout)
    if result.returncode:
        # Raw Docker diagnostics can include configuration or credentials.
        raise RuntimeError(f"Read-only command failed: {arguments[0]} {arguments[1]}")
    raw = result.stdout
    return raw.decode("utf-16-le" if b"\x00" in raw[:100] else "utf-8-sig").strip()


def docker_json(*arguments):
    return json.loads(command(["docker", *arguments]))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)  # Only the exact temporary output created above.


def vhdx_metadata(path):
    path = Path(path)
    result = {"path": str(path), "exists": path.is_file(), "logical_bytes": None, "allocated_bytes": None}
    if not path.is_file():
        return result
    result["logical_bytes"] = path.stat().st_size
    if os.name == "nt":
        from ctypes import wintypes

        library = ctypes.WinDLL("kernel32", use_last_error=True)
        get_size = library.GetCompressedFileSizeW
        get_size.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        get_size.restype = wintypes.DWORD
        high = wintypes.DWORD()
        ctypes.set_last_error(0)
        low = get_size(str(path), ctypes.byref(high))
        if low != 0xFFFFFFFF or ctypes.get_last_error() == 0:
            result["allocated_bytes"] = (high.value << 32) | low
    return result


def container_projection(item):
    config, host = item.get("Config", {}), item.get("HostConfig", {})
    state = item.get("State", {})
    labels = config.get("Labels") or {}
    return {
        "id": item["Id"],
        "name": item["Name"].lstrip("/"),
        "image_id": item["Image"],
        "image_reference": config.get("Image"),
        "status": state.get("Status"),
        "started_at": state.get("StartedAt"),
        "restart_count": item.get("RestartCount"),
        "health": state.get("Health", {}).get("Status", "NOT_CONFIGURED"),
        "logging": host.get("LogConfig"),
        "log_path": item.get("LogPath"),
        "compose_project": labels.get("com.docker.compose.project"),
        "compose_service": labels.get("com.docker.compose.service"),
        "compose_files": labels.get("com.docker.compose.project.config_files"),
        "mounts": [
            {key: m.get(key) for key in ("Type", "Name", "Source", "Destination", "RW")} for m in item.get("Mounts", [])
        ],
        "networks": sorted(item.get("NetworkSettings", {}).get("Networks", {})),
        "configuration_sha256": hashlib.sha256(
            json.dumps({"Config": config, "HostConfig": host}, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def linux_metadata(containers, volumes):
    # Interpolated identifiers must match Docker's restricted identifier grammar.
    # No environment, log contents, model contents or private database rows are read.
    lines = [
        "set -eu",
        "set -o pipefail",
        f"test -d {WSL_ROOT}/containers || exit 3",
        'df -P -B1 /mnt/docker-desktop-disk | tail -n 1 | awk \'{print "FS\\t"$2"\\t"$3"\\t"$4}\'',
    ]
    for volume in volumes:
        name = volume["Name"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
            raise ValueError("Unexpected volume identifier")
        lines.append(f"du -sk '{WSL_ROOT}/volumes/{name}/_data' | awk '{{print \"VOL\\t{name}\\t\"$1*1024}}'")
    for container in containers:
        identity = container["id"]
        if not re.fullmatch(r"[0-9a-f]{64}", identity):
            raise ValueError("Unexpected container identifier")
        # All files in this container's log directories, excluding config metadata.
        directory = f"{WSL_ROOT}/containers/{identity}"
        lines.append(
            f"find '{directory}' -maxdepth 2 -type f \\( -name '*-json.log*' -o -path '*/local-logs/*' \\) -exec stat -c '%s' {{}} \\; | awk '{{s+=$1}} END {{print \"LOG\\t{identity}\\t\"s+0}}'"
        )
    text = command(["wsl", "-d", "docker-desktop", "--exec", "sh", "-c", "\n".join(lines)], timeout=45)
    result = {"filesystem": None, "volumes": {}, "logs": {}}
    for line in text.splitlines():
        fields = line.split("\t")
        if fields[0] == "FS" and len(fields) == 4:
            result["filesystem"] = dict(zip(("capacity_bytes", "used_bytes", "available_bytes"), map(int, fields[1:])))
        elif fields[0] in ("VOL", "LOG") and len(fields) == 3:
            result["volumes" if fields[0] == "VOL" else "logs"][fields[1]] = int(fields[2])
    return result


def growth(current, previous):
    if not previous or previous.get("schema") != current.get("schema"):
        return {"status": "INSUFFICIENT_HISTORY", "rates_bytes_per_day": {}}
    elapsed = current["observed_epoch"] - previous.get("observed_epoch", current["observed_epoch"])
    if elapsed < 60:
        return {"status": "INTERVAL_TOO_SHORT", "rates_bytes_per_day": {}}
    rates = {}
    previous_disks = {entry["path"]: entry for entry in previous.get("virtual_disks", [])}
    for entry in current.get("virtual_disks", []):
        before = previous_disks.get(entry["path"], {}).get("allocated_bytes")
        after = entry.get("allocated_bytes")
        if before is not None and after is not None:
            rates[entry["path"]] = (after - before) * 86400 / elapsed
    for kind in ("volumes", "logs"):
        before_values = (previous.get("linux") or {}).get(kind, {})
        after_values = (current.get("linux") or {}).get(kind, {})
        for identity in before_values.keys() & after_values.keys():
            rates[f"{kind}:{identity}"] = (after_values[identity] - before_values[identity]) * 86400 / elapsed
    return {"status": "OBSERVED_DELTA_NOT_RECLAIMABILITY", "interval_seconds": elapsed, "rates_bytes_per_day": rates}


def collect(previous=None):
    start = time.perf_counter()
    start_cpu = time.process_time()
    info = docker_json("info", "--format", "{{json .}}")
    identities = command(["docker", "ps", "-aq"]).splitlines()
    projected = [container_projection(item) for item in docker_json("inspect", *identities)] if identities else []
    volume_names = command(["docker", "volume", "ls", "-q"]).splitlines()
    volumes = docker_json("volume", "inspect", *volume_names) if volume_names else []
    usage = [json.loads(line) for line in command(["docker", "system", "df", "--format", "{{json .}}"]).splitlines()]
    image_lines = command(["docker", "image", "ls", "--no-trunc", "--format", "{{json .}}"]).splitlines()
    images = [json.loads(line) for line in image_lines]
    local = Path(os.environ.get("LOCALAPPDATA", "C:/Users/Admin/AppData/Local")) / "Docker/wsl"
    disks = [vhdx_metadata(local / "disk/docker_data.vhdx"), vhdx_metadata(local / "main/ext4.vhdx")]
    drive = Path(local.anchor or "/")
    space = shutil.disk_usage(drive)
    report = {
        "schema": "abex.docker.storage.v1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "observed_epoch": time.time(),
        "production_mutated": False,
        "engine_version": info.get("ServerVersion"),
        "docker_root": info.get("DockerRootDir"),
        "default_log_driver": info.get("LoggingDriver"),
        "container_count": info.get("Containers"),
        "running_count": info.get("ContainersRunning"),
        "image_count": info.get("Images"),
        "containers": projected,
        "images": images,
        "docker_usage": usage,
        "virtual_disks": disks,
        "windows_storage": {"capacity_bytes": space.total, "free_bytes": space.free},
        "volumes": [{"name": value["Name"], "driver": value["Driver"]} for value in volumes],
        "recoverable_host_bytes": None,
        "errors": [],
    }
    try:
        report["linux"] = linux_metadata(projected, volumes)
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as error:
        report["linux"] = None
        report["errors"].append(type(error).__name__ + ":Linux metadata unavailable")
    running = {item["name"] for item in projected if item["status"] == "running"}
    warnings = ["BASELINE_CONTAINER_MISSING:" + name for name in sorted(EXPECTED - running)]
    tags = {item.get("Repository", "") + ":" + item.get("Tag", "") for item in images}
    warnings.extend("HISTORICAL_ROLLBACK_IMAGE_MISSING:" + tag for tag in sorted(HISTORICAL_ROLLBACK_TAGS - tags))
    for item in projected:
        policy = item.get("logging") or {}
        if policy.get("Type") == "json-file" and not all(
            policy.get("Config", {}).get(k) for k in ("max-size", "max-file")
        ):
            warnings.append("UNBOUNDED_JSON_LOG:" + item["name"])
        if item["health"] == "unhealthy":
            warnings.append("UNHEALTHY:" + item["name"])
    if space.free / space.total < 0.10:
        warnings.append("WINDOWS_FREE_BELOW_10_PERCENT")
    report["growth"] = growth(report, previous)
    if any(value > 5 * 1024**3 for value in report["growth"]["rates_bytes_per_day"].values()):
        warnings.append("STORAGE_GROWTH_ABOVE_PROVISIONAL_5_GIB_PER_DAY_REVIEW_ONLY")
    report["warnings"] = warnings
    report["process_cpu_seconds"] = time.process_time() - start_cpu
    report["collection_seconds"] = time.perf_counter() - start
    report["status"] = "PARTIAL" if report["errors"] else "OBSERVED"
    return report


def logging_plan(report):
    matches = [item for item in report["containers"] if item["name"] == "orqevia-intelligence-1"]
    if len(matches) != 1:
        raise ValueError("Intelligence identity must be reconciled first")
    item = matches[0]
    return {
        "status": "PREPARED_NOT_APPLIED_RECREATION_REQUIRES_MAINTENANCE",
        "expected_container_id": item["id"],
        "expected_image_id": item["image_id"],
        "expected_configuration_sha256": item["configuration_sha256"],
        "current_log_config": item["logging"],
        "proposed_log_config": LOG_POLICY,
        "composition_owner": item["compose_project"],
        "preserve_all_other_configuration": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--logging-plan", type=Path)
    args = parser.parse_args()
    previous = json.loads(args.previous.read_text(encoding="utf-8-sig")) if args.previous else None
    try:
        report = collect(previous)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        report = {
            "schema": "abex.docker.storage.v1",
            "status": "UNAVAILABLE",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "observed_epoch": time.time(),
            "production_mutated": False,
            "running_count": None,
            "image_count": None,
            "volumes": [],
            "containers": [],
            "warnings": [],
            "collection_seconds": None,
            "errors": [type(error).__name__ + ":Read-only collection unavailable; no raw diagnostics exported"],
            "recoverable_host_bytes": None,
        }
    atomic_json(args.output, report)
    if args.logging_plan and report["status"] != "UNAVAILABLE":
        atomic_json(args.logging_plan, logging_plan(report))
    print(
        json.dumps(
            {
                "running": report["running_count"],
                "images": report["image_count"],
                "volumes": len(report["volumes"]),
                "warnings": report["warnings"],
                "errors": report["errors"],
                "collection_seconds": report["collection_seconds"],
                "recoverable_host_bytes": None,
            }
        )
    )
    return 0 if report["status"] == "OBSERVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
