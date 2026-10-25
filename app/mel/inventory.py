"""Lightweight inventory without importing an inference framework or downloading models."""

from __future__ import annotations

from importlib import metadata
import os
from pathlib import Path
import platform
import shutil


def runtime_inventory() -> dict:
    packages = {}
    for name in ("onnxruntime", "onnxruntime-gpu", "onnx", "numpy", "torch", "transformers"):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = None
    model_dir = os.getenv("ORQEVIA_MEL_MODEL_DIR", "").strip()
    graph = Path(model_dir) / "model.onnx" if model_dir else None
    return {
        "platform": platform.system(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "logical_cpus": os.cpu_count(),
        "processor": platform.processor(),
        "packages": packages,
        "local_onnx_artifact": {
            "configured": bool(model_dir),
            "available": bool(graph and graph.is_file()),
            "bytes": graph.stat().st_size if graph and graph.is_file() else None,
            "integrity": "NOT_VERIFIED_BY_METADATA_INVENTORY",
        },
        "acceleration": {
            "nvidia_cli_present": shutil.which("nvidia-smi") is not None,
            "nvidia_2_4": "NOT_VERIFIED",
            "reason": "A device, compatible graph, sparse kernel and representative benchmark are all required.",
        },
        "compatibility": [
            {
                "technique": "onnx_dynamic_int8",
                "status": "BENCHMARK_REQUIRED",
                "scope": "Reviewed local MiniLM CPU graph only",
            },
            {
                "technique": "fp16_bf16",
                "status": "NOT_VERIFIED",
                "scope": "No compatible accelerated execution benchmark",
            },
            {
                "technique": "int4",
                "status": "NOT_VERIFIED",
                "scope": "Model/operator and kernel compatibility not established",
            },
            {
                "technique": "structured_pruning",
                "status": "NOT_VERIFIED",
                "scope": "No recovery training or task-quality evidence",
            },
            {
                "technique": "unstructured_pruning",
                "status": "NOT_VERIFIED",
                "scope": "No sparse-kernel performance evidence",
            },
            {
                "technique": "remote_api_weight_modification",
                "status": "NOT_APPLICABLE",
                "scope": "Externally hosted weights are not controlled locally",
            },
        ],
    }
