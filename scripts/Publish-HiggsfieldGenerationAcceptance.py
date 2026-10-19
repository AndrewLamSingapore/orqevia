"""Publish a sanitized live-generation acceptance receipt for the backend."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import secret_refs
from app.higgsfield_media import (
    HiggsfieldApiProvider,
    HiggsfieldMediaSettings,
    higgsfield_generation_contract_sha256,
)


ACCEPTANCE_DIR = Path(r"C:\ProgramData\ORQEVIA\acceptance")
DEFAULT_OUTPUT = Path(r"C:\ProgramData\ORQEVIA\inputs\higgsfield-generation-acceptance.json")
DEFAULT_SECRET = Path(r"C:\Users\Admin\Documents\ABEX\secrets\higgsfield_api_key.txt")
REQUEST_ID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\Z"
)


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


def latest_receipt() -> Path:
    candidates = sorted(
        ACCEPTANCE_DIR.glob("higgsfield-acceptance-*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise SystemExit("no Higgsfield acceptance receipt found")
    return candidates[0]


def read_digest(path: Path) -> str:
    try:
        value = path.read_text(encoding="ascii").strip().lower()
    except (OSError, UnicodeError):
        raise SystemExit("acceptance receipt digest is unavailable") from None
    if re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise SystemExit("acceptance receipt digest is malformed")
    return value


def publish(acceptance_receipt: Path, *, output: Path, secret_file: Path) -> dict:
    digest_file = acceptance_receipt.with_name(acceptance_receipt.name + ".sha256")
    try:
        raw = acceptance_receipt.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeError, ValueError):
        raise SystemExit("acceptance receipt is unavailable or invalid") from None
    if not 1 <= len(raw) <= 128 * 1024:
        raise SystemExit("acceptance receipt size is invalid")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != read_digest(digest_file):
        raise SystemExit("acceptance receipt digest mismatch")
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "orqevia.higgsfield-generation-acceptance.v1"
        or value.get("terminal_status") != "completed"
        or value.get("error_code") is not None
        or REQUEST_ID.fullmatch(str(value.get("request_id", ""))) is None
        or not isinstance(value.get("task_id"), str)
        or not value["task_id"]
        or not isinstance(value.get("model"), str)
        or not value["model"]
        or not isinstance(value.get("idempotency_key"), str)
        or re.fullmatch(r"[\x21-\x7e]{1,255}", value["idempotency_key"]) is None
        or not isinstance(value.get("observed_at_utc"), str)
        or type(value.get("polls")) is not int
        or value["polls"] < 0
        or value.get("result_urls_exported") is not False
        or not isinstance(value.get("outputs"), list)
        or not 1 <= len(value["outputs"]) <= 100
    ):
        raise SystemExit("acceptance receipt contract is invalid")
    try:
        estimated_usd = float(value.get("estimated_usd"))
        maximum_cost_usd = float(value.get("maximum_cost_usd"))
    except (TypeError, ValueError):
        raise SystemExit("acceptance receipt cost fields are invalid") from None
    if not 0 <= estimated_usd <= maximum_cost_usd <= 0.25 or not maximum_cost_usd > 0:
        raise SystemExit("acceptance receipt cost bound is invalid")
    outputs = []
    for output_record in value["outputs"]:
        if not isinstance(output_record, dict):
            raise SystemExit("acceptance output record is invalid")
        artifact = Path(str(output_record.get("path", "")))
        try:
            info = artifact.lstat()
            resolved_artifact = artifact.resolve(strict=True)
            artifact_raw = artifact.read_bytes()
        except OSError:
            raise SystemExit("acceptance artifact is unavailable") from None
        expected_bytes = output_record.get("bytes")
        expected_sha256 = str(output_record.get("sha256", "")).lower()
        if (
            not artifact.is_absolute()
            or ACCEPTANCE_DIR.resolve() not in resolved_artifact.parents
            or not stat.S_ISREG(info.st_mode)
            or type(expected_bytes) is not int
            or not 1 <= expected_bytes <= 100 * 1024 * 1024
            or len(artifact_raw) != expected_bytes
            or re.fullmatch(r"[a-f0-9]{64}", expected_sha256) is None
            or hashlib.sha256(artifact_raw).hexdigest() != expected_sha256
            or not isinstance(output_record.get("host"), str)
            or not output_record["host"]
            or re.fullmatch(r"[A-Za-z0-9.-]{1,255}", output_record["host"]) is None
        ):
            raise SystemExit("acceptance artifact integrity check failed")
        outputs.append(
            {
                "bytes": expected_bytes,
                "sha256": expected_sha256,
                "host": output_record["host"][:255],
            }
        )

    secret_refs.HIGGSFIELD_API_KEY_FILE = str(secret_file.resolve())
    provider = HiggsfieldApiProvider(HiggsfieldMediaSettings(enabled=False, api_key_ref="file:HIGGSFIELD_API_KEY"))
    fingerprint = provider.credential_fingerprint()
    if fingerprint is None:
        raise SystemExit("credential fingerprint is unavailable")

    published = {
        "schema_version": "orqevia.higgsfield-generation-acceptance.v1",
        "provider": "higgsfield",
        "observed_at_utc": value["observed_at_utc"],
        "published_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "request_id": value["request_id"],
        "task_id": value["task_id"],
        "model": value["model"],
        "idempotency_key": value["idempotency_key"],
        "terminal_status": "completed",
        "polls": value["polls"],
        "error_code": None,
        "estimated_usd": str(value["estimated_usd"]),
        "maximum_cost_usd": str(value["maximum_cost_usd"]),
        "outputs": outputs,
        "result_urls_exported": False,
        "credential_fingerprint_sha256": fingerprint,
        "provider_contract_sha256": higgsfield_generation_contract_sha256(),
        "entitlement_scope": "SELECTED_MODEL_EXECUTION",
        "source_receipt_sha256": digest,
    }
    published_raw = (json.dumps(published, indent=2, sort_keys=True) + "\n").encode("utf-8")
    published_digest = hashlib.sha256(published_raw).hexdigest()
    digest_path = output.with_name(output.name + ".sha256")
    atomic_write(output, published_raw)
    atomic_write(digest_path, (published_digest + "\n").encode("ascii"))
    return {
        "result": "PUBLISHED",
        "request_id": published["request_id"],
        "terminal_status": published["terminal_status"],
        "output_count": len(outputs),
        "receipt": str(output),
        "sha256": published_digest,
        "source_receipt": str(acceptance_receipt),
        "source_receipt_sha256": digest,
        "credential_fingerprint_present": True,
        "provider_contract_sha256": published["provider_contract_sha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acceptance-receipt", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--secret-file", type=Path, default=DEFAULT_SECRET)
    args = parser.parse_args()
    receipt = args.acceptance_receipt.resolve() if args.acceptance_receipt else latest_receipt().resolve()
    result = publish(receipt, output=args.output.resolve(), secret_file=args.secret_file.resolve())
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
