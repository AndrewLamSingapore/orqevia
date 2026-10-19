"""Export the cached MiniLM sentence encoder to a pinned local ONNX artifact."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    output = args.output.resolve()
    model_path = output / "model.onnx"
    if model_path.exists() and not args.force:
        raise SystemExit(f"refusing to overwrite existing artifact: {model_path}")
    output.mkdir(parents=True, exist_ok=True)

    from huggingface_hub import snapshot_download

    snapshot = Path(
        snapshot_download(
            MODEL,
            revision=args.revision,
            local_files_only=True,
        )
    )
    environment = dict(os.environ)
    environment["HF_HUB_OFFLINE"] = "1"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "optimum.exporters.onnx",
            "-m",
            str(snapshot),
            "--library-name",
            "sentence_transformers",
            "--task",
            "sentence-similarity",
            "--monolith",
            str(output),
        ],
        check=True,
        env=environment,
    )
    required = {
        "model.onnx",
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
    }
    missing = sorted(name for name in required if not (output / name).is_file())
    if missing:
        raise SystemExit("incomplete ONNX export: " + ",".join(missing))

    manifest = {
        "schema_version": "orqevia.minilm-onnx.v1",
        "source_model": MODEL,
        "source_revision": args.revision,
        "library": "sentence_transformers",
        "task": "sentence-similarity",
        "opset": 18,
        "dimensions": 384,
        "max_tokens": 256,
        "model_file": "model.onnx",
        "model_sha256": digest(model_path),
        "model_bytes": model_path.stat().st_size,
        "exported_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    (output / "onnx-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
