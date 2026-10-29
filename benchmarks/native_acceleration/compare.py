"""Compare the actual candidate with pinned main in one bounded process."""

from __future__ import annotations

import os

for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[name] = "1"

import argparse
from importlib.metadata import version
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.pif import core
from app.pif.service import PIFService
from benchmarks.native_acceleration.baseline import fixture, measure, stats
import psutil

REVISION = "f37673b4ce618cc7cd672c987594f849d9985f02"


def startup():
    program = """
import sys,time,psutil
sys.path.insert(0,sys.argv[1])
start=time.perf_counter()
import app.pif.core
if sys.argv[2]=='numpy':
 import app.pif.numpy_backend
 import numpy
print(time.perf_counter()-start,psutil.Process().memory_info().rss)
"""
    result = {}
    for variant in ("python", "numpy"):
        times, imports, rss = [], [], []
        for _ in range(7):
            start = time.perf_counter()
            raw = subprocess.check_output([sys.executable, "-I", "-c", program, str(ROOT), variant], text=True)
            times.append(time.perf_counter() - start)
            seconds, memory = raw.split()
            imports.append(float(seconds))
            rss.append(int(memory))
        result[variant] = {
            "fresh_process_wall": stats(times),
            "module_import": stats(imports),
            "rss_after_import_peak_bytes": max(rss),
            "raw_import_seconds": imports,
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reference = ROOT / "benchmarks/native_acceleration/reference_core.py"
    source = (
        reference.read_bytes()
        if reference.exists()
        else subprocess.check_output(["git", "show", REVISION + ":app/pif/core.py"], cwd=ROOT)
    )
    module = type(sys)("pif_pinned_reference")
    sys.modules[module.__name__] = module
    exec(compile(source, "pinned_core.py", "exec"), module.__dict__)
    process = psutil.Process()
    try:
        process.cpu_affinity(process.cpu_affinity()[:2])
    except (AttributeError, psutil.Error):
        pass
    report = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "numpy": version("numpy"),
        "psutil": version("psutil"),
        "baseline": REVISION,
        "scope": "SYNTHETIC_FIXTURE_NOT_PRODUCTION",
        "cases": {},
        "production_mutated": False,
    }
    rss = []
    for size, steps in [(8, 16), (24, 64), (48, 256)]:
        model = fixture(size)
        old_model = module.MarkovModel.from_dict(model.as_dict())
        oracle = old_model.forecast("s0", steps)
        entry = {}
        with tempfile.TemporaryDirectory(prefix="pif-compare-") as folder:
            service = PIFService(
                Path(folder) / "registry.db",
                enabled=True,
                tenant_id="fixture:compare",
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
                    "evaluation": {"scope": "SYNTHETIC_ONLY"},
                    "production_quality_validated": False,
                },
            )
            original = core.MarkovModel.forecast
            for variant in ("baseline", "candidate"):
                os.environ["ORQEVIA_PIF_NUMPY_ENABLED"] = "1" if variant == "candidate" else "0"
                core.MarkovModel.forecast = original if variant == "candidate" else module.MarkovModel.forecast

                def call():
                    result = service.forecast_state("s0", steps=steps, model_id="fixture")
                    assert result["status"] == "SHADOW" and not result["grants_execution_authority"]
                    assert max(abs(result["data"]["probabilities"][k] - oracle[k]) for k in oracle) < 1e-12

                entry[variant] = measure(call)
                rss.append(process.memory_info().rss)
            core.MarkovModel.forecast = original
        report["cases"][f"forecast_service_{size}"] = entry
    os.environ["ORQEVIA_PIF_NUMPY_ENABLED"] = "0"
    for name, old_call, new_call in [
        (
            "stationary_16",
            lambda: module.stationary_distribution(fixture(16)),
            lambda: core.stationary_distribution(fixture(16)),
        ),
        (
            "simulation_8x32x100",
            lambda: module.simulate(fixture(8), "s0", steps=32, samples=100, seed=42),
            lambda: core.simulate(fixture(8), "s0", steps=32, samples=100, seed=42),
        ),
    ]:
        assert old_call() == new_call()
        report["cases"][name] = {
            "baseline": measure(old_call),
            "candidate": measure(new_call),
            "exact_output_match": True,
        }
    report["observed_rss_peak_bytes"] = max(rss)
    report["rss_scope"] = "SAMPLED_AFTER_VARIANTS_NOT_ALLOCATION_PEAK"
    report["available_memory_bytes"] = psutil.virtual_memory().available
    report["startup"] = startup()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                name: {variant: data["median_seconds"] for variant, data in case.items() if isinstance(data, dict)}
                for name, case in report["cases"].items()
            }
        )
    )


if __name__ == "__main__":
    main()
