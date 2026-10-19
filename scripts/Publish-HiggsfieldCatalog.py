"""Publish sanitized Windows-CLI discovery for the read-only backend mount."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.higgsfield_media import HiggsfieldCliDiscovery


DEFAULT_CLI = Path.home() / "AppData" / "Roaming" / "npm" / "node_modules" / "@higgsfield" / "cli" / "vendor" / "hf.exe"
DEFAULT_OUTPUT = Path(r"C:\ProgramData\ORQEVIA\inputs\higgsfield-catalog.json")


def atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".pending")
    try:
        with temporary.open("wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", type=Path, default=DEFAULT_CLI)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--digest", type=Path)
    args = parser.parse_args()
    digest_path = args.digest or args.output.with_name(args.output.name + ".sha256")

    discovery = HiggsfieldCliDiscovery(str(args.cli))
    cli_version = discovery.version()
    catalog = discovery.snapshot()
    envelope = {
        "schema_version": "orqevia.higgsfield-catalog.v1",
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "cli_version": cli_version,
        "catalog": catalog,
    }
    raw = (json.dumps(envelope, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if b'"email"' in raw.lower():
        raise SystemExit("refusing to publish snapshot containing an email field")

    digest = hashlib.sha256(raw).hexdigest()
    atomic_write(args.output, raw)
    atomic_write(digest_path, (digest + "\n").encode("ascii"))
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "digest_file": str(digest_path.resolve()),
                "sha256": digest,
                "cli_version": cli_version,
                "model_count": catalog["model_count"],
                "workflow_count": catalog["workflow_count"],
                "execution_authority": "NONE_DISCOVERY_ONLY",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
