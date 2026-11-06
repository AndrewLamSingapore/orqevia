"""Profile real PIF methods against existing optimized NumPy, using fixture state.

No model calls, production writes, source changes, downloads or worker services.
"""

from __future__ import annotations

import os

for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "1"

import argparse
import cProfile
import hashlib
import io
import json
import math
from pathlib import Path
import platform
import pstats
import random
import statistics
import sys
import tempfile
import threading
import time

import psutil
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.pif.core import MarkovModel, stationary_distribution, simulate  # noqa:E402
from app.pif.service import PIFService  # noqa:E402


def fixture(size):
    rng = random.Random(20261029 + size)
    states = tuple(f"s{i}" for i in range(size))
    rows = []
    for _ in states:
        row = [rng.random() + 0.05 for _ in states]
        total = math.fsum(row)
        rows.append(tuple(x / total for x in row))
    return MarkovModel(
        states,
        tuple(rows),
        tuple(tuple(1 for _ in states) for _ in states),
        (),
        0.0,
        None,
        None,
        hashlib.sha256(f"fixture:{size}".encode()).hexdigest(),
        ("fixture",),
        size,
        tuple((a, b) for a in states for b in states),
    )


def numpy_forecast(model, start, steps):
    current = np.asarray(model.initial(start), dtype=np.float64)
    power = np.asarray(model.matrix, dtype=np.float64)
    exponent = steps
    while exponent:
        if exponent & 1:
            current = current @ power
            current = current / current.sum()
        exponent >>= 1
        if exponent:
            power = power @ power
            power = power / power.sum(axis=1, keepdims=True)
    return dict(zip(model.states, current.tolist()))


def stats(values):
    values = sorted(values)
    return {
        "n": len(values),
        "median_seconds": statistics.median(values),
        "p95_seconds": values[max(0, math.ceil(0.95 * len(values)) - 1)],
        "variance_seconds_squared": statistics.variance(values) if len(values) > 1 else None,
        "operations_per_second": len(values) / sum(values),
    }


def measure(function, repeats=21):
    for _ in range(3):
        function()
    process = psutil.Process()
    rss = [process.memory_info().rss]
    available = [psutil.virtual_memory().available]
    stop = threading.Event()

    def sample():
        while not stop.wait(0.01):
            rss.append(process.memory_info().rss)
            available.append(psutil.virtual_memory().available)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    times = []
    cpu = time.process_time()
    try:
        for _ in range(repeats):
            start = time.perf_counter()
            function()
            times.append(time.perf_counter() - start)
        used_cpu = time.process_time() - cpu
    finally:
        stop.set()
        sampler.join()
    return {
        **stats(times),
        "process_cpu_seconds": used_cpu,
        "raw_seconds": times,
        "average_cpu_core_equivalents": used_cpu / sum(times),
        "sampled_rss_peak_bytes": max(rss),
        "memory_samples": len(rss),
        "available_memory_min_bytes": min(available),
        "memory_sampling_seconds": 0.01,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    process = psutil.Process()
    try:
        process.cpu_affinity(process.cpu_affinity()[:2])
    except (AttributeError, psutil.Error):
        pass
    report = {
        "scope": "FIXTURE_PIF_KERNEL_AND_PERSISTED_SERVICE_BELOW_HTTP_AUTH_NOT_PRODUCTION_FORECAST_QUALITY",
        "source_revision": "f37673b4ce618cc7cd672c987594f849d9985f02",
        "platform": platform.platform(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "blas_threads": 1,
        "cases": [],
        "production_mutated": False,
        "synthetic_evidence_only": True,
    }
    original = MarkovModel.forecast
    for size, steps in [(8, 16), (24, 64), (48, 256)]:
        model = fixture(size)
        expected = original(model, "s0", steps)
        candidate = numpy_forecast(model, "s0", steps)
        error = max(abs(expected[k] - candidate[k]) for k in expected)
        assert error < 1e-10
        entry = {
            "states": size,
            "steps": steps,
            "absolute_error": error,
            "python_method": measure(lambda: original(model, "s0", steps)),
            "numpy_method": measure(lambda: numpy_forecast(model, "s0", steps)),
        }
        with tempfile.TemporaryDirectory(prefix="pif-benchmark-") as folder:
            service = PIFService(
                Path(folder) / "registry.db",
                enabled=True,
                tenant_id="fixture:benchmark",
                min_transitions=1,
                min_source_transitions=1,
            )
            service.store.save_model(
                service.tenant_id,
                "fixture",
                model,
                {
                    "deployment_mode": "SHADOW_ONLY",
                    "min_transitions": 1,
                    "min_source_transitions": 1,
                    "evaluation": {"scope": "SYNTHETIC_BENCHMARK_ONLY"},
                    "production_quality_validated": False,
                },
            )

            def call():
                result = service.forecast_state("s0", steps=steps, model_id="fixture")
                assert result["status"] == "SHADOW" and result["grants_execution_authority"] is False
                assert max(abs(result["data"]["probabilities"][k] - expected[k]) for k in expected) < 1e-10
                return result

            entry["python_service"] = measure(call)
            try:
                MarkovModel.forecast = numpy_forecast
                entry["numpy_service"] = measure(call)
            finally:
                MarkovModel.forecast = original
            profiler = cProfile.Profile()
            profiler.enable()
            call()
            profiler.disable()
            stream = io.StringIO()
            pstats.Stats(profiler, stream=stream).sort_stats("cumulative").print_stats(12)
            entry["profile"] = stream.getvalue()
        report["cases"].append(entry)
    model = fixture(16)
    report["other_baselines"] = {
        "stationary_16": measure(lambda: stationary_distribution(model), repeats=11),
        "simulation_8_states_32_steps_100_samples": measure(
            lambda: simulate(fixture(8), "s0", steps=32, samples=100, seed=42), repeats=11
        ),
        "sha256_1mib": measure(lambda: hashlib.sha256(b"x" * 1048576).digest()),
        "json_32k_values": measure(lambda: json.dumps(list(range(32768)), separators=(",", ":"))),
    }
    report["process_peak_scope"] = "RSS_AFTER_ALL_CASES_NOT_PER_VARIANT_ALLOCATION"
    report["final_rss_bytes"] = process.memory_info().rss
    (args.output / "python-numpy-baseline.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "cases": [
                    {
                        k: v
                        for k, v in c.items()
                        if k not in ["profile"] and not k.endswith("_method") and not k.endswith("_service")
                    }
                    | {
                        k: {x: v[x] for x in ["median_seconds", "p95_seconds", "n"]}
                        for k, v in c.items()
                        if k.endswith("_method") or k.endswith("_service")
                    }
                    for c in report["cases"]
                ],
                "final_rss_bytes": report["final_rss_bytes"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
