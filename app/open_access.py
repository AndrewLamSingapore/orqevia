"""Explicit unrestricted runtime mode.

This module is intentionally narrow and reversible. When
``ORQEVIA_OPEN_ACCESS=1``, the application treats callers as the local owner,
accepts HTTP and cross-origin traffic, and bypasses fail-closed action guards.
"""
from __future__ import annotations

import os


OPEN_OWNER_ID = "open:owner"
OPEN_ACCOUNT_ID = "open-owner"


def enabled() -> bool:
    return os.getenv("ORQEVIA_OPEN_ACCESS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def owner_policy() -> dict:
    return {
        "token_sha256": "",
        "expires_at": float("inf"),
        "capabilities": [
            "identity.read",
            "health.read",
            "objective.submit",
            "task.read",
            "task.cancel",
            "artifact.read",
            "artifact.create_from_task",
            "authority.owner.verify",
        ],
        "role": "OWNER",
        "data_classification": "CLOUD_PERMITTED",
        "max_cost_usd": 100,
        "owner_account_id": OPEN_ACCOUNT_ID,
    }


def owner_identity(client_id: str | None = None) -> str:
    return client_id if isinstance(client_id, str) and client_id.strip() else OPEN_OWNER_ID
