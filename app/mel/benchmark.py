"""Optional offline MiniLM benchmark. No imports of ONNX/NumPy at module import.

This tool writes a separate candidate and never modifies the retained baseline,
registry assignments, inference configuration, or input corpus. A fresh-process
cold measurement does not imply the operating system's disk cache was flushed.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import time

from .service import ExperimentEvidence

MINILM_SHA256 = "e81857e1b034a003c6dba3ae71271faa3c0ca29f8e0b06505ef2e0e6c35ab0f8"
TOKENIZER_FILES = ("config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "vocab.txt")


def file_digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def load_corpus(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    rows = data.get("chunks", []) if isinstance(data, dict) else data
    if not isinstance(rows, list) or not rows:
        raise ValueError("corpus must contain nonempty JSON records")
    texts = []
    for row in rows:
        text = row.get("text") if isinstance(row, dict) else row
        if not isinstance(text, str) or not text.strip():
            raise ValueError("every corpus record must contain nonempty text")
        texts.append(text)
    return texts


def peak_process_memory() -> int:
    """OS-reported process peak resident/working-set bytes; no GPU claim."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class MemoryCounters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (field, ctypes.c_size_t) for field in (
                    "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                    "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage",
                )
            ]
        counters = MemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise OSError("process peak-memory observation unavailable")
        return int(counters.PeakWorkingSetSize)
    import resource
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def summarize_times(values: list[float], batch_size: int) -> dict:
    if len(values) < 2 or any(not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError("timing needs repeated positive finite observations")
    ordered = sorted(values)
    mean = statistics.mean(values)
    return {
        "mean_ms": mean,
        "p50_ms": statistics.median(values),
        "p95_ms": ordered[math.ceil(len(ordered) * 0.95) - 1],
        "stdev_ms": statistics.stdev(values),
        "min_ms": ordered[0],
        "max_ms": ordered[-1],
        "samples": len(values),
        "throughput_items_per_second": 1000 * batch_size / mean,
    }


def worker(model_dir: Path, expected: str, corpus: Path, repeats: int, threads: int) -> dict:
    start = time.perf_counter()
    cpu_start = time.process_time()
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    # Reuse the production tokenizer, CPU session and preprocessing contract.
    from app.onnx_embedding import OnnxMiniLMEncoder

    texts = load_corpus(corpus)
    startup_peak = peak_process_memory()
    load_start = time.perf_counter()
    encoder = OnnxMiniLMEncoder(model_dir, expected, model_name="all-MiniLM-L6-v2", threads=threads)
    load_ms = (time.perf_counter() - load_start) * 1000
    cold_start = time.perf_counter()
    encoder.encode(texts[:1], batch_size=1)
    cold_ms = (time.perf_counter() - cold_start) * 1000
    timing = {}
    for batch_size in (1, 8):
        # Warm-up is recorded as excluded overhead, never substituted for cold.
        batch = [texts[i % len(texts)] for i in range(batch_size)]
        for _ in range(3):
            encoder.encode(batch, batch_size=batch_size)
        observed = []
        for iteration in range(repeats):
            batch = [texts[(iteration * batch_size + i) % len(texts)] for i in range(batch_size)]
            before = time.perf_counter()
            encoder.encode(batch, batch_size=batch_size)
            observed.append((time.perf_counter() - before) * 1000)
        timing[f"batch_{batch_size}"] = observed
    # First-sentence queries are explicitly a baseline-agreement proxy, not labels.
    queries = [next((line.strip() for line in text.splitlines() if line.strip()), text) for text in texts]
    vectors = encoder.encode(texts + queries, batch_size=8)
    return {
        "load_ms": load_ms,
        "cold_first_batch_ms": cold_ms,
        "peak_process_memory_bytes": peak_process_memory(),
        "startup_peak_memory_bytes": startup_peak,
        "artifact_bytes": (model_dir / "model.onnx").stat().st_size,
        "cpu_seconds": time.process_time() - cpu_start,
        "wall_seconds": time.perf_counter() - start,
        **timing,
        "vectors": vectors.tolist(),
        "provider": encoder.provider,
    }


def aggregate(workers: list[dict]) -> dict:
    result = {}
    for field in ("load_ms", "cold_first_batch_ms", "cpu_seconds", "wall_seconds"):
        result[field] = statistics.mean(item[field] for item in workers)
    for field in ("peak_process_memory_bytes", "startup_peak_memory_bytes", "artifact_bytes"):
        result[field] = max(item[field] for item in workers)
    for batch in (1, 8):
        result[f"batch_{batch}"] = summarize_times([value for item in workers for value in item[f"batch_{batch}"]], batch)
    return result


def quality_summary(baseline_vectors, candidate_vectors, document_count: int) -> dict:
    import numpy as np

    baseline = np.asarray(baseline_vectors, dtype=np.float64)
    candidate = np.asarray(candidate_vectors, dtype=np.float64)
    if baseline.shape != candidate.shape or baseline.shape != (2 * document_count, 384):
        raise ValueError("embedding dimensions do not match the retained MiniLM contract")
    if not np.isfinite(baseline).all() or not np.isfinite(candidate).all():
        raise ValueError("non-finite benchmark output")
    denominator = np.linalg.norm(baseline, axis=1) * np.linalg.norm(candidate, axis=1)
    if (denominator <= 0).any():
        raise ValueError("zero-norm embedding output")
    cosine = np.clip(np.sum(baseline * candidate, axis=1) / denominator, -1, 1)
    base_ranks = np.argmax(baseline[document_count:] @ baseline[:document_count].T, axis=1)
    candidate_ranks = np.argmax(candidate[document_count:] @ candidate[:document_count].T, axis=1)
    return {
        "mean_cosine": float(np.mean(cosine)),
        "min_cosine": float(np.min(cosine)),
        "max_absolute_error": float(np.max(np.abs(baseline - candidate))),
        "top1_agreement": float(np.mean(base_ranks == candidate_ranks)),
        "critical_task_quality_validated": False,
        "task_quality_loss": None,
        "task_quality_evidence_sha256": None,
    }


def quantize_baseline(model_dir: Path, candidate: Path) -> dict:
    # The caller verifies this exact retained graph before ONNX parsing.
    from onnxruntime.quantization import QuantType, quantize_dynamic
    import onnx

    start = time.perf_counter()
    cpu_start = time.process_time()
    candidate.mkdir(parents=True, exist_ok=False)
    for filename in TOKENIZER_FILES:
        shutil.copyfile(model_dir / filename, candidate / filename)
    graph = onnx.load(str(model_dir / "model.onnx"), load_external_data=False)
    if any(item.data_location == onnx.TensorProto.EXTERNAL for item in graph.graph.initializer):
        raise ValueError("external tensor loading is unsupported by this benchmark")
    onnx.checker.check_model(graph)
    baseline_elements = sum(math.prod(tensor.dims) for tensor in graph.graph.initializer)
    quantize_dynamic(
        str(model_dir / "model.onnx"), str(candidate / "model.onnx"),
        op_types_to_quantize=["MatMul"], weight_type=QuantType.QInt8,
        per_channel=True, reduce_range=False,
    )
    transformed = onnx.load(str(candidate / "model.onnx"), load_external_data=False)
    onnx.checker.check_model(transformed)
    operators = {}
    for node in transformed.graph.node:
        operators[node.op_type] = operators.get(node.op_type, 0) + 1
    if not operators.get("MatMulInteger"):
        raise ValueError("quantization produced no integer MatMul operators")
    return {
        "method": "ONNX Runtime dynamic per-channel QInt8 MatMul weights",
        "wall_seconds": time.perf_counter() - start,
        "cpu_seconds": time.process_time() - cpu_start,
        "peak_process_memory_bytes": peak_process_memory(),
        "baseline_initializer_elements": baseline_elements,
        "initializer_elements_are_not_a_verified_trainable_parameter_count": True,
        "candidate_operators": operators,
        "tokenizer_file_sha256": {filename: file_digest(candidate / filename) for filename in TOKENIZER_FILES},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workload-kind", choices=["controlled_fixture", "local_corpus"], default="controlled_fixture")
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--repeats", type=int, default=40)
    parser.add_argument("--process-runs", type=int, default=3)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--expected-sha256", default=MINILM_SHA256, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.repeats < 2 or args.process_runs < 2 or not 1 <= args.threads <= 8:
        parser.error("repeated observations and a production-compatible thread count are required")
    if args.worker:
        print(json.dumps(worker(args.model_dir, args.expected_sha256, args.corpus, args.repeats, args.threads), allow_nan=False))
        return 0
    if args.output_dir.exists():
        parser.error("output directory already exists; preserve earlier benchmark evidence")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    model_dir = args.model_dir.resolve()
    if args.expected_sha256 != MINILM_SHA256 or file_digest(model_dir / "model.onnx") != MINILM_SHA256:
        parser.error("this benchmark supports only the reviewed retained MiniLM baseline digest")
    texts = load_corpus(args.corpus)
    args.output_dir.mkdir(parents=True)
    # Freeze input privately for the workers; no text appears in the public receipt.
    workload = args.output_dir / "private-workload.json"
    workload.write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
    candidate_dir = args.output_dir / "candidate"
    preparation = quantize_baseline(model_dir, candidate_dir)
    candidate_sha = file_digest(candidate_dir / "model.onnx")
    workers = {"baseline": [], "candidate": []}
    for process_run in range(args.process_runs):
        order = ("baseline", "candidate") if process_run % 2 == 0 else ("candidate", "baseline")
        for label in order:
            directory = model_dir if label == "baseline" else candidate_dir
            digest = MINILM_SHA256 if label == "baseline" else candidate_sha
            command = [sys.executable, "-B", "-m", "app.mel.benchmark", "--worker", "--model-dir", str(directory), "--expected-sha256", digest, "--corpus", str(workload), "--output-dir", str(args.output_dir), "--source-revision", args.source_revision, "--repeats", str(args.repeats), "--threads", str(args.threads)]
            observed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
            if observed.returncode:
                (args.output_dir / f"worker-{label}-{process_run}-error.log").write_text(observed.stderr, encoding="utf-8")
                raise RuntimeError(f"{label} benchmark worker failed; private diagnostic retained")
            workers[label].append(json.loads(observed.stdout))
            print(f"Measured {label} process {process_run + 1}/{args.process_runs}", file=sys.stderr)
    quality = quality_summary(workers["baseline"][0]["vectors"], workers["candidate"][0]["vectors"], len(texts))
    if file_digest(model_dir / "model.onnx") != MINILM_SHA256:
        raise ValueError("retained baseline changed during benchmarking")
    from .inventory import runtime_inventory
    inventory = runtime_inventory()
    evidence = {
        "schema_version": "1.0", "model_id": "all-MiniLM-L6-v2",
        "technique": "onnx_dynamic_int8", "baseline_sha256": MINILM_SHA256,
        "candidate_sha256": candidate_sha,
        "measured_at": datetime.now(timezone.utc).isoformat(), "source_revision": args.source_revision,
        "workload": {"sha256": file_digest(workload), "sample_count": len(texts), "kind": args.workload_kind, "representative": False, "labeled_sample_count": 0},
        "hardware": {"platform": platform.system(), "processor": platform.processor(), "logical_cpus": os.cpu_count(), "threads": args.threads, "provider": workers["baseline"][0]["provider"], "packages": inventory["packages"]},
        "measurements": {label: aggregate(value) for label, value in workers.items()},
        "quality": quality, "compatible": True, "preparation": preparation,
    }
    ExperimentEvidence.parse(evidence)
    for values in workers.values():
        for item in values:
            item.pop("vectors")
    report = {
        "evidence": evidence, "raw_measurements": workers,
        "decision": "retain_baseline", "operational_quality": "NOT_VERIFIED",
        "method": {"fresh_process_runs_per_artifact": args.process_runs, "warmup_calls_per_batch": 3, "timed_repeats_per_batch_per_process": args.repeats, "timing_includes_tokenization": True, "cold_definition": "fresh process/session and first batch; OS disk cache retained", "memory_definition": "OS process peak working set/RSS, maximum across separate workers", "query_definition": "First nonempty line of each local document; agreement proxy only, no relevance labels", "worker_order": "alternating artifact order by process run", "shared_host_other_workloads_controlled": False, "physical_energy_or_dollar_cost": "NOT_MEASURED", "private_input": "private-workload.json is local private input; never publish or commit"},
    }
    (args.output_dir / "benchmark.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"decision": "retain_baseline", "operational_quality": "NOT_VERIFIED", "output": str(args.output_dir / "benchmark.json")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
