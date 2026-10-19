"""Verify the Higgsfield REST key with a non-billable estimate request."""
from __future__ import annotations

import argparse
import asyncio
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import secret_refs
from app.higgsfield_media import HiggsfieldApiProvider, HiggsfieldMediaSettings
from app.media_generation import MediaJobRequest, MediaProviderError


DEFAULT_SECRET = Path(r"C:\Users\Admin\Documents\ABEX\secrets\higgsfield_api_key.txt")
DEFAULT_OUTPUT = Path(r"C:\ProgramData\ORQEVIA\inputs\higgsfield-provider-validation.json")
DOCUMENTED_ESTIMATE_MODEL = "higgsfield-ai/soul/v2/standard"


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
    parser.add_argument("--secret-file", type=Path, default=DEFAULT_SECRET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--digest", type=Path)
    parser.add_argument("--model-path", default=DOCUMENTED_ESTIMATE_MODEL)
    args = parser.parse_args()
    digest_path = args.digest or args.output.with_name(args.output.name + ".sha256")
    secret_refs.HIGGSFIELD_API_KEY_FILE = str(args.secret_file.resolve())

    settings = HiggsfieldMediaSettings(
        enabled=False,
        api_key_ref="file:HIGGSFIELD_API_KEY",
    )
    provider = HiggsfieldApiProvider(settings)
    credential_ready = provider.health()["readiness"] == "READY"
    credential_fingerprint = provider.credential_fingerprint()
    result = "FAILED"
    error_code = None
    estimate = None
    if credential_ready:
        try:
            request = MediaJobRequest.create(
                task_id="higgsfield-credential-validation",
                operation="image",
                model_path=args.model_path,
                payload={"prompt": "Neutral studio product photograph"},
                data_classification="CLOUD_PERMITTED",
                max_cost_usd="1.00",
                charge_authorized=False,
            )
            estimate = asyncio.run(provider.estimate(request))
            result = "PASSED"
        except MediaProviderError as error:
            error_code = error.code
    else:
        error_code = "CREDENTIAL_UNAVAILABLE"

    receipt = {
        "schema_version": "orqevia.higgsfield-provider-validation.v1",
        "result": result,
        "validated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "credential_format_verified": credential_ready,
        "credential_fingerprint_sha256": credential_fingerprint,
        "provider_authentication_verified": result == "PASSED",
        "estimate_verified": result == "PASSED",
        "quota_entitlement_verified": False,
        "generation_execution_verified": False,
        "billable_generation_submitted": False,
        "network_probe_performed": credential_ready,
        "model_path": args.model_path,
        "estimated_usd": str(estimate.usd) if estimate is not None else None,
        "estimated_credits": str(estimate.credits) if estimate is not None and estimate.credits is not None else None,
        "error_code": error_code,
    }
    raw = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    atomic_write(args.output, raw)
    atomic_write(digest_path, (digest + "\n").encode("ascii"))
    print(json.dumps({
        "result": result,
        "credential_format_verified": credential_ready,
        "provider_authentication_verified": result == "PASSED",
        "estimate_verified": result == "PASSED",
        "billable_generation_submitted": False,
        "estimated_usd": receipt["estimated_usd"],
        "estimated_credits": receipt["estimated_credits"],
        "error_code": error_code,
        "receipt": str(args.output.resolve()),
        "sha256": digest,
    }))
    return 0 if result == "PASSED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
