"""Repack the upstream MiT wheel with research-only requirements removed.

The upstream wheel declares its complete research environment as mandatory
requirements. ORQEVIA installs the upstream code and priming assets but uses its
own inference, storage and security stack. This tool removes only the
``Requires-Dist`` metadata lines and rebuilds the wheel RECORD, leaving the
upstream package files and version unchanged.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import zipfile
from pathlib import Path


def _record_hash(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def repack(source: Path, output: Path) -> None:
    records: list[tuple[str, str, int]] = []
    record_name = ""
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename.endswith(".dist-info/METADATA"):
                text = data.decode("utf-8")
                data = "".join(
                    line for line in text.splitlines(keepends=True) if not line.startswith("Requires-Dist:")
                ).encode("utf-8")
            if info.filename.endswith(".dist-info/RECORD"):
                record_name = info.filename
                continue
            dst.writestr(info, data)
            records.append((info.filename, _record_hash(data), len(data)))
        if not record_name:
            raise ValueError(f"{source} does not contain a wheel RECORD")
        record_lines = [f"{name},sha256={digest},{size}" for name, digest, size in records]
        record_lines.append(f"{record_name},,")
        dst.writestr(record_name, "\n".join(record_lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    repack(args.source, args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
