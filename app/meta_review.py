"""Proposal-only JARVIS meta review.

This layer reads outcomes and proposes corrections. It never writes trust or
policy state, preserving the Stable Spine rule that authority changes require a
pre-approved mechanism or explicit owner action.
"""
from __future__ import annotations

import json
from typing import Any

from .spine import SpineStore


class MetaReviewer:
    def __init__(self, store: SpineStore | None = None):
        self.store = store or SpineStore()

    def review(self, limit: int = 200) -> dict[str, Any]:
        with self.store.connect() as db:
            rows = db.execute(
                "select action_type,execution_status,verification_json,created_at from audit_trail order by created_at desc limit ?",
                (max(1, min(limit, 1000)),),
            ).fetchall()

        by_action: dict[str, dict[str, int]] = {}
        for row in rows:
            stats = by_action.setdefault(row["action_type"], {"total": 0, "failures": 0, "pending": 0, "verified": 0})
            stats["total"] += 1
            status = str(row["execution_status"])
            if status in {"FAILED", "BLOCKED", "REJECTED"}:
                stats["failures"] += 1
            if status in {"PENDING_APPROVAL", "AUTHORIZED"}:
                stats["pending"] += 1
            try:
                verification = json.loads(row["verification_json"])
            except Exception:
                verification = {}
            if verification.get("execution") == "VERIFIED":
                stats["verified"] += 1

        proposals: list[dict[str, Any]] = []
        for action, stats in sorted(by_action.items()):
            if stats["failures"] >= 2:
                proposals.append({
                    "type": "TRUST_DEMOTION_PROPOSAL",
                    "action_type": action,
                    "reason": f"{stats['failures']} recent failed/blocked/rejected outcomes",
                    "suggested_change": "tighten_or_quarantine",
                    "auto_apply": False,
                })
            elif stats["total"] >= 20 and stats["failures"] == 0 and stats["verified"] >= 20:
                proposals.append({
                    "type": "GRADUATION_REVIEW_PROPOSAL",
                    "action_type": action,
                    "reason": f"{stats['verified']} verified outcomes without recorded failure",
                    "suggested_change": "review_for_bounded_graduation",
                    "auto_apply": False,
                })

        return {"audited_actions": by_action, "proposals": proposals, "applied_changes": 0}
