"""GitHub-hosted, off-ABEX Ollama memory evidence for one synthetic A18 trial.

Run on the runner host, never inside PRIME. The Docker socket stays outside
PRIME; only the atomically replaced, non-secret /dev/shm receipt directory is
mounted read-only into its disposable container. No ABEX sensor is represented.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request
import uuid


MIB = 1024 * 1024
MODEL = os.getenv("PRIME_OFFHOST_MODEL", os.getenv("A18_OFFHOST_MODEL", "gemma3:1b"))
if MODEL not in {"gemma3:1b", "qwen3:1.7b", "qwen2.5:1.5b", "qwen2.5:3b"}:
    raise RuntimeError("unsupported bounded off-host model")
SCHEMA = "prime.backend-memory.v1"
PROFILE_SCHEMA = "abex.measured-compute.v1"
RESERVE_MIB = 2048
CONTEXT_TOKENS = 2048
OUTPUT_TOKENS = 256
_DIGEST = re.compile(r"(?:sha256:)?[0-9a-f]{64}\Z")


class EvidenceError(RuntimeError):
    pass


def _runner_only(directory: Path) -> None:
    if (sys.platform != "linux" or os.getenv("GITHUB_ACTIONS") != "true"
            or os.getenv("RUNNER_OS") != "Linux"
            or os.getenv("RUNNER_ENVIRONMENT") != "github-hosted"):
        raise EvidenceError("requires an isolated GitHub-hosted Linux runner")
    resolved = directory.resolve()
    if (resolved.parent != Path("/dev/shm") or
            not resolved.name.startswith(("prime-a18-", "prime-a19-"))):
        raise EvidenceError("telemetry must remain in dedicated runner tmpfs")
    if not Path("/sys/fs/cgroup/cgroup.controllers").is_file():
        raise EvidenceError("cgroup v2 is required for complete memory scope")


def _docker_identity(container: str) -> tuple[str, int, str, int]:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", container):
        raise EvidenceError("invalid container name")
    result = subprocess.run(
        ["docker", "inspect", "--format",
         "{{.Id}}|{{.State.Pid}}|{{.State.StartedAt}}|{{.HostConfig.Memory}}|{{.State.Running}}",
         container], capture_output=True, text=True, timeout=5, check=False,
    )
    if result.returncode != 0:
        raise EvidenceError("backend Docker identity unavailable")
    parts = result.stdout.strip().split("|")
    if len(parts) != 5 or parts[4] != "true" or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
        raise EvidenceError("backend Docker identity incomplete")
    try:
        pid, hard_limit = int(parts[1]), int(parts[3])
    except ValueError as exc:
        raise EvidenceError("backend PID or memory cap invalid") from exc
    if pid <= 1 or hard_limit < 4 * 1024 * MIB or not parts[2]:
        raise EvidenceError("backend requires a running, bounded Docker memory cap")
    return parts[0], pid, parts[2], hard_limit


def _require_loopback_binding(container: str) -> None:
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{json .HostConfig.PortBindings}}", container],
        capture_output=True, text=True, timeout=5, check=False,
    )
    if result.returncode != 0:
        raise EvidenceError("backend endpoint binding unavailable")
    try:
        bindings = json.loads(result.stdout)
    except ValueError as exc:
        raise EvidenceError("backend endpoint binding malformed") from exc
    if bindings != {"11434/tcp": [{"HostIp": "127.0.0.1", "HostPort": "11434"}]}:
        raise EvidenceError("backend endpoint is not uniquely bound to runner loopback")


def _bytes_file(path: Path) -> int | None:
    raw = path.read_text(encoding="ascii").strip()
    if raw == "max":
        return None
    value = int(raw)
    if value < 0:
        raise EvidenceError("negative cgroup memory value")
    return value


def _meminfo(path: Path = Path("/proc/meminfo")) -> tuple[int, int]:
    values = {}
    for line in path.read_text(encoding="ascii").splitlines():
        if line.startswith(("MemTotal:", "MemAvailable:")):
            key, amount, unit = line.split()
            if unit != "kB":
                raise EvidenceError("unexpected VM memory units")
            values[key[:-1]] = int(amount) * 1024
    total, available = values.get("MemTotal"), values.get("MemAvailable")
    if not total or available is None or not 0 <= available <= total:
        raise EvidenceError("VM memory scope unavailable")
    return total, available


def _scope(pid: int, hard_limit: int, *,
           proc_root: Path = Path("/proc"), cgroup_root: Path = Path("/sys/fs/cgroup")) -> tuple[int, int, int]:
    lines = (proc_root / str(pid) / "cgroup").read_text(encoding="ascii").splitlines()
    unified = [line[3:] for line in lines if line.startswith("0::/")]
    if len(unified) != 1:
        raise EvidenceError("backend unified cgroup is unavailable")
    root = cgroup_root.resolve()
    leaf = (root / unified[0].lstrip("/")).resolve()
    if not leaf.is_relative_to(root) or leaf == root:
        raise EvidenceError("backend cgroup scope invalid")
    vm_total, vm_available = _meminfo(proc_root / "meminfo")
    capacity, available = vm_total, vm_available
    found_docker_cap = False
    node = leaf
    while True:
        max_path, current_path = node / "memory.max", node / "memory.current"
        # cgroup v2's hierarchy root can omit memory files. The host VM is
        # still bounded above by /proc/meminfo; no non-root scope may be skipped.
        if node == root and not max_path.exists() and not current_path.exists():
            pass
        else:
            if not max_path.is_file() or not current_path.is_file():
                raise EvidenceError("cgroup memory scope incomplete")
            bound = _bytes_file(max_path)
            used = _bytes_file(current_path)
            if used is None:
                raise EvidenceError("cgroup current memory unavailable")
            if bound is not None:
                if used > bound:
                    raise EvidenceError("cgroup memory exceeds bound")
                capacity = min(capacity, bound)
                available = min(available, bound - used)
                found_docker_cap |= bound == hard_limit
        if node == root:
            break
        node = node.parent
    if not found_docker_cap or capacity < 4 * 1024 * MIB or available < 0:
        raise EvidenceError("Docker/ancestor/VM effective memory scope incomplete")
    peak = _bytes_file(leaf / "memory.peak")
    if peak is None or peak <= 0 or peak > hard_limit:
        raise EvidenceError("backend cgroup peak unavailable")
    return capacity, available, peak


def _backend(container: str) -> dict:
    identity = _docker_identity(container)
    capacity, available, peak = _scope(identity[1], identity[3])
    if _docker_identity(container) != identity:
        raise EvidenceError("backend restarted during observation")
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[0-9a-f-]{36}", boot_id):
        raise EvidenceError("VM boot identity unavailable")
    return {"instance": identity[0] + "@" + identity[2], "boot_id": boot_id,
            "capacity_mib": capacity // MIB, "available_mib": available // MIB,
            "peak_mib": math.ceil(peak / MIB), "hard_cap_mib": identity[3] // MIB}


def _api(endpoint: str, path: str, payload: dict | None = None) -> dict:
    if endpoint != "http://127.0.0.1:11434":
        raise EvidenceError("only the runner loopback Ollama endpoint is allowed")
    raw = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    request = urllib.request.Request(endpoint + path, data=raw,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=45) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise EvidenceError("Ollama metadata malformed")
    return value


def _model_identity(endpoint: str) -> tuple[str, str]:
    version = _api(endpoint, "/api/version").get("version")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9A-Za-z.+-]{1,40}", version):
        raise EvidenceError("Ollama runtime version unavailable")
    models = _api(endpoint, "/api/tags").get("models")
    if not isinstance(models, list):
        raise EvidenceError("Ollama model inventory unavailable")
    matches = [row.get("digest") for row in models
               if isinstance(row, dict) and row.get("name") == MODEL]
    if len(matches) != 1 or not isinstance(matches[0], str) or not _DIGEST.fullmatch(matches[0]):
        raise EvidenceError("unique immutable model digest unavailable")
    return version, matches[0].removeprefix("sha256:")


def _atomic_json(path: Path, value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        temp.chmod(0o644)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return hashlib.sha256(raw).hexdigest()


def _model_resident(endpoint: str) -> bool:
    loaded = _api(endpoint, "/api/ps").get("models")
    if not isinstance(loaded, list) or any(
            not isinstance(row, dict) or not isinstance(row.get("name"), str)
            for row in loaded):
        raise EvidenceError("loaded-model inventory unavailable")
    return any(row["name"] == MODEL for row in loaded)


def _require_calibration_unloaded(endpoint: str) -> None:
    if not _model_resident(endpoint):
        return
    response = _api(endpoint, "/api/generate", {
        "model": MODEL, "prompt": "", "stream": False, "keep_alive": 0,
    })
    if response.get("done") is not True:
        raise EvidenceError("explicit calibration unload did not complete")
    # Bounded observation, never an unbounded retry or admission bypass.
    for _ in range(40):
        if not _model_resident(endpoint):
            return
        time.sleep(0.25)
    raise EvidenceError("calibration model did not unload")


def prepare(container: str, directory: Path, endpoint: str) -> dict:
    _runner_only(directory)
    if endpoint != "http://127.0.0.1:11434":
        raise EvidenceError("only runner-loopback Ollama endpoint is allowed")
    _require_loopback_binding(container)
    directory.mkdir(mode=0o755, exist_ok=False)
    first = _backend(container)
    version, digest = _model_identity(endpoint)
    # Exactly one bounded synthetic calibration; not an A18 task or PASS.
    response = _api(endpoint, "/api/generate", {
        "model": MODEL, "prompt": "synthetic runner memory calibration",
        # Release the calibration model before the queue reserves its full
        # measured demand. Otherwise resident memory is counted twice.
        "stream": False, "keep_alive": 0,
        "options": {"num_ctx": CONTEXT_TOKENS, "num_predict": OUTPUT_TOKENS},
    })
    if response.get("done") is not True:
        raise EvidenceError("calibration did not complete")
    _require_calibration_unloaded(endpoint)
    second = _backend(container)
    if (first["instance"], first["boot_id"]) != (second["instance"], second["boot_id"]):
        raise EvidenceError("backend restarted during calibration")
    if _model_identity(endpoint) != (version, digest):
        raise EvidenceError("model or runtime changed during calibration")
    observed = second["peak_mib"]
    margin = max(256, math.ceil(observed / 4))
    demand = observed + margin
    if demand > second["hard_cap_mib"] - RESERVE_MIB:
        raise EvidenceError("measured model demand lacks enforced memory reserve")
    profile = {
        "schema": PROFILE_SCHEMA, "normal_concurrency": 1,
        "minimum_available_mib": RESERVE_MIB,
        "context_tokens": CONTEXT_TOKENS, "output_limit": OUTPUT_TOKENS,
        "runtime_version": version,
        "models": {MODEL: {"digest": digest, "peak_mib": demand}},
        "measurement": {"kind": "cgroup_v2_memory_peak_one_synthetic_calibration",
                        "observed_mib": observed, "margin_mib": margin,
                        "backend_instance": second["instance"],
                        "boot_id": second["boot_id"], "hard_cap_mib": second["hard_cap_mib"]},
    }
    sha = _atomic_json(directory / "profile.json", profile)
    return {"profile_sha256": sha, "measured_peak_mib": observed,
            "reserved_peak_mib": demand, "model_digest": digest,
            "backend_instance": second["instance"]}


def collect(container: str, directory: Path, endpoint: str, seconds: int) -> None:
    _runner_only(directory)
    if endpoint != "http://127.0.0.1:11434":
        raise EvidenceError("only runner-loopback Ollama endpoint is allowed")
    _require_loopback_binding(container)
    if not directory.is_dir() or not (directory / "profile.json").is_file():
        raise EvidenceError("measured profile missing")
    if not 1 <= seconds <= 180:
        raise EvidenceError("collector duration must be bounded")
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        sample = _backend(container)
        receipt = {"schema": SCHEMA, "endpoint": endpoint,
                   "instance": sample["instance"], "boot_id": sample["boot_id"],
                   "scope_complete": True, "capacity_mib": sample["capacity_mib"],
                   "available_mib": sample["available_mib"],
                   "captured_at": time.time()}
        _atomic_json(directory / "backend-memory.json", receipt)
        time.sleep(0.4)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "collect"))
    parser.add_argument("--container", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--seconds", type=int, default=90)
    args = parser.parse_args()
    try:
        if args.mode == "prepare":
            print(json.dumps(prepare(args.container, args.directory, args.endpoint), sort_keys=True))
        else:
            collect(args.container, args.directory, args.endpoint, args.seconds)
    except (EvidenceError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise SystemExit("off-host telemetry unavailable: " + str(exc)) from None


if __name__ == "__main__":
    main()
